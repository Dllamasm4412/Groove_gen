# Segment-Based Control Redesign — Council Synthesis & Next Steps

**Date:** 2026-08-04
**Question:** Redesign the closed loop from per-bar musical morphing to **segment-level control** —
fixed songs per segment (~30–60 s), an HR-trajectory setpoint (e.g. 120→75 at ~6 BPM/min ±3 BPM),
a genre-energy ladder (calm→r&b→pop→latin), and pre-generation + crossfade so the song keeps
playing while the next one renders.
**Council:** Opus (control-systems, read the code line-by-line), GPT-5 (systems/supervisory),
Gemini (music-therapy/HCI). Full responses: `council_seg_opus.md`, `council_seg_gpt.md`,
`council_seg_gemini.md`. Brief: `council_segment_brief.md`.

---

## TL;DR — what all three agree on

1. **Control at segment rate, not per bar.** One control update per segment boundary. This makes
   "nothing changes inside a segment" true *by construction*, which is exactly your comfort goal.
2. **Do NOT throw away the validated `CascadeController`.** Opus proved it is already
   timescale-agnostic — `dt` is documented as "seconds per update"; "bar" appears only in
   docstrings and counter names. So the redesign is **the same controller called once per segment
   with new constants** — zero new controller classes. (This is the "Option B story, Option A
   code-preservation" synthesis; GPT independently proposed the same supervisory shape.)
3. **Setpoint = rate-limited LINEAR ramp in HR units**, not exponential, not adaptive. This is a
   *reference governor* upstream of the untouched `HRArousalMapper`.
4. **6 BPM/min is a REFERENCE slew rate, never a promised physiological rate.** The paper must say
   "tracks a reference shaped at 6 BPM/min," NEVER "reduces HR at 6 BPM/min." 120→75 is ~7.5 min.
5. **The ±3 BPM deadband on *raw* HR is below the respiratory noise floor** — the #1 landmine.
   Feed the controller a **30 s artifact-gated trailing mean** (SEM ≈ 0.7 BPM → 3 BPM becomes ~4σ).
6. **Genre ladder is a heavily-gated COARSE actuator** — step one rung only after tempo+tier are
   saturated AND error persists AND a minimum dwell has elapsed. Target ~3–5 genre changes per
   15 min ("a set, not a shuffle" / Gemini: not "scanning radio stations").
7. **Pre-generation is a non-problem:** rendering a whole 30 s segment as ONE FluidSynth call is
   ~2 s vs a 30 s budget (~15× margin). One background render + a 1-deep queue. No clever
   concurrency needed.
8. **This makes the paper STRONGER, not just different** — you inherit the iso-principle
   (music-therapy) literature, the two-timescale story becomes honest (rendering fast / control
   slow), and "per-bar morphing was an unvalidated assumption we falsified by ear" is a genuine
   system-design finding.

---

## Decision (locked recommendation)

| Dimension | Decision | Source of agreement |
|---|---|---|
| Control cadence | **Per segment** (Option B semantics) | all three |
| Controller code | **Reuse `CascadeController`, new constants, no new classes** | Opus (proved timescale-agnostic), GPT |
| Segment length | **Fixed 30 s** for the pilot (NOT 60, NOT a 30–60 mix) | Opus arithmetic + GPT "fixed dose" |
| Setpoint law | Rate-limited linear ramp + first-order terminal taper + progress gate + 8 BPM lead clamp = **reference governor** | all three (Opus most specific) |
| Slew rate | 6 BPM/min reference (reportable), a *shaped reference* not a physiological promise | all three |
| Deadband | ±3 BPM **on 30 s artifact-gated mean HR**, 1 BPM Schmitt re-arm | all three |
| Genre ladder | 4 rungs `calm→r&b→pop→latin`, gated by (persistence ≥2 seg) × (tempo+tier saturated) × (dwell ≥2 seg); asymmetric: N=2 calming, **N=3 exciting** | all three; asymmetry = Opus |
| Direction | **Consider up-regulation as the primary demo** (75→100 has real range; 120→75 needs a stressor/IRB) | Opus pushback — DECISION NEEDED FROM YOU |
| Crossfade | Equal-power, downbeat-aligned, **2 beats** (~1.2 s), no time-stretch; cap `max_step_bpm 8→4` | all three; 2-beat = Opus (beat-drift math) |
| Trace | **Keep one row PER BAR**, add ~25 segment/HR/ladder columns | Opus (critical), GPT |
| Playback | New `player.py` (`SoundDevicePlayer` live / `NullPlayer` for CI); `push()` blocking = the clock | Opus |

---

## THREE CODE FAULTS — verified in the actual source, fix BEFORE Phase 2

I confirmed each of these by reading the code directly (not taking the council's word):

**(0a) The `calm` rung does not exist in the controller.**
`pd_controller.py:274` → `GENRE_ENERGY_ORDER = ["r&b", "pop", "latin"]` and
`GENRE_EQUILIBRIUM_BAND` (line 448) has only those three keys. But the renderer *does* know `calm`.
So `run_session.py:157`:
```python
gi = ctrl.genre_order.index(cfg.genre) if cfg.genre in ctrl.genre_order else 0
```
**silently starts a `calm` scene at r&b** — no warning, no trace record. A ballad anchor → whole
session runs one rung off from what Methods says.
**Fix:** insert `"calm"` at index 0 of `GENRE_ENERGY_ORDER`; add
`GENRE_EQUILIBRIUM_BAND["calm"] = (0.03, 0.50)` (**must sit below r&b's 0.68 ceiling** or the
band-precedence logic breaks). Log `scene_genre_requested` + `ladder_rung_initial`.

**(0b) Saturation/step direction is chosen from `setpoint < 0.5`, not the sign of the error.**
`pd_controller.py:653, 660, 727, 731` all branch on `setpoint < 0.5` / `>= 0.5`. A calming session
120→75 (`resting=60,max=120`) sweeps arousal 1.00→0.25 — **crossing 0.5 mid-session** — so the
direction test flips even though the error sign never changed. The old per-bar loop had ~250 bars
to recover; at segment cadence you get ~30 chances total and the ladder goes deaf halfway down.
**Fix:** branch on signed error (`error >= 0`) instead of `setpoint >= 0.5`. Then re-run the
existing `__main__` self-test as the regression gate.

**(0c) `polish()` peak-normalizes every call → loudness STEP at every crossfade.**
`symbolic_bed_proto.py:154` → `mix = mix/(np.max(np.abs(mix))+1e-9)*0.95`. Per-segment polish means
a level jump at every seam — the single most audible possible artifact.
**Fix:** add `normalize=False` (or one fixed session gain calibrated from the loudest reachable
tier/genre); log `segment_peak` / `segment_rms_db`.

**(Bonus, verified) Non-monotonic ladder at the bottom.** `renderer.py:65` `_drum_genre` returns
`"pop"` for calm, and `drum_bar_tier` treats pop/rnb/calm identically — so a **tier-5 calm segment
renders full pop drums** (16th hats, ghost snares, crash), louder/busier than a tier-2 r&b segment
on the rung *above*. The energy ladder is non-monotonic at the bottom.
**Fix:** `RUNG_TIER_CAP = {"calm":2, "r&b":4, "pop":5, "latin":5}` (~3 lines in the renderer).

---

## The setpoint law (reference governor) — from Opus, concur

Per-subject constants; ρ=6 BPM/min=0.1 BPM/s, T=30 s, D=3 BPM, L=8 BPM lead, τ=60 s terminal.

1. **Init to the participant's own baseline** (iso-principle): `H_ref(0) = mean(HR over 60 s baseline)`.
2. Signed distance `Δ = H_goal − H_ref(n−1)`, `s = sign(Δ)`.
3. **Terminal taper:** effective rate `r_eff = min(ρ, |Δ|/τ)` — linear far away, softens into a
   first-order approach in the last ~6 BPM (removes the arrival corner + terminal chatter).
4. **Progress gate `g∈{0,1}`** (anti-windup): freeze the ramp if the participant is lagging past
   the lead clamp — don't let the reference run away from a listener who isn't following.
5. Advance `H_ref(n) = H_ref(n−1) + s·min(|Δ|, r_eff·T·g)`.
6. Clamp lead: `H_ref(n) ← H_meas + clip(H_ref(n) − H_meas, −L, +L)`.
7. Convert once at the boundary: `setpoint_arousal = mapper.to_arousal(H_ref(n))` → `ctrl.step()`.

**Why not exponential:** its steepest slope is at t=0 — exactly when an aroused participant can
least follow — and to honor "~6 BPM/min" you'd rate-limit it into a linear ramp anyway.
**Why not adaptive:** ~30 updates/subject can't identify a per-subject plant; it also makes every
session a different system, destroying the "same pre-registered controller everywhere" claim a
method paper needs. Per-subject adaptation belongs in `HRArousalMapper(resting,max)`, calibrated
once offline.

---

## The #1 landmine and its (mandatory, 4-part) fix

**±3 BPM on unsmoothed HR is inside the respiratory-sinus-arrhythmia noise (±5–10 BPM).** As
specified the ladder walks to a rail in ~3 min every session and pins there — every trace looks
identical, coarse actuator looks broken, and you get exactly the genre-every-90 s churn the
redesign was meant to kill.

1. **Measurement window = control period:** feed a **30 s trailing mean of artifact-gated RR**,
   sampled at the boundary. Free — you're waiting 30 s anyway.
2. **Margin check:** ~35 beats/30 s, beat-to-beat SD ~4 BPM → SEM ≈ 4/√35 ≈ **0.7 BPM**, so
   3 BPM is ~4σ. Put this calculation in Methods — it turns the deadband from arbitrary to derived.
3. **Artifact gating before averaging** (~8 lines): reject RR outside [300, 2000] ms and any beat
   >20% from the running median; log rejection count per segment.
4. **Pre-register window + gate before collecting** so it doesn't read as post-hoc tuning of the
   exact parameter that decides whether the actuator fires. Log `hr_bpm_raw` AND `hr_bpm_smoothed`.

---

## Paper impact (all three: STRONGER)

- **Claim:** "per-bar closed-loop control" → **"segment-cadence closed-loop control of a
  physiological setpoint *trajectory*, with a genre-energy ladder as coarse actuator and
  pre-generated crossfaded segments as the actuation mechanism."**
- **Frame as fixing a latent validity problem**, not scope creep: per-bar morphing was an
  unvalidated assumption ("per-bar morphing is desirable") that you falsified by ear.
- **Figures:** F1 tracking → y-axis in **BPM** (measured HR + ramp + goal + ±3 shaded band;
  arousal inset keeps calibration auditable). F2 actuator **staircase** by segment (sparser — the
  honest cost; mitigated by 30 s). F3 latency → **pre-generation margin** (~15×) + keep per-bar
  render distribution as a sub-panel. F4 **NEW** transition audit (RMS envelope around each
  crossfade + distribution of tempo deltas → "N% of transitions exactly beat-matched"). F5
  ablation **must be replaced**: old cascade-vs-parallel stops oscillating at segment cadence →
  ablate the **comfort mechanisms** (deadband on/off, dwell on/off) and report *genre changes per
  15 min* + tracking MAE (~3–5 with vs 15+ without).
- **Stats:** ~30 updates × 5–8 participants ≈ 150–240 decisions. Report as **system
  characterization with per-session traces shown individually.** No group inferential test on n=6.

---

## NEXT STEPS (ordered)

**Phase 2A — fix the faults + build the new pieces (before any live audio):**
1. Fix (0a)/(0b) in `pd_controller.py`; re-run `__main__` self-test (regression gate). *[builder → rebuild if applicable; this is plain .py]*
2. Add `RUNG_TIER_CAP` + `normalize=False` path (renderer + `symbolic_bed_proto.polish`).
3. New `hr_trajectory.py` (~45 lines) — reference governor above; unit-test it standalone.
4. New `player.py` — `SoundDevicePlayer` + `NullPlayer` (default = Null, keeps CI bit-identical).
5. `renderer.render_segment(tier, tempo, genre, n_bars, xfade_head_bars=1)` — ONE MIDI / ONE
   FluidSynth call; pass `bar_idx=bar_in_segment, n_bars=bars_per_segment` so the existing
   fill@`%4==3` + crash@last-bar fire per segment (free transition cue).
6. `crossfade()` — equal-power, downbeat-aligned, 2 beats; assert `tempo_delta ≤ 4`.
7. Nest `run_session()` loop: control ONCE per segment, trace row PER BAR; inject `player`.
8. Extend trace schema (append-only; the 8 irreducible cols minimum:
   `segment_idx, is_segment_boundary, hr_ref_bpm, hr_traj_error_bpm, in_deadband, ladder_rung,
   pregen_ms, underrun`).

**Phase 2B — validate in sim (no participant):**
9. Headless run against the (clearly-labeled fabricated) toy plant — confirm
   `groupby('segment_idx')[plan_cols].nunique().max() == 1` (machine-checked within-segment
   invariance) and ~3–5 genre changes/15 min with comfort mechanisms on.
10. Latency: `render_segment` p50/p95 vs 30 s budget → the new F3.
11. Render an audible **segment-transition demo MP4** (verify mean_volume ≠ −inf) — down-reg and
    up-reg, showing crossfades + a genre step.

**Phase 3 — thin operator UI + tag `v0.1-pilot`.**

**DECISIONS I NEED FROM YOU:**
- **A. Direction:** up-regulation (75→100, real range, light IRB) as the *primary* demo, or
  down-regulation with a brief validated arousal-induction (Stroop/mental-arithmetic)? Opus argues
  up-reg is the better *demonstration* even though down-reg is the more interesting application.
- **B. Hardware:** order the **Polar H10** now — it's the longest-lead item and the whole HR path
  depends on it. (The 30 s artifact-gated RR pipeline needs real RR intervals, not just BPM.)

---

## Dissent / where the council did NOT fully agree

- **Segment length:** Gemini was comfortable with 30–60 s; **Opus argues hard for a fixed 30 s**
  (at 30 s the reference advances exactly one deadband/segment — self-consistent; at 60 s it's two
  → ladder arms every segment). GPT: fixed dose beats a 30–60 mix. → **Adopt fixed 30 s.**
- **Direction of the demo:** only Opus raised the "120 seated = you induced stress" realism
  problem. This is the one genuinely open decision (A above).
- **"Song" terminology:** Opus warns a 30 s / 3-loop cue is not a "song" — call it a **segment**
  or **cue** in the paper to remove an easy reviewer objection.
