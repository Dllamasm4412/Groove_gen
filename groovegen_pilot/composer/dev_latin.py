"""
Latin development policy (v2c.latin.1) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.16).

Opt-in only (SessionComposer(develop=True)); live with run_pilot_zero
--generator v2c. v2c.latin.0 developed the nylon only; after the first v2c live
run (2026-10-05: latin2 for several segments "sounded the same all the time")
v2c.latin.1 adds piano and bass development over the same nylon lines (see
"Piano and bass" below; the nylon seed stays v2c.latin.0).

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

Rules (pitch-only; nylon)
-------------------------
- every nylon note keeps its onset, duration and velocity (by voice: low /
  middle / top of its triad); note count, percussion, programs and tempo are
  untouched (piano and bass: pitches only, below);
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

Piano and bass (v2c.latin.1; accompany(), after the nylon)
----------------------------------------------------------
Every visit (fallbacks included) plays one bass and one piano pattern over
bars 5-8 (pos 0: the answer to the source's bars 1-4) or 3-8 (pos 1, 2);
bars 1-2 stay the source's. Pitch-only: every note keeps its onset, duration
and velocity.
    bass    swap (fifth on 2.5, octave on 3), anticipate (the next bar's root
            on 4.5, the tumbao anticipation; not in bar 8), octave (the root's
            octave on 4.5), swap+anticipate
    piano   dyads R3 (root + third, the source), 35 (third + fifth), 5R (fifth +
            root above), each placed nearest the source dyad: '35' / '5R' on
            every onset, 'x>y' x on beat 1 and y after it (motion in the bar)
Each pattern must differ from the previous visit's, and the pair from every
visit in HISTORY_WINDOW (relaxed in turn when nothing passes; 1 repeat in 108
visits, 4 visits apart). Only balanced() pairs are played: the measured
per-pattern effects (ACCOMP_EFFECT) predict the segment's dLUFS and
dlow_ratio within ACCOMP_LUFS_TOL / ACCOMP_LOW_TOL (without it, piano
re-voicings raised the latin:1-2 low_ratio shift to 2.4-3.4x its allowed
value). Pairs are tried in a seeded order; the first whose pitched p05 / median
/ p95 equal the source's (zero-width envelopes; piano and bass sit on either
side of the nylon median, so p05 and p95 decide) and that passes guard() is
played (piano and bass notes are chord tones, the beat-4.5 bass note may be
the next bar's, each inside the source's range +- REG_SLACK). Rendered census
vs v2c.latin.0 (60 segments, latin:1-5, stims 1/2, visits 0-5): segment dLUFS
-0.22..+0.04 (median -0.09), dlow_ratio -0.014..+0.010. Certification --audio
(latin:1-3, stims 1/2, 12 visits): same cell verdicts as v2c.latin.0;
low_ratio and LUFS cell shifts inside their allowance; pulse_clarity shift
latin:1 +0.0144 (allowed 0.0130; v2c.latin.0 +0.0097), latin:2 +0.0092
(allowed 0.0025; v2c.latin.0 +0.0056, already over).
"""

from __future__ import annotations

import copy
import itertools
import random
from dataclasses import dataclass, replace
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

DEV_VERSION = 'v2c.latin.1'
SEED_VERSION = 'v2c.latin.0'        # the nylon's seed: v2c.latin.0 nylon lines are kept
ACCOMP_VERSION = 'v2c.latin.1'      # the piano / bass layer's seed
NO_CONTEXT = 'no_nylon'
NYLON = 24
BASS = 33
PIANO = 0
TUMBAO = (0.0, 1.5, 2.0, 3.5)       # bass beats: root, octave, fifth, root (+ octave on 2.75 at latin:4-5)
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

__all__ = ['DEV_VERSION', 'SEED_VERSION', 'ACCOMP_VERSION', 'NO_CONTEXT', 'read_context', 'develop', 'unchanged_record',
           'POLICY']


@dataclass(frozen=True)
class Accomp:
    """The source's piano and bass, per bar (composer._gen_latin layout)."""
    bass: int                                    # bass track index
    piano: int                                   # piano track index
    bass_at: tuple[tuple[tuple[float, int], ...], ...]               # per bar: (beat, note index)
    piano_at: tuple[tuple[tuple[float, tuple[int, int]], ...], ...]  # per bar: (beat, dyad low / high)
    bass_lo: int
    bass_hi: int
    piano_lo: int
    piano_hi: int


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
    accomp: Optional[Accomp] = None              # None: piano / bass not in the expected layout


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
                      lo=lo, hi=hi, accomp=read_accomp(src, bar_s, chords))


def read_accomp(src: pretty_midi.PrettyMIDI, bar_s: float, chords: tuple[frozenset, ...]) -> Optional[Accomp]:
    """Piano dyads and tumbao bass by bar and beat; None unless every bar has the
    bass on beats 1, 2.5, 3 and 4.5 (+ 3.75) with chord roots on beat 1, and
    piano dyads of chord tones."""
    find = lambda name, prog: next((i for i, x in enumerate(src.instruments)  # noqa: E731
                                    if not x.is_drum and x.name == name and x.program == prog and x.notes), None)
    bass, piano = find('bass', BASS), find('piano', PIANO)
    if bass is None or piano is None:
        return None

    def by_bar(notes):
        out: list[dict[float, list[int]]] = [{} for _ in range(BARS)]
        for j, n in enumerate(notes):
            b = int(n.start / bar_s + 1e-6)
            if not 0 <= b < BARS:
                return None
            out[b].setdefault(round((n.start / bar_s - b) * 4 * 4) / 4, []).append(j)
        return out

    bn, pn = src.instruments[bass].notes, src.instruments[piano].notes
    bb, pb = by_bar(bn), by_bar(pn)
    if bb is None or pb is None:
        return None
    bass_at, piano_at = [], []
    for b, ch in enumerate(chords):
        if not set(TUMBAO) <= set(bb[b]) <= set(TUMBAO) | {2.75} or any(len(v) != 1 for v in bb[b].values()):
            return None
        if bn[bb[b][0.0][0]].pitch % 12 not in ch or not pb[b]:
            return None
        dyads = []
        for beat, js in sorted(pb[b].items()):
            js = sorted(js, key=lambda j: pn[j].pitch)
            if len(js) != 2 or any(pn[j].pitch % 12 not in ch for j in js):
                return None
            dyads.append((beat, (js[0], js[1])))
        bass_at.append(tuple(sorted((beat, js[0]) for beat, js in bb[b].items())))
        piano_at.append(tuple(dyads))
    bp, pp = [n.pitch for n in bn], [n.pitch for n in pn]
    return Accomp(bass=bass, piano=piano, bass_at=tuple(bass_at), piano_at=tuple(piano_at),
                  bass_lo=min(bp) - REG_SLACK, bass_hi=max(bp) + REG_SLACK,
                  piano_lo=min(pp) - REG_SLACK, piano_hi=max(pp) + REG_SLACK)


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


def accomp_failures(pm: pretty_midi.PrettyMIDI, c: LatinNylon) -> list[str]:
    """Piano notes are tones of their bar's chord, bass notes too (the beat-4.5 one
    may anticipate the next bar's), each inside its window."""
    a = c.accomp
    if a is None:
        return []
    bn, pn = pm.instruments[a.bass].notes, pm.instruments[a.piano].notes
    fails = set()
    for b, ch in enumerate(c.chords):
        nxt = c.chords[b + 1] if b + 1 < BARS else ch
        for beat, j in a.bass_at[b]:
            if bn[j].pitch % 12 not in (ch | nxt if beat == TUMBAO[-1] else ch):
                fails.add('bass_chord')
            if not a.bass_lo <= bn[j].pitch <= a.bass_hi:
                fails.add('bass_window')
        for _, js in a.piano_at[b]:
            if any(pn[j].pitch % 12 not in ch for j in js):
                fails.add('piano_chord')
            if any(not a.piano_lo <= pn[j].pitch <= a.piano_hi for j in js):
                fails.add('piano_window')
    return sorted(fails)


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: LatinNylon) -> GuardResult:
    """Only nylon, piano and bass pitches may change (piano and bass only when read
    by read_accomp); every triad keeps its pitch classes inside the window; piano
    and bass as accomp_failures; pitched p05 / median / p95 unchanged."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.nylon].notes
        chord = any({notes[j].pitch % 12 for j in g} != ch for gs, ch in zip(c.idx, c.chords) for g in gs)
        window = any(not c.lo <= notes[j].pitch <= c.hi for gs in c.idx for g in gs for j in g)
        a, b = sm.bounded_features(pm, BARS), sm.bounded_features(src, BARS)
        moved = [f for f in ('pitched_pitch_p05', 'pitched_pitch_median', 'pitched_pitch_p95')
                 if abs(a[f] - b[f]) > 1e-9]
        return (['chord'] if chord else []) + (['window'] if window else []) + accomp_failures(pm, c) + moved

    mutable = {c.nylon: None} | ({} if c.accomp is None else {c.accomp.bass: None, c.accomp.piano: None})
    return de.guard(developed, src, mutable, check, de.MAX_PITCH_SHIFT, BARS)


# =============================================================================
# Piano and bass (v2c.latin.1)
# =============================================================================

ACCOMP_SPANS = {0: tuple(ANSWER), 1: tuple(range(len(THEME), BARS)), 2: tuple(range(len(THEME), BARS))}
BASS_PATTERNS = ('swap', 'anticipate', 'octave', 'swap+anticipate')
PIANO_PATTERNS = ('35', '5R', 'R3>35', 'R3>5R', '35>R3', '5R>35')
# Rendered effect of each pattern alone over bars 3-8 vs the source (dLUFS,
# dlow_ratio; Musyng_Kite, latin:1-3 x stims 1/2/19, 6 segments, 2026-10-05; the
# spread over segments was within +-0.005 low_ratio). Every piano re-voicing
# raises low_ratio (its dyads sit higher, and play quieter); bass swap lowers
# it. A bass 'third' (the chord's third on 2.5: +0.20 LU, +0.0097 low_ratio)
# had no piano pattern to balance it and was dropped.
ACCOMP_EFFECT = {'swap': (-0.078, -0.0093), 'anticipate': (0.002, 0.0), 'octave': (0.047, -0.0001),
                 'swap+anticipate': (-0.077, -0.0094),
                 '35': (-0.050, 0.0059), '5R': (-0.119, 0.0166), 'R3>35': (-0.022, 0.0027),
                 'R3>5R': (-0.053, 0.0073), '35>R3': (-0.028, 0.0032), '5R>35': (-0.087, 0.0120)}
EFFECT_BARS = 6
ACCOMP_LUFS_TOL = 0.15              # LU, predicted segment change
ACCOMP_LOW_TOL = 0.005              # predicted low_ratio change (half the latin:1-2 audio envelope)


def _span_tag(span) -> str:
    return f'{span[0] + 1}-{span[-1] + 1}'


def _degrees(root: int, ch: frozenset) -> tuple[int, int, int]:
    """Root, third and fifth pitch classes of triad ch over root."""
    third = next(p for p in ch if (p - root) % 12 in (3, 4))
    fifth = next(p for p in ch if (p - root) % 12 == 7)
    return root % 12, third, fifth


def predicted_effect(bass: str, piano: str, span) -> tuple[float, float]:
    """Predicted (dLUFS, dlow_ratio) of a pattern pair over `span` (additive, scaled by bars)."""
    k = len(span) / EFFECT_BARS
    return tuple(round(k * (a + b), 4) for a, b in zip(ACCOMP_EFFECT[bass], ACCOMP_EFFECT[piano]))


def balanced(bass: str, piano: str, span) -> bool:
    lufs, low = predicted_effect(bass, piano, span)
    return abs(lufs) <= ACCOMP_LUFS_TOL + 1e-9 and abs(low) <= ACCOMP_LOW_TOL + 1e-9


def bass_line(src: pretty_midi.PrettyMIDI, c: LatinNylon, pattern: str, span) -> Optional[dict[int, int]]:
    """Bass note index -> pitch for `pattern` over the bars of `span` (the tumbao,
    pitch-only): swap = fifth on 2.5, octave on 3; anticipate = the next bar's
    root on 4.5 (not in bar 8: what follows the segment is unknown); octave = the
    root's octave on 4.5. None if a pitch leaves the window."""
    a = c.accomp
    notes = src.instruments[a.bass].notes
    at = [dict(bar) for bar in a.bass_at]
    out = {}
    for b in span:
        p = {beat: notes[j].pitch for beat, j in at[b].items()}
        new = {}
        for op in pattern.split('+'):
            if op == 'swap':
                new[1.5], new[2.0] = p[2.0], p[1.5]
            elif op == 'anticipate' and b + 1 < BARS:
                new[3.5] = notes[at[b + 1][0.0]].pitch
            elif op == 'octave':
                new[3.5] = p[0.0] + 12
        if any(x is None or not a.bass_lo <= x <= a.bass_hi for x in new.values()):
            return None
        out.update({at[b][beat]: x for beat, x in new.items()})
    return out


def _dyad(kind: str, root: int, ch: frozenset, low: int, a: Accomp) -> Optional[tuple[int, int]]:
    """Dyad `kind` of the chord (R3 root + third, 35 third + fifth, 5R fifth + the
    root above) with its low note nearest `low`, both inside the piano window."""
    r, t, f = _degrees(root, ch)
    pcs = {'R3': (r, t), '35': (t, f), '5R': (f, r)}[kind]
    gap = (pcs[1] - pcs[0]) % 12
    lows = [p for p in range(a.piano_lo, a.piano_hi - gap + 1) if p % 12 == pcs[0]]
    if not lows:
        return None
    x = min(lows, key=lambda p: (abs(p - low), p))
    return x, x + gap


def piano_line(src: pretty_midi.PrettyMIDI, c: LatinNylon, pattern: str, span) -> Optional[dict[int, int]]:
    """Piano note index -> pitch for `pattern` over the bars of `span`: 'x' plays
    dyad x on every onset; 'x>y' plays x on beat 1 and y on the later onsets
    (motion inside the bar). Each dyad sits nearest the source's. None if a
    dyad does not fit the window."""
    a = c.accomp
    notes, bass = src.instruments[a.piano].notes, src.instruments[a.bass].notes
    first, _, rest = pattern.partition('>')
    out = {}
    for b in span:
        root = bass[dict(a.bass_at[b])[0.0]].pitch
        for k, (_, (lo, hi)) in enumerate(a.piano_at[b]):
            d = _dyad(first if k == 0 or not rest else rest, root, c.chords[b], notes[lo].pitch, a)
            if d is None:
                return None
            out[lo], out[hi] = d
    return out


def _accomp_of(rec: DevRecord) -> Optional[tuple[str, str]]:
    """(bass pattern, piano pattern) of a record's ops, else None."""
    pat = {op.split(':', 1)[0]: op.split(':', 1)[1].split('@')[0] for op in rec.ops
           if op.startswith(('bass:', 'piano:'))}
    return (pat['bass'], pat['piano']) if {'bass', 'piano'} <= set(pat) else None


def accompany(out: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: LatinNylon,
              records: list[DevRecord], visit: int, seed: int) -> tuple[pretty_midi.PrettyMIDI, tuple[str, ...]]:
    """Piano and bass development over the (developed) nylon `out`: one bass and one
    piano pattern over bars 5-8 (pos 0) or 3-8 (pos 1, 2; the other span when
    nothing passes), bars 1-2 the source's. Both patterns differ from the previous
    visit's, and the pair from every visit in HISTORY_WINDOW; those rules relax in
    turn when nothing passes. Only balanced() pairs are played. Pairs are tried in
    a seeded order; the first whose pitched p05 / median / p95 equal the source's
    and that passes guard() wins."""
    a = c.accomp
    if a is None:
        return out, ('accomp:none',)
    rng = random.Random(f'{ACCOMP_VERSION}:{seed}')
    pairs = list(itertools.product(BASS_PATTERNS, PIANO_PATTERNS))
    rng.shuffle(pairs)
    pos = visit % BLOCK_LEN
    spans = (ACCOMP_SPANS[pos], ACCOMP_SPANS[1 if pos == 0 else 0])
    prev = _accomp_of(records[-1]) if records else None
    recent = {_accomp_of(r) for r in records[-HISTORY_WINDOW:]}
    fixed = [n.pitch for i, x in enumerate(out.instruments) if not x.is_drum and i not in (a.bass, a.piano)
             for n in x.notes]
    want = tuple(float(np.percentile([n.pitch for x in src.instruments if not x.is_drum for n in x.notes], q))
                 for q in (5, 50, 95))
    for strict in (2, 1, 0):
        for span in spans:
            for bp, pp in pairs:
                if strict >= 1 and prev is not None and (bp == prev[0] or pp == prev[1]):
                    continue
                if strict >= 2 and (bp, pp) in recent:
                    continue
                if not balanced(bp, pp, span):
                    continue
                bass, piano = bass_line(src, c, bp, span), piano_line(src, c, pp, span)
                if bass is None or piano is None:
                    continue
                ps = fixed + [bass.get(j, n.pitch) for j, n in enumerate(out.instruments[a.bass].notes)] \
                    + [piano.get(j, n.pitch) for j, n in enumerate(out.instruments[a.piano].notes)]
                if any(abs(float(np.percentile(ps, q)) - w) > 1e-9 for q, w in zip((5, 50, 95), want)):
                    continue
                pm = copy.deepcopy(out)
                for track, line in ((a.bass, bass), (a.piano, piano)):
                    for j, p in line.items():
                        pm.instruments[track].notes[j].pitch = p
                if guard(pm, src, c).ok:
                    return pm, (f'bass:{bp}@{_span_tag(span)}', f'piano:{pp}@{_span_tag(span)}')
    return out, ('accomp:none',)


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
    """The nylon line (de.select; v2c.latin.0 lines), then the piano and bass (accompany)."""
    out, rec, info = de.select(POLICY, src, c, records, visit, seed)
    out, ops = accompany(out, src, c, records, visit, seed)
    rec = replace(rec, ops=rec.ops + ops)
    info['motif_ops'] = list(rec.ops)
    return out, rec, info
