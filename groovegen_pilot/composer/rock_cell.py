"""
rock_cell.py -- Rock-family generator for GrooveGen (classic hard rock idiom).

Idiom and scope
---------------
Classic hard rock, ~110-130 BPM, in the AC/DC / early-Zeppelin /
Queens-of-the-Stone-Age tradition. Power-chord-driven, backbeat drums, driving
8th-note bass, minor-pentatonic riff overlay at the top tier.

Stress-tests the shared libraries by importing FOUR of the six pattern
functions and TWO of the eight voicing functions from `voicings.py` and
`patterns.py`. The only rock-specific logic in this file is:
  1. The tier -> tempo / density / drive mapping (rock-specific ramp).
  2. The backbeat drum pattern (kick 1&3, snare 2&4, hats, tier-scaled crashes).
  3. The progression bank (i-VII-VI-VII, i-VI-III-VII, minor / mixolydian
     power-chord grammars).
  4. The tier-5 guitar-solo overlay routing.

Everything else -- power chord voicings, open triads, driving 8ths bass,
pentatonic riff -- comes from the shared libraries.

Rhythm-guitar articulation (v2 change)
--------------------------------------
The original v1 rhythm guitar strummed every-8th-note power chords, which
sounded like a piano hitting chords rather than a rock guitar. v2 splits
into:
  Clean tiers (1-2): sparse 8th-note strums of open-position triads. Chords
     ring; there's room to breathe. Feels like a rock intro.
  Driven tiers (3-5): palm-mute 16th-note gallop on the low strings
     (root + 5th only) with syncopated chord punches (full voicing) placed
     off the drum backbeat. Higher tiers add more chord punches and heavier
     syncopation. This is the AC/DC / early-Metallica signature articulation.

Contract
--------
Preserves the frozen `generate_segment(genre, tempo_bpm, density,
duration_bars, seed)` interface for genre == 'rock'.
Returns a `music21.stream.Score` with:
  Part 0: Electric bass (GM 34, "Electric Bass (finger)")
  Part 1: Rhythm guitar -- power chords or open triads by tier
          (GM 30, "Overdriven Guitar" at higher tiers; GM 27, "Electric Guitar
          (clean)" at lower tiers)
  Part 2: Backbeat drums (channel 10)
  Part 3 (optional, tier == 5 only): Lead guitar overlay running a minor
          pentatonic 8th-note riff (GM 30, "Overdriven Guitar")

Ladder position in GrooveGen
----------------------------
Rock sits at the top of the calm -> lofi -> R&B -> pop -> Latin -> rock energy
ramp. The controller's reference governor should not schedule a direct
transition from calm to rock -- the ladder mediates the intermediate families.

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Sequence

from music21 import duration, instrument, key, meter, note, pitch, stream, tempo

from composer.patterns import (
    driving_eighths_bass,
    pentatonic_riff,
)
from composer.voicings import (
    open_position_triad,
    power_chord,
)


# ---------------------------------------------------------------------------
# Public config
# ---------------------------------------------------------------------------

# Classic hard-rock tempo band. Chosen so rock sits cleanly at the TOP of the
# calm(60-78) -> lofi(70-85) -> R&B(85-105) -> pop(100-115) -> Latin(100-120)
# -> rock(110-130) monotone ladder. If a future subgenre wants faster tempos
# (punk, hardcore), spin up a separate cell -- do not widen this band.
ROCK_TEMPO_MIN_BPM: int = 110
ROCK_TEMPO_MAX_BPM: int = 130

# Tier -> tempo. Higher tier => more energy, still inside the rock band.
_TIER_TEMPO: dict[int, int] = {1: 110, 2: 115, 3: 120, 4: 125, 5: 130}

# Density floor per tier: rhythm-guitar 8th-note density (fraction of 8ths
# actually struck). Tier 1 leaves lots of air; tier 5 saturates.
_TIER_DENSITY_FLOOR: dict[int, float] = {1: 0.35, 2: 0.55, 3: 0.75, 4: 0.90, 5: 1.00}

# Drive: which guitar patch is used, and how power-chord-forward the voicing
# is. Tiers 1-2 use clean guitar + open triads; tiers 3-5 use overdriven
# guitar + power chords.
#   "clean"    -> GM 27 (Electric Guitar clean), open_position_triad
#   "driven"   -> GM 30 (Overdriven Guitar), power_chord
_TIER_DRIVE: dict[int, str] = {1: "clean", 2: "clean", 3: "driven", 4: "driven", 5: "driven"}

# Drum design for rock: full backbeat, tier-scaled velocities. Unlike calm,
# rock drums are the primary energy carrier, so velocities are much higher.
#
# 4/4 backbeat per bar (16th-note grid, 16 steps per bar):
#   Kick   : beats 1 and 3           (steps 0, 8)
#   Snare  : beats 2 and 4           (steps 4, 12)
#   Hi-hat : every 8th note          (steps 0, 2, 4, 6, 8, 10, 12, 14)
#   Crash  : beat 1 of the FIRST bar (accent), tier >= 4 only
#
# GM percussion note numbers (channel 10):
#   36 = Bass Drum 1 (kick)
#   38 = Acoustic Snare
#   42 = Closed Hi-Hat
#   46 = Open Hi-Hat  (used only in tier 5 for one accent per bar)
#   49 = Crash Cymbal 1
_ROCK_KICK_MIDI:  int = 36
_ROCK_SNARE_MIDI: int = 38
_ROCK_HAT_MIDI:   int = 42
_ROCK_OPEN_HAT_MIDI: int = 46
_ROCK_CRASH_MIDI: int = 49

# Velocities. Rock kits sit MUCH louder than calm.
_TIER_KICK_VEL:  dict[int, int] = {1: 70, 2: 78, 3: 85, 4: 92, 5: 100}
_TIER_SNARE_VEL: dict[int, int] = {1: 65, 2: 72, 3: 82, 4: 90, 5: 98}
_TIER_HAT_VEL:   dict[int, int] = {1: 50, 2: 55, 3: 62, 4: 68, 5: 74}
_TIER_CRASH_VEL: dict[int, int] = {1: 0,  2: 0,  3: 0,  4: 90, 5: 105}
_TIER_CRASH_ON:  dict[int, bool] = {1: False, 2: False, 3: False, 4: True, 5: True}

# Bass velocity ramps with tier; driving 8ths on the root.
_TIER_BASS_VEL_BASE: dict[int, int] = {1: 65, 2: 72, 3: 80, 4: 88, 5: 95}

# Rhythm-guitar velocity ramps with tier.
_TIER_RHYTHM_GTR_VEL: dict[int, int] = {1: 55, 2: 62, 3: 75, 4: 85, 5: 92}

# Rock progressions. All in minor / Mixolydian, using power-chord-friendly
# Roman numerals from _ROMAN_TABLE where possible. Every progression is 4
# chords over a 4-bar phrase.
#
# NOTE: rock's harmonic grammar is minor/Mixolydian, not major-diatonic. To
# stay compatible with the shared _ROMAN_TABLE (which is major-key), the
# rock cell uses the RELATIVE MAJOR of its intended minor key at the
# key-selection stage. E.g. an intended A-minor progression `i-VII-VI-VII`
# is represented as `vi-V-IV-V` in C major (the relative major), which the
# shared _ROMAN_TABLE resolves correctly. This is a bookkeeping choice, not
# a musical one -- the resulting pitches are the same rock chords.
#
# Cross-key spelling reference (relative-major -> intended minor-key sense):
#   Roman "vi"  <=> minor i     (tonic minor)
#   Roman "V"   <=> minor VII   (subtonic major)
#   Roman "IV"  <=> minor VI    (submediant major)
#   Roman "I"   <=> minor III   (mediant major)
#   Roman "iii" <=> minor v     (dominant minor)
_PROGRESSIONS: list[list[str]] = [
    ["vi", "V",  "IV", "V"],       # i-VII-VI-VII in the relative minor
    ["vi", "IV", "iii", "V"],      # i-VI-v-VII (Andalusian-tinged rock)
    ["I",  "V",  "vi", "IV"],      # "Don't Stop Believin'" cadence
    ["vi", "I",  "IV", "I"],       # i-III-VI-III in the relative minor
]


# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

@dataclass
class RockSpec:
    tempo_bpm: int
    density: float
    duration_bars: int
    tier: int
    key_root: str        # relative-major spelling; see _PROGRESSIONS note
    add_lead_riff: bool  # tier == 5 by default
    drive: str           # "clean" or "driven"
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
) -> RockSpec:
    """Clamp inputs into the rock identity band and derive tier."""
    clamped_bpm = max(ROCK_TEMPO_MIN_BPM, min(ROCK_TEMPO_MAX_BPM, tempo_bpm))
    tier = min(_TIER_TEMPO, key=lambda t: abs(_TIER_TEMPO[t] - clamped_bpm))
    density = max(_TIER_DENSITY_FLOOR[tier], min(1.0, density))
    rng = random.Random(seed)
    # Rock keys favor the guitar-friendly ones: E, A, D, G, C.
    key_root = rng.choice(["C", "D", "E", "G", "A"])
    return RockSpec(
        tempo_bpm=clamped_bpm,
        density=density,
        duration_bars=duration_bars,
        tier=tier,
        key_root=key_root,
        add_lead_riff=(tier == 5),
        drive=_TIER_DRIVE[tier],
        seed=seed,
    )


def _select_progression(seed: int) -> list[str]:
    rng = random.Random(seed ^ 0x51ED)
    return list(rng.choice(_PROGRESSIONS))


def rock_drum_pattern(
    tier: int,
    duration_bars: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Classic-rock backbeat pattern.

    Returns (offset_beats, midi_pitch, duration_beats, velocity) events.
    Caller routes to MIDI channel 10 on export.

    Per bar (4/4):
      Kick   on beats 1 and 3   (tier-scaled loud)
      Snare  on beats 2 and 4   (tier-scaled loud)
      Hi-hat on every 8th note  (tier-scaled)
      Crash  on beat 1 of bar 0 (tier >= 4 only, big accent)
      Open hi-hat on the AND of beat 4, tier == 5 only (setup for the downbeat)
    """
    rng = random.Random(seed ^ 0xD70)
    events: list[tuple[float, int, float, int]] = []
    kick_vel  = _TIER_KICK_VEL[tier]
    snare_vel = _TIER_SNARE_VEL[tier]
    hat_vel   = _TIER_HAT_VEL[tier]
    crash_on  = _TIER_CRASH_ON[tier]
    crash_vel = _TIER_CRASH_VEL[tier]

    def _v(base: int) -> int:
        return max(1, base + rng.randint(-4, 4))

    for bar in range(duration_bars):
        base = bar * 4.0

        # Crash on beat 1 of bar 0 only (tier >= 4).
        if bar == 0 and crash_on:
            events.append((base + 0.0, _ROCK_CRASH_MIDI, 1.0, _v(crash_vel)))

        # Kick on 1 and 3
        events.append((base + 0.0, _ROCK_KICK_MIDI, 0.25, _v(kick_vel)))
        events.append((base + 2.0, _ROCK_KICK_MIDI, 0.25, _v(kick_vel)))

        # Snare on 2 and 4
        events.append((base + 1.0, _ROCK_SNARE_MIDI, 0.25, _v(snare_vel)))
        events.append((base + 3.0, _ROCK_SNARE_MIDI, 0.25, _v(snare_vel)))

        # Hi-hat on every 8th note
        for eighth in range(8):
            hat_offset = base + eighth * 0.5
            # Skip the "and of 4" if this bar is a tier-5 bar, so we can put an
            # open-hat accent there instead.
            if tier == 5 and eighth == 7:
                events.append(
                    (hat_offset, _ROCK_OPEN_HAT_MIDI, 0.5, _v(hat_vel + 8))
                )
            else:
                events.append(
                    (hat_offset, _ROCK_HAT_MIDI, 0.125, _v(hat_vel))
                )

    return events


def _rhythm_guitar_clean_pattern(
    chord_pitches: list[int],
    chord_dur_beats: float,
    density: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Clean rhythm-guitar strum pattern for tiers 1-2.

    Sparse 8th-note strums of the full chord voicing, density-gated. This is
    the "intro before the band kicks in" texture: open-position triads, room
    to breathe. Returns (offset_beats, midi_pitch, duration_beats, velocity)
    events -- one event per pitch per strike.
    """
    rng = random.Random(seed ^ 0x671A)
    events: list[tuple[float, int, float, int]] = []
    step_beat = 0.5  # 8th note
    n_eighths = int(chord_dur_beats / step_beat)
    base_vel = _TIER_RHYTHM_GTR_VEL[tier]

    for i in range(n_eighths):
        # Density gate: downbeats (i even) preferred; upbeats sampled.
        strike = False
        if i % 2 == 0 and density >= 0.5:
            strike = True
        elif rng.random() < density:
            strike = True
        if not strike:
            continue

        vel = base_vel + (5 if i % 2 == 0 else -3) + rng.randint(-3, 3)
        vel = max(1, min(120, vel))

        # A clean strum sustains through the next slot -- lets the chord ring.
        strike_dur = step_beat * 1.5
        offset = i * step_beat
        for p in chord_pitches:
            events.append((offset, p, strike_dur, vel))
    return events


# Palm-mute gallop patterns per driven tier. Each pattern is a 16-slot bitmap
# over one bar (16th-note grid, slot indices 0-15). Values:
#   'M' = palm-muted root/5th chug (short, quiet, root+5th only)
#   'C' = open chord punch (full voicing, longer sustain, louder)
#   '.' = rest
#
# Tier 3: light gallop, chord punch on beat 1 only. Leaves rhythmic space.
#   Beats:  1 . . . 2 . . . 3 . . . 4 . . .
#   Slots:  0 1 2 3 4 5 6 7 8 9 A B C D E F
#           C M . M M M . M M M . M M M . M
#
# Tier 4: heavier gallop, chord punches on beats 1 and 3 (backbeat sync).
#           C M M M C M M M C M M M M M . M
#
# Tier 5: saturated gallop, syncopated chord punches on 1, and-of-2, 3.
#           C M M M M M C M C M M M C M M M
_GALLOP_PATTERNS: dict[int, list[str]] = {
    3: ['C','M','.','M', 'M','M','.','M', 'M','M','.','M', 'M','M','.','M'],
    4: ['C','M','M','M', 'C','M','M','M', 'C','M','M','M', 'M','M','.','M'],
    5: ['C','M','M','M', 'M','M','C','M', 'C','M','M','M', 'C','M','M','M'],
}


def _rhythm_guitar_gallop_pattern(
    chord_pitches: list[int],
    chord_dur_beats: float,
    tier: int,
    seed: int,
) -> list[tuple[float, int, float, int]]:
    """Palm-mute 16th-note gallop with syncopated chord punches (tiers 3-5).

    This is the AC/DC / Metallica rhythm-guitar signature:
    - Palm-muted chugs are short (staccato), quiet, and hit only the LOW
      strings (root + 5th, no octave) -- the "chunk" sound.
    - Chord punches hit the FULL power-chord voicing, are louder, and sustain
      longer -- the "ring" sound.
    - Syncopation places chord punches away from the drum backbeat on higher
      tiers, which is what makes riffs sound like riffs and not scales.

    Because `chord_pitches` from `power_chord(include_octave=True)` is
    [root, fifth, octave] in ascending order, the muted chugs use the first
    two pitches (root + fifth); chord punches use all three.

    Returns (offset_beats, midi_pitch, duration_beats, velocity) events.
    """
    rng = random.Random(seed ^ 0x9A11)
    events: list[tuple[float, int, float, int]] = []
    pattern = _GALLOP_PATTERNS[tier]
    slot_beat = 0.25  # 16th note
    n_slots_per_bar = 16
    total_slots = int(chord_dur_beats / slot_beat)
    base_vel = _TIER_RHYTHM_GTR_VEL[tier]

    # Muted chugs use root + fifth only (the bottom two pitches of the voicing).
    # If the voicing is only 2 notes (no octave), muted chug is still root + fifth.
    if len(chord_pitches) >= 2:
        chug_pitches = chord_pitches[:2]
    else:
        chug_pitches = list(chord_pitches)

    for slot in range(total_slots):
        # Repeat the 1-bar pattern for the chord's full duration.
        pattern_slot = pattern[slot % n_slots_per_bar]
        offset = slot * slot_beat

        if pattern_slot == '.':
            continue

        elif pattern_slot == 'M':
            # Muted chug: root + 5th, short (staccato), quiet.
            chug_vel = max(1, base_vel - 20 + rng.randint(-3, 3))
            chug_dur = slot_beat * 0.5  # staccato -- half the slot length
            for p in chug_pitches:
                events.append((offset, p, chug_dur, chug_vel))

        elif pattern_slot == 'C':
            # Chord punch: full voicing, louder, longer sustain.
            # Sustain until the next non-rest slot (approximated: 1 beat).
            punch_vel = min(120, base_vel + 10 + rng.randint(-3, 3))
            punch_dur = 1.0  # one beat of ring
            for p in chord_pitches:
                events.append((offset, p, punch_dur, punch_vel))

    return events


# ---------------------------------------------------------------------------
# Segment builder
# ---------------------------------------------------------------------------

def generate_rock_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
    add_lead_riff: bool | None = None,
) -> stream.Score:
    """Generate a rock segment as a music21 Score.

    Contract matches `generate_segment(genre='rock', tempo_bpm, density,
    duration_bars, seed)`. Returns a Score with:
      Part 0: Electric bass (driving 8ths on the chord root)
      Part 1: Rhythm guitar (power chords / open triads by tier)
      Part 2: Backbeat drums (channel 10)
      Part 3 (optional): Lead guitar with pentatonic riff (tier 5 only)
    """
    spec = _resolve_spec(tempo_bpm, density, duration_bars, seed)
    if add_lead_riff is not None:
        spec.add_lead_riff = add_lead_riff

    progression = _select_progression(spec.seed)
    key_root_midi = _key_root_midi(spec.key_root)

    bars_per_chord = max(1, spec.duration_bars // len(progression))
    beats_per_bar = 4
    chord_dur_beats = bars_per_chord * beats_per_bar

    # ---- Build the Score -------------------------------------------------
    score = stream.Score()
    score.insert(0, tempo.MetronomeMark(number=spec.tempo_bpm))
    score.insert(0, meter.TimeSignature("4/4"))
    # Rock harmony is minor/Mixolydian but we notate in the relative major (see
    # _PROGRESSIONS docstring). Notation is a cosmetic choice; pitches are
    # correct.
    score.insert(0, key.Key(spec.key_root))

    # Part 0: Electric bass.
    bass_part = stream.Part(id="rock_bass")
    bass_part.insert(0, instrument.ElectricBass())

    # Part 1: Rhythm guitar. Instrument choice depends on drive level.
    rhythm_part = stream.Part(id="rock_rhythm_guitar")
    if spec.drive == "driven":
        rhythm_part.insert(0, instrument.ElectricGuitar())  # GM 30-ish; renderer
    else:
        rhythm_part.insert(0, instrument.ElectricGuitar())

    # Part 2: Drums.
    drum_part = stream.Part(id="rock_drums")
    drum_kit = instrument.Percussion()
    drum_kit.midiChannel = 9  # channel 10 in 1-indexed terms
    drum_part.insert(0, drum_kit)

    # Part 3 (optional): Lead guitar overlay for tier 5.
    lead_part: stream.Part | None = None
    if spec.add_lead_riff:
        lead_part = stream.Part(id="rock_lead_guitar")
        lead_part.insert(0, instrument.ElectricGuitar())

    # Iterate chords.
    running_offset = 0.0
    for chord_idx, roman in enumerate(progression):
        chord_seed = spec.seed + 1000 * chord_idx + 7

        # ---- Rhythm guitar voicing + pattern (from shared library) -----
        if spec.drive == "driven":
            chord_voicing = power_chord(
                key_root_midi=key_root_midi,
                roman=roman,
                include_octave=True,
                register_low=40,   # E2
                register_high=64,  # E4
            )
            # Driven tiers (3-5) use the palm-mute gallop pattern -- this is
            # what makes rock guitar sound like guitar, not like piano hitting
            # chords. Density is NOT a knob here; the gallop pattern is fixed
            # per tier so the tier-graded rhythm feel is deterministic.
            rhythm_events = _rhythm_guitar_gallop_pattern(
                chord_pitches=chord_voicing,
                chord_dur_beats=chord_dur_beats,
                tier=spec.tier,
                seed=chord_seed,
            )
        else:
            chord_voicing = open_position_triad(
                key_root_midi=key_root_midi,
                roman=roman,
                register_low=48,   # C3
                register_high=72,  # C5
            )
            # Clean tiers (1-2) use the sparse strum pattern.
            rhythm_events = _rhythm_guitar_clean_pattern(
                chord_pitches=chord_voicing,
                chord_dur_beats=chord_dur_beats,
                density=spec.density,
                tier=spec.tier,
                seed=chord_seed,
            )
        for offs, p_midi, dur_beats, vel in rhythm_events:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = vel
            rhythm_part.insert(running_offset + offs, n)

        # ---- Bass line (from shared library) ---------------------------
        bass_events = driving_eighths_bass(
            key_root_midi=key_root_midi,
            roman=roman,
            duration_beats=chord_dur_beats,
            seed=chord_seed ^ 0xBA55,
            register_low=36,  # C2
            register_high=55, # G3
        )
        # Rescale library velocity to this tier's bass velocity.
        for offs, p_midi, dur_beats, vel_lib in bass_events:
            n = note.Note()
            n.pitch.midi = p_midi
            n.duration = duration.Duration(dur_beats)
            n.volume.velocity = _TIER_BASS_VEL_BASE[spec.tier] + (vel_lib - 70)
            bass_part.insert(running_offset + offs, n)

        # ---- Lead riff (tier 5 only, from shared library) --------------
        if lead_part is not None:
            riff_events = pentatonic_riff(
                key_root_midi=key_root_midi,
                roman=roman,
                duration_beats=chord_dur_beats,
                density=0.75,  # busy but not saturated
                seed=chord_seed ^ 0xEEF,
                register_low=64,  # E4
                register_high=84, # C6
            )
            for offs, p_midi, dur_beats, _ in riff_events:
                n = note.Note()
                n.pitch.midi = p_midi
                n.duration = duration.Duration(dur_beats)
                n.volume.velocity = 88
                lead_part.insert(running_offset + offs, n)

        running_offset += chord_dur_beats

    # ---- Drums (computed once across the full segment) -------------------
    drum_events = rock_drum_pattern(
        tier=spec.tier,
        duration_bars=spec.duration_bars,
        seed=spec.seed ^ 0xD70,
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
    score.insert(0, rhythm_part)
    score.insert(0, drum_part)
    if lead_part is not None:
        score.insert(0, lead_part)

    score.metadata = _make_metadata(spec, progression)
    return score


def _make_metadata(spec: RockSpec, progression: Sequence[str]):
    """Attach a music21 Metadata object with a compact provenance blob."""
    from music21 import metadata as m21meta

    md = m21meta.Metadata()
    md.title = f"rock_tier{spec.tier}_{spec.key_root}_seed{spec.seed}"
    md.composer = "GrooveGen.rock_cell.v2"
    md.groovegen_rock_spec = {
        "family": "rock",
        "tier": spec.tier,
        "tempo_bpm": spec.tempo_bpm,
        "density": spec.density,
        "duration_bars": spec.duration_bars,
        "key_root": spec.key_root,
        "progression": list(progression),
        "drive": spec.drive,
        "add_lead_riff": spec.add_lead_riff,
        "seed": spec.seed,
        "drums": {
            "pattern": "backbeat: kick_1_3 + snare_2_4 + hats_8th"
                       + (" + crash_bar0" if _TIER_CRASH_ON[spec.tier] else "")
                       + (" + open_hat_and4" if spec.tier == 5 else ""),
            "kick_velocity":  _TIER_KICK_VEL[spec.tier],
            "snare_velocity": _TIER_SNARE_VEL[spec.tier],
            "hat_velocity":   _TIER_HAT_VEL[spec.tier],
            "crash_on":       _TIER_CRASH_ON[spec.tier],
        },
        "rhythm_guitar": {
            "voicing": "power_chord" if spec.drive == "driven" else "open_position_triad",
            "pattern": (
                f"palm_mute_gallop_tier{spec.tier}"
                if spec.drive == "driven"
                else "clean_strum"
            ),
            "gallop_bitmap": (
                "".join(_GALLOP_PATTERNS[spec.tier]) if spec.drive == "driven" else None
            ),
            "velocity_base": _TIER_RHYTHM_GTR_VEL[spec.tier],
        },
        "bass": {
            "pattern": "driving_eighths_bass",
            "velocity_base": _TIER_BASS_VEL_BASE[spec.tier],
        },
        "lead_riff": {
            "enabled": spec.add_lead_riff,
            "pattern": "pentatonic_riff" if spec.add_lead_riff else None,
        },
        "generator_version": "rock_cell.v2",
    }
    return md


# ---------------------------------------------------------------------------
# Adapter for the frozen generate_segment contract
# ---------------------------------------------------------------------------

def generate_segment_rock_adapter(
    genre: str,
    tempo_bpm: int,
    density: float,
    duration_bars: int,
    seed: int,
) -> stream.Score:
    """Adapter matching the composer boundary for genre == 'rock'."""
    if genre != "rock":
        raise ValueError(
            f"generate_segment_rock_adapter received genre={genre!r}; only 'rock' is supported."
        )
    return generate_rock_segment(
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

    out_dir = os.environ.get("ROCK_OUT_DIR", "./rock_cell_v1_smoke")
    os.makedirs(out_dir, exist_ok=True)

    for tier in range(1, 6):
        bpm = _TIER_TEMPO[tier]
        density_val = _TIER_DENSITY_FLOOR[tier]
        score_out = generate_rock_segment(
            tempo_bpm=bpm,
            density=density_val,
            duration_bars=8,
            seed=42 + tier,
        )
        fp = os.path.join(out_dir, f"rock_tier{tier}_bpm{bpm}_d{density_val:.2f}.mid")
        score_out.write("midi", fp=fp)
        print(f"wrote {fp}", file=sys.stderr)
