"""
Drum variation for the v2 generator (LIVE_GENERATION_PLAN.md sections 4.3-4.4, 6.8).

Post-generation transform on a copy of the base PrettyMIDI; composer.py and
the frozen cells are not touched and the pitched tracks are never modified
(Phase 2a). Every op is count-neutral and velocity-neutral (a note keeps its
velocity), and no voice outside the base segment's own drum voices is ever
written, so the cell's drum voice set (a bounded-set feature) cannot grow.

Ops, cheapest first (v2a.2; rendered-audio evidence in plan section 6.8):
  1. exchange: two nearby non-kick notes of different voices trade slots, a
     rearrangement that keeps the onset grid and the voice mix;
     family: a note becomes another voice of its own timbre family that the
     base plays (closed / pedal / open hat and ride, snare / rim / clap,
     conga / bongo / timbale articulations);
  2. move: one note shifts by a 16th. Kept only if the segment's bounded
     features stay within BUDGET_FRAC of the energy guard's bounds; at most
     MAX_MOVES per segment, since a 16th move costs pulse clarity on audio;
  3. cross: a hat / hand note is re-voiced in place as the brightest
     snare-family (else hand) voice the base plays, never a kick. At most
     MAX_CROSS per segment, and only while drum_brightness stays within
     BRIGHT_DROP of the base.

Bars 4 and 8 (the phrase ends) always get an op, so no run of identical bars
exceeds 3 and both phrase ends are marked; if nothing within budget fits
there, a family / cross op may exceed the cross cap and brightness budget
(the feature budget is never exceeded). The other varied bars (A', and the
second op of the bar-8 fill) only get ops within budget. Each bar tries its
fill window first, then the whole bar. `relax`, raised by the caller on
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
        self.budget_frac = min(1.0, BUDGET_FRAC * (1 + relax))
        self.max_moves = MAX_MOVES + relax
        self.max_cross = MAX_CROSS + relax
        self.bright_drop = BRIGHT_DROP * (1 + relax)
        self.n: Counter = Counter()
        self.touched: set[int] = set()     # id() of hits an op already moved or re-voiced

    def within_budget(self) -> bool:
        from composer.energy_guard import within_bounds
        return within_bounds(sm.bounded_features(self.pm, self.bars), self.base_feats, self.budget_frac)

    def bright_ok(self) -> bool:
        return drum_brightness(self.pm) >= self.base_bright - self.bright_drop - 1e-9

    def accept(self, kind: str, strict: bool) -> bool:
        """Budget check after an op is applied. strict=False (phrase ends only)
        waives the cross cap and brightness budget, never the feature budget."""
        if kind == 'move':
            return self.n['move'] < self.max_moves and self.within_budget()
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
    if tier == 'cheap':
        for i, a in enumerate(free):
            for b in free[i + 1:]:
                pa, pb = a.note.pitch, b.note.pitch
                if (pa in KICK or pb in KICK or pa == pb or a.pos == b.pos
                        or abs(a.pos - b.pos) > EXCHANGE_SPAN
                        or (b.pos, pa) in sounding or (a.pos, pb) in sounding):
                    continue
                d = b.pos - a.pos
                out.append(('exchange', f'{pa}@{a.pos}<>{pb}@{b.pos}', *_shift((a, b), (d, -d), ctx.step), (a, b)))
        for h in free:
            fam = FAMILY.get(h.note.pitch)
            if fam is None:
                continue
            for v in FAMILIES[fam]:
                if v != h.note.pitch and v in ctx.voices and (h.pos, v) not in sounding:
                    out.append(('family', f'{h.note.pitch}>{v}@{h.pos}', *_repitch(h, v), (h,)))
    elif tier == 'move':
        for pitches, blockers in _MOVES:
            for h in free:
                if h.note.pitch not in pitches:
                    continue
                for d in (-1, 1):
                    p = h.pos + d
                    if 0 <= p < STEPS and not any(o.pos == p and o.note.pitch in blockers for o in bar):
                        out.append(('move', f'{h.note.pitch}@{h.pos}{"+" if d > 0 else "-"}1',
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


def _one_op(bars: list[list[_Hit]], b: int, window: range, rng: random.Random,
            ctx: _Ctx, strict: bool, settled: set) -> Optional[str]:
    """Apply the cheapest acceptable op to bar b; None if nothing fits."""
    tiers = ('cheap', 'move', 'cross') if strict else ('cheap', 'cross')
    for tier in tiers:
        cands = _candidates(tier, bars[b], window, ctx)
        rng.shuffle(cands)
        for kind, desc, do, undo, changed in cands:
            do()
            if ctx.accept(kind, strict) and _distinct_ok(bars, b, settled):
                ctx.n[kind] += 1
                ctx.touched.update(id(h) for h in changed)
                return f'{kind}:{desc}'
            undo()
    return None


def vary(base: pretty_midi.PrettyMIDI, genre: str, var_seed: int,
         relax: int = 0) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Varied copy of `base` (base itself is not modified) and a log of what changed."""
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
        for strict in ((True, False) if required else (True,)):
            for w in windows:
                desc = desc or _one_op(bars, b, w, rng, ctx, strict, settled)
        if desc is not None:
            ops[b].append(desc)
        settled.add(b)
    for inst in pm.instruments:
        if inst.is_drum:
            inst.notes.sort(key=lambda n: (n.start, n.pitch))
    return pm, {'form_template': template, 'bar_roles': roles, 'drum_ops': ops,
                'op_counts': dict(sorted(ctx.n.items())), 'relax': relax,
                'drum_brightness_delta': round(drum_brightness(pm) - ctx.base_bright, 4)}
