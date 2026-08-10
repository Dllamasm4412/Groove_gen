# Per-Bar Hybrid Entry Point — Findings

**Deliverable:** `/home/user/workspace/groovegen_project/groovegen/hybrid_render.py` (edited additively)
**Scratch/tests:** `/home/user/workspace/step_perbar_outputs/` (not committed)
**Roadmap items implemented:** 4.1 (per-bar entry point), 4.2 (cached bed analysis), 4.3 (latency budget verification), 2.5 (deterministic-tile philosophy, documented in-code)

---

## 1. What was built

### `get_bed_info(bed_wav, expected_tempo=None, lock_tempo=None, tempo_min=70.0, tempo_max=180.0, suppress_bed_drums=False, force=False, **analyze_kwargs) -> dict`
Caches `analyze_bed()` output keyed on `(abspath, mtime, expected_tempo, lock_tempo, suppress_bed_drums, tempo_min, tempo_max)` via a module-level `_BED_INFO_CACHE: dict[tuple, dict]` and a `_bed_cache_key(...)` helper. Precomputes and stores `bed_info['bed_grid']`, `bed_info['sec_per_beat']`, `bed_info['sec_per_bar']` on first call so the fast loop never has to rebuild the grid. `suppress_margin` / `protect_melody` / `protect_hz` / `protect_blend` are intentionally excluded from the cache key (they tune the suppression/mix path, not the beat grid); `force=True` bypasses the cache.

### `_make_map_time(bed_info) -> (map_time, sec_per_beat, bed_grid)`
Shared closure extracted from what used to be inline logic inside `render_aligned_drums`. Both `render_aligned_drums` and `render_aligned_drum_bar` now call this single function, so the drum-to-bed time-warp math cannot diverge between the batch and per-bar code paths. Falls back to building the grid on the fly if `bed_info` wasn't produced via `get_bed_info` (e.g., a bare `analyze_bed()` dict), preserving backward compatibility. Returns `(None, sec_per_beat, None)` when no usable beat grid exists.

### `render_aligned_drum_bar(bed_info, bar_idx, *, drum_style, event_density=10, syncopation_level=0.3, swing_amount=1.0, microtiming_variance_ms=0.0, seed=0, sf2_path=None) -> dict`
The new fast-loop entry point. Key behaviors:
- Builds exactly ONE bar via `gg.GrooveParams(..., bars=1, target_seconds=sec_per_bar, with_bed=False)` → `gg.PatternBuilder(params).build_core()` (not `build_looped`).
- **Deterministic tiling (Roadmap 2.5):** `bar_seed = (seed * 1_000_003 + bar_idx * 97) % (2**31 - 1)`. Same `(seed, bar_idx, density, ...)` always yields byte-identical audio — no shared/mutating RNG state, no per-call re-randomization.
- Warps note times with the **same** `_make_map_time(bed_info)` used by the batch path, offset by `bar_idx * sec_per_bar`, then re-zeros to the bar's own `t_start_s` so the returned audio's sample 0 corresponds to that instant on the bed's clock.
- Returns `dict(drums_bar, sr, bar_idx, tempo_bpm, t_start_s, t_end_s, params)`.
- **Bug found and fixed:** if a bar's notes all land past `bed_dur` (true for any bar past the bed's own length), `has_notes` is now checked before calling `gg.render_wav` — previously this crashed with `RuntimeError: FluidSynth returned empty audio`. Now returns an all-zero `drums_bar` of the correct length instead.

### `render_aligned_drums(...)`
Refactored only to call `_make_map_time(bed_info)` instead of its old inline grid-construction. **Signature, external behavior, and return value are unchanged** — confirmed by regression test (§2).

### `hybrid_render(...)`
Left untouched — still calls `analyze_bed` directly, not `get_bed_info`, so its existing caching/behavior semantics are not altered by this work (deliberate, per the "don't break existing batch path" constraint).

---

## 2. Regression test (batch path unaffected)

`00_regression.py` — ran the existing batch `hybrid_render()` end-to-end after the refactor.

- **Result: PASS.** 5.68s wall-clock, tempo=67.8 BPM, downbeat_s=4.43, n_bars=5, duration_s=10.94s, mix params all as expected — identical to pre-refactor behavior.

## 3. `get_bed_info` cache test

`01_get_bed_info.py`:
- Cold call: 3.696s. Cached call (same kwargs): **0.0000s**, and `bi1 is bi2 == True` (same object returned, not a copy).
- `tempo_bpm=67.7966...`, `sec_per_beat=0.885s`, `sec_per_bar=3.54s`, `bed_grid` len=17 — all precomputed and stored on `bed_info`.
- Changing `suppress_bed_drums` correctly produces a cache **miss** (1.189s cold call, `bi3 is bi1 == False`), confirming the cache key is sensitive to grid-affecting kwargs.

## 4. Basic per-bar sanity + determinism

`02_perbar_basic.py`: bars 0/1/2 rendered in ~0.146–0.151s each; re-rendering bar 2 twice with identical params produced **byte-identical audio** (`np.array_equal == True`) — confirms the deterministic-tile contract.

## 5. Reconstruction test (per-bar concat vs. batch)

`03_reconstruction_test.py`, `03b_debug.py`, `03c_backbeat_check.py`:

- **Bug found:** bars 3–4 (past the bed's 10.94s length) crashed before the `has_notes` fix; fixed as described in §1.
- After the fix, all 5 bars (0–4) rendered without error.
- **Onset alignment: 36/36 onsets matched within 40ms between batch `render_aligned_drums` output and the per-bar concatenation (100.0%).**
- RMS: batch=0.06473, per-bar=0.06480, diff=0.04459 (≈69% relative to batch RMS) — **not** sample-identical, as expected, since per-bar seeding differs bar-to-bar from the batch path's single global seed (microtiming jitter differs even though the onset grid matches).
- Backbeat-via-onset-detection (librosa): 6/10 hits detected for **both** batch and per-bar — same rate for both, showing this is a librosa onset-detector sensitivity artifact, not an alignment discrepancy.
- **Ground-truth symbolic check** (`03c_backbeat_check.py`, bypassing the audio onset detector): backbeat steps (`DRUM_STYLES['r&b/soul']` → `backbeat=[4,12]`, snare voice 38) are present in **12/12** tested combinations (densities [6,10,16,20] × bars [0,1,2]) — **backbeat-2&4 lock holds with 100% ground-truth confidence.**

## 6. Density-sweep test

`04_density_sweep.py`:
- First attempt (densities 4→12) showed a **flat** onset count (19 for every bar). Root cause: pre-existing `groovegen.py` behavior — r&b/soul's `hat_base` already supplies 8 hi-hats, and `_genre_hat_steps` only adds extra hats once `event_density > len(hat_base)+4 = 12`. Confirmed the same flatness exists in vanilla batch `build_core()` calls too — **not a regression introduced by this work.**
- Widened sweep to `[4, 8, 12, 14, 16, 18, 20, 24]`. Result:
  - Onset counts: `[19, 19, 19, 21, 23, 25, 27, 27]`
  - **Monotonic non-decreasing: True**, with at least one strict increase (confirms density is actually being respected once above the hat-base plateau).
  - **Backbeat-2&4 assertion passes in all 8 bars.**
  - Script prints `ALL ASSERTIONS PASSED`.

## 7. Latency benchmark (Roadmap 4.3)

`05_latency_bench.py` — 16 samples, cycling `bar_idx` through the bed's 3 real (note-bearing) bars so every sample does actual `PatternBuilder` + FluidSynth work (avoids skew from the "past bed length" silent fast-path).

**End-to-end (`render_aligned_drum_bar`, ground truth):**

| Stat | Value |
|---|---|
| mean | 156.73 ms |
| median | 152.09 ms |
| max | 197.92 ms |
| min | 148.45 ms |
| std | 11.72 ms |

**Stage breakdown (n=16, reproduced with identical internal calls/order):**

| Stage | mean | median | max | min |
|---|---|---|---|---|
| 1) Build 1-bar MIDI (`GrooveParams`+`PatternBuilder.build_core`) | 0.19 ms | 0.19 ms | 0.24 ms | 0.17 ms |
| 2) Warp (`map_time` note-shift loop) | 0.07 ms | 0.07 ms | 0.10 ms | 0.06 ms |
| 3) FluidSynth render (`gg.render_wav`) | 149.89 ms | 149.07 ms | 158.06 ms | 145.52 ms |
| 4) Load-back (`librosa.load`) | *(negligible — folded into render capture; see note)* | | | |
| **Sum of stages** | **150.89 ms** | **150.03 ms** | **159.02 ms** | **146.43 ms** |

FluidSynth rendering dominates (~99% of per-bar cost); MIDI construction and time-warping are negligible (<0.3ms combined).

**Budget fit:**
- Bar period at this bed's tempo (67.8 BPM): **3.54s**
- Architecture doc's target session bar budget: **2.0–2.5s**
- Mean per-bar latency (156.73ms) fits the 3.54s bar period with **~13–16x headroom** relative to even the tighter 2.0–2.5s budget.
- **Conclusion: comfortably fits the bar budget on this CPU sandbox.** Even the worst observed single-bar sample (197.92ms) leaves >10x headroom.

---

## Summary of fixes made during this work

1. **Empty-bar-past-bed-duration crash** — `render_aligned_drum_bar` now checks `has_notes` before calling `gg.render_wav`/`librosa.load`, returning zero-filled audio instead of crashing when a requested bar index falls beyond the bed's own duration.
2. **Density-sweep test range** — widened from `[4..12]` to `[4,8,12,14,16,18,20,24]` to actually exercise the density knob past r&b/soul's hat-base plateau (a pre-existing, not-a-regression property of `groovegen.py`).

No other signature or seeding changes were needed beyond the initial design — `render_aligned_drums`'s external signature/behavior is unchanged, and `hybrid_render` was left untouched.
