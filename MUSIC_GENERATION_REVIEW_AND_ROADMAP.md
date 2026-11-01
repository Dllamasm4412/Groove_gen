# GrooveGen music generation: architecture review and development roadmap

Status: review and proposal only (2026-10-30). No source code, stimuli, ladder, tests or
research artifacts were changed. This file is the only addition.

> **Revised 2026-11-01.** `MUSIC_GENERATION_V3_ARCHITECTURE.md` supersedes the architecture
> (sections 3.2, 5 and 6) and the roadmap of this document. The diagnosis in sections 1–2 still
> stands. Errata (details in the revision, section 1.3):
> 1. The phase 2 target "≤ 2/9 chord-cycle recurrence" is impossible with 3-visit blocks; at
>    least 6/9 repeats are planned. The correct measure is unplanned cross-block recurrence
>    (baseline 2/3).
> 2. "40 of 58 boundaries change genre" came from a scripted path, not from the controller.

**What was reviewed.** Release `pilot-zero-v2c-locked` (commit `65f2338`), which lives on
branch `experiment-music-ratings`. It is **not** on `main` (main stops at `650e66a`), so paths
below refer to that commit. The Experiment 1 rating study (`dc2db77`, same branch) was read
for its design only.

**Evidence labels** used throughout:

| Label | Meaning |
|---|---|
| **[C]** | Confirmed by reading the code at `65f2338` |
| **[R]** | Confirmed by running the locked code (MIDI only, scratch environment that reproduces the identity fixtures: `test_composer_identity.py`, `test_generator_boundary.py`, `test_session_composer.py`, 25 passed). Scripts in Appendix A |
| **[P]** | Reported by the project's own documents (`V2_CONTEXT.md`, `LIVE_GENERATION_PLAN.md`, release notes) |
| **[H]** | Hypothesis; needs computational analysis or listening/physiological data |
| **[E]** | Recommendation supported by published evidence |
| **[Eng]** | Engineering judgement, not evidence |

---

## 1. Current system architecture

### 1.1 Pipeline

```
LadderMPC (control.py) --(genre, tier)--> SessionSegmentSource (session_generator.py)
   -> SessionComposer.compose(genre, tier, visit_idx)          (composer/arrangement.py)
        schedule(): base_seed = H('base', stim, genre, tier, block, j, GEN_VERSION)
                    var_seed  = H('var',  stim, genre, tier, visit, GEN_VERSION)
        generate_segment(genre, tempo, density, 8, base_seed)    (composer.py, frozen v1)
        vary(): up to 12 drum candidates, R4 novelty <= 0.97     (composer/variation.py)
        energy_guard.check() vs the base segment                 (composer/energy_guard.py)
        develop_engine.select() via genre policy (pitch only)    (composer/develop_engine.py, dev_*.py, motif.py)
   -> SymbolicSegmentRenderer (FluidSynth CLI, Musyng_Kite, MASTER_GAIN_DB -2.5)
   -> CrossfadeMixer(fade_bars=0.25, 'tail_out') -> player
```

### 1.2 Levels that already exist (the system is already hierarchical, implicitly)

| Level | What exists | Where | Nature |
|---|---|---|---|
| Session | One `SessionComposer` per session; per-cell visit counters; hiphop/rock key lock; controller stall rotation for variety | `session_generator.py`, `arrangement.schedule`, `control.LadderMPC._rotation_pick` | Seeds and counters, **per cell**; the variety rotation lives in the controller |
| Composition / block | 3 visits share `base_seed` (progression, bass, voicing, groove family) | `arrangement.BLOCK_LEN = 3` | A seed into the v1 composer, not an explicit plan |
| Phrase / segment | Drum form templates T1–T3, phrase ends at bars 4 and 8, pitch development roles (theme, answer, recall, sequence) | `variation.py`, `dev_*.py` | Post-hoc transforms of a finished segment |
| Bar / note | Count-, velocity- and voice-neutral drum ops; pitch-only line edits | `variation.COST`, `develop_engine.MAX_PITCH_SHIFT = 2.0` | Rich constraint machinery |

### 1.3 What each genre can produce (base material space) [C][R]

From `composer.py` and the frozen cells; counts from 400 seeds at tier 3 (Appendix A1).

| Genre | Harmony | Bass | Drums | Lines | Distinct base drum layers | Notes |
|---|---|---|---|---|---|---|
| calm | i.i.d. random choice from 6 chords, 2 bars per chord | none | one fixed grid | piano: 1 note per bar | 1 | `_gen_calm`; `GENRE_CFG['calm']['include_drums']=False` yet drums are written |
| lofi | `_gen_rnb` with softened velocities | as rnb | as rnb, every other hat dropped | as rnb | 4 | `_gen_lofi` wraps `_gen_rnb` |
| rnb | 4 orderings of the same 4 chords, 1 per bar, 4-bar loop x2 | 4 patterns | 4 families | keys dyad on beat 3 + random stabs at d >= 0.5 | 4 | labelled "D minor", but F#m7 / Dsus2 / Em7 / Cadd9 use both C and C# |
| pop | 4 orderings of the same 4 chords (3 distinct cycles under rotation), 4-bar loop x2 | 4 patterns | 4 families, **density ignored** | lead: per-bar chord-tone walk, random 0–2 sixteenth jitter, no motif | 4 | `_apply_pop_drums` takes no density |
| latin | 4 orderings of the same 4 chords, every track loops 4 bars x2 | 1 tumbao figure (4 contents, one per progression) | clave + 4 conga variants | no melody | 8 | odd bars break clave (1.4) |
| hiphop | tonic pedal; one fixed 2-bar RH hook; 5 keys | fixed | fixed bitmap per tier | lead doubles the hook | 1 | **5 distinct segments in 400 seeds; key lock leaves 1 per tier per session** |
| rock | 4 progressions x 5 keys | from shared patterns | fixed bitmap per tier | tier-5 solo overlay | 1 | 20 distinct segments in 400 seeds |

### 1.4 Musical-correctness findings [C][R]

- **Duplicate cells.** For the same seed, `calm:1 == calm:2`, `lofi:1 == lofi:2`, `rnb:1 == rnb:2`,
  and `pop:1 == pop:2` (60/60 seeds identical MIDI each). Density 0.15 and 0.35 fall on the same
  side of every density threshold in those generators. The project recorded this for calm only.
  The live ladder therefore has 27 rungs but 23 distinct cell distributions. The energy
  differences between those pairs are seed-sampling noise.
- **Latin clave.** `_gen_latin` alternates `[0, 3, 6, 10, 12]` (a complete 3-2 son clave on a
  16th grid) with `[4, 6, 10, 13, 15]` on the next bar. The second pattern is neither 2-3 son
  (`[2, 4, 8, 11, 14]`) nor a rotation of 3-2. Every odd bar is out of clave. Clave is the
  defining structural constraint of the genre.
- **Labels and config.** `GENRE_CFG` keys ("D minor" for lofi/rnb) and `include_drums` (calm) do
  not match what is generated. This matters as soon as any planner reads them.
- **Hip-hop identity.** `hiphop_cell.py` is written "in the exact frame of" two named commercial
  tracks. If listeners recognise them, familiarity enters as a confound: familiarity strongly
  modulates emotional and reward responses (Pereira et al., 2011). There is also an originality
  question for research stimuli. [H] for recognisability; test it.
- **Timbre.** Rock renders with GM 26 (Musyng_Kite "Jazz Guitar"), chosen by ear [P]. Genre
  typicality has not been checked with listeners.

### 1.5 Control, energy and real time [C][P][R]

- Energy score `E` = z-weighted LUFS 0.40, drum onset rate 0.25, tempo 0.20, centroid 0.10,
  flux 0.05 (`music_features_measured.ENERGY_WEIGHTS`). Ladder order was adjusted by four
  replicated blind comparisons (developer, n = 1) [P].
- **74% of the ladder's energy variance is between genres** [R]. Within-genre spans: pop 0.040,
  lofi 0.021, calm 0.000 (all inside the tie band `tie_band_e = 0.042`), rnb 0.089, latin 0.119,
  rock 0.492, hiphop 0.683.
- On a monotone climb, **19 of 26 adjacent rungs change genre**. In a simulated 18-minute
  up / top-rotation / down session, **40 of 58 segment boundaries were genre changes** [R].
  That path includes a 9-segment top-of-ladder rotation, which alternates genre by design; the
  climb from lofi:3 alone changes genre on 17 of 21 steps.
- Adaptation happens once per 8-bar segment (14.8–29.5 s). The runner wakes `render_lead_s =
  3.0` s before the queue drains. Compose plus render averages 0.85 s, with a 1.44 s maximum (RC2) [P].
  MIDI-only composition in this review's container took a median of 0.8 s and a maximum of 1.1 s
  for latin and hiphop, and 0.03–0.33 s for the other genres [R]. Headroom is about 1 s.
- Generator boundary: the generator sees only (genre, tier, visit_idx) plus `stim_seed`; tests
  enforce this (`tests/test_generator_boundary.py`). This is a real strength.

### 1.6 What to preserve

- Determinism, provenance, versioned seeds (`H(...)` with salts), and byte-identity fixtures
  for every released generator.
- The generator boundary and the "variation is not a hidden actuator" principle (plan §5, A6).
- Measure-then-decide discipline: op attribution, measured level tables, certification against
  rendered audio, explicit residuals instead of quietly loosened thresholds.
- The fallback chains: candidate, gentle pass, previous material, base.
- The decision to keep neural models out of the live path, and the careful claims language.

---

## 2. Root causes of musical repetition

### 2.1 Confirmed by the implementation [C][R]

1. **The base vocabulary is tiny, and harmony is genre-invariant.** In lofi, rnb, pop and latin,
   every segment is one fixed chord set as a 4-bar, one-chord-per-bar loop played twice. There
   are 2–3 distinct cycles under rotation per genre. Hip-hop has one hook per tier per session.
   Rock has 4 progressions.
2. **Variation is post-hoc and surface-level by design.** Drum ops are count-, velocity- and
   voice-neutral, and only bars 4 and 8 plus "A'" bars change. Pitched development is
   pitch-only: onsets, durations, velocities and counts stay fixed, and register moves at most
   2 semitones. The features listeners most plausibly use to say "same song" (chord loop, groove
   family, line rhythm, arrangement, tempo, key) are exactly the features held constant within a
   block.
3. **The definition of "controlled" freezes the old generator's incidental variance.**
   Certification envelopes come from the v1 generator's own seed spread (`certify_stimuli.py`,
   `v1_wide`). Where v1 never varied something, the allowance is zero or near zero: latin
   pitched register, calm/hiphop/rock/latin on-beat ratio SD 0, rock pulse allowance 0.001 [P].
   Then any new material fails. The construct-level tolerance the project already has
   (E within `tie_band_e`/2) is the right kind of rule. The per-feature v1 envelopes are what
   lock repetition in.
4. **Memory is per cell, and material is re-drawn on every tier step.** `base_seed` hashes the
   tier, so pop:3 to pop:4 changes progression rotation, bass pattern and possibly drum family.
   No cell knows what a neighbouring cell played. In simulation, lofi and rnb share chord
   cycles, because they share `_gen_rnb`.
5. **Windowed anti-repetition with a small pool cycles at period window + 1.** Calm drums cycle
   with period 5 under `REPEAT_WINDOW = 4` [P]. Before `rotation_no_repeat`, controller rotation
   ping-ponged latin2/rnb3 [P]. Memory does not create variety when the pool is small; it only
   sets the cycle length.
6. **There is no structure above 8 bars.** Each segment starts at bar 1 with no pickup,
   transition or section role. The only long-range structure is the 3-visit block.
7. **Duplicate cells** (1.4) mean some "different conditions" are the same music.

### 2.2 Suggested by outputs and measurements [R][P]

- Dwelling 10 segments (about 2.5 min) in pop:3 or latin:2: only 2 distinct chord cycles. In 8 of
  9 segments the chord cycle (any rotation) had been heard in the previous 4 minutes. The bar-1
  drum pattern had too, in 7–8 of 9.
- Simulated 18-minute session: about half of all segments repeat a chord cycle and a groove heard
  in the previous 4 minutes, while 40 of 58 boundaries change genre. **Two problems coexist:
  sameness when the controller dwells, discontinuity when it moves.**
- Developer listening: latin2 "sounded the same all the time"; calm repeats after about 4 min;
  hiphop melodic development sounded "meaningfully less repetitive" [P].
- Within-block drum similarity is R4 0.92–0.99 [P]. The ops change little of the bar.

### 2.3 Hypotheses that need data [H]

- **H1.** Perceived "same song" is driven mainly by harmonic loop, groove family, tempo/key and
  timbre, not by the micro-variations v2 adds.
- **H2.** Frequent genre switching makes sessions feel fragmented without making them feel
  varied, because each genre's small pool recurs.
- **H3.** Material changes that coincide with control steps (tier or genre change) produce
  transient orienting responses (Sokolov, 1963; Bradley, 2009) that confound HR-based control.
- **H4.** Over 15 minutes, harmonic-loop recurrence contributes more to fatigue than drum-bar
  recurrence.

---

## 3. Critical assessment of the three proposals

### 3.1 Hierarchical generation (session / composition / phrase / bar): **adopt, modified (thin)**

| Question | Assessment |
|---|---|
| Would it improve the system? | Yes, but only through what the levels **contain**. Adding layers does not add variety; a richer composition level and explicit phrase roles do. |
| Already hierarchical? | Yes (1.2). Each level is a seed or a post-hoc transform, not a plan. The composition level is the weakest. |
| What does it solve? | Continuity across tier steps (one "song" can intensify); long-range returns; coordinated change across instruments (today drums and pitched development vary independently); section contrast. |
| Complexity and overhead? | Computing a plan is negligible if it is precomputed. The real risk is code complexity. Mitigate by making levels **data structures** (`MaterialSpec`, roles), not separate generators or agents. |
| Highest-value levels? | Composition (material identity and pools) > phrase/section roles > session schedule > bar (already strong). |
| Separate modules? | New: a material module (specs and pools) and a small schedule module. Phrase roles live inside the realizers and `variation.py` / `develop_engine.py`. Bar level stays as is. |
| Better architecture? | Not fundamentally. "Plan, then realize, then check a feature contract" is the right family; end-to-end neural generation or a runtime constraint solver are worse for control and latency (section 4). |
| Coherence and control? | Top-down: the material fixes harmony, so bass and lines agree, and roles change layers together. Controlled features attach to the intensity realization and are verified by the contract, independent of material identity. |
| Real-time feasible? | Yes. Plans are built at session start; realization is about 0.03–1 s per segment. Add speculative pre-composition (phase 6). |

### 3.2 Session-level diversity / musical memory: **modify; reject reactive closed-loop memory as the generation mechanism**

Why reactive, history-driven avoidance is the wrong primary mechanism:

1. **Path dependence on physiology.** If segment content depends on everything played before
   it, it depends on the controller's path, which depends on HR. That would break today's
   invariant ("a cell's k-th visit is identical whatever route", `session_generator.py`) and turn
   novelty into a physiology-dependent stimulus property.
2. **Cycling.** With a small pool, windowed avoidance cycles at window + 1 (2.1, item 5). Greedy
   "most dissimilar to the last item" selection ping-pongs between extremes. [Eng]
3. **Quality risk.** Maximising distance pushes selection toward atypical, pool-edge material.
   Liking is related to typicality and complexity in an inverted-U fashion (Berlyne, 1971;
   Chmiel & Schubert, 2017). [E]
4. **It treats the symptom.** The cause is pool size and how material is keyed (2.1).

What to do instead [Eng]:

- **An open-loop, precomputed `MaterialSchedule`** per genre family, built from `stim_seed` at
  session start. It covers the material space by design: shuffle-bag without replacement over
  factorised levels, a minimum recurrence distance, and **planned returns** of earlier themes for
  familiarity (repetition at controlled distances; Huron, 2006; Margulis, 2014). It is indexed
  by the genre's block count, not the cell's. It is enumerable, so it can be pre-certified like
  plan §6.4.
- **Factorised identities with co-prime pool sizes** (for example 7 harmonic loops x 5 groove
  families x 9 motifs). Each factor recurs at a predictable, tunable distance. Full combinations
  repeat only after 315 blocks.
- **A `SessionMonitor`** that computes similarity to the session history for logging and
  evaluation only. It never feeds generation decisions.
- Keep the per-cell exact-repeat rejection as a safety net.

Answers to the specific questions:

| Question | Answer |
|---|---|
| How should similarity be represented? | As factor IDs by construction (loop, groove family, bass figure, motif, arrangement mask, key, tempo), plus continuous distances for evaluation (section 7). |
| How much history? | All of it. It is a few KB per session. The design question is recurrence policy (minimum distances in minutes, planned returns), not storage. The thresholds are [H] and need calibration (phase 0). |
| Could diversity hurt quality or genre identity? | Yes, if it maximises distance. Use quality-gated, typicality-weighted coverage instead. |
| Feasible live? | Trivially (IDs, a precomputed schedule). |
| Independent of experimental parameters? | Yes, if it acts only on flexible factors, is open-loop, and keeps the novelty rate equal across cells (generalised A6). |
| How to prevent cycling? | Pool size well above any window, shuffle-bag coverage, co-prime factor cycles, planned rather than emergent recurrence. |

### 3.3 Controlled / flexible / structural separation: **adopt, modified**

The repository already has a version: Locked / Bounded / Freely variable (plan §3). Three
modifications:

1. **Roles are per experiment, not per feature.** Syncopation can be held in one protocol and
   manipulated in another. Represent this as `FeatureSpec(name, extractor, role ∈ {controlled,
   held, flexible, measured}, target, tolerance, rationale)` in a versioned protocol file.
2. **Tolerances come from the construct, not from v1 seed spread.** Base them on the ladder's
   resolution (the existing `tie_band_e` rule), perceptual discrimination where known (loudness
   on the order of 1 dB; tempo a few percent), and the experiment's hypotheses. Keep the v1
   envelopes as diagnostics. Verify with equivalence tests (TOST) against pre-registered margins.
3. **Couplings are measured and compensated, not just forbidden.** Generalise the existing level
   tables (`hook_levels.py`, `levels_*.py`) and `dev_latin.ACCOMP_EFFECT` into a coupling table:
   the measured effect of each flexible decision on each controlled feature. Then **re-balance**
   (velocities, ghost-note counts, layer gain) to hit targets, instead of rejecting every
   candidate that moves a feature.

**Hard vs soft.** Hard: structural rules (clave, scale membership on strong beats, voice ranges,
protected skeleton, phrase boundaries, programs within the genre palette, no vocals) and
controlled-feature tolerances after compensation. Soft: diversity, typicality, role preferences,
voice-leading smoothness. Soft rules are ranking costs, as the candidate ranking does today.
**Violations** go through the existing generate, repair, test, fallback chain. Every violation is
logged. Fallback rates must be balanced across cells, because an uneven fallback rate is itself a
novelty confound.

**Closed loop.** The controller sets targets in controlled-feature space (today a cell or `u`).
The contract guarantees the generator honours them. Flexible features follow the open-loop
schedule. Physiology never enters the generator.

**Not independent: examples to encode as couplings.** Harmonic complexity interacts with groove
(Matthews et al., 2019). Added layers and staggered entrances raise perceived groove (Hurley,
Martens & Janata, 2014). Loudness drives perceived arousal (Dean, Bailes & Schubert, 2011). Pitch
choice changes loudness through Musyng_Kite sample-zone level jumps of up to about 7 dB [P].

### 3.4 Danceability, musical energy and emotional arousal

**Proxies in use today** [C]:

| Construct | Proxy in the system | Status |
|---|---|---|
| Musical energy | `E` = LUFS 0.40, drum onset rate 0.25, tempo 0.20, centroid 0.10, flux 0.05 (rendered audio); ladder `u` | Controlled (one dimension, via cell choice) |
| Danceability | None as a control variable. `pulse_clarity` (onset-envelope autocorrelation), drum on-beat ratio (±0.05) and the protected skeleton act as guards. Experiment 1 asks "want to move or dance" | Held (partly), measured; not controlled |
| Arousal | HR from PPG is the controlled output; the generator never sees it (`test_generator_boundary.py`) | Kept outside the generator, correctly |

**Where they are entangled** [C][R]:

- The ladder is one-dimensional. Tempo, loudness, density, timbre and genre move together, and
  groove-relevant features co-vary without control. Pulse clarity ranges from 0.595 (latin:1) to
  0.946 (rock:2). Syncopation is a fixed property of each genre's patterns.
- Tempo is inside `E`. It is also the most consistent musical driver of HR and respiration
  (Bernardi et al., 2006; Koelsch & Jäncke, 2015) and a strong groove factor. An `E`-to-HR
  relation therefore cannot be attributed to non-tempo features without a design that separates
  them.
- Experiment 1's "calming or relaxing" item mixes valence and arousal.
- The code itself does not equate the constructs: the generator boundary and the claims
  language are sound.

**Independent manipulation is not possible today**: there is one control dimension, and within-
genre levers are weak (1.5).

**Correlated vs independently controllable**:

| Feature | Expected relation | Use |
|---|---|---|
| Tempo | Correlated with energy, groove and HR | Treat as correlated |
| Loudness | Mainly perceived intensity / arousal (Dean et al., 2011) | Energy lever |
| Syncopation | Inverted-U relation to groove (Witek et al., 2014; Matthews et al., 2019); at a fixed onset count, roughly orthogonal to energy | **The most promising lever to dissociate groove from energy** |
| Harmonic complexity | Interacts with groove (Matthews et al., 2019) | Coupled; keep moderate in high-groove cells |

**Recommended representation**: three layers, kept apart in code and in claims.

1. **Musical features (measured exactly, generator-side).** Tempo, per-role onset rates,
   syncopation index, pulse clarity, LUFS, centroid, harmonic rhythm, novelty events. This is
   what the system can claim to **control**. Code: a `features.py` registry used by the contract
   and the trace.
2. **Perceptual predictions (versioned models fitted to listener ratings).** Predicted perceived
   energy and predicted groove, each with its validity statistics. They are hypotheses, and are
   labelled as such wherever the controller uses them. Code: `perceptual_models/<version>.json`.
3. **Physiological responses (HR, HRV).** Measured in experiments; never an input to the
   generator.

**How to validate.** Use within-genre factorial stimuli (tempo x syncopation x loudness x
density). Rate them for perceived energy, EGQ urge-to-move and pleasure, felt arousal (SAM) and
liking, and fit mixed models to estimate the couplings. Then run open-loop (yoked) physiological
sessions. Only after that can mappings from layer 1 to layers 2 and 3 be claimed.

### 3.5 Real-time biofeedback: slow structure vs fast parameters

**Actual capabilities** [C][P]:

- One decision per 8-bar segment (14.8–29.5 s); a 3.0 s render lead; about 1 s worst-case
  headroom.
- Changes happen only at segment boundaries, through a quarter-bar `tail_out` join.
- HR is polled at 1 Hz with a 10 s median.

**Assessment.** Separating slow structure from fast parameters is appropriate, with "fast"
defined as **per segment**:

| Layer | Timescale | What changes |
|---|---|---|
| Slowest | Session | Session plan and genre |
| Slow | Genre material block, about 1–3 min | Material identity |
| Fast | Per segment, 15–30 s | Intensity: layers, per-role density, velocity |

Sub-segment (per-bar) adaptation is not justified yet. The HR estimate's effective bandwidth
(10 s median) and cardiac response latencies already match segment-level updates, and shorter
units would add more seams [Eng, consistent with the project's own timescale argument]. The real
problem is that today's fast control action (the cell) also changes slow structure (genre and
material).

**Requirements met by the recommended architecture**:

- **Real-time parameter changes.** Intensity per segment; material is unchanged within a genre
  block.
- **Smooth transitions.** A transition-in at the start of the incoming segment (the decision is
  known by then); staggered entrances; session keys chosen close to the ladder neighbours'
  keys. Same-tempo joins already keep the beat grid.
- **Stable groove.** Tempo, kick/snare skeleton, pulse clarity and syncopation stay controlled
  features while intensity changes.
- **Boundary scheduling.** Segment boundaries are 8-bar phrase boundaries. Material changes
  happen only at block boundaries.
- **Responsiveness vs quality.** The MPC's one-rung step is kept. With wider within-genre spans
  (phase 5), a step changes intensity instead of identity.
- **Latency.** Speculative pre-composition (phase 6). A streaming renderer is a later option for
  tempo ramps and sustained notes across boundaries.

---

## 4. Alternative approaches

| Approach | Fit here | Trade-offs | Recommendation |
|---|---|---|---|
| Extend the rule-based / procedural system | High | Inspectable, deterministic, certifiable; needs musical authoring effort | **Primary** |
| Probabilistic chord / figure models from corpora (e.g. de Clercq & Temperley, 2011 for rock) | High, offline | Larger idiomatic pools; still seedable | **Use offline to build pools**, freeze as data |
| Generative grammars (Steedman, 1984; Rohrmeier, 2011; Quick & Hudak, 2013) | Medium | Strong for tonal phrase syntax; loop-based dance genres are additive or layered (Butler, 2006; Spicer, 2004) | A small **layer / section grammar**, not tonal harmonic grammar |
| Constraint-based composition (Pachet & Roy, 2011; Herremans & Chew, 2017) | Medium-high, offline | Hard and soft constraints, tension profiles; too slow and unpredictable for per-segment runtime | Offline motif / progression generation |
| Motif / transformational techniques (Schoenberg, 1967; Collins & Laney, 2017) | High | Gives melodic identity and development, **including rhythm** | **Extend `develop_engine` beyond pitch-only** |
| Quality-diversity search (MAP-Elites; Mouret & Clune, 2015) | Medium, offline | Builds pattern libraries spanning e.g. syncopation x density with other features held | Phase 7+, for factorial groove stimuli |
| Statistical / neural (Music Transformer, MusicVAE, FIGARO) | Low now | Data and licensing, memorisation risk, weak exact control, latency; the project rules exclude it live | **Postpone.** At most offline proposals curated into frozen pools |
| Hybrid neural-symbolic | Low now | Same as above plus complexity | Postpone |

---

## 5. Recommended architecture

### 5.1 Name and principle

**Plan, realize, verify, with material identity separated from control intensity.** Material
identity is slow, scheduled and open-loop. Intensity is per segment, controlled and verified.
Bar-level variation stays as is.

### 5.2 Diagram

```
 session start: stim_seed, protocol file (FeatureSpec roles + tolerances), GEN_VERSION v3
   |
   v
 MaterialSchedule (new, composer/material_schedule.py)            SLOW, open loop, precomputed
   genre family -> [material_id per genre block], coverage + planned returns
   |
 LadderMPC (unchanged at first) --(genre, tier)-->
   |
   v
 SessionComposer v3 (composer/arrangement.py, new GEN_VERSION; v2a/v2c paths kept)
   |- MaterialSpec    = pool[genre][schedule[family][genre_block]]  identity: loop, bass figure,
   |                                                                  groove family, motif, palette
   |- SectionRole     = roles(pos in genre block)                    establish / develop / vary / return
   |- IntensityParams = intensity[genre][tier]                       FAST: density, layer mask,
   |                                                                  per-role onset targets, velocity
   |- realize_<genre>(material, role, intensity, var_seed) -> MIDI   (new realizer modules)
   |- variation.vary / develop_engine (rhythm-aware motif ops added)  bar level, existing
   |- FeatureContract.check + rebalance (new feature_contract.py)     hard rules, controlled targets
   |- fallback chain (existing pattern)
   v
 SymbolicSegmentRenderer -> CrossfadeMixer -> player                  unchanged
   |
   +-- SessionMonitor (new, log only): factor IDs, similarity, novelty events -> trace (append-only)
```

### 5.3 Components, responsibilities and files

| Component | Responsibility | Files |
|---|---|---|
| `MaterialSpec` + pools | The composition identity: key, harmonic loop (chord symbols **and harmonic rhythm**, 4- or 8-bar), bass figure, groove family, motif (rhythm + contour), arrangement palette. Pools are versioned JSON data, sha-pinned. | new `composer/material.py`, `composer/pools/<genre>.json`; reuse `chord_pitches`, `voicings.py`, `patterns.py` |
| `MaterialSchedule` | Path-independent per genre family: block n of genre g has a fixed material. Coverage, minimum recurrence distance, planned returns. lofi and rnb form one family with disjoint pools. | new `composer/material_schedule.py` |
| Realizers | `realize_<genre>(material, role, intensity, var_seed)`. They replace `_gen_*` for v3 only. `composer.py` and the frozen cells stay byte-identical for v1/v2. | new `composer/realize_*.py` |
| Intensity table | What a tier means inside a genre: layer mask, per-role onset targets, velocity profile, tempo where the protocol allows. Makes tiers distinct (fixes duplicates) and can widen within-genre spans (phase 5). | new `composer/intensity.py`; `segment_renderer.TIER_TO_DENSITY` kept for v1/v2 |
| Section roles | Coordinated, multi-instrument development over a material's visits: layer entrances and exits, rhythmic motif variation, harmonic variant, fills, transition-in. | realizers + `variation.py` + `develop_engine.py` |
| `FeatureContract` | Generalises `energy_guard.BOUNDS` and certification gates: FeatureSpec roles, construct tolerances, structural predicates, coupling-table prediction, rebalance. | new `feature_contract.py`, `protocols/<version>.json`, `couplings_<sf2sha>.json` |
| `SessionMonitor` | Similarity and novelty logging; evaluation only. | new `session_monitor.py`; append-only columns in `trace_schema.py` |
| Speculative pre-composition | Compose and render down / hold / up candidates during playback; commit only the chosen one. Pure functions, so no state advances until commit. | `run_session_v2.py` (opt-in flag) |

### 5.4 Information boundary

Generator inputs become (genre, tier, genre_block_idx, pos_in_block, stim_seed, protocol
version). Today's inputs are (genre, tier, visit_idx) and are also path-derived counts, so this
is the same kind of information. **Change in the invariant:** "the n-th block of genre g has
the same material on every path; its realization depends on the tier chosen." Yoked replay stays
exact. Extend `tests/test_generator_boundary.py` to cover the new invariant.

### 5.5 Failure modes and unwanted behaviour

| Risk | Mitigation |
|---|---|
| Pools drift from genre identity | Typicality listening checks per pool item; structural predicates per genre (e.g. clave invariant) |
| Factor combinations clash (a bass figure against a harmonic rhythm) | Compatibility tables; hard predicates |
| Compensation flattens musical dynamics | Cap the magnitude of rebalancing; log every adjustment |
| Novelty co-varies with `u` (richer pools in some genres) | Equalise schedule novelty rates; generalise A6 to all factors |
| The schedule cycles | Pool size well above recurrence distance; coverage metric in certification |
| Tempo jumps within one "song" (hiphop/rock tier tempos) | Accept and log, or move tempo to the slow layer; a streaming renderer could ramp it later |
| Compose time grows | Speculative pre-composition; latency budget test |
| Ladder invalidated | New version, re-measured energy table, by-ear checks with more than one listener |

---

## 6. Detailed implementation roadmap

Phases 0, 1 and 6 change no stimuli. Phases 2–5 create a new system version (`v3`). The locked
`v2c` stays selectable as the baseline condition, with identity fixtures for v1, v2a.3 and
v2c.* kept green. Numeric targets are provisional engineering targets [Eng] unless stated.

### Phase 0: Baseline and measurement harness (no stimulus change)

1. **Problem.** There is no session-level measure of repetition, and Experiment 1 rates only the
   first 4 bars of each cell's first visit.
2. **Change.** `session_diversity_metrics.py` (MIDI and audio), scripted and plant-driven
   session paths, and a baseline report for the locked v2c (stim seeds 1–3). Design a perceptual
   similarity calibration study (section 7.2).
3. **Rationale.** Changes cannot be judged without a baseline. Metric validity has to be checked
   against listeners (Müllensiefen & Frieler, 2004) [E].
4. **Files.** New tools only; reuse `stimulus_metrics.py`, `pitched_metrics.py`,
   `simulate_session_v2.py`, `music_features_measured.py`.
5. **Dependencies.** None.
6. **Musical benefit.** Indirect: tells you which factors to spend effort on (H1).
7. **Control and reproducibility.** None changed; reports are deterministic.
8. **Testing.** Determinism (two runs give identical reports); unit tests on metric functions.
9. **Risks.** Metrics that look objective but do not track perception.
10. **Success.** A baseline report (factor recurrence, distances, coverage, genre-change rate,
    within-segment loop structure), and the calibration study run or pre-registered.

### Phase 1: Feature contract in audit mode (no stimulus change)

1. **Problem.** "Controlled" is operationalised as the v1 seed spread, which forbids new
   material (2.1, item 3).
2. **Change.** `feature_contract.py` + `protocols/pilot_zero_v2c.json` (reproduces today's
   gates) + `protocols/v3_draft.json` (construct tolerances). Run both on v2c outputs. Assemble
   the coupling table from existing level tables and attribution results. Record a decision for
   every feature's role and tolerance, with its rationale.
3. **Rationale.** Separates the scientific definition of the condition from the old generator's
   accidents. Makes held vs manipulated explicit per protocol.
4. **Files.** New `feature_contract.py`, `protocols/`; read-only use of `energy_guard.py`,
   `certify_stimuli.py`.
5. **Dependencies.** Phase 0 metrics.
6. **Musical benefit.** Unlocks room for variation in the later phases.
7. **Control.** Clarifies it; no stimulus change.
8. **Testing.** Fidelity: the v2c protocol reproduces current certification verdicts exactly.
   Identity tests unchanged.
9. **Risks.** Tolerances loosened without justification. Every change needs a written rationale
   and researcher sign-off.
10. **Success.** Fidelity 100%; a signed tolerance table; a list of features whose v1 envelope
    is narrower than the construct tolerance.

### Phase 2: v3 material vocabulary, realizers and correctness fixes (opt-in `--generator v3`)

1. **Problem.** Tiny pools; duplicate cells; broken clave; pitch-only lines with no rhythmic
   identity.
2. **Change.**
   - Per-genre pools:
     - 12–24 harmonic loops, including 8-bar loops and varied harmonic rhythm (two chords per
       bar, or two bars per chord);
     - 6–12 bass figures with compatibility to each harmonic rhythm;
     - several groove families per groove-feature level;
     - motif rhythm templates.
   - Realizers that read `MaterialSpec`.
   - An intensity table that makes every tier distinct.
   - Fix the clave so it is consistent across bars.
   - Correct key labels; separate lofi and rnb pools.
   - Remove calm velocity clipping.
3. **Rationale.** Root cause 1 is vocabulary. Corpus-informed pools keep material idiomatic
   (e.g. rock progressions from de Clercq & Temperley, 2011) [E for idiom].
4. **Files.** New `composer/material.py`, `composer/pools/*.json`, `composer/realize_*.py`,
   `composer/intensity.py`. `arrangement.py` gains a v3 path behind `GEN_VERSION`. **No edits to
   `composer.py`, `hiphop_cell.py`, `rock_cell.py`.**
5. **Dependencies.** Phase 1 contract (to know what may move).
6. **Musical benefit.** The largest single reduction in sameness: harmony, bass and groove
   finally vary between blocks.
7. **Control.** New condition: re-measure the energy table, rebuild the ladder, re-certify,
   pre-certify the enumerable set (plan §6.4).
8. **Testing.**
   - New identity fixtures for v3; structural predicates (clave, scale, ranges) at 0 violations.
   - Contract TOST per cell.
   - Generalised A6.
   - Phase 0 metrics vs v2c.
   - Listening by at least 3 people beyond the developer.
9. **Risks.** Genre typicality drops; harmonic complexity reduces groove (Matthews et al., 2019).
   Keep complexity moderate in high-groove cells.
10. **Success (provisional).**
    - In the pop:3 dwell simulation, segments repeating a chord cycle heard in the last 4 min
      fall from 8/9 to at most 2/9.
    - Structural violations 0; all cells inside contract tolerances.
    - Compose time p95 under 1.0 s.
    - Typicality ratings not lower than v2c (equivalence margin pre-set).

### Phase 3: Genre-level material schedule and tier/material decoupling

1. **Problem.** Per-cell memory; tier steps re-draw material (2.1, item 4); session-level
   recurrence is uncontrolled.
2. **Change.** `MaterialSchedule` per genre family, indexed by genre block. The tier selects
   intensity only. Planned returns. `SessionMonitor` logging. Generator boundary test extended.
3. **Rationale.** The control action (tier) then changes only intended features. Diversity is
   designed, not emergent. Repetition is controlled for familiarity (Margulis, 2014) [E for the
   role of repetition; parameters are Eng].
4. **Files.** New `composer/material_schedule.py`, `session_monitor.py`; `arrangement.py`;
   `session_generator.py` (visit counting per genre); `trace_schema.py` (append columns).
5. **Dependencies.** Phase 2 pools (with small pools, decoupling would reduce variety).
6. **Musical benefit.** A song can build across tier steps; returns create recognisable form.
7. **Control.** Removes novelty-on-step confounds within a genre. Genre changes still carry
   novelty; log them.
8. **Testing.**
   - Path-invariance tests for the new invariant.
   - Recurrence-distance distributions; coverage over 15 and 30 min.
   - Novelty balance across `u`.
9. **Risks.** Hiphop/rock tempo changes within a song; interleaved genres sound like "two songs
   alternating".
10. **Success.**
    - Within-genre tier steps keep material 100%.
    - Unplanned recurrence never closer than the set minimum.
    - Generalised A6 passes.

### Phase 4: Section roles, coordinated development and transitions

1. **Problem.** Development is pitch-only and per instrument. There is no arrangement arc and
   no transition device.
2. **Change.**
   - Roles (establish, develop, vary, breakdown or lift, return) that drive layer masks
     (staggered entrances), rhythmic motif variants (displacement, augmentation, call and
     response) within contract tolerances, harmonic variants within the pool, and fills.
   - A **transition-in** at the start of the incoming segment (the outgoing audio is already
     rendered when the decision is made).
   - A MIDI pulse-clarity / syncopation predictor, so rhythmic edits are checked before
     rendering.
3. **Rationale.** Form in these genres is largely additive or layered (Butler, 2006; Spicer,
   2004). Staggered entrances increase groove and engagement (Hurley et al., 2014) [E]. Note that
   this is also a coupling: roles must be balanced across cells.
4. **Files.** Realizers, `variation.py`, `develop_engine.py` + policies (new `RHYTHM_OPS`), new
   `composer/roles.py`.
5. **Dependencies.** Phases 2–3.
6. **Musical benefit.** Intentional-sounding development and smoother boundaries.
7. **Control.** Roles change groove-relevant features, so their schedule must be identical for
   every cell and logged.
8. **Testing.** Contract per role; role balance across `u`; listening for coherence.
9. **Risks.** Roles become a hidden actuator; breakdowns dip energy.
10. **Success.**
    - Every role keeps controlled features in tolerance.
    - Coherence ratings no lower than v2c; similarity ratings lower.

### Phase 5: Within-genre intensity range and ladder re-measurement (protocol amendment)

1. **Problem.** 74% of energy variance is between genres, so control means genre switching
   (40/58 boundaries in simulation).
2. **Change.** Widen within-genre energy spans through layers, per-role density, velocity
   profile, and possibly tempo (as hiphop and rock already do). Re-measure; rebuild the ladder;
   retune the controller offline.
3. **Rationale.** Lets the controller act mainly on intensity, with genre on a slower clock.
   That realises the slow/fast separation (section 3.5).
4. **Files.** `composer/intensity.py`, `music_features_measured.py --table`, `ladder.py`,
   `run_pilot_zero.build_live_ladder`, `control.ControllerConfig` (rotation may become
   unnecessary).
5. **Dependencies.** Phases 2–4.
6. **Musical benefit.** Fewer jarring genre jumps; longer coherent stretches.
7. **Control.** Changes the plant and the ladder, so it needs a new protocol version.
8. **Testing.** Simulated sessions (`--hr plant`) and ladder audits with more than one listener.
9. **Risks.** Energy and danceability decouple differently per genre.
10. **Success.**
    - Every genre with 3 or more tiers spans at least 2x `tie_band_e`.
    - Simulated genre-change rate halves at equal tracking error.

### Phase 6: Real-time robustness (can run in parallel after phase 0; required before phase 2 goes live)

1. **Problem.** About 1 s of worst-case headroom against the 3.0 s render lead.
2. **Change.** Speculative pre-composition and render of the down / hold / up candidates
   during playback, plus the rotation-band cells while the controller is in a stall (rotation
   can jump up to 4 rungs). Commit only the chosen one; visit counters advance only on commit.
   Add a latency budget test.
3. **Rationale.** The MPC moves at most one rung, and rotation picks come from a small known
   band, so a handful of candidates cover every decision. This turns a 3 s budget into about
   15–30 s.
4. **Files.** `run_session_v2.py` (opt-in), `session_generator.py` (a pure `peek` without
   advancing counters).
5. **Dependencies.** None.
6. **Musical benefit.** Enables heavier realizers safely.
7. **Control.** None, as long as committed content is identical to what non-speculative
   composition would produce (test it).
8. **Testing.** Byte-identity of committed segments vs the sequential path; 3 x 15-min runs with
   0 underruns.
9. **Risks.** CPU contention on the laptop during PPG processing.
10. **Success.** Segment-ready p99 below 50% of the render lead; 0 underruns.

### Phase 7: Validation studies

These are described in section 7.2. Run the similarity calibration early (phase 0). Run the
v2c-vs-v3 session study after phase 4. Run physiological checks of novelty events (H3) before
any closed-loop claims about v3.

---

## 7. Musical and scientific evaluation framework

### 7.1 Automated measures

| Target | Measures | Caveat |
|---|---|---|
| Harmonic diversity | Chord-loop IDs; chord-sequence edit distance; tonal pitch-space distance (Lerdahl, 2001); harmonic-rhythm entropy | Symbol distance does not equal perceived distance |
| Rhythmic diversity | Drum-pattern distances weighted by metric position (PAD/SAD, Gómez-Marín et al., 2015; swap distance, Toussaint, 2004); groove-family IDs | Note-level Jaccard (R4) overweights sparse bars [P] |
| Melodic diversity | Rhythm + contour motif distance (hybrid measures, Müllensiefen & Frieler, 2004), transposition-invariant | Validate against listeners |
| Structure | Bar-level self-similarity matrices and novelty curves (Foote, 2000); scape plots (Müller & Jiang, 2012); loop period | |
| Between compositions | Factor-ID recurrence distance; intra-/inter-set feature distributions (Yang & Lerch, 2020) | |
| Session repetition | Coverage per 5 min; recurrence-distance distributions; entropy of material use | |
| Coherence | Rule-violation counts (scale on strong beats, ranges, clave, phrase alignment); expectation-model IC (IDyOM; Pearce, 2005) as a diagnostic | IC is a proxy, not quality |
| Genre consistency | Distance to genre feature prototypes; structural predicates | Needs listener typicality ratings |
| Danceability-related preservation | Tempo (exact), pulse clarity, syncopation index (Longuet-Higgins & Lee, 1984; polyphonic variant as in Witek et al., 2014), on-beat ratio, per-role onset rates | These are proxies; groove itself is a listener construct |
| Controlled-parameter stability | Equivalence tests (TOST) per cell against pre-registered margins; fallback-rate balance; generalised A6 | |

### 7.2 Listening and physiological studies (human-subject evidence required)

| Study | Design | Measures |
|---|---|---|
| Similarity calibration (phase 0) | Triads ("odd one out") or pairwise ratings on segment pairs that differ in one factor at a time (loop, groove, motif, arrangement, timbre); ordinal embedding / MDS | Which factors drive perceived similarity (H1); correlation of metrics with perception |
| Coherence and typicality | Blind paired comparisons v2c vs v3 at matched cells; Bradley-Terry (reuse `gate_widget/scoring.py`) | Coherence, "sounds intentional", genre typicality, recognition of known songs (hiphop) |
| Danceability | EGQ: urge to move and pleasure scales (Senn et al., 2020); optional spontaneous movement or tapping (Janata et al., 2012; Hurley et al., 2014) | Equivalence at matched controlled features |
| Engagement and fatigue | 15–20 min sessions, within subjects, counterbalanced order, different stim seeds; periodic probes every 2–3 min (liking, boredom, "want to keep listening"), end-of-session state boredom (Fahlman et al., 2013); optional free-stop time | Trajectories over time, v2c vs v3 |
| Novelty events and physiology | Open-loop (yoked) playback; event-locked HR around material changes vs control steps | Orienting responses (H3); needed before closed-loop claims |

**Construct separation in ratings.** Experiment 1 asks "want to move or dance" and "calming or
relaxing". "Calming" mixes valence and arousal. Add perceived energy or intensity, felt arousal
(SAM; Bradley & Lang, 1994), and liking as separate items. Perceived and felt emotion differ
(Gabrielsson, 2002).

**Baseline.** The locked v2c is the reference condition; v1 bank is a lower anchor. Freeze the
baseline renders and manifests before any v3 work, as the project already does for Experiment 1.

### 7.3 Regression tests to keep and add

- **Keep:** `test_composer_identity.py`, `test_develop_identity*.py`, `test_generator_boundary.py`,
  `test_session_v2_integration.py`, `test_energy_order.py`, plan invariance, and the five
  regression gates.
- **Add:**
  - v3 identity fixtures;
  - structural-predicate property tests (clave, scale, ranges);
  - contract TOST per cell;
  - schedule coverage and recurrence tests;
  - the new path invariant;
  - the latency budget test;
  - speculative-vs-sequential identity.

---

## 8. Additional improvements

**Essential**

- Resolve the duplicate cells: make tiers distinct, or collapse the ladder to distinct cells.
- Fix the clave and the key/config labels.
- Make the lofi/rnb relationship explicit: one family or disjoint material.
- Make `run_pilot_zero.py` refuse to start without an explicit `--generator`, or default it to
  the locked configuration. Today the default is `bank`, so it is easy to run the wrong system.
- Update stale "not used by the live runner" comments (already noted in the release notes).
- Add session-level perceptual tests (Experiment 1 covers 4 bars of first visits only).
- Check hip-hop hook recognisability.

**High value**

- Speculative pre-composition.
- Transition-in devices.
- Choose the hiphop/rock session keys to be tonally close to their ladder neighbours (calm F,
  pop C, latin Cm, lofi/rnb D), so genre jumps are less jarring.
- Reduce soundfont coupling at its source: per-note level-normalised sample zones, or a
  soundfont with smoother layers. Pitch choice would then stop moving loudness, which removes
  much of the constraint machinery. This is a new timbre, so it is a new version.
- A more typical rock guitar timbre (needs re-measurement).
- An expressive performance layer (phrase-level velocity arcs, articulation). Treat swing and
  microtiming as **controlled** genre features, not random variety: their groove effects are
  mixed (Davies et al., 2013; Senn et al., 2018). If any humanisation is used, use correlated
  (1/f-like) deviations (Hennig et al., 2011).

**Longer-term research**

- Quality-diversity libraries for factorial groove stimuli (syncopation x density with energy
  held).
- Expectation-based control of surprise and uncertainty (Cheung et al., 2019; Gold et al., 2019).
- A streaming renderer with a persistent synthesizer (no seams, tempo ramps, sustained notes
  across boundaries).
- 2-D control (energy x groove) once perceptual models are validated.
- Personalisation and preference.

**Challenged assumptions**

- **"Variation must not move any measured feature."** Gate on the construct, compensate the
  rest.
- **"More memory gives more variety."** Pool size and planning do; memory only sets the cycle
  length.
- **"Faster adaptation is better."** The HR estimate uses a 10 s median, and cardiac responses
  integrate over seconds. Segment-level (15–30 s) updates already match that bandwidth, so the
  bottleneck is continuity, not speed.
- **"Event density is monotonic in groove and in physiological arousal and safe for linear
  control"** (`groovegen_project/ARCHITECTURE_TWO_TIMESCALE.md`). For perceived groove there is
  supporting evidence within moderate ranges (Madison et al., 2011; Stupacher et al., 2016).
  Monotonic physiological effects have not been shown. Treat it as a hypothesis.

---

## 9. Risks and open questions

**Risks**

- Every stimulus change creates a new experimental condition. Keep v2c runnable and every
  artifact versioned.
- Novelty as a hidden actuator: material changes coinciding with control steps; uneven novelty
  or fallback rates across `u`.
- Orienting responses to novelty can move HR independently of energy (H3).
- Metric validity: objective difference does not equal perceived difference.
- Over-reliance on one listener: the ladder order and the rock gain were set by the developer's
  ear (n = 1).

**Open questions for the researcher**

1. Is the experimental unit the cell (genre x tier) or the energy level `u`? If `u`, material may
   vary freely inside the contract.
2. Is genre a manipulated variable, a nuisance, or a preference factor? Today it is the main
   energy lever.
3. Should the novelty rate be constant across conditions, or a manipulated factor?
4. Will participants have repeated sessions? If so, rotate stim seeds across sessions.
5. What equivalence margins define "same condition" for each controlled feature?

---

## 10. Final recommendation

**Do first:**

1. Phase 0: baseline and similarity calibration.
2. Phase 1: feature contract in audit mode, with signed tolerances.
3. Phase 6: speculative pre-composition, in parallel.

**Then the highest musical impact:**

4. Phase 2: expanded, idiomatic material pools with correctness fixes.
5. Phase 3: genre-level material schedule decoupled from tier.

**Verdicts on the three proposals:**

- Hierarchical generation: **adopt, modified**. A thin hierarchy of data structures (material,
  roles, intensity), not four generators.
- Session-level memory: **modify**. An open-loop planned schedule plus a log-only monitor.
  Reject reactive memory-driven generation.
- Controlled / flexible / structural separation: **adopt, modified**. Roles per protocol,
  construct-based tolerances, measured couplings with compensation.

**Avoid or postpone:** neural generation; closed-loop novelty optimisation; sub-segment
adaptation; maximising dissimilarity; randomised humanisation as "variety"; loosening any gate
without a construct rationale.

---

## References

- Berlyne, D. E. (1971). *Aesthetics and Psychobiology*. Appleton-Century-Crofts.
- Bernardi, L., Porta, C., & Sleight, P. (2006). Cardiovascular, cerebrovascular, and respiratory changes induced by different types of music in musicians and non-musicians. *Heart*, 92(4), 445–452.
- Bradley, M. M. (2009). Natural selective attention: Orienting and emotion. *Psychophysiology*, 46(1), 1–11.
- Bradley, M. M., & Lang, P. J. (1994). Measuring emotion: The Self-Assessment Manikin. *J. Behav. Ther. Exp. Psychiatry*, 25(1), 49–59.
- Butler, M. J. (2006). *Unlocking the Groove*. Indiana University Press.
- Cheung, V. K. M., et al. (2019). Uncertainty and surprise jointly predict musical pleasure. *Current Biology*, 29(23), 4084–4092.
- Chmiel, A., & Schubert, E. (2017). Back to the inverted-U for music preference. *Psychology of Music*, 45(6), 886–909.
- Collins, T., & Laney, R. (2017). Computer-generated stylistic compositions with long-term repetitive and phrasal structure. *J. Creative Music Systems*, 1(2).
- Davies, M., Madison, G., Silva, P., & Gouyon, F. (2013). The effect of microtiming deviations on the perception of groove in short rhythms. *Music Perception*, 30(5), 497–510.
- Dean, R. T., Bailes, F., & Schubert, E. (2011). Acoustic intensity causes perceived changes in arousal levels in music. *PLoS ONE*, 6(4), e18591.
- de Clercq, T., & Temperley, D. (2011). A corpus analysis of rock harmony. *Popular Music*, 30(1), 47–70.
- Fahlman, S. A., et al. (2013). Development and validation of the Multidimensional State Boredom Scale. *Assessment*, 20(1), 68–85.
- Foote, J. (2000). Automatic audio segmentation using a measure of audio novelty. *Proc. IEEE ICME*.
- Gabrielsson, A. (2002). Emotion perceived and emotion felt: Same or different? *Musicae Scientiae*, Special Issue 2001–2002, 123–147.
- Gold, B. P., et al. (2019). Predictability and uncertainty in the pleasure of music: A reward for learning? *J. Neuroscience*, 39(47), 9397–9409.
- Gómez-Marín, D., Jordà, S., & Herrera, P. (2015). PAD and SAD: Two awareness-weighted rhythmic similarity distances. *Proc. ISMIR*, 666–672.
- Hennig, H., et al. (2011). The nature and perception of fluctuations in human musical rhythms. *PLoS ONE*, 6(10), e26457.
- Herremans, D., & Chew, E. (2017). MorpheuS: Generating structured music with constrained patterns and tension. *IEEE Trans. Affective Computing*.
- Huron, D. (2006). *Sweet Anticipation*. MIT Press.
- Hurley, B. K., Martens, P. A., & Janata, P. (2014). Spontaneous sensorimotor coupling with multipart music. *JEP: HPP*, 40(4), 1679–1696.
- Janata, P., Tomic, S. T., & Haberman, J. M. (2012). Sensorimotor coupling in music and the psychology of the groove. *JEP: General*, 141(1), 54–75.
- Koelsch, S., & Jäncke, L. (2015). Music and the heart. *European Heart Journal*, 36(44), 3043–3049.
- Lerdahl, F. (2001). *Tonal Pitch Space*. Oxford University Press.
- Longuet-Higgins, H. C., & Lee, C. S. (1984). The rhythmic interpretation of monophonic music. *Music Perception*, 1(4), 424–441.
- Madison, G., Gouyon, F., Ullén, F., & Hörnström, K. (2011). Modeling the tendency for music to induce movement in humans. *JEP: HPP*, 37(5), 1578–1594.
- Margulis, E. H. (2014). *On Repeat: How Music Plays the Mind*. Oxford University Press.
- Matthews, T. E., et al. (2019). The sensation of groove is affected by the interaction of rhythmic and harmonic complexity. *PLoS ONE*, 14(1), e0204539.
- Mouret, J.-B., & Clune, J. (2015). Illuminating search spaces by mapping elites. arXiv:1504.04909.
- Müllensiefen, D., & Frieler, K. (2004). Cognitive adequacy in the measurement of melodic similarity. *Computing in Musicology*, 13, 147–176.
- Müller, M., & Jiang, N. (2012). A scape plot representation for visualizing repetitive structures of music recordings. *Proc. ISMIR*.
- Pachet, F., & Roy, P. (2011). Markov constraints: Steerable generation of Markov sequences. *Constraints*, 16(2), 148–172.
- Pearce, M. T. (2005). *The Construction and Evaluation of Statistical Models of Melodic Structure in Music Perception and Composition* (PhD thesis). City University London.
- Pereira, C. S., et al. (2011). Music and emotions in the brain: Familiarity matters. *PLoS ONE*, 6(11), e27241.
- Quick, D., & Hudak, P. (2013). Grammar-based automated music composition in Haskell. *Proc. ACM FARM*.
- Rohrmeier, M. (2011). Towards a generative syntax of tonal harmony. *J. Mathematics and Music*, 5(1), 35–53.
- Schoenberg, A. (1967). *Fundamentals of Musical Composition*. Faber.
- Senn, O., et al. (2018). Groove in drum patterns as a function of both rhythmic properties and listeners' attitudes. *PLoS ONE*, 13(6), e0199604.
- Senn, O., et al. (2020). Experience of Groove Questionnaire: Instrument development and initial validation. *Music Perception*, 38(1), 46–65.
- Sokolov, E. N. (1963). *Perception and the Conditioned Reflex*. Pergamon.
- Spicer, M. (2004). (Ac)cumulative form in pop-rock music. *twentieth-century music*, 1(1), 29–64.
- Steedman, M. J. (1984). A generative grammar for jazz chord sequences. *Music Perception*, 2(1), 52–77.
- Stupacher, J., Hove, M. J., & Janata, P. (2016). Audio features underlying perceived groove and sensorimotor synchronization in music. *Music Perception*, 33(5), 571–589.
- Toussaint, G. (2004). A comparison of rhythmic similarity measures. *Proc. ISMIR*.
- Witek, M. A. G., et al. (2014). Syncopation, body-movement and pleasure in groove music. *PLoS ONE*, 9(4), e94446.
- Yang, L.-C., & Lerch, A. (2020). On the evaluation of generative models in music. *Neural Computing and Applications*, 32, 4773–4784.

---

## Appendix A. Reproducing the measurements

All runs are MIDI only, on a detached checkout of `65f2338`, with `pretty_midi`, `music21` 10.5.2
and `numpy`. The identity tests above passed in that environment.

**A1. Tier identity and material space.** For calm, lofi, rnb, pop and latin, compare
`stimulus_metrics.content_sha(bar_onset_sets(pm, 8))` of `generate_segment(g, *cell_plan(g, t1),
8, s)` vs tier `t2` for seeds 0–59. Then, at tier 3 for 400 seeds, count distinct full contents,
drum layers (`'drum'`), per-bar pitch-class sequences, and per-track contents.

**A2. Session simulation.** Use `SessionSegmentSource(stim_seed=1, develop=True)` with
`next_segment(genre, tier)` along these cell paths:
- latin:2 x10;
- pop:3 x10;
- the ear-ladder climb from lofi:3, then top rotation (rock:5, hiphop:5, rock:4) x3, then the
  descent with a 4-segment rnb:3 hold;
- a pop:3–5 / hiphop:3 oscillation;
- a lofi / rnb / latin:1 low-region path.

Per segment, read the comping track's per-bar pitch-class sets (calm `pad`, lofi/rnb/pop `ep`,
latin `nylon`, hiphop `Piano`, rock `Electric Guitar`). Canonicalise the first 4 bars' chord cycle
under rotation. Count recurrences of the cycle and the bar-1 drum onset set within 240 s, and
count genre changes.

**A3. Energy decomposition.** Within- vs between-genre sum of squares of the Appendix A energy
values in `MUSIC_GENERATION_SYSTEM.md` (equal to `energy_table_v1.json` ladder `u`).

**A4. Timing.** `time.perf_counter()` around `next_segment` for 4 visits of seven cells.
