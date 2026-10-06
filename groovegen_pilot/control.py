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

from dataclasses import dataclass
from typing import NamedTuple

from ladder import Cell, Ladder

try:
    # Optional import so control.py stays usable in environments without
    # librosa (which user_descriptor pulls transitively via music_features).
    from user_descriptor import UserDescriptor
except Exception:  # pragma: no cover - defensive
    UserDescriptor = None  # type: ignore


# =============================================================================
# Config & Types
# =============================================================================


@dataclass
class ControllerConfig:
    horizon: int = 3  # MPC horizon in segments
    max_step_per_segment: int = 1  # rungs; NOT relaxed for large error (Opus)
    dead_zone_bpm: float = 1.5  # +/- this from target => hold
    w_error: float = 1.0  # bpm^2 weight
    w_churn: float = 0.01  # experiential pilot: cheap movement so ladder walks
    # single-rung moves are cheap relative to bpm err
    w_arousal: float = 0.20  # unused stub for future cascade
    # Reference governor
    reach_optimism: float = 1.3  # multiplier on g_hat when ID uncertain
    reach_floor_bpm: float = 2.0  # minimum reachable radius
    unreach_ratio: float = 1.6  # request > ratio*reach => log unreachable
    # Arousal handling. Two modes:
    #   'hr_primary' (default, backward compat): HR is the tracked signal.
    #     Arousal (if present) is a feedforward shifting effective error by
    #     K_subj_bpm_per_pt * (A - arousal_baseline).
    #   'arousal_primary' (new): arousal IS the tracked signal.
    #     Caller passes arousal_target as hr_target and arousal_base as hr_base.
    #     HR is still logged but not used for error.
    arousal_mode: str = "hr_primary"
    K_subj_bpm_per_pt: float = 0.5  # bpm equivalent per 1-point arousal
    arousal_baseline: float = 5.0  # neutral point on 1..9 scale
    # RLS for gain identification
    rls_forget: float = 0.97
    rls_g_prior_bpm: float = 2.5  # prior on |K|; matches Opus 0.03*HR_base @ ~80
    rls_g_max_bpm: float = 12.0  # hard cap; anything above is implausible
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
    user_descriptor: object | None = None  # UserDescriptor or None
    tiebreak_epsilon: float = 0.05  # fraction of best_J that counts as a tie (tightened v2.5 — was 0.15, made too many candidates tie)
    tiebreak_epsilon_abs: float = 0.05  # absolute floor for near-zero best_J
    # Energy-jump cap: max |u| change per segment, applied to MPC candidates
    # and to rotation/relaxation picks. None = rung limit only. The largest
    # adjacent-rung gap is 0.101 (calm2 -> lofi1 on the 29-cell tier-capped
    # ladder), so any cap >= 0.11 still allows every 1-rung move.
    max_du_per_segment: float | None = None
    # -------------------------------------------------------------------
    # Saturation handling (engineering listening modes, default OFF).
    # "Stuck" = error to the RAW target beyond the dead zone, but the MPC
    # does not move toward it: at a ladder end, mid-ladder when g_hat has
    # collapsed, or when the governor has shrunk the target to current HR.
    # Counted per segment (rotation segments keep counting while the error
    # keeps its sign, unless the MPC asks for a cell beyond the rotation
    # band); stuck_release_segments dead-zone segments clear it.
    #   saturation_rotation: after rotation_after_segments stuck, rotate
    #     through genres with cells within rotation_band_u of the stall
    #     cell's energy (least-recently-played genre, its cell furthest in
    #     the push direction). With rotation_no_repeat > 0 a pick skips the
    #     cells played in the last rotation_no_repeat segments while any
    #     other band cell remains, and within a genre takes its least-
    #     recently-played band cell (furthest in the push direction among
    #     equals): a band holding one cell of one genre no longer alternates
    #     that cell every other segment (v2c live run 2026-10-05: latin2 /
    #     rnb3 x3 each). 0 = the earlier picks.
    #   target_relaxation: after relax_after_segments stuck, set the target
    #     aside: step away from it at max_step_per_segment until u has moved
    #     relax_depth_u from the stall cell, then re-climb to the stall cell
    #     (following the MPC if it wants further) and resume normal MPC.
    # Segments chosen by these modes are not the controller's HR response;
    # they are flagged in ControlDecision.control_mode ('rotate'/'relax').
    # -------------------------------------------------------------------
    saturation_rotation: bool = False
    rotation_after_segments: int = 3
    rotation_band_u: float = 0.20
    rotation_no_repeat: int = 2
    target_relaxation: bool = False
    relax_after_segments: int = 8
    relax_depth_u: float = 0.35
    stuck_release_segments: int = 2
    # Relaxation while pushing DOWN means playing more energetic music during
    # a lowering phase, so by default it only runs for upward pushes.
    relax_on_down_push: bool = False


class ControlDecision(NamedTuple):
    next_rung: int
    next_genre: str
    next_tier: int
    governed_r: float  # setpoint after governor
    raw_r: float  # setpoint before governor
    is_unreachable: bool
    g_hat_bpm: float
    saturation_state: str  # 'ok' | 'sat_hi' | 'sat_lo'
    dead_zone_active: bool
    predicted_hr_H: float  # HR predicted at horizon end
    effective_error_bpm: float  # error used by controller (post arousal FF)
    control_mode: str = "mpc"  # 'mpc' | 'rotate' | 'relax' (saturation modes) | 'stale_hold'
    mpc_rung: int = -1  # rung the MPC chose before any saturation override


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

    def __init__(self, ladder: Ladder, config: ControllerConfig | None = None):
        self.ladder = ladder
        self.cfg = config or ControllerConfig()
        # RLS state for gain identification
        # We estimate G in HR_delta_k+1 = G * u_effective  (small-signal approx)
        self._g_hat = self.cfg.rls_g_prior_bpm
        self._P = self.cfg.rls_g_prior_bpm**2
        # History for RLS update
        self._prev_hr: float | None = None
        self._prev_u: float | None = None
        self._prev_hr_base: float | None = None
        # Saturation counter (structural anti-windup)
        self._sat_count = 0
        # Saturation-mode state (only used when rotation/relaxation enabled)
        self._stuck_dir = 0  # +1 stuck pushing up, -1 pushing down
        self._stuck_count = 0
        self._released = 0
        self._relax_dir = 0  # push direction being relaxed (+1 / -1)
        self._relax_phase = ""  # '' | 'down' (away from target) | 'up' (re-climb)
        self._anchor_rung = 0  # rung where the current stall began
        self._last_target: float | None = None  # stuck state resets on change
        self._step_idx = 0
        self._genre_last_seen: dict[str, int] = {}
        self._cell_last_seen: dict[tuple[str, int], int] = {}

    # -----------------------------------------------------------------
    # Reference governor
    # -----------------------------------------------------------------

    def _governor(self, raw_r: float, hr_base: float) -> tuple[float, bool]:
        """Shrink target to the identified reachable set. Returns (r, unreachable_flag)."""
        reach = max(self.cfg.reach_floor_bpm, self.cfg.reach_optimism * self._g_hat)
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

    def _predict_hr(self, hr_now: float, u_seq: list[float], hr_base: float) -> float:
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

    def step(
        self,
        hr_bpm: float,
        hr_target: float,
        hr_base: float,
        current_rung: int,
        arousal_1_9: float | None = None,
    ) -> ControlDecision:
        # 1. Update RLS gain estimate from the previous action's outcome
        self._update_gain(hr_bpm, hr_base)

        # 2. Reference governor
        governed_r, unreachable = self._governor(hr_target, hr_base)

        # 3. Compute raw + effective error. Two modes:
        if self.cfg.arousal_mode == "arousal_primary":
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
            candidates = [
                c
                for c in range(
                    max(0, current_rung - step), min(n_cells - 1, current_rung + step) + 1
                )
                if self._du_ok(current_rung, c)
            ]
            # 6. Evaluate each candidate over horizon H
            #    (constant-u prediction; the first action dominates)
            best_rung = current_rung
            best_J = float("inf")
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
                J = (
                    self.cfg.w_error * (0.5 * err_H * err_H + 0.5 * err_ss * err_ss)
                    + self.cfg.w_churn * (c - current_rung) ** 2
                )
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
                        w = float(getattr(desc, "genre_weights", {}).get(genre, 0.0))
                        # Sort key: (-weight, rung index) so higher weight wins,
                        # ties broken toward lower rung for reproducibility.
                        return (-w, c)

                    ties.sort(key=_score)
                    best_rung = ties[0][0]
            chosen_rung = best_rung

        # 6b. Optional saturation modes (rotation / target relaxation)
        mpc_rung = chosen_rung
        control_mode = "mpc"
        if self.cfg.saturation_rotation or self.cfg.target_relaxation:
            if hr_target != self._last_target:
                self._reset_stuck()  # new target (e.g. protocol phase change)
                self._last_target = hr_target
            # Stuck is judged against the RAW target: the governor shrinks an
            # unreachable target to where HR already is, so the governed
            # error sits in the dead zone while HR stays short of the target.
            if self.cfg.arousal_mode == "arousal_primary":
                raw_target_err = (
                    0.0 if arousal_1_9 is None else hr_target - float(arousal_1_9)
                )
            else:
                raw_target_err = hr_target - hr_bpm
            chosen_rung, control_mode = self._saturation_override(
                mpc_rung, current_rung, raw_target_err
            )

        # 7. Saturation bookkeeping (anti-windup: freeze RLS on next call)
        n_cells = len(self.ladder.cells)
        if chosen_rung == 0 and effective_err < 0:
            sat_state = "sat_lo"
            self._sat_count += 1
        elif chosen_rung == n_cells - 1 and effective_err > 0:
            sat_state = "sat_hi"
            self._sat_count += 1
        else:
            sat_state = "ok"
            self._sat_count = 0

        # 8. Snapshot decision + record for next-step RLS
        cell = self.ladder.by_rung[chosen_rung]
        u_next = cell.u
        # Predict HR at horizon end under the chosen action
        pred_H = self._predict_hr(hr_bpm, [u_next] * self.cfg.horizon, hr_base)

        # Store for next step's RLS update
        self._prev_hr = hr_bpm
        self._prev_u = u_next
        self._genre_last_seen[cell.genre] = self._step_idx
        self._cell_last_seen[cell.gt()] = self._step_idx
        self._step_idx += 1
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
            control_mode=control_mode,
            mpc_rung=mpc_rung,
        )

    def hold(self, current_rung: int, hr_target: float, hr_base: float) -> ControlDecision:
        """
        Decision for a segment with no usable HR: keep the current rung.

        Reads state only (governor); RLS, the previous-action record and the
        saturation-mode state are untouched, so no gain update is made on
        invented HR. The next step() compares HR against the last real
        observation.
        """
        governed_r, unreachable = self._governor(hr_target, hr_base)
        cell = self.ladder.by_rung[current_rung]
        return ControlDecision(
            next_rung=current_rung,
            next_genre=cell.genre,
            next_tier=cell.tier,
            governed_r=governed_r,
            raw_r=hr_target,
            is_unreachable=unreachable,
            g_hat_bpm=self._g_hat,
            saturation_state="ok",
            dead_zone_active=False,
            predicted_hr_H=float("nan"),
            effective_error_bpm=float("nan"),
            control_mode="stale_hold",
            mpc_rung=current_rung,
        )

    # -----------------------------------------------------------------
    # Saturation modes
    # -----------------------------------------------------------------

    def _saturation_override(
        self, mpc_rung: int, current_rung: int, raw_target_err: float
    ) -> tuple[int, str]:
        """Apply rotation / relaxation when the controller is stuck."""
        cfg = self.cfg
        if abs(raw_target_err) <= cfg.dead_zone_bpm:
            push = 0
        else:
            push = 1 if raw_target_err > 0 else -1

        # Relaxation excursion: 'down' moves away from the target direction
        # until u has moved relax_depth_u from the anchor, 'up' re-climbs to
        # the anchor (or follows the MPC if it wants to go further).
        if self._relax_phase:
            d = self._relax_dir
            if push != d:
                self._reset_stuck()
                return mpc_rung, "mpc"
            anchor_u = self.ladder.by_rung[self._anchor_rung].u
            if self._relax_phase == "down":
                if d * (anchor_u - self.ladder.by_rung[current_rung].u) < cfg.relax_depth_u:
                    return self._capped_step(current_rung, -d), "relax"
                self._relax_phase = "up"
            if d * (current_rung - self._anchor_rung) >= 0:
                self._reset_stuck()
                return mpc_rung, "mpc"
            nxt = self._capped_step(current_rung, d)
            nxt = min(nxt, self._anchor_rung) if d > 0 else max(nxt, self._anchor_rung)
            if d * (mpc_rung - nxt) > 0:
                nxt = mpc_rung
            return nxt, "relax"

        # Stuck bookkeeping. Stalled = pushing but the MPC does not move in
        # the push direction (ladder end, or collapsed g_hat mid-ladder).
        stalled = push != 0 and (mpc_rung - current_rung) * push <= 0
        rotating = (
            cfg.saturation_rotation and self._stuck_count >= cfg.rotation_after_segments
        )
        # Rotation ends once the MPC asks for a cell beyond the rotation band
        # in the push direction (mid-ladder, g_hat has recovered). Without
        # this, rotation overrode such climbs for as long as the error kept
        # its sign (L2 run 2026-09-28: 21 segments cycling hiphop2/latin1/rock1
        # while the MPC asked for rnb1). At a ladder end nothing lies beyond
        # the band, so rotation there is unchanged.
        if rotating and push == self._stuck_dir:
            anchor_u = self.ladder.by_rung[self._anchor_rung].u
            if push * (self.ladder.by_rung[mpc_rung].u - anchor_u) > cfg.rotation_band_u:
                self._reset_stuck()
                return mpc_rung, "mpc"
        if push != 0 and (stalled or (rotating and push == self._stuck_dir)):
            if push != self._stuck_dir or self._stuck_count == 0:
                self._stuck_dir, self._stuck_count = push, 0
                self._anchor_rung = current_rung
            self._stuck_count += 1
            self._released = 0
        elif push != 0:
            self._reset_stuck()
            return mpc_rung, "mpc"
        else:
            if self._stuck_count > 0:
                self._released += 1
                if self._released >= cfg.stuck_release_segments:
                    self._reset_stuck()
            return mpc_rung, "mpc"

        d = self._stuck_dir
        if (
            cfg.target_relaxation
            and (d > 0 or cfg.relax_on_down_push)
            and self._stuck_count >= cfg.relax_after_segments
        ):
            self._relax_dir, self._relax_phase = d, "down"
            return self._capped_step(current_rung, -d), "relax"
        if cfg.saturation_rotation and self._stuck_count >= cfg.rotation_after_segments:
            return self._rotation_pick(d, current_rung), "rotate"
        return mpc_rung, "mpc"

    def _du_ok(self, from_rung: int, to_rung: int) -> bool:
        cap = self.cfg.max_du_per_segment
        if cap is None or from_rung == to_rung:
            return True
        return abs(self.ladder.by_rung[to_rung].u - self.ladder.by_rung[from_rung].u) <= cap

    def _capped_step(self, current_rung: int, d: int) -> int:
        """Furthest rung in direction d within max_step_per_segment and the
        energy-jump cap (at least one rung when not at a ladder end)."""
        last = len(self.ladder.cells) - 1
        for k in range(self.cfg.max_step_per_segment, 0, -1):
            r = max(0, min(last, current_rung + d * k))
            if self._du_ok(current_rung, r):
                return r
        return max(0, min(last, current_rung + d))

    def _reset_stuck(self) -> None:
        self._stuck_dir, self._stuck_count, self._released = 0, 0, 0
        self._relax_dir, self._relax_phase = 0, ""

    def _rotation_pick(self, d: int, current_rung: int) -> int:
        """Most extreme cell (in push direction d) of the least-recently-played
        genre within rotation_band_u of both the anchor cell's energy (no
        drift) and the current cell's energy (no large single-segment hop)."""
        anchor_u = self.ladder.by_rung[self._anchor_rung].u
        current_u = self.ladder.by_rung[current_rung].u
        w = self.cfg.rotation_band_u
        band = [
            c for c in self.ladder.cells
            if abs(c.u - anchor_u) <= w
            and abs(c.u - current_u) <= w
            and self._du_ok(current_rung, c.rung)
        ]
        current_genre = self.ladder.by_rung[current_rung].genre
        n = self.cfg.rotation_no_repeat
        if n > 0:
            recent = {k for k, s in self._cell_last_seen.items() if s >= self._step_idx - n}
            pool = [c for c in band if c.rung != current_rung and c.gt() not in recent] \
                or [c for c in band if c.rung != current_rung] or band
            options = [c for c in pool if c.genre != current_genre] or pool
            options.sort(key=lambda c: (self._genre_last_seen.get(c.genre, -1),
                                        self._cell_last_seen.get(c.gt(), -1), -d * c.u))
            return options[0].rung
        best: dict[str, Cell] = {}
        for c in band:
            b = best.get(c.genre)
            if b is None or (c.u > b.u if d > 0 else c.u < b.u):
                best[c.genre] = c
        options = [c for g, c in best.items() if g != current_genre] or list(best.values())
        options.sort(key=lambda c: (self._genre_last_seen.get(c.genre, -1), -d * c.u))
        return options[0].rung


if __name__ == "__main__":
    import random

    from ladder import build_ladder
    from plant_model import FOPDTPlant, Subject

    L = build_ladder()
    ctrl = LadderMPC(L, ControllerConfig())

    # Simulate a typical subject with baseline 75, K=4, target = baseline + 3
    subj = Subject(baseline=75.0, K=4.0, tau=60.0, d=1, u_sat=0.8, kind="typical")
    plant = FOPDTPlant(subj, dt=20.0, noise_sigma=0.5, rng=random.Random(0))

    current_rung = 0
    hr = subj.baseline
    r_raw = 78.0
    print(f"Target: {r_raw} bpm, subject baseline: {subj.baseline}, K: {subj.K}")
    print(
        f"{'step':>4} {'HR':>7} {'rung':>4} {'genre':>6} {'tier':>4} "
        f"{'gov_r':>7} {'g_hat':>6} {'err':>6}"
    )
    for k in range(20):
        dec = ctrl.step(hr, hr_target=r_raw, hr_base=subj.baseline, current_rung=current_rung)
        current_rung = dec.next_rung
        u = L.by_rung[current_rung].u
        hr = plant.step(u)
        print(
            f"{k:>4} {hr:>7.2f} {current_rung:>4} "
            f"{dec.next_genre:>6} {dec.next_tier:>4} "
            f"{dec.governed_r:>7.2f} {dec.g_hat_bpm:>6.2f} "
            f"{dec.effective_error_bpm:>+6.2f}"
        )

    # Now test the UNREACHABLE case: target 120, K=4 -> should refuse
    print("\n--- Unreachable target test ---")
    ctrl2 = LadderMPC(L, ControllerConfig())
    plant.reset()
    hr = subj.baseline
    r_raw = 120.0
    for k in range(5):
        dec = ctrl2.step(hr, hr_target=r_raw, hr_base=subj.baseline, current_rung=0)
        u = L.by_rung[dec.next_rung].u
        hr = plant.step(u)
    print(f"Requested {r_raw}, governed {dec.governed_r:.2f}, unreachable={dec.is_unreachable}")
    assert dec.is_unreachable, "should have refused 120 bpm target"
    assert dec.governed_r < 90, f"governed_r should be << 120, got {dec.governed_r}"
    print("PASS: controller refused unreachable target")
