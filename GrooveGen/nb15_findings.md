# Notebook 15 build + validation findings

## Deliverables

- **Builder script:** `/home/user/workspace/groovegen_project/build_notebook_15.py`
  (uses `nbformat.v4.new_notebook`/`new_code_cell`/`new_markdown_cell`, ids
  auto-assigned, `nbformat=4`, `nbformat_minor=5`).
- **Notebook:** `/home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb`
- **Cell count:** 12 cells, in the exact order specified in `nb15_spec.md`:
  1. MD — title + honesty/what-this-proves + iso-principle citations
  2. code — Colab setup (full install list + nb13 zip/sys.path pattern)
  3. code — imports + GPU check + load MusicGen (`facebook/musicgen-small`)
  4. MD — scripted HR curve (3 phases) + HR→arousal mapping rationale
  5. code — build `hr_curve` + `TARGET_AROUSAL`; plot input curve
  6. code — run `CascadeController` loop over bars → record trace; print tier counts
  7. MD — transition mechanism = hard cut (seam-metric comparison vs. crossfade/fill/ramp)
  8. code — `splice_beds_downbeat_hard_cut` + 3 helpers (verbatim from `transition_assessment.md`)
  9. code — generate beds per committed tempo (MusicGen) + per-bar drums; assemble via hard cuts; save wav
  10. code — build the 4-panel synced figure (incl. `tier_that_acted` strip)
  11. code — render MP4 (robust ffmpeg pattern) + volumedetect assertion; display
  12. MD — evidence-tier table + limitations + future work (closing honesty cell)

## Validation results

### (a) Builder run
`python3 build_notebook_15.py` ran cleanly and wrote the `.ipynb` with 12 cells.

### (b) nbformat.validate + ast.parse
- `nbformat.validate(nb)`: **PASS**
- All 12 cell ids unique: **PASS**
- `ast.parse` on every code cell (with `!`/`%` magic lines stripped first):
  **PASS on all 8 code cells** (cells 1, 2, 4, 5, 7, 8, 9, 10 in 0-indexed
  terms — i.e. every code cell in the notebook).
  - Initial build had 2 `SyntaxError`s from raw-string docstrings using
    escaped `\"\"\"` inside the outer `r"""..."""` Python wrapper in the
    builder; fixed by switching those inner docstring delimiters to `'''`
    (semantically identical Python, no behavior change) and rebuilt/re-validated.
- Content checks (markdown): iso-principle citations for Mayr & Starcke 2021
  and Watanabe/Kashino/Ooishi 2017, `SIMULATED` disclaimer, evidence-tier
  table, N=19 Latin caveat, and "system/method" framing language — **all PASS**.
- Code checks: `splice_beds_downbeat_hard_cut` + all 3 helpers present,
  `CascadeController` imported/reused (not reimplemented — no
  `class CascadeController` definition in the notebook), `tier_that_acted`
  color-strip panel present, `volumedetect`/`mean_volume`/`-inf` assertion
  present, no `-f concat` demuxer usage, `facebook/musicgen-small` model id
  present — **all PASS**.

### (c) DRY-RUN: closed-loop control wiring
Script: `/home/user/workspace/nb15_dryrun/dryrun_control.py` (byte-identical
logic to the code shipped in notebook cells 5–6; re-verified by extracting
the actual notebook cells and re-running them standalone — see
`/home/user/workspace/nb15_dryrun/extracted/control_cells.py`, same output).

3-phase HR curve: N_BARS=68 — ramp-down bars [0,24), plateau bars [24,48)
with a 6-bar triangular perturbation spike starting at bar 34, then a
12-bar recovery/hold tail.

**tier_that_acted counts: `{'density': 14, 'tempo': 11, 'none': 43}`**

- ≥1 `'tempo'` action: **PASS** (11 tempo actions, escalating once density saturated during the ramp-down)
- ≥1 `'none'` action during the plateau: **PASS** (43 total `'none'` bars, including plateau bars before/after the perturbation)
- Perturbation triggers a corrective action: **PASS** — perturbation window (bars 34–43):
  ```
  bar= 34 hr= 68.1  tier=none     density= 3  tempo=109.2
  bar= 35 hr= 81.5  tier=density  density= 3  tempo=109.2
  bar= 36 hr= 94.4  tier=density  density= 3  tempo=109.2
  bar= 37 hr=107.9  tier=tempo    density= 3  tempo=109.2
  bar= 38 hr= 95.0  tier=tempo    density= 3  tempo=105.6
  bar= 39 hr= 81.9  tier=tempo    density= 3  tempo=103.9
  bar= 40 hr= 67.5  tier=none     density= 3  tempo=103.2
  ```
  The fast density loop reacts first (bars 35–36), escalating to the tempo
  tier once density is saturated at its floor (bars 37–39), then settles
  back to `'none'` once the spike passes — exactly the disturbance-rejection
  behavior required by the spec (density-first, tempo-if-saturated).

Genre stayed at `'pop'` throughout this run (never reached density+tempo
double-saturation for the `n_bars_saturated_for_genre=5` threshold), which
is expected and desired — the hero clip is deliberately scoped to the
robust R&B<->Pop range per the spec's Latin N=19 caveat guidance; the genre
tier is exercised (and asserted) separately in notebook 13's simulation.

### (d) DRY-RUN: splice_beds_downbeat_hard_cut on the two uploaded beds
Script: `/home/user/workspace/nb15_dryrun/dryrun_splice.py`, re-verified via
extracted notebook cell 8 (`/home/user/workspace/nb15_dryrun/extracted/splice_cell.py`).

- Bed A (r&b, `.../c11d88d97a6f4aaf95cdfc94d6b36941/download.wav`), expected tempo 136.4 BPM
- Bed B (salsa, `.../63787d33f08b41dba1d938272f63641a/download-3.wav`), expected tempo 95.2 BPM

Splice result: `cut_time_a_s=7.95`, `start_time_b_s=0.142`, `seam_sample=350595`, `sr=44100`.

Output wav: `sr=44100`, `duration_s=18.748`, **`max_amp=0.76205`, `rms=0.10451`**,
all samples finite (`826787/826787`).

- `max_amp > 0`: **PASS**
- `rms > 0`: **PASS**
- all finite: **PASS**

### (e) DRY-RUN: ffmpeg still→segment→mux→volumedetect path
Script: `/home/user/workspace/nb15_dryrun/dryrun_ffmpeg.py` (dummy fixed-size
figure + 2s 440Hz sine tone, same `_run()`/scale-filter/flags used in
notebook cell 11).

- Segment build (`-loop 1 -framerate 25 ... -vf scale=trunc(iw/2)*2:trunc(ih/2)*2 -r 25 -pix_fmt yuv420p -c:v libx264`): succeeded
- Mux (`-c:v copy -c:a aac -shortest`): succeeded
- `ffmpeg -af volumedetect`: **`mean_volume: -13.5 dB`, `max_volume: -4.1 dB`**
- `mean_volume != -inf`: **PASS**

## Notes / deviations

- The spec's "verbatim" instruction for the splice function is honored at
  the code-semantics level: the only textual difference between the
  notebook's copy and `transition_assessment.md`'s listing is that inner
  docstrings use `'''...'''` instead of `"""..."""` (required because the
  whole cell source in the Python builder is itself wrapped in an
  `r"""..."""` string — using literal `"""` inside would terminate it early).
  Logic, variable names, control flow, and behavior are byte-identical;
  confirmed via `diff` and via re-running the extracted notebook cell against
  the same two uploaded beds with identical output metrics.
- MusicGen itself was **not** run in the sandbox (no GPU), per instructions.
  Cell 9 (bed generation) and cell 3 (model load) are Colab-only and were
  validated only via `ast.parse` + code-review against nb14's proven pattern,
  not executed.
- All render-noise filtering used the specified grep pattern:
  `2>&1 | grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|librosa"`.

## Summary for reporting back

- **Notebook path:** `/home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb`
- **Cell count:** 12
- **nbformat.validate:** PASS (nbformat 4.5)
- **tier_that_acted counts (control dry-run):** `{'density': 14, 'tempo': 11, 'none': 43}` over 68 bars
- **Splice dry-run:** max_amp=0.76205, rms=0.10451, all finite (18.75s output, non-silent)
- **ffmpeg/volumedetect dry-run:** mean_volume=-13.5 dB, max_volume=-4.1 dB (not -inf)
