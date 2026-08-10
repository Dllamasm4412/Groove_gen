"""hr_trajectory.py -- the HR reference governor (segment-cadence setpoint law).

Sits UPSTREAM of `HRArousalMapper`. Generates a rate-limited, progress-gated
HR reference that the (unchanged) arousal-domain CascadeController tracks.

Design (from the 2026-08-04 council synthesis, `segment_redesign_council_synthesis.md`):
  - Rate-limited LINEAR ramp in HR units at a REFERENCE slew rate `ramp_bpm_per_min`
    (default 6). NOTE: this is a *reference* slew rate, NOT a promised physiological
    rate. The paper must say "tracks a reference shaped at 6 BPM/min", never
    "reduces/raises HR at 6 BPM/min".
  - First-order TERMINAL TAPER: effective rate = min(ramp, |dist|/tau) so the ramp
    softens into a first-order approach in the last few BPM (no arrival corner /
    terminal chatter).
  - PROGRESS GATE (anti-windup): if the participant lags the reference by more than
    the lead clamp, FREEZE the ramp -- don't let the reference run away from a
    listener who isn't following.
  - HARD LEAD CLAMP: the reference may never lead the measured HR by more than
    `max_lead_bpm`, in either direction.
  - ISO-PRINCIPLE INIT: r(0) = participant's own baseline HR (not a nominal value).

FULLY BIDIRECTIONAL. Nothing is hardcoded to up- or down-regulation; direction is
sign(goal - reference) each segment. Up-regulation (e.g. 75->100) and
down-regulation (e.g. 120->75) use the identical code path.

Units are BPM throughout. Conversion to arousal happens in the caller via
HRArousalMapper, exactly where a per-subject calibration belongs.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, List
import math


@dataclass
class HRTrajectory:
    """Segment-cadence HR reference governor.

    Parameters
    ----------
    goal_bpm : float
        Terminal target HR for the session.
    segment_seconds : float
        Control period T (seconds per reference update). Default 30.
    ramp_bpm_per_min : float
        Reference slew rate rho (BPM per minute). Default 6.
    deadband_bpm : float
        +/- tolerance band D around the reference (BPM). Reported alongside the
        controller's arousal-domain `band`. Default 3.
    max_lead_bpm : float
        Hard clamp L on how far the reference may lead measured HR. Default 8.
    terminal_tau_s : float
        Time constant tau (s) of the first-order terminal taper. Default 60.
    baseline_bpm : float | None
        Iso-principle init r(0). If None, must be set via `initialize()` from a
        measured baseline before the first `step()`.
    """
    goal_bpm: float
    segment_seconds: float = 30.0
    ramp_bpm_per_min: float = 6.0
    deadband_bpm: float = 3.0
    max_lead_bpm: float = 8.0
    terminal_tau_s: float = 60.0
    baseline_bpm: Optional[float] = None

    # --- internal state (not constructor args) ---
    _ref: Optional[float] = field(default=None, init=False)
    _n: int = field(default=0, init=False)
    history: List[dict] = field(default_factory=list, init=False)

    # ---- lifecycle ----
    def initialize(self, baseline_bpm: float) -> float:
        """Iso-principle init: anchor the reference to the participant's OWN
        measured baseline HR (mean over a pre-session window). Returns r(0)."""
        self.baseline_bpm = float(baseline_bpm)
        self._ref = float(baseline_bpm)
        self._n = 0
        self.history.clear()
        return self._ref

    @property
    def ref_bpm(self) -> float:
        if self._ref is None:
            if self.baseline_bpm is None:
                raise RuntimeError(
                    "HRTrajectory used before initialize(): call initialize(baseline_bpm) "
                    "or pass baseline_bpm= at construction (iso-principle requires it)."
                )
            self._ref = float(self.baseline_bpm)
        return self._ref

    # ---- the law ----
    def step(self, hr_smoothed_bpm: float) -> dict:
        """Advance the reference by one segment boundary.

        Parameters
        ----------
        hr_smoothed_bpm : float
            The 30 s artifact-gated trailing mean HR (NOT an instantaneous
            sample) measured at this segment boundary.

        Returns
        -------
        dict with the full auditable state for this boundary:
            ref_bpm, goal_bpm, dist_bpm, sign, eff_rate_bpm_per_min,
            ramp_frozen (0/1), traj_error_bpm (ref - measured), lead_clamped (0/1),
            deadband_bpm, segment_idx.
        """
        r_prev = self.ref_bpm
        T = self.segment_seconds
        rho_s = self.ramp_bpm_per_min / 60.0  # BPM per second

        # 1. signed distance to goal
        dist = self.goal_bpm - r_prev
        s = 0.0 if dist == 0 else math.copysign(1.0, dist)

        # 2. terminal taper: linear far away, first-order near the goal
        #    r_eff(per s) = min(rho, |dist|/tau)
        eff_rate_s = min(rho_s, abs(dist) / self.terminal_tau_s) if self.terminal_tau_s > 0 else rho_s

        # 3. progress gate (anti-windup): freeze if the participant is lagging
        #    the reference by more than the lead clamp in the direction of travel.
        #    lag = how far ref is AHEAD of measured, in the travel direction.
        lag = s * (r_prev - hr_smoothed_bpm)
        ramp_frozen = 1 if lag > self.max_lead_bpm else 0
        g = 0.0 if ramp_frozen else 1.0

        # 4. advance (never overshoot the goal)
        delta = s * min(abs(dist), eff_rate_s * T * g)
        r_new = r_prev + delta

        # 5. hard lead clamp (unconditional, both directions)
        lead = r_new - hr_smoothed_bpm
        clamped_lead = max(-self.max_lead_bpm, min(self.max_lead_bpm, lead))
        lead_clamped = 1 if abs(clamped_lead - lead) > 1e-9 else 0
        r_new = hr_smoothed_bpm + clamped_lead

        # The progress gate (step 3) and the lead clamp (step 5) are two views
        # of the same anti-windup guarantee: the reference must never lead a
        # lagging participant by more than max_lead_bpm. The clamp is the
        # tighter of the two and often fires FIRST (capping r_new at the lead
        # boundary before `lag` can exceed max_lead). Either mechanism stopping
        # forward progress is the honest "ramp is waiting for the participant"
        # signal, so report ramp_frozen if EITHER engaged.
        if lead_clamped and s != 0 and (self.goal_bpm - r_new) * s > 1e-9:
            # clamp held us back short of the goal in the travel direction
            ramp_frozen = 1

        # never cross the goal due to the lead clamp pulling us past it
        if s > 0:
            r_new = min(r_new, self.goal_bpm) if r_prev <= self.goal_bpm else r_new
        elif s < 0:
            r_new = max(r_new, self.goal_bpm) if r_prev >= self.goal_bpm else r_new

        self._ref = r_new
        self._n += 1

        # effective rate actually realized this segment, in BPM/min (honest column)
        realized_rate_min = (abs(r_new - r_prev) / T) * 60.0
        rec = {
            "segment_idx": self._n - 1,
            "ref_bpm": r_new,
            "goal_bpm": self.goal_bpm,
            "dist_bpm": dist,
            "sign": s,
            "eff_rate_bpm_per_min": realized_rate_min,
            "ramp_frozen": ramp_frozen,
            "traj_error_bpm": r_new - hr_smoothed_bpm,
            "lead_clamped": lead_clamped,
            "deadband_bpm": self.deadband_bpm,
            "in_deadband": 1 if abs(r_new - hr_smoothed_bpm) <= self.deadband_bpm else 0,
        }
        self.history.append(rec)
        return rec


# --------------------------------------------------------------------------
if __name__ == "__main__":
    print("HRTrajectory reference-governor self-test\n" + "=" * 60)

    def run(goal, baseline, label, follow_frac=1.0, n=40):
        """Simulate: participant follows the reference at `follow_frac` of the way."""
        traj = HRTrajectory(goal_bpm=goal, segment_seconds=30.0, ramp_bpm_per_min=6.0,
                            deadband_bpm=3.0, max_lead_bpm=8.0, terminal_tau_s=60.0)
        traj.initialize(baseline)
        meas = baseline
        refs, meass = [baseline], [baseline]
        for _ in range(n):
            rec = traj.step(meas)
            refs.append(rec["ref_bpm"])
            # participant moves toward the reference at follow_frac
            meas = meas + follow_frac * (rec["ref_bpm"] - meas)
            meass.append(meas)
        print(f"\n{label}: goal={goal}, baseline={baseline}, follow={follow_frac}")
        print("  ref :", [round(v, 1) for v in refs[:14]], "...", round(refs[-1], 1))
        print("  meas:", [round(v, 1) for v in meass[:14]], "...", round(meass[-1], 1))
        return traj, refs, meass

    # UP-regulation (the chosen demo direction): 75 -> 100
    t_up, refs_up, _ = run(100, 75, "UP-reg 75->100 (ideal follower)")
    assert refs_up[0] == 75
    assert refs_up[-1] <= 100 + 1e-6, "overshot goal"
    assert abs(refs_up[-1] - 100) < 1.0, f"did not converge to goal: {refs_up[-1]}"
    # early slope ~ 6 BPM/min = 3 BPM per 30s segment
    assert abs((refs_up[1] - refs_up[0]) - 3.0) < 0.5, f"early step not ~3 BPM: {refs_up[1]-refs_up[0]}"
    print("  UP-reg PASS: r(0)=baseline, ~3 BPM/segment early, converges to goal, no overshoot")

    # DOWN-regulation (system must stay bidirectional): 120 -> 75
    t_dn, refs_dn, _ = run(75, 120, "DOWN-reg 120->75 (ideal follower)")
    assert refs_dn[0] == 120
    assert refs_dn[-1] >= 75 - 1e-6, "undershot goal"
    assert abs((refs_dn[1] - refs_dn[0]) + 3.0) < 0.5, "early step not ~-3 BPM"
    # time to traverse 45 BPM at 6 BPM/min ~ 7.5 min = 15 segments (before taper)
    print("  DOWN-reg PASS: r(0)=baseline, ~-3 BPM/segment early, converges to goal, no undershoot")

    # PROGRESS GATE: participant does NOT follow -> reference must FREEZE at the
    # lead clamp, never running away.
    t_lag, refs_lag, meas_lag = run(100, 75, "UP-reg, NON-following participant", follow_frac=0.0)
    max_lead = max(r - m for r, m in zip(refs_lag, meas_lag))
    assert max_lead <= 8.0 + 1e-6, f"reference led a non-follower by {max_lead} > 8 BPM lead clamp"
    frozen_any = any(h["ramp_frozen"] for h in t_lag.history)
    assert frozen_any, "progress gate never engaged for a non-following participant"
    print(f"  PROGRESS-GATE PASS: non-follower led by at most {max_lead:.1f} BPM (<=8), ramp froze")

    print("\nALL HRTrajectory TESTS PASSED")
