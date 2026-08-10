# Position B Roadmap — Real-Time Generative Synthesis (Fall Semester Plan)

**Goal (Position B):** a system that GENERATES novel audio LIVE, conditioned on a target musical state (genre, exact BPM, rhythmic density, ideally arousal/valence), stays tempo-stable, and can be continued/spliced seamlessly — so the generative model itself is the timing-competent engine, not a wobbly bed source that has to be corrected after the fact.

**Status:** deferred (not for TEI). This is the fall research arc. Framing below is deliberately critical — I flag what is a plug-in fix vs. genuine unproven research engineering, because betting the semester on the wrong assumption is the real risk.

---

## The single most important framing decision

The literature splits cleanly into two philosophies, and **you should NOT try to make the neural model the timing authority.** Every working closed-loop music system found in the research (AffectMachine-Pop, HEARTBEATS) reaches exact tempo the same way: **keep the clock symbolic, commit changes at bar boundaries, and treat the neural audio model as a timbral generator that gets corrected into alignment** — never ask the audio model to self-discipline to a grid ([position_b_techniques_research.md]). This is exactly GrooveGen's current architecture (symbolic drums = clock, MusicGen = bed). 

**Implication — this is the critical insight:** "Position B" as *"the neural model generates perfectly tempo-locked audio live"* is the hard, risky, maybe-unnecessary version. The *achievable and defensible* Position B is: **the neural model generates live, and a thin deterministic correction layer + symbolic clock guarantee the grid.** Don't over-scope to the first when the second is what actually ships and what the field actually does.

---

## Three candidate paths (ranked by realism, most critical view)

### Path 1 — Upgrade the generator: MusiConGen + Rubber Band correction (LOW risk, HIGH confidence)
**This is the path I'd actually start with.** It's an incremental, reproducible upgrade of your current stack, not a rewrite.

- **MusiConGen** ([arXiv:2407.15060](https://arxiv.org/html/2407.15060v1), [GitHub](https://github.com/YatingMusic/MusiConGen)): a fine-tuned MusicGen that ADDS explicit symbolic **BPM + beat/downbeat conditioning** (design tolerance ~70 ms), open MIT code, **finetunable on consumer GPUs** (trained on 4×RTX-3090), inference >12 GB VRAM. It reduces tempo drift *at the source* instead of correcting it after. This is the closest, lowest-friction upgrade from `musicgen-small`.
- **Rubber Band time-stretch** ([technical docs](https://breakfastquay.com/rubberband/technical.html)): the ONLY technique in the whole survey that gives *deterministic, exact* tempo correction — compute stretch ratio to the known target BPM, apply it. Because MusiConGen's residual drift would be small, the stretch ratio is near-1, so artifacts are minimal. Mature, CPU-cheap, real-time-capable. This is the highest-confidence fix found.
- **LoopGen** ([arXiv:2504.04466](https://www.arxiv.org/pdf/2504.04466.pdf)): training-free, bar/beat-aware circular-padding inference for seamless indefinite loop extension — solves "extend a bed without seams" independent of tempo-lock.

**Verdict:** MusiConGen (drift reduction at source) + Rubber Band (deterministic exact lock) + LoopGen (seamless extension) is a *combination* that plausibly delivers tempo-locked beds without a real-time streaming model at all. **Critical caveat:** none of these makes generation *faster than real-time* — they fix the tempo/seam problem, not the speed problem. If "live" means "generate offline, adapt live" (Position C++), this path is enough. If "live" strictly means "synthesize new audio within the loop in real time," Path 1 alone doesn't get there.

### Path 2 — Adopt a true real-time architecture: Magenta RT (open) / Lyria RT (closed) (MEDIUM risk)
This is the only architecture class that is *genuinely* live-generative.

- **Magenta RealTime** ([arXiv:2508.04651](https://arxiv.org/pdf/2508.04651.pdf)): open-weights (800M), a real **chunked streaming/continuation** architecture — each 2 s chunk conditions on the previous 10 s + a style embedding; RTF ~1.6 on free-tier Colab TPU. Continuous style steering via weighted prompt blends. **This is the most architecturally aligned with your real-time need.** Weaknesses: **no confirmed hard-BPM control** in the open model, and a 10 s memory window limits long-term structure. On-device inference "coming soon."
- **Lyria RealTime** ([Live Music API docs](https://ai.google.dev/api/live_music.md.txt)): same architecture family, but with an **explicit numeric `bpm` parameter (60–200)** plus density/brightness/key sliders over a WebSocket. Best-in-class control surface. **Fatal for a PhD paper: fully closed, API-only, no weights, no finetuning, tempo changes require a hard `reset_context()` (not seamless).** A reproducibility and licensing risk you should not build a dissertation chapter on.

**Verdict:** Magenta RT is the right *open* bet if you want true live generation; the research contribution would be **adding explicit BPM/beat control to Magenta RT** (which it lacks) — a real, publishable NIME/ISMIR-scale contribution. Lyria RT is useful only as a *prototype/demo/aspiration reference*, never as the shipped engine. **Critical caveat:** adding hard tempo control to a block-autoregressive model is genuine research, not integration — scope it as a semester project, not a two-week task.

### Path 3 — Fast open batch generator + inference-time control: ACE-Step + DITTO-2 (HIGH risk, most novel)
- **ACE-Step** ([GitHub](https://github.com/ace-step/ACE-Step-1.5)): open weights, explicit **BPM/key/time-signature metadata control**, extreme speed (4-min song in ~20 s on A100; runs on 4 GB VRAM). But it is a **batch full-song generator, not a low-latency streaming instrument** — no proven 2 s-chunk live path. A 2026 streaming-distillation follow-up ([arXiv:2606.24307](https://arxiv.org/html/2606.24307v1)) suggests chunked real-time is achievable on this base, but that's bleeding-edge.
- **DITTO-2** ([arXiv:2405.20289](https://arxiv.org/abs/2405.20289)): best *training-free* technique to layer continuous control (intensity, structure, tempo-like targets) onto any diffusion backbone via inference-time optimization; 10–20× faster than DITTO. **Critical caveat:** no official public code found for DITTO/DITTO-2, and DITTO alone is >10× slower than real-time. Adopting this is unproven research engineering, not a plug-in.

**Verdict:** the most novel and the most likely to consume the whole semester with nothing shippable. Interesting for a PhD *if* the intellectual contribution IS the control technique. Do not start here.

---

## What LoRA actually buys you (revisiting your question, critically)

LoRA on MusicGen/MusiConGen gives you **stylistic fidelity** — "make generations sit closer to this user's music" (the natural sequel to the 12-song idea: 12 songs → prompt now, whole library → LoRA later). It does **NOT** give you tempo-lock, streaming, or real-time speed — those are *architectural*, not style-fidelity, problems. So: **LoRA is a personalization tool, not the Position-B unlock.** If a reviewer hears "LoRA gets us to real-time generative synthesis," they'll push back correctly. Frame LoRA as personalization future-work; frame Position B as an architecture/technique problem (Paths 1–2).

---

## Recommended fall sequence (realistic, staged, de-risked)

1. **Weeks 1–3 — Path 1 baseline.** Stand up MusiConGen, feed it your committed BPMs, measure residual drift vs. current MusicGen (reuse today's jitter/grid-error diagnostic). Add Rubber Band lock + LoopGen extension. **Deliverable:** tempo-locked personalized beds, offline. This alone likely fixes GrooveGen's audio quality permanently and is a solid NIME systems result.
2. **Weeks 4–7 — evaluate the speed gap.** Decide honestly whether "generate offline + adapt live" (Path 1) already satisfies your dissertation's "live generative" claim. If yes, you're done — write it up. If you truly need in-loop synthesis, proceed.
3. **Weeks 8–12 — Path 2 research.** Prototype Magenta RT in the loop; scope the contribution as "adding explicit BPM/beat conditioning to a real-time block-AR model." Use Lyria RT only as a comparison/reference for what the control surface should feel like.
4. **Ongoing — LoRA personalization** on top of whichever generator wins, as the 12-song → full-library evolution.

**Compute reality check:** Paths 1 finetuning and 2 prototyping both fit consumer/prosumer GPUs (RTX 3090/4090, 24 GB) or Colab. Only DITTO-2-style inference optimization and full ACE-Step training push toward A100. Budget Colab Pro / lab GPU accordingly; none of this needs a cluster.

## Bottom line
Start with Path 1 (MusiConGen + Rubber Band + LoopGen) — it's low-risk, reproducible, consumer-GPU-friendly, and likely fixes audio quality outright while giving you a NIME-worthy result. Treat true in-loop synthesis (Path 2, Magenta RT + a BPM-control contribution) as the deeper fall research question, and only escalate to it if Path 1's "offline-generate + adapt-live" genuinely fails your dissertation's novelty bar. Do not build on closed APIs (Lyria/Suno) or unreleased code (DITTO-2) as load-bearing components.

_Sources: full model landscape in `position_b_models_research.md`; techniques + closed-loop precedents in `position_b_techniques_research.md`._
