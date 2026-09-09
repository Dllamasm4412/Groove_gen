"""
hiphop_cell.py -- Hip-hop-family generator for GrooveGen.

Idiom and scope
---------------
G-funk / West Coast boom-bap, ~90-95 BPM, in a Dr. Dre 2001-era production
frame. The core identity is a repeating syncopated piano hook over minor-key
progressions, with hard straight-16th drums and sustained synth-bass support.

Stress-tests the shared libraries by importing ONE pattern function from
`patterns.py`. The only hip-hop-specific logic in this file is:
  1. The tier -> tempo / density / arrangement mapping (G-funk-specific ramp).
  2. The straight 16th boom-bap drum pattern with tier-scaled additions.
  3. The progression bank in relative-major notation for minor-key movement.
  4. The bass/sub-bass/pad orchestration around the piano riff.

Everything else -- piano-hook event generation -- comes from shared libraries.

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'hiphop'.
Returns a `music21.stream.Score` with:
  Part 0: Main synth-bass sustain layer (Electric Bass placeholder)
  Part 1: Acoustic piano hook layer (left + right hands from gfunk_piano_riff)
  Part 2: Boom-bap drums (channel 10)
  Part 3 (tier >= 4 only): Sub-bass doubling layer (Sampler placeholder)
  Part 4 (tier == 5 only): High polysynth pad root underlay (Sampler placeholder)

Ladder position in GrooveGen
----------------------------
Hip-hop (G-funk) sits above lofi and below pop/Latin/rock in perceived energy,
carried less by tempo spread and more by drum weight plus riff insistence.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

from composer.patterns import gfunk_piano_riff

# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

HIPHOP_TEMPO_MIN_BPM: int = 90
HIPHOP_TEMPO_MAX_BPM: int = 95

# Tier -> tempo. Higher tier => more energy, still inside the G-funk band.
_TIER_TEMPO: dict[int, int] = {1: 90, 2: 91, 3: 92, 4: 93, 5: 95}

# Density floor per tier. Density drives gfunk_piano_riff note activity.
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90, 5: 1.00}

# Kept for API/metadata compatibility with prior cells; this cell does not
# construct piano voicings directly.
_TIER_VOICING_KIND: dict[int, str] = {
    1: "gfunk_riff",
    2: "gfunk_riff",
    3: "gfunk_riff",
    4: "gfunk_riff",
    5: "gfunk_riff",
}

# GM percussion note numbers (channel 10).
_HIPHOP_KICK_MIDI: int = 36
_HIPHOP_SNARE_MIDI: int = 38
_HIPHOP_CLAP_MIDI: int = 39
_HIPHOP_RIM_MIDI: int = 37
_HIPHOP_HAT_MIDI: int = 42
_HIPHOP_OPEN_HAT_MIDI: int = 46

# Tier-scaled velocity constants requested for this family.
_TIER_KICK_VEL: dict[int, int] = {1: 90, 2: 94, 3: 98, 4: 102, 5: 105}
_TIER_SNARE_VEL: dict[int, int] = {1: 85, 2: 90, 3: 94, 4: 98, 5: 100}
_TIER_CLAP_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 82}
_TIER_HAT_VEL: dict[int, int] = {1: 55, 2: 60, 3: 64, 4: 67, 5: 70}
_TIER_OPEN_HAT_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 76, 5: 82}
_TIER_RIM_GHOST_VEL: dict[int, int] = {1: 0, 2: 0, 3: 36, 4: 40, 5: 45}
_TIER_RHODES_VEL: dict[int, int] = {1: 68, 2: 72, 3: 76, 4: 80, 5: 84}
_TIER_BASS_VEL_BASE: dict[int, int] = {1: 75, 2: 78, 3: 80, 4: 82, 5: 85}
_TIER_PAD_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 40}
_TIER_SUB_BASS_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 74, 5: 78}

# West Coast G-funk here is explicit straight-time, no swing.
_TIER_SWING_RATIO: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}

# Progressions represented in RELATIVE MAJOR, following the same convention
# used by rock_cell and latin_cell:
#
# Cross-key spelling reference (relative-major -> intended minor-key sense):
#   Roman "vi"  <=> minor i     (tonic minor)
#   Roman "V"   <=> minor VII   (subtonic major)
#   Roman "IV"  <=> minor VI    (submediant major)
#   Roman "I"   <=> minor III   (mediant major)
#   Roman "ii"  <=> minor iv    (predominant)
_PROGRESSIONS: list[list[str]] = [
    ["vi", "IV", "iii", "ii"],
    ["vi", "V", "vi", "IV"],
    ["vi", "IV", "V", "vi"],
    ["ii", "V", "vi", "IV"],
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass
class HiphopSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str
    voicing_kind: str
    add_warm_pad: bool
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
) -> HiphopSpec:
    """Clamp inputs into the G-funk hip-hop identity band and derive tier."""
    clamped_bpm = max(HIPHOP_TEMPO_MIN_BPM, min(HIPHOP_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    clamped_density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))

    rng = random.Random(seed)
    key_root = rng.choice(["C", "D", "Eb", "F", "G", "Ab", "Bb"])

    return HiphopSpec(
        tempo_bpm=clamped_bpm,
        density=clamped_density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        voicing_kind=_TIER_VOICING_KIND[tier],
        add_warm_pad=(tier == 5),
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    """Select a 4-chord G-funk loop deterministically from the progression bank."""
    rng = random.Random(seed ^ 0x4F11)
    return list(rng.choice(_PROGRESSIONS))


def _barwise_roots_and_symbols(
    progression: Sequence[str],
    key_root_midi: int,
    duration_bars: int,
) -> tuple[list[int], list[str]]:
    """Expand progression into per-bar roots/symbols for riff scheduling.

    The riff function consumes one root pitch and one Roman symbol per bar so
    this helper resolves bar-local harmonic context from the 4-chord loop.
    """
    from composer.calm_cell import _build_chord_tones

    chord_root_pitches: list[int] = []
    chord_symbols: list[str] = []
    for bar_idx in range(duration_bars):
        roman = progression[bar_idx % len(progression)]
        tones = _build_chord_tones(key_root_midi, roman)
        root = tones[0]
        # Keep roots in a stable low-mid register so LH and bass are consistent.
        while root < 48:
            root += 12
        while root > 59:
            root -= 12
        chord_root_pitches.append(root)
        chord_symbols.append(roman)
    return chord_root_pitches, chord_symbols


def _tier_drum_flags(tier: int) -> dict[str, bool]:
    """Compute tier-enabled drum/arrangement elements for metadata routing."""
    return {
        "kick": True,
        "snare": True,
        "clap": tier == 5,
        "hat": True,
        "open_hat": tier >= 4,
        "rim_ghost": tier >= 3,
        "sub_bass": tier >= 4,
        "pad": tier == 5,
    }


def hiphop_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Build the straight-time G-funk boom-bap drum bed.

    Per-bar bitmap is fixed by tier so groove identity is deterministic; random
    state is only used for velocity jitter.
    """
    rng = random.Random(seed ^ 0xD2E1)
    events: list[tuple[float, int, float, int]] = []

    def _v(base: int, spread: int = 3) -> int:
        return max(1, min(120, base + rng.randint(-spread, spread)))

    for bar in range(duration_bars):
        base = bar * 4.0

        # Hat ladder: quarter (tier1), 8ths (tier2), 16ths (tier3+).
        if tier == 1:
            hat_slots = (0, 4, 8, 12)
        elif tier == 2:
            hat_slots = tuple(range(0, 16, 2))
        else:
            hat_slots = tuple(range(16))

        for slot in hat_slots:
            offset = base + slot * 0.25
            if tier >= 4 and slot == 14:
                events.append(
                    (offset, _HIPHOP_OPEN_HAT_MIDI, 0.25, _v(_TIER_OPEN_HAT_VEL[tier], 2))
                )
            else:
                events.append((offset, _HIPHOP_HAT_MIDI, 0.125, _v(_TIER_HAT_VEL[tier], 2)))

        # Kick scaling.
        kick_slots = [0] if tier == 1 else [0, 6]
        for slot in kick_slots:
            events.append(
                (base + slot * 0.25, _HIPHOP_KICK_MIDI, 0.25, _v(_TIER_KICK_VEL[tier], 2))
            )

        # Snare scaling.
        snare_slots = [8] if tier == 1 else [4, 12]
        for slot in snare_slots:
            events.append(
                (base + slot * 0.25, _HIPHOP_SNARE_MIDI, 0.25, _v(_TIER_SNARE_VEL[tier], 2))
            )
            if tier == 5:
                events.append(
                    (base + slot * 0.25, _HIPHOP_CLAP_MIDI, 0.25, _v(_TIER_CLAP_VEL[tier], 2))
                )

        # Rim ghosts on e-of-2 and e-of-4 from tier 3+.
        if tier >= 3:
            for slot in (3, 11):
                events.append(
                    (base + slot * 0.25, _HIPHOP_RIM_MIDI, 0.125, _v(_TIER_RIM_GHOST_VEL[tier], 2))
                )

    return events


def _add_bass_events_for_bar(
    bass_events: list[tuple[float, int, float, int]],
    sub_bass_events: list[tuple[float, int, float, int]],
    bar_idx: int,
    lh_pitch: int,
    tier: int,
    rng: random.Random,
) -> None:
    """Add bar-level bass and optional sub-bass sustains from left-hand root.

    Main bass doubles the piano LH root one octave up and sustains the bar.
    Tier 3+ adds a one-beat octave jump on beat 4.5 every 4th bar.
    Tier 4+ mirrors rhythm in a deeper sub-bass part.
    """
    bar_offset = bar_idx * 4.0
    main_pitch = lh_pitch + 12
    main_vel = max(1, min(120, _TIER_BASS_VEL_BASE[tier] + rng.randint(-2, 2)))
    bass_events.append((bar_offset, main_pitch, 4.0, main_vel))

    if tier >= 3 and (bar_idx + 1) % 4 == 0:
        bass_events.append((bar_offset + 3.5, main_pitch + 12, 1.0, max(1, min(120, main_vel + 2))))

    if tier >= 4:
        sub_pitch = main_pitch - 12
        sub_vel = max(1, min(120, _TIER_SUB_BASS_VEL[tier] + rng.randint(-2, 2)))
        sub_bass_events.append((bar_offset, sub_pitch, 4.0, sub_vel))
        if tier >= 3 and (bar_idx + 1) % 4 == 0:
            sub_bass_events.append(
                (bar_offset + 3.5, sub_pitch + 12, 1.0, max(1, min(120, sub_vel + 2)))
            )


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------


def generate_hiphop_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
    add_warm_pad: bool | None = None,
) -> stream.Score:
    """Generate a G-funk hip-hop segment as a music21 Score.

    Contract matches `generate_segment(genre='hiphop', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      Part 0: Main synth-bass sustains
      Part 1: Acoustic piano riff (LH+RH from gfunk_piano_riff)
      Part 2: Straight boom-bap drums (channel 10)
      Part 3 (tier >= 4): Sub-bass doubling layer
      Part 4 (tier == 5): High polysynth pad root underlay
    """
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    if add_warm_pad is not None:
        spec.add_warm_pad = add_warm_pad

    progression = _select_progression(spec.seed)
    key_root_midi = _key_root_midi(spec.key_root)

    # ---- Build the Score -------------------------------------------------
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, key.Key(spec.key_root))

    # Part 0: Main synth-bass (ElectricBass placeholder for GM39 routing).
    bass_part = stream.Part(id="hiphop_bass")
    bass_part.insert(0, instrument.ElectricBass())

    # Part 1: Piano riff.
    piano_part = stream.Part(id="hiphop_piano")
    piano_part.insert(0, instrument.Piano())

    # Part 2: Drums.
    drum_part = stream.Part(id="hiphop_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9
    drum_part.insert(0, drum_kit)

    # Part 3 (optional, tier >= 4): sub-bass.
    sub_bass_part: stream.Part | None = None
    if spec.tier >= 4:
        sub_bass_part = stream.Part(id="hiphop_sub_bass")
        sub_bass_part.insert(0, instrument.Sampler())

    # Part 4 (optional, tier == 5): high pad.
    pad_part: stream.Part | None = None
    if spec.add_warm_pad:
        pad_part = stream.Part(id="hiphop_pad")
        pad_part.insert(0, instrument.Sampler())

    # Build barwise harmonic roots and call shared G-funk riff generator.
    bar_roots, bar_symbols = _barwise_roots_and_symbols(
        progression=progression,
        key_root_midi=key_root_midi,
        duration_bars=spec.duration_bars,
    )
    riff_rng = random.Random(spec.seed ^ 0x1F5A)
    left_hand_events, right_hand_events = gfunk_piano_riff(
        chord_root_pitches=bar_roots,
        chord_symbols=bar_symbols,
        key_root=spec.key_root,
        rng=riff_rng,
        density=spec.density,
    )

    # Insert piano LH + RH on one acoustic piano part.
    for offs, p_midi, dur_beats, vel in left_hand_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        piano_part.insert(offs, n)
    for offs, p_midi, dur_beats, vel in right_hand_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = max(1, min(120, round(0.5 * _TIER_RHODES_VEL[spec.tier] + 0.5 * vel)))
        piano_part.insert(offs, n)

    # Build bass/sub-bass from LH roots so harmonic anchor always matches riff.
    bass_rng = random.Random(spec.seed ^ 0xBA55)
    bass_events: list[tuple[float, int, float, int]] = []
    sub_bass_events: list[tuple[float, int, float, int]] = []
    for bar_idx in range(spec.duration_bars):
        lh_pitch = left_hand_events[bar_idx][1]
        _add_bass_events_for_bar(
            bass_events=bass_events,
            sub_bass_events=sub_bass_events,
            bar_idx=bar_idx,
            lh_pitch=lh_pitch,
            tier=spec.tier,
            rng=bass_rng,
        )

    for offs, p_midi, dur_beats, vel in bass_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        bass_part.insert(offs, n)

    if sub_bass_part is not None:
        for offs, p_midi, dur_beats, vel in sub_bass_events:
            n = note.Note(p_midi)
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            sub_bass_part.insert(offs, n)

    # Tier-5 pad: quiet sustained roots for cinematic depth.
    if pad_part is not None:
        pad_rng = random.Random(spec.seed ^ 0x9AD1)
        for bar_idx, root in enumerate(bar_roots):
            pad_pitch = root + 12
            while pad_pitch < 67:
                pad_pitch += 12
            while pad_pitch > 86:
                pad_pitch -= 12
            vel = max(35, min(45, _TIER_PAD_VEL[spec.tier] + pad_rng.randint(-3, 3)))
            n = note.Note(pad_pitch)
            n.duration = duration.Duration(4.0)
            n.volume.velocity = vel
            pad_part.insert(bar_idx * 4.0, n)

    # Drums over full segment.
    drum_events = hiphop_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xD2E1,
    )
    for offs, p_midi, dur_beats, vel in drum_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        drum_part.insert(offs, n)

    # Assemble with deterministic part order for validation.
    score.insert(0, bass_part)
    if sub_bass_part is not None:
        score.insert(0, sub_bass_part)
    score.insert(0, piano_part)
    score.insert(0, drum_part)
    if pad_part is not None:
        score.insert(0, pad_part)

    score.metadata = _make_metadata(spec, progression)
    return score


def _make_metadata(spec: HiphopSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object with a compact provenance blob."""
    from music21 import metadata as m21meta

    drum_flags = _tier_drum_flags(spec.tier)

    md = m21meta.Metadata()
    md.title = f"hiphop_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.hiphop_cell.v2_gfunk"
    md.groovegen_hiphop_spec = {
        "family": "hiphop",
        "subfamily": "gfunk",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "voicing_kind": spec.voicing_kind,
        "riff_style": "gfunk_piano_riff",
        "swing_enabled": False,
        "swing_ratio": _TIER_SWING_RATIO[spec.tier],
        "drum_pattern": {
            "kick": drum_flags["kick"],
            "snare": drum_flags["snare"],
            "clap": drum_flags["clap"],
            "hat": drum_flags["hat"],
            "open_hat": drum_flags["open_hat"],
            "rim_ghost": drum_flags["rim_ghost"],
            "sub_bass": drum_flags["sub_bass"],
            "pad": drum_flags["pad"],
        },
        "warm_pad_enabled": spec.add_warm_pad,
        "bass_octave_jump_enabled": spec.tier >= 3,
        "seed": spec.seed,
        "generator_version": "hiphop_cell.v2_gfunk",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------


def generate_segment_hiphop_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the composer boundary for genre == 'hiphop'."""
    if genre != "hiphop":
        raise ValueError(
            f"generate_segment_hiphop_adapter received genre={genre!r}; only 'hiphop' is supported."
        )
    return generate_hiphop_segment(
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

    out_dir = os.environ.get("HIPHOP_OUT_DIR", "./hiphop_cell_v1_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_hiphop_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=100 + tier,
        )
        fp = os.path.join(out_dir, f"hiphop_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
