# V2 generator: working context

Short source of truth for the v2 (controlled live generation) work. The design,
history and full result tables live in `LIVE_GENERATION_PLAN.md` (sections 4.3-4.4,
6.7-6.13); this file only records the current state and the next step.

## Branch and commits

- Branch `v2-controlled-live-generation`. Latest commits: `2bdf0e9` v2b.1 melody-only
  checkpoint, `7e4b5b9` v2b.0 motif
  prototype, `03ff71c` audition
  harness, `62f7944` A6 novelty balance, `7e47c3b` v2a.3 (op cost, deterministic novelty selection), `079d2ba`
  v2a.2, `d0cf24c` certification, `4e88a0a` v2a.
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
- `audition_v2.py` (developer listening only, not in the live path): renders dwell,
  sequence or preset auditions through the unchanged generators, FluidSynth and the
  live join (run_session_v2 trim + `CrossfadeMixer(fade_bars=0.25, 'tail_out')`).
- `composer/motif.py` (v2b.1, opt-in `SessionComposer(stim_seed, develop=True)`,
  hiphop only, not wired live): pitch-only motif development of the hiphop RH hook
  after drum selection, with the measured level / motion check (plan 6.12a).
  `DEV_VERSION` 'v2b.1' is the provenance label; motif seeds hash `SEED_VERSION`
  'v2b.0', so v2b.1 replays the certified and auditioned Step A MIDI. Plumbing:
  `SessionGenerator(develop=)`, `certify_stimuli.py --develop`,
  `audition_v2.py --generator v2b|v2-v2b`.
- `composer/develop_engine.py` (v2c, uncommitted pending approval): the shared
  development engine (selection, history, fallbacks, generic guard, chord context,
  levels). Policies are registered in `POLICIES`: hiphop `motif.py` (v2b.1, now a
  policy on the engine, MIDI byte-identical), `composer/dev_calm.py` (v2c.calm.0) and
  `composer/dev_lofi.py` (v2c.lofi.0). Other genres have no policy and are unchanged.
  Level tables are `composer/levels_calm.py`, `levels_lofi_color.py` and
  `levels_lofi_stab.py`. `develop_metrics.py` compares calm / lofi v2a.3 vs
  developed (plan 6.13).
- `composer/hook_levels.py`: measured per-(pitch, velocity) piano levels, generated
  by `measure_hook_levels.py`, sha-pinned to the sf2.
- `pitched_metrics.py` (diagnostic): melody/bass/whole-segment repetition metrics
  and a v2a.3 vs v2b comparison CLI. The bass track is the one with most notes
  below 48 (the old rule picked the tier 4+ sub-bass).
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
- Develop mode:
  - genres without a policy (rnb, pop, latin, rock) are byte-identical to v2a.3;
  - hiphop v2b.1 is byte-identical to its fixture (`tests/test_develop_identity.py`);
  - onsets, note counts, velocities, bass, progressions, tempo and programs are
    unchanged;
  - drums equal v2a.3 except in calm (drum window 12);
  - the generator reads no physiology (`tests/test_generator_boundary.py`,
    `tests/test_motif.py`, `tests/test_develop_engine.py`).

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

## Audition harness (2026-09-30)

- Each WAV is a fresh generator session; v2 content depends only on
  (stim_seed, genre, tier, visit_idx, GEN_VERSION), so the same arguments give the
  same MIDI (and, with the same soundfont, a byte-identical WAV).
- Output `renders/audition_v2/<stamp>/` (gitignored): one WAV per audition,
  `manifest.csv` (one row per segment: start time, cell, visit, seeds, candidate,
  novelty, MIDI sha), `manifest.json` (args, join config, soundfont sha, per-audition
  peak / clipping / fallbacks), `LISTENING_NOTES.md` (segment start times and the
  checklist). `--segment-wavs` adds per-segment WAVs; `--generator both` adds a v1
  bank A/B over the same cells.
- Differences from live: no HR, controller or player; no live gaps (render lead,
  underruns); cells are fixed, not chosen by the MPC; v2 is not wired live.
- Initial set `renders/audition_v2/20260930_194351` (stim_seed 1, 2 workers, 32 s):
  hiphop:3 x8 2:51, rock:3 x8 2:09, calm:2 x8 3:57, rnb:4 x6 1:56, latin:2 x6 1:51,
  ladder sequence 2:26. Peak <= 0.82, no clipping, no tail scaling, gen fallback 0;
  hiphop:3 novelty fallback 5/8 (known, 1/8 new bars within block). calm:2 drums
  cycle with period 5 across blocks (visits 5-7 replay the drums of 0-2): calm's
  base drums are seed-invariant and novelty only looks at the previous visit.

## v2b.0 motif development (2026-09-30, first slice, superseded by v2b.1; plan 6.12)

- Opt-in only; default v2a.3 output unchanged; v1 byte-identical; live runner and
  controller untouched. Not audio-certified (5/48 tested segments newly outside the
  reference envelopes) and not ready for live integration.
- Developer listening (hiphop:3 x8, stim_seed 1, v2a.3 vs v2b): v2b sounds
  meaningfully less repetitive; keep the architecture. Listening is not certification.

- Rules, schedule and results are in plan 6.12. Hiphop pitched window repeats go
  from 7 to 0 and melody phrase variety from 0.03 to about 0.5. Bass and drums are
  unchanged.
- Audio at the default reference (`renders/certification/v2b_hiphop_full/`, runs
  `v2a3`, `v2b` [displacement draft], `v2b_fold`, `v2b_pitch` [final]):
  - segment_ok 0.958 -> 0.854;
  - 5/48 new edge misses: LUFS 1, pulse 2, low_ratio 2. Not certified.
- Durable findings:
  - lead fold: notes <= 84 are octave-doubled, so the octave-doubled count is kept
    per phrase;
  - onset displacement moved pulse_clarity, so development is pitch-only.
- Audition `renders/audition_v2/20260930_205851`:
  - `01_dwell_hiphop3_x8_v2_s1.wav` (v2a.3) vs `02_dwell_hiphop3_x8_v2b_s1.wav` (v2b);
  - drums identical; no clipping; no fallbacks.
- Recorded for later:
  - latin sounds higher-energy than its ladder placement; the ladder is not changed;
  - calm repeats after about 4 min (drum period 5, see the audition harness section).

## v2b.1 melody-only (2026-10-01, plan 6.12a / 6.12b)

Architecture of hiphop v2b.1:
- drums: v2a.3 controlled variation;
- hook: v2b.1 stateful development;
- bass, harmony, key and hook rhythm: the cell's original, unchanged.

- Step A (motif.py, v2b.1): hook level table + level / motion check in selection.
  Certification runs `v2b_energy2` and `v2b1_melody` (MIDI-identical):
  - LUFS / low_ratio misses 3 -> 0;
  - segment_ok 0.896;
  - census fallback 1.1%;
  - novelty kept.

  Residuals (thresholds unchanged, for the envelope-policy review):
  - hiphop:1 pulse shift, inherited from v2a.3;
  - pulse misses on edge bases (hiphop:3 1 new, hiphop:5 2);
  - the hiphop:3 flux shift 0.00397 vs 0.00359, the cost of real pitched
    development. Do not reduce development to remove it.
- Bass development (experimental vb.0, Step B) was prototyped and rejected after
  developer A/B listening; its code was removed and it is not active (plan 6.12b).
  The bass is the stable anchor.
- Audition: `renders/audition_v2/v2b1_hiphop3_s1` (v2b.1, hiphop:3 x8, stim_seed 1).
  The listening comparison was `stepB_hiphop3_s1`; its 03 file is the rejected bass
  prototype.

## Pitched audit, non-hiphop genres (2026-10-01, MIDI only, no generator change)

Base segments via `schedule()` + `generate_segment()`, 12 visits x stim seeds 1-2,
plus 150 sampled base seeds per cell. v2a.3 leaves pitched tracks equal to the base
(checked on 7 cells).
- Every genre: the 3 visits of a block replay identical pitched material (calm 88 s,
  lofi 74 s, rnb 58 s, latin 55 s, pop 49 s, rock 44-52 s per block).
- rnb, lofi, pop, latin: each genre uses exactly 4 chord pc-sets, and the 4
  "progressions" are reorderings of the same 4 chords. The harmony is effectively
  seed-invariant within a genre.
- calm: the rhythm is seed-invariant. The piano plays one note on every downbeat (8 per
  segment), the pad changes chord every 2 bars, and the drums are a fixed grid. Only
  the pitches vary (the seed space is all-distinct). calm:1 and calm:2 produce
  identical MIDI for a given seed (`max(2, int(d*8))` = 2 at both densities). The
  ladder is not changed; this is recorded for later. 22% of piano notes clip at
  velocity 127. Drum period 5 (v2a.3 `REPEAT_WINDOW` 4); a scratch run with a window
  of 12 gave 12/12 distinct drums and 0 fallbacks (MIDI only, not adopted).
- lofi / rnb: no melody. The keys track is a root+3rd dyad on beat 3, plus random
  off-beat stabs at density >= 0.5. At density < 0.5 every pitched track loops 4 bars
  x2. EP has 8 contents in the seed space, bass 16.
- pop: the lead (program 25) is a per-bar chord-tone walk, 8/8 distinct bars, with no
  internal motif. It is new every block (cross-block Jaccard 0.01-0.03).
- latin: no melody (nylon montuno triads, piano dyads, tumbao). Every track loops 4
  bars. The whole pitched seed space is 8 contents (tiers 1-2) or 12 (tiers 3-5); bass
  and piano have 4, fixed by the progression. Cross-block exact repeats are frequent
  (latin:2 s1: 2 distinct of 4 blocks).
- rock: rock:3-4 have 4 pitched contents (progression only), rock:1-2 guitar and the
  rock:5 lead are seed-varied. Listening at rock:3 was natural, so no change.
- `hook_levels` covers program 0 at pitches 70-98 and velocities up to 112 only.
  calm piano (62-81, up to 127), keys (60-81), pad 89, EP 4, guitar 25 and nylon 24
  need tables before audio certification.
- Proposed order: calm, lofi/rnb (one generator; lofi is the live initial cell), pop,
  latin, rock none. Shared engine + genre policy; pitch-only; bass and harmony
  unchanged.

## v2c shared engine, Calm and Lo-fi (2026-10-01, plan 6.13; uncommitted)

- Engine plus policies as above. Hiphop v2b.1 is byte-identical; no seed salt
  changed.
- Calm (calm:2 first, all tiers run):
  - pitch-only piano, chord tones of the pad's bar chord;
  - one tone move per visit, or a recall in odd blocks, and a bar-8 ending;
  - 12-visit exact / near anti-repeat;
  - not brighter or higher (mean +0.5 max, no new top);
  - drum window 12 (develop only): 12/12 distinct, 0 drum fallbacks in 24 visits.

  Results:
  - MIDI: exact previous-visit repeats 8 -> 0-1; distinct 0.33 -> 0.92-1.0.
  - Audio: segment_ok 0.583 vs base 0.625. All flips come from the drums (window 12
    picks costlier variants late), not the piano. This is a residual; the proposed
    fix is a pulse proxy in develop-mode drum ranking.
- Lo-fi (lofi:2 prototype, lofi:3 live start):
  - keys-only guide-tone / voicing development with EP-stacked adjacent dyads;
  - one op per visit;
  - source voicing may recur;
  - pitched p95 never lowered (the lofi:3 bases sit on the v1 p95 floor).

  Results:
  - MIDI: exact previous-visit repeats 8-9 -> 0; distinct 0.33 -> 0.83-1.0.
  - Audio: lofi:3 24/24 and lofi:2 20/24, identical to base, no flips, ΔLUFS
    <= 0.03.
- Not fixed, recorded:
  - calm:1 = calm:2 MIDI;
  - 22% of calm piano notes at velocity 127.
- Auditions in `renders/audition_v2/`, all A/B v2a.3 vs developed, stim_seed 1:
  - `v2c_calm2_s1` (calm:2 x12);
  - `v2c_lofi3_s1` (lofi:3 x8);
  - `v2c_lofi2_s1` (lofi:2 x8).

## Next task

1. Developer listening to the v2c auditions. Then, on approval, commit the shared
   engine plus Calm and Lo-fi. Next is R&B, stronger than lofi (plan 6.13
   recommendation). Do not add bass variation.
2. Then the envelope review, separate from A6 and the generator:
   - calm:1-2, hiphop:1 and rock:1-5 (pulse / centroid; their v1 drums are
     seed-invariant);
   - then the single-segment misses.
   Use `--preset problem` to audition these cells.
Non-drum novelty beyond the v2b hiphop slice, and the calm:2 cross-block drum cycle, are future work.

## Reproduce

```
cd groovegen_pilot
../.venv/bin/python3.12 -m pytest tests/test_variation.py -q
../.venv/bin/python3.12 certify_stimuli.py --cells hiphop:1,hiphop:3,rock:5 [--audio] --workers 6
../.venv/bin/python3.12 certify_stimuli.py --audio --workers 6        # full, ~11 min
../.venv/bin/python3.12 op_attribution.py --cells hiphop:3,rock:5 --probes 2
../.venv/bin/python3.12 audition_v2.py --preset initial --stim-seed 1 --workers 2
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell hiphop:3 --visits 8 --stim-seed 1
../.venv/bin/python3.12 audition_v2.py --mode sequence --cells calm:2,lofi:2,rnb:2 --visits-per-cell 1
../.venv/bin/python3.12 audition_v2.py --preset problem --generator both     # v1 vs v2 A/B
../.venv/bin/python3.12 -m pytest tests/test_motif.py -q                     # v2b
../.venv/bin/python3.12 pitched_metrics.py --cells hiphop:1,hiphop:3,hiphop:5 --visits 8 --stim-seeds 1,2
../.venv/bin/python3.12 certify_stimuli.py --cells hiphop:1,hiphop:3,hiphop:5 --visits 8 --audio --workers 3 --develop
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell hiphop:3 --visits 8 --stim-seed 1 --generator v2-v2b
../.venv/bin/python3.12 measure_hook_levels.py                              # after a soundfont change
../.venv/bin/python3.12 measure_hook_levels.py --profile calm               # also lofi_color, lofi_stab
../.venv/bin/python3.12 -m pytest tests/test_develop_engine.py tests/test_develop_identity.py tests/test_dev_calm.py tests/test_dev_lofi.py -q
../.venv/bin/python3.12 develop_metrics.py --cells calm:1,calm:2,lofi:2,lofi:3 --visits 12 --stim-seeds 1,2,19
../.venv/bin/python3.12 certify_stimuli.py --cells lofi:2,lofi:3 --visits 12 --audio --workers 3 --develop --stim-seeds 1,2
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell calm:2 --visits 12 --stim-seed 1 --generator v2-v2b
```
