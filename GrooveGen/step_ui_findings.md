# Rewire genre UI to hybrid engine — findings

## What changed

`/home/user/workspace/groovegen_project/app_genre.py` was rewritten to drive the
**hybrid engine** (`groovegen/hybrid_render.py::hybrid_render`) instead of the
old continuous engine (`groovegen/continuous.py::render_continuous`), per the
decisive A/B result. Gradio layout, genre checkboxes + free-text routing
(`genre_router.route_genres` / `KNOWN_PRESET_KEYS`, unchanged), advanced
controls (seconds/seed/bed_source), and the dark-theme (`#171614` /
`#4F98A3`) plot panel are all preserved structurally.

### New render flow in `generate()`
1. `preset = get_preset(primary_key)` — tempo comes from `preset['tempo_hint']`
   (no tempo slider was in the original UI, so none was added; the existing
   "seconds" slider is kept but now labeled informational for the hybrid path,
   since bed duration — not the slider — determines actual output length).
2. Bed selection:
   - `bed_source in ('auto','musicgen')` **and** `GPU` present →
     `generate_musicgen_beds(preset['bed_prompt'], preset['tempo_hint'], n=1)`,
     using MusicGen (`facebook/musicgen-small` via `transformers`) code copied
     from `notebooks/09-hybrid-musicgen-bed.ipynb` cell 11 (12s clip,
     `max_new_tokens = seconds*50`, resampled to 44.1kHz, saved as wav). Wrapped
     in try/except; `bed_source == 'musicgen'` with no GPU or a MusicGen failure
     returns a clear error status instead of silently falling back.
   - Otherwise → `_select_fallback_beds()` picks ONE uploaded bed (salsa bed if
     primary genre is `latin/salsa`, r&b bed otherwise) — simplified from the
     old multi-bed crossfade-pool logic since hybrid only uses one bed at a time.
3. `hybrid_render(bed_wav=..., drum_style=preset['drum_style'], out_wav=OUT_DIR/mix_<genre>_<seed>.wav, expected_tempo=float(preset['tempo_hint']), lock_tempo=preset.get('lock_tempo'), mix_kwargs=preset.get('mix_kwargs'), suppress_bed_drums=preset.get('suppress_bed_drums', False), event_density=..., syncopation_level=..., swing_amount=..., microtiming_variance_ms=..., seed=int(seed), sf2_path=SF2)`.
   Also forwards `preset['lock_tempo']`, `preset['mix_kwargs']`, and
   `preset['suppress_bed_drums']` (all returned by `get_preset`) since the real
   `hybrid_render` signature accepts and expects them for correct per-genre
   behavior (e.g. salsa/r&b tempo pinning, r&b bed-forward mix).
4. Density-walk plot **replaced** with `_plot_knob_bars()`: a dark-theme bar
   chart of the genre's fixed knobs (event_density, syncopation, swing,
   microtiming), reusing the `#171614` background / `#4F98A3` accent styling.
   `ABOUT_DENSITY_MD` rewritten to describe the hybrid path (MusicGen/uploaded
   bed + genre-idiomatic drums beat-warped onto the bed's detected grid)
   instead of the old per-bar random-walk claim.
5. Multi-genre handling: only the primary (first-resolved) genre is actually
   rendered per call (hybrid aligns one drum pass to one bed's grid). Other
   resolved genres are explicitly listed in the status markdown under
   **"Not yet layered (one genre at a time in this build)"** — never silently
   dropped.

## Hybrid_render return keys actually used

Inspected the real return dict at the end of `hybrid_render()`
(`groovegen/hybrid_render.py` ~line 785):

```python
dict(
    out_wav=out_wav,
    detected_tempo_bpm=round(bed_info["tempo_bpm"], 1),
    downbeat_s=round(bed_info["downbeat_s"], 3),
    n_bars=drum_info["n_bars"],
    duration_s=round(mix_info["duration_s"], 2),
    knobs=knob_kwargs,
    bed_drums_suppressed=bool(suppress_bed_drums),
    mix=dict(clarity=..., bed_hpf_hz=..., sidechain_depth_db=..., drum_gain_db=...),
)
```

Keys used in `app_genre.py`: **`out_wav`** (the mixed wav path returned to
Gradio), **`detected_tempo_bpm`** and **`n_bars`**/**`duration_s`** (status
text). Note there is no `"wav_path"` key (that was the old `render_continuous`
meta key) — the correct key is `out_wav`.

## Signature fixes / notes vs. the task's assumed API

- `get_preset()` returns additional fields beyond the 5 named in the task spec
  (`bed_prompt`, `tempo_hint`, `drum_style`, `knobs`, `seed_genre`) that
  `hybrid_render` actually needs for correct genre-specific behavior:
  `lock_tempo`, `mix_kwargs`, `suppress_bed_drums`. These are forwarded from
  the preset dict rather than hardcoded, matching how notebook 09's working
  pipeline calls `hybrid_render`.
- `generate_musicgen_beds()` copied from the notebook was adjusted to resample
  MusicGen's native sampling rate (`model.config.audio_encoder.sampling_rate`)
  to 44.1kHz before writing, since the rest of the pipeline (uploaded beds,
  `hybrid_render`'s internal processing) assumes 44.1kHz.
- `_select_fallback_beds()` simplified to return a single bed (hybrid only
  uses one bed per render), vs. the old function's multi-bed list for
  `continuous.py`'s crossfade pool.
- Removed the unused `GrooveParams`/`render_continuous` imports and the
  per-bar `band`/`step_sd` random-walk parameters entirely — they don't apply
  to the hybrid path.

## Dry-run results (CPU sandbox, no GPU)

Ran `/home/user/workspace/step_ui_outputs/dry_run_ui.py` with
`cwd=/home/user/workspace/groovegen_project`:

```
generate(["r&b/soul"], "", 12, 0, "uploaded")
  -> wav_path: /tmp/groovegen_genre_ui/mix_r&b_soul_0.wav
  -> png_path: /tmp/groovegen_genre_ui/knobs_r&b_soul_0.png
  -> detected bed tempo: 96.0 BPM (requested 96 BPM), 6 bars, 10.9s
```

**Non-silence check:**
- numpy RMS = **0.072185**, peak = 0.535706 (sr=44100, 482454 samples)
- ffmpeg `volumedetect`: **mean_volume: -22.8 dB**, max_volume: -5.4 dB

Both confirm a real, audible (non-silent) mixed wav produced via the hybrid
engine using the uploaded r&b bed
(`/home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav`)
and SF2 at `/usr/share/sounds/sf2/FluidR3_GM.sf2`. The PNG (knob bar chart)
was also confirmed to exist (39,573 bytes).

Also manually smoke-tested a multi-genre + approximate-free-text case
(`["latin/salsa","pop"]` + `"jazz, lo-fi"`, bed_source="auto"): correctly
rendered the salsa bed as primary (bed auto-selected via
`_select_fallback_beds` since `latin/salsa` was primary), and reported
`pop, r&b/soul, calm` as "not yet layered" — nothing silently dropped.

No signature errors, no exceptions, no code changes were needed after the
first dry-run pass.

## Files

- Overwritten: `/home/user/workspace/groovegen_project/app_genre.py`
- Dry-run script: `/home/user/workspace/step_ui_outputs/dry_run_ui.py`
- Dry-run outputs (generated under `/tmp/groovegen_genre_ui/`, not in
  workspace since OUT_DIR uses `tempfile.gettempdir()`):
  `mix_r&b_soul_0.wav`, `knobs_r&b_soul_0.png`,
  `mix_latin_salsa_7.wav`, `knobs_latin_salsa_7.png`
