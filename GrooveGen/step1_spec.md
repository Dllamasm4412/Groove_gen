# STEP 1 BUILD SPEC — Continuous, non-repetitive GrooveGen engine (event-density-centered)

## Context
GrooveGen = hybrid engine: neural BED (MusicGen, offline/expensive) + symbolic DRUMS (pretty_midi + FluidSynth, online/cheap). Primary groove knob (locked by literature) = **EVENT DENSITY** (monotonic, safe for closed-loop control). Backbeat = anchor (must stay locked for entrainment). Syncopation = bounded spice only (clamp 0.20–0.40). Microtiming = cosmetic.

Sandbox = Python 3.12, CPU only, NO MusicGen/GPU. Use uploaded/synthetic beds as the "bed bank". SoundFont: /usr/share/sounds/sf2/FluidR3_GM.sf2.

## The problem to fix
`groovegen.py::PatternBuilder.build_looped()` (line ~983) copies ONE core bar byte-for-byte N times and tiles ONE bed cycle repeatedly → perfect repetition. That is what we must replace.

## Key existing code (DO NOT break the frozen study path)
- `GrooveParams` dataclass (line ~344): tempo_bpm, bars, target_seconds, seed, event_density(int), swing_amount, swing_level, syncopation_level(0-1), microtiming_variance_ms, with_bed, bed_profile, drum_style.
- `PatternBuilder.build_core()` builds ONE bar from params. `build_looped()` tiles it. `_density_steps()` allocates onset budget by metrical rank (kick+snare=4 baseline; hats fill quarters→8ths→16ths; spill to ghost snares). `sec_per_beat`, `bar_seconds` properties. `render_wav(pm, out_wav, ...)` renders + loudness-normalizes.
- Seed drives all stochastic elements via `np.random.default_rng(params.seed)`.

## DELIVERABLE 1: new module `continuous.py` in groovegen_project/groovegen/
Add a NEW module (do NOT rewrite groovegen.py's frozen study path). It must:

### A. Per-bar symbolic variation via a bounded random walk on EVENT DENSITY
- Function `density_walk(base_density:int, n_bars:int, band:tuple[int,int], step_sd:float, seed:int) -> list[int]`:
  seeded Gaussian random walk, clamped to `band` (e.g. (6,14)), reflecting at edges. This is the PRIMARY variation axis.
- Function `bar_params(base:GrooveParams, bar_idx:int, density:int, seed:int) -> GrooveParams`:
  returns a copy of `base` with: event_density=density; seed = base.seed + bar_idx (deterministic-but-different per bar); syncopation_level = clamp(base.syncopation_level + small seeded jitter, 0.20, 0.40) ONLY if base.syncopation_level>0 else 0; microtiming tiny (e.g. base value). Backbeat is NEVER moved (it's structural in build_core — just don't touch beats 2&4).
- Function `build_varied_drums(base:GrooveParams, n_bars:int, band, step_sd, seed) -> pretty_midi.PrettyMIDI`:
  for each bar, build a 1-bar core with bar_params, offset its notes by bar_idx*bar_seconds, append to one drum instrument. Result = endless-feeling, never-identical drum track. Return the PrettyMIDI (drums only) + also return the list of per-bar densities (for a manipulation-check plot).

### B. Bed-bank + beat-matched (bar-aligned) equal-power crossfade
- Function `crossfade_beds(bed_wavs:list[str], tempo_bpm:float, out_wav:str, target_seconds:float, xfade_bars:float=1.0, fs:int=44100) -> dict`:
  load each bed wav (librosa, mono, fs), time-stretch/trim each to an integer number of bars at tempo_bpm if needed (keep simple: trim to nearest whole bar; if a bed is shorter than one bar, tile it). Concatenate beds in sequence with EQUAL-POWER crossfades of length `xfade_bars * bar_seconds`, aligned so the crossfade starts on a bar boundary. Loop through the bank as many times as needed to reach target_seconds. Equal-power = `cos/sin` ramps (fade_out=cos(θ), fade_in=sin(θ), θ in [0,π/2]). Return dict with duration, n_segments, xfade_s.

### C. Top-level `render_continuous(base:GrooveParams, bed_wavs:list[str], out_stem:str, n_bars:int, band, step_sd, seed, drum_gain_db=-3.0, bed_gain_db=-6.0) -> dict`
  - build varied drums → render to wav via render_wav (reuse from groovegen.py).
  - crossfade the bed bank to the same duration.
  - mix drums + bed (align lengths, apply gains, prevent clip). Write `{out_stem}.wav`. Return metadata incl. per-bar densities list.

## DELIVERABLE 2: sandbox test + audio verification
- Use the two uploaded beds as the bed bank:
  - salsa: /home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
  - r&b:   /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
  (both 44.1kHz mono ~10.94s ~95-96bpm). Use tempo_bpm=96, base event_density=9, band=(6,13), n_bars=16, seed=0, syncopation_level=0.3.
- Render `/home/user/workspace/step1_outputs/continuous_demo.wav`.
- VERIFY: (1) print duration (~16 bars @96bpm = ~40s), (2) confirm bars are NOT identical — compare note counts / onset positions across bars and print the per-bar density list showing variation, (3) confirm bed crossfades happened (n_segments>1), (4) render an MP4 later (parent will do video). For now confirm the WAV is non-silent: `ffmpeg -i continuous_demo.wav -af volumedetect -f null - 2>&1 | grep mean_volume` — mean must NOT be -inf.
- Save a small manipulation-check PNG: per-bar event density over bars (line/step plot), title "Per-bar event density varies (primary knob) — backbeat locked". Palette accent #4F98A3 on dark #171614 is fine, or default whitegrid. Save to /home/user/workspace/step1_outputs/density_walk.png.

## Critical requirements
- DO NOT modify the frozen study/stimulus path in groovegen.py. New code lives in continuous.py.
- Everything seeded & reproducible.
- Filter render noise: `2>&1 | grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|_a in|librosa"`
- Report back: file paths written, per-bar density list, volumedetect mean_volume, and any design decisions/tradeoffs you made. Be critical — if bar-trimming the beds causes audible clicks or the crossfade sounds bad, say so and note the fix.

## Output location
All new outputs → /home/user/workspace/step1_outputs/ . New code → /home/user/workspace/groovegen_project/groovegen/continuous.py
