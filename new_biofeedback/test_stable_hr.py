"""Offline checks for the estimator's stable-HR beat-doubling gate. No serial.

Run: python new_biofeedback/test_stable_hr.py

Part 1 uses synthetic PPG (systolic + diastolic Gaussian per beat): clean
pulses keep their HR from 45 to 150 bpm; a diastolic wave strong enough to be
counted as a beat (window HR ~2x) is either re-detected at the true HR
(ok_undoubled) or rejected with the previous HR kept, never clamped. Part 2
replays every raw recording in ppg_live_recordings/ (skipped if absent): no
valid window exceeds 1.5x or falls below 0.67x the recording's valid median;
windows removed within 1.25x of it (i.e. by the quality floor, not the
doubling gate) must be <= 1% of those kept. Part 3
checks the diag reasons logged per 1 Hz update (ppg_hr_<stamp>.csv) and that
pulse-free noise is almost never valid (quality floor).
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import ppg_live_estimator_adaptive_haptics_stable_hr as est  # noqa: E402
from replay_haptic_pacer import load_raw  # noqa: E402
from replay_stable_hr import replay  # noqa: E402

GATE = est.HR_MAX_DOUBLE_PERIOD_GAIN
MIN_AC, MIN_SD = est.HR_MIN_PERIOD_AC, est.HR_MIN_PULSE_SD
MAX_AC_L = est.HR_UNDOUBLE_MAX_AC_L


def synth(bpm, dia_amp, dia_delay_s, sys_w=0.15, dia_w=0.12, dur_s=8.0):
    t = np.arange(0.0, dur_s, 1.0 / est.FS)
    period = 60.0 / bpm
    x = np.zeros_like(t)
    for b in np.arange(-period, dur_s + period, period):
        x += np.exp(-0.5 * ((t - b) / sys_w) ** 2)
        x += dia_amp * np.exp(-0.5 * ((t - b - dia_delay_s) / dia_w) ** 2)
    x += 0.02 * np.random.default_rng(0).standard_normal(len(t))
    return t, 2200.0 + 600.0 * x, np.zeros(len(t), int)


def test_clean_pulses_keep_hr():
    for bpm in (45, 60, 90, 120, 150):
        t, x, c = synth(bpm, dia_amp=0.3, dia_delay_s=0.25, sys_w=0.07, dia_w=0.07)
        _, window_hr, ok = est.estimate_stable_hr(t, x, c)
        assert ok and abs(window_hr - bpm) < 1.0, (bpm, window_hr, ok)
    print("(clean) PASS: synthetic pulses at 45-150 bpm valid, window HR within 1 bpm")


def test_doubled_beats_recovered_or_rejected():
    cases = [(60, 0.8, 0.40, 0.15, 0.12), (60, 0.6, 0.40, 0.07, 0.07),
             (70, 0.8, 0.40, 0.15, 0.12), (70, 0.6, 0.40, 0.07, 0.07)]
    n_recovered = 0
    for bpm, amp, delay, sw, dw in cases:
        t, x, c = synth(bpm, amp, delay, sw, dw)
        est.HR_MAX_DOUBLE_PERIOD_GAIN = np.inf
        est.HR_MIN_PERIOD_AC = -np.inf
        _, window_hr, ok = est.estimate_stable_hr(t, x, c)
        est.HR_MIN_PERIOD_AC = MIN_AC
        assert ok and window_hr > 1.7 * bpm, ("case no longer doubles without the gates", bpm, window_hr)
        est.HR_MAX_DOUBLE_PERIOD_GAIN = GATE
        hr, window_hr, ok = est.estimate_stable_hr(t, x, c, previous_hr=bpm + 0.5)
        if ok:
            assert abs(window_hr - bpm) < 1.0, (bpm, window_hr)
            n_recovered += 1
        else:
            assert np.isnan(window_hr) and hr == bpm + 0.5, (bpm, hr, window_hr, ok)
        est.HR_UNDOUBLE_MAX_AC_L = -np.inf          # recovery off: always rejected
        hr, window_hr, ok = est.estimate_stable_hr(t, x, c, previous_hr=bpm + 0.5)
        est.HR_UNDOUBLE_MAX_AC_L = MAX_AC_L
        assert not ok and np.isnan(window_hr) and hr == bpm + 0.5, (bpm, hr, window_hr, ok)
    assert n_recovered >= 1
    print(f"(doubled) PASS: {len(cases)} synthetic ~2x windows valid without the gates; with "
          f"them {n_recovered} re-detected within 1 bpm of true HR, the rest rejected with "
          "previous HR kept (not clamped)")


def test_diag_reasons():
    def reason(t, x, c):
        d = {}
        est.estimate_stable_hr(t, x, c, diag=d)
        return d

    t, x, c = synth(70, dia_amp=0.3, dia_delay_s=0.25, sys_w=0.07, dia_w=0.07)
    d = reason(t, x, c)
    assert d["reason"] == "ok" and d["n_valid_ibi"] >= 7 and d["double_gain"] < GATE, d
    assert reason(t[:-10], x[:-10], c[:-10])["reason"] == "short_history"
    t2, x2, c2 = synth(60, 0.8, 0.40, 0.15, 0.12)
    d2 = reason(t2, x2, c2)
    assert d2["reason"] == "ok_undoubled" and d2["double_gain"] < GATE, d2
    t4, x4, c4 = synth(70, 0.8, 0.40, 0.15, 0.12)
    assert reason(t4, x4, c4)["reason"] == "doubled_beats"
    c3 = c.copy()
    c3[200:220] = 1                     # 200 ms rail run
    assert reason(t, x, c3)["reason"] == "clip_run"
    assert reason(t, np.full(len(t), 2200.0), c)["reason"] == "weak_pulse"   # flat: SD 0
    assert d["period_ac"] > 0.5 and d["pulse_sd"] > 50, d
    small = 2200.0 + (x - 2200.0) * 0.02          # same pulses, ~10 counts SD
    assert reason(t, small, c)["reason"] == "weak_pulse"
    print("(diag) PASS: reasons ok / short_history / ok_undoubled / doubled_beats / clip_run / "
          "weak_pulse; period_ac and pulse_sd logged")


def test_noise_rejected():
    t = np.arange(0.0, 8.0, 1.0 / est.FS)
    c = np.zeros(len(t), int)
    n_valid = {}
    for kind in ("white", "brown"):
        n_valid[kind] = 0
        for seed in range(200):
            w = np.random.default_rng(seed).standard_normal(len(t))
            if kind == "brown":
                w = np.cumsum(w) - np.cumsum(w).mean()
            d = {}
            _, _, ok = est.estimate_stable_hr(t, 2200.0 + 100.0 * w / w.std(), c, diag=d)
            n_valid[kind] += ok
            assert ok or d["reason"] in ("aperiodic", "weak_pulse", "no_pulses", "few_ibi", "doubled_beats"), d
    assert n_valid["white"] <= 2 and n_valid["brown"] <= 8, n_valid
    print(f"(noise) PASS: pulse-free noise (SD 100 counts) valid in {n_valid['white']}/200 white, "
          f"{n_valid['brown']}/200 brown windows")


def test_replay_recordings():
    raws = sorted((HERE / "ppg_live_recordings").glob("ppg_live_raw_*.csv"))
    if not raws:
        print("(replay) SKIP: no recordings")
        return
    n_removed = n_quality = 0
    n_valid = 0
    for path in raws:
        t, x, c = load_raw(path)
        est.HR_MAX_DOUBLE_PERIOD_GAIN = np.inf
        est.HR_MIN_PERIOD_AC, est.HR_MIN_PULSE_SD = -np.inf, -np.inf
        off = replay(t, x, c)
        est.HR_MAX_DOUBLE_PERIOD_GAIN = GATE
        est.HR_MIN_PERIOD_AC, est.HR_MIN_PULSE_SD = MIN_AC, MIN_SD
        on = replay(t, x, c)
        med = np.median([r["window_hr_bpm"] for r in on if r["valid"]])
        for a, b in zip(off, on):
            if b["valid"]:
                n_valid += 1
                assert 0.67 * med <= b["window_hr_bpm"] <= 1.5 * med, (path.stem, b)
            elif a["valid"]:
                if a["window_hr_bpm"] > 1.25 * med:
                    n_removed += 1
                else:
                    n_quality += 1
    assert n_quality <= 0.01 * n_valid, (n_quality, n_valid)
    print(f"(replay) PASS: {len(raws)} recordings; no valid window > 1.5x or < 0.67x median; doubling "
          f"gate removed {n_removed} windows > 1.25x median; quality floor removed "
          f"{n_quality} plausible windows ({n_valid} kept)")


if __name__ == "__main__":
    test_clean_pulses_keep_hr()
    test_doubled_beats_recovered_or_rejected()
    test_diag_reasons()
    test_noise_rejected()
    test_replay_recordings()
    print("\nALL STABLE HR TESTS PASSED")
