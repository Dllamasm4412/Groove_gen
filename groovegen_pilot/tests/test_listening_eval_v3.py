"""
listening_eval_v3.py (the second v3 listening package): the samples ask the
generators for what the listening guide says they contain. Generation only;
rendering is covered by the package's own verification step.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

pytest.importorskip('librosa')
pytest.importorskip('pyloudnorm')

import listening_eval_v3 as le  # noqa: E402
import stimulus_metrics as sm  # noqa: E402
from composer import GENRE_CFG  # noqa: E402
from composer.v3.checks import rule_violations  # noqa: E402

TABLE = 'FluidR3_GM'


def sample(sid):
    return next(s for s in le.SAMPLES if s['id'] == sid)


def test_sample_rules_are_the_documented_ones():
    assert [sample(f'A{i}')['seed'] for i in range(1, 6)] == [101, 102, 103, 104, 105]
    assert all(sample(f'A{i}')['levels'] == (3, 3, 3) for i in range(1, 6))
    subs = {sid: le.gen_v3(sample(sid)['seed'], (3,), 'composition', TABLE)[0][1]['substyle'] for sid in ('B1', 'B2')}
    assert subs == {'B1': 'boombap', 'B2': 'dark'}
    # the first seed from 201 with each sub-style
    from composer.v3.source import HipHopV3Source
    first = {}
    for seed in range(201, 260):
        first.setdefault(HipHopV3Source(seed).current_state().spec.substyle, seed)
    assert (first['boombap'], first['dark']) == (sample('B1')['seed'], sample('B2')['seed'])


def test_constant_and_tier_tempo_play_the_same_notes():
    a = le.gen_v3(1, (2, 3, 4, 3), 'composition', TABLE)
    b = le.gen_v3(1, (2, 3, 4, 3), 'tier', TABLE)
    tiers = GENRE_CFG['hiphop']['tier_tempo']
    for (pa, ia, _), (pb, ib, _), lv in zip(a, b, (2, 3, 4, 3)):
        assert ia['role'] == ib['role'] and ib['tempo_bpm'] == tiers[lv] and ia['tempo_bpm'] == ia['comp_tempo_bpm']

        def steps(pm):
            q = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
            return sorted((i.name, int(round(n.start / q)), n.pitch, n.velocity) for i in pm.instruments for n in i.notes)
        assert steps(pa) == steps(pb)


def test_held_section_changes_only_the_level():
    ramp = le.gen_v3_held(101, 1, (1, 2, 3, 4, 5), TABLE)
    plans = [p for _, _, p in ramp]
    assert {p.role for p in plans} == {'S'}
    assert len({(p.harmony, p.hook_units, p.fills, p.op) for p in plans}) == 1
    assert [p.level for p in plans] == [1, 2, 3, 4, 5]
    for pm, info, plan in ramp:
        assert rule_violations(pm, plan, info['tempo_bpm']) == []
    steady = le.gen_v3_held(101, 1, (3,) * 5, TABLE)
    assert len({sm.midi_sha256(pm) for pm, _, _ in steady}) == 1
    # the held section is A1's second segment
    a1 = le.gen_v3(101, (3, 3), 'composition', TABLE)
    assert sm.midi_sha256(a1[1][0]) == sm.midi_sha256(steady[0][0])


def test_blind_assignment_is_fixed_and_mixed():
    ids = [p['id'] for p in le.PAIRS]
    a = le.blind_assignments(ids)
    assert a == le.blind_assignments(ids)
    assert all(sorted(v.values()) == ['v2c', 'v3'] for v in a.values())
    assert 0 < sum(v['X'] == 'v3' for v in a.values()) < len(ids)


def test_pairs_match_tier_tempo_and_length():
    for p in le.PAIRS:
        v2 = le.gen_v2c(p['seed'], p['tier'], le.E_SEGMENTS)
        v3 = le.gen_v3(p['seed'], (p['tier'],) * le.E_SEGMENTS, 'tier', TABLE)
        assert len(v2) == len(v3) == le.E_SEGMENTS
        # v2c's MIDI stores the tempo at microsecond resolution (90 BPM reads back as 89.99995)
        assert {round(float(pm.get_tempo_changes()[1][0]), 3) for pm, _, _ in v2 + v3} == \
            {float(GENRE_CFG['hiphop']['tier_tempo'][p['tier']])}
