# CLAUDE.md

## Project Identity
GrooveGen is a real-time closed-loop physiological music control system that adapts a symbolic MIDI bed (drums, bass, harmony) to PPG-derived signals per segment within a 15 min session. The live runner currently uses LadderMPC (genre x tier rungs); the CascadeController (tempo, density, genre) is validated offline and not yet wired live.

## Environment
- **venv**: `.venv/bin/python3.12` (Homebrew Python 3.12.13 via symlink)
- **Activation**: `source .venv/bin/activate` (macOS/Darwin)
- **Git remote**: `git@github.com:Dllamasm4412/Groove_gen.git` (main branch)

## Core Pipeline
Current runnable path (`groovegen_pilot/run_pilot_zero.py` → `run_session_v2`):
PPG (XIAO M0 serial) → SerialPPGSource → LadderMPC (`groovegen_pilot/control.py`; ladder of genre x tier rungs, RLS gain + reference governor) → SymbolicSegmentRenderer (MIDI → FluidSynth WAV) → CrossfadeMixer → player (blocking queue) → live audio + trace.

CascadeController (`groovegen_project/groovegen/pd_controller.py`) + HRTrajectory + tier_mapping are validated offline (self-tests, notebooks, `app_experiment.py` Gradio UI) but are NOT yet wired to live PPG or the renderer in any runnable script.

## Non-Negotiable Rules

### Scope & Claims
- **No vocals, ever.** No vocal synthesis, no lyric generation, no vocal samples.
- **Symbolic MIDI + FluidSynth only in live control path.** No neural networks, MusicGen, AMT, or transformers in the real-time loop. Symbolic beds deferred to M1 post-sign-off.
- **Never claim "calms" or "regulates" a user.** Frame as: "tracks the arousal reference" or "adapts music parameters in response to PPG."
- **Dual-lever plant is FABRICATED.** Offline sim and ablation only. Never in live path. Never cited as evidence of human response.
- **PPG sensor, not Polar H10.** Confirm sensor specifics in SENSOR_NOTES.md before sensor-related changes.

### Artifacts & Integration
- **groovegen_pilot/profiles/** and **groovegen_pilot/renders/** are gitignored. Do not commit recordings, PPG data, or audio outputs.
- **Frozen renders (frozen_v2/)** are read-only verification assets. Never modify; only diff outputs against them.
- **No auto-playback.** Player defaults to NullPlayer (headless). Require explicit SoundDevicePlayer config.
- **No hand-edit .ipynb.** Edit the `build_notebook_*.py` builder; rebuild. Plain `.py` modules are edited directly.

### Code Reuse
- **CascadeController is frozen.** Reuse unchanged. Do not create new controller classes.
- **No new harmony.py module.** Chord/bass logic is in `symbolic_bed_proto.py` (build_pop, build_salsa, build_rnb, build_calm) and `genre_styles.py` (StyleSpec). Extend those; do not fork.
- **Chord richness wiring gap:** `chord_richness` in `symbolic_from_profile.map_profile` is computed then dropped. Wire it into the existing builder path during audio-quality pass; do not build parallel richness.
- **Trace schema is append-only.** Never remove or rename columns in `groovegen_pilot/trace_schema.py`. Add columns only.
- **Within-segment plan invariance:** After any control-loop change, verify: `df.groupby('segment_idx')[plan_cols].nunique().max() == 1`

### Git & Verification
- **No git actions without explicit approval.** Do not stage, commit, or push—only propose with safe-commit skill.
- **No verification claims without command evidence.** If you claim a test passed, show the run output. Use groovegen-verify skill.
- **Pretty-MIDI ↔ music21 round-trip is prohibited.** These libraries have destructive conversions. Preserve MIDI provenance in FluidSynth render path.
- **No emojis unless the user asks.** Keep output prose-based and scannable.

## Available Skills
Reference these in `.claude/skills/` for detailed workflows—do not duplicate their content here:

- **controller-change**: Safely assess/implement CascadeController, governor, arousal modes, ladder transitions, control metrics.
- **genre-integration**: Inspect/plan/implement genre registration into GENRE_CFG, generators, adapters, renderer paths.
- **groovegen-verify**: End-of-task verification using existing environment, targeted evidence, deterministic disposable artifacts.
- **render-audit**: Audit MIDI/audio rendering, soundfont use, tempo, crossfades without modifying frozen_v2/.
- **research-protocol-check**: Classify work scope (engineering vs. current-pilot vs. amendment-required).
- **safe-commit**: Propose safe, reviewable commits without staging generated/private artifacts.
- **trace-analysis**: Analyze session traces, timing, controller behavior, latency with reproducible, protocol-aware outputs.

## Current Status
M1 active. Verified: HRTrajectory self-test converges in both directions (75→100, 120→75) offline; LadderMPC runner closes the loop on live PPG (pilot zero ≤10 min, up-regulation only; Stage 0 re-check 2026-09-24, 4 segments, plan invariance holds, audio confirmed by ear). NOT yet demonstrated: CascadeController on live PPG, 15-min sessions, down-regulation on live physiology, gap-free audio. Subject-zero pilot runner and gate widget v2 recently added. In progress: haptic pacing (`new_biofeedback/`), engineering validation on developer only.

**v2 generation (branch `v2-controlled-live-generation`, 2026-10-05).** Full detail in `groovegen_pilot/V2_CONTEXT.md`; read its last sections, not the whole file.
- Committed: opt-in stateful generation, `--generator v2c` (default `bank` byte-identical); one SessionComposer per session; development policies for calm, lofi, rnb, pop, latin, hiphop (melody only); rock has no policy. Latest commits b72ec6e (Pop+Latin), e330677 (live integration). First live v2c developer run 2026-10-05 (feedback below).
- Rock presentation (developer decision 2026-10-05, uncommitted, applies to both `bank` and `v2c`):
  - `GENRE_CFG['rock']`: guitar unchanged (program 26), `drum_velocity_scale=1.20`, and per-tier `render_gain_db` {1: +4, 2: +3, 3: +3, 4: +1.5, 5: 0} dB. The developer chose rock:1 by ear; tiers 2-5 keep the same offset above their neighbours.
  - The gain travels as a MIDI text event (`composer.render_directive`). The renderer then renders that MIDI in float, applies the gain and a -1 dBFS limiter. Every other genre's render is bit-identical.
  - Rock identity fixtures have been regenerated (only Rock keys changed).
- After the first v2c live run (2026-10-05, uncommitted; detail in V2_CONTEXT.md "After the first v2c live run"):
  - Energy is measured WITHOUT the Rock presentation gain (`music_features_measured.energy_audio`; certification too). Table re-measured, only Rock changed. Live rungs: rock1 8, rock2 15, rock3 21, rock4 25, rock5 26; hiphop3 (22) is still above pop5 (20) by measurement.
  - `--ladder ear` + `energy_order_by_ear.json`: a by-ear order with the measured u values (u set unchanged).
  - Saturation rotation no longer ping-pongs: `ControllerConfig.rotation_no_repeat=2` (0 = old pick).
  - Latin v2c.latin.1: piano and bass development (pitch-only, chord tones, exact register, only measured-balanced pattern pairs); nylon unchanged. Certification residual: pulse_clarity shift latin:1-2 over allowance.
- Final perceptual ladder (2026-10-06, frozen): `energy_order_by_ear.json` from `ladder_min_change.py freeze` (the minimum-change re-order under the four blind listening relations that replicated; detail in V2_CONTEXT.md). Live: `--ladder ear`.
- Rotation keeps the controller direction (2026-10-06): during rotation, genre variety never reverses a move the MPC requested; holds keep the variety pick.
- Master headroom (2026-10-06): `segment_renderer.MASTER_GAIN_DB = -2.5` on every rendered segment (hiphop:4-5 clipped in fluidsynth 16-bit). Energy measurement renders the reference level, so the table, ladder and envelopes are unchanged.
- Next: developer fills the by-ear ratings, then `energy_by_ear.py apply`, then a live run with `--generator v2c --ladder ear` (the developer runs live PPG).

## Notes
- **Registered genres**: calm, lofi, rnb, pop, latin, hiphop, rock (35-cell ladder by default; the live runner uses the 27-cell tier-capped ladder with all 7 genres, `--initial-cell lofi:3`; latin capped at tier 3 live only via `LIVE_TIER_CAP_OVERRIDES` in run_pilot_zero.py, 2026-09-28, because the developer hears latin as rnb-level energy). Live cell energy is MEASURED by default (`--ladder measured`, 2026-09-25): `energy_table_v1.json` from `music_features_measured.py` (rendered LUFS 0.40, drum onsets/s 0.25, played tempo 0.20, centroid 0.10, flux 0.05, z over 35 cells; near-ties within the median within-cell SD ordered by tempo); `--ladder prior` keeps the old unmeasured prior. Saturation rotation is on live, band 2x within-cell SD (0.03 u); since 2026-09-28 it releases to the MPC when the MPC asks for a cell beyond the band in the stuck direction (before, a collapsed gain mid-ladder locked L2 sessions in hiphop2/rock1/latin1; decision replay of the L2 runs in control.py comment). latin has a closed hi-hat layer (composer v1.5). Re-run `music_features_measured.py --table` after any composer/cell change or the table goes stale. hiphop and rock render through their frozen cell modules (`composer/hiphop_cell.py`, `composer/rock_cell.py`) and take a per-tier tempo from `GENRE_CFG[...]['tier_tempo']`. Registration sites: `GENRE_CFG`/`_GENERATORS` (composer.py), `_BRIGHTNESS`/`_RMS_BASE` (ladder.py), `energy_table_v1.json` (re-measure), `RUNG_TIER_CAP`/aliases (segment_renderer.py), `_GENRE_HASH` (melody_bank.py).
- **Regression gates** (run after any change): `hr_trajectory.py`, `test_faults_fixed.py`, `pd_controller.py`, `tier_mapping.py`, `scene.py`.
- **Estimator link** (`--hr-source estimator`, `--haptic-pacing`): the new_biofeedback estimator owns the serial port and HR/RR; GrooveGen gets HR over localhost UDP (`estimator_hr_source.py`, protocol in `new_biofeedback/groovegen_link.py`) and sends pacer goals. Runner defaults: 1 Hz HR polling with a 10 s median, stale HR -> `stale_hold`, crossfade `tail_out`. No valid HR for 5 s logs "ADJUST THE PPG SENSOR" (every 10 s) and "PPG signal back" on recovery; the baseline pauses (no longer aborts) and the session holds its cell. A GrooveGen stop ends that pacer only; the next runner's goal arms a fresh one (before 2026-09-28 a stop, e.g. from an aborted baseline, disabled pacing until the estimator restarted). The runner warns "HAPTICS NOT RUNNING" after segment 1 if `--haptic-pacing` is set and the estimator reports no pacer. Offline checks: `test_estimator_hr_source.py`, `new_biofeedback/test_haptic_pacer.py`, `new_biofeedback/test_stable_hr.py` (beat-doubling gate; replay any raw CSV with `new_biofeedback/replay_stable_hr.py`). Run live once without haptics (L1, 2026-09-24): HR feed worked, but doubled-beat HR reached the controller (see SENSOR_NOTES.md); gate and a signal-quality floor (rejects pulse-free noise; `aperiodic` / `weak_pulse`) added afterwards. First L1b attempt (2026-09-25, HR ~80 after cycling) aborted in baseline: the gate rejected most windows as doubled; doubled windows are now re-detected at the true period (`ok_undoubled`). L1b rerun 2026-09-25 11:46 (10 min, music, no haptics): 30/30 segments fresh HR; developer reports HR matched the Apple Watch throughout (by eye, not logged).
- **Alignment logs** (offline-verified 2026-09-25, not yet run live): estimator writes `ppg_hr_<stamp>.csv` (every 1 Hz HR update: MCU `time_s` + host `wall_time_s`, reject `reason`, `double_gain`, `period_ac`, `pulse_sd`, serial backlog, HB pulses in window) and `sent`/`wall_time_s` columns in the haptic events CSV. A pilot session folder adds `estimator_rx.csv` (every datagram verbatim + receive time), `hr_polls.csv` (every HR read; with trace `hr_decision_t_wall` it reproduces each segment's `hr_bpm` exactly), and summary `condition` / `audio_output` / `estimator_session` (from HB pulses actually sent, not flags), also written on Ctrl+C. Map trace -> raw PPG: trace `hr_decision_t_wall` -> `hr_polls` -> `estimator_rx` `t_ppg` -> raw `time_s`; fit wall vs MCU per `log_stamp`.
- **Inter-segment gap**: fixed offline, NOT yet confirmed live. `run_session_v2` cuts each render to its bars + one crossfade (fluidsynth release tail was 2.7–7.2 s below −50 dBFS) and wakes `render_lead_s=3.0` before queued audio runs out so the next render (0.6–1.7 s) is queued in time. Offline 24-segment sim: 0 underruns, ~0.1 s mean silence per boundary (old: ~4 s). Trace `wall_time`/`session_time` now mark when bars play, not when they were enqueued.
