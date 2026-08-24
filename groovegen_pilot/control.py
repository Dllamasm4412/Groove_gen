"""
GrooveGen closed-loop controller (M0.5 Step 5.5).

Implements the council-synthesis intersection design:

    1. Reference governor  -- shrinks HR_target to reachable set given
                              per-subject gain estimate g_hat. Refuses
                              off-scale requests structurally.
    2. Ladder MPC (H=3)    -- enumerative planning over <=5 neighbor cells;
                              no solver, just a for-loop.
    3. Arousal feedforward -- Gemini's clean form:
                                  e = (r - HR) - K_subj * (A - A_base)
    4. Rate limits         -- tier <= 1 rung/segment; NOT relaxed for large
                              error (Opus's Watanabe-based inverted rule).
    5. Online gain RLS     -- estimates K per subject; feeds governor.

The controller consumes:
    - hr_bpm         (current HR reading)
    - arousal_1_9    (subjective, once per segment; None if not polled)
    - current_rung   (last commanded ladder rung)
    - HR_target      (raw setpoint from researcher)
    - HR_base        (session baseline)

and returns a ControlDecision naming the next rung, along with diagnostic
fields (governed_r, is_unreachable, g_hat, saturation_state).

Public API
----------
    ControllerConfig       Configuration dataclass
    ControlDecision        NamedTuple returned each step
    LadderMPC              The controller. .step(...) each segment.

Invariants
----------
    - Next rung is within +/- ControllerConfig.max_step_per_segment of current
    - `is_unreachable` is True iff governed_r != raw HR_target
    - g_hat_bpm is >= 0 (we only estimate magnitude of authority; sign of
      response is a separate SubjectResponsivity flag not implemented here)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import NamedTuple, Optional

from ladder import Ladder

try:
    # Optional import so control.py stays usable in environments without
    # librosa (which user_descriptor pulls transitively via music_features).
    from user_descriptor import UserDescriptor  # noqa: F401
except Exception:  # pragma: no cover - defensive
    UserDescriptor = None  # type: ignore


# =============================================================================
# Config & Types
# =============================================================================

@dataclass
class ControllerConfig:
    horizon: int = 3                    # MPC horizon in segments
    max_step_per_segment: int = 1       # rungs; NOT relaxed for large error (Opus)
    dead_zone_bpm: float = 1.5          # +/- this from target => hold
    w_error: float = 1.0                # bpm^2 weight
    w_churn: float = 0.15               # (delta-rung)^2 weight (per rung); low so
                                        # single-rung moves are cheap relative to bpm err
    w_arousal: float = 0.20             # unused stub for future cascade
    # Reference governor
    reach_optimism: float = 1.3         # multiplier on g_hat when ID uncertain
    reach_floor_bpm: float = 2.0        # minimum reachable radius
    unreach_ratio: float = 1.6          # request > ratio*reach => log unreachable
    # Arousal handling. Two modes:
    #   'hr_primary' (default, backward compat): HR is the tracked signal.
    #     Arousal (if present) is a feedforward shifting effective error by
    #     K_subj_bpm_per_pt * (A - arousal_baseline).
    #   'arousal_primary' (new): arousal IS the tracked signal.
    #     Caller passes arousal_target as hr_target and arousal_base as hr_base.
    #     HR is still logged but not used for error.
    arousal_mode: str = 'hr_primary'
    K_subj_bpm_per_pt: float = 0.5      # bpm equivalent per 1-point arousal
    arousal_baseline: float = 5.0       # neutral point on 1..9 scale
    # RLS for gain identification
    rls_forget: float = 0.97
    rls_g_prior_bpm: float = 2.5        # prior on |K|; matches Opus 0.03*HR_base @ ~80
    rls_g_max_bpm: float = 12.0         # hard cap; anything above is implausible
    # Plant priors used inside MPC prediction
    plant_tau_s: float = 60.0
    plant_dt_s: float = 20.0
    plant_delay_segments: int = 1
    # -------------------------------------------------------------------
    # M1 personalization (A+B, weak tiebreak).
    # user_descriptor is the 6-float payload from user_descriptor.py.
    # If set, MPC candidates whose cost J is within tiebreak_epsilon of
    # the best candidate are re-ranked by user_descriptor.genre_weights.
    # Default None -> preserves pre-M1 behavior; fielded N=400 study runs
    # with user_descriptor=None per DEVIATIONS.md v2.3.
    # -------------------------------------------------------------------
    user_descriptor: Optional[object] = None  # UserDescriptor or None
    tiebreak_epsilon: float = 0.15  # fraction of best_J that counts as a tie
    tiebreak_epsilon_abs: float = 0.05  # absolute floor for near-zero best_J


class ControlDecision(NamedTuple):
    next_rung: int
    next_genre: str
    next_tier: int
    governed_r: float          # setpoint after governor
    raw_r: float               # setpoint before governor
    is_unreachable: bool
    g_hat_bpm: float
    saturation_state: str      # 'ok' | 'sat_hi' | 'sat_lo'
    dead_zone_active: bool
    predicted_hr_H: float      # HR predicted at horizon end
    effective_error_bpm: float # error used by controller (post arousal FF)


# =============================================================================
# Controller
# =============================================================================


class LadderMPC:
    """
    Closed-loop controller composing:
        reference governor -> ladder MPC -> RLS gain estimator.

    Usage
    -----
        ctrl = LadderMPC(ladder, ControllerConfig())
        for k in range(N):
            decision = ctrl.step(hr_bpm=hr_k,
                                  hr_target=r_raw,
                                  hr_base=base,
                                  current_rung=current,
                                  arousal_1_9=arousal_k)
            # ... apply decision.next_rung to composer/renderer
            # then next segment:
            #   pass the new hr_bpm to step()
    """

    def __init__(self, ladder: Ladder, config: Optional[ControllerConfig] = None):
        self.ladder = ladder
        self.cfg = config or ControllerConfig()
        # RLS state for gain identification
        # We estimate G in HR_delta_k+1 = G * u_effective  (small-signal approx)
        self._g_hat = self.cfg.rls_g_prior_bpm
        self._P = (self.cfg.rls_g_prior_bpm ** 2)
        # History for RLS update
        self._prev_hr: Optional[float] = None
        self._prev_u: Optional[float] = None
        self._prev_hr_base: Optional[float] = None
        # Saturation counter (structural anti-windup)
        self._sat_count = 0

    # -----------------------------------------------------------------
    # Reference governor
    # -----------------------------------------------------------------

    def _governor(self, raw_r: float, hr_base: float) -> tuple[float, bool]:
        """Shrink target to the identified reachable set. Returns (r, unreachable_flag)."""
        reach = max(self.cfg.reach_floor_bpm,
                    self.cfg.reach_optimism * self._g_hat)
        delta = raw_r - hr_base
        governed_r = hr_base + max(-reach, min(reach, delta))
        unreachable = abs(delta) > self.cfg.unreach_ratio * reach
        return governed_r, unreachable

    # -----------------------------------------------------------------
    # RLS gain update
    # -----------------------------------------------------------------

    def _update_gain(self, hr_now: float, hr_base: float) -> None:
        """
        Recursive Least Squares on |HR_deviation - baseline_drift|.
        Uses the previous u command and previous HR to update g_hat.
        """
        if self._prev_hr is None or self._prev_u is None:
            return
        # Small-signal observation: y_k = HR_now - hr_base ~= G * u_prev
        # (ignoring dynamics; RLS + forgetting handles the mismatch)
        y = hr_now - hr_base
        phi = self._prev_u
        if phi < 0.05:  # not enough excitation
            return
        lam = self.cfg.rls_forget
        K_rls = self._P * phi / (lam + phi * self._P * phi)
        y_hat = self._g_hat * phi
        self._g_hat = self._g_hat + K_rls * (y - y_hat)
        # Clamp to plausible range
        self._g_hat = max(0.0, min(self.cfg.rls_g_max_bpm, self._g_hat))
        self._P = (self._P - K_rls * phi * self._P) / lam

    # -----------------------------------------------------------------
    # Plant prediction (used inside MPC)
    # -----------------------------------------------------------------

    def _predict_hr(self, hr_now: float, u_seq: list[float],
                    hr_base: float) -> float:
        """
        Roll forward the FOPDT plant assuming K = g_hat, tau = cfg.plant_tau_s,
        delay = cfg.plant_delay_segments. Returns HR at end of horizon.
        """
        import math
        alpha = math.exp(-self.cfg.plant_dt_s / self.cfg.plant_tau_s)
        # Delay buffer initialized with the previously-applied u
        d = self.cfg.plant_delay_segments
        buf = [self._prev_u if self._prev_u is not None else 0.0] * d
        hr = hr_now
        for u in u_seq:
            u_eff = buf[0]
            buf = buf[1:] + [u]
            target = hr_base + self._g_hat * u_eff
            hr = alpha * hr + (1.0 - alpha) * target
        return hr

    # -----------------------------------------------------------------
    # Main step
    # -----------------------------------------------------------------

    def step(self,
             hr_bpm: float,
             hr_target: float,
             hr_base: float,
             current_rung: int,
             arousal_1_9: Optional[float] = None) -> ControlDecision:
        # 1. Update RLS gain estimate from the previous action's outcome
        self._update_gain(hr_bpm, hr_base)

        # 2. Reference governor
        governed_r, unreachable = self._governor(hr_target, hr_base)

        # 3. Compute raw + effective error. Two modes:
        if self.cfg.arousal_mode == 'arousal_primary':
            # Arousal is the tracked signal. hr_target has been passed as
            # the arousal target (1..9), hr_base as arousal baseline.
            # If no arousal report, hold (return zero error).
            if arousal_1_9 is None:
                raw_err = 0.0
                effective_err = 0.0
            else:
                raw_err = governed_r - float(arousal_1_9)
                effective_err = raw_err
        else:
            # hr_primary (default): Gemini's form
            #    e_effective = (r - hr) - K_subj * (A - A_base)
            raw_err = governed_r - hr_bpm
            if arousal_1_9 is not None:
                arousal_dev = float(arousal_1_9) - self.cfg.arousal_baseline
                effective_err = raw_err - self.cfg.K_subj_bpm_per_pt * arousal_dev
            else:
                effective_err = raw_err

        # 4. Dead zone: within +/- dead_zone_bpm, hold current
        dead_zone_active = abs(effective_err) <= self.cfg.dead_zone_bpm
        if dead_zone_active:
            chosen_rung = current_rung
        else:
            # 5. Enumerate legal neighbors (rate-limited)
            step = self.cfg.max_step_per_segment
            n_cells = len(self.ladder.cells)
            candidates = list(range(max(0, current_rung - step),
                                     min(n_cells - 1, current_rung + step) + 1))
            # 6. Evaluate each candidate over horizon H
            #    (constant-u prediction; the first action dominates)
            best_rung = current_rung
            best_J = float('inf')
            current_u = self.ladder.by_rung[current_rung].u
            all_costs: list[tuple[int, float]] = []
            for c in candidates:
                u_c = self.ladder.by_rung[c].u
                # Rollout: apply u_c for horizon H segments
                u_seq = [u_c] * self.cfg.horizon
                hr_H = self._predict_hr(hr_bpm, u_seq, hr_base)
                err_H = governed_r - hr_H
                # Also compute STEADY-STATE HR under u_c so the objective
                # sees the ultimate target, not just the delayed near-horizon
                # value. Prevents the fine ladder + small g_hat degenerate case.
                hr_ss = hr_base + self._g_hat * u_c
                err_ss = governed_r - hr_ss
                # Churn cost is quadratic in RUNG delta (not energy delta), so
                # it is comparable across genres regardless of rung spacing.
                J = (self.cfg.w_error * (0.5 * err_H * err_H + 0.5 * err_ss * err_ss)
                     + self.cfg.w_churn * (c - current_rung) ** 2)
                all_costs.append((c, J))
                if J < best_J:
                    best_J = J
                    best_rung = c

            # ------ M1 personalization: weak genre tiebreak ------
            # Among candidates within tiebreak_epsilon*|best_J| of the best,
            # prefer the candidate whose family has the highest user weight.
            # No-op when user_descriptor is None (default).
            desc = self.cfg.user_descriptor
            if desc is not None and all_costs:
                # Tolerance band around best_J. Uses max(relative, absolute)
                # so tiebreak still fires when best_J is near zero (e.g.
                # controller sitting near target, all candidates score alike).
                tol = max(
                    self.cfg.tiebreak_epsilon * abs(best_J),
                    self.cfg.tiebreak_epsilon_abs,
                )
                ties = [(c, J) for (c, J) in all_costs if (J - best_J) <= tol]
                if len(ties) > 1:
                    # Pick by max genre weight (deterministic fallback: rung idx)
                    def _score(item):
                        c, _J = item
                        genre = self.ladder.by_rung[c].genre
                        w = float(getattr(desc, 'genre_weights', {}).get(genre, 0.0))
                        # Sort key: (-weight, rung index) so higher weight wins,
                        # ties broken toward lower rung for reproducibility.
                        return (-w, c)
                    ties.sort(key=_score)
                    best_rung = ties[0][0]
            chosen_rung = best_rung

        # 7. Saturation bookkeeping (anti-windup: freeze RLS on next call)
        n_cells = len(self.ladder.cells)
        if chosen_rung == 0 and effective_err < 0:
            sat_state = 'sat_lo'
            self._sat_count += 1
        elif chosen_rung == n_cells - 1 and effective_err > 0:
            sat_state = 'sat_hi'
            self._sat_count += 1
        else:
            sat_state = 'ok'
            self._sat_count = 0

        # 8. Snapshot decision + record for next-step RLS
        cell = self.ladder.by_rung[chosen_rung]
        u_next = cell.u
        # Predict HR at horizon end under the chosen action
        pred_H = self._predict_hr(hr_bpm, [u_next] * self.cfg.horizon, hr_base)

        # Store for next step's RLS update
        self._prev_hr = hr_bpm
        self._prev_u = u_next
        self._prev_hr_base = hr_base

        return ControlDecision(
            next_rung=chosen_rung,
            next_genre=cell.genre,
            next_tier=cell.tier,
            governed_r=governed_r,
            raw_r=hr_target,
            is_unreachable=unreachable,
            g_hat_bpm=self._g_hat,
            saturation_state=sat_state,
            dead_zone_active=dead_zone_active,
            predicted_hr_H=pred_H,
            effective_error_bpm=effective_err,
        )


if __name__ == '__main__':
    import random
    from ladder import build_ladder
    from plant_model import Subject, FOPDTPlant

    L = build_ladder()
    ctrl = LadderMPC(L, ControllerConfig())

    # Simulate a typical subject with baseline 75, K=4, target = baseline + 3
    subj = Subject(baseline=75.0, K=4.0, tau=60.0, d=1, u_sat=0.8, kind='typical')
    plant = FOPDTPlant(subj, dt=20.0, noise_sigma=0.5, rng=random.Random(0))

    current_rung = 0
    hr = subj.baseline
    r_raw = 78.0
    print(f'Target: {r_raw} bpm, subject baseline: {subj.baseline}, K: {subj.K}')
    print(f'{"step":>4} {"HR":>7} {"rung":>4} {"genre":>6} {"tier":>4} '
          f'{"gov_r":>7} {"g_hat":>6} {"err":>6}')
    for k in range(20):
        dec = ctrl.step(hr, hr_target=r_raw, hr_base=subj.baseline,
                         current_rung=current_rung)
        current_rung = dec.next_rung
        u = L.by_rung[current_rung].u
        hr = plant.step(u)
        print(f'{k:>4} {hr:>7.2f} {current_rung:>4} '
              f'{dec.next_genre:>6} {dec.next_tier:>4} '
              f'{dec.governed_r:>7.2f} {dec.g_hat_bpm:>6.2f} '
              f'{dec.effective_error_bpm:>+6.2f}')

    # Now test the UNREACHABLE case: target 120, K=4 -> should refuse
    print('\n--- Unreachable target test ---')
    ctrl2 = LadderMPC(L, ControllerConfig())
    plant.reset()
    hr = subj.baseline
    r_raw = 120.0
    for k in range(5):
        dec = ctrl2.step(hr, hr_target=r_raw, hr_base=subj.baseline,
                          current_rung=0)
        u = L.by_rung[dec.next_rung].u
        hr = plant.step(u)
    print(f'Requested {r_raw}, governed {dec.governed_r:.2f}, '
          f'unreachable={dec.is_unreachable}')
    assert dec.is_unreachable, 'should have refused 120 bpm target'
    assert dec.governed_r < 90, f'governed_r should be << 120, got {dec.governed_r}'
    print('PASS: controller refused unreachable target')
