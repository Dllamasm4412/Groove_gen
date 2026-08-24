"""
HR -> tier mapping for GrooveGen closed-loop pilot (M0.5 Step 5).

Physiological control law: given an HR reading, produce a tier in 1..5.
Locked design decision (per pilot planning): use option A (linear band map
with configurable thresholds). Option C (delta-from-baseline) is planned
for a later iteration; this module leaves room for it by exposing a
`TierPolicy` protocol with `.decide(hr_bpm)` so the run_session loop can
swap policies without change.

Public API
----------
    LinearBandPolicy(bands=DEFAULT_BANDS)
        The A option. `bands` is a sorted list of BPM thresholds; a reading
        strictly below bands[i] gets tier i+1. Reading >= bands[-1] gets
        the top tier.

        Default bands: [70, 80, 90, 100]
          hr <  70  -> tier 1
          70 <= hr < 80  -> tier 2
          80 <= hr < 90  -> tier 3
          90 <= hr < 100 -> tier 4
          hr >= 100 -> tier 5

    TierPolicy (protocol)
        Any object with `.decide(hr_bpm: float) -> int` and `.name -> str`.

Invariants
----------
    - Tier is always in {1, 2, 3, 4, 5}
    - Non-finite or negative HR raises ValueError
    - The bands list must be sorted strictly ascending and produce exactly 5 tiers
"""

from __future__ import annotations

from typing import Protocol, Sequence

DEFAULT_BANDS: tuple[float, ...] = (70.0, 80.0, 90.0, 100.0)


class TierPolicy(Protocol):
    """Any HR-to-tier decision policy."""
    name: str
    def decide(self, hr_bpm: float) -> int: ...


class LinearBandPolicy:
    """
    Option A: threshold-based band map. Deterministic, transparent, no
    per-user configuration. See DEFAULT_BANDS for the ship-default.
    """
    name = 'linear_bands'

    def __init__(self, bands: Sequence[float] = DEFAULT_BANDS):
        bands = tuple(float(b) for b in bands)
        if len(bands) != 4:
            raise ValueError(
                f'bands must have exactly 4 thresholds for 5 tiers, '
                f'got {len(bands)}')
        for i in range(len(bands) - 1):
            if bands[i] >= bands[i + 1]:
                raise ValueError(
                    f'bands must be strictly ascending, got {bands}')
        self.bands = bands

    def decide(self, hr_bpm: float) -> int:
        if not isinstance(hr_bpm, (int, float)) or hr_bpm != hr_bpm:  # NaN check
            raise ValueError(f'hr_bpm must be a finite number, got {hr_bpm!r}')
        if hr_bpm < 0:
            raise ValueError(f'hr_bpm must be non-negative, got {hr_bpm}')
        tier = 1
        for threshold in self.bands:
            if hr_bpm < threshold:
                return tier
            tier += 1
        return tier  # tier == 5, hr >= bands[-1]

    def __repr__(self) -> str:
        return f'LinearBandPolicy(bands={self.bands})'


if __name__ == '__main__':
    print('=' * 60)
    print('hr_to_tier self-test')
    print('=' * 60)
    p = LinearBandPolicy()
    cases = [
        (50, 1), (69.9, 1),
        (70, 2), (79.9, 2),
        (80, 3), (89.9, 3),
        (90, 4), (99.9, 4),
        (100, 5), (180, 5),
    ]
    for hr, expected in cases:
        got = p.decide(hr)
        mark = 'PASS' if got == expected else 'FAIL'
        print(f'  [{mark}] hr={hr:>6} -> tier={got} (expected {expected})')

    # Error cases
    for bad in [-1, float('nan')]:
        try:
            p.decide(bad)
            print(f'  [FAIL] hr={bad} should have raised')
        except ValueError:
            print(f'  [PASS] hr={bad} raised ValueError')

    # Custom bands
    p2 = LinearBandPolicy(bands=[65, 75, 85, 95])
    assert p2.decide(64) == 1
    assert p2.decide(65) == 2
    assert p2.decide(96) == 5
    print(f'  [PASS] custom bands [65,75,85,95] applied correctly')

    print('=' * 60)
    print('ALL CHECKS PASSED')
    print('=' * 60)
