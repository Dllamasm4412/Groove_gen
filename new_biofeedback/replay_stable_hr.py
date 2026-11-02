#!/usr/bin/env python3
"""Replay a logged raw PPG CSV through the live 1 Hz stable-HR estimator.

No serial, no haptics. Uses the same estimate_stable_hr call and cadence as
the live loop and writes the HR series GrooveGen would have received:

    python replay_stable_hr.py ppg_live_recordings/ppg_live_raw_X.csv --out /tmp/hr

--no-period-gate disables the beat-doubling gate (HR_MAX_DOUBLE_PERIOD_GAIN) to
compare before/after. --speed K time-compresses the recording by K (HR x K)
to check the estimator at higher HR on real waveforms.
"""

import argparse
import csv
from collections import deque
from pathlib import Path

import numpy as np

import ppg_live_estimator_adaptive_haptics_stable_hr as est
from replay_haptic_pacer import load_raw

FIELDS = ["time_s", "stable_hr_bpm", "window_hr_bpm", "valid"]


def time_compress(t, raw, clipped, speed):
    """Resample so the recording plays `speed` times faster at the same FS."""
    t_new = np.arange(t[0], t[0] + (t[-1] - t[0]) / speed, 1.0 / est.FS)
    src = t[0] + (t_new - t[0]) * speed
    raw_new = np.interp(src, t, raw)
    clip_new = (np.interp(src, t, clipped.astype(float)) > 0).astype(int)
    return t_new, raw_new, clip_new


def replay(t_all, raw_all, clip_all):
    hr_n = int(est.HR_WINDOW_S * est.FS)
    times = deque(maxlen=hr_n)
    samples = deque(maxlen=hr_n)
    clipped = deque(maxlen=hr_n)
    stable_hr = np.nan
    last_update = -np.inf
    rows = []
    for t, raw, clip in zip(t_all, raw_all, clip_all):
        times.append(t)
        samples.append(raw)
        clipped.append(clip)
        if len(samples) >= hr_n and (t - last_update) >= est.HR_UPDATE_S:
            stable_hr, window_hr, ok = est.estimate_stable_hr(
                times, samples, clipped, previous_hr=stable_hr,
            )
            last_update = t
            rows.append({"time_s": t, "stable_hr_bpm": stable_hr,
                         "window_hr_bpm": window_hr, "valid": ok})
    return rows


def summarize(rows):
    window = np.array([r["window_hr_bpm"] for r in rows if r["valid"]], float)
    out = {"n_updates": len(rows), "valid_frac": len(window) / max(1, len(rows))}
    if len(window):
        # Ratio of each valid window HR to the recording's valid median flags
        # ~2x (doubled) and other gross outliers without assuming a fixed cap.
        med = float(np.median(window))
        out.update(median_bpm=med, p99_bpm=float(np.percentile(window, 99)),
                   max_bpm=float(np.max(window)),
                   n_over_1p5x_median=int(np.sum(window > 1.5 * med)))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_csv", nargs="+")
    parser.add_argument("--no-period-gate", action="store_true",
                        help="Disable the beat-doubling autocorrelation gate")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="Time-compress the recording by this factor (HR x speed)")
    parser.add_argument("--out", default=None, help="Directory for per-update CSVs")
    args = parser.parse_args()

    if args.no_period_gate:
        est.HR_MAX_DOUBLE_PERIOD_GAIN = np.inf

    for path in args.raw_csv:
        t, raw, clip = load_raw(path)
        if args.speed != 1.0:
            t, raw, clip = time_compress(t, raw, clip, args.speed)
        rows = replay(t, raw, clip)
        s = summarize(rows)
        stem = Path(path).stem
        print(f"{stem}: " + " ".join(
            f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in s.items()))
        if args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            with (out_dir / f"{stem}_stable_hr.csv").open("w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(rows)


if __name__ == "__main__":
    main()
