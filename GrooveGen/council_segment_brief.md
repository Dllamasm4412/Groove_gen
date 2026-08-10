# Council Brief — Segment-Based Control Redesign (GrooveGen)

## The correction from the researcher (Daniel, PhD, CU Boulder)
The current architecture assumes PER-BAR song adaptation driven by instantaneous HR.
This is WRONG for the use case. Rapid song-morphing (every ~2-5 s) is uncomfortable to
listen to. The new model:

- The system tracks a **target HR trajectory**, not instantaneous HR. Example: HR now = 120,
  goal = 75. Bring HR down at a BOUNDED rate (~6 BPM/min) with a **±3 BPM deadband/tolerance**.
  Do not chase small fluctuations.
- Music plays as a coherent **SONG SEGMENT** for a sustained stretch, then transitions to the
  next song. **Segment length: ~30–60 s** (user's answer).
- **Within a segment the SONG IS FIXED** (user's answer: "Song fixed per segment"). No per-bar
  tier/tempo nudging inside a segment. Adaptation happens ONLY at segment→segment transitions.
- **Generate the NEXT song AHEAD OF TIME** (during current segment playback) and cross-transition
  smoothly, so the listener never hears a gap or a jarring cut.
- **Genre energy ladder (user's key point):** genres the user provides are ORDERED BY ENERGY.
  To excite from calm, walk gradually: calm → r&b → pop → latin. To calm down, walk the reverse.
  This ladder is the COARSE actuator at the segment level (which genre/energy the next segment is),
  complementing tempo/intensity.

## What is already built and VALIDATED (do not re-litigate)
- Arousal-tracking framing LOCKED: controller tracks arousal 0..1; HR→arousal is a stated
  per-subject linear calibration (HRArousalMapper).
- CascadeController: density (fast) + tempo + genre (slow outer tiers under saturation).
  genre_order = ["r&b","pop","latin"] (energy order). Density[3,20]→tier[1,5] map with
  Schmitt hysteresis + ≤1 tier/bar rate limit.
- Phase 0: headless run_session() with per-bar trace CSV, crash-safe flush. PASSED stress test.
- Phase 1: ONE consolidated per-bar renderer (SymbolicBarRenderer over FluidSynth). Real audio.
  Measured render latency p50≈221ms, p95≈330ms per bar << bar budget. Scene selector (map_profile)
  sets initial genre/tempo/tier. 92 one-off scripts attic'd.
- Publishability LOCKED: SYSTEM/METHOD contribution (closed-loop physiological music control),
  NOT efficacy. NO VOCALS. Pilot on pop primarily (r&b/latin ride same engine).
- Constraints: Colab T4, ONE session, likely run participants on LOCAL laptop (no realtime audio
  device on Colab). Polar H10 for HR. Trace CSV = the paper.

## The tension the council MUST resolve
The validated controller is a PER-BAR fast loop. The new requirement is a SEGMENT-level
(30–60 s) control cadence with a fixed song per segment. These are different timescales.
Options the council should weigh (and pick / synthesize the best):

A) **Two-loop reframe:** keep the per-bar controller but run it INTERNALLY to *design the next
   segment's fixed parameters* (genre rung on the energy ladder, tempo, intensity tier), then
   FREEZE those for the whole 30–60 s segment. The per-bar loop becomes a "segment planner"
   run once per transition, not a live actuator. Trace logs both the segment plan and the HR
   trajectory error.
B) **Pure segment controller:** discard per-bar control entirely for the live path; a single
   segment-level controller reads the HR-trajectory error at each transition, steps ONE rung on
   the genre-energy ladder and/or adjusts tempo/tier for the next segment. Simpler story.
C) **Hybrid:** segment-level genre/tempo selection + a slow within-segment tempo glide only
   (user rejected this — they chose "song fixed per segment" — so likely OUT, but note it).

## Specific questions for each council member
1. Which option (A/B/C/other) best fits: (a) the comfort requirement, (b) the genre-energy-ladder
   idea, (c) a clean, defensible METHOD paper (system contribution, not efficacy)?
2. How to define the **HR-trajectory setpoint** the segment controller tracks? Linear rate ramp
   (~6 BPM/min, ±3 deadband) vs exponential approach vs adaptive. Recommend one and justify.
3. How does the **±3 BPM deadband** interact with the **genre-ladder step** and **segment cadence**?
   (i.e., only step a rung when trajectory error exceeds deadband for N consecutive segments?)
4. **Pre-generation / crossfade:** how to generate the next segment during the current one and
   transition smoothly. Beat-matched crossfade? Fixed 30–60 s? What must the renderer/loop change?
5. What is the **minimum change** to the existing headless run_session() + trace schema to support
   segment cadence WITHOUT throwing away validated code? Be concrete about the trace columns.
6. What is the biggest RISK or landmine in this redesign, and what would you do about it?
7. Does this change the paper's claim or figures? If so, how?

Be concrete, opinionated, and disagree with the premise if warranted. The researcher explicitly
values honest technical pushback over agreement.
