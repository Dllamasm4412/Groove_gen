"""
Drum variation for the v2 generator (LIVE_GENERATION_PLAN.md sections 4.3-4.4).

Post-generation transform on a copy of the base PrettyMIDI; composer.py and
the frozen cells are not touched and the pitched tracks are never modified
(Phase 2a). Every change is count-neutral and velocity-neutral:

- micro-ops move one note by a 16th or swap it to another voice the base
  already plays (same note count, same velocity multiset). A move can merge
  or split onsets and change the on-beat share, so each candidate move is
  kept only if the segment's bounded features stay within BUDGET_FRAC of
  the energy guard's bounds (exact, via the guard's own feature code). A bar
  where no op fits re-voices one hat / hand note in place as a fill voice;
- fills are replacements: non-protected hat / snare / hand notes in the
  window are re-voiced in place (same onset positions, same count), with
  the removed velocities re-assigned in rising order (a crescendo into the
  next downbeat). Only notes whose pitch actually changes count; a fill
  window with nothing to re-voice gets micro-ops instead, so every non-A
  bar differs from its base bar whenever any op is possible.

No voice outside the base segment's own drum voices is ever written, so the
cell's drum voice set (a bounded-set feature) cannot grow. Toms (plan 4.4)
are deferred until the audio tier shows fills keep the cell's timbre.

Protected notes (never moved, swapped or cleared) are derived from the base
rather than a fixed table: every clave 75 and crash 49, kick and snare/clap/
rim on quarter-note beats, calm's kick and rim, hiphop's slot-10 kick.
"""

from __future__ import annotations

import copy
import random
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

# Bar roles: A = base bar, A' = base bar + 1-2 micro-ops, Fs = short fill
# (last beat), F = phrase-end fill (last 2 beats). Same list for every cell.
TEMPLATES: dict[str, tuple[str, ...]] = {
    'T1': ('A', 'A', "A'", 'Fs', 'A', 'A', "A'", 'F'),
    'T2': ('A', "A'", 'A', 'A', 'A', "A'", 'A', 'F'),
    'T3': ('A', 'A', 'A', 'Fs', 'A', "A'", 'A', 'F'),
}
FILL_WINDOW = {'Fs': range(12, 16), 'F': range(8, 16)}
FILL_CLEAR = HATS + BACKBEAT + HAND

# Fill styles: voices cycled across the fill positions (only voices present
# in the base are used), optional lift voice on the last position.
FILL_STYLES: dict[str, list[dict]] = {
    'calm':   [{'voices': (37,)}],
    'lofi':   [{'voices': (38,), 'lift': 46}, {'voices': (38, 36), 'lift': 46}],
    'rnb':    [{'voices': (38,), 'lift': 46}, {'voices': (38, 36), 'lift': 46}],
    'pop':    [{'voices': (38,)}, {'voices': (39,)}, {'voices': (38, 39)}],
    'latin':  [{'voices': (63, 64)}, {'voices': (65, 63)}],
    'hiphop': [{'voices': (38,)}, {'voices': (38, 36)}],
    'rock':   [{'voices': (38,)}, {'voices': (38, 36)}],
}
SHORT_FILL = {'calm': False}       # calm: phrase-end fill on bar 8 only (Fs -> A')
BUDGET_FRAC = 0.8                  # micro-op moves use at most this share of each guard bound


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


def _sorted(hits: list[_Hit]) -> list[_Hit]:
    return sorted(hits, key=lambda h: (h.pos, h.note.pitch, h.note.velocity))


def _move(h: _Hit, d: int, step: float) -> None:
    h.note.start += d * step
    h.note.end += d * step
    h.pos += d


class _Ctx:
    """Per-segment state shared by the ops: grid step, base voices, feature budget."""

    def __init__(self, pm: pretty_midi.PrettyMIDI, step: float, voices: set, style: Optional[dict]):
        from composer.energy_guard import BARS
        self.pm, self.step, self.voices, self.style, self.bars = pm, step, voices, style, BARS
        self.base_feats = sm.bounded_features(pm, BARS)

    def within_budget(self) -> bool:
        from composer.energy_guard import within_bounds
        return within_bounds(sm.bounded_features(self.pm, self.bars), self.base_feats, BUDGET_FRAC)


def _shift_op(pitches: tuple, blockers: tuple) -> Callable:
    """Move one non-protected note of `pitches` by +-1 16th within the bar,
    onto a slot where no note of `blockers` sounds, within the feature budget."""
    def op(bar: list[_Hit], rng: random.Random, ctx: _Ctx) -> Optional[str]:
        cands = []
        for h in _sorted(bar):
            if h.protected or h.note.pitch not in pitches:
                continue
            for d in (-1, 1):
                p = h.pos + d
                if 0 <= p < STEPS and not any(o.pos == p and o.note.pitch in blockers for o in bar):
                    cands.append((h, d))
        rng.shuffle(cands)
        for h, d in cands:
            _move(h, d, ctx.step)
            if ctx.within_budget():
                return f'{h.note.pitch}@{h.pos - d}{"+" if d > 0 else "-"}1'
            _move(h, -d, ctx.step)
        return None
    return op


def _swap_op(a: int, b: int) -> Callable:
    """Swap one non-protected a <-> b note, only if the base plays both voices."""
    def op(bar: list[_Hit], rng: random.Random, ctx: _Ctx) -> Optional[str]:
        if a not in ctx.voices or b not in ctx.voices:
            return None
        cands = []
        for h in _sorted(bar):
            if h.protected or h.note.pitch not in (a, b):
                continue
            new = b if h.note.pitch == a else a
            if not any(o.pos == h.pos and o.note.pitch == new for o in bar):
                cands.append((h, new))
        if not cands:
            return None
        h, new = rng.choice(cands)
        old, h.note.pitch = h.note.pitch, new
        return f'{old}>{new}@{h.pos}'
    return op


MICRO_OPS: dict[str, Callable] = {
    'hat_shift': _shift_op(HATS, HATS),
    'kick_shift': _shift_op(KICK, KICK + BACKBEAT),
    'ghost_shift': _shift_op(BACKBEAT, KICK + BACKBEAT),
    'hat_swap': _swap_op(42, 46),
    'hand_swap': _swap_op(63, 64),
}


def _revoice(bar: list[_Hit], rng: random.Random, ctx: _Ctx) -> Optional[str]:
    """Re-voice one non-protected hat / hand note in place as a fill voice.

    Last-resort op for bars where no move fits the budget (sparse all-on-beat
    cells such as calm1-2 and hiphop1): onset times are unchanged, so the
    rates and on-beat share are too. Only slots before the phrase-end fill
    window are used, so an A' bar cannot reproduce the bar-8 fill.
    """
    if ctx.style is None:
        return None
    targets = ctx.style['voices'] + ((ctx.style['lift'],) if ctx.style.get('lift') else ())
    sounding = {(o.pos, o.note.pitch) for o in bar}
    cands = [(h, v) for h in _sorted(bar)
             if not h.protected and h.note.pitch in HATS + HAND and h.pos < FILL_WINDOW['F'][0]
             for v in targets if v != h.note.pitch and (h.pos, v) not in sounding]
    if not cands:
        return None
    h, new = rng.choice(cands)
    old, h.note.pitch = h.note.pitch, new
    return f'{old}>{new}@{h.pos}'


def _micro(bar: list[_Hit], rng: random.Random, ctx: _Ctx) -> list[str]:
    n = rng.choice((1, 2))
    names = sorted(MICRO_OPS)
    rng.shuffle(names)
    done = []
    for name in names:
        if len(done) == n:
            break
        desc = MICRO_OPS[name](bar, rng, ctx)
        if desc is not None:
            done.append(f'{name}:{desc}')
    if not done:
        desc = _revoice(bar, rng, ctx)
        if desc is not None:
            done.append(f'revoice:{desc}')
    return done


def _fill(bar: list[_Hit], window: range, style: dict) -> list[str]:
    """Re-voice non-protected hat / snare / hand notes in the window in place."""
    voices = style['voices']
    cleared = [h for h in _sorted(bar)
               if h.pos in window and not h.protected and h.note.pitch in FILL_CLEAR]
    if not cleared:
        return []
    sounding = {(o.pos, o.note.pitch) for o in bar if o not in cleared}
    revoiced: list[_Hit] = []
    positions = sorted({h.pos for h in cleared})
    for k, pos in enumerate(positions):
        for h in (h for h in cleared if h.pos == pos):
            order = [voices[(k + i) % len(voices)] for i in range(len(voices))]
            if pos == positions[-1] and style.get('lift') is not None:
                order = [style['lift']] + order
            new = next((v for v in order if v != h.note.pitch and (pos, v) not in sounding), None)
            if new is None:
                sounding.add((pos, h.note.pitch))      # keep the original note
                continue
            h.note.pitch = new
            sounding.add((pos, new))
            revoiced.append(h)
    # Crescendo: the revoiced notes keep their velocity multiset, rising in time
    for h, v in zip(revoiced, sorted(h.note.velocity for h in revoiced)):
        h.note.velocity = v
    return [f'fill:{h.note.pitch}@{h.pos}' for h in revoiced]


def vary(base: pretty_midi.PrettyMIDI, genre: str, var_seed: int) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Varied copy of `base` (base itself is not modified) and a log of what changed."""
    rng = random.Random(var_seed)
    pm = copy.deepcopy(base)
    step = _step_s(pm)
    template = rng.choice(sorted(TEMPLATES))
    roles = list(TEMPLATES[template])
    if not SHORT_FILL.get(genre, True):
        roles = ["A'" if r == 'Fs' else r for r in roles]

    hits = [_Hit(n, step, genre) for inst in pm.instruments if inst.is_drum for n in inst.notes]
    voices = {h.note.pitch for h in hits}
    styles = [s for s in FILL_STYLES.get(genre, [])
              if any(v in voices for v in s['voices'])]
    styles = [{**s, 'voices': tuple(v for v in s['voices'] if v in voices),
               'lift': s.get('lift') if s.get('lift') in voices else None} for s in styles]
    style = rng.choice(styles) if styles else None
    ctx = _Ctx(pm, step, voices, style)

    ops: list[list[str]] = []
    for b, role in enumerate(roles):
        bar = [h for h in hits if h.bar == b]
        done: list[str] = []
        if role in FILL_WINDOW and style is not None:
            done = _fill(bar, FILL_WINDOW[role], style)
        if role != 'A' and not done:
            done = _micro(bar, rng, ctx)
        ops.append(done)
    for inst in pm.instruments:
        if inst.is_drum:
            inst.notes.sort(key=lambda n: (n.start, n.pitch))
    return pm, {'form_template': template, 'bar_roles': roles, 'drum_ops': ops,
                'fill_style': None if style is None else list(style['voices'])}
