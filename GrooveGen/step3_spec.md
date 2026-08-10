# STEP 3 SPEC — Two-timescale architecture + latency analysis (for TEI 2027 paper)

## Purpose
Write a rigorous architecture specification document for GrooveGen framed as the generative engine inside a closed-loop Brain-Body Computer Interface (BBCI). This is destined for the TEI 2027 system paper ("Groove_model", due July 31, 2026). Output = a clean markdown doc the user can adapt into LaTeX/Overleaf.

## The core idea to formalize: TWO TIMESCALES
GrooveGen separates generation into two loops running at very different rates:
- **SLOW loop (offline / seconds-to-minutes):** neural BED generation via MusicGen. Expensive, GPU-bound, ~non-real-time. Produces harmonic/timbral backdrop. Pre-generated into a BED BANK; swapped via beat-matched equal-power crossfade.
- **FAST loop (online / per-bar, <~tens of ms symbolic + synthesis):** symbolic DRUM/groove generation via pretty_midi + FluidSynth. Cheap, controllable, real-time. The EVENT DENSITY knob (primary, monotonic, closed-loop-safe) is modulated here every bar. Backbeat locked (entrainment anchor); syncopation bounded spice; microtiming cosmetic.

This mirrors motor control / predictive-coding hierarchies: a slow "plan" layer and a fast "execution" layer. It is what makes real-time biofeedback feasible — you never wait on MusicGen inside the control loop.

## The closed loop (BBCI context — from the user's dissertation)
Physiology (PPG, GSR, Respiration — 3 signals only) → feature extraction (HR/HRV from PPG, SCR/SCL from GSR, resp rate) → **Proportional-Derivative (PD) controller** → target EVENT DENSITY (and secondarily backbeat salience) → fast symbolic loop updates the groove per bar → music + haptic feedback → entrains sensorimotor-autonomic loops → changes physiology. Application domains: emotion regulation + motor learning (throwing-task experiment, football to target). Explain WHY density is the controlled variable (monotonic → PD-stable; syncopation's inverted-U would be a control hazard — cite the Step 0 decision).

## Sections the doc MUST contain
1. **Abstract / one-paragraph system summary.**
2. **System overview diagram (describe in text + an ASCII/mermaid block):** the two loops + the closed physiological loop. Provide a mermaid diagram.
3. **Slow loop spec:** MusicGen bed generation, bed-bank strategy, crossfade (equal-power, bar-aligned), why offline.
4. **Fast loop spec:** per-bar symbolic groove, GrooveParams knobs, event-density random-walk placeholder → replaced by controller target, backbeat lock rationale, seed=base+bar_idx reproducibility.
5. **Control layer:** PD control law (give the actual equation: u(t)=Kp·e(t)+Kd·de/dt, mapping physiological error e = target_arousal − measured_arousal to Δdensity), why PD not full PID (drift/steady-state considerations), saturation/clamping (density band, syncopation clamp 0.20–0.40), stability argument leaning on density monotonicity.
6. **Latency analysis (the technical heart — MUST be quantitative):**
   - Budget the end-to-end loop: physiological sampling window → feature extraction → controller update → symbolic bar build → FluidSynth synthesis → audio output → haptic actuation.
   - Give REALISTIC per-stage latency estimates with justification (e.g. PPG needs a few-second window for HRV; GSR/SCR slow ~1-3s; symbolic bar build sub-ms to ~ms; FluidSynth render of one bar; audio buffer). 
   - KEY INSIGHT: the control update rate is BAR-QUANTIZED (one decision per bar ≈ 2–2.5 s at 96–120 BPM), which naturally matches the slow autonomic response timescale (HRV, SCR rise times are seconds) — so bar-rate control is not a limitation, it's WELL-MATCHED to the plant's dynamics. Make this argument explicitly and rigorously; it is a strong paper point.
   - Contrast with the naive "regenerate the whole neural track per update" approach and show the two-timescale design's latency advantage with a small table.
7. **Novelty / optimization contributions:** continuous non-repetitive generation, bar-rate controllability, timescale separation, entrainment-preserving anchor. Position vs prior generative-music and biofeedback-music systems briefly.
8. **Limitations & future work:** deterministic _density_steps onset quantization (same-density bars share onsets; velocity humanization workaround), CPU vs GPU deployment, haptic actuation latency unmeasured, need for user-in-the-loop validation, IRB (~June 2026).
9. **A latency budget TABLE** and a **timescale comparison TABLE**.

## Grounding / citations
Use the Step 0 literature file for the density/syncopation/control-hazard argument: /home/user/workspace/symbolic_analysis/groove_knob_literature.md (has full citations w/ URLs — reuse them). Key claims to cite inline with markdown links: density monotonic (Madison 2011), syncopation inverted-U control hazard (Witek 2014), tempo/onset-rate → autonomic (Gomez & Danuser 2007), syncopation degrades sensorimotor sync (JoCN 2020). Also may do 2-4 targeted web searches for: real-time biofeedback music systems latency, MusicGen inference latency/real-time factor, PPG HRV window length requirements, GSR/SCR latency — to ground the latency numbers. Cite everything with real URLs.

## Style
- Markdown, clear headers, tables, one mermaid diagram + one ASCII fallback.
- Technical, paper-ready tone (the user is a PhD writing for TEI). Precise, quantitative, honest about assumptions.
- Every latency number must state its basis (measured / literature / estimated-with-reason).
- Inline citations with real URLs.

## Output
Write to /home/user/workspace/groovegen_project/ARCHITECTURE_TWO_TIMESCALE.md
Report back: section list, the latency budget table contents, and any numbers you had to estimate vs cite.
