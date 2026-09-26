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

GrooveGen link (groovegen_link.py; localhost UDP). --publish-udp sends each
1 Hz HR/RR estimate to GrooveGen. --goal-udp lets GrooveGen arm and steer
pacing: no pacer (and no echo pulses) until the first goal message, the goal
then follows GrooveGen's phase schedule, and pacing stops on {"stop": 1} or
if GrooveGen goes silent for 10 s:
    python ppg_live_estimator_adaptive_haptics_stable_hr.py \
        --port /dev/cu.usbmodemXXXX --publish-udp 127.0.0.1:5005 --goal-udp 5006

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
# Beat-doubling gate: when the diastolic/reflected wave is counted as a beat,
# the detected interval L is half the true period, so the cardiac-band PPG
# repeats better at 2L than at L. Reject when autocorr(2L) - autocorr(L)
# exceeds this. 12 recordings (2026-09-22/24), also time-compressed 1.5x and
# 1.9x: clean windows p99 <= 0.05, max 0.31 (2 of 4106 above 0.2); all 83
# windows at ~2x HR in the 22:21 run were 0.68..1.32.
HR_MAX_DOUBLE_PERIOD_GAIN = 0.2
# A doubled window is re-detected with peaks at least this fraction of the
# true period (2L) apart, so only the larger peak of each pair is kept, and
# accepted (reason ok_undoubled) only if it then passes both gates. Tried only
# when autocorr(L) < HR_UNDOUBLE_MAX_AC_L: a true half-period lag is
# anti-correlated (157 real doubled windows: <= -0.24); the one false
# recovery found (1.9x replay, HR halved) had +0.04. The live run 2026-09-25
# 11:28 (after cycling, HR ~80) was doubled in 76 of 101 updates.
HR_UNDOUBLE_MIN_FRAC = 0.75
HR_UNDOUBLE_MAX_AC_L = -0.1
# Signal-quality floor. The peak screens are relative, so band-passed noise
# with no pulse gave "valid" HR in ~60% of white-noise windows. Reject when
# the cardiac-band PPG barely repeats at the detected beat interval, or its
# SD is below HR_MIN_PULSE_SD counts. Offline (2026-09-25): 12 recordings,
# 1821 valid windows, period_ac p1 0.42, pulse_sd min 44 (7 windows lost,
# 0.4%; 12 of 1146 at 1.5-1.9x speed); noise passing: white 0.3%, pink
# 0.7%, brown 2% of windows (was 62/37/17%). Not yet checked on a real
# finger-off recording.
HR_MIN_PERIOD_AC = 0.3
HR_MIN_PULSE_SD = 20.0


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


def extract_pulses(t, raw, min_required_peaks=8, min_required_ibi=6, min_ibi_s=None):
    """Bandpass PPG and return robustly screened peaks and derived features.

    min_ibi_s overrides the minimum peak spacing (default 60 / MAX_BPM)."""
    x, t = np.asarray(raw, float), np.asarray(t, float)
    if len(x) < 40:
        return None

    try:
        ppg = bandpass(detrend(x), CARDIAC_BAND[0], CARDIAC_BAND[1], FS)
    except ValueError:
        return None

    min_distance = int(FS * (60.0 / MAX_BPM if min_ibi_s is None else min_ibi_s))
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


def period_autocorr(raw, period_s):
    """Normalized autocorrelation of the cardiac-band PPG at lag period_s."""
    lag = int(round(period_s * FS))
    x = np.asarray(raw, float)
    if lag < 1 or lag >= len(x) // 2:
        return np.nan
    try:
        ppg = bandpass(detrend(x), CARDIAC_BAND[0], CARDIAC_BAND[1], FS)
    except ValueError:
        return np.nan
    z = ppg - np.mean(ppg)
    var = np.mean(z * z)
    if var <= 0:
        return np.nan
    return float(np.mean(z[:-lag] * z[lag:]) / var)


def estimate_stable_hr(t, raw, clipped, previous_hr=np.nan, diag=None):
    """Estimate HR from the median valid IBI over the latest HR_WINDOW_S.

    Returns (smoothed_hr, window_hr, is_valid). The smoothed estimate uses an
    EMA only after a valid raw/window estimate has been obtained. If diag is a
    dict it is filled with the outcome for logging: reason (ok, short_history,
    clip_run, weak_pulse, no_pulses, few_ibi, doubled_beats, aperiodic;
    ok_undoubled = valid after re-detecting a doubled window),
    n_valid_ibi, double_gain,
    period_ac (autocorrelation at the detected beat interval) and pulse_sd
    (cardiac-band SD, ADC counts). Band-passed noise can pass the relative
    peak screens, so the last two are logged to judge signal quality.
    """
    if diag is None:
        diag = {}
    diag.update(reason="short_history", n_valid_ibi=0, double_gain=np.nan,
                period_ac=np.nan, pulse_sd=np.nan)
    n = int(HR_WINDOW_S * FS)
    if len(raw) < n:
        return previous_hr, np.nan, False

    wt = np.asarray(t, float)[-n:]
    wx = np.asarray(raw, float)[-n:]
    wc = np.asarray(clipped, int)[-n:]

    try:
        diag["pulse_sd"] = float(np.std(bandpass(detrend(wx), CARDIAC_BAND[0], CARDIAC_BAND[1], FS)))
    except ValueError:
        pass
    if has_long_clip_run(wx, wc):
        diag["reason"] = "clip_run"
        return previous_hr, np.nan, False
    if not diag["pulse_sd"] >= HR_MIN_PULSE_SD:
        diag["reason"] = "weak_pulse"
        return previous_hr, np.nan, False

    def detect(min_ibi_s=None):
        data = extract_pulses(wt, wx, min_required_peaks=5,
                              min_required_ibi=HR_MIN_VALID_IBI, min_ibi_s=min_ibi_s)
        if data is None:
            return None
        ibi = np.diff(data[0])
        return ibi[(ibi >= 60.0 / HR_MAX_BPM) & (ibi <= 60.0 / HR_MIN_BPM)]

    ibi = detect()
    if ibi is None:
        diag["reason"] = "no_pulses"
        return previous_hr, np.nan, False
    diag["n_valid_ibi"] = len(ibi)
    if len(ibi) < HR_MIN_VALID_IBI:
        diag["reason"] = "few_ibi"
        return previous_hr, np.nan, False

    # Windows whose detected beat interval is half the waveform's period
    # (double-counted beats) are re-detected once at the doubled period;
    # if that still fails the gates they are rejected (never clamped).
    median_ibi = float(np.median(ibi))
    ac_1x = period_autocorr(wx, median_ibi)
    gain = period_autocorr(wx, 2.0 * median_ibi) - ac_1x
    undoubled = False
    if gain > HR_MAX_DOUBLE_PERIOD_GAIN and ac_1x < HR_UNDOUBLE_MAX_AC_L:
        ibi2 = detect(HR_UNDOUBLE_MIN_FRAC * 2.0 * median_ibi)
        if ibi2 is not None and len(ibi2) >= HR_MIN_VALID_IBI:
            median2 = float(np.median(ibi2))
            ac2 = period_autocorr(wx, median2)
            gain2 = period_autocorr(wx, 2.0 * median2) - ac2
            if gain2 <= HR_MAX_DOUBLE_PERIOD_GAIN:
                ibi, median_ibi, ac_1x, gain, undoubled = ibi2, median2, ac2, gain2, True
                diag["n_valid_ibi"] = len(ibi)
    diag["period_ac"] = float(ac_1x)
    diag["double_gain"] = float(gain)
    if gain > HR_MAX_DOUBLE_PERIOD_GAIN:
        diag["reason"] = "doubled_beats"
        return previous_hr, np.nan, False
    if not ac_1x >= HR_MIN_PERIOD_AC:
        diag["reason"] = "aperiodic"
        return previous_hr, np.nan, False

    window_hr = float(np.median(60.0 / ibi))
    if not np.isfinite(previous_hr):
        smoothed_hr = window_hr
    else:
        smoothed_hr = HR_EMA_ALPHA * window_hr + (1.0 - HR_EMA_ALPHA) * previous_hr

    diag["reason"] = "ok_undoubled" if undoubled else "ok"
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
    parser.add_argument("--pace-invalid-window-s", type=float, default=None,
                        help="Pacing mode: count the 30 s invalid-HR limit over this trailing "
                             "window instead of the whole run (default: whole run)")
    parser.add_argument("--publish-udp", default=None, metavar="HOST:PORT",
                        help="Publish each 1 Hz HR/RR estimate as JSON to GrooveGen")
    parser.add_argument("--goal-udp", type=int, default=None, metavar="PORT",
                        help="Pacing goals from GrooveGen on 127.0.0.1:PORT; disables peak echo")
    args = parser.parse_args()
    if args.goal_udp is not None and args.pace_goal_bpm is not None:
        parser.error("--goal-udp and --pace-goal-bpm are exclusive (GrooveGen sets the goal)")

    from groovegen_link import GrooveGenLink, parse_host_port
    link = GrooveGenLink(
        publish_addr=None if args.publish_udp is None else parse_host_port(args.publish_udp),
        goal_port=args.goal_udp,
    )

    pacing_enabled = args.pace_goal_bpm is not None or args.goal_udp is not None
    pacer = None
    pacer_stopped = False   # a GrooveGen stop before arming: never create the pacer
    if pacing_enabled:
        from haptic_pacer import DONE, LOG_FIELDS, HapticPacer
    if args.pace_goal_bpm is not None:
        pacer = HapticPacer(goal_bpm=args.pace_goal_bpm, max_seconds=args.pace_max_seconds,
                            invalid_window_s=args.pace_invalid_window_s)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_path = out_dir / f"ppg_live_raw_{stamp}.csv"
    estimate_path = out_dir / f"ppg_live_adaptive_{stamp}.csv"
    haptic_path = out_dir / f"ppg_haptic_events_{stamp}.csv"
    pacer_path = out_dir / f"ppg_pacer_{stamp}.csv"
    hr_path = out_dir / f"ppg_hr_{stamp}.csv"

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
    hr_diag = {}
    n_hb_sent = 0                      # HB commands actually written to the XIAO
    hb_sent_t = deque()                # their MCU times, for per-window motor counts
    goal_source = "udp" if args.goal_udp is not None else "cli" if pacing_enabled else None

    print(f"Opening {args.port} at {args.baud} baud")
    print("Stable HR: 8 s window / 1 s update; haptics begin after valid HR warm-up.")
    print("Stable RR: 30 s / 5 s; fast RR change detector: 15 s / 2.5 s.")
    print("Close Arduino Serial Monitor and Serial Plotter. Press Ctrl+C to stop.\n")

    with serial.Serial(args.port, args.baud, timeout=1) as ser, \
         raw_path.open("w", newline="") as raw_file, \
         estimate_path.open("w", newline="") as estimate_file, \
         haptic_path.open("w", newline="") as haptic_file, \
         hr_path.open("w", newline="") as hr_file:

        raw_writer = csv.writer(raw_file)
        est_writer = csv.writer(estimate_file)
        haptic_writer = csv.writer(haptic_file)
        hr_writer = csv.writer(hr_file)
        raw_writer.writerow(["time_s", "raw_ppg", "clipped"])
        est_writer.writerow([
            "time_s", "stable_hr_bpm", "window_hr_bpm", "fast_candidate_rpm",
            "stable_candidate_rpm", "published_rpm", "stable_confidence", "status",
            "rate_change", "riiv_rpm", "riiv_quality", "riav_rpm", "riav_quality",
            "rifv_rpm", "rifv_quality",
        ])
        # host_time_s is the MCU time of the triggering sample (historical name);
        # wall_time_s is host time.time(); sent=0 means logged but not written
        # to the XIAO (--no-haptics).
        haptic_writer.writerow([
            "host_time_s", "ppg_peak_time_s", "instantaneous_bpm", "stable_hr_bpm",
            "window_hr_bpm", "command", "pace_bpm", "wall_time_s", "sent",
        ])
        # One row per 1 Hz HR update (the value published to GrooveGen). time_s
        # (MCU) + wall_time_s pair the two clocks; serial_backlog_bytes is
        # ser.in_waiting then, so backlogged rows can be dropped from a clock fit.
        # n_hb_in_window counts HB commands sent in the HR window (motor artifact).
        hr_writer.writerow([
            "time_s", "wall_time_s", "serial_backlog_bytes", "stable_hr_bpm",
            "window_hr_bpm", "valid", "reason", "n_valid_ibi", "double_gain",
            "period_ac", "pulse_sd", "n_hb_in_window", "n_hb_sent",
        ])
        if pacing_enabled:
            pacer_file = pacer_path.open("w", newline="")
            pacer_writer = csv.DictWriter(pacer_file, fieldnames=LOG_FIELDS)
            pacer_writer.writeheader()
            last_pacer_state = None
            if pacer is not None:
                print(f"Pacing mode: goal request {args.pace_goal_bpm:.1f} bpm, "
                      f"max {args.pace_max_seconds:.0f} s. Warm-up needs 10 consecutive valid HR updates.")
            else:
                print(f"Pacing mode: waiting for a GrooveGen goal on UDP {args.goal_udp} "
                      f"(max {args.pace_max_seconds:.0f} s once armed). No pulses until then.")
        if args.publish_udp is not None:
            print(f"Publishing HR/RR to GrooveGen at {args.publish_udp}")

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

                # GrooveGen goals / stop / watchdog (drains all pending datagrams)
                if args.goal_udp is not None:
                    msg = link.poll()
                    if msg == "stop":
                        if pacer is not None and pacer.state != DONE:
                            pacer.stop("session_end")
                            print("PACER stop from GrooveGen (session_end)")
                        pacer_stopped = True
                    elif msg is not None and not pacer_stopped:
                        if pacer is None:
                            pacer = HapticPacer(goal_bpm=msg, max_seconds=args.pace_max_seconds,
                                                invalid_window_s=args.pace_invalid_window_s)
                            print(f"PACER armed by GrooveGen: goal request {msg:.1f} bpm; "
                                  f"warm-up needs 10 consecutive valid HR updates.")
                        elif pacer.set_goal(msg, t):
                            print(f"PACER goal -> {pacer.goal_bpm:.1f} bpm (request {msg:.1f}, "
                                  f"from ref {pacer.origin_bpm:.1f})")
                    if pacer is not None and pacer.state != DONE and link.watchdog_expired():
                        pacer.stop("controller_lost")
                        print("PACER stop: no GrooveGen message for "
                              f"{link.watchdog_s:.0f} s (controller_lost)")

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
                        diag=hr_diag,
                    )
                    last_hr_update = t
                    wall_now = time.time()
                    while hb_sent_t and hb_sent_t[0] < t - HR_WINDOW_S:
                        hb_sent_t.popleft()
                    hr_writer.writerow([
                        f"{t:.3f}", f"{wall_now:.3f}", ser.in_waiting,
                        "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                        "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                        int(hr_is_valid), hr_diag["reason"], hr_diag["n_valid_ibi"],
                        "" if not np.isfinite(hr_diag["double_gain"]) else f"{hr_diag['double_gain']:.3f}",
                        "" if not np.isfinite(hr_diag["period_ac"]) else f"{hr_diag['period_ac']:.3f}",
                        "" if not np.isfinite(hr_diag["pulse_sd"]) else f"{hr_diag['pulse_sd']:.2f}",
                        len(hb_sent_t), n_hb_sent,
                    ])
                    hr_file.flush()

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

                    if args.publish_udp is not None:
                        mode = ("off" if args.no_haptics else "pacing" if pacing_enabled
                                else "echo")
                        link.publish({
                            "t_wall": wall_now,
                            "t_ppg": t,
                            "hr_bpm": float(stable_hr) if hr_is_valid else None,
                            "valid": bool(hr_is_valid),
                            "window_hr": float(latest_window_hr),
                            "rr_rpm": float(last_published_rr),
                            "haptic_mode": mode,
                            "pacer_state": None if pacer is None else pacer.state,
                            "pace_bpm": None if pacer is None else float(pacer.pace_bpm),
                            "goal_bpm": None if pacer is None else float(pacer.goal_bpm),
                            "hr0": None if pacer is None else float(pacer.hr0),
                            "hr_reason": hr_diag["reason"],
                            "n_hb_sent": n_hb_sent,
                            "goal_source": goal_source,
                            "log_stamp": stamp,
                        })

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
                        elif hr_is_valid and not args.no_haptics and args.goal_udp is None:
                            send_command(ser, "HB")
                            n_hb_sent += 1
                            hb_sent_t.append(t)
                            haptic_writer.writerow([
                                f"{t:.3f}",
                                f"{peak_t:.3f}",
                                "" if not np.isfinite(beat_bpm) else f"{beat_bpm:.2f}",
                                "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                                "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                                "HB",
                                "",
                                f"{time.time():.3f}",
                                1,
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
                            if command == "HB":
                                n_hb_sent += 1
                                hb_sent_t.append(t)
                        haptic_writer.writerow([
                            f"{t:.3f}", "", "",
                            "" if not np.isfinite(stable_hr) else f"{stable_hr:.2f}",
                            "" if not np.isfinite(latest_window_hr) else f"{latest_window_hr:.2f}",
                            command,
                            "" if not np.isfinite(pacer.pace_bpm) else f"{pacer.pace_bpm:.2f}",
                            f"{time.time():.3f}",
                            int(not args.no_haptics),
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
            print("\nStopped.")
        finally:
            # Motors off on every exit path (Ctrl+C, serial error, crash).
            if not args.no_haptics:
                try:
                    send_command(ser, "OFF")
                except (serial.SerialException, OSError):
                    pass
            link.close()
            if pacing_enabled:
                pacer_file.close()

    print("Raw data saved to:", raw_path)
    print("Estimates saved to:", estimate_path)
    print("Haptic events saved to:", haptic_path)
    print("1 Hz HR log saved to:", hr_path)
    if pacing_enabled:
        print("Pacer log saved to:", pacer_path)


if __name__ == "__main__":
    main()
