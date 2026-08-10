# GrooveGen — Experiment UI + 12-Song Pipeline (How to Run)

Two new pieces, both built and tested this session. All CPU-only, no MusicGen, no network.

## 1. Closed-loop experiment / simulation UI

Drive the real `CascadeController` from a heart-rate signal and watch GENRE→TEMPO→DENSITY respond bar by bar.

**Run locally:**
```bash
pip install gradio
cd groovegen_project
python app_experiment.py                 # http://127.0.0.1:7861
python app_experiment.py --host 0.0.0.0  # open from another device on the LAN
```
**Colab:** `!python app_experiment.py` (a public share link is created automatically).

**How to use:**
1. Set **subject calibration**: resting HR (→ arousal 0) and max/target-ceiling HR (→ arousal 1). This is per-participant.
2. Set the **Target HR** (where you want to steer the listener) and **Measured HR** (typed now; PPG later).
3. Click **Step one bar**. The controller runs one bar; the panels show genre / tempo / density and which tier acted. The trace + plot accumulate.
4. **Export trace CSV** to save the full bar-by-bar run for analysis.

Verified behavior: as measured HR descends toward target, tempo walks down and genre goes latin→pop→r&b (→calm at low enough setpoint), with tiers escalating density→tempo→genre exactly as designed.

### Swapping in the ESP32 + DigiRobot PPG later (NO UI changes)
The HR input is abstracted in `groovegen/hr_source.py`:
- **Now:** `TextInputHRSource` (manual).
- **Later:** `SerialHRSource(port="/dev/ttyUSB0", baudrate=115200)`.

ESP32 firmware contract — print one BPM float per line:
```cpp
Serial.println(bpm);   // e.g. 72.5\n
```
Then `pip install pyserial`, construct `SerialHRSource`, call `.start()`, and the UI reads it identically. A background thread + sanity gate (20–240 BPM) already handle noisy/blocking reads.

**Honest scope:** this is the control loop + a simulator. HR is an input the controller TRACKS; the UI does not model how music would actually move real HR (no efficacy claim).

## 2. 12-song personalization pipeline (steps 1–3, free/local)

Turns a user's 12 songs into a personalized arc + MusicGen prompts. Spec: `../twelve_song_personalization_pipeline.md`.

- `groovegen/profile_from_songs.py` — `extract_features(path)` (librosa, matches `track_features.csv` columns) + `build_profile({'danceable':[...6], 'enjoyed':[...2], 'relaxing':[...3-4]})` → 3 median centroids + confidence weights + input sanity checks (flags mislabeled songs, asserts danceable > relaxing tempo).
- `groovegen/arc_from_profile.py` — `arc_from_profile(profile)` → 4 personalized segments (tempo bands + anchor blends), genres from `GENRE_ENERGY_ORDER`.
- `groovegen/prompt_from_anchor.py` — `prompt_from_anchor(anchor, tempo)` → MusicGen text prompt, snapped to the 6 known style words.

**Test it (synthetic 12-song set, no real audio needed):**
```bash
cd /home/user/workspace
python test_pipeline.py
```
Confirmed: centroids (122.5 > 98 > 71 BPM), mislabel caught, monotonic arc, 4 sensible prompts.

### Step 4 — generate + quality-gate + cache (`generate_and_gate.py`) — BUILT

Generate each personalized prompt with MusicGen, MEASURE tempo stability, and regenerate/quantize/fall-back if it wanders — then cache. This is the step that stops a wobbly generated bed (the "pop drums sound off" problem) from ever reaching the live loop.

Cascade per segment: generate → gate (beat_jitter ≤ 12 ms AND grid_err ≤ 40 ms, the "latin-quality" bar) → retry up to K → beat-sync quantize → clean uploaded-bed fallback → cache.

**In Colab (after the MusicGen model is loaded):**
```python
from groovegen.generate_and_gate import make_musicgen_generator, generate_and_gate, summarize
from groovegen.arc_from_profile import arc_from_profile

segments = arc_from_profile(profile)          # each has genre, tempo_bpm, prompt
gen = make_musicgen_generator(model, proc, device)   # reuses nb15 gen_bed logic
results = generate_and_gate(
    segments, gen, OUT_DIR,
    fallback_beds={'pop': CLEAN_POP_WAV, 'latin': LATIN_WAV, 'r&b': RNB_WAV},
    max_tries=3, cache=True)
print(summarize(results))
```

**Dry-run locally (no GPU/network):** pass a fake generator — see `../test_generate_and_gate.py`. Verified: clean bed passes on try 1; wobbly bed exhausts retries + quantize then falls back to a clean uploaded bed; second run hits the cache with **0 MusicGen calls**. The summary reports honest MusicGen call counts (the credit meter) and writes `bed_manifest.json`.

### Step 5 — wire cached gated beds into nb15 — DONE

nb15's bed-generation loop now checks `outputs/audio/nb15/beds/` first (toggle `USE_CACHED_BEDS`, default on). If `generate_and_gate` already wrote a quality-gated bed for a segment (`segN_<genre>_<bpm>bpm.wav`, or any `segN_*.wav` for a fallback/quantized bed), nb15 REUSES it; otherwise it generates inline as before. Net effect: every bed reaching the live loop has passed the tempo-stability gate, and re-runs cost zero MusicGen.

End-to-end handoff verified locally (`../test_step5_handoff.py`): 4 personalized segments → gated beds written with nb15's exact naming → nb15's lookup finds all 4 (including the `&` in `r&b`). The deliberately-wobbly pop bed fell back to a clean uploaded bed, so nothing wobbly reaches the mix.

**Colab run order:** (1) build profile from 12 songs → (2) `arc_from_profile` → (3) `generate_and_gate(..., out_dir=OUT_DIR+'/beds', fallback_beds={...})` → (4) run nb15 with `USE_CACHED_BEDS=True`. Steps 1–3 are the only GPU/MusicGen part; nb15 then just mixes and splices the cached beds.

### Mix balance fix (melody up, drums down) — DONE

The old segment mix summed `0.8*bed + 0.9*drums`, which put drums ~1 dB LOUDER than the bed/melody (worst in dense latin). Now `1.0*bed + 0.62*drums` (drums ~4 dB under), with an extra ~1.5 dB trim on latin's busy kit. This is Daniel's requested "a little more melody, quieter latin drums" — free/local, applied in the builder.

**MusicGen note:** the MusicGen code is complete and wired (`make_musicgen_generator` + `generate_and_gate` + nb15). It only RUNS on Colab GPU — running the finished notebook there IS "the MusicGen section." It is not executed in this environment on purpose (no GPU + it's the credit-heavy part), which is exactly what the gate/cache exist to minimize.

**Feature coverage note:** implemented all features named in spec §§2-3/§5. Skipped (not required by the pipeline): `beat_this_*`, `downbeat_*`, `meter_estimate`, `lhl_syncopation_*`. Full accounting in `../profile_from_songs_report.md`.
