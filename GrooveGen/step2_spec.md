# STEP 2 BUILD SPEC — Genre UI (Gradio) wrapping the continuous engine

## Goal
Evolve the existing Gradio app so a user picks their favorite genres (checkboxes for known presets + free-text for anything else), hits Generate, and gets a CONTINUOUS, non-repetitive stream (from the Step 1 engine) plus a live EVENT-DENSITY curve plot. Runs in Colab (GPU/MusicGen) AND degrades gracefully in the CPU sandbox (synthetic/uploaded beds, no MusicGen).

## Locked decisions (from user)
1. INPUT = BOTH: checkbox group of known presets + a free-text box for arbitrary genres.
2. OUTPUT = continuous stream (wrap Step 1 `render_continuous`) + the per-bar density curve image.

## Existing code to reuse (DO NOT rewrite the engine or presets)
- `groovegen_project/app.py` (334 lines) — existing single-genre Gradio app. Build the NEW app as `groovegen_project/app_genre.py` (keep app.py intact) OR add a new tab; simplest: NEW file `app_genre.py`.
- `groovegen/continuous.py` — Step 1 engine: `render_continuous(base:GrooveParams, bed_wavs:list[str], out_stem, n_bars, band, step_sd, seed, drum_gain_db, bed_gain_db)`, `density_walk()`, `build_varied_drums()`, `crossfade_beds()`. USE THIS for output.
- `groovegen/genre_presets.py` — `GENRE_PRESETS` dict (keys: hip-hop/rap, r&b/soul, pop, latin/salsa, classic-rock, metal), `get_preset(genre, ...)` returns dict(bed_prompt, tempo_hint, drum_style, knobs{event_density,syncopation_level,swing_amount,microtiming_variance_ms}, seed_genre, ...), `list_genres()`.
- `groovegen/groovegen.py` — `GrooveParams`, `render_wav`.

## Free-text → preset mapping
Add a helper `map_free_text_genre(text:str) -> str` in a small new module `groovegen/genre_router.py`:
- Normalize (lowercase, strip). 
- Keyword/substring match against known preset keys and common aliases (e.g. "rap"/"trap"/"boom bap"→hip-hop/rap; "soul"/"neo-soul"/"funk"→r&b/soul; "edm"/"house"/"dance"/"electro"→pop; "salsa"/"latin"/"reggaeton"/"cumbia"→latin/salsa; "rock"/"punk"/"indie"→classic-rock; "metal"/"thrash"/"djent"→metal; "lofi"/"lo-fi"/"chill"/"ambient"→calm; "jazz"→r&b/soul; "afrobeat"→pop).
- Fallback: fuzzy nearest by difflib.get_close_matches against known keys+aliases; if nothing, default to "pop" and flag it as approximate.
- Return the matched preset key AND a bool `approx`. Provide `route_genres(selected:list[str], free_text:str) -> list[tuple[label, preset_key, approx]]` combining both inputs, dedup by preset_key.

## The Generate callback
`generate(selected_genres, free_text, seconds, seed, bed_source)`:
1. route genres → list of (label, preset_key, approx). If empty → return a friendly message.
2. For the FIRST resolved genre (MVP: one continuous stream at a time — the stream IS the deliverable; multiple selected genres become the bed bank / future queue):
   - `p = get_preset(preset_key)`; build `GrooveParams` from p['knobs'] + p['tempo_hint'].
   - Bed bank: 
     * COLAB path (GPU/MusicGen available): generate 1-2 MusicGen beds from p['bed_prompt'] (leave a clearly-marked hook `generate_musicgen_beds(prompt, tempo, n)` that returns wav paths; in sandbox this raises/So we fall back).
     * SANDBOX/CPU fallback: use uploaded beds as the bank:
       - salsa: /home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
       - r&b:   /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
       Choose bed(s) loosely by genre (latin→salsa bed, else r&b bed; both if multiple genres).
   - Compute n_bars from seconds & tempo. band = (max(4, base_density-3), base_density+3). step_sd=1.2.
   - Call `render_continuous(...)` → wav. 
3. Build the density-curve PNG (reuse Step 1 style: step plot of per-bar densities, dark theme accent #4F98A3, title "Per-bar event density (primary knob) — backbeat locked"). render_continuous already returns the densities list.
4. Return: (audio_filepath, density_png_path, status_markdown). Status shows resolved genres, tempo, base density, and notes any approx free-text mappings + whether MusicGen or fallback beds were used.

## UI layout (gr.Blocks, theme Soft, title "GrooveGen — Genre Stream")
- Header markdown explaining: pick genres → continuous non-repetitive stream driven by event density.
- Left column: 
  * `gr.CheckboxGroup(list of known preset keys, label="Known genres")`
  * `gr.Textbox(label="Other genres (comma-separated)", placeholder="e.g. lo-fi, afrobeat, jazz")`
  * Accordion Advanced: seconds slider (10-60, default 30), seed number (default 0), bed_source radio ["auto","musicgen","uploaded"].
  * Generate button (primary).
- Right column:
  * `gr.Audio(type="filepath", label="Continuous stream")`
  * `gr.Image(label="Event-density curve (the control axis)")`
  * `gr.Markdown` status.
- Small "About the density curve" markdown: explain X=bar, Y=onsets/bar, stair-step because density is set per bar, green playhead in the video export; this curve is what the future PD/biofeedback controller will drive.

## DELIVERABLE
- `groovegen_project/app_genre.py` (the Gradio app; `demo = build_ui()`, `if __name__=='__main__': demo.launch()`).
- `groovegen/genre_router.py` (map_free_text_genre, route_genres).
- A Colab notebook `notebooks/10_genre_ui.ipynb` (nbformat) with: setup cell (pip install gradio if needed), a cell that imports and launches the app with `share=True`, and a markdown intro. Keep it minimal.

## SANDBOX TEST (must pass before reporting done)
Run a headless test WITHOUT launching the server:
- import app_genre; call `generate(['latin/salsa'], 'lo-fi, jazz', 30, 0, 'auto')` and confirm it returns a real wav path (non-silent via ffmpeg volumedetect mean != -inf), a real png path, and a status string. 
- confirm free-text 'lo-fi'→calm and 'jazz'→r&b/soul mapping works (print route_genres output).
- Do NOT actually launch gradio in the sandbox (no browser); just verify the callback + imports work. Print the status string.

## Critical / be honest
- If gradio isn't installed in the sandbox, `pip install gradio` quietly (or note it and still test the callback by importing the render logic directly).
- Report: files written, route_genres output for the test, the generate() status string, volumedetect mean_volume of the produced wav, and any tradeoffs (esp. the "one stream at a time" MVP choice and how multiple genres are handled).
- Filter render noise: grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|_a in|librosa|gradio"

## Output locations
Code → groovegen_project/app_genre.py, groovegen_project/groovegen/genre_router.py, groovegen_project/notebooks/10_genre_ui.ipynb
Test outputs → /home/user/workspace/step2_outputs/
