# GrooveGen v3: revised architecture for closed-loop generative music

Status: review and plan only (2026-11-01). No source code, stimuli, controller behaviour, tests
or research artifacts were changed. This document revises `MUSIC_GENERATION_REVIEW_AND_ROADMAP.md`
(2026-10-30, "the previous roadmap"). Where they disagree, this one applies.

**Reviewed code:** release `pilot-zero-v2c-locked` (`65f2338`, branch `experiment-music-ratings`),
the corpus and analyses on `main` (`groovegen_project/data/`, `groovegen_project/sophia/`), and
the earlier two-timescale design (`groovegen_project/ARCHITECTURE_TWO_TIMESCALE.md`).

**Evidence labels:**

| Label | Meaning |
|---|---|
| **[C]** | Read in the code |
| **[R]** | Computed or run by the reviewer (method stated) |
| **[P]** | Reported in project documents |
| **[E]** | Published evidence |
| **[H]** | Hypothesis |
| **[Eng]** | Engineering judgement; numeric thresholds marked [Eng] are provisional |

**Central conclusion.** The previous roadmap protected experimental control by keeping
composition decisions independent of the controller. That was stronger than the science
requires, and it reduced physiological adaptation to "choose a genre and an intensity". The
revised architecture keeps the scientifically necessary principle:

> **No musical change is uncontrolled or unmeasured.**

It drops the unnecessary one:

> No physiological influence on composition.

Physiology reaches every level of composition, at matched timescales, through typed, logged
controller intents. The generator is deterministic given its seed, its versions and the intent
history, so sessions replay exactly. Yoked replays remove the contingency on the listener's
physiology while keeping the music identical.

---

## 1. Assessment of the previous roadmap

### 1.1 Still valid

| Conclusion | Status |
|---|---|
| Root causes: tiny vocabulary; surface-only, post-hoc variation; gating against the v1 generator's own seed spread; per-cell memory; tier steps re-drawing material | Valid; nothing in this review contradicts them [C][R] |
| Correctness defects: duplicate tier pairs (calm/lofi/rnb/pop 1 = 2); Latin odd bars out of clave; wrong key labels | Valid [R] |
| Feature contract with construct-based tolerances, measured couplings and compensation | Valid; becomes the core of the controller–generator interface (section 5) |
| No neural models in the live path; speculative pre-composition; no sub-segment adaptation for now | Valid (section 2.4) |
| Perceptual calibration before trusting diversity metrics | Valid; extended in section 8 |

### 1.2 What changes, and why

| Previous position | Revised position | Reason |
|---|---|---|
| Open-loop, precomputed `MaterialSchedule`; composition independent of the trajectory | History-aware, deterministic **planner conditioned on controller intents**. The open-loop schedule is kept only as a selectable protocol condition | Under the previous design, physiology changed only genre and intensity. Composition was selection from fixed pools plus parametric realisation (section 2.2, Q1–Q2) |
| "Physiology never enters the generator" | **Raw physiology** never enters it; **controller decisions** do, through a typed interface | The boundary that matters is mediation and logging, not isolation |
| Path independence as an invariant | **Intent-conditional determinism**: `MIDI_n = G(seed, versions, intent_1..n)` | Replay and yoking need determinism given the recorded intents, not path independence (Q6) |
| Pools of 12–24 enumerated progressions/figures per genre as the main expansion | **Generative mechanisms** (grammars, parametric generators, transformation operators) over small, principled primitive sets | Libraries grow linearly, recur audibly and cannot hit arbitrary feature targets (section 3.1) |
| All genres in phase 2; controller untouched until late | **Interface first, then a hip-hop vertical slice** through controller, planner, realiser, contract, render and replay; controller extension earlier | The interface and the two-timescale control are the main architectural risks; one genre tests them end to end |
| "Within-genre intensity widening" as a late protocol amendment | Part of the slice: hip-hop already spans most of the ladder | Section 2.4 (Q3) |

### 1.3 Errata

1. **The phase 2 target was impossible under the proposal's own design.** The target was
   "segments repeating a chord cycle heard in the last 4 min fall from 8/9 to at most 2/9" (pop:3
   dwell, 10 visits). With 3-visit blocks that keep one harmonic loop, visits 1, 2, 4, 5, 7 and 8
   repeat their own block's loop by design, so at least 6/9 must repeat. The metric counted
   **planned intra-block repetition**. The measured baseline 8/9 decomposes into 6 planned
   intra-block repeats plus **2 of the 3 new-block segments** reusing an earlier block's cycle
   (only 2 distinct cycles occurred). The correct target counts only unplanned cross-composition
   recurrence: baseline 2/3, target 0/3. Planned repetition is measured separately (section 6.4).
2. **"40 genre changes across 58 boundaries" was a scripted path, not a controller simulation.**
   The path was a monotone climb, a 9-segment top rotation that alternates genre by design, and a
   descent. The ladder-order fact (19 of 26 adjacent rungs differ in genre) stands. **The
   genre-switch rate under the real controller has not been measured.** It depends on HR
   dynamics, dwell and saturation. Phase 0 measures it.

---

## 2. Closed-loop architecture analysis

### 2.1 The two principles

| Principle | Keep? | How it is enforced |
|---|---|---|
| A. No **uncontrolled, unmeasured** change in musical features | **Yes, strictly** | Every change is typed, attributed to a cause, measured against a contract and logged. The novelty magnitude per segment is a measured quantity with a declared budget |
| B. No **physiological influence** on composition | **No** | It would reduce the system to selection. Replaced by: influence only through declared, logged intents whose effect on the music is a tested function |

### 2.2 Answers to the eight questions

| # | Question | Answer |
|---|---|---|
| 1 | What changed in response to physiology under the previous architecture? | The cell (genre, tier), and after decoupling the intensity parameters (density, layers, velocity) plus *when* a genre's schedule advanced. *What* material was composed was fixed by the precomputed schedule [C: previous design] |
| 2 | Was it still generating? | Partly. Each segment's MIDI would be realised at runtime, but identity came from finite curated pools in a fixed order. That is "selection of predetermined identities + parametric realisation", which is your concern |
| 3 | Can physiology influence composition itself? | Yes, through three typed channels at matched timescales (section 6.2): **intensity targets** per segment; **structure requests** (build, sustain, release, transition) per section; **style/composition changes** by the supervisor, at minutes. The generator decides *how* to realise them musically |
| 4 | Would the precomputed schedule constrain creativity or adaptation? | Yes. It fixes identity order regardless of what the controller needs, cannot align a build or breakdown with a control request, and caps diversity at the pool size. It remains useful as a **control condition** (fixed development clock) |
| 5 | Must material selection be independent of the trajectory? | No. What must be controlled is the **amount and timing of novelty** (it can move HR through orienting responses; Sokolov, 1963; Bradley, 2009) and its **feature effects**. The specific identity can depend on history, provided both are measured |
| 6 | Seeded generation + recorded trajectories instead of path independence? | Yes. Determinism given (seed, generator/protocol versions, intent log) gives exact replay and yoked controls. What is lost is "visit k of cell c is identical across participants". That comparison is weak anyway, because participants visit different cells. Analyses should condition on **logged realised features** instead of cell labels |
| 7 | How can a history-aware generator stay interpretable? | Five rules, listed below the table |
| 8 | What stays independent of physiology, and what may adapt? | Table in 2.3 |

The five rules for question 7:

1. Generator state is a pure function of logged inputs.
2. Plan revisions are logged, each with its triggering intent.
3. Every musical change carries a `cause` (`intensity`, `structure_request`, `supervisor_switch`,
   `development_clock`, `anti_repetition`).
4. Novelty magnitude per segment is measured and budgeted.
5. Counterfactual replay: rerun the generator offline with edited intent logs to characterise its
   response function without participants.

### 2.3 What may depend on physiology (through intents)

| Aspect | Physiology-dependent? | Rationale |
|---|---|---|
| Style rules, structural constraints (clave, backbeat skeleton, scale/chord-tone rules), realiser rule set | **Never** | Defines the stimulus class |
| Protocol-held features (e.g. syncopation level, swing, tempo within a composition) | **Never** within a protocol | Held features are what make other manipulations interpretable |
| Intensity features (layers, per-role density, dynamics, brightness class) | **Yes, per segment** | The primary actuator |
| Section-level trajectory (build, sustain, release) | **Yes, if the protocol enables structure requests**; otherwise a fixed development clock | Lets structure serve control; it is a declared channel |
| Composition identity *timing* (when a new composition starts) | **Yes**, via the supervisor (reachability, residency) | Large changes only when control needs them or residency ends |
| Composition identity *content* (which progression, hook, groove) | **History-dependent, not physiology-dependent** (seed + history + style) | Content varies, but its feature effects are verified and logged |
| Novelty budget | **Fixed per protocol** in confirmatory work; may be a controlled channel in exploratory protocols | Novelty is a plausible physiological driver; it must be held or manipulated, never incidental |

### 2.4 Controller reassessment, against the code and real timing

**Facts** [C]:
- `LadderMPC.step` enumerates rungs within ±1 of the current one (`max_step_per_segment=1`) over
  `horizon=3` segments.
- Cost = error at the horizon + steady-state error + `w_churn=0.01`·(Δrung)². There is **no genre
  or continuity term**.
- Plant: FOPDT with `plant_tau_s=60`, `plant_dt_s=20`, a one-segment delay, and static gain
  `g_hat·u`.
- `g_hat` is estimated by RLS from the HR deviation against the **commanded cell's mean `u`**,
  not the segment actually played. Prior 2.5 bpm across the whole `u` range, cap 12 bpm.
- Dead zone 1.5 bpm; reference governor; saturation rotation for variety.
- HR is the 10 s median of 1 Hz polls. Segments last 14.8–29.5 s. Decisions are made
  `render_lead_s=3.0` before the queue drains [C][P].
- The prior gain implies the music's **expected control authority is a few bpm**, close to the
  dead zone and to sensor noise. Control performance is unproven beyond n = 1 up-regulation runs
  [P]. Any redesign must be judged on tracking data, not musical arguments.

**Within-genre range** [R]: computed from `energy_table_v1.json` with the release's own formula
(`music_features_measured.energy_scores`, z over 35 cells, min–max over the 27 live cells).

| Change | Δu |
|---|---|
| +1 dB loudness | 0.052 |
| +1 drum onset/s | 0.053 |
| +1 BPM | 0.0033 |
| +100 Hz spectral centroid | 0.0027 |
| +4 dB and +3 drum onsets/s at fixed tempo | ≈ 0.37 (tie band 0.042) |

Hip-hop already spans 0.173–0.856, mostly through loudness and drum density; its tempo
contribution (85→96 BPM) is only 0.036 [R]. So **tempo can stay constant within a composition**,
a slow identity feature, without losing intensity range. Other genres are narrow because their
generators barely change loudness or drums with tier (pop drums ignore density) [C], not because
the energy metric cannot move.

**The seven controller questions:**

1. **Can LadderMPC be extended?** Yes, without a new class (the project rule forbids new
   controller classes). Three changes:
   - A candidate generator: within-style intensity steps every segment; cross-style candidates
     only when the supervisor opens a switch window.
   - Cost terms: `w_switch`·[style change] and a perceptual-continuity term on feature distance.
   - RLS on **achieved** `u`, taken from the realisation report.
   All are config flags, off by default, with existing decisions byte-identical.
2. **Residency, switching penalty, hysteresis?** Yes. Switching among stable subsystems can
   destabilise a loop unless switching is slowed by dwell time or hysteresis (Liberzon, 2003;
   Hespanha & Morse, 2002) [E]. Musically it gives continuity. Tune by simulation; never at the
   cost of tracking (acceptance in phase 4).
3. **Is the within-genre range enough?** For hip-hop and rock, yes today (0.68, 0.49). For the
   others, plausibly about 0.3–0.4 `u` with loudness, layers and drum density [R estimate; must
   be verified on rendered audio]. No single genre should span calm (`u` 0) to rock:5 (1), so
   switches stay necessary at the extremes.
4. **When the current genre cannot reach the target**:
   - the fast loop saturates (anti-windup already exists);
   - the supervisor checks each style's **capability envelope** (measured reachable `u` range);
   - if the governed target lies outside the current envelope for N consecutive decisions
     [Eng: N = 2], it schedules a switch at the next section boundary to the nearest style that
     covers it, preferring tempo- and key-compatible styles, with a transition device;
   - if no style covers it, the governor shrinks the target (existing behaviour) and logs
     `unreachable`.
5. **Are some genre transitions useful?** Possibly. Large perceptual changes may be stronger
   actuators, especially toward calm for down-regulation, or may cause orienting transients
   [H]. Treat this as an empirical question: run the ablation "switching free vs penalised"
   (section 8.5) and measure event-locked HR around switches.
6. **Responsiveness vs continuity.** Intensity keeps one decision per segment. Continuity costs
   and hysteresis apply only to identity changes. Segment boundaries are phrase boundaries, so
   intensity changes land musically.
7. **A different formulation than the 1-D ladder?** Use a **2-D (style × intensity) state with
   a scalar plant input** (`u` = energy). A multi-input feature controller (MIMO) is not
   advisable now: one noisy output (HR) at segment rate cannot identify separate gains for
   correlated inputs (poor excitation). Bandit or RL selection needs many sessions per person;
   postpone it. The offline `CascadeController` (tempo, density, genre) shows the multi-actuator
   idea, but tempo as a separate channel is the most movement-confounded lever (section 2.5).

**Faster than one decision per segment?** Not now. The HR estimate's 10 s median and cardiac
response latencies already match segment rate. Faster changes add seams without adding usable
control bandwidth [Eng].

### 2.5 Danceability, movement and the meaning of HR

- **HR is not arousal.** Name variables as what they are: `hr_bpm`, `hr_reference_bpm`. Arousal
  enters only through validated measures: self-report (the existing `arousal_1_9` /
  `arousal_primary` mode), and later validated multi-signal estimates. The controller tracks an
  **HR reference**. "Arousal regulation" is the research hypothesis, not a variable in the loop.
- **Movement confound.** Groove invites movement, and movement raises HR metabolically.
  Rhythmic music can also entrain breathing, which modulates HR. The sensor is a **finger PPG on
  a XIAO M0 with no motion sensor**. `SENSOR_NOTES.md` reports large wrong readings after slight
  movement, and its motion-artifact section is still TODO [P]. High-groove conditions could
  therefore both raise HR and degrade signal quality, a missing-not-at-random bias.
  Architecture response:
  1. Add an IMU channel (e.g. a XIAO variant with an on-board IMU, or a wrist accelerometer) as
     a measured disturbance: a movement index and artifact flags in the state estimator.
  2. Log signal-quality rejections per segment and test whether they vary with condition.
  3. Two protocol modes: **still** (instructed stillness; movement measured as a check) and
     **free** (movement allowed; analysed as a mediator: music → movement → HR).
  4. Keep groove-salient features (kick/snare skeleton, pulse-clarity floor, syncopation)
     **held** across intensity levels in confirmatory protocols, so intensity effects are not
     groove effects.
- **Second actuator.** With `--haptic-pacing`, the haptic pacer receives `seg_target_bpm` and
  paces heartbeat-like pulses from the current HR toward it at 6 BPM/min [C]. Haptic pulses also
  couple into the raw PPG (+150–200 counts) until the motor supply is separated [P]. Music
  effects can only be attributed with haptics off, or with haptics as a crossed factor.

**Three layers of claims:**

| Layer | Examples | Claim allowed |
|---|---|---|
| Musical features | Tempo, per-role onset rates, syncopation index, pulse clarity, LUFS, layer mask, novelty magnitude | Controlled exactly; verified per segment |
| Perceptual responses | Perceived energy, urge to move (EGQ), repetition, fatigue | Predicted by versioned models; listener validation required |
| Physiological outcomes | HR, HR variability, movement, respiration | Experimental measurement with yoked and sham controls |

---

## 3. Musical vocabulary expansion strategy

### 3.1 Libraries vs generative mechanisms

| | Pattern library | Generative mechanism |
|---|---|---|
| Growth | Linear in authoring effort | Combinatorial in rules × parameters |
| Recurrence | Items are salient chunks and recur recognisably | Outputs share principles, not surfaces |
| Controllability | Search for the nearest item; gaps between items | **Constructive**: generate *to* a target (density, syncopation, register, harmonic rhythm) |
| Coherence | Easy: each item is vetted | Harder: needs constraints, compatibility predicates and listening checks |
| Certification | Enumerate all outputs (plan §6.4) | Too many to enumerate. **Certify the generator statistically**: sampled coverage of the target grid plus per-segment contract checks at runtime |
| Copying risk | High if items come from songs | Low if only aggregate statistics are used |

**Recommendation:** generative mechanisms over **small, principled primitive sets**. Libraries are
kept only for genre-defining primitives: clave patterns, a boom-bap skeleton, rhythm cells,
harmonic-rhythm templates. Development is done with **transformation operators**, not more
items.

### 3.2 Mechanisms per layer (hip-hop first; same structure for other styles)

| Layer | Mechanism | Controlled inputs | Hard constraints |
|---|---|---|---|
| Harmony | Weighted grammar over minor-centred loops: tonic pedal, i–bVI, i–bVII, i–iv, i–v, i–bII (Phrygian colour), i–iv–bVI–v, soul-style 7th/9th loops; loop length 1/2/4 bars; harmonic rhythm 1 chord per 1–2 bars | Harmonic-complexity class (couples with groove; Matthews et al., 2019) | Loop closure; start on i; no unintended functional cadence in the default style |
| Groove | Skeleton (kick 1, snare 2 and 4) + metrical-weight template + probabilistic ornament grammar (kick placements, ghost snares, hat subdivision and accents, open-hat placement respecting the choke rule) | Per-role onset rates, syncopation index band, pulse-clarity floor, swing (held) | Skeleton protected; open-hat ring rule (`variation.open_hat_rings`) |
| Bass | Derived from harmony + kick: roots on chord-change downbeats, lock-in with kick on strong slots, approach notes, octave pops, sub layer by intensity | Bass onset rate, register | Chord tone on chord-change downbeats; register floor (Musyng bass has no sample below 26) [P] |
| Hook / motif | Rhythm cell (genre cells on a 16th grid) × scale-degree contour with chord-tone targets on strong beats; phrase forms (sentence, call–response, AABA′) | Hook density, register, level (measured level tables) | Range; leap limits; no ≥ k-note match with known melodies (copy check) |
| Development | Operators: sequence, inversion, rhythmic displacement within contract, fragmentation, augmentation, re-orchestration, call→response swap (Schoenberg, 1967; Collins & Laney, 2017) | Novelty budget per segment | Contract after every operator |
| Arrangement | Layer masks per intensity level; staggered entrances (Hurley et al., 2014); hook re-voicing on another instrument | Intensity level → layer mask | Programs within the style palette; brightness compensation |
| Form | Section grammar: intro, groove A, groove B, build, peak, breakdown, return, outro, each with an intensity annotation | Structure requests | Legal transitions only |

### 3.3 What the corpus can and cannot provide

**Available** [C][P]:
- `survey_and_music_data_N122.csv`: 122 participants aged 18–25, 976 participant–song rows (8
  each) in four conditions (sensory-motor, self-relevant, peer, computer).
  - Spotify descriptors: tempo, danceability, energy, valence, artist genres.
  - Questionnaires: eBMRQ, BFI, IRI.
- `track_features.csv`: 644 tracks, audio descriptors from 30 s previews: tempo (two trackers),
  beat consistency, PLP, LHL syncopation, onset density, on/off-beat event density, spectral
  features, MFCCs, HPSS percussive/harmonic ratios, sub- and low-band energy.
- `song_excerpts/urls.txt`: 13 YouTube links (calm, latin, pop, rnb).
- Prior analyses (`sophia/RESULTS_MEMO.md`, `BED_FEATURE_PROFILE.md`):
  - Danceability is only modestly predicted (cross-validated R² 0.18).
  - Percussive ratio and low-band energy are the strongest positive predictors.
  - 110–130 BPM tracks score about 9 points higher.
  - **No syncopation inverted-U** in commercial audio.
- Genre prevalence: pop 41%, rock 23%, country/folk 19%, hip-hop/rap 15%, r&b/soul 11.5%, latin
  2%. Hip-hop/rap danceability 67.5, pop 61.2.

**Not available:** symbolic transcriptions, chords, bass lines, melodies, drum transcriptions,
section annotations, or **any participant groove rating**. The outcome is Spotify's proprietary
danceability, not human judgment [P].

**Use it for:**
1. Feature **targets and ranges** per style for the target population: tempo band, onset density,
   bass-forward and percussive balance, beat consistency.
2. **Priors**, not validated perceptual models.
3. Style selection: pop and hip-hop are the most prevalent danceable families in this
   population; country/folk is prevalent but absent from GrooveGen.

**Symbolic statistics must come from elsewhere:**
- Music-theoretic genre rules (labelled as expert rules and validated by listening).
- Openly licensed symbolic corpora: the Groove MIDI Dataset (Gillick et al., 2019; CC BY 4.0)
  for drum-onset statistics; rock/pop harmony corpora (de Clercq & Temperley, 2011; Burgoyne et
  al., 2011) for transition probabilities.
- Use only **aggregate statistics** (position-wise onset probabilities, chord-transition
  probabilities), never sequences. Add a copy check against any reference material, including
  the current `hiphop_cell._PIANO_RH_TWO_BAR`, which is written to echo two named commercial
  tracks [C].

**Risks and mitigations:**
- Overfitting to individual songs: aggregate statistics only; no excerpt-level extraction from
  `song_excerpts/`.
- Valid but incoherent combinations: compatibility predicates (harmonic rhythm × bass figure,
  hook range × chord tones, groove family × bass lock), style templates encoding co-occurrence,
  expert and listener typicality checks.

### 3.4 How large the space must be

Derive size from use, not maximisation. A 15-minute session with compositions of 2–6 minutes
needs about 3–6 compositions. Four sessions per participant need about 20 per style with no
salient recurrence of hook, harmonic loop or groove. The requirement is **about 20+ perceptually
distinct compositions per style**, measured by the similarity calibration (section 8.3), not by
combinatorial counts.

---

## 4. Proposed system architecture

```
SENSING (100 Hz)                  STATE ESTIMATION (1 Hz)                  PROTOCOL
finger PPG (XIAO M0) ─────────►  stable-HR estimator (new_biofeedback/)    HR reference schedule
[add] IMU / accelerometer ────►  HR (10 s median), quality, staleness,     (hr_trajectory, phases),
[opt] self-report arousal ────►  movement index, artifact flags           held features, budgets
                                            │                                        │
                                            ▼                                        ▼
        ┌──────────────── CONTROLLER (control.LadderMPC, extended by config) ─────────────────┐
        │ fast loop (each segment): governor + MPC over intensity within the current style    │
        │ supervisor (section boundaries): residency, hysteresis, reachability, switch cost   │
        │ RLS on ACHIEVED u from the RealizationReport; anti-windup; hold on stale HR         │
        └───────────────┬─────────────────────────────────────────────────────┬─────────────┘
                        │ ControlIntent (no physiological values)             │ pacer goal
                        ▼                                                     ▼ (separate actuator)
        COMPOSITION PLANNER (history-aware, deterministic, receding horizon)   haptic pacer
          session plan ▸ composition identity ▸ section roles ▸ phrase plan
          + depth-1 branches for the next decision {down, hold, up, [switch]}
                        │ SegmentPlan (per branch)
                        ▼
        REALISER (style mechanisms: harmony grammar, groove generator, bass, hook/motif,
                  development operators, arrangement masks) → bar/note events
                        │ MIDI candidates
                        ▼
        FEATURE VERIFICATION (contract: structural predicates, controlled-feature targets,
                  MIDI→audio predictors, compensation, fallback chain) → RealizationReport
                        │ committed branch only
                        ▼
        RENDER (FluidSynth, sf2 sha-pinned) → [opt] live audio feature measurement
                        ▼
        CrossfadeMixer('tail_out') → player → LISTENER ─────────────► back to sensing

LOGS (append-only trace): intents, plan revisions with causes, realization reports,
MIDI sha, achieved features, novelty vector, HR / quality / movement, haptic state
REPLAY: G(seed, versions, intent log) → identical MIDI.  YOKED: recorded audio → another listener
```

| Component | Files (existing → proposed) |
|---|---|
| State estimation | `new_biofeedback/ppg_live_estimator_*.py`, `estimator_hr_source.py`; add movement channel |
| Controller | `control.py` `LadderMPC` + `ControllerConfig` flags (`style_mode`, `w_switch`, `min_dwell_sections`, `switch_hysteresis`, `rls_on_achieved_u`); `ladder.py` gains per-style intensity ladders and capability envelopes |
| Interface | new `groovegen_pilot/control_intent.py` (dataclasses only) |
| Planner | new `groovegen_pilot/composer/v3/planner.py` |
| Realiser | new `composer/v3/style_hiphop.py` (mechanisms), `composer/v3/operators.py`, `composer/v3/intensity_hiphop.py` |
| Verification | new `composer/v3/contract.py`; reuses `stimulus_metrics.py`, `energy_guard.BOUNDS` ideas, level tables `composer/hook_levels.py`, `levels_*.py` |
| Runner | `run_session_v2.py` (`segment_source=` already pluggable; speculative branches opt-in); `session_generator.py` gains a v3 source; `trace_schema.py` append-only columns |
| Replay | new `groovegen_pilot/replay_session.py` (planned in plan §6.5 but not present at `65f2338`) |

Frozen and untouched: `composer.py`, `composer/hiphop_cell.py`, `composer/rock_cell.py`,
`arrangement.py` v2a/v2c paths, all identity fixtures, Experiment 1 stimuli, the ladder files.

---

## 5. Controller and generator interface

### 5.1 Messages

**`ControlIntent`** (controller to planner, once per segment decision; never contains HR,
targets, errors, gains or participant identity):

| Field | Meaning | May change |
|---|---|---|
| `seq`, `segment_idx` | Ordering | Every segment |
| `style` | Genre / style id | Only when the supervisor commits a switch (≥ `min_dwell`) |
| `u_target` | Scalar intensity in the global `u` scale (plant input) | Every segment, ±1 intensity step |
| `feature_targets` | Derived deterministically from `u_target` by the style's **intensity map** (layer mask, per-role onset rates, dynamics offset, brightness class), each with a tolerance | With `u_target` |
| `held` | Features fixed by the protocol (e.g. syncopation band, swing, tempo within composition) | Never within a protocol |
| `structure_request` | `none / build / sustain / release / transition` + urgency | At most once per section; only if the protocol enables it |
| `novelty_budget` | `surface / phrase / section / composition` | Protocol schedule, or supervisor on a switch |
| `mode` | `mpc / hold / stale_hold / supervisor_switch` | Every segment |

**`SegmentPlan`** (planner to realiser): composition id and spec hash, section index and role,
phrase plan, feature targets, operator list, seeds.

**`RealizationReport`** (realiser and verification, back to the planner, the controller and the
trace):
- MIDI sha;
- achieved MIDI features and predicted audio features, including predicted `u`;
- deviations from targets; compensation applied; fallback level;
- **novelty vector** (change per factor vs the previous segment and vs the session);
- change causes; compute time.

The controller uses predicted (later measured) **achieved `u`** in its RLS.

### 5.2 Rates

| Signal | Rate |
|---|---|
| PPG | 100 Hz |
| HR updates | 1 Hz; 10 s median per decision |
| `ControlIntent` | 1 per segment (14.8–29.5 s), decided 3 s before the queue drains |
| Structure requests | ≤ 1 per section (2–4 segments) |
| Style or composition changes | Not before `min_dwell` [Eng: 2 sections ≈ 1–2 min] unless reachability forces it after the hysteresis count |

Speculative branches give the realiser and renderer the whole current segment (about 15–30 s)
instead of 3 s.

### 5.3 Reproducibility

- `MIDI_n = G(stim_seed, generator version, protocol version, intent_1..n)`.
- Tests:
  - replay from the intent log reproduces every MIDI sha;
  - the default (locked) path stays byte-identical;
  - the generator imports no physiology modules (extends `tests/test_generator_boundary.py`:
    the generator may import `control_intent`, never `hr_sources`, `serial_ppg_source`,
    `estimator_hr_source`, `control`).
- Yoked control: play a recorded session's audio to another participant.
- Counterfactual characterisation: replay edited intent logs offline.

### 5.4 Identity, intensity and coupling

**Decomposition: adopt as software and as an experimental aim, not as a perceptual
assumption.**

- **Relatively separable at fixed controlled features:**
  - Pitch content (progression choice within a complexity class, motif contour) and mode: mode
    relates more to valence than to arousal; tempo, loudness and articulation relate to arousal
    (Gomez & Danuser, 2007; Gabrielsson & Lindström, 2010) [E].
- **Coupled** (must be measured and compensated):
  - instrumentation and register → brightness and loudness (Musyng sample-zone jumps up to
    ~7 dB [P]);
  - harmonic rhythm and complexity → activity and groove (Matthews et al., 2019);
  - layers and staggered entrances → groove (Hurley et al., 2014);
  - drum family → syncopation and pulse;
  - articulation → perceived energy.
- **Represented in software as:**
  - a `FeatureSpec` registry (name, extractor, role per protocol, tolerance, rationale);
  - a **coupling table** (measured effect of each realiser decision type on each controlled
    feature, per soundfont sha), generalising `hook_levels.py`, `levels_*.py` and
    `dev_latin.ACCOMP_EFFECT`;
  - MIDI→audio predictors.
  - The realiser chooses identity elements subject to targets, then compensates residuals
    through intensity parameters (velocity, ghost-note count, layer gain), then verifies.
- **Controlled variation** = a change requested by a declared intent or the declared development
  clock, within the novelty budget, with features in contract. **Uncontrolled novelty** = any
  change in an undeclared feature family beyond its hold tolerance, or beyond the budget. It is
  flagged and falls back.

**How this differs from the current system.** Today the controller picks a cell label, which
indexes a fixed distribution whose mean energy was measured offline. The generator then varies
material inside it without knowing why. In v3 the controller commands explicit feature targets.
The generator composes new material that satisfies them and reports what it achieved. Control,
logging and plant identification all run on realised features.

---

## 6. Hierarchical musical planning

### 6.1 Units

| Unit | Definition | Duration | Today | v3 role |
|---|---|---|---|---|
| Bar | 4 beats (4/4) | 1.8–3.7 s | Grid of all ops | Event generation |
| Phrase | 4 bars | 7–15 s | Bars 1–4, 5–8; phrase ends marked | Motif statement / answer unit |
| Segment | 8 bars = 2 phrases | 14.8–29.5 s | Render, control and crossfade unit | Unchanged: one `ControlIntent` each |
| Section | 1–4 consecutive segments sharing a role and arrangement state | 15 s – 2 min | Absent | Unit of structure requests and development |
| Material block | v2 term: 3 visits of a cell sharing `base_seed` | 3 visits | `arrangement.BLOCK_LEN=3` | **Retired** (replaced by section and composition) |
| Composition | One identity: key, tempo, harmonic material, hook/motif set, groove family, palette | ~2–6 min | Nearest: block | Unit of identity; ends by supervisor switch or composition-length policy |
| Session | Whole listening period (baseline + phases) | 10–15 min live | Runner session | Contains several compositions; carries cross-composition memory |

Nesting: session ⊃ compositions ⊃ sections ⊃ segments ⊃ phrases ⊃ bars. Section boundaries are
segment boundaries; segment boundaries are phrase boundaries.

### 6.2 How physiology reaches each level

| Level | Planner decides | Physiological influence | Timescale |
|---|---|---|---|
| Session | Permitted styles, dramaturgy (from protocol phases), cross-composition memory | None directly (protocol) | Session |
| Composition | New identity when started; tempo, key, material | **Timing** via supervisor (reachability, residency); content seeded and history-aware | Minutes |
| Section | Role sequence (build, peak, breakdown, return) | **Structure requests** (if enabled), else development clock | 1–2 min |
| Segment / phrase | Intensity realisation, phrase-level development operator | **Intensity targets** every segment | 15–30 s |
| Bar / note | Events satisfying targets and rules | Via targets only | Bars |

### 6.3 Planning under unpredictable control

| Option | Reproducibility | Musical structure | Responsiveness | Compute | Verdict |
|---|---|---|---|---|---|
| Fixed open-loop schedule (previous) | Path-independent | Good, but blind to control | Low | Nil | **Control condition only** |
| Fully reactive re-planning each segment | Deterministic given intents | Fragmented | High | Low | Reject |
| **Receding-horizon plan with commitment levels** | Deterministic given intents; revisions logged | Good: sections persist, revisions only at boundaries | High at segment level | Low | **Adopt** |
| **Depth-1 conditional branches** for the next segment | Same | Every branch is a valid continuation | Immediate | 3–4 realisations + renders per segment, inside the 15–30 s window | **Adopt with the above** |
| Deep branching trees (depth ≥ 2) | Same | Marginal gain | Same | Exponential | Reject |

**Commitment levels:**

| Element | Commitment |
|---|---|
| The playing segment | Immutable |
| The next segment | Chosen from branches at decision time |
| The current section's role | Stable unless a structure request or switch arrives at a boundary |
| The composition identity | Stable unless the supervisor switches |

A section grammar guarantees that every request maps to a legal musical move:

- **up:** the next intensity level within the role, then a build;
- **down:** a sparser variant, then a breakdown;
- **hold:** variation within the role.

### 6.4 Repetition metrics that respect structure

| Metric | Measures | Desired |
|---|---|---|
| Within-composition repetition ratio | Share of bars that recur, exactly or near, inside the composition | A **band**, calibrated by listening [H] |
| Varied-repetition share | Share of recurrences that are varied, not literal | High |
| Longest literal run | Bars or phrases of exact repeat | Capped [Eng: ≤ 2 phrases] |
| Unplanned cross-composition recurrence | Hook, harmonic loop or groove from a *different* composition within T minutes | 0 (baseline 2/3 in the pop:3 dwell) |
| Planned returns | Tagged recalls of earlier material | Reported, not penalised |
| Exposure dose | Minutes of a given hook, loop or groove in the last W minutes | Capped [H] |
| Novelty rate × magnitude by level | Changes per minute at surface, phrase, section and composition level | Matches the declared budget |
| Structural clarity | Self-similarity block contrast (Foote, 2000) | Sections visible |
| Session predictability | Information content of events under a model trained on the session so far (IDyOM-style; Pearce, 2005) | Not flat and low over long windows [H] |

---

## 7. Revised implementation roadmap

All v3 work lives in new modules behind opt-in flags (`--generator v3`, `ControllerConfig`
flags off by default) under a new versioned protocol. Locked versions, fixtures and Experiment 1
stimuli stay unchanged. Numeric thresholds are [Eng] unless cited.

### Phase 0: Definitions, corrections, baselines (no behaviour change)

- **Work:**
  - unit definitions (6.1) and structure-aware metrics (6.4) in `session_diversity_metrics.py`;
  - controller baseline: `simulate_session_v2.py --hr plant` (engineering only, synthetic plant)
    and replay of recorded HR traces, measuring tracking error, time in band, genre switches per
    minute and saturation time;
  - hip-hop baseline diversity;
  - design of the similarity calibration study.
- **Dependencies:** none.
- **Tests:** the metrics are deterministic; their unit tests pass.
- **Accept:**
  - a baseline report including the **controller-driven** genre-switch rate (replacing the
    scripted 40/58);
  - corrected repetition metrics reproduce the erratum decomposition (6 planned + 2/3 unplanned).

### Phase 1: Interface and logging on the locked system (behaviour-identical)

- **Work:**
  - `control_intent.py` (dataclasses);
  - an adapter mapping each `ControlDecision` to a `ControlIntent`;
  - `SessionComposer` info → `RealizationReport` with MIDI features and predicted `u`;
  - append-only trace columns;
  - `replay_session.py`;
  - optional timing probe of live audio feature measurement on the rendered buffer.
- **Dependencies:** phase 0.
- **Tests:**
  - existing identity fixtures and `test_session_v2_integration.py` stay green;
  - plan invariance (`df.groupby('segment_idx')[plan_cols].nunique().max() == 1`);
  - schema append-only.
- **Accept:**
  - 3 scripted sessions: every pre-existing column and the enqueued audio byte-identical;
  - replay from the intent log reproduces 100% of MIDI shas.

### Phase 2: Hip-hop v3 vertical slice, offline (`--generator v3`, hip-hop only; other genres fall through to v2c)

- **Why hip-hop:**
  - it has the worst repetition (1 base segment per tier per session) [R];
  - it already spans `u` 0.17–0.86, which enables single-style closed-loop tests with existing
    `u` values;
  - it is prevalent and danceable in the target population [P];
  - it retires a cell built to echo two named tracks;
  - its frozen music21 path is the slowest generator (0.8–1.1 s) [R].
  - Pop follows as the test of harmonic richness and intensity widening.
- **Work:**
  - mechanisms (3.2);
  - intensity map `u → feature targets` calibrated to the existing hip-hop rungs at a fixed
    composition tempo;
  - receding-horizon planner;
  - contract;
  - branch generation.
  - **pretty_midi only** (no music21).
- **Dependencies:** phase 1 interface.
- **Tests:**
  - determinism and replay identity;
  - structural predicates: backbeat skeleton, chord tones on strong beats, ranges, choke rule;
  - contract compliance over a `u_target` grid (0.15–0.90 by 0.05) × 30 seeds;
  - **intent-response tests**: a `u` step changes the targeted features in the commanded
    direction within one segment; a structure request yields the requested role at the next
    boundary;
  - novelty-budget adherence;
  - copy check;
  - latency test.
- **Accept:**
  - 0 structural violations;
  - predicted `u` within `tie_band_e/2` of target in ≥ 95% of segments;
  - intensity map monotone with predicted span ≥ 0.6;
  - on rendered audio (developer machine), hip-hop `u` monotone and within 20% of the measured
    hip-hop:1–5 span;
  - 30 compositions with no shared hook or loop identity;
  - unplanned cross-composition recurrence 0 in simulated sessions;
  - realise + verify p95 < 0.3 s per branch; all branches rendered before the decision.

### Phase 3: Intent-matched listening validation of the slice (open loop)

- **Work:** the same recorded and scripted intent sequences drive v2c-hip-hop and v3-hip-hop.
  External listeners (sample size by power analysis) rate:
  - perceived repetition over 5-minute excerpts;
  - typicality and coherence;
  - EGQ urge-to-move and pleasure;
  - the direction of intensity steps.
- **Dependencies:** phase 2.
- **Accept** (margins pre-registered):
  - v3 non-inferior on typicality, coherence and EGQ;
  - v3 superior on perceived repetition;
  - intensity steps perceived in the commanded direction.

### Phase 4: Controller extension (config flags, off by default)

- **Work:**
  - per-style intensity candidates;
  - `w_switch`, minimum dwell, hysteresis, capability envelopes (reachability);
  - RLS on achieved `u`;
  - structure requests from the error trend (protocol-gated).
- **Dependencies:** phases 1–2.
- **Tests:**
  - every existing controller test unchanged (`tests/test_energy_order.py`,
    `test_faults_fixed.py`, the 5 regression gates);
  - new unit tests: no oscillation or limit cycles, dwell honoured, reachability switch fires
    after the hysteresis count.
- **Accept** (synthetic plant + replayed traces; engineering only):
  - tracking RMSE and time-in-band **non-inferior** to the locked controller [Eng: margin +10%];
  - fewer style switches;
  - no reversal of requested moves.

### Phase 5: Engineering closed-loop runs (developer, versioned engineering protocol)

- **Work:** hip-hop-only v3 sessions, then v3 hip-hop with v2c fallback styles for the extremes.
  Log movement once the IMU exists.
- **Dependencies:** phases 2–4; sensing track S.
- **Accept:**
  - 0 underruns over 3 × 15 min;
  - commanded-vs-achieved feature fidelity as in phase 2;
  - controller behaviour as simulated;
  - signal-quality rejection rate reported by intensity level.

### Phase 6: Second style (pop), then others

- **Work:**
  - harmonic grammar informed by pop/rock corpora;
  - intensity widening at fixed tempo;
  - capability envelopes measured on audio;
  - re-measure a v3 energy table with the **v1 z-parameters frozen** (so `u` stays comparable);
  - supervisor across styles.
- **Accept:** as phase 2 per style; global ladder audit with more than one listener.

### Phase 7: Formal studies

Section 8.5 ablations; closed-loop vs yoked vs sham; still vs free movement; haptics as a
crossed factor.

### Track S (parallel): sensing and confounds

- Add an IMU channel.
- Complete the `SENSOR_NOTES.md` noise-floor and motion-artifact TODOs.
- Separate the haptic motor supply from the PPG supply.
- Validate HR against a reference device.

**Accept:** artifact rate vs movement characterised; haptic-on PPG uncontaminated.

---

## 8. Evaluation framework

### 8.1 Software and technical

- Determinism: replay identity across processes and machines with the same sf2 sha.
- Timing: decision-to-ready p99; underruns.
- Continuity: loudness step and beat-grid alignment at joins; clicks.
- Generator correctness: structural predicates; property-based tests.
- Feature contracts: per-segment residuals; TOST per intensity level.
- Fallback-rate balance across `u`.

### 8.2 Musical (automated and expert)

- Harmonic coherence: rule checks and expert ratings.
- Rhythmic quality: groove-feature profiles vs corpus ranges; kick–bass lock-in.
- Motif development: detection of operators and recurrence.
- Genre typicality: expert ratings and distance to style feature ranges.
- Meaningful diversity: the section 6.4 metrics, calibrated by 8.3.

### 8.3 Perceptual (human data required)

- Similarity calibration with triads.
- Perceived repetition and fatigue over 15–20 minutes: periodic liking, boredom and
  "want to continue" probes; state boredom (Fahlman et al., 2013).
- Danceability: EGQ (Senn et al., 2020), plus measured movement as a separate variable.
- Coherence and engagement.
- Perceived energy, separately from perceived calmness.

### 8.4 Closed-loop

| Question | Measure |
|---|---|
| Does physiology still shape the music? | Variance of realised intensity, structure and identity features explained by intents; lagged dependence of feature changes on HR error (present in closed loop, absent in yoked) |
| Do intended adaptations occur? | Commanded vs achieved features per segment |
| Is control maintained or improved? | HR tracking RMSE, time in band, settling, overshoot vs the locked baseline, with **yoked** (same audio, no contingency) and **sham** (statistically matched random intents) controls |
| Is it arousal? | Not inferable from HR alone; add self-report (SAM), movement and respiration covariates; interpret only with yoked and sham contrasts |

### 8.5 Ablations

1. **Music only (open loop, intent-matched):** the same intent sequences drive

   | Arm | Generator |
   |---|---|
   | A0 | Locked v2c |
   | A1 | v3 mechanisms without the planner (intensity only) |
   | A2 | A1 + hierarchical development |
   | A3 | A2 + structure requests |

   Identical control trajectories isolate the music.

2. **Controller only:** locked v2c generator with (B0) locked `LadderMPC` vs (B1) the extended
   controller. This isolates control from vocabulary.
3. **Factorial in simulation** (generator {v2c, v3} × controller {locked, extended}); live only
   for the decisive contrasts (A0+B0 vs A3+B1, each with yoked controls).
4. **Switching free vs penalised** (Q5).
5. **Novelty budget fixed vs controlled** (exploratory).

Computational diversity is never taken as proof of perceptual improvement. HR change is never
taken as proof of arousal regulation.

---

## 9. Critical comparison

### 9.1 The seven recommendations

| Recommendation | Verdict | Reasoning |
|---|---|---|
| 1. Vocabulary expansion as the primary fix for repetition | **Adopt, modified** | Primary for cross-composition repetition, but realised through generative mechanisms, not pools. Not sufficient alone: within-composition development and controller switching behaviour also drive fatigue and fragmentation |
| 2. Separate identity from intensity | **Adopt as decomposition and interface; reject as an independence assumption** | Couplings are measured, compensated and verified; structure may adapt through section requests |
| 3. Two-timescale supervisory + fast control | **Adopt, modified** | Implemented inside `LadderMPC` via config. Switching remains available (reachability, protocol). Judged on non-inferior tracking, not on musical arguments |
| 4. Hierarchical planning | **Adopt, modified** | Receding horizon with commitment levels and depth-1 branches; levels are data structures; physiology enters each level at its own timescale |
| 5. Deterministic history-aware generation instead of path independence | **Adopt** | With intent logs, replay tests, change attribution and novelty budgets. The open-loop schedule is kept as a control condition |
| 6. Real-time generation under physiological constraints | **Adopt** | Feasible at segment rate with speculative branches. Sub-segment adaptation postponed |
| 7. Single-genre prototype | **Adopt, modified** | Hip-hop first (reasons in phase 2), pop second, preceded by the interface phases (0–1), because the interface is the main risk |

### 9.2 Advantages and disadvantages vs the previous proposal

| | Previous | Revised |
|---|---|---|
| Physiological influence on composition | Intensity + genre only | Intensity, section trajectory and composition timing, all typed |
| Confound control | Strong by construction | Strong by measurement: budgets, attribution, yoked controls. **More analysis burden** |
| Reproducibility | Path-independent | Intent-conditional; replay required; cross-participant cell comparisons weaker |
| Diversity mechanism | Bigger pools | Generators + operators; certification becomes statistical |
| Risk | Lower engineering risk | Higher: generator coherence, planner complexity, controller tuning. Mitigated by the vertical slice and opt-in flags |
| Time to first evidence | Long (all genres) | Shorter (one style end to end) |

### 9.3 Assumptions, hidden dependencies, confounds and risks

- **Control authority is unproven.** The prior gain is 2.5 bpm across the full `u` range, the
  dead zone 1.5 bpm, and the evidence is n = 1 up-regulation runs. Better music may not show as
  better control; studies need power analysis.
- **The `u` scale is defined by the v1 cells** (z over 35 cells). v3 needs frozen normalisation
  parameters or `u` drifts.
- **MIDI→audio predictors are soundfont-specific.** Pin the sf2 sha; re-measure after any change.
- **Movement** (finger PPG, no IMU) and **haptic coupling into PPG** threaten the HR signal
  exactly in the conditions of interest.
- **Novelty → orienting responses.** With history-aware planning and structure requests,
  novelty timing can become physiology-dependent. That is acceptable only when it is declared,
  budgeted and logged, or disabled in confirmatory protocols.
- **Proxy outcomes in the corpus.** Spotify danceability is proprietary; the groove proxy was
  weak (R² 0.18).
- **Single-listener tuning.** The ladder order and rock gain were set by ear (n = 1).
- **Feature targets can be met unmusically.** Structural predicates and listening gates guard
  against it.
- **The project rule "no new controller classes"** shapes the controller design. If the
  supervisor grows complex, revisit the rule explicitly with the researcher rather than work
  around it.

---

## 10. Final recommendation

**Smallest high-value steps, in order:**

1. **Phase 0.** Correct the metrics, measure the controller-driven genre-switch rate, set the
   hip-hop baselines. This is cheap and replaces two numbers that were wrong or ambiguous.
2. **Phase 1.** `ControlIntent` / `RealizationReport` plus replay on the locked system,
   behaviour-identical. It makes every later change measurable and replayable, and it is where
   "physiology influences composition through declared channels" becomes code.
3. **Phase 2.** The hip-hop v3 slice: the largest repetition gain, already the full intensity
   range, and the first end-to-end proof that the controller can drive genuinely new
   composition.
4. **Track S** in parallel: an IMU and a separated haptic supply, because the HR signal is the
   foundation of every closed-loop claim.

**Avoid or postpone:**
- neural generation;
- MIMO feature control;
- RL or bandit genre selection;
- sub-segment adaptation;
- deep branching;
- maximising diversity;
- treating HR as arousal;
- any change to locked stimuli outside a versioned protocol.

---

## References

New in this revision (see the previous document for the rest):

- Burgoyne, J. A., Wild, J., & Fujinaga, I. (2011). An expert ground truth set for audio chord recognition and music analysis. *Proc. ISMIR*.
- Gabrielsson, A., & Lindström, E. (2010). The role of structure in the musical expression of emotions. In P. N. Juslin & J. Sloboda (Eds.), *Handbook of Music and Emotion* (pp. 367–400). Oxford University Press.
- Gillick, J., Roberts, A., Engel, J., Eck, D., & Bamman, D. (2019). Learning to groove with inverse sequence transformations. *Proc. ICML*. (Groove MIDI Dataset, CC BY 4.0.)
- Gomez, P., & Danuser, B. (2007). Relationships between musical structure and psychophysiological measures of emotion. *Emotion*, 7(2), 377–387.
- Hespanha, J. P., & Morse, A. S. (2002). Switching between stabilizing controllers. *Automatica*, 38(11), 1905–1917.
- Liberzon, D. (2003). *Switching in Systems and Control*. Birkhäuser.

Reused: Bradley (2009); Collins & Laney (2017); de Clercq & Temperley (2011); Fahlman et al.
(2013); Foote (2000); Hurley, Martens & Janata (2014); Matthews et al. (2019); Pearce (2005);
Schoenberg (1967); Senn et al. (2020); Sokolov (1963).

## Appendix: how the new numbers were obtained

- **Energy sensitivity:** `energy_table_v1.json` at `65f2338`; `E = Σ w_f (x_f − μ_f)/σ_f` with
  population SD over the 35 table cells (as `energy_scores`); `Δu = Δ(E) / (E_max − E_min)` over
  the 27 cells of `energy_order_by_ear.json`. E span 3.212.
- **Controller facts:** `control.py` (`ControllerConfig`, `LadderMPC.step`, `_update_gain`,
  `_predict_hr`); `run_session_v2.py` (HR window, decision, haptic goal).
- **Corpus facts:** `groovegen_project/data/data_dictionary.csv`, row and column counts of the
  two CSVs, `sophia/RESULTS_MEMO.md`, `sophia/BED_FEATURE_PROFILE.md`,
  `sophia/genre_analysis_results.json`, `song_excerpts/urls.txt`.
- **Erratum decomposition:** derived from `arrangement.BLOCK_LEN = 3` and the dwell measurement
  in the previous document (Appendix A2).
