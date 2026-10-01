"""
Drum variation for the v2 generator (LIVE_GENERATION_PLAN.md sections 4.3-4.4, 6.8).

Post-generation transform on a copy of the base PrettyMIDI; composer.py and
the frozen cells are not touched and the pitched tracks are never modified
(Phase 2a). Every op is count-neutral and velocity-neutral (a note keeps its
velocity), and no voice outside the base segment's own drum voices is ever
written, so the cell's drum voice set (a bounded-set feature) cannot grow.

Ops, cheapest first (v2a.3; per-op rendered-audio attribution in plan
sections 6.8-6.9):
  1. exchange: two nearby non-kick notes of different voices in one timbre
     family (closed / pedal / open hat and ride, snare / rim / clap, conga /
     bongo / timbale articulations) trade slots, keeping the onset grid and
     the voice mix. Cross-family exchanges moved the snare accent (rnb 4);
  2. move: a note off any regular line of its lane shifts by a 16th, within
     BUDGET_FRAC of the energy guard's bounds;
  3. family: a note becomes another voice of its own timbre family that the
     base plays (a hand-drum articulation swap ranks with exchange, COST);
  4. grid_move: as move, for a note in an evenly spaced run of its lane (a
     straight hat line, a conga pulse). Costs pulse clarity on audio, so at
     most MAX_MOVES per segment;
  5. cross: a hat / hand note is re-voiced in place as the brightest
     snare-family (else hand) voice the base plays, never a kick. Phrase
     ends only unless relax >= 1 (the caller retries when a variation
     repeats an earlier visit), at most MAX_CROSS per segment, and only while
     drum_brightness stays within BRIGHT_DROP of the base.
No op may change the open-hat rings (open_hat_rings): a closed / pedal hat
chokes a ringing open hat, so creating, removing or moving a 46, or changing
the hat that cuts it, changed centroid and flux by up to 2 allowances per op
(hiphop 3-5, rock 5).

Bars 4 and 8 (the phrase ends) always get an op, so no run of identical bars
exceeds 3 and both phrase ends are marked; if nothing within budget fits
there, a family / cross op may exceed the cross cap and brightness budget
(the feature budget is never exceeded), and as a last resort (PASSES) an
exchange / family op may change the open-hat rings. The other varied bars
(A', and the second op of the bar-8 fill) only get ops within budget. Each
tier tries the bar's fill window first, then the whole bar. `relax`, raised by the caller on
retries, loosens the move / cross caps, the brightness budget and the move
feature budget (up to the full guard bounds) for cells with few options
(calm, hiphop 1: every free note is an on-beat hat).

Protected notes (never moved or re-voiced) are derived from the base
rather than a fixed table: every clave 75 and crash 49, kick and snare/clap/
rim on quarter-note beats, calm's kick and rim, hiphop's slot-10 kick.
"""

from __future__ import annotations

import copy
import random
from collections import Counter
from typing import Callable, Optional

import pretty_midi

import stimulus_metrics as sm

STEPS = 16                         # 16th slots per bar; every v1 drum onset is on this grid
BEAT_SLOTS = (0, 4, 8, 12)
KICK = (35, 36)
BACKBEAT = (37, 38, 39, 40)
HATS = (42, 44, 46, 51)            # movable hats / ride (crash 49 is protected)
HAND = (56, 60, 61, 62, 63, 64, 65, 66)
CLAVE, CRASH = 75, 49
_EXTRA_PROTECTED = {('hiphop', 36, 10)}   # hiphop_drum_pattern kick slots 0 and 10

# Timbre families for 'family' ops (hats and ride; snare, rim, clap; congas;
# bongos; timbales).
FAMILIES = ((42, 44, 46, 51), (37, 38, 39, 40), (62, 63, 64), (60, 61), (65, 66))
FAMILY = {v: i for i, fam in enumerate(FAMILIES) for v in fam}
# Coarse brightness class of each voice, from its spectral centroid rendered
# alone through the live soundfont (Musyng_Kite, plan 6.8): above 5 kHz 1.0,
# 1-3 kHz 0.6, 0.2-1 kHz 0.3, below 0.1 kHz 0.
BRIGHTNESS = {42: 1.0, 44: 1.0, 46: 1.0, 51: 1.0,
              37: 0.6, 39: 0.6, 49: 0.6, 60: 0.6, 65: 0.6, 66: 0.6, 75: 0.6,
              38: 0.3, 40: 0.3, 56: 0.3, 61: 0.3, 62: 0.3, 63: 0.3, 64: 0.3,
              35: 0.0, 36: 0.0}
CROSS_TARGETS = (37, 39, 60, 65, 66, 56, 62, 40, 61, 38, 63, 64)   # brightest first, no kick

# Bar roles: A = base bar, A' = base bar + 1 op, Fs = short fill (last beat),
# F = phrase-end fill (last 2 beats). Bars 4 and 8 are varied in every template.
TEMPLATES: dict[str, tuple[str, ...]] = {
    'T1': ('A', 'A', "A'", 'Fs', 'A', 'A', "A'", 'F'),
    'T2': ('A', "A'", 'A', "A'", 'A', "A'", 'A', 'F'),
    'T3': ('A', 'A', 'A', 'Fs', 'A', "A'", 'A', 'F'),
}
FILL_WINDOW = {'Fs': range(12, 16), 'F': range(8, 16)}
PHRASE_ENDS = (3, 7)               # 0-based bars 4 and 8
# Bar pairs that must differ: each phrase end vs the two bars before it
# (stimulus_metrics R6), and bar 4 vs bar 8 (R1 >= 3 with only those varied).
DISTINCT_PAIRS = ((3, 2), (3, 1), (7, 6), (7, 5), (7, 3))
SHORT_FILL = {'calm': False}       # calm: phrase-end fill on bar 8 only (Fs -> A')
F_OPS = 2                          # ops on the bar-8 fill (the second within budget only)
EXCHANGE_SPAN = 4                  # exchange partners at most a beat apart
BUDGET_FRAC = 0.4                  # moves use at most this share of each guard bound (x (1 + relax), <= 1)
MAX_MOVES = 1                      # 16th moves per segment
MAX_CROSS = 2                      # cross-family re-voices per segment (phrase ends may exceed)
BRIGHT_DROP = 0.01                 # drum_brightness may fall this far below the base
CHOKE = (42, 44, 46)               # GM hat exclusive class: a closed / pedal hat cuts a ringing open hat
LANE_SPACING = 4                   # a note in a 3-note evenly spaced run (step <= this) of its lane is on a grid


class _Hit:
    """A drum note with its bar / 16th slot (recomputed after a move)."""

    __slots__ = ('note', 'bar', 'pos', 'protected')

    def __init__(self, note: pretty_midi.Note, step_s: float, genre: str):
        self.note = note
        slot = int(round(note.start / step_s))
        self.bar, self.pos = divmod(slot, STEPS)
        self.protected = is_protected(genre, note.pitch, self.pos)


def is_protected(genre: str, pitch: int, pos: int) -> bool:
    if pitch in (CLAVE, CRASH):
        return True
    if genre == 'calm' and pitch in (36, 37):
        return True
    if (pitch in KICK or pitch in BACKBEAT) and pos in BEAT_SLOTS:
        return True
    return (genre, pitch, pos) in _EXTRA_PROTECTED


def _step_s(pm: pretty_midi.PrettyMIDI) -> float:
    tempo = float(pm.get_tempo_changes()[1][0])
    return 60.0 / tempo / 4


def protected_notes(pm: pretty_midi.PrettyMIDI, genre: str) -> list[tuple]:
    """(pitch, start, end, velocity) of every protected drum note, sorted."""
    step = _step_s(pm)
    out = []
    for inst in pm.instruments:
        if inst.is_drum:
            for n in inst.notes:
                if _Hit(n, step, genre).protected:
                    out.append((n.pitch, round(n.start, 6), round(n.end, 6), n.velocity))
    return sorted(out)


def drum_brightness(pm: pretty_midi.PrettyMIDI) -> float:
    """Velocity-weighted mean BRIGHTNESS class of the drum notes (0 = all kick,
    1 = all hats). A MIDI-side proxy for the drums' share of the spectral
    centroid; unknown voices count as 0.5."""
    num = den = 0.0
    for inst in pm.instruments:
        if inst.is_drum:
            for n in inst.notes:
                num += n.velocity * BRIGHTNESS.get(n.pitch, 0.5)
                den += n.velocity
    return num / den if den else float('nan')


def open_hat_rings(pm: pretty_midi.PrettyMIDI, step_s: float) -> tuple:
    """(open hat slot, slot of the next hat that chokes it or None) for every
    open hat 46. An open hat rings until the next closed / pedal / open hat, so
    an op that changes this tuple changes the drums' sustained high end."""
    lane = sorted((int(round(n.start / step_s)), n.pitch) for inst in pm.instruments if inst.is_drum
                  for n in inst.notes if n.pitch in CHOKE)
    return tuple((s, next((t for t, _ in lane[k + 1:] if t > s), None))
                 for k, (s, p) in enumerate(lane) if p == 46)


def _lane(pitch: int):
    return FAMILY.get(pitch, 'kick' if pitch in KICK else pitch)


def _on_grid(h: _Hit, bar: list[_Hit]) -> bool:
    """True if h is part of an evenly spaced run of 3 in its lane (timbre family),
    e.g. a hat on a straight 8th line: moving it breaks the pulse."""
    lane = {o.pos for o in bar if _lane(o.note.pitch) == _lane(h.note.pitch)}
    p = h.pos
    return any({p - s, p + s} <= lane or {p + s, p + 2 * s} <= lane or {p - s, p - 2 * s} <= lane
               for s in range(1, LANE_SPACING + 1))


def _sorted(hits: list[_Hit]) -> list[_Hit]:
    return sorted(hits, key=lambda h: (h.pos, h.note.pitch, h.note.velocity))


def _move(h: _Hit, d: int, step: float) -> None:
    h.note.start += d * step
    h.note.end += d * step
    h.pos += d


class _Ctx:
    """Per-segment state shared by the ops: grid step, base voices, budgets, op counts."""

    def __init__(self, pm: pretty_midi.PrettyMIDI, step: float, voices: set, relax: int):
        from composer.energy_guard import BARS
        self.pm, self.step, self.voices, self.bars = pm, step, voices, BARS
        self.base_feats = sm.bounded_features(pm, BARS)
        self.base_bright = drum_brightness(pm)
        self.base_rings = self.rings = open_hat_rings(pm, step)   # rings: after accepted ring breaks
        self.budget_frac = min(1.0, BUDGET_FRAC * (1 + relax))
        self.max_moves = MAX_MOVES + relax
        self.max_cross = MAX_CROSS + relax
        self.bright_drop = BRIGHT_DROP * (1 + relax)
        self.n: Counter = Counter()
        self.touched: set[int] = set()     # id() of hits an op already moved or re-voiced
        self.cost = 0                      # sum of op_cost of the applied ops (+ RING_BREAK_COST each)

    def within_budget(self) -> bool:
        from composer.energy_guard import within_bounds
        return within_bounds(sm.bounded_features(self.pm, self.bars), self.base_feats, self.budget_frac)

    def bright_ok(self) -> bool:
        return drum_brightness(self.pm) >= self.base_bright - self.bright_drop - 1e-9

    def accept(self, kind: str, strict: bool, keep_rings: bool = True) -> bool:
        """Budget check after an op is applied. strict=False (phrase ends only)
        waives the cross cap and brightness budget, never the feature budget;
        keep_rings=False (phrase ends, last resort) also waives the open-hat rings."""
        if keep_rings and open_hat_rings(self.pm, self.step) != self.rings:
            return False
        if kind == 'move':
            return self.within_budget()
        if kind == 'grid_move':
            return self.n['grid_move'] < self.max_moves and self.within_budget()
        if kind == 'cross':
            return not strict or (self.n['cross'] < self.max_cross and self.bright_ok())
        if kind == 'family':
            return not strict or self.bright_ok()
        return True                # exchange: onset grid and voice mix unchanged


# A candidate op: (kind, description, apply, undo, hits it changes)
Cand = tuple[str, str, Callable[[], None], Callable[[], None], tuple]


def _repitch(h: _Hit, new: int) -> tuple[Callable, Callable]:
    old = h.note.pitch

    def do():
        h.note.pitch = new

    def undo():
        h.note.pitch = old
    return do, undo


def _shift(hits: tuple, ds: tuple, step: float) -> tuple[Callable, Callable]:
    def do():
        for h, d in zip(hits, ds):
            _move(h, d, step)

    def undo():
        for h, d in zip(hits, ds):
            _move(h, -d, step)
    return do, undo


# Moves: (pitches that move, pitches that block the destination slot)
_MOVES = ((HATS, HATS), (KICK, KICK + BACKBEAT), (BACKBEAT, KICK + BACKBEAT))


def _candidates(tier: str, bar: list[_Hit], window: range, ctx: _Ctx) -> list[Cand]:
    free = [h for h in _sorted(bar) if not h.protected and h.pos in window and id(h) not in ctx.touched]
    sounding = {(o.pos, o.note.pitch) for o in bar}
    out: list[Cand] = []
    if tier == 'exchange':
        for i, a in enumerate(free):
            for b in free[i + 1:]:
                pa, pb = a.note.pitch, b.note.pitch
                if (pa in KICK or pb in KICK or pa == pb or a.pos == b.pos
                        or FAMILY.get(pa) is None or FAMILY.get(pa) != FAMILY.get(pb)
                        or abs(a.pos - b.pos) > EXCHANGE_SPAN
                        or (b.pos, pa) in sounding or (a.pos, pb) in sounding):
                    continue
                d = b.pos - a.pos
                out.append(('exchange', f'{pa}@{a.pos}<>{pb}@{b.pos}', *_shift((a, b), (d, -d), ctx.step), (a, b)))
    elif tier == 'family':
        for h in free:
            fam = FAMILY.get(h.note.pitch)
            if fam is None:
                continue
            for v in FAMILIES[fam]:
                if v != h.note.pitch and v in ctx.voices and (h.pos, v) not in sounding:
                    out.append(('family', f'{h.note.pitch}>{v}@{h.pos}', *_repitch(h, v), (h,)))
    elif tier in ('move', 'grid_move'):
        for pitches, blockers in _MOVES:
            for h in free:
                if h.note.pitch not in pitches or _on_grid(h, bar) != (tier == 'grid_move'):
                    continue
                for d in (-1, 1):
                    p = h.pos + d
                    if 0 <= p < STEPS and not any(o.pos == p and o.note.pitch in blockers for o in bar):
                        out.append((tier, f'{h.note.pitch}@{h.pos}{"+" if d > 0 else "-"}1',
                                    *_shift((h,), (d,), ctx.step), (h,)))
    elif tier == 'cross':
        for h in free:
            if h.note.pitch not in HATS + HAND:
                continue
            new = next((v for v in CROSS_TARGETS if v in ctx.voices
                        and FAMILY.get(v) != FAMILY.get(h.note.pitch) and (h.pos, v) not in sounding), None)
            if new is not None:
                out.append(('cross', f'{h.note.pitch}>{new}@{h.pos}', *_repitch(h, new), (h,)))
    return out


def _distinct_ok(bars: list[list[_Hit]], b: int, settled: set) -> bool:
    """Bar b differs from every DISTINCT_PAIRS partner that will not change again."""
    def sig(i):
        return frozenset((h.note.pitch, h.pos) for h in bars[i])
    return all(sig(x) != sig(y) for x, y in DISTINCT_PAIRS
               if b in (x, y) and ({x, y} - {b}) <= settled)


TIERS = ('exchange', 'move', 'family', 'grid_move', 'cross')   # cheapest first
# Required phrase-end passes: (strict, keep_rings, tiers). The later passes
# only re-try the ops whose budget they waive. The last one serves bases whose
# every hat is an open hat or the hat that chokes one (some lofi / rnb bases
# with an open hat on every off-beat): there only hat ops give enough
# distinct bars for the repeat window. Each use is counted as 'ring_break'.
PASSES = ((True, True, TIERS), (False, True, ('family', 'cross')), (False, False, ('exchange', 'family')))
OPTIONAL_TIERS = TIERS[:-1]        # optional ops re-voice across families only on retries (relax >= 1)


# Op cost (lower first; ops of equal cost are tried in one shuffled pool).
# Timing displacement, timbre-family change, brightness and pulse / accent
# disruption, from the per-op attribution (plan 6.9): an exchange keeps the
# voice mix, an off-grid 16th move shifts one onset, a family swap changes a
# timbre inside one family, a grid move breaks a regular line (pulse), a
# cross changes the family (brightness). A family swap between articulations
# of one hand drum (conga open / mute, bongo high / low, timbale high / low)
# is about centroid-neutral (latin 63>64: 0.00x) while repeated exchanges
# drift it (+0.14x each), so it costs the same as an exchange.
COST = {'exchange': 1, 'move': 2, 'family': 3, 'grid_move': 4, 'cross': 5}
ARTICULATION_FAMILIES = frozenset(FAMILY[p] for p in (60, 62, 65))
RING_BREAK_COST = 5


def op_cost(kind: str, changed: tuple) -> int:
    if kind == 'family' and FAMILY.get(changed[0].note.pitch) in ARTICULATION_FAMILIES:
        return COST['exchange']
    return COST[kind]


def _sig(bar: list[_Hit]) -> frozenset:
    return frozenset((h.note.pitch, h.pos) for h in bar)


def bar_signatures(pm: pretty_midi.PrettyMIDI, genre: str) -> frozenset:
    """The drum patterns of pm's bars, as `vary(avoid=...)` compares them."""
    step = _step_s(pm)
    hits = [_Hit(n, step, genre) for inst in pm.instruments if inst.is_drum for n in inst.notes]
    return frozenset(_sig([h for h in hits if h.bar == b]) for b in {h.bar for h in hits})


def _one_op(bars: list[list[_Hit]], b: int, windows: tuple, rng: random.Random,
            ctx: _Ctx, strict: bool, settled: set, keep_rings: bool = True,
            tiers: tuple = TIERS, avoid: frozenset = frozenset(), fresh: bool = False) -> Optional[str]:
    """Apply the cheapest acceptable op to bar b; None if nothing fits. Each
    cost level tries the fill window before the whole bar, so a cheaper op
    anywhere in the bar wins over a costlier one in the window. Within a
    cost level, an op whose bar is not in `avoid` (the previous visit's bars)
    goes first; with `fresh`, every cost level below cross is searched for
    such an op before any other is taken. Novelty never buys a cross: in
    hiphop:3-5 (whose ring-safe cheap ops give few bar variants) it doubled
    their crosses and moved the centroid -17 -> -40 Hz (allowed 36)."""
    levels = sorted({COST[t] for t in tiers} | ({COST['exchange']} if 'family' in tiers else set()))
    for fresh_only in ((True, False) if fresh and avoid else (False,)):
        for level in levels:
            if fresh_only and level >= COST['cross']:
                continue
            for w in windows:
                cands = [c for t in tiers for c in _candidates(t, bars[b], w, ctx) if op_cost(c[0], c[4]) == level]
                rng.shuffle(cands)
                for want_new in ((True,) if fresh_only else (True, False) if avoid else (False,)):
                    desc = _try(cands, bars, b, ctx, strict, settled, keep_rings, level,
                                avoid if want_new else None)
                    if desc is not None:
                        return desc
    return None


def _try(cands: list, bars: list[list[_Hit]], b: int, ctx: _Ctx, strict: bool, settled: set,
         keep_rings: bool, level: int, avoid: Optional[frozenset]) -> Optional[str]:
    for kind, desc, do, undo, changed in cands:
        do()
        if (ctx.accept(kind, strict, keep_rings) and _distinct_ok(bars, b, settled)
                and (avoid is None or _sig(bars[b]) not in avoid)):
            rings = open_hat_rings(ctx.pm, ctx.step)
            if rings != ctx.rings:
                ctx.n['ring_break'] += 1
                ctx.cost += RING_BREAK_COST
                ctx.rings = rings
            ctx.n[kind] += 1
            ctx.cost += level
            ctx.touched.update(id(h) for h in changed)
            return f'{kind}:{desc}'
        undo()
    return None


def vary(base: pretty_midi.PrettyMIDI, genre: str, var_seed: int, relax: int = 0,
         avoid: frozenset = frozenset(), fresh: bool = False) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Varied copy of `base` (base itself is not modified) and a log of what
    changed. `avoid` holds bar patterns (`bar_signatures`) to steer away from,
    `fresh` makes that a priority over op cost (see _one_op)."""
    rng = random.Random(var_seed)
    pm = copy.deepcopy(base)
    step = _step_s(pm)
    template = rng.choice(sorted(TEMPLATES))
    roles = list(TEMPLATES[template])
    if not SHORT_FILL.get(genre, True):
        roles = ["A'" if r == 'Fs' else r for r in roles]

    hits = [_Hit(n, step, genre) for inst in pm.instruments if inst.is_drum for n in inst.notes]
    bars = [[h for h in hits if h.bar == b] for b in range(len(roles))]
    ctx = _Ctx(pm, step, {h.note.pitch for h in hits}, relax)

    # Phrase ends first (they get the capped ops), then the other varied bars,
    # then the extra bar-8 fill ops.
    order = [(b, True) for b in reversed(PHRASE_ENDS)]
    order += [(b, False) for b, r in enumerate(roles) if r != 'A' and b not in PHRASE_ENDS]
    order += [(PHRASE_ENDS[-1], False)] * (F_OPS - 1)
    settled = {b for b, r in enumerate(roles) if r == 'A'}
    ops: list[list[str]] = [[] for _ in roles]
    for b, required in order:
        window = FILL_WINDOW.get(roles[b], range(STEPS))
        windows = (window, range(STEPS)) if len(window) < STEPS else (window,)
        desc = None
        opt_tiers = OPTIONAL_TIERS if relax == 0 else TIERS
        for strict, keep_rings, tiers in (PASSES if required else ((True, True, opt_tiers),)):
            desc = desc or _one_op(bars, b, windows, rng, ctx, strict, settled, keep_rings, tiers,
                                   avoid, fresh)
        if desc is not None:
            ops[b].append(desc)
        settled.add(b)
    for inst in pm.instruments:
        if inst.is_drum:
            inst.notes.sort(key=lambda n: (n.start, n.pitch))
    return pm, {'form_template': template, 'bar_roles': roles, 'drum_ops': ops,
                'op_counts': dict(sorted(ctx.n.items())), 'op_cost': ctx.cost, 'relax': relax,
                'fresh_bars': sum(r != 'A' and _sig(bars[b]) not in avoid for b, r in enumerate(roles)) if avoid else None,
                'drum_brightness_delta': round(drum_brightness(pm) - ctx.base_bright, 4)}
