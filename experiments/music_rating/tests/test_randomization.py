"""Participant-level randomization: deterministic, complete, constrained."""

from __future__ import annotations

import session_store as ss
import stimuli as st


def main_of(manifest):
    return st.by_kind(manifest, 'main')


def test_same_code_same_order(loaded):
    _, manifest, _ = loaded
    seed = ss.participant_seed('P001')
    assert seed == ss.participant_seed('P001')
    assert ss.randomize(main_of(manifest), seed) == ss.randomize(main_of(manifest), seed)


def test_orders_differ_between_participants(loaded):
    _, manifest, _ = loaded
    orders = {tuple(ss.randomize(main_of(manifest), ss.participant_seed(f'P{i:03d}'))[0]) for i in range(1, 41)}
    assert len(orders) == 40


def test_every_order_is_complete_and_constrained(loaded):
    _, manifest, _ = loaded
    main = main_of(manifest)
    ladder = [s['stimulus_id'] for s in sorted(main, key=lambda s: s['rung'])]
    genre = {s['stimulus_id']: s['genre'] for s in main}
    for i in range(1, 201):
        order, attempts = ss.randomize(main, ss.participant_seed(f'P{i:03d}'))
        assert sorted(order) == sorted(ladder) and len(order) == 27 == len(set(order))
        assert order != ladder and order != ladder[::-1]
        assert all(genre[a] != genre[b] for a, b in zip(order, order[1:]))
        assert abs(ss.rank_corr(order, ladder)) <= ss.MAX_ABS_RANK_CORR
        assert attempts >= 1


def test_rank_corr_extremes(loaded):
    ids = list('abcdefg')
    assert ss.rank_corr(ids, ids) == 1.0
    assert ss.rank_corr(ids[::-1], ids) == -1.0


def test_session_records_seed_and_plan(new_session, loaded):
    _, manifest, _ = loaded
    sess = new_session('P007')
    m = sess.meta
    assert m['randomization_seed'] == ss.participant_seed('P007')
    order, _ = ss.randomize(main_of(manifest), m['randomization_seed'])
    trials = m['trials']
    practice_ids = [s['stimulus_id'] for s in st.by_kind(manifest, 'practice')]
    assert [t['stimulus_id'] for t in trials[:2]] == practice_ids            # practice first, fixed order
    assert [t['kind'] for t in trials] == ['practice'] * 2 + ['main'] * 27
    assert [t['stimulus_id'] for t in trials[2:]] == order
    assert [t['presentation_order'] for t in trials[2:]] == list(range(1, 28))
    assert not set(practice_ids) & set(order)
