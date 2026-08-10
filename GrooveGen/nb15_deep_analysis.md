# GrooveGen nb15 v3 — Deep Analysis, Fix Recommendation, Next Steps

## 1. Why only the pop section sounds off (confirmed with measurements)

I extracted each segment from your rendered MP4 and measured it. The pop section is objectively the outlier:

| segment | target BPM | detected BPM | beat jitter | onset irregularity | verdict |
|---------|-----------:|-------------:|------------:|-------------------:|---------|
| latin   | 125 | 126.0 | **5.5 ms** | 0.086 | rock-solid |
| **pop** | 110 | 110.0 | **29.5 ms** | 0.464 | **5× worse — the problem** |
| r&b     | 97  | 95.7  | 17.7 ms | 0.316 | fine |
| calm    | 82  | 82.0  | 49.4 ms | 0.221 | fine (sparse → noisy tracker, but perceptually OK) |

Pop's **tempo is correct** (110) but its **beat timing is 5× jitterier than latin**. Two independent tests confirm the cause:
- Drum onsets land on average **127 ms off** an ideal 110 grid (a beat is only 545 ms — that's ~23% of a beat of slop, continuously).
- One clear loop seam ~25 s into the segment.

**Root cause:** pop is the ONLY MusicGen-**generated** bed in this run. Latin and R&B use the clean **uploaded** WAV loops you provided, which have crisp, steady pulses. Generated beds wander in tempo within the clip, so the drum aligner and the bed disagree — the drums sound "off" against the music. The code already tries to compensate (madmom downbeat tracking + grid regularization in `hybrid_render.py`), but on this particular wobbly generated bed it isn't enough.

## 2. Which fix I recommend (you asked for my honest pick)

**Recommendation: Option A — use a clean uploaded pop bed. It is clearly the best.**

Reasoning:
- It attacks the actual root cause (generated-bed wander) instead of patching symptoms. Latin and R&B sound great *precisely because* they use clean uploaded beds — pop should get the same treatment.
- **Zero credits.** It removes a MusicGen call rather than adding one.
- I prototyped the two code-only alternatives and they're only partial:
  - **Option B (quantize the generated bed):** my prototype cut jitter 20.7 → 13.5 ms, but the grid error stayed ~150 ms and global time-stretch *added* artifacts. Half a fix.
  - **Option C (snap drums to detected downbeats):** the code already essentially does this via madmom; the residual wander is inside the bars, so C can't fully remove the clash.
  - **Option D (regenerate pop N times, pick steadiest):** burns credits and still yields a generated bed. Not recommended.

**What I need from you for Option A:** one clean ~110 BPM pop loop (four-on-the-floor or straight backbeat), same kind of short WAV as the latin/r&b ones you already uploaded. Drop it in and I'll wire it in — no Colab regeneration of pop needed.

**If you'd rather not hunt for a bed right now:** I'll apply Option B+C together as the interim (quantize the generated bed *and* re-lock drums to its post-quantize grid). It won't be as clean as A, but it's free and noticeably better than v3. Tell me which and I'll build it.

## 3. Mix fix you requested (melody louder, latin drums too loud) — FREE, no Colab

I found the cause in the notebook. The render cell does a crude flat sum:

```python
mix = 0.8 * bed_y + 0.9 * mixed   # drums are actually +1 dB LOUDER than the bed
```

It bypasses the project's real mix bus (`mix_stems`, which defaults to bed −2 dB / drums −4.5 dB **plus** kick sidechain-ducking and a bed high-pass). So in v3 the drums dominate — worst in latin where density is highest (8).

**Fix:** route the segment mix through `mix_stems` (so you also get sidechain + HPF), OR, minimally, flip the gains to:

```python
mix = 1.0 * bed_y + 0.62 * mixed   # melody on top; drums ~4 dB under the bed
```

Plus a small **per-genre drum trim for latin** (its density-8 kit is the loudest): latin drums an extra ~1.5 dB down. This directly delivers "a little more melody, latin drums quieter." All of this runs on CPU locally — no MusicGen, no credits.

## 4. Next steps (toward the TEI 2027 system paper, due July 31)

1. **Lock pop quality (this fix).** Once pop matches latin/r&b, the hero artifact is publishable-clean end to end.
2. **Standardize on uploaded beds for all four genres.** Right now the paper's hero clip mixes uploaded (latin/r&b) and generated (pop) beds — inconsistent and it's the one weak spot. A clean bed per genre band makes the whole arc uniform and reproducible, and lets you state the mechanism cleanly in the paper.
3. **Route all renders through `mix_stems`.** The good mix bus already exists; the notebook just isn't using it. Adopting it everywhere removes the "drums too loud" class of issue permanently and is a defensible, documented gain-staging choice for the methods section.
4. **Write the two paper sections I flagged earlier** (contributions + limitations). The honesty guardrails are already locked in the notebook prose — they translate almost directly into the limitations section (scripted setpoint, no efficacy claim, toy plant, N=19 Latin caveat).
5. **Optional polish:** a short A/B video (v3 pop vs. fixed pop) makes a strong figure/supplement for reviewers.

## 5. Credit-saving recommendations (you asked)

- **The only expensive step is MusicGen generation.** Everything else (control loop, drum synthesis, mixing, splicing, video) is CPU and free.
- **Cache/reuse beds instead of regenerating.** `get_bed_info` is already cached, but beds themselves are regenerated per run. Save the four segment beds to WAV once and reuse them — every re-render after that costs zero MusicGen.
- **Prefer uploaded beds** (Option A) — each uploaded bed is one fewer MusicGen call, permanently.
- **Do all mix/level/tuning changes locally** (like today's fix) — none of them need Colab.
- **Dry-run the control trace on CPU** before any GPU render (already the workflow) so you never spend a GPU session discovering a logic bug.
- **Fewer, targeted subagents.** I did today's diagnosis in-process (no subagent spawns) precisely to save credits, since it was measurement work, not parallelizable research.

## Bottom line
Pop is off because it's the one generated bed; the fix I recommend is a clean uploaded pop bed (best + saves credits). The "drums too loud" issue is a separate, one-line mix bug I can fix locally right now. Both are free. Send me a pop loop (or say "interim B+C") and tell me to apply the mix fix, and I'll rebuild.
