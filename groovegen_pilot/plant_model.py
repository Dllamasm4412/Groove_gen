"""
FOPDT plant + subject sampler for GrooveGen closed-loop simulation
(M0.5 Step 5.5).

First-order-plus-dead-time HR response to musical energy input:

    HR[k+1] = HR[k] + (dt / tau) * (baseline - HR[k] + K * u[k - d]) + noise

where:
    u        : commanded energy in [0, 1] (from the ladder)
    K        : per-subject full-scale musical HR authority (bpm at u=1)
    tau      : HR response time constant (s)
    d        : input delay (segments)
    dt       : segment duration (s)
    baseline : subject's resting/session baseline HR (bpm)

Constants blended from the council synthesis (Opus + Gemini + GPT):
    tau_mean = 60 s          (Opus 50, Gemini 45, GPT 75 -> midpoint)
    T_d      = 1 segment     (all three)
    K prior  = 0.03 * baseline  (Opus, from Watanabe +5.6% halved)

Subject population per Opus Monte Carlo bench (400 subjects):
    30% non-responders    (K ~ U(0, 1.5) bpm)
    50% typical           (K ~ U(2, 5) bpm)
    15% strong            (K ~ U(5, 9) bpm)
    5%  paradoxical       (K sign reversed, magnitude ~ typical)

The plant is deliberately SATURATING (Hammerstein) — a linear plant
would let any controller look great. Saturation matches Watanabe 2017
Exp 2, where HR gained nothing past +10% relative tempo.

Public API
----------
    Subject                        Dataclass with baseline, K, tau, d, u_sat, kind
    sample_subject(rng)            Draw one Subject from the population
    sample_population(n, rng)      Draw n Subjects
    FOPDTPlant(subject, dt)        Simulator; call .step(u) each segment

Invariants
----------
    - Subject.K may be negative (paradoxical); Subject.u_sat in (0, 1]
    - dt is the segment duration in seconds
    - Plant.step returns the NEW HR (bpm), rounded to 3 decimals
"""

from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass


# =============================================================================
# Subject population
# =============================================================================

@dataclass
class Subject:
    baseline: float          # bpm
    K: float                 # bpm at u=1 (signed; negative = paradoxical)
    tau: float               # s
    d: int                   # segments of input delay
    u_sat: float             # saturation point; input clamped at this energy
    kind: str                # 'non_responder' | 'typical' | 'strong' | 'paradoxical'

    def summary(self) -> str:
        return (f'Subject(kind={self.kind}, baseline={self.baseline:.1f}, '
                f'K={self.K:+.2f}, tau={self.tau:.0f}s, d={self.d}, '
                f'u_sat={self.u_sat:.2f})')


# Council-agreed population mix (Opus + GPT)
_POP_MIX = (
    ('non_responder', 0.30),
    ('typical',       0.50),
    ('strong',        0.15),
    ('paradoxical',   0.05),
)


def _sample_K(kind: str, rng: random.Random) -> float:
    """Sample full-scale authority in bpm for a given subject kind."""
    if kind == 'non_responder':
        return rng.uniform(0.0, 1.5)
    if kind == 'typical':
        return rng.uniform(2.0, 5.0)
    if kind == 'strong':
        return rng.uniform(5.0, 9.0)
    if kind == 'paradoxical':
        # Same magnitude range as typical, opposite sign
        return -rng.uniform(2.0, 5.0)
    raise ValueError(f'unknown kind: {kind}')


def sample_subject(rng: random.Random | None = None,
                   force_kind: str | None = None) -> Subject:
    """
    Sample one Subject from the council-agreed population.

    Parameters
    ----------
    rng : random.Random or None
        RNG. None -> a fresh module-level RNG.
    force_kind : str or None
        If provided, override the population mix and sample this kind.
    """
    r = rng if rng is not None else random.Random()
    if force_kind is not None:
        kind = force_kind
    else:
        roll = r.random()
        acc = 0.0
        kind = _POP_MIX[-1][0]
        for k, p in _POP_MIX:
            acc += p
            if roll < acc:
                kind = k
                break
    baseline = r.uniform(60.0, 85.0)
    K = _sample_K(kind, r)
    # tau ~ LogNormal(log 60, 0.30), truncated 30..120
    tau = math.exp(math.log(60.0) + r.gauss(0.0, 0.30))
    tau = max(30.0, min(120.0, tau))
    d = r.choice([1, 1, 1, 2])   # d=1 modal, occasional d=2 per GPT
    u_sat = r.uniform(0.55, 1.0)
    return Subject(baseline=baseline, K=K, tau=tau, d=d, u_sat=u_sat, kind=kind)


def sample_population(n: int, rng: random.Random | None = None) -> list[Subject]:
    r = rng if rng is not None else random.Random()
    return [sample_subject(r) for _ in range(n)]


# =============================================================================
# Plant simulator
# =============================================================================


class FOPDTPlant:
    """
    Discrete-time first-order-with-dead-time plant with Hammerstein saturation.

    Parameters
    ----------
    subject : Subject
    dt : float
        Segment duration in seconds. Discrete timestep.
    noise_sigma : float
        Std of additive Gaussian noise on HR (bpm). Default 1.5 (Gemini prior).
    rng : random.Random, optional
        Deterministic noise stream.

    Usage
    -----
        plant = FOPDTPlant(subject, dt=20.0)
        for u_k in u_sequence:
            hr_k = plant.step(u_k)   # returns HR AFTER applying u_k with delay
    """

    def __init__(self, subject: Subject, dt: float,
                 noise_sigma: float = 1.5,
                 rng: random.Random | None = None):
        self.subject = subject
        self.dt = float(dt)
        self.noise_sigma = float(noise_sigma)
        self.rng = rng if rng is not None else random.Random()
        # State: HR starts at baseline
        self.hr = subject.baseline
        # Delay line for u (length = d)
        self.u_queue: deque[float] = deque([0.0] * subject.d, maxlen=subject.d)
        self.k = 0  # step counter

    def step(self, u: float) -> float:
        """
        Advance one segment. `u` is the commanded energy for THIS segment.
        The plant applies the delayed u (from d segments ago) to update HR.
        Returns the new HR in bpm.
        """
        # Apply saturation on incoming command
        u_clamped = max(0.0, min(1.0, float(u)))
        u_applied = min(u_clamped, self.subject.u_sat) / self.subject.u_sat
        # Delay: use the u from d segments ago
        u_effective = self.u_queue[0]
        self.u_queue.append(u_applied)   # push new u, discard oldest
        # First-order update: alpha = exp(-dt/tau)
        alpha = math.exp(-self.dt / self.subject.tau)
        target = self.subject.baseline + self.subject.K * u_effective
        new_hr = alpha * self.hr + (1.0 - alpha) * target
        # Additive measurement noise
        new_hr += self.rng.gauss(0.0, self.noise_sigma)
        self.hr = new_hr
        self.k += 1
        return round(self.hr, 3)

    def reset(self) -> None:
        self.hr = self.subject.baseline
        self.u_queue = deque([0.0] * self.subject.d, maxlen=self.subject.d)
        self.k = 0


if __name__ == '__main__':
    rng = random.Random(42)
    pop = sample_population(200, rng)
    counts = {}
    for s in pop:
        counts[s.kind] = counts.get(s.kind, 0) + 1
    print(f'Population of 200: {counts}')
    # Expected ~30/50/15/5
    assert 45 <= counts.get('non_responder', 0) <= 75, counts
    assert 85 <= counts.get('typical', 0) <= 115, counts

    # Deterministic step test
    subj = Subject(baseline=70, K=5.0, tau=60, d=1, u_sat=0.8, kind='typical')
    plant = FOPDTPlant(subj, dt=20.0, noise_sigma=0.0, rng=random.Random(0))
    hrs = [plant.step(1.0) for _ in range(10)]
    print(f'Step response u=1.0: {[round(h,2) for h in hrs]}')
    # After many steps, HR should approach baseline + K * u_sat_normalized = 70 + 5*1 = 75
    assert 74.0 < hrs[-1] < 75.1, hrs
    print(f'  Final HR: {hrs[-1]:.2f} (expected ~75.0 = baseline + K)')

    # Delay test
    plant.reset()
    hr0 = plant.step(0.0)
    hr1 = plant.step(1.0)
    hr2 = plant.step(1.0)
    # With d=1, u=1 at step 1 shouldn't affect HR until step 2
    print(f'Delay check: hr after u=0 -> {hr0:.3f}, u=1 -> {hr1:.3f}, u=1 -> {hr2:.3f}')
    assert abs(hr0 - 70.0) < 0.01, hr0
    assert abs(hr1 - 70.0) < 0.01, hr1  # delayed
    assert hr2 > hr1, (hr1, hr2)

    print('ALL CHECKS PASSED')
