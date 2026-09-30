"""
Energy guard for the v2 generator (LIVE_GENERATION_PLAN.md sections 3 and 4.8).

check(varied, base, genre) accepts a variation only if, against its own base
segment:
  1. locked features are identical (tempo, tempo-map length, bar count,
     GM programs);
  2. drum voices are a subset of the base's (bounded-set feature);
  3. the pitched tracks are note-for-note identical (Phase 2a varies drums only);
  4. every protected drum note (composer/variation.py) is present unchanged;
  5. the drum note count is unchanged (all ops are count-neutral);
  6. the bounded MIDI features stay within BOUNDS of the base.

Per-role drum rates are reported in deltas but not gated: fills re-voice hats
as snare / conga by design, and the energy table does not use role rates.
Their timbre effect is checked on rendered audio (plan section 6.3).
The cell-envelope and audio checks belong to certification (Phase 3).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pretty_midi

import stimulus_metrics as sm
from composer.variation import protected_notes

BARS = 8
# Provisional, relative to the base segment (plan section 3.2): 'rel' is a
# fraction of the base value, 'abs' an absolute difference.
BOUNDS: dict[str, tuple[str, float]] = {
    'drum_rate': ('rel', 0.04),
    'note_rate': ('rel', 0.05),
    'drum_onbeat_ratio': ('abs', 0.05),
    'vel_mean': ('abs', 2.0),
    'vel_p90': ('abs', 3.0),
    'drum_vel_mean': ('abs', 2.0),
}
REPORTED = ('drum_low_rate', 'drum_backbeat_rate', 'drum_hats_rate', 'drum_hand_rate')


@dataclass
class GuardResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    deltas: dict[str, float] = field(default_factory=dict)


def _pitched(pm: pretty_midi.PrettyMIDI) -> list[tuple]:
    return [(i, n.pitch, round(n.start, 6), round(n.end, 6), n.velocity)
            for i, inst in enumerate(pm.instruments) if not inst.is_drum
            for n in sorted(inst.notes, key=lambda n: (n.start, n.pitch))]


def _drum_notes(pm: pretty_midi.PrettyMIDI) -> list[tuple]:
    return sorted((n.pitch, round(n.start, 6), round(n.end, 6), n.velocity)
                  for inst in pm.instruments if inst.is_drum for n in inst.notes)


def bounded_deltas(fv: dict, fb: dict) -> dict[str, float]:
    """Delta of each BOUNDS feature, in the bound's own unit ('rel' or 'abs')."""
    out = {}
    for f, (kind, _) in BOUNDS.items():
        d = fv[f] - fb[f]
        out[f] = round(d / fb[f], 4) if kind == 'rel' and fb[f] else round(d, 4)
    return out


def within_bounds(fv: dict, fb: dict, frac: float = 1.0) -> bool:
    """True if every BOUNDS feature of fv is within frac * tolerance of fb."""
    d = bounded_deltas(fv, fb)
    return all(abs(d[f]) <= frac * tol + 1e-9 for f, (_, tol) in BOUNDS.items())


def check(varied: pretty_midi.PrettyMIDI, base: pretty_midi.PrettyMIDI, genre: str) -> GuardResult:
    fails: list[str] = []
    if sm.locked_signature(varied) != sm.locked_signature(base):
        fails.append('locked')
    v_voices = set(sm.bounded_set_features(varied)['drum_voices'])
    b_voices = set(sm.bounded_set_features(base)['drum_voices'])
    if not v_voices <= b_voices:
        fails.append(f'drum_voices+{sorted(v_voices - b_voices)}')
    if _pitched(varied) != _pitched(base):
        fails.append('pitched_changed')
    v_drums = _drum_notes(varied)
    if not set(protected_notes(base, genre)) <= set(v_drums):
        fails.append('protected_changed')
    if len(v_drums) != len(_drum_notes(base)):
        fails.append('drum_count')

    fv, fb = sm.bounded_features(varied, BARS), sm.bounded_features(base, BARS)
    deltas = bounded_deltas(fv, fb)
    fails += [f'{f}:{deltas[f]:+g}' for f in BOUNDS if abs(deltas[f]) > BOUNDS[f][1] + 1e-9]
    for f in REPORTED:
        deltas[f] = round(fv[f] - fb[f], 4)
    return GuardResult(ok=not fails, failures=fails, deltas=deltas)
