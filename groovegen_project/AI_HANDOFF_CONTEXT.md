# GrooveGen — AI Handoff Context

**Purpose of this document:** you (an AI model or engineer) are picking up this project with
the code but zero conversation history. This file is an operational manual, not a narrative —
it tells you what the system is, what rules you must not break, exactly which files to touch
for common tasks, and where the evidence for every non-obvious design decision lives. Read
section 2 (NON-NEGOTIABLE RULES) before touching anything.

Repo root referenced throughout: `/home/user/workspace/groovegen_project/`. A sibling
directory `/home/user/workspace/assess/` holds research/audit docs referenced below —
`CODE_AUDIT.md`, `PATH_RESEARCH.md`, `BUILD_SPEC.md`, `BUILD_REPORT.md`.

---

## 1. TL;DR

- GrooveGen is a **closed-loop, biofeedback-styled music generation system**: a PD/cascade
  controller walks genre→tempo→density in response to a heart-rate signal, and instrumental
  audio beds (MusicGen + a curated library + a symbolic-latin fallback) are rendered and
  spliced to match the committed trace. The **current, non-stale pipeline** is the
  `A_setup_and_experiment_ui.ipynb` → `LIB_build_beds.ipynb` → `BC_generate_and_closed_loop.ipynb`
  (which internally `%run`s `15_closed_loop_hr_audio.ipynb`) chain — see Section 4.
- This is a **systems/methods paper for TEI 2027** (deadline **July 31, 2026**), not an
  efficacy study: nothing in this codebase claims to measure or change a real person's heart
  rate, arousal, or emotion. The heart rate driving the controller is a **scripted setpoint the
  controller tracks**, never a sensor reading or a validated physiological simulation. Get this
  framing wrong in any writing/code you touch and you will introduce a paper-blocking claim.
- The most recent completed work is the **curated bed library system**
  (`groovegen/bed_library.py` + `notebooks/LIB_build_beds.ipynb`), which replaces on-the-fly
  MusicGen generation as the primary audio source, fixes off-beat drums, weak latin/salsa
  fidelity, and bad transitions. See Section 5 — this is almost certainly what you'll be
  asked to extend next.
- **Notebooks are generated artifacts.** Every `.ipynb` under `notebooks/` that matters is
  built by a same-named `build_notebook_*.py` script at repo root. **Never hand-edit a
  `.ipynb`.** Edit the builder, then run `python3 build_notebook_X.py` to regenerate it. This
  is the single most important workflow rule in this repo (Section 3).
- The user (Daniel, PhD student, CU Boulder, triple-track Cognitive Science/Atlas/HCI) is
  technically strong, wants **honest pushback** (do not paper over gaps or oversell claims —
  he audits code and evidence tiers closely), works on **Colab T4 GPU** where bare
  WAV/MP3 playback is frequently unreliable (deliver **MP4 or zip**, always verify audio with
  `ffmpeg -af volumedetect`), and prefers **subagents/parallelism** for large or
  credit-expensive tasks.

---

## 2. NON-NEGOTIABLE PROJECT RULES

These are hard constraints. Violating any of them either breaks the science-honesty framing
the TEI submission depends on, or breaks something that has already been fixed once (don't
regress a fix). If a task seems to require breaking one of these, stop and flag it explicitly
rather than silently complying.

### 2.1 Publishability framing: SYSTEM/METHOD, not efficacy
- This is a **systems and methods** contribution: a closed-loop control architecture
  (genre→tempo→density cascade) and an audio-assembly pipeline (bed selection, re-timing,
  drum alignment, splicing). It is **not** an efficacy claim about lowering heart rate,
  regulating emotion, or "calming" a real listener.
- **Heart rate is a SCRIPTED, IMPOSED SETPOINT** the controller **TRACKS** — never
  "regulates," "lowers," or "responds to" in any writing. It is not read from a sensor and not
  output by a validated physiological model. See `build_notebook_15.py` (search
  `"SCRIPTED, IMPOSED SETPOINT"`) and `groovegen/pd_controller.py`'s `synth_hr()` /
  `dual_lever_plant_step()`, whose docstring literally says **"*** A FABRICATED TOY PLANT, NOT
  A VALIDATED PHYSIOLOGICAL MODEL ***"**.
- Respiration traces shown in notebook 15's figures are **synthesized for scenario realism
  and are never read by the controller** — the controller's `measurement` input comes only
  from the HR setpoint curve. Don't wire respiration into the controller without flagging that
  as a scope change.
- **Iso-principle citations are SIGN-ONLY, not efficacy evidence.** The two citations —
  Mayr & Starcke (2021), *PubMed* [34886210](https://pubmed.ncbi.nlm.nih.gov/34886210/), and
  Watanabe, Kashino & Ooishi (2017), *PubMed* [28266647](https://pubmed.ncbi.nlm.nih.gov/28266647/)
  — justify only the **direction** "lower tempo/density = calming direction," never a fitted
  magnitude or an effect-size claim for this implementation. This exact framing is written out
  in `build_notebook_15.py` in the cell titled `## Why "SIGN only" -- the iso-principle
  citations`. Reuse that language; don't paraphrase it into something stronger.
- Notebook 15 carries a full **evidence-tier table** (search `Evidence-tier table` in
  `build_notebook_15.py`) that classifies every claim as e.g. "simulated control-loop",
  "real-audio demo (single run, not independently replicated)", "literature citation,
  sign-only", or "real-human-data: NONE YET". Any new claim you add to a paper draft or a
  notebook should be slotted into this same tiering discipline.

### 2.2 NO VOCALS, anywhere, ever
- Every MusicGen text prompt in this codebase must end with **"instrumental, no vocals"**
  (verified literal suffix, e.g. `groovegen/genre_presets.py`, and asserted at build time in
  `build_notebook_libbuild.py` — `assert "no vocals" in p, ...` at line 286). This is a hard
  project rule, not a style preference — repeated explicitly in `LIB_build_beds.ipynb`'s intro
  markdown: *"No vocals anywhere -- every MusicGen prompt below ends in 'instrumental, no
  vocals'"*.
- **There is intentionally no raw-reference-song audio fallback anywhere in the pipeline.**
  If MusicGen generation + quantization can't pass the quality gate after `max_tries`, the
  system keeps the **cleanest generated (still-instrumental) attempt** — it never substitutes
  the original reference song audio (which would contain vocals). This is explicit in
  `groovegen/generate_and_gate.py` (search `"we NEVER substitute a raw reference song here"`)
  and reconfirmed in `BUILD_REPORT.md` §5: *"no raw reference-song-audio fallback path anywhere
  in the new code."* **Do not reintroduce this fallback** even to "fix" a stubborn quality-gate
  failure — that was removed on purpose after it was found to be the mechanism smuggling
  vocals into supposedly-instrumental output.
- Reference songs (used by `groovegen/profile_from_songs.py` to build an "anchor" feature
  vector) are used **only for feature extraction** (tempo, MFCCs, spectral centroid, HPSS
  ratios, onset density) — **never played, never used as generation seed audio, never used as
  a fallback bed.** If you see code that plays or renders a reference song's own audio as
  output, that is a bug, not a feature.

### 2.3 Quality gate: jitter + pulse_clarity ONLY
- `groovegen/generate_and_gate.py`'s `QualityGate` dataclass (`max_beat_jitter_ms=45.0`,
  `min_pulse_clarity=0.30` defaults) gates **exclusively** on `beat_jitter_ms` and
  `pulse_clarity` inside `.passes()`:
  ```python
  def passes(self, m: dict) -> bool:
      return (m["beat_jitter_ms"] <= self.max_beat_jitter_ms
              and m.get("pulse_clarity", 1.0) >= self.min_pulse_clarity)
  ```
- `grid_err_mean_ms` is measured and reported but is **explicitly diagnostic-only** —
  it does NOT gate. The dataclass docstring calls this out as the **"2026-07 recalibration"**:
  the old gate required onsets within 40ms of the quarter-note grid, but real music
  (eighths/sixteenths/syncopation) legitimately scores 130–170ms "grid error" and always
  failed — which is what forced the (now-removed) raw-reference-song fallback described in
  2.2. **Do not re-add grid_err to the pass/fail condition** — that regresses the exact bug
  this recalibration fixed. `max_grid_err_ms=40.0` still exists as a dataclass field for
  backward-compat/diagnostics only.
- The same `QualityGate(max_beat_jitter_ms=45.0, min_pulse_clarity=0.30)` machinery is reused
  verbatim by `LIB_build_beds.ipynb` for library-candidate curation — keep any gate changes in
  sync across `generate_and_gate.py` and the library builder cell 1.1 (`build_notebook_libbuild.py`).

### 2.4 Colab environment realities
- User's runtime is **Colab T4 GPU**, and Colab frequently ships `huggingface_hub` 1.x, which
  is **incompatible with the pinned `transformers==4.44.2`** (newer transformers throws a CUDA
  device-side assert inside MusicGen — do not upgrade transformers to "fix" this). See Section
  4 for the exact pin set and the self-healing guard pattern.
- The user **often cannot play bare WAV/MP3 files inline** in his environment. Deliverables
  should be **MP4 (video+muxed audio) or a zip**, never a bare audio file as the primary
  artifact. Always verify the audio track is actually present and non-silent with:
  ```bash
  ffmpeg -i output.mp4 -af volumedetect -f null -
  ```
  and confirm `mean_volume` is **not** `-inf` (an `-inf` mean_volume means the video has a
  silent/empty audio track — a real, previously-hit failure mode in this project).
- Daniel values direct technical pushback over agreeable hedging — if something in a request
  would violate 2.1–2.3, say so plainly rather than quietly working around it.
- For large or multi-file tasks (e.g. rebuilding several notebooks, auditing many modules),
  prefer using subagents/parallel work rather than one long serial pass — Daniel explicitly
  wants this for credit-efficiency on big tasks.

---

## 3. REPO MAP

```
groovegen_project/
├── config.py                     # central path config; find_soundfont() preference order
├── groovegen/                    # the installable package (public API in __init__.py)
│   ├── __init__.py                #  exports: GrooveParams, PatternBuilder, BedProfile,
│   │                               #  BED_PROFILES, BED_HERO, BED_HERO_STUDY, BED_DORIAN,
│   │                               #  BED_POP, BED_LIFT, DEFAULT_BED_PROFILE,
│   │                               #  STUDY_BED_PROFILE, generate, render_wav, default_sf2,
│   │                               #  FS, TARGET_LUFS (from .groovegen); also exposes the
│   │                               #  `dlbed` and `genre_styles` submodules directly.
│   ├── groovegen.py                # core pattern/render engine (not in required-reading list
│   │                               #  for this handoff, but is what __init__.py re-exports from)
│   ├── genre_styles.py             # GENRE_STYLES: StyleSpec per genre (hip-hop/rap 90bpm,
│   │                               #  r&b/soul 96bpm, pop 120bpm, latin/salsa 180bpm,
│   │                               #  classic-rock 94bpm, metal 123bpm). comp_style options:
│   │                               #  block/sustain_accent/arp/staccato_chug.
│   │                               #  build_style_seed(genre, bars, seed), seed_feature_summary().
│   │                               #  GM program + percussion-key constants.
│   ├── prompt_from_anchor.py       # nearest_known_genre() (tempo+timbre nearest-centroid
│   │                               #  heuristic, NOT a trained classifier — see docstring),
│   │                               #  _busy_or_minimal/_drum_descriptor/_brightness_descriptor/
│   │                               #  _harmonic_descriptor, prompt_from_anchor(anchor, tempo_bpm).
│   │                               #  NOTE: this function's own returned string does NOT append
│   │                               #  "instrumental, no vocals" — that suffix is added by the
│   │                               #  callers (builder notebook prompt cells / genre_presets.py),
│   │                               #  not inside this module. Only 5 of ~20 numeric anchor
│   │                               #  features are ever read here (see Section 5.3).
│   ├── generate_and_gate.py        # measure_tempo_stability(), QualityGate (Section 2.3),
│   │                               #  beatsync_quantize(), generate_and_gate() driver,
│   │                               #  make_musicgen_generator() (loop-to-length, 1.5ms fade).
│   ├── bed_library.py              # NEWEST module (Section 5). sanitize_genre(),
│   │                               #  list_library(), pick_nearest_bed(), retime_bed()
│   │                               #  (pyrubberband primary / librosa fallback with warning).
│   ├── hybrid_render.py            # largest module (1144 lines). _suppress_percussion()
│   │                               #  (HPSS to strip MusicGen's baked drums),
│   │                               #  _madmom_beat_grid(), _fix_octave(), _octave_snap_grid()
│   │                               #  (recently rewritten — see Section 7), analyze_bed()
│   │                               #  (aka get_bed_info, cached), _build_bed_grid(),
│   │                               #  render_aligned_drums()/render_aligned_drum_bar(),
│   │                               #  mix_stems(), hybrid_render().
│   ├── dlbed.py                    # midi_bed_to_profile(), build_genre_song(),
│   │                               #  register_genre_song/register_dl_bed, SWEEP_LEVELS,
│   │                               #  render_genre_demo().
│   ├── pd_controller.py            # PDDensityController (PD, no integral term —
│   │                               #  ARCHITECTURE_TWO_TIMESCALE.md §5.2), synth_physiology()
│   │                               #  (SYNTHETIC DATA), TempoController, synth_hr(),
│   │                               #  GENRE_ENERGY_ORDER, GENRE_EQUILIBRIUM_BAND,
│   │                               #  dual_lever_plant_step() (TOY PLANT), CascadeController
│   │                               #  (3-tier genre→tempo→density, hysteresis-gated).
│   ├── profile_from_songs.py        # reference-song feature extraction (13 MFCCs, centroid,
│   │                               #  HPSS ratios, onset density, tempo) — feature source for
│   │                               #  prompt_from_anchor's anchor dict.
│   ├── arc_from_profile.py, auto_fallback.py, bayesopt.py, build_stimulus_grid.py,
│   │   continuous.py, genre_presets.py, genre_router.py, hr_source.py,
│   │   madmom_compat.py, make_compare_video.py, melody_timbre_compare.py,
│   │   render_iterations.py, song_resolver.py     # supporting/legacy modules, not required
│   │                               #  reading for this handoff — grep before assuming behavior.
├── build_notebook_partA.py        # → notebooks/A_setup_and_experiment_ui.ipynb  (CURRENT)
├── build_notebook_libbuild.py     # → notebooks/LIB_build_beds.ipynb             (CURRENT, newest)
├── build_notebook_BC.py           # → notebooks/BC_generate_and_closed_loop.ipynb (CURRENT)
├── build_notebook_15.py           # → notebooks/15_closed_loop_hr_audio.ipynb    (CURRENT,
│                                   #   %run-invoked from inside BC's Part C, not run standalone
│                                   #   in the normal flow — but still independently openable)
├── build_notebook_12.py, build_notebook_13.py, build_notebook_14.py  # builders for legacy
│                                   #   numbered notebooks 12/13/14 — still present, still
│                                   #   buildable, but NOT part of the current run pipeline.
├── notebooks/
│   ├── A_setup_and_experiment_ui.ipynb        # CURRENT — Part 0 setup + experiment UI (CPU-only)
│   ├── LIB_build_beds.ipynb                   # CURRENT — one-time GPU bed-library build+curate
│   ├── BC_generate_and_closed_loop.ipynb      # CURRENT — GPU: Part B (generate+gate) + Part C (%run 15)
│   ├── 15_closed_loop_hr_audio.ipynb          # CURRENT — hero artifact; also runnable standalone
│   ├── 00_setup.ipynb … 14_tempo_crossfade_audio_proof.ipynb  # LEGACY numbered series (00–14),
│   │                                           #   superseded by A/LIB/BC/15 — do not treat as
│   │                                           #   the current pipeline even though the files exist.
│   └── extra_transition_cell.py               # standalone paste-in snippet, NOT compiled by any
│                                               #   builder (confirmed via project-wide %run/import
│                                               #   search) — its old np.interp-based
│                                               #   _resample_to_tempo() was replaced with a
│                                               #   RubberBand-based _retime_array_to_tempo() per
│                                               #   BUILD_REPORT.md, but this file is not wired
│                                               #   into any notebook build.
├── README.md, HOW_TO_RUN.md       # STALE — describe an old 00–08 numbered pipeline with
│                                   #   Raspberry Pi / app.py web-UI notes. Do not follow these
│                                   #   for run instructions; use COLAB_RUNBOOK.md + Section 4 below.
├── COLAB_RUNBOOK.md                # CURRENT — matches the A/LIB/BC/15 pipeline; primary run doc.
├── ARCHITECTURE_TWO_TIMESCALE.md   # TEI 2027 architecture + latency analysis (background)
├── HYBRID_IMPROVEMENT_ROADMAP.md   # Roadmap with 🔴/🟡/⚪ deadline-priority flags for TEI paper
├── DL_BED_FEASIBILITY.md, EXPERIMENT_UI_AND_PIPELINE.md, GROOVEGEN_V1_REPORT.md,
│   NEXT_STEPS_ROADMAP.md, STAGE1_PROTOCOL.md   # background/history docs, not required reading
│                                               #   for this handoff but useful for Section 6.
└── PROJECT_HISTORY_AND_DECISIONS.md            # ⚠️ REFERENCED BELOW BUT DOES NOT YET EXIST
                                                # on disk as of this handoff (confirmed via
                                                # `find` — no match anywhere in the workspace).
                                                # Treat Section 6 below as the best-available
                                                # substitute until that file is created.

assess/  (sibling directory: /home/user/workspace/assess/)
├── BUILD_SPEC.md      # the spec that ordered the bed-library build (Section 5)
├── CODE_AUDIT.md       # root-cause audit — 4 confirmed findings (Section 5.4)
├── PATH_RESEARCH.md    # literature/tooling justification for library + RubberBand approach
├── BUILD_REPORT.md     # what was actually built/changed, offline test results, caveats
└── DIAGNOSIS_INPUT.md  # original bug report that triggered the audit (not required reading)
```

### CRITICAL WORKFLOW RULE — notebooks are generated, never hand-edited
Every current notebook is produced by running its builder script with plain `python3`:

```bash
python3 build_notebook_partA.py      # -> notebooks/A_setup_and_experiment_ui.ipynb
python3 build_notebook_libbuild.py   # -> notebooks/LIB_build_beds.ipynb
python3 build_notebook_BC.py         # -> notebooks/BC_generate_and_closed_loop.ipynb
python3 build_notebook_15.py         # -> notebooks/15_closed_loop_hr_audio.ipynb
```

Builders construct cells with two tiny helpers, `md(text)` and `code(text)`, appended to a
`cells` list, then call `nbf.write(nb, f)` at the end (e.g. `build_notebook_BC.py:343-345`,
`out = "notebooks/BC_generate_and_closed_loop.ipynb"`). **If you need to change notebook
behavior, edit the corresponding `build_notebook_*.py` string literal, then re-run the
builder.** Editing the `.ipynb` JSON directly will be silently clobbered the next time anyone
regenerates it, and diverges from what the builder documents.

**Backslash gotcha:** inside a builder's `code(r"""...""")` **raw** string, a literal `\\` in
the source is NOT collapsed the way it would be in a plain (non-raw) Python string — it stays
two characters. `BUILD_REPORT.md` §4 documents a real bug from this: six `print(f"\\n...")`
lines inside raw-string cells in `build_notebook_libbuild.py` would have printed the literal
two characters `\n` instead of a newline. When writing/editing raw-string cell bodies, use a
single `\n` for an actual newline; only use `\\` when you want a literal backslash to survive
into the emitted cell (e.g. inside a shell command string that itself needs an escaped
character). After any such edit, rebuild and spot check the emitted cell source, and
`grep` the builder for stray `\\n` patterns as a regression check.

---

## 4. HOW TO RUN (current pipeline)

Primary reference: `COLAB_RUNBOOK.md` (current; `README.md`/`HOW_TO_RUN.md` are stale — ignore
their notebook numbering). Run in this order, all on Colab:

### (a) `notebooks/LIB_build_beds.ipynb` — once, on GPU
Builds and lets you curate the multi-BPM instrumental bed library. Structure (from
`build_notebook_libbuild.py`, 18 cells): 0.1 code-zip upload/setup → 0.2 install (full stack +
**pyrubberband + rubberband-cli + fluidsynth + fluid-soundfont-gm**) → 0.3 hub guard + MusicGen
load → Part 1 config (`BPM_ANCHORS`, reference-anchored `PROMPTS` dict) → 1.1 generate
MusicGen candidates per (genre, bpm), gated → 1.2 latin symbolic fallback (MIDI + fluidsynth)
→ 1.3 curate (listen + edit the `KEEP` dict) → 1.4 commit `KEEP` into `library/{genre}/{bpm}bpm_{tag}.wav`
→ **1.5 persist `library/` to Google Drive** (`MyDrive/GrooveGen/bed_library/`) so it survives
a runtime disconnect. Run this only when you need to (re)curate the library, not every session.

### (b) `notebooks/A_setup_and_experiment_ui.ipynb` — CPU is fine
Setup (Part 0) + the experiment UI (Part A): calibrate a subject, type a target/measured
heart rate, and step the closed-loop cascade controller bar-by-bar. No GPU needed (built by
`build_notebook_partA.py`).

### (c) `notebooks/BC_generate_and_closed_loop.ipynb` — GPU
- **0.1 / 0.1b**: unzip code, then **restore the bed library from Drive** if present (mirrors
  from `MyDrive/GrooveGen/bed_library` back into local `library/`, so `USE_LIBRARY=True` finds
  curated beds without regenerating; harmless no-op if there's no Drive copy — falls back to
  `gen_bed`).
- **0.2**: install stack, pinned exactly as below.
- **Part B**: hub guard, load MusicGen, then `generate_and_gate(segments, gen, BED_CACHE_DIR,
  gate=QualityGate(max_beat_jitter_ms=45.0, min_pulse_clarity=0.30), max_tries=5, cache=True)`
  — writes beds to `outputs/audio/nb15/beds/`.
- **Part C**: sets `os.environ["GROOVEGEN_SETUP_DONE"] = "1"`, then `%run
  notebooks/15_closed_loop_hr_audio.ipynb` **in-process** — nb15 detects that flag and skips
  its own redundant reinstall/model-reload, reusing Part B's already-loaded MusicGen and cached
  beds. You'll see `[BC] setup skipped ...` / `[BC] reusing already-loaded MusicGen`. nb15
  itself has `USE_CACHED_BEDS = True`, so per-segment you should see `CACHED gated bed ->
  segK_...` confirming zero redundant MusicGen calls.
- Alternative: open `notebooks/15_closed_loop_hr_audio.ipynb` directly and step through it
  cell-by-cell (e.g. to tweak the HR setpoint curve, mix, or figure) — cached beds on disk are
  picked up the same way.

### Colab dependency pins (exact — do not deviate)
```
transformers==4.44.2
huggingface_hub>=0.23.2,<0.26
tokenizers<0.20
```
plus, for the library builder and any RubberBand/symbolic-latin path:
```
pyrubberband           (pip)
rubberband-cli         (apt-get)
fluidsynth             (apt-get)
fluid-soundfont-gm     (apt-get — install EXPLICITLY; not always pulled in by fluidsynth alone
                        on current Colab images, and a silent missing-soundfont failure only
                        surfaces downstream in the symbolic-latin fallback)
```
`transformers==4.44.2` is pinned because newer versions throw a **CUDA device-side assert**
inside MusicGen. Do not `-U` it.

### The hub-1.x self-healing guard
Colab images increasingly ship `huggingface_hub` 1.x, which transformers 4.44.2 cannot use
(`ImportError`). Because downgrading an **already-imported** package only takes effect after a
process restart, every install cell that loads MusicGen (`build_notebook_BC.py`,
`build_notebook_libbuild.py`, `build_notebook_15.py`) runs this exact guard pattern before
importing `transformers`:
```python
import importlib.metadata as _md, sys as _sys
_hub = _md.version("huggingface_hub")
if int(_hub.split(".")[0]) >= 1:
    print(f"huggingface_hub=={_hub} is too new; installing a compatible version...")
    get_ipython().system('pip install -q "huggingface_hub>=0.23.2,<0.26" "transformers==4.44.2" "tokenizers<0.20"')
    if "huggingface_hub" in _sys.modules or "transformers" in _sys.modules:
        raise SystemExit(
            "Installed the correct huggingface_hub, but the old one was already loaded "
            "in this session. RESTART THE RUNTIME: Runtime menu -> Restart session. "
            "Then re-run 0.1, 0.2, and this cell. (One-time on a fresh VM.)")
print("huggingface_hub OK ==", _md.version("huggingface_hub"))
```
**Fresh runtime vs same-runtime rerun rule:** on a brand-new VM, this guard installs the
correct hub version and continues in the same run (nothing was imported yet, so no restart is
needed) *unless* the initial version check itself trips (`>=1`) after `huggingface_hub` or
`transformers` already got imported earlier in that same session — in that case it raises
`SystemExit` and you must **Runtime → Restart session**, then re-run cells 0.1, 0.2, and this
guard cell from the top. If you're rerunning cells in an already-successfully-initialized
runtime (hub already pinned, MusicGen already loaded), the guard is a fast no-op — you do not
need to restart every time, only the first time a stale hub 1.x install is detected mid-session.

---

## 5. BED LIBRARY SYSTEM (most recent work)

This is very likely what you'll be asked to extend, so read this section fully before touching
`groovegen/bed_library.py`, `build_notebook_libbuild.py`, or the library-lookup block in
`build_notebook_15.py`.

### 5.1 Architecture
- **Layout on disk:** `library/{genre}/{bpm}bpm_{tag}.wav`, e.g.
  `library/latin-salsa/128bpm_cand2.wav`. Genre folder names are sanitized with
  `sanitize_genre()` — same regex as `generate_and_gate.py`'s existing sanitizer,
  `re.sub(r"[^0-9A-Za-z]+", "-", g).strip("-")` — so `"latin/salsa"` → `"latin-salsa"`,
  `"r&b/soul"` → `"r-b-soul"`.
- **`groovegen/bed_library.py`** (180 lines) exposes:
  - `list_library(genre, library_dir=LIBRARY_DIR)` — returns `[(bpm, path), ...]` parsed from
    filenames; `[]` for a missing/empty folder.
  - `pick_nearest_bed(genre, target_bpm, library_dir=LIBRARY_DIR)` — nearest-bpm match within
    that genre; `None` if the genre folder is empty.
  - `retime_bed(src_path, dst_path, from_bpm, to_bpm, crispness=6)` — pitch-preserving
    time-stretch via **pyrubberband** (primary), falling back to `librosa.effects.time_stretch`
    **with an explicit `warnings.warn(...)`** if pyrubberband/the `rubberband` CLI is
    unavailable (never a silent quality downgrade). Skips the stretch (near-identity copy)
    when the ratio is negligibly close to 1.0.
- **`USE_LIBRARY = True`** toggle lives in `build_notebook_15.py` right next to
  `BED_CACHE_DIR`. Per-segment bed resolution priority, in order:
  1. **Library** — `pick_nearest_bed(lib_genre, seg_tempo)` then `retime_bed(...)` to the exact
     committed tempo. `GENRE_TO_LIBRARY_KEY = {"latin": "latin/salsa", "pop": "pop", "r&b":
     "r&b/soul", "calm": "calm"}` maps nb15's display genre keys to the library's folder keys
     explicitly (deliberately not relying on string equality, so a rename on either side fails
     loudly instead of silently missing the library).
  2. **Per-run quality-gated cache** (`BED_CACHE_DIR`, existing `generate_and_gate` behavior) —
     used only if the library has nothing for that genre.
  3. **`gen_bed()` (live MusicGen)** — last resort.
  Set `USE_LIBRARY = False` to fall back to the pre-library cache-or-generate behavior
  unchanged.
- **Reference-anchored prompts + symbolic-latin fallback:** `LIB_build_beds.ipynb`'s `PROMPTS`
  dict (in `build_notebook_libbuild.py`) writes rich, genre-true prompts naming concrete
  instrumentation and a well-known-style cue — e.g. for latin/salsa 128 BPM: *"an authentic
  salsa/latin groove in the style of classic Marc Anthony salsa, at 128 BPM, piano montuno
  locked to a 2-3 son clave, syncopated bass tumbao, congas and timbales, bright horn stabs,
  instrumental, no vocals"*. `BPM_ANCHORS` per genre: `latin/salsa: [128,120,112,105]`,
  `pop: [104,100,95,90]`, `r&b/soul: [88,84,80]`, `calm: [80,76,72,70]`,
  `N_CANDIDATES_PER_ANCHOR = 3`. If MusicGen's latin/salsa candidates repeatedly fail the
  quality gate (dense montuno/clave textures can defeat MusicGen's drum coherence), a
  **symbolic fallback** — `genre_styles.build_style_seed("latin/salsa", ...)` rendered to audio
  via the `fluidsynth` CLI + a GM soundfont — provides an honest, MIDI-based alternative that
  never depends on MusicGen learning clave/montuno/tumbao correctly.
- **Drive persistence:** `LIB_build_beds.ipynb` cell **1.5** mounts Drive and mirrors
  `library/` → `MyDrive/GrooveGen/bed_library/` (run once, after curating). `BC_generate_and_
  closed_loop.ipynb` cell **0.1b** restores it: if local `library/` already has `.wav` files it
  no-ops; otherwise it mounts Drive and copies `MyDrive/GrooveGen/bed_library/*/*.wav` back into
  local `library/`, printing `"restored {N} beds from Drive -> library/"`, or `"no Drive
  library found -- USE_LIBRARY will fall back to gen_bed."` if there's nothing there.

### 5.2 Why this exists — the 4 root causes it fixes
Full detail in `/home/user/workspace/assess/CODE_AUDIT.md`; summary of the 4 confirmed
findings and how the library system addresses them:

1. **Prompt fidelity collapse.** `profile_from_songs.py` extracts ~20 numeric features per
   reference song (13 MFCCs + spectral centroid/std + 2 HPSS ratios + onset density + event
   ratio + tempo), but `prompt_from_anchor()` only ever reads 5 of them and collapses each to a
   ternary/binary categorical word — **none of the 13 MFCCs are used at all.** The final prompt
   template encodes exactly 1 continuous number (tempo) + 4 categorical flags + 1-of-6 genre
   words. This is architecturally why MusicGen output can't resemble a reference song's actual
   timbral character — the song's fingerprint never reaches the model. *(The library system
   doesn't fully solve this — it sidesteps it for the primary audio path by using
   human-curated, richly-worded, reference-anchored prompts instead of the lossy automatic
   pipeline for at least the pre-built library beds.)*
2. **Genre-snap unreliability, especially for latin/salsa.** `nearest_known_genre()` computes
   `dist = 0.4*tempo_dist + 1.0*timbre_dist` against hand-authored prior constants — "a simple
   nearest-centroid heuristic, not a trained classifier" per its own docstring. Worse: `genre_
   styles.py` sets latin's nominal tempo anchor at 180 BPM, but the live controller caps latin
   at `tempo_max=140`, so `tempo_dist` is always measured against a target latin can never
   reach — meaning **pop or metal can structurally out-score latin at plausible committed
   tempos.** Additionally, the automatic prompt template never emits "clave", "montuno",
   "conga", "tumbao", or "horn stabs" even though `genre_styles.py` encodes exactly that
   vocabulary for the symbolic/MIDI side — that richer description never reaches the MusicGen
   text prompt. *(Fixed for library beds: the library's `PROMPTS` dict hard-codes that
   vocabulary directly, bypassing the lossy automatic prompt builder entirely for latin/salsa.)*
3. **Naive resampling pitch-shifted audio.** The old `_resample_to_tempo()` (in
   `notebooks/extra_transition_cell.py`, not wired into any current builder) used plain
   `np.interp` linear resampling — "like a turntable," per its own comment — which necessarily
   pitch-shifts audio proportional to the tempo-change ratio. Hard-coded `BAND_TARGET_BPM`
   steps (128/104/88/72) produce ratios up to ~1.23×, well beyond negligible drift, causing
   audible pitch/transient smear. *(Fixed: `retime_bed()` uses RubberBand, a genuine
   phase-vocoder/time-domain stretcher that decouples tempo from pitch, verified by
   `PATH_RESEARCH.md` §4 as reliable to ±10–20% with graceful degradation out to ~50%, versus
   librosa's own phase_vocoder which its authors describe as "likely to produce many audible
   artifacts.")*
4. **Drum-grid trust / doubled-tempo detection.** Drums are rendered onto the bed's *detected*
   beat grid (`hr.get_bed_info(...)`, aliased to `hybrid_render.analyze_bed()`), which used a
   `_fix_octave`/`_octave_snap_grid` correction with a hard-coded `tempo_max=180` band and a
   re-entrant fold-decision loop. On a 199-BPM-detected / 128-BPM-true latin case, one fold
   step only reaches ~99.5 BPM and then the loop's own re-test of its post-fold ratio caused it
   to either understop or oscillate — landing drums on the wrong grid entirely (audible as
   "drums disconnected from the bed"). *(Fixed: `_octave_snap_grid` was rewritten to make the
   densify/thin/leave-alone decision **once**, directly from the raw pre-fold ratio, never
   re-testing a post-fold value — see Section 7 for the exact before/after numbers. `build_
   notebook_15.py` was also changed to pass a **segment-specific** `tempo_min`/`tempo_max` band
   — `max(30.0, expected_tempo*0.55)` to `expected_tempo*1.45` — to `hr.get_bed_info(...)`
   instead of relying on the old fixed 70–180 default, so the octave-fold logic stays anchored
   to the right neighborhood for every genre, not just pop/rock tempos. The `splice_beds_
   downbeat_hard_cut` helper's two internal `get_bed_info` calls were updated the same way,
   since `get_bed_info`'s cache key includes `tempo_min`/`tempo_max` and would otherwise
   silently miss the freshly-computed cache entry.)*

Also relevant background from `PATH_RESEARCH.md`: the curated-library-with-nearest-BPM-
selection pattern has direct precedent in peer-reviewed adaptive/biofeedback-music systems
(e.g. [Van den Berghe et al. 2021, *Scientific Reports*](https://www.nature.com/articles/s41598-021-83538-w),
a 77-track BPM-tagged database with tempo-shift-not-pitch-shift playback), and MusicGen-class
models are documented to draw only ~5.7–6% of training data from non-Western genres
([arXiv "Missing Melodies"](https://arxiv.org/html/2412.04100v3)), which is the literature
basis for treating latin/salsa's weak generative fidelity as a structural, citable limitation
rather than a prompt-engineering failure — motivating the symbolic/soundfont fallback as the
more honest choice for that genre specifically.

---

## 6. KEY DESIGN DECISIONS & RATIONALE

The canonical, detailed log of *why* things are built the way they are is meant to live in
**`PROJECT_HISTORY_AND_DECISIONS.md`** (a sibling file at
`/home/user/workspace/groovegen_project/PROJECT_HISTORY_AND_DECISIONS.md`). **As of this
handoff, that file does not exist yet** (confirmed via a full-workspace search) — treat any
reference to it as forward-looking/pending. If it exists by the time you read this, read it
before this section; if not, flag its absence to whoever assigned you this task, and in the
meantime rely on the primary sources already cited throughout this document:

- `/home/user/workspace/assess/BUILD_SPEC.md` — the literal task spec that ordered the bed
  library build (goal, deliverables, constraints).
- `/home/user/workspace/assess/CODE_AUDIT.md` — the 4 root-cause findings (Section 5.2 above).
- `/home/user/workspace/assess/PATH_RESEARCH.md` — model-comparison table and literature
  justification for the library + RubberBand + symbolic-latin approach (Section 5.2 above).
- `/home/user/workspace/assess/BUILD_REPORT.md` — exactly what was implemented, offline test
  results (including a full `_octave_snap_grid` before/after table), and caveats (Section 7
  draws on this directly).
- `ARCHITECTURE_TWO_TIMESCALE.md` — the two-timescale design (slow neural bed + fast symbolic
  drums) and why the controller has no integral term (§5.2 of that doc).
- `HYBRID_IMPROVEMENT_ROADMAP.md` — a prioritized roadmap with 🔴 PAPER-CRITICAL / 🟡
  PAPER-NICE / ⚪ POST-DEADLINE flags against the **TEI 2027, July 31, 2026** deadline —
  useful for triaging any "what should I work on" question.

---

## 7. KNOWN CAVEATS / GOTCHAS

- **MusicGen's 30-second position-embedding ceiling.** `facebook/musicgen-small`'s sinusoidal
  positional-embedding table (`generation_config.max_length=1500`) tops out around 1500 tokens
  ≈ 30s at MusicGen's ~50Hz EnCodec token rate. Requesting more overflows `position_ids` →
  `index_select` out of range → `CUDA error: device-side assert triggered` inside
  `MusicgenSinusoidalPositionalEmbedding.forward`. The fix already in place
  (`build_notebook_15.py`'s `gen_bed()`/`_loop_to_length()`): generate a **short** bed
  (`GEN_SECONDS = 12.0`, `MAX_NEW_TOKENS_CAP = 1400`, safely under the ceiling) and **loop** it
  to fill a longer segment — trimmed to a whole number of bars first (so the loop point lands
  on a downbeat) with a 1.5ms micro-fade at the wrap to kill click artifacts. Do not simply
  raise `max_new_tokens` past ~1400 to get longer single-shot generations.
- **The 199-vs-128 BPM octave case only reconciles to ~99.5–100 BPM, not exactly 128, without
  `lock_tempo`.** This is mathematically expected, not a bug: 199/128 = 1.555, which is not a
  power of 2, so a single octave-fold (halving) is the closest any pure fold can get —
  confirmed directly in `hybrid_render.py`'s `_octave_snap_grid` docstring and in `BUILD_
  REPORT.md`'s verification table (199→99.5 exactly; contrast with the clean cases 64→128 and
  256→128, both exact). The residual ~28 BPM gap is a genuine tempo-detection error, not an
  octave error, and closing it fully requires passing `analyze_bed`'s existing `lock_tempo`
  parameter when the caller already knows the true committed tempo — don't try to "fix" this
  further inside `_octave_snap_grid` itself; that function's job stops at reaching the nearest
  reachable octave.
- **Latin/salsa MusicGen fidelity is prompt-dependent and inherently weaker than other
  genres.** This is a documented, literature-grounded limitation (non-Western training-data
  scarcity — Section 5.2, finding #2), not something a better prompt alone fully solves, which
  is why the symbolic/fluidsynth fallback exists as a first-class option for this genre rather
  than a last-resort patch.
- **The quality gate measures tempo steadiness, not genre authenticity.** `QualityGate` only
  checks `beat_jitter_ms` and `pulse_clarity` (Section 2.3) — it will happily pass a
  perfectly-steady bed that sounds nothing like "salsa." Only a human, during `LIB_build_
  beds.ipynb`'s curation cell (1.3, editing the `KEEP` dict), judges genre-authenticity/
  "salsa-ness." Do not assume a passing gate implies genre-correct output.
- **`notebooks/extra_transition_cell.py` is not wired into any builder.** It's a standalone
  paste-in snippet (confirmed via project-wide search — no `%run`/import references it from any
  current builder). Its `_resample_to_tempo` was replaced with a RubberBand-based
  `_retime_array_to_tempo` per `BUILD_REPORT.md`, but if you need this behavior in the live
  pipeline, you must explicitly wire it in — it does not run automatically.
- **README.md and HOW_TO_RUN.md are stale.** They document an old 00–08 notebook numbering
  with a Raspberry Pi / `app.py` web-UI flow that has been superseded by the A/LIB/BC/15
  pipeline. Don't use them for run instructions; use `COLAB_RUNBOOK.md` and Section 4 above.
  If you're asked to update project docs, these two are prime candidates for a rewrite or a
  "superseded — see COLAB_RUNBOOK.md" banner.

---

## 8. GLOSSARY

- **Bed** — an instrumental backing track (drums+harmony+bass etc., no vocals) for one segment
  of the piece, either MusicGen-generated, pulled from the curated `library/`, or (latin only,
  as a fallback) symbolic MIDI rendered via fluidsynth.
- **Knob** — a controllable musical parameter the system can vary in real time to express the
  controller's output (e.g. event density, tempo, genre).
- **Tier1 / Tier2** — the two-timescale architecture's layers: a slow-changing "neural bed"
  (regenerated occasionally, expensive) and a fast-updating symbolic drum layer (updated
  per-bar, cheap) — see `ARCHITECTURE_TWO_TIMESCALE.md`.
- **Cascade** (`CascadeController` in `pd_controller.py`) — the 3-tier genre→tempo→density
  controller with anti-fight hysteresis: density always acts every step; tempo only acts once
  density has been saturated for `n_bars_saturated_for_tempo` (default 3) consecutive bars;
  genre only acts once tempo has also been saturated for `n_bars_saturated_for_genre` (default
  5) consecutive bars. Prevents multiple tiers from fighting each other over the same error.
- **AMT** — Automatic Music Transcription; used in `dlbed.py`'s `midi_bed_to_profile()` to turn
  transcribed MIDI into a frozen `BedProfile`.
- **StyleSpec** — the dataclass in `genre_styles.py` defining a genre's nominal tempo,
  `comp_style` (block/sustain_accent/arp/staccato_chug), instrumentation (GM program numbers),
  and descriptive text, keyed by genre name in the `GENRE_STYLES` dict.
- **comp_style** — the harmonic "comping" pattern style a `StyleSpec` uses: `block` (block
  chords), `sustain_accent`, `arp` (arpeggiated), or `staccato_chug`.
- **Iso-principle** — music-therapy concept: match the listener's current affective/arousal
  state first, then gradually shift the music toward a target state. Used here **only to
  justify the sign/direction** of the controller's tempo/density mapping (Section 2.1), never
  as efficacy evidence. Sources: [Mayr & Starcke 2021](https://pubmed.ncbi.nlm.nih.gov/34886210/),
  [Watanabe, Kashino & Ooishi 2017](https://pubmed.ncbi.nlm.nih.gov/28266647/).
- **BBCI** — Brain-Body Computer Interface; the broader closed-loop system this project is a
  generative-audio component of (PPG/GSR/respiration → PD control → music/haptics), per
  `HYBRID_IMPROVEMENT_ROADMAP.md`'s framing.
- **Gate** (quality gate) — `QualityGate` in `generate_and_gate.py`; pass/fail test on
  `beat_jitter_ms` + `pulse_clarity` only (Section 2.3), used both by the live per-run
  generation path and by `LIB_build_beds.ipynb`'s candidate curation.

---

## 9. "IF YOU ARE ASKED TO..." PLAYBOOK

### Add a new genre
Touch, in order: (1) `groovegen/genre_styles.py` — add a new `StyleSpec` entry to
`GENRE_STYLES` (tempo, `comp_style`, instrumentation, descriptive text); (2) `groovegen/
prompt_from_anchor.py` — add a `_GENRE_PROMPT_WORD` entry and a `_GENRE_TIMBRE_PRIOR` tuple for
`nearest_known_genre()`'s heuristic; (3) `groovegen/pd_controller.py` — decide whether the new
genre needs an entry in `GENRE_ENERGY_ORDER` and `GENRE_EQUILIBRIUM_BAND` if it participates in
the cascade's genre tier; (4) `build_notebook_libbuild.py` — add a `BPM_ANCHORS` entry and
hand-write reference-anchored `PROMPTS` for it (remember the `"instrumental, no vocals"`
suffix and, if it's a genre with sparse MusicGen training data like latin, consider a symbolic
fallback path); (5) `build_notebook_15.py` — add it to `GENRE_TO_LIBRARY_KEY`, `GENRE_TO_STYLE`,
`GENRE_DISPLAY_LABEL`, and its tempo `BAND_RANGE`; (6) rebuild affected notebooks and re-curate
the library (run `LIB_build_beds.ipynb` again for the new genre's anchors).

### Add a new BPM anchor to an existing genre
Edit `BPM_ANCHORS` in `build_notebook_libbuild.py` (add the value to that genre's list) and add
a matching entry to that genre's dict in `PROMPTS`. Rebuild with `python3
build_notebook_libbuild.py`, then re-run `LIB_build_beds.ipynb` on GPU to generate/curate
candidates at the new anchor and commit them into `library/{genre}/{bpm}bpm_{tag}.wav`. No
change needed to `pick_nearest_bed`/`retime_bed` — they already work over whatever anchors
exist on disk.

### Change the HR setpoint arc
Edit the scripted HR curve cell in `build_notebook_15.py` (search for the cell that defines the
descending HR curve / calls into `TempoController`/`CascadeController` with `initial_tempo`
seeded from a resting-HR-like value — see `pd_controller.py`'s `tctrl.reset(initial_tempo=
resting_hr)` pattern). Preserve the **"SCRIPTED, IMPOSED SETPOINT... controller TRACKS it, does
not cause the descent"** framing in any accompanying markdown — do not describe a new arc as
something the music "achieves." If the new arc changes how many genre-band crossings occur,
check/update the `4 <= len(segments) <= 5` and `EXPECTED_GENRE_ORDER` assertions in
`build_notebook_15.py`'s segment-derivation cell, or they will fail loudly (by design).

### Improve latin/salsa fidelity further
Start from `/home/user/workspace/assess/CODE_AUDIT.md` finding #2 and `PATH_RESEARCH.md` §5.
Do not simply try harder MusicGen prompts as the only lever — the literature basis here is that
non-Western genre fidelity is a structural training-data limitation. Prefer: (1) expanding the
symbolic/fluidsynth fallback's musical vocabulary in `genre_styles.py`'s latin `StyleSpec` and
`build_style_seed()`; (2) adding more curated MusicGen candidates at tighter BPM anchors in
`LIB_build_beds.ipynb` and being more selective in the curation step; (3) only as a secondary
option, consider `musicgen-style`/`musicgen-melody` conditioning per `PATH_RESEARCH.md` §1–2 —
note these are text+audio-conditioned variants Meta ships, not yet integrated anywhere in this
codebase, so this would be new integration work, not a config change.

### Draft or extend the TEI paper
Deadline is **July 31, 2026**. Start from `HYBRID_IMPROVEMENT_ROADMAP.md` (has 🔴/🟡/⚪
deadline-priority flags per work item) and `ARCHITECTURE_TWO_TIMESCALE.md` (system architecture
section). Reuse the **evidence-tier table** pattern from `build_notebook_15.py` (search
`Evidence-tier table`) for any claims table — every claim must be classified (e.g. "simulated
control-loop", "real-audio demo, single run", "literature citation, sign-only", "real-human-data:
NONE YET"), and nothing may claim measured physiological efficacy (Section 2.1). Cite Mayr &
Starcke (2021) and Watanabe/Kashino/Ooishi (2017) only for sign, never magnitude.

### Run a (simulated) study end-to-end
Run the pipeline in Section 4 order (LIB once → A → BC, which %runs 15). Confirm `USE_LIBRARY =
True` and that the Drive-backed library actually restored (`BC` cell 0.1b output should say
"restored N beds from Drive", not "no Drive library found"). At the end, verify the MP4 output
with `ffmpeg -i <file>.mp4 -af volumedetect -f null -` and confirm `mean_volume` is not
`-inf` before treating the run as successful. Remember: no human-subjects data is used or
implied anywhere in the current notebooks (IRB pending) — do not add real physiological input
without flagging that as a scope change requiring IRB consideration.

### Fix a build/runtime error mentioning `huggingface_hub` or a CUDA device-side assert
This is almost certainly the hub-1.x/transformers-4.44.2 mismatch (Section 4). Do not upgrade
transformers. Re-run the setup/install/hub-guard cells from the top of whichever notebook
failed; if the guard cell raises `SystemExit` telling you to restart, **Runtime → Restart
session**, then re-run cells 0.1, 0.2, and the guard cell again — do not skip the restart.

### Regenerate any notebook after editing its builder
```bash
python3 build_notebook_<name>.py
```
then re-open the `.ipynb` under `notebooks/` to confirm the emitted cells look right (especially
check for the raw-string `\\` gotcha in Section 3 if you touched any `code(r"""...""")` block).
Never hand-edit the resulting `.ipynb`.
