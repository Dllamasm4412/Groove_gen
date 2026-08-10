# GrooveGen — Best Next Move + Full Integration Plan
### Council synthesis (Opus 5 / GPT-5.6 / Gemini 3.1 Pro) + code-verified reality check
**Date:** 2026-08-04 · **For:** Daniel Llamas (CU Boulder) · **Decision owner:** you

---

## TL;DR — the verdict is unanimous

**Go DEPTH, not breadth. Stop building genre engines. Spend the next ~3 weeks turning the scattered scripts into ONE runnable, instrumented, closed-loop system that emits a per-bar trace CSV — that trace is the paper.**

All three models reached this independently. No dissent on the core call. The disagreements are only about *sequencing details*, and Opus contributed three code-verified findings that change the plan materially.

---

## Three things the council caught that we had WRONG (verified against the code)

Opus inspected the actual repo instead of trusting the brief. I re-checked all three — they are real, and they must be resolved before any wiring:

1. **The validated controller's actuator is NOT "L1–L5 tiers."** `pd_controller.PDDensityController` outputs an integer **event-density in [3, 20]** (~18 steps), plus a separate genre-energy tier walked along `GENRE_ENERGY_ORDER`. Nothing maps density∈[3,20] → tier∈[1,5]. Our locked paper claim ("monotonic L1–L5 intensity tiers") describes an actuator the validated controller does not currently drive. **This is the #1 thing to reconcile.**

2. **The controller tracks arousal (0..1), not heart rate.** `step(setpoint, measurement)` is in arousal units; `hr_source.HRArousalMapper` converts bpm→arousal *separately and unvalidated*. "Tracks a HR setpoint" is really a two-stage cascade through a latent variable. A reviewer hits this in paragraph one. Decide now: either (a) claim arousal-tracking and treat HR→arousal as a stated, cited mapping, or (b) validate the mapping. Do not let the paper imply direct HR tracking.

3. **The UI is wired to the REJECTED path.** `groovegen_ui_app_staged.py` imports `dlbed`, whose own docstring says it turns Anticipatory-Music-Transformer MIDI into a **frozen, design-time BedProfile**. That's a batch/offline architecture. So "Phase 4 = wire the UI" is actually "replace the UI's data model." Budget it as a rewrite of a thin shell, not plumbing.

**Why this matters:** these three are the difference between "we have a validated controller, just wire it" (the brief's assumption) and the truth: *the validated sim controller and the paper's stated claim are not yet the same object.* Reconciling them IS the integration work.

---

## Question-by-question consensus

### 1. Best next move — DEPTH (unanimous)
The claim is a **control** claim; its evidence is a tracking trace + a latency/jitter figure. Zero genre engines move that number — each one adds validation debt (more space you must argue is monotonic and controllable). You have **no end-to-end run yet**, so you don't know your bar-deadline miss rate, whether tier quantization causes limit-cycling, or whether audio is continuous. IRB + recruitment both gate off a frozen artifact; every week of breadth pushes the freeze date.

> Opus's framing, worth quoting: *"The single most paper-valuable artifact you can produce in the next 14 days is a figure showing per-bar control interval vs. render latency, with jitter and deadline misses, next to a tracking plot."*

### 2. Minimum genre set — pop family only (unanimous)
Ship **STAB/COMP with the pop pack** as the participant default; r&b/latin/calm ride the *same* engine so they're near-free (include if smoke test passes, cut without regret otherwise). **Rock proxy: keep in repo, exclude from participant-facing choice** — a GM-timbre rock condition invites a sound-quality critique that contaminates a control paper (GPT + Gemini + Opus all said this). **Trap/EDM: no, not even as a hedge.**
- Ecological-validity objection ("participant's anchor is trap, gets pop") is solved **in the protocol, not code**: inclusion criterion = anchor song must map to the shipped pack (verified by `map_profile()` at screening); disclose as a stated limitation. Cost: zero engineering days.

### 3. Integration plan critique — 1→2→3→4 spine is right, with edits
- **Insert Phase 0 (do first): the data/timing contract.** All three flagged **timebase/latency misalignment — not music generation — as the #1 hidden landmine.** Write the trace CSV schema + a headless `run_session(config)->(trace.csv, wav)` entry point BEFORE any wiring. This also forces the units decision (finding #2) on day one.
- **Swap 3 before 2** (Opus): the adapter defines initial conditions + legal parameter ranges; wiring the loop against hardcoded values first means rewiring later.
- **Re-budget Phase 2 from 1 day → 3 days.** It's not plumbing.
- **Actuator quantization → limit-cycling** (Opus, specific + actionable): a PD loop quantized to 5 levels will chatter at boundaries. Keep controller state continuous, quantize only at render, add Schmitt-trigger hysteresis on tier boundaries, rate-limit to ≤1 tier change/bar, and **log both continuous command and applied tier** → report quantization-induced error as a separate honest term. *Turns the worst risk into a contribution.*
- **Colab has no realtime audio device** (Opus): live human-in-the-loop on hosted Colab is the shakiest assumption. Decide empirically in week 2: (a) run participants on a **local runtime/laptop** with realtime FluidSynth (recommended), or (b) lookahead double-buffering (≥2 bars) with equal-power crossfades and honest control-lag reporting.

### 4. Code consolidation — additive, NOT a refactor (unanimous)
Do not touch 90 scripts. Instead (~1 day):
1. `mkdir attic/` (or `archive/`), `git mv` ~85 non-critical-path scripts into it. Don't delete, don't fix, don't test.
2. Promote only the **~8–12 critical-path modules** into one `groovegen/` package: renderer (`symbolic_bed_proto`, `symbolic_tiers_demo`), controller (`pd_controller`), adapter (`profile_from_songs`/`symbolic_from_profile`), style packs, `hr_source`, and the new `session_runner`. Resolve root-vs-package duplicates now (`dlbed.py` is byte-identical in both places — that's how divergence starts).
3. **Acceptance test:** from a clean runtime, `import groovegen; groovegen.run_session(demo_config)` produces a valid trace CSV + playable WAV. Nothing else counts as "integrated."
4. Rule going forward: a file enters the package only if it's on the critical path AND has a smoke test.
5. **Tag `v0.1-pilot` and freeze.** During collection: crash fixes only, logged in the trace's `code_version`.

### 5. Minimum pilot UI — operator console, single screen (unanimous)
- Inputs: participant ID, condition/order, anchor-song profile (JSON/file), session length (bars), HR source dropdown (sim/manual/serial), setpoint-script selector.
- Controls: **START / STOP / ABORT.** That's it.
- Live readout: HR setpoint vs measured (rolling plot), current tier, tempo, bar index, **deadline-miss counter**, last-sample age / signal quality.
- On finish: absolute path of saved trace displayed.
- **Non-negotiable (Opus):** append-and-flush the trace **every bar** — a crash at minute 8 must not lose the session.
- **Distractions to skip:** piano-roll/waveform/spectrogram visualizers, theming, participant-facing aesthetics, in-UI genre browsing, A/B compare, figure generation inside the UI (make figures from the CSV in a separate notebook), and — critically — **any operator slider that overrides params mid-session** (that's an uncontrolled variable that invalidates the trace).

### 6. What NOT to do in the next 2–3 weeks (unanimous + Opus additions)
- No trap engine, no EDM engine, no new genre engines.
- **No rock DSP chain** — Opus: "~150 lines" is a ~5× underestimate and ends in a subjective listening test with no stopping rule. Timbre project inside a control paper.
- No neural audio, no vocals, no melody-quality work.
- No `bayesopt.py` / parameter search / auto-tuning — hand-tuned gains you can *report* beat optimized gains you can't explain.
- No new notebooks — the session runner is a `.py`; notebooks only call it.
- No big refactor, no renaming for elegance, no test suite beyond smoke tests.
- No new controller variants — reuse the existing naive-parallel-vs-cascade contrast as your ablation.
- Don't write the Discussion yet; write **Methods now** (it's determined), let Results wait for traces.

---

## The one piece of pushback beyond the questions (Opus — and it's right)

**If the loop's *measurement* stays a synthetic plant (`synth_physiology` / `dual_lever_plant_step`), then with n=5–8 humans you have a simulation wearing a biofeedback costume, and a reviewer will say exactly that.** The setpoint can legitimately be scripted; the **measurement must come off a real human.** But do NOT build sensing — **buy a Polar H10 (~$90), stream over BLE behind the existing `HRSource` interface.** Ten minutes of setup vs weeks of ESP32+PPG debugging, and it's a citable validated device. **Order it today** — it's the longest-lead, lowest-effort item on the whole plan.

---

## The concrete 3-week plan (adopt this)

### Phase 0 — Contracts & headless harness (0.5 day) — DO FIRST
- Define trace CSV schema (single source of truth). Minimum columns:
  `wall_t, bar_idx, hr_bpm_raw, arousal_setpoint, arousal_measured, error, density_cmd_continuous, density_applied, tier_cmd, tier_applied, tempo_cmd, tempo_applied, loudness_db, render_ms, deadline_miss, genre, seed, code_version`
- Stub `run_session(config) -> (trace.csv, session.wav)` headless entry point.
- **Resolve finding #2 here:** write down, in one paragraph in Methods, exactly what the controller tracks (arousal) and how HR maps to it.

### Phase 1 — One renderer interface + adapter as initial condition (Phase 3 folded in) (2 days)
- Consolidate renderer behind one function; wire `map_profile()` as the once-per-session scene selector (start tier, bpm range, transpose). `attic/` move happens here.
- **Reconcile finding #1:** decide the actuator story — map density[3,20]→tier[1,5] with a documented monotonic function, OR reframe the paper claim to "event-density control" and derive tiers as reporting buckets. Pick one and make the code + Methods agree.

### Phase 2 — Headless closed loop (3 days — re-budgeted)
- Controller → renderer, once per bar, with hysteresis + rate-limiting + continuous-state/quantized-output logging.
- **Phase 2.5 stress test (Gemini):** run hundreds of bars headless with mock HR; verify timing precision, sign-stability, monotonic transitions, no dropped/misaligned bars.
- Measure latency/jitter/deadline-miss → this is a paper figure.
- **Resolve Colab-vs-local audio empirically here.** Three full dry runs on the exact hardware you'll use for participants.

### Phase 3 — Thin operator UI over the headless runner (2 days)
- UI holds ZERO logic — it only calls `run_session()`. New thin shell (not the `dlbed`-based staged app).
- Per-bar trace flush. START/STOP/ABORT. Live setpoint/measured/tier/tempo/deadline-miss readout.
- Two end-to-end rehearsals with lab members, including the consent script.
- Tag `v0.1-pilot`. **Freeze.**

**Fallback (Opus):** if behind at end of week 2, **cut the UI and run the pilot from the headless runner in a notebook cell.** The trace CSV is the paper; the UI is not.

### Parallel / immediate
- **Order the Polar H10 today.**
- **Tier monotonicity mini-study** (Opus — worth more than any genre engine): render 5 clips/pack, have 8–12 lab members rank them, report Kendall's tau. If tiers aren't monotonic, your plant has a sign flip and the field controller is unstable regardless of sim behavior. ~2 hrs of your time.
- Draft **Methods** now.

---

## What this buys you
A single command → a full closed-loop session → a complete, reproducible per-bar trace CSV, driven off a real HR sensor, with a latency/jitter characterization and a tracking plot. **That is the paper.** Everything currently competing for "next" (more genres, better guitar tone, neural audio) is either negative-value or future-work until that artifact exists.

*Sources: `council_next_opus.md`, `council_next_gpt.md`, `council_next_gemini.md` (full council responses); code verified directly in `groovegen_project/groovegen/pd_controller.py`, `hr_source.py`, `dlbed.py`, `groovegen_ui_app_staged.py`; genre distribution in `genre_distribution_sophia.txt`; prior plan in `groovegen_project/INTEGRATION_ROADMAP.md`.*

---

# ADDENDUM (2026-08-04) — SEGMENT-BASED CONTROL REDESIGN (supersedes per-bar control)

**Trigger (Daniel):** don't change the song every ~5 s off HR. Set a hysteresis window
(e.g. HR 120, goal 75, move ~6 BPM/min ±3 BPM), keep a song playing while the next renders,
because changing songs too fast is uncomfortable. Song fixed per segment; segment ~30–60 s;
organize the user's genres by energy so we can walk calm→r&b→pop→latin to excite (and back to calm).

**Second council run (Opus/GPT/Gemini) — full synthesis in `segment_redesign_council_synthesis.md`.**
This ADDENDUM overrides the "once per bar" control cadence in Phase 2 above. **Trace stays per bar;
CONTROL moves to per segment.** Renderer consolidation (Phase 1) is unchanged and still valid.

## Locked decisions
- **Control per SEGMENT**, reusing the validated `CascadeController` with new constants (it is
  already timescale-agnostic — `dt` = seconds/update; "bar" is only docstrings/counter names).
  **Zero new controller classes.**
- **Fixed 30 s segments** for the pilot (Opus arithmetic: at 30 s the reference advances exactly
  one deadband/segment; 60 s arms the ladder every segment).
- **Setpoint = reference governor:** rate-limited linear ramp (6 BPM/min, *reportable reference*,
  NOT a physiological promise) + first-order terminal taper + progress gate + 8 BPM lead clamp,
  initialized to the participant's own baseline (iso-principle), upstream of the untouched
  `HRArousalMapper`. No exponential, no adaptive.
- **Deadband ±3 BPM on a 30 s artifact-gated trailing mean of RR** (SEM ≈ 0.7 BPM → ~4σ), 1 BPM
  Schmitt re-arm. NEVER on instantaneous HR (below RSA noise floor → ladder pins to a rail in ~3 min).
- **Genre ladder = gated coarse actuator**, 4 rungs calm→r&b→pop→latin: step 1 rung only when
  error persists ≥2 seg AND tempo+tier saturated AND dwell ≥2 seg; asymmetric N=2 calming / N=3
  exciting. Target ~3–5 genre changes / 15 min.
- **Pre-gen/crossfade:** render whole segment as ONE FluidSynth call (~2 s vs 30 s = ~15× margin);
  1 background render + 1-deep queue; equal-power downbeat-aligned **2-beat** crossfade, no
  time-stretch, cap `max_step_bpm 8→4`. New `player.py` (`SoundDevicePlayer`/`NullPlayer`).

## THREE CODE FAULTS — fix before Phase 2 (all verified in source)
- **(0a)** `GENRE_ENERGY_ORDER`/`GENRE_EQUILIBRIUM_BAND` lack `calm` → `run_session.py:157` silently
  runs a calm scene at r&b. Add `calm` at idx 0; band `(0.03,0.50)` (below r&b's 0.68 ceiling).
- **(0b)** `_density_saturated`/`_tempo_saturated`/genre-step (lines 653/660/727/731) branch on
  `setpoint<0.5` → direction FLIPS when a trajectory setpoint crosses 0.5. Use signed error.
- **(0c)** `symbolic_bed_proto.polish()` peak-normalizes every call → loudness step per crossfade.
  Add `normalize=False`; log `segment_peak`.
- **(bonus)** `renderer._drum_genre` maps calm→pop → tier-5 calm = full pop drums (ladder
  non-monotonic at bottom). Add `RUNG_TIER_CAP={calm:2,r&b:4,pop:5,latin:5}`.

## Paper impact (STRONGER): iso-principle literature acquired; two-timescale story becomes honest
(rendering fast / control slow); "per-bar morphing was an unvalidated assumption we falsified by
ear." F1→BPM axis w/ ±3 band; F2→segment staircase (sparser, honest cost); F3→pre-gen margin;
F4 NEW transition audit ("% exactly beat-matched"); F5 ablation REPLACED (deadband/dwell on-off,
genre changes/15 min). No group inferential test on n=6.

## Open decision for Daniel
**Direction:** up-regulation (75→100, real range, light IRB) as the primary *demonstration*, OR
down-regulation with a brief validated arousal induction? (Opus: up-reg is the better demo even
though down-reg is the more interesting application.)

*Source: `segment_redesign_council_synthesis.md`; council responses `council_seg_{opus,gpt,gemini}.md`;
code verified in `groovegen_project/groovegen/pd_controller.py`, `groovegen_pilot/run_session.py`,
`groovegen_pilot/renderer.py`, `symbolic_bed_proto.py`.*
