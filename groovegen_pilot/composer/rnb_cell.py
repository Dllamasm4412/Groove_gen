"""
rnb_cell.py -- R&B-family generator for GrooveGen (modern mellow groove idiom).

Idiom and scope
---------------
Modern R&B in an Am-centered palette: chord-forward Rhodes stabs, sub-bass
anchors with light ornaments, and a half-time straight-16th drum bed.

This module mirrors the cell-file architecture used by sibling generators:
constants, small helper functions, and a single generate_rnb_segment() entry
point returning a music21 Score for the existing MIDI render path.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from music21 import chord, duration, instrument, key, meter, note, stream, tempo

# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

RNB_TEMPO_MIN_BPM: int = 75
RNB_TEMPO_MAX_BPM: int = 85

# LOCKED tier ladder.
_TIER_TEMPO: dict[int, int] = {1: 75, 2: 78, 3: 80, 4: 83, 5: 85}
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.40, 2: 0.60, 3: 0.70, 4: 0.85, 5: 1.00}

# GM percussion note numbers (channel 10).
_RNB_KICK_MIDI: int = 36
_RNB_SNARE_MIDI: int = 38
_RNB_CLOSED_HAT_MIDI: int = 42
_RNB_OPEN_HAT_MIDI: int = 46

# Tier-scaled base velocities (jittered +/- 3 per note).
_TIER_RHODES_VEL: dict[int, int] = {1: 70, 2: 73, 3: 76, 4: 79, 5: 82}
_TIER_BASS_VEL: dict[int, int] = {1: 88, 2: 91, 3: 94, 4: 97, 5: 100}
_TIER_KICK_VEL: dict[int, int] = {1: 90, 2: 95, 3: 100, 4: 104, 5: 108}
_TIER_SNARE_VEL: dict[int, int] = {1: 78, 2: 83, 3: 87, 4: 91, 5: 95}
_TIER_GHOST_SNARE_VEL: dict[int, int] = {1: 42, 2: 45, 3: 48, 4: 52, 5: 55}
_TIER_CLOSED_HAT_VEL: dict[int, int] = {1: 55, 2: 60, 3: 65, 4: 69, 5: 72}
_TIER_OPEN_HAT_VEL: dict[int, int] = {1: 68, 2: 72, 3: 77, 4: 81, 5: 85}

# Progression bank in A minor. Seed selects one progression per segment.
_PROGRESSIONS: list[list[str]] = [
    ["Am9", "Dm9", "G13", "Cmaj7"],
    ["Am7", "Fmaj7", "Cmaj9", "G7"],
    ["Am7", "Em7", "Fmaj7", "G7sus4"],
    ["Am(add9)", "Dm7", "Fmaj9", "E7#9"],
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass
class RnbSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    seed: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp_velocity(base: int, rng: random.Random) -> int:
    """Apply small humanization jitter and clamp to legal MIDI velocity range."""
    return max(1, min(127, base + rng.randint(-3, 3)))


def _resolve_spec(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> RnbSpec:
    """Clamp inputs to R&B band and infer tier from nearest tier tempo."""
    clamped_bpm = max(RNB_TEMPO_MIN_BPM, min(RNB_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    clamped_density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))
    bars = max(1, int(duration_bars))
    return RnbSpec(
        tempo_bpm=clamped_bpm,
        density=clamped_density,
        duration_bars=bars,
        tier=tier,
        seed=seed,
    )


def _root_midi_for_symbol(symbol: str) -> int:
    """Return a sub-bass-friendly root MIDI for each chord symbol in A-minor space."""
    root_map = {
        "Am9": 33,
        "Am7": 33,
        "Am(add9)": 33,
        "Dm9": 38,
        "Dm7": 38,
        "Em7": 40,
        "E7#9": 40,
        "Fmaj7": 41,
        "Fmaj9": 41,
        "G13": 43,
        "G7": 43,
        "G7sus4": 43,
        "Cmaj7": 36,
        "Cmaj9": 36,
    }
    if symbol not in root_map:
        raise ValueError(f"Unsupported R&B chord symbol: {symbol!r}")
    return root_map[symbol]


def _chord_pitches_for_symbol(symbol: str) -> Sequence[int]:
    """Return voiced extended-chord tones for Rhodes in the C4-B5 zone."""
    voiced = {
        "Am9": [57, 60, 64, 67, 71],
        "Dm9": [62, 65, 69, 72, 76],
        "G13": [55, 59, 62, 65, 76],
        "Cmaj7": [60, 64, 67, 71],
        "Am7": [57, 60, 64, 67],
        "Fmaj7": [53, 57, 60, 64],
        "Cmaj9": [60, 64, 67, 71, 74],
        "G7": [55, 59, 62, 65],
        "Em7": [52, 55, 59, 62],
        "G7sus4": [55, 60, 62, 65],
        "Am(add9)": [57, 60, 64, 71],
        "Dm7": [62, 65, 69, 72],
        "Fmaj9": [53, 57, 60, 64, 67],
        "E7#9": [52, 56, 59, 62, 67],
    }
    if symbol not in voiced:
        raise ValueError(f"Unsupported R&B chord symbol: {symbol!r}")
    return voiced[symbol]


def _rhodes_stab_offsets(density: float) -> list[float]:
    """Compute per-bar stab timing on a 16th grid."""
    offsets = [0.0, 2.0]  # beats 1 and 3
    if density > 0.8:
        offsets.append(2.25)  # e of 3
    if density > 0.6:
        offsets.append(3.75)  # 16th before next bar
    return sorted(offsets)


def _append_rhodes_bar(
    rhodes_part: stream.Part,
    symbol: str,
    bar_offset: float,
    tier: int,
    density: float,
    rng: random.Random,
) -> None:
    """Insert Rhodes chord stabs for one bar."""
    chord_tones = _chord_pitches_for_symbol(symbol)
    stab_offsets = _rhodes_stab_offsets(density)

    for offs in stab_offsets:
        dur_beats = 0.75 if offs in (0.0, 2.0) else 0.5
        vel = _clamp_velocity(_TIER_RHODES_VEL[tier], rng)
        ch = chord.Chord(chord_tones)
        ch.duration = duration.Duration(dur_beats)
        ch.volume.velocity = vel
        rhodes_part.insert(bar_offset + offs, ch)


def _append_bass_bar(
    bass_part: stream.Part,
    symbol: str,
    bar_offset: float,
    tier: int,
    density: float,
    rng: random.Random,
) -> None:
    """Insert sub-bass pattern for one bar."""
    root = _root_midi_for_symbol(symbol)
    fifth = root + 7

    root_note = note.Note()
    root_note.pitch.midi = root
    root_note.duration = duration.Duration(2.0)
    root_note.volume.velocity = _clamp_velocity(_TIER_BASS_VEL[tier], rng)
    bass_part.insert(bar_offset + 0.0, root_note)

    if density > 0.5:
        fifth_note = note.Note()
        fifth_note.pitch.midi = fifth
        fifth_note.duration = duration.Duration(1.0)
        fifth_note.volume.velocity = _clamp_velocity(_TIER_BASS_VEL[tier] - 3, rng)
        bass_part.insert(bar_offset + 2.0, fifth_note)

    if density > 0.75:
        ornament_pitch = rng.choice([root + 3, fifth])  # b3 or 5 relative to root
        ornament = note.Note()
        ornament.pitch.midi = ornament_pitch
        ornament.duration = duration.Duration(0.25)
        ornament.volume.velocity = _clamp_velocity(_TIER_BASS_VEL[tier] - 8, rng)
        bass_part.insert(bar_offset + 3.25, ornament)


def rnb_drum_pattern(
    tier: int,
    duration_bars: int,
    density: float,
    rng: random.Random,
) -> list[tuple[float, int, float, int]]:
    """Half-time R&B drum events as (offset, midi, dur, vel)."""
    events: list[tuple[float, int, float, int]] = []

    for bar in range(duration_bars):
        base = bar * 4.0

        # Kick anchors on beats 1 and 3.
        events.append(
            (base + 0.0, _RNB_KICK_MIDI, 0.25, _clamp_velocity(_TIER_KICK_VEL[tier], rng))
        )
        events.append(
            (base + 2.0, _RNB_KICK_MIDI, 0.25, _clamp_velocity(_TIER_KICK_VEL[tier], rng))
        )

        # Snare/rimshot on beat 3 only.
        events.append(
            (base + 2.0, _RNB_SNARE_MIDI, 0.25, _clamp_velocity(_TIER_SNARE_VEL[tier], rng))
        )

        # Optional ghost snare on e of 2.
        if density > 0.85:
            events.append(
                (
                    base + 1.25,
                    _RNB_SNARE_MIDI,
                    0.125,
                    _clamp_velocity(_TIER_GHOST_SNARE_VEL[tier], rng),
                )
            )

        # Closed hat ladder: 8ths for tiers 1-2, 16ths for tiers 3-5.
        hat_step = 0.5 if tier <= 2 else 0.25
        n_hats = int(4.0 / hat_step)
        for i in range(n_hats):
            events.append(
                (
                    base + i * hat_step,
                    _RNB_CLOSED_HAT_MIDI,
                    0.125 if hat_step == 0.25 else 0.2,
                    _clamp_velocity(_TIER_CLOSED_HAT_VEL[tier], rng),
                )
            )

        # Open hat on and-of-4 every 2nd bar when density is high enough.
        if density > 0.7 and ((bar + 1) % 2 == 0):
            events.append(
                (
                    base + 3.5,
                    _RNB_OPEN_HAT_MIDI,
                    0.25,
                    _clamp_velocity(_TIER_OPEN_HAT_VEL[tier], rng),
                )
            )

        # Very soft pickup kick ghosts at bar 4 and 8.
        if density > 0.9 and bar in (3, 7):
            events.append((base + 3.5, _RNB_KICK_MIDI, 0.125, _clamp_velocity(58, rng)))

    return events


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------


def generate_rnb_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int = 8,
    seed: int = 7001,
) -> music21.stream.Score:
    """Generate an R&B segment as a music21 Score."""
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    rng = random.Random(spec.seed)
    progression = list(rng.choice(_PROGRESSIONS))

    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, key.Key("A", "minor"))

    # Part 0: sub-bass (Synth Bass 1, GM program 39).
    bass_part = stream.Part(id="rnb_sub_bass")
    bass_inst = instrument.Instrument()
    bass_inst.midiProgram = 39
    bass_part.insert(0, bass_inst)

    # Part 1: Rhodes electric piano chords (GM program 4).
    rhodes_part = stream.Part(id="rnb_rhodes")
    rhodes_inst = instrument.Instrument()
    rhodes_inst.midiProgram = 4
    rhodes_part.insert(0, rhodes_inst)

    # Part 2: half-time R&B drums on channel 10.
    drum_part = stream.Part(id="rnb_drums")
    drum_inst = instrument.Percussion()
    drum_inst.midiChannel = 9
    drum_part.insert(0, drum_inst)

    for bar in range(spec.duration_bars):
        bar_offset = bar * 4.0
        symbol = progression[bar % len(progression)]
        _append_rhodes_bar(rhodes_part, symbol, bar_offset, spec.tier, spec.density, rng)
        _append_bass_bar(bass_part, symbol, bar_offset, spec.tier, spec.density, rng)

    drum_events = rnb_drum_pattern(spec.tier, spec.duration_bars, spec.density, rng)
    for offs, midi_pitch, dur_beats, vel in drum_events:
        n = note.Note()
        n.pitch.midi = midi_pitch
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        drum_part.insert(offs, n)

    score.insert(0, bass_part)
    score.insert(0, rhodes_part)
    score.insert(0, drum_part)
    return score


if __name__ == "__main__":
    score = generate_rnb_segment(
        tempo_bpm=_TIER_TEMPO[3],
        density=_TIER_DENSITY_FLOOR[3],
        duration_bars=8,
        seed=7001,
    )
    out_path = Path("/tmp/rnb_cell_smoke.mid")
    score.write("midi", fp=str(out_path))

    notes = list(score.recurse().notes)
    note_count = len(notes)
    assert score is not None and note_count > 20, f"empty/too-thin R&B output (notes={note_count})"

    print(f"wrote {out_path}; notes={note_count} duration={score.highestTime:.2f}s")
    print("Am-based, 4 chords x 2 iterations")
