"""
Live-ladder energy order after the first v2c live run (2026-10-05): energy is
measured without the Rock presentation gain (music_features_measured.
energy_audio), the developer's by-ear ratings can reorder the measured ladder
(ladder.build_ladder(ear_ratings=), energy_by_ear.py, run_pilot_zero --ladder
ear), the frozen perceptual ladder (energy_order_by_ear.json from
ladder_min_change.py, 2026-10-06) is pinned, and saturation rotation no longer
alternates two cells (ControllerConfig.rotation_no_repeat).
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
# The frozen perceptual ladder (energy_order_by_ear.json, 2026-10-06)
# ---------------------------------------------------------------------------

FINAL = ['calm1', 'calm2', 'lofi1', 'hiphop1', 'lofi2', 'lofi3', 'hiphop2', 'latin1', 'rnb1', 'rock1',
         'rnb2', 'rnb3', 'latin2', 'rnb4', 'latin3', 'rock2', 'pop1', 'pop2', 'pop3', 'hiphop3',
         'pop4', 'pop5', 'hiphop4', 'rock3', 'hiphop5', 'rock4', 'rock5']


@pytest.fixture(scope='module')
def runtime_ladders():
    """The ladders run_pilot_zero builds for --ladder ear and --ladder measured."""
    import simulate_session_v2 as sim

    return sim.live_stack('ear'), sim.live_stack('measured')


def test_final_ladder_order_pinned(runtime_ladders):
    (ear, _, _, ear_sha), _ = runtime_ladders
    assert [f'{c.genre}{c.tier}' for c in ear.cells] == FINAL
    assert ear_sha is not None


def test_final_ladder_integrity(runtime_ladders):
    """27 live cells, each once; tiers ascending within every genre; the live
    tier caps (latin capped at 3 live) unchanged."""
    from run_pilot_zero import LIVE_TIER_CAP_OVERRIDES
    from segment_renderer import RUNG_TIER_CAP

    (ear, _, _, _), (measured, _, _, _) = runtime_ladders
    cells = [c.gt() for c in ear.cells]
    assert len(cells) == len(set(cells)) == 27 and set(cells) == {c.gt() for c in measured.cells}
    caps = {**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES}
    assert LIVE_TIER_CAP_OVERRIDES == {'latin': 3}
    for g in {c.genre for c in ear.cells}:
        tiers = [c.tier for c in ear.cells if c.genre == g]
        assert tiers == list(range(1, caps.get(g, 5) + 1))      # ascending rung order = ascending tier


def test_final_ladder_keeps_step_magnitudes(runtime_ladders):
    """Order-only: the rung u values (so every step size, the noise floor and
    the rotation band) are the measured ladder's."""
    (ear, ctl_e, _, _), (measured, ctl_m, _, _) = runtime_ladders
    assert [c.u for c in ear.cells] == pytest.approx([c.u for c in measured.cells], abs=1e-12)
    assert ear.noise_u == pytest.approx(measured.noise_u)
    assert ctl_e.cfg == ctl_m.cfg


def test_final_ladder_is_the_min_change_solution():
    """ladder_min_change: the replicated listening relations give FINAL as the unique
    minimum-change order (total 12, largest 3, 9 moved), and the file matches it."""
    import ladder_min_change as lm
    from run_pilot_zero import EAR_ORDER

    assert list(lm.FINAL_ORDER) == FINAL
    features, tie_band, sha, e, current = lm.inputs()
    cells = [c.gt() for c in current.cells]
    cur = {k: i for i, k in enumerate(cells)}
    order, stats = lm.solve(cells, cur, e)
    assert [lm.name(k) for k in order] == FINAL
    assert stats == {'total_displacement': 12, 'max_displacement': 3, 'moved_cells': 9}
    assert lm.solve(cells, cur, e, extra_cuts=[order], fix=tuple(stats.values())) is None   # unique
    ratings, _ = load_ear_ratings(EAR_ORDER)
    assert sorted(ratings, key=ratings.get) == [(lm.name(k)[:-1], int(lm.name(k)[-1])) for k in order]
    assert json.loads(EAR_ORDER.read_text())['energy_table_sha256'] == load_energy_table(TABLE)[3]


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
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.026,
                                         top_rotation_cells=0))         # the band only
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
    assert np.array_equal(got, r._render_pm_to_audio(plain, master=False))     # reference level
    assert render_directive(rock) is not None                     # input untouched
    rms = lambda x: float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2)))  # noqa: E731
    assert 20 * np.log10(rms(r._render_pm_to_audio(rock, master=False)) / rms(got)) > 2.0
    tempo, density = cell_plan('pop', 3)
    pop = generate_segment('pop', tempo_bpm=tempo, density=density, duration_bars=8, seed=7)
    assert np.array_equal(energy_audio(r, pop), r._render_pm_to_audio(pop, master=False))


def test_table_records_the_exclusion():
    table = json.loads(TABLE.read_text())
    assert 'render gain' in table['excludes']


# ---------------------------------------------------------------------------
# Rotation keeps the controller's direction (2026-10-06)
# ---------------------------------------------------------------------------


def _random_history(ctrl, rng, n_steps=12):
    """A random recent-play history (cell and genre recency) on ctrl's ladder."""
    ctrl._step_idx = n_steps
    ctrl._cell_last_seen, ctrl._genre_last_seen = {}, {}
    for s in range(n_steps):
        c = rng.choice(ctrl.ladder.cells)
        ctrl._cell_last_seen[c.gt()] = ctrl._genre_last_seen[c.genre] = s


@pytest.mark.parametrize('m', [+1, -1], ids=['up', 'down'])
def test_requested_move_never_reversed_by_rotation(runtime_ladders, m):
    """Every rung of the frozen ladder as current cell, anchors across the band,
    either push direction, 30 random histories: when the MPC asks for a move,
    the rotation pick moves the same way (never holds, never reverses)."""
    import random

    (ear, ctl, _, _), _ = runtime_ladders
    rng = random.Random(0)
    ctrl = LadderMPC(ear, ctl.cfg)
    w = ctrl.cfg.rotation_band_u
    checked = 0
    for cur in ear.cells:
        mpc = cur.rung + m
        if not 0 <= mpc < len(ear.cells):
            continue
        for anchor in [c for c in ear.cells if abs(c.u - cur.u) <= w]:
            ctrl._anchor_rung = anchor.rung
            for d in (+1, -1):
                for _ in range(30):
                    _random_history(ctrl, rng)
                    pick = ctrl._rotation_pick(d, cur.rung, mpc)
                    assert m * (pick - cur.rung) > 0, (cur, anchor, d, pick)
                    checked += 1
    assert checked > 1000


def test_requested_move_prefers_fresh_cells_then_other_genre():
    """Direction first; among the cells that way, one not played recently, then
    another genre, then nearest the MPC's rung."""
    L = _to_ladder({('calm', 1): 0.0, ('rnb', 1): 0.50, ('rnb', 2): 0.505, ('latin', 2): 0.51,
                    ('pop', 1): 0.515, ('rock', 5): 1.0})
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.026))
    cur = ctrl._anchor_rung = L.index('rnb', 1)
    ctrl._step_idx = 10
    ctrl._cell_last_seen = {('rnb', 2): 9}                      # rnb2 recent
    assert ctrl._rotation_pick(+1, cur, cur + 1) == L.index('latin', 2)
    ctrl._cell_last_seen = {}
    assert ctrl._rotation_pick(+1, cur, cur + 1) == L.index('latin', 2)   # rnb2 same genre as current
    ctrl._cell_last_seen = {('latin', 2): 9}
    assert ctrl._rotation_pick(+1, cur, cur + 1) == L.index('pop', 1)
    ctrl._cell_last_seen = {('latin', 2): 9, ('pop', 1): 8, ('rnb', 2): 7}
    assert ctrl._rotation_pick(+1, cur, cur + 1) == L.index('rnb', 2)     # fresh beats other genre
    ctrl._cell_last_seen = {('latin', 2): 9, ('pop', 1): 8, ('rnb', 2): 9}
    assert ctrl._rotation_pick(+1, cur, cur + 1) == L.index('latin', 2)   # all recent: nearest other genre
    top = L.index('pop', 1)
    ctrl._anchor_rung, ctrl._cell_last_seen = top, {}
    assert ctrl._rotation_pick(+1, top, top + 1) == top + 1    # nothing that way in the band: the MPC's rung
    assert ctrl._rotation_pick(-1, top, top - 1) == L.index('latin', 2)   # nearest the MPC's rung


def test_hold_rotation_still_varies_on_the_frozen_ladder(runtime_ladders):
    """A hold at a saturated top (rock5) or mid-ladder (rnb2, latin2): picks stay
    in the band (at the top: the top neighbourhood), rotate through several
    cells and never alternate two."""
    (ear, ctl, _, _), _ = runtime_ladders
    top = len(ear.cells) - 1
    for genre, tier, d in (('rock', 5, +1), ('rnb', 2, +1), ('latin', 2, -1)):
        ctrl = LadderMPC(ear, ctl.cfg)
        cur = ctrl._anchor_rung = ear.index(genre, tier)
        anchor_u = ear.by_rung[cur].u
        if cur == top and d > 0:
            band = list(ear.cells[top - ctl.cfg.top_rotation_cells:])
        else:
            band = [c for c in ear.cells if abs(c.u - anchor_u) <= ctrl.cfg.rotation_band_u]
        played = []
        for _ in range(12):
            c = ear.by_rung[cur]
            ctrl._genre_last_seen[c.genre] = ctrl._cell_last_seen[c.gt()] = ctrl._step_idx
            ctrl._step_idx += 1
            cur = ctrl._rotation_pick(d, cur, None)
            played.append(cur)
            assert ear.by_rung[cur] in band
        if len(band) >= 3:
            assert len(set(played)) >= 3, (genre, tier, played)
            assert not any(a == c and b == e for a, b, c, e in zip(played, played[1:], played[2:], played[3:]))


def test_max_rotation_jump_characterized(runtime_ladders):
    """Frozen ladder, live band (2 x noise_u = 0.0267 u): a rotation pick can move
    at most 4 rungs (rnb2 <-> latin3, 0.026 u); no single pick exceeds the band."""
    (ear, ctl, _, _), _ = runtime_ladders
    w = ctl.cfg.rotation_band_u
    assert w == pytest.approx(0.0267, abs=1e-4)
    jumps = [(abs(a.rung - b.rung), a.gt(), b.gt()) for a in ear.cells for b in ear.cells if abs(a.u - b.u) <= w]
    big = max(jumps)
    assert big[0] == 4 and {big[1], big[2]} == {('rnb', 2), ('latin', 3)}


def test_closed_loop_never_reverses_a_requested_move(runtime_ladders):
    """step() under synthetic first-order plants (engineering only; not a model of
    any person): weak and typical responders, up then down targets, 10 seeds.
    Every decision where the MPC asked to move goes that way, including the
    rotation segments, and rotation segments where the MPC asked to move occur."""
    import random

    from plant_model import FOPDTPlant, Subject

    (ear, ctl, _, _), _ = runtime_ladders
    rotating_moves = 0
    for K in (3.0, 14.0):
        for seed in range(10):
            ctrl = LadderMPC(ear, ctl.cfg)
            plant = FOPDTPlant(Subject(72.0, K, 60.0, 1, 1.0, 'synthetic'), dt=18.0, noise_sigma=1.0,
                               rng=random.Random(seed))
            rung, hr = ear.index('lofi', 3), 72.0
            for k in range(60):
                target = 72.0 + (25.0 if k < 30 else -15.0)
                dec = ctrl.step(hr_bpm=hr, hr_target=target, hr_base=72.0, current_rung=rung)
                m = (dec.mpc_rung > rung) - (dec.mpc_rung < rung)
                if m:
                    assert m * (dec.next_rung - rung) > 0, (K, seed, k, rung, dec)
                    rotating_moves += dec.control_mode == 'rotate'
                hr = plant.step(ear.by_rung[dec.next_rung].u)
                rung = dec.next_rung
    assert rotating_moves > 0


def test_rotation_with_current_outside_the_anchor_band_holds():
    """Current cell more than the band away from the anchor (the MPC moved it
    there): a hold pick keeps the current cell instead of raising."""
    L = _to_ladder({('calm', 1): 0.0, ('rnb', 1): 0.50, ('rnb', 2): 0.51, ('pop', 1): 0.60, ('rock', 5): 1.0})
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.026))
    ctrl._anchor_rung = L.index('rnb', 1)
    cur = L.index('pop', 1)
    assert ctrl._rotation_pick(+1, cur, None) == cur
    assert ctrl._rotation_pick(+1, cur, cur + 1) == cur + 1          # a requested move still follows the MPC


# ---------------------------------------------------------------------------
# Variety at the top of the ladder (2026-10-07)
# ---------------------------------------------------------------------------


def _top_stall(ladder, cfg, n=45, seed=0):
    """Closed loop with a synthetic first-order plant that cannot reach the
    target (engineering only): the controller climbs to the top and stalls.
    Returns the (rung, control_mode, mpc_rung, prev_rung) of every decision."""
    import random

    from plant_model import FOPDTPlant, Subject

    ctrl = LadderMPC(ladder, cfg)
    plant = FOPDTPlant(Subject(72.0, 14.0, 60.0, 1, 1.0, 'synthetic'), dt=18.0, noise_sigma=0.5,
                       rng=random.Random(seed))
    rung, hr, out = ladder.index('lofi', 3), 72.0, []
    for _ in range(n):
        dec = ctrl.step(hr_bpm=hr, hr_target=72.0 + 40.0, hr_base=72.0, current_rung=rung)
        out.append((dec.next_rung, dec.control_mode, dec.mpc_rung, rung))
        hr = plant.step(ladder.by_rung[dec.next_rung].u)
        rung = dec.next_rung
    return out


def test_top_stall_rotates_near_the_top(runtime_ladders):
    """Frozen ladder, live config: a long upward stall at rock5 rotates among
    rock5, rock4 and hiphop5 (never two rock5 in a row once rotating), with
    rotation jumps of at most 2 rungs and no reversal of a requested move."""
    (ear, ctl, _, _), _ = runtime_ladders
    top = len(ear.cells) - 1
    near = {top - 2, top - 1, top}
    assert {ear.by_rung[r].gt() for r in near} == {('hiphop', 5), ('rock', 4), ('rock', 5)}
    for seed in range(5):
        seq = _top_stall(ear, ctl.cfg, seed=seed)
        rot = [i for i, x in enumerate(seq) if x[1] == 'rotate']
        assert len(rot) >= 10, seed
        assert all(seq[i][0] in near for i in rot)
        assert all(abs(seq[i][0] - seq[i][3]) <= 2 for i in rot)
        assert {seq[i][0] for i in rot} == near
        tail = [x[0] for x in seq[rot[0]:]]
        assert not any(a == b == top for a, b in zip(tail, tail[1:])), tail
        for nxt, _, mpc, prev in seq:
            m = (mpc > prev) - (mpc < prev)
            assert m == 0 or m * (nxt - prev) > 0


def test_top_stall_old_behaviour_replays_the_top(runtime_ladders):
    """top_rotation_cells=0 (the band only) reproduces Test A: rock5 every segment."""
    import dataclasses

    (ear, ctl, _, _), _ = runtime_ladders
    seq = _top_stall(ear, dataclasses.replace(ctl.cfg, top_rotation_cells=0))
    rot = [x[0] for x in seq if x[1] == 'rotate']
    assert rot and set(rot) == {len(ear.cells) - 1}


def test_top_neighbourhood_only_for_upward_top_stalls():
    """A downward stall at the bottom and an upward stall below the top keep the
    energy band."""
    L = _to_ladder({('calm', 1): 0.0, ('calm', 2): 0.001, ('lofi', 1): 0.15, ('pop', 1): 0.5,
                    ('pop', 2): 0.51, ('rock', 4): 0.86, ('hiphop', 5): 0.855, ('rock', 5): 1.0})
    ctrl = LadderMPC(L, ControllerConfig(saturation_rotation=True, rotation_band_u=0.027))
    ctrl._step_idx = 5
    bottom = L.index('calm', 1)
    ctrl._anchor_rung = bottom
    assert ctrl._rotation_pick(-1, bottom, None) in {bottom, L.index('calm', 2)}
    mid = L.index('pop', 2)
    ctrl._anchor_rung = mid
    assert ctrl._rotation_pick(+1, mid, None) in {mid, L.index('pop', 1)}
    top = L.index('rock', 5)
    ctrl._anchor_rung = top
    assert ctrl._rotation_pick(+1, top, None) == L.index('hiphop', 5)     # other genre, never played
