# V2 generator: working context

Short source of truth for the v2 (controlled live generation) work. The design,
history and full result tables live in `LIVE_GENERATION_PLAN.md` (sections 4.3-4.4,
6.7-6.18); this file only records the current state and the next step.

## Branch and commits

- Branch `v2-controlled-live-generation`. Latest commits: `288743e` R&B v2c.rnb.0,
  `004c9dc` shared engine + Calm + Lo-fi,
  `2bdf0e9` v2b.1 melody-only checkpoint, `7e4b5b9` v2b.0 motif
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
- `composer/develop_engine.py` (v2c, committed in `004c9dc`): the shared
  development engine (selection, history, fallbacks, generic guard, chord context,
  levels). Policies are registered in `POLICIES`: hiphop `motif.py` (v2b.1, now a
  policy on the engine, MIDI byte-identical), `composer/dev_calm.py` (v2c.calm.0) and
  `composer/dev_lofi.py` (v2c.lofi.0). Other genres have no policy and are unchanged.
  Level tables are `composer/levels_calm.py`, `levels_lofi_color.py` and
  `levels_lofi_stab.py`. `develop_metrics.py` compares calm / lofi v2a.3 vs
  developed (plan 6.13).
- `composer/dev_rnb.py` (v2c.rnb.0, developer listening approved 2026-10-01): R&B
  keys development on the engine, reusing the `dev_lofi` reader and dyads; level
  tables `levels_rnb_color.py`, `levels_rnb_stab.py`; `develop_metrics.py` covers rnb
  (plan 6.14).
- `composer/dev_pop.py` (v2c.pop.0, uncommitted, awaiting developer listening): pop
  lead-guitar development on the engine (theme -> variation -> answer -> recall);
  level table `levels_pop_lead.py` (program 25); `develop_metrics.py` covers pop
  (plan 6.15). `develop_engine.chord_context` gained `min_frac` (default 0.5 keeps
  every accepted genre byte-identical; pop's stabbed EP needs 0).
- `composer/dev_latin.py` (v2c.latin.0, uncommitted; technically validated;
  developer listening pending): nylon voicing development (pitch classes kept,
  exact pitched p05 / median / p95); level table `levels_latin_nylon.py`
  (program 24); `develop_metrics.py` covers latin (plan 6.16).
- Rock: deliberately no policy (plan 6.17); `develop=True` leaves it
  byte-identical.
- `session_generator.py` + `run_session_v2(segment_source=)` +
  `run_pilot_zero.py --generator {bank,v2a,v2c} --stim-seed N` (uncommitted;
  offline-verified, not yet run live): the opt-in v2 generator in the real session
  path, default `bank` unchanged (plan 6.18). `simulate_session_v2.py` runs the
  live stack offline with a scripted HR and real FluidSynth.
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
  - genres without a policy (latin, rock) are byte-identical to v2a.3;
  - hiphop v2b.1 is byte-identical to its fixture (`tests/test_develop_identity.py`);
  - calm v2c.calm.0 and lofi v2c.lofi.0 are byte-identical to theirs, including the
    approved auditions (`tests/test_develop_identity_v2c.py`);
  - rnb v2c.rnb.0 likewise (`tests/test_develop_identity_rnb.py`);
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

## v2c shared engine, Calm and Lo-fi (2026-10-01, plan 6.13; approved, `004c9dc`)

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

## v2c R&B (2026-10-01, plan 6.14; approved, frozen)

- Keys-only, pitch-only; two ops per developed visit:
  - pos 1: hook contour on bars 1-4 + answer on 5-8 (recall of the previous block's
    hook in odd blocks);
  - pos 2: bar-8 ending + bar 4 or one bar.
- 5th+7th only where the EP plays the 7th (F#min7, Emin7); never the source's
  4-bar loop; exact / near / ending history over 6 visits.
- Register guard: pitched p95 and median never move toward the v1 envelope edge
  the source sits on (the edge follows the colour / EP octave).
- Level table predicts the rendered change (r ~0.9) but the effect is small, so the
  candidate-filter tolerance is 0.5 dB, not 0.2 (0.2 left a third of rnb:1-2 visits
  unchanged). It filters MIDI-predicted level only; certification envelopes are
  unchanged and rendered developed segments moved <= 0.037 LU.
- Results:
  - MIDI: exact previous-visit repeats 8-9 -> 0 (2 fallbacks at one seed); distinct
    0.25-0.33 -> 0.75-1.0; bar-4/8 pair variety 0.25-0.33 -> 0.58-0.92.
  - Hard fallback 11/96 developed visits, mostly high-register rnb:1-2 (guard).
  - Audio: segment_ok 0.9375 vs base 0.9271, no new misses, ΔLUFS <= 0.037.
- Auditions (A/B, stim_seed 1): `renders/audition_v2/v2c_rnb3_s1` (rnb:3 x8),
  `v2c_rnb2_s1` (rnb:2 x8).

## v2c Pop (2026-10-01, plan 6.15; technical validation complete; listening pending)

- Lead-only (program 25), pitch-only; EP, bass, drums, onsets, durations,
  velocities, counts and tempo are untouched.
- Theme = the source's bars 1-2. Bars 5-6 share their chords, so a block's visits
  run:
  - theme (restated on 5-6);
  - variation (answer on bar 8 + bar-4 ending), or a recall of the previous
    block's theme in odd blocks;
  - sequence on bar 7 + bar-8 ending.
- Repairs:
  - `fix_unisons`: FluidSynth ends both voices of a same-key overlap at the first
    note-off, so new unisons are moved; the theme notes are never the ones moved.
  - `balance`: lowers non-theme notes until the pitched p95 is back at the source.
- Rules:
  - chord tones in root..root + 12;
  - no note above the source maximum; pitched median exact, p95 within the shift
    bound (both predicted exactly from `others + lead`);
  - bounded leaps;
  - 6-visit exact / near / ending history.
- `LEVEL_TOL_DB` 1.0: a candidate filter only. Pop's lead moves rendered LUFS by
  0.031 LU/dB (max 0.042), and 0.5 only added fallbacks.
- Results:
  - exact repeats 24 -> 0 per cell; distinct 0.33 -> 1.0;
  - theme on bars 5-6: 22-30 of 36;
  - hard fallback 11/180.
  - Audio: pop:1/3/5 segment_ok and miss sets identical to v2a.3; 0 flips; ΔLUFS
    <= 0.051.
- `chord_context` gained `min_frac` (default 0.5, so other genres are unchanged).
  Bar binning in `develop_metrics.py` was fixed.
- Auditions (A/B, stim_seed 1): `renders/audition_v2/v2c_pop3_s1` (pop:3 x8),
  `v2c_pop1_s1` (pop:1 x8).

## v2c Latin (2026-10-02, plan 6.16; technically validated; developer listening pending)

- Nylon-only, pitch-only voicing changes: each triad keeps its chord, closed
  voicings in the source window +- 2, one voicing per bar except bar 8's ending
  triad, bars 1-2 fixed.
- Latin's pitched median / p05 / p95 envelopes have zero width (every seed plays
  the same pitch multiset). Ops therefore enumerate bar units jointly and keep only
  lines with the exact register; the ending triad pairs with bar 8's other triads.
- Results:
  - exact repeats 8-9 -> 0 per session; distinct 0.25-0.33 -> 1.0;
  - ending equal to the previous visit's 8-10 -> 0-2;
  - top-contour similarity 0.84-0.96 -> 0.68-0.75;
  - hard fallback 7/180.
- Audio (latin:1-3): segment_ok 49/72 -> 47/72 (10 ok -> miss, 8 miss -> ok).
  Every flip has identical drums and lies on a feature v2a.3 already misses;
  ΔLUFS mean 0.008, max 0.074. Recorded as a residual; envelopes unchanged.
- Ladder position and the live tier cap are unchanged.
- Auditions: `renders/audition_v2/v2c_latin3_s1`, `v2c_latin1_s1`.

## Rock (2026-10-02, plan 6.17): deliberate no-op

- rock:3-5 is a root + 5th gallop on one power chord per 2 bars. The only pitch
  freedoms are the progression (harmony, out of scope) or the dyad octave, which
  zero-width p95 (64 at rock:3-4) and median (57 at rock:4) forbid.
- Drums already rotate (10-12 distinct per 12 visits).
- The rock:5 lead overlay is the only candidate for a future slice.

## Opt-in live integration (2026-10-02, plan 6.18; offline-verified, not yet run live)

- `--generator v2c` gives one SessionComposer per session. A revisit continues the
  cell's visits. The source gets only (genre, tier). Appended trace columns record
  provenance and timing (`render_s`, `planned_s`, `queued_ahead_s`).
- Default `bank`: HEAD vs working copy, 3 scripted sessions, all HEAD columns and
  the enqueued audio byte-identical.
- `tests/test_session_v2_integration.py` (A-G + boundary, tempo, invariance): 11
  pass.
- Simulated session `renders/integration_v2/20261002_010333_v2c/`: 37 segments,
  12.3 min, deterministic WAV.
- Real compose + render max 2.09 s (p95 1.68) against the 3.0 s render lead.

## Rock presentation (2026-10-05; wired, gains set, uncommitted)

- Developer decision by ear: keep the guitar (program 26, Musyng Kite "Jazz Guitar";
  rock_cell.py's clean/overdriven docstring is wrong), drums x1.20, Rock as loud as
  its neighbours, in both `bank` and `v2c`. Composition frozen.
- Wired in `composer.py` `GENRE_CFG['rock']`:
  - `drum_velocity_scale=1.20`, applied in `_gen_rock` (clamp 1..127). Variation ops
    are velocity-neutral, so v2c keeps it.
  - `render_gain_db={1: 4.0, 2: 3.0, 3: 3.0, 4: 1.5, 5: 0.0}`. The developer chose
    rock:1 +4 dB by ear (hiphop2 -> rock1 -> latin1); tiers 2-5 sit at the same
    metered offset (+3.1 LU) above their live neighbours, rounded to 0.5 dB, and
    rock:5 is not cut. Check: `renders/rock_mix/20261005_rock_final/listen/`.
    `_gen_rock` writes the gain into the MIDI as a text event (`render_directive`).
- Renderer (`segment_renderer.py`): directive MIDI renders `-O float`, then the
  gain, then `limit_peaks` (look-ahead, -1 dBFS ceiling, 20 ms). Float matches the
  16-bit render to -95 dB. MIDI without the directive (every other genre) uses the
  old command, bit-identical to HEAD (checked on pop, hiphop, latin).
- Why the gain needs float + limiter: by LUFS, Rock at x1.20 already matches pop at
  rock:2-3 and is louder than hiphop at rock:4-5 (rock:1 ~0.9 LU low), and rock:5
  clipped inside fluidsynth's int16 output. The developer still hears Rock as low,
  so the gains are set by ear per tier.
- Gain audition: `renders/rock_mix/20261005_rock_gain/listen/` (0/+2/+4/+6 dB per
  tier between live neighbours; built before wiring, with the candidate tool).
- Verified: identity fixtures regenerated, only Rock keys changed
  (`composer_identity_v1.json`, `develop_identity_v2b1.json`); full suite before
  regeneration 566 pass / 3 fail (all Rock identity); after it, rock + identity
  tests 250 pass; 5 gates exit 0. v2c sim
  `renders/integration_v2/20261005_rock_wired_v2c/`: 0 full-scale samples, max
  compose+render 1.58 s; rock:4-5 compose+render max 1.82 s.
- `energy_table_v1.json` re-measured (`renders/smoke_audit/energy_20261005_rock/`):
  - No non-Rock cell changed.
  - Rock LUFS: -22.22/-19.52/-18.82/-16.37/-14.23 -> -17.49/-15.95/-15.15/-14.46/-13.73.
  - Rock centroid is +450..+565 Hz.
- Live 27-cell ladder: rock:1 rung 7 -> 14 (above latin:3), rock:2 15 -> 21,
  rock:3 20 -> 24, rock:4 24 -> 25, rock:5 stays at 26. hiphop:5 drops 25 -> 23.
  The default scripted v2c sim (`renders/integration_v2/20261005_rock_final_v2c/`)
  no longer reaches Rock: 35 segments, max 1.34 s, 0 full-scale samples.
- Rock certification `--audio` (`renders/certification/20261005_rock_presentation/`):
  - It reproduces the new table exactly.
  - Verdicts are as before the change (2026-09-30 audio run): variation and
    within-range still fail, with 16-20 failing checks per cell either way.
  - These are the pre-existing Rock envelope issue (see Next task). Nothing was
    loosened.
- Full suite after the table: 610 pass. The 4 failures were Rock identity
  fixtures (regenerated; only Rock keys changed) and one gain test (fixed).
- `rock_mix_audition.py` is audition-only. Its outputs from before wiring are not
  reproducible now, because composed Rock already carries x1.20.

## After the first v2c live run (2026-10-05; uncommitted)

Developer feedback on the run: up-steps pop5 -> rock1 and pop5 -> hiphop3 sound
wrong; latin2 held for several segments "sounded the same all the time"; no high
Rock was heard (the session never climbed past hiphop4, rung 22, so rock3-5 at
24-26 were never asked for).

- **Energy without the Rock gain.** The presentation gain is a loudness match by
  ear, not energy. `music_features_measured.energy_audio` (also used by
  `certify_stimuli.render_one`) drops the render directive before metering.
  Table re-measured (`renders/smoke_audit/energy_20261005_rock_nogain/`); only
  rock:1-5 changed. The table records `excludes`. Live ladder now: calm1 calm2
  hiphop1 lofi1-3 hiphop2 latin1 **rock1 (8)** rnb1-3 latin2 rnb4 latin3 **rock2
  (15)** pop1-5 **rock3 (21)** hiphop3-5 **rock4 (25) rock5 (26)**. hiphop3 is still
  above pop5 by measurement.
- **By-ear order** (`ladder.build_ladder(ear_ratings=)`, `run_pilot_zero --ladder
  ear`, file `energy_order_by_ear.json`). The developer's ratings re-assign the
  measured u values in rating order (ties keep the measured order; ratings must
  not fall with tier). The u set is unchanged, so controller and rotation-band
  tuning carry over. Kit: `energy_by_ear.py render` writes one clip per live cell
  (v2c, two visits, live renderer incl. Rock gain), every adjacent step, and
  `ratings.csv`; `energy_by_ear.py apply` validates and writes the JSON.
  Kit rendered: `renders/energy_by_ear/20261005_1526/`. Ratings pending.
- **Rotation without ping-pong** (`ControllerConfig.rotation_no_repeat=2`, live
  default). The rotation pick skips cells played in the last 2 segments while the
  band has others, prefers another genre, then genre and cell recency. The old
  pick (least-recent genre, most extreme cell) alternated latin2 / rnb3; it is
  kept for `rotation_no_repeat=0`. Tests in `tests/test_energy_order.py`.
- **Latin v2c.latin.1: piano and bass development** (`composer/dev_latin.py`
  `accompany`). The nylon is unchanged (seed `v2c.latin.0`; 180/180 visits
  identical). Every visit plays one bass pattern (swap, anticipate, octave,
  swap+anticipate) and one piano dyad pattern (35, 5R, R3>35, R3>5R, 35>R3,
  5R>35) over bars 5-8 or 3-8. Both change every visit; pitch-only; chord tones;
  exact register.
  - Unbalanced first try: piano re-voicings raised latin:1-2 low_ratio shift to
    +0.0070 / +0.0051 (allowed 0.0021), segment_ok 0.08 / 0.17
    (`renders/certification/v2c_latin1_dev_unbalanced`). Fix: measured
    per-pattern effects (`ACCOMP_EFFECT`); only pairs whose predicted dLUFS /
    dlow_ratio stay within 0.15 LU / 0.005 are played; bass "third" dropped.
  - Certification `--audio` (`renders/certification/v2c_latin1_dev`): cell
    verdicts as v2c.latin.0; segment_ok latin:1-3 0.21 / 0.25 / 0.79 (was 0.58 /
    0.46 / 0.92); LUFS and low_ratio cell shifts inside allowance; pulse_clarity
    latin:1 +0.0144 (allowed 0.0130; was +0.0097), latin:2 +0.0092 (allowed 0.0025;
    already over at +0.0056). Recorded as a residual, envelopes unchanged.
  - Rendered census vs v2c.latin.0 (60 segments): dLUFS -0.22..+0.04, median -0.09.
  - Dwell auditions: `renders/audition_v2/20261005_latin1_latin2_dwell`, `..._latin3_dwell`.
- v2c sim `renders/integration_v2/20261005_latin1_v2c/`: 38 segments, plan
  invariance max nunique 1.

## Next task

1. Developer: listen to the Latin dwell auditions, then fill
   `renders/energy_by_ear/20261005_1526/ratings.csv`; then `energy_by_ear.py
   apply`. Then a live developer run with `--generator v2c --ladder ear`; check
   `queued_ahead_s` and gen_visit_idx in its trace.
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
../.venv/bin/python3.12 -m pytest tests/test_dev_rnb.py tests/test_develop_identity_rnb.py -q
../.venv/bin/python3.12 measure_hook_levels.py --profile rnb_color            # also rnb_stab
../.venv/bin/python3.12 develop_metrics.py --cells rnb:1,rnb:2,rnb:3,rnb:4 --visits 12 --stim-seeds 1,2,19
../.venv/bin/python3.12 certify_stimuli.py --cells rnb:1,rnb:2,rnb:3,rnb:4 --visits 12 --audio --workers 3 --develop --stim-seeds 1,2
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell rnb:3 --visits 8 --stim-seed 1 --generator v2-v2b
../.venv/bin/python3.12 -m pytest tests/test_dev_pop.py -q
../.venv/bin/python3.12 measure_hook_levels.py --profile pop_lead
../.venv/bin/python3.12 develop_metrics.py --cells pop:1,pop:2,pop:3,pop:4,pop:5 --visits 12 --stim-seeds 1,2,19
../.venv/bin/python3.12 certify_stimuli.py --cells pop:1,pop:3,pop:5 --visits 12 --audio --workers 3 --develop --stim-seeds 1,2
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell pop:3 --visits 8 --stim-seed 1 --generator v2-v2b
../.venv/bin/python3.12 -m pytest tests/test_dev_latin.py -q
../.venv/bin/python3.12 measure_hook_levels.py --profile latin_nylon
../.venv/bin/python3.12 develop_metrics.py --cells latin:1,latin:3,latin:5 --visits 12 --stim-seeds 1,2,19
../.venv/bin/python3.12 certify_stimuli.py --cells latin:1,latin:2,latin:3 --visits 12 --audio --workers 4 --develop --stim-seeds 1,2
../.venv/bin/python3.12 audition_v2.py --mode dwell --cell latin:3 --visits 8 --stim-seed 1 --generator v2-v2b
../.venv/bin/python3.12 -m pytest tests/test_session_v2_integration.py -q
../.venv/bin/python3.12 simulate_session_v2.py --sf2 ../soundfonts/Musyng_Kite.sf2 --generator v2c
../.venv/bin/python3.12 simulate_session_v2.py --sf2 ../soundfonts/Musyng_Kite.sf2 --generator v2c --sweep 3
../.venv/bin/python3.12 -m pytest tests/test_energy_order.py tests/test_dev_latin.py -q
../.venv/bin/python3.12 music_features_measured.py --table          # after any composer / cell change
../.venv/bin/python3.12 energy_by_ear.py render --sf2 Musyng_Kite.sf2 --out renders/energy_by_ear/<ts>
../.venv/bin/python3.12 energy_by_ear.py apply --ratings renders/energy_by_ear/<ts>/ratings.csv
```
