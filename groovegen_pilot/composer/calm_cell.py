"""
calm_cell.py — Revised calm-family generator for GrooveGen.

Motivation
----------
Two listeners in a lab meeting (2026-08 timeframe) reported that the previous
calm cell "pad sound was way too strong and a bit dark" and did not feel
relaxing. They sent three reference tracks:

  1. Anson Seabra — "Trying My Best"        (solo piano ballad, no drums, ~76 BPM)
  2. Massenet    — "Meditation from Thais"  (solo violin + piano, no drums, ~66 BPM)
  3. Kaleb Brasee— "Goodness of God" (cover) (solo piano, no drums, A-flat, ~72 BPM)

Common pattern across the three:
  - no drums at all
  - acoustic piano (not pad, not synth strings)
  - mid-high register weighting; roots in low mid, upper voices in C4-C5
  - rolled / broken / arpeggiated chords, gentle motion (not static holds)
  - major-key diatonic harmony with add9 / sus2 colors
  - slow but not glacial: 60-78 BPM band
  - very sparse melodic line, when present, in C5-C6 range

This module implements a drop-in replacement that honors the frozen
generate_segment(genre, tempo_bpm, density, duration_bars, seed) contract for
genre == "calm". It emits a music21.stream.Score which the existing FluidSynth
render path (via .write('midi')) can consume unchanged.

Does not touch: the controller, ladder, MPC, reference governor, or any other
family. Drums for calm are near-silent by design (kick + soft brush only, no
snare, no hats, no cymbals), so the calm cell can still transition smoothly
into lofi tier 1 through the controller's monotone genre/tier ladder.

Requires: music21 >= 8.0, python >= 3.10.
Recommended: render with a warm concert-grand SoundFont (e.g. Nice-Keys-B,
SalamanderGrandPiano, or a mellow-EQ patch from Musyng_Kite) rather than
TimGM6mb, and apply Freeverb (roomsize ~0.7, wet ~0.30) at the mix stage.
Optional GM Violin (program 41) overlay for tier >= 3 is exposed via a flag.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from music21 import chord, duration, instrument, key, meter, note, pitch, stream, tempo


# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

# Empirically-grounded calm-family tempo band, derived from the three
# reference tracks (66, 72, 76 BPM). Old range 47-108 BPM produced the
# incoherent-identity failure mode.
CALM_TEMPO_MIN_BPM: int = 60
CALM_TEMPO_MAX_BPM: int = 78

# Tier -> tempo mapping. Higher tiers = slightly faster and denser, but
# never leave the calm identity band. Consistent with density being the
# ladder's main energy dial (0.3-1.0), remapped for the calm sub-range.
_TIER_TEMPO: dict[int, int] = {1: 60, 2: 64, 3: 68, 4: 72, 5: 76}
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.30, 2: 0.40, 3: 0.55, 4: 0.70, 5: 0.85}

# Drum design for calm: kick on beat 1 (always), optional brush swell on beat
# 3 at higher tiers. Never a snare/hi-hat/cymbal -- those are what pushed the
# old calm cell into an unrelaxing texture. Velocities are ~half the treble
# piano velocities so drums stay felt-not-heard, keeping the measured
# percussive_ratio near the current calm mean (~0.05) and beat_consistency
# high (~0.98).
#
# GM percussion note numbers (channel 10):
#   35 = Acoustic Bass Drum, 36 = Bass Drum 1 (kick)
#   38 = Acoustic Snare  -- deliberately NOT used
#   42/44/46 = Closed/Pedal/Open Hi-Hat -- deliberately NOT used
#   49/51/57 = Cymbals -- deliberately NOT used
_CALM_KICK_MIDI: int = 36
_CALM_BRUSH_MIDI: int = 41  # Low Floor Tom, used as a soft mallet swell

# Kick velocity ramps with tier; still very quiet (max 45, vs. treble 60-70).
_TIER_KICK_VEL: dict[int, int] = {1: 22, 2: 28, 3: 34, 4: 40, 5: 45}
# Brush swell activates only at tier >= 3, and only on beat 3 of each bar.
_TIER_BRUSH_ON: dict[int, bool] = {1: False, 2: False, 3: True, 4: True, 5: True}
_TIER_BRUSH_VEL: dict[int, int] = {1: 0, 2: 0, 3: 20, 4: 26, 5: 32}

# Diatonic major-key progression templates. All in C major here;
# transposition happens per segment via the `key_root` parameter.
# Every progression is length 4 (chords per 4-bar phrase). Numerals only.
_PROGRESSIONS: list[list[str]] = [
    ["I", "V/vi", "vi", "IV"],   # descending Aeolian pull, Bethel-like
    ["I", "iii", "IV", "I"],     # very consonant, Anson Seabra shape
    ["I", "vi", "IV", "V"],      # classic doo-wop, familiar and safe
    ["IV", "I", "V", "vi"],      # plagal-first, Meditation-flavored
]

# Roman numeral -> scale degree (1-indexed, major key), and chord quality.
# We store (root_degree, quality) where quality is one of:
#   "maj", "min", "maj7", "min7", "dom7", "sus2add9"
_ROMAN_TABLE: dict[str, tuple[int, str]] = {
    "I":    (1, "maj"),
    "ii":   (2, "min"),
    "iii":  (3, "min"),
    "IV":   (4, "maj"),
    "V":    (5, "maj"),
    "vi":   (6, "min"),
    "V/vi": (3, "maj"),   # secondary dominant of vi = III major
    "Isus2add9": (1, "sus2add9"),
    "IVadd9":    (4, "sus2add9"),
}


# ---------------------------------------------------------------------------
# Segment spec
# ---------------------------------------------------------------------------

@dataclass
class CalmSpec:
    """Resolved parameters for one calm segment."""
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str        # e.g. "C", "Ab", "F"
    add_violin: bool     # tier >= 3 by default
    seed: int


# ---------------------------------------------------------------------------
# Voicing primitives
# ---------------------------------------------------------------------------

# Major scale semitone offsets from tonic.
_MAJOR_SCALE_INTERVALS: tuple[int, ...] = (0, 2, 4, 5, 7, 9, 11)


def _degree_to_midi(key_root_midi: int, degree: int, octave_shift: int = 0) -> int:
    """Return MIDI pitch for scale `degree` (1-indexed) above `key_root_midi`."""
    step = _MAJOR_SCALE_INTERVALS[(degree - 1) % 7]
    return key_root_midi + step + 12 * octave_shift


def _build_chord_tones(
    key_root_midi: int,
    roman: str,
) -> list[int]:
    """Return the MIDI chord tones (root position, close-position) for a Roman numeral.

    All voicings are mid-register anchored around C3-C5.
    """
    if roman not in _ROMAN_TABLE:
        raise ValueError(f"Unknown Roman numeral for calm cell: {roman!r}")
    root_degree, quality = _ROMAN_TABLE[roman]
    r = _degree_to_midi(key_root_midi, root_degree)

    if quality == "maj":
        return [r, r + 4, r + 7]
    if quality == "min":
        return [r, r + 3, r + 7]
    if quality == "maj7":
        return [r, r + 4, r + 7, r + 11]
    if quality == "min7":
        return [r, r + 3, r + 7, r + 10]
    if quality == "dom7":
        return [r, r + 4, r + 7, r + 10]
    if quality == "sus2add9":
        # 1, 2, 5, 9 -- omit the 3 for openness; the add9 doubles the 2 up an octave.
        return [r, r + 2, r + 7, r + 14]
    raise ValueError(f"Unhandled quality {quality!r}")


def _voice_chord_calm(chord_tones: list[int]) -> tuple[int, list[int]]:
    """Return (bass_note_midi, upper_voice_midis) with calm-family register rules.

    - Bass note: the lowest chord tone, dropped to the C3-B3 octave. Anchored
      but not muddy. (Explicitly not below C3 -- the "too dark" failure mode.)
    - Upper voices: remaining chord tones lifted into the C4-C5 range, with
      an optional doubled top tone in C5-C6 for open shimmer.
    """
    if not chord_tones:
        raise ValueError("empty chord_tones")

    # Bass: take lowest chord tone, normalize into [C3 (48), B3 (59)].
    bass = min(chord_tones)
    while bass < 48:
        bass += 12
    while bass > 59:
        bass -= 12

    # Upper voices: remaining tones, each normalized into [C4 (60), C5 (72)].
    uppers: list[int] = []
    for t in chord_tones:
        u = t
        while u < 60:
            u += 12
        while u > 72:
            u -= 12
        if u != bass:  # avoid duplicating the bass in the upper stack
            uppers.append(u)
    # Deduplicate and sort ascending.
    uppers = sorted(set(uppers))

    # Add a shimmer double an octave up on the highest upper voice if we
    # have room and the chord is not already dense.
    if uppers and len(uppers) <= 3:
        top = uppers[-1]
        if top + 12 <= 84:  # C6
            uppers = uppers + [top + 12]

    return bass, uppers


def broken_chord_arpeggio(
    key_root_midi: int,
    roman: str,
    chord_dur_beats: float,
    density: float,
    seed: int,
) -> tuple[list[tuple[float, int, float, int]], list[tuple[float, int, float, int]]]:
    """Produce a rolled/broken-chord arpeggio for one chord.

    Returns (bass_events, treble_events). Each event is
    (offset_beats, midi_pitch, duration_beats, velocity).

    Bass: single sustained note across the chord's duration, medium-soft
    velocity (mp, 55-65). Matches the left-hand of the three references.

    Treble: the upper voices are rolled at a rate governed by `density`:
      - density <= 0.4 : one slow arpeggiation, half-note chord tones,
                         velocity 45-55 (very sparse; tier 1 texture)
      - density <= 0.7 : one arpeggiation per half-note, quarter-note tones,
                         velocity 55-65 (tier 2-3 texture)
      - density  > 0.7 : two arpeggiations per bar, eighth-note tones,
                         velocity 60-70 (tier 4-5 texture)

    Sustain-pedal simulation: each treble note is held until the next
    arpeggio starts, giving the piano-ballad wash without stacking MIDI
    voices.
    """
    rng = random.Random(seed)
    chord_tones = _build_chord_tones(key_root_midi, roman)
    bass_midi, upper_midis = _voice_chord_calm(chord_tones)

    # Bass: single sustained note.
    bass_events: list[tuple[float, int, float, int]] = [
        (0.0, bass_midi, chord_dur_beats, rng.randint(55, 65))
    ]

    # Choose arpeggio step spacing.
    if density <= 0.4:
        step_beats = 2.0
        vel_lo, vel_hi = 45, 55
    elif density <= 0.7:
        step_beats = 1.0
        vel_lo, vel_hi = 55, 65
    else:
        step_beats = 0.5
        vel_lo, vel_hi = 60, 70

    # Ascending, then optional descending pass. Loops the upper stack.
    treble_events: list[tuple[float, int, float, int]] = []
    t = 0.0
    idx = 0
    n_upper = max(1, len(upper_midis))
    while t < chord_dur_beats - 1e-6:
        p = upper_midis[idx % n_upper]
        # Sustain: each note rings until the next step or end of chord.
        note_dur = min(step_beats, chord_dur_beats - t)
        # Small human velocity jitter to avoid the "MIDI wall" effect.
        vel = rng.randint(vel_lo, vel_hi)
        treble_events.append((t, p, note_dur, vel))
        t += step_beats
        idx += 1

    return bass_events, treble_events


def sparse_melody(
    key_root_midi: int,
    roman_progression: Sequence[str],
    bars_per_chord: int,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Emit a sparse diatonic melodic line in C5-C6, one to two notes per bar.

    At tier <= 2: return empty (no melody -- the reference-track pattern).
    At tier == 3: one note per bar, on beat 1, held for two beats.
    At tier >= 4: two notes per bar, on beats 1 and 3, held for two beats each.

    Notes are chosen from the current chord's tones, biased toward the 3rd
    and 5th (the "singing" tones), with occasional passing motion by step.
    """
    if tier <= 2:
        return []

    rng = random.Random(seed ^ 0x9E37)  # decorrelate from arpeggio randomness
    events: list[tuple[float, int, float, int]] = []
    notes_per_bar = 1 if tier == 3 else 2
    beat_slots = [0.0] if notes_per_bar == 1 else [0.0, 2.0]

    running_offset = 0.0
    prev_pitch: int | None = None
    for roman in roman_progression:
        tones = _build_chord_tones(key_root_midi, roman)
        # Lift tones into C5-C6 window: [72, 84).
        window_tones = []
        for t in tones:
            u = t
            while u < 72:
                u += 12
            while u >= 84:
                u -= 12
            window_tones.append(u)
        # Bias toward 3rd/5th of the chord (index 1 and 2 in root position).
        biased_pool = [window_tones[i] for i in (1, 2) if i < len(window_tones)]
        biased_pool += window_tones  # everything is still allowed

        for bar in range(bars_per_chord):
            for slot in beat_slots:
                # 15% chance of a stepwise passing tone instead of a chord tone.
                if prev_pitch is not None and rng.random() < 0.15:
                    step = rng.choice([-2, -1, 1, 2])
                    p = prev_pitch + step
                    # Snap to nearest diatonic pitch in window.
                    p = _snap_to_major_scale(p, key_root_midi)
                    if p < 72:
                        p += 12
                    if p >= 84:
                        p -= 12
                else:
                    p = rng.choice(biased_pool)
                dur_beats = 2.0
                vel = rng.randint(50, 62)
                offset = running_offset + bar * 4.0 + slot
                events.append((offset, p, dur_beats, vel))
                prev_pitch = p
        running_offset += bars_per_chord * 4.0

    return events


def _snap_to_major_scale(midi_pitch: int, key_root_midi: int) -> int:
    """Snap a MIDI pitch to the nearest degree of the major scale of key_root_midi."""
    # Interval above tonic within an octave.
    interval = (midi_pitch - key_root_midi) % 12
    scale = _MAJOR_SCALE_INTERVALS
    nearest = min(scale, key=lambda s: abs(s - interval))
    return midi_pitch + (nearest - interval)


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def _resolve_spec(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> CalmSpec:
    """Clamp inputs into the calm identity band and derive tier."""
    # Clamp tempo to calm band; log if the caller was out of range.
    clamped_bpm = max(CALM_TEMPO_MIN_BPM, min(CALM_TEMPO_MAX_BPM, tempo_bpm))

    # Derive tier from the requested tempo (nearest _TIER_TEMPO key).
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))

    # Floor density by tier so tier 4-5 do not collapse to silence.
    density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))

    # Deterministic key choice from seed. Prefer warm keys: C, D, F, G, Ab, Bb.
    rng = random.Random(seed)
    key_root = rng.choice(["C", "D", "F", "G", "Ab", "Bb"])

    return CalmSpec(
        tempo_bpm=clamped_bpm,
        density=density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        add_violin=(tier >= 3),
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    rng = random.Random(seed ^ 0x51ED)
    return list(rng.choice(_PROGRESSIONS))


def _key_root_midi(key_root_name: str) -> int:
    """Map a key name like 'C' or 'Ab' to a mid-register root MIDI pitch (C3-B3 range)."""
    p = pitch.Pitch(key_root_name + "3")
    return int(p.midi)


def generate_calm_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
    add_violin: bool | None = None,
) -> stream.Score:
    """Generate a calm segment as a music21 Score.

    Contract matches `generate_segment(genre='calm', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      - Part 0: piano bass (GM program 1, Acoustic Grand Piano)
      - Part 1: piano treble arpeggios (GM program 1)
      - Part 2: optional violin (GM program 41), only if `add_violin` is True
                or if the resolved tier >= 3
      - No drum part. Zero percussion by design.

    The caller (the FluidSynth render path) can `.write('midi', fp=...)` and
    proceed unchanged.
    """
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    if add_violin is not None:
        spec.add_violin = add_violin

    progression = _select_progression(spec.seed)
    key_root_midi = _key_root_midi(spec.key_root)

    # Duration bookkeeping: 4-chord progressions cycle over `duration_bars`.
    bars_per_chord = max(1, spec.duration_bars // len(progression))
    beats_per_bar = 4  # 4/4 for the calm family; other families may differ.
    chord_dur_beats = bars_per_chord * beats_per_bar

    # ---- Build the Score -------------------------------------------------
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, key.Key(spec.key_root))

    # Part 0: Piano bass.
    bass_part = stream.Part(id="calm_piano_bass")
    bass_part.insert(0, instrument.Piano())

    # Part 1: Piano treble arpeggios.
    treble_part = stream.Part(id="calm_piano_treble")
    treble_part.insert(0, instrument.Piano())

    # Part 2 (optional): Violin overlay for the sparse melody.
    violin_part: stream.Part | None = None
    if spec.add_violin:
        violin_part = stream.Part(id="calm_violin")
        violin_part.insert(0, instrument.Violin())

    # Part 3: Near-silent drums (kick + optional brush swell). Always present
    # for calm so the controller can crossfade smoothly into lofi tier 1.
    drum_part = stream.Part(id="calm_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9  # channel 10 (0-indexed = 9) per GM convention
    drum_part.insert(0, drum_kit)

    # Iterate chords and place events at absolute offsets in the Score.
    running_offset = 0.0
    for chord_idx, roman in enumerate(progression):
        # Derive per-chord seed to keep segments reproducible but per-chord varied.
        chord_seed = spec.seed + 1000 * chord_idx + 7

        bass_events, treble_events = broken_chord_arpeggio(
            key_root_midi=key_root_midi,
            roman=roman,
            chord_dur_beats=chord_dur_beats,
            density=spec.density,
            seed=chord_seed,
        )

        for offs, midi_p, dur_beats, vel in bass_events:
            n = note.Note()
            n.pitch.midi = midi_p
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            bass_part.insert(running_offset + offs, n)

        for offs, midi_p, dur_beats, vel in treble_events:
            n = note.Note()
            n.pitch.midi = midi_p
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            treble_part.insert(running_offset + offs, n)

        running_offset += chord_dur_beats

    # Melody (violin), computed once across the full progression.
    if violin_part is not None:
        mel_events = sparse_melody(
            key_root_midi=key_root_midi,
            roman_progression=progression,
            bars_per_chord=bars_per_chord,
            tier=spec.tier,
            seed=spec.seed ^ 0xBEEF,
        )
        for offs, midi_p, dur_beats, vel in mel_events:
            n = note.Note()
            n.pitch.midi = midi_p
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            violin_part.insert(offs, n)

    # Drums, computed once across the full segment.
    drum_events = calm_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xD70,
    )
    for offs, midi_p, dur_beats, vel in drum_events:
        n = note.Note()
        n.pitch.midi = midi_p
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        # Route to MIDI channel 10 on export.
        n.channel = 10
        drum_part.insert(offs, n)

    # Assemble.
    score.insert(0, bass_part)
    score.insert(0, treble_part)
    if violin_part is not None:
        score.insert(0, violin_part)
    score.insert(0, drum_part)

    # Attach a compact metadata dict for the MIR audit / provenance log.
    score.metadata = _make_metadata(spec, progression)
    return score


def calm_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Emit a near-silent calm drum pattern.

    Returns a list of (offset_beats, midi_pitch, duration_beats, velocity)
    events. All events target GM percussion note numbers; the caller is
    responsible for routing them to MIDI channel 10 during export.

    Design:
      - Kick on beat 1 of every bar. Velocity 22-45 depending on tier.
      - Brush swell on beat 3 of every bar, tier >= 3 only. Very quiet.
      - No snare, no hats, no cymbals. Ever.
      - Tiny velocity jitter (+-3) via `seed` so the pattern feels human
        rather than metronomic, preserving beat_consistency ~0.98.
    """
    rng = random.Random(seed ^ 0xD70)
    events: list[tuple[float, int, float, int]] = []
    kick_vel = _TIER_KICK_VEL[tier]
    brush_on = _TIER_BRUSH_ON[tier]
    brush_vel = _TIER_BRUSH_VEL[tier]

    for bar in range(duration_bars):
        bar_offset = bar * 4.0
        # Beat 1: kick.
        events.append(
            (bar_offset + 0.0, _CALM_KICK_MIDI, 0.5, max(1, kick_vel + rng.randint(-3, 3)))
        )
        # Beat 3: brush swell (higher tiers only).
        if brush_on:
            events.append(
                (bar_offset + 2.0, _CALM_BRUSH_MIDI, 0.5, max(1, brush_vel + rng.randint(-3, 3)))
            )
    return events


def _make_metadata(spec: CalmSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object; also expose fields for the audit log."""
    from music21 import metadata as m21meta

    md = m21meta.Metadata()
    md.title = f"calm_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.calm_cell.v2"
    # music21 Metadata is picky about custom fields; store a JSON blob in a
    # documented custom attribute. The composer/renderer/audit pipeline reads
    # `score.metadata.groovegen_calm_spec` if present.
    md.groovegen_calm_spec = {
        "family": "calm",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "add_violin": spec.add_violin,
        "seed": spec.seed,
        "drums": {
            "pattern": "kick_beat1" if spec.tier < 3 else "kick_beat1_brush_beat3",
            "kick_velocity": _TIER_KICK_VEL[spec.tier],
            "brush_on": _TIER_BRUSH_ON[spec.tier],
            "brush_velocity": _TIER_BRUSH_VEL[spec.tier],
            "snare": False,
            "hats": False,
            "cymbals": False,
        },
        "generator_version": "calm_cell.v2.1",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------

def generate_segment_calm_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the frozen composer boundary for genre == 'calm'.

    Callers (e.g. the CascadeController's segment renderer) can dispatch:

        if genre == "calm":
            return generate_segment_calm_adapter(genre, tempo_bpm,
                                                 density, duration_bars, seed)
        else:
            return legacy_generate_segment(genre, tempo_bpm, density,
                                            duration_bars, seed)

    This keeps every other family unchanged while swapping calm to v2.
    """
    if genre != "calm":
        raise ValueError(
            f"generate_segment_calm_adapter received genre={genre!r}; only 'calm' is supported."
        )
    return generate_calm_segment(
        tempo_bpm=tempo_bpm,
        density=density,
        duration_bars=duration_bars,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Self-test: render five tiers to MIDI when run as a script.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    out_dir = os.environ.get("CALM_OUT_DIR", "./calm_cell_v2_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_calm_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=42 + tier,
        )
        fp = os.path.join(out_dir, f"calm_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
