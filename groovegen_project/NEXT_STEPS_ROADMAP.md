# GrooveGen — Next-Steps Roadmap
### Realism, Groove Control, and a Calming / Emotion-Regulation Mode
*Prepared June 25, 2026*

---

## 0. The central design tension

You stated two generative goals:

1. **Groove induction** with *fine-grained, reproducible control* over drum-beat features (the research instrument).
2. **MusicGen-level realism**, eventually.
3. **A calming / relaxing mode** that down-regulates the sympathetic nervous system (SNS) and supports emotion regulation.

Goals (1) and (2) pull in **opposite directions** with today's technology, and understanding why is the foundation of every decision below.

### Why MusicGen alone breaks your study

Per the [MusicGen paper](https://ai.honu.io/papers/musicgen/), MusicGen is a **single transformer LM over compressed (EnCodec-style) audio tokens**, conditioned on only two things:

- **Text** (e.g. "lofi slow bpm electro chill", "drum and bass beat with intense percussions"), and
- a **chroma-based melody** contour.

It offers **no separate, continuous, trustworthy control** over tempo, syncopation, swing, or drum density — the exact five knobs that constitute your manipulation. You can *mention* "syncopated drums" in a prompt, but you cannot move syncopation from Witek-level 0 → 81 and guarantee nothing else changed. The paper itself only claims control via **text** and **melody conditioning** — nothing about isolated rhythmic parameters or stem-level steering.

**Conclusion:** Realism and parametric groove control are, today, a real tradeoff. Raw text-to-audio destroys the clean causal attribution your study needs.

---

## 1. The resolution: keep the symbolic brain, upgrade the body

Your symbolic MIDI architecture is *correct for the science* — it gives exact, reproducible, measurable knob control. The realism gap is **not** in generation; it's in **rendering** (FluidSynth + General MIDI = dated sound). So the strategy is to **swap the renderer, not the generator**, and keep groove defined/measured at the symbolic layer where the knobs live.

**Architecture principle (binding):**
> Layer 1 = musical content + groove character (symbolic, fully knob-controlled and measurable).
> Layer 2 = realism (neural or sample-based rendering) applied *on top*, never replacing the controlled symbolic stream.
> Groove features are always re-measured from the final audio to confirm control survived.

### Phase 1 — Better rendering (low risk, weeks)
- Keep symbolic generation exactly as-is.
- Replace GM soundfonts with high-quality sampled instruments (premium SF2 / SFZ libraries; consider per-instrument sample libraries for drums, bass, keys).
- Add **per-stem mixing** (separate kick/snare/hat/bass/chords busses). The Sophia analysis already validated **percussive-ratio** (β≈+4.66) and **bass-energy** (β≈+2.97) as real danceability actuators, so a proper mix bus *directly serves the science*, not just aesthetics.
- Outcome: large realism jump, **zero** loss of control.

### Phase 2 — Neural audio rendering of YOUR MIDI (the key unlock)
Goal: realistic timbre while your symbolic groove still dictates the rhythm. Options, roughly in order of control-preservation:
- **(a) MIDI-to-audio neural synthesis / neural sampler** — renders your exact note/timing stream with realistic instrument audio.
- **(b) MusicGen-Melody conditioned on your stems** — feed your controlled groove as the conditioning signal so the model supplies timbre while your rhythm leads. Control is partial: prompt + melody only.
- **(c) Audio-diffusion with time-varying control** — e.g. [Music ControlNet (CMU, 2024)](https://gclef-cmu.org/static/pdfs/2024musiccontrolnet.pdf) demonstrates imposing time-varying melody / dynamics / rhythm controls on audio diffusion; [Controllable Music Production with Diffusion + Guidance Gradients](https://ar5iv.labs.arxiv.org/html/2311.00613) is a related direction. This is the most promising long-term reconciliation of realism + control and warrants a **feasibility spike** before committing.
- Recommendation: prototype (a) first (most control), evaluate (c) as the research frontier.

### Phase 3 — Validate that control survived (non-negotiable)
- Re-extract groove features (density, syncopation, swing, microtiming, tempo) **from the rendered audio**.
- Confirm each knob still moves its target feature **monotonically**.
- You already have the manipulation-check infrastructure from the stimulus grid — reuse it.

---

## 2. Robustness improvements (independent of realism)

- **Move the predictive/control model onto symbolic features.** The 2026-06-02 reassessment found the features that actually predict groove (Senn's Event_Density, Syncopation, Swing_16, Tempo, Tempo_Instability) live in the **symbolic/MIDI layer**, not in commercial-audio descriptors — audio-extracted versions did not transfer (external CV R² ≈ 0.035 ± 0.069, ~0). Build the generator's control model on symbolic features computed directly from your own MIDI.
- **Primary corpora:** Senn 2018 (Lucerne Groove Research Library, human-rated groove, 11 published symbolic predictors) as primary; supplement with Janata 2012 and the Groove MIDI Dataset (GMD) to grow *n*.
- **Actually run the familiarity / trait moderators.** You have the columns (eBMRQ Sensory-Motor, Music_importance, Active_musician, Musical_training). Senn 2018 found **style-bias R²=.123 and familiarity η²=.051 dominate syncopation's R²=.010** — so personalization is not a nicety, it's the largest lever. Validate it in your own data.
- **Per-participant genre personalization** is already built (genre layer) — keep it; it harnesses the dominant familiarity effect rather than fighting it.

---

## 3. Calming / SNS-down-regulation mode

**This is much better-supported physiologically than the groove literature** — and it slots into your existing architecture cleanly, because it's *the same knobs, inverted*. Groove mode maximizes drive; calming mode minimizes it.

### Evidence-based design targets

| Parameter | Calming setting | Evidence |
|---|---|---|
| **Tempo** | Slow (~60 BPM, master lever) | Slow music lowers HR/BP, raises HRV/parasympathetic ([Cureus 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9417331/)); 60 BPM in a slowing sequence gave greatest vagal shift ([Bretherton et al. 2019](https://journals.sagepub.com/doi/10.1177/2059204319858281)) |
| **Phrase period** | ~10 s arcs (≈6 breaths/min, 0.1 Hz) | Phrases at a 10-s period entrain Mayer waves & maximize baroreflex sensitivity (9.5→11.5 ms/mmHg) ([Bernardi, Neth Heart J 2012](https://pmc.ncbi.nlm.nih.gov/articles/PMC3547422/); [BMJ 2001](https://www.semanticscholar.org/paper/f7835a4b3c93773448e32943023897d94b388341)) |
| **Dynamics** | Minimal; NO crescendos | Crescendos drive vasoconstriction & BP up ([McGill / Bernardi](https://www.psych.mcgill.ca/labs/mcl/pdf/nicolo6.pdf)) |
| **Event density** | Low | Fewer onsets → lower arousal |
| **Syncopation / swing** | ~0 / off | Removes the "urge-to-move" drive |
| **Harmony / timbre** | Consonant, legato, warm, soft | Sedative music = slow tempo, legato, minimal dynamic contrast ([ANS review, PMC3011183](https://pmc.ncbi.nlm.nih.gov/articles/PMC3011183/)) |
| **Loudness** | Low SPL | Lower intensity → less sympathetic activation |

### Caveats to respect
- Effects are **real but inconsistent across individuals** ([ANS review](https://pmc.ncbi.nlm.nih.gov/articles/PMC3011183/)); response magnitude is partly predicted by resting autonomic state ([Bretherton 2019](https://journals.sagepub.com/doi/10.1177/2059204319858281)).
- **Familiarity/preference moderates everything** — a 2024 HRV meta-analysis found participant-selected music outperforms standardized music ([Frontiers Psychology 2024](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2026.1750786/full)). Keep genre/familiarity personalization in calming mode too.
- HRV-direction reporting in the literature is inconsistent (measure/units vary) — pre-register your exact HRV metric (e.g. HFnu, RMSSD).

### The closed-loop opportunity (your biofeedback wheelhouse)
Calming mode is the natural target for a **closed-loop biofeedback system**: read PPG / GSR / respiration, and have the generator gradually slow tempo and lengthen phrase arcs toward the 6/min (0.1 Hz) resonance until sympathetic markers (e.g. LF/HF, SCL, respiration rate) drop. This is a genuinely novel contribution and unifies both modes under one control framework:

> **One groove instrument, two directions.** The same parametric engine drives *up* (groove/urge-to-move) or *down* (calming/parasympathetic). The dependent variable flips from "wanting to move" to "autonomic down-regulation," but the control architecture is identical.

---

## 4. Suggested sequencing

1. **Now:** Phase-1 rendering upgrade (soundfonts + per-stem mix) — biggest realism-per-effort.
2. **Next:** Refactor the control/predictive model onto symbolic features (Senn/GMD); run the familiarity moderator on your own data.
3. **Parallel, low-cost:** Build calming mode as an inverted preset of the existing knobs + 10-s phrase scaffolding. It needs no new ML.
4. **Feasibility spike:** Phase-2 neural rendering — prototype MIDI-to-audio and/or Music-ControlNet-style time-varying control; validate that knobs survive (Phase 3).
5. **Longer-term research arc:** closed-loop biofeedback unifying groove-up and calming-down modes.

---

*Sources: MusicGen paper (ai.honu.io/papers/musicgen); Bernardi et al. BMJ 2001 / Neth Heart J 2012; Bretherton et al. 2019; Cureus 2022; Senn et al. 2018 (PLOS ONE, 10.1371/journal.pone.0199604); Music ControlNet (CMU 2024); GrooveGen reassessment 2026-06-02 and Sophia analysis (this project).*
