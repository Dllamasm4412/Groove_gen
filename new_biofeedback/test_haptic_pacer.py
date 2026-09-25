"""Offline checks for HapticPacer. No serial, no haptics.

Run: python new_biofeedback/test_haptic_pacer.py

Part 1 drives the pacer with synthetic HR (follower, non-follower, both
directions, dropouts, out-of-range HR, duration limit). Part 2 replays every
raw recording in ppg_live_recordings/ through the estimator's own HR and peak
functions and checks the safety bounds on real signal quality.
"""

import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import haptic_pacer as hp  # noqa: E402
from replay_haptic_pacer import load_raw, replay  # noqa: E402

EPS = 1e-6
SAMPLE_S = 0.01
SLEW_PER_UPDATE = hp.PACE_RAMP_BPM_PER_MIN / 60.0


def drive(pacer, hr_fn, duration_s):
    """Synthetic loop: HR update at 1 Hz, a PPG peak every 60/HR s, poll at 100 Hz.

    hr_fn(t, pacer) -> (hr_bpm, valid). Returns (updates, commands).
    """
    updates, commands = [], []
    next_peak = 0.5
    hr, valid = hr_fn(0.0, pacer)
    for i in range(int(duration_s / SAMPLE_S)):
        t = round(i * SAMPLE_S, 6)
        if i % int(1.0 / SAMPLE_S) == 0:
            hr, valid = hr_fn(t, pacer)
            updates.append(pacer.update_hr(t, hr, valid))
        if valid and t >= next_peak:
            pacer.on_peak(t)
            next_peak = t + 60.0 / hr
        command = pacer.poll(t)
        if command is not None:
            commands.append((t, command, pacer.state, pacer.pace_bpm))
    return updates, commands


def follower(hr0):
    """HR that tracks the pacing rate exactly (best case)."""
    def fn(t, pacer):
        hr = pacer.pace_bpm if np.isfinite(pacer.pace_bpm) else hr0
        return hr, True
    return fn


def constant(hr, invalid_spans=(), jumps=()):
    """Constant HR, with optional invalid spans and (t_from, hr) level changes."""
    def fn(t, pacer):
        level = hr
        for t_from, new_hr in jumps:
            if t >= t_from:
                level = new_hr
        valid = not any(a <= t < b for a, b in invalid_spans)
        return level, valid
    return fn


def pacing_rows(updates):
    return [u for u in updates if u["state"] in (hp.PACING, hp.HOLDING)]


def hb_times(commands):
    return [c[0] for c in commands if c[1] == "HB"]


# ---- Part 1: synthetic ----

def test_warmup_no_pulses_and_reset():
    invalid = [(4.0, 5.0)]
    pacer = hp.HapticPacer(goal_bpm=70.0)
    updates, commands = drive(pacer, constant(65.0, invalid_spans=invalid), 30.0)
    started = next(u["time_s"] for u in updates if u["state"] == hp.PACING)
    # Invalid at t=4 resets the count: 10 valid updates run 5..14.
    assert started == 14.0, started
    assert all(t >= started for t in hb_times(commands)), "HB during warmup"
    print(f"(warmup) PASS: no HB before start; invalid update reset warmup (start t={started:.0f}s)")


def test_warmup_ignores_decaying_ema():
    # Run 18:53: first window read 148.7, EMA decayed 129 -> 70 over ~10 s. HR0 must be the settled value.
    decay = [148.7, 129.4, 115.0, 104.1, 95.8, 89.2, 84.0, 79.5, 76.1, 73.4, 71.1, 69.7, 68.6, 67.5]
    def fn(t, pacer):
        i = int(t)
        return (decay[i] if i < len(decay) else 67.0), True
    pacer = hp.HapticPacer(goal_bpm=62.0)
    updates, commands = drive(pacer, fn, 40.0)
    started = next(u for u in updates if u["state"] == hp.PACING)
    assert abs(started["hr0_bpm"] - 67.0) < 1.5, started["hr0_bpm"]
    assert started["goal_bpm"] == 62.0 and pacer.state == hp.PACING, (started, pacer.state)
    print(f"(warmup spread) PASS: decaying EMA 148->67 gives HR0 {started['hr0_bpm']:.1f} at t={started['time_s']:.0f}s (not ~82)")


def test_goal_clipped():
    up = hp.HapticPacer(goal_bpm=90.0)
    drive(up, constant(65.0), 15.0)
    down = hp.HapticPacer(goal_bpm=40.0)
    drive(down, constant(65.0), 15.0)
    assert up.goal_bpm == 71.0 and up.goal_clipped, (up.goal_bpm, up.goal_clipped)
    assert down.goal_bpm == 59.0 and down.goal_clipped, (down.goal_bpm, down.goal_clipped)
    ok = hp.HapticPacer(goal_bpm=68.0)
    drive(ok, constant(65.0), 15.0)
    assert ok.goal_bpm == 68.0 and not ok.goal_clipped
    print("(goal clip) PASS: 90->71, 40->59 at HR0=65; 68 unclipped")


def check_follower(hr0, goal, direction):
    pacer = hp.HapticPacer(goal_bpm=goal)
    updates, commands = drive(pacer, follower(hr0), 300.0)
    rows = pacing_rows(updates)
    pace = np.array([r["pace_bpm"] for r in rows])
    steps = np.diff(pace)
    assert np.all(direction * steps >= -EPS), "pace moved away from goal"
    assert np.max(np.abs(steps)) <= SLEW_PER_UPDATE + EPS, np.max(np.abs(steps))
    assert np.all(direction * (pace - goal) <= EPS), "pace crossed goal"
    assert abs(pace[-1] - goal) < 0.2, pace[-1]

    hb = np.array(hb_times(commands))
    ibi = np.diff(hb)
    assert np.all(ibi >= 60.0 / hp.PACE_MAX_BPM - SAMPLE_S), ibi.min()
    # Each interval matches the pace in force when it was scheduled.
    sched = np.array([c[3] for c in commands if c[1] == "HB"])[:-1]
    assert np.max(np.abs(ibi - 60.0 / sched)) <= SAMPLE_S + EPS, np.max(np.abs(ibi - 60.0 / sched))
    return pace, steps, hb


def test_follower_up():
    pace, steps, hb = check_follower(65.0, 71.0, +1)
    print(f"(follower up) PASS: 65->{pace[-1]:.2f} (goal 71) in 286 s, "
          f"max step {np.max(np.abs(steps)):.3f} bpm/s <= {SLEW_PER_UPDATE:.3f}, {len(hb)} HB, IBI = 60/pace +/-10 ms")


def test_follower_down():
    pace, steps, hb = check_follower(80.0, 74.0, -1)
    print(f"(follower down) PASS: 80->{pace[-1]:.2f} (goal 74), "
          f"max step {np.max(np.abs(steps)):.3f} bpm/s, never below goal, {len(hb)} HB")


def test_non_follower_lead_bound():
    for goal, direction in ((71.0, +1), (59.0, -1)):
        pacer = hp.HapticPacer(goal_bpm=goal, max_lead_bpm=3.0)
        updates, _ = drive(pacer, constant(65.0), 200.0)
        rows = pacing_rows(updates)
        lead = np.array([r["pace_bpm"] - r["hr_bpm"] for r in rows])
        assert np.all(np.abs(lead) <= 3.0 + EPS), np.abs(lead).max()
        assert abs(rows[-1]["pace_bpm"] - (65.0 + direction * 3.0)) < EPS, rows[-1]["pace_bpm"]
        assert rows[-1]["ramp_frozen"] == 1
    print("(non-follower) PASS: HR fixed at 65, pace plateaus at 65+/-lead (3) with ramp_frozen=1, both directions")


def test_short_dropout_keeps_pulsing():
    pacer = hp.HapticPacer(goal_bpm=71.0)
    updates, commands = drive(pacer, constant(65.0, invalid_spans=[(60.0, 62.0)]), 80.0)
    assert not any(c[1] == "OFF" for c in commands), "OFF on 2 s dropout"
    assert any(60.0 <= t <= 63.0 for t in hb_times(commands)), "no HB while holding"
    frozen = [u["ref_bpm"] for u in updates if 59.0 <= u["time_s"] <= 61.0]
    assert frozen[1] == frozen[2] == frozen[0], frozen
    print("(2 s dropout) PASS: HOLDING keeps HB at frozen pace, no OFF")


def test_long_dropout_stops_and_resumes():
    pacer = hp.HapticPacer(goal_bpm=71.0)
    fn = constant(65.0, invalid_spans=[(60.0, 65.0)], jumps=[(62.0, 61.0)])
    updates, commands = drive(pacer, fn, 90.0)
    offs = [c[0] for c in commands if c[1] == "OFF"]
    assert len(offs) == 1 and 62.0 < offs[0] <= 62.0 + SAMPLE_S + EPS, offs
    resumed = next(u["time_s"] for u in updates if u["time_s"] > 60.0 and u["state"] == hp.PACING)
    assert resumed == 67.0, resumed  # valid at 65, 66, 67
    gap = [t for t in hb_times(commands) if offs[0] <= t < resumed]
    assert not gap, gap
    after = [t for t in hb_times(commands) if t >= resumed]
    assert after, "never resumed pulsing"
    rows = pacing_rows(updates)
    for prev, cur in zip(rows, rows[1:]):
        step = abs(cur["pace_bpm"] - prev["pace_bpm"])
        on_boundary = abs(abs(cur["pace_bpm"] - cur["hr_bpm"]) - hp.PACE_MAX_LEAD_BPM) < 1e-6
        assert step <= SLEW_PER_UPDATE + EPS or on_boundary, (prev, cur)
    print(f"(5 s dropout) PASS: OFF at {offs[0]:.2f}s (last valid 59 s + hold 3 s), slew/clamp holds across "
          f"a 4 bpm HR change during the dropout, silent until 3rd valid update "
          f"(t={resumed:.0f}s), first HB after resume {after[0]:.2f}s")


def test_signal_lost_ends():
    pacer = hp.HapticPacer(goal_bpm=71.0)
    updates, commands = drive(pacer, constant(65.0, invalid_spans=[(60.0, 200.0)]), 120.0)
    assert pacer.state == hp.DONE and pacer.reason == "signal_lost", (pacer.state, pacer.reason)
    assert not [t for t in hb_times(commands) if t > 62.0 + SAMPLE_S], "HB after hold expired"
    done_t = next(u["time_s"] for u in updates if u["state"] == hp.DONE)
    print(f"(signal lost) PASS: DONE/signal_lost at t={done_t:.0f}s (>30 s invalid), no HB after hold expiry")


def test_hr_out_of_range_pauses():
    pacer = hp.HapticPacer(goal_bpm=100.0)
    updates, commands = drive(pacer, constant(97.0, jumps=[(40.0, 110.0)]), 60.0)
    assert pacer.state == hp.PAUSED and pacer.reason == "hr_out_of_range", (pacer.state, pacer.reason)
    off = [c[0] for c in commands if c[1] == "OFF"]
    assert len(off) == 1 and 40.0 <= off[0] <= 40.0 + SAMPLE_S + EPS, off
    assert not [t for t in hb_times(commands) if t > off[0]]
    assert all(u["pace_bpm"] <= hp.PACE_MAX_BPM + EPS for u in updates if np.isfinite(u["pace_bpm"]))

    low = hp.HapticPacer(goal_bpm=40.0)
    updates, _ = drive(low, constant(48.0), 40.0)
    rows = pacing_rows(updates)
    assert all(r["pace_bpm"] >= hp.PACE_MIN_BPM - EPS for r in rows)
    assert low.state == hp.PACING and rows[-1]["abs_bound"] == 1
    print("(abs range) PASS: HR 97->110 pauses with OFF (pace capped at 100); HR 48 paces at floor 50 with abs_bound=1")


def test_max_duration():
    pacer = hp.HapticPacer(goal_bpm=71.0, max_seconds=60.0)
    updates, commands = drive(pacer, constant(65.0), 100.0)
    assert pacer.state == hp.DONE and pacer.reason == "max_duration"
    off = [c[0] for c in commands if c[1] == "OFF"]
    start = next(u["time_s"] for u in updates if u["state"] == hp.PACING)
    assert len(off) == 1 and start + 60.0 < off[0] <= start + 60.0 + SAMPLE_S + EPS, (start, off)
    assert not [t for t in hb_times(commands) if t > off[0]]
    print(f"(max duration) PASS: OFF at {off[0]:.2f}s = start {start:.0f}s + 60 s, no HB after")


def test_abs_range_near_limits():
    # Reviewer case 1: HR0 44, goal 48. Goal is clipped into 50..100, and HR 44
    # cannot be paced within the lead at >= 50, so no pulses at all.
    low = hp.HapticPacer(goal_bpm=48.0)
    updates, commands = drive(low, constant(44.0), 40.0)
    assert low.goal_bpm == 50.0, low.goal_bpm
    assert not hb_times(commands) and low.state == hp.PAUSED and low.reason == "hr_out_of_range"
    # Reviewer case 2: warmup at 108, HR 105, goal 62 -> goal clipped to 100, pace <= 100.
    high = hp.HapticPacer(goal_bpm=62.0)
    updates, commands = drive(high, constant(108.0, jumps=[(10.0, 105.0)]), 60.0)
    assert high.goal_bpm == 100.0, high.goal_bpm
    paces = [c[3] for c in commands if c[1] == "HB"]
    assert paces and max(paces) <= hp.PACE_MAX_BPM + EPS, max(paces)
    for u in pacing_rows(updates):
        assert hp.PACE_MIN_BPM - EPS <= u["pace_bpm"] <= hp.PACE_MAX_BPM + EPS, u
    print(f"(near limits) PASS: HR0 44/goal 48 -> goal 50, never pulses; HR0 108 -> goal 100, max HB pace {max(paces):.1f}")


def test_hr_past_goal_no_off_cycling():
    pacer = hp.HapticPacer(goal_bpm=71.0)
    updates, commands = drive(pacer, constant(65.0, jumps=[(30.0, 80.0)]), 80.0)
    offs = [c[0] for c in commands if c[1] == "OFF"]
    assert pacer.state == hp.PAUSED and pacer.reason == "hr_past_goal", (pacer.state, pacer.reason)
    assert len(offs) == 1, offs
    assert not [t for t in hb_times(commands) if t > offs[0]]
    print(f"(past goal) PASS: HR 65->80 with goal 71 pauses as hr_past_goal, exactly 1 OFF over 50 s (no resume cycling)")


def test_bad_inputs():
    for kwargs in ({"goal_bpm": float("nan")}, {"goal_bpm": 70.0, "max_seconds": float("inf")},
                   {"goal_bpm": 70.0, "max_seconds": float("nan")}, {"goal_bpm": 70.0, "max_lead_bpm": -1.0}):
        try:
            hp.HapticPacer(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"accepted {kwargs}")
    pacer = hp.HapticPacer(goal_bpm=71.0)
    drive(pacer, constant(65.0), 20.0)
    for bad in (None, float("nan"), float("inf"), "x"):
        row = pacer.update_hr(20.0, bad, True)
        assert row["hr_valid"] == 0, (bad, row)
    print("(bad inputs) PASS: NaN/inf/negative constructor args raise ValueError; None/NaN/inf/str HR with valid=True treated invalid")


def test_stall_single_pulse_and_capped_invalid_time():
    pacer = hp.HapticPacer(goal_bpm=71.0)
    _, commands = drive(pacer, constant(65.0), 30.0)
    before = len(hb_times(commands))
    burst = [pacer.poll(40.0), pacer.poll(40.0), pacer.poll(40.001)]
    assert burst.count("HB") == 1, burst
    # One invalid update after a 34 s host stall counts at most PACE_MAX_UPDATE_DT_S.
    pacer.update_hr(29.0, 65.0, True)
    row = pacer.update_hr(63.0, 65.0, False)
    assert row["invalid_total_s"] <= hp.PACE_MAX_UPDATE_DT_S + EPS and pacer.state != hp.DONE, row
    print(f"(stall) PASS: 10 s poll jump gives 1 HB (after {before}), 34 s stall adds {row['invalid_total_s']:.0f} s invalid, not DONE")


def test_stop_off_only_when_pulsing():
    paused = hp.HapticPacer(goal_bpm=71.0)
    _, commands = drive(paused, constant(65.0, invalid_spans=[(20.0, 40.0)]), 30.0)
    assert paused.state == hp.PAUSED
    paused.stop()
    assert paused.poll(30.0) is None, "OFF from PAUSED"
    warm = hp.HapticPacer(goal_bpm=71.0)
    warm.stop()
    assert warm.poll(0.0) is None, "OFF from WARMUP"
    live = hp.HapticPacer(goal_bpm=71.0)
    drive(live, constant(65.0), 30.0)
    live.stop()
    assert live.poll(30.0) == "OFF" and live.poll(30.01) is None
    print("(stop) PASS: stop() sends one OFF only when pulsing; none from PAUSED or WARMUP")


# ---- Part 2: replay on logged PPG ----

def check_replay(name, updates, commands):
    rows = pacing_rows(updates)
    hb = [c for c in commands if c["command"] == "HB"]
    stats = {"rows": len(rows), "hb": len(hb), "off": len(commands) - len(hb)}
    if not rows:
        return stats

    for r in rows:
        assert hp.PACE_MIN_BPM - EPS <= r["pace_bpm"] <= hp.PACE_MAX_BPM + EPS, (name, r)
        direction = 1.0 if r["goal_bpm"] >= r["hr0_bpm"] else -1.0
        assert direction * (r["pace_bpm"] - r["goal_bpm"]) <= EPS, (name, "crossed goal", r)
        if r["hr_valid"]:
            assert abs(r["pace_bpm"] - r["hr_bpm"]) <= hp.PACE_MAX_LEAD_BPM + EPS, (name, "lead", r)

    # Slew: the ramp moves <= 0.1 bpm per 1 s update unless the lead clamp is
    # dragging the pace along with measured HR (pace sits on the lead boundary).
    fast = 0
    for prev, cur in zip(rows, rows[1:]):
        step = abs(cur["pace_bpm"] - prev["pace_bpm"])
        on_boundary = abs(abs(cur["pace_bpm"] - cur["hr_bpm"]) - hp.PACE_MAX_LEAD_BPM) < 1e-6
        if step > SLEW_PER_UPDATE + EPS:
            assert on_boundary, (name, "slew", prev, cur)
            fast += 1
    stats["clamp_steps"] = fast

    # No HB unless pacing/holding, and never more than the hold after invalid onset.
    last_valid_t = None
    ui = 0
    for c in commands:
        while ui < len(updates) and updates[ui]["time_s"] <= c["time_s"]:
            if updates[ui]["hr_valid"]:
                last_valid_t = updates[ui]["time_s"]
            ui += 1
        if c["command"] != "HB":
            continue
        assert c["state"] in (hp.PACING, hp.HOLDING), (name, c)
        if not updates[ui - 1]["hr_valid"]:
            assert c["time_s"] - last_valid_t <= hp.PACE_HOLD_S + SAMPLE_S + EPS, (name, "HB past hold", c)

    hb_t = np.array([c["time_s"] for c in hb])
    if len(hb_t) > 1:
        ibi = np.diff(hb_t)
        assert np.all(ibi >= 60.0 / hp.PACE_MAX_BPM - SAMPLE_S - EPS), (name, ibi.min())
    stats["hr0"] = rows[0]["hr0_bpm"]
    stats["goal"] = rows[0]["goal_bpm"]
    stats["pace_end"] = rows[-1]["pace_bpm"]
    stats["states"] = {s: sum(u["state"] == s for u in updates)
                       for s in (hp.WARMUP, hp.PACING, hp.HOLDING, hp.PAUSED, hp.DONE)}
    return stats


def test_replay_recordings():
    raws = sorted((HERE / "ppg_live_recordings").glob("ppg_live_raw_*.csv"))
    assert raws, "no recordings"
    for path in raws:
        # Goal requests far outside +/-6 exercise the goal clip in both directions.
        cases = [("up", 200.0, ()), ("down", 1.0, ())]
        t_all, _, _ = load_raw(path)
        mid = (t_all[-1] - t_all[0]) / 2.0
        cases.append(("up+clip", 200.0, [(mid, 5.0)]))
        for label, goal, spans in cases:
            t, raw, clip = load_raw(path, spans)
            updates, commands = replay(t, raw, clip, goal)
            s = check_replay(path.stem, updates, commands)
            if s["rows"] == 0:
                print(f"  {path.stem[13:]} {label:8s} never left warmup ({len(updates)} HR updates)")
                continue
            print(f"  {path.stem[13:]} {label:8s} HR0 {s['hr0']:.1f} goal {s['goal']:.1f} "
                  f"pace_end {s['pace_end']:.1f} HB {s['hb']:3d} OFF {s['off']} "
                  f"clamp_steps {s['clamp_steps']} states {s['states']}")
    print(f"(replay) PASS: bounds, goal clip, slew/clamp, hold and HB spacing hold on {len(raws)} recordings")


if __name__ == "__main__":
    test_warmup_no_pulses_and_reset()
    test_warmup_ignores_decaying_ema()
    test_goal_clipped()
    test_follower_up()
    test_follower_down()
    test_non_follower_lead_bound()
    test_short_dropout_keeps_pulsing()
    test_long_dropout_stops_and_resumes()
    test_signal_lost_ends()
    test_hr_out_of_range_pauses()
    test_max_duration()
    test_abs_range_near_limits()
    test_hr_past_goal_no_off_cycling()
    test_bad_inputs()
    test_stall_single_pulse_and_capped_invalid_time()
    test_stop_off_only_when_pulsing()
    test_replay_recordings()
    print("\nALL HAPTIC PACER TESTS PASSED")
