# GrooveGen — AI Continuation Context

**Purpose:** everything another AI assistant needs to make *safe, correct* changes to this project
without re-deriving it. Read `PROJECT_HANDOFF.md` first for the "what/why"; this file is the
"how the code fits together + what you must not break."

**Snapshot:** 2026-08-05. Runtime: Google Colab, Python 3.12, T4 GPU, ONE session at a time.

---

## 0. Hard rules (violating these has broken things before)

1. **DEV RULE — notebooks are BUILT, not hand-edited.** For any `*.ipynb`, edit its builder
   (`build_notebook_*.py`) then rebuild the `.ipynb`. **Never edit a `.ipynb` directly.** Plain
   `.py` modules are edited directly and are fine.
2. **The user often CANNOT play bare WAV/MP3 inline.** Deliver **MP4** (or a zip) for anything the
   user must hear. **Verify EVERY MP4** before sharing:
   `ffmpeg -i X.mp4 -af volumedetect -f null -` → `mean_volume` must **NOT** be `-inf`.
3. **MP4 caption pattern:** ffmpeg `showwaves` + `drawtext` (font DejaVuSans-Bold). Write the
   filter to a file and use `-filter_complex_script vf.txt`. Use **literal UTF-8** characters, NOT
   `\u` escapes. Palette: `0x20808D`, `0xFFC553`, `0x6DAA45` on `0x171614` background.
4. **No vocals. Ever.** Locked constraint.
5. **No efficacy claims.** The contribution is the SYSTEM/METHOD. In code comments, docs, figures,
   and paper text: "tracks the arousal *reference*," never "calms/excites the user."
6. **The toy plant `dual_lever_plant_step` is FABRICATED.** Offline sim / ablation only. Never in
   the live path, never as evidence of human response.
7. **The real measurement must come from a real human** for the pilot (`use_synthetic_plant=True`
   is dev-only).

## 1. Signal flow (who calls whom)

```
HRSource → 30s artifact-gated trailing mean → HRArousalMapper.to_arousal(bpm)
  → HRTrajectory.step(hr_smoothed)  [reference governor, per SEGMENT] → arousal_setpoint
  → CascadeController.step(setpoint, measured)  [per SEGMENT] → {genre,tempo,density,tier}
  → TierMapper.step(density) → tier_applied
  → renderer.render_segment(tier, tempo, genre, n_bars)  [ONE MIDI, ONE FluidSynth call]
  → crossfade(prev_tail, next_head)  [equal-power, downbeat-aligned, 2 beats]
  → Player.push(audio)  [blocking = the clock]
Trace: one row PER BAR (append-only, crash-safe). Control: ONCE per segment.
```

## 2. Verified interfaces (from direct code inspection — trust these)

### `pd_controller.CascadeController` (in `groovegen_project/groovegen/pd_controller.py`)
```python
CascadeController(*, tempo_kp, tempo_kd, tempo_min=60, tempo_max=140,
                  max_step_bpm=8.0, density_kp, density_kd, density_min=3,
                  density_max=20, band=0.05, n_bars_saturated_for_tempo=3,
                  n_bars_saturated_for_genre=5, genre_order=None)
.reset(initial_genre_idx=0, initial_tempo=None, initial_density=None)
.step(setpoint, measurement) -> dict{genre, tempo_bpm, density, tier_that_acted}
```
- **Timescale-agnostic:** `dt` = seconds per update; "bar" appears only in docstrings/counters.
  The segment redesign reuses this class UNCHANGED except for constants — **do not add new
  controller classes.**
- `genre_order` default is now `["calm","r&b","pop","latin"]` (fault 0a fix).
- Direction now branches on **signed error**, not `setpoint<0.5` (fault 0b fix).
- Pilot constants (set at construction / via config): `max_step_bpm=4`,
  `band = 3.0/(max_hr-resting_hr)`, `n_bars_saturated_for_tempo=1`,
  `n_bars_saturated_for_genre=2`.

### `HRTrajectory` (reference governor, `groovegen_pilot/hr_trajectory.py`) — NEW, verified green
```python
@dataclass
HRTrajectory(goal_bpm, segment_seconds=30, ramp_bpm_per_min=6, deadband_bpm=3,
             max_lead_bpm=8, terminal_tau_s=60, baseline_bpm=None)
.initialize(baseline_bpm)          # iso-principle: start at participant baseline
.step(hr_smoothed_bpm) -> dict{
    segment_idx, ref_bpm, goal_bpm, dist_bpm, sign, eff_rate_bpm_per_min,
    ramp_frozen, traj_error_bpm, lead_clamped, deadband_bpm, in_deadband }
```
- Sits UPSTREAM of `HRArousalMapper`. Fully **bidirectional** (same code path both directions).
- Self-test: `python groovegen_pilot/hr_trajectory.py` (up-reg 75→100, down-reg 120→75,
  progress-gate freeze for a non-follower). Must stay green.

### `HRArousalMapper` (in `groovegen_project/groovegen/hr_source.py`)
`arousal = clip((bpm - resting_hr)/(max_hr - resting_hr), 0, 1)`. Per-subject, calibrated once at
session start. Report both `hr_bpm_raw` and `arousal_measured` in every trace row.

### `renderer.SymbolicBarRenderer` (`groovegen_pilot/renderer.py`)
```python
SymbolicBarRenderer(sf2=SF2_DEFAULT, sr=44100, gain=0.8, polish=False)
.render_bar(tier, tempo_bpm, genre, bar_idx, n_bars) -> stereo float32 | None
# TODO (Phase 2A-4): .render_segment(tier, tempo_bpm, genre, n_bars, xfade_head_bars=1)
#   = ONE PrettyMIDI + ONE render_midi() call. Factor _bar_midi body into _write_bar(...).
```
- `RUNG_TIER_CAP = {"calm":2, "r&b":4, "pop":5, "latin":5}` (fault-bonus fix), applied in
  `_bar_midi` via `tier = min(int(tier), RUNG_TIER_CAP.get(g, 5))`.
- `_norm_genre` → `pop | r&b | latin | calm`. `_drum_genre` → `salsa | pop` (only latin→salsa).
- SF2 at `/usr/share/sounds/sf2/FluidR3_GM.sf2` (override on Colab). Font at
  `/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf`.

### `symbolic_bed_proto.polish(mix, normalize=True, gain=1.0)` (`symbolic_bed_proto.py`)
- `normalize=False` path (fault 0c fix): use fixed `gain` for per-segment renders so there is **no
  loudness step at crossfades**. Default `normalize=True` preserves back-compat.

### `symbolic_tiers_demo.drum_bar_tier(d, t0, spb, tier, genre="pop", bar_idx, n_bars)`
- Special-cases `genre=="salsa"`. Fires fill @ `bar_idx % 4 == 3`, crash @ `bar_idx == n_bars-1`.
  Pass `bar_idx=bar_in_segment, n_bars=bars_per_segment` so these cues fire per SEGMENT.

### `symbolic_from_profile.map_profile(feat)` (`symbolic_from_profile.py`)
- Input keys: `tempo_final, spectral_centroid_mean, hpss_harmonic_ratio, hpss_percussive_ratio,
  onset_density, lhl_syncopation_mean`.
- Output: `genre, bpm, start_tier, transpose, chord_richness, _src`.

### `scene.Scene` / `scene.scene_from_features(feat)` (`groovegen_pilot/scene.py`)
- Once-per-session INITIAL conditions only (genre/bpm/start_tier/transpose).
- **STALE DOCSTRING:** it still says "genre-morph mid-session is a locked-out confound." The
  segment redesign REVERSES this (genre ladder is now an actuator). Rewrite that docstring when you
  touch it — do not treat the docstring as current policy.

### `run_session.py` (`groovegen_pilot/run_session.py`)
- Line ~157: `gi = ctrl.genre_order.index(cfg.genre) if cfg.genre in ctrl.genre_order else 0`.
- Phase 2A-5 TODO: nest the loop so **control fires once per segment** (`ctrl.step()`), while a
  trace row is written **per bar**.

### Trace schema (`groovegen_pilot/trace_schema.py`) — SINGLE SOURCE OF TRUTH
- One row per bar, flushed every bar. Extend **append-only**. The 8 irreducible new columns for the
  segment redesign: `segment_idx, is_segment_boundary, hr_ref_bpm, hr_traj_error_bpm, in_deadband,
  ladder_rung, pregen_ms, underrun`.
- Existing columns include: `wall_t, bar_idx, hr_bpm_raw, arousal_setpoint, arousal_measured,
  error, density_cmd, tier_cmd, tier_applied, tempo_cmd, tempo_applied, genre, tier_that_acted,
  render_ms, deadline_miss, seed, code_version`.

### `TierMapper` (`groovegen_pilot/tier_mapping.py`)
- `density_to_tier_raw(density, dmin=3, dmax=20)` and stateful `TierMapper(...).step(density) ->
  (tier_cmd, tier_applied)` with Schmitt hysteresis + ≤1-tier/bar rate limit. Rails (1 and 5) stay
  reachable. Keeps controller density CONTINUOUS; quantize to tier only at render time.

## 3. Invariants a change must preserve (machine-checkable where noted)

- **Within-segment plan invariance:** `df.groupby('segment_idx')[plan_cols].nunique().max() == 1`.
  Nothing in the plan (genre/tempo/tier) changes inside a segment.
- **Genre-change rate:** ~3–5 changes / 15 min with comfort mechanisms on (deadband + dwell).
- **Ladder monotonicity:** effective energy is non-decreasing across rungs calm→r&b→pop→latin
  (guaranteed by `RUNG_TIER_CAP`). calm@5 effective tier ≤ r&b@2.
- **No deadline misses:** `render_ms` per bar < bar duration; whole-segment render ≪ 30 s.
- **Bit-identical headless runs:** default `Player = NullPlayer`, fixed `seed`, so CI is
  reproducible. Live audio (`SoundDevicePlayer`) is opt-in.
- **Crossfade safety:** `assert tempo_delta <= 4` before a crossfade (equal-power, downbeat-aligned,
  2 beats, no time-stretch).

## 4. Regression gates — run these after ANY change, all must pass

```bash
python groovegen_pilot/hr_trajectory.py              # reference governor (bidirectional)
python groovegen_pilot/test_faults_fixed.py          # the three-fault regression suite
python groovegen_project/groovegen/pd_controller.py  # controller __main__ self-test
python groovegen_pilot/tier_mapping.py               # tier mapper anti-chatter self-check
python groovegen_pilot/scene.py                      # scene selector smoke test
```

## 5. Gotchas / landmines (learned the hard way)

- **±3 BPM deadband on RAW HR is below the RSA noise floor** → the ladder pins to a rail in ~3 min.
  ALWAYS feed the 30 s artifact-gated trailing mean (reject RR outside [300,2000] ms and >20% from
  running median). Log `hr_bpm_raw` AND `hr_bpm_smoothed`.
- **A setpoint crossing arousal 0.5 mid-session used to flip the ladder direction** (fault 0b). Any
  new direction logic must branch on **error sign**, never on absolute setpoint.
- **Per-call peak normalization causes an audible loudness jump at every seam** (fault 0c). Use
  `polish(normalize=False, gain=...)` for segment renders.
- **A tier-5 calm segment can out-energize r&b** unless `RUNG_TIER_CAP` is applied (fault-bonus).
- **`requirements.txt` pins matter** for the MusicGen bed path: `transformers==4.44.2`,
  `huggingface_hub>=0.23.2,<0.26`, `tokenizers<0.20` (notebooks self-heal if the pins drift).
- **Colab-BLE bridge is finicky.** Live Bluetooth-LE HR into cloud Colab may add latency or fail;
  keep an **offline RR-replay path** so development and the paper survive a hardware delay. The user
  likely runs participants on a LOCAL laptop (no realtime audio on Colab).

## 5b. Import paths (verified from the extracted zip)

The pilot modules live in `groovegen_pilot/` and import each other by bare name, plus a few root
modules (`symbolic_bed_proto`, `symbolic_from_profile`, `symbolic_tiers_demo`) and the validated
controller. Set `sys.path` to include, in order: `groovegen_pilot/`, repo root, and
`groovegen_project/groovegen/`. Then `import pd_controller` / `import hr_source` resolve directly.

**Gotcha:** do NOT `from groovegen import pd_controller` against the LEAN zip — its
`groovegen_project/groovegen/__init__.py` eagerly imports submodules that the lean zip omits
(only `pd_controller` + `hr_source` are bundled). Either import the two modules by bare name (add
`groovegen_project/groovegen/` to `sys.path`), or use the FULL zip which contains the whole
`groovegen` package. All eight pilot modules + the controller import clean this way (verified).

## 6. What's built vs. what's next (as of snapshot)

- **Built + green:** Phase 1 latency/tracking validation; fault fixes 0a/0b/0c/bonus;
  `hr_trajectory.py` reference governor (bidirectional).
- **Next (Phase 2A-3→5):** `player.py` (`SoundDevicePlayer`+`NullPlayer`);
  `renderer.render_segment()` + `crossfade()`; nested `run_session()` (control/segment, trace/bar)
  + extended trace schema.
- **Then (2B):** sim validation (invariance check, genre-change rate, latency + transition-audit
  figures) + audible bidirectional transition demo MP4.
- **Then (3):** thin operator UI; tag `v0.1-pilot`.
- **Hardware:** order the Polar H10 (longest-lead; needs real RR intervals).
