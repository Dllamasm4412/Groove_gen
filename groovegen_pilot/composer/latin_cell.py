"""
latin_cell.py -- Latin-family generator for GrooveGen.

Idiom and scope
---------------
Latin pop / Latin urban, ~100-120 BPM, with a montuno-informed piano layer,
3-3-2 tresillo bass identity, and tier-scaled Afro-Cuban percussion accents.
This family is patterns-forward (like rock): shared rhythmic pattern functions
carry the idiom, while this file wires them into the GrooveGen tier ladder.

Stress-tests the shared libraries by importing FOUR pattern functions and THREE
voicing functions from `patterns.py` and `voicings.py`. The only Latin-specific
logic in this file is:
  1. The tier -> tempo / density / voicing mapping (Latin-specific ramp).
  2. The percussion layer growth (shaker -> clave -> congas -> cowbell -> fills).
  3. The progression bank using relative-major notation for minor-leaning loops.
    4. The tier-5 culmination as saturated montuno + full percussion + timbale fills.

Everything else -- montuno ostinato, tresillo bass, tier-1 walk intro,
and voicing constructors -- comes from shared libraries.

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'latin'.
Returns a `music21.stream.Score` with:
  Part 0: Upright bass (GM 32, Acoustic Bass)
  Part 1: Piano comping + montuno on one interleaved part (GM 0, Acoustic Grand)
  Part 2: Latin percussion (channel 10)

Tier-5 differentiation comes from montuno saturation plus full percussion and
phrase-end timbale-style fills, not from a separate melodic solo layer.

Ladder position in GrooveGen
----------------------------
Latin sits between pop and rock on the calm -> lofi -> R&B -> pop -> Latin ->
rock energy ramp. It should read as a coherent extension of pop's pulse with
more syncopated bass-piano interlock, not as a genre reset.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

from composer.patterns import (
    bassline_walk,
    montuno_pattern,
    tresillo_bass,
)
from composer.voicings import (
    open_position_triad,
    quartal_voicing,
    shell_voicing,
)

# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

LATIN_TEMPO_MIN_BPM: int = 100
LATIN_TEMPO_MAX_BPM: int = 120

# Tier -> tempo. Higher tier => more energy, still inside the Latin band.
_TIER_TEMPO: dict[int, int] = {1: 100, 2: 105, 3: 110, 4: 115, 5: 120}

# Density floor per tier. Tier 1 leaves air; tier 5 is near saturation.
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.20, 2: 0.35, 3: 0.55, 4: 0.75, 5: 0.95}

# Tier voicing map for the piano stab layer.
_TIER_VOICING_KIND: dict[int, str] = {
    1: "open_position_triad",
    2: "shell_voicing",
    3: "shell_voicing",
    4: "quartal_voicing",
    5: "quartal_voicing",
}

# Tier montuno densities. Tier 1-2 do not run montuno; tier 3+ does.
_TIER_MONTUNO_DENSITY: dict[int, float] = {1: 0.00, 2: 0.00, 3: 0.50, 4: 0.75, 5: 1.00}

# GM percussion note numbers (channel 10).
_LATIN_KICK_MIDI: int = 36
_LATIN_SIDE_STICK_MIDI: int = 37
_LATIN_COWBELL_MIDI: int = 56
_LATIN_HI_BONGO_MIDI: int = 60
_LATIN_LOW_BONGO_MIDI: int = 61
_LATIN_OPEN_HIGH_CONGA_MIDI: int = 63
_LATIN_LOW_CONGA_MIDI: int = 64
_LATIN_SHAKER_MIDI: int = 70
_LATIN_CLAVES_MIDI: int = 75

# Tier-scaled velocity constants requested for this family.
_TIER_MONTUNO_VEL: dict[int, int] = {1: 0, 2: 0, 3: 65, 4: 73, 5: 80}
_TIER_TRESILLO_BASS_VEL: dict[int, int] = {1: 0, 2: 66, 3: 72, 4: 78, 5: 84}
_TIER_PIANO_STAB_VEL: dict[int, int] = {1: 60, 2: 65, 3: 71, 4: 78, 5: 83}
_TIER_CLAVE_VEL: dict[int, int] = {1: 0, 2: 63, 3: 68, 4: 73, 5: 78}
_TIER_SHAKER_VEL: dict[int, int] = {1: 56, 2: 60, 3: 64, 4: 68, 5: 72}
_TIER_CONGA_VEL: dict[int, int] = {1: 0, 2: 0, 3: 68, 4: 73, 5: 78}
_TIER_COWBELL_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 72, 5: 78}

# Additional helpers for balancing non-requested layers.
_TIER_WALK_BASS_VEL_BASE: dict[int, int] = {1: 60, 2: 0, 3: 0, 4: 0, 5: 0}
_TIER_KICK_ACCENT_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 72}

# Latin progressions (minor-leaning) represented in RELATIVE MAJOR, following
# the same convention used by rock_cell:
#
# Cross-key spelling reference (relative-major -> intended minor-key sense):
#   Roman "vi"  <=> minor i     (tonic minor)
#   Roman "V"   <=> minor VII   (subtonic major)
#   Roman "IV"  <=> minor VI    (submediant major)
#   Roman "I"   <=> minor III   (mediant major)
#   Roman "ii"  <=> minor iv    (predominant)
_PROGRESSIONS: list[list[str]] = [
    ["vi", "V", "IV", "V"],
    ["I", "V", "vi", "IV"],
    ["ii", "V", "I", "vi"],
    ["vi", "IV", "V", "V"],
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass
class LatinSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str
    voicing_kind: str
    montuno_enabled: bool
    seed: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _key_root_midi(key_root_name: str) -> int:
    """Map a key name like 'C' or 'Eb' to a mid-register root MIDI pitch (C3-B3)."""
    p = pitch.Pitch(key_root_name + "3")
    return int(p.midi)


def _resolve_spec(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> LatinSpec:
    """Clamp inputs into the Latin identity band and derive tier-level toggles."""
    clamped_bpm = max(LATIN_TEMPO_MIN_BPM, min(LATIN_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    clamped_density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))

    rng = random.Random(seed)
    key_root = rng.choice(["C", "D", "Eb", "F", "G"])

    return LatinSpec(
        tempo_bpm=clamped_bpm,
        density=clamped_density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        voicing_kind=_TIER_VOICING_KIND[tier],
        montuno_enabled=(tier >= 3),
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    """Select a 4-chord Latin loop deterministically from the progression bank."""
    rng = random.Random(seed ^ 0x1A71)
    return list(rng.choice(_PROGRESSIONS))


def _voice_chord_for_tier(
    voicing_kind: str,
    key_root_midi: int,
    roman: str,
) -> list[int]:
    """Build the tier-selected voicing shape for one harmonic slot.

    This keeps voicing selection explicit and deterministic per tier so the
    generator's identity is defined by tier design rather than by run-time
    improvisation.
    """
    if voicing_kind == "open_position_triad":
        return open_position_triad(
            key_root_midi=key_root_midi,
            roman=roman,
            register_low=55,
            register_high=76,
        )
    if voicing_kind == "shell_voicing":
        return shell_voicing(
            key_root_midi=key_root_midi,
            roman=roman,
            include_root=True,
            register_low=52,
            register_high=76,
        )
    if voicing_kind == "quartal_voicing":
        return quartal_voicing(
            key_root_midi=key_root_midi,
            roman=roman,
            n_stacked_fourths=3,
            register_low=57,
            register_high=82,
        )
    raise ValueError(f"Unknown latin voicing_kind: {voicing_kind!r}")


def _piano_stab_pattern(
    chord_pitches: Sequence[int],
    chord_dur_beats: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Emit short piano stabs on beats 1 and 3 for each bar in the chord span.

    This preserves the requested comping skeleton in tiers 1-2 and keeps an
    accent layer behind montuno in tiers 3-5. Durations are short so rhythmic
    definition stays clear at 120 BPM.
    """
    rng = random.Random(seed ^ 0x57AB)
    events: list[tuple[float, int, float, int]] = []
    n_bars = max(1, int(chord_dur_beats // 4.0))
    stab_dur = 0.50 if tier <= 2 else 0.35

    for bar in range(n_bars):
        base = bar * 4.0
        for beat, accent in ((0.0, 2), (2.0, 0)):
            vel = max(1, min(120, _TIER_PIANO_STAB_VEL[tier] + accent + rng.randint(-3, 3)))
            for p_midi in chord_pitches:
                events.append((base + beat, p_midi, stab_dur, vel))

    return events


def _latin_bass_for_chord(
    key_root_midi: int,
    roman: str,
    chord_dur_beats: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Build the tier-specific bass role for one chord span.

    Tier 1 uses a walking intro texture (`bassline_walk`) to stage entry.
    Tiers 2-5 switch to tresillo (`tresillo_bass`) to make Latin identity
    immediately audible.
    """
    if tier == 1:
        walk_events = bassline_walk(
            key_root_midi=key_root_midi,
            roman=roman,
            duration_beats=chord_dur_beats,
            seed=seed ^ 0xBA51,
            register_low=36,
            register_high=52,
        )
        out: list[tuple[float, int, float, int]] = []
        for offs, p_midi, dur_beats, vel_lib in walk_events:
            vel = max(1, min(120, _TIER_WALK_BASS_VEL_BASE[tier] + (vel_lib - 58)))
            out.append((offs, p_midi, min(dur_beats, 0.90), vel))
        return out

    tresillo_events = tresillo_bass(
        key_root_midi=key_root_midi,
        roman=roman,
        duration_beats=chord_dur_beats,
        seed=seed ^ 0x7351,
        register_low=36,
        register_high=52,
    )
    out = []
    for offs, p_midi, dur_beats, vel_lib in tresillo_events:
        vel = max(1, min(120, _TIER_TRESILLO_BASS_VEL[tier] + (vel_lib - 62)))
        out.append((offs, p_midi, min(dur_beats, 0.75), vel))
    return out


def _clave_offsets_for_bar(bar_idx: int) -> list[float]:
    """Return 3-2 son-clave offsets for one bar inside a repeating 2-bar cycle.

    Cycle:
      Bar A (3-side): beats 1, 2.5, 4.0
      Bar B (2-side): beats 2.0, 3.0
    """
    if bar_idx % 2 == 0:
        return [0.0, 1.5, 3.0]
    return [1.0, 2.0]


def _tier_percussion_flags(tier: int) -> dict[str, bool]:
    """Compute tier-enabled percussion layers for metadata and routing decisions."""
    return {
        "clave": tier >= 2,
        "shaker": True,
        "congas": tier >= 3,
        "cowbell": tier >= 4,
        "timbale_fills": tier == 5,
        "kick_accents": tier == 5,
    }


def latin_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Build the tier-scaled Latin percussion bed across the full segment.

    The pattern is deterministic in timing and instrumentation by tier; random
    state only jitters velocities to avoid machine-flat dynamics.
    """
    rng = random.Random(seed ^ 0x1A710)
    events: list[tuple[float, int, float, int]] = []

    flags = _tier_percussion_flags(tier)

    def _v(base: int, spread: int = 3) -> int:
        return max(1, min(120, base + rng.randint(-spread, spread)))

    for bar in range(duration_bars):
        base = bar * 4.0

        # Shaker on all 8ths, all tiers.
        for eighth in range(8):
            events.append(
                (base + eighth * 0.5, _LATIN_SHAKER_MIDI, 0.125, _v(_TIER_SHAKER_VEL[tier], 2))
            )

        if flags["clave"]:
            for offs in _clave_offsets_for_bar(bar):
                midi_pitch = (
                    _LATIN_SIDE_STICK_MIDI if (bar + int(offs * 2)) % 2 == 0 else _LATIN_CLAVES_MIDI
                )
                events.append((base + offs, midi_pitch, 0.125, _v(_TIER_CLAVE_VEL[tier], 2)))

        if flags["congas"]:
            # Conga support: slap on and-of-2, open tone on beat 4.
            events.append((base + 2.5, _LATIN_LOW_CONGA_MIDI, 0.25, _v(_TIER_CONGA_VEL[tier], 2)))
            events.append(
                (base + 3.0, _LATIN_OPEN_HIGH_CONGA_MIDI, 0.50, _v(_TIER_CONGA_VEL[tier] + 3, 2))
            )

        if flags["cowbell"]:
            for beat in range(4):
                events.append(
                    (base + float(beat), _LATIN_COWBELL_MIDI, 0.125, _v(_TIER_COWBELL_VEL[tier], 2))
                )

        if flags["kick_accents"] and bar % 2 == 1:
            events.append((base + 0.0, _LATIN_KICK_MIDI, 0.25, _v(_TIER_KICK_ACCENT_VEL[tier], 2)))

        if tier == 5:
            # Optional bongo color in the top tier.
            events.append(
                (base + 1.0, _LATIN_HI_BONGO_MIDI, 0.25, _v(_TIER_CONGA_VEL[tier] - 6, 2))
            )
            events.append(
                (base + 1.5, _LATIN_LOW_BONGO_MIDI, 0.25, _v(_TIER_CONGA_VEL[tier] - 8, 2))
            )

            # Phrase-end fill windows (bars 4 and 8 in 1-indexed counting).
            if flags["timbale_fills"] and (bar + 1) in (4, 8):
                fill_offsets = (2.5, 3.0, 3.25, 3.5, 3.75)
                fill_notes = (_LATIN_HI_BONGO_MIDI, _LATIN_LOW_BONGO_MIDI)
                for idx, offs in enumerate(fill_offsets):
                    events.append(
                        (base + offs, fill_notes[idx % 2], 0.125, _v(_TIER_CONGA_VEL[tier] + 2, 2))
                    )

    return events


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------


def generate_latin_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Generate a Latin segment as a music21 Score.

    Contract matches `generate_segment(genre='latin', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      Part 0: Upright bass
      Part 1: Piano stabs + montuno interleaved on one piano part
      Part 2: Latin percussion (channel 10)
    """
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
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

    # Part 0: Upright bass.
    bass_part = stream.Part(id="latin_bass")
    bass_part.insert(0, instrument.AcousticBass())

    # Part 1: Piano stabs + montuno.
    piano_part = stream.Part(id="latin_piano")
    piano_part.insert(0, instrument.Piano())

    # Part 2: Percussion.
    drum_part = stream.Part(id="latin_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9
    drum_part.insert(0, drum_kit)

    running_offset = 0.0
    for chord_idx, roman in enumerate(progression):
        chord_seed = spec.seed + 1000 * chord_idx + 17

        voicing = _voice_chord_for_tier(
            voicing_kind=spec.voicing_kind,
            key_root_midi=key_root_midi,
            roman=roman,
        )

        # Piano stabs (all tiers).
        stab_events = _piano_stab_pattern(
            chord_pitches=voicing,
            chord_dur_beats=chord_dur_beats,
            tier=spec.tier,
            seed=chord_seed,
        )
        for offs, p_midi, dur_beats, vel in stab_events:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            piano_part.insert(running_offset + offs, n)

        # Montuno layer (tier 3+).
        if spec.montuno_enabled:
            montuno_events = montuno_pattern(
                key_root_midi=key_root_midi,
                roman=roman,
                duration_beats=chord_dur_beats,
                density=_TIER_MONTUNO_DENSITY[spec.tier],
                seed=chord_seed ^ 0xA071,
                register_low=64,
                register_high=84,
            )
            for offs, p_midi, dur_beats, vel_lib in montuno_events:
                n = note.Note()
                n.pitch.midi = p_midi
                n.duration = duration.Duration(min(dur_beats, 0.50))
                n.volume.velocity = max(1, min(120, _TIER_MONTUNO_VEL[spec.tier] + (vel_lib - 60)))
                piano_part.insert(running_offset + offs, n)

        # Bass layer by tier.
        bass_events = _latin_bass_for_chord(
            key_root_midi=key_root_midi,
            roman=roman,
            chord_dur_beats=chord_dur_beats,
            tier=spec.tier,
            seed=chord_seed ^ 0xB455,
        )
        for offs, p_midi, dur_beats, vel in bass_events:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            bass_part.insert(running_offset + offs, n)

        running_offset += chord_dur_beats

    # Drums over full segment.
    drum_events = latin_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0x1A710,
    )
    for offs, p_midi, dur_beats, vel in drum_events:
        n = note.Note()
        n.pitch.midi = p_midi
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        drum_part.insert(offs, n)

    # Assemble.
    score.insert(0, bass_part)
    score.insert(0, piano_part)
    score.insert(0, drum_part)

    score.metadata = _make_metadata(spec, progression)
    return score


def _make_metadata(spec: LatinSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object with a compact provenance blob."""
    from music21 import metadata as m21meta

    percussion_enabled = _tier_percussion_flags(spec.tier)

    md = m21meta.Metadata()
    md.title = f"latin_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.latin_cell.v2"
    md.groovegen_latin_spec = {
        "family": "latin",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "voicing_kind_by_tier": dict(_TIER_VOICING_KIND),
        "voicing_kind": spec.voicing_kind,
        "percussion": percussion_enabled,
        "montuno_enabled": spec.montuno_enabled,
        "generator_version": "latin_cell.v2",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------


def generate_segment_latin_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the composer boundary for genre == 'latin'."""
    if genre != "latin":
        raise ValueError(
            f"generate_segment_latin_adapter received genre={genre!r}; only 'latin' is supported."
        )
    return generate_latin_segment(
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

    out_dir = os.environ.get("LATIN_OUT_DIR", "./latin_cell_v1_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_latin_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=200 + tier,
        )
        fp = os.path.join(out_dir, f"latin_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
