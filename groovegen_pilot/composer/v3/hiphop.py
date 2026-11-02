"""
Hip-hop v3: composition creation, segment planning and realisation.

A composition (CompositionSpec) is created from a seed by small generative
rules, not chosen from a list of finished patterns:
  - harmony: a weighted chord-transition grammar per sub-style, with loop
    closure and a harmonic-rhythm shape (1 or 2 bars per chord, or a
    half-bar turnaround), plus a contrast loop that leads back to the tonic;
  - groove: kick placements drawn from metrical weights around the fixed
    boom-bap anchors (kick on 1, snare on 2 and 4), a 2-bar kick variation,
    a 16th hat mask, open-hat and ghost-snare positions, swing and a small
    laid-back snare offset;
  - bass: derived from the harmony and the kick (roots on chord changes,
    other notes on kick hits, approach notes into chord changes);
  - hook: a 2-bar motif built from authored 1-bar rhythm cells and a
    constrained diatonic walk, fitted to each chord when realised (strong
    notes on chord tones, the rest avoiding semitone clashes);
  - comping: voice-led chords whose rhythm fills the hook's rests.

Segments realise one shared SegmentPlan (harmony per step, hook content per
2-bar unit, fills, layers), so every part follows the same chord changes,
grid and phrase ends. Musical development follows the composition's form
(statement, variation, contrast, return); the intensity level only selects
layers, densities and dynamics and never changes the composition's identity.
"""

from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Optional

import pretty_midi

from composer.arrangement import H
from composer.v3 import GEN_VERSION
from composer.v3.state import (CompositionSpec, CompositionState, Loop, Motif, MotifNote,
                               SegmentPlan)
from composer.v3.theory import (BARS, STEPS_PER_BAR, Chord, Grid, degree_to_midi, directed,
                                lead_voice, melodic_pcs, place, weighted)

# =============================================================================
# Style knowledge
# =============================================================================

# Authored 1-bar rhythm cells for hooks: (onset in 16ths, length in 16ths).
# Primitives written for GrooveGen, not transcribed from recordings.
CELLS: dict[str, tuple[tuple[int, float], ...]] = {
    'c1': ((0, 2), (3, 1), (6, 2), (10, 2)),
    'c2': ((0, 3), (4, 2), (7, 1), (8, 4)),
    'c3': ((2, 2), (4, 2), (7, 3), (12, 2)),
    'c4': ((0, 1), (2, 1), (3, 2), (6, 1), (8, 2), (11, 3)),
    'c5': ((4, 4), (10, 2), (12, 4)),
    'c6': ((0, 6), (6, 2), (8, 8)),
    'c7': ((0, 2), (2, 2), (4, 2), (6, 2), (8, 4), (12, 2)),
    'c8': ((3, 1), (6, 1), (8, 2), (11, 1), (14, 2)),
    'c9': ((0, 4), (6, 2), (10, 6)),
    'c10': ((0, 2), (3, 2), (8, 2), (11, 2), (14, 2)),
    'c11': ((2, 2), (6, 2), (10, 2), (14, 2)),
    'c12': ((0, 3), (3, 3), (6, 2), (10, 3), (13, 3)),
    'c13': ((0, 2), (4, 1), (5, 1), (6, 2), (12, 4)),
    'c14': ((1, 1), (2, 2), (8, 1), (9, 1), (10, 2)),
    'c15': ((0, 8), (8, 4), (12, 4)),
    'c16': ((0, 2), (2, 1), (4, 2), (7, 1), (8, 2), (10, 1), (12, 2), (14, 1)),
}

# Register and articulation per GM program used by the palettes.
HOOK_REGISTER = {0: (60, 86), 11: (62, 88), 73: (65, 93), 28: (52, 76), 45: (55, 81), 8: (67, 93)}
CHORD_REGISTER = {4: (50, 74), 0: (48, 74), 48: (48, 76), 49: (48, 76), 89: (48, 74)}
ARTICULATION = {0: 0.75, 11: 0.9, 73: 0.95, 28: 0.55, 45: 0.45, 8: 0.85, 61: 0.6}
BASS_LO, BASS_HI, BASS_CENTER = 31, 45, 37.0
COUNTER_LO, COUNTER_HI = 60, 79

SUBSTYLES: dict[str, dict] = {
    # Piano or vibes hooks over keys or strings, swung boom-bap, octave-popping bass.
    'boombap': dict(
        tempo=(86, 94), swing=(0.52, 0.58), snare_lag_ms=6.0, snare=38,
        palettes=(dict(hook=0, chords=4, bass=33, counter=48, double=11),
                  dict(hook=11, chords=0, bass=33, counter=49, double=0),
                  dict(hook=0, chords=48, bass=32, counter=4, double=11)),
        trans={'i': {'bVI': 3, 'iv': 3, 'bVII': 2, 'v': 2, 'bIII': 1, 'bII': 0.7},
               'bVI': {'bVII': 2, 'i': 3, 'v': 1.5, 'iv': 1},
               'iv': {'i': 3, 'bVII': 2, 'v': 1, 'bVI': 1},
               'bVII': {'i': 3, 'bVI': 2, 'bIII': 1},
               'v': {'i': 3, 'bVI': 2, 'iv': 1},
               'bIII': {'bVI': 2, 'iv': 2, 'bVII': 1},
               'bII': {'i': 4}},
        quality={'i': ('m7', 'm'), 'iv': ('m7',), 'bVI': ('maj7', 'M'), 'bVII': ('M', '7'),
                 'v': ('m7', 'm'), 'bIII': ('maj7',), 'bII': ('maj7', 'M')},
        loop_sizes={2: 3, 3: 2, 4: 3},
        cells=('c1', 'c3', 'c4', 'c8', 'c10', 'c12', 'c13', 'c14'),
        answer_cells=('c5', 'c9', 'c11', 'c2', 'c15'),
        kick={10: 3, 7: 2, 8: 1.5, 14: 1.5, 3: 1, 11: 1, 6: 1, 15: 0.5},
        bass={'lock_octave': 2, 'lock': 1},
        comp={'stabs': 3, 'held': 1},
        hat_odd=(0.3, 0.6),
        ops={'sequence': 3, 'fragment': 2, 'displace': 2, 'ornament': 1, 'invert': 1, 'rhythm': 1},
    ),
    # Rich 7th/9th keys, laid-back swing, walking bass, vibes / flute / guitar hooks.
    'soul': dict(
        tempo=(82, 90), swing=(0.56, 0.62), snare_lag_ms=12.0, snare=38,
        palettes=(dict(hook=11, chords=4, bass=33, counter=49, double=73),
                  dict(hook=73, chords=4, bass=33, counter=48, double=11),
                  dict(hook=28, chords=4, bass=33, counter=89, double=11)),
        trans={'i': {'iv': 3, 'bVI': 2, 'IV': 2, 'bIII': 1.5, 'bVII': 1},
               'iv': {'bVII': 3, 'i': 2, 'v': 1},
               'IV': {'i': 3, 'iv': 1},
               'bVII': {'bIII': 2.5, 'i': 2, 'bVI': 1},
               'bIII': {'bVI': 3, 'iv': 1, 'ii': 1},
               'bVI': {'ii': 1.5, 'bVII': 2, 'V': 1, 'i': 1},
               'ii': {'V': 4},
               'V': {'i': 4},
               'v': {'i': 3}},
        quality={'i': ('m9', 'm7'), 'iv': ('m9', 'm7'), 'IV': ('9', '7'), 'bVII': ('9', '7sus4'),
                 'bIII': ('maj9', 'maj7'), 'bVI': ('maj9', 'maj7'), 'ii': ('m7b5',), 'V': ('7b9', '7'),
                 'v': ('m7',)},
        loop_sizes={2: 2, 3: 1, 4: 3, 5: 1},
        cells=('c2', 'c5', 'c6', 'c9', 'c11', 'c13', 'c15', 'c3'),
        answer_cells=('c11', 'c9', 'c6', 'c15', 'c8'),
        kick={8: 2, 10: 2, 7: 1, 15: 1, 3: 1, 11: 0.7},
        bass={'walk': 3, 'lock': 1},
        comp={'neo': 3, 'held': 1, 'stabs': 1},
        hat_odd=(0.2, 0.5),
        ops={'ornament': 3, 'rhythm': 2, 'sequence': 2, 'invert': 1, 'fragment': 1},
    ),
    # Minor triads, Phrygian and harmonic-minor colour, straight time, pizzicato / piano / celesta.
    'dark': dict(
        tempo=(88, 96), swing=(0.5, 0.52), snare_lag_ms=0.0, snare=40,
        palettes=(dict(hook=45, chords=49, bass=38, counter=61, double=8),
                  dict(hook=0, chords=89, bass=38, counter=48, double=8),
                  dict(hook=8, chords=48, bass=33, counter=61, double=0)),
        trans={'i': {'bVI': 3, 'bII': 2, 'v': 2, 'iv': 2, 'V': 1},
               'bII': {'i': 4},
               'bVI': {'v': 2, 'V': 2, 'i': 2, 'bII': 1},
               'v': {'i': 3, 'bVI': 1},
               'V': {'i': 4},
               'iv': {'i': 2, 'V': 2, 'bVI': 1}},
        quality={'i': ('m', 'madd9'), 'bII': ('M', 'maj7'), 'bVI': ('M',), 'v': ('m',), 'V': ('7', 'M'),
                 'iv': ('m',)},
        loop_sizes={2: 4, 3: 2, 4: 2},
        cells=('c1', 'c6', 'c7', 'c9', 'c12', 'c15', 'c16', 'c10'),
        answer_cells=('c15', 'c6', 'c9', 'c5', 'c11'),
        kick={8: 2, 10: 1, 11: 2, 14: 1, 6: 1, 3: 1},
        bass={'sustain': 3, 'lock': 1},
        comp={'held': 3, 'stabs': 1},
        hat_odd=(0.25, 0.55),
        ops={'invert': 2, 'sequence': 3, 'fragment': 1, 'displace': 1, 'rhythm': 1},
    ),
}

# Roles per segment. S1 opens the composition (hook enters at bar 5), S
# states the theme, V/V2 develop it, C/C2 contrast it over the second loop
# (C2 leads back), R/R2 return to it; R2 closes the composition.
FORMS: tuple[tuple[str, ...], ...] = (
    ('S1', 'S', 'V', 'V2', 'C', 'C2', 'R', 'R2'),
    ('S1', 'S', 'V', 'C', 'C2', 'R', 'V2', 'R2'),
    ('S1', 'S', 'C', 'C2', 'R', 'V', 'V2', 'R2'),
)

# Intensity levels: which layers sound. Identity (tempo, key, harmony, kick
# anchors, hook anchors, palette) is the same at every level.
LAYERS: dict[int, frozenset[str]] = {
    1: frozenset({'kick_min', 'snare', 'hat_q', 'bass_min', 'chords_held', 'hook_anchor'}),
    2: frozenset({'kick', 'snare', 'hat_8', 'bass', 'chords_8', 'hook', 'fills_min'}),
    3: frozenset({'kick', 'snare', 'hat_16', 'open_hat', 'ghost', 'bass', 'bass_pickup', 'chords',
                  'hook', 'fills'}),
    4: frozenset({'kick', 'snare', 'hat_16', 'open_hat', 'ghost', 'bass', 'bass_pickup', 'chords',
                  'hook', 'fills', 'clap', 'perc', 'counter'}),
    5: frozenset({'kick', 'snare', 'hat_16', 'open_hat', 'ghost', 'bass', 'bass_pickup', 'chords',
                  'hook', 'fills', 'clap', 'perc', 'counter', 'counter_active', 'double', 'crash'}),
}

# Velocities per level. Drum values follow the v2c hip-hop tier ladder
# (hiphop_cell _TIER_*_VEL); melodic offsets are calibrated by rendered loudness
# (audition_v3.py --calibrate) so that a level sits near the v2c tier's LUFS.
DRUM_VEL = {
    'kick': {1: 102, 2: 104, 3: 106, 4: 110, 5: 114},
    'snare': {1: 92, 2: 96, 3: 100, 4: 104, 5: 108},
    'hat': {1: 60, 2: 64, 3: 68, 4: 72, 5: 76},
    'clap': {4: 74, 5: 86},
    'perc': {4: 44, 5: 52},
    'ghost': {3: 32, 4: 36, 5: 40},
}
MEL_BASE = {'hook': 92, 'chords': 60, 'bass': 92, 'counter': 56, 'double': 62}
MEL_OFFSET = {1: -12, 2: -10, 3: -1, 4: 4, 5: 8}

# Mix: each melodic program's loudness at a fixed phrase and velocity (FluidSynth,
# LUFS, measured with audition_v3.py) is levelled to a common reference by MIDI
# channel volume (CC7, 40 log10 law; 100 = the GM default = 0 dB), then each role
# gets its place in the mix. Velocities stay free for dynamics and articulation.
PROGRAM_LUFS = {0: -27.7, 4: -20.9, 8: -24.1, 11: -28.2, 28: -29.8, 32: -24.3, 33: -24.8, 38: -21.9,
                45: -24.3, 48: -26.3, 49: -23.5, 61: -23.2, 73: -21.7, 89: -29.4}
ROLE_TRIM_DB = {'hook': -1.0, 'chords': -0.5, 'bass': 1.5, 'counter': -3.0, 'double': -6.0}
REFERENCE_LUFS = -25.0
CC7_REF = 90                 # channel volume for 0 dB trim; leaves +5.8 dB of headroom to 127
MIX_TRIM_RANGE = (-6.0, 5.0)


def channel_volume(program: int, role: str, comp_trim_db: float = 0.0) -> int:
    trim = ROLE_TRIM_DB[role] + REFERENCE_LUFS - PROGRAM_LUFS.get(program, REFERENCE_LUFS) + comp_trim_db
    return int(max(1, min(127, round(CC7_REF * 10 ** (trim / 40)))))

KICK, SNARE_RIM, CLAP, HAT, PEDAL_HAT, OPEN_HAT, CRASH, TAMBOURINE, MARACAS = 36, 37, 39, 42, 44, 46, 49, 54, 70


def _rng(*key) -> random.Random:
    return random.Random(H(*key))


# =============================================================================
# Composition creation (identity)
# =============================================================================


def _shape(n: int, rng) -> tuple[tuple[int, ...], ...]:
    """Harmonic rhythm: which chord index each of the 4 bars starts with
    (a second entry is a half-bar change)."""
    if n == 2:
        return weighted(rng, {((0,), (0,), (1,), (1,)): 2, ((0,), (1,), (0,), (1,)): 1})
    if n == 3:
        return weighted(rng, {((0,), (0,), (1,), (2,)): 1, ((0,), (1,), (2,), (2,)): 1})
    if n == 4:
        return ((0,), (1,), (2,), (3,))
    return ((0,), (1,), (2,), (3, 4))           # n == 5: half-bar turnaround in bar 4


def make_loop(rng, sub: dict, quality: dict, start: Optional[str], avoid: set,
              lead_to_tonic: bool = False) -> Loop:
    """A closed chord loop from the sub-style's transition grammar.

    start=None picks a non-tonic opening (contrast loops); lead_to_tonic asks
    that the last chord can move to i, so a contrast can hand back to the theme."""
    trans = sub['trans']
    best = None
    for attempt in range(80):
        n = weighted(rng, sub['loop_sizes'])
        first = start or weighted(rng, {k: w for k, w in trans['i'].items() if k != 'i'})
        seq = [first]
        while len(seq) < n:
            nxt = weighted(rng, trans[seq[-1]])
            if nxt == seq[-1]:
                continue
            seq.append(nxt)
        if len(set(seq)) < 2 or tuple(seq) in avoid:
            continue
        closes = seq[0] in trans.get(seq[-1], {})
        leads = 'i' in trans.get(seq[-1], {})
        if closes and (leads or not lead_to_tonic):
            best = seq
            break
        if best is None and (closes or leads):
            best = seq
    seq = best or [start or 'bVI', 'i']
    shape = _shape(len(seq), rng)
    chords = [Chord(r, quality[r]) for r in seq]
    bars = tuple(tuple((0 if j == 0 else 8, chords[idx]) for j, idx in enumerate(b)) for b in shape)
    return Loop(bars)


def _mode_for(*loops: Loop) -> str:
    romans = {r for lp in loops for r in lp.romans()}
    if 'IV' in romans:
        return 'dorian'
    if 'bII' in romans:
        return 'phrygian'
    return 'aeolian'


def make_kicks(rng, weights: dict) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Kick on beat 1 plus 1-3 syncopated hits (never on the snare's 4 / 12);
    the second bar of the 2-bar unit varies one hit."""
    def ok(s, have):
        if s in (0, 4, 12) or s in have:
            return False
        if (s - 1) in have and s not in (11, 15):
            return False
        return (s + 1) not in have or (s + 1) in (11, 15)

    k = weighted(rng, {1: 3, 2: 5, 3: 2})
    a = {0}
    while len(a) < 1 + k:
        cands = {s: w for s, w in weights.items() if ok(s, a)}
        if not cands:
            break
        a.add(weighted(rng, cands))
    b = set(a)
    for _ in range(20):
        how = weighted(rng, {'pickup': 2, 'move': 2, 'drop': 1, 'add': 1})
        b = set(a)
        extra = sorted(s for s in a if s)
        if how == 'pickup':
            s = weighted(rng, {15: 2, 14: 1, 13: 1})
            if ok(s, b):
                b.add(s)
        elif how == 'move' and extra:
            s = rng.choice(extra)
            b.discard(s)
            t = s + rng.choice((-2, -1, 1, 2))
            if 0 < t < 16 and ok(t, b):
                b.add(t)
            else:
                b.add(s)
        elif how == 'drop' and len(extra) >= 2:
            b.discard(rng.choice(extra))
        elif how == 'add':
            cands = {s: w for s, w in weights.items() if ok(s, b)}
            if cands:
                b.add(weighted(rng, cands))
        if b != a:
            break
    return tuple(sorted(a)), tuple(sorted(b))


def _cell_notes(cell: str, offset: int) -> list[tuple[int, float, bool]]:
    notes = CELLS[cell]
    return [(offset + s, d, i == 0 or s % 4 == 0) for i, (s, d) in enumerate(notes)]


_STEP_W = {0: 1.0, 1: 3.0, -1: 3.0, 2: 2.0, -2: 2.0, 3: 0.8, -3: 0.8, 4: 0.5, -4: 0.5, 5: 0.3, -5: 0.3}
_STABLE = (-7, -5, -3, 0, 2, 4, 7, 9)


def _walk(rng, n: int, start: int, lo: int = -3, hi: int = 9) -> list[int]:
    degs = [start]
    for _ in range(n - 1):
        prev = degs[-1]
        last_iv = degs[-1] - degs[-2] if len(degs) >= 2 else 0
        opts = dict(_STEP_W)
        if abs(last_iv) >= 3:                   # gap fill: step back after a leap
            opts = {iv: w for iv, w in opts.items() if iv * last_iv < 0 and abs(iv) <= 2}
        if len(degs) >= 3 and degs[-1] == degs[-2] == degs[-3]:
            opts.pop(0, None)
        opts = {iv: w for iv, w in opts.items() if lo <= prev + iv <= hi} or {(-1 if prev > lo else 1): 1}
        degs.append(prev + weighted(rng, opts))
    return degs


def _close(degs: list[int], targets=_STABLE) -> list[int]:
    out = list(degs)
    out[-1] = min(targets, key=lambda t: (abs(t - out[-1]), t))
    return out


def _sound_line(pitches: list[int]) -> bool:
    """A singable hook line: at least 4 pitch classes over a perfect fourth or
    more, at least one change of direction, no three equal notes in a row."""
    if len(set(pitches)) < 4 or max(pitches) - min(pitches) < 5:
        return False
    if any(a == b == c for a, b, c in zip(pitches, pitches[1:], pitches[2:])):
        return False
    moves = [(b > a) - (b < a) for a, b in zip(pitches, pitches[1:]) if b != a]
    return any(x != y for x, y in zip(moves, moves[1:]))


def make_motif(rng, cells: tuple[str, ...], avoid: set, fit, sparse: bool = False) -> Motif:
    """A 2-bar hook: cell A in bar 1; bar 2 restates it a third away (sequence),
    gives it a new ending, or answers with a contrasting cell of similar density.

    `fit(notes)` realises (step, degree, strong) notes over the composition's
    first chord; a candidate is kept only if that realisation is a sound line
    and its two bars differ, so the motif survives being fitted to chords."""
    best = None
    for attempt in range(80):
        c1 = rng.choice(cells)
        form = weighted(rng, {'sequence': 3, 'vary': 3, 'contrast': 2})
        if form == 'contrast':
            others = [c for c in cells if c != c1 and abs(len(CELLS[c]) - len(CELLS[c1])) <= 2]
            c2 = rng.choice(others) if others else c1
        else:
            c2 = c1
        bar1 = _cell_notes(c1, 0)
        bar2 = _cell_notes(c2, 16)
        start = weighted(rng, {0: 1, 2: 1.5, 4: 2})
        d1 = _walk(rng, len(bar1), start)
        if form == 'sequence':                  # a third (or fourth) away: lands on other chord tones
            shift = weighted(rng, {-2: 2, 2: 2, 3: 1, -3: 1})
            d2 = [d + shift for d in d1]
        elif form == 'vary':                    # same rhythm, a new ending over the last two notes
            d2 = list(d1)
            d2[-1] += rng.choice((-3, -2, 2, 3))
            if len(d2) >= 3:
                d2[-2] += rng.choice((-1, 1))
        else:
            d2 = _walk(rng, len(bar2), d1[-1] + rng.choice((-2, -1, 1, 2)))
        degs = _close(d1 + d2)
        if sparse:
            degs = [max(-3, min(7, d)) for d in degs]
        notes = tuple(MotifNote(s, d, g, strong) for (s, d, strong), g in zip(bar1 + bar2, degs))
        m = Motif(notes, (c1, c2))
        if m.signature() in avoid:
            continue
        pitches = fit(m)
        half = sum(1 for n in m.notes if n.step < 16)
        bars_differ = pitches[:half] != pitches[half:] or c1 != c2
        if _sound_line(pitches) and bars_differ:
            return m
        if best is None and bars_differ:
            best = m
    return best or m


def make_comp_rhythm(rng, style: str, motif: Motif) -> tuple[tuple[int, float], ...]:
    """Comping hits for one 2-bar unit, placed mostly where the hook rests."""
    if style == 'held':
        return ((0, 16.0), (16, 16.0))
    busy = set()
    for n in motif.notes:
        busy.update({n.step - 1, n.step, n.step + 1})
    if style == 'neo':
        hits = [(0, 6.0), (16, 6.0)]
        cands = [s for s in (6, 10, 14, 22, 26, 30) if s not in busy] or [10, 26]
        for s in sorted(rng.sample(cands, min(len(cands), rng.choice((2, 3))))):
            hits.append((s, 3.0))
        return tuple(sorted(hits))
    cands = [s for s in range(32) if (s % 2 == 0 or s % 4 == 3) and s not in busy]
    weights = {s: (2.0 if s % 4 in (2, 3) else 1.0) for s in cands}
    k = rng.choice((3, 4, 5))
    hits = set()
    if rng.random() < 0.5:
        hits.add(0)
    while len(hits) < k and weights:
        s = weighted(rng, weights)
        weights.pop(s)
        if all(abs(s - h) >= 2 for h in hits):
            hits.add(s)
    return tuple((s, rng.choice((1.0, 1.5, 2.0))) for s in sorted(hits))


def create_spec(index: int, seed: int, retired_loops: set, retired_motifs: set,
                avoid_substyle: Optional[str] = None) -> CompositionSpec:
    rng = random.Random(seed)
    sw = {k: (0.4 if k == avoid_substyle else 1.0) for k in SUBSTYLES}
    substyle = weighted(rng, sw)
    sub = SUBSTYLES[substyle]
    palette = dict(rng.choice(sub['palettes']))
    quality = {r: rng.choice(q) for r, q in sorted(sub['quality'].items())}
    loop_a = make_loop(rng, sub, quality, 'i', set(retired_loops))
    loop_b = make_loop(rng, sub, quality, None, set(retired_loops) | {loop_a.romans()}, lead_to_tonic=True)
    kick_a, kick_b = make_kicks(rng, sub['kick'])
    p_lo, p_hi = sub['hat_odd']
    p = rng.uniform(p_lo, p_hi)
    hat_mask = tuple(s for s in range(16) if s % 2 == 0 or rng.random() < p + (0.2 if s % 4 == 3 else 0.0))
    if sum(1 for s in hat_mask if s % 2) < 2:
        hat_mask = tuple(sorted(set(hat_mask) | {7, 15}))
    open_hats = tuple(sorted(rng.sample((6, 14, 10), rng.choice((1, 1, 2)))))
    kicks = set(kick_a) | set(kick_b)
    ghost_cands = [s for s in (3, 7, 9, 10, 14, 15, 6) if s not in kicks and s not in open_hats]
    ghosts = tuple(sorted(rng.sample(ghost_cands, min(len(ghost_cands), rng.choice((2, 3))))))
    hook_prog = palette['hook']
    lo, hi = HOOK_REGISTER[hook_prog]
    key_pc = rng.randrange(12)
    hook_tonic = place(key_pc, lo + 3, lo + 14, lo + 8)
    mode = _mode_for(loop_a, loop_b)

    def fit(m: Motif, chord: Chord = loop_a.bars[0][0][1]) -> list[int]:
        return [p for _, p in fit_line(m.notes, chord, key_pc, mode, hook_tonic, lo, hi)]

    motif = make_motif(rng, sub['cells'], set(retired_motifs), fit)
    answer = make_motif(rng, sub['answer_cells'], set(retired_motifs) | {motif.signature()},
                        lambda m: fit(m, loop_b.bars[0][0][1]), sparse=True)
    comp_style = weighted(rng, sub['comp'])
    ops_w = dict(sub['ops'])
    op1 = weighted(rng, ops_w)
    ops_w.pop(op1)
    op2 = weighted(rng, ops_w)
    return CompositionSpec(
        comp_id=f'v3h{index}-{seed:08x}', index=index, seed=seed, substyle=substyle,
        tempo=float(rng.randint(*sub['tempo'])), swing=round(rng.uniform(*sub['swing']), 3),
        snare_lag_s=sub['snare_lag_ms'] / 1000.0, key_pc=key_pc, mode=mode,
        palette=tuple(sorted(palette.items())), loop_a=loop_a, loop_b=loop_b,
        kick_a=kick_a, kick_b=kick_b, hat_mask=hat_mask, open_hats=open_hats, ghosts=ghosts,
        snare_pitch=sub['snare'], bass_style=weighted(rng, sub['bass']), comp_style=comp_style,
        comp_rhythm=make_comp_rhythm(rng, comp_style, motif), motif=motif, answer=answer,
        hook_tonic=hook_tonic, hook_range=(lo, hi), form=rng.choice(FORMS), ops=(op1, op2),
    )


# =============================================================================
# Development operators (on the motif, in degree space)
# =============================================================================


def _with(m: Motif, notes) -> Motif:
    return Motif(tuple(sorted(notes, key=lambda n: n.step)), m.cells)


def _endings(m: Motif, finals: tuple[int, ...], approach: tuple[int, ...], hold: bool) -> list[Motif]:
    """Candidate re-endings of `m`, mildest first: the last note moved to each of
    `finals`, then also the note before it moved by each of `approach`."""
    last = m.notes[-1]
    tail = max(last.dur, min(4.0, 32 - last.step)) if hold else last.dur
    out = []
    for t in sorted(finals, key=lambda t: (abs(t - last.deg), t)):
        out.append(_with(m, m.notes[:-1] + (replace(last, deg=t, dur=tail),)))
    if len(m.notes) >= 3:
        pen = m.notes[-2]
        for a in approach:
            for t in sorted(finals, key=lambda t: (abs(t - last.deg), t)):
                out.append(_with(m, m.notes[:-2] + (replace(pen, deg=pen.deg + a), replace(last, deg=t, dur=tail))))
    return out


def _first_audible(cands: list[Motif], base: Motif, spec: CompositionSpec, harmony, u: int,
                   min_frac: float = 0.0) -> Motif:
    """The first candidate whose realised line in unit u differs from `base`'s
    (by at least `min_frac` of its notes when min_frac > 0)."""
    ref = set(_unit_line(spec, harmony, base, u))
    for c in cands:
        line = set(_unit_line(spec, harmony, c, u))
        if min_frac <= 0 and line != ref:
            return c
        if min_frac > 0 and 1 - len(line & ref) / max(len(line), len(ref), 1) >= min_frac:
            return c
    return cands[-1]


def open_ending(m: Motif, spec: CompositionSpec, harmony, u: int) -> Motif:
    """Antecedent: end away from the tonic (2nd or 5th degree), audibly."""
    return _first_audible(_endings(m, (1, 4, -3, 8, 6), (1, -1, 2), hold=False), m, spec, harmony, u)


def closed_ending(m: Motif, spec: CompositionSpec, harmony, u: int) -> Motif:
    """Consequent: end on the tonic, held longer, approached so it is heard as an ending."""
    return _first_audible(_endings(m, (0, 7, -7), (1, -1, 2, -2), hold=True), m, spec, harmony, u)


DEVELOP_ESCALATION = ('sequence', 'invert', 'rhythm', 'fragment', 'displace', 'ornament')


def develop(m: Motif, op: str, key: tuple, cells: tuple[str, ...], spec: CompositionSpec, harmony,
            u: int = 0) -> tuple[Motif, str]:
    """`op` applied to `m`, escalating to the next operator if the result is not
    audibly different from `m` once fitted to the harmony (a third of its
    notes must change). Returns the motif and the operator actually used."""
    order = (op,) + tuple(o for o in DEVELOP_ESCALATION if o != op)
    cands = [(apply_op(m, o, _rng('v3op', *key, o), cells), o) for o in order]
    chosen = _first_audible([c for c, _ in cands], m, spec, harmony, u, min_frac=0.34)
    return chosen, dict((id(c), o) for c, o in cands)[id(chosen)]


def apply_op(m: Motif, op: str, rng, cells: tuple[str, ...]) -> Motif:
    notes = list(m.notes)
    if op == 'sequence':                         # by a third or fourth: moves onto other chord tones
        k = rng.choice((2, -2, 3))
        out = [replace(n, deg=n.deg + k) for n in notes]
    elif op == 'invert':
        pivot = notes[0].deg
        out = [replace(n, deg=max(-5, min(10, 2 * pivot - n.deg))) for n in notes]
    elif op == 'displace':
        out = [replace(n, step=n.step + 2, dur=min(n.dur, 30 - n.step)) for n in notes if n.step + 2 <= 30]
    elif op == 'ornament':
        # upper-neighbour 16th before up to three strong notes that follow a rest
        out = [notes[0]]
        added = 0
        for prev, n in zip(notes, notes[1:]):
            if n.strong and n.step - 1 > prev.step and added < 3:
                out[-1] = replace(out[-1], dur=min(out[-1].dur, n.step - 1 - prev.step))
                out.append(MotifNote(n.step - 1, 1.0, n.deg + 1, False))
                added += 1
            out.append(n)
    elif op == 'fragment':
        head = [n for n in notes if n.step < 16]
        shift = rng.choice((1, -1, 2))
        out = head + [replace(n, step=n.step + 16, deg=n.deg + shift) for n in head]
    else:  # 'rhythm': keep the pitch line, give bar 2 a different cell
        bar2_cells = [c for c in cells if c not in m.cells] or list(cells)
        cell = rng.choice(bar2_cells)
        head = [n for n in notes if n.step < 16]
        tail_degs = [n.deg for n in notes if n.step >= 16] or [head[-1].deg]
        new = _cell_notes(cell, 16)
        degs = (tail_degs + [tail_degs[-1]] * len(new))[:len(new)]
        out = head + [MotifNote(s, d, g, strong) for (s, d, strong), g in zip(new, degs)]
    res = _with(m, out)
    if res.signature() == m.signature() or not res.notes:
        res = _with(m, [replace(n, deg=n.deg + 1) for n in notes])
    return res


# =============================================================================
# Segment planning (the shared plan)
# =============================================================================


def _letter(role: str) -> str:
    return role.rstrip('12')


def plan_segment(state: CompositionState, level: int) -> SegmentPlan:
    """The shared plan for the composition's next segment at `level`.

    Everything except `layers` depends only on the composition and the segment
    ordinal, so the same segment at another level keeps its harmony, hook,
    fills and form position (identity is level-invariant)."""
    spec, o = state.spec, state.ordinal
    form = spec.form
    role = form[o]
    letters = [_letter(r) for r in form]
    section_idx = sum(1 for i in range(1, o + 1) if letters[i] != letters[i - 1])
    first = o == 0 or letters[o - 1] != letters[o]
    last = o == len(form) - 1 or letters[o + 1] != letters[o]
    sub = SUBSTYLES[spec.substyle]
    loops = {'C': (spec.loop_b, spec.loop_b), 'C2': (spec.loop_b, spec.loop_a)}.get(role, (spec.loop_a, spec.loop_a))
    harmony = SegmentPlan.harmony_from(loops)
    m, n = spec.motif, spec.answer
    opened = lambda x, u: open_ending(x, spec, harmony, u)      # noqa: E731
    closed = lambda x, u: closed_ending(x, spec, harmony, u)    # noqa: E731
    op = ''
    if role == 'S1':
        units = (None, None, m, closed(m, 3))
    elif role in ('S', 'R'):
        units = (m, opened(m, 1), m, closed(m, 3))
    elif role == 'V':
        mv, op = develop(m, spec.ops[0], (spec.seed, 0), sub['cells'], spec, harmony)
        units = (mv, opened(mv, 1), mv, closed(mv, 3))
    elif role == 'V2':
        mv, op = develop(m, spec.ops[1], (spec.seed, 1), sub['cells'], spec, harmony)
        units = (mv, opened(mv, 1), m, closed(m, 3))
    elif role == 'C':
        nv, _ = develop(n, 'sequence', (spec.seed, 'answer'), sub['answer_cells'], spec, harmony, 2)
        units = (n, opened(n, 1), nv, opened(nv, 3))
    elif role == 'C2':
        frag, op = develop(m, 'fragment', (spec.seed, 'lead'), sub['cells'], spec, harmony, 2)
        units = (n, opened(n, 1), frag, opened(m, 3))
    else:  # 'R2': return, recall the first development, then close the composition
        mv, op = develop(m, spec.ops[0], (spec.seed, 0), sub['cells'], spec, harmony, 2)
        units = (m, opened(m, 1), mv, closed(m, 3))
    fr = _rng('v3fill', spec.seed, o)
    bar4 = weighted(fr, {'none': 1, 'pickup': 2, 'kickdouble': 1.5, 'openhat': 1.5})
    if o == len(form) - 1 or last:
        bar8 = weighted(fr, {'dropout': 2, 'roll': 2})
    else:
        bar8 = weighted(fr, {'pickup': 2, 'kickdouble': 1.5, 'roll': 1, 'openhat': 1})
    return SegmentPlan(spec=spec, level=int(level), ordinal=o, role=role, section_idx=section_idx,
                       first_of_section=first, last_of_section=last,
                       harmony=harmony, hook_units=units, op=op,
                       fills=(bar4, bar8), layers=LAYERS[int(level)], seed=H('v3seg', spec.seed, o))


# =============================================================================
# Realisation
# =============================================================================


class _Part:
    """Note buffer for one instrument with overlap-safe insertion."""

    def __init__(self, program: int, name: str, is_drum: bool = False):
        self.inst = pretty_midi.Instrument(program=program, is_drum=is_drum, name=name)

    def add(self, pitch: int, start: float, end: float, vel: float, seg_end: float) -> None:
        end = min(end, seg_end - 0.005)
        if end - start < 0.02 or start >= seg_end:
            return
        v = int(max(1, min(127, round(vel))))
        self.inst.notes.append(pretty_midi.Note(velocity=v, pitch=int(pitch), start=start, end=end))

    def finish(self) -> pretty_midi.Instrument:
        """Merge same-pitch strikes closer than 30 ms (a fill hit on a ghost
        note keeps the louder one), then trim a note that would still sound
        when the same pitch strikes again (FluidSynth ends both at the first
        note-off)."""
        notes = sorted(self.inst.notes, key=lambda n: (n.pitch, n.start, -n.velocity))
        kept: list[pretty_midi.Note] = []
        for n in notes:
            if kept and kept[-1].pitch == n.pitch and n.start - kept[-1].start < 0.03:
                kept[-1].velocity = max(kept[-1].velocity, n.velocity)
                kept[-1].end = max(kept[-1].end, n.end)
                continue
            kept.append(n)
        for a, b in zip(kept, kept[1:]):
            if a.pitch == b.pitch and a.end > b.start - 0.01:
                a.end = max(a.start + 0.02, b.start - 0.01)
        self.inst.notes = sorted(kept, key=lambda n: (n.start, n.pitch))
        return self.inst


def _kick_steps(plan: SegmentPlan, bar: int) -> tuple[int, ...]:
    spec = plan.spec
    if 'kick_min' in plan.layers:
        return (0,)
    return spec.kick_a if bar % 2 == 0 else spec.kick_b


def _dropout(plan: SegmentPlan, bar: int, step: int) -> bool:
    return bar == BARS - 1 and plan.fills[1] == 'dropout' and step >= 8


def realize_drums(plan: SegmentPlan, grid: Grid, rng) -> pretty_midi.Instrument:
    spec, L = plan.spec, plan.layers
    lv = plan.level
    seg_end = grid.seg_s
    part = _Part(0, 'drums', is_drum=True)

    def hit(pitch, step, vel, length=0.6, lag=0.0):
        s = grid.t(step) + lag
        part.add(pitch, s, s + length * grid.step_s, vel + rng.randint(-3, 3), seg_end)

    for bar in range(BARS):
        b0 = bar * STEPS_PER_BAR
        kicks = set(_kick_steps(plan, bar))
        fill = plan.fills[0] if bar == 3 else plan.fills[1] if bar == 7 else 'none'
        if fill != 'none' and 'fills_min' not in L and 'fills' not in L:
            fill = 'pickup' if bar == 7 else 'none'
        if 'fills_min' in L and fill == 'roll':
            fill = 'pickup'
        if fill == 'kickdouble':
            kicks |= {14, 15}
        # kick
        for s in sorted(kicks):
            if _dropout(plan, bar, s):
                continue
            vel = DRUM_VEL['kick'][lv] - (8 if s % 4 else 0)
            hit(KICK, b0 + s, vel, 1.0)
        # backbeat (laid back by the composition's snare lag)
        for s in (4, 12):
            hit(spec.snare_pitch, b0 + s, DRUM_VEL['snare'][lv], 1.0, spec.snare_lag_s)
            if 'clap' in L:
                hit(CLAP, b0 + s, DRUM_VEL['clap'][lv], 1.0, spec.snare_lag_s)
        # hats
        if 'hat_q' in L:
            hat_steps = (0, 4, 8, 12)
        elif 'hat_8' in L:
            hat_steps = tuple(range(0, 16, 2))
        else:
            hat_steps = tuple(range(16))        # every 16th; the mask sets the accents
        opens = set(spec.open_hats) if ('open_hat' in L and bar % 2 == 1) else set()
        if fill == 'openhat':
            opens |= {14}
        for s in hat_steps:
            if _dropout(plan, bar, s):
                continue
            accent = 1.0 if s % 4 == 0 else 0.9 if s % 2 == 0 else 0.76 if s in spec.hat_mask else 0.52
            pitch = OPEN_HAT if s in opens else HAT
            hit(pitch, b0 + s, DRUM_VEL['hat'][lv] * accent, 1.6 if pitch == OPEN_HAT else 0.5)
        # ghost snares
        if 'ghost' in L:
            for s in spec.ghosts:
                if s not in kicks and not _dropout(plan, bar, s):
                    hit(SNARE_RIM if spec.substyle == 'soul' else spec.snare_pitch, b0 + s,
                        DRUM_VEL['ghost'][lv], 0.5, spec.snare_lag_s)
        # auxiliary percussion
        if 'perc' in L:
            for s in (4, 12):
                hit(TAMBOURINE, b0 + s, DRUM_VEL['perc'][lv] + 6, 0.5, spec.snare_lag_s)
            for s in (2, 6, 10, 14):
                if not _dropout(plan, bar, s):
                    hit(MARACAS, b0 + s, DRUM_VEL['perc'][lv], 0.4)
        # fills on the last beat of bars 4 and 8
        if fill == 'pickup':
            hit(spec.snare_pitch, b0 + 14, DRUM_VEL['snare'][lv] * 0.55, 0.5)
            hit(spec.snare_pitch, b0 + 15, DRUM_VEL['snare'][lv] * 0.75, 0.5)
        elif fill == 'roll':
            for i, s in enumerate((13, 14, 15)):
                hit(spec.snare_pitch, b0 + s, DRUM_VEL['snare'][lv] * (0.55 + 0.15 * i), 0.5)
        elif fill == 'dropout':
            hit(spec.snare_pitch, b0 + 15, DRUM_VEL['snare'][lv] * 0.8, 0.5)
        if bar == 0 and 'crash' in L and plan.first_of_section and plan.ordinal > 0:
            hit(CRASH, b0, 78, 8.0)
    return part.finish()


def realize_bass(plan: SegmentPlan, grid: Grid, rng) -> pretty_midi.Instrument:
    spec, L = plan.spec, plan.layers
    key = spec.key_pc
    part = _Part(spec.program('bass'), 'bass')
    seg_end = grid.seg_s
    changes = set(plan.changes())
    onsets: list[tuple[int, str]] = []
    for bar in range(BARS):
        b0 = bar * STEPS_PER_BAR
        steps = {s - b0: 'change' for s in changes if b0 <= s < b0 + STEPS_PER_BAR}
        steps.setdefault(0, 'change')
        if 'bass' in L:
            kicks = _kick_steps(plan, bar)
            if spec.bass_style == 'sustain':
                kicks = tuple(s for s in kicks if s in (0, 8, 10, 11))
            for s in kicks:
                steps.setdefault(s, 'kick')
        if 'bass_pickup' in L and bar < BARS - 1:
            nxt = b0 + STEPS_PER_BAR
            if plan.chord_at(nxt) != plan.chord_at(nxt - 1) and 15 not in steps and 14 not in steps:
                steps[15] = 'pickup'
        for s, why in sorted(steps.items()):
            if not _dropout(plan, bar, s):
                onsets.append((b0 + s, why))
    prev_pitch = None
    tone_idx = 0
    for i, (g, why) in enumerate(onsets):
        nxt = onsets[i + 1][0] if i + 1 < len(onsets) else BARS * STEPS_PER_BAR
        if plan.fills[1] == 'dropout' and g < 120:
            nxt = min(nxt, 120)
        chord = plan.chord_at(g)
        root = place(chord.root_pc(key), BASS_LO, BASS_HI, BASS_CENTER)
        vel = MEL_BASE['bass'] + MEL_OFFSET[plan.level] + (6 if g % 16 == 0 else 0)
        if why == 'change' or g % 16 == 0:
            pitch, tone_idx = root, 0
        elif why == 'pickup':
            target = place(plan.chord_at(g + 1).root_pc(key), BASS_LO, BASS_HI, BASS_CENTER)
            pitch = target - 1 if spec.bass_style != 'walk' else target + (2 if target + 2 <= BASS_HI else -2)
            vel -= 10
        elif spec.bass_style == 'lock_octave' and g % 4 and prev_pitch == root and root + 12 <= 55:
            pitch = root + 12
            vel -= 6
        elif spec.bass_style == 'walk':
            tones = sorted({place(pc, BASS_LO, BASS_HI + 7, root + 5) for pc in chord.pcs(key)[:4]})
            tone_idx = (tone_idx + 1) % len(tones)
            pitch = tones[tone_idx]
        else:
            pitch = root
        legato = {'lock': 0.7, 'lock_octave': 0.55, 'walk': 0.9, 'sustain': 0.97}[spec.bass_style]
        length = max(1.0, min(16.0, (nxt - g) * legato))
        s, e = grid.span(g, length)
        part.add(pitch, s, e, vel + rng.randint(-2, 2), seg_end)
        prev_pitch = pitch
    return part.finish()


def _hook_floor(hook: list, a: float, b: float) -> Optional[int]:
    """Lowest hook pitch sounding in steps [a, b) (the full line, whatever the level)."""
    ps = [p for g, p, d, _ in hook if g < b and a < g + max(d, 1.0)]
    return min(ps) if ps else None


def _voicing_pcs(chord: Chord, key: int, substyle: str) -> tuple[int, ...]:
    pcs = chord.pcs(key)
    if len(pcs) >= 5:                       # 9th chords: drop the fifth
        pcs = (pcs[0], pcs[1], pcs[3], pcs[4]) if substyle != 'soul' else (pcs[1], pcs[3], pcs[4], pcs[2])
    return pcs


def realize_chords(plan: SegmentPlan, grid: Grid, rng) -> pretty_midi.Instrument:
    spec, L = plan.spec, plan.layers
    key = spec.key_pc
    prog = spec.program('chords')
    lo, hi = CHORD_REGISTER[prog]
    part = _Part(prog, 'chords')
    seg_end = grid.seg_s
    style = 'held' if 'chords_held' in L else spec.comp_style
    hits: list[tuple[int, float]] = []
    if style == 'held':
        bounds = list(plan.changes()) + [BARS * STEPS_PER_BAR]
        for a, b in zip(bounds, bounds[1:]):
            if b - a > STEPS_PER_BAR and 'chords_held' not in L:
                for s in range(a, b, STEPS_PER_BAR):
                    hits.append((s, min(STEPS_PER_BAR, b - s)))
            else:
                hits.append((a, b - a))
    else:
        for unit in range(BARS // 2):
            for s, d in spec.comp_rhythm:
                if 'chords_8' in L and s % 2:
                    continue
                hits.append((unit * 32 + s, d))
        covered = {s for s, _ in hits}
        for c in plan.changes():                # state every chord change
            if not any(abs(c - s) <= 2 for s in covered):
                hits.append((c, 2.0 if style == 'stabs' else 6.0))
        hits.sort()
    prev = None
    hook = hook_notes(plan)
    for i, (g, d) in enumerate(hits):
        nxt = hits[i + 1][0] if i + 1 < len(hits) else BARS * STEPS_PER_BAR
        chord = plan.chord_at(g)
        if g % 16 >= 14 and plan.chord_at(g - g % 16 + 16) != chord and g - g % 16 + 16 < BARS * STEPS_PER_BAR:
            chord = plan.chord_at(g - g % 16 + 16)          # anticipation of the next bar's chord
        length = min(d, nxt - g) * (0.95 if style != 'stabs' else 0.8)
        # keep the voicing under the melody it accompanies
        floor = _hook_floor(hook, g, g + max(length, 1.0))
        top = hi if floor is None or floor - 1 < lo + 12 else min(hi, floor - 1)
        voicing = lead_voice(_voicing_pcs(chord, key, spec.substyle), prev, lo, top, min((lo + hi) / 2, top - 6))
        prev = voicing
        s, e = grid.span(g, max(0.8, length))
        vel = MEL_BASE['chords'] + MEL_OFFSET[plan.level] + (4 if g % 4 else 0)
        for p in voicing:
            part.add(p, s, e, vel + rng.randint(-3, 3), seg_end)
    return part.finish()


def fit_line(notes, chord, key_pc: int, mode: str, tonic: int, lo: int, hi: int,
             prev: Optional[int] = None, prev_deg: Optional[int] = None) -> list[tuple[int, int]]:
    """(step, pitch) of motif notes fitted to the harmony: strong notes on chord
    tones, the others avoiding semitone clashes, each moving in the direction
    the motif's degrees intend. `chord` is a Chord or a step -> Chord function."""
    chord_at = chord if callable(chord) else (lambda s: chord)
    out = []
    for n in notes:
        c = chord_at(n.step)
        raw = degree_to_midi(n.deg, key_pc, mode, tonic)
        allowed = c.core_pcs(key_pc) if n.strong else melodic_pcs(c, key_pc, mode)
        direction = 0 if prev_deg is None else (n.deg > prev_deg) - (n.deg < prev_deg)
        p = directed(raw, prev, direction, allowed, lo, hi)
        out.append((n.step, p))
        prev, prev_deg = p, n.deg
    return out


def _unit_line(spec: CompositionSpec, harmony, motif: Motif, u: int) -> tuple:
    """The realised line of `motif` alone in 2-bar unit u of a segment's harmony."""
    return tuple(fit_line(motif.notes, lambda s: _chord_at(harmony, u * 32 + s), spec.key_pc, spec.mode,
                          spec.hook_tonic, *spec.hook_range))


def _chord_at(harmony, step: float) -> Chord:
    cur = harmony[0][1]
    for s, c in harmony:
        if s > step + 1e-9:
            break
        cur = c
    return cur


def hook_notes(plan: SegmentPlan) -> list[tuple[int, int, float, bool]]:
    """(global step, pitch, length in steps, strong) of the hook, fitted to the harmony."""
    spec = plan.spec
    out = []
    prev, prev_deg = None, None
    for u, motif in enumerate(plan.hook_units):
        if motif is None:
            continue
        notes = [n for n in motif.notes if u * 32 + n.step < BARS * STEPS_PER_BAR]
        line = fit_line(notes, lambda s, u=u: plan.chord_at(u * 32 + s), spec.key_pc, spec.mode,
                        spec.hook_tonic, *spec.hook_range, prev=prev, prev_deg=prev_deg)
        for j, (n, (_, pitch)) in enumerate(zip(notes, line)):
            nxt = notes[j + 1].step if j + 1 < len(notes) else 32
            out.append((u * 32 + n.step, pitch, min(n.dur, nxt - n.step), n.strong))
        if notes:
            prev, prev_deg = line[-1][1], notes[-1].deg
    return out


def realize_hook(plan: SegmentPlan, grid: Grid, rng, program: int, name: str = 'hook',
                 transpose: int = 0, vel_base: Optional[int] = None) -> pretty_midi.Instrument:
    part = _Part(program, name)
    seg_end = grid.seg_s
    artic = ARTICULATION.get(program, 0.8)
    base = (MEL_BASE['hook'] if vel_base is None else vel_base) + MEL_OFFSET[plan.level]
    for g, pitch, length, strong in hook_notes(plan):
        if 'hook_anchor' in plan.layers and not strong:
            continue
        s, e = grid.span(g, max(0.5, length * artic))
        arch = 4 if (g % 32) < 16 else 0                     # phrase arch: first bar of a unit leans in
        part.add(pitch + transpose, s, e, base + arch + (6 if strong else 0) + rng.randint(-3, 3), seg_end)
    return part.finish()


def realize_counter(plan: SegmentPlan, grid: Grid, rng) -> pretty_midi.Instrument:
    """Sustained guide tones (3rds / 7ths), voice-led across the changes."""
    spec = plan.spec
    key = spec.key_pc
    part = _Part(spec.program('counter'), 'counter')
    seg_end = grid.seg_s
    bounds = list(plan.changes()) + [BARS * STEPS_PER_BAR]
    prev = None
    base = MEL_BASE['counter'] + MEL_OFFSET[plan.level]
    hook = hook_notes(plan)
    for a, b in zip(bounds, bounds[1:]):
        chord = plan.chord_at(a)
        r = chord.root_pc(key)
        ivs = [i for i in chord.pcs(key)]
        guides = [(r + iv) % 12 for iv in (3, 4, 10, 11) if (r + iv) % 12 in ivs] or list(chord.core_pcs(key))
        floor = _hook_floor(hook, a, b)               # stay a minor third or more under the melody,
        hi_c = COUNTER_HI if floor is None else min(COUNTER_HI, floor - 3)
        if hi_c < COUNTER_LO + 2:                     # and rest while the melody is down in its register
            continue
        lo_c = hi_c - 14
        target = prev if prev is not None else hi_c - 5
        cands = [place(pc, lo_c, hi_c, target) for pc in guides]
        pitch = min(cands, key=lambda p: (abs(p - target), p))
        segs = [(a, b)]
        if 'counter_active' in plan.layers and b - a >= 16:
            segs = [(a, a + (b - a) // 2), (a + (b - a) // 2, b)]
        for k, (x, y) in enumerate(segs):
            p = pitch
            if k == 1:
                others = [c for c in cands if c != pitch] or [pitch]
                p = min(others, key=lambda q: (abs(q - pitch), q))
            s, e = grid.span(x, (y - x) * 0.97)
            part.add(p, s, e, base + rng.randint(-2, 2), seg_end)
            prev = p
    return part.finish()


def realize(plan: SegmentPlan, tempo: Optional[float] = None) -> pretty_midi.PrettyMIDI:
    """MIDI for one segment. `tempo` overrides the composition tempo (the
    runner-compatible 'tier' tempo policy); everything else is the plan's."""
    spec = plan.spec
    grid = Grid(tempo or spec.tempo, spec.swing)
    pm = pretty_midi.PrettyMIDI(initial_tempo=grid.tempo)
    seeds = {k: _rng('v3real', plan.seed, plan.level, k) for k in ('drums', 'bass', 'chords', 'hook', 'counter', 'double')}
    # the contrast's second motif speaks through the palette's second lead voice; the
    # return brings back the original sound (channel volume keeps both level-matched)
    contrast = plan.role in ('C', 'C2')
    hook_prog = spec.program('double') if contrast else spec.program('hook')
    pm.instruments.append(realize_drums(plan, grid, seeds['drums']))
    pm.instruments.append(realize_bass(plan, grid, seeds['bass']))
    pm.instruments.append(realize_chords(plan, grid, seeds['chords']))
    pm.instruments.append(realize_hook(plan, grid, seeds['hook'], hook_prog))
    if 'counter' in plan.layers:
        pm.instruments.append(realize_counter(plan, grid, seeds['counter']))
    if 'double' in plan.layers:
        dbl = spec.program('hook') if contrast else spec.program('double')
        top = max((p for _, p, _, _ in hook_notes(plan)), default=0)
        pm.instruments.append(realize_hook(plan, grid, seeds['double'], dbl, 'double',
                                           transpose=12 if top + 12 <= 100 else 0, vel_base=MEL_BASE['double']))
    pm.instruments = [i for i in pm.instruments if i.notes]
    for inst in pm.instruments:
        if not inst.is_drum:
            cc7 = channel_volume(inst.program, inst.name, spec.mix_trim_db)
            inst.control_changes.append(pretty_midi.ControlChange(7, cc7, 0.0))
    return pm


def calibrate_spec(spec: CompositionSpec, table: dict) -> CompositionSpec:
    """Set the composition's melodic trim so its level-3 statement is predicted
    to meet the table's loudness target (the locked v2c hip-hop:3 level on that
    soundfont). Drums are left as they are; the trim is bounded."""
    from composer.v3.levels import predict_lufs

    o = next((i for i, r in enumerate(spec.form) if r == 'S'), 0)
    trim = 0.0
    for _ in range(3):                         # CC7 rounding and the 127 cap: settle in a few steps
        s = replace(spec, mix_trim_db=trim)
        pm = realize(plan_segment(CompositionState(s, ordinal=o), 3))
        dur = BARS * 240.0 / spec.tempo
        e_drums = 10 ** (predict_lufs(pm, dur, table, 'drums') / 10)
        e_mel = 10 ** (predict_lufs(pm, dur, table, 'melodic') / 10)
        need = 10 ** (table['target_lufs_l3'] / 10) - e_drums
        step = MIX_TRIM_RANGE[0] if need <= 0 else 10 * math.log10(need / e_mel)
        trim = max(MIX_TRIM_RANGE[0], min(MIX_TRIM_RANGE[1], trim + step))
        if abs(step) < 0.1:
            break
    return replace(spec, mix_trim_db=round(trim, 2))


def segment_info(plan: SegmentPlan) -> dict:
    spec = plan.spec
    return {
        'gen_version': GEN_VERSION, 'composition_id': spec.comp_id, 'composition_idx': spec.index,
        'substyle': spec.substyle, 'key': f'{"C C# D Eb E F F# G Ab A Bb B".split()[spec.key_pc]} {spec.mode}',
        'comp_tempo_bpm': spec.tempo, 'swing': spec.swing, 'role': plan.role, 'section_idx': plan.section_idx,
        'ordinal': plan.ordinal, 'level': plan.level, 'op': plan.op, 'fills': '/'.join(plan.fills),
        'loop_a': '-'.join(c.name(spec.key_pc) for bar in spec.loop_a.bars for _, c in bar),
        'loop_b': '-'.join(c.name(spec.key_pc) for bar in spec.loop_b.bars for _, c in bar),
        'palette': ','.join(f'{r}:{p}' for r, p in spec.palette), 'bass_style': spec.bass_style,
        'comp_style': spec.comp_style, 'kick_a': spec.kick_a, 'kick_b': spec.kick_b,
        'form': '-'.join(spec.form), 'ops': '/'.join(spec.ops), 'cells': '/'.join(spec.motif.cells),
    }
