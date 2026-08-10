# GrooveGen — Project Handoff & Complete Context

**Owner:** Daniel Llamas — PhD student, University of Colorado Boulder
(Cognitive Science / ATLAS / HCI-Engineering triple track; Brain Music Lab).
**Snapshot date:** 2026-08-05.
**Current tag target:** `v0.1-pilot` (segment-based closed loop; Phase 2A in progress).
**Audience:** this document is written so that BOTH a human collaborator AND another AI
assistant can pick the project up cold and continue it without losing any context.

> Companion documents (read these next):
> - `AI_CONTINUATION_CONTEXT.md` — the interface map, invariants, dev rules, and gotchas an AI
>   needs to make safe code changes.
> - `PROJECT_HISTORY_AND_DECISIONS.md` — the chronological decision log (why the design is what
>   it is; every reversal and the evidence behind it).
> - `VENUE_RECOMMENDATION.md` — where to submit a paper this fall (AI-council-backed).
> - `segment_redesign_council_synthesis.md` (repo root) — the authoritative spec for the
>   current segment-based redesign.
> - `groovegen_integration_master_plan.md` (repo root) — the master build plan + addendum.

---

## 1. What GrooveGen is (one paragraph)

GrooveGen is a **closed-loop system that generates a musical bed and steers it in real time from
a listener's heart rate.** A control loop reads the listener's HR, converts it to a normalized
*arousal* value, compares it to a scripted *reference trajectory*, and adjusts the music to track
that reference — getting the music more energetic to raise arousal (up-regulation) or calmer to
lower it (down-regulation). The system is **bidirectional**: nothing is hardcoded to one
direction. The musical actuator is a **symbolic** (MIDI → FluidSynth) generator, chosen because
its render latency is bounded and sub-bar, which a real-time control loop requires.

## 2. The contribution (what the paper claims — LOCKED)

- **Contribution TYPE: SYSTEM / METHOD.** We contribute a *working closed-loop architecture* and
  its empirical systems characterization. **We do NOT claim efficacy** — i.e. we do not claim the
  music measurably changes human physiology. That framing is deliberate and locked.
- **No vocals anywhere** (locked constraint).
- **Novelty:**
  1. A **cascade control architecture** for music: a fast event-density loop, a tempo loop that
     engages only when density saturates, and a **genre-energy ladder** (calm → r&b → pop → latin)
     as a gated coarse actuator.
  2. A **two-timescale design result**: control runs slowly (once per ~30 s segment) while
     rendering is fast (a whole segment renders in ~2 s vs a 30 s budget, ≈15× real-time margin).
     This is the empirical justification for a symbolic (not neural-audio) bed.
  3. An honest **design-correction finding**: per-bar musical morphing was an unvalidated
     assumption; we falsified it by ear and moved to segment-cadence control. That reversal is
     itself a reportable systems lesson.
- **Grounding:** the *iso-principle* from music-therapy literature (meet the listener where they
  are, then lead them) motivates initializing the reference to the participant's own baseline.

## 3. How the closed loop works (end to end)

```
   Polar H10 (BLE)                                                  speakers
        │ RR intervals                                                 ▲
        ▼                                                              │
   HRSource ──► 30 s artifact-gated trailing mean (hr_bpm_smoothed)    │
        │                                                              │
        ▼                                                              │
   HRArousalMapper:  arousal = clip((bpm - resting)/(max - resting),0,1)│
        │  arousal_measured                                            │
        ▼                                                              │
   HRTrajectory (reference governor)  ── arousal_setpoint ─┐           │
        │  (rate-limited linear ramp + terminal taper                  │
        │   + progress gate + lead clamp; per SEGMENT)      │          │
        ▼                                                    ▼          │
   CascadeController.step(setpoint, measured)  ─► {genre, tempo, density, tier}
        │  (density loop → tempo loop → genre ladder; ONE step / segment)
        ▼                                                              │
   TierMapper (density→tier, hysteresis + rate limit)                  │
        │  tier_applied                                                │
        ▼                                                              │
   renderer.render_segment(tier, tempo, genre, n_bars) ─► ONE MIDI, ONE FluidSynth call
        │  stereo float32 audio for the whole segment                 │
        ▼                                                              │
   crossfade() equal-power, downbeat-aligned, 2 beats ────────────────┘
        │  (previous segment tail ⨝ next segment head)
        ▼
   Player (SoundDevicePlayer live / NullPlayer for CI) — blocking push() = the clock
```

Every **bar** a row is appended to the session trace (crash-safe). **Control** happens once per
**segment** (≈30 s). "Nothing changes inside a segment" is therefore true *by construction*.

## 4. Key parameters (the pilot configuration — LOCKED by council)

| Parameter | Value | Why |
|---|---|---|
| Segment length | **fixed 30 s** | reference advances exactly one deadband/segment (self-consistent) |
| Reference slew | **6 BPM/min** (a *reportable reference rate*, NOT a physiological promise) | iso-principle pacing |
| Deadband | **±3 BPM on a 30 s artifact-gated trailing mean of RR** (≈4σ, SEM≈0.7 BPM) | ±3 on RAW HR is below the RSA noise floor — the #1 landmine |
| Schmitt re-arm | 1 BPM | anti-chatter on the deadband |
| Lead clamp | 8 BPM | never let the reference run away from a lagging listener |
| Terminal taper τ | 60 s | soften the arrival, remove terminal chatter |
| Genre ladder | `calm → r&b → pop → latin` (4 rungs) | coarse energy actuator |
| Ladder gating | step 1 rung only when error persists ≥2 seg AND tempo+tier saturated AND dwell ≥2 seg | ~3–5 genre changes / 15 min ("a set, not a shuffle") |
| Ladder asymmetry | N=2 segments to calm, **N=3** to excite | easier to soothe than to arouse |
| `max_step_bpm` | **8 → 4** | keeps most transitions beat-matchable |
| Density range | [3, 20] (integer, continuous internally) | validated cascade fast-loop |
| Tier range | [1, 5] (render-time bucket, hysteresis + ≤1/bar rate limit) | reporting + anti-chatter |
| `RUNG_TIER_CAP` | `{calm:2, r&b:4, pop:5, latin:5}` | keeps the energy ladder monotonic at the bottom |
| Crossfade | equal-power, downbeat-aligned, **2 beats** (~1.2 s), no time-stretch | least-audible seam |
| HR→arousal | per-subject linear calibration (resting→0, max→1), calibrated once at session start | disclosed modeling choice, not a learned model |

## 5. Direction decision (LOCKED)

**Up-regulation (75 → 100 BPM) is the primary DEMO direction** (real seated range, light IRB
footprint). **The system stays fully bidirectional** — down-regulation (e.g. 120 → 75) uses the
identical code path in reverse and is validated in simulation and in the reference-governor
self-test. Nothing in the controller, reference governor, or renderer is hardcoded to one
direction.

## 6. Verified empirical findings (the results we already have)

1. **Render latency (per bar, real FluidSynth on Colab T4):** p50 ≈ 221 ms, p95 ≈ 330 ms; render
   consumes ~10–14 % of a bar's real-time budget; **zero deadline misses** over the measured run.
2. **Whole-segment render:** a full 30 s segment renders as ONE FluidSynth call in ~2 s → ≈15×
   real-time margin. Pre-generation is therefore a non-problem (1 background render + 1-deep queue).
3. **Tracking (simulation):** tracking MAE ≈ 0.071 (arousal units) over 48 bars against the toy
   plant. (NOTE: the toy plant `dual_lever_plant_step` is FABRICATED — offline sim/ablation only,
   never in the live path or in any efficacy claim.)
4. **Three code faults found by reading the source and fixed + regression-tested** (see §7).
5. **Reference governor** verified bidirectional: up-reg 75→100 and down-reg 120→75 both converge
   with no overshoot; a non-following participant is never led by more than the 8 BPM clamp.
6. **Sophia secondary analysis** (n=122 participants / 643 unique tracks) grounds the "bed feature
   profile" (which acoustic features a calm bed should hit). See `groovegen_project/sophia/`.

## 7. The three code faults (found, fixed, verified) — do NOT regress these

These were discovered by reading the actual source (not assumed) and each is now fixed with a
green regression test (`groovegen_pilot/test_faults_fixed.py` + the controller's own
`__main__` self-test).

- **(0a) Missing `calm` rung.** The controller's `GENRE_ENERGY_ORDER` lacked `calm`, so a calm
  scene silently started at r&b. FIX: `calm` inserted at ladder index 0;
  `GENRE_EQUILIBRIUM_BAND["calm"]=(0.03,0.50)` (below r&b's 0.68 ceiling).
- **(0b) Direction chosen from `setpoint<0.5` instead of error sign.** A session whose setpoint
  crosses arousal 0.5 mid-way would flip the ladder direction. FIX: branch on signed `error`.
- **(0c) `polish()` peak-normalized every call** → a loudness STEP at every crossfade. FIX:
  `polish(normalize=False, gain=...)` for per-segment renders.
- **(bonus) Non-monotonic ladder at the bottom** — a tier-5 calm segment rendered full pop drums.
  FIX: `RUNG_TIER_CAP` clamps tier by genre in the renderer.

## 8. Current status & what's next

**Done:** Phase 1 (latency/tracking validation); Phase 2A-1 (three faults fixed + regression
gate green); Phase 2A-2 (`hr_trajectory.py` reference governor built + self-test green,
bidirectional).

**Immediately next (Phase 2A-3 → 2A-5):**
1. `player.py` — `SoundDevicePlayer` (live, blocking `push()` on a bounded queue = the clock) +
   `NullPlayer` (DEFAULT; keeps headless/CI runs bit-identical). Inject like `renderer` is.
2. `renderer.render_segment(tier, tempo_bpm, genre, n_bars, xfade_head_bars=1)` — ONE PrettyMIDI /
   ONE `render_midi()` call; factor `_bar_midi` into `_write_bar(...)`; pass
   `bar_idx=bar_in_segment, n_bars=bars_per_segment` so fill@`%4==3` + crash@last-bar fire per
   segment. Add `crossfade()` (equal-power `y=cos(πn/2N)x+sin(πn/2N)z`, downbeat-aligned, 2 beats,
   assert `tempo_delta ≤ 4`).
3. Nest `run_session()` loop: control ONCE per segment (`ctrl.step()`), trace row PER BAR; extend
   the trace schema (append-only). Use `symbolic_bed_proto.polish(normalize=False, gain=...)`.

**Phase 2B (sim validation):** confirm `groupby('segment_idx')[plan_cols].nunique().max()==1`
(within-segment invariance), ~3–5 genre changes/15 min, latency figure, and render an audible
bidirectional transition demo MP4 (verify `mean_volume ≠ -inf`).

**Phase 3:** thin operator UI; tag `v0.1-pilot`.

**Hardware — DO THIS SOON:** order a **Polar H10** (longest-lead item; the 30 s artifact-gated
pipeline needs real RR intervals, not just BPM).

## 9. How to run

See `groovegen_pilot/` for the clean pilot (`renderer.py`, `scene.py`, `run_session.py`,
`hr_trajectory.py`, `phase1_check.py`, `test_faults_fixed.py`, plus `trace_schema.py`,
`tier_mapping.py`). See `groovegen_project/HOW_TO_RUN.md` and the root `HOW_TO_RUN.md` for the
full v1 pipeline and Colab runbook. Environment: Google Colab, Python 3.12, T4 GPU, ONE session
at a time. System deps: `fluidsynth fluid-soundfont-gm rubberband-cli`. Python deps:
`groovegen_project/requirements.txt` (pins matter for the MusicGen bed path).

Quick verification any AI/human should run first:
```bash
python groovegen_pilot/hr_trajectory.py        # reference governor self-test (bidirectional)
python groovegen_pilot/test_faults_fixed.py    # the three-fault regression gate
python groovegen_project/groovegen/pd_controller.py   # controller __main__ self-test
```

## 10. Paper figures (planned)

- **F1** tracking, y-axis in **BPM** (measured HR + reference ramp + goal + ±3 shaded band;
  arousal inset keeps calibration auditable).
- **F2** actuator **staircase** by segment.
- **F3** pre-generation margin (~15×) + per-bar render distribution sub-panel.
- **F4 (new)** transition audit — RMS envelope around each crossfade + distribution of tempo
  deltas ("N % of transitions exactly beat-matched").
- **F5 (replaces old ablation)** comfort-mechanism ablation: deadband on/off, dwell on/off →
  genre changes / 15 min + tracking MAE.
- **Stats:** system characterization with per-session traces shown individually. No group
  inferential test on n≈6.
