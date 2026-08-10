# GrooveGen — Copilot Workspace Instructions

You are assisting on GrooveGen, a real-time closed-loop physiological
music control system. A PhD student (solo, time-constrained) is the
sole developer. Read PROJECT_HANDOFF.md, AI_CONTINUATION_CONTEXT.md,
and PROJECT_HISTORY_AND_DECISIONS.md before making non-trivial changes.

## Locked constraints (do not relitigate)

- **Contribution type is SYSTEM/METHOD, not efficacy.** Never write code
  comments, docstrings, or log messages that claim the system "calms"
  or "regulates" a user. Correct framing: "tracks the arousal reference."
- **No vocals, ever.** No vocal synthesis, no lyric generation, no vocal
  samples.
- **No neural networks in the live control path.** Symbolic MIDI + FluidSynth
  only. MusicGen / AMT / MMM / any transformer-based generator is out of
  scope for the current milestone (v0.1-pilot / DIS 2027 submission).
- **The toy plant `dual_lever_plant_step` is FABRICATED.** Offline sim
  and ablation only. Never in the live path. Never cited as evidence of
  human response.
- **Sensor is a PPG source, not Polar H10.** Docs may still reference H10
  in older sections — treat PPG as the truth. Confirm sensor specifics
  in SENSOR_NOTES.md before making sensor-related changes.

## Development rules

- **Never hand-edit `.ipynb` files.** Edit the `build_notebook_*.py`
  builder, then rebuild. Plain `.py` modules are edited directly.
- **Reuse the validated `CascadeController` unchanged.** Do not create
  new controller classes. It is timescale-agnostic.
- **Do not create a new `harmony.py` module.** Chord/bass logic already
  partially exists in `symbolic_bed_proto.py` (build_pop / build_salsa /
  build_rnb / build_calm) and `genre_styles.py` (StyleSpec). Extend
  those; do not fork.
- **`chord_richness` in `symbolic_from_profile.map_profile` is a wiring
  gap** (computed then dropped on the floor). When the audio-quality
  pass starts, wire it into the existing builder path — do not build a
  parallel richness system.
- **Trace schema is append-only.** Never remove or rename columns in
  `groovegen_pilot/trace_schema.py`. New columns are additive.
- **Preserve within-segment plan invariance.** After any change touching
  the control loop, verify:
  `df.groupby('segment_idx')[plan_cols].nunique().max() == 1`

## Current milestone (M1)

Target: closed loop running end-to-end on live PPG, 15 min clean, in
each direction (up-reg 75→100 and down-reg 120→75), with zero deadline
misses, plan invariance holding, and no audio dropouts or crossfade clicks.

M1 build order (do not skip or reorder):
1. `groovegen_pilot/player.py` — SoundDevicePlayer (blocking queue =
   the clock) + NullPlayer (default, headless). Dependency-injectable.
2. `renderer.render_segment(tier, tempo_bpm, genre, n_bars,
   xfade_head_bars=1, layers=None)` — one MIDI, one FluidSynth call.
   `layers` is a list of callables; for M1 pass `[drums_layer]`.
3. `crossfade(prev_tail, next_head, n_beats=2, tempo_bpm)` — equal-power,
   downbeat-aligned, `assert abs(tempo_delta) <= 4`.
4. Nested `run_session()` — control fires ONCE per segment, trace row
   PER BAR, extended trace schema (8 new columns).

Audio quality (SF2 swap, chord/bass extension, humanization) is
explicitly deferred until AFTER M1 is signed off. Do not interleave
quality work with M1 plumbing.

## Regression gates (run all after any change)

```bash
python groovegen_pilot/hr_trajectory.py
python groovegen_pilot/test_faults_fixed.py
python groovegen_project/groovegen/pd_controller.py
python groovegen_pilot/tier_mapping.py
python groovegen_pilot/scene.py
