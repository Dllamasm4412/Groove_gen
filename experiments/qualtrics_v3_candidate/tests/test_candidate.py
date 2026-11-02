"""
Candidate corpus builder: the conditions, seeds, IDs and audio finishing it
relies on. Fast (no full build); the build verifies its own output files.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
pytest.importorskip('pyloudnorm')

import build_candidate as bc  # noqa: E402


def test_conditions_are_the_original_27():
    conds, src = bc.load_conditions()
    assert len(conds) == 27 and [c['ladder_rung'] for c in conds] == list(range(27))
    assert len({c['condition_id'] for c in conds}) == 27
    assert {c['genre'] for c in conds} == {'calm', 'lofi', 'rnb', 'pop', 'latin', 'hiphop', 'rock'}
    assert src['source'].startswith('experiments/music_rating/stimuli/')


def test_neutral_ids_are_a_hidden_permutation():
    conds, _ = bc.load_conditions()
    ids = bc.neutral_ids(conds)
    assert sorted(ids.values()) == [f'S{i:02d}' for i in range(1, 28)]
    in_rung_order = [ids[c['condition_id']] for c in conds]
    assert in_rung_order != sorted(in_rung_order)            # not the ladder order
    by_genre = {}
    for c in conds:
        by_genre.setdefault(c['genre'], []).append(int(ids[c['condition_id']][1:]))
    assert not all(v == sorted(v) and v[-1] - v[0] == len(v) - 1 for v in by_genre.values())


@pytest.mark.parametrize('cell', ['calm:1', 'hiphop:3', 'rock:5', 'latin:2'])
def test_original_condition_segment_is_reproduced_exactly(cell):
    from stimulus_metrics import midi_sha256

    conds, _ = bc.load_conditions()
    c = next(c for c in conds if c['condition_id'] == cell)
    pm, info = bc.v2c_segment(c['genre'], c['tier'])
    assert midi_sha256(pm) == c['original_segment_midi_sha256']
    assert float(info['tempo_bpm']) == c['tempo_bpm']


def test_candidate_seeds_are_fixed():
    assert bc.H(bc.SEED_SALT, 'pop', 3, 0) == bc.H(bc.SEED_SALT, 'pop', 3, 0)
    assert bc.H(bc.SEED_SALT, 'pop', 3, 0) != bc.H(bc.SEED_SALT, 'pop', 3, 1)


def test_finish_cuts_eight_bars_with_fades():
    tempo = 100.0
    raw = np.ones((bc.bar_frames(tempo) * 9, 2), np.float32) * 0.5
    clip = bc.finish(raw, tempo, 8)
    assert clip.shape[0] == 8 * bc.bar_frames(tempo) + int(round(bc.bar_frames(tempo) * bc.FADE_BARS))
    assert abs(clip[0, 0]) < 1e-6 and abs(clip[-1, 0]) < 0.01 and abs(clip[clip.shape[0] // 2, 0] - 0.5) < 1e-6


def test_preview_is_about_ten_seconds():
    for tempo in (65, 78, 90, 104, 118, 130):
        n = bc.preview_bars(tempo)
        assert 2 <= n <= 8 and abs(n * 240.0 / tempo - 10.0) <= 120.0 / tempo + 1e-9
