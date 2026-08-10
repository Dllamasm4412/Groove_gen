"""Builder for Notebook LIB: generate + curate the multi-BPM bed library.

Run ONCE (GPU) to populate library/{genre}/{bpm}bpm_{tag}.wav. build_notebook_15.py
and build_notebook_BC.py then READ this library at runtime via
groovegen.bed_library.pick_nearest_bed + retime_bed instead of generating fresh
MusicGen beds every run -- see BUILD_SPEC.md items 1-3 and PATH_RESEARCH.md section 3
for why a curated library replaces on-the-fly generation as the primary path.

Structure (see BUILD_SPEC.md item 2):
  0.1  setup (verbatim BC pattern)               0.2  install (verbatim BC + rubberband)
  0.3  hub guard + MusicGen load (verbatim BC)   1.0  BPM anchors + prompts config
  1.1  generate loop (MusicGen candidates, gated)  1.2  latin symbolic fallback (fluidsynth)
  1.3  curation (listen + KEEP dict)             1.4  commit KEEP -> library/
"""
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
def md(t): cells.append(nbf.v4.new_markdown_cell(t))
def code(t): cells.append(nbf.v4.new_code_cell(t))

md(r"""# GrooveGen — Notebook LIB: Build + Curate the Bed Library

**Run this ONCE per curation pass (GPU).** It generates several MusicGen candidate
beds per (genre, BPM anchor), plus a fluidsynth-rendered symbolic-latin option at
every latin/salsa anchor, gates each candidate on the same tempo-steadiness rule the
live pipeline uses, and lets you **listen and pick** the keeper for each cell. The
kept files are copied into `library/{genre}/{bpm}bpm_{tag}.wav` — the exact layout
`groovegen.bed_library.pick_nearest_bed` reads from at runtime (see
`build_notebook_15.py` and `build_notebook_BC.py`, which now prefer this library over
fresh generation).

**Why a library instead of generating every run** (see
`/Users/daniel/Desktop/PhD/groove_gen_project/assess/PATH_RESEARCH.md` section 3): curated, tempo-tagged
music libraries with nearest-BPM runtime selection are an established pattern in the
adaptive/biofeedback-music literature (e.g. Van den Berghe et al. 2021, *Scientific
Reports* — a 77-track BPM-tagged database with tempo-shift-not-pitch-shift playback).
It also sidesteps MusicGen's training-data bias against non-Western genres (latin/
salsa is part of the ~5-6% non-Western share of typical training corpora — arXiv
"Missing Melodies") by giving latin an honest **symbolic/soundfont fallback** that
never depends on MusicGen learning clave/montuno/tumbao correctly.

**Runtime:** GPU (Runtime → Change runtime type → GPU). No vocals anywhere — every
MusicGen prompt below ends in "instrumental, no vocals", and the symbolic path is
pure MIDI+soundfont (structurally incapable of vocals).

Run top to bottom, listen in section 1.3, edit the `KEEP` dict, then run 1.4.""")

# ---------------- 0.1 setup (copied verbatim from build_notebook_BC.py) ----------------
md("""## Part 0 — Setup

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

# ---------------- 0.2 install (BC's cell + pyrubberband/rubberband-cli) ----------------
md("""### 0.2 Install the full audio + ML stack

Same pin as BC (`transformers==4.44.2`, `huggingface_hub<0.26`) plus this notebook's
own additions: **pyrubberband + rubberband-cli** (RubberBand re-timing -- see
`groovegen/bed_library.py`) and **fluidsynth + a GM soundfont** (symbolic-latin
rendering in section 1.2; fluidsynth/fluid-soundfont-gm are already pulled in by the
line below, matching BC's install).

Do **not** `-U` transformers. Restart the runtime if Colab asks after this cell, then
re-run 0.1 only.""")

code("""import sys
os.system("pip install -q Cython")
os.system("pip install -q --no-build-isolation madmom")
# Pin transformers AND huggingface_hub together (see BC 0.2 for the full rationale:
# transformers 4.44.2 requires huggingface-hub<1.0, but Colab now ships hub 1.x).
os.system('pip install -q "transformers==4.44.2" "huggingface_hub>=0.23.2,<0.26" "tokenizers<0.20"')
os.system("pip install -q pretty_midi librosa soundfile imageio imageio-ffmpeg pyloudnorm scikit-learn")
os.system("pip install -q pyfluidsynth gradio")
# fluidsynth CLI + a GM soundfont for the symbolic-latin fallback (section 1.2).
# This is BEST-EFFORT and non-fatal: if it fails, only section 1.2 (the symbolic
# latin option) is unavailable -- all MusicGen generation (incl. latin via prompt)
# still works. We retry, refresh the apt lists first, and NEVER swallow errors,
# because a silent soundfont-missing failure is what quietly breaks 1.2.
import shutil as _shutil
os.system("apt-get -qq update")
os.system("apt-get -qq install -y fluidsynth fluid-soundfont-gm")
if _shutil.which("fluidsynth") is None:
    # retry once WITHOUT -qq so any real apt error is visible in the cell output
    print("[fluidsynth] first install attempt did not land the binary; retrying verbosely...")
    os.system("apt-get update")
    os.system("apt-get install -y fluidsynth fluid-soundfont-gm")
# --- library-notebook-specific additions -------------------------------------
# pyrubberband: Python wrapper around the `rubberband` CLI binary. RubberBand
# (unlike librosa's phase vocoder) stays artifact-free from tiny deviations up
# to large stretches -- see PATH_RESEARCH.md section 4 -- so it's the re-timing
# engine bed_library.retime_bed uses to move a library bed from its tagged BPM
# to the exact committed tempo.
os.system("pip install -q pyrubberband")
os.system("apt-get -qq install -y rubberband-cli > /dev/null")

# Verify the transformers/hub pin actually took (Colab sometimes keeps a
# preloaded hub in the running process -- if so, a runtime restart is required
# before importing).
import importlib.metadata as _md
_hub = _md.version("huggingface_hub")
print("huggingface_hub ==", _hub)
if int(_hub.split(".")[0]) >= 1:
    print("\\n[!] hub is still 1.x in this process. Runtime > Restart session,"
          "\\n    then re-run 0.1 and 0.2. This is expected the first time.")

# Verify rubberband + fluidsynth binaries landed (retime_bed / symbolic fallback
# both warn-and-degrade rather than silently doing the wrong thing if missing,
# but it's cheaper to catch a broken install here than mid-generation).
print("rubberband CLI:", _shutil.which("rubberband") or "MISSING -- retime_bed will fall back to librosa with a warning")
_fs = _shutil.which("fluidsynth")
if _fs:
    print("fluidsynth CLI:", _fs)
else:
    print("fluidsynth CLI: MISSING -- section 1.2 (symbolic latin) will be SKIPPED.")
    print("                This is NON-FATAL: all MusicGen bed generation (including")
    print("                latin via prompt in 1.1) still works. Only the MIDI+soundfont")
    print("                latin option is unavailable. Safe to continue.")
print("full stack + library deps installed")""")

# ---------------- 0.3 hub guard + MusicGen load (copied from BC ~line 233-266) --------
md("""### 0.3 Hub guard + load MusicGen
Identical guard/load pattern to `build_notebook_BC.py` Part B.3b -- kept byte-for-byte
so the two notebooks' MusicGen behavior never drifts apart.""")

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
    measure_tempo_stability, QualityGate)

device = "cuda" if torch.cuda.is_available() else "cpu"
assert device == "cuda", "No GPU. Runtime -> Change runtime type -> GPU, then re-run."
MODEL_ID = "facebook/musicgen-small"
proc  = AutoProcessor.from_pretrained(MODEL_ID)
model = MusicgenForConditionalGeneration.from_pretrained(
    MODEL_ID, use_safetensors=True).to(device)
print("MusicGen loaded on", device)""")

# ---------------- 1.0 BPM anchors + reference-anchored prompts ----------------
md("""## Part 1 — Config: BPM anchors + reference-anchored prompts

**BPM anchors per genre band** (matches the bands `build_notebook_15.py`'s
`TEMPO_BAND_GENRE` walks: latin >=112, pop 98-112, r&b 84-98, calm <84 -- anchors
below cover each band plus one point beyond its edge so `pick_nearest_bed` always has
a close match, never a >10 BPM reach).

**Why these prompts are richer than the live pipeline's** (see CODE_AUDIT.md finding
#1-2): `prompt_from_anchor.py`'s runtime prompts collapse ~20 numeric song features
into 1 tempo number + 4 generic descriptor words, and literally never emit the words
"clave", "montuno", "tumbao", or "conga" even for latin/salsa. Because THIS notebook's
prompts are hand-written once and curated (not auto-generated per session), we can
afford to make them maximally genre-specific and reference-anchored -- the cost of a
rich prompt is paid once at library-build time, not on every run.""")

code(r"""BPM_ANCHORS = {
    "latin/salsa": [128, 120, 112, 105],
    "pop":         [104, 100, 95, 90],     # pop band 88-105
    "r&b/soul":    [88, 84, 80],           # r&b band 80-88
    "calm":        [80, 76, 72, 70],
}
N_CANDIDATES_PER_ANCHOR = 3

# Reference-anchored prompts: name a well-known-style cue + concrete instrumentation
# vocabulary per (genre, bpm), not just "a {genre} groove at {bpm} BPM". For
# latin/salsa specifically, always include clave/montuno/tumbao/conga vocabulary --
# this is the fix for CODE_AUDIT.md finding #2 (the live prompt builder never emits
# those words). Every prompt ends "instrumental, no vocals" (hard project rule).
PROMPTS = {
    "latin/salsa": {
        128: ("an authentic salsa/latin groove in the style of classic Marc Anthony "
              "salsa, at 128 BPM, piano montuno locked to a 2-3 son clave, syncopated "
              "bass tumbao, congas and timbales, bright horn stabs, instrumental, no vocals"),
        120: ("an authentic salsa/latin groove in the style of classic Marc Anthony "
              "salsa, at 120 BPM, piano montuno locked to a 2-3 son clave, syncopated "
              "bass tumbao, congas and timbales, bright horn stabs, instrumental, no vocals"),
        112: ("a mid-tempo salsa/latin groove, son montuno feel, at 112 BPM, piano "
              "montuno over a 2-3 clave, walking bass tumbao, congas, timbales, "
              "occasional horn stab accents, instrumental, no vocals"),
        105: ("a relaxed salsa/latin groove, son montuno feel, at 105 BPM, piano "
              "montuno over a 2-3 clave, bass tumbao, congas and light timbales, "
              "instrumental, no vocals"),
    },
    "pop": {
        104: ("an upbeat danceable pop groove in the style of a Dua Lipa / Bruno Mars "
              "dance-pop track, at 104 BPM, syncopated plucky clavinet or synth comp, "
              "punchy finger-bass, tight steady drums, bright and energetic, "
              "instrumental, no vocals"),
        100: ("a steady danceable pop groove at 100 BPM, syncopated synth/clavinet "
              "comp, punchy bass, tight drums, bright and upbeat but not rushed, "
              "instrumental, no vocals"),
        95:  ("a mid-tempo pop groove at 95 BPM, warm synth or electric-piano comp, "
              "melodic bass, steady unhurried drums, polished contemporary pop feel, "
              "instrumental, no vocals"),
        90:  ("a laid-back pop groove at 90 BPM, warm electric piano comp, smooth "
              "melodic bass, steady relaxed drums, contemporary pop-soul crossover "
              "feel, instrumental, no vocals"),
    },
    "r&b/soul": {
        88: ("a warm neo-soul / r&b groove in the style of a D'Angelo or Anderson "
             ".Paak track, at 88 BPM, laid-back electric piano and clavinet comp, "
             "deep finger-bass in the pocket, softly swung steady drums, warm and "
             "smooth, instrumental, no vocals"),
        84: ("a warm r&b/soul groove at 84 BPM, mellow electric piano comp, deep "
             "laid-back finger-bass, softly swung drums, smooth and intimate, "
             "instrumental, no vocals"),
        80: ("a slow warm r&b/soul groove at 80 BPM, sparse mellow electric piano "
             "comp, deep laid-back bass, soft swung drums, smooth and mellow, "
             "instrumental, no vocals"),
    },
    "calm": {
        80: ("a hushed, sparse neo-soul groove at 80 BPM, minimal warm electric "
             "piano, slow deep bass, very sparse soft drums, gentle and intimate, "
             "instrumental, no vocals"),
        76: ("a hushed, sparse neo-soul groove at 76 BPM, minimal warm electric "
             "piano, slow deep bass, very sparse soft drums, calm and gentle, "
             "instrumental, no vocals"),
        72: ("a slow, hushed neo-soul groove at 72 BPM, minimal warm electric piano "
             "or pad, slow deep bass, extremely sparse soft drums, gentle and "
             "meditative, instrumental, no vocals"),
        70: ("a very slow, hushed neo-soul groove at 70 BPM, minimal sustained warm "
             "pad, slow deep bass, extremely sparse soft drums, meditative and calm, "
             "instrumental, no vocals"),
    },
}
# Sanity: every prompt must exist for every configured anchor, and every prompt
# must say instrumental/no vocals (no vocals anywhere in this codebase).
for genre, anchors in BPM_ANCHORS.items():
    for bpm in anchors:
        assert bpm in PROMPTS[genre], f"missing prompt for {genre} @ {bpm} bpm"
        p = PROMPTS[genre][bpm]
        assert "no vocals" in p, f"prompt for {genre}@{bpm} missing 'no vocals': {p}"
    if genre == "latin/salsa":
        for bpm in anchors:
            p = PROMPTS[genre][bpm].lower()
            assert any(w in p for w in ("clave", "montuno", "tumbao")), (
                f"latin prompt for {bpm} bpm missing clave/montuno/tumbao vocabulary")
print("BPM anchors + prompts OK:")
for genre, anchors in BPM_ANCHORS.items():
    print(f"  {genre:10s}: {anchors}")""")

# ---------------- 1.1 generate loop ----------------
md("""## 1.1 Generate MusicGen candidates per (genre, bpm), gated

Reuses the SAME `measure_tempo_stability` + `QualityGate` machinery
`generate_and_gate.py` uses at runtime (jitter + pulse_clarity gate, grid_err
diagnostic-only -- **not regressing the gate fix**: no raw-reference-song fallback
exists here either, every candidate is a MusicGen instrumental). Candidates land in
`library_candidates/{genre}/{bpm}bpm_cand{k}.wav` with a printed gate report; nothing
is auto-promoted to `library/` -- that only happens after you curate in 1.3-1.4.""")

code(r"""import re as _re
import numpy as np
import soundfile as sf

CAND_DIR = "library_candidates"
os.makedirs(CAND_DIR, exist_ok=True)

GEN_SECONDS = 12.0          # same short-generate-then-loop strategy as nb15/BC
TOKENS_PER_SEC = 50
MAX_NEW_TOKENS_CAP = 1400

def _loop_to_length(a, sr, target_seconds, tempo_bpm):
    '''Identical to nb15/BC's helper: trim to a whole-bar multiple (so the loop
    point lands on a downbeat) then tile to >= target_seconds, with a 1.5ms
    micro-fade at the wrap to kill sample-boundary clicks.'''
    target_n = int(round(target_seconds * sr))
    sec_per_bar = 4.0 * 60.0 / float(tempo_bpm)
    bar_n = max(1, int(round(sec_per_bar * sr)))
    whole_bars = max(1, len(a) // bar_n)
    a = a[: whole_bars * bar_n]
    f = max(1, int(0.0015 * sr))
    if len(a) > 2 * f:
        ramp = np.linspace(0.0, 1.0, f, dtype=a.dtype)
        a = a.copy(); a[:f] *= ramp; a[-f:] *= ramp[::-1]
    if len(a) >= target_n:
        return a[:target_n]
    reps = int(np.ceil(target_n / len(a)))
    return np.tile(a, reps)[:target_n]

def gen_bed_candidate(prompt, out_wav, seconds, tempo_bpm):
    '''Same generation strategy as nb15.gen_bed / BC's make_musicgen_generator:
    short MusicGen sample (capped well under the ~30s position-embedding limit),
    looped to the requested length at the target tempo's own bar length.'''
    gen_tokens = min(int(GEN_SECONDS * TOKENS_PER_SEC), MAX_NEW_TOKENS_CAP)
    inputs = proc(text=[prompt], padding=True, return_tensors="pt").to(device)
    with torch.no_grad():
        wav = model.generate(**inputs, max_new_tokens=gen_tokens,
                              do_sample=True, guidance_scale=3.0)
    sr = model.config.audio_encoder.sampling_rate
    a = wav[0, 0].cpu().numpy()
    a = _loop_to_length(a, sr, seconds, tempo_bpm)
    sf.write(out_wav, a, sr)
    return out_wav, sr

gate = QualityGate(max_beat_jitter_ms=45.0, min_pulse_clarity=0.30)  # SAME gate as live pipeline
CAND_SECONDS = 16.0   # long enough for a stable tempo/pulse measurement

candidate_manifest = []  # (genre, bpm, k, path, metrics, passed)
for genre, anchors in BPM_ANCHORS.items():
    safe_genre = _re.sub(r"[^0-9A-Za-z]+", "-", genre).strip("-") or "bed"
    genre_dir = os.path.join(CAND_DIR, safe_genre)
    os.makedirs(genre_dir, exist_ok=True)
    for bpm in anchors:
        prompt = PROMPTS[genre][bpm]
        for k in range(N_CANDIDATES_PER_ANCHOR):
            out_wav = os.path.join(genre_dir, f"{bpm}bpm_cand{k}.wav")
            gen_bed_candidate(prompt, out_wav, CAND_SECONDS, bpm)
            y, sr = sf.read(out_wav)
            m = measure_tempo_stability(y, sr, bpm)
            passed = gate.passes(m)
            candidate_manifest.append((genre, bpm, k, out_wav, m, passed))
            print(f"  {genre:10s} {bpm:5.0f}bpm cand{k}: jitter={m['beat_jitter_ms']:5.1f}ms "
                  f"pulse={m['pulse_clarity']:.2f} grid*={m['grid_err_mean_ms']:5.1f}ms "
                  f"{'PASS' if passed else 'below-gate (still kept as a candidate to audition)'}")
print(f"\n{len(candidate_manifest)} MusicGen candidates generated -> {CAND_DIR}/")
print("grid* is DIAGNOSTIC ONLY (not gated) -- see generate_and_gate.QualityGate docstring.")""")

# ---------------- 1.2 latin symbolic fallback (fluidsynth) ----------------
md("""## 1.2 Latin symbolic fallback (MIDI + soundfont, no MusicGen)

Per PATH_RESEARCH.md section 5, latin/salsa is honestly better served by a
symbolic/soundfont construction than by text-to-music generation, given documented
training-data bias against non-Western genres. `genre_styles.build_style_seed`
already encodes the clave/montuno/tumbao/conga/horn-stab structure explicitly (as
MIDI, not as prompt text) -- we render that MIDI through fluidsynth at each latin BPM
anchor, so there's always a clean, structurally-correct latin option per anchor even
if every MusicGen candidate above sounds generic.""")

code(r"""import glob as _glob
import subprocess

from groovegen.genre_styles import build_style_seed

def _find_soundfont():
    cands = [
        "/usr/share/sounds/sf2/FluidR3_GM.sf2",
        "/usr/share/sounds/sf2/default-GM.sf2",
        "/etc/alternatives/default-GM.sf2",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    hits = _glob.glob("/usr/share/sounds/sf2/*.sf2") + _glob.glob("/usr/share/sounds/**/*.sf2", recursive=True)
    if hits:
        return hits[0]
    return None

# Section 1.2 is OPTIONAL. If fluidsynth or a soundfont didn't install (see 0.2),
# skip this whole section cleanly -- the MusicGen latin candidates from 1.1 are
# still available, and curation/commit below work fine without the symbolic option.
import shutil as _shutil
_HAVE_FS = _shutil.which("fluidsynth") is not None
SF2_PATH = _find_soundfont() if _HAVE_FS else None
symbolic_manifest = []
if not _HAVE_FS or SF2_PATH is None:
    _why = "fluidsynth binary" if not _HAVE_FS else "GM soundfont (.sf2)"
    print(f"[1.2] SKIPPED -- {_why} not found. This is fine: latin MusicGen candidates")
    print("      from 1.1 are still available for curation. To enable the symbolic latin")
    print("      option, get fluidsynth+fluid-soundfont-gm installed in 0.2 and re-run.")
else:
  print("using soundfont:", SF2_PATH)

LATIN_GENRE_KEY = "latin/salsa"   # matches genre_styles.GENRE_STYLES key exactly
safe_latin = _re.sub(r"[^0-9A-Za-z]+", "-", LATIN_GENRE_KEY).strip("-")
symbolic_dir = os.path.join(CAND_DIR, safe_latin)
os.makedirs(symbolic_dir, exist_ok=True)

# When fluidsynth/soundfont is unavailable, _anchors_to_render is empty so this
# loop is a clean no-op (symbolic_manifest stays []). Otherwise it renders one
# symbolic-latin candidate per latin BPM anchor.
_anchors_to_render = BPM_ANCHORS[LATIN_GENRE_KEY] if (_HAVE_FS and SF2_PATH) else []
for bpm in _anchors_to_render:
    # build_style_seed bakes genre_styles.py's OWN nominal tempo (180 for
    # latin/salsa) into the MIDI's note timing; we want the MIDI itself
    # authored at the anchor's true tempo, so we render enough bars that,
    # after re-timing 180 -> bpm below, we still cover CAND_SECONDS.
    bars = 8
    pm = build_style_seed(LATIN_GENRE_KEY, bars=bars, seed=0)
    raw_midi = os.path.join(symbolic_dir, f"_raw_{bpm}bpm.mid")
    pm.write(raw_midi)

    raw_wav = os.path.join(symbolic_dir, f"_raw_{bpm}bpm.wav")
    # fluidsynth renders the MIDI at genre_styles.py's own nominal 180 BPM
    # (the tempo baked into the MIDI file's timing); -F writes to a WAV
    # instead of playing live audio, -ni = no MIDI-in, non-interactive.
    subprocess.run(
        ["fluidsynth", "-ni", SF2_PATH, raw_midi, "-F", raw_wav, "-r", "44100"],
        check=True, capture_output=True,
    )

    # Re-time the fixed-180-bpm render down/up to this anchor's true bpm with
    # the SAME RubberBand path the runtime uses (bed_library.retime_bed) --
    # keeps the symbolic fallback on the identical re-timing quality bar as
    # every other library entry, and pitch-correct (unlike naive resampling).
    from groovegen.bed_library import retime_bed
    out_wav = os.path.join(symbolic_dir, f"{bpm}bpm_symbolic.wav")
    retime_bed(raw_wav, out_wav, from_bpm=180.0, to_bpm=float(bpm), crispness=6)

    y, sr = sf.read(out_wav)
    m = measure_tempo_stability(y, sr, bpm)
    symbolic_manifest.append((bpm, out_wav, m))
    print(f"  latin/salsa {bpm:5.0f}bpm symbolic: dur={len(y)/sr:5.1f}s "
          f"jitter={m['beat_jitter_ms']:5.1f}ms pulse={m['pulse_clarity']:.2f}")

print(f"\n{len(symbolic_manifest)} symbolic-latin candidates -> {symbolic_dir}/")""")

# ---------------- 1.3 curation (listen + KEEP dict) ----------------
md("""## 1.3 Curate: listen to every candidate, then edit `KEEP`

Playback cells below group every candidate by genre/bpm (MusicGen candidates first,
then the symbolic-latin option where it exists). **Listen, then edit the `KEEP` dict**
in the next cell: for each `"{genre}/{bpm}bpm"` key, name which candidate tag to keep
(`"cand0"`, `"cand1"`, `"cand2"`, or `"symbolic"` for latin/salsa). Leaving a key out of
`KEEP` skips that bpm anchor entirely (it simply won't be in the library, and
`pick_nearest_bed` will reach for the next-nearest anchor that IS present).""")

code(r"""from IPython.display import Audio, display

for genre, anchors in BPM_ANCHORS.items():
    safe_genre = _re.sub(r"[^0-9A-Za-z]+", "-", genre).strip("-") or "bed"
    for bpm in anchors:
        print(f"\n=== {genre} @ {bpm} bpm ===")
        for k in range(N_CANDIDATES_PER_ANCHOR):
            p = os.path.join(CAND_DIR, safe_genre, f"{bpm}bpm_cand{k}.wav")
            if os.path.exists(p):
                print(f"  cand{k}:")
                display(Audio(p))
        if genre == LATIN_GENRE_KEY:
            sp = os.path.join(CAND_DIR, safe_genre, f"{bpm}bpm_symbolic.wav")
            if os.path.exists(sp):
                print("  symbolic:")
                display(Audio(sp))""")

code(r"""# ---- EDIT THIS: pick the keeper tag for each "{genre}/{bpm}bpm" you listened to.
# Values are candidate tags: "cand0" | "cand1" | "cand2" | "symbolic" (latin only).
# This default selection keeps the FIRST MusicGen candidate everywhere and the
# symbolic render for latin/salsa (matching PATH_RESEARCH.md's recommendation that
# latin is more honestly served by the symbolic path) -- edit after listening above.
KEEP = {}
for genre, anchors in BPM_ANCHORS.items():
    for bpm in anchors:
        key = f"{genre}/{bpm}bpm"
        KEEP[key] = "symbolic" if genre == LATIN_GENRE_KEY else "cand0"

print("KEEP selections (edit the dict above after listening, then re-run this cell):")
for k, v in KEEP.items():
    print(f"  {k:22s} -> {v}")""")

# ---------------- 1.4 commit KEEP -> library/ ----------------
md("""## 1.4 Commit `KEEP` into `library/`

Copies exactly the candidates named in `KEEP` into
`library/{genre}/{bpm}bpm_{tag}.wav` -- the layout `groovegen.bed_library.list_library`
/ `pick_nearest_bed` read. Prints the resulting library tree so you can confirm
coverage before switching `build_notebook_15.py` / `build_notebook_BC.py` to
`USE_LIBRARY = True`.""")

code(r"""import shutil
from groovegen.bed_library import sanitize_genre, LIBRARY_DIR

os.makedirs(LIBRARY_DIR, exist_ok=True)
committed = []
for key, tag in KEEP.items():
    # genre names themselves contain "/" (e.g. "latin/salsa", "hip-hop/rap",
    # "r&b/soul"), and the key is f"{genre}/{bpm}bpm" -- so split on the LAST
    # "/" only, leaving the genre (with its internal slash) intact.
    genre, bpm_str = key.rsplit("/", 1)
    bpm = bpm_str.replace("bpm", "")
    safe_genre = sanitize_genre(genre)
    cand_dir = os.path.join(CAND_DIR, safe_genre)
    if tag == "symbolic":
        src = os.path.join(cand_dir, f"{bpm}bpm_symbolic.wav")
    else:
        src = os.path.join(cand_dir, f"{bpm}bpm_{tag}.wav")
    if not os.path.exists(src):
        print(f"  [!] SKIP {key} -> {tag}: {src} not found (did you run 1.1/1.2 for this anchor?)")
        continue
    dst_dir = os.path.join(LIBRARY_DIR, safe_genre)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, f"{bpm}bpm_{tag}.wav")
    shutil.copyfile(src, dst)
    committed.append(dst)
    print(f"  {key:22s} -> {dst}")

print(f"\n{len(committed)} beds committed to {LIBRARY_DIR}/. Library tree:")
for genre_dir in sorted(_glob.glob(os.path.join(LIBRARY_DIR, "*"))):
    print(f"  {genre_dir}/")
    for f in sorted(_glob.glob(os.path.join(genre_dir, "*.wav"))):
        print(f"    {os.path.basename(f)}")

assert committed, "nothing was committed -- check KEEP tags match generated candidate files"
print("\nDone. build_notebook_15.py / build_notebook_BC.py with USE_LIBRARY=True will "
      "now pick_nearest_bed() from this library and retime_bed() to the exact committed "
      "tempo, falling back to gen_bed only if a genre folder is empty.")""")

# ---------------- 1.5 persist library/ to Google Drive ----------------
md("""## 1.5 Persist the library to Google Drive (survives a disconnect)

The committed `library/` lives on the Colab VM's local disk, which is **wiped when the
runtime disconnects or times out**. Building the library costs a full GPU generation pass,
so we mirror it to Drive **once** here; the A/BC/15 notebooks then restore it automatically
at startup (see their setup cells) instead of regenerating.

Run this cell after 1.4. It mounts Drive and copies `library/` ->
`MyDrive/GrooveGen/bed_library/`. Safe to skip if you are happy rebuilding every session,
but recommended.""")

code(r"""# Mirror the curated library to Drive so it outlives this runtime.
import os, shutil, glob as _glob
try:
    from google.colab import drive
    drive.mount("/content/drive")
    DRIVE_LIB = "/content/drive/MyDrive/GrooveGen/bed_library"
    os.makedirs(DRIVE_LIB, exist_ok=True)
    n = 0
    for src in _glob.glob(os.path.join(LIBRARY_DIR, "*", "*.wav")):
        rel = os.path.relpath(src, LIBRARY_DIR)          # {genre}/{bpm}bpm_{tag}.wav
        dst = os.path.join(DRIVE_LIB, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst); n += 1
    print(f"mirrored {n} beds -> {DRIVE_LIB}")
    print("Library is now persistent. A/BC/15 will restore it from Drive automatically.")
except ImportError:
    print("Not on Colab -- skipping Drive mirror (library/ already on local disk).")""")

nb["cells"] = cells
nb["metadata"] = {
    "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
    "language_info": {"name": "python"},
}
out = "notebooks/LIB_build_beds.ipynb"
with open(out, "w") as f:
    nbf.write(nb, f)
print("wrote", out, "with", len(cells), "cells")
