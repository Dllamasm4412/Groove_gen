"""
Lo-fi development policy (v2c.lofi.0) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.13).

Opt-in only (SessionComposer(develop=True)); not used by the live runner.

Material
--------
composer._gen_lofi is _gen_rnb softened: per bar one EP chord (program 4,
held 0.95 bar; progressions are orders of F#min7, Dsus2, Emin7, Cadd9, a
4-bar loop played twice), bass (program 33), and a 'keys' track (program 0)
playing a beat-3 color dyad (1.5 beats, octave 5 or 6) and, at density >= 0.5
(lofi:3), int(d * 4) off-beat stabs (0.4 beats, octave 5). Both dyads are
chord_pitches(chord)[:2]: root + 3rd (root + 2nd on sus2) in every bar. In
v2a.3 the keys of a block's three visits are identical.

Rules (pitch-only, keys only)
-----------------------------
- every keys note keeps its onset, duration, velocity; the note count, EP,
  bass, drums, programs and tempo are untouched;
- a bar's dyad is two adjacent tones of the chord as the EP stacks it
  (develop_engine.chord_context reads the pcs; the EP's ascending order gives
  the stacking), a 2nd to a 4th apart: root+3rd, 3rd+5th, 5th+7th where the
  EP plays a 7th (no 7th added to a chord that has none);
- the color dyad and the bar's stabs take the same dyad, each placed in the
  octave nearest its own source register (ties down);
- top voice (the color dyad's upper note): within FAR of the source in every
  bar, no bar above the source's highest, mean within MAX_MEAN_RISE of the
  source's either way (a darker voicing lowers the segment's pitched p95,
  which certification gates: lofi:3 bases sit on its v1 floor),
  leaps between bars at most max(MAX_LEAP, the source's leap there);
- predicted keys level (composer/levels_lofi_color.py and levels_lofi_stab.py,
  measured with the note lengths lofi plays) within LEVEL_TOL_DB of the source;
- the segment's pitched p95 is not lowered (guard): the lofi:3 v2a.3 bases
  sit on the v1 envelope floor of that gated feature.

Development (visit v, block b = v // 3, pos = v % 3; one op per visit)
---------------------------------------------------------------------
    pos 0         the block's source voicing (allowed to recur: not every
                  visit has to be new)
    pos 1, b odd  recall: the previous block's last top-voice contour over
                  bars 5-8 (up / down / same, at most RECALL_MISMATCH steps
                  off), realised with the current chords' dyads; candidate k
                  takes the k-th closest; once they run out, as pos 1
    pos 1         guide (bars 5-8 re-voiced for the smoothest top voice from
                  bar 4), voice (one bar of 1-7 re-voiced) or bar4
    pos 2         ending: bar 8 re-voiced
History: a developed voicing equal to one of the last HISTORY_WINDOW visits
is rejected (no near-repeat rule; lighter than R&B). Gentle pass: one bar
re-voiced. Fallbacks as the engine: the previous voicing with a new ending,
then the source voicing.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from functools import cache
from statistics import mean
from typing import Optional

import pretty_midi

import stimulus_metrics as sm
from composer import develop_engine as de
from composer.develop_engine import ChordContext, DevRecord
from composer.energy_guard import GuardResult
from composer import levels_lofi_color, levels_lofi_stab

DEV_VERSION = 'v2c.lofi.0'
SEED_VERSION = 'v2c.lofi.0'
NO_CONTEXT = 'no_keys'
BLOCK_LEN = 3
BARS = 8
KEYS, EP = 0, 4                     # GM programs
HISTORY_WINDOW = 6
N_CANDIDATES = 12
FAR = 5                             # semitones: top voice vs the source, per bar
MAX_LEAP = 5                        # semitones: top-voice leap between bars always allowed
MAX_MEAN_RISE = 1.0                 # semitones: top-voice mean vs the source, up or down
LEVEL_TOL_DB = 0.2                  # predicted keys level vs the source (hiphop v2b.1 value)
DYAD_INTERVALS = (2, 3, 4, 5)       # a 2nd to a 4th
RECALL_MISMATCH = 1                 # contour steps (of 4) a recall may differ in

Dyad = tuple[int, int]
Voicing = tuple[Dyad, ...]


@dataclass(frozen=True)
class LofiKeys:
    keys: int                       # instrument index of the keys
    harmony: tuple[int, ...]        # EP track(s)
    chords: tuple[ChordContext, ...]
    options: tuple[tuple[tuple[int, int], ...], ...]   # per bar: legal (pc_lo, interval) dyads
    color: tuple[tuple[int, int], ...]                  # per bar: note indices (lo, hi) of the color dyad
    stabs: tuple[tuple[tuple[int, int], ...], ...]      # per bar: note indices (lo, hi) of each stab
    base: Voicing                   # source color dyads
    stab_base: tuple[tuple[Dyad, ...], ...]
    velocities: tuple[int, ...]     # per keys note index
    max_leaps: tuple[int, ...]      # per bar pair: allowed top-voice leap


def _dyads(stack: list[int]) -> tuple[tuple[int, int], ...]:
    """Adjacent tones of the stacked chord, a 2nd to a 4th apart, as (lower pc, interval)."""
    out = []
    for a, b in zip(stack, stack[1:]):
        iv = (b - a) % 12
        if iv in DYAD_INTERVALS:
            out.append((a % 12, iv))
    return tuple(out)


def place(dyad: tuple[int, int], ref: Dyad) -> Dyad:
    """The (pc_lo, interval) dyad in the octave whose midpoint is nearest ref's (ties down)."""
    pc, iv = dyad
    mid = (ref[0] + ref[1]) / 2
    lo = min((p for p in range(ref[0] - 12, ref[0] + 13) if p % 12 == pc),
             key=lambda p: (abs(p + iv / 2 - mid), p))
    return lo, lo + iv


def read_context(src: pretty_midi.PrettyMIDI, sched, tempo: float) -> Optional[LofiKeys]:
    keys = next((i for i, x in enumerate(src.instruments)
                 if not x.is_drum and x.program == KEYS and x.name == 'keys' and x.notes), None)
    harmony = tuple(i for i, x in enumerate(src.instruments) if not x.is_drum and x.program == EP and x.notes)
    if keys is None or not harmony:
        return None
    bar_s = 4 * 60.0 / tempo
    chords = de.chord_context(src, harmony, bar_s, BARS)
    if any(c is None for c in chords):
        return None
    notes = src.instruments[keys].notes
    groups: list[dict] = [dict() for _ in range(BARS)]
    for j, n in enumerate(notes):
        b = int(n.start / bar_s + 1e-6)
        if not 0 <= b < BARS:
            return None
        groups[b].setdefault(round(n.start, 6), []).append(j)
    options, color, stabs, base, stab_base = [], [], [], [], []
    for b in range(BARS):
        stack = []
        for p in sorted(n.pitch for i in harmony for n in src.instruments[i].notes
                        if min(n.end, (b + 1) * bar_s) - max(n.start, b * bar_s) > bar_s / 2):
            if p % 12 not in [q % 12 for q in stack]:
                stack.append(p)
        opts = _dyads(stack)
        dyads = [tuple(sorted(js, key=lambda j: notes[j].pitch)) for js in groups[b].values()]
        if not opts or any(len(d) != 2 for d in dyads) or not dyads:
            return None
        ci = max(range(len(dyads)), key=lambda i: (notes[dyads[i][0]].end - notes[dyads[i][0]].start, -i))
        pair = tuple(notes[j].pitch for j in dyads[ci])
        if any(p % 12 not in chords[b].pcs for p in pair):
            return None
        options.append(opts)
        color.append(dyads[ci])
        base.append(pair)
        st = tuple(d for i, d in enumerate(dyads) if i != ci)
        stabs.append(st)
        stab_base.append(tuple(tuple(notes[j].pitch for j in d) for d in st))
    tops = [d[1] for d in base]
    return LofiKeys(keys=keys, harmony=harmony, chords=tuple(chords), options=tuple(options),
                    color=tuple(color), stabs=tuple(stabs), base=tuple(base), stab_base=tuple(stab_base),
                    velocities=tuple(n.velocity for n in notes),
                    max_leaps=tuple(max(MAX_LEAP, abs(b - a)) for a, b in zip(tops, tops[1:])))


def bar_options(c: LofiKeys, b: int) -> list[Dyad]:
    """The bar's legal dyads, placed near the source dyad, in option order."""
    return list(dict.fromkeys(place(o, c.base[b]) for o in c.options[b]))


def _pcs(d: Dyad) -> tuple[int, int]:
    return d[0] % 12, d[1] - d[0]


def valid(v: Voicing, c: LofiKeys) -> bool:
    if len(v) != BARS:
        return False
    for b, (d, s) in enumerate(zip(v, c.base)):
        if d != s and (_pcs(d) not in c.options[b] or d != place(_pcs(d), s)):
            return False
        if abs(d[1] - s[1]) > FAR:
            return False
    tops = [d[1] for d in v]
    if max(tops) > max(d[1] for d in c.base) or abs(mean(tops) - mean(d[1] for d in c.base)) > MAX_MEAN_RISE + 1e-9:
        return False
    return all(abs(b - a) <= m for a, b, m in zip(tops, tops[1:], c.max_leaps))


# =============================================================================
# Operations
# =============================================================================


def op_bar(v: Voicing, c: LofiKeys, rng: random.Random, bars, tag: str) -> tuple[Voicing, str]:
    """One bar (drawn from `bars`) takes another of its legal dyads."""
    b = rng.choice(list(bars))
    opts = [d for d in bar_options(c, b) if d != v[b]]
    if not opts:
        return v, f'{tag}:none'
    d = rng.choice(opts)
    return v[:b] + (d,) + v[b + 1:], f'{tag}@{b + 1}:{d[0]}-{d[1]}'


def _chains(c: LofiKeys, bars: range) -> list[tuple[Dyad, ...]]:
    out = [()]
    for b in bars:
        out = [ch + (d,) for ch in out for d in bar_options(c, b)]
    return out


def op_guide(v: Voicing, c: LofiKeys, rng: random.Random) -> tuple[Voicing, str]:
    """Bars 5-8 re-voiced so the top voice moves least from bar 4 on (ties: rng order)."""
    chains = _chains(c, range(4, BARS))
    rng.shuffle(chains)

    def motion(ch):
        tops = [v[3][1]] + [d[1] for d in ch]
        return sum(abs(b - a) for a, b in zip(tops, tops[1:]))
    for ch in sorted(chains, key=motion):
        new = v[:4] + ch
        if new != v and valid(new, c):
            return new, 'guide@5-8'
    return v, 'guide:none'


def _signs(v: Voicing, bars: range) -> tuple[int, ...]:
    return tuple((v[b][1] > v[b - 1][1]) - (v[b][1] < v[b - 1][1]) for b in bars)


def recalls(v: Voicing, old: Voicing, c: LofiKeys) -> list[Voicing]:
    """Bars 5-8 re-voiced with the current chords' dyads so the top voice follows
    the old voicing's contour (up / down / same, from bar 4), at most
    RECALL_MISMATCH steps off; closest contour, then least motion from v."""
    want = _signs(old, range(4, BARS))
    out = []
    for ch in _chains(c, range(4, BARS)):
        new = v[:4] + ch
        miss = sum(a != b for a, b in zip(_signs(new, range(4, BARS)), want))
        if new != v and miss <= RECALL_MISMATCH and valid(new, c):
            out.append((miss, sum(abs(a[1] - b[1]) for a, b in zip(new, v)), new))
    return [new for *_, new in sorted(out)]


def _candidate(c: LofiKeys, records: list[DevRecord], visit: int, k: int, rng: random.Random,
               gentle: bool) -> DevRecord:
    block, pos = divmod(visit, BLOCK_LEN)
    if pos == 0:
        return DevRecord(motif=c.base, theme=c.base, plan=(c.base,), role='base', ops=())
    prev = records[visit - 1]
    role = 'develop'
    if gentle:
        m, d = op_bar(prev.motif, c, rng, range(BARS), 'voice')
    elif pos == 2:
        m, d = op_bar(prev.motif, c, rng, (BARS - 1,), 'ending')
    else:
        m = prev.motif
        if block % 2:                              # candidate k: the k-th best recall
            r = recalls(prev.motif, records[(block - 1) * BLOCK_LEN + 2].motif, c)
            if k < len(r):
                role, m, d = 'recall', r[k], 'recall@5-8'
        if m == prev.motif:
            op = rng.choice(('guide', 'guide', 'voice', 'voice', 'bar4'))
            if op == 'guide':
                m, d = op_guide(prev.motif, c, rng)
            elif op == 'voice':
                m, d = op_bar(prev.motif, c, rng, range(BARS - 1), 'voice')
            else:
                m, d = op_bar(prev.motif, c, rng, (3,), 'bar4')
    return DevRecord(motif=m, theme=prev.theme, plan=(m,), role=role, ops=(d,))


def repeats(rec: DevRecord, recent: list[DevRecord], c: LofiKeys) -> Optional[str]:
    """Only developed voicings must be new; the source voicing may recur."""
    if rec.role != 'base' and rec.motif in {r.motif for r in recent}:
        return 'history'
    return None


# =============================================================================
# Level, realization, guard
# =============================================================================


@cache
def color_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_lofi_color.LEVEL_DB, levels_lofi_color.VELOCITIES, pitch, velocity)


@cache
def stab_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_lofi_stab.LEVEL_DB, levels_lofi_stab.VELOCITIES, pitch, velocity)


def stab_voicing(v: Voicing, c: LofiKeys) -> tuple[tuple[Dyad, ...], ...]:
    """Each stab takes its bar's dyad, placed near its own source register."""
    return tuple(tuple(s if d == base else place(_pcs(d), s) for s in sb)
                 for d, base, sb in zip(v, c.base, c.stab_base))


def keys_level(v: Voicing, c: LofiKeys) -> float:
    vel = c.velocities
    total = sum(color_level(p, vel[j]) for d, idx in zip(v, c.color) for p, j in zip(d, idx))
    for sv, si in zip(stab_voicing(v, c), c.stabs):
        total += sum(stab_level(p, vel[j]) for d, idx in zip(sv, si) for p, j in zip(d, idx))
    return total


def energy_shift(plan: tuple[Voicing, ...], aux, c: LofiKeys) -> dict:
    """Predicted keys level change (dB) and top-voice mean / top change vs the source."""
    v = plan[0]
    tops, base = [d[1] for d in v], [d[1] for d in c.base]
    return {'level_db': de.db(keys_level(v, c), keys_level(c.base, c)),
            'mean_rise': round(mean(tops) - mean(base), 4), 'top_rise': max(tops) - max(base)}


def energy_cost(shift: dict) -> float:
    return round(max(abs(shift['level_db']) / LEVEL_TOL_DB, max(shift['mean_rise'], 0) / MAX_MEAN_RISE), 6)


def realize(src: pretty_midi.PrettyMIDI, c: LofiKeys, plan: tuple[Voicing, ...]) -> pretty_midi.PrettyMIDI:
    out = copy.deepcopy(src)
    notes = out.instruments[c.keys].notes
    v = plan[0]
    for d, idx in zip(v, c.color):
        for p, j in zip(d, idx):
            notes[j].pitch = p
    for sv, si in zip(stab_voicing(v, c), c.stabs):
        for d, idx in zip(sv, si):
            for p, j in zip(d, idx):
                notes[j].pitch = p
    return out


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: LofiKeys) -> GuardResult:
    """Only keys pitches may change; every keys note a tone of its bar's EP chord; the
    segment's upper register stays the source's (no keys note above its highest, pitched
    p95 not lowered: re-voicing the peak bar removes the top notes that set p95)."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.keys].notes
        bad = any(notes[j].pitch % 12 not in ch.pcs
                  for ch, ci, si in zip(c.chords, c.color, c.stabs) for j in ci + tuple(x for d in si for x in d))
        top = max(notes[ci[1]].pitch for ci in c.color) > max(d[1] for d in c.base)
        low = sm.bounded_features(pm, BARS)['pitched_pitch_p95'] < sm.bounded_features(src, BARS)['pitched_pitch_p95'] - 1e-9
        return (['off_chord'] if bad else []) + (['register'] if top else []) + (['p95_lowered'] if low else [])

    return de.guard(developed, src, {c.keys: None}, check, de.MAX_PITCH_SHIFT, BARS)


def _previous(prev: DevRecord, rng: random.Random, c: LofiKeys) -> DevRecord:
    """The previous voicing with a new ending (the source's at a block start: new chords)."""
    v = prev.motif if valid(prev.motif, c) else c.base
    for _ in range(8):
        e, d = op_bar(v, c, rng, (BARS - 1,), 'ending')
        if e != v and valid(e, c):
            return DevRecord(motif=e, theme=prev.theme, plan=(e,), role='fallback', ops=(d,))
    return DevRecord(motif=v, theme=prev.theme, plan=(v,), role='fallback', ops=('ending:none',))


def unchanged_record(c: LofiKeys, records: list[DevRecord]) -> DevRecord:
    """The unchanged segment plays the source voicing; the block theme carries on."""
    theme = records[-1].theme if records and len(records) % BLOCK_LEN else c.base
    return DevRecord(c.base, theme, (c.base,), 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=_candidate, valid=lambda rec, c: all(valid(p, c) for p in rec.plan),
    energy=energy_shift, cost=energy_cost, realize=realize, guard=guard,
    previous=_previous, unchanged=unchanged_record, repeats=repeats)


def develop(src: pretty_midi.PrettyMIDI, c: LofiKeys, records: list[DevRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    return de.select(POLICY, src, c, records, visit, seed)
