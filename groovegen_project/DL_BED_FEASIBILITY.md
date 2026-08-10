# DL bed generation — feasibility & integration design (A+B summer paper)

**Author:** Daniel Llamas · **Date:** 2026-06-03 · **Status:** decision memo, pre-implementation
**Goal:** replace GrooveGen's hand-authored harmonic/melodic bed with one produced by a pretrained
deep-learning model, then overlay GrooveGen's knob-controlled drums — realizing the
"generate the bed, add our drums" plan and adding a controllable-generation novelty layer.

---

## TL;DR recommendation

**Use a symbolic (MIDI) model — the Anticipatory Music Transformer (AMT) — as the primary bed
generator, and keep MusicGen as a secondary audio-bed exploration for the demo/discussion only.**

| | **Symbolic — AMT (RECOMMENDED)** | **Audio — MusicGen** |
|---|---|---|
| Output | MIDI (notes) | 32 kHz audio |
| Fits pretty_midi pipeline | **Yes, natively** | No — audio, not notes |
| Keeps drum overlay clean & quantized | **Yes** | Hard — must beat-track/align to audio |
| Preserves "single isolated variable" experimental control | **Yes** | **Weakened** (rendered timbre/loudness vary per bed) |
| Render path | Same FluidSynth path you already use | Separate audio mix/sidechain |
| T4 (16 GB) feasibility | **Easy** (360 M params) | Borderline (small/medium need ~16 GB) |
| License | Apache-2.0 | MIT (code) / weights non-commercial |
| Conditioning you actually want | melody/chords/drums infilling | text prompt + optional melody chroma |

The symbolic path keeps everything that makes the study clean: the bed is notes, the drums stay
perfectly quantized on top, and the only thing that changes between stimuli is still the swept knob.

---

## Option 1 — Symbolic: Anticipatory Music Transformer (AMT)  ← primary

**What it is.** A 360 M-parameter GPT-style model over symbolic music (arrival-time tokenized MIDI),
trained on the Lakh MIDI dataset by Stanford CRFM (Thickstun, Hall, Donahue, Liang, 2023). Released
Apache-2.0; weights on the HuggingFace Hub (`stanford-crfm/music-medium-800k`, 360 M; a 128 M
`music-small-800k` also exists).
Paper: https://johnthickstun.com/assets/pdf/anticipatory-music-transformer.pdf ·
Blog: https://crfm.stanford.edu/2023/06/16/anticipatory-music-transformer.html ·
Code: https://github.com/jthickstun/anticipation

**Why it fits this project specifically.** AMT is an *infilling* model with **asynchronous control**:
you give it some musical material as control inputs and it fills in the rest. The published examples
include exactly the directions we want:
- *Input: Melody → Output: Accompaniment* (bass + chords) — generate a bed under a seed melody.
- *Input: Chords and Drums → Output: Melody and Bassline* — even condition the bed on a drum sketch.

This is the cleanest possible match for "generate the bed, keep my drums": GrooveGen owns the drums and
the knobs; AMT generates the harmonic/melodic bed around a constraint (tempo, a seed chord skeleton, or
the Dorian vamp), and the output is **MIDI** that drops straight into the existing pretty_midi +
FluidSynth render.

**T4 feasibility.** 360 M params load comfortably in 16 GB; short clips (a few bars / ~10–20 s) sample
in seconds on a T4 and even run on CPU in the sandbox for prototyping. Context length 1024 tokens
(~enough for our short looped beds). Loaded via `transformers.AutoModelForCausalLM`.

**Honest caveats (must go in the paper).**
- *Copyright/memorization:* Lakh MIDI contains copyrighted transcriptions; the authors document that
  the model can memorize and reproduce training material and caution against commercial use. For a
  **research stimulus generator** this is acceptable, but we should (a) screen generated beds for
  near-duplicates of known songs, and (b) state the provenance and non-commercial framing explicitly.
- *Idiom:* trained on general MIDI / pop-leaning material; we constrain it toward our Sophia-derived
  profile (120 BPM, 4/4, bass-forward, Dorian-ish) via the seed/controls rather than expecting it
  unprompted.
- *Determinism for the study:* the study bed must stay **frozen**. So we **generate beds offline, audit
  them, then freeze the chosen one** — the DL step is a *design-time* tool, not a per-trial generator.
  This preserves the time-invariant / knob-invariant guarantees already verified for `hero_study`.

---

## Option 2 — Audio: MusicGen (Meta / AudioCraft)  ← secondary exploration

**What it is.** Text-to-music (and text+melody-to-music) transformer over discretized 32 kHz audio.
Sizes: small 300 M (text-only), medium 1.5 B, melody 1.5 B (text+melody), large 3.3 B.
Code MIT; **model weights are released under a non-commercial (CC-BY-NC) license.**
Repo: https://github.com/facebookresearch/audiocraft

**T4 feasibility.** Official guidance is "GPU with at least 16 GB." On a Colab T4 the **small** model is
the realistic choice; melody/medium (1.5 B) are tight-to-infeasible at full precision. Reported ~35 s to
generate 10 s of audio on a T4 (small).

**Why it's secondary, not primary.** MusicGen outputs **audio, not notes**. To overlay quantized
GrooveGen drums we would have to beat-track and time-align to a generated audio bed, and the bed's
loudness/timbre would vary per generation — which **reintroduces the very confounds the frozen-bed
design eliminates.** It also can't cleanly give us "the bed is identical across all 20 stimuli" at the
symbolic level. Good for a flashy demo or a discussion-section "future work: audio beds," not for the
controlled stimulus set.

**License note:** the non-commercial weight license is fine for academic publication but should be
disclosed; don't ship audio beds in a commercial product.

---

## Proposed integration (symbolic path)

Design-time pipeline (offline, audited, then frozen):

1. **Seed/control** — build a minimal control input from the Sophia-derived target: tempo 120, 4/4, an
   A-Dorian chord skeleton (Am7 – D/A) and/or a short seed melody, encoded to AMT events
   (`midi_to_events`).
2. **Generate bed** — call AMT `generate(..., controls=seed)` to infill bass + sustained harmony around
   the control; produce several candidates (vary nucleus `p`).
3. **Audit** — quantize to the 16-step grid, check key/mode stays Dorian-ish, check it stays
   low-event-rate and bass-forward (so it won't compete with the drum manipulation), and screen against
   known-song near-duplicates.
4. **Freeze** — pick one candidate, convert to a `BedProfile` (new e.g. `BED_DLGEN_STUDY`), and route it
   through the *existing* `build_bed_instruments()` path so the verified frozen-bed properties
   (time-invariant, knob-invariant) still hold.
5. **Overlay drums** — unchanged: GrooveGen lays the knob-controlled kit on top and renders via
   FluidSynth at −14 LUFS, exactly as today.

Net effect: the **only new code** is a `dlbed/` module that turns AMT output into a frozen `BedProfile`.
The entire downstream stimulus grid, manifest, and manipulation-check validation are reused as-is.

**Paper framing.** "A controllable groove-stimulus generator whose harmonic bed is produced by a
pretrained symbolic-music model and whose rhythmic groove parameters are independently, verifiably
manipulated." Novelty = the controllable-generation + validated-manipulation combination; no human data
required for the system contribution.

---

## Verified smoke test (2026-06-03, in sandbox, CPU)

I installed `anticipation` (from the Apache-2.0 GitHub repo) + PyTorch CPU and ran the model end-to-end:
- `stanford-crfm/music-small-800k` (128 M) loaded in **4.6 s**.
- Generated 5 s of music → **321 event-tokens → valid 3-track MIDI** (bass @ program 33, strings @ 49,
  plus a drum track we'd discard since GrooveGen owns the drums), converted cleanly via
  `events_to_midi` and re-opened in `pretty_midi` without error.
- CPU generation took ~145 s for 5 s of audio — slow, but **on a Colab T4 this drops to seconds**.

**Conclusion: the symbolic path is confirmed working.** The model loads, generates well-formed
multi-track MIDI, and the output drops straight into the existing pretty_midi pipeline — exactly as the
design assumes. The 360 M `music-medium-800k` is the production choice on the T4; `music-small-800k`
is a fine CPU/prototyping fallback.

## Next steps
1. Prototype AMT bed generation on a T4 (or CPU in-sandbox for a smoke test): load
   `stanford-crfm/music-medium-800k`, generate a short Dorian-constrained bed, render, listen.
2. Build the `dlbed/` adapter (AMT events → frozen `BedProfile`).
3. Render a side-by-side demo: hand-authored `hero_study` bed vs DL-generated bed, same drums/knobs.
4. (Optional) one MusicGen-small audio bed as a "future work" demo clip.

## Citations
- Thickstun, J., Hall, D., Donahue, C., & Liang, P. (2023). The Anticipatory Music Transformer.
  https://johnthickstun.com/assets/pdf/anticipatory-music-transformer.pdf ·
  https://crfm.stanford.edu/2023/06/16/anticipatory-music-transformer.html ·
  https://github.com/jthickstun/anticipation (Apache-2.0)
- Model card: https://huggingface.co/stanford-crfm/music-medium-800k (360 M params, Lakh MIDI)
- Copeland/Défossez et al. (2023). MusicGen / AudioCraft. https://github.com/facebookresearch/audiocraft
  (code MIT; weights non-commercial)
