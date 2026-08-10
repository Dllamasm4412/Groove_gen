# nb15 REDESIGN SPEC — Latin down-regulation scenario, deliberate tempo jumps

## WHY (user feedback on the previous nb15 run)
The previous run had TWO real flaws the user heard/saw:
1. **Over-actuation:** 7 hard cuts crammed into a tiny window (116→115→113→112→111→110→109 BPM), each only 1–3 BPM apart. A new bed regeneration + hard-cut splice fired every ~1–2 bars for a sub-perceptual tempo change. Sounds like a stutter, not a groove. Then long dead plateaus.
2. **Density too busy:** started at 14 events/bar — competes with the MusicGen bed's own percussion.

The user proposed (and we AGREED) a better scenario. Their exact answers to the design questions:
- Tempo steps: **BIG JUMPS (~15 BPM, 3–4 total)**. e.g. 125→~110→~95→~80.
- Respiration: **SHOWN, NOT DRIVING** — display as a realism panel; controller follows the arousal/HR setpoint only.
- Density: **CALM — cap ~8, floor ~3**.

## THE NEW SCENARIO (narrative arc)
Start state: **high arousal — HR ~125 bpm + high respiration, Latin music playing.**
Down-regulation: scripted HR setpoint descends 125 → low. Controller TRACKS the descending setpoint.
Genre arc as arousal falls: **Latin → Pop → R&B → calm** (walking DOWN the energy axis).
Tempo: a few DELIBERATE big jumps, not many micro-steps.
Each committed segment is **~15 s** (coherent musical unit, under MusicGen token ceiling).

## CRITICAL HONESTY GUARDRAILS (non-negotiable — TEI system-paper framing)
- We have NO physiological model and NO human trials. We CANNOT claim the music lowers HR.
- In the SIMULATION, HR is a SCRIPTED descending setpoint that WE impose. The controller's only job is to TRACK it.
- Every claim must say "tracks a simulated descending setpoint," NEVER "reduces/lowers HR" or "regulates emotion."
- Respiration is SHOWN for scenario realism only; it does NOT drive the controller. Say so explicitly in a panel label AND a disclaimer cell.
- Keep the top disclaimer cell + iso-principle cites (PubMed 34886210 Mayr/Starcke 2021; 28266647 Watanabe/Kashino/Ooishi 2017 — for plant SIGN only) + closing per-claim EVIDENCE-TIER table (claim | evidence | tier ∈ {simulated / real-audio-demo / none-yet}) + limitations + future work. Keep the Latin N=19 caveat.

## THE KEY CONTROL FIX: commit deadband + bigger steps
Root cause: the notebook regenerated a bed for EVERY distinct committed tempo value, and the tempo tier committed sub-perceptual changes.
Fix lives in the NOTEBOOK segment-building loop (NOT controller internals — keep CascadeController reusable):
1. **Bigger steps:** construct the CascadeController's TempoController with `max_step_bpm≈15` (pass via whatever kwarg path CascadeController exposes; inspect its __init__. If it doesn't expose it, set it on the controller's `.tempo_ctrl.max_step_bpm` after construction — that attribute exists, confirmed).
2. **Commit deadband:** maintain `last_committed_tempo`. Walk the per-bar CascadeController.step() trace, but only START A NEW BED SEGMENT when the newly committed tempo differs from `last_committed_tempo` by **≥ COMMIT_DEADBAND_BPM (=12)** OR the genre changed. Otherwise the current segment simply extends (more bars, same bed). This collapses the 7 micro-cuts into 3–4 deliberate ~15 BPM jumps.
3. Result target: roughly Latin@~125 → Pop@~108 → R&B@~92 → calm@~78, i.e. 3–4 committed segments, each ~15 s, each a clearly audible transition.

## DENSITY FIX
- Cap density at **8** (was 14), floor **3**. If PDDensityController exposes clamp/min/max, set them; else clamp the returned density in the notebook loop: `density = int(np.clip(density, 3, 8))`.
- Optional but nice: thin the drum overlay slightly relative to the bed so the symbolic drums COMPLEMENT the MusicGen percussion rather than double it. If render_aligned_drums takes event_density, pass the clamped value.

## SCRIPTED HR / SETPOINT / RESPIRATION
- Build a SCRIPTED HR curve: starts ~125 bpm, descends smoothly to ~72 bpm over the timeline. Add a short plateau near the end (controller idle → tier_that_acted='none') so the "doesn't fidget" behavior is visible. OPTIONAL small perturbation bump is fine but the user's stated scenario is a clean descent — keep it mostly a descent; a small mid perturbation is allowed if it doesn't add many cuts.
- Convert HR to arousal setpoint in [0,1] with an explicit, documented mapping (e.g. linear map resting..max HR → 0..1). Keep the SAME mapping used previously if one exists in nb15; else define clearly and cite iso-principle for SIGN only.
- Respiration: synthesize a "high then easing" respiration-rate trace for the SAME timeline (e.g. ~22 → ~12 breaths/min). It is DISPLAYED ONLY.

## VISUALIZATION (4 synced panels, stacked, shared x-axis = time)
1. **SIMULATED HR** (bpm) — label "SIMULATED" inside the panel; plot resting-HR reference line.
2. **Respiration** (breaths/min) — panel title must say "shown, not driving the controller".
3. **Tempo** (bpm) — STEPPED line; vertical dotted markers at each HARD CUT; annotate each committed tempo. Should now show only 3–4 steps.
4. **Density** (events/bar) — stepped; plus the MANDATORY **tier_that_acted color strip** (density/tempo/genre/none) as a thin horizontal band so the cascade is VISIBLE. Without it "just looks like music got calmer."
- Dark theme: BG #171614, FG #CDCCCA, muted #797876, accent #4F98A3, teal #20808D, green #6DAA45, warn #BB653B, gold #FFC553, resting-HR line #BCE2E7. DejaVu Sans, 150 dpi.

## OUTPUT: ONE MP4 you SEE + HEAR
- Render the full stitched audio (Latin→Pop→R&B→calm with hard cuts + per-bar density) as WAV, then MP4 with the 4-panel figure as the video track and the audio muxed in.
- MUST verify non-silent: `ffmpeg -i out.mp4 -af volumedetect -f null -` → mean_volume must NOT be -inf.
- Use the ROBUST ffmpeg pattern already in nb15 (fixed-size frames, scale=trunc(iw/2)*2:trunc(ih/2)*2, -r 25 -pix_fmt yuv420p -c:v libx264, -c:a aac, _run() wrapper printing stderr on failure). Do NOT reintroduce concat-demuxer on mismatched PNGs.

## KEEP ALL PRIOR FIXES (already in nb15 — do NOT regress)
- `!pip install -q transformers==4.44.2` (NOT -U). CUDA_LAUNCH_BLOCKING=1 in imports cell.
- Download resilience in setup cell: hf_transfer + HF_HUB_ENABLE_HF_TRANSFER=1 + HF_HUB_DOWNLOAD_TIMEOUT=60.
- Model load: `from_pretrained(MODEL_ID, use_safetensors=True)` (skips the pytorch_model.bin that stalls the download).
- Token cap + loop-to-length: GEN_SECONDS=12, MAX_NEW_TOKENS_CAP=1400; gen_bed generates SHORT bed then loops to fill segment length; _loop_to_length trims to whole bars + 1.5ms micro-fade. gen_bed signature includes tempo_bpm.
- splice_beds_downbeat_hard_cut (hard cut, zero overlap, 1.5ms micro-fades). NO crossfade.
- CascadeController REUSED from groovegen.pd_controller — never reimplement the class.

## BUILDER + VALIDATION
- Edit the existing builder `/home/user/workspace/groovegen_project/build_notebook_15.py` (don't start from scratch — most cells are correct; change: HR/respiration scripting cell, setpoint mapping, segment-build loop for deadband+bigger steps+density clamp, viz cell to add respiration panel + keep tier strip, honesty cells to add respiration-not-driving disclaimer).
- INNER docstrings inside the r"""...""" cell wrappers MUST use ''' not """ (triple-double-quote inside a triple-double-quote string breaks the builder — this bug bit twice already).
- Re-emit notebook to `/home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb`.
- VALIDATE: `nbformat.validate`; `ast.parse` every code cell AFTER stripping lines matching `^\s*[!%]` (shell magics aren't valid Python).
- DRY-RUN the control loop standalone (extract the setpoint curve + CascadeController wiring from the notebook's own cells and run): assert the committed-segment count is **3–5** (NOT ~11), assert tier_that_acted contains 'tempo' and 'none', assert density stays within [3,8].
- DRY-RUN the splice on the r&b + salsa beds: assert finite, non-silent (max_amp>0).
- DRY-RUN ffmpeg on a tiny synthetic case to prove volumedetect mean_volume != -inf (reuse the proven pattern).
- Write findings to `/home/user/workspace/nb15_redesign_findings.md`: committed-segment count + the actual tempo/genre arc the dry-run produced, density range, tier counts, and confirmation all prior fixes are intact.

## BEDS AVAILABLE (uploaded)
- r&b bed: /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
- salsa/latin bed: /home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
(These are the beds nb15 already references. For pop/calm segments the notebook GENERATES beds via MusicGen at the committed tempo/genre — that path already exists.)

## FILES
- Builder: /home/user/workspace/groovegen_project/build_notebook_15.py
- Notebook out: /home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb
- Controller (reuse, inspect for max_step_bpm/density clamp kwargs): /home/user/workspace/groovegen_project/groovegen/pd_controller.py
- hybrid_render: /home/user/workspace/groovegen_project/groovegen/hybrid_render.py
- Findings out: /home/user/workspace/nb15_redesign_findings.md
