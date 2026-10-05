"""
Latin development policy (v2c.latin.0) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.16).

Opt-in only (SessionComposer(develop=True)); not used by the live runner.

Material
--------
composer._gen_latin: one chord per bar from four orders of Cmin / A#maj / G#maj /
Gmaj (a 4-bar loop played twice, so bars b and b + 4 share a chord). The nylon
(program 24) plays the chord's root-position triad in octave 4 (48-65) on 2 / 3
/ 4 off-beats per bar (latin:1-2 / 3 / 4-5), each note 0.9 eighth long at
velocity 70-85; the piano plays root + third in octave 5 on beats 1 and 3 (and
4 at latin:4-5), the bass a tumbao, the percussion the clave. There is no
melody: the nylon's top voice is the triad's fifth (G, F, D#, D), so the loop's
top line leaps (up to 10) and is the same in every bar of a chord.

Source statistics (latin:1-5, stims 1/2): every v1 seed plays the same pitch
multiset (the progressions only reorder the chords), so the pitched median
(58.5 at latin:1-3, 59 at latin:4-5), p05 (31 / 31.15) and p95 (72) are
constant per cell and their certification envelopes have zero width. The
median falls on the nylon (A#maj root 58 / Gmaj third 59); p05 is bass, p95
piano.

Rules (pitch-only, nylon only)
------------------------------
- every nylon note keeps its onset, duration and velocity (by voice: low /
  middle / top of its triad); note count, piano, bass, percussion, programs
  and tempo are untouched;
- every triad keeps its pitch-class set (the chord); only its voicing changes:
  a closed voicing (span < 12) inside [source low - REG_SLACK, source high +
  REG_SLACK]; all triads of a bar share a voicing, except the last one of bar 8
  (the ending);
- bars 1-2 are the source's (the anchor: the loop is heard as it was);
- predicted pitched median, p05 and p95 equal the source's (zero-width
  envelopes; predicted from every pitched note, as
  stimulus_metrics.bounded_features); nylon mean within MAX_MEAN_SHIFT;
- top-voice leaps: the largest at most the source's, the mean at most the
  source's (voicing changes only smooth the top line);
- predicted nylon level (composer/levels_latin_nylon.py) within LEVEL_TOL_DB.
  Census over 697 rule-valid candidates (latin:1-5, stims 1/2, 12 visits,
  rendered): predicted level -0.21..+0.44 dB, segment dLUFS -0.08..+0.11
  (r = 0.38 with the prediction), dlow_ratio within -0.015..+0.009; the exact register
  rule already bounds the level, so the filter is a backstop;
- guard (on the realized MIDI): pitch classes per triad, window, register.

Development (visit v, block b = v // 3, pos = v % 3)
---------------------------------------------------
    pos 0   theme: bars 1-4 the source's; bars 5-8 answer them over the same
            chords with a voice-led top line (the rule-passing bars 5-8 whose
            tops move nearest a step of -2 / 0 / +2 per bar, by candidate)
    pos 1   A': bars 5-6 kept (the call), bars 7-8 re-led (the answer) with
            their own ending triad; in odd blocks, for the first half of the
            candidates, bars 5-6 recall an earlier block's theme instead, only
            when its chords are those of the current bars 5-8 (no recall over
            another order), and bars 7-8 answer it
    pos 2   A'': bars 3-4 re-led from bar 2 towards bar 5 (approach) + a new
            ending triad; bar 8's other triads are re-voiced too only when that
            leaves fewer than APPROACH_MIN lines (they re-balance the exact
            register)
Each chord's closed voicings put a different number of notes below the pitched
median, so a single bar or triad can rarely move without breaking the exact
median: every op enumerates its units (two or more bars and the ending triad)
jointly and keeps only rule-passing lines, ranked by the op's top-line score;
later candidates take lower ranks (ranks k // 3 and k // 3 + 1).
History over HISTORY_WINDOW visits (four blocks; latin blocks often repeat
exactly): exact repeats (every role), near repeats (one triad off a visit
before the previous), the bar-4 / bar-8 ending pair and the previous visit's
top contour (developed visits). Gentle pass: two adjacent bars of 3-8 take
the rule-passing voicings that move their tops least, with a new ending triad
where one passes. Fallbacks as the engine: the previous voicing line with
bars 7-8 and the ending re-voiced, then the source.
"""

from __future__ import annotations

import copy
import itertools
import random
from dataclasses import dataclass
from functools import cache
from statistics import mean
from typing import Optional

import numpy as np
import pretty_midi

import stimulus_metrics as sm
from composer import develop_engine as de
from composer import levels_latin_nylon
from composer.develop_engine import DevRecord
from composer.energy_guard import GuardResult

DEV_VERSION = 'v2c.latin.0'
SEED_VERSION = 'v2c.latin.0'
NO_CONTEXT = 'no_nylon'
NYLON = 24
BLOCK_LEN = 3
BARS = 8
HALF = 4
THEME = (0, 1)                      # bars 1-2: the anchor
ANSWER = (4, 5, 6, 7)               # bars 5-8: same chords as bars 1-4
HISTORY_WINDOW = 12                 # four blocks
ENDING_WINDOW = 6
N_CANDIDATES = 12
APPROACH_MIN = 4                    # approach lines below which bar 8's other triads join (compensating)
STEPS = (-2, 0, 2)                  # top-voice target step per bar, by candidate
REG_SLACK = 2                       # semitones beyond the source's nylon range
MAX_MEAN_SHIFT = 0.5                # semitones: nylon mean vs the source (rule-valid lines: |shift| <= 0.375)
LEAP_SLACK = 0.0                    # semitones: mean top-voice leap over the source's
LEVEL_TOL_DB = 0.5                  # predicted nylon level vs the source (rule-valid lines: -0.21..+0.44; plan 6.16)

Voicing = tuple[int, int, int]
Line = tuple[tuple[Voicing, ...], ...]

__all__ = ['DEV_VERSION', 'SEED_VERSION', 'NO_CONTEXT', 'read_context', 'develop', 'unchanged_record', 'POLICY']


@dataclass(frozen=True)
class LatinNylon:
    nylon: int                                   # nylon track index
    chords: tuple[frozenset, ...]                # per bar: the triad's pitch classes
    options: tuple[tuple[Voicing, ...], ...]     # per bar: legal voicings, by top then low
    idx: tuple[tuple[tuple[int, ...], ...], ...] # per bar, per triad: note indices low to top
    base: Line                                   # the source's voicings, per bar per triad
    velocities: tuple[int, ...]                  # per flat position
    others: tuple[int, ...]                      # pitches of the other pitched tracks
    lo: int
    hi: int


def voicings(pcs: frozenset, lo: int, hi: int) -> tuple[Voicing, ...]:
    """Closed voicings (span < 12, one note per pitch class) of a triad in lo..hi."""
    out = [(a, b, c) for a in range(lo, hi + 1) for b in range(a + 1, hi + 1) for c in range(b + 1, min(hi, a + 11) + 1)
           if len({a % 12, b % 12, c % 12}) == 3 and {a % 12, b % 12, c % 12} == pcs]
    return tuple(sorted(out, key=lambda v: (v[-1], v[0])))


def read_context(src: pretty_midi.PrettyMIDI, sched, tempo: float) -> Optional[LatinNylon]:
    nylon = next((i for i, x in enumerate(src.instruments)
                  if not x.is_drum and x.program == NYLON and x.name == 'nylon' and x.notes), None)
    if nylon is None:
        return None
    bar_s = 4 * 60.0 / tempo
    notes = src.instruments[nylon].notes
    stabs: dict[float, list[int]] = {}
    for j, n in enumerate(notes):
        stabs.setdefault(round(n.start, 6), []).append(j)
    bars: list[list[tuple[int, ...]]] = [[] for _ in range(BARS)]
    for t in sorted(stabs):
        b = int(t / bar_s + 1e-6)
        g = tuple(sorted(stabs[t], key=lambda j: notes[j].pitch))
        if not 0 <= b < BARS or len(g) != 3:
            return None
        bars[b].append(g)
    if len({len(g) for g in bars}) != 1 or not bars[0]:
        return None
    base = tuple(tuple(tuple(notes[j].pitch for j in g) for g in bar) for bar in bars)
    if any(len(set(bar)) != 1 for bar in base):
        return None
    chords = tuple(frozenset(p % 12 for p in bar[0]) for bar in base)
    if any(len(ch) != 3 for ch in chords):
        return None
    flat = [p for bar in base for v in bar for p in v]
    lo, hi = min(flat) - REG_SLACK, max(flat) + REG_SLACK
    options = tuple(voicings(ch, lo, hi) for ch in chords)
    if any(bar[0] not in opts for bar, opts in zip(base, options)):
        return None
    return LatinNylon(nylon=nylon, chords=chords, options=options,
                      idx=tuple(tuple(bar) for bar in bars), base=base,
                      velocities=tuple(notes[j].velocity for bar in bars for g in bar for j in g),
                      others=tuple(sorted(n.pitch for i, x in enumerate(src.instruments)
                                          if not x.is_drum and i != nylon for n in x.notes)),
                      lo=lo, hi=hi)


# =============================================================================
# Rules
# =============================================================================


def _flat(v: Line) -> list[int]:
    return [p for bar in v for t in bar for p in t]


def tops(v: Line) -> list[int]:
    return [t[-1] for bar in v for t in bar]


def top_leaps(v: Line) -> list[int]:
    f = tops(v)
    return [abs(b - a) for a, b in zip(f, f[1:])]


def contour(v: Line) -> tuple[int, ...]:
    f = tops(v)
    return tuple((b > a) - (b < a) for a, b in zip(f, f[1:]))


def register(v: Line, c: LatinNylon) -> tuple[float, float, float]:
    """Pitched p05, median and p95 of the segment with nylon voicings v
    (stimulus_metrics.bounded_features: every pitched note)."""
    ps = list(c.others) + _flat(v)
    return tuple(float(np.percentile(ps, q)) for q in (5, 50, 95))


def valid(v: Line, c: LatinNylon) -> bool:
    if len(v) != BARS or any(len(a) != len(b) for a, b in zip(v, c.base)):
        return False
    if v[:len(THEME)] != c.base[:len(THEME)]:
        return False
    if any(t not in opts for bar, opts in zip(v, c.options) for t in bar):
        return False
    if any(len(set(bar)) > 1 for bar in v[:-1]) or len(set(v[-1][:-1])) > 1:
        return False
    if any(abs(a - b) > 1e-9 for a, b in zip(register(v, c), register(c.base, c))):
        return False
    if abs(mean(_flat(v)) - mean(_flat(c.base))) > MAX_MEAN_SHIFT + 1e-9:
        return False
    lv, lb = top_leaps(v), top_leaps(c.base)
    return max(lv) <= max(lb) and mean(lv) <= mean(lb) + LEAP_SLACK + 1e-9


def _valid_record(rec: DevRecord, c: LatinNylon) -> bool:
    return all(valid(p, c) for p in rec.plan)


# =============================================================================
# Operations
# =============================================================================


def _set(v: Line, b: int, t: Voicing) -> Line:
    return v[:b] + (tuple(t for _ in v[b]),) + v[b + 1:]


def _top(v: Line, b: int) -> int:
    return v[b][0][-1]


def _step_tag(step: int) -> str:
    return '-=+'[(step > 0) - (step < 0) + 1]


def revoice(v: Line, c: LatinNylon, bars, end: bool = False) -> list[Line]:
    """Every rule-passing line that re-voices whole `bars` and, if end, bar 8's last
    triad on its own (v itself excluded). Each chord's voicings put a different
    number of notes below the pitched median, so the exact-register rule needs
    two or more units changed together; changes are enumerated jointly (at most
    4 voicings per unit)."""
    units = [c.options[b] for b in bars] + ([c.options[BARS - 1]] if end else [])
    out = []
    for combo in itertools.product(*units):
        w = v
        for b, t in zip(bars, combo):
            w = _set(w, b, t)
        if end:
            w = w[:BARS - 1] + (w[BARS - 1][:-1] + (combo[-1],),)
        if w != v and valid(w, c):
            out.append(w)
    return out


def _flow(w: Line, bars, step: int) -> int:
    """How far the top line over `bars` (from the bar before) is from moving by `step` per bar."""
    t = [_top(w, bars[0] - 1)] + [_top(w, b) for b in bars]
    return sum(abs(y - x - step) for x, y in zip(t, t[1:]))


def _end_move(w: Line) -> int:
    """Top-voice motion into the last triad (the ending gesture)."""
    return abs(w[BARS - 1][-1][-1] - w[BARS - 1][0][-1])


def _pick(ok: list[Line], key, rng: random.Random, depth: int) -> Optional[Line]:
    """One of ranks depth and depth + 1 (later candidates reach further down the
    ranking when history rejects the closest); None if there are none."""
    ranked = sorted(ok, key=lambda w: (key(w), tops(w)))[depth:depth + 2]
    return rng.choice(ranked) if ranked else None


def theme_line(c: LatinNylon, rng: random.Random, step: int, depth: int = 0) -> Line:
    """Bars 5-8 answer the source's bars 1-4 with a voice-led top line."""
    w = _pick(revoice(c.base, c, ANSWER), lambda w: _flow(w, ANSWER, step), rng, depth)
    return c.base if w is None else w


def op_answer(v: Line, c: LatinNylon, rng: random.Random, step: int, depth: int) -> tuple[Line, str]:
    """Bars 7-8 re-led by `step` per bar, with their own ending triad."""
    w = _pick(revoice(v, c, ANSWER[2:], end=True), lambda w: (_flow(w, ANSWER[2:], step), _end_move(w)), rng, depth)
    return (v, 'answer:none') if w is None else (w, f'answer@7-8:{_step_tag(step)}')


def op_approach(v: Line, c: LatinNylon, rng: random.Random, depth: int) -> tuple[Line, str]:
    """Bars 3-4 re-voiced so bar 3 follows bar 2 by a step and bar 4's top lands
    next to bar 5's from below or above (the approach), with a new ending triad
    nearest the old one. Bar 8's other triads join (they re-balance the register:
    at 3 triads per bar a whole bar moves the count below the median in threes)
    when bars 3-4 and the ending triad alone leave fewer than APPROACH_MIN lines."""
    step, side = rng.choice(STEPS), rng.choice((-1, 1))

    def key(w: Line) -> tuple:
        return abs(_top(w, 2) - _top(w, 1) - step) + abs(_top(w, 3) - _top(w, 4) - side), \
            int(w[BARS - 1][0] != v[BARS - 1][0]), abs(w[BARS - 1][-1][-1] - v[BARS - 1][-1][-1])

    tag = ''
    ok = [w for w in revoice(v, c, (2, 3), end=True) if w[BARS - 1][-1] != v[BARS - 1][-1]]
    if len(ok) < APPROACH_MIN:
        ok = [w for w in revoice(v, c, (2, 3, BARS - 1), end=True) if w[BARS - 1][-1] != v[BARS - 1][-1]]
        tag = '+8'
    w = _pick(ok, key, rng, depth)
    return (v, 'approach:none') if w is None else (w, f"approach@3-4{tag}:{_step_tag(step)}{'-+'[side > 0]}+end")


def op_recall(v: Line, c: LatinNylon, rng: random.Random, src: tuple, depth: int) -> tuple[Line, str]:
    """Bars 5-6 restate an earlier block's theme (same chords), bars 7-8 answer it."""
    w = v[:ANSWER[0]] + tuple(src[:2]) + v[ANSWER[2]:]
    ok = revoice(w, c, ANSWER[2:], end=True) + ([w] if valid(w, c) and w != v else [])
    w = _pick(ok, lambda w: (_flow(w, ANSWER[2:], 0), _end_move(w)), rng, depth)
    return (v, 'recall:none') if w is None else (w, 'recall@5-6')


def op_neighbor(v: Line, c: LatinNylon, rng: random.Random) -> tuple[Line, str]:
    """Two adjacent bars of 3-8 take the rule-passing voicings that move their tops
    least, with a new ending triad where one passes (with bar 8's other triads
    if needed; else the old ending)."""
    for b in rng.sample(range(len(THEME), BARS - 1), BARS - 1 - len(THEME)):
        def key(w: Line) -> tuple:
            return sum(abs(_top(w, x) - _top(v, x)) for x in (b, b + 1)), int(w[BARS - 1][0] != v[BARS - 1][0])
        ok = [w for w in revoice(v, c, (b, b + 1), end=True) + revoice(v, c, sorted({b, b + 1, BARS - 1}), end=True)
              if w[BARS - 1][-1] != v[BARS - 1][-1]]
        w = _pick(ok, key, rng, 0)
        if w is not None:
            return w, f'neighbor@{b + 1}-{b + 2}+end'
        w = _pick(revoice(v, c, (b, b + 1)), key, rng, 0)
        if w is not None:
            return w, f'neighbor@{b + 1}-{b + 2}'
    return v, 'neighbor:none'


def _block_theme(records: list[DevRecord], block: int, c: LatinNylon) -> tuple:
    i = block * BLOCK_LEN
    return records[i].theme if i < len(records) else c.base[ANSWER[0]:]


def _recall_source(records: list[DevRecord], block: int, c: LatinNylon, own: tuple) -> Optional[tuple]:
    """The latest earlier block's theme over the current bars 5-8 chords (else None)."""
    for b in range(block - 1, -1, -1):
        i = b * BLOCK_LEN
        if i >= len(records):
            continue
        th = records[i].theme
        if th != own and len(th) == len(ANSWER) and \
                all(len(x) == len(c.base[a]) and frozenset(p % 12 for p in x[0]) == c.chords[a]
                    for a, x in zip(ANSWER, th)):
            return th
    return None


def _draft(c: LatinNylon, records: list[DevRecord], visit: int, k: int, rng: random.Random,
           gentle: bool) -> DevRecord:
    block, pos = divmod(visit, BLOCK_LEN)
    step, depth = STEPS[k % len(STEPS)], k // len(STEPS)
    if pos == 0:
        if gentle:
            w = _pick(revoice(c.base, c, ANSWER[:2]) + revoice(c.base, c, ANSWER[2:]),
                      lambda w: hamming(w, c.base), rng, k)
            m = c.base if w is None else w
            return DevRecord(motif=m, theme=m[ANSWER[0]:], plan=(m,), role='theme', ops=('answer@part',))
        m = theme_line(c, rng, step, depth)
        return DevRecord(motif=m, theme=m[ANSWER[0]:], plan=(m,), role='theme', ops=(f'answer@5-8:{_step_tag(step)}',))
    theme = _block_theme(records, block, c)
    prev = records[visit - 1]
    v = prev.motif if prev.motif != c.base and valid(prev.motif, c) else theme_line(c, rng, 0)
    if gentle:
        m, d = op_neighbor(v, c, rng)
        return DevRecord(motif=m, theme=theme, plan=(m,), role='develop', ops=(d,))
    if pos == 2:
        m, d = op_approach(v, c, rng, depth)
        return DevRecord(motif=m, theme=theme, plan=(m,), role='develop', ops=(d,))
    src = _recall_source(records, block, c, theme) if block % 2 and k < N_CANDIDATES // 2 else None
    if src is not None:
        m, d = op_recall(v, c, rng, src, k // len(STEPS))
        return DevRecord(motif=m, theme=theme, plan=(m,), role='recall', ops=(d,))
    m, d = op_answer(v, c, rng, step, depth)
    return DevRecord(motif=m, theme=theme, plan=(m,), role='develop', ops=(d,))


def hamming(a: Line, b: Line) -> int:
    return sum(x != y for p, q in zip(a, b) for x, y in zip(p, q))


def endings(v: Line) -> tuple[Voicing, Voicing]:
    return v[HALF - 1][-1], v[BARS - 1][-1]


def repeats(rec: DevRecord, recent: list[DevRecord], c: LatinNylon) -> Optional[str]:
    """Exact repeats of any recent visit (every role); developed visits also: near
    (one triad off a visit before the previous), the ending pair over the last
    ENDING_WINDOW visits and the previous visit's top contour."""
    v = rec.motif
    if v in {r.motif for r in recent}:
        return 'history'
    if rec.role == 'theme':
        return None
    if any(len(r.motif) == len(v) and hamming(v, r.motif) <= 1 for r in recent[:-1]):
        return 'near'
    if endings(v) in {endings(r.motif) for r in recent[-ENDING_WINDOW:]}:
        return 'ending'
    if recent and contour(v) == contour(recent[-1].motif):
        return 'contour'
    return None


# =============================================================================
# Level, guard
# =============================================================================


@cache
def note_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_latin_nylon.LEVEL_DB, levels_latin_nylon.VELOCITIES, pitch, velocity)


def nylon_level(v: Line, c: LatinNylon) -> float:
    return sum(note_level(p, vel) for p, vel in zip(_flat(v), c.velocities))


def energy_shift(plan: tuple[Line, ...], aux, c: LatinNylon) -> dict:
    """Predicted nylon level change (dB), nylon mean and top-voice mean change vs the source."""
    f, fb = _flat(plan[0]), _flat(c.base)
    return {'level_db': de.db(nylon_level(plan[0], c), nylon_level(c.base, c)),
            'mean_shift': round(mean(f) - mean(fb), 4),
            'top_shift': round(mean(tops(plan[0])) - mean(tops(c.base)), 4)}


def energy_cost(shift: dict) -> float:
    return round(max(abs(shift['level_db']) / LEVEL_TOL_DB, abs(shift['mean_shift']) / MAX_MEAN_SHIFT), 6)


def realize(src: pretty_midi.PrettyMIDI, c: LatinNylon, plan: tuple[Line, ...]) -> pretty_midi.PrettyMIDI:
    out = copy.deepcopy(src)
    notes = out.instruments[c.nylon].notes
    for bar, gs in zip(plan[0], c.idx):
        for t, g in zip(bar, gs):
            for p, j in zip(t, g):
                notes[j].pitch = p
    return out


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: LatinNylon) -> GuardResult:
    """Only nylon pitches may change; every triad keeps its pitch classes inside the
    window; pitched p05 / median / p95 unchanged."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.nylon].notes
        chord = any({notes[j].pitch % 12 for j in g} != ch for gs, ch in zip(c.idx, c.chords) for g in gs)
        window = any(not c.lo <= notes[j].pitch <= c.hi for gs in c.idx for g in gs for j in g)
        a, b = sm.bounded_features(pm, BARS), sm.bounded_features(src, BARS)
        moved = [f for f in ('pitched_pitch_p05', 'pitched_pitch_median', 'pitched_pitch_p95')
                 if abs(a[f] - b[f]) > 1e-9]
        return (['chord'] if chord else []) + (['window'] if window else []) + moved

    return de.guard(developed, src, {c.nylon: None}, check, de.MAX_PITCH_SHIFT, BARS)


def _previous(prev: DevRecord, rng: random.Random, c: LatinNylon) -> DevRecord:
    """The previous voicing line with bars 7-8 and the ending re-voiced (the source at
    a block start)."""
    v = prev.motif if valid(prev.motif, c) else c.base
    ok = revoice(v, c, ANSWER[2:], end=True)
    if ok:
        e = rng.choice(sorted(ok, key=lambda w: (hamming(w, v), tops(w)))[:2])
        return DevRecord(motif=e, theme=prev.theme, plan=(e,), role='fallback', ops=('answer@7-8:prev',))
    return DevRecord(motif=v, theme=prev.theme, plan=(v,), role='fallback', ops=('answer:none',))


def unchanged_record(c: LatinNylon, records: list[DevRecord]) -> DevRecord:
    return DevRecord(c.base, c.base[ANSWER[0]:], (c.base,), 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=_draft, valid=_valid_record,
    energy=energy_shift, cost=energy_cost, realize=realize, guard=guard,
    previous=_previous, unchanged=unchanged_record, repeats=repeats)


def develop(src: pretty_midi.PrettyMIDI, c: LatinNylon, records: list[DevRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    return de.select(POLICY, src, c, records, visit, seed)
