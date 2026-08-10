# Notebook 13 — Three-Tier Cascade Closed-Loop Control Simulation: Findings

**Location:** `/home/user/workspace/groovegen_project/`
**Notebook:** `notebooks/13_cascade_closed_loop.ipynb` (9 cells, pure simulation — no MusicGen compute)
**Extended module:** `groovegen/pd_controller.py`

---

## 1. New API added to `pd_controller.py`

`PDDensityController` was **not modified** — it remains frozen and ear-validated, per the task constraint. Everything below is additive.

### `GENRE_ENERGY_ORDER`
```python
GENRE_ENERGY_ORDER = ["r&b", "pop", "latin"]  # ascending energy/arousal
```
A single named, trivially swappable constant. Comment in-code documents that this is a **personalizable default**, not a universal law — Latin has low support (N=19) vs. pop (N=244) and r&b (N=78), so the only strongly-supported claim from the underlying corpus analysis is "R&B is the calmest." Swapping to a different ascending-energy ordering is a one-line change.

### `TempoController`
```python
TempoController(kp, kd=0.0, tempo_min=60, tempo_max=140, max_step_bpm=8, dt=None)
  .reset(initial_tempo=None)
  .step(setpoint_arousal, measurement_arousal) -> float  # tempo_bpm
  .at_min / .at_max  # saturation flags
```
PD control on tempo, with a hard per-call step cap (`max_step_bpm`) so tempo moves in small, musically-plausible increments rather than jumping — this produces the required stairstep (quantized-to-bed-segment) shape rather than a smooth curve.

### `synth_hr(n_bars, resting_bpm=72.0, kind="calm_step", seed=0)`
Thin convenience wrapper around the existing `synth_physiology` generator, used to seed initial tempo from a simulated resting heart rate (60–100 BPM range) rather than an arbitrary constant.

### `GENRE_EQUILIBRIUM_BAND`
```python
GENRE_EQUILIBRIUM_BAND = {
    "r&b":   (0.10, 0.68),
    "pop":   (0.18, 0.80),
    "latin": (0.28, 0.95),
}
```
Each genre occupies a `[floor, ceiling]` sub-range of the 0–1 arousal scale reachable by its tempo/density levers. This is what gives a genre switch an actual causal effect on the plant: moving to a calmer genre lowers the ceiling the inner loops can reach, so a persistently-saturated tempo/density pair needs the genre tier to keep converging. Values are illustrative/tuned for a visibly convergent demo, **not** measured from real listener data (documented in-code).

### `dual_lever_plant_step(arousal, genre, tempo_bpm, density, *, tempo_min, tempo_max, density_min, density_max, relax=0.10, w_tempo=0.5, w_density=0.5, external_drive=0.0, noise=0.0)`
Toy plant: relaxes `arousal` toward a genre-dependent equilibrium point (`floor + (ceil-floor) * lever_norm`, where `lever_norm` blends normalized tempo and density) at rate `relax` per bar, plus optional noise/external drive. This is what makes both tempo and density actually push the same underlying arousal state, and is what the naive-parallel contrast exploits to show a fight.

### `CascadeController`
```python
CascadeController(
    tempo_kp=4.0, tempo_kd=1.0, tempo_min=60, tempo_max=140, max_step_bpm=8,
    density_kp=2.5, density_kd=0.8, density_min=3, density_max=20,
    band=0.05, n_bars_saturated_for_tempo=3, n_bars_saturated_for_genre=5,
    genre_order=None,   # defaults to GENRE_ENERGY_ORDER
)
  .reset(initial_genre_idx=0, initial_tempo=None, initial_density=None)
  .genre  # current genre string
  .step(setpoint, measurement) -> {"genre", "tempo_bpm", "density", "tier_that_acted"}
```
Composes GENRE → TEMPO → DENSITY as a true cascade, not three independent loops:
- **Density** (existing `PDDensityController`, unchanged) always runs and is the fast, fine-grained lever — it gets first crack at every bar's error.
- **Tempo** only engages once density has been saturated at a rail for `n_bars_saturated_for_tempo` consecutive bars (hysteresis/consecutive-bar counter) — it does not chase the same raw error density is already handling.
- **Genre** only advances/retreats once tempo has *also* been saturated for `n_bars_saturated_for_genre` consecutive bars — the coarsest, slowest lever acts last and least often.
- A one-slot **"committed_next_tempo" buffer** implements generate-ahead/double-buffering: tempo decided from the arousal state at the start of segment *n* is what plays in segment *n+1* (one-segment commitment lag), matching real bed-generation constraints.
- `tier_that_acted` is returned every step for auditability/plotting.

This is the **anti-fight discipline** the task calls out: no tier independently recomputes from the global goal — each outer tier only fires when the inner tier(s) have demonstrably failed to hold the band alone, so the loops never race each other over the same error on the same timescale.

---

## 2. Self-test confirmation

`python3 groovegen/pd_controller.py` → **ALL ASSERTIONS PASSED** (both tiers):
- `PDDensityController` tier: unchanged, still passes (mean density 3.00 during high-arousal bars vs. 12.67 during low-arousal bars).
- `TempoController` / `CascadeController` tier: tempo trace respects `max_step_bpm=8` and stays in `[60,140]`; a 60-bar down-regulation run (calm_setpoint=0.15, start arousal=0.95) visits genres `['latin','pop','r&b']` in order, ends at tempo=60.0, density=3, arousal=0.1751, `|error|=0.0251`.

---

## 3. Cascade vs. naive-parallel convergence numbers

Contrast demo (90 bars, setpoint=0.15, start arousal=0.95, latin start genre, shared seed):

| Metric | Cascade | Naive parallel | Ratio |
|---|---|---|---|
| Final \|error\| | 0.0448 | 0.3023 | cascade **6.7×** tighter |
| Tail (last 30 bars) mean \|error\| | 0.0294 | 0.2320 | — |
| Tail (last 30 bars) std (variance proxy) | 0.0131 | 0.0837 | cascade **6.4×** lower variance |

The naive-parallel strawman recomputes a single full-authority lever from scratch every bar as a plain proportional response to a **2-bar-stale** measurement (`lever_norm = clip(0.5 + 1.5·error, 0, 1)`), with no persistent per-tier state and no saturation gating — modeling "tempo and density react in lockstep, at full authority, to the same raw error." This produces a genuine, sustained delay-induced limit cycle (visible sawtooth oscillation), while the cascade converges smoothly and tightly to the setpoint. This is the anti-fight property the notebook sets out to demonstrate, and both assertions (`cascade tail_std < naive tail_std`, `cascade final_err < naive final_err`) pass.

Up-regulation run (100 bars, setpoint=0.85, start arousal ~0.15 seeded from resting HR 62 BPM): converges to `|error|=0.0547`, and genre climbs `r&b → pop → latin` exactly matching `GENRE_ENERGY_ORDER`, confirming the up/down symmetry of the cascade logic.

---

## 4. Verification checklist

- [x] `pd_controller.py` self-test run — **ALL ASSERTIONS PASSED** (both tiers).
- [x] `build_notebook_13.py` executed — writes `notebooks/13_cascade_closed_loop.ipynb`, 9 cells.
- [x] `nbformat.validate()` — passes (nbformat 4.5).
- [x] `ast.parse()` on all 5 code cells (Colab-only `!pip`/`files.*` lines stripped first) — all parse cleanly.
- [x] End-to-end execution in sandbox at `/home/user/workspace/step_nb13_outputs/run_all.py` — down-regulation converges, contrast demo assertions pass (cascade 6.4× lower variance, 6.7× tighter final error), up-regulation converges with correct genre order.
- [x] Visual inspection of all 3 saved PNGs — no clipped/overlapping text (one clipping issue on the down-regulation plot's rotated y-axis label was found and fixed by shortening the label text and adding `pad_inches=0.3` to the `savefig` call; re-rendered clean).

---

## Post-delivery layout fix (down-regulation plot)

After initial delivery, the down-regulation plot (`cascade_downreg_timeseries.png`) was found to have all 3 panels squashed into the top ~15% of their vertical space, with the "pop"/"r&b" genre-switch labels floating in dead space. Root cause: the genre-switch label text in panel 2 was placed at a hardcoded data-coordinate y-position (`cascade.tempo_ctrl.tempo_max - 4` = 136), far above the panel's actual tempo range (60-88 BPM in this run). `fig.tight_layout()` expanded its bounding-box calculation to accommodate that far-out-of-range text, which collapsed all three (`sharex`-linked) panels down to ~7% of the figure height each.

Fix applied identically in both `build_notebook_13.py` and the sandbox `run_all.py` (down-regulation cell only — the up-regulation cell, which already used an in-range anchor `tempo_min + 4`, was left untouched):
- Genre-switch labels now use `ax2.get_xaxis_transform()` (x in data coordinates, y in axes-fraction 0-1) and are placed at `y=0.95`, i.e. near the top of whatever the panel's actual autoscaled range turns out to be, rather than a hardcoded absolute data value.
- Removed the hardcoded `ax3.set_ylim(0, 21)` on the down-regulation density panel so it autoscales tightly to its own data (which spans ~3-16 in this run) instead of the full controller-limit range.

Re-rendered and visually confirmed: all three down-regulation panels now autoscale tightly to their own data (arousal ~0.09-0.95, tempo ~60-89, density ~3-16) with no dead space, and the genre labels sit cleanly near the top of the tempo panel — matching the up-regulation plot's layout. All numeric results (self-test, convergence numbers, contrast-demo assertions) are unchanged since only plot cosmetics were touched.

## 5. Notable build/debugging issues encountered

- Two plant designs were rejected before settling on the genre-dependent-equilibrium relaxation plant: (a) an additive-nudge plant saturated arousal to 0 and got stuck; (b) a flat relaxation-toward-fixed-equilibrium plant converged but showed no genre-dependent effect (genre switches were cosmetic). The final design ties genre to a `[floor, ceiling]` band via `GENRE_EQUILIBRIUM_BAND`, giving genre a real causal effect and clean bidirectional convergence.
- Getting the naive-parallel strawman to actually oscillate (rather than just converge with a steady-state offset) required abandoning a persistent-controller-state design in favor of a stateless, lagged-error, full-authority recomputation each bar — this is what produces the genuine delay-induced limit cycle used in the contrast figure.
- A y-axis label on the down-regulation plot was clipped at the top edge by `bbox_inches="tight"`; fixed by shortening the label ("arousal (SIMULATED)") and adding `pad_inches=0.3` to `fig.savefig(...)`.

---

## Output files

- Notebook: `/home/user/workspace/groovegen_project/notebooks/13_cascade_closed_loop.ipynb`
- Extended module: `/home/user/workspace/groovegen_project/groovegen/pd_controller.py`
- Notebook builder: `/home/user/workspace/groovegen_project/build_notebook_13.py`
- Sandbox execution script + PNGs: `/home/user/workspace/step_nb13_outputs/run_all.py`
  - `/home/user/workspace/step_nb13_outputs/cascade_downreg_timeseries.png`
  - `/home/user/workspace/step_nb13_outputs/cascade_vs_naive_contrast.png`
  - `/home/user/workspace/step_nb13_outputs/cascade_upreg_timeseries.png`

**No zip was rebuilt and no MusicGen audio was generated in this task**, per instructions.
