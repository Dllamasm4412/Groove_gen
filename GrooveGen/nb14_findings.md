# NB14 findings — tempo-crossfade cascade audio proof

## Deliverables
- Builder script: `/home/user/workspace/groovegen_project/build_notebook_14.py`
- Notebook: `/home/user/workspace/groovegen_project/notebooks/14_tempo_crossfade_audio_proof.ipynb`
- Sandbox dry-run script (throwaway, not shipped): `/home/user/workspace/groovegen_project/_dryrun_xfade_check.py`
- Dry-run output wavs: `/home/user/workspace/groovegen_project/outputs/audio/_dryrun_naive_xfade.wav`, `_dryrun_aligned_xfade.wav`

## Notebook structure
- 13 cells total (4 markdown + 9 code), matching the spec's 13-section outline exactly:
  1. MD — title, what this proves, key risk
  2. Code — Colab setup (pip/apt + zip upload/extract/sys.path, copied from nb13 cell 1's exact pattern)
  3. Code — imports + GPU check + MusicGen model load (nb09 pattern)
  4. MD — bed generation plan (88/76/64 down-regulation)
  5. Code — generate 3 beds, save wavs
  6. Code — `get_bed_info` analysis, detected vs. target BPM disclosure
  7. Code — `render_aligned_drums` (pop, event_density=10, seed=0) + mix + peak-normalize
  8. MD — the two crossfade strategies explained
  9. Code — `equal_power_xfade` + `beat_aligned_xfade` function definitions
  10. Code — build `seq_naive` and `seq_aligned` across both transitions, peak-normalize, save wavs
  11. Code — comparison MP4 (dark-palette labeled frames + muxed audio via ffmpeg)
  12. Code — `ffmpeg volumedetect` assertion (mean dB != -inf)
  13. MD — how to listen / what to judge / CascadeController.step() wiring

## Validation results
- **nbformat**: `nbformat=4`, `nbformat_minor=5`. `nbformat.validate(nb)` — **PASS**.
- **Cell ids**: all 13 cells have unique auto-assigned ids (via `nbformat.v4.new_code_cell` / `new_markdown_cell`) — confirmed no duplicates.
- **ast.parse**: all 9 code cells parse cleanly. The two `!pip`/`!apt` Colab-magic lines in cell 2 are Jupyter shell-magic syntax (not valid bare Python) — verified by substituting `pass  # <line>` for magic lines before `ast.parse`, which is the standard notebook-validation technique (mirrors IPython's own line-transform); all cells pass under that check.
- Notebook does **not** run MusicGen or touch a GPU in the sandbox, per the constraint — it is built purely as a script and inspected via nbformat/ast.

## Dry-run of the crossfade math (sandbox, real audio, no MusicGen)
Ran `get_bed_info` + `render_aligned_drums` (`drum_style="pop"`, `event_density=10`, `seed=0`) on the two uploaded beds, built a mix for each, then applied both shipped crossfade functions.

Inputs:
- r&b bed: `uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav` — detected tempo **68.18 BPM**, duration 10.94s, sec_per_bar 3.520, 8 downbeats
- salsa bed: `uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav` — detected tempo **95.24 BPM**, duration 10.94s, sec_per_bar 2.520, 10 downbeats

Mixes (`0.8*bed + 0.9*drums`, peak-normalized to 0.95):
- mix_rnb: max=0.9500, rms=0.0779
- mix_salsa: max=0.9500, rms=0.1171

Crossfade outputs (peak-normalized to 0.95):

| Variant | Length (samples) | Max amplitude | RMS | Finite |
|---|---|---|---|---|
| **Naive equal-power** (`equal_power_xfade`, fade_s=2.0) | 876,708 | **0.9500** | **0.098814** | True |
| **Beat-aligned** (`beat_aligned_xfade`, fade_bars=1.0) | 785,421 | **0.9500** | **0.098416** | True |

Both assertions passed: `np.abs(out).max() > 0`, RMS > 0, and `np.isfinite(out).all()` for both variants. The two function bodies in the dry-run script are byte-identical to the ones written into notebook cell 9, so what was tested is what ships.

## Notes / honest caveats
- The dry-run used two *different-genre* beds (r&b + salsa) purely to exercise the splice math on real audio with different tempos/grids in the sandbox — the notebook itself only ever crossfades same-genre (`pop`) beds at different tempos, per spec.
- `beat_aligned_xfade` falls back to `sec_per_bar`-based windows / `downbeat_s` if `downbeats` is unavailable, so it degrades gracefully even on beds where madmom's per-bar downbeat tracking is sparse.
- The MP4 render and `ffmpeg volumedetect` assertion cell were built and reviewed but not executed in the sandbox (no MusicGen beds exist yet outside Colab) — the assertion logic (`mean_db != float("-inf")`) is present in cell 12 and will fail loudly in Colab if the muxed audio is ever silent.
