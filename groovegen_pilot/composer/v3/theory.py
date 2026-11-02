"""
Pitch, chord, scale, voicing and timing helpers for the v3 generators.

Pure functions only: no RNG, no MIDI objects. Pitch classes are 0..11, MIDI
pitches are ints; harmony is expressed relative to the composition's key
(Roman numeral roots in semitones above the tonic), so material is
transposition-invariant by construction.
"""

from __future__ import annotations

from dataclasses import dataclass

STEPS_PER_BAR = 16          # 16th-note grid
BARS = 8                    # one segment (run_session_v2.SessionConfigV2.bars_per_segment)
SEG_STEPS = STEPS_PER_BAR * BARS

# Chord qualities as intervals above the root. 9ths are written as 14 so the
# voicer can place them above the triad; tension tones are everything above 11.
QUALITIES: dict[str, tuple[int, ...]] = {
    'm': (0, 3, 7),
    'M': (0, 4, 7),
    'm7': (0, 3, 7, 10),
    'm9': (0, 3, 7, 10, 14),
    'madd9': (0, 3, 7, 14),
    'maj7': (0, 4, 7, 11),
    'maj9': (0, 4, 7, 11, 14),
    '7': (0, 4, 7, 10),
    '9': (0, 4, 7, 10, 14),
    '7b9': (0, 4, 7, 10, 13),
    'm7b5': (0, 3, 6, 10),
    '7sus4': (0, 5, 7, 10),
    # added for the multi-genre styles (genres.py); hip-hop never draws these
    'add9': (0, 4, 7, 14),
    'sus2': (0, 2, 7),
    'sus4': (0, 5, 7),
    '6': (0, 4, 7, 9),
    '5': (0, 7),
    'm11': (0, 3, 7, 10, 14, 17),
    '9sus4': (0, 5, 7, 10, 14),
    '13': (0, 4, 7, 10, 14, 21),
}

# Roman numeral -> root in semitones above the (minor) tonic.
ROMAN_ROOT: dict[str, int] = {
    'i': 0, 'bII': 1, 'ii': 2, 'bIII': 3, 'iv': 5, 'IV': 5, 'v': 7, 'V': 7, 'bVI': 8, 'bVII': 10,
    # added for major-key and modal styles (genres.py)
    'I': 0, 'II': 2, 'iii': 4, 'III': 4, 'vi': 9, 'vii': 11,
}

MODES: dict[str, tuple[int, ...]] = {
    'aeolian': (0, 2, 3, 5, 7, 8, 10),
    'dorian': (0, 2, 3, 5, 7, 9, 10),
    'phrygian': (0, 1, 3, 5, 7, 8, 10),
    # added for the multi-genre styles (genres.py)
    'ionian': (0, 2, 4, 5, 7, 9, 11),
    'mixolydian': (0, 2, 4, 5, 7, 9, 10),
    'lydian': (0, 2, 4, 6, 7, 9, 11),
    'harmonic': (0, 2, 3, 5, 7, 8, 11),
}

PC_NAMES = ('C', 'C#', 'D', 'Eb', 'E', 'F', 'F#', 'G', 'Ab', 'A', 'Bb', 'B')


@dataclass(frozen=True)
class Chord:
    roman: str
    quality: str

    def root_pc(self, key_pc: int) -> int:
        return (key_pc + ROMAN_ROOT[self.roman]) % 12

    def pcs(self, key_pc: int) -> tuple[int, ...]:
        """Every chord tone, tensions included, in voicing order."""
        r = self.root_pc(key_pc)
        return tuple((r + i) % 12 for i in QUALITIES[self.quality])

    def core_pcs(self, key_pc: int) -> frozenset[int]:
        """Root, third, fifth and seventh: the tones a strong-beat melody note may land on."""
        r = self.root_pc(key_pc)
        return frozenset((r + i) % 12 for i in QUALITIES[self.quality] if i < 12)

    def name(self, key_pc: int) -> str:
        return f"{PC_NAMES[self.root_pc(key_pc)]}{'' if self.quality == 'M' else self.quality}"


def melodic_pcs(chord: Chord, key_pc: int, mode: str) -> frozenset[int]:
    """Pitch classes a melody may use over `chord`: its chord tones plus the
    key's scale tones, minus

      - avoid notes: a scale tone a semitone *above* a chord tone (b9 over the
        root, b13 over the fifth, the 4th over a major third). A semitone
        *below* a chord tone stays usable (the 9th under a minor third);
      - the unaltered form of a degree the chord raises: the scale tone a
        semitone below a chord tone that is not in the scale (the natural b7
        under V7's raised third, b6 under a dorian IV's major third).
    """
    chord_pcs = set(chord.pcs(key_pc))
    scale = {(key_pc + i) % 12 for i in MODES[mode]}
    ok = set(chord_pcs)
    for s in scale - chord_pcs:
        above_tone = any((s - c) % 12 == 1 for c in chord_pcs)
        under_raised = (s + 1) % 12 in chord_pcs and (s + 1) % 12 not in scale
        if not (above_tone or under_raised):
            ok.add(s)
    return frozenset(ok)


def degree_to_midi(deg: int, key_pc: int, mode: str, tonic_midi: int) -> int:
    """Diatonic scale degree (0 = tonic, 7 = tonic an octave up, negative below)
    to a MIDI pitch, with tonic_midi the tonic of degree 0."""
    octave, step = divmod(deg, 7)
    return tonic_midi + 12 * octave + MODES[mode][step]


def snap(pitch: int, allowed: frozenset[int], prefer_up: bool = True) -> int:
    """Nearest pitch whose pitch class is in `allowed` (ties toward prefer_up)."""
    if pitch % 12 in allowed:
        return pitch
    for d in range(1, 7):
        order = (pitch + d, pitch - d) if prefer_up else (pitch - d, pitch + d)
        for p in order:
            if p % 12 in allowed:
                return p
    return pitch


def fold(pitch: int, lo: int, hi: int) -> int:
    """Move `pitch` by octaves into [lo, hi] (hi - lo >= 12)."""
    while pitch < lo:
        pitch += 12
    while pitch > hi:
        pitch -= 12
    return pitch


def directed(raw: int, prev: int | None, direction: int, allowed: frozenset[int], lo: int, hi: int) -> int:
    """The allowed pitch in [lo, hi] nearest `raw` that keeps the motif's
    intended motion from `prev` (direction +1 up, -1 down, 0 repeat), so fitting
    a line to a chord never flattens its contour into repeated notes."""
    cands = [p for p in range(lo, hi + 1) if p % 12 in allowed]
    if prev is not None:
        if direction > 0:
            moved = [p for p in cands if p > prev]
        elif direction < 0:
            moved = [p for p in cands if p < prev]
        else:
            moved = [prev] if prev % 12 in allowed else []
        cands = moved or cands
    return min(cands, key=lambda p: (abs(p - raw), p)) if cands else raw


def bounded(pitch: int, allowed: frozenset[int], lo: int, hi: int) -> int:
    """`pitch` if it lies in [lo, hi], else the nearest allowed pitch inside
    the range (a melody that runs into the ceiling repeats its top note
    instead of jumping an octave)."""
    if lo <= pitch <= hi:
        return pitch
    inside = [p for p in range(lo, hi + 1) if p % 12 in allowed]
    return min(inside, key=lambda p: (abs(p - pitch), p)) if inside else fold(pitch, lo, hi)


def place(pc: int, lo: int, hi: int, center: float) -> int:
    """The pitch of class `pc` in [lo, hi] nearest `center` (when the range is
    narrower than an octave and holds no such pitch, the one nearest the range)."""
    cands = [p for p in range(lo, hi + 1) if p % 12 == pc]
    if not cands:
        cands = [p for p in range(lo - 12, hi + 13) if p % 12 == pc]
        return min(cands, key=lambda p: (max(lo - p, p - hi, 0), abs(p - center), p))
    return min(cands, key=lambda p: (abs(p - center), p))


def voicings(pcs: tuple[int, ...], lo: int, hi: int) -> list[tuple[int, ...]]:
    """Close-position voicings of `pcs` (each inversion, every octave) inside
    [lo, hi], low intervals kept open (no seconds or thirds below MIDI 52)."""
    out = []
    n = len(pcs)
    for start in range(n):
        order = pcs[start:] + pcs[:start]
        for bottom in range(lo, hi + 1):
            if bottom % 12 != order[0]:
                continue
            notes = [bottom]
            for pc in order[1:]:
                p = notes[-1] + 1
                while p % 12 != pc:
                    p += 1
                notes.append(p)
            if notes[-1] > hi:
                continue
            if any(b - a < 5 and a < 52 for a, b in zip(notes, notes[1:])):
                continue
            out.append(tuple(notes))
    return out


def lead_voice(pcs: tuple[int, ...], prev: tuple[int, ...] | None, lo: int, hi: int,
               center: float) -> tuple[int, ...]:
    """The voicing of `pcs` that moves least from `prev` (voice leading); the
    one nearest `center` when there is no previous chord."""
    cands = voicings(pcs, lo, hi)
    if not cands:
        return tuple(sorted(place(pc, lo, hi, center) for pc in pcs))

    def cost(v):
        if prev is None:
            return abs(sum(v) / len(v) - center), v
        a, b = sorted(v), sorted(prev)
        if len(a) == len(b):
            move = sum(abs(x - y) for x, y in zip(a, b))
        else:
            move = sum(min(abs(x - y) for y in b) for x in a)
        return move + 0.25 * abs(sum(v) / len(v) - center), v

    return min(cands, key=cost)


@dataclass(frozen=True)
class Grid:
    """Shared timing for every instrument of a segment: 16th steps with swing.

    swing is the share of an 8th taken by its first 16th (0.5 = straight,
    0.58 = a moderate hip-hop swing). Every part reads onsets from the same
    grid, so drums, bass and keys swing together."""

    tempo: float
    swing: float = 0.5

    @property
    def beat_s(self) -> float:
        return 60.0 / self.tempo

    @property
    def bar_s(self) -> float:
        return 4 * self.beat_s

    @property
    def step_s(self) -> float:
        return self.beat_s / 4

    @property
    def seg_s(self) -> float:
        return BARS * self.bar_s

    def t(self, step: float) -> float:
        """Time in seconds of a (possibly fractional) global 16th step."""
        whole = int(step)
        pair, odd = divmod(whole, 2)
        eighth = 2 * self.step_s
        return pair * eighth + odd * eighth * self.swing + (step - whole) * self.step_s

    def span(self, step: float, dur_steps: float) -> tuple[float, float]:
        start = self.t(step)
        return start, start + dur_steps * self.step_s


def weighted(rng, options: dict) -> object:
    """Deterministic weighted choice over a dict's keys (sorted for stability)."""
    keys = sorted(options, key=str)
    return rng.choices(keys, weights=[options[k] for k in keys], k=1)[0]
