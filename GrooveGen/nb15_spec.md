# Notebook 15 — Closed-Loop HR-Driven Audio Demo (paper hero artifact)

## One-line goal
A scripted SIMULATED heart-rate curve drives CascadeController.step(), which
drives REAL audio: bed regeneration at new tempos joined by downbeat-aligned
HARD CUTS (crossfade is dead), plus per-bar density changes. Output = ONE MP4
where you SEE the HR trace + tempo/density/tier traces and HEAR the system
respond. This is the paper's hero artifact (TEI 2027, system/method contribution).

## Framing decisions (locked, from two subagent assessments)
- TRANSITION = downbeat-aligned HARD CUT. Won every objective seam metric vs
  fill-masked and tempo-ramp (click 0.027 vs 0.093; RMS-disc lowest; 0ms phase
  err; near-zero latency). Crossfade REJECTED by user's ear + by construction
  (smears two incompatible tempo grids). Frame the hard cut honestly: the
  transition is *allowed to be audible*; the bar is "glitch-free seam (no click,
  no doubled hit)", NOT "inaudible transition". This is a lower, more honest bar
  than crossfade's failed goal — say so in the notebook.
- CONTRIBUTION CLAIM = system/method, NEVER efficacy. Never write "regulates
  emotion". Write "control architecture that produces stable, non-oscillating
  tempo/density trajectories in response to a simulated arousal signal,
  demonstrated in real audio." Physiology is SIMULATED; plant is a literature-
  grounded TOY (sign only, not fitted).

## HR curve (MUST include 3 phases — audit requirement)
The scripted synthetic HR (bpm) -> arousal setpoint drives the loop. Include:
1. RAMP DOWN (down-regulation): HR starts elevated (~elevated arousal) and the
   TARGET is calm -> controller lowers tempo, walks genre backward if tempo
   saturates. This is the robust R&B<-Pop half — the hero clip.
2. PLATEAU: HR holds steady in-band -> controller should mostly do nothing
   (tier_that_acted == 'none' or small density-only corrections). Proves it
   doesn't fidget when it shouldn't.
3. PERTURBATION (disturbance rejection): inject a sudden HR spike during the
   plateau -> controller must reject it (density fast-loop first, tempo if it
   saturates). This proves DISTURBANCE REJECTION, not just ramp-tracking — the
   audit says this is what elevates it from demo to proof.
Keep total musical duration reasonable (~30-45 s of audio) so the MP4 is short
enough to watch but long enough to hear the transitions. Map HR->arousal with a
simple documented linear/normalized transform (state the mapping in a markdown
cell; it is a modeling choice, not a measurement).

## Closed-loop wiring (per musical bar)
Use the EXISTING CascadeController from groovegen.pd_controller. Do NOT
reimplement. Loop structure per control tick (= per bar or per few bars):
```
from groovegen.pd_controller import CascadeController, GENRE_ENERGY_ORDER
cc = CascadeController(...)               # reuse defaults from nb13
cc.reset(initial_genre, initial_tempo, initial_density, initial_arousal?)
for bar in range(N_BARS):
    hr = hr_curve[bar]
    measurement = hr_to_arousal(hr)
    out = cc.step(setpoint=TARGET_AROUSAL[bar], measurement=measurement)
    # out = {genre, tempo_bpm, density, tier_that_acted}
    record(out)
```
Then RENDER audio from the recorded trace:
- Whenever tempo (or genre) changes vs the previous committed bed -> we need a
  NEW bed at the new target tempo. On Colab: generate via MusicGen (reuse nb14's
  transformers facebook/musicgen-small pattern + prompt-for-tempo-then-detect).
  Join consecutive beds with splice_beds_downbeat_hard_cut (see below).
- Density changes每 bar -> re-render aligned drums for that bar at the new
  event_density via hybrid_render.render_aligned_drums(bed_info, drum_style,
  event_density=out['density']). Density is the FAST per-bar lever.
- GENERATE-AHEAD: model the commitment lag exactly as nb13 does — when the
  controller commits a next tempo, the bed for it is "already generating" and
  becomes available one segment later. In the audio demo this means: when tempo
  changes, the hard cut to the new bed happens at the NEXT downbeat boundary,
  not instantly. Make this visible in the plot (mark "committed" vs "took
  effect").

## The splice function (DROP IN VERBATIM — validated by subagent A)
Include splice_beds_downbeat_hard_cut + its 3 helpers
(last_complete_downbeat_idx, first_downbeat_idx, micro_fade) exactly as in
/home/user/workspace/transition_assessment.md. It uses get_bed_info keys
y, sr, bed_grid, sec_per_bar, downbeat_s, duration_s — all confirmed to exist.
1.5ms micro-fade each side = click prevention only, ZERO overlap (this is the
crossfade fix). Sample-copy the helper bodies from transition_assessment.md.

## The visualization (MUST show the mechanism — audit requirement)
Multi-panel synced figure, project dark palette (BG #171614, FG #CDCCCA,
accent #4F98A3, teal #20808D, gold #FFC553, green #6DAA45, warn #BB653B,
resting-HR line #BCE2E7). Panels stacked, shared x = time/bars:
1. SIMULATED HR (bpm) trace — label the word "SIMULATED" INSIDE the panel; mark
   the perturbation spike. Show target/resting band shaded.
2. TEMPO (bpm) trace — stepped; mark each hard-cut transition with a vertical
   gold line + "→ NN BPM"; show committed-vs-took-effect if generate-ahead lag.
3. DENSITY trace — per-bar events/bar.
4. tier_that_acted STRIP — a colored row per bar (density / tempo / genre / none
   in 4 distinct colors with a legend). THIS is what makes the cascade visible;
   without it the video "just looks like music got calmer." Do not omit.
Add genre-change text labels where genre switches.

## MP4 render (reuse the ROBUST pattern proven in nb14 — NOT concat demuxer)
- Build the audio (concatenated beds w/ hard cuts + per-bar drums mixed in).
- Two options for video: (a) simplest robust = one static full multi-panel
  figure held for the whole clip, muxed with the audio (fixed canvas, no
  bbox_inches='tight'); (b) nicer = an animated playhead sweeping across the
  static panels. Do (a) first (guaranteed to work); attempt (b) only if cheap.
- ffmpeg: loop still -> segment with scale=trunc(iw/2)*2:trunc(ih/2)*2, -r 25,
  -pix_fmt yuv420p, -c:v libx264; then mux -c:a aac -shortest. Wrap ffmpeg calls
  in a _run() that PRINTS stderr on failure. NEVER feed raw mismatched images to
  the concat demuxer.
- CRITICAL: after writing MP4, run `ffmpeg -i out.mp4 -af volumedetect -f null -`
  and assert mean_volume != -inf; print the measured dB in a cell.

## In-notebook honesty cells (audit requirement — put these IN the notebook)
- Top markdown: what this proves (system behavior in real audio) and what it
  does NOT (no human data, no efficacy claim, HR is simulated, plant is a
  literature-grounded toy — reuse the exact disclaimer language from
  pd_controller.py). Cite iso-principle for plant SIGN only:
  Mayr/Starcke 2021 https://pubmed.ncbi.nlm.nih.gov/34886210/ ;
  Watanabe/Kashino/Ooishi 2017 https://pubmed.ncbi.nlm.nih.gov/28266647/ .
- If the Latin genre tier is touched, print the N=19 caveat. Safer: scope the
  hero clip to the robust R&B<->Pop range and only *mention* Latin as a
  personalizable default.
- Closing markdown: a per-claim EVIDENCE-TIER table (claim | evidence | tier:
  simulated / real-audio-demo / real-human-data[none yet]) so nothing is
  "evidence-laundered". And an explicit "future work" line: human pilot, plant
  fitting, live sensors.

## Build / validate constraints
- Build via /home/user/workspace/groovegen_project/build_notebook_15.py that
  emits groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb.
- nbformat.v4, nbformat_minor=5, unique cell ids (new_code_cell/new_markdown_cell
  auto-assign). nbformat.validate must pass. ast.parse every code cell (strip
  !/% magic lines first).
- Colab setup cell = the FULL install list now known-good from nb14:
  Cython; madmom (--no-build-isolation); transformers -U; pretty_midi librosa
  soundfile imageio imageio-ffmpeg pyloudnorm scikit-learn; pyfluidsynth;
  apt fluidsynth fluid-soundfont-gm. Then the nb13 zip-upload/sys.path pattern.
- DO NOT run MusicGen in sandbox. DRY-RUN in sandbox: the closed-loop control
  wiring (feed a scripted hr_curve through CascadeController, assert the trace
  has all tiers acting incl a 'tempo' and a 'none', and that perturbation causes
  a corrective action), AND the splice function on the two uploaded beds
  (assert non-silent + finite), AND the ffmpeg still->mux->volumedetect path
  (assert mean dB != -inf). Copy the SAME code that ships.
- Render-noise filter: 2>&1 | grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|librosa"

## Uploaded beds for the sandbox dry-run
- r&b:  uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
- salsa: uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav

## Notebook cell order
1 MD title + honesty/what-this-proves + iso-principle cite
2 code Colab setup (install list + zip/sys.path)
3 code imports + GPU check + load MusicGen
4 MD the scripted HR curve (3 phases) + hr->arousal mapping rationale
5 code build hr_curve + TARGET_AROUSAL arrays; plot the input curve
6 code run CascadeController loop over bars -> record trace; print tier counts
7 MD transition mechanism = hard cut (why, with the seam-metric result vs xfade)
8 code splice_beds_downbeat_hard_cut + 3 helpers (verbatim)
9 code generate beds per committed tempo (MusicGen) + per-bar drums; assemble
   full audio via hard cuts; save wav
10 code build the 4-panel synced figure (incl tier_that_acted strip)
11 code render MP4 (robust ffmpeg) + volumedetect assertion; display
12 MD evidence-tier table + limitations + future work (closing honesty cell)
