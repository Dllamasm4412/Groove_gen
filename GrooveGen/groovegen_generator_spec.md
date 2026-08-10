# GrooveGen — Parametric Symbolic Groove Generator: Engineering Spec (v2)

**Author:** Daniel Llamas
**Date:** 2026-06-02
**Purpose:** A deterministic, parametric MIDI drum-pattern generator with controllable "knobs" that map directly onto groove-relevant musical parameters, rendered to audio through a fixed drum kit. This is the stimulus instrument for an open-loop perturbation pilot and, later, the actuator layer of a closed-loop BBCI.

This spec deliberately replaces the MusicGen + Conformer + Sophia design. Rationale: groove-relevant control variables live in the symbolic layer (notes, timing, accents), not the audio-mix layer. A symbolic engine lets each knob *be* the thing you manipulate, with no inversion loss. See `grooveGen_reassessment_2026-06-02`.

---

## 1. Design principles

1. **Knobs are causes, not consequences.** Each control writes directly into the MIDI note grid. No audio-feature inversion anywhere in the pipeline.
2. **Timbre is held constant.** All conditions render through the *same* drum kit / soundfont at the *same* mix. This isolates rhythmic structure as the only thing varying across conditions — essential for clean causal attribution.
3. **Determinism with seeded stochasticity.** Given a parameter vector + random seed, the generator produces a bit-identical pattern. Any stochastic element (e.g., microtiming jitter, fill placement) is seeded so stimuli are exactly reproducible and re-renderable.
4. **One knob, one axis.** Knobs are designed to be as orthogonal as possible so single-knob dose-response sweeps are interpretable. Known couplings (e.g., density ↔ syncopation) are documented in §6.
5. **Loopable.** A 1-bar (or 2-bar) core pattern loops seamlessly to any stimulus length (target ~30 s) with no audible seam.

---

## 2. The five knobs

All knobs are normalized to a documented numeric range. Final level spacing comes from the companion literature doc (`groove_knob_literature.md`); ranges below are the engineering envelope.

| # | Knob | Symbol | Engine range | What it physically changes |
|---|---|---|---|---|
| 1 | Event density | `event_density` | onsets/bar (e.g. 4–32) | Number of drum onsets per bar (mainly hi-hat/ghost-note subdivision). |
| 2 | Swing amount | `swing_amount` | swing ratio 1.0–2.0 (50:50 → 66:34) | Delay applied to off-beat subdivisions (8th and/or 16th). |
| 3 | Syncopation level | `syncopation_level` | 0.0–1.0 (index) | Probability/weight of placing accents on weak metric positions and removing them from strong ones. |
| 4 | Microtiming variance | `microtiming_variance` | 0–~30 ms SD | Gaussian timing jitter (seeded) added per onset around the quantized grid. |
| 5 | Tempo | `tempo_bpm` | 60–160 BPM | Global playback tempo. |

> Note: per the microtiming literature debate (see companion doc), knob 4 may be designed to test a *near-zero-is-best* hypothesis rather than assumed to increase groove. The engine supports it either way; the experiment decides.

**Secondary / render-stage controls (not primary causal knobs):** `percussive_prominence` and `low_band_bias` — applied at the rendering/mix stage to bias timbre toward groove-inviting profiles. These are the two surviving Sophia→Senn audio actuators (`hpss_percussive_ratio`, `low_band_energy_ratio`), demoted to render parameters exactly as the reassessment recommends. Held constant during knob sweeps; optionally manipulated in a later study.

---

## 3. Pattern model

### 3.1 Grid
- Meter: 4/4 (extensible).
- Resolution: 16th-note grid → 16 steps/bar. Internally store at higher PPQ (e.g. 480) so microtiming and swing are sub-step continuous.
- Instruments (General MIDI percussion channel 10):
  - Kick (GM 36), Snare (GM 38), Closed Hat (GM 42), Open Hat (GM 46), optional Ghost/Rim (GM 37/39), optional Ride (GM 51).

### 3.2 Base pattern
A canonical backbeat skeleton is the anchor for all manipulations so the beat remains perceivable (beat salience preserved):
- Kick: steps 1, 9 (beats 1 and 3) baseline.
- Snare: steps 5, 13 (beats 2 and 4) — the backbeat.
- Hat: subdivision controlled by `event_density`.

All five knobs perturb *from* this skeleton rather than generating from scratch, which keeps the tactus stable (Madison-style beat salience) while the knobs vary.

### 3.3 Knob → grid transforms (engine semantics)

1. **`event_density`**: sets hi-hat (and ghost-note) subdivision and fill probability. Low = quarter-note hats; high = 16th hats + ghost snares. Implemented as a target onset count; onsets added at metrically-ranked positions (strong-before-weak) until target reached.
2. **`swing_amount`**: delays even-numbered subdivisions. `swing_amount` r means the off-subdivision is placed at fraction r/(1+r) of the beat-pair. Apply at the 8th or 16th level (configurable; default 16th per Senn `Swing_16`).
3. **`syncopation_level`**: uses a metric-weight model (Longuet-Higgins & Lee / Witek operationalization). Higher levels move accents/onsets from strong metric positions to weak ones and insert rests on strong positions, increasing the syncopation index in controlled increments. Engine exposes a target syncopation index and selects edits to hit it.
4. **`microtiming_variance`**: after quantized placement, add seeded Gaussian jitter (SD in ms) to each onset's time. SD = 0 → mechanically perfect. Kick/snare jitter can be scaled independently from hats.
5. **`tempo_bpm`**: sets the MIDI tempo / render playback rate. Does not alter the grid.

---

## 4. Rendering pipeline (Python)

```
parameter_vector + seed
        │
        ▼
[pattern_builder]  → pretty_midi.PrettyMIDI object (channel-10 drums)
        │
        ▼
[loop_to_length]   → repeat bars to ~30 s, seamless
        │
        ▼
[render]           → FluidSynth + fixed SF2 drum soundfont → WAV (44.1 kHz)
        │
        ▼
[mix_stage]        → optional percussive_prominence / low_band_bias (held constant for knob sweeps)
        │
        ▼
[loudness_normalize] → EBU R128 / -14 LUFS so loudness is constant across conditions
        │
        ▼
stimulus_<id>.wav  +  stimulus_<id>.mid  +  metadata row
```

**Stack:**
- `pretty_midi` — symbolic construction (stable, no TF dependency).
- `fluidsynth` (CLI or `pyfluidsynth`) + a fixed `.sf2` drum soundfont — deterministic render. (note-seq/GrooVAE deliberately avoided for the core engine; see §7.)
- `pyloudnorm` or `ffmpeg loudnorm` — loudness normalization (critical: prevents loudness from confounding groove ratings).
- `soundfile`/`numpy` — I/O.

**Why this stack:** stable, scriptable, Colab-friendly, fully reproducible, and stays in the same Python environment as your physiological-signal analysis. FluidSynth render of a 1-bar loop is millisecond-fast, so generating a full stimulus grid is cheap.

---

## 5. Stimulus-grid export

The generator's experiment mode produces a stimulus set + manifest for the pilot.

- **Single-knob sweep mode (primary):** hold 4 knobs at reference/center values, sweep 1 knob across its 4 levels. 5 knobs × 4 levels = 20 core conditions. With repeats/counterbalancing this is a clean repeated-measures design and avoids the combinatorial explosion of a full 4^5 = 1024 grid.
- **Optional factorial subset:** a Latin-square or fractional-factorial subset (~40 stimuli) if interactions are of interest.
- **Manifest:** `stimuli_manifest.csv` with one row per stimulus: `stimulus_id, event_density, swing_amount, syncopation_level, microtiming_variance, tempo_bpm, percussive_prominence, low_band_bias, seed, wav_path, mid_path, measured_loudness_LUFS, computed_syncopation_index, computed_swing_ratio`.
- **Built-in feature verification:** for each rendered stimulus, recompute the actual symbolic features (syncopation index, swing ratio, onset count, microtiming SD) from the MIDI and log them, to confirm the knob produced the intended manipulation (manipulation check).

---

## 6. Known knob couplings (document, don't pretend orthogonal)

- **Density ↔ Syncopation:** more onsets create more opportunities for syncopated placement. Mitigation: define syncopation as a *normalized* index relative to onset count, and verify via the manifest's `computed_syncopation_index` that density sweeps hold syncopation roughly constant and vice versa.
- **Swing ↔ Microtiming:** swing is a *systematic* timing offset; microtiming variance is *random* jitter. Keep them mechanically separate (swing = deterministic shift applied before jitter).
- **Tempo ↔ everything:** at very high tempo, dense 16th patterns become unplayable/blurred. Cap density-at-tempo combinations sensibly.

---

## 7. Optional Phase-2 enhancement: learned microtiming "feel"

Hand-built patterns are mechanically exact (good for clean manipulation). If you later want naturalistic human feel as a *condition* rather than a confound, GrooVAE / the Groove MIDI Dataset (Magenta) can "humanize" a quantized pattern by adding learned microtiming + velocity. Keep this isolated behind a flag — it introduces sampling variance and a stale TF dependency (note-seq last released 2022), so it is NOT part of the core deterministic engine. Treat learned feel as one more controllable knob to test, not a default.

---

## 8. Integration hooks for the closed loop (later)

The engine is built so the same `parameter_vector` that defines a stimulus can be updated in real time:
- `render_realtime(param_vector)` path that re-renders / re-triggers a short loop on parameter change (or, better, drives a live sampler so there's no re-render latency).
- Physio → groove-estimate → knob-adjustment → re-render is the eventual loop. For the open-loop pilot, only the offline `render()` path is needed; the realtime path is stubbed.
- Haptic sync: the symbolic grid already contains exact onset times, so beat-synchronized ESP32 haptic pulses can be derived directly from the kick/snare onset list — no audio beat-tracking needed. This is a side benefit of working in the symbolic layer.

---

## 9. Build order (engineering, decoupled from any paper deadline)

1. `pattern_builder` + backbeat skeleton → render one fixed loop to WAV. (Proves the pretty_midi → FluidSynth → loudness-normalized WAV path.)
2. Add knobs 5, 1, 2 (tempo, density, swing) — the mechanically simple ones.
3. Add knob 3 (syncopation) with the metric-weight model + manifest syncopation-index verification.
4. Add knob 4 (microtiming jitter, seeded).
5. Stimulus-grid export + manifest + manipulation-check logging.
6. (Later) realtime path + haptic onset export + optional GrooVAE humanize flag.

Each step is independently testable and produces audible output you can sanity-check by ear.
