# GrooveGen — Project History & Decision Log

A chronological record of *why* the design is what it is: the major decisions, the reversals, and
the evidence behind each. Read alongside `PROJECT_HANDOFF.md` (what it is) and
`AI_CONTINUATION_CONTEXT.md` (how the code fits). Dates are approximate where the record is a
findings doc rather than a dated event.

---

## Phase 0 — v1.0 parametric stimulus generator (through ~June 2026)

- **What:** a literature-grounded parametric groove-stimulus generator (`groovegen_project/`,
  tagged v1.0, snapshot 2026-06-03). Five knobs locked to literature target bands and verified by
  manipulation checks: syncopation (Witek index), event density (onsets/bar), swing, tempo,
  microtiming. A frozen, time-invariant "study bed" isolates each knob as the sole variable. A
  20-stimulus manifest logs achieved manipulation-check values.
- **Primary groove knob = EVENT DENSITY** — chosen because it is monotonic and safe for
  closed-loop control (backbeat stays locked as the entrainment anchor; syncopation is bounded
  "spice" only; microtiming is cosmetic). See `step1_spec.md`.
- **Sophia secondary analysis** (n=122 participants / 643 unique tracks) grounds the bed feature
  profile. Key finding: danceability and energy are only weakly correlated (r≈−0.07) and yield
  *different* genre orderings — evidence against a common design assumption in affective-music
  systems. See `groovegen_project/sophia/`.

## Phase 1 — hybrid architecture: symbolic clock + neural bed

- **Decision (locked):** keep the **symbolic drums as the timing authority** (pretty_midi +
  FluidSynth = the clock) and treat any neural audio model (MusicGen) as a *timbral generator*
  that gets corrected onto the grid — never ask the neural model to be tempo-competent. This
  mirrors how every working closed-loop music system in the literature (AffectMachine-Pop,
  HEARTBEATS) reaches exact tempo. See `position_b_fall_plan.md`,
  `position_b_techniques_research.md`.
- **Why:** making the neural model the timing authority is the hard, risky, possibly-unnecessary
  version. The achievable and defensible version is: neural generates live, a thin deterministic
  correction layer + symbolic clock guarantee the grid.

## Transition mechanism study — crossfade first rejected, later re-adopted (narrowly)

- **Early finding:** a naive crossfade between two *different-tempo* beds sounds bad (the user
  heard two tempos overlapping). Three mechanisms were tested on a hard ~43% tempo-change case
  (136→95 BPM): downbeat-aligned hard cut, fill-masked cut, and tempo-ramp/time-stretch. See
  `transition_assessment.md`.
- **Reconciliation (current design):** crossfade is back, but **only under tight constraints** —
  equal-power, **downbeat-aligned**, **2 beats**, **no time-stretch**, and only when
  `tempo_delta ≤ 4` BPM (enforced by capping `max_step_bpm 8→4`). Under cascade quiescence most
  transitions are near beat-matched, so the earlier failure case rarely arises. This is why the
  crossfade helper asserts the tempo delta before running.

## Publishability framing — LOCKED to SYSTEM/METHOD, no efficacy

- **The `tei_publishability_audit.md` (July 13, 2026)** established the durable framing, written
  under the user's explicit honesty mandate: the paper is an **Artifact/Method (system)**
  contribution — "we built a working closed-loop control architecture with these specific
  properties, demonstrated in simulation and in real audio" — which needs **zero human subjects**
  to be true. It is NOT an empirical/efficacy contribution.
- **The single most important sentence** (must appear in the abstract's first paragraph): state
  explicitly that validation is simulation + informal listening + one piece of non-physiological
  survey data, and that no human closed-loop physiological data exists yet. Burying this reads as
  hiding it.
- **Defensible vs. desk-reject wording** is tabulated in `tei_publishability_audit.md`. Golden
  rule: "tracks the arousal *reference*," never "calms/regulates the user."
- **TEI itself is now OFF the table** for this fall (author's call — time constraints; the TEI
  cycle timing doesn't work). The system/method *framing* the audit established still holds and
  transfers to the recommended venues.

## Arousal-tracking framing — LOCKED

- The controller operates in normalized **arousal ∈ [0,1]** space. HR → arousal is a **stated,
  per-subject linear calibration** (`HRArousalMapper`: `arousal = clip((bpm−resting)/(max−resting),
  0, 1)`), calibrated once at session start. Both `hr_bpm_raw` and `arousal_measured` are logged so
  the mapping is fully auditable. The control claim is arousal-*tracking*, not direct HR
  regulation. See `groovegen_pilot/METHODS_control_framing.md`, `trace_schema.py`.

## Integration decision (2026-08-04) — DEPTH not breadth

- **Council (Opus / GPT / Gemini) unanimous:** stop building new genre engines; turn the scattered
  scripts into ONE runnable, instrumented, closed-loop system that emits a **per-bar trace CSV** —
  *that trace is the paper.* See `groovegen_integration_master_plan.md`.
- **Opus caught 3 things (verified against code)**, the most important being that the validated
  controller's actuator is an integer **event-density in [3,20]**, NOT the paper's L1–L5 tiers.
  Resolution: keep controller density continuous, map density→tier only at render time with
  hysteresis + a ≤1-tier/bar rate limit (`tier_mapping.py`). Log both, so quantization-induced
  tracking error is a separate reportable term.

## Segment-based control redesign (2026-08-04) — the big reversal

- **The reversal:** per-bar musical *morphing* was an unvalidated assumption. It was falsified by
  ear (mid-segment changes sounded wrong). The corrected design is **control at SEGMENT rate**
  (one control update per ~30 s segment); "nothing changes inside a segment" is now true *by
  construction*. This reversal is itself a reportable systems finding, not scope creep.
- **Council (Opus read the code line-by-line, GPT, Gemini) converged** — full synthesis in
  `segment_redesign_council_synthesis.md`. Key agreements:
  - **Reuse the validated `CascadeController` unchanged** (it is timescale-agnostic; `dt` = seconds
    per update). ZERO new controller classes. ("Option B semantics, Option A code.")
  - **Fixed 30 s segments** (not 60, not a mix): at 30 s the reference advances exactly one
    deadband per segment (self-consistent).
  - **Reference governor** (`hr_trajectory.py`): rate-limited **linear** ramp (NOT exponential,
    NOT adaptive — can't identify a per-subject plant in ~30 updates) + terminal taper + progress
    gate + 8 BPM lead clamp, initialized to participant baseline (iso-principle).
  - **6 BPM/min is a REPORTABLE reference slew rate, never a physiological promise.**
  - **Deadband ±3 BPM on a 30 s artifact-gated trailing mean of RR** (SEM≈0.7 BPM → ~4σ). The #1
    landmine: ±3 BPM on RAW HR is below the RSA noise floor and pins the ladder to a rail in ~3 min.
  - **Genre ladder = gated coarse actuator** (calm→r&b→pop→latin), asymmetric N=2 calming / N=3
    exciting, target ~3–5 genre changes / 15 min.
  - **Pre-gen is a non-problem:** a whole 30 s segment renders in ~2 s (≈15× margin).
  - **Trace stays PER BAR** even though control is per segment (machine-check within-segment
    invariance).

## Three code faults fixed (2026-08-04/05) — verified before Phase 2

Found by reading the actual source (not assumed), each now fixed with a green regression gate
(`groovegen_pilot/test_faults_fixed.py` + the controller `__main__` self-test):

- **(0a)** `calm` rung was missing from the controller → a calm scene silently started at r&b.
  FIX: `calm` at ladder index 0; `GENRE_EQUILIBRIUM_BAND["calm"]=(0.03,0.50)` (below r&b's 0.68).
- **(0b)** direction chosen from `setpoint<0.5` → a setpoint crossing 0.5 mid-session flipped the
  ladder. FIX: branch on signed `error`.
- **(0c)** `polish()` peak-normalized every call → loudness step at every crossfade. FIX:
  `polish(normalize=False, gain=...)`.
- **(bonus)** non-monotonic ladder at the bottom (tier-5 calm rendered full pop drums). FIX:
  `RUNG_TIER_CAP={"calm":2,"r&b":4,"pop":5,"latin":5}`.

## Direction decision (2026-08-04, user) — up-reg primary demo, system bidirectional

- **User's call:** "sure we can do up regulation for a demo. Just keep in mind that the idea is to
  have a system that can up regulate and down regulate." → **Up-regulation (75→100) is the primary
  DEMO** (real seated range, light IRB); the **system stays fully bidirectional** (nothing
  hardcoded). The reference-governor self-test verifies both directions + the progress-gate freeze.

## Reference governor built + verified (2026-08-05)

- `groovegen_pilot/hr_trajectory.py` implements the governor above and passes its `__main__`
  self-test: up-reg 75→100 and down-reg 120→75 both converge with no overshoot; a non-following
  participant is never led by more than the 8 BPM clamp (`ramp_frozen` flags correctly). The
  progress gate and lead clamp are two views of the same anti-windup guarantee; the trace reports
  `ramp_frozen` if either engages.

## Venue decision (2026-08-05) — AI-council-backed

- A 3-model council (Opus / GPT / Gemini) unanimously recommended **NIME 2027 (~Feb 2027) full
  paper + demo** as primary, **CHI 2027 LBW** as backup, and **TISMIR/IMWUT** as the 2027 archival
  extension. All three flagged **CHI 2027 full paper (Sep 10, 2026) as a trap** for a solo,
  time-constrained student with no draft/data/hardware. Full reasoning: `VENUE_RECOMMENDATION.md`
  (+ `council_venue_{opus,gpt,gemini}.md`).

---

## Standing constraints (never violated across the whole project)

- **No vocals, anywhere.**
- **No efficacy claims** — SYSTEM/METHOD contribution only.
- **Honest technical pushback is expected** — name trade-offs, recommend against bad paths.
- **Toy plant is fabricated** — offline sim/ablation only.
- **Dev rule:** edit notebook *builders*, then rebuild `.ipynb`; never hand-edit `.ipynb`. Plain
  `.py` modules are edited directly.
- **Deliver audio as MP4/zip** (user often can't play bare WAV/MP3 inline); verify every MP4's
  `mean_volume ≠ -inf`.
