"""
lofi_cell.py -- Lofi-family generator for GrooveGen.

Idiom and scope
---------------
Lofi hip-hop / chillhop, ~70-85 BPM. Rhodes-piano forward, upright bass,
sparse boom-bap-lite drums, jazz-adjacent extended chord voicings with
smooth voice leading between them. The "hazy" quality comes from the
harmony (rich extensions + smooth voice-leading), not from tempo tricks
or complex rhythms.

Stress-tests the shared VOICINGS library where rock_cell stressed the
patterns library:
  - `smooth_voice_lead`  -- state-carrying voice leading across the phrase
  - `quartal_voicing`    -- stacked 4ths for McCoy-Tyner lofi flavor
  - `sus_add9`           -- sus2/sus4 add9 for floating harmony
  - `rootless_A_B`       -- Bill Evans rootless voicings (higher tiers only)
  - `broken_chord_arpeggio_re` -- gentle arpeggio texture from patterns.py

Everything else is lofi-specific glue:
  1. Tier -> tempo / density / voicing-type mapping.
  2. Sparse boom-bap-lite drum pattern (much quieter than rock).
  3. Rhodes-forward instrumentation (GM 5, Electric Piano 1).
  4. Optional tier-4+ vinyl-noise pad overlay (GM 89, Warm Pad).

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'lofi'. Returns a
`music21.stream.Score` with:
  Part 0: Upright bass (GM 32, Acoustic Bass)
  Part 1: Rhodes piano -- extended voicings, sustained (GM 5)
  Part 2: Rhodes piano -- broken-chord arpeggios in a higher register (GM 5)
  Part 3: Boom-bap-lite drums (channel 10)
  Part 4 (optional, tier >= 4): Warm pad underlay (GM 89, Warm Pad)

Ladder position in GrooveGen
----------------------------
Lofi sits between calm and R&B on the energy ramp:
  calm (60-78) -> lofi (70-85) -> R&B (85-105) -> pop (100-115) ->
  Latin (100-120) -> rock (110-130)

The lofi->R&B transition is the most seamless in the ladder because both
families share jazz-derived harmony; only the rhythmic density really
changes.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

from composer.patterns import broken_chord_arpeggio_re
from composer.voicings import (
    quartal_voicing,
    rootless_A_B,
    smooth_voice_lead,
    sus_add9,
)


# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

LOFI_TEMPO_MIN_BPM: int = 70
LOFI_TEMPO_MAX_BPM: int = 85

# Tier -> tempo. Slower band than rock; lofi tiers shouldn't feel "faster",
# they should feel "richer".
_TIER_TEMPO: dict[int, int] = {1: 70, 2: 74, 3: 78, 4: 82, 5: 85}

# Density floor per tier: arpeggio density (fraction of 16ths struck).
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.20, 2: 0.35, 3: 0.50, 4: 0.65, 5: 0.80}

# Voicing type per tier. Lower tiers use simpler voicings; higher tiers use
# richer jazz voicings. All tiers thread through smooth_voice_lead to keep
# chord-to-chord motion minimal (this is the lofi harmonic signature).
#   1: sus2 add9        -- floaty, simple, two-color harmony
#   2: sus4 add9        -- slightly more tension
#   3: quartal          -- stacked 4ths, McCoy Tyner adjacent
#   4: rootless_A       -- Bill Evans rootless A-form
#   5: rootless_B       -- Bill Evans rootless B-form (richer, higher extensions)
_TIER_VOICING_KIND: dict[int, str] = {
    1: "sus2_add9",
    2: "sus4_add9",
    3: "quartal",
    4: "rootless_A",
    5: "rootless_B",
}

# Drums: boom-bap-lite. MUCH quieter than rock (~60-75 velocity range).
# Kick beats 1 & 3, snare beats 2 & 4, hats on 8ths. Optional rim-click
# accents at higher tiers.
_LOFI_KICK_MIDI:      int = 36
_LOFI_SNARE_MIDI:     int = 40   # Electric Snare (softer than Acoustic)
_LOFI_HAT_MIDI:       int = 42
_LOFI_OPEN_HAT_MIDI:  int = 46
_LOFI_RIMSHOT_MIDI:   int = 37   # Side Stick (rim click) -- lofi signature

# Velocities: everything is soft. This is what separates lofi drums from
# rock drums even though the bitmap positions are nearly identical.
_TIER_KICK_VEL:    dict[int, int] = {1: 55, 2: 62, 3: 68, 4: 72, 5: 76}
_TIER_SNARE_VEL:   dict[int, int] = {1: 45, 2: 52, 3: 58, 4: 62, 5: 66}
_TIER_HAT_VEL:     dict[int, int] = {1: 30, 2: 36, 3: 42, 4: 48, 5: 52}
_TIER_RIMSHOT_VEL: dict[int, int] = {1: 0,  2: 0,  3: 40, 4: 45, 5: 50}
_TIER_RIMSHOT_ON:  dict[int, bool] = {1: False, 2: False, 3: True, 4: True, 5: True}

_TIER_BASS_VEL_BASE:  dict[int, int] = {1: 50, 2: 55, 3: 60, 4: 65, 5: 68}
_TIER_RHODES_CHORD_VEL: dict[int, int] = {1: 55, 2: 60, 3: 65, 4: 68, 5: 72}
_TIER_ARPEGGIO_VEL:  dict[int, int] = {1: 45, 2: 50, 3: 55, 4: 60, 5: 62}
_TIER_PAD_VEL:       dict[int, int] = {1: 0,  2: 0,  3: 0,  4: 32, 5: 38}
_TIER_PAD_ON:        dict[int, bool] = {1: False, 2: False, 3: False, 4: True, 5: True}

# Lofi progression bank. All are stepwise or ii-V-I-derived progressions with
# smooth voice-leading potential. Notated in major keys directly.
_PROGRESSIONS: list[list[str]] = [
    ["ii", "V",  "I", "vi"],       # jazz ii-V-I with vi tag
    ["I",  "vi", "IV", "V"],       # classic 50s / lofi staple
    ["vi", "ii", "V", "I"],        # relative-minor ii-V-I
    ["I",  "iii","vi", "IV"],      # stepwise descending thirds feel
    ["IV", "iii","ii", "I"],       # descending 4ths, very lofi
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

@dataclass
class LofiSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str
    voicing_kind: str        # from _TIER_VOICING_KIND
    add_warm_pad: bool       # tier >= 4
    seed: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _key_root_midi(key_root_name: str) -> int:
    """Map a key name like 'C' or 'D' to a mid-register root MIDI pitch (C3-B3)."""
    p = pitch.Pitch(key_root_name + "3")
    return int(p.midi)


def _resolve_spec(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> LofiSpec:
    """Clamp inputs into the lofi identity band and derive tier."""
    clamped_bpm = max(LOFI_TEMPO_MIN_BPM, min(LOFI_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))
    rng = random.Random(seed)
    # Lofi keys favor "warm" keys with lots of accidentals in melody; the
    # actual pitch content is transposed either way, so this is really just
    # a variety knob rather than a musical claim.
    key_root = rng.choice(["C", "D", "Eb", "F", "G", "Ab", "Bb"])
    return LofiSpec(
        tempo_bpm=clamped_bpm,
        density=density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        voicing_kind=_TIER_VOICING_KIND[tier],
        add_warm_pad=_TIER_PAD_ON[tier],
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    rng = random.Random(seed ^ 0x10F1)
    return list(rng.choice(_PROGRESSIONS))


def _extend_triad_to_seventh(
    triad: list[int],
    roman: str,
) -> list[int]:
    """Add a diatonic 7th to a major/minor triad.

    Convention (major-key context, matches _ROMAN_TABLE):
      I, IV                 -> maj7 (add root+11)
      ii, iii, vi           -> min7 (add root+10)
      V                     -> dom7 (add root+10)
      V/vi (secondary dom)  -> dom7 (add root+10)

    If the input already has 4+ notes, return it unchanged.
    Used by lofi's rootless voicings, which require a 7th chord as input.
    """
    if len(triad) >= 4:
        return list(triad)
    root = triad[0]
    # Map Roman -> seventh-interval-above-root.
    seventh_interval = {
        "I": 11, "IV": 11,           # maj7
        "ii": 10, "iii": 10, "vi": 10, # min7
        "V": 10, "V/vi": 10,          # dom7
    }.get(roman, 10)
    return sorted(list(triad) + [root + seventh_interval])


def _voice_chord_for_tier(
    voicing_kind: str,
    key_root_midi: int,
    roman: str,
    prev_voicing: list[int] | None,
) -> list[int]:
    """Build one chord voicing per the tier's voicing kind, then smooth-voice-lead
    it against the previous chord if there was one.

    This is the lofi-signature move: rich voicings, but the chord-to-chord
    motion is minimized by threading everything through smooth_voice_lead.
    Rock does the opposite -- power chords with no voice-leading logic.

    For rootless voicings (tiers 4-5) we need a 7th chord as input, but
    _ROMAN_TABLE only gives triads for I/ii/iii/IV/V/vi. We extend to the
    appropriate diatonic 7th first via _extend_triad_to_seventh.
    """
    # Import here to avoid module-load-time circular dependency with calm_cell.
    from composer.calm_cell import _build_chord_tones

    # First, build the raw voicing (unsmoothed).
    if voicing_kind == "sus2_add9":
        raw = sus_add9(
            key_root_midi=key_root_midi, roman=roman, which="sus2",
            register_low=55, register_high=79,  # G3-G5
        )
    elif voicing_kind == "sus4_add9":
        raw = sus_add9(
            key_root_midi=key_root_midi, roman=roman, which="sus4",
            register_low=55, register_high=79,
        )
    elif voicing_kind == "quartal":
        raw = quartal_voicing(
            key_root_midi=key_root_midi, roman=roman, n_stacked_fourths=3,
            register_low=55, register_high=79,
        )
    elif voicing_kind == "rootless_A":
        # Rootless needs 4-note chords; build seventh chord tones explicitly.
        triad = _build_chord_tones(key_root_midi, roman)
        seventh_chord = _extend_triad_to_seventh(triad, roman)
        raw = rootless_A_B(
            chord_tones=seventh_chord, form="A",
            register_low=55, register_high=79,
        )
    elif voicing_kind == "rootless_B":
        triad = _build_chord_tones(key_root_midi, roman)
        seventh_chord = _extend_triad_to_seventh(triad, roman)
        raw = rootless_A_B(
            chord_tones=seventh_chord, form="B",
            register_low=55, register_high=79,
        )
    else:
        raise ValueError(f"Unknown lofi voicing_kind: {voicing_kind!r}")

    # Then smooth-voice-lead it to the previous chord (if any). This uses the
    # `chord_tones=` path of smooth_voice_lead: we pass the raw voicing as the
    # chord tones so it doesn't try to look up a Roman numeral again.
    smoothed = smooth_voice_lead(
        chord_tones=raw,
        prev_voicing=prev_voicing,
        register_low=55, register_high=79,
    )
    return smoothed


# ---------------------------------------------------------------------------
# Drum & bass patterns (lofi-specific)
# ---------------------------------------------------------------------------

def lofi_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Boom-bap-lite drum pattern.

    Per bar (4/4):
      Kick   on beats 1 and 3          (soft)
      Snare  on beats 2 and 4          (soft; rim-click accents at tier >= 3)
      Hi-hat on every 8th note         (very soft)
      Open hi-hat on the "and" of 4    (tier >= 4 only, per-bar accent)
      Rim click on the "and" of 3      (tier >= 3, adds boom-bap flavor)

    Returns (offset_beats, midi_pitch, duration_beats, velocity) events.
    Caller routes to MIDI channel 10 on export.
    """
    rng = random.Random(seed ^ 0xBEAB)
    events: list[tuple[float, int, float, int]] = []
    kick_vel  = _TIER_KICK_VEL[tier]
    snare_vel = _TIER_SNARE_VEL[tier]
    hat_vel   = _TIER_HAT_VEL[tier]
    rim_vel   = _TIER_RIMSHOT_VEL[tier]
    rim_on    = _TIER_RIMSHOT_ON[tier]

    def _v(base: int) -> int:
        return max(1, base + rng.randint(-3, 3))

    for bar in range(duration_bars):
        base = bar * 4.0

        # Kick on beats 1 and 3
        events.append((base + 0.0, _LOFI_KICK_MIDI, 0.25, _v(kick_vel)))
        events.append((base + 2.0, _LOFI_KICK_MIDI, 0.25, _v(kick_vel)))

        # Snare on beats 2 and 4
        events.append((base + 1.0, _LOFI_SNARE_MIDI, 0.25, _v(snare_vel)))
        events.append((base + 3.0, _LOFI_SNARE_MIDI, 0.25, _v(snare_vel)))

        # Hi-hat on every 8th note
        for eighth in range(8):
            hat_offset = base + eighth * 0.5
            if tier >= 4 and eighth == 7:
                # Open hi-hat accent on the "and" of 4
                events.append(
                    (hat_offset, _LOFI_OPEN_HAT_MIDI, 0.5, _v(hat_vel + 6))
                )
            else:
                events.append(
                    (hat_offset, _LOFI_HAT_MIDI, 0.125, _v(hat_vel))
                )

        # Rim click on the "and" of 3 (boom-bap flavor accent)
        if rim_on:
            events.append(
                (base + 2.5, _LOFI_RIMSHOT_MIDI, 0.125, _v(rim_vel))
            )

    return events


def _lofi_bass_pattern(
    key_root_midi: int,
    roman: str,
    chord_dur_beats: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Simple upright-bass pattern: root on beat 1, 5th on beat 3.

    At tier >= 3, adds a passing tone on the "and" of beat 4 to lead into
    the next chord. This is the lofi upright-bass signature: sparse,
    room-to-breathe, walks a little at higher tiers.
    """
    from composer.calm_cell import _build_chord_tones
    rng = random.Random(seed ^ 0xBA22)
    events: list[tuple[float, int, float, int]] = []
    base_vel = _TIER_BASS_VEL_BASE[tier]

    # Get the chord's root and 5th (approximate -- use the first and third
    # tones of the chord as root and 5th).
    tones = _build_chord_tones(key_root_midi, roman)
    root_midi = tones[0]
    fifth_midi = tones[2] if len(tones) >= 3 else tones[0] + 7

    # Drop bass to a low register (C2-C3).
    while root_midi >= 48:
        root_midi -= 12
    while fifth_midi >= 48:
        fifth_midi -= 12
    while root_midi < 36:
        root_midi += 12
    while fifth_midi < 36:
        fifth_midi += 12

    n_bars = int(chord_dur_beats / 4.0)
    for bar in range(n_bars):
        bar_offset = bar * 4.0
        # Root on beat 1
        events.append((bar_offset + 0.0, root_midi, 1.5, base_vel + rng.randint(-2, 2)))
        # 5th on beat 3
        events.append((bar_offset + 2.0, fifth_midi, 1.5, base_vel - 4 + rng.randint(-2, 2)))
        # Passing tone on "and" of 4 (tier >= 3)
        if tier >= 3 and bar < n_bars - 1:  # skip on last bar of chord (avoid conflict with next-chord downbeat)
            passing = root_midi + rng.choice([-2, -1, 1, 2])
            events.append((bar_offset + 3.5, passing, 0.5, base_vel - 8 + rng.randint(-2, 2)))

    return events


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def generate_lofi_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
    add_warm_pad: bool | None = None,
) -> stream.Score:
    """Generate a lofi segment as a music21 Score.

    Contract matches `generate_segment(genre='lofi', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      Part 0: Upright bass
      Part 1: Rhodes piano -- sustained extended voicings
      Part 2: Rhodes piano -- gentle broken-chord arpeggios
      Part 3: Boom-bap-lite drums (channel 10)
      Part 4 (optional, tier >= 4): Warm pad underlay
    """
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    if add_warm_pad is not None:
        spec.add_warm_pad = add_warm_pad

    progression = _select_progression(spec.seed)
    key_root_midi = _key_root_midi(spec.key_root)

    bars_per_chord = max(1, spec.duration_bars // len(progression))
    beats_per_bar = 4
    chord_dur_beats = bars_per_chord * beats_per_bar

    # ---- Build the Score -------------------------------------------------
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, key.Key(spec.key_root))

    # Parts
    bass_part = stream.Part(id="lofi_bass")
    bass_part.insert(0, instrument.AcousticBass())

    rhodes_chord_part = stream.Part(id="lofi_rhodes_chords")
    rhodes_chord_part.insert(0, instrument.ElectricPiano())  # GM 5 (Rhodes-adjacent)

    rhodes_arp_part = stream.Part(id="lofi_rhodes_arp")
    rhodes_arp_part.insert(0, instrument.ElectricPiano())

    drum_part = stream.Part(id="lofi_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9
    drum_part.insert(0, drum_kit)

    pad_part: stream.Part | None = None
    if spec.add_warm_pad:
        pad_part = stream.Part(id="lofi_warm_pad")
        pad_part.insert(0, instrument.Sampler())  # placeholder; renderer routes to GM 89

    # ---- Iterate chords with smooth voice leading ------------------------
    running_offset = 0.0
    prev_voicing: list[int] | None = None
    for chord_idx, roman in enumerate(progression):
        chord_seed = spec.seed + 1000 * chord_idx + 11

        # ---- Rhodes sustained chord voicing (from shared library) ------
        voicing = _voice_chord_for_tier(
            voicing_kind=spec.voicing_kind,
            key_root_midi=key_root_midi,
            roman=roman,
            prev_voicing=prev_voicing,
        )
        chord_vel = _TIER_RHODES_CHORD_VEL[spec.tier]
        for p_midi in voicing:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(chord_dur_beats)  # sustained the whole chord
            n.volume.velocity = chord_vel
            rhodes_chord_part.insert(running_offset, n)

        # ---- Rhodes gentle arpeggio (from shared patterns library) -----
        # broken_chord_arpeggio_re returns (bass_events, treble_events). For
        # lofi we only use the treble arpeggio -- the bass line comes from
        # our own _lofi_bass_pattern (upright feel). This preserves the
        # shared-library dependency while keeping lofi's own bass character.
        _bass_unused, arp_treble = broken_chord_arpeggio_re(
            key_root_midi=key_root_midi,
            roman=roman,
            chord_dur_beats=chord_dur_beats,
            density=spec.density,
            seed=chord_seed ^ 0xA5A,
        )
        arp_vel = _TIER_ARPEGGIO_VEL[spec.tier]
        for offs, p_midi, dur_beats, vel_lib in arp_treble:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = max(1, arp_vel + (vel_lib - 60))
            rhodes_arp_part.insert(running_offset + offs, n)

        # ---- Upright bass -----------------------------------------------
        bass_events = _lofi_bass_pattern(
            key_root_midi=key_root_midi,
            roman=roman,
            chord_dur_beats=chord_dur_beats,
            tier=spec.tier,
            seed=chord_seed ^ 0xBA22,
        )
        for offs, p_midi, dur_beats, vel in bass_events:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            bass_part.insert(running_offset + offs, n)

        # ---- Warm pad underlay (tier >= 4) ------------------------------
        if pad_part is not None:
            # Same voicing, dropped an octave, super quiet, held.
            pad_voicing = [p - 12 for p in voicing if p - 12 >= 43]  # >= G2
            if pad_voicing:
                pad_vel = _TIER_PAD_VEL[spec.tier]
                for p_midi in pad_voicing[:3]:  # thin the pad -- 3 notes max
                    n = note.Note()
                    n.pitch.midi = p_midi
                    n.duration = duration.Duration(chord_dur_beats)
                    n.volume.velocity = pad_vel
                    pad_part.insert(running_offset, n)

        prev_voicing = voicing
        running_offset += chord_dur_beats

    # ---- Drums (computed once across the full segment) -------------------
    drum_events = lofi_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xBEAB,
    )
    for offs, p_midi, dur_beats, vel in drum_events:
        n = note.Note()
        n.pitch.midi = p_midi
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        n.channel = 10
        drum_part.insert(offs, n)

    # ---- Assemble --------------------------------------------------------
    score.insert(0, bass_part)
    score.insert(0, rhodes_chord_part)
    score.insert(0, rhodes_arp_part)
    score.insert(0, drum_part)
    if pad_part is not None:
        score.insert(0, pad_part)

    score.metadata = _make_metadata(spec, progression)
    return score


def _make_metadata(spec: LofiSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object with a compact provenance blob."""
    from music21 import metadata as m21meta

    md = m21meta.Metadata()
    md.title = f"lofi_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.lofi_cell.v1"
    md.groovegen_lofi_spec = {
        "family": "lofi",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "voicing_kind": spec.voicing_kind,
        "voice_leading": "smooth_voice_lead",
        "add_warm_pad": spec.add_warm_pad,
        "seed": spec.seed,
        "drums": {
            "pattern": "boom_bap_lite: kick_1_3 + snare_2_4 + hats_8th"
                       + (" + rim_and3" if _TIER_RIMSHOT_ON[spec.tier] else "")
                       + (" + open_hat_and4" if spec.tier >= 4 else ""),
            "kick_velocity":  _TIER_KICK_VEL[spec.tier],
            "snare_velocity": _TIER_SNARE_VEL[spec.tier],
            "hat_velocity":   _TIER_HAT_VEL[spec.tier],
        },
        "rhodes_chords": {
            "voicing": spec.voicing_kind,
            "sustain": "full_chord_duration",
            "velocity_base": _TIER_RHODES_CHORD_VEL[spec.tier],
        },
        "rhodes_arpeggio": {
            "pattern": "broken_chord_arpeggio_re",
            "register": "octave_above_chord_voicing",
            "velocity_base": _TIER_ARPEGGIO_VEL[spec.tier],
        },
        "bass": {
            "pattern": "upright_root_5_with_passing",
            "velocity_base": _TIER_BASS_VEL_BASE[spec.tier],
        },
        "warm_pad": {
            "enabled": spec.add_warm_pad,
            "voicing": "chord_octave_below" if spec.add_warm_pad else None,
        },
        "generator_version": "lofi_cell.v1",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------

def generate_segment_lofi_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the composer boundary for genre == 'lofi'."""
    if genre != "lofi":
        raise ValueError(
            f"generate_segment_lofi_adapter received genre={genre!r}; only 'lofi' is supported."
        )
    return generate_lofi_segment(
        tempo_bpm=tempo_bpm,
        density=density,
        duration_bars=duration_bars,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import os
    import sys

    out_dir = os.environ.get("LOFI_OUT_DIR", "./lofi_cell_v1_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_lofi_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=100 + tier,
        )
        fp = os.path.join(out_dir, f"lofi_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
