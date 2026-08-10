# How to Run GrooveGen

Two supported paths. **Google Colab is the easy path** (zero local install, free T4 GPU for the
deep-learning bed). **Local** is for when you want everything on your own machine.

The package you were shared is `groovegen_project_v1.zip` (~64 MB). It contains the code, the
notebooks, the data CSVs, and the soundfont folder.

---

## What needs a GPU vs. what doesn't

| Notebook | What it does | Runtime |
|----------|--------------|---------|
| `04_genre_analysis.ipynb` | Ranks genres in Sophia's data, locks the study menu | CPU |
| `05_dl_bed_generation.ipynb` | Builds the per-genre style seed → Anticipatory Music Transformer embellishes it → freezes a MIDI bed | **GPU (T4)** |
| `06_drum_overlay_demo.ipynb` | Overlays the knob-controlled drums on a frozen bed | CPU |
| `07_song_generator.ipynb` | **Main demo.** Top-3 genres → 3 full songs (Intro→Verse→Chorus→Chorus) | **GPU (T4)** |

GPU is only needed for the AMT model step (notebooks 05 and 07). Everything else — including all the
audio rendering — runs fine on CPU. If you run 05/07 without a GPU they fall back to the style seed
directly (still produces audio, just without the transformer's embellishment).

---

# Path A — Google Colab (recommended)

The notebooks already carry a **self-contained bootstrap cell** that installs everything, unzips the
project, and mounts your Drive. You don't have to set anything up manually.

### Step 1 — Open Colab and set the runtime
1. Go to <https://colab.research.google.com>.
2. **File → Upload notebook**, and upload `07_song_generator.ipynb` (or `04`/`05`/`06`).
   - The notebooks live inside the zip under `groovegen_project/notebooks/`. You can also just open
     the zip on your computer and grab the one `.ipynb` you want.
3. For `05` or `07`: **Runtime → Change runtime type → T4 GPU → Save.** (Skip for `04`/`06` — CPU is fine.)

### Step 2 — Run the first (setup) cell
Run the top cell. It will:
- `pip install` all Python deps + `transformers`, `torch`, and the `anticipation` library,
- `apt-get install` FluidSynth + a GM soundfont,
- prompt you to **upload `groovegen_project_v1.zip`** (only the first time in a session),
- unzip it fresh to `/content/groovegen_project` so you never run stale code,
- mount your Google Drive.

When it asks, upload the `groovegen_project_v1.zip` file you were shared.

### Step 3 — Run the rest top-to-bottom
Use **Runtime → Run all**, or run each cell in order. In `07` you'll set your three genres near the top:

```python
MY_TOP3 = ["pop", "classic-rock", "hip-hop/rap"]   # pick any 3 from the menu
```

Valid genre names: `"hip-hop/rap"`, `"r&b/soul"`, `"pop"`, `"latin/salsa"`, `"classic-rock"`, `"metal"`.

### Step 4 — Get your output
Songs are written as **WAV** to your Drive at:

```
MyDrive/GrooveGen/songs/
```

They also embed inline in the notebook so you can play them right there. If Drive isn't mounted they
fall back to the local (ephemeral) `outputs/` folder, so mounting Drive is worth it.

> **Tip:** the setup cell always re-unzips the latest zip, so whenever I send you an updated
> `groovegen_project_v1.zip`, just upload the new one and re-run — no stale code.

---

# Path B — Local (your own machine)

Works on macOS and Linux. On Windows, use WSL2 (FluidSynth + soundfont setup is much smoother there).

### Step 1 — Unzip the project
```bash
unzip groovegen_project_v1.zip
cd groovegen_project
```

### Step 2 — Install the FluidSynth system library + a GM soundfont
The Python audio rendering calls the **FluidSynth** C library (not just the `pyfluidsynth` wheel), and
it needs a General-MIDI soundfont.

**macOS (Homebrew):**
```bash
brew install fluid-synth
```
Then get a good soundfont. The thin default (`TimGM6mb.sf2`) sounds "8-bit"; use the full
**FluidR3_GM** (~148 MB) for realistic instruments. Download it and drop it here:
```
groovegen_project/soundfonts/FluidR3_GM.sf2
```
(The code automatically prefers a soundfont in `soundfonts/` over anything else.)

**Linux (Debian/Ubuntu):**
```bash
sudo apt-get install -y fluidsynth fluid-soundfont-gm
```
That installs FluidSynth and puts a GM soundfont at `/usr/share/sounds/sf2/`, which the code finds
automatically. For best quality, also grab FluidR3_GM and drop it in `soundfonts/` as above.

### Step 3 — Python environment + dependencies
Use a virtual environment (Python 3.10–3.12 recommended):
```bash
python3 -m venv .venv
source .venv/bin/activate           # Windows WSL: same; native Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

`requirements.txt` covers the core engine + notebooks. For the **deep-learning bed** (notebooks 05/07)
also install:
```bash
pip install transformers torch
pip install "git+https://github.com/jthickstun/anticipation.git"
```
On a machine without a GPU, `torch` runs on CPU and the AMT step falls back to the style seed — slower
but it works.

### Step 4a — Run via Jupyter (same notebooks as Colab)
```bash
pip install jupyter        # already in requirements.txt
jupyter notebook
```
Open `notebooks/07_song_generator.ipynb`. The setup cell detects it's **not** in Colab and skips the
install/unzip/Drive steps — it just assumes you're already inside the project folder with deps
installed (which you are). Run the cells top-to-bottom. Output WAVs land in the local `outputs/`
folder.

### Step 4b — Run as plain scripts (no notebook)
You can drive the engine directly from Python. The snippets below are **tested end-to-end on CPU** —
run them from inside `groovegen_project/`.

**Build one full song for a genre** (style seed → arrange into Intro→Verse→Chorus→Chorus → drums → WAV).
This is the CPU path; it skips the AMT transformer and uses the genre style seed directly:
```bash
PYTHONPATH=. python - <<'PY'
import os
import groovegen as gg
from groovegen import dlbed, genre_styles as gs

os.makedirs("outputs", exist_ok=True)
genre, tempo = "pop", 120          # any of the 6 genres

# 1) Build a genre style seed MIDI (no GPU needed)
seed = gs.build_style_seed(genre, bars=2)
src_mid = "outputs/src_pop.mid"
seed.write(src_mid)

# 2) Arrange into a full song + register it as a bed profile
prof = dlbed.register_genre_song(src_mid, genre, tempo, name="song_pop")

# 3) Render full track with knob-controlled drums on top
params = gg.GrooveParams(tempo_bpm=float(tempo), bed_profile=prof, with_bed=True,
                         target_seconds=16, event_density=8, syncopation_level=2, seed=7)
pm = gg.PatternBuilder(params).build_looped()
gg.render_wav(pm, "outputs/song_pop.wav", sf2_path=gg.default_sf2())
print("done -> outputs/song_pop.wav")
PY
```

> Genre names: `"hip-hop/rap"`, `"r&b/soul"`, `"pop"`, `"latin/salsa"`, `"classic-rock"`, `"metal"`.
> To use the **AMT transformer** (notebooks 05/07) instead of the bare seed, run those notebooks on a
> GPU — the model embellishes the seed before step 2.

**Lower-level groove engine** (drums + a built-in study bed, no full-song arrangement). `bed_profile`
must be one of `hero`, `hero_study`, `dorian_vamp`, `pop_loop`, `anthemic_lift`; `event_density` is an
integer (onsets/bar, default 8); `syncopation_level` is the groove knob:
```bash
PYTHONPATH=. python - <<'PY'
import os
import groovegen as gg
os.makedirs("outputs", exist_ok=True)
params = gg.GrooveParams(
    tempo_bpm=120.0,
    bed_profile="pop_loop",
    with_bed=True,
    target_seconds=16,
    event_density=8,
    syncopation_level=2,
)
gg.generate(params, "outputs/demo", sf2_path=gg.default_sf2())
print("done -> outputs/demo.wav")
PY
```

---

# The web UI (`app.py`)

There's a browser UI (built with Gradio) so you don't have to touch code: pick a genre, set the
tempo + **groove knob**, hit **Generate**, and play the result inline. Same app runs on your laptop,
Colab, and a Raspberry Pi.

### On your computer
```bash
cd groovegen_project
pip install gradio          # already in requirements.txt
python app.py               # opens http://127.0.0.1:7860
```
Then open the printed URL in your browser. Controls: genre, tempo, groove knob (syncopation),
event density, and under **Advanced** — seed bars, length, random seed, and the AMT toggle.

### On Google Colab
Open `notebooks/08_ui.ipynb`, run the setup cell (upload the zip when asked), then run the launch
cell. It prints a public **`https://....gradio.live`** link you can open in any browser, including
your phone. Use a **T4 GPU** runtime only if you want the AMT transformer; engine-only works on CPU.

### On a Raspberry Pi (serve to your network)
```bash
python app.py --host 0.0.0.0      # then browse to http://<pi-ip>:7860 from any device
```
Use engine-only on the Pi (leave the AMT toggle off) — see the Raspberry Pi note below.

### Deep-learning (AMT) toggle
The **"Use AMT transformer"** checkbox under *Advanced* runs the Anticipatory Music Transformer over
the genre seed before arranging. It activates only when a GPU + the `transformers`/`torch`/
`anticipation` packages are present (e.g. Colab T4); on any other machine it **falls back to the fast
engine path automatically** and tells you so in the status panel.

---

## Can it run on a Raspberry Pi 4?

**Mostly yes.** The system is two layers with very different weight:

- **The engine** (genre seeds, arrangement, drums, the groove knob, WAV rendering) is pure Python +
  FluidSynth — no `torch`. FluidSynth, pretty_midi, numpy/scipy and soundfile all have ARM builds, so
  the **whole musical pipeline + the UI run fine on a Pi 4** (offline rendering, not instant, but fine).
- **The deep-learning bed** (Anticipatory Music Transformer, `music-medium-800k`, 360M params) lives
  **only in notebooks 05/07** and the optional UI toggle. On a Pi 4 (no CUDA, ARM CPU, ~4 GB RAM) it's
  impractical — very slow and memory-tight. The smaller `music-small-800k` is more plausible but still
  sluggish.

**Recommended split:** run the engine + UI on the Pi for a self-contained / installation use, and do
the AMT-embellished beds on Colab or your laptop, then copy the frozen MIDI beds to the Pi. The engine
already has a CPU fallback that skips the transformer and uses the genre seed directly — which is
exactly what produced the demo songs — so the Pi can run the full musical system end-to-end without it.

**Pi setup:** `sudo apt-get install -y fluidsynth fluid-soundfont-gm`, then
`pip install -r requirements.txt` (skip `transformers`/`torch`/`anticipation`), then
`python app.py --host 0.0.0.0`.

---

## Quick troubleshooting

| Symptom | Fix |
|---------|-----|
| `No default .sf2 soundfont found` | Put `FluidR3_GM.sf2` in `groovegen_project/soundfonts/`, or `apt-get install fluid-soundfont-gm` (Linux). |
| Audio sounds thin / "8-bit" | You're on the tiny `TimGM6mb.sf2`. Install the full **FluidR3_GM** soundfont (Step 2). |
| `fluidsynth` import or render error | The **system** FluidSynth library isn't installed (Step 2) — `pyfluidsynth` alone isn't enough. |
| AMT / model step is very slow or OOM | You're on CPU. Use a Colab **T4 GPU** runtime for notebooks 05/07. |
| Colab: "could not find config.py after unzip" | You uploaded loose notebooks instead of the project **zip**. Upload `groovegen_project_v1.zip`. |
| Negative-start-time crash | Already guarded in the code; if you hit it after edits, clamp note starts with `max(0.0, t)`. |

---

## TL;DR

- **Just want songs, easiest:** Colab → upload `07_song_generator.ipynb` → T4 GPU → Run all → upload
  the zip when prompted → songs land in `MyDrive/GrooveGen/songs/`.
- **Local:** install FluidSynth + FluidR3_GM soundfont → `pip install -r requirements.txt`
  (+ `transformers torch anticipation` for the DL bed) → run the notebooks in Jupyter or call
  `dlbed.build_genre_song(...)` from a script.
