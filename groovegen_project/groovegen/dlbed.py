"""dlbed — adapter that turns a DL-generated MIDI bed into a frozen GrooveGen BedProfile.

The deep-learning model (Anticipatory Music Transformer, notebook 05) produces a short multi-track
MIDI bed conditioned toward a target genre. This module quantizes that MIDI onto GrooveGen's 16-step,
N-bar grid and emits a `BedProfile` so the EXISTING, already-verified bed/drum/render path
(`PatternBuilder.build_bed_instruments` -> `build_looped` -> `render_wav`) can be reused unchanged.

Because we route through `build_bed_instruments` (sections=None), the resulting bed is automatically
time-invariant and knob-invariant — the same guarantees verified for `hero_study` carry over for free.
The DL step is therefore a DESIGN-TIME tool: generate offline, audit, freeze, then sweep knobs.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pretty_midi

from . import groovegen as gg


# General MIDI program groups we treat as "bass" vs "harmony/melody"
_BASS_PROGRAMS = set(range(32, 40))          # GM bass family
_PERC_OR_FX = set(range(112, 128))           # percussive/sound-fx — ignore


def _quantize_step(t: float, bar_seconds: float, steps_per_bar: int = 16) -> int:
    """Map an absolute time to a 0..steps_per_bar-1 step within its bar."""
    bar_t = t % bar_seconds
    return int(round(bar_t / bar_seconds * steps_per_bar)) % steps_per_bar


def midi_bed_to_profile(midi_path: str, genre: str, tempo: int,
                        n_bars: int = 2, name: str | None = None) -> gg.BedProfile:
    """Convert a DL-generated MIDI bed into a frozen GrooveGen BedProfile.

    For each of `n_bars` bars we extract:
      - bass root  = the most common bass-register pitch in that bar (or lowest note),
      - chord tones = the set of sustained harmony pitches sounding at the bar downbeat,
      - melody motif = up to ~4 (step, pitch) events from the highest-register line,
                       quantized to the 16-step grid.
    The result routes through build_bed_instruments() exactly like the hand-authored beds.
    """
    pm = pretty_midi.PrettyMIDI(midi_path)
    spb = 60.0 / tempo
    bar_seconds = spb * 4.0  # 4/4

    # Collect notes by role, dropping drums and fx
    bass_notes, harm_notes = [], []
    for inst in pm.instruments:
        if inst.is_drum or inst.program in _PERC_OR_FX:
            continue
        target = bass_notes if (inst.program in _BASS_PROGRAMS) else harm_notes
        target.extend(inst.notes)
    # Fallback: if the model didn't emit a bass-program track, treat the lowest
    # 20% of pitches as bass.
    if not bass_notes and harm_notes:
        pitches = sorted(n.pitch for n in harm_notes)
        cutoff = pitches[max(0, int(0.2 * len(pitches)) - 1)]
        bass_notes = [n for n in harm_notes if n.pitch <= cutoff]
        harm_notes = [n for n in harm_notes if n.pitch > cutoff]

    chords = []
    for bar in range(n_bars):
        t_lo, t_hi = bar * bar_seconds, (bar + 1) * bar_seconds
        # --- bass root: most common bass pitch active in this bar
        bar_bass = [n.pitch for n in bass_notes if t_lo <= (n.start % (n_bars * bar_seconds)) < t_hi]
        if bar_bass:
            root = int(np.bincount(np.array(bar_bass) % 128).argmax())
        else:
            root = 45  # A2 default anchor
        # --- chord tones: harmony pitches sounding near the downbeat, deduped to a triad/7th
        downbeat = t_lo + 0.01
        sounding = sorted({n.pitch for n in harm_notes
                           if n.start <= (downbeat % (n_bars * bar_seconds)) + bar * bar_seconds < n.end}
                          ) if harm_notes else []
        if not sounding:  # fall back to harmony onsets in the bar
            sounding = sorted({n.pitch for n in harm_notes
                               if t_lo <= (n.start % (n_bars * bar_seconds)) < t_hi})
        # keep up to 4 chord tones in a sensible register (48..79)
        tones = [p for p in sounding if 48 <= p <= 79][:4] or [root + 12, root + 16, root + 19]
        # --- melody motif: highest line, up to 4 quantized events
        bar_mel = [n for n in harm_notes
                   if t_lo <= (n.start % (n_bars * bar_seconds)) < t_hi and n.pitch >= 64]
        bar_mel.sort(key=lambda n: n.start)
        motif, seen_steps = [], set()
        for n in bar_mel:
            s = _quantize_step(n.start, bar_seconds)
            if s not in seen_steps:
                motif.append((s, int(n.pitch)))
                seen_steps.add(s)
            if len(motif) >= 4:
                break
        if not motif:  # guarantee a non-empty, sparse motif
            motif = [(0, tones[-1] + 12 if tones else root + 24)]
        chords.append((root, [int(p) for p in tones], motif))

    return gg.BedProfile(
        name=name or f"dlgen_{genre.replace('/', '_')}",
        desc=f"DL-generated frozen bed (genre={genre}); AMT->quantized to grid; time/knob-invariant",
        chords=tuple(chords),
        bass_program=gg.GM_FINGERED_BASS,
        chord_program=gg.GM_SYNTH_PAD,
        melody_program=gg.GM_GRAND_PIANO,
        bass_steps=(0, 3, 4, 6, 8, 11, 12, 14),
        bass_vel=62, chord_vel=44, melody_vel=74,
        sections=None,  # FROZEN plain loop -> time- & knob-invariant
    )


def _densify_motif(motif: list, root: int, tones: list) -> list:
    """Build a denser, higher 'chorus lift' motif from a sparse verse motif.

    Mirrors how BED_HERO's chorus is denser + higher than its verse. We take the
    verse events, raise them an octave (capped), and interpolate extra stepwise
    chord-tone events between them so the bar feels fuller (~5-6 notes vs 2-3).
    """
    pool = sorted({(p % 12) + 60 for p in (tones or [root + 12])})  # chord tones up high
    base = sorted(motif, key=lambda e: e[0]) if motif else [(0, (tones or [root + 12])[-1])]
    out, steps_used = [], set()
    for i, (s, p) in enumerate(base):
        hp = p + 12 if p + 12 <= 84 else p          # octave-up lift, capped at C6
        if s not in steps_used:
            out.append((s, int(hp))); steps_used.add(s)
        # insert a passing chord-tone partway to the next event
        nxt = base[i + 1][0] if i + 1 < len(base) else s + 6
        mid_step = (s + nxt) // 2
        if mid_step != s and mid_step not in steps_used and 0 <= mid_step < 16:
            pt = pool[(i + 1) % len(pool)]
            out.append((mid_step, int(pt))); steps_used.add(mid_step)
    # one extra high accent near the end of the bar for a 'lift' feel
    if 14 not in steps_used:
        out.append((14, int(min(84, (pool[-1] if pool else root + 24) + 0))))
    return sorted(out, key=lambda e: e[0])[:6]


def build_genre_song(midi_path: str, genre: str, tempo: int,
                     n_bars: int = 2, name: str | None = None) -> gg.BedProfile:
    """Turn a DL-generated MIDI bed into a FULL SONG-FORM BedProfile.

    Unlike `midi_bed_to_profile` (which freezes a plain knob-invariant loop for
    the experiment), this arranges the AMT material into the same song arc as
    the hero/champion song: Intro (bed only) -> Verse (sparse melody) ->
    Chorus -> Chorus (denser, higher 'lift'). Routes through build_bed_song().

    The per-bar harmony/bass come straight from the AMT bed; the VERSE motif is
    the extracted melody, and the CHORUS motif is a densified/raised variant.
    """
    # Reuse the frozen-profile extractor to get per-bar (root, tones, motif).
    frozen = midi_bed_to_profile(midi_path, genre, tempo, n_bars=n_bars, name="_tmp")
    chords = list(frozen.chords)  # tuple of (root, tones, verse_motif) per bar

    verse_motifs = tuple(list(c[2]) for c in chords)
    chorus_motifs = tuple(_densify_motif(c[2], c[0], c[1]) for c in chords)

    # Carry the genre's INSTRUMENTATION through to the rendered song. Without
    # this every genre collapses to pad+bass+piano and they sound alike. We pull
    # the chord/bass timbres from the style-engine spec (Rhodes for r&b, OD
    # guitar for rock, grand piano montuno for salsa, ...).
    chord_prog, bass_prog, mel_prog = gg.GM_SYNTH_PAD, gg.GM_FINGERED_BASS, gg.GM_GRAND_PIANO
    comp_plan = None
    try:
        from . import genre_styles as _gs
        if genre in _gs.GENRE_STYLES:
            _spec = _gs.GENRE_STYLES[genre]
            chord_prog, bass_prog = _spec.chord_program, _spec.bass_program
            # melody/lead timbre per genre family
            _MEL = {"r&b/soul": _gs.GM_ELECTRIC_PIANO, "hip-hop/rap": _gs.GM_ELECTRIC_PIANO,
                    "classic-rock": _gs.GM_OVERDRIVE_GUITAR, "latin/salsa": gg.GM_GRAND_PIANO,
                    "metal": _gs.GM_OVERDRIVE_GUITAR,
                    "pop": _gs.GM_GRAND_PIANO}  # bright piano melody over the clavinet pop comp
            mel_prog = _MEL.get(genre, gg.GM_GRAND_PIANO)
            # Carry the genre's COMP PHRASING through to the song renderer so the
            # chords don't collapse to one robotic block per bar. pop/rock use
            # the natural sustain-accent comp; the others get a lightly
            # humanized block comp on their own comp_steps.
            comp_plan = dict(
                steps=list(_spec.comp_steps),
                comp_style=_spec.comp_style,
                base_vel=_spec.base_vel,
                strum_ms=_spec.strum_ms if _spec.humanize else 0.0,
                humanize=True,
                seed=7,
            )
    except Exception:
        pass

    return gg.BedProfile(
        name=name or f"song_{genre.replace('/', '_')}",
        desc=f"DL-generated FULL SONG (genre={genre}); AMT->grid; Intro->Verse->Chorus song form",
        chords=tuple(chords),
        bass_program=bass_prog,
        chord_program=chord_prog,
        melody_program=mel_prog,
        bass_steps=(0, 3, 4, 6, 8, 11, 12, 14),  # anthemic pushed/dotted feel
        bass_vel=62, chord_vel=44, melody_vel=74,
        comp_plan=comp_plan,
        # Same build-up arc as BED_HERO: intro suppresses melody, chorus lifts.
        sections=(
            ("intro",  0.0),
            ("verse",  1.0),
            ("chorus", 1.08),
            ("chorus", 1.08),
        ),
        section_motifs=(
            ("intro",  tuple(() for _ in range(n_bars))),  # no melody
            ("verse",  verse_motifs),
            ("chorus", chorus_motifs),
        ),
    )


def register_genre_song(midi_path: str, genre: str, tempo: int,
                        n_bars: int = 2, name: str | None = None) -> str:
    """Build a full song-form BedProfile and register it. Returns the name."""
    prof = build_genre_song(midi_path, genre, tempo, n_bars=n_bars, name=name)
    gg.BED_PROFILES[prof.name] = prof
    return prof.name


def register_dl_bed(midi_path: str, genre: str, tempo: int,
                    n_bars: int = 2, name: str | None = None) -> str:
    """Build a BedProfile from a DL MIDI bed and register it in gg.BED_PROFILES.

    Returns the profile name (use it as GrooveParams.bed_profile).
    """
    prof = midi_bed_to_profile(midi_path, genre, tempo, n_bars=n_bars, name=name)
    gg.BED_PROFILES[prof.name] = prof
    return prof.name


# Verified knob level arrays (identical to build_stimulus_grid.py — already manipulation-checked).
# Tier-1 default is event_density (strongest, simplest groove driver): 4/8/14/24 -> ~5/9/15/25 onsets/bar.
SWEEP_LEVELS = {
    "density":      [4, 8, 14, 24],            # -> GrooveParams.event_density (int target onsets/bar)
    "syncopation":  [0.0, 0.25, 0.5, 1.0],     # -> GrooveParams.syncopation_level (0..1) -> S=0/16/32/49
    "swing":        [1.0, 1.25, 1.6, 2.0],     # -> GrooveParams.swing_amount ratio -> 50/56/62/67%
    "tempo":        [70.0, 95.0, 115.0, 150.0],  # -> GrooveParams.tempo_bpm
}
# Maps the friendly sweep name to the actual GrooveParams field it drives.
_SWEEP_PARAM = {"density": "event_density", "syncopation": "syncopation_level",
                "swing": "swing_amount", "tempo": "tempo_bpm"}
DENSITY_LEVELS = tuple(SWEEP_LEVELS["density"])  # back-compat alias


def render_genre_demo(midi_path: str, genre: str, tempo: int, out_dir: str,
                      sweep: str = "density", target_seconds: float = 12.0,
                      sf2_path: str | None = None) -> list[dict]:
    """Overlay knob-controlled drums on a frozen DL genre bed and render the sweep.

    Renders one WAV per level of the chosen Tier-1 knob (default: event density) on top of the same
    frozen bed. Returns a list of metadata dicts (one per level). The bed is generated once, frozen
    (sections=None), and reused across every level so the only thing that changes is the swept knob.
    """
    if sweep not in SWEEP_LEVELS:
        raise ValueError(f"sweep must be one of {sorted(SWEEP_LEVELS)}, got {sweep!r}")
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    prof_name = register_dl_bed(midi_path, genre, tempo)
    field = _SWEEP_PARAM[sweep]
    levels = SWEEP_LEVELS[sweep]
    results = []
    for i, lvl in enumerate(levels):
        kwargs = dict(tempo_bpm=float(tempo), bed_profile=prof_name,
                      with_bed=True, target_seconds=target_seconds)
        # The tempo sweep overrides tempo_bpm itself; all others set their own field.
        kwargs[field] = lvl
        params = gg.GrooveParams(**kwargs)
        pb = gg.PatternBuilder(params)
        pm = pb.build_looped()
        stem = out / f"{genre.replace('/', '_')}_{sweep}_L{i}"
        meta = gg.render_wav(pm, str(stem) + ".wav", sf2_path=sf2_path)
        meta.update(genre=genre, sweep=sweep, param=field, level_index=i, level=lvl,
                    onsets_per_bar=pb.onset_count_per_bar(),
                    syncopation_index=round(pb.syncopation_index(), 1),
                    wav=str(stem) + ".wav")
        results.append(meta)
        print(f"  L{i} {field}={lvl} -> {meta['onsets_per_bar']} onsets/bar, "
              f"S={meta['syncopation_index']}, {Path(meta['wav']).name}")
    (out / f"{genre.replace('/', '_')}_{sweep}_manifest.json").write_text(
        json.dumps(results, indent=2, default=str))
    return results
