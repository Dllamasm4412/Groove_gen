# STEP 1B REBUILD SPEC — Fix drum coherence + transition speed-up; discrete-piece default

## Context / what we learned (all measured, not guessed)
User feedback on the Step 1 continuous demo: (a) drums sound incoherent / density not musical, (b) transitions between beds speed up and sound weird, (c) user does NOT want always-continuous — prefers discrete finished pieces, with optional crossfade only when continuity is explicitly wanted.

THREE ROOT CAUSES confirmed by measurement:
1. **Incoherent density mapping.** `groovegen.py::PatternBuilder._density_steps()` fills a ranked list quarters→8ths→16ths, so varying density bar-to-bar makes the HI-HAT SUBDIVISION ITSELF teleport (e.g. density 6→[0,4] 2 hats, 9→[0,2,4,8,12] lopsided, 12→[0,2,4,6,8,10,12,14] straight 8ths). Also the density-9 pattern [0,2,4,8,12] is LOPSIDED (gap between 4 and 8). Result: no stable pulse; ear hears the hat pattern jumping around = "off".
2. **Transition speed-up = TEMPO MISMATCH.** Drums render on a rigid 96 BPM grid, but beds have DIFFERENT real tempos: salsa bed 10.94s = 4 bars @ 87.75 BPM (~88), r&b bed is a different tempo entirely. So (i) drums @96 rush against an 88 BPM bed, and (ii) crossfading two beds at different tempos changes pulse speed mid-fade. This is the "speeds up / weird" artifact.
3. **Always-continuous coupling** forced a single drum timeline against a cycling bed bank at conflicting tempos.

## User's chosen design (LOCKED)
- Variation feel: **SUBTLE, PHRASE-LEVEL** — keep a rock-steady hat pulse spine; vary only ghost notes/accents; change the varied quantity only every ~4 bars (phrase level), not every bar.
- Hat spine: **YES, constant hi-hat pulse spine** (fixed subdivision always present); density adds ghost snares / open-hat accents / velocity dynamics ON TOP. Do NOT let the base subdivision thin/thicken.
- Continuity: **DISCRETE PIECES ARE THE DEFAULT.** Each piece = one bed + drums locked to THAT bed's real tempo. Continuity is OPTIONAL and only crossfades pieces AT THE SAME TEMPO.

## DELIVERABLES (all in groovegen_project/groovegen/ — do NOT modify the frozen study path in groovegen.py; put new logic in continuous.py, extend it)

### 1. Tempo detection + lock  (fixes root cause #2)
- `detect_bed_tempo(bed_wav, candidate_range=(70,140)) -> float`: estimate the bed's true tempo. Use librosa beat_track BUT also try the "integer-bars" heuristic: for the given duration, find the tempo in range that makes duration ≈ an integer number of 4/4 bars (bar_s = 4*60/bpm), and reconcile with beat_track (prefer the integer-bars tempo when beat_track is ambiguous/octave-error). Return the bar-aligned tempo. For the salsa bed this should land ~87.75; document the r&b bed's detected tempo.
- In `render_continuous`/new `render_piece`: the drum grid tempo MUST equal the chosen bed's detected tempo (NOT a hardcoded 96). This alone removes the drum "rush".

### 2. Musically-coherent density mapping  (fixes root cause #1) — NEW, do not touch frozen _density_steps
Add `coherent_density_layers(base_density:int, seed:int) -> dict` used only by the varied path:
- **Constant hat spine**: always place a steady closed-hat subdivision (default straight 8ths: steps [0,2,4,6,8,10,12,14]) at every bar, NEVER removed. This is the pulse anchor.
- **Density adds ORNAMENTATION on top of the spine, in this priority order** (so changes are additive/musical, never lopsided):
  1. velocity dynamics on the existing hats (accent on-beats),
  2. ghost snares on off-16ths (symmetric order: 3,7,11,15 then 1,5,9,13),
  3. open-hat accents on the 'and's (e.g. step 14 then 6),
  4. optional extra kick pushes at very high density.
- The spine is fixed; only the ornamentation COUNT scales with (base_density - spine_baseline). No lopsided gaps, subdivision never teleports.
- Provide a helper `build_varied_drums_coherent(base:GrooveParams, n_bars, band, seed, phrase_bars=4)` that:
  - uses a PHRASE-LEVEL density value: draw a new density only every `phrase_bars` bars (a small bounded step, ±1, clamped to band), hold it across the phrase. Subtle.
  - builds each bar from the constant spine + ornamentation for the current phrase density.
  - keeps backbeat locked (beats 2&4) and reuses genre drum style if base.drum_style set (respect the genre's hat_base as the spine when present).
  - seed = base.seed + bar_idx for reproducible per-note velocity humanization (±2) so no two bars are byte-identical, but the PATTERN is stable within a phrase.

### 3. Discrete-piece render + optional same-tempo crossfade  (fixes root cause #3)
- `render_piece(base:GrooveParams, bed_wav:str, out_stem, seconds, band=None, seed=0, subtle=True) -> dict`:
  - detect bed tempo → set drum tempo to it.
  - n_bars from seconds & tempo. If band None, band = (base_density-1, base_density+1) (SUBTLE).
  - build coherent varied drums (phrase_bars=4), render, loop/trim the SINGLE bed (no bank) to match — loop the bed by whole bars at its own tempo, equal-power crossfade the LOOP SEAM of the SAME bed (same tempo, so no speed change).
  - mix, write wav, return metadata (tempo, per-phrase densities, duration).
- `crossfade_pieces(piece_wavs:list[str], tempos:list[float], out_wav, xfade_s=2.0)`: ONLY allow crossfading pieces whose tempos match within ~2 BPM; if they differ, either (a) refuse with a clear message, or (b) time-stretch the second piece to the first's tempo (librosa) before crossfading. Default behavior: if tempos differ >2bpm, print a warning and time-stretch. This is the OPTIONAL continuity path.

### SANDBOX TEST (must pass, audio-verify)
Use both uploaded beds:
- salsa: /home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
- r&b:   /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
1. Print detect_bed_tempo for both (salsa≈88 expected).
2. Render TWO discrete pieces to /home/user/workspace/step1b_outputs/: 
   - piece_salsa.wav (salsa bed, drum_style latin/salsa if available, base_density ~7, 16s, subtle) — drums MUST be locked to the salsa bed's tempo.
   - piece_rnb.wav (r&b bed, drum_style r&b/soul, base_density ~6, 16s, subtle).
3. Print the per-phrase density list for each (should change only every 4 bars, by ±1, small range) and confirm the hat spine is present in every bar (constant subdivision).
4. Audio-verify each: `ffmpeg -i X.wav -af volumedetect -f null - 2>&1 | grep mean_volume` (must not be -inf).
5. Also produce one OPTIONAL-continuity demo: crossfade the two pieces (different tempos → will time-stretch the second) to /home/user/workspace/step1b_outputs/continuous_optional.wav, and REPORT whether the seam still sounds like a speed change (measure tempo continuity at the seam if you can, or at least confirm both halves share one tempo after stretch).

### Critical / be honest
- The GOAL is coherent, musical drums that lock to the bed tempo and vary only subtly at phrase boundaries. If after the fix the drums still fight the bed, MEASURE why (tempo? phase/downbeat offset?) and report it rather than hiding it.
- If the r&b bed's tempo genuinely can't be reconciled (ambiguous), say so and pick the integer-bars tempo.
- Do NOT modify the frozen study path in groovegen.py. All new code in continuous.py.
- Filter render noise: grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|_a in|librosa"

## Report back
- detect_bed_tempo for both beds.
- per-phrase density lists (proving subtle phrase-level variation) + confirmation the hat spine is constant every bar.
- volumedetect mean_volume for piece_salsa, piece_rnb, continuous_optional.
- Whether the drum-rush and transition-speedup are gone (with any measurement you used to confirm).
- Any remaining limitation.

## Output
Code → extend /home/user/workspace/groovegen_project/groovegen/continuous.py
Outputs → /home/user/workspace/step1b_outputs/
