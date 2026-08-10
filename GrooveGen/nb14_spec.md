# Notebook 14 — Colab audio-proof of the tempo-crossfade cascade

## Goal
Prove, WITH REAL AUDIO the user can hear, that the tempo tier of the cascade
works: generate real MusicGen beds at descending tempos (down-regulation), warp
genre drums onto each, and crossfade between consecutive tempos so the tempo
change is smooth. Render everything into ONE MP4 the user can play inline.

This is the "audio-proof layer" (todo #5). Notebook 13 already proved the CONTROL
math in simulation (6.7x tighter than naive). NB14 proves the AUDIO.

## Decisions (fail-fast defaults — do NOT re-ask the user)
- **Bed source:** MusicGen on GPU (facebook/musicgen-small via transformers).
  Down-regulation direction: **88 -> 76 -> 64 BPM** (3 beds, descending).
- **Crossfade A/B:** build BOTH and let the user hear the difference:
  - (A) NAIVE equal-power crossfade: just overlap the two full mixes with an
    equal-power (cos/sin) gain ramp. Beats will NOT be phase-aligned across the
    two different-tempo beds — this is the failure mode to expose.
  - (B) BEAT-ALIGNED crossfade: find the last downbeat of the outgoing segment
    and the first downbeat of the incoming segment (from bed_info downbeats /
    bed_grid) and align the crossfade window so the incoming downbeat lands
    where the outgoing bar would have continued. Equal-power ramp over ~1 bar.
  Render A and B as separate audio, then one comparison MP4 with both back to
  back (spoken/silence gap + on-screen label) so the ear can judge.
- **Genre:** single genre for this proof (pop) to isolate the TEMPO variable.
  Genre-tier switching is already demonstrated in nb13 sim; nb14 is about tempo
  audio. Keep drum_style="pop", event_density mid (e.g. 10).

## Environment / Colab setup (match existing notebooks 09/12/13)
First code cell = Colab setup:
```
!pip install -q Cython
!pip install -q --no-build-isolation madmom
!pip install -q -U transformers
!pip install -q pretty_midi librosa soundfile imageio imageio-ffmpeg
# FluidSynth + a GM soundfont for drums:
!apt-get -qq install -y fluidsynth >/dev/null
# clone / cd into groovegen_project so `from groovegen import hybrid_render` works
```
Assume the user uploads/clones the groovegen_project package (same as prior
notebooks — reuse whatever import pattern nb12/nb13 use; check them). Detect GPU
with torch.cuda.is_available() and print it. If no GPU, fall back to CPU with a
printed warning (MusicGen-small runs on CPU, just slow).

## MusicGen bed generation (match nb09 pattern EXACTLY — transformers, NOT audiocraft)
- `from transformers import AutoProcessor, MusicgenForConditionalGeneration`
- model `facebook/musicgen-small`, move to cuda if available.
- MusicGen does NOT accept exact BPM. Prompt with tempo words, then DETECT the
  real tempo with hybrid_render.get_bed_info(...) and report the actual BPM.
  Prompt template e.g. "a {feel} pop groove at about {bpm} BPM, steady drums,
  warm keys, {mood}". For 88 use "mid-tempo", 76 "relaxed downtempo", 64 "slow
  calm". Generate ~12-16 s each (enough for a couple bars + crossfade overlap).
- Save each bed to a wav (soundfile) so get_bed_info can analyze from disk.

## Hybrid render (use existing API — DO NOT reimplement)
For each bed:
```
from groovegen import hybrid_render as hr
info = hr.get_bed_info(bed_wav, expected_tempo=target_bpm)  # detects real tempo
res  = hr.render_aligned_drums(info, drum_style="pop", event_density=10, seed=0)
drums = res["drums"]           # float32, len == bed length, at info sr
bed   = info["y"]              # mono bed audio at info["sr"]
sr    = info["sr"]
mix   = 0.8*bed[:len(drums)] + 0.9*drums   # simple mix; then peak-normalize
```
Report each bed's DETECTED tempo_bpm (info["tempo_bpm"]) vs the target — this is
the honest "MusicGen didn't give us exactly 88" disclosure.

## Crossfade implementations (the core of the proof)
Write two functions in a notebook cell:

def equal_power_xfade(a, b, sr, fade_s):
    n = int(fade_s*sr); ...
    # cos/sin equal-power ramp over the overlap of a's tail and b's head
    # returns concatenation: a[:-n] + (a_tail*cosramp + b_head*sinramp) + b[n:]

def beat_aligned_xfade(mix_a, info_a, mix_b, info_b, sr, fade_bars=1.0):
    # choose splice point near end of mix_a on a downbeat of bed A
    # choose head of mix_b starting at first downbeat of bed B
    # crossfade length = fade_bars * bed A sec_per_bar (info_a["sec_per_bar"])
    # equal-power ramp; align so B's downbeat coincides with the grid continuation
    # Use info["downbeats"] or info["bed_grid"] + info["sec_per_bar"].

Build the full descending sequence twice:
  seq_naive     = xfade(mix88, mix76) then xfade(result, mix64)  [equal_power]
  seq_aligned   = beat_aligned across the same three
Peak-normalize each final sequence.

## MP4 render (verify audio! mean dB must NOT be -inf)
- Build a simple visual (matplotlib, dark theme per project palette): a panel
  showing tempo dropping 88->76->64 as a stepped line with the crossfade regions
  shaded, plus a big label of which variant is playing ("NAIVE equal-power" then
  "BEAT-ALIGNED"). Use the project dark palette (BG #171614, FG #CDCCCA, accent
  #4F98A3, gold #FFC553).
- Simplest robust approach: one static labeled image per variant, hold it for the
  variant's duration, concat the two variants' audio with a ~0.7 s silence gap,
  mux with ffmpeg. Or a lightweight animated playhead if easy — static is fine.
- Use imageio-ffmpeg / ffmpeg to combine. Write final audio to wav, images to
  png, then ffmpeg to make an MP4 with AAC audio.
- CRITICAL: after writing the MP4, run
  `ffmpeg -i out.mp4 -af volumedetect -f null -` and assert the mean_volume is
  NOT -inf. Print the measured mean dB in a cell so the user sees the proof the
  audio is real. Also write both variant wavs so the user has raw audio too.

## Notebook structure (markdown + code cells)
1. MD: title + what this proves + the key risk (different-tempo beds -> beats
   won't align in a naive crossfade; beat-aligned fixes it). Reference nb13.
2. Code: Colab setup (pip/apt).
3. Code: imports + GPU check + load MusicGen model.
4. MD: bed generation plan (88/76/64, down-reg).
5. Code: generate 3 beds, save wavs.
6. Code: analyze each with get_bed_info, print detected vs target BPM.
7. Code: render aligned drums + mix for each bed.
8. MD: the two crossfade strategies explained.
9. Code: equal_power_xfade + beat_aligned_xfade functions.
10. Code: build seq_naive and seq_aligned; peak-normalize; save wavs.
11. Code: build the comparison MP4 (visual + muxed audio).
12. Code: ffmpeg volumedetect assertion (mean dB != -inf), print result.
13. MD: how to listen / what to judge / next step (wire into CascadeController
    from pd_controller.py so the tempo tier drives which bed to generate next).

## Constraints
- nbformat 4.5 (nbformat.v4, set nbformat_minor=5, give every cell an id).
- Build via a python script build_notebook_14.py that emits
  groovegen_project/notebooks/14_tempo_crossfade_audio_proof.ipynb
- Every code cell must ast.parse cleanly. Validate with nbformat.validate.
- Do NOT run MusicGen in the sandbox (no GPU / heavy). The notebook is FOR Colab.
  BUT dry-run the pure-python crossfade math (equal_power + beat_aligned) in the
  sandbox on the two uploaded beds to prove the splice logic before shipping.
- Reuse hybrid_render + pd_controller APIs; do not reimplement drum/bed logic.
- Reference in the final MD how this connects to CascadeController.step() which
  returns {genre,tempo_bpm,density,tier_that_acted}.

## Uploaded beds for the sandbox dry-run of crossfade math
- r&b bed:  uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
- salsa bed: uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
(These are just to exercise get_bed_info + the two xfade functions on real audio
in the sandbox — different tempos, proves the splice runs and produces non-silent
output. The Colab notebook itself generates fresh MusicGen beds.)

## Concrete patterns to REUSE (verbatim style from existing notebooks)

### Setup cell (from nb13) — zip upload + extract + sys.path
```
!pip install -q Cython
!pip install -q --no-build-isolation madmom
!pip install -q -U transformers
!pip install -q pretty_midi librosa soundfile imageio imageio-ffmpeg
!apt-get -qq install -y fluidsynth >/dev/null

from google.colab import files
import zipfile, os, glob, sys
up = files.upload()  # pick groovegen_code_only.zip
zip_name = next(k for k in up if k.endswith('.zip'))
with zipfile.ZipFile(zip_name) as z:
    z.extractall('.')
proj = 'groovegen_project'
sys.path.insert(0, proj)
os.chdir(proj)   # so relative sf2/output paths behave like other notebooks
```
(Confirm the exact extract dir / sys.path line by reading nb13 cell 1 fully.)

### MusicGen (from nb09)
```
import torch, soundfile as sf
from transformers import MusicgenForConditionalGeneration, AutoProcessor
device = "cuda" if torch.cuda.is_available() else "cpu"
proc  = AutoProcessor.from_pretrained("facebook/musicgen-small")
model = MusicgenForConditionalGeneration.from_pretrained("facebook/musicgen-small").to(device)
SECONDS=14.0; MAX_NEW_TOKENS=int(SECONDS*50)
def gen_bed(prompt, out_wav):
    inputs = proc(text=[prompt], padding=True, return_tensors="pt").to(device)
    with torch.no_grad():
        wav = model.generate(**inputs, max_new_tokens=MAX_NEW_TOKENS, do_sample=True, guidance_scale=3.0)
    sr = model.config.audio_encoder.sampling_rate
    a = wav[0,0].cpu().numpy()
    sf.write(out_wav, a, sr)
    return out_wav, sr
```
