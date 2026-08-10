# GrooveGen — Colab Runbook

End-to-end: run the experiment UI, generate personalized music beds from your 12 songs, and run the closed-loop control. Copy each block into a Colab cell in order. GPU runtime required (Runtime → Change runtime type → GPU).

Two things run in different places, on purpose:
- **The UI + the control system** are CPU-only and light — they run anywhere (Colab CPU, or your laptop).
- **MusicGen bed generation** needs the GPU — that's the only heavy part, and the gate/cache exist to keep it cheap (re-runs cost zero).

You do **Part B (generate beds) once**, then **Part C (control loop)** reuses the cached beds forever.

---

## Part 0 — Setup (run once per Colab session)

### Cell 0.1 — get the code into Colab
Upload `groovegen_code_only.zip` (the file I shared) using the Colab file panel, then:
```python
!unzip -oq groovegen_code_only.zip
%cd groovegen_project
import sys, os
sys.path.insert(0, os.getcwd())
print("cwd:", os.getcwd())
print("has groovegen pkg:", os.path.isdir("groovegen"))
```

### Cell 0.2 — install dependencies
```python
# audio + ML stack. transformers is PINNED to 4.44.2 on purpose — newer
# versions throw a CUDA device-side assert inside MusicGen's positional
# embedding. Do NOT -U this.
!pip install -q hf_transfer
!pip install -q Cython
!pip install -q --no-build-isolation madmom
!pip install -q transformers==4.44.2
!pip install -q pretty_midi librosa soundfile imageio imageio-ffmpeg pyloudnorm scikit-learn
!pip install -q pyfluidsynth gradio
!apt-get -qq install -y fluidsynth > /dev/null
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "1"
print("deps installed")
```
Restart the runtime if Colab asks after installing (Runtime → Restart), then re-run Cell 0.1 only.

---

## Part A — Run the Experiment UI (manual HR now, ESP32/PPG later)

This is the interface where you type the target HR (setpoint) and the measured HR, step the loop one bar at a time, and watch the genre/tempo/density tiers respond. It does **not** need MusicGen — it exercises the control system with the drum engine.

### Cell A.1 — launch the UI
```python
# Colab has no local display, so share=True is auto-enabled → you get a public
# gradio.live link. Click it to open the UI in a new tab.
!python app_experiment.py --port 7861
```
What you'll see and do in the UI:
1. **Subject calibration** — enter resting HR and max HR (used to map BPM → arousal 0..1).
2. **Target HR** (the setpoint you want to steer toward) and **Measured HR** (what you'd read from the sensor).
3. **Step one bar** — the cascade controller acts: it prints genre / tempo / density and which tier acted, appends to a live trace table, and updates the dark plot.
4. **Export CSV** — saves the full trace for analysis.

To stop the UI, interrupt the cell (■). Later, swap `TextInputHRSource` for `SerialHRSource(port=...)` to read the ESP32 + DigiRobot PPG — the UI code already has that class; firmware just prints one BPM float per line.

> Note: while the UI cell is running it blocks the notebook. Run Parts B and C in a **separate** Colab notebook, or stop the UI first. They share the same `groovegen_project` folder, so cached beds are visible to both.

---

## Part B — Generate personalized beds from your 12 songs (GPU, once)

This is "the MusicGen section." You give it your 12 songs bucketed into danceable / enjoyed / relaxing; it builds your musical profile, derives a 4-segment arc, writes a MusicGen prompt per segment, generates each bed, **gates it on tempo stability**, and caches the good ones. Wobbly beds get retried/quantized or replaced with a clean fallback — so nothing wobbly (the old pop-drum problem) ever reaches the loop.

### Cell B.1 — point at your 12 songs
Upload your audio files to Colab (any format librosa reads: wav/mp3/m4a/flac), then fill in the paths:
```python
song_paths = {
    "danceable": [   # 6 high-arousal / danceable tracks
        "songs/dance1.mp3", "songs/dance2.mp3", "songs/dance3.mp3",
        "songs/dance4.mp3", "songs/dance5.mp3", "songs/dance6.mp3",
    ],
    "enjoyed": [     # 2 you love but aren't necessarily danceable
        "songs/enjoy1.mp3", "songs/enjoy2.mp3",
    ],
    "relaxing": [    # 2 (ideally 3–4) you find relaxing
        "songs/relax1.mp3", "songs/relax2.mp3",
    ],
}
for bucket, paths in song_paths.items():
    for p in paths:
        assert os.path.exists(p), f"missing: {p}"
print("all song files found")
```

### Cell B.2 — build your profile + the personalized arc
```python
from groovegen.profile_from_songs import build_profile
from groovegen.arc_from_profile import arc_from_profile
from groovegen.prompt_from_anchor import prompt_from_anchor

profile = build_profile(song_paths)     # 3 anchor centroids + confidence + sanity checks
arc = arc_from_profile(profile)         # 4 segments: danceable -> ... -> calm

# arc gives genre + tempo per segment; build the MusicGen prompt from each
# segment's blended anchor. generate_and_gate needs keys: genre, tempo_bpm, prompt.
segments = []
for seg in arc:
    prompt = prompt_from_anchor(seg["blended_anchor"], seg["tempo_bpm"])
    segments.append({"genre": seg["genre"], "tempo_bpm": seg["tempo_bpm"], "prompt": prompt})

for s in segments:
    print(f"  {s['genre']:6s} {s['tempo_bpm']:.0f} bpm  |  {s['prompt']}")
```
Sanity check the printout: tempos should descend (danceable → calm), and prompts should read like real style descriptions. `build_profile` will raise if a bucket looks mislabeled (e.g. "danceable" slower than "relaxing").

### Cell B.3 — load MusicGen and generate + gate + cache the beds
```python
import torch
from transformers import MusicgenForConditionalGeneration, AutoProcessor
from groovegen.generate_and_gate import make_musicgen_generator, generate_and_gate, summarize, QualityGate

device = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_ID = "facebook/musicgen-small"
proc  = AutoProcessor.from_pretrained(MODEL_ID)
model = MusicgenForConditionalGeneration.from_pretrained(MODEL_ID, use_safetensors=True).to(device)
print("MusicGen loaded on", device)

gen = make_musicgen_generator(model, proc, device)   # reuses the exact nb15 gen logic

BED_CACHE_DIR = "outputs/audio/nb15/beds"            # nb15 reads beds from here
os.makedirs(BED_CACHE_DIR, exist_ok=True)

# Optional but recommended: clean uploaded beds as fallbacks per genre band.
# If a generated bed can't pass the tempo-stability gate after retries+quantize,
# the loop uses the clean bed instead. Point these at your best clean WAVs.
fallback_beds = {
    # "pop":   "songs/clean_pop_bed.wav",
    # "latin": "songs/clean_latin_bed.wav",
    # "r&b":   "songs/clean_rnb_bed.wav",
}

results = generate_and_gate(
    segments, gen, BED_CACHE_DIR,
    gate=QualityGate(max_beat_jitter_ms=12.0, max_grid_err_ms=40.0),  # the latin-quality bar
    max_tries=3, fallback_beds=fallback_beds, cache=True,
)
print(summarize(results))
```
Read the summary: each segment shows source (`generated` / `quantized` / `uploaded_fallback` / `cached`), jitter, grid error, pass/fail, and the honest MusicGen call count. Any `failed_gate > 0` means that segment had no clean fallback — add one to `fallback_beds` and re-run (only the failing segment regenerates; the rest are cached).

> **Fallbacks matter for pop.** There is no clean uploaded pop bed yet. If your generated pop bed wobbles and no `pop` fallback is set, it will pass through as the best-effort generated bed. Provide a clean pop WAV to guarantee quality.

---

## Part C — Run the closed-loop control with your beds (nb15)

Now run the notebook that ties it together: it takes an HR setpoint curve, runs the cascade controller (genre → tempo → density), pulls the **cached gated beds** from Part B, renders per-bar drums, mixes (melody on top, drums under), and splices with downbeat-aligned hard cuts.

### Cell C.1 — open and run nb15
Open `notebooks/15_closed_loop_hr_audio.ipynb` in Colab (File → Open notebook → Upload, or from the file panel). It's already set to reuse your beds:
```python
USE_CACHED_BEDS = True          # already the default in the notebook
BED_CACHE_DIR = "outputs/audio/nb15/beds"
```
Run all cells. In the bed-generation loop you'll see, for each segment:
```
[k/4] genre=<label>  CACHED gated bed -> segK_<genre>_<bpm>bpm.wav
```
That confirms it's reusing your Part B beds (zero new MusicGen calls). If a segment isn't cached, it falls back to generating inline.

### Cell C.2 — what nb15 produces
- A committed genre/tempo/density **trace** driven by the scripted HR setpoint (HR is a setpoint the controller *tracks* — not a claim that music changes HR).
- The final **rendered audio** with the new mix balance (melody up, latin drums trimmed ~1.5 dB).
- Downbeat-aligned hard cuts between segments (no crossfade).

To hear it reliably (Colab inline WAV can be flaky), export an MP4 at the end — the notebook's video/mux cells do this. Always verify audio is present:
```python
!ffmpeg -i outputs/.../final.mp4 -af volumedetect -f null - 2>&1 | grep mean_volume
# mean_volume must NOT be -inf
```

---

## Where the sensor plugs in (later)

Everything above uses manual HR. To close the loop with hardware:
1. Flash the ESP32 + DigiRobot PPG to print one BPM float per line: `Serial.println(bpm);`
2. In the UI, swap `TextInputHRSource` → `SerialHRSource(port="/dev/ttyUSB0", baudrate=115200)` (class already in `groovegen/hr_source.py`; 20–240 BPM gate, background thread).
3. The controller and bed pipeline don't change — only the HR *source* changes.

---

## Quick mental model
- **Profile → arc → prompts → generate_and_gate** = personalize + guarantee quality (Part B, GPU, once).
- **nb15** = the closed loop that consumes those beds (Part C, reuses cache).
- **app_experiment.py** = the interactive front end for driving/observing the controller (Part A).
- HR is a **scripted setpoint the controller tracks** — this is a system/method contribution, not an efficacy claim.
