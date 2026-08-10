# Hybrid Architecture Options — GrooveGen Bed/Drum Decomposition

## Recommendation (read this first)

**Go symbolic for the bed. Option 1 (symbolic melody+harmony bed via soundfont + existing FluidSynth drum engine) is the right call, with Option 4 (fully symbolic, single renderer) as the natural end-state if time allows.** Kill Option 2 (MusicGen drum-loop bank) outright — it reintroduces the exact rhythm/percussion entanglement problem this whole investigation exists to escape, just with extra plumbing. Option 3 (better neural bed model) is a legitimate *future-work* item, not a fix for the current paper — the "better" models that actually solve stem separation (MusicGen-Stem, STAGE) are research code, not deployable Colab pipelines, so pursuing them now trades a known, solvable problem for an unknown, possibly unsolvable one on a deadline that has already passed once.

Ranking for **this system, this paper, right now**: **1 ≈ 4 > 3 (future work only) >> 2 (do not do)**.

The research-framing angle (item 5) is not a tiebreaker footnote — it's the actual justification. For a TEI system/method paper whose contribution is *closed-loop per-bar drum-density control*, symbolic beds are not a compromise, they are the methodologically correct choice: they make the confound-free claim ("genre is carried by the harmonic bed; the controller only touches drum density") verifiable by construction rather than by assertion, and they make the whole pipeline exactly reproducible from the paper's description. Chasing neural-audio realism for the bed spends effort on a dimension reviewers will not evaluate you on (this is not a generative-audio-quality paper) while directly risking the dimension they will evaluate you on (control fidelity, reproducibility, internal validity).

---

## Option 1: Symbolic bed (MIDI, soundfont-rendered) + existing synthetic drum engine

**What it is:** Compose/generate melody+harmony+bass as MIDI (hand-written, rule-based, or a symbolic model like Magenta/MMM), render via FluidSynth soundfont, mix with the existing per-bar-controllable synthetic drum track. Drums and bed are separate audio streams by construction — no separation step ever needed.

- **Control fidelity (per-bar):** Perfect. Nothing changes here — this is exactly the current drum engine's control path, untouched.
- **Genre authenticity:** Fully in your hands. Genre lives in chord voicings, rhythm-of-the-bed (montuno/clave figures for salsa, ii-V-I motion for jazz-inflected r&b, etc.), and instrumentation choice (soundfont patch selection). This requires real musical knowledge to encode (or a symbolic generator conditioned on genre), but it is achievable and — crucially — auditable: you can point to the MIDI and show *why* it sounds like salsa.
- **Audio quality ceiling:** Bounded by soundfont quality. General-purpose soundfonts (FluidR3, or a curated multi-sample library) sound clearly synthetic/General-MIDI-ish compared to MusicGen's neural timbre. This is the real cost of this option and should be stated plainly in the paper as a limitation, not hidden.
- **Colab feasibility:** Trivial. FluidSynth rendering is CPU-only, near-instant, no GPU/VRAM contention with anything else, no model download flakiness, no session-limit risk.
- **Reproducibility for research:** Best of all options. MIDI is deterministic given a seed/ruleset; the soundfont is a fixed file; the whole pipeline can be fully specified in the paper's methods section and re-run bit-for-bit by anyone. This is a major, underrated win for a system/method paper.
- **Implementation effort vs. existing codebase:** Low-to-moderate. You already have FluidSynth wired up for drums, tempo-locking/beat-grid machinery, and presumably a bed-library abstraction the controller reads from — this option *reuses* nearly all of that infrastructure and just swaps the bed's audio source from "MusicGen render" to "MIDI render." The main new work is composing or generating decent-sounding MIDI beds per genre (a few hours to a couple of days depending on how much you hand-write vs. automate).
- **Does it collapse the whole problem?** Yes — this is the key insight. The rhythm/percussion entanglement problem MusicGen has is a problem specifically because MusicGen outputs an inseparable audio mixture. A symbolic bed never produces a mixture; there is nothing to separate. This isn't a clever workaround, it's a change of representation that makes the failure mode structurally impossible.
- **What's lost:** Timbral realism and "production feel" — the sheen, texture, and human micro-variation that made MusicGen's audio attractive in the first place. For a listener doing a close A/B against a Spotify track, symbolic-soundfont will sound noticeably more artificial. For a controlled psychophysiology experiment (heart-rate tracking) where the point is drum density as a stimulus variable, this cost is likely small relative to the reproducibility and control gains.

## Option 2: Pre-rendered MusicGen drum-loop bank, crossfaded by density

**What it is:** Generate a small set of MusicGen drum loops per genre at discrete density levels (e.g., 3-4 tiers spanning density 3-20), then have the controller crossfade/switch between them in real time to approximate the requested per-bar density.

- **Control fidelity (per-bar):** Fundamentally degraded. The controller currently sets an *integer density 3-20 per bar*; a loop bank gives you a handful of discrete points and crossfades between them, which is qualitatively different from true per-bar synthesis. Crossfading between loops of different densities also risks phase/tempo mismatches and audible "seams" unless the loops are extremely tightly tempo-locked and beat-gridded — solvable, but adds a whole layer of engineering to reconstruct control fidelity you already have for free with the synthetic engine.
- **Genre authenticity:** Better drum *timbre* per genre than FluidSynth synth drums, in principle — this is the option's only real selling point.
- **Audio quality ceiling:** Higher timbral realism for drums specifically than synthetic drums. But this directly reintroduces the paper's own finding: MusicGen drum content is percussion-*and*-rhythm entangled, meaning the "melodic/genre" character the user wants confined to the bed will leak into these drum loops too (a MusicGen salsa drum loop will carry clave/tumbao phrasing baked in, not a neutral density-only percussion track). That undermines the hard requirement that genre identity lives in the bed, not the drums.
- **Colab feasibility:** Fine at generation time (offline, one-time cost to build the bank) but adds real-time crossfade/looping logic that has to be built and debugged from scratch.
- **Reproducibility for research:** Weak. The specific loops chosen, how crossfades are timed, and how well the density number maps to actual perceived density all become extra undocumented/hard-to-specify parameters. A reviewer asking "how exactly does density value map to audio?" gets a much messier answer than with a synthesis engine that has a legible parameter → output relationship.
- **Implementation effort vs. existing codebase:** Highest of all four generative options. You'd be throwing away the existing FluidSynth drum engine's clean parametric control and rebuilding a loop-bank-plus-crossfade system, which is genuinely more engineering than any other option here, for a benefit (drum timbre) that is secondary to the paper's actual contribution.
- **Verdict:** This option tries to have it both ways and gets the worst of both: it doesn't sound as controllable as synthesis, and it doesn't actually solve the entanglement problem for the drums themselves — it just relocates it from "beds" to "drum loops." Not recommended.

## Option 3: Better neural bed model (drumless-capable / stem model) + synthetic drums

**What it is:** Keep the current two-timescale architecture (neural bed + synthetic drums) but swap MusicGen-small/full for something explicitly designed to emit a drums-free stem — e.g., MusicGen-Stem (Meta, multi-stem autoregressive MusicGen variant) or STAGE (accompaniment-generation model that can condition on a metronome/beat track and output an isolated non-drum stem).

- **Control fidelity (per-bar):** Same as current architecture — drums stay on the existing synthetic engine, so per-bar control is unaffected. The bed itself is still generated once per segment (slow timescale), so this doesn't change control fidelity, only bed quality.
- **Genre authenticity:** Potentially the best of the neural options if the stem model actually holds up — melody/harmony from a real learned audio model, cleanly separated from drums by construction (not post-hoc separation, so no HPSS/Demucs failure mode).
- **Audio quality ceiling:** Highest ceiling of any option — genuine neural-audio timbre for the bed.
- **Colab feasibility:** Real risk. MusicGen-Stem and STAGE are recent (2025) research releases, not production-hardened HF pipelines like `facebook/musicgen-small`. Expect: unclear/absent public weights, custom inference code, dependency conflicts, and non-trivial VRAM/setup work on a T4 with no guarantee of success. This is exactly the kind of "one more model swap might fix it" trap that already cost time on HPSS/Demucs.
- **Reproducibility for research:** Moderate at best. Depends heavily on whether the chosen model has stable, citable, publicly released weights and inference code. If it's a research checkpoint that could be pulled or changed, that's a reproducibility liability for a paper.
- **Implementation effort vs. existing codebase:** Moderate-to-high and *uncertain* — the two-timescale bed/drum split, tempo-locking, and beat-grid machinery all carry over unchanged (this is the option's appeal), but the actual model integration is unproven and could easily consume the remaining schedule without a guaranteed payoff, unlike Option 1 which is guaranteed to work because it sidesteps the hard problem entirely.
- **Verdict:** Legitimate **future work** to mention in the paper's discussion/limitations section ("a learned stem-aware bed generator could recover production realism without sacrificing separability — we leave this to future work"), but not a responsible bet for the current deliverable given the deadline has already slipped once and the models are immature.

## Option 4: Fully symbolic (bed + drums both symbolic, single renderer)

**What it is:** Extend Option 1 by also representing drums symbolically (MIDI drum track) instead of using FluidSynth's existing synthetic-drum-engine-as-is — i.e., one unified symbolic representation and one soundfont render pass for the whole mix, with the controller directly writing MIDI drum events per bar.

- **Control fidelity (per-bar):** Perfect and arguably *cleaner* than Option 1 — a single symbolic representation for the whole piece means density control, bed, and drums all live in the same data model (MIDI), which simplifies analysis, logging, and any post-hoc verification the paper needs (e.g., "here is the exact MIDI density trace we compared to heart rate").
- **Genre authenticity:** Same as Option 1 — fully controlled by the bed's harmonic/rhythmic content.
- **Audio quality ceiling:** Same ceiling as Option 1 (soundfont-limited), possibly marginally more coherent since bed and drums are rendered by the same engine/soundfont pass rather than two separately-sourced audio streams being mixed — reduces any risk of level/timbre mismatch between "synthetic-drum-engine audio" and "soundfont bed audio."
- **Colab feasibility:** Trivial, same as Option 1.
- **Reproducibility for research:** Best of all options, marginally better than Option 1 — one file format, one renderer, no cross-engine mixing step to document.
- **Implementation effort vs. existing codebase:** This is the one place it costs more than Option 1: it likely means re-plumbing the *existing* FluidSynth synthetic drum engine's control interface to emit MIDI note events instead of (or in addition to) whatever its current audio-rendering path is, which is real, if bounded, refactoring work. If the existing drum engine already has a MIDI-adjacent internal representation, this is cheap; if it's tightly coupled to direct audio synthesis, this is a non-trivial rewrite for a benefit (representational unification) that's more about elegance/reproducibility than new capability.
- **Verdict:** The right end-state, but only worth the extra refactor if there's schedule slack after Option 1 ships. Don't let it block getting Option 1 working first.

---

## The research-framing argument (Option 5), argued both ways

**Case FOR symbolic strengthening the paper:**
A TEI system/method paper is judged on the soundness, novelty, and *reproducibility* of the control method — not on whether the demo sounds like a Spotify track. Symbolic representation makes the paper's central causal claim ("controller manipulates drum density; genre-bearing content is untouched") mechanically true and independently verifiable, rather than something the authors assert and hope holds up to scrutiny about cross-contamination (exactly the entanglement problem this investigation surfaced). It also means a reviewer or replicator can regenerate the exact stimulus from the paper's description alone — no model weights, no GPU, no stochastic neural sampling to control for. This is a genuinely stronger paper on the axis TEI actually reviews on: rigor of the interaction method.

**Case AGAINST (steelman the other side):**
Reviewers and readers do perceive audio quality, and "sounds like a MIDI file" can trigger an unconscious quality discount that makes the whole system look like a toy, regardless of how sound the control method is — first impressions matter even in venues that claim to value method over polish, and a demo video with thin GM-soundfont timbre may undersell a genuinely novel contribution. Neural-audio timbre also better resembles the kind of music a real listener's heart-rate response was presumably calibrated against in prior literature (real recorded music), so there's a construct-validity argument that ecological realism of the *audio stimulus* matters for a physiological-response study, not just the control signal.

**Resolution:** The construct-validity concern is real but is about the *stimulus*, not the *paper's contribution* — and it can be substantially mitigated with a well-chosen, genre-appropriate soundfont/sample library (not default GM patches) at low cost, without touching the control architecture at all. The "toy" perception risk is a presentation problem (pick good samples, mix well, maybe add light convolution reverb/saturation for polish) rather than an architecture problem. On balance, symbolic wins for this paper: it removes a real methodological vulnerability (unverifiable genre/drum separation) in exchange for a cosmetic risk (thinner timbre) that is manageable with production polish and doesn't require gambling on immature research models under a deadline that has already slipped once.

---

## Summary comparison table

| | Control fidelity | Genre authenticity | Audio ceiling | Colab feasibility | Reproducibility | Effort vs. existing code |
|---|---|---|---|---|---|---|
| 1. Symbolic bed + existing synth drums | Perfect | High (fully authored) | Soundfont-limited | Trivial | Best-tier | Low-moderate, reuses most infra |
| 2. MusicGen drum-loop bank + crossfade | Degraded (discrete, seams) | Drums leak genre (bad) | Higher drum timbre only | Moderate | Weak | Highest — new subsystem, discards clean drum control |
| 3. Better neural bed (stem model) + synth drums | Perfect (unchanged) | Potentially best (if it works) | Highest (if it works) | Risky/unproven | Moderate, model-dependent | Moderate-high, uncertain payoff |
| 4. Fully symbolic (one renderer) | Perfect, most legible | High | Soundfont-limited | Trivial | Best overall | Moderate — refactors drum engine to MIDI |

**Bottom line:** Ship Option 1 now — it reuses the tempo-locking/beat-grid/bed-library/FluidSynth-drum infrastructure you already have, eliminates the entanglement failure mode by construction, and is the most defensible architecture for a control-focused TEI paper. Treat Option 4 as a cheap follow-on refactor if time permits. Note Option 3 in the paper as future work rather than attempting it now. Do not pursue Option 2.
