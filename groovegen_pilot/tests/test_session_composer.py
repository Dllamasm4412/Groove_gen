"""
Tests for the v2 Phase 2a generator (composer/arrangement.py, variation.py,
energy_guard.py): determinism, seed schedule, key lock, guard invariants and
the repetition targets of LIVE_GENERATION_PLAN.md on every live cell.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import generate_segment  # noqa: E402
from composer.arrangement import (BARS, BLOCK_LEN, SessionComposer, cell_plan,  # noqa: E402
                                  schedule, session_key)
from composer.energy_guard import _drum_notes, _pitched, check  # noqa: E402
from composer.variation import protected_notes  # noqa: E402
from stimulus_audit import live_ladder  # noqa: E402

VISITS = 6


@pytest.fixture(scope='module')
def live_cells() -> list[tuple[str, int]]:
    ladder, _ = live_ladder('measured')
    return [(c.genre, c.tier) for c in ladder.cells]


def _base(genre: str, tier: int, base_seed: int):
    tempo, density = cell_plan(genre, tier)
    return generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=BARS, seed=base_seed)


def test_deterministic_across_instances():
    for genre, tier in (('pop', 3), ('latin', 2), ('hiphop', 1)):
        for v in (0, 4):
            a, ia = SessionComposer(1).compose(genre, tier, v)
            b, ib = SessionComposer(1).compose(genre, tier, v)
            assert sm.midi_sha256(a) == sm.midi_sha256(b)
            assert ia == ib


def test_stim_seed_changes_content():
    a, _ = SessionComposer(1).compose('pop', 3, 0)
    b, _ = SessionComposer(2).compose('pop', 3, 0)
    assert sm.midi_sha256(a) != sm.midi_sha256(b)


def test_block_reuse_and_fresh_var_seeds():
    s = [schedule(1, 'rnb', 2, v) for v in range(2 * BLOCK_LEN)]
    assert len({x.base_seed for x in s[:BLOCK_LEN]}) == 1
    assert len({x.base_seed for x in s[BLOCK_LEN:]}) == 1
    assert s[0].base_seed != s[BLOCK_LEN].base_seed
    assert len({x.var_seed for x in s}) == len(s)
    assert [x.pos_in_block for x in s] == list(range(BLOCK_LEN)) * 2


def test_schedule_rejects_negative_visit():
    with pytest.raises(ValueError):
        schedule(1, 'pop', 3, -1)


@pytest.mark.parametrize('genre', ['hiphop', 'rock'])
def test_session_key_lock(genre, live_cells):
    """Every base seed of a key-locked genre picks the session key, and the
    frozen cell itself records that key when generating from the seed (pins
    cell_key to real output; tonal_collection is not used because a flat-7
    progression in C fits the F major collection)."""
    from composer import GENRE_CFG
    if genre == 'hiphop':
        from composer.hiphop_cell import generate_hiphop_segment as gen
    else:
        from composer.rock_cell import generate_rock_segment as gen

    lo, hi = GENRE_CFG[genre]['tempo_range']
    for stim in (1, 2):
        want = session_key(stim, genre)
        assert want is not None
        for g, tier in live_cells:
            if g != genre:
                continue
            tempo, density = cell_plan(genre, tier)
            for v in (0, BLOCK_LEN, 2 * BLOCK_LEN):
                sch = schedule(stim, genre, tier, v)
                assert sch.session_key == want
                score = gen(tempo_bpm=max(lo, min(hi, tempo)), density=density,
                            duration_bars=BARS, seed=sch.base_seed)
                assert getattr(score.metadata, f'groovegen_{genre}_spec')['key_root'] == want


def test_other_genres_not_key_locked():
    assert session_key(1, 'pop') is None
    assert schedule(1, 'pop', 3, 0).key_draws == 1


@pytest.mark.parametrize('cell', [('calm', 1), ('lofi', 3), ('rnb', 4), ('pop', 5),
                                  ('latin', 3), ('hiphop', 2), ('rock', 4)])
def test_guard_invariants_against_regenerated_base(cell):
    genre, tier = cell
    sc = SessionComposer(1)
    for v in range(VISITS):
        pm, info = sc.compose(genre, tier, v)
        assert not info['gen_fallback'] and info['error'] is None
        base = _base(genre, tier, info['base_seed'])
        assert _pitched(pm) == _pitched(base)
        assert sm.locked_signature(pm) == sm.locked_signature(base)
        assert set(protected_notes(base, genre)) <= set(_drum_notes(pm))
        assert set(sm.bounded_set_features(pm)['drum_voices']) <= set(sm.bounded_set_features(base)['drum_voices'])
        assert len(_drum_notes(pm)) == len(_drum_notes(base))
        assert check(pm, base, genre).ok
        assert _drum_notes(pm) != _drum_notes(base)


def test_repetition_targets_all_live_cells(live_cells):
    """R1 >= 3 distinct drum bars, R2 <= 3 identical bars in a row, bar 8
    marked, no fallback, no exact repeat within a block."""
    sc = SessionComposer(1)
    bad = []
    for genre, tier in live_cells:
        drums = []
        for v in range(VISITS):
            pm, info = sc.compose(genre, tier, v)
            m = sm.segment_metrics(pm, BARS)
            drums.append(m['drum_sha'])
            if (info['gen_fallback'] or m['distinct_drum_bars'] < 3
                    or m['max_identical_drum_run'] > 3 or not m['phrase_end_bar8_marked']):
                bad.append((genre, tier, v, info['gen_fallback'], m['distinct_drum_bars'],
                            m['max_identical_drum_run'], m['phrase_end_bar8_marked']))
        for b in range(0, VISITS, BLOCK_LEN):
            block = drums[b:b + BLOCK_LEN]
            if len(set(block)) != len(block):
                bad.append((genre, tier, f'block {b // BLOCK_LEN} repeats'))
    assert not bad, bad


def test_variation_error_falls_back_to_base(monkeypatch):
    import composer.variation as variation

    def boom(*a, **k):
        raise RuntimeError('boom')

    monkeypatch.setattr(variation, 'vary', boom)
    pm, info = SessionComposer(1).compose('pop', 3, 0)
    assert info['gen_fallback'] and 'boom' in info['error']
    assert sm.midi_sha256(pm) == sm.midi_sha256(_base('pop', 3, info['base_seed']))
