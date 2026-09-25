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

## Notes
- **Registered genres**: calm, lofi, rnb, pop, latin (hiphop and rock cells exist but unregistered—see genre-integration for wiring).
- **Regression gates** (run after any change): `hr_trajectory.py`, `test_faults_fixed.py`, `pd_controller.py`, `tier_mapping.py`, `scene.py`.
- **Inter-segment gap** (~6.2–6.7 s without music) is still present. Root cause is mostly rendered WAV tail (2.7–6.0 s below −50 dBFS after the last bar, passed through by CrossfadeMixer), plus ~0.5–1 s serial render time. A background render thread alone recovers only ~1 s; trimming or overlapping the tail is required. Use render-audit.
