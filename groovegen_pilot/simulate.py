"""
Monte Carlo closed-loop simulator for GrooveGen (M0.5 Step 5.5d).

Runs the actual production controller against a population of virtual
subjects (from plant_model.sample_population), against three policy
comparators:

    1. closed_loop  : the LadderMPC controller under test
    2. reactive     : the current HR->tier mirror (current GrooveGen)
    3. yoked        : plays a TIME-REVERSED action sequence of matched
                      energy distribution -- this is the primary control
                      (per Opus council report). A working closed-loop
                      controller must beat its own yoked replay.

Primary metric (Opus council synthesis):
    Closed-Loop Advantage (CLA) = (MAE_yoked - MAE_closed) / sigma_within

Secondary metrics:
    - MAE, p90 MAE (bpm)
    - Time-in-band (%): fraction of segments with |HR - r| < 3 bpm after settle
    - Musical churn: sum |delta_rung| across the session
    - Refusal correctness: for provably-unreachable targets, was is_unreachable
      set for >= 60% of segments?
    - g_hat identification error: |g_hat_final - |K_true||

Public API
----------
    SimConfig            simulation parameters
    SimResult            per-policy per-subject outcome
    run_single           one subject, one policy, one target -> SimResult
    run_monte_carlo      full sweep over population + policies
    summarize            reduce results to a comparison table

CLI
---
    python simulate.py                    # 100 subjects, small default sweep
    python simulate.py --n 400 --out sim_step5_5.csv
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Sequence

from ladder import build_ladder, Ladder
from control import ControllerConfig, LadderMPC
from plant_model import sample_population, Subject, FOPDTPlant


# =============================================================================
# Config & Result types
# =============================================================================

@dataclass
class SimConfig:
    n_segments: int = 24            # 24 * 20 s = 8 min per subject
    dt_s: float = 20.0
    n_settle: int = 5               # exclude first N segments from steady-state metrics
    band_bpm: float = 3.0           # +/- for time-in-band
    target_bpm_delta: float = 3.5   # signed offset from baseline (reachable for most)
    unreach_target_delta: float = 25.0  # for refusal-correctness test
    noise_sigma: float = 1.5


@dataclass
class SimResult:
    subject_kind: str
    K_true: float
    target_delta: float
    policy: str
    mae: float
    p90: float
    time_in_band_pct: float
    churn_rungs: int
    g_hat_final: float
    unreachable_pct: float
    hr_trace: list[float] = field(default_factory=list)
    rung_trace: list[int] = field(default_factory=list)


# =============================================================================
# Policy shims
# =============================================================================

def _reactive_policy(hr_bpm: float, hr_base: float, ladder: Ladder) -> int:
    """
    The current-GrooveGen reactive mirror: map HR bands -> tier, then
    pick the rung in the middle-energy genre matching that tier.

    This is exactly the policy Opus's bench identifies as a POSITIVE-
    FEEDBACK AMPLIFIER for strong responders (MAE 5.31 vs 3.25 for MPC).
    """
    # Linear-band map identical to hr_to_tier.LinearBandPolicy defaults
    if hr_bpm < 70: tier = 1
    elif hr_bpm < 80: tier = 2
    elif hr_bpm < 90: tier = 3
    elif hr_bpm < 100: tier = 4
    else: tier = 5
    # Use rnb as the "neutral" genre for the reactive mapping
    return ladder.by_gt[('rnb', tier)].rung


def _yoked_actions(closed_loop_rungs: list[int]) -> list[int]:
    """Time-reversed closed-loop actions => yoked comparator (Opus §8)."""
    return list(reversed(closed_loop_rungs))


# =============================================================================
# Single-subject rollout
# =============================================================================

def run_single(subject: Subject,
               target_delta: float,
               policy: str,
               ladder: Ladder,
               cfg: SimConfig,
               rng: random.Random,
               fixed_rungs: list[int] | None = None) -> SimResult:
    """
    Run one subject for cfg.n_segments segments under one policy.

    policy in {'closed_loop', 'reactive', 'yoked', 'fixed'}
        'fixed' plays back `fixed_rungs` verbatim.
    """
    plant = FOPDTPlant(subject, dt=cfg.dt_s,
                        noise_sigma=cfg.noise_sigma, rng=rng)
    r_raw = subject.baseline + target_delta

    ctrl: LadderMPC | None = None
    if policy == 'closed_loop':
        ctrl = LadderMPC(ladder, ControllerConfig())

    hr_trace: list[float] = []
    rung_trace: list[int] = []
    unreachable_count = 0
    g_hat_final = 0.0
    current_rung = 0
    hr = subject.baseline

    for k in range(cfg.n_segments):
        # Decide next rung under the active policy
        if policy == 'closed_loop':
            dec = ctrl.step(hr_bpm=hr, hr_target=r_raw,
                             hr_base=subject.baseline,
                             current_rung=current_rung)
            current_rung = dec.next_rung
            if dec.is_unreachable:
                unreachable_count += 1
            g_hat_final = dec.g_hat_bpm
        elif policy == 'reactive':
            current_rung = _reactive_policy(hr, subject.baseline, ladder)
        elif policy == 'yoked' or policy == 'fixed':
            if fixed_rungs is None:
                raise ValueError('yoked/fixed policy requires fixed_rungs')
            current_rung = fixed_rungs[k]
        else:
            raise ValueError(f'unknown policy: {policy}')

        # Apply, advance plant
        u = ladder.by_rung[current_rung].u
        hr = plant.step(u)
        hr_trace.append(hr)
        rung_trace.append(current_rung)

    # Metrics: exclude first n_settle segments from error stats
    errors = [abs(hr - r_raw) for hr in hr_trace[cfg.n_settle:]]
    mae = statistics.mean(errors) if errors else 0.0
    p90 = sorted(errors)[int(0.9 * len(errors))] if errors else 0.0
    in_band = sum(1 for e in errors if e < cfg.band_bpm)
    tib_pct = 100.0 * in_band / max(1, len(errors))
    churn = sum(abs(rung_trace[i + 1] - rung_trace[i])
                for i in range(len(rung_trace) - 1))
    unreach_pct = 100.0 * unreachable_count / cfg.n_segments

    return SimResult(
        subject_kind=subject.kind,
        K_true=subject.K,
        target_delta=target_delta,
        policy=policy,
        mae=mae,
        p90=p90,
        time_in_band_pct=tib_pct,
        churn_rungs=churn,
        g_hat_final=g_hat_final,
        unreachable_pct=unreach_pct,
        hr_trace=hr_trace,
        rung_trace=rung_trace,
    )


# =============================================================================
# Full Monte Carlo
# =============================================================================

def run_monte_carlo(n_subjects: int,
                    cfg: SimConfig,
                    seed: int = 42,
                    target_mode: str = 'fixed') -> dict[str, list[SimResult]]:
    """
    For each subject, run all three policies AGAINST THE SAME PLANT SEED
    (paired comparison). Returns {policy_name: [SimResult, ...]}.

    target_mode:
        'fixed'    -> target_delta = cfg.target_bpm_delta for all subjects
        'authority' -> target_delta = 0.8 * |K_true| for each subject
                       (per Opus council report §7.2 -- oracle-reachable)
    """
    ladder = build_ladder()
    rng_pop = random.Random(seed)
    subjects = sample_population(n_subjects, rng_pop)

    results: dict[str, list[SimResult]] = {
        'closed_loop': [],
        'reactive': [],
        'yoked': [],
    }

    for s_idx, subj in enumerate(subjects):
        if target_mode == 'authority':
            # sign of target follows sign of K so paradoxicals still get
            # a target their K can reach
            target_delta = 0.8 * subj.K
        else:
            target_delta = cfg.target_bpm_delta
        # Paired: same noise seed for each policy run on this subject
        base_seed = seed + s_idx * 1000

        # 1. Closed loop
        cl = run_single(subj, target_delta, 'closed_loop', ladder, cfg,
                         random.Random(base_seed))
        results['closed_loop'].append(cl)

        # 2. Reactive mirror
        rx = run_single(subj, target_delta, 'reactive', ladder, cfg,
                         random.Random(base_seed))
        results['reactive'].append(rx)

        # 3. Yoked open-loop = time-reversed closed-loop actions
        yoked_seq = _yoked_actions(cl.rung_trace)
        yk = run_single(subj, target_delta, 'yoked', ladder, cfg,
                         random.Random(base_seed), fixed_rungs=yoked_seq)
        results['yoked'].append(yk)

    return results


def summarize(results: dict[str, list[SimResult]],
              n_subjects: int) -> str:
    """Return a printable table + Closed-Loop Advantage."""
    lines = []
    lines.append(f'\nMonte Carlo results, N = {n_subjects} subjects\n')
    header = f'{"policy":>12} {"MAE":>7} {"p90":>7} {"tib%":>7} {"churn":>7} {"g_hat":>7}'
    lines.append(header)
    lines.append('-' * len(header))
    for policy in ('closed_loop', 'reactive', 'yoked'):
        maes = [r.mae for r in results[policy]]
        p90s = [r.p90 for r in results[policy]]
        tibs = [r.time_in_band_pct for r in results[policy]]
        churns = [r.churn_rungs for r in results[policy]]
        gs = [r.g_hat_final for r in results[policy]]
        lines.append(
            f'{policy:>12} '
            f'{statistics.mean(maes):>7.2f} '
            f'{statistics.mean(p90s):>7.2f} '
            f'{statistics.mean(tibs):>7.1f} '
            f'{statistics.mean(churns):>7.1f} '
            f'{statistics.mean(gs):>7.2f}'
        )
    # Closed-Loop Advantage
    mae_cl = [r.mae for r in results['closed_loop']]
    mae_yk = [r.mae for r in results['yoked']]
    diffs = [yk - cl for cl, yk in zip(mae_cl, mae_yk)]
    # Within-subject sigma = std of the closed-loop trace itself (proxy)
    sigmas = []
    for r in results['closed_loop']:
        if len(r.hr_trace) > 1:
            sigmas.append(statistics.pstdev(r.hr_trace))
    sigma_w = statistics.mean(sigmas) if sigmas else 1.0
    cla = statistics.mean(diffs) / max(0.1, sigma_w)
    lines.append('')
    lines.append(f'Closed-Loop Advantage (CLA) = {cla:+.3f}  '
                 f'(mean MAE_yoked - MAE_closed = {statistics.mean(diffs):+.2f} bpm; '
                 f'sigma_within = {sigma_w:.2f})')
    # Stratify by subject kind
    lines.append('')
    lines.append('MAE stratified by subject kind:')
    lines.append(f'{"kind":>15} {"n":>4} {"closed":>7} {"reactive":>9} {"yoked":>7}')
    for kind in ('non_responder', 'typical', 'strong', 'paradoxical'):
        idxs = [i for i, r in enumerate(results['closed_loop'])
                if r.subject_kind == kind]
        if not idxs: continue
        cl = statistics.mean(results['closed_loop'][i].mae for i in idxs)
        rx = statistics.mean(results['reactive'][i].mae for i in idxs)
        yk = statistics.mean(results['yoked'][i].mae for i in idxs)
        lines.append(f'{kind:>15} {len(idxs):>4} {cl:>7.2f} {rx:>9.2f} {yk:>7.2f}')

    return '\n'.join(lines)


# =============================================================================
# Unreachable-target refusal test
# =============================================================================

def test_refusal(n_subjects: int, cfg: SimConfig, seed: int = 42) -> str:
    """Run closed-loop against target = baseline + 25 bpm; controller should refuse."""
    ladder = build_ladder()
    rng_pop = random.Random(seed + 999)
    subjects = sample_population(n_subjects, rng_pop)
    refused = []
    for s_idx, subj in enumerate(subjects):
        r = run_single(subj, cfg.unreach_target_delta, 'closed_loop', ladder,
                         cfg, random.Random(seed + s_idx))
        refused.append(r.unreachable_pct)
    n_refusing = sum(1 for p in refused if p >= 60.0)
    return (f'Refusal correctness: {n_refusing}/{n_subjects} subjects '
            f'({100.0*n_refusing/n_subjects:.1f}%) flagged target=+25bpm '
            f'as UNREACHABLE for >=60% of segments (mean flag% = '
            f'{statistics.mean(refused):.1f}%)')


# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=100,
                    help='number of virtual subjects')
    ap.add_argument('--n-segments', type=int, default=24)
    ap.add_argument('--target-delta', type=float, default=3.5,
                    help='signed bpm offset from baseline')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--out', type=str, default='',
                    help='optional path to save per-subject CSV')
    ap.add_argument('--target-mode', choices=['fixed', 'authority'],
                    default='fixed',
                    help='fixed = target-delta for all; authority = 0.8*|K_true|')
    args = ap.parse_args()

    cfg = SimConfig(n_segments=args.n_segments,
                     target_bpm_delta=args.target_delta)
    print(f'Running Monte Carlo: N={args.n}, target_mode={args.target_mode}, '
          f'{args.n_segments} segments/subject...')
    results = run_monte_carlo(args.n, cfg, seed=args.seed,
                                target_mode=args.target_mode)
    print(summarize(results, args.n))
    print()
    print(test_refusal(args.n, cfg, seed=args.seed))

    if args.out:
        with open(args.out, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['policy', 'subject_kind', 'K_true', 'target_delta',
                        'mae', 'p90', 'tib_pct', 'churn', 'g_hat_final',
                        'unreach_pct'])
            for policy in ('closed_loop', 'reactive', 'yoked'):
                for r in results[policy]:
                    w.writerow([policy, r.subject_kind, f'{r.K_true:.3f}',
                                f'{r.target_delta:.2f}', f'{r.mae:.3f}',
                                f'{r.p90:.3f}', f'{r.time_in_band_pct:.2f}',
                                r.churn_rungs, f'{r.g_hat_final:.3f}',
                                f'{r.unreachable_pct:.1f}'])
        print(f'\nSaved per-subject results to {args.out}')


if __name__ == '__main__':
    main()
