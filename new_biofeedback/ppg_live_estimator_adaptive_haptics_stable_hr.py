#!/usr/bin/env python3
"""Adaptive live PPG HR/RR estimator with stable-HR-gated heartbeat haptics.

Firmware companion:
    xiao_ppg_haptic_serial_bridge.ino

The XIAO streams at 100 Hz:
    time_ms,raw_ppg,clipped

This program:
- keeps the adaptive RR pipeline (30 s stable / 15 s fast),
- estimates a stable HR after an 8-second PPG warm-up,
- sends HB commands only when stable HR quality is valid, and
- triggers one short D9 haptic pulse for each newly confirmed PPG peak.

The haptic feedback is PPG-peak synchronized, while stable HR protects against
false/unstable triggering and provides a smoother current-HR estimate.

Test actuator communication first:
    python ppg_live_estimator_adaptive_haptics_stable_hr.py \
        --port /dev/cu.usbmodemXXXX --test-haptics

Normal run:
    python ppg_live_estimator_adaptive_haptics_stable_hr.py \
        --port /dev/cu.usbmodemXXXX

Pacing mode (haptic_pacer.HapticPacer replaces peak echo: HB at a rate that
starts at the current HR and ramps toward the goal, clipped to HR0 +/- 6):
    python ppg_live_estimator_adaptive_haptics_stable_hr.py \
        --port /dev/cu.usbmodemXXXX --pace-goal-bpm 58 --pace-max-seconds 180

Dependencies:
    python -m pip install numpy scipy pyserial
"""

import argparse
import csv
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np
import serial
from scipy.interpolate import interp1d
from scipy.signal import butter, detrend, filtfilt, find_peaks, welch

FS = 100.0
RESP_FS = 8.0
STABLE_WINDOW_S = 30.0
STABLE_UPDATE_S = 5.0
FAST_WINDOW_S = 15.0
FAST_UPDATE_S = 2.5
CARDIAC_BAND = (0.5, 3.0)
RESP_BAND = (0.10, 0.70)
MIN_BPM = 40.0
MAX_BPM = 180.0
CLIP_MARGIN = 4
# HR and beat gates tolerate brief rail contact at pulse peaks (strong
# perfusion); longer runs (finger lifted or pressed) still reject the window.
# The respiration gate (analyze_window) stays strict.
MAX_CLIP_RUN_S = 0.10

AMP_AGREEMENT_RPM = 2.5
MIN_AMP_QUALITY = 0.35
STABLE_CONFIRM_WINDOWS = 3
STABLE_TOLERANCE_RPM = 2.5
FAST_CONFIRM_WINDOWS = 2
FAST_TOLERANCE_RPM = 3.0
CHANGE_TRIGGER_RPM = 3.0

# Beat-synchronous haptic detection.
BEAT_WINDOW_S = 8.0
BEAT_UPDATE_S = 0.10
HAPTIC_MIN_IBI_S = 60.0 / MAX_BPM
HAPTIC_MAX_IBI_S = 60.0 / MIN_BPM
HAPTIC_CONFIRM_LAG_S = 0.08

# Stable HR estimator and haptic gate.
HR_WINDOW_S = 8.0
HR_UPDATE_S = 1.0
HR_MIN_VALID_IBI = 4
HR_EMA_ALPHA = 0.25
HR_MIN_BPM = 40.0
HR_MAX_BPM = 180.0


def bandpass(x, low, high, fs, order=3):
    nyq = fs / 2.0
    b, a = butter(order, [low / nyq, high / nyq], btype="band")
    return filtfilt(b, a, x)


def robust_normalize(x):
    x = detrend(np.asarray(x, dtype=float))
    mad = np.median(np.abs(x - np.median(x)))
    if mad < 1e-9:
        return None
    return x / (1.4826 * mad)


def dominant_frequency(x, fs):
    z = robust_normalize(x)
    if z is None or len(z) < int(10 * fs):
        return None
    try:
        y = bandpass(z, RESP_BAND[0], RESP_BAND[1], fs)
    except ValueError:
        return None

    nperseg = min(len(y), int(12 * fs))
    if nperseg < int(10 * fs):
        return None

    f, p = welch(y, fs=fs, nperseg=nperseg, noverlap=nperseg // 2)
    mask = (f >= RESP_BAND[0]) & (f <= RESP_BAND[1])
    f, p = f[mask], p[mask]
    if len(p) < 3 or np.sum(p) <= 0:
        return None

    i = int(np.argmax(p))
    peak = p[i]
    second = np.max(np.delete(p, i)) if len(p) > 1 else 0.0
    concentration = peak / np.sum(p)
    separation = peak / (second + 1e-12)
    quality = concentration * min(separation, 3.0)
    return {"rpm": float(60.0 * f[i]), "quality": float(quality)}


def resample_feature(t, x, grid):
    t, x = np.asarray(t, float), np.asarray(x, float)
    valid = np.isfinite(t) & np.isfinite(x)
    t, x = t[valid], x[valid]
    if len(t) < 5 or np.any(np.diff(t) <= 0):
        return None
    if grid[0] < t[0] or grid[-1] > t[-1]:
        return None
    return interp1d(t, x, kind="linear")(grid)


def extract_pulses(t, raw, min_required_peaks=8, min_required_ibi=6):
    """Bandpass PPG and return robustly screened peaks and derived features."""
    x, t = np.asarray(raw, float), np.asarray(t, float)
    if len(x) < 40:
        return None

    try:
        ppg = bandpass(detrend(x), CARDIAC_BAND[0], CARDIAC_BAND[1], FS)
    except ValueError:
        return None

    min_distance = int(FS * 60.0 / MAX_BPM)
    prominence = max(0.45 * np.std(ppg), 1e-6)
    peaks, _ = find_peaks(ppg, distance=min_distance, prominence=prominence)
    if len(peaks) < min_required_peaks:
        return None

    peak_t0 = t[peaks]
    ibi0 = np.diff(peak_t0)
    plausible = ibi0[(ibi0 >= 60.0 / MAX_BPM) & (ibi0 <= 60.0 / MIN_BPM)]
    if len(plausible) < min_required_ibi:
        return None

    median_ibi = np.median(plausible)
    keep = np.r_[True, np.abs(ibi0 - median_ibi) <= 0.30 * median_ibi]
    peaks = peaks[keep]
    peak_t = t[peaks]
    if len(peaks) < min_required_peaks:
        return None

    troughs = np.empty(len(peaks), dtype=int)
    for i, pk in enumerate(peaks):
        left = 0 if i == 0 else peaks[i - 1]
        troughs[i] = left + np.argmin(ppg[left:pk + 1])

    peak_val = ppg[peaks]
    amplitude = peak_val - ppg[troughs]
    valid_amp = amplitude > 0
    peak_t = peak_t[valid_amp]
    peak_val = peak_val[valid_amp]
    amplitude = amplitude[valid_amp]

    ibi = np.diff(peak_t)
    stable = (ibi >= 0.65 * median_ibi) & (ibi <= 1.35 * median_ibi)
    if np.sum(stable) < min_required_ibi:
        return None

    hr_t = peak_t[1:][stable]
    hr = 60.0 / ibi[stable]
    return peak_t, peak_val, amplitude, hr_t, hr


def analyze_window(t, raw, clipped):
    if np.any(clipped) or np.any(raw <= CLIP_MARGIN) or np.any(raw >= 4095 - CLIP_MARGIN):
        return {"status": "clipped", "rr": np.nan, "confidence": 0.0}

    data = extract_pulses(t, raw)
    if data is None:
        return {"status": "poor_pulse_quality", "rr": np.nan, "confidence": 0.0}

    peak_t, peak_val, amplitude, hr_t, hr = data
    grid = np.arange(t[0] + 2.0, t[-1] - 2.0, 1.0 / RESP_FS)
    riiv = resample_feature(peak_t, peak_val, grid)
    riav = resample_feature(peak_t, amplitude, grid)
    rifv = resample_feature(hr_t, hr, grid)

    candidates = {
        "riiv": dominant_frequency(riiv, RESP_FS) if riiv is not None else None,
        "riav": dominant_frequency(riav, RESP_FS) if riav is not None else None,
        "rifv": dominant_frequency(rifv, RESP_FS) if rifv is not None else None,
    }
    candidates = {name: item for name, item in candidates.items() if item is not None}

    output = {
        "status": "amplitude_features_unreliable",
        "rr": np.nan,
        "confidence": 0.0,
        "bpm": float(np.median(hr)),
        "candidates": candidates,
    }

    amp = [
        candidates[name] for name in ("riiv", "riav")
        if name in candidates and candidates[name]["quality"] >= MIN_AMP_QUALITY
    ]

    if len(amp) == 2 and abs(amp[0]["rpm"] - amp[1]["rpm"]) <= AMP_AGREEMENT_RPM:
        w0, w1 = amp[0]["quality"], amp[1]["quality"]
        output["rr"] = float((w0 * amp[0]["rpm"] + w1 * amp[1]["rpm"]) / (w0 + w1))
        output["confidence"] = float(min(1.0, (w0 + w1) / 1.4))
        output["status"] = "candidate"
    elif len(amp) == 1:
        output["status"] = "single_amplitude_feature"
    elif len(amp) == 2:
        output["status"] = "amplitude_features_disagree"

    return output


def has_long_clip_run(wx, wc):
    """True if any run of rail samples in the window exceeds MAX_CLIP_RUN_S."""
    rail = (wc != 0) | (wx <= CLIP_MARGIN) | (wx >= 4095 - CLIP_MARGIN)
    if not np.any(rail):
        return False
    edges = np.diff(np.r_[0, rail.astype(int), 0])
    runs = np.flatnonzero(edges == -1) - np.flatnonzero(edges == 1)
    return bool(np.max(runs) > round(MAX_CLIP_RUN_S * FS))


def estimate_stable_hr(t, raw, clipped, previous_hr=np.nan):
    """Estimate HR from the median valid IBI over the latest HR_WINDOW_S.

    Returns (smoothed_hr, window_hr, is_valid). The smoothed estimate uses an
    EMA only after a valid raw/window estimate has been obtained.
    """
    n = int(HR_WINDOW_S * FS)
    if len(raw) < n:
        return previous_hr, np.nan, False

    wt = np.asarray(t, float)[-n:]
    wx = np.asarray(raw, float)[-n:]
    wc = np.asarray(clipped, int)[-n:]

    if has_long_clip_run(wx, wc):
        return previous_hr, np.nan, False

    data = extract_pulses(
        wt,
        wx,
        min_required_peaks=5,
        min_required_ibi=HR_MIN_VALID_IBI,
    )
    if data is None:
        return previous_hr, np.nan, False

    peak_t = data[0]
    ibi = np.diff(peak_t)
    valid = (ibi >= 60.0 / HR_MAX_BPM) & (ibi <= 60.0 / HR_MIN_BPM)
    if np.sum(valid) < HR_MIN_VALID_IBI:
        return previous_hr, np.nan, False

    window_hr = float(np.median(60.0 / ibi[valid]))
    if not np.isfinite(previous_hr):
        smoothed_hr = window_hr
    else:
        smoothed_hr = HR_EMA_ALPHA * window_hr + (1.0 - HR_EMA_ALPHA) * previous_hr

    return float(smoothed_hr), window_hr, True


def newly_confirmed_heartbeat(t, raw, clipped, last_sent_peak_t):
    """Return (new_peak_time, instantaneous_bpm), else (None, nan)."""
    n = int(BEAT_WINDOW_S * FS)
    if len(raw) < n:
        return None, np.nan

    wt = np.asarray(t, float)[-n:]
    wx = np.asarray(raw, float)[-n:]
    wc = np.asarray(clipped, int)[-n:]
    if has_long_clip_run(wx, wc):
        return None, np.nan

    data = extract_pulses(wt, wx, min_required_peaks=4, min_required_ibi=3)
    if data is None:
        return None, np.nan

    peak_t = data[0]
    if len(peak_t) < 2:
        return None, np.nan

    confirmed = peak_t[peak_t <= wt[-1] - HAPTIC_CONFIRM_LAG_S]
    if len(confirmed) == 0:
        return None, np.nan

    candidate_t = float(confirmed[-1])
    if candidate_t <= last_sent_peak_t + 1e-6:
        return None, np.nan

    if np.isfinite(last_sent_peak_t):
        ibi_s = candidate_t - last_sent_peak_t
        if not (HAPTIC_MIN_IBI_S <= ibi_s <= HAPTIC_MAX_IBI_S):
            return None, np.nan
        instantaneous_bpm = 60.0 / ibi_s
    else:
        instantaneous_bpm = np.nan

    return candidate_t, instantaneous_bpm


def parse_line(line):
    fields = line.strip().split(",")
    if len(fields) < 2:
        return None
    try:
        t = float(fields[0]) / 1000.0
        raw = float(fields[1])
        clipped = int(fields[2]) if len(fields) > 2 else int(raw <= CLIP_MARGIN or raw >= 4095 - CLIP_MARGIN)
        return t, raw, clipped
    except ValueError:
        return None


def field(candidates, name, key):
    item = candidates.get(name)
    return "" if item is None else f"{item[key]:.2f}"


def format_candidate(value):
    return "--" if not np.isfinite(value) else f"{value:.1f}"


def send_command(ser, command):
    ser.write((command + "\n").encode("ascii"))
    ser.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--out", default="ppg_live_recordings")
    parser.add_argument("--no-haptics", action="store_true", help="Log and analyze PPG without sending HB commands")
    parser.add_argument("--test-haptics", action="store_true", help="Send a one-time XIAO TEST command after connection")
    parser.add_argument("--pace-goal-bpm", type=float, default=None,
                        help="Pacing mode: ramp HB rate from current HR toward this goal instead of echoing peaks")
    parser.add_argument("--pace-max-seconds", type=float, default=300.0,
                        help="Pacing mode: stop pacing after this many seconds")
    args = parser.parse_args()

    pacer = None
    if args.pace_goal_bpm is not None:
        from haptic_pacer import LOG_FIELDS, HapticPacer
        pacer = HapticPacer(goal_bpm=args.pace_goal_bpm, max_seconds=args.pace_max_seconds)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"ppg_live_raw_{stamp}.csv"
    estimate_path = out_dir / f"ppg_live_adaptive_{stamp}.csv"
    haptic_path = out_dir / f"ppg_haptic_events_{stamp}.csv"
    pacer_path = out_dir / f"ppg_pacer_{stamp}.csv"

    history_n = int((STABLE_WINDOW_S + 5.0) * FS)
    stable_n = int(STABLE_WINDOW_S * FS)
    fast_n = int(FAST_WINDOW_S * FS)
    beat_n = int(BEAT_WINDOW_S * FS)
    hr_n = int(HR_WINDOW_S * FS)

    times = deque(maxlen=history_n)
    samples = deque(maxlen=history_n)
    clipped = deque(maxlen=history_n)

    stable_history = deque(maxlen=STABLE_CONFIRM_WINDOWS)
    fast_history = deque(maxlen=FAST_CONFIRM_WINDOWS)
    last_published_rr = np.nan
    last_stable_update = -np.inf
    last_fast_update = -np.inf
    last_beat_update = -np.inf
    last_hr_update = -np.inf
    last_sent_peak_t = -np.inf
    latest_fast_rr = np.nan
    stable_hr = np.nan
    latest_window_hr = np.nan
    hr_is_valid = False

    print(f"Opening {args.port} at {args.baud} baud")
    print("Stable HR: 8 s window / 1 s update; haptics begin after valid HR warm-up.")
    print("Stable RR: 30 s / 5 s; fast RR change detector: 15 s / 2.5 s.")
    print("Close Arduino Serial Monitor and Serial Plotter. Press Ctrl+C to stop.\n")

    with serial.Serial(args.port, args.baud, timeout=1) as ser, \
         raw_path.open("w", newline="") as raw_file, \
         estimate_path.open("w", newline="") as estimate_file, \
         haptic_path.open("w", newline="") as haptic_file:

        raw_writer = csv.writer(raw_file)
        est_writer = csv.writer(estimate_file)
        haptic_writer = csv.writer(haptic_file)
        raw_writer.writerow(["time_s", "raw_ppg", "clipped"])
        est_writer.writerow([
            "time_s", "stable_hr_bpm", "window_hr_bpm", "fast_candidate_rpm",
            "stable_candidate_rpm", "published_rpm", "stable_confidence", "status",
            "rate_change", "riiv_rpm", "riiv_quality", "riav_rpm", "riav_quality",
            "rifv_rpm", "rifv_quality",
        ])
        haptic_writer.writerow([
            "host_time_s", "ppg_peak_time_s", "instantaneous_bpm", "stable_hr_bpm",
            "window_hr_bpm", "command", "pace_bpm",
        ])
        if pacer is not None:
            pacer_file = pacer_path.open("w", newline="")
            pacer_writer = csv.DictWriter(pacer_file, fieldnames=LOG_FIELDS)
            pacer_writer.writeheader()
            last_pacer_state = None
            print(f"Pacing mode: goal request {args.pace_goal_bpm:.1f} bpm, "
                  f"max {args.pace_max_seconds:.0f} s. Warm-up needs 10 consecutive valid HR updates.")

        # SAMD21 often resets upon USB serial open.
        time.sleep(2.0)
        ser.reset_input_buffer()

        if args.test_haptics and not args.no_haptics:
            send_command(ser, "TEST")
            print("Sent XIAO haptic TEST command: left, right, then both.")

        try:
            while True:
                item = parse_line(ser.readline().decode("utf-8", errors="ignore"))
                if item is None:
                    continue

                t, raw, clip = item
                times.append(t)
                samples.append(raw)
                clipped.append(clip)
                raw_writer.writerow([f"{t:.3f}", int(raw), clip])

                # The HR gate must be ready before heartbeat haptics begin.
                if len(samples) >= hr_n and (t - last_hr_update) >= HR_UPDATE_S:
                    stable_hr, latest_window_hr, hr_is_valid = estimate_stable_hr(
                        times,
                        samples,
                        clipped,
                        previous_hr=stable_hr,
                    )
                    last_hr_update = t

                    if hr_is_valid:
                        print(
                            f"HR stable={stable_hr:.1f} bpm "
                            f"(window={latest_window_hr:.1f} bpm)"
                        )

                    if pacer is not None:
                        row = pacer.update_hr(t, stable_hr, hr_is_valid)
                        pacer_writer.writerow(row)
                        pacer_file.flush()
                        if row["state"] != last_pacer_state:
                            print(f"PACER {row['state']} ({row['reason']}) HR0={row['hr0_bpm']:.1f} "
                                  f"goal={row['goal_bpm']:.1f} pace={row['pace_bpm']:.1f}")
                            last_pacer_state = row["state"]

                # Peak-synchronous feedback: one command for each new accepted PPG peak,
                # but only after the stable-HR quality gate is valid.
                if len(samples) >= beat_n and (t - last_beat_update) >= BEAT_UPDATE_S:
                    peak_t, beat_bpm = newly_confirmed_heartbeat(
                        times,
                        samples,
                        clipped,
                        last_sent_peak_t,
                    )
                    last_beat_update = t

                    if peak_t is not None:
                        if pacer is not None:
                            pacer.on_peak(peak_t)
                        elif hr_is_valid and not args.no_haptics:
                            send_command(ser, "HB")
                            haptic_writer.writerow([
                                f"{t:.3f}",
                                f"{peak_t:.3f}",
                                "" if not np.isfinite(beat_bpm) else f"{beat_bpm:.2f}",
                                "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                                "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                                "HB",
                                "",
                            ])
                            haptic_file.flush()
                            text_bpm = "--" if not np.isfinite(beat_bpm) else f"{beat_bpm:.1f}"
                            print(f"HB peak={peak_t:.3f}s ibi_hr={text_bpm} stable_hr={stable_hr:.1f}")

                        # Always advance duplicate suppression once an accepted PPG beat
                        # is observed, whether or not haptics are enabled/gated.
                        last_sent_peak_t = peak_t

                if pacer is not None:
                    command = pacer.poll(t)
                    if command is not None:
                        if not args.no_haptics:
                            send_command(ser, command)
                        haptic_writer.writerow([
                            f"{t:.3f}", "", "",
                            "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                            "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                            command,
                            "" if not np.isfinite(pacer.pace_bpm) else f"{pacer.pace_bpm:.2f}",
                        ])
                        haptic_file.flush()
                        if command == "HB":
                            print(f"PACE HB pace={pacer.pace_bpm:.1f} stable_hr={stable_hr:.1f} state={pacer.state}")
                        else:
                            print(f"PACE {command} ({pacer.reason})")

                if len(samples) >= fast_n and (t - last_fast_update) >= FAST_UPDATE_S:
                    ft = np.asarray(times, float)[-fast_n:]
                    fx = np.asarray(samples, float)[-fast_n:]
                    fc = np.asarray(clipped, int)[-fast_n:]
                    fast = analyze_window(ft, fx, fc)
                    last_fast_update = t
                    latest_fast_rr = fast.get("rr", np.nan)

                    if fast["status"] == "candidate":
                        if fast_history and abs(latest_fast_rr - fast_history[-1]) > FAST_TOLERANCE_RPM:
                            fast_history.clear()
                        fast_history.append(latest_fast_rr)
                    else:
                        fast_history.clear()

                if len(samples) < stable_n or (t - last_stable_update) < STABLE_UPDATE_S:
                    continue

                st = np.asarray(times, float)[-stable_n:]
                sx = np.asarray(samples, float)[-stable_n:]
                sc = np.asarray(clipped, int)[-stable_n:]
                stable_result = analyze_window(st, sx, sc)
                last_stable_update = t
                status = stable_result["status"]
                stable_rr = stable_result.get("rr", np.nan)
                rate_change = False

                if (
                    len(fast_history) == FAST_CONFIRM_WINDOWS
                    and np.ptp(fast_history) <= FAST_TOLERANCE_RPM
                    and np.isfinite(last_published_rr)
                    and abs(np.median(fast_history) - last_published_rr) >= CHANGE_TRIGGER_RPM
                ):
                    stable_history.clear()
                    rate_change = True

                if status == "candidate":
                    if stable_history and abs(stable_rr - stable_history[-1]) > STABLE_TOLERANCE_RPM:
                        stable_history.clear()
                    stable_history.append(stable_rr)

                    if len(stable_history) == STABLE_CONFIRM_WINDOWS and np.ptp(stable_history) <= STABLE_TOLERANCE_RPM:
                        last_published_rr = float(np.median(stable_history))
                        status = "published"
                    else:
                        status = f"pending_{len(stable_history)}_of_{STABLE_CONFIRM_WINDOWS}"
                else:
                    stable_history.clear()

                candidates = stable_result.get("candidates", {})
                est_writer.writerow([
                    f"{t:.3f}",
                    "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                    "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                    "" if not np.isfinite(latest_fast_rr) else f"{latest_fast_rr:.2f}",
                    "" if not np.isfinite(stable_rr) else f"{stable_rr:.2f}",
                    "" if not np.isfinite(last_published_rr) else f"{last_published_rr:.2f}",
                    f"{stable_result.get('confidence', 0.0):.2f}",
                    status,
                    int(rate_change),
                    field(candidates, "riiv", "rpm"), field(candidates, "riiv", "quality"),
                    field(candidates, "riav", "rpm"), field(candidates, "riav", "quality"),
                    field(candidates, "rifv", "rpm"), field(candidates, "rifv", "quality"),
                ])
                raw_file.flush()
                estimate_file.flush()

                diag = ", ".join(
                    f"{name}={item['rpm']:.1f}/Q{item['quality']:.2f}"
                    for name, item in candidates.items()
                )
                print(
                    f"t={t:7.1f}s HR={format_candidate(stable_hr):>5} "
                    f"fast={format_candidate(latest_fast_rr):>5} "
                    f"stable={format_candidate(stable_rr):>5} "
                    f"RR={format_candidate(last_published_rr):>5} "
                    f"{status} change={int(rate_change)} [{diag}]"
                )

        except KeyboardInterrupt:
            if not args.no_haptics:
                try:
                    send_command(ser, "OFF")
                except serial.SerialException:
                    pass
            print("\nStopped.")
        finally:
            if pacer is not None:
                pacer_file.close()

    print("Raw data saved to:", raw_path)
    print("Estimates saved to:", estimate_path)
    print("Haptic events saved to:", haptic_path)
    if pacer is not None:
        print("Pacer log saved to:", pacer_path)


if __name__ == "__main__":
    main()
