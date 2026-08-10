"""tier_mapping.py — reconcile the controller's continuous density command with
the paper's L1-L5 intensity tiers, with anti-chatter protection.

WHY THIS EXISTS (council finding #1 + landmine #1):
  * The validated CascadeController fast loop emits an integer event-density in
    [density_min, density_max] = [3, 20].
  * The paper claim + the renderer (symbolic_tiers_demo.drum_bar_tier) speak in
    intensity TIERS 1..5.
  * A PD loop whose output is quantized to 5 levels will CHATTER at tier
    boundaries (limit cycle). So we:
      1. keep the controller's density state CONTINUOUS (never quantize upstream),
      2. map density -> tier only here, at render time,
      3. apply a Schmitt-trigger hysteresis band on the boundaries,
      4. rate-limit to <= 1 tier change per bar.
  * We log BOTH tier_cmd (pre-hysteresis) and tier_applied (post) so the
    quantization-induced tracking error is a separate, reportable term.
"""
from __future__ import annotations
import numpy as np


def density_to_tier_raw(density: float, dmin: int = 3, dmax: int = 20) -> int:
    """Linear, MONOTONIC map density[dmin,dmax] -> tier[1,5]. No hysteresis."""
    frac = (float(density) - dmin) / (dmax - dmin + 1e-9)
    frac = min(1.0, max(0.0, frac))
    return int(np.clip(round(1 + frac * 4), 1, 5))


class TierMapper:
    """Stateful density->tier mapper with hysteresis + rate limiting.

    hysteresis (in *tier fraction* units, 0..1 of one tier width): the density
    must cross a boundary by this margin before the applied tier changes. This
    kills boundary chatter. rate_limit caps applied-tier movement per bar.
    """

    def __init__(self, dmin: int = 3, dmax: int = 20,
                 hysteresis: float = 0.25, max_tier_step: int = 1,
                 initial_tier: int = 1):
        self.dmin = int(dmin)
        self.dmax = int(dmax)
        self.hysteresis = float(hysteresis)
        self.max_tier_step = int(max_tier_step)
        self._applied = int(np.clip(initial_tier, 1, 5))

    @property
    def tier(self) -> int:
        return self._applied

    def _continuous_tier(self, density: float) -> float:
        frac = (float(density) - self.dmin) / (self.dmax - self.dmin + 1e-9)
        frac = min(1.0, max(0.0, frac))
        return 1.0 + frac * 4.0  # continuous in [1,5]

    def step(self, density: float) -> tuple[int, int]:
        """Return (tier_cmd, tier_applied).

        tier_cmd    = naive rounded tier from density (what a memoryless map gives)
        tier_applied= hysteresis + rate-limited tier we actually render this bar
        """
        cont = self._continuous_tier(density)          # e.g. 2.73
        tier_cmd = int(np.clip(round(cont), 1, 5))

        # Hysteresis: only move off the current applied tier once the continuous
        # value is more than `hysteresis` PAST the midpoint toward the next tier.
        # Rails (tier 1 and 5) use a plain rounding threshold so they stay
        # reachable even at the extreme density values.
        target = self._applied
        up_thresh = self._applied + 0.5 + self.hysteresis
        dn_thresh = self._applied - 0.5 - self.hysteresis
        if cont >= 4.5:                      # top rail always reachable
            target = 5
        elif cont <= 1.5:                    # bottom rail always reachable
            target = 1
        elif cont >= up_thresh:
            target = self._applied + int(np.floor(cont - self._applied))
        elif cont <= dn_thresh:
            target = self._applied - int(np.floor(self._applied - cont))
        target = int(np.clip(target, 1, 5))

        # Rate limit: at most max_tier_step change per bar.
        delta = int(np.clip(target - self._applied,
                            -self.max_tier_step, self.max_tier_step))
        self._applied = int(np.clip(self._applied + delta, 1, 5))
        return tier_cmd, self._applied


if __name__ == "__main__":
    # quick self-check: a density ramp should climb tiers WITHOUT chattering
    tm = TierMapper()
    dens = list(range(3, 21)) + list(range(20, 2, -1))
    rows = []
    for d in dens:
        tc, ta = tm.step(d)
        rows.append((d, tc, ta))
    print("density  tier_cmd  tier_applied")
    for d, tc, ta in rows:
        print(f"  {d:5d}     {tc}          {ta}")
