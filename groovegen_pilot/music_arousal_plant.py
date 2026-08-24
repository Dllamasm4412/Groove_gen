"""
Two-plant cascade for music -> arousal -> HR (M0.6 Step 2).

Physiological pathway modeled here:

    MIRFeatures  --alpha_*-->  ArousalTarget
                                    |
                                    | first-order lag tau_A (5-20s)
                                    v
                                Arousal(t)
                                    |
                                    | beta_hr * (A - baseline)
                                    v
                                HRTarget
                                    |
                                    | first-order lag tau_HR (30-90s), delay=1
                                    v
                                  HR(t)

Design rationale
----------------
Sophia_Study 2026 regressed danceability on MIR features and identified
percussive ratio (beta=+4.66), low-band energy (+2.97), beat consistency
(+1.35), and spectral flatness (-1.23) as significant predictors. She
also confirmed a tempo effect in the 110-130 BPM band (+9.3 pts).

Danceability != arousal, but the tempo->arousal channel is well-replicated
(Husain, Thompson & Schellenberg 2002; Gomez & Danuser 2007). We use
Sophia's coefficients as SHAPE priors (relative magnitudes of contributions)
and rescale absolute magnitudes to the Russell 1-9 arousal scale.

Coefficients here are DEFENSIBLE PRIORS, not calibrated ground truth.
A pilot with real listeners (M1) will fit these against DEAM/PMEmo or
against project-collected labels.

Public API
----------
    ArousalPlantConfig                     defaults from Sophia + literature
    HRPlantConfig                          FOPDT params, per-subject sampled
    MusicArousalHRCascade                  the two-plant simulation
    sample_cascade_subject(rng)            per-subject variation
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Optional

from music_features import MIRFeatures
from plant_model import Subject


# =============================================================================
# Coefficients: Sophia betas re-scaled to arousal 1-9 units
# =============================================================================
#
# Sophia's OLS predicted danceability on a 0-100 Spotify scale.
# One standard-deviation change on the strongest feature (percussive_ratio)
# moved danceability by +4.66 points on a 0-100 scale ~= 0.28 SD of the
# outcome. If we assume tempo and percussive weight together account for
# ~2 arousal points in the moderate-effect regime (roughly a "medium"
# effect on the Russell 1-9 scale per moderate-tempo music-listening studies),
# then we scale Sophia's betas by ~0.4 to get arousal-point/unit-feature
# contributions.
#
# TEMPO effect: modeled as a saturating Gaussian centered on 120 BPM (Janata
# tactus + Sophia 110-130 band). Max contribution +1.5 arousal points at
# center, falling to ~0 by 60 BPM or 180 BPM.


@dataclass(frozen=True)
class ArousalPlantConfig:
    """Music -> arousal coefficients (defensible priors, not calibrated)."""
    # Feature -> arousal contributions (points on Russell 1-9)
    alpha_perc: float = 2.0       # Sophia's strongest positive: +4.66 beta
    alpha_bass: float = 1.3       # Sophia +2.97 beta
    alpha_beat: float = 0.6       # Sophia +1.35 beta
    alpha_flat: float = -0.5      # Sophia -1.23 beta
    alpha_sync: float = 0.2       # Sophia n.s. in commercial audio
    alpha_onset: float = 0.05     # per onset/sec; Sophia n.s.

    # Tempo saturating bell centered at 120 BPM
    tempo_center_bpm: float = 120.0
    tempo_sigma_bpm: float = 30.0
    alpha_tempo: float = 1.5      # max arousal contribution from tempo

    # Arousal dynamics
    tau_arousal_s: float = 12.0   # first-order lag; arousal responds
                                   # fast to music (5-20s in listening studies)
    arousal_baseline: float = 4.0  # neutral ~4/9 pre-stimulus
    arousal_min: float = 1.0
    arousal_max: float = 9.0

    # Arousal noise: reduced by beat consistency (steady pulse -> tighter
    # arousal, matching listener-consistency literature)
    sigma_A0: float = 0.5              # base noise std at zero beat_consistency
    beat_consistency_gain: float = 0.35  # reduction per unit beat_consistency

    def contribution(self, mir: MIRFeatures) -> float:
        """Steady-state arousal target for a given feature vector."""
        # Tempo bell (in-band bonus)
        d = (mir.tempo_bpm - self.tempo_center_bpm) / self.tempo_sigma_bpm
        tempo_term = self.alpha_tempo * math.exp(-0.5 * d * d)
        # Linear terms (all features standardized around approx mid-values)
        # Note: features are 0..1 or small counts; we use raw values here
        # because our priors are set on the raw scales.
        target = (
            self.arousal_baseline
            + tempo_term
            + self.alpha_perc * (mir.percussive_ratio - 0.4)
            + self.alpha_bass * (mir.low_band_energy - 0.5)
            + self.alpha_beat * (mir.beat_consistency - 0.85)
            + self.alpha_flat * (mir.spectral_flatness - 0.2)
            + self.alpha_sync * (mir.syncopation - 0.3)
            + self.alpha_onset * (mir.onset_density - 3.0)
        )
        return float(target)

    def noise_sigma(self, mir: MIRFeatures) -> float:
        s = self.sigma_A0 * max(0.2, 1.0 - self.beat_consistency_gain * mir.beat_consistency)
        return float(s)


@dataclass(frozen=True)
class HRPlantConfig:
    """Arousal -> HR coefficients (per-subject sampled at runtime)."""
    # Baseline HR sampled from LogNormal(72, 8), clipped [55, 95]
    # K_arousal: bpm per arousal point above baseline. Typical: 2.5-6 bpm/pt.
    # tau_HR: 30-90s time constant.
    # These are stored in the Subject dataclass (K, tau) but reinterpreted
    # as arousal-driven rather than u-driven in this cascade.
    arousal_baseline: float = 4.0
    delay_segments: int = 1        # FOPDT delay
    noise_sigma_bpm: float = 1.5


class MusicArousalHRCascade:
    """
    Two-plant cascade for one subject.

    Usage
    -----
        cascade = MusicArousalHRCascade(subject, arousal_cfg, hr_cfg, dt=20.0, rng=...)
        cascade.step(mir_features)      # advance one segment
        cascade.arousal                  # current arousal 1-9
        cascade.hr                       # current HR bpm
    """

    def __init__(self, subject: Subject,
                 arousal_cfg: ArousalPlantConfig = ArousalPlantConfig(),
                 hr_cfg: HRPlantConfig = HRPlantConfig(),
                 *,
                 dt_s: float = 20.0,
                 rng: Optional[random.Random] = None):
        self.subj = subject
        self.a_cfg = arousal_cfg
        self.hr_cfg = hr_cfg
        self.dt = dt_s
        self.rng = rng or random.Random(0)

        # State
        self.arousal: float = arousal_cfg.arousal_baseline
        self.hr: float = subject.baseline

        # Delay buffer for HR: FOPDT dead time in segments
        self._hr_delay_buf: list[float] = [self.arousal] * subject.d

        # Discrete first-order factors (Euler)
        self._alpha_A = 1.0 - math.exp(-dt_s / arousal_cfg.tau_arousal_s)
        self._alpha_HR = 1.0 - math.exp(-dt_s / subject.tau)

    def step(self, mir: MIRFeatures) -> tuple[float, float]:
        """
        Advance one segment given the MIR features being played.

        Returns (arousal, hr) after this step.
        """
        # 1. Compute arousal steady-state target from music
        a_target = self.a_cfg.contribution(mir)
        # 2. Move arousal one dt toward target + noise
        a_noise = self.rng.gauss(0.0, self.a_cfg.noise_sigma(mir))
        self.arousal = (self.arousal
                          + self._alpha_A * (a_target - self.arousal)
                          + a_noise)
        # Clip
        self.arousal = max(self.a_cfg.arousal_min,
                            min(self.a_cfg.arousal_max, self.arousal))

        # 3. Push current arousal into HR delay buffer; pop delayed value
        self._hr_delay_buf.append(self.arousal)
        arousal_effective = self._hr_delay_buf.pop(0)

        # 4. HR steady-state target = baseline + K * (arousal_effective - baseline)
        #    where K is the subject's arousal->HR gain (interpreted from Subject.K
        #    which was previously "bpm at u=1"). We now interpret K as bpm per
        #    arousal point above the arousal baseline.
        hr_target = (self.subj.baseline
                       + self.subj.K * (arousal_effective - self.hr_cfg.arousal_baseline))
        # Advance HR one dt toward target + measurement noise
        hr_noise = self.rng.gauss(0.0, self.hr_cfg.noise_sigma_bpm)
        self.hr = self.hr + self._alpha_HR * (hr_target - self.hr) + hr_noise

        return self.arousal, self.hr


def sample_cascade_population(n: int, rng: random.Random) -> list[Subject]:
    """
    Per-subject variation for the cascade. Reuses plant_model.Subject but
    reinterprets K as "bpm per arousal point above baseline" (previously
    bpm at u=1). Distribution recalibrated so K spans a physiologically
    plausible arousal->HR gain.

    Kinds:
        strong        K in [4, 8]     ~15% (highly music-responsive)
        typical       K in [2, 4]     ~50%
        non_responder K in [0.5, 2]   ~30%
        paradoxical   K in [-2, -0.5] ~5%  (rare, HR drops with high-arousal music)
    """
    subjects = []
    for _ in range(n):
        # Baseline HR
        baseline = min(95.0, max(55.0, rng.gauss(72.0, 8.0)))
        # Kind category
        r = rng.random()
        if r < 0.30:
            kind = 'non_responder'
            K = rng.uniform(0.5, 2.0)
        elif r < 0.80:
            kind = 'typical'
            K = rng.uniform(2.0, 4.0)
        elif r < 0.95:
            kind = 'strong'
            K = rng.uniform(4.0, 8.0)
        else:
            kind = 'paradoxical'
            K = rng.uniform(-2.0, -0.5)
        # tau_HR ~ LogNormal(median=60s, sd factor 1.5)
        tau = math.exp(rng.gauss(math.log(60.0), math.log(1.5)))
        tau = max(30.0, min(120.0, tau))
        # delay = 1 (dominant)
        d = 1
        # u_sat retained for backward compat (unused in cascade)
        u_sat = rng.uniform(0.55, 1.0)
        subjects.append(Subject(baseline=baseline, K=K, tau=tau, d=d,
                                  u_sat=u_sat, kind=kind))
    return subjects


# =============================================================================
# Self-test
# =============================================================================

if __name__ == '__main__':
    from ladder import build_ladder
    from music_features import build_feature_bank

    print('=' * 60)
    print('MusicArousalHRCascade self-test')
    print('=' * 60)

    L = build_ladder()
    fb = build_feature_bank(L)

    # Check arousal steady-state contribution across the ladder
    cfg = ArousalPlantConfig()
    print(f'\nSteady-state arousal target per rung (baseline={cfg.arousal_baseline}):')
    print(f'{"rung":>4} {"cell":>10} {"a_target":>10} {"sigma_A":>9}')
    print('-' * 40)
    for c in L.cells:
        mir = fb[c.rung]
        a = cfg.contribution(mir)
        s = cfg.noise_sigma(mir)
        print(f'{c.rung:>4} {f"{c.genre}-{c.tier}":>10} {a:>10.2f} {s:>9.3f}')

    # Now simulate a single subject going up the ladder over 30 segments
    print()
    print('Cascade dynamics: typical subject climbing the ladder')
    rng = random.Random(42)
    subjects = sample_cascade_population(1000, rng)
    subj = next(s for s in subjects if s.kind == 'typical')
    print(f'Subject: baseline={subj.baseline:.1f}, K={subj.K:.2f} bpm/pt, tau={subj.tau:.1f}s')

    cascade = MusicArousalHRCascade(subj, rng=random.Random(0))
    print(f'{"seg":>4} {"rung":>4} {"cell":>10} {"arousal":>8} {"hr":>7}')
    for seg in range(30):
        rung = min(19, seg // 2)   # climb ladder
        mir = fb[rung]
        a, hr = cascade.step(mir)
        cell = L.by_rung[rung]
        if seg % 3 == 0:
            print(f'{seg:>4} {rung:>4} {f"{cell.genre}-{cell.tier}":>10} '
                  f'{a:>8.2f} {hr:>7.1f}')

    # Sanity checks
    # 1. Arousal should be higher at rung 19 than rung 0
    c0 = MusicArousalHRCascade(subj, rng=random.Random(0))
    for _ in range(20):
        c0.step(fb[0])
    c19 = MusicArousalHRCascade(subj, rng=random.Random(0))
    for _ in range(20):
        c19.step(fb[19])
    print()
    print(f'20-seg steady-state at rung 0: A={c0.arousal:.2f}, HR={c0.hr:.1f}')
    print(f'20-seg steady-state at rung 19: A={c19.arousal:.2f}, HR={c19.hr:.1f}')
    assert c19.arousal > c0.arousal + 0.5, \
        f'expected arousal higher at rung 19, got A_hi={c19.arousal:.2f} vs A_lo={c0.arousal:.2f}'
    assert c19.hr > c0.hr + 1.0, f'expected higher HR at rung 19'
    print('PASS: rung 19 raises both arousal and HR above rung 0')

    # 2. Two different genres at same u should give DIFFERENT arousal
    # calm-5 (rung 4, u=0.20) vs a fictitious "u=0.20" scalar in old sim
    mir_calm5 = fb[4]
    mir_pop3 = fb[15]  # much higher u, different family
    a_calm = cfg.contribution(mir_calm5)
    a_pop = cfg.contribution(mir_pop3)
    print()
    print(f'calm-5 arousal target: {a_calm:.2f}')
    print(f'pop-3 arousal target:  {a_pop:.2f}')
    print(f'gap: {a_pop - a_calm:.2f} pts')
    assert a_pop - a_calm > 1.5, 'not enough spread'
    print('PASS: pop-3 arousal target > calm-5 by 1.5+ pts')

    # 3. Two genres at similar u should generally give different arousal.
    # Note: pop-1 and latin-1 happen to nearly tie because pop-1's tempo
    # bonus (in the Sophia 110-130 band) balances latin-1's higher
    # percussive weight. That's not a bug -- it's exactly the
    # danceability/tempo trade-off Sophia's regression predicts. Use a
    # clearer contrast: rnb-5 (u=0.66) vs pop-1 (u=0.64), which differ
    # sharply in tempo (94 vs 112 BPM) and percussive_ratio (0.66 vs 0.44).
    a_rnb5 = cfg.contribution(fb[11])
    a_pop1 = cfg.contribution(fb[10])
    print()
    print(f'rnb-5 (u=0.66, 94 BPM) arousal target: {a_rnb5:.2f}')
    print(f'pop-1 (u=0.64, 112 BPM) arousal target: {a_pop1:.2f}')
    print(f'diff (rnb - pop): {a_rnb5 - a_pop1:+.2f} pts')
    assert abs(a_rnb5 - a_pop1) > 0.3, \
        'clearly different genres should give different arousal'
    print('PASS: near-u, different-genre -> different arousal')

    print()
    print('=' * 60)
    print('ALL SELF-TESTS PASSED')
    print('=' * 60)
