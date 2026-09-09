"""
patterns.py -- Shared rhythmic-pattern library for GrooveGen.

Purpose
-------
This module holds the hand-designed RHYTHMIC PATTERN generators that the
per-family composer cells (calm, lofi, hiphop, rnb, pop, rock, latin) call to
turn a chord into a time-stamped sequence of note events -- arpeggios,
ostinatos, walking basslines, riffs. Like `voicings.py`, this is a deliberate
rule-based library; no ML model is invoked.

Event tuple format (matches `calm_cell.calm_drum_pattern` and
`calm_cell.broken_chord_arpeggio`):

    (offset_beats: float, midi_pitch: int, duration_beats: float, velocity: int)

`offset_beats` is measured from the START of the pattern's chord (not from
the start of the whole segment). Composer cells sum this with a running chord
offset when they assemble the full segment. This is the same convention
`calm_cell.py` uses.

Design conventions
------------------
1. Every pattern accepts EITHER `(key_root_midi, roman)` OR explicit
   `chord_tones: list[int]`. `chord_tones` wins when both are supplied.
2. `duration_beats` (float) sets how long the pattern runs before it wraps.
   Patterns loop cleanly at bar boundaries.
3. Every pattern accepts an optional `seed: int` used ONLY for velocity
   jitter and small rhythmic humanization. Pitch content is fully
   deterministic; the same (chord, duration, seed) always produces the same
   set of events.
4. Patterns are pitched by default. Drum patterns follow the same tuple
   format but the `midi_pitch` field is a GM percussion note number (35-81)
   and the composer cell is responsible for routing to MIDI channel 10 --
   exactly as `calm_cell.calm_drum_pattern` does.
5. Patterns clamp their pitches into a family-appropriate register at
   construction time; composer cells can override with `register_low`
   /`register_high` kwargs.

Functions
---------
    montuno_pattern           Latin piano ostinato (salsa / son montuno)
    bassline_walk             Walking-quarter jazz/R&B bassline
    tresillo_bass             3-3-2 Latin bass ostinato
    driving_eighths_bass      Pumping 8th-note rock bass on the root
    pentatonic_riff           Minor-pentatonic 8th-note melodic riff (rock)
    broken_chord_arpeggio_re  Re-export of the calm-family broken-chord
                              arpeggio, for cross-family reuse

Author: Daniel Llamas Maldonado
"""

from __future__ import annotations

import random
from collections.abc import Sequence

from composer.calm_cell import (
    _build_chord_tones,
)
from composer.calm_cell import (
    broken_chord_arpeggio as _broken_chord_arpeggio_impl,
)

# Event tuple type alias for clarity.
Event = tuple[float, int, float, int]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_chord_tones(
    chord_tones: Sequence[int] | None,
    key_root_midi: int | None,
    roman: str | None,
) -> list[int]:
    if chord_tones is not None:
        return list(chord_tones)
    if key_root_midi is None or roman is None:
        raise ValueError("Pattern needs either chord_tones or (key_root_midi + roman).")
    return _build_chord_tones(key_root_midi, roman)


def _clamp_octave(pitch: int, low: int, high: int) -> int:
    """Bring `pitch` into [low, high] by octave shifts. Preserves pitch class."""
    p = pitch
    while p < low:
        p += 12
    while p > high:
        p -= 12
    return max(low, min(high, p))


# ---------------------------------------------------------------------------
# Pattern generators
# ---------------------------------------------------------------------------


def montuno_pattern(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    duration_beats: float = 8.0,
    density: float = 0.7,
    seed: int = 0,
    register_low: int = 60,  # C4
    register_high: int = 84,  # C6
) -> list[Event]:
    """Salsa / son-montuno piano ostinato.

    Classic 2-bar montuno pattern in 4/4:

        beat: 1 & 2 & 3 & 4 &   1 & 2 & 3 & 4 &
        hit : x . x . . x x .   x . x . . x x .

    (8th-note grid; hits on 1, 2, "and-of-3", 4 -- displaced across two bars.)

    Voicing per hit: octaves of the 3rd and 5th, alternating across the
    pattern. Sits in the upper midrange (C4-C6) so it doesn't fight the
    tumbao bass.

    Recommended family: Latin.
    Not appropriate for: rock (too syncopated), calm.

    `density` controls whether the pattern's weaker hits (beats 2 and 4) are
    kept. density=1.0 plays all 8 hits over the 2-bar pattern; density<=0.5
    drops the beat-2 and beat-4 hits.
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("montuno_pattern needs at least a triad.")
    third = _clamp_octave(tones[1], register_low, register_high)
    fifth = _clamp_octave(tones[2], register_low, register_high)

    # Positions in an 8-beat bar-pair, in beats.
    positions = [
        (0.0, third, 1.0),  # beat 1, strong
        (1.0, fifth, 0.5),  # beat 2, weak
        (2.5, third, 0.5),  # and-of-3, syncopated
        (3.0, fifth, 1.0),  # beat 4, strong
        (4.0, third, 1.0),
        (5.0, fifth, 0.5),
        (6.5, third, 0.5),
        (7.0, fifth, 1.0),
    ]
    # If density <=0.5, drop the beat-2 and beat-4 accents (indices 1, 3, 5, 7).
    if density <= 0.5:
        positions = [positions[i] for i in (0, 2, 4, 6)]

    rng = random.Random(seed ^ 0xA110)
    events: list[Event] = []
    t = 0.0
    while t < duration_beats - 1e-6:
        for offset, pitch, dur in positions:
            evt_offset = t + offset
            if evt_offset >= duration_beats:
                break
            # Clamp duration to segment end.
            dur_final = min(dur, duration_beats - evt_offset)
            vel = 60 + rng.randint(-6, 6)  # ~mp with human jitter
            events.append((evt_offset, pitch, dur_final, vel))
        t += 8.0  # 2-bar pattern
    return events


def bassline_walk(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    duration_beats: float = 4.0,
    seed: int = 0,
    register_low: int = 36,  # C2
    register_high: int = 55,  # G3
) -> list[Event]:
    """Walking bassline: one note per beat, quarter-note grid.

    Rule per beat within a bar:
      beat 1: root of current chord
      beat 2: 3rd
      beat 3: 5th
      beat 4: chromatic approach to the NEXT beat's target
               (or the 7th, if this is a 4-note chord; seed decides)

    In the absence of a "next chord" context, beat 4 falls back to the 7th
    (4-note chord) or root+2 (approach tone from below root of next bar).

    Recommended families: R&B, jazz-influenced pop.
    Not appropriate for: calm, rock (see `driving_eighths_bass`), Latin
    (see `tresillo_bass`).
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("bassline_walk needs at least a triad.")

    root = _clamp_octave(tones[0], register_low, register_high)
    third = _clamp_octave(tones[1], register_low, register_high)
    fifth = _clamp_octave(tones[2], register_low, register_high)
    seventh = _clamp_octave(tones[3], register_low, register_high) if len(tones) >= 4 else None

    rng = random.Random(seed ^ 0xBA11)
    events: list[Event] = []
    n_bars = int(duration_beats // 4)
    for bar in range(n_bars):
        base = bar * 4.0
        # Beat 1
        events.append((base + 0.0, root, 1.0, 60 + rng.randint(-4, 4)))
        # Beat 2
        events.append((base + 1.0, third, 1.0, 55 + rng.randint(-4, 4)))
        # Beat 3
        events.append((base + 2.0, fifth, 1.0, 55 + rng.randint(-4, 4)))
        # Beat 4: 7th if available, else chromatic approach a semitone below root.
        if seventh is not None and rng.random() < 0.6:
            events.append((base + 3.0, seventh, 1.0, 55 + rng.randint(-4, 4)))
        else:
            approach = _clamp_octave(root - 1, register_low, register_high)
            events.append((base + 3.0, approach, 1.0, 55 + rng.randint(-4, 4)))
    # Handle any remaining fractional beats (unusual but possible).
    remainder = duration_beats - n_bars * 4.0
    if remainder > 0.5:
        events.append((n_bars * 4.0, root, remainder, 55))
    return events


def tresillo_bass(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    duration_beats: float = 4.0,
    seed: int = 0,
    register_low: int = 36,  # C2
    register_high: int = 55,  # G3
) -> list[Event]:
    """Tresillo bass: the 3-3-2 rhythmic cell that underlies dembow, reggaeton,
    Cuban son, and modern Latin pop.

    Per bar (16th-note grid, 16 steps), attacks on:
      step 0  (beat 1)
      step 3  (beat 1 "and-of-and")
      step 6  (beat 2.5 -- "and of 2")

    Then rest until the next bar. Bass alternates root and 5th across attacks.

    Recommended family: Latin.
    Not appropriate for: rock, calm, R&B, hip-hop (though hip-hop occasionally
    borrows tresillo -- promote to hip-hop cell explicitly if you want it).
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if len(tones) < 3:
        raise ValueError("tresillo_bass needs at least a triad.")

    root = _clamp_octave(tones[0], register_low, register_high)
    fifth = _clamp_octave(tones[2], register_low, register_high)

    rng = random.Random(seed ^ 0x71E5)
    events: list[Event] = []
    step_beat = 0.25  # 16th-note = 0.25 beats
    n_bars = max(1, int(duration_beats // 4))
    for bar in range(n_bars):
        base = bar * 4.0
        # Tresillo attacks at 16th steps 0, 3, 6 within the bar.
        pattern_steps = [0, 3, 6]
        for i, s in enumerate(pattern_steps):
            pitch = root if i % 2 == 0 else fifth
            offset = base + s * step_beat
            # Duration reaches to the next attack, or 1 beat max.
            if i + 1 < len(pattern_steps):
                next_offset = base + pattern_steps[i + 1] * step_beat
                dur = next_offset - offset
            else:
                # Last attack of the bar rings to the end of the bar.
                dur = (bar + 1) * 4.0 - offset
            vel = 62 + rng.randint(-5, 5)
            events.append((offset, pitch, dur, vel))
    return events


def driving_eighths_bass(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    duration_beats: float = 4.0,
    seed: int = 0,
    register_low: int = 36,  # C2
    register_high: int = 55,  # G3
) -> list[Event]:
    """Pumping 8th-note rock bass on the root.

    Every 8th note of every bar plays the chord's ROOT, at moderate-loud
    velocity, with a tiny down/up accent pattern (down-beats slightly louder
    than up-beats). This is the "AC/DC / punk / indie rock" bass shape.

    Recommended family: rock.
    Not appropriate for: calm, R&B, Latin (all far too busy for this).
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if not tones:
        raise ValueError("driving_eighths_bass needs at least a root tone.")
    root = _clamp_octave(tones[0], register_low, register_high)

    rng = random.Random(seed ^ 0xD817)
    events: list[Event] = []
    step_beat = 0.5  # 8th note
    n_eighths = int(duration_beats / step_beat)
    for i in range(n_eighths):
        offset = i * step_beat
        # Down-beats (i even) slightly louder than up-beats (i odd).
        base_vel = 75 if i % 2 == 0 else 68
        vel = base_vel + rng.randint(-4, 4)
        events.append((offset, root, step_beat, vel))
    return events


# Minor-pentatonic intervals (semitones from tonic): 1, b3, 4, 5, b7.
_MINOR_PENT_INTERVALS: tuple[int, ...] = (0, 3, 5, 7, 10)


def pentatonic_riff(
    key_root_midi: int | None = None,
    roman: str | None = None,
    chord_tones: Sequence[int] | None = None,
    duration_beats: float = 4.0,
    density: float = 0.7,
    seed: int = 0,
    register_low: int = 60,  # C4
    register_high: int = 79,  # G5
) -> list[Event]:
    """Minor-pentatonic 8th-note melodic riff, rock/blues idiom.

    Generates a sequence of 8th notes drawn from the minor pentatonic scale
    rooted at the chord's root. Motion rules:
      - Prefer stepwise within the pentatonic scale (adjacent index).
      - Occasional leaps (index +/- 2) at ~20% probability.
      - `density` controls what fraction of 8th-note slots get a note
        (rest otherwise). 1.0 = fully saturated, 0.5 = half-time feel.

    Recommended family: rock.
    Not appropriate for: calm, Latin, R&B (uses different scales).
    """
    tones = _resolve_chord_tones(chord_tones, key_root_midi, roman)
    if not tones:
        raise ValueError("pentatonic_riff needs at least a root tone.")

    root = tones[0]
    # Build a 2-octave pentatonic pitch pool inside the register window.
    pool: list[int] = []
    for octave in (0, 1, 2):
        for iv in _MINOR_PENT_INTERVALS:
            p = root + iv + 12 * octave
            if register_low <= p <= register_high:
                pool.append(p)
    pool = sorted(set(pool))
    if not pool:
        raise ValueError("pentatonic_riff: no pentatonic pitches fit the register window.")

    rng = random.Random(seed ^ 0xEEF)
    events: list[Event] = []
    step_beat = 0.5  # 8th note
    n_eighths = int(duration_beats / step_beat)
    # Start on the tonic near the middle of the pool.
    idx = min(range(len(pool)), key=lambda i: abs(pool[i] - (register_low + register_high) // 2))
    for i in range(n_eighths):
        if rng.random() > density:
            continue  # rest
        # Move: 60% stay/step, 20% leap, 20% return to tonic-ish.
        r = rng.random()
        if r < 0.6:
            idx = max(0, min(len(pool) - 1, idx + rng.choice([-1, 0, 1])))
        elif r < 0.8:
            idx = max(0, min(len(pool) - 1, idx + rng.choice([-2, 2])))
        else:
            # Return to nearest tonic
            tonics = [j for j, p in enumerate(pool) if (p - root) % 12 == 0]
            if tonics:
                idx = min(tonics, key=lambda j: abs(j - idx))
        pitch = pool[idx]
        offset = i * step_beat
        vel = 70 + rng.randint(-5, 5)
        events.append((offset, pitch, step_beat, vel))
    return events


def _key_tonic_midi(key_root: str, octave: int = 5) -> int:
    """Return MIDI pitch of the given key root in the given octave."""
    note_to_semitone = {
        "C": 0,
        "C#": 1,
        "Db": 1,
        "D": 2,
        "D#": 3,
        "Eb": 3,
        "E": 4,
        "F": 5,
        "F#": 6,
        "Gb": 6,
        "G": 7,
        "G#": 8,
        "Ab": 8,
        "A": 9,
        "A#": 10,
        "Bb": 10,
        "B": 11,
    }
    semitone = note_to_semitone.get(key_root)
    if semitone is None:
        raise ValueError(f"Unsupported key root: {key_root!r}")
    return 12 * (octave + 1) + semitone


def gfunk_piano_riff(
    chord_root_pitches: list[int],
    chord_symbols: list[str],
    key_root: str,
    rng: random.Random,
    density: float = 0.6,
) -> tuple[list[Event], list[Event]]:
    """Generate a deterministic 4-bar G-funk piano hook pattern.

    Returns `(left_hand_events, right_hand_events)` where each event is
    `(start_beat_offset, midi_pitch, duration_beats, velocity)`.

    Left hand: one sustained root per bar, two octaves below each bar's chord
    root for warm low-end support.

    Right hand: a repeating syncopated melodic hook drawn from the natural
    minor scale rooted at `key_root`, kept in octave-5 register (MIDI 72-84).
    Density controls how many notes of each bar's sparse HOOK/ANSWER bitmap
    are active.
    """
    if not chord_root_pitches:
        return [], []

    # Keep external interface parity: symbols are context for callers even when
    # this riff implementation does not require harmonic re-interpretation.
    _ = chord_symbols

    density_clamped = max(0.0, min(1.0, density))

    minor_scale_semitones = [0, 2, 3, 5, 7, 8, 10]

    hook_slots = [0, 6, 12]
    answer_slots = [0, 12]
    hook_template = {0: 0, 6: 4, 12: 0}
    answer_template = {0: 4, 12: 0}

    key_tonic_pitch = _key_tonic_midi(key_root, octave=5)

    left_hand_events: list[Event] = []
    right_hand_events: list[Event] = []
    n_bars = len(chord_root_pitches)

    for bar_idx in range(n_bars):
        bar_offset = bar_idx * 4.0

        # Left hand sustained root, two octaves down.
        lh_pitch = chord_root_pitches[bar_idx] - 24
        lh_vel = max(70, min(80, 75 + rng.randint(-5, 5)))
        left_hand_events.append((bar_offset, lh_pitch, 4.0, lh_vel))

        # Left-hand octave-up pickup on the and-of-3.
        pickup_pitch = chord_root_pitches[bar_idx] - 12
        pickup_vel = max(65, min(70, 67 + rng.randint(-2, 3)))
        left_hand_events.append((bar_offset + 2.5, pickup_pitch, 0.5, pickup_vel))

        # Right hand alternates HOOK and ANSWER rhythmic bitmaps by bar.
        is_hook = bar_idx % 2 == 0
        base_slots = hook_slots if is_hook else answer_slots
        template = hook_template if is_hook else answer_template
        base_count = len(base_slots)
        min_count = 2 if is_hook else 1
        target_count = max(min_count, round(density_clamped * base_count))
        if target_count < base_count:
            active_slots = sorted(rng.sample(base_slots, target_count))
        else:
            active_slots = list(base_slots)

        chord_root_pitch = chord_root_pitches[bar_idx]
        chord_offset_semitones = (chord_root_pitch % 12 - (key_tonic_pitch % 12)) % 12

        for slot in active_slots:
            degree_idx = template[slot]
            if is_hook and slot == 6 and rng.random() >= 0.5:
                degree_idx = 5

            pitch_val = key_tonic_pitch + chord_offset_semitones + minor_scale_semitones[degree_idx]
            while pitch_val < 72:
                pitch_val += 12
            while pitch_val > 84:
                pitch_val -= 12

            rh_offset = bar_offset + slot * 0.25
            rh_vel = 65 + rng.randint(0, 20)
            right_hand_events.append((rh_offset, pitch_val, 0.25, rh_vel))

    return left_hand_events, right_hand_events


# ---------------------------------------------------------------------------
# Re-export of calm-family arpeggio so other cells can reuse it consistently.
# ---------------------------------------------------------------------------


def broken_chord_arpeggio_re(
    key_root_midi: int,
    roman: str,
    chord_dur_beats: float,
    density: float,
    seed: int,
) -> tuple[list[Event], list[Event]]:
    """Re-export of `calm_cell.broken_chord_arpeggio` under a stable name here.

    Returns `(bass_events, treble_events)` exactly like the calm-cell version.
    Provided so future non-calm families that want the same arpeggio texture
    (e.g. a soft-lofi cell or an R&B intro) can import it from `patterns.py`
    without depending on `calm_cell.py` directly.
    """
    return _broken_chord_arpeggio_impl(
        key_root_midi=key_root_midi,
        roman=roman,
        chord_dur_beats=chord_dur_beats,
        density=density,
        seed=seed,
    )


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    C_MIDI = 48  # C3
    print("Pattern library self-test (chord: Cmaj7, key: C, 4-beat window)", file=sys.stderr)
    print("-" * 60, file=sys.stderr)

    def _summarize(name: str, events: list[Event]) -> None:
        if not events:
            print(f"  {name:32s} -> 0 events", file=sys.stderr)
            return
        pitches = sorted({p for _, p, _, _ in events})
        offsets = [round(o, 3) for o, _, _, _ in events][:8]
        print(
            f"  {name:32s} -> {len(events):3d} events, "
            f"pitches={pitches[:5]}{'...' if len(pitches) > 5 else ''}, "
            f"first offsets={offsets}",
            file=sys.stderr,
        )

    _summarize("montuno_pattern", montuno_pattern(C_MIDI, "I", duration_beats=8.0, seed=1))
    _summarize("bassline_walk", bassline_walk(C_MIDI, "I", duration_beats=4.0, seed=1))
    _summarize("tresillo_bass", tresillo_bass(C_MIDI, "I", duration_beats=4.0, seed=1))
    _summarize(
        "driving_eighths_bass", driving_eighths_bass(C_MIDI, "I", duration_beats=4.0, seed=1)
    )
    _summarize(
        "pentatonic_riff", pentatonic_riff(C_MIDI, "I", duration_beats=4.0, density=0.8, seed=1)
    )
    b, t = broken_chord_arpeggio_re(C_MIDI, "I", chord_dur_beats=4.0, density=0.7, seed=1)
    _summarize("broken_chord_arpeggio_re (bass)", b)
    _summarize("broken_chord_arpeggio_re (treble)", t)
