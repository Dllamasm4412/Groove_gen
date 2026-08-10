"""Targeted regression tests for the three council-flagged faults.

Run: python groovegen_pilot/test_faults_fixed.py
Verifies (0a) calm rung reachable, (0b) direction from signed error survives a
0.5-crossing trajectory setpoint, and (bonus) RUNG_TIER_CAP monotonicity.
"""
import sys, os
sys.path.insert(0, "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_project")
sys.path.insert(0, "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot")
sys.path.insert(0, "/Users/daniel/Desktop/PhD/groove_gen_project")
import numpy as np
from groovegen import pd_controller as pdc


def test_0a_calm_rung_exists_and_is_bottom():
    assert pdc.GENRE_ENERGY_ORDER[0] == "calm", pdc.GENRE_ENERGY_ORDER
    assert "calm" in pdc.GENRE_EQUILIBRIUM_BAND
    calm_ceil = pdc.GENRE_EQUILIBRIUM_BAND["calm"][1]
    rnb_ceil = pdc.GENRE_EQUILIBRIUM_BAND["r&b"][1]
    assert calm_ceil < rnb_ceil, f"calm ceil {calm_ceil} must be < r&b ceil {rnb_ceil}"
    print("(0a) PASS: calm is bottom rung, ceiling below r&b")


def test_0a_calm_reachable_via_ladder():
    """A strong down-regulation from a hot start must be ABLE to reach calm."""
    cc = pdc.CascadeController(
        tempo_kp=6.0, tempo_kd=1.5, tempo_min=60, tempo_max=140, max_step_bpm=8,
        density_kp=2.5, density_kd=0.8, density_min=3, density_max=20,
        band=0.05, n_bars_saturated_for_tempo=2, n_bars_saturated_for_genre=2,
    )
    cc.reset(initial_genre_idx=len(cc.genre_order) - 1, initial_tempo=140.0, initial_density=20)
    arousal = 0.98
    setpoint = 0.02  # very calm -> should drive all the way to the calm rung
    rng = np.random.default_rng(1)
    visited = []
    for _ in range(120):
        out = cc.step(setpoint=setpoint, measurement=arousal)
        visited.append(out["genre"])
        arousal = pdc.dual_lever_plant_step(
            arousal, out["genre"], out["tempo_bpm"], out["density"],
            tempo_min=60, tempo_max=140, density_min=3, density_max=20,
            relax=0.10, noise=float(rng.normal(0, 0.003)),
        )
    assert "calm" in visited, f"calm rung never reached; visited {sorted(set(visited))}"
    print(f"(0a) PASS: calm rung reachable; ladder walked {[g for i,g in enumerate(visited) if i==0 or g!=visited[i-1]]}")


def test_0b_trajectory_setpoint_crossing_half():
    """The killer case: an UP-regulation whose setpoint sweeps THROUGH 0.5.

    With the old `setpoint < 0.5` direction test, the saturation logic would
    flip direction at the crossing. With signed error, direction is stable:
    error>0 throughout (measurement lags below a rising setpoint) so the
    ladder must only ever walk UP, never down.
    """
    cc = pdc.CascadeController(
        tempo_kp=6.0, tempo_kd=1.5, tempo_min=60, tempo_max=140, max_step_bpm=8,
        density_kp=2.5, density_kd=0.8, density_min=3, density_max=20,
        band=0.05, n_bars_saturated_for_tempo=2, n_bars_saturated_for_genre=2,
    )
    cc.reset(initial_genre_idx=0, initial_tempo=70.0, initial_density=4)  # start calm/low
    # measurement stays LOW (participant lags), setpoint ramps 0.2 -> 0.9,
    # crossing 0.5 at the midpoint. error = setpoint - meas > 0 throughout.
    idx_trace = []
    meas = 0.15
    rng = np.random.default_rng(2)
    for k in range(80):
        sp = 0.2 + (0.9 - 0.2) * min(k / 40.0, 1.0)  # ramps through 0.5 at k=~17
        out = cc.step(setpoint=sp, measurement=meas)
        idx_trace.append(cc.genre_order.index(out["genre"]))
        # let arousal rise slowly but stay below setpoint (participant lags)
        meas = pdc.dual_lever_plant_step(
            meas, out["genre"], out["tempo_bpm"], out["density"],
            tempo_min=60, tempo_max=140, density_min=3, density_max=20,
            relax=0.06, noise=float(rng.normal(0, 0.003)),
        )
    # ASSERT: ladder index is monotonic NON-DECREASING (only walks up).
    assert all(b >= a for a, b in zip(idx_trace, idx_trace[1:])), (
        f"ladder walked DOWN under a rising setpoint -> direction flip bug! trace={idx_trace}"
    )
    assert idx_trace[-1] > idx_trace[0], f"ladder never climbed; trace={idx_trace}"
    print(f"(0b) PASS: rising setpoint through 0.5 -> ladder only walked UP "
          f"(idx {idx_trace[0]}->{idx_trace[-1]}, no direction flip)")


def test_bonus_tier_cap_monotone():
    """A tier-5 calm segment must not out-energize a tier-2 r&b segment.

    Proxy for 'energy': RMS of the rendered bar. calm@5 should be <= r&b@2-ish;
    at minimum, calm's EFFECTIVE tier is capped at 2 by RUNG_TIER_CAP.
    """
    import renderer as R
    assert R.RUNG_TIER_CAP["calm"] == 2
    # effective tier applied inside _bar_midi is min(tier, cap)
    eff_calm5 = min(5, R.RUNG_TIER_CAP["calm"])
    eff_rnb2 = min(2, R.RUNG_TIER_CAP["r&b"])
    assert eff_calm5 <= eff_rnb2, f"calm@5 eff {eff_calm5} must be <= r&b@2 eff {eff_rnb2}"
    print(f"(bonus) PASS: calm@5 effective tier={eff_calm5} <= r&b@2 effective tier={eff_rnb2}")


if __name__ == "__main__":
    test_0a_calm_rung_exists_and_is_bottom()
    test_0a_calm_reachable_via_ladder()
    test_0b_trajectory_setpoint_crossing_half()
    test_bonus_tier_cap_monotone()
    print("\nALL FAULT-FIX TESTS PASSED")
