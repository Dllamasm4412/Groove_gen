# Next-session handoff: L2 live run (measured ladder + haptic pacing)

Written 2026-09-26 for a Claude session resuming GrooveGen work. Read this file,
then CLAUDE.md (project rules), then the memory index. Everything below was
true at the end of the 2026-09-25 session; re-check anything you rely on
(`git status`, `grep`) before acting on it.

## 0. Standing rules from the user (verbatim, still in force)

- "Do not actuate haptics or start a live PPG session on me without a separate
  explicit confirmation step for each one, distinct from approving the overall plan."
- "no hardware actuation without a distinct explicit confirmation immediately
  before each live test, no verification claims without command evidence, no git
  actions without approval."
- "Do not treat 'the code runs without crashing' as a successful test at any
  stage. State what each stage's success would actually demonstrate, and what it
  would not yet demonstrate."
- "The Python estimator script keeps ownership of HR and respiration rate
  estimation; do not propose replacing or relocating that."

The user runs live hardware themselves: give them the terminal commands, and
analyse the output once they give you the session folder name. Never start a
live run. Plus the CLAUDE.md rules: no git stage/commit/push without approval
(propose with the safe-commit skill), frozen_v2 is read-only, no auto-playback
(give `afplay` commands), the trace schema is append-only, no "calms" or
"regulates" claims, no emojis. Reference HR is an Apple Watch; the user's max
HR is below 120 bpm.

## 1. Where things stand

The user listened to the transition renders and approved the measured ladder
("this actually sounds really good to me"). Then they asked to integrate the
haptics into the run for a test. The integration was already wired and is
verified offline. **The live L2 run has NOT happened yet** (as of this writing).
The next step is the user running it, then you analysing it.

### Changes made on 2026-09-25 (all uncommitted)

1. **Estimator doubled-beat recovery.** In
   `new_biofeedback/ppg_live_estimator_adaptive_haptics_stable_hr.py`,
   `estimate_stable_hr` re-detects peaks at 0.75 x the doubled period. It
   accepts the result as `ok_undoubled` only if both quality gates pass, and
   only tries this when autocorr(L) < -0.1 (`HR_UNDOUBLE_MAX_AC_L`).
   - Replaying the 11:28 recording raised valid HR updates from 16% to 91%.
   - Tests: `new_biofeedback/test_stable_hr.py`.
   - Details are in SENSOR_NOTES.md.
2. **L1b live rerun** (`groovegen_pilot/renders/pilot_zero/daniel_L1b_20260925_114637/`;
   10 min, music only, no haptics).
   - 30/30 segments had fresh HR, and HR matched the watch by eye.
   - HR did not rise: mean error to the raw target was 9.47 bpm (3.35 to the
     governed reference).
   - The user flagged the rnb4 -> hiphop2 step: it lowered tempo and energy
     during up-regulation.
3. **Latin hi-hat.** `groovegen_pilot/composer.py` `_gen_latin` (v1.5) adds a
   closed hi-hat, pitch 42.
   - Hits per bar: quarters at tier 1, 8ths at tiers 2-4, 8ths plus 16th
     pickups at tier 5.
   - It makes no RNG draws, so every other note is unchanged. This was
     verified on 40 segments.
4. **Measured energy ladder.**
   - `groovegen_pilot/music_features_measured.py` (new) renders every cell
     exactly as `run_session_v2` plays it, over 8 melody-bank variants, and
     writes `groovegen_pilot/energy_table_v1.json` (new).
     - Table sha256: 31d441a8...; renders.csv sha256: da75717e...
     - Rendering is deterministic: two runs gave identical output.
   - Energy formula: E = 0.40 z(LUFS) + 0.25 z(drum onsets/s)
     + 0.20 z(played tempo) + 0.10 z(centroid) + 0.05 z(flux), with z taken
     over all 35 cells.
   - `groovegen_pilot/ladder.py` changes:
     - `build_ladder(features=, weights=, tie_band=)`; with no features it
       still uses the prior.
     - `load_energy_table(path)`.
     - `Ladder.noise_u`: the median within-cell SD of E, in u units (0.015).
     - Tie groups: cells closer than the tie band are ordered by tempo, so the
       slower cell sits lower.
5. **Runner (`groovegen_pilot/run_pilot_zero.py`).**
   - New flags: `--ladder measured|prior` (default measured) and `--energy-table`.
   - Latin is back: `LIVE_EXCLUDE_GENRES = ()`, so the live ladder has 29 cells
     and all 7 genres.
   - Saturation rotation is on by default (`--no-saturation-rotation` to
     disable); `--rotation-band-u` defaults to 2 x noise_u = 0.030.
   - New summary fields: `ladder_source`, `energy_table`,
     `energy_table_sha256`, `rotation_band_u`, `ladder_cells`.
6. **Trace.** `TraceRowV2` in `run_session_v2.py` has a new last column,
   `cell_u` (append-only).
7. **Test change** in `new_biofeedback/test_haptic_pacer.py` (the user has been
   told to review it).
   - The replay slew check now also accepts a fast pace step when the lead
     clamp lets go, provided the new pace equals the ramp reference `ref_bpm`.
   - This was triggered by today's recording: after a pause, a 1 bpm step.
   - Pacer code itself is unchanged.
8. **Docs.** The CLAUDE.md "Registered genres" note describes the measured
   ladder. The memory file `tempo-direction-preference.md` was updated, and
   `latin-off-live-ladder.md` was deleted.

### Offline evidence (commands were run and exited 0)

- **Regression gates:** hr_trajectory.py, test_faults_fixed.py,
  groovegen_project/groovegen/pd_controller.py, tier_mapping.py and scene.py
  all pass.
- **Other scripts:**
  - test_step5_5.py, ladder.py, control.py and test_estimator_hr_source.py pass.
  - `test_segment_renderer.py --sf2 ../soundfonts/Musyng_Kite.sf2` passes.
  - `new_biofeedback/test_haptic_pacer.py` passes (14 recordings) and
    `test_stable_hr.py` passes.
- **frozen_v2:** unchanged, 70 files, with shasums matching the pre-work baseline.
- **Fake-clock sims (45 segments; synthetic HR, NOT a human model):**
  - Plan invariance is 1.
  - No up-step drops tempo, drums and LUFS together.
  - The down run visits all 7 genres.
- **`run_pilot_zero.main()` end to end** (fake estimator, real renderer, `--no-play`):
  - The measured ladder loads, latin has 5 cells, rotation is on at 0.030, and
    `cell_u` matches the ladder on every row.
  - With `--haptic-pacing`, each segment target (74.0) is sent as the goal and
    logged as `haptic_goal_bpm`. Keepalives are at most 1.0 s apart, and a stop
    is sent at the end.

The scratch scripts behind these checks live in the previous session's
scratchpad (`/private/tmp/claude-501/.../scratchpad/`: sim_measured.py,
runner_haptic.py, ladder_preview.py, render_transitions.py). They may be gone,
so recreate them if needed.

## 2. Next step: L2 live run (the user runs it; you don't)

Give these commands again only after the user confirms points 2a-2c. Start the
estimator first, wait for steady HR, then start the runner.

Terminal 1 (estimator; owns the serial port and the motors):
```
cd /Users/daniel/Desktop/PhD/groove_gen_project/new_biofeedback
../.venv/bin/python3.12 ppg_live_estimator_adaptive_haptics_stable_hr.py --port /dev/cu.usbmodem2023101 --publish-udp 127.0.0.1:5005 --goal-udp 5006 --pace-max-seconds 660 --pace-invalid-window-s 60
```
Terminal 2 (GrooveGen; plays audio):
```
cd /Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot
../.venv/bin/python3.12 run_pilot_zero.py --sf2 ../soundfonts/Musyng_Kite.sf2 --hr-source estimator --haptic-pacing --subject-id daniel_L2 --session-minutes 10
```
Stop the estimator with Ctrl+C after the runner finishes.

Open questions the user was asked to confirm (answers not yet received):
- **2a. `--pace-max-seconds 660`:** the pacer default of 300 s stops pulses
  about halfway through a 10-min session.
- **2b. `--pace-invalid-window-s 60`:** by default, pacing ends for good after
  30 s of cumulative invalid HR over the whole run. Today's recording was about
  91% valid, roughly 50 s invalid per 10 min.
- **2c. Pacing goal vs music target:** the pacer clips its goal to HR at
  pacing start +/- 6 bpm (`PACE_MAX_GOAL_OFFSET_BPM`). With the music target
  at baseline + 10, the pulses aim lower than the music.
- **Other pacing bounds:** pace stays within +/-5 bpm of measured HR, ramps at
  most 6 bpm/min, and stays within 50-100 bpm.

What the run can show:
- the full live loop: HR in, goals out, HB pulses sent, music adapting;
- the alignment logs working live for the first time;
- how the measured ladder, rotation and latin hat sound live.

What it cannot show:
- that music or haptics raise HR (one run, no comparison condition);
- down-regulation;
- 15-min sessions.

## 3. After the run: analysis checklist

Use the trace-analysis skill. The session folder is
`groovegen_pilot/renders/pilot_zero/daniel_L2_<stamp>/`. It holds
session_trace.csv, summary.json, hr_polls.csv, estimator_rx.csv, baseline_hr.csv
and pilot.log. Estimator logs are in `new_biofeedback/ppg_live_recordings/`:
`ppg_live_raw_<stamp>.csv`, `ppg_hr_<stamp>.csv` and `ppg_haptic_events_<stamp>.csv`.

1. **Provenance:**
   - summary `condition` should be `music+haptic`;
   - `estimator_session.n_hb_sent > 0`;
   - `provenance_warnings` should be empty;
   - `ladder_source == measured`, and `energy_table_sha256` starts 31d441a8;
   - `rotation_band_u` is about 0.030.
2. **Plan invariance:** use
   `df.groupby('segment_idx')[plan_cols].nunique().max() == 1`, with plan_cols
   genre, tier, tempo_bpm, rung, seed, hr_bpm, hr_target_bpm, control_mode and
   cell_u.
3. **HR quality:**
   - fraction of fresh segments;
   - `ok_undoubled` count, and reject reasons in `ppg_hr_*.csv`;
   - compare against the Apple Watch reading, if the user reports it.
4. **Control metrics:** report error to the raw target and error to the
   governed reference separately, labelled. Compare with L1b (9.47 raw, 3.35
   governed), but it is not a controlled comparison.
5. **Ladder behaviour:**
   - genres visited;
   - counts of `rotate` and `mpc` modes;
   - up-steps that drop tempo, and whether drums or LUFS rose (use
     energy_table_v1.json);
   - how often the top cells (rock5, hiphop5) were reached.
6. **Haptics:**
   - pacer states over time (warmup, pacing, holding, paused, done) and their
     reasons;
   - goal clipping (`goal_clipped`);
   - pace vs HR (never more than 5 bpm apart);
   - whether pacing ended early (`max_duration`, `signal_lost`,
     `controller_lost`);
   - HB timing vs PPG motor artefact.
7. **Timing:** follow the trace `hr_decision_t_wall` -> hr_polls ->
   estimator_rx `t_ppg` -> raw `time_s` chain (see the CLAUDE.md "Alignment
   logs" note). Check inter-segment gaps if the user reports any audible
   silence.
8. **Record results:** update the CLAUDE.md Current Status/notes and
   SENSOR_NOTES.md with what was actually demonstrated, dated.

## 4. Open design questions to raise with the user (not decided)

- **hiphop 3-5 near the top of the ladder.** They are slow (90-96 bpm) but have
  the densest drums (about 6 hits/s) and are loud. So pop5 -> hiphop3 and
  rock4 -> hiphop5 -> rock5 swing about 30 bpm. The user liked the renders; if
  it bothers them live, the options are to cap hiphop at tier 2 on the live
  ladder or to raise the tempo weight.
- **Rotation does nothing at rock5.** The nearest cell (hiphop5) is 0.098 below
  it, well beyond the 0.03 band. A band of 0.10-0.16 alternates rock5 and
  hiphop5; 0.26 adds pop5.
- **Clipping:** some hiphop4, hiphop5 and rock5 renders peak at 0 dBFS. Use the
  render-audit skill; do not touch frozen_v2.
- **Flat loudness across tiers:** calm1/calm2 and pop's tiers are within 0.4 LU
  of each other, so their tier moves are near-inaudible in loudness.
- **Pacer hold preference** (memory `haptic-pacer-hold-preference`): the user
  wants pacing to keep pulsing through brief invalid HR. Deferred.
- **Stale table:** re-run `music_features_measured.py --sf2
  ../soundfonts/Musyng_Kite.sf2 --out renders/smoke_audit/energy_<ts> --table
  energy_table_v1.json` after any composer or cell change. It takes about 2.5 min.

## 5. Commits (propose only when asked, via safe-commit)

Uncommitted files that belong to this work:
- **estimator:** new_biofeedback/ppg_live_estimator_adaptive_haptics_stable_hr.py,
  test_stable_hr.py, test_haptic_pacer.py, haptic_pacer.py;
- **ladder, runner and trace:** groovegen_pilot/ladder.py, run_pilot_zero.py,
  run_session_v2.py, music_features_measured.py and energy_table_v1.json;
- **latin hat:** composer.py;
- **docs:** CLAUDE.md, SENSOR_NOTES.md.

Other modified files predate this work. Check their diffs before grouping them:
composer/__init__.py, control.py, crossfade.py, melody_bank.py,
segment_renderer.py, estimator_hr_source.py and test_estimator_hr_source.py
(the last two untracked).

Never stage `groovegen_pilot/renders/`, `profiles/`, `new_biofeedback/ppg_live_recordings/`
or the scratch smoke folders.

Suggested split: (1) estimator undoubling plus tests; (2) latin hi-hat;
(3) measured energy ladder, runner defaults and the `cell_u` trace column;
(4) docs.
