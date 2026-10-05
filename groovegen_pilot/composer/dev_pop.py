"""
Pop development policy (v2c.pop.0) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.15).

Opt-in only (SessionComposer(develop=True)); not used by the live runner.

Material
--------
composer._gen_pop: one chord per bar (orders of Cmaj7, Gmaj, Amin7, Fmaj7, a
4-bar loop played twice), EP stabs (program 4, 0.4 beats), bass (program 33)
and a 'lead' track (program 25): int(d * 8) notes per bar (at least 2; pop:1-5
play 2/2/4/6/7), on a 16th grid with 0-2 sixteenths of jitter, 2-4 sixteenths
long, velocity 65-82. Each bar's pitches walk the pool of its chord's tones from
the root in octave 5 to the root an octave up (60-81), in a seed-picked contour
rotated at random per bar. So every lead note is a chord tone, a segment's 8
bars are 5-8 distinct, and there is no motif: no bar recurs as a phrase. In
v2a.3 the three visits of a block replay the same lead; a new block's lead is
new (cross-block overlap <= 0.14).

Source statistics (pop:1-5, stim seeds 1/2/19, 12 visits): within-bar leaps are
up to 12 (the root to its octave), cross-bar leaps up to 21; pitched p95 sits
0.23 from its v1 envelope ceiling at pop:4-5 and 0.45 from the floor at pop:2;
the pitched median envelope is 0.5 wide at pop:3 (the median sits on the EP /
lead boundary).

Rules (pitch-only, lead only)
-----------------------------
- every lead note keeps its onset, duration and velocity; the note count, EP,
  bass, drums, programs and tempo are untouched;
- every lead note is a tone of its bar's chord (read from the EP,
  develop_engine.chord_context) inside the source's window for that bar (root
  to root + 12, the generator's pool);
- bars 1-2 are the source's: the block's theme (anchor), never changed;
- no note above the source's highest; lead mean within MAX_MEAN_SHIFT of the
  source's; leaps between bars at most max(MAX_LEAP_X, the source's leap there);
  mean absolute leap at most the source's + LEAP_SLACK; no unison between
  overlapping notes the source does not have (candidates are repaired:
  fix_unisons); chord roots at most ROOT_SLACK
  more of the notes than in the source (no root-following);
- predicted lead level (composer/levels_pop_lead.py) within LEVEL_TOL_DB;
- pitched median unchanged, pitched p95 not raised nor lowered by more than
  develop_engine.MAX_PITCH_SHIFT (predicted from every
  pitched note, as stimulus_metrics.bounded_features; see the source
  statistics); a candidate whose p95 rises is first balanced: its highest notes
  outside bars 1-2 and 5-6 step down a pool tone until p95 is back (op
  'balance:n'; the engine ranks balanced candidates after the others);
- guard (on the realized MIDI): the same pool / register / median / p95 checks.

Theme transfer: a theme is its notes' intervals above the bar root; on another
bar each interval snaps to the nearest tone of that bar's pool (the same pitches
on the same chord, a chord-tone sequence on another). Bars b and b + 4 carry the
same chord.

Development (visit v, block b = v // 3, pos = v % 3)
---------------------------------------------------
    pos 0   theme: bars 5-6 restate bars 1-2 (the theme returns over the same
            chords); bars 3-4 and 7-8 the source's; if that breaks a rule (a leap
            or unison at the joins), candidates k > 0 also re-pitch the last note
            of bar 4 and / or the first of bar 7 (join)
    pos 1   A': the theme stays in bars 5-6 (the call); answer: bar 8's tail
            moves one pool step + a new first-phrase ending (last note of bar
            4); in odd blocks, for the first half of the candidates, the first
            block's theme is recalled on bars 5-6 instead (snapped to the
            current chords) + a new ending of bar 4 or bar 8
    pos 2   A'': bar 7 sequences bar 6 one pool step up or down (contour
            continuation) + a new bar-8 ending
History over HISTORY_WINDOW visits: exact repeats, near repeats (one note off a
visit before the previous one), and phrase endings (last notes of bars 4 and 8)
of developed visits. Gentle pass: one note of bars 3-4 or 7-8 moved by one pool
step.
Fallbacks as the engine: the previous line with a new ending, then the source.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from functools import cache
from statistics import mean
from typing import Optional

import numpy as np
import pretty_midi

import stimulus_metrics as sm
from composer import develop_engine as de
from composer import levels_pop_lead
from composer.develop_engine import DevRecord
from composer.energy_guard import GuardResult

DEV_VERSION = 'v2c.pop.0'
SEED_VERSION = 'v2c.pop.0'
NO_CONTEXT = 'no_lead'
LEAD = 25
EP = 4
BLOCK_LEN = 3
BARS = 8
HALF = 4
THEME = (0, 1)                      # bars 1-2: the anchor
RETURN = (4, 5)                     # bars 5-6: same chords as bars 1-2
HISTORY_WINDOW = 6                  # two blocks
N_CANDIDATES = 12
MAX_LEAP_X = 12                     # semitones between bars (the source's own leap there if larger)
LEAP_SLACK = 1.0                    # semitones: mean absolute leap over the source's
MAX_MEAN_SHIFT = 1.5                # semitones: lead mean vs the source, up or down
ROOT_SLACK = 0.125                  # share of notes on the chord root over the source's
# predicted lead level vs the source. A candidate filter, not a certification tolerance:
# over 1105 rule-valid candidates (pop:1-5, stims 1-2) the prediction tracks rendered
# segment LUFS (r 0.62; 0.80 at pop:1) but at 0.031 LU per dB (the lead is a small part
# of the mix): max |dLUFS| 0.042 below 0.25 dB, 0.041 at 0.5-1.0 dB; 0.5 dB only added
# fallbacks (theme returns at pop:1-2 predict -0.6 to -0.9 dB)
LEVEL_TOL_DB = 1.0

Line = tuple[tuple[int, ...], ...]

__all__ = ['DEV_VERSION', 'SEED_VERSION', 'NO_CONTEXT', 'read_context', 'develop', 'unchanged_record', 'POLICY']


@dataclass(frozen=True)
class PopLead:
    lead: int                                # lead track index
    harmony: tuple[int, ...]                 # EP track indices
    chords: tuple[de.ChordContext, ...]
    roots: tuple[int, ...]                   # per bar: the root pitch at the bottom of the pool
    pools: tuple[tuple[int, ...], ...]       # per bar: chord tones root..root + 12
    idx: tuple[tuple[int, ...], ...]         # per bar: lead note indices in onset order
    base: Line                               # the source's pitches, per bar
    velocities: tuple[int, ...]              # per flat position (bars in order)
    overlaps: tuple[tuple[int, int], ...]    # flat positions of notes sounding together
    max_cross: tuple[int, ...]               # per bar boundary: largest legal leap
    others: tuple[int, ...]                  # pitches of the other pitched tracks (register features)


def read_context(src: pretty_midi.PrettyMIDI, sched, tempo: float) -> Optional[PopLead]:
    lead = next((i for i, x in enumerate(src.instruments)
                 if not x.is_drum and x.program == LEAD and x.name == 'lead' and x.notes), None)
    harmony = tuple(i for i, x in enumerate(src.instruments)
                    if not x.is_drum and x.program == EP and x.name == 'ep' and x.notes)
    if lead is None or not harmony:
        return None
    bar_s = 4 * 60.0 / tempo
    chords = de.chord_context(src, harmony, bar_s, BARS, min_frac=0.0)
    if any(c is None for c in chords):
        return None
    notes = src.instruments[lead].notes
    groups: list[list[int]] = [[] for _ in range(BARS)]
    for j, n in enumerate(notes):
        b = int(n.start / bar_s + 1e-6)
        if not 0 <= b < BARS:
            return None
        groups[b].append(j)
    if len({len(g) for g in groups}) != 1 or not groups[0]:
        return None
    idx = tuple(tuple(sorted(g, key=lambda j: (round(notes[j].start, 6), j))) for g in groups)
    octave = min((notes[j].pitch - ch.root) // 12 for g, ch in zip(idx, chords) for j in g)
    roots = tuple(ch.root + 12 * octave for ch in chords)
    pools = tuple(tuple(de.chord_tones(ch, r, r + 12)) for ch, r in zip(chords, roots))
    base = tuple(tuple(notes[j].pitch for j in g) for g in idx)
    if any(p not in pool for bar, pool in zip(base, pools) for p in bar):
        return None
    flat = [j for g in idx for j in g]
    overlaps = tuple((a, b) for a in range(len(flat)) for b in range(a + 1, len(flat))
                     if notes[flat[a]].end > notes[flat[b]].start + 1e-6
                     and notes[flat[b]].end > notes[flat[a]].start + 1e-6)
    # the returning theme may keep its own bar 1 -> 2 leap at bars 5 -> 6
    cross = [abs(base[b + 1][0] - base[b][-1]) for b in range(BARS - 1)]
    max_cross = tuple(max(MAX_LEAP_X, x, cross[0] if b == RETURN[0] else 0) for b, x in enumerate(cross))
    return PopLead(lead=lead, harmony=harmony, chords=tuple(chords), roots=roots, pools=pools, idx=idx,
                   base=base, velocities=tuple(notes[j].velocity for j in flat), overlaps=overlaps,
                   others=tuple(sorted(n.pitch for i, x in enumerate(src.instruments)
                                       if not x.is_drum and i != lead for n in x.notes)),
                   max_cross=max_cross)


# =============================================================================
# Rules
# =============================================================================


def _flat(v: Line) -> list[int]:
    return [p for bar in v for p in bar]


def leaps(v: Line) -> list[int]:
    f = _flat(v)
    return [abs(b - a) for a, b in zip(f, f[1:])]


def root_share(v: Line, c: PopLead) -> float:
    f = [(p - r) % 12 == 0 for bar, r in zip(v, c.roots) for p in bar]
    return sum(f) / len(f)


def register(v: Line, c: PopLead) -> tuple[float, float]:
    """Pitched median and p95 of the segment with lead line v
    (stimulus_metrics.bounded_features: every pitched note)."""
    ps = list(c.others) + _flat(v)
    return float(np.percentile(ps, 50)), float(np.percentile(ps, 95))


def valid(v: Line, c: PopLead) -> bool:
    if len(v) != BARS or any(len(a) != len(b) for a, b in zip(v, c.base)):
        return False
    if v[:len(THEME)] != c.base[:len(THEME)]:
        return False
    if any(p not in pool for bar, pool in zip(v, c.pools) for p in bar):
        return False
    f, fb = _flat(v), _flat(c.base)
    if max(f) > max(fb) or abs(mean(f) - mean(fb)) > MAX_MEAN_SHIFT + 1e-9:
        return False
    if any(abs(v[b + 1][0] - v[b][-1]) > c.max_cross[b] for b in range(BARS - 1)):
        return False
    if mean(leaps(v)) > mean(leaps(c.base)) + LEAP_SLACK + 1e-9:
        return False
    if any(f[a] == f[b] and fb[a] != fb[b] for a, b in c.overlaps):
        return False
    (med, p95), (med0, p950) = register(v, c), register(c.base, c)
    if abs(med - med0) > 1e-9 or not p950 - de.MAX_PITCH_SHIFT - 1e-9 <= p95 <= p950 + 1e-9:
        return False
    return root_share(v, c) <= root_share(c.base, c) + ROOT_SLACK + 1e-9


def fix_unisons(v: Line, c: PopLead) -> Line:
    """Each overlapping pair the change made a unison (the source's are kept): one
    note takes the nearest pool tone that sounds with no note at its pitch - the one
    outside the theme bars (1-2, 5-6) if the other is inside, else the later; never
    one in bars 1-2. FluidSynth ends both voices of a key at the first note-off, so
    a new unison would shorten the second note."""
    f, fb = _flat(v), _flat(c.base)
    bar_of = [b for b, bar in enumerate(v) for _ in bar]
    keep = set(THEME) | set(RETURN)
    for a, b in c.overlaps:
        t = a if bar_of[b] in keep and bar_of[a] not in keep else b
        if f[a] == f[b] and fb[a] != fb[b] and bar_of[t] not in THEME:
            near = {f[x] for x, y in c.overlaps if y == t} | {f[y] for x, y in c.overlaps if x == t}
            opts = [q for q in c.pools[bar_of[t]] if q not in near]
            if opts:
                f[t] = min(opts, key=lambda q: (abs(q - f[t]), q))
    out, i = [], 0
    for bar in v:
        out.append(tuple(f[i:i + len(bar)]))
        i += len(bar)
    return tuple(out)


def balance(v: Line, c: PopLead) -> tuple[Line, int]:
    """While the pitched p95 is above the source's, the highest lead note outside
    the anchor and the theme bars (latest first) takes the next lower tone of its
    pool that no overlapping note sounds. Returns the line and the number of moves."""
    p95 = register(c.base, c)[1]
    keep, n = set(THEME) | set(RETURN), len(c.base[0])         # every bar has n notes
    moves = 0
    while register(v, c)[1] > p95 + 1e-9:
        f = _flat(v)
        pos = [(p, i) for i, p in enumerate(f) if i // n not in keep]
        for p, i in sorted(pos, reverse=True):
            b, j = divmod(i, n)
            near = {f[x] for x, y in c.overlaps if y == i} | {f[y] for x, y in c.overlaps if x == i}
            lower = [q for q in c.pools[b] if q < p and q not in near]
            if lower:
                v = _set(v, b, v[b][:j] + (lower[-1],) + v[b][j + 1:])
                moves += 1
                break
        else:
            break
    return v, moves


def _valid_record(rec: DevRecord, c: PopLead) -> bool:
    return all(valid(p, c) for p in rec.plan)


# =============================================================================
# Operations
# =============================================================================


def theme_of(v: Line, c: PopLead) -> tuple[tuple[int, ...], ...]:
    """Bars 1-2 as intervals above their bar roots."""
    return tuple(tuple(p - c.roots[b] for p in v[b]) for b in THEME)


def snap(interval: int, c: PopLead, b: int) -> int:
    """The tone of bar b's pool nearest `interval` above its root (higher on a tie)."""
    return min(c.pools[b], key=lambda q: (abs(q - c.roots[b] - interval), -q))


def place_theme(v: Line, c: PopLead, theme, bars=RETURN) -> Line:
    out = list(v)
    for b, ivs in zip(bars, theme):
        if len(ivs) == len(v[b]):
            out[b] = tuple(snap(i, c, b) for i in ivs)
    return tuple(out)


def _step(p: int, c: PopLead, b: int, s: int) -> int:
    pool = c.pools[b]
    return pool[min(max(pool.index(p) + s, 0), len(pool) - 1)]


def _fits(ps, c: PopLead, b: int, s: int) -> bool:
    """Every pitch of ps can move s pool steps in bar b without leaving the pool."""
    return all(0 <= c.pools[b].index(p) + s < len(c.pools[b]) for p in ps)


def _set(v: Line, b: int, bar: tuple[int, ...]) -> Line:
    return v[:b] + (bar,) + v[b + 1:]


def op_tail(v: Line, c: PopLead, rng: random.Random, b: int, tag: str, reach: int) -> tuple[Line, str]:
    """The last note of bar b moves to another pool tone at most `reach` pool steps away."""
    bar = v[b]
    opts = [q for s in range(-reach, reach + 1) if s for q in [_step(bar[-1], c, b, s)] if q != bar[-1]]
    if not opts:
        return v, f'{tag}:none'
    q = rng.choice(sorted(set(opts)))
    return _set(v, b, bar[:-1] + (q,)), f'{tag}@{b + 1}:{q}'


def op_answer(v: Line, c: PopLead, rng: random.Random) -> tuple[Line, str]:
    """Bar 8's tail (last note, sometimes the last two) moves one pool step, so bars
    7-8 answer the theme returning in bars 5-6."""
    b = BARS - 1
    bar = list(v[b])
    k = 2 if len(bar) > 2 and rng.random() < 0.5 else 1
    dirs = [s for s in (-1, 1) if _fits(bar[-k:], c, b, s)]
    if not dirs:
        return v, 'answer:none'
    s = rng.choice(dirs)
    for i in range(len(bar) - k, len(bar)):
        bar[i] = _step(bar[i], c, b, s)
    return _set(v, b, tuple(bar)), f"answer@{b + 1}:{k}{'+-'[s < 0]}"


def op_sequence(v: Line, c: PopLead, rng: random.Random) -> tuple[Line, str]:
    """Bar 7 takes bar 6's shape (intervals snapped to bar 7's chord), as is or one
    pool step up or down: the contour continues."""
    src, dst = RETURN[1], RETURN[1] + 1
    shape = [snap(p - c.roots[src], c, dst) for p in v[src]]
    dirs = [s for s in (-1, 0, 1) if _fits(shape, c, dst, s) and
            tuple(_step(p, c, dst, s) for p in shape) != v[dst]]
    if not dirs:
        return v, 'sequence:none'
    s = rng.choice(dirs)
    return _set(v, dst, tuple(_step(p, c, dst, s) for p in shape)), f"sequence@{dst + 1}:{'-=+'[s + 1]}"


def op_neighbor(v: Line, c: PopLead, rng: random.Random, bars) -> tuple[Line, str]:
    b = rng.choice(list(bars))
    i = rng.randrange(len(v[b]))
    q = _step(v[b][i], c, b, rng.choice((-1, 1)))
    bar = v[b][:i] + (q,) + v[b][i + 1:]
    return _set(v, b, bar), f'neighbor@{b + 1}.{i + 1}:{q}'


def op_join(v: Line, c: PopLead, rng: random.Random) -> tuple[Line, str]:
    """The notes next to the returning theme (last of bar 4, first of bar 7; one or
    both) take other tones of their pools, so the return joins the line (leap,
    unison)."""
    ends = rng.choice(((HALF - 1,), (RETURN[1] + 1,), (HALF - 1, RETURN[1] + 1)))
    tags = []
    for b in ends:
        i = -1 if b == HALF - 1 else 0
        q = rng.choice([p for p in c.pools[b] if p != v[b][i]])
        bar = list(v[b])
        bar[i] = q
        v = _set(v, b, tuple(bar))
        tags.append(f'{b + 1}:{q}')
    return v, 'join@' + ','.join(tags)


def theme_line(c: PopLead) -> Line:
    return fix_unisons(place_theme(c.base, c, theme_of(c.base, c)), c)


def _candidate(c: PopLead, records: list[DevRecord], visit: int, k: int, rng: random.Random,
               gentle: bool) -> DevRecord:
    rec = _draft(c, records, visit, k, rng, gentle)
    m, moves = balance(fix_unisons(rec.motif, c), c)
    ops = rec.ops + ((f'balance:{moves}',) if moves else ())
    return DevRecord(motif=m, theme=rec.theme, plan=(m,), role=rec.role, ops=ops)


def _draft(c: PopLead, records: list[DevRecord], visit: int, k: int, rng: random.Random,
           gentle: bool) -> DevRecord:
    block, pos = divmod(visit, BLOCK_LEN)
    theme = theme_of(c.base, c)
    if pos == 0:
        if gentle:
            m = place_theme(c.base, c, theme[:1], RETURN[:1])
            return DevRecord(motif=m, theme=theme, plan=(m,), role='theme', ops=('return@5',))
        m, ops = theme_line(c), ('return@5-6',)
        if k and not valid(fix_unisons(m, c), c):
            m, d = op_join(m, c, rng)
            ops += (d,)
        return DevRecord(motif=m, theme=theme, plan=(m,), role='theme', ops=ops)
    prev = records[visit - 1]
    v = prev.motif if prev.motif != c.base and valid(prev.motif, c) else theme_line(c)
    if gentle:
        m, d = op_neighbor(v, c, rng, [b for b in range(len(THEME), BARS) if b not in RETURN])
        return DevRecord(motif=m, theme=theme, plan=(m,), role='develop', ops=(d,))
    if pos == 2:
        m, d1 = op_sequence(v, c, rng)
        m, d2 = op_tail(m, c, rng, BARS - 1, 'ending', 2)
        return DevRecord(motif=m, theme=theme, plan=(m,), role='develop', ops=(d1, d2))
    # pos 1: answer + the first phrase's ending, or (odd blocks) the first block's theme
    # in bars 5-6 + one phrase ending
    first = records[0].theme
    if block % 2 and k < N_CANDIDATES // 2 and first != theme:
        m, d1, role = place_theme(v, c, first), 'recall@5-6', 'recall'
        m, d2 = op_tail(m, c, rng, rng.choice((HALF - 1, BARS - 1)), 'ending', 2)
    else:
        (m, d1), role = op_answer(v, c, rng), 'develop'
        m, d2 = op_tail(m, c, rng, HALF - 1, 'ending', 2)
    return DevRecord(motif=m, theme=theme, plan=(m,), role=role, ops=(d1, d2))


def hamming(a: Line, b: Line) -> int:
    return sum(x != y for x, y in zip(_flat(a), _flat(b)))


def endings(v: Line) -> tuple[int, int]:
    return v[HALF - 1][-1], v[BARS - 1][-1]


def repeats(rec: DevRecord, recent: list[DevRecord], c: PopLead) -> Optional[str]:
    """Developed lines only (the block's theme statement may recur): exact, near (one
    note off a visit before the previous) and phrase-ending history."""
    if rec.role == 'theme':
        return None
    v = rec.motif
    if v in {r.motif for r in recent}:
        return 'history'
    if any(len(r.motif) == len(v) and hamming(v, r.motif) <= 1 for r in recent[:-1]):
        return 'near'
    if endings(v) in {endings(r.motif) for r in recent}:
        return 'ending'
    return None


# =============================================================================
# Level, guard
# =============================================================================


@cache
def note_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_pop_lead.LEVEL_DB, levels_pop_lead.VELOCITIES, pitch, velocity)


def lead_level(v: Line, c: PopLead) -> float:
    return sum(note_level(p, vel) for p, vel in zip(_flat(v), c.velocities))


def energy_shift(plan: tuple[Line, ...], aux, c: PopLead) -> dict:
    """Predicted lead level change (dB) and lead mean / top change vs the source."""
    f, fb = _flat(plan[0]), _flat(c.base)
    return {'level_db': de.db(lead_level(plan[0], c), lead_level(c.base, c)),
            'mean_shift': round(mean(f) - mean(fb), 4), 'top_rise': max(f) - max(fb)}


def energy_cost(shift: dict) -> float:
    return round(max(abs(shift['level_db']) / LEVEL_TOL_DB, abs(shift['mean_shift']) / MAX_MEAN_SHIFT), 6)


def realize(src: pretty_midi.PrettyMIDI, c: PopLead, plan: tuple[Line, ...]) -> pretty_midi.PrettyMIDI:
    out = copy.deepcopy(src)
    notes = out.instruments[c.lead].notes
    for bar, idx in zip(plan[0], c.idx):
        for p, j in zip(bar, idx):
            notes[j].pitch = p
    return out


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: PopLead) -> GuardResult:
    """Only lead pitches may change; every lead note in its bar's pool; no lead note
    above the source's highest; pitched median unchanged, p95 not raised."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.lead].notes
        off = any(notes[j].pitch not in pool for idx, pool in zip(c.idx, c.pools) for j in idx)
        top = max(n.pitch for n in notes) > max(_flat(c.base))
        a, b = sm.bounded_features(pm, BARS), sm.bounded_features(src, BARS)
        moved = (['median_moved'] if abs(a['pitched_pitch_median'] - b['pitched_pitch_median']) > 1e-9 else []) + \
                (['p95_up'] if a['pitched_pitch_p95'] - b['pitched_pitch_p95'] > 1e-9 else [])
        return (['off_chord'] if off else []) + (['register'] if top else []) + moved

    return de.guard(developed, src, {c.lead: None}, check, de.MAX_PITCH_SHIFT, BARS)


def _previous(prev: DevRecord, rng: random.Random, c: PopLead) -> DevRecord:
    """The previous line with a new ending (the theme statement at a block start)."""
    v = prev.motif if prev.motif != c.base and valid(prev.motif, c) else theme_line(c)
    if not valid(v, c):
        v = c.base
    for _ in range(8):
        e, d = op_tail(v, c, rng, BARS - 1, 'ending', 2)
        e = fix_unisons(e, c)
        if e != v and valid(e, c):
            return DevRecord(motif=e, theme=theme_of(c.base, c), plan=(e,), role='fallback', ops=(d,))
    return DevRecord(motif=v, theme=theme_of(c.base, c), plan=(v,), role='fallback', ops=('ending:none',))


def unchanged_record(c: PopLead, records: list[DevRecord]) -> DevRecord:
    return DevRecord(c.base, theme_of(c.base, c), (c.base,), 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=_candidate, valid=_valid_record,
    energy=energy_shift, cost=energy_cost, realize=realize, guard=guard,
    previous=_previous, unchanged=unchanged_record, repeats=repeats)


def develop(src: pretty_midi.PrettyMIDI, c: PopLead, records: list[DevRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    return de.select(POLICY, src, c, records, visit, seed)
