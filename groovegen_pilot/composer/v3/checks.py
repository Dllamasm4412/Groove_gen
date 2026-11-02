"""
Musical rule checks and identity signatures for v3 hip-hop segments.

rule_violations(pm, plan, tempo) returns a list of violated rules (empty =
all pass). These are the structural and pairwise constraints of the plan
(section 6.4): they show that the parts agree with each other and with the
shared plan; they are not evidence of musical quality.
"""

from __future__ import annotations

import bisect

import pretty_midi

from composer.v3.hiphop import KICK, hook_notes
from composer.v3.state import CompositionSpec, SegmentPlan
from composer.v3.theory import BARS, STEPS_PER_BAR, Grid, melodic_pcs

VOCAL_PROGRAMS = {52, 53, 54, 85, 91}
RANGES = {'bass': (28, 57), 'chords': (40, 84), 'hook': (50, 100), 'counter': (46, 84), 'double': (50, 112)}
TOL_S = 0.03


def _steps(grid: Grid) -> list[float]:
    return [grid.t(s) for s in range(BARS * STEPS_PER_BAR + 1)]


def _step_of(times: list[float], t: float) -> int | None:
    i = bisect.bisect_left(times, t - TOL_S)
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(times) and abs(times[j] - t) <= TOL_S:
            return j
    return None


def rule_violations(pm: pretty_midi.PrettyMIDI, plan: SegmentPlan, tempo: float) -> list[str]:
    spec = plan.spec
    grid = Grid(tempo, spec.swing)
    times = _steps(grid)
    bad: list[str] = []
    inst = {i.name: i for i in pm.instruments}

    # MIDI validity
    tempi = pm.get_tempo_changes()[1]
    if len(tempi) != 1 or abs(tempi[0] - tempo) > 1e-6:
        bad.append('tempo')
    for i in pm.instruments:
        if not i.is_drum and i.program in VOCAL_PROGRAMS:
            bad.append(f'vocal_program:{i.name}')
        lo, hi = RANGES.get(i.name, (0, 127))
        for n in i.notes:
            if not (1 <= n.velocity <= 127) or n.end <= n.start or n.start < 0 or n.end > grid.seg_s + 1e-6:
                bad.append(f'note_invalid:{i.name}')
                break
            if not i.is_drum and not lo <= n.pitch <= hi:
                bad.append(f'range:{i.name}:{n.pitch}')
                break
        by_pitch: dict[int, list] = {}
        for n in i.notes:
            by_pitch.setdefault(n.pitch, []).append(n)
        for ns in by_pitch.values():
            ns.sort(key=lambda n: n.start)
            if any(a.end > b.start + 1e-6 for a, b in zip(ns, ns[1:])):
                bad.append(f'same_pitch_overlap:{i.name}')
                break
    for name in ('drums', 'bass', 'chords'):
        if name not in inst:
            bad.append(f'missing:{name}')
    if bad and any(b.startswith('missing') for b in bad):
        return bad

    # groove anchors: kick on 1 and the backbeat on 2 and 4 in every bar
    drums = inst['drums'].notes
    lag = spec.snare_lag_s
    kick_steps = {_step_of(times, n.start) for n in drums if n.pitch == KICK}
    snare_steps = {_step_of(times, n.start - lag) for n in drums if n.pitch == spec.snare_pitch}
    for bar in range(BARS):
        b0 = bar * STEPS_PER_BAR
        if b0 not in kick_steps:
            bad.append(f'kick_downbeat:bar{bar + 1}')
        if not {b0 + 4, b0 + 12} <= snare_steps:
            bad.append(f'backbeat:bar{bar + 1}')

    # bass: the chord root at every change; other notes on a kick, or a pickup
    key = spec.key_pc
    bass = sorted(inst['bass'].notes, key=lambda n: n.start)
    bass_on = {}
    for n in bass:
        s = _step_of(times, n.start)
        if s is None:
            bad.append('bass_offgrid')
            continue
        bass_on[s] = n.pitch
    for s in plan.changes():
        if plan.fills[1] == 'dropout' and s >= 120:
            continue
        if bass_on.get(s) is None or bass_on[s] % 12 != plan.chord_at(s).root_pc(key):
            bad.append(f'bass_root_at_change:{s}')
    changes = set(plan.changes())
    for s in bass_on:
        if s in changes or s % STEPS_PER_BAR == 0 or s in kick_steps or s % STEPS_PER_BAR in (14, 15):
            continue
        bad.append(f'bass_unlocked:{s}')

    # hook: on-beat notes are chord tones; every note avoids semitone clashes
    for g, pitch, _, strong in hook_notes(plan):
        chord = plan.chord_at(g)
        if strong and pitch % 12 not in chord.core_pcs(key):
            bad.append(f'hook_strong_not_chord_tone:{g}')
        elif pitch % 12 not in melodic_pcs(chord, key, spec.mode):
            bad.append(f'hook_avoid_note:{g}')

    # the counter-line stays under the melody it accompanies
    if 'counter' in inst and 'hook' in inst:
        for c in inst['counter'].notes:
            if any(h.start < c.end and c.start < h.end and c.pitch >= h.pitch for h in inst['hook'].notes):
                bad.append(f'counter_not_below_hook:{c.pitch}')
                break

    # chords: every voicing note belongs to its chord (or the anticipated next one)
    for n in inst['chords'].notes:
        s = _step_of(times, n.start)
        if s is None:
            bad.append('chord_offgrid')
            continue
        pcs = set(plan.chord_at(s).pcs(key))
        nxt_bar = s - s % STEPS_PER_BAR + STEPS_PER_BAR
        if s % STEPS_PER_BAR >= 14 and nxt_bar < BARS * STEPS_PER_BAR:
            pcs |= set(plan.chord_at(nxt_bar).pcs(key))
        if n.pitch % 12 not in pcs:
            bad.append(f'chord_tone:{s}')
            break
    return bad


def identity(spec: CompositionSpec) -> dict:
    """Transposition-invariant identity of a composition (key and tempo excluded)."""
    return {
        'substyle': spec.substyle,
        'loop_a': spec.loop_a.signature(),
        'loop_b': spec.loop_b.signature(),
        'motif': spec.motif.signature(),
        'kick': (spec.kick_a, spec.kick_b),
        'palette': spec.palette,
        'comp': (spec.comp_style, spec.comp_rhythm),
        'bass': spec.bass_style,
    }


def identity_differences(a: CompositionSpec, b: CompositionSpec) -> list[str]:
    ia, ib = identity(a), identity(b)
    return [k for k in ia if ia[k] != ib[k]]
