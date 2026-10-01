# V2 generator: working context

Short source of truth for the v2 (controlled live generation) work. The design,
history and full result tables live in `LIVE_GENERATION_PLAN.md` (sections 4.3-4.4,
6.7-6.11); this file only records the current state and the next step.

## Branch and commits

- Branch `v2-controlled-live-generation`. Latest commits: `7e47c3b` v2a.3
  (op cost, deterministic novelty selection), `079d2ba` v2a.2, `d0cf24c`
  certification, `4e88a0a` v2a.
- Fresh-session start: read `CLAUDE.md`, this file, then `git branch --show-current`,
  `git status --short`, `git log --oneline -8`; read only the plan sections and code
  ranges you need.

## Implementation state

- `composer/arrangement.py`: `SessionComposer`, `GEN_VERSION` (seeds depend on it).
  Up to 12 candidates (3 rounds x 4, round r at relax r). Novelty range: drum R4
  against the previous visit <= `R4_PREV_MAX` = 0.97. The cheapest valid in-range
  candidate is chosen, else the nearest valid one (`novelty_fallback`), else the
  base. History holds (drum sha, content sha, drum bar sets, bar signatures).
- `composer/variation.py`: `vary(base, genre, var_seed, relax, avoid, fresh)`:
  post-generation drum ops on bars 4 and 8 (required) and other varied bars
  (optional). Ops are chosen by cost level (`COST`, `op_cost`); hand-drum
  articulation swaps cost the same as an exchange.
- `certify_stimuli.py`: MIDI plus rendered-audio certification against the v1 envelopes.
  Per v1_live / v2_session row: `same_base_as_prev`, `new_drum_bar_frac`,
  `new_drum_patterns`, `changed_drum_bar_frac`; summary `a6_novelty_balance` (A6) and
  `r4_energy_rho_diagnostic` (old A6, no pass/fail).
- `op_attribution.py` (debug only, not in the live path): renders each logged op
  alone on its base and reports per-op centroid, flux, pulse, LUFS and E deltas in
  units of the cell's certification allowance.

## Invariants (must hold after every change)

- v1 is byte-identical (`tests/test_composer_identity.py`). v2 is off by default and
  not wired live. `composer.py`, the frozen hiphop and rock cells, the controller and
  `run_session_v2.py` are not modified.
- Ops are count-neutral and velocity-neutral, never add a voice the base lacks, never
  create a kick, and never touch protected notes (clave, crash, on-beat kick and
  snare, calm kick and rim, hiphop slot-10 kick).
- Certification thresholds do not change in v2a.3; no envelope loosening without
  evidence reported first.

## Previous certification (v2a.2, audio run `renders/certification/20260930_122337`)

27/27 repetition targets, fallback 0, variation-controlled 8/27, LUFS max 0.006 LU,
E max 0.0085, centroid shift mean -13 Hz.

## v2a.3 attribution findings (op_attribution, 7 cells, allowance units per op)

- hiphop:3-5 flux drop: closed-to-open hat changes. family 42>46 gives flux -0.4 to
  -0.74. The reverse, 46>42, fixes flux but costs centroid -0.9 to -1.5, so it is
  not a clean fix. Mechanism: GM hat choke (42 and 44 cut a ringing 46), so any op
  that creates, removes or moves a 46, or changes the hat that chokes it, changes
  sustained high-frequency energy.
- rock:5: all of the drift comes from open/closed hat ops (exchange 42<>46,
  family 42<>46), the same choke mechanism.
- rnb:4 pulse: cross-family exchanges (38<>42, 38<>51, 38<>46) displace the snare
  accent, costing -0.5 to -0.9 pulse each.
- latin:2 pulse: moves of the regular 8th-note hat lane (-5.1 per op). This arises
  because the fill window is searched through every tier before the whole bar is
  searched with cheap ops (a loop-order bug), and from required-bar fallbacks.
- hiphop:1: every available change costs about 1x of some allowance (cross 42>38
  costs centroid; a move of 42 costs pulse). Relax 0 gives only 4 cross patterns,
  fewer than the 5 needed for the repeat window. Classified as an unavoidable
  conflict; its threshold is not loosened.

## v2a.3 rules (committed in 7e47c3b)

1. Open-hat ring preserved: the set of (46 onset, next 42/44/46 onset) pairs is
   unchanged by every op. Waived only by a last-resort pass on a required phrase
   end (exchange / family only, counted as `ring_break`), for bases whose every hat
   is a 46 or its choke (some lofi / rnb bases: 46 on every off-beat).
2. Exchanges only within one timbre family.
3. A 16th move of a note in an evenly spaced run of 3 of its lane (spacing <= 4) is
   a `grid_move`, capped at MAX_MOVES; other moves (`move`) are limited only by the
   feature budget.
4. (Superseded by op cost, plan 6.10.) Tier order: exchange, move, family, grid_move, cross (`TIERS`, `PASSES`). Tiers
   form the outer loop and windows the inner loop.
5. Cross only on required phrase ends at relax 0; optional ops may cross on
   retries (relax >= 1). Without that, hiphop:3 fell back in 18 of 24 segments.
6. `GEN_VERSION = 'v2a.3'`.

Census (MIDI, 2 stim seeds x 12 visits, all 27 cells): fallback 0, no structure
failures.

## v2a.3 results so far

- Targeted audio (`renders/certification/20260930_132619`, 10 cells), compared
  with v2a.2:
  - hiphop:3-5 flux is inside its allowance (hiphop:3 -0.007 -> +0.003, allowed 0.004).
  - rock:5 centroid -54 -> -9 Hz (allowed 30); flux and pulse are inside.
  - rnb:4 pulse -0.017 -> -0.002 (allowed 0.013); rnb:4 is now variation-controlled.
  - hiphop:4 is now variation-controlled.
- Full MIDI run (`20260930_133435`): 27/27 targets, variation-controlled 26/27
  (hiphop:1 on-beat -0.027 vs 0.025), fallback 0.
- Open problem, a6 regression: rho 0.40 vs limit 0.30 (v2a.2: 0.08).
  - Cause: hiphop:3-5 R4 rose 0.96 -> 0.99. Their only ring-safe ops touch the
    single rim note per bar, so consecutive visits reuse the same bar patterns.
  - Restoring hiphop:3-5's v2a.2 R4 alone would give rho 0.29.
  - Allowing optional cross at relax 0 did not help (rho 0.398): the rim ops win
    the tier order.
  - Novelty there needs hat-lane changes: ring breaks cost flux, crosses cost about
    -0.5x centroid each. This needs the user's decision.
- latin:2: only 63<>64 exchanges (4.7 per segment, +0.14x centroid each, whole
  segment +0.68x). The shift is inside its allowance but centroid envelope misses
  rose 3 -> 14.
- rock:1-4 and hiphop:1: every available op costs at least 1x of some allowance.
  Rock's pulse allowance is 0.001; v1 drums are seed-invariant, so the envelope
  reflects only pitched variation.

## Decisions 1 and 2 (committed in 7e47c3b; plan 6.10)

- Op cost replaces the tier order: exchange 1, move 2, family 3, grid_move 4,
  cross 5; an articulation swap costs 1.
- Novelty: a candidate set, R4 ceiling 0.97 (the v2a.2 within-block p75), and
  no floor (R4 per op depends on density). `fresh` never buys a cross.
- Full audio `20260930_143933`, compared with `20260930_133905`:
  - variation-controlled cells 12 -> 11; repetition targets 27/27; fallback 0;
  - within-block R4 q95 1.0 -> 0.971, exact repeats 10% -> 0%;
  - centroid envelope misses 29 -> 11; flux misses 14 -> 8;
  - pulse shift-fail cells 4 -> 6 (hiphop:1, rock:1);
  - a6 0.40 -> 0.43.
- a6 is driven by base drum seed-invariance (cross-block R4) and by density.
  New bar patterns per visit vs u gives rho +0.10.
- MIDI `20260930_143529`: variation-controlled cells 26/27.
- Full suite: 74 passed. The 5 gates exit 0.

## Decisions (2026-09-30)

- The old a6 still fails (0.43). It is confounded by base drum seed-invariance
  and density, so it stays as a diagnostic only. The generator is not changed to
  pass it.
- hiphop:3 novelty is meaningful drum variation constrained by the available
  audio-safe degrees of freedom; no further crosses are spent on it. Non-drum
  novelty is future work.
- The v2a.3 generator rules are frozen while the metric is reviewed.

## A6: novelty balance (adopted 2026-09-30; plan 6.11)

- C1 is the within-block new drum-bar share: the share of drum bars whose onset set
  occurs nowhere in the previous visit, over same-base visits only.
- A6 passes if mean C1 >= 1/8 and |OLS slope of C1 on u| / mean <= 0.25.
  - **0.25 is a provisional engineering threshold, not perceptually validated.**
    It is not tightened or loosened at this stage.
  - Spearman, the within-genre tier trend, the bootstrap and new-block values are
    diagnostics, not gates.
- The old R4 A6 is `r4_energy_rho_diagnostic` (a rho only, no pass/fail). It is
  density- and base-change-confounded, and it passed v2a.2 (+0.08) although
  v2a.2's new material rose with u (+0.69).
- v2a.3 (MIDI `20260930_192025`):
  - C1 mean 0.274 (hiphop:3 0.148 .. latin:3 0.422);
  - rel change -0.074 [-0.179, +0.039];
  - rho_u -0.33; within-genre tier rho -0.12;
  - **A6 passes**; old R4 rho 0.4262.
- The novelty generator is not modified further.

## Next task

Envelope review, separate from A6 and the generator:
- calm:1-2, hiphop:1 and rock:1-5 (pulse / centroid; their v1 drums are
  seed-invariant);
- then the single-segment misses.
Non-drum novelty for hiphop:3 is future work.

## Reproduce

```
cd groovegen_pilot
../.venv/bin/python3.12 -m pytest tests/test_variation.py -q
../.venv/bin/python3.12 certify_stimuli.py --cells hiphop:1,hiphop:3,rock:5 [--audio] --workers 6
../.venv/bin/python3.12 certify_stimuli.py --audio --workers 6        # full, ~11 min
../.venv/bin/python3.12 op_attribution.py --cells hiphop:3,rock:5 --probes 2
```
