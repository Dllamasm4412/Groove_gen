"""
jazzhop_cell.py -- Jazz-hop-family generator for GrooveGen.

Idiom and scope
---------------
Instrumental jazz-hop / jazz-influenced boom-bap, ~82-95 BPM. Minor-leaning
Rhodes harmony with shell and rootless voicings, walking upright bass, and
harder boom-bap drums with triplet-swing hats in upper tiers.

Stress-tests the shared libraries by importing ONE pattern function and TWO
voicing functions from `patterns.py` and `voicings.py`. The only jazz-hop-specific
logic in this file is:
  1. The tier -> tempo / density / voicing mapping (jazz-hop-specific ramp).
  2. The boom-bap drum bitmap with tier-scaled ghosting and swung hats.
  3. The progression bank using relative-major notation for minor-leaning loops.
  4. The tier-5 warm-pad and Rhodes-fill routing.

Everything else -- walking bass and voicing constructors -- comes from shared
libraries.

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'jazzhop'.
Returns a `music21.stream.Score` with:
  Part 0: Upright bass (GM 32, Acoustic Bass)
  Part 1: Rhodes / Electric Piano comping layer
  Part 2: Boom-bap percussion (channel 10)
  Part 3 (optional, tier == 5 only): Warm sub-pad underlay (renderer routes to GM 89)

Ladder position in GrooveGen
----------------------------
Jazz-hop sits between lofi and R&B on the calm -> lofi -> jazz-hop -> R&B ->
pop -> Latin -> rock energy ramp. Tempo overlaps adjacent families, but drum
weight and swing feel make jazz-hop a separate energy step.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

from composer.patterns import bassline_walk
from composer.voicings import rootless_A_B, shell_voicing

# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

JAZZHOP_TEMPO_MIN_BPM: int = 82
JAZZHOP_TEMPO_MAX_BPM: int = 95

# Tier -> tempo. Higher tier => more energy, still inside the jazz-hop band.
_TIER_TEMPO: dict[int, int] = {1: 82, 2: 85, 3: 88, 4: 92, 5: 95}

# Density floor per tier. Tier 1 leaves air; tier 5 is near saturation.
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.15, 2: 0.30, 3: 0.50, 4: 0.70, 5: 0.90}

# Tier voicing map for the Rhodes comping layer.
_TIER_VOICING_KIND: dict[int, str] = {
    1: "shell",
    2: "shell",
    3: "shell",
    4: "rootless_A",
    5: "rootless_B",
}

# Swing enable by tier and fixed swing ratio for upper tiers.
_TIER_SWING_ENABLED: dict[int, bool] = {1: False, 2: False, 3: True, 4: True, 5: True}
_TIER_SWING_RATIO: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.33, 4: 0.33, 5: 0.33}

# GM percussion note numbers (channel 10).
_JAZZHOP_KICK_MIDI: int = 36
_JAZZHOP_SNARE_MIDI: int = 38
_JAZZHOP_GHOST_SNARE_MIDI: int = 40
_JAZZHOP_RIM_MIDI: int = 37
_JAZZHOP_HAT_MIDI: int = 42
_JAZZHOP_OPEN_HAT_MIDI: int = 46

# Tier-scaled velocity constants requested for this family.
_TIER_KICK_VEL: dict[int, int] = {1: 75, 2: 80, 3: 85, 4: 90, 5: 95}
_TIER_SNARE_VEL: dict[int, int] = {1: 70, 2: 75, 3: 80, 4: 86, 5: 90}
_TIER_GHOST_SNARE_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 32, 5: 38}
_TIER_HAT_VEL: dict[int, int] = {1: 55, 2: 58, 3: 62, 4: 66, 5: 70}
_TIER_OPEN_HAT_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 64, 5: 68}
_TIER_RIM_GHOST_VEL: dict[int, int] = {1: 0, 2: 0, 3: 52, 4: 56, 5: 60}
_TIER_RHODES_VEL: dict[int, int] = {1: 58, 2: 64, 3: 70, 4: 76, 5: 82}
_TIER_BASS_VEL_BASE: dict[int, int] = {1: 58, 2: 63, 3: 68, 4: 72, 5: 76}
_TIER_PAD_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 38}

# Jazz-hop progressions represented in RELATIVE MAJOR, following
# the same convention used by rock_cell and latin_cell:
#
# Cross-key spelling reference (relative-major -> intended minor-key sense):
#   Roman "vi"  <=> minor i     (tonic minor)
#   Roman "V"   <=> minor VII   (subtonic major)
#   Roman "IV"  <=> minor VI    (submediant major)
#   Roman "I"   <=> minor III   (mediant major)
#   Roman "ii"  <=> minor iv    (predominant)
_PROGRESSIONS: list[list[str]] = [
    ["vi", "ii", "V", "vi"],
    ["vi", "V", "vi", "V"],
    ["vi", "IV", "ii", "V"],
    ["ii", "V", "I", "vi"],
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------


@dataclass
class JazzhopSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str
    voicing_kind: str
    swing_enabled: bool
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
) -> JazzhopSpec:
    """Clamp inputs into the jazz-hop identity band and derive tier-level toggles."""
    clamped_bpm = max(JAZZHOP_TEMPO_MIN_BPM, min(JAZZHOP_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    clamped_density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))

    rng = random.Random(seed)
    key_root = rng.choice(["C", "D", "Eb", "F", "G", "Ab", "Bb"])

    return JazzhopSpec(
        tempo_bpm=clamped_bpm,
        density=clamped_density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        voicing_kind=_TIER_VOICING_KIND[tier],
        swing_enabled=_TIER_SWING_ENABLED[tier],
        add_warm_pad=(tier == 5),
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    """Select a 4-chord jazz-hop loop deterministically from the progression bank."""
    rng = random.Random(seed ^ 0x4A22)
    return list(rng.choice(_PROGRESSIONS))


def _extend_triad_to_seventh(
    triad: list[int],
    roman: str,
) -> list[int]:
    """Add a diatonic 7th to a triad so rootless voicings can be built safely.

    Rootless voicing helpers require seventh-chord material. This helper mirrors
    the established pattern used in other family cells to avoid changing shared
    harmony utilities.
    """
    if len(triad) >= 4:
        return list(triad)
    root = triad[0]
    seventh_interval = {
        "I": 11,
        "IV": 11,
        "ii": 10,
        "iii": 10,
        "vi": 10,
        "V": 10,
        "V/vi": 10,
    }.get(roman, 10)
    return sorted(list(triad) + [root + seventh_interval])


def _voice_chord_for_tier(
    voicing_kind: str,
    key_root_midi: int,
    roman: str,
) -> list[int]:
    """Build the tier-selected chord voicing for one harmonic slot.

    Tiers 1-3 keep shell voicings for focused minor color. Tiers 4-5 switch to
    rootless A/B forms to add 9th-rich color without changing the core groove.
    """
    if voicing_kind == "shell":
        return shell_voicing(
            key_root_midi=key_root_midi,
            roman=roman,
            include_root=True,
            register_low=50,
            register_high=76,
        )

    from composer.calm_cell import _build_chord_tones

    triad = _build_chord_tones(key_root_midi, roman)
    seventh_chord = _extend_triad_to_seventh(triad, roman)
    if voicing_kind == "rootless_A":
        return rootless_A_B(
            chord_tones=seventh_chord,
            form="A",
            register_low=52,
            register_high=79,
        )
    if voicing_kind == "rootless_B":
        return rootless_A_B(
            chord_tones=seventh_chord,
            form="B",
            register_low=52,
            register_high=82,
        )
    raise ValueError(f"Unknown jazzhop voicing_kind: {voicing_kind!r}")


def _rhodes_pattern_for_chord(
    chord_pitches: Sequence[int],
    chord_dur_beats: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Emit tier-specific Rhodes events for one chord span.

    Rhythm density scales by tier: sustained intro in tier 1, then short stabs
    with added syncopation in upper tiers so harmony supports the drum lift.
    """
    rng = random.Random(seed ^ 0x88D1)
    events: list[tuple[float, int, float, int]] = []
    n_bars = max(1, int(chord_dur_beats // 4.0))
    base_vel = _TIER_RHODES_VEL[tier]

    for bar in range(n_bars):
        bar_offset = bar * 4.0
        if tier == 1:
            for p_midi in chord_pitches:
                vel = max(1, min(120, base_vel + rng.randint(-3, 3)))
                events.append((bar_offset, p_midi, 4.0, vel))
            continue

        if tier == 2:
            hit_offsets = (0.0, 2.0)
        elif tier == 3:
            hit_offsets = (0.0, 2.0, 2.5)
        else:
            hit_offsets = (0.0, 2.0, 2.5, 3.5)

        for offs in hit_offsets:
            dur_beats = 1.0 if offs in (2.5, 3.5) else 1.5
            if tier == 2:
                dur_beats = 1.0
            for p_midi in chord_pitches:
                vel = max(1, min(120, base_vel + (3 if offs == 0.0 else 0) + rng.randint(-3, 3)))
                events.append((bar_offset + offs, p_midi, dur_beats, vel))

    return events


def _tier5_rhodes_fill(
    key_root_midi: int,
    roman: str,
    chord_dur_beats: float,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Create a short call-and-response Rhodes fill for tier 5 phrase endings.

    The fill appears only in selected bars (handled by caller), giving brief
    pentatonic motion without turning the bed into a continuous solo layer.
    """
    from composer.calm_cell import _build_chord_tones

    rng = random.Random(seed ^ 0xF115)
    tones = _build_chord_tones(key_root_midi, roman)
    root = tones[0]

    scale_intervals = [0, 3, 5, 7, 10]
    fill: list[tuple[float, int, float, int]] = []
    start = max(0.0, chord_dur_beats - 1.0)
    for idx in range(4):
        midi_pitch = root + 12 + scale_intervals[rng.randrange(len(scale_intervals))]
        while midi_pitch < 67:
            midi_pitch += 12
        while midi_pitch > 88:
            midi_pitch -= 12
        fill.append((start + idx * 0.25, midi_pitch, 0.20, 74 + rng.randint(-3, 3)))
    return fill


def _swing_offset_for_slot(slot: int, tier: int) -> float:
    """Return additional beat offset for swung 8th-upbeat slots in tier 3+.

    Offbeat slots 2, 6, 10, and 14 are delayed by 33% of a 16th-note to create
    the requested triplet-leaning hat feel.
    """
    if tier < 3:
        return 0.0
    if slot in (2, 6, 10, 14):
        return 0.25 * _TIER_SWING_RATIO[tier]
    return 0.0


def _tier_drum_flags(tier: int) -> dict[str, bool]:
    """Compute tier-enabled drum elements for routing and metadata."""
    return {
        "kick": True,
        "snare": True,
        "ghost_snare": tier >= 4,
        "hat": True,
        "open_hat": tier >= 4,
        "rim_ghost": tier >= 3,
        "warm_pad": tier == 5,
    }


def jazzhop_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Build the boom-bap drum bed across the full segment.

    The bitmap is fixed by tier for rhythmic identity, while deterministic
    velocity jitter prevents machine-flat dynamics.
    """
    rng = random.Random(seed ^ 0xB00B)
    events: list[tuple[float, int, float, int]] = []

    def _v(base: int, spread: int = 3) -> int:
        return max(1, min(120, base + rng.randint(-spread, spread)))

    for bar in range(duration_bars):
        base = bar * 4.0
        is_phrase_tail = (bar + 1) % 4 == 0

        # Tier 1 uses quarter-note hats; tier 2+ uses 8th-note hats.
        hat_slots = (0, 4, 8, 12) if tier == 1 else tuple(range(0, 16, 2))
        for slot in hat_slots:
            offset = base + slot * 0.25 + _swing_offset_for_slot(slot, tier)
            if tier >= 4 and slot == 14:
                events.append(
                    (offset, _JAZZHOP_OPEN_HAT_MIDI, 0.25, _v(_TIER_OPEN_HAT_VEL[tier], 2))
                )
            else:
                events.append((offset, _JAZZHOP_HAT_MIDI, 0.125, _v(_TIER_HAT_VEL[tier], 2)))

        # Kick scaling by tier.
        kick_slots = [0] if tier == 1 else [0, 6]
        for slot in kick_slots:
            offset = base + slot * 0.25 + _swing_offset_for_slot(slot, tier)
            events.append((offset, _JAZZHOP_KICK_MIDI, 0.25, _v(_TIER_KICK_VEL[tier], 2)))

        # Snare scaling by tier.
        snare_slots = [8] if tier == 1 else [4, 12]
        for slot in snare_slots:
            offset = base + slot * 0.25
            events.append((offset, _JAZZHOP_SNARE_MIDI, 0.25, _v(_TIER_SNARE_VEL[tier], 2)))

        # Rim ghosts (tier 3+): slot 3 and 11.
        if tier >= 3:
            for slot in (3, 11):
                offset = base + slot * 0.25
                events.append((offset, _JAZZHOP_RIM_MIDI, 0.125, _v(_TIER_RIM_GHOST_VEL[tier], 2)))

        # Ghost snare rolls (tier 4+): slots 13, 14, 15 on phrase-tail bars only.
        if tier >= 4 and is_phrase_tail:
            for slot in (13, 14, 15):
                offset = base + slot * 0.25 + _swing_offset_for_slot(slot, tier)
                events.append(
                    (offset, _JAZZHOP_GHOST_SNARE_MIDI, 0.125, _v(_TIER_GHOST_SNARE_VEL[tier], 2))
                )

    return events


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------


def generate_jazzhop_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
    add_warm_pad: bool | None = None,
) -> stream.Score:
    """Generate a jazz-hop segment as a music21 Score.

    Contract matches `generate_segment(genre='jazzhop', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      Part 0: Upright bass
      Part 1: Rhodes comping
      Part 2: Boom-bap drums (channel 10)
      Part 3 (optional): Warm sub-pad underlay (tier 5 only)
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

    # Part 0: Upright bass.
    bass_part = stream.Part(id="jazzhop_bass")
    bass_part.insert(0, instrument.AcousticBass())

    # Part 1: Rhodes comping.
    rhodes_part = stream.Part(id="jazzhop_rhodes")
    rhodes_part.insert(0, instrument.ElectricPiano())

    # Part 2: Drums.
    drum_part = stream.Part(id="jazzhop_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9
    drum_part.insert(0, drum_kit)

    # Part 3 (optional): Warm pad underlay at tier 5.
    pad_part: stream.Part | None = None
    if spec.add_warm_pad:
        pad_part = stream.Part(id="jazzhop_warm_pad")
        pad_part.insert(0, instrument.Sampler())

    running_offset = 0.0
    for chord_idx, roman in enumerate(progression):
        chord_seed = spec.seed + 1000 * chord_idx + 31

        voicing = _voice_chord_for_tier(
            voicing_kind=spec.voicing_kind,
            key_root_midi=key_root_midi,
            roman=roman,
        )

        # Rhodes comping events.
        rhodes_events = _rhodes_pattern_for_chord(
            chord_pitches=voicing,
            chord_dur_beats=chord_dur_beats,
            tier=spec.tier,
            seed=chord_seed,
        )
        for offs, p_midi, dur_beats, vel in rhodes_events:
            n = note.Note(p_midi)
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            rhodes_part.insert(running_offset + offs, n)

        # Tier-5 optional short Rhodes fill on bars 4 and 8 only.
        if spec.tier == 5:
            bar_start_idx = chord_idx * bars_per_chord
            for local_bar in range(bars_per_chord):
                global_bar_num = bar_start_idx + local_bar + 1
                if global_bar_num not in (4, 8):
                    continue
                fill_events = _tier5_rhodes_fill(
                    key_root_midi=key_root_midi,
                    roman=roman,
                    chord_dur_beats=4.0,
                    seed=chord_seed ^ (global_bar_num * 13),
                )
                local_offset = local_bar * 4.0
                for offs, p_midi, dur_beats, vel in fill_events:
                    n = note.Note(p_midi)
                    n.duration = duration.Duration(dur_beats)
                    n.volume.velocity = vel
                    rhodes_part.insert(running_offset + local_offset + offs, n)

        # Walking upright bass across all tiers.
        bass_events = bassline_walk(
            key_root_midi=key_root_midi,
            roman=roman,
            duration_beats=chord_dur_beats,
            seed=chord_seed ^ 0xB455,
            register_low=36,
            register_high=52,
        )
        for offs, p_midi, dur_beats, vel_lib in bass_events:
            n = note.Note(p_midi)
            n.duration = duration.Duration(min(dur_beats, 1.25))
            n.volume.velocity = max(1, min(120, _TIER_BASS_VEL_BASE[spec.tier] + (vel_lib - 60)))
            bass_part.insert(running_offset + offs, n)

        # Warm pad underlay mirrors chord tones one octave down.
        if pad_part is not None:
            pad_voicing = [p_midi - 12 for p_midi in voicing if p_midi - 12 >= 43]
            if pad_voicing:
                for p_midi in pad_voicing[:3]:
                    n = note.Note(p_midi)
                    n.duration = duration.Duration(chord_dur_beats)
                    n.volume.velocity = _TIER_PAD_VEL[spec.tier]
                    pad_part.insert(running_offset, n)

        running_offset += chord_dur_beats

    # Drums over full segment.
    drum_events = jazzhop_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xB00B,
    )
    for offs, p_midi, dur_beats, vel in drum_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        drum_part.insert(offs, n)

    # Assemble.
    score.insert(0, bass_part)
    score.insert(0, rhodes_part)
    score.insert(0, drum_part)
    if pad_part is not None:
        score.insert(0, pad_part)

    score.metadata = _make_metadata(spec, progression)
    return score


def _make_metadata(spec: JazzhopSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object with a compact provenance blob."""
    from music21 import metadata as m21meta

    md = m21meta.Metadata()
    md.title = f"jazzhop_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.jazzhop_cell.v1"
    md.groovegen_jazzhop_spec = {
        "family": "jazzhop",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "voicing_kind": spec.voicing_kind,
        "swing_enabled": spec.swing_enabled,
        "swing_ratio": _TIER_SWING_RATIO[spec.tier],
        "drum_elements": _tier_drum_flags(spec.tier),
        "warm_pad_enabled": spec.add_warm_pad,
        "seed": spec.seed,
        "generator_version": "jazzhop_cell.v1",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------


def generate_segment_jazzhop_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the composer boundary for genre == 'jazzhop'."""
    if genre != "jazzhop":
        raise ValueError(
            f"generate_segment_jazzhop_adapter received genre={genre!r}; only 'jazzhop' is supported."
        )
    return generate_jazzhop_segment(
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

    out_dir = os.environ.get("JAZZHOP_OUT_DIR", "./jazzhop_cell_v1_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_jazzhop_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=300 + tier,
        )
        fp = os.path.join(out_dir, f"jazzhop_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
