#!/usr/bin/env python3
"""Replay a logged raw PPG CSV through HapticPacer. No serial, no haptics.

Mirrors the live estimator loop: the same estimate_stable_hr and
newly_confirmed_heartbeat functions at the same cadences, then feeds the
pacer and records the commands it would have sent.

    python replay_haptic_pacer.py ppg_live_recordings/ppg_live_raw_X.csv \
        --goal 62 --out /tmp/replay

Optional --clip START:DURATION forces clipped=1 over that span (seconds from
the start of the recording) to exercise the degraded-signal path.
"""

import argparse
import csv
from collections import deque
from pathlib import Path

import numpy as np

import ppg_live_estimator_adaptive_haptics_stable_hr as est
from haptic_pacer import LOG_FIELDS, HapticPacer


def load_raw(path, clip_spans=()):
    t, raw, clipped = [], [], []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            t.append(float(row["time_s"]))
            raw.append(float(row["raw_ppg"]))
            clipped.append(int(row["clipped"]))
    t, raw, clipped = np.array(t), np.array(raw), np.array(clipped)
    for start, dur in clip_spans:
        span = (t >= t[0] + start) & (t < t[0] + start + dur)
        clipped[span] = 1
    return t, raw, clipped


def replay(t_all, raw_all, clip_all, goal_bpm, max_seconds=None):
    """Return (update_rows, command_rows) for one recording."""
    kwargs = {} if max_seconds is None else {"max_seconds": max_seconds}
    pacer = HapticPacer(goal_bpm=goal_bpm, **kwargs)

    history_n = int((est.STABLE_WINDOW_S + 5.0) * est.FS)
    hr_n = int(est.HR_WINDOW_S * est.FS)
    beat_n = int(est.BEAT_WINDOW_S * est.FS)
    times = deque(maxlen=history_n)
    samples = deque(maxlen=history_n)
    clipped = deque(maxlen=history_n)

    stable_hr = np.nan
    last_hr_update = -np.inf
    last_beat_update = -np.inf
    last_peak_t = -np.inf
    updates, commands = [], []

    for t, raw, clip in zip(t_all, raw_all, clip_all):
        times.append(t)
        samples.append(raw)
        clipped.append(clip)

        if len(samples) >= hr_n and (t - last_hr_update) >= est.HR_UPDATE_S:
            stable_hr, _, hr_is_valid = est.estimate_stable_hr(
                times, samples, clipped, previous_hr=stable_hr,
            )
            last_hr_update = t
            updates.append(pacer.update_hr(t, stable_hr, hr_is_valid))

        if len(samples) >= beat_n and (t - last_beat_update) >= est.BEAT_UPDATE_S:
            peak_t, _ = est.newly_confirmed_heartbeat(times, samples, clipped, last_peak_t)
            last_beat_update = t
            if peak_t is not None:
                pacer.on_peak(peak_t)
                last_peak_t = peak_t

        command = pacer.poll(t)
        if command is not None:
            commands.append({
                "time_s": t,
                "command": command,
                "pace_bpm": pacer.pace_bpm,
                "state": pacer.state,
            })

    return updates, commands


def parse_clip(text):
    start, dur = text.split(":")
    return float(start), float(dur)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_csv")
    parser.add_argument("--goal", type=float, required=True, help="Goal HR (BPM)")
    parser.add_argument("--clip", type=parse_clip, action="append", default=[],
                        help="Force clipping over START:DURATION seconds (repeatable)")
    parser.add_argument("--out", required=True, help="Output directory for replay CSVs")
    args = parser.parse_args()

    t, raw, clip = load_raw(args.raw_csv, args.clip)
    updates, commands = replay(t, raw, clip, args.goal)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(args.raw_csv).stem
    with (out_dir / f"{stem}_pacer_updates.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(updates)
    with (out_dir / f"{stem}_pacer_commands.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["time_s", "command", "pace_bpm", "state"])
        writer.writeheader()
        writer.writerows(commands)

    hb = [c for c in commands if c["command"] == "HB"]
    states = {}
    for row in updates:
        states[row["state"]] = states.get(row["state"], 0) + 1
    print(f"{stem}: {len(updates)} HR updates, {len(hb)} HB, "
          f"{len(commands) - len(hb)} OFF, states={states}")
    print("Saved to:", out_dir)


if __name__ == "__main__":
    main()
