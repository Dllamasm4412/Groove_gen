# nb15 Re-tune Findings: Tempo-Band-Derived Genre Arc

**Notebook:** `/home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb`
**Builder:** `/home/user/workspace/groovegen_project/build_notebook_15.py`
**Spec:** `/home/user/workspace/nb15_retune_spec.md`

## Summary of the fix

The prior arc was compressed: tempo took three separate steps *inside* Latin
(125->111->96 bpm) while genre stayed pinned to Latin, then latin->pop->r&b
all flipped in the final ~6 BPM once the old `tempo_min=90` floor was hit —
because genre was read from the `CascadeController`'s own internal
saturation-escalation index, and that index only escalates once the tempo
tier saturates.

**The fix implemented:** genre is now a **display derivation of the
committed tempo band**, computed by a new `genre_from_tempo()` function in
cell 9 (and reused identically for the cell-10 viz), not read from the
cascade's internal `genre` field. `tempo_min` was lowered from 90 to 70 so
the tempo tier alone has enough range to track the whole scripted descent,
and `END_HR_BPM` was lowered from 72.0 to 74.0. The `CascadeController`
itself (tempo + density tiers) is **reused unmodified** — only the notebook's
genre *display* logic changed.

Tempo bands (non-overlapping, matching `GENRE_ENERGY_ORDER`'s qualitative
ranking, latin > pop > r&b, with calm as an r&b/soul sub-band):

| Genre | Tempo band |
|---|---|
| `latin` | >= 112 bpm |
| `pop` | 98 - 112 bpm |
| `r&b` | 84 - 98 bpm |
| `calm` (sparse low-tempo R&B/soul) | < 84 bpm |

**Honesty note (verified against source):** `groovegen/genre_styles.py`
defines exactly six `StyleSpec`s (`hip-hop/rap`, `r&b/soul`, `pop`,
`latin/salsa`, `classic-rock`, `metal`) — there is **no `'calm'`
`StyleSpec`**. `GENRE_TO_STYLE['calm'] = 'r&b'` makes this literal in code:
calm renders through the exact same r&b/soul style, at the lowest tempo
band, with density floored to `[3, 4]` (`CALM_DENSITY_FLOOR=3`,
`CALM_DENSITY_CEIL=4`) via a post-processing clamp in `build_segment_mix`.
Every print statement, prompt, panel label, and markdown reference to calm
in the notebook now reads **"calm (sparse low-tempo R&B/soul)"**, never a
bare "calm" implying a fourth distinct genre.

---

## Control dry-run results

Executed the notebook's **own** cell source verbatim (extracted via
`nbformat`, not reimplemented) for cell 5 (HR curve build), cell 6
(`CascadeController` loop), and the segment-building portion of cell 9 (up
to, but not including, the MusicGen bed-generation calls, which require a
GPU runtime not available in this dry-run sandbox).

### Per-segment table

| idx | genre | committed_tempo (bpm) | n_bars | start_bar | end_bar | density range |
|---|---|---|---|---|---|---|
| 0 | latin | 125 | 24 | 0 | 24 | 8-8 |
| 1 | pop | 110 | 14 | 24 | 38 | 3-8 |
| 2 | r&b | 97 | 10 | 38 | 48 | 3-3 |
| 3 | calm (sparse low-tempo R&B/soul) | 82 | 16 | 48 | 64 | 3-3 |

Full JSON (including per-bar density arrays) saved to
`/home/user/workspace/nb15_retune_dryrun_segments.json`.

Arc achieved: **latin@125 -> pop@110 -> r&b@97 -> calm@82 bpm**, four
committed segments, one big jump (~15 BPM) at each genre-band crossing —
matching the spec's target shape (`latin@~125 -> pop@~108 -> r&b@~90 ->
calm@~76`) to within a few BPM per segment while landing every segment
correctly inside its own tempo band.

### Assertions (all passed)

| Assertion | Result |
|---|---|
| Committed-segment count in [4,5] | **PASS** — 4 segments |
| Genre sequence latin->pop->r&b->calm, all present, in order | **PASS** — `['latin', 'pop', 'r&b', 'calm']` |
| Each genre's committed tempo inside its own band | **PASS** — 125>=112 (latin); 98<=110<112 (pop); 84<=97<98 (r&b); 82<84 (calm) |
| Density in [3,8] for all bars | **PASS** — observed range 3-8 |
| `'tempo'` and `'none'` present in `tier_that_acted` counts | **PASS** — `{'none': 30, 'tempo': 30, 'density': 4}` |
| `'genre'` in `tier_that_acted` (informational only, no longer required) | Absent (0) — expected, since genre is now a display derivation, not a cascade actuator tier |

Diagnostic: the cascade's own **internal** genre-escalation field (not used
for display) stayed pinned at `'latin'` throughout the run — confirming
that with `tempo_min=70`, the tempo tier alone has enough range to track the
full descent and the internal genre-saturation tier never needs to fire.

---

## Splice dry-run (r&b + salsa beds)

Executed cell 8's `splice_beds_downbeat_hard_cut` (and its 3 helpers)
**verbatim**, extracted from the notebook, against the two real uploaded
beds:
- r&b bed: `/home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav`
- salsa bed: `/home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav`

Output saved to `/home/user/workspace/nb15_retune_splice_dryrun_output.wav`.

| Metric | Value |
|---|---|
| Output duration | 18.75 s |
| Sample rate | 44100 Hz |
| Max amplitude | 0.7621 |
| RMS | 0.10451 |
| Finite (no NaN/Inf) | **PASS** |
| Non-silent (max > 1e-6) | **PASS** |
| Seam sample / cut times | `seam_sample=350595`, `cut_time_a_s=7.95`, `start_time_b_s=0.142` |

---

## FFmpeg volumedetect dry-run

Replicated cell 11's fixed-size-frame ffmpeg pattern (`-loop 1` still ->
`scale=trunc(iw/2)*2:trunc(ih/2)*2 -r 25 -pix_fmt yuv420p -c:v libx264`,
muxed with `-c:a aac -shortest`) using the real splice-dry-run audio output
above as the audio track.

| Metric | Value |
|---|---|
| `mean_volume` | **-19.7 dB** (not `-inf`) |
| `max_volume` | -2.3 dB |
| Assertion `mean_volume != -inf` | **PASS** |

---

## nbformat / ast validation

| Check | Result |
|---|---|
| `nbformat.validate(nb)` | **PASSED** |
| Cell count | 12 (matches builder's `wrote ... with 12 cells` log) |
| `ast.parse` on every code cell (magics `^\s*[!%]` stripped first) | **PASSED** — all 8 code cells parse cleanly |

---

## Prior-fix confirmation (grep against the emitted notebook)

| Prior fix | Found | Occurrences |
|---|---|---|
| `transformers==4.44.2` pin | YES | 1 |
| `CUDA_LAUNCH_BLOCKING` | YES | 1 |
| `hf_transfer` | YES | 2 |
| `HF_HUB_DOWNLOAD_TIMEOUT=60` | YES | 1 |
| `use_safetensors=True` | YES | 2 |
| `GEN_SECONDS` token cap | YES | 3 |
| `MAX_NEW_TOKENS_CAP` | YES | 2 |
| `_loop_to_length` (loop-to-length gen_bed) | YES | 2 |
| `splice_beds_downbeat_hard_cut` (verbatim, no crossfade) | YES | 10 |
| `CascadeController` imported, not redefined (`class CascadeController` count = 0) | YES | 1 import, 0 redefinitions |
| Scripted-setpoint "TRACKS" language | YES | 8 |
| Respiration "SHOWN, NOT DRIVING" language | YES | 9 |
| PubMed 34886210 (Mayr & Starcke, iso-principle) | YES | 3 |
| PubMed 28266647 (Watanabe/Kashino/Ooishi) | YES | 3 |
| Evidence-tier table | YES | 1 |
| Limitations section | YES | 1 |
| Latin N=19 caveat | YES | 2 |
| 4 viz panels + mandatory `tier_that_acted` strip | YES | panels 1-5 each found exactly once (4 conceptual panels + tier strip, across 5 synced axes as originally designed) |

No prior fix was regressed.

---

## Summary table

| Item | Status |
|---|---|
| Builder edited (`build_notebook_15.py`) | Done — cells 1, 4, 5, 6, 9, 10, 12 updated |
| Notebook re-emitted | Done — 12 cells written to `notebooks/15_closed_loop_hr_audio.ipynb` |
| `nbformat.validate` | PASS |
| `ast.parse` (all code cells) | PASS |
| Control dry-run (segment count, genre order, tempo bands, density, tier_that_acted) | PASS — see per-segment table above |
| Splice dry-run (r&b + salsa beds) | PASS — finite, non-silent |
| FFmpeg volumedetect dry-run | PASS — `mean_volume = -19.7 dB` |
| Prior-fix regression check | PASS — all fixes present, none regressed |
| Calm honesty requirement | Verified — no fake calm `StyleSpec`; `GENRE_TO_STYLE['calm']='r&b'`; labeled "calm (sparse low-tempo R&B/soul)" everywhere |

## Source files referenced

- Builder: `/home/user/workspace/groovegen_project/build_notebook_15.py`
- Emitted notebook: `/home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb`
- `groovegen/pd_controller.py` — `CascadeController` (reused unmodified)
- `groovegen/genre_styles.py` — confirms no `'calm'` `StyleSpec` exists
- Per-segment dry-run JSON: `/home/user/workspace/nb15_retune_dryrun_segments.json`
- Splice dry-run output audio: `/home/user/workspace/nb15_retune_splice_dryrun_output.wav`
- FFmpeg dry-run artifacts: `/home/user/workspace/nb15_retune_ffmpeg_dryrun_final.mp4`, `nb15_retune_ffmpeg_dryrun_segment.mp4`, `nb15_retune_ffmpeg_dryrun_still.png`
