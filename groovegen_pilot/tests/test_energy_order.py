"""
Live-ladder energy order after the first v2c live run (2026-10-05): energy is
measured without the Rock presentation gain (music_features_measured.
energy_audio), the developer's by-ear ratings can reorder the measured ladder
(ladder.build_ladder(ear_ratings=), energy_by_ear.py, run_pilot_zero --ladder
ear), and saturation rotation no longer alternates two cells
(ControllerConfig.rotation_no_repeat).
"""

from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

from control import ControllerConfig, LadderMPC  # noqa: E402
from ladder import _to_ladder, build_ladder, load_ear_ratings, load_energy_table  # noqa: E402

SF2 = PILOT.parent / 'soundfonts' / 'Musyng_Kite.sf2'
TABLE = PILOT / 'energy_table_v1.json'


def _live(ear_ratings=None):
    from run_pilot_zero import LIVE_TIER_CAP_OVERRIDES
    from segment_renderer import RUNG_TIER_CAP

    f, w, tb, _ = load_energy_table(TABLE)
    return build_ladder(tier_caps={**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES},
                        features=f, weights=w, tie_band=tb, ear_ratings=ear_ratings)


def _ratings_in_order(ladder):
    return {c.gt(): float(c.rung) for c in ladder.cells}


# ---------------------------------------------------------------------------
# By-ear order
# ---------------------------------------------------------------------------


def test_ratings_in_measured_order_leave_the_ladder_unchanged():
    m = _live()
    assert _live(_ratings_in_order(m)) == m


def test_ear_order_moves_cells_and_keeps_the_u_values():
    m = _live()
    r = _ratings_in_order(m)
    r[('hiphop', 3)] = r[('pop', 5)] - 0.5           # heard below pop5
    for t in (4, 5):
        r[('hiphop', t)] = max(r[('hiphop', t)], r[('hiphop', 3)])
    e = _live(r)
    assert e.index('hiphop', 3) < e.index('pop', 5)
    assert sorted(c.u for c in e.cells) == sorted(c.u for c in m.cells)
    assert [c.gt() for c in e.cells] == sorted(r, key=lambda k: (r[k], m.energy(*k)))
    for g in {c.genre for c in e.cells}:
        us = [c.u for c in sorted((c for c in e.cells if c.genre == g), key=lambda c: c.tier)]
        assert all(a < b for a, b in zip(us, us[1:]))


def test_equal_ratings_keep_the_measured_order():
    m = _live()
    e = _live({c.gt(): 5.0 for c in m.cells})
    assert e == m


def test_ratings_that_fall_with_tier_are_rejected():
    r = _ratings_in_order(_live())
    r[('rnb', 3)] = r[('rnb', 2)] - 1
    with pytest.raises(ValueError, match='fall with tier for rnb'):
        _live(r)


def test_missing_ratings_are_rejected():
    r = _ratings_in_order(_live())
    del r[('pop', 2)]
    with pytest.raises(ValueError, match='missing'):
        _live(r)


def test_ear_ratings_need_the_measured_ladder():
    with pytest.raises(ValueError, match='features'):
        build_ladder(ear_ratings={})


def test_energy_by_ear_apply_round_trip(tmp_path):
    import energy_by_ear

    m = _live()
    r = _ratings_in_order(m)
    r[('hiphop', 3)], r[('hiphop', 4)], r[('hiphop', 5)] = 18.5, 18.6, 18.7
    csv_path = tmp_path / 'ratings.csv'
    with csv_path.open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(energy_by_ear.RATINGS_FIELDS)
        for (g, t), x in sorted(r.items()):
            w.writerow([f'{g}:{t}', x, ''])
    out = tmp_path / 'energy_order_by_ear.json'
    energy_by_ear.main(['apply', '--ratings', str(csv_path), '--out', str(out)])
    ratings, sha = load_ear_ratings(out)
    assert ratings == r and len(sha) == 64
    assert json.loads(out.read_text())['energy_table_sha256'] == load_energy_table(TABLE)[3]


def test_energy_by_ear_apply_reports_bad_rows(tmp_path):
    import energy_by_ear

    csv_path = tmp_path / 'ratings.csv'
    csv_path.write_text('cell,rating,notes\nrnb:1,high,\nrock:9,3,\n')
    with pytest.raises(SystemExit, match='not a number'):
        energy_by_ear.main(['apply', '--ratings', str(csv_path), '--out', str(tmp_path / 'o.json')])


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------

# The 2026-10-05 stall: anchor rnb2; latin has one cell in the band, rnb three.
BAND_LADDER = {('calm', 1): 0.0, ('rnb', 1): 0.500, ('rnb', 2): 0.510, ('rnb', 3): 0.515,
               ('latin', 2): 0.520, ('pop', 1): 0.700, ('rock', 5): 1.0}


def _rotate(no_repeat: int, n: int = 9) -> list[str]:
    """n rotation picks from rnb2 pushing up, with step()'s recency bookkeeping."""
    L = _to_ladder(dict(BAND_LADDER))
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.026,
                                         rotation_no_repeat=no_repeat))
    cur = ctrl._anchor_rung = L.index('rnb', 2)
    played = []
    for _ in range(n):
        cell = L.by_rung[cur]
        ctrl._genre_last_seen[cell.genre] = ctrl._cell_last_seen[cell.gt()] = ctrl._step_idx
        ctrl._step_idx += 1
        cur = ctrl._rotation_pick(+1, cur)
        played.append(f'{L.by_rung[cur].genre}{L.by_rung[cur].tier}')
    return played


def test_old_rotation_alternates_two_cells():
    assert _rotate(0) == ['latin2', 'rnb3'] * 4 + ['latin2']


def test_rotation_does_not_repeat_recent_cells():
    played = _rotate(2)
    assert all(a != b for a, b in zip(played, played[1:]))
    assert all(len({*played[i:i + 3]}) == 3 for i in range(len(played) - 2))
    assert played.count('latin2') <= 3 and {'rnb1', 'rnb2', 'rnb3'} <= set(played)


def test_rotation_stays_in_the_band():
    assert set(_rotate(2, 20)) <= {'rnb1', 'rnb2', 'rnb3', 'latin2'}


def test_rotation_with_a_single_band_cell_holds_it():
    L = _to_ladder({('calm', 1): 0.0, ('pop', 5): 0.9, ('rock', 5): 1.0})
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.026))
    ctrl._anchor_rung = top = L.index('rock', 5)
    assert ctrl._rotation_pick(+1, top) == top


def test_default_config_keeps_rotation_off():
    assert ControllerConfig().saturation_rotation is False


# ---------------------------------------------------------------------------
# Energy measured without the presentation gain
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not SF2.exists() or shutil.which('fluidsynth') is None, reason='needs fluidsynth + sf2')
def test_energy_audio_drops_only_the_presentation_gain():
    import copy

    from composer import RENDER_DIRECTIVE, generate_segment, render_directive
    from composer.arrangement import cell_plan
    from music_features_measured import energy_audio
    from segment_renderer import SymbolicSegmentRenderer

    r = SymbolicSegmentRenderer(str(SF2))
    tempo, density = cell_plan('rock', 1)
    rock = generate_segment('rock', tempo_bpm=tempo, density=density, duration_bars=8, seed=7)
    assert render_directive(rock) is not None
    plain = copy.deepcopy(rock)
    plain.text_events = [e for e in plain.text_events if not e.text.startswith(RENDER_DIRECTIVE)]
    got = energy_audio(r, rock)
    assert np.array_equal(got, r._render_pm_to_audio(plain))
    assert render_directive(rock) is not None                     # input untouched
    rms = lambda x: float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))  # noqa: E731
    assert 20 * np.log10(rms(r._render_pm_to_audio(rock)) / rms(got)) > 2.0
    tempo, density = cell_plan('pop', 3)
    pop = generate_segment('pop', tempo_bpm=tempo, density=density, duration_bars=8, seed=7)
    assert np.array_equal(energy_audio(r, pop), r._render_pm_to_audio(pop))


def test_table_records_the_exclusion():
    table = json.loads(TABLE.read_text())
    assert 'render gain' in table['excludes']
