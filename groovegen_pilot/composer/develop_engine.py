"""
Shared pitched-development engine for the v2 SessionComposer (opt-in,
SessionComposer(stim_seed, develop=True); LIVE_GENERATION_PLAN.md 6.12-6.15).
Not used by the live runner.

    SessionComposer -> develop_engine (this module) -> genre policy

The engine owns what every genre shares: the record type, the deterministic
candidate loop and its ranking, the history window (exact and near repeats),
the energy check with an optional repair, the gentle pass and the fallback
chain (previous material with a new ending, then the unchanged segment), the
generic guard (locked signature, track shapes, untouched notes and tracks,
energy_guard BOUNDS, pitched register shift), measured per-note levels,
chord context read from the comping tracks, IDs and provenance.

A genre policy (composer/motif.py hiphop, composer/dev_calm.py,
composer/dev_lofi.py, composer/dev_rnb.py, composer/dev_pop.py) supplies the musical part as a Policy plus module
functions read_context / develop / unchanged_record, and is registered in
POLICIES. Policies are pitch-only: onsets, durations, velocities, note counts,
programs and tempo stay the source segment's.

Selection (select()): N candidates per pass from deterministic sub-seeds
(seed << 8 | k + gentle * N). A candidate failing the policy rules or
repeating the history window is rejected; one failing only the energy check
gets the policy's repair, if any. Passing candidates are ranked unrepaired
first, then energy cost, then k; the first that passes the guard is used. If
none does, the gentle pass; then policy.previous (the previous visit's
material with a new ending; its plan must not repeat the window); then the
unchanged segment. motif_selection
logs which. This is the hiphop v2b.1 selection unchanged; its MIDI is pinned
by tests/test_develop_identity.py.
"""

from __future__ import annotations

import importlib
import math
import random
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import pretty_midi

import stimulus_metrics as sm
from composer.energy_guard import BOUNDS, GuardResult, bounded_deltas

BARS = 8
MAX_PITCH_SHIFT = 2.0      # semitones: pitched median / p05 / p95 vs the source segment
# genre -> policy module. Each exposes DEV_VERSION, SEED_VERSION,
# read_context(src, sched, tempo), develop(src, ctx, records, visit, seed),
# unchanged_record(ctx, records) and, optionally, DRUM_REPEAT_WINDOW.
# rock has deliberately no policy (LIVE_GENERATION_PLAN.md section 6.17): its
# pitched layer is a power-chord gallop with no line to develop, so develop mode
# leaves it byte-identical.
POLICIES = {'hiphop': 'composer.motif', 'calm': 'composer.dev_calm', 'lofi': 'composer.dev_lofi',
            'rnb': 'composer.dev_rnb', 'pop': 'composer.dev_pop', 'latin': 'composer.dev_latin'}
DEVELOP_GENRES = tuple(POLICIES)


@dataclass(frozen=True)
class DevRecord:
    motif: tuple                # this visit's material (hiphop: the motif M)
    theme: tuple                # the block's theme
    plan: tuple                 # what is played (hiphop: 4 phrases)
    role: str                   # base | develop | derive | return | recall | fallback ...
    ops: tuple[str, ...]


@dataclass(frozen=True)
class Policy:
    """The genre-specific half of select(). ctx is the policy's read of the
    source segment; aux is prepare(src, ctx), computed once per visit."""
    dev_version: str
    history_window: int
    n_candidates: int
    candidate: Callable          # (ctx, records, visit, k, rng, gentle) -> DevRecord
    valid: Callable              # (rec, ctx) -> bool: the rules, every plan element
    energy: Callable             # (plan, aux, ctx) -> dict
    cost: Callable               # (shift) -> float, <= 1 passes
    realize: Callable            # (src, ctx, plan) -> PrettyMIDI
    guard: Callable              # (out, src, ctx) -> GuardResult
    previous: Callable           # (prev record, rng, ctx) -> DevRecord: fallback material
    unchanged: Callable          # (ctx, records) -> DevRecord: the record of the unchanged segment
    prepare: Callable = lambda src, ctx: None
    repeats: Optional[Callable] = None   # (rec, recent records, ctx) -> reason or None; default exact
    repair: Optional[Callable] = None    # (rec, ctx, aux, why_not) -> DevRecord or None
    repair_op: str = 'balance'           # op prefix that marks a repaired candidate


def policy_module(genre: str):
    """The registered policy module of genre, or None."""
    name = POLICIES.get(genre)
    return importlib.import_module(name) if name else None


def exact_repeat(rec: DevRecord, recent: Sequence[DevRecord], ctx=None) -> Optional[str]:
    """The default history rule: the material or the whole plan equals a recent visit's."""
    if rec.motif in {r.motif for r in recent} or rec.plan in {r.plan for r in recent}:
        return 'history'
    return None


def select(policy: Policy, src: pretty_midi.PrettyMIDI, ctx, records: list[DevRecord], visit: int,
           seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    """Visit `visit` of the cell, given records of visits 0..visit-1 (in order)."""
    recent = records[-policy.history_window:]
    repeats = policy.repeats or exact_repeat
    aux = policy.prepare(src, ctx)
    info = {'dev_version': policy.dev_version, 'motif_candidates': 0, 'motif_rejections': {}}

    def reject(why: str) -> None:
        info['motif_rejections'][why] = info['motif_rejections'].get(why, 0) + 1

    def why_not(rec: DevRecord) -> Optional[str]:
        if not policy.valid(rec, ctx):
            return 'rules'
        return repeats(rec, recent, ctx) if visit else None

    n = policy.n_candidates
    for gentle in (False, True):
        ranked = []
        for k in range(n):
            rec = policy.candidate(ctx, records, visit, k, random.Random((seed << 8) | (k + gentle * n)), gentle)
            info['motif_candidates'] += 1
            why = why_not(rec)
            if why is None and policy.cost(policy.energy(rec.plan, aux, ctx)) > 1:
                rec = policy.repair(rec, ctx, aux, why_not) if policy.repair else None
                why = 'energy' if rec is None else None
            if why:
                reject(why)
                continue
            shift = policy.energy(rec.plan, aux, ctx)
            ranked.append(((bool(rec.ops) and rec.ops[-1].startswith(policy.repair_op), policy.cost(shift), k),
                           rec, shift))
        for (_, _, k), rec, shift in sorted(ranked, key=lambda x: x[0]):
            out = policy.realize(src, ctx, rec.plan)
            verdict = policy.guard(out, src, ctx)
            if verdict.ok:
                info.update(motif_candidate_idx=k, motif_fallback=False,
                            motif_selection='gentle' if gentle else 'candidate',
                            motif_guard_deltas=verdict.deltas, motif_energy=shift)
                return out, rec, describe(info, rec)
            reject('guard')
    info.update(motif_candidate_idx=None, motif_fallback=True)
    if records:
        rec = policy.previous(records[-1], random.Random(seed), ctx)
        shift = policy.energy(rec.plan, aux, ctx)
        out = policy.realize(src, ctx, rec.plan)
        if rec.plan not in {r.plan for r in recent} and policy.cost(shift) <= 1 and policy.guard(out, src, ctx).ok:
            info.update(motif_selection='previous', motif_energy=shift)
            return out, rec, describe(info, rec)
    rec = policy.unchanged(ctx, records)
    info.update(motif_selection='unchanged', motif_energy=policy.energy(rec.plan, aux, ctx))
    return src, rec, describe(info, rec)


def material_id(m) -> str:
    return sm.content_sha([frozenset(m)])[:8]


def describe(info: dict, rec: DevRecord) -> dict:
    info.update(motif_role=rec.role, motif_ops=list(rec.ops), motif_id=material_id(rec.motif),
                motif_theme_id=material_id(rec.theme), motif_plan=[material_id(p) for p in rec.plan])
    return info


# =============================================================================
# Guard
# =============================================================================


def track_shape(inst) -> tuple:
    return (len(inst.notes), tuple(sorted(Counter(n.velocity for n in inst.notes).items())),
            tuple(sorted(Counter(round(n.end - n.start, 6) for n in inst.notes).items())))


def track_notes(inst) -> list[tuple]:
    return sorted((n.pitch, round(n.start, 6), round(n.end, 6), n.velocity) for n in inst.notes)


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI,
          mutable: dict[int, Optional[tuple[Callable[[int], bool], str]]],
          check: Optional[Callable[[pretty_midi.PrettyMIDI], list[str]]] = None,
          max_pitch_shift: float = MAX_PITCH_SHIFT, bars: int = BARS) -> GuardResult:
    """Development may change only the notes of the `mutable` tracks: None
    allows any note of the track, (keep, name) keeps the notes whose pitch
    satisfies keep (failure `name`). Every track keeps its note count,
    velocities and durations; other tracks are identical. check() adds the
    policy's own failures (key, register). Then the energy_guard BOUNDS and
    the pitched median / p05 / p95 shift."""
    fails: list[str] = []
    if sm.locked_signature(developed) != sm.locked_signature(src):
        fails.append('locked')
    if len(developed.instruments) != len(src.instruments):
        return GuardResult(ok=False, failures=fails + ['tracks'])
    for i, (a, b) in enumerate(zip(developed.instruments, src.instruments)):
        if track_shape(a) != track_shape(b):
            fails.append(f'shape[{i}]')
        if i in mutable:
            if mutable[i] is not None:
                keep, name = mutable[i]
                if [x for x in track_notes(a) if keep(x[0])] != [x for x in track_notes(b) if keep(x[0])]:
                    fails.append(name)
        elif track_notes(a) != track_notes(b):
            fails.append(f'track[{i}]_changed')
    if check is not None:
        fails += check(developed)
    fv, fb = sm.bounded_features(developed, bars), sm.bounded_features(src, bars)
    deltas = bounded_deltas(fv, fb)
    fails += [f'{f}:{deltas[f]:+g}' for f in BOUNDS if abs(deltas[f]) > BOUNDS[f][1] + 1e-9]
    for f in ('pitched_pitch_median', 'pitched_pitch_p05', 'pitched_pitch_p95'):
        deltas[f] = round(fv[f] - fb[f], 4)
        if abs(deltas[f]) > max_pitch_shift + 1e-9:
            fails.append(f'{f}:{deltas[f]:+g}')
    return GuardResult(ok=not fails, failures=fails, deltas=deltas)


# =============================================================================
# Measured levels
# =============================================================================


def table_level(level_db: dict, velocities: Sequence[int], pitch: int, velocity: int) -> float:
    """Rendered energy of one note (linear) from a measured level table:
    dB interpolated between the measured velocities, pitch and velocity
    clamped to the table."""
    row = level_db[min(max(pitch, min(level_db)), max(level_db))]
    v = min(max(velocity, velocities[0]), velocities[-1])
    i = min(sum(v >= x for x in velocities) - 1, len(velocities) - 2)
    f = (v - velocities[i]) / (velocities[i + 1] - velocities[i])
    return 10 ** ((row[i] + f * (row[i + 1] - row[i])) / 10)


def db(a: float, b: float) -> float:
    """Level of a over b in dB (0 when either is not positive), rounded to 1e-4."""
    return round(10 * math.log10(a / b), 4) if a > 0 and b > 0 else 0.0


# =============================================================================
# Chord context
# =============================================================================


@dataclass(frozen=True)
class ChordContext:
    pcs: frozenset              # pitch classes sounding in the bar on the harmony tracks
    root: int                   # pitch class of the lowest of them at the bar start
    bass: int                   # that lowest MIDI pitch


def chord_context(pm: pretty_midi.PrettyMIDI, tracks: Sequence[int], bar_s: float,
                  bars: int = BARS, min_frac: float = 0.5) -> list[Optional[ChordContext]]:
    """Per bar, the chord the comping tracks actually play: the pitch classes of
    every note of `tracks` sounding for more than min_frac of the bar (0: any
    note sounding in the bar, for stabbed comping such as pop's EP), root =
    lowest of them. Read from the MIDI (no key or scale assumed); None for a
    bar with no such note. Used only to choose legal pitches."""
    out: list[Optional[ChordContext]] = []
    for b in range(bars):
        lo, hi = b * bar_s, (b + 1) * bar_s
        held = [n.pitch for i in tracks for n in pm.instruments[i].notes
                if min(n.end, hi) - max(n.start, lo) > bar_s * min_frac]
        out.append(ChordContext(frozenset(p % 12 for p in held), min(held) % 12, min(held)) if held else None)
    return out


def chord_tones(ctx: ChordContext, lo: int, hi: int) -> list[int]:
    """MIDI pitches lo..hi whose pitch class is in the chord."""
    return [p for p in range(lo, hi + 1) if p % 12 in ctx.pcs]


def neighbor_tones(pitch: int, ctx: ChordContext, near: int = 2, far: int = 5) -> list[int]:
    """Chord tones near pitch, per direction: those within `near` semitones,
    else the nearest one within `far` (steps where the chord has them, no
    forced steps)."""
    out = []
    for side in (chord_tones(ctx, pitch + 1, pitch + far), chord_tones(ctx, pitch - far, pitch - 1)[::-1]):
        close = [p for p in side if abs(p - pitch) <= near]
        out += close or side[:1]
    return out
