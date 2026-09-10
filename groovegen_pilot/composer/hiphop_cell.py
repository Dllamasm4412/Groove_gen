"""
hiphop_cell_v4.py -- Hip-hop-family generator for GrooveGen (Still D.R.E. /
Remember the Name idiom).

Idiom and scope
---------------
Stark, minor-key, single-note stabbing ostinato hip-hop in the exact frame of
Dr. Dre "Still D.R.E." (2001, F#m, ~93 BPM) and Fort Minor "Remember the Name"
(The Rising Tied, F#m, ~87 BPM).

The defining features of that sound -- and the ones v3 did NOT capture -- are:
  1. A repeating SINGLE-NOTE MELODIC OSTINATO in the upper register, not a
     triadic arpeggio. Think the 9-note Still D.R.E. hook and the martial
     staccato piano of Remember the Name.
  2. NO chord progression movement. Both tracks pedal on the tonic minor for
     the entire loop. Harmony is implied by the ostinato's scale-degree
     content, not by a chord cycle.
  3. LEFT-HAND OCTAVE STABS on beat 1 and beat 3 -- the anchor of both tracks.
  4. STACCATO articulation everywhere. Piano notes are short (16th length),
     not sustained.
  5. Straight-16th boom-bap DRUMS with kicks that push into the snare
     (double-kick pickups into beats 2 and 4), not the whole-note push v3
     used.
  6. A single-note LEAD stab that DOUBLES the piano hook one octave up, so
     the ostinato reads as a "big" unison motif -- exactly the Still D.R.E.
     synth-doubling-piano effect.

Why this file replaces v3
-------------------------
v3 played a triadic arpeggio ("root - 5th - octave - 3rd - 5th - root") over
a rotating progression, with a whining pentatonic call-and-response lead. That
is a G-funk / Xxplosive sound, not a Still D.R.E. sound. This v4 collapses
the piano hook to a single melodic line pedaled on the tonic minor, keeps
the lead as a unison doubling of that line, and locks the drum bed into the
martial variant used by both reference tracks.

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'hiphop'.

Returns a `music21.stream.Score` with:
  Part 0: Left-hand octave-stab bass (Electric Bass placeholder)
  Part 1: Right-hand single-note piano ostinato (Acoustic Piano, staccato)
  Part 2: Boom-bap drums (channel 10)
  Part 3: Unison synth-piano DOUBLING lead one octave above the piano hook
          (Sampler placeholder routed to a bright piano / synth-piano patch)
  Part 4 (tier >= 4): Sub-bass doubling the LH octave stabs
  Part 5 (tier == 5): Warm string / pad underlay on the tonic minor

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

# Widened the low end to hit Remember the Name (87 BPM) as well as Still D.R.E.
# (93 BPM), keeping the whole family inside one identifiable pocket.
HIPHOP_TEMPO_MIN_BPM: int = 85
HIPHOP_TEMPO_MAX_BPM: int = 96

# Tier -> tempo. Lower tiers sit closer to Remember the Name; upper tiers sit
# closer to Still D.R.E.
_TIER_TEMPO: dict[int, int] = {1: 85, 2: 87, 3: 90, 4: 93, 5: 96}

# Density floor per tier. Density drives ornament count on the ostinato and
# ghosted drum activity, NOT the ostinato's core shape.
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90, 5: 1.00}

# Voicing kind is now the single-note stabbing ostinato at every tier.
_TIER_VOICING_KIND: dict[int, str] = {
    1: "single_note_stab_ostinato",
    2: "single_note_stab_ostinato",
    3: "single_note_stab_ostinato",
    4: "single_note_stab_ostinato",
    5: "single_note_stab_ostinato",
}

# GM percussion note numbers (channel 10).
_HIPHOP_KICK_MIDI: int = 36
_HIPHOP_SNARE_MIDI: int = 38
_HIPHOP_CLAP_MIDI: int = 39
_HIPHOP_RIM_MIDI: int = 37
_HIPHOP_HAT_MIDI: int = 42
_HIPHOP_OPEN_HAT_MIDI: int = 46

# Tier-scaled velocity constants. Punchy West Coast weight.
_TIER_KICK_VEL: dict[int, int] = {1: 100, 2: 104, 3: 108, 4: 112, 5: 115}
_TIER_SNARE_VEL: dict[int, int] = {1: 96, 2: 100, 3: 104, 4: 108, 5: 112}
_TIER_CLAP_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 78, 5: 90}
_TIER_HAT_VEL: dict[int, int] = {1: 60, 2: 64, 3: 68, 4: 72, 5: 76}
_TIER_OPEN_HAT_VEL: dict[int, int] = {1: 0, 2: 0, 3: 72, 4: 80, 5: 86}
_TIER_RIM_GHOST_VEL: dict[int, int] = {1: 0, 2: 0, 3: 38, 4: 42, 5: 46}
_TIER_PIANO_VEL: dict[int, int] = {1: 82, 2: 88, 3: 94, 4: 100, 5: 105}
_TIER_LH_VEL: dict[int, int] = {1: 80, 2: 84, 3: 88, 4: 92, 5: 96}
_TIER_LEAD_VEL: dict[int, int] = {1: 60, 2: 68, 3: 76, 4: 84, 5: 92}
_TIER_BASS_VEL_BASE: dict[int, int] = {1: 92, 2: 96, 3: 100, 4: 104, 5: 108}
_TIER_SUB_BASS_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 80, 5: 86}
_TIER_PAD_VEL: dict[int, int] = {1: 0, 2: 0, 3: 0, 4: 0, 5: 45}

# Straight-time; the martial feel comes from staccato + kick placement, not swing.
_TIER_SWING_RATIO: dict[int, float] = {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0, 5: 0.0}

# Progressions preserved for metadata compatibility but SINGLE-CHORD pedal is
# used at generation time to match the reference tracks. The list is retained
# so downstream tooling (evaluation, dashboards) does not break on missing keys.
_PROGRESSIONS: list[list[str]] = [
    ["vi", "vi", "vi", "vi"],  # tonic-minor pedal, Still D.R.E. / Remember the Name
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
# Scale / key helpers
# ---------------------------------------------------------------------------

# Natural minor scale, semitones from the minor tonic.
_NATURAL_MINOR: tuple[int, ...] = (0, 2, 3, 5, 7, 8, 10)


def _key_root_midi(key_root_name: str) -> int:
    """Return the RELATIVE-MAJOR root as MIDI in the C3-B3 register."""
    p = pitch.Pitch(key_root_name + "3")
    return int(p.midi)


def _minor_tonic_midi_from_rel_major(rel_major_midi: int) -> int:
    """Convert the notated relative-major root to the actual minor tonic MIDI.

    GrooveGen notates keys in relative major. The tonic minor sits a minor
    third BELOW the relative-major root (e.g. C major <-> A minor).
    """
    return rel_major_midi - 3


def _resolve_spec(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> HiphopSpec:
    """Clamp inputs into the identity band and derive tier."""
    clamped_bpm = max(HIPHOP_TEMPO_MIN_BPM, min(HIPHOP_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    clamped_density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))

    rng = random.Random(seed)
    # Keys chosen so the derived minor tonic sits near F#m / Am / Em / Dm --
    # the pocket the reference tracks live in.
    #   A rel-major -> F#m   (Still D.R.E.)
    #   C rel-major -> Am
    #   G rel-major -> Em
    #   F rel-major -> Dm
    #   D rel-major -> Bm
    key_root = rng.choice(["A", "C", "G", "F", "D"])

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
    """Return the single tonic-minor pedal used by both reference tracks.

    Kept as a function for API compatibility with prior versions; seed is
    ignored because the pedal is fixed.
    """
    _ = seed
    return list(_PROGRESSIONS[0])


def _tier_drum_flags(tier: int) -> dict[str, bool]:
    """Compute tier-enabled drum/arrangement elements for metadata routing."""
    return {
        "kick": True,
        "snare": True,
        "clap": tier >= 4,
        "hat": True,
        "open_hat": tier >= 3,
        "rim_ghost": tier >= 3,
        "sub_bass": tier >= 4,
        "pad": tier == 5,
        "lead": True,
    }


# ---------------------------------------------------------------------------
# Drum bed  --  martial boom-bap shared by Still D.R.E. and Remember the Name
# ---------------------------------------------------------------------------


def hiphop_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Straight-time martial boom-bap.

    Slot grid: 16 sixteenth-notes per bar (slot i -> beat i * 0.25).

    Bitmap:
      Kick   : slots 0 and 10 always. Tier 3+ adds a 16th-pickup kick on
               slot 11 (a-of-3) that pushes into the beat-4 snare -- the
               Remember the Name double-kick feel.
               Tier 1 keeps only slot 0 for a sparse read.
      Snare  : slots 4 and 12  ->  beats 2 and 4.
               Tier >= 4 layers a clap on top of the snare.
      Hat    : quarters (tier 1), 8ths (tier 2), 16ths (tier 3+).
      OpenHt : slot 14 (and-of-4) at tier 3+.
      Rim    : slots 3 and 11 at tier 3+ for extra grid density
               (dropped where a pickup kick is already there).

    Deterministic bitmap; RNG only jitters velocity.
    """
    rng = random.Random(seed ^ 0xD2E1)
    events: list[tuple[float, int, float, int]] = []

    def _v(base: int, spread: int = 3) -> int:
        return max(1, min(120, base + rng.randint(-spread, spread)))

    for bar in range(duration_bars):
        base = bar * 4.0

        # Hat ladder.
        if tier == 1:
            hat_slots: tuple[int, ...] = (0, 4, 8, 12)
        elif tier == 2:
            hat_slots = tuple(range(0, 16, 2))
        else:
            hat_slots = tuple(range(16))

        for slot in hat_slots:
            offset = base + slot * 0.25
            if tier >= 3 and slot == 14:
                events.append(
                    (offset, _HIPHOP_OPEN_HAT_MIDI, 0.25, _v(_TIER_OPEN_HAT_VEL[tier], 2))
                )
            else:
                events.append(
                    (offset, _HIPHOP_HAT_MIDI, 0.125, _v(_TIER_HAT_VEL[tier], 2))
                )

        # Kick pattern.
        kick_slots: list[int] = [0] if tier == 1 else [0, 10]
        for slot in kick_slots:
            events.append(
                (base + slot * 0.25, _HIPHOP_KICK_MIDI, 0.25, _v(_TIER_KICK_VEL[tier], 2))
            )
        # Pickup kick pushing into beat 4 for tier 3+ (Remember the Name feel).
        if tier >= 3:
            events.append(
                (base + 11 * 0.25, _HIPHOP_KICK_MIDI, 0.125, _v(_TIER_KICK_VEL[tier] - 6, 2))
            )

        # Snare on 2 and 4, with clap layer at tier 4+.
        for slot in (4, 12):
            events.append(
                (base + slot * 0.25, _HIPHOP_SNARE_MIDI, 0.25, _v(_TIER_SNARE_VEL[tier], 2))
            )
            if tier >= 4:
                events.append(
                    (base + slot * 0.25, _HIPHOP_CLAP_MIDI, 0.25, _v(_TIER_CLAP_VEL[tier], 2))
                )

        # Rim ghost on slot 3 only (slot 11 is now the pickup kick).
        if tier >= 3:
            events.append(
                (base + 3 * 0.25, _HIPHOP_RIM_MIDI, 0.125, _v(_TIER_RIM_GHOST_VEL[tier], 2))
            )

    return events


# ---------------------------------------------------------------------------
# Piano ostinato  --  single-note stabbing hook (the identity)
# ---------------------------------------------------------------------------

# Right-hand hook expressed as (slot, minor_scale_degree_index, octave_offset).
# Scale degrees are 0..6 into the natural minor built on the minor tonic
# (i.e. 0 = tonic, 2 = minor third, 4 = fifth, 6 = minor seventh).
# Octave offset is added on top of the minor-tonic root MIDI.
#
# This is a 2-bar phrase (slots 0..31 across two bars of 16 sixteenth-notes)
# that echoes the shape of both reference tracks: a stark, angular contour
# that outlines i - v - i - b7 - v - i - iv - i and repeats.
#
# Slots chosen to fall on strong 8th positions with a couple of 16th pickups.
_PIANO_RH_TWO_BAR: tuple[tuple[int, int, int], ...] = (
    # Bar 0
    (0,  0, 24),   # tonic, 2 octaves above minor root
    (3,  4, 24),   # fifth  (16th pickup)
    (4,  0, 24),   # tonic on beat 2
    (7,  6, 24),   # minor 7 (pickup)
    (8,  4, 24),   # fifth on beat 3
    (12, 3, 24),   # fourth on beat 4
    (14, 0, 24),   # tonic (and-of-4)
    # Bar 1  --  answer phrase, drops slightly, closes on tonic
    (16, 2, 24),   # minor third
    (19, 4, 24),   # fifth (pickup)
    (20, 0, 24),   # tonic on beat 2
    (23, 6, 24),   # minor 7 (pickup)
    (24, 4, 24),   # fifth on beat 3
    (28, 2, 24),   # minor third on beat 4
    (30, 0, 24),   # tonic (and-of-4), closes the phrase
)


# Left-hand octave stabs on beats 1 and 3 -- the anchor of both tracks.
_PIANO_LH_TWO_BAR: tuple[tuple[int, int, int], ...] = (
    # (slot_in_two_bar, scale_degree, octave_offset)
    (0,  0, 0),    # tonic, low
    (8,  0, 0),    # tonic on beat 3
    (16, 0, 0),
    (24, 0, 0),
)


def _build_piano_events(
    minor_tonic_midi: int,
    tier: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> tuple[
    list[tuple[float, int, float, int]],  # right hand
    list[tuple[float, int, float, int]],  # left hand
]:
    """Build the staccato single-note ostinato + LH octave stabs.

    The 2-bar phrase repeats for the whole segment. Density controls whether
    the 16th-note pickup notes at slots 3/7/19/23 are dropped (low tier =
    sparser, tier 5 = every note).
    """
    rng = random.Random(seed ^ 0x1F5A)
    rh: list[tuple[float, int, float, int]] = []
    lh: list[tuple[float, int, float, int]] = []
    base_vel_rh = _TIER_PIANO_VEL[tier]
    base_vel_lh = _TIER_LH_VEL[tier]

    # Bright staccato: fixed 16th-note length (0.25 beats).
    RH_DUR = 0.25
    LH_DUR = 0.25  # short octave stab, not a sustain

    pickup_slots = {3, 7, 19, 23}

    for phrase_start in range(0, duration_bars, 2):
        abs_bar = phrase_start * 4.0
        # Handle the tail bar if duration_bars is odd -- only render the
        # first-bar half of the phrase.
        max_phrase_beats = min(8.0, (duration_bars - phrase_start) * 4.0)

        # Right hand.
        for slot, deg_idx, oct_offset in _PIANO_RH_TWO_BAR:
            phrase_beat = slot * 0.25
            if phrase_beat >= max_phrase_beats:
                continue
            # Density thinning of the 16th pickups.
            if slot in pickup_slots and density < 0.75:
                continue
            semi = _NATURAL_MINOR[deg_idx]
            pitch_midi = minor_tonic_midi + oct_offset + semi
            # Keep RH in bright piano register (C5..C7).
            while pitch_midi < 72:
                pitch_midi += 12
            while pitch_midi > 96:
                pitch_midi -= 12
            vel = max(1, min(120, base_vel_rh + rng.randint(-3, 3)))
            rh.append((abs_bar + phrase_beat, pitch_midi, RH_DUR, vel))

        # Left hand octaves.
        for slot, deg_idx, oct_offset in _PIANO_LH_TWO_BAR:
            phrase_beat = slot * 0.25
            if phrase_beat >= max_phrase_beats:
                continue
            semi = _NATURAL_MINOR[deg_idx]
            lo = minor_tonic_midi + oct_offset + semi
            # Keep LH in the C2..C4 region for a chesty stab.
            while lo < 36:
                lo += 12
            while lo > 55:
                lo -= 12
            hi = lo + 12
            vel = max(1, min(120, base_vel_lh + rng.randint(-2, 2)))
            lh.append((abs_bar + phrase_beat, lo, LH_DUR, vel))
            lh.append((abs_bar + phrase_beat, hi, LH_DUR, max(1, min(120, vel - 4))))

    return rh, lh


# ---------------------------------------------------------------------------
# Lead  --  unison doubling of the piano ostinato, one octave up
# ---------------------------------------------------------------------------


def _build_lead_events_from_piano(
    rh_events: Sequence[tuple[float, int, float, int]],
    tier: int,
    density: float,
) -> list[tuple[float, int, float, int]]:
    """Double the RH piano ostinato one octave above at attenuated velocity.

    This is what gives Still D.R.E. its big unison-hook read. Tier 1 skips the
    doubling entirely to keep low-energy segments piano-only.
    """
    if tier == 1:
        return []

    events: list[tuple[float, int, float, int]] = []
    base_vel = _TIER_LEAD_VEL[tier]

    # Density gate: below 0.6, drop the 16th-note pickups from the double.
    for offs, p_midi, dur, _vel in rh_events:
        beat_in_bar = offs - int(offs // 4.0) * 4.0
        is_pickup = abs(beat_in_bar - round(beat_in_bar * 2) / 2) > 1e-6
        if density < 0.6 and is_pickup:
            continue
        doubled = p_midi + 12
        while doubled > 96:
            doubled -= 12
        vel = max(1, min(120, base_vel))
        events.append((offs, doubled, dur, vel))

    return events


# ---------------------------------------------------------------------------
# Bass  --  follows the LH octave stabs, adds simple movement at tier 3+
# ---------------------------------------------------------------------------


def _build_bass_events(
    minor_tonic_midi: int,
    tier: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> tuple[
    list[tuple[float, int, float, int]],  # bass
    list[tuple[float, int, float, int]],  # sub-bass
]:
    """Bass reinforces the LH tonic stab on beats 1 and 3.

    Tier 3+ adds an approach tone (b7) on the "and of 4" going into the next
    bar's downbeat. Tier 4+ mirrors the whole pattern one octave lower on a
    dedicated sub-bass part.
    """
    rng = random.Random(seed ^ 0xBA55)
    bass: list[tuple[float, int, float, int]] = []
    sub: list[tuple[float, int, float, int]] = []
    base_vel = _TIER_BASS_VEL_BASE[tier]
    sub_base_vel = _TIER_SUB_BASS_VEL[tier]

    # Bass in a low register E1..E3.
    tonic = minor_tonic_midi
    while tonic > 43:
        tonic -= 12
    while tonic < 28:
        tonic += 12

    approach = tonic - 2  # whole step below tonic (b7 approach)
    while approach < 28:
        approach += 12
    while approach > 43:
        approach -= 12

    for bar in range(duration_bars):
        base = bar * 4.0
        # Beat 1 hit.
        vel1 = max(1, min(120, base_vel + rng.randint(-2, 2)))
        bass.append((base + 0.0, tonic, 0.5, vel1))
        # Beat 3 hit.
        vel3 = max(1, min(120, base_vel + rng.randint(-2, 2)))
        bass.append((base + 2.0, tonic, 0.5, vel3))

        # Density-gated ghost on the "and of 2" for movement.
        if density >= 0.75:
            vel_g = max(1, min(120, base_vel - 8))
            bass.append((base + 1.5, tonic, 0.25, vel_g))

        # Approach into next bar at tier 3+.
        if tier >= 3 and bar < duration_bars - 1:
            bass.append((base + 3.75, approach, 0.25, max(1, min(120, base_vel - 4))))

        # Sub-bass mirror at tier 4+.
        if tier >= 4:
            sub_pitch = tonic - 12
            while sub_pitch < 24:
                sub_pitch += 12
            while sub_pitch > 31:
                sub_pitch += 0  # already in range; sub sits at C1..G1
                break
            sv1 = max(1, min(120, sub_base_vel + rng.randint(-2, 2)))
            sub.append((base + 0.0, sub_pitch, 0.5, sv1))
            sv3 = max(1, min(120, sub_base_vel + rng.randint(-2, 2)))
            sub.append((base + 2.0, sub_pitch, 0.5, sv3))

    return bass, sub


# ---------------------------------------------------------------------------
# Pad  --  tier 5 warm string underlay on the tonic minor
# ---------------------------------------------------------------------------


def _build_pad_events(
    minor_tonic_midi: int,
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Sustained tonic-minor triad in the upper-mid register, one chord per bar."""
    rng = random.Random(seed ^ 0x9AD1)
    events: list[tuple[float, int, float, int]] = []

    # Build minor triad tones from tonic.
    root = minor_tonic_midi
    third = root + 3
    fifth = root + 7
    # Move into the pad register (G4..G5-ish).
    while root < 67:
        root += 12
        third += 12
        fifth += 12
    while root > 79:
        root -= 12
        third -= 12
        fifth -= 12

    for bar in range(duration_bars):
        vel = max(35, min(50, _TIER_PAD_VEL[tier] + rng.randint(-3, 3)))
        for p_midi in (root, third, fifth):
            events.append((bar * 4.0, p_midi, 4.0, vel))

    return events


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
    """Generate a Still D.R.E. / Remember the Name style hip-hop segment."""
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    if add_warm_pad is not None:
        spec.add_warm_pad = add_warm_pad

    progression = _select_progression(spec.seed)
    rel_major_midi = _key_root_midi(spec.key_root)
    minor_tonic_midi = _minor_tonic_midi_from_rel_major(rel_major_midi)

    # ---- Build the Score -------------------------------------------------
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    score.insert(0, key.Key(spec.key_root))

    # Part 0: Bass.
    bass_part = stream.Part(id="hiphop_bass")
    bass_part.insert(0, instrument.ElectricBass())

    # Part 1: Piano (LH + RH).
    piano_part = stream.Part(id="hiphop_piano")
    piano_part.insert(0, instrument.Piano())

    # Part 2: Drums.
    drum_part = stream.Part(id="hiphop_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9
    drum_part.insert(0, drum_kit)

    # Part 3: Unison synth-piano doubling lead.
    lead_part = stream.Part(id="hiphop_lead")
    lead_inst = instrument.Sampler()
    # GM 1 (0-indexed 0) = Acoustic Grand for a bright doubling read. The
    # renderer is free to route this to a brighter synth-piano / bell patch.
    lead_inst.midiProgram = 0
    lead_part.insert(0, lead_inst)

    # Part 4 (tier >= 4): Sub-bass.
    sub_bass_part: stream.Part | None = None
    if spec.tier >= 4:
        sub_bass_part = stream.Part(id="hiphop_sub_bass")
        sub_bass_part.insert(0, instrument.Sampler())

    # Part 5 (tier == 5): Warm pad.
    pad_part: stream.Part | None = None
    if spec.add_warm_pad:
        pad_part = stream.Part(id="hiphop_pad")
        pad_part.insert(0, instrument.Sampler())

    # ---- Piano events ---------------------------------------------------
    rh_events, lh_events = _build_piano_events(
        minor_tonic_midi=minor_tonic_midi,
        tier=spec.tier,
        density=spec.density,
        duration_bars=spec.duration_bars,
        seed=spec.seed,
    )
    for offs, p_midi, dur_beats, vel in rh_events + lh_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        piano_part.insert(offs, n)

    # ---- Lead: double the RH one octave up ------------------------------
    lead_events = _build_lead_events_from_piano(
        rh_events=rh_events,
        tier=spec.tier,
        density=spec.density,
    )
    for offs, p_midi, dur_beats, vel in lead_events:
        n = note.Note(p_midi)
        n.duration = duration.Duration(dur_beats)
        n.volume.velocity = vel
        lead_part.insert(offs, n)

    # ---- Bass + sub-bass ------------------------------------------------
    bass_events, sub_bass_events = _build_bass_events(
        minor_tonic_midi=minor_tonic_midi,
        tier=spec.tier,
        density=spec.density,
        duration_bars=spec.duration_bars,
        seed=spec.seed,
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

    # ---- Pad (tier 5) ---------------------------------------------------
    if pad_part is not None:
        for offs, p_midi, dur_beats, vel in _build_pad_events(
            minor_tonic_midi=minor_tonic_midi,
            tier=spec.tier,
            duration_bars=spec.duration_bars,
            seed=spec.seed,
        ):
            n = note.Note(p_midi)
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            pad_part.insert(offs, n)

    # ---- Drums ----------------------------------------------------------
    for offs, p_midi, dur_beats, vel in hiphop_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xD2E1,
    ):
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
    score.insert(0, lead_part)
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
    md.composer = "GrooveGen.hiphop_cell.v4_stilldre_rtn"
    md.groovegen_hiphop_spec = {
        "family": "hiphop",
        "subfamily": "stilldre_rtn",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "voicing_kind": spec.voicing_kind,
        "riff_style": "single_note_stab_ostinato_v4",
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
            "lead": drum_flags["lead"],
        },
        "warm_pad_enabled": spec.add_warm_pad,
        "bass_style": "tonic_octave_stab_with_b7_approach",
        "lead_style": "octave_doubling_of_piano_ostinato",
        "seed": spec.seed,
        "generator_version": "hiphop_cell.v4_stilldre_rtn",
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

    out_dir = os.environ.get("HIPHOP_OUT_DIR", "./hiphop_cell_v4_smoke")
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
