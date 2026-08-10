# SPEC — Colab A/B notebook: old hybrid drums vs new coherent drums, on ONE real MusicGen bed

## Why
User feedback: the SANDBOX pieces (Step 1b/1c, continuous.py) sound worse than the earlier HYBRID MusicGen version — BOTH the bed AND the drums were better in the hybrid version. Sandbox can't run MusicGen, so we must verify on Colab GPU. Critically, we must NOT assume the new "coherent" drums are better — the user may have preferred the OLD genre-idiomatic drums (more pocket/character). So the notebook must let the user A/B BOTH drum engines on the SAME real MusicGen bed and decide.

## Two drum engines to compare (same bed, same genre, same tempo)
- **Mode A (OLD, "hybrid"):** `from groovegen import hybrid_render as hr; hr.hybrid_render(bed_wav, drum_style, out_wav, expected_tempo=..., **knobs)`. This is the genre-idiomatic path (hybrid_render.py) that the user liked — it beat-warps drums onto the bed's detected grid via analyze_bed/madmom.
- **Mode B (NEW, "coherent piece"):** `from groovegen import continuous as ct; ct.render_piece(base_GrooveParams, bed_wav, out_stem, seconds=..., subtle=True)`. Constant hat spine + phrase-level density + tempo-lock + downbeat align (Step 1b/1c).

## Deliverable: a NEW Colab notebook groovegen_project/notebooks/11_ab_drum_engines.ipynb (nbformat v4)
Cells:
1. (markdown) Title + purpose: "Judge on a REAL MusicGen bed: old genre-idiomatic drums (A) vs new coherent drums (B). Pick which drum engine to keep."
2. (code) Install deps — mirror notebook 09 cell 2 exactly (apt fluidsynth, pip Cython then --no-build-isolation madmom, transformers, torch, etc.). Copy the working install block from 09-hybrid-musicgen-bed.ipynb.
3. (code) Upload + unzip groovegen_code_only.zip (mirror 09 cell 5); set root + sys.path; import gg, hybrid_render as hr, continuous as ct, genre_presets.
4. (markdown) Pick genre + tempo.
5. (code) Choose ONE genre (default 'r&b/soul') and a tempo; get preset via genre_presets.get_preset; set BED_PROMPT from preset['bed_prompt'].
6. (markdown) Generate the bed with MusicGen (GPU) — mirror 09 cell 11 (musicgen-small, ~12s, 32kHz→save 44.1k wav BED_WAV). Copy the working MusicGen generation block from notebook 09.
7. (code) MODE A: hr.hybrid_render(BED_WAV, drum_style=preset_drum_style, out_wav='mixA_hybrid.wav', expected_tempo=TEMPO, event_density=..., syncopation_level=..., swing_amount=..., microtiming_variance_ms=...) using the preset's knobs. display Audio.
8. (code) MODE B: build GrooveParams(tempo_bpm=TEMPO, drum_style=preset_drum_style, event_density=..., syncopation_level=..., swing_amount=..., seconds→bars) and ct.render_piece(base, BED_WAV, out_stem='mixB_coherent', seconds=SAME_AS_A, subtle=True). display Audio.
9. (markdown) "Listen to A vs B. A = old genre-idiomatic (more character?). B = new coherent (more stable?). Note which drums sit better on the bed."
10. (code) Build a 2-way A/B comparison VIDEO (reuse the pattern from notebook 09 cell 17 — dark cards, per-segment audio+silent tail, concat) labeling segment 1 "A — hybrid (old)" and segment 2 "B — coherent (new)", both on the SAME bed. Save ab_drum_engines.mp4. Also verify each mix audio non-silent via a quick numpy RMS check.
11. (code) files.download for mixA, mixB, and the video.
12. (markdown) Notes: musicgen-small on free T4; if B sounds blander we bring genre character back into render_piece; if B's alignment is better we port it into hybrid_render. This notebook is the decision point.

## Constraints
- Copy the ACTUAL working install + MusicGen + video-builder code from notebook 09 (read it) so nothing is invented — adapt cell 17's video builder to 2 segments.
- Keep TEMPO and knob settings IDENTICAL between A and B so only the drum engine differs.
- Do NOT run MusicGen in the sandbox (no GPU). Just BUILD the notebook (valid nbformat) and sanity-check it parses. You may dry-run the NON-MusicGen logic (imports, GrooveParams build, render_piece signature) against continuous.py to catch arg-name errors, using one of the uploaded beds as a stand-in bed so cell 7/8 logic is verified to not crash (call hr.hybrid_render and ct.render_piece on the uploaded r&b bed in a scratch script — NOT inside the notebook — to confirm both signatures work; report the mean_volume of both).
- Uploaded r&b bed for the dry-run: /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav

## Report back
- Confirm notebook 11 written + valid nbformat, cell count.
- Dry-run results: did hr.hybrid_render and ct.render_piece both run on the stand-in bed without signature errors? volumedetect/RMS of each. Any arg mismatches you had to resolve.
- The exact knob values you wired for the fair A/B.

## Output
Notebook → /home/user/workspace/groovegen_project/notebooks/11_ab_drum_engines.ipynb
Dry-run scratch outputs → /home/user/workspace/step_ab_outputs/
