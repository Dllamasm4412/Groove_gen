"""Builder for Notebook ABC: ONE notebook, ONE runtime session.
Part 0 setup -> Part B (generate gated cached beds from 12 songs) ->
Part C (run the nb15 closed loop on those cached beds) ->
Part D (the experiment UI, LAST because its launch cell blocks).

This is the single-session merge of A_setup_and_experiment_ui + BC. The UI is
placed at the very end so 'Run all' flows straight through the automated B->C
pipeline; the blocking UI only runs if/when you reach the final cell."""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md("""# GrooveGen — Notebook ABC: Full Pipeline in One Runtime

**One notebook, one GPU session.** This merges the old A + BC notebooks so you never
have to switch runtimes:

- **Part 0** — setup + install (+ restore the bed library from Drive if you built it)
- **Part B** — turn your 12 songs into quality-gated, cached music beds (GPU, once)
- **Part C** — run the nb15 closed loop that consumes those beds
- **Part D** — the interactive experiment UI (**runs LAST, on purpose**)

**Why the UI is last:** its launch cell keeps running while the UI is live (it blocks
the notebook). Putting it at the end means **Runtime → Run all** flows cleanly through
the automated B→C pipeline; you only hit the blocking UI cell if you actually want it.
If you just want the generated closed-loop audio, stop after Part C.

**Runtime:** GPU required (Runtime → Change runtime type → GPU). Part D's UI itself is
CPU-only, but since it lives in this GPU notebook it simply reuses the same runtime.

**Prerequisite:** run `LIB_build_beds.ipynb` once first (GPU) and let its cell 1.5 mirror
the library to Drive — then you can delete that runtime; Part 0 below restores it here.

Run top to bottom. Part B is the only GPU/MusicGen-heavy step, and its beds are cached —
so re-running Part C later costs **zero** new generation.""")

# ---------------- Part 0 (full install) ----------------
md("""## Part 0 — Setup (full install)

### 0.1 Get the code into Colab
Just run this cell. If it can't find `groovegen_code_only.zip`, it opens an **upload
widget right here** -- pick the zip from your computer and it unzips automatically. No
need to use Colab's side file panel.""")

code("""import os, sys, glob, zipfile

def _already_setup():
    return os.path.isdir("groovegen") or (
        os.path.isdir("groovegen_project")
        and os.path.isdir(os.path.join("groovegen_project", "groovegen")))

def _find_zip():
    # look in cwd and the usual Colab spots, newest first
    cands = []
    for d in (".", "/content", os.path.expanduser("~")):
        cands += glob.glob(os.path.join(d, "groovegen_code_only*.zip"))
        cands += glob.glob(os.path.join(d, "groovegen_project*.zip"))
    cands = [c for c in dict.fromkeys(cands) if os.path.exists(c)]
    cands.sort(key=os.path.getmtime, reverse=True)
    return cands[0] if cands else None

if not _already_setup():
    zip_path = _find_zip()
    if zip_path is None:
        # nothing on disk -> ask for it right in the cell
        try:
            from google.colab import files
            print("Select groovegen_code_only.zip from your computer ...")
            up = files.upload()   # opens a Choose Files button in the output
            zip_path = next((k for k in up if k.lower().endswith(".zip")), None)
            assert zip_path, "No .zip was chosen. Re-run this cell and pick the zip."
        except ImportError:
            raise FileNotFoundError(
                "groovegen_code_only.zip not found and not in Colab. "
                "Put the zip next to this notebook and re-run.")
    print("unzipping:", zip_path)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(".")

# step into the project folder if we extracted into one
if os.path.isdir("groovegen_project") and not os.path.isdir("groovegen"):
    os.chdir("groovegen_project")

sys.path.insert(0, os.getcwd())
print("cwd:", os.getcwd())
print("has groovegen pkg:", os.path.isdir("groovegen"))
assert os.path.isdir("groovegen"), \\
    "Still no groovegen/ package -- the wrong zip may have been uploaded."
print("setup OK")""")

md("""### 0.1b Restore the bed library from Drive (if built previously)

If you ran `LIB_build_beds.ipynb` and mirrored the library to Drive (its cell 1.5),
this restores `library/` into the current runtime so `USE_LIBRARY=True` finds your
curated beds without regenerating them. Harmless no-op if there's no Drive copy
(the pipeline just falls back to on-the-fly generation).""")

code(r"""# Restore curated bed library from Drive if this runtime doesn't have it yet.
# NOTE: this cell runs BEFORE 0.2 installs the audio/ML stack, so it must NOT
# import from `groovegen` (bed_library -> groovegen.py pulls in pretty_midi etc.,
# which don't exist yet). Restoring is just a file copy, so we hardcode the
# library folder name -- keep this in sync with bed_library.LIBRARY_DIR ("library").
import os, glob, shutil
LIBRARY_DIR = "library"   # must match groovegen.bed_library.LIBRARY_DIR
_have = glob.glob(os.path.join(LIBRARY_DIR, "*", "*.wav"))
if _have:
    print(f"library/ already present: {len(_have)} beds")
else:
    try:
        from google.colab import drive
        drive.mount("/content/drive")
        DRIVE_LIB = "/content/drive/MyDrive/GrooveGen/bed_library"
        src_beds = glob.glob(os.path.join(DRIVE_LIB, "*", "*.wav"))
        if src_beds:
            for src in src_beds:
                rel = os.path.relpath(src, DRIVE_LIB)
                dst = os.path.join(LIBRARY_DIR, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copyfile(src, dst)
            print(f"restored {len(src_beds)} beds from Drive -> {LIBRARY_DIR}/")
        else:
            print("no Drive library found -- USE_LIBRARY will fall back to gen_bed.")
    except ImportError:
        print("not on Colab -- skipping Drive restore.")""")

md("""### 0.2 Install the full audio + ML stack

`transformers` is **pinned to 4.44.2** on purpose — newer versions throw a CUDA
device-side assert inside MusicGen. Do **not** `-U` it. Restart the runtime if Colab
asks after this cell, then re-run 0.1 only.""")

code("""import sys
os.system("pip install -q Cython")
os.system("pip install -q --no-build-isolation madmom")
# Pin transformers AND huggingface_hub together. transformers 4.44.2 requires
# huggingface-hub<1.0, but Colab now ships hub 1.x -> installing them in one
# command lets pip's resolver downgrade the hub to a compatible version.
os.system('pip install -q "transformers==4.44.2" "huggingface_hub>=0.23.2,<0.26" "tokenizers<0.20"')
os.system("pip install -q pretty_midi librosa soundfile imageio imageio-ffmpeg pyloudnorm scikit-learn")
os.system("pip install -q gradio")
# fluidsynth for the closed-loop DRUM renderer (Part C -> nb15's render_aligned_drums
# -> pretty_midi.fluidsynth). ORDER MATTERS: install the SYSTEM fluidsynth FIRST (it
# provides libfluidsynth.so), THEN pip pyfluidsynth -- the binding dlopen's
# libfluidsynth at import, so if the apt lib isn't present the binding loads with
# _HAS_FLUIDSYNTH=False and pretty_midi raises "pyfluidsynth is not installed" mid-mix.
# Also install fluid-soundfont-gm (the FluidR3_GM.sf2 the drum kit needs). Part C runs
# nb15 with GROOVEGEN_SETUP_DONE=1 (skipping nb15's OWN installer), so this cell is the
# ONLY place the closed-loop fluidsynth stack gets installed -- it must be complete.
os.system("apt-get -qq update")
os.system("apt-get -qq install -y fluidsynth fluid-soundfont-gm libfluidsynth3")
os.system("pip install -q pyfluidsynth")
try:
    import fluidsynth as _fs_check
    print("pyfluidsynth import:", "OK" if getattr(_fs_check, "Synth", None) else "loaded but no Synth attr")
except Exception as _e:
    print("[!] pyfluidsynth import FAILED:", repr(_e), "-- retrying apt libfluidsynth verbosely...")
    os.system("apt-get install -y libfluidsynth3 fluidsynth fluid-soundfont-gm")
    os.system("pip install -q --force-reinstall pyfluidsynth")
# pyrubberband + the rubberband CLI: the production-quality re-timing engine
# bed_library.retime_bed uses to move a library bed to the exact committed tempo.
# WITHOUT it, retime_bed falls back to librosa's phase vocoder (audible artifacts).
# Every library bed is retimed on each run, so this materially affects audio quality.
os.system("pip install -q pyrubberband")
os.system("apt-get -qq install -y rubberband-cli")
import shutil as _shutil
print("rubberband CLI:", _shutil.which("rubberband") or "MISSING -- retime_bed will fall back to librosa (lower quality)")

# Verify the pin actually took (Colab sometimes keeps a preloaded hub in the
# running process -- if so, a runtime restart is required before importing).
import importlib.metadata as _md
_hub = _md.version("huggingface_hub")
print("huggingface_hub ==", _hub)
if int(_hub.split(".")[0]) >= 1:
    print("\\n[!] hub is still 1.x in this process. Runtime > Restart session,"
          "\\n    then re-run 0.1 and 0.2. This is expected the first time.")
print("full stack installed")""")

# ---------------- Part B ----------------
md("""## Part B — Generate personalized beds from your 12 songs (GPU, once)

Bucket your 12 songs, build your musical profile, derive a 4-segment arc, write a
MusicGen prompt per segment, generate each bed, **gate it on tempo stability**, and
cache the good ones. Wobbly beds get retried/quantized or replaced by a clean fallback,
so nothing wobbly ever reaches the loop.""")

md("""### B.0 Name your songs -- no uploads needed
Instead of uploading 12 mp3s, just list each song as `("Title", "Artist")` in the
right bucket below. This fetches a **legal 30-second preview** for each from the
**public iTunes Search API** -- no Apple developer account, no API key, no login --
and saves it to `songs/<bucket>N.m4a`. Your normal feature extractor then runs on
those clips, so profiles match the manual path.

Honest limits (all surfaced in the printout):
- **30 s only.** Fine for track-level tempo/energy/valence; Apple picks a representative
  section, but a song with a very different intro vs drop may probe an unexpected part --
  the per-track `~bpm | rms` line lets you eyeball it.
- **Coverage:** obscure/very new tracks may have no preview -> reported as a MISS. For a
  miss, drop that one file into `songs/` yourself named `<bucket><N>` and re-run B.1.
- **Versions:** a remix/live/cover is flagged `[!] verify`. Tighten the query (add the
  album, or "original") if it grabbed the wrong one.""")

code("""song_requests = {
    "danceable": [   # ~6 high-arousal / danceable
        ("Levitating",   "Dua Lipa"),
        ("Despecha",     "Rosalia"),
        ("Don't Start Now", "Dua Lipa"),
        ("Titi Me Pregunto", "Bad Bunny"),
        ("As It Was",    "Harry Styles"),
        ("Blinding Lights", "The Weeknd"),
    ],
    "enjoyed": [     # ~2 you love (not necessarily danceable)
        ("Redbone",      "Childish Gambino"),
        ("Sunflower",    "Post Malone"),
    ],
    "relaxing": [    # ~2+ you find relaxing
        ("Weightless",   "Marconi Union"),
        ("Saturn",       "Sleeping At Last"),
    ],
}
# ^ REPLACE these with YOUR songs. Keep the (Title, Artist) shape.

from groovegen.song_resolver import resolve_songs
song_paths, misses = resolve_songs(song_requests, out_dir="songs", probe=True)""")

md("""### B.1 `song_paths` -- built by B.0's resolver
This just uses what B.0 fetched. If B.0 reported any MISS, save that file into `songs/`
named `<bucket><N>` (e.g. `enjoyed2.m4a`), add its path to the right list below, and
re-run this cell. Expecting ~6 danceable / 2 enjoyed / 2 relaxing (more relaxing is fine).""")

code("""# song_paths came from B.0. To patch in a manually-saved MISS, append its path:
# song_paths["enjoyed"].append("songs/enjoyed2.m4a")

for bucket, paths in song_paths.items():
    for p in paths:
        assert os.path.exists(p), f"missing: {p}"
assert song_paths["danceable"], "no danceable songs resolved -- fix B.0 titles/artists"
assert song_paths["relaxing"], "no relaxing songs resolved -- fix B.0 titles/artists"
if misses:
    print(f"NOTE: {len(misses)} song(s) missed in B.0 -- add them manually before relying "
          f"on the full set: {[m['name'] for m in misses]}")
n = sum(len(v) for v in song_paths.values())
print(f"{n} song clip(s) ready across {sum(1 for v in song_paths.values() if v)} buckets")
for b, paths in song_paths.items():
    print(f"  {b}: {len(paths)}")""")

md("""### B.2 Build your profile + the personalized arc + prompts
`arc_from_profile` gives genre + tempo per segment; we build the MusicGen prompt from
each segment's blended anchor. `generate_and_gate` needs keys: genre, tempo_bpm, prompt.""")

code("""from groovegen.profile_from_songs import build_profile
from groovegen.arc_from_profile import arc_from_profile
from groovegen.prompt_from_anchor import prompt_from_anchor

profile = build_profile(song_paths)
arc = arc_from_profile(profile)

segments = []
for seg in arc:
    prompt = prompt_from_anchor(seg["blended_anchor"], seg["tempo_bpm"])
    segments.append({"genre": seg["genre"], "tempo_bpm": seg["tempo_bpm"], "prompt": prompt})

for s in segments:
    print(f"  {s['genre']:6s} {s['tempo_bpm']:.0f} bpm  |  {s['prompt']}")
# Sanity: tempos should descend (danceable -> calm); build_profile raises on a
# mislabeled bucket (e.g. 'danceable' slower than 'relaxing').""")

md("""### B.3 How the beds are made (read me)
Your 12 songs are **reference material for feature extraction only** -- they are never
played in the output. From each segment's blended feature anchor we built a MusicGen
text prompt (the `prompt` column above), and MusicGen generates a **fresh instrumental
bed** for it. musicgen-small is instrumental, so **no vocals ever appear** in a bed.

Each generated bed is quality-gated on **tempo steadiness** (beat jitter) and **pulse
clarity** -- the two things that actually matter for laying drums on top. (An earlier
version also required every note to sit on the quarter-note grid, which real music never
does; that mistakenly rejected every generated bed and fell back to your raw vocal
songs. Fixed: the grid number is still reported for reference but no longer gates.)

If a bed can't pass, it is regenerated (up to `max_tries`), then beat-quantized -- and
if it still can't pass, the cleanest **generated instrumental** attempt is kept and
flagged. A raw reference song is **never** substituted in as a bed.""")

md("""### B.3b Load MusicGen and generate + gate + cache
Beds are written to `outputs/audio/nb15/beds/` -- the exact folder nb15 reads from in
Part C.""")

code("""# --- guard: transformers 4.44.2 needs huggingface_hub<1.0 --------------------
# If Colab's hub 1.x is still installed/imported, fix it BEFORE importing
# transformers (which raises ImportError otherwise). A downgrade of an
# already-imported package only takes effect after a runtime restart, so we
# stop with a clear instruction rather than failing cryptically.
import importlib.metadata as _md, sys as _sys
_hub = _md.version("huggingface_hub")
if int(_hub.split(".")[0]) >= 1:
    print(f"huggingface_hub=={_hub} is too new; installing a compatible version...")
    get_ipython().system('pip install -q "huggingface_hub>=0.23.2,<0.26" "transformers==4.44.2" "tokenizers<0.20"')
    if "huggingface_hub" in _sys.modules or "transformers" in _sys.modules:
        raise SystemExit(
            "\\n============================================================\\n"
            "Installed the correct huggingface_hub, but the old one was\\n"
            "already loaded in this session. RESTART THE RUNTIME:\\n"
            "  Runtime menu -> Restart session\\n"
            "Then re-run 0.1, 0.2, and this cell. (One-time on a fresh VM.)\\n"
            "============================================================")
print("huggingface_hub OK ==", _md.version("huggingface_hub"))

import torch
from transformers import MusicgenForConditionalGeneration, AutoProcessor
from groovegen.generate_and_gate import (
    make_musicgen_generator, generate_and_gate, summarize, QualityGate)

device = "cuda" if torch.cuda.is_available() else "cpu"
assert device == "cuda", "No GPU. Runtime -> Change runtime type -> GPU, then re-run."
MODEL_ID = "facebook/musicgen-small"
proc  = AutoProcessor.from_pretrained(MODEL_ID)
model = MusicgenForConditionalGeneration.from_pretrained(
    MODEL_ID, use_safetensors=True).to(device)
print("MusicGen loaded on", device)

gen = make_musicgen_generator(model, proc, device)   # reuses nb15 gen logic

BED_CACHE_DIR = "outputs/audio/nb15/beds"
os.makedirs(BED_CACHE_DIR, exist_ok=True)

results = generate_and_gate(
    segments, gen, BED_CACHE_DIR,
    # Gate on tempo steadiness + pulse clarity (NOT on-grid-ness -- see B.3).
    gate=QualityGate(max_beat_jitter_ms=45.0, min_pulse_clarity=0.30),
    max_tries=5, cache=True,   # retry MusicGen more; never fall back to raw songs
)
print(summarize(results))
# summary columns: source (generated/quantized/cached) / jitter / grid_err (diagnostic
# only) / pulse / pass + honest MusicGen call count. Every bed is a MusicGen
# instrumental. failed_gate>0 just means a segment's steadiest attempt was still a
# little loose -- it's kept (instrumental, flagged); re-run to try fresh seeds if you
# want (only failing/uncached segments regenerate).""")

# ---------------- Part C ----------------
md("""## Part C — Run the closed loop on your beds (nb15)

Part C is **notebook 15** itself. Rather than duplicate its cells, we run it in-process
with `%run` so it shares this runtime, the loaded MusicGen model, and the cached beds
from Part B. nb15 has `USE_CACHED_BEDS = True`, so for each segment you'll see
`CACHED gated bed -> segK_...` — confirming zero new MusicGen calls.

We set `GROOVEGEN_SETUP_DONE=1` first: nb15's setup cells detect that flag and **skip
their redundant reinstall and the second MusicGen load**, reusing what Part B already set
up (you'll see `[BC] setup skipped ...` and `[BC] reusing already-loaded MusicGen`).

If you'd rather step through nb15 cell-by-cell (to tweak the HR setpoint curve, the mix,
or the figure), open `notebooks/15_closed_loop_hr_audio.ipynb` directly instead of running
the cell below — the cached beds are already on disk and it will pick them up the same way.""")

code("""# Tell nb15's setup/model cells to skip reinstall + reload (Part B already did both).
os.environ["GROOVEGEN_SETUP_DONE"] = "1"
# Run the full nb15 closed loop end-to-end, reusing the cached beds from Part B.
%run notebooks/15_closed_loop_hr_audio.ipynb""")

md("""### What Part C produced
- A committed **genre/tempo/density trace** that TRACKS the scripted HR setpoint
  (HR is a setpoint the controller tracks — not an efficacy claim).
- Rendered audio with the new mix balance (melody up, latin drums trimmed ~1.5 dB) and
  downbeat-aligned hard cuts between segments.
- An MP4 (figure + muxed audio). Verify audio is present:""")

code("""import glob
mp4s = sorted(glob.glob("outputs/**/*.mp4", recursive=True), key=os.path.getmtime)
if mp4s:
    latest = mp4s[-1]
    print("latest MP4:", latest)
    os.system(f'ffmpeg -i "{latest}" -af volumedetect -f null - 2>&1 | grep mean_volume')
    # mean_volume must NOT be -inf
else:
    print("no MP4 found yet -- check the nb15 render cell output above")""")

md("""### Re-running later
The cached beds persist in `outputs/audio/nb15/beds/`. To iterate on the control loop
(setpoint, mix, figure) **without** paying for generation again, just re-run Part C —
Part B stays cached. To personalize for a **new** set of songs, change `song_paths` in
B.1 and re-run Part B (it overwrites the cache).""")

# ---------------- Part D (experiment UI — LAST, blocking) ----------------
md("""## Part D — Experiment UI (run this LAST)

The live interface where you type a target HR (setpoint) and measured HR, step the loop
one bar at a time, and watch the genre/tempo/density tiers respond. It exercises the
control system with the drum engine and does **not** need MusicGen.

**This cell blocks while the UI is live** — that's why it's the final cell. Everything
above (Parts B and C) has already run by the time you get here, so blocking is fine.
Interrupt the cell (the ■ stop button) to shut the UI down. Setup from Part 0 is reused,
so there's nothing extra to install.""")

code("""from app_experiment import build_ui

demo = build_ui()
# inline=True renders the UI inside this cell's output.
# share=True also gives a public gradio.live link (handy if inline is cramped).
demo.launch(inline=True, share=True, quiet=True)""")

md("""### Stopping / restarting the UI
The launch cell keeps running while the UI is live. To stop it, interrupt the cell
(the ■ stop button). To restart, just re-run the launch cell above.

### Later: real sensor instead of typed HR
When the ESP32 + DigiRobot PPG is ready, the UI does **not** change — only the HR
*source* does. In `groovegen/hr_source.py`, `SerialHRSource(port=\"/dev/ttyUSB0\", baudrate=115200)`
reads one BPM float per line (`Serial.println(bpm);` in firmware) and exposes the same
interface as the manual `TextInputHRSource`.""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
out = "notebooks/ABC_full_pipeline.ipynb"
with open(out, "w") as f:
    nbf.write(nb, f)
print("wrote", out, "with", len(cells), "cells")
