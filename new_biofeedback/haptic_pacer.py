"""Graduated haptic heartbeat pacing, driven by the stable-HR estimator.

Pure logic, no serial I/O, so it can be replayed against logged PPG
(replay_haptic_pacer.py) before it ever drives the XIAO motors.

Echo mode sends HB on every confirmed PPG peak. Pacing mode instead
schedules HB pulses at a pacing rate that starts at the user's own current
HR and ramps toward a goal HR:

- Current state: HR0 = median stable HR over the first
  PACE_INIT_VALID_UPDATES consecutive valid HR updates whose spread is
  within PACE_WARMUP_MAX_SPREAD_BPM (the estimator's EMA can start from a
  bad first window and decay for ~10 s; that decay must not become HR0).
- Goal state: a manually set goal, clipped to HR0 +/- PACE_MAX_GOAL_OFFSET_BPM.
- Ramp: groovegen_pilot/hr_trajectory.HRTrajectory, reused unchanged at a
  1 s step (6 BPM/min linear slew, first-order terminal taper, progress
  gate, hard lead clamp). This is a reference slew rate for the pacing
  pulses, not a claim about how fast HR follows.
- Safety bounds, each enforced separately and logged when active:
    |pace - measured HR| <= PACE_MAX_LEAD_BPM
    PACE_MIN_BPM <= pace <= PACE_MAX_BPM
    pace never crosses the goal (goal is also clipped to the absolute range)
  If the bounds cannot all hold (HR outside the absolute range, or past the
  goal by more than the lead), pacing pauses.
- Degraded signal: an invalid HR update freezes the reference. Pulses
  continue at the frozen pace until PACE_HOLD_S after the last valid
  update, then stop (OFF). Pacing resumes after PACE_RESUME_VALID_UPDATES
  consecutive valid updates at which the bounds can hold. More than
  PACE_MAX_INVALID_S of invalid updates in total ends pacing (or, with
  invalid_window_s set, within any trailing window of that length).
- Goal updates (set_goal, e.g. from GrooveGen's phase schedule): the new
  goal is clipped exactly like the first one (HR0 +/- PACE_MAX_GOAL_OFFSET_BPM,
  absolute range) and a fresh ramp starts at the current reference, so the
  pace does not jump. "Never past the goal" is then judged from that origin;
  a goal within PACE_GOAL_HOLD_BAND_BPM of the origin (a hold) has no
  direction. All other bounds are unchanged.

Usage from the estimator loop:
    pacer = HapticPacer(goal_bpm=62.0)
    pacer.update_hr(t, stable_hr, hr_is_valid)   # every HR update (1 Hz)
    pacer.set_goal(66.0, t)                      # optional, any time
    pacer.on_peak(peak_t)                        # every confirmed PPG peak
    command = pacer.poll(t)                      # every sample; "HB", "OFF" or None
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "groovegen_pilot"))
from hr_trajectory import HRTrajectory  # noqa: E402

PACE_MAX_LEAD_BPM = 5.0
PACE_RAMP_BPM_PER_MIN = 6.0
PACE_TERMINAL_TAU_S = 60.0
PACE_MIN_BPM = 50.0
PACE_MAX_BPM = 100.0
PACE_MAX_GOAL_OFFSET_BPM = 6.0
PACE_INIT_VALID_UPDATES = 10
PACE_WARMUP_MAX_SPREAD_BPM = 4.0
PACE_HOLD_S = 3.0
PACE_RESUME_VALID_UPDATES = 3
PACE_MAX_INVALID_S = 30.0
PACE_MAX_SECONDS = 300.0
PACE_PEAK_ALIGN_TIMEOUT_S = 2.0
PACE_GOAL_HOLD_BAND_BPM = 0.5
PACE_MAX_UPDATE_DT_S = 2.0   # cap per-update invalid time so a host stall is not counted as signal loss

# States
WARMUP = "warmup"      # collecting HR0; no pulses
PACING = "pacing"      # valid HR; pulses at the bounded pace
HOLDING = "holding"    # HR invalid < PACE_HOLD_S; pulses at the frozen pace
PAUSED = "paused"      # no pulses; waiting for consecutive valid HR
DONE = "done"          # finished (max duration, signal lost); no pulses

LOG_FIELDS = [
    "time_s", "state", "hr_bpm", "hr_valid", "hr0_bpm", "goal_bpm",
    "goal_clipped", "ref_bpm", "pace_bpm", "lead_bound", "abs_bound",
    "ramp_frozen", "invalid_total_s", "reason", "origin_bpm",
]


class HapticPacer:
    def __init__(self, goal_bpm, max_seconds=PACE_MAX_SECONDS, max_lead_bpm=PACE_MAX_LEAD_BPM,
                 invalid_window_s=None):
        for name, value in (("goal_bpm", goal_bpm), ("max_seconds", max_seconds),
                            ("max_lead_bpm", max_lead_bpm)):
            if not (np.isfinite(value) and value > 0):
                raise ValueError(f"{name} must be finite and > 0, got {value!r}")
        if invalid_window_s is not None and not (np.isfinite(invalid_window_s)
                                                 and invalid_window_s > 0):
            raise ValueError(f"invalid_window_s must be finite and > 0, got {invalid_window_s!r}")
        # None: PACE_MAX_INVALID_S counts over the whole run (default).
        # Otherwise it counts over the trailing invalid_window_s seconds.
        self.invalid_window_s = None if invalid_window_s is None else float(invalid_window_s)
        self._invalid_log = []   # (t, dt) of invalid updates, windowed mode only
        self.goal_request_bpm = float(goal_bpm)
        self.max_seconds = float(max_seconds)
        self.max_lead_bpm = float(max_lead_bpm)

        self.state = WARMUP
        self.reason = ""
        self.warmup_hr = []
        self.hr0 = np.nan
        self.goal_bpm = np.nan
        self.goal_clipped = False
        self.origin_bpm = np.nan   # where the current ramp started (HR0 until set_goal)
        self.goal_updated = False
        self.traj = None
        self.ref_bpm = np.nan
        self.pace_bpm = np.nan
        self.lead_bound = False
        self.abs_bound = False
        self.ramp_frozen = False

        self.pace_start_t = np.nan
        self.next_pulse_t = None
        self.align_since_t = np.nan
        self.invalid_since_t = np.nan
        self.invalid_total_s = 0.0
        self.last_update_t = np.nan
        self.last_valid_t = np.nan
        self.resume_count = 0
        self.pending_off = False

    # ---- HR updates (1 Hz) ----

    def update_hr(self, t, hr_bpm, valid):
        """Feed one stable-HR update. Returns a log row (dict)."""
        dt = 0.0 if not np.isfinite(self.last_update_t) else t - self.last_update_t
        dt = min(dt, PACE_MAX_UPDATE_DT_S)
        self.last_update_t = t
        # Only trust hr_bpm when valid: the estimator returns the previous
        # smoothed HR unchanged on invalid windows.
        try:
            valid = bool(valid) and np.isfinite(float(hr_bpm))
        except (TypeError, ValueError):
            valid = False

        if self.state == WARMUP:
            if valid:
                self.warmup_hr.append(float(hr_bpm))
                self.warmup_hr = self.warmup_hr[-PACE_INIT_VALID_UPDATES:]
                if (len(self.warmup_hr) == PACE_INIT_VALID_UPDATES
                        and np.ptp(self.warmup_hr) <= PACE_WARMUP_MAX_SPREAD_BPM):
                    self._start(t)
            else:
                self.warmup_hr.clear()

        elif self.state in (PACING, HOLDING, PAUSED):
            if not valid:
                self.invalid_total_s += dt
                if self.invalid_window_s is not None:
                    self._invalid_log.append((t, dt))
                self.resume_count = 0
                if self.state == PACING:
                    self.state = HOLDING
                    self.invalid_since_t = self.last_valid_t
                    self.reason = "hr_invalid"
            elif self.state == PAUSED:
                if self._infeasible_reason(float(hr_bpm)) is not None:
                    self.resume_count = 0
                else:
                    self.resume_count += 1
                if self.resume_count >= PACE_RESUME_VALID_UPDATES:
                    self.state = PACING
                    self.reason = "resumed"
                    self.next_pulse_t = None
                    self.align_since_t = t
                    self._advance(t, hr_bpm)
            else:
                self.state = PACING
                self._advance(t, hr_bpm)

            self._check_limits(t)

        if valid:
            self.last_valid_t = t
        return self._row(t, hr_bpm, valid)

    def _start(self, t):
        self.hr0 = float(np.median(self.warmup_hr))
        self.goal_bpm = self._clip_goal(self.goal_request_bpm)
        self.goal_clipped = abs(self.goal_bpm - self.goal_request_bpm) > 1e-9

        self.traj = self._new_trajectory()
        self.ref_bpm = self.traj.initialize(self.hr0)
        self.origin_bpm = self.hr0
        self.pace_start_t = t
        self.align_since_t = t
        self.last_valid_t = t
        self.state = PACING
        self.reason = "started"
        self._bound(self.ref_bpm, self.hr0, t)

    def _clip_goal(self, goal_bpm):
        lo = self.hr0 - PACE_MAX_GOAL_OFFSET_BPM
        hi = self.hr0 + PACE_MAX_GOAL_OFFSET_BPM
        lo, hi = max(lo, PACE_MIN_BPM), min(hi, PACE_MAX_BPM)
        return float(np.clip(goal_bpm, lo, hi))

    def _new_trajectory(self):
        return HRTrajectory(
            goal_bpm=self.goal_bpm,
            segment_seconds=1.0,
            ramp_bpm_per_min=PACE_RAMP_BPM_PER_MIN,
            max_lead_bpm=self.max_lead_bpm,
            terminal_tau_s=PACE_TERMINAL_TAU_S,
        )

    def set_goal(self, goal_bpm, t):
        """Change the goal. Returns True if the ramp was restarted.

        WARMUP: replaces the request (clipped at start). DONE: ignored.
        Otherwise the goal is clipped as at start; if it differs from the
        current goal, a new ramp starts at the current reference (no pace
        jump) and the pace is re-bounded at the next HR update.
        """
        if not (np.isfinite(goal_bpm) and goal_bpm > 0):
            raise ValueError(f"goal_bpm must be finite and > 0, got {goal_bpm!r}")
        if self.state == DONE:
            return False
        if self.state == WARMUP:
            self.goal_request_bpm = float(goal_bpm)
            return False
        goal = self._clip_goal(goal_bpm)
        if abs(goal - self.goal_bpm) < 1e-9:
            return False
        self.goal_request_bpm = float(goal_bpm)
        self.goal_bpm = goal
        self.goal_clipped = abs(goal - self.goal_request_bpm) > 1e-9
        self.origin_bpm = float(self.ref_bpm)
        self.goal_updated = True
        self.traj = self._new_trajectory()
        self.ref_bpm = self.traj.initialize(self.origin_bpm)
        self.reason = "goal_changed"
        return True

    def _direction(self):
        """+1 pacing up, -1 down, 0 holding (no 'past the goal' limit)."""
        d = self.goal_bpm - self.origin_bpm
        if self.goal_updated and abs(d) < PACE_GOAL_HOLD_BAND_BPM:
            return 0
        return 1 if d >= 0 else -1

    def _advance(self, t, hr_bpm):
        rec = self.traj.step(float(hr_bpm))
        self.ref_bpm = rec["ref_bpm"]
        self.ramp_frozen = bool(rec["ramp_frozen"])
        self._bound(self.ref_bpm, float(hr_bpm), t)

    def _bound(self, ref_bpm, hr_bpm, t):
        """Apply the safety bounds independently of HRTrajectory's own clamp."""
        pace = min(max(ref_bpm, hr_bpm - self.max_lead_bpm), hr_bpm + self.max_lead_bpm)
        self.lead_bound = abs(pace - ref_bpm) > 1e-9

        clipped = min(max(pace, PACE_MIN_BPM), PACE_MAX_BPM)
        self.abs_bound = abs(clipped - pace) > 1e-9
        pace = clipped

        # Never pace past the goal in the direction of travel from the origin.
        direction = self._direction()
        if direction > 0:
            pace = min(pace, self.goal_bpm)
        elif direction < 0:
            pace = max(pace, self.goal_bpm)

        reason = self._infeasible_reason(hr_bpm)
        if reason is not None:
            self._pause(t, reason)
            return
        self.pace_bpm = float(pace)

    def _infeasible_reason(self, hr_bpm):
        """None if some pace satisfies every bound at this HR, else why not."""
        lo = max(hr_bpm - self.max_lead_bpm, PACE_MIN_BPM)
        hi = min(hr_bpm + self.max_lead_bpm, PACE_MAX_BPM)
        if lo > hi + 1e-9:
            return "hr_out_of_range"
        direction = self._direction()
        if direction > 0:
            hi = min(hi, self.goal_bpm)
        elif direction < 0:
            lo = max(lo, self.goal_bpm)
        if lo > hi + 1e-9:
            return "hr_past_goal"
        return None

    # ---- peaks and per-sample polling ----

    def on_peak(self, peak_t):
        """Align the first pulse after (re)starting to a confirmed PPG peak."""
        if self.state == PACING and self.next_pulse_t is None and np.isfinite(self.pace_bpm):
            self.next_pulse_t = peak_t + 60.0 / self.pace_bpm

    def poll(self, t):
        """Call on every sample. Returns "HB", "OFF", or None."""
        if self.state == HOLDING and t - self.invalid_since_t > PACE_HOLD_S:
            self._pause(t, "hr_invalid_timeout")
        self._check_limits(t)

        if self.pending_off:
            self.pending_off = False
            return "OFF"

        if self.state not in (PACING, HOLDING) or not np.isfinite(self.pace_bpm):
            return None

        if self.next_pulse_t is None:
            # No peak arrived to align to; start the schedule from now.
            if t - self.align_since_t < PACE_PEAK_ALIGN_TIMEOUT_S:
                return None
            self.next_pulse_t = t

        if t < self.next_pulse_t:
            return None

        ibi = 60.0 / self.pace_bpm
        self.next_pulse_t += ibi
        if self.next_pulse_t <= t:
            # Fell behind (host stall); never burst to catch up.
            self.next_pulse_t = t + ibi
        return "HB"

    # ---- lifecycle ----

    def _pause(self, t, reason):
        if self.state in (PACING, HOLDING):
            self.pending_off = True
        self.state = PAUSED
        self.reason = reason
        self.resume_count = 0
        self.next_pulse_t = None

    def _check_limits(self, t):
        if self.state in (WARMUP, DONE):
            return
        if self._invalid_s(t) > PACE_MAX_INVALID_S:
            self.stop("signal_lost")
        elif t - self.pace_start_t > self.max_seconds:
            self.stop("max_duration")

    def _invalid_s(self, t):
        if self.invalid_window_s is None:
            return self.invalid_total_s
        cutoff = t - self.invalid_window_s
        self._invalid_log = [(ti, dt) for ti, dt in self._invalid_log if ti > cutoff]
        return sum(dt for _, dt in self._invalid_log)

    def stop(self, reason="stopped"):
        if self.state in (PACING, HOLDING):
            self.pending_off = True
        self.state = DONE
        self.reason = reason
        self.next_pulse_t = None

    def _row(self, t, hr_bpm, valid):
        return {
            "time_s": t,
            "state": self.state,
            "hr_bpm": hr_bpm,
            "hr_valid": int(valid),
            "hr0_bpm": self.hr0,
            "goal_bpm": self.goal_bpm,
            "goal_clipped": int(self.goal_clipped),
            "ref_bpm": self.ref_bpm,
            "pace_bpm": self.pace_bpm,
            "lead_bound": int(self.lead_bound),
            "abs_bound": int(self.abs_bound),
            "ramp_frozen": int(self.ramp_frozen),
            "invalid_total_s": self.invalid_total_s,
            "reason": self.reason,
            "origin_bpm": self.origin_bpm,
        }
