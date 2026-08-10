# GrooveGen — Project History and Decision Log

**Prepared for:** Daniel Llamas (PhD, Cognitive Science + Electrical/Computer Engineering, CU Boulder — Brain Music Lab / ATLAS) and advisors/collaborators
**Purpose:** the definitive, single-document record of everything done on GrooveGen since the Sophia secondary-analysis phase — what was found, what was built, what decisions were made, and *why* — with every claim traced back to its source document.
**Scope note:** this document synthesizes, but does not replace, the underlying memos. Where a number or result is quoted, the source file is cited inline. If a fact could not be confirmed from a source document, it is flagged explicitly as uncertain rather than invented.

---

## 1. Project overview and where it sits

GrooveGen is the generative music engine at the center of a planned **closed-loop Brain-Body Computer Interface (BBCI)** that uses rhythm to influence autonomic and sensorimotor state, plus the empirical groundwork (a secondary analysis of an existing dataset, "Sophia's dataset") that grounds its design choices. The system has two intertwined identities that the project has had to keep distinct in its own framing:

1. **A literature-grounded, parametric groove-stimulus generator** — a symbolic (MIDI-based) drum engine whose knobs (density, tempo, beat salience, syncopation, swing, microtiming) are individually calibrated against the groove-perception literature and verified by automated manipulation checks in rendered audio, originally built to supply stimuli for a planned Stage-1 listening study (`GROOVEGEN_V1_REPORT.md`, `STAGE1_PROTOCOL.md`).
2. **The generative core of a closed-loop BBCI** — a two-timescale architecture (slow neural "bed" generation + fast per-bar symbolic drum synthesis) driven by a PD (proportional-derivative) controller that reads physiological signals (PPG/GSR/respiration) and commands event density bar-by-bar, targeting emotion-regulation and motor-learning applications (`ARCHITECTURE_TWO_TIMESCALE.md`).

**Target venue and deadline.** The near-term deliverable is a **system/method paper for TEI 2027** (tentatively titled "Groove_model" in internal docs), due **July 31, 2026** (`HYBRID_IMPROVEMENT_ROADMAP.md`). The explicit framing constraint — repeated throughout the project's own documents and important enough to restate here — is that this is a **systems/methods contribution, not an efficacy claim**: no human-subject data currently exists (IRB pending as of the architecture writeup, `ARCHITECTURE_TWO_TIMESCALE.md` §9), and the paper's job is to demonstrate that the generator's knobs behave as the literature predicts and that the closed-loop architecture is engineered soundly — not that it changes anyone's heart rate or emotional state yet. This constraint recurs in §3 below and should be treated as binding on all future writing about the system.

---

## 2. The Sophia secondary analysis

### 2.1 What it is and why it exists

Before any drum-generation work began, the project ran a **secondary analysis of an existing dataset** collected by a collaborator referred to as "Sophia" — a 122-participant study whose experimental factor was `music_condition` (four levels, one of which is "sensory-motor") (`sophia/RESULTS_MEMO.md`). The analysis was not a new experiment; it re-purposed already-collected song-level audio features and Spotify metadata to answer questions that would ground GrooveGen's design before any stimuli were built.

### 2.2 The critical target-variable caveat

**This must be stated up front because it constrains every claim drawn from the analysis.** The outcome variable used throughout — `song_dance` — is **Spotify's proprietary danceability score (0–100), a song-level constant, not a human groove or dance-urge rating collected from Sophia's participants.** The data dictionary confirms there is no per-trial participant groove judgment in the dataset; `music_condition` (including its "sensory-motor" level) is the experimental factor, not a rating (`sophia/RESULTS_MEMO.md`). Every "danceability" number in this document is therefore a property of the *song*, as scored by Spotify's internal model, not a measurement of how any human participant felt while listening. `GROOVEGEN_V1_REPORT.md` explicitly calls out that the recommended upgrade path is Senn et al. 2018's external dataset (248 drum patterns, 665 human raters) to eventually claim human-groove validity (§4, and `sophia/RESULTS_MEMO.md` caveats section). All framing in the project's own documents — and in this one — respects that distinction.

### 2.3 Layer 1 — groove-proxy validation

Run against **N = 643 unique tracks** (644 with audio features, one dropped for missing `beat_consistency`), dated 2026-06-02 (`sophia/RESULTS_MEMO.md`). A theory-grounded acoustic `groove_proxy` was constructed as a unit-weighted z-sum: `beat_consistency + plp_mean + hpss_percussive_ratio + low_band_energy_ratio − z(lhl_syncopation_mean)²` (`sophia/RESULTS_MEMO.md`).

| Hypothesis | Result | Pre-reg threshold | Verdict |
|---|---|---|---|
| H1 convergent — corr(groove_proxy, song_dance) | Pearson r = 0.22 [0.10, 0.38]; Spearman ρ = 0.40 | r ≥ 0.50 | **FAIL** (Pearson); ρ moderate |
| H2 discriminant — r(dance) > r(energy) | r_dance = 0.22 > r_energy = 0.17 | — | PASS (weakly) |
| H3 Witek inverted-U — negative quadratic on syncopation | quadratic β = +0.22, p = 0.21 | β < 0, p < .05 | **FAIL** — no inverted-U |
| H4 Janata tempo band — dance peaks 110–130 BPM | inband mean 66.1 vs 56.8, **+9.3 pts**, p < .001 (n = 203 inband) | — | PASS (clear) |

(`sophia/RESULTS_MEMO.md`)

The Pearson/Spearman gap (0.22 vs. 0.40) is attributed to a handful of extreme-syncopation tracks whose quadratic penalty produces very negative proxy values, making the rank-based ρ the more trustworthy read (`sophia/RESULTS_MEMO.md`). H3 is flagged in the memo itself as "the scientifically important null" — not a disappointing result, but the central empirical motivation for the entire controlled-manipulation approach (see §2.5 below).

### 2.4 Layer 2 — acoustic predictors of `song_dance`

A 7-feature standardized OLS with 10-fold song-held-out cross-validation, with two feature-name substitutions noted because the pre-registered names were absent from `track_features.csv` (`onset_rate → onset_density`; `spectral_flux_mean → spectral_flatness_mean`) (`sophia/RESULTS_MEMO.md`).

- **Cross-validated R² = 0.18 ± 0.04**; CV Spearman ρ = 0.44 ± 0.05; in-sample adjusted R² = 0.19 (`sophia/RESULTS_MEMO.md`).

| Feature | β (std) | 95% CI | Direction |
|---|---|---|---|
| **hpss_percussive_ratio** | **+4.66** | [3.57, 5.74] | more drum-driven → more danceable |
| **low_band_energy_ratio** | **+2.97** | [1.98, 3.97] | more bass → more danceable |
| beat_consistency | +1.35 | [0.33, 2.37] | steadier pulse → more danceable |
| onset_density | +0.70 | [−0.30, 1.69] | n.s. |
| lhl_syncopation_mean | −0.57 | [−1.59, 0.45] | n.s. |
| spectral_flatness_mean | −1.23 | [−2.37, −0.10] | noisier timbre → less danceable |
| tempo_final | −2.23 | [−3.23, −1.24] | corpus-tempo-skew artifact, not a "slower is groovier" signal |

(`sophia/RESULTS_MEMO.md`)

The negative `tempo_final` beta is explicitly called out as an artifact of most corpus tracks sitting above the danceable band, not evidence against the tempo sweet-spot — H4's segmented result (above) is the correct tempo read (`sophia/RESULTS_MEMO.md`).

### 2.5 The trait-moderator null

A mixed model, `song_dance ~ condition * SM_factor + (1|Participant)`, tested whether trait sensory-motor reward sensitivity (eBMRQ Sensory-Motor subscale) moderates the sensory-motor-vs-self-relevant danceability gap. The result is described as **a clean null**: trait sensory-motor reward does **not** moderate this gap (`README.md`). This null is load-bearing for the system's design philosophy: it motivates a **stimulus-side approach** to inducing groove (build the right stimulus for everyone) rather than a **trait-gated approach** (screen or tailor by who has high trait sensory-motor reward). In other words, the null pushes design effort toward controllable features of the *music* rather than toward participant-selection or personality-based tailoring.

### 2.6 The four concrete design decisions this analysis drove

The Sophia analysis is not a side finding — it directly produced four decisions that shape the entire generator architecture described in §3–§6:

| # | Decision | Evidence driving it |
|---|---|---|
| 1 | **Validated actuators: `hpss_percussive_ratio` and `low_band_energy_ratio`** are promoted to render-stage mix biases in the symbolic generator (i.e., the system deliberately pushes percussive weight and bass energy in its mixes). | Standardized betas +4.66 and +2.97 respectively, both with 95% CIs well clear of zero, in the Layer-2 model (CV R² = 0.18 ± 0.04) (`sophia/RESULTS_MEMO.md`; `GROOVEGEN_V1_REPORT.md` §4). |
| 2 | **The Janata 110–130 BPM tempo band is adopted as the system's danceable-tempo target**, and both the bed and the Tier-1 tempo knob are designed to sit inside/near it. | H4: tracks in 110–130 BPM score +9.3 danceability points, p < .001, n = 203 inband (`sophia/RESULTS_MEMO.md`); matches Janata et al. 2012's independently published band (`GROOVEGEN_V1_REPORT.md` §2). |
| 3 | **The Witek syncopation inverted-U does NOT transfer to commercial/naturalistic audio** (quadratic β = +0.22, n.s.) — this null is treated as the single strongest motivation for GrooveGen's whole controlled-manipulation approach: the effect cannot be recovered passively from real recordings and must be induced via a **parametric, symbolic sweep**, which is exactly what the generator's knob grid provides. | H3 result (`sophia/RESULTS_MEMO.md`); explicitly called "the cleanest motivation for the whole project, not a weakness" (`GROOVEGEN_V1_REPORT.md` §4). |
| 4 | **Genre/style-fit dominates variance beyond any single structural rhythm feature** → the harmonic/instrumental "bed" should be genre-personalized per participant rather than held as an arbitrary fixed nuisance variable. | Grounded in Senn et al. 2018 (external literature, cited alongside the Sophia analysis): style bias explains R²≈0.12 of pleasure-to-move, rising to ≈0.15 with familiarity, versus syncopation and density each at only R²≈0.01 (`README.md`; `GROOVEGEN_V1_REPORT.md` §4). |

Decision 4 is the pivot point of the whole project's architecture and is expanded in §3 and §4.

---

## 3. The system architecture that resulted

### 3.1 The knob tiers

The generator exposes a small set of independently-controllable "knobs," explicitly **ordered by evidence strength** rather than treated as equally-weighted parameters (`README.md`; `GROOVEGEN_V1_REPORT.md` §2.1):

- **Tier 1 — load-bearing.** Event density (onsets/bar), tempo (107–126 BPM peak window), and beat salience/pulse clarity (the backbeat skeleton: kick 1&3, snare 2&4). These have the firmest, most consistent literature support (Madison 2011; Etani 2018; Janata 2012) *and* are the features the Sophia analysis's own results most directly support — `hpss_percussive_ratio` and tempo-band findings map onto density and tempo respectively (`GROOVEGEN_V1_REPORT.md` §2.1). These "carry the system's core groove claim" (`README.md`).
- **Tier 2 — validated demonstrations.** Syncopation (reproduces the canonical Witek inverted-U in controlled symbolic synthesis, even though it does not appear in Sophia's naturalistic-audio analysis — see §2.6, decision 3) and swing (contested/novel; several studies find quantized performs at least as well as swung/humanized timing). These are real, replicated effects but smaller and/or condition-dependent; the system demonstrates fidelity to their canonical curves without staking its central claim on them (`GROOVEGEN_V1_REPORT.md` §2.1).
- **Control variable — microtiming.** Held at 0 by default; folk wisdom that "humanized" timing feels groovier is not supported in the literature (Frühauf 2013; Davies 2013; Senn 2016), so it exists mainly to demonstrate a null (`GROOVEGEN_V1_REPORT.md` §2.1).

The practical consequence stated in the report: the genre-personalized bed plus the Tier-1 drum knobs alone constitute a defensible groove-induction system — syncopation and swing are "bonus demonstrations" the generator happens to support (`GROOVEGEN_V1_REPORT.md` §2.1).

### 3.2 The frozen genre-personalized bed and the constant-bed causal-cleanliness argument

Under the drums sits a musical "bed" (bass + chords + melody), which in the current design is **generated in the participant's preferred genre**, then **frozen** so it is bit-for-bit identical across every knob setting a given participant experiences (`README.md`). The rationale is explicitly causal: because genre is a per-participant **constant**, not a manipulated factor, any change in perceived groove within a session is attributable to the drum manipulation and not to the bed — this invariance is what the project's documents describe as making the planned listening study "causally clean" (`README.md`; `STAGE1_PROTOCOL.md` §3). Two verified properties operationalize this:

- **Time-invariant**: the frozen bed folds to a small number of distinct events per repeating cycle — the study report cites 216 notes folding to 33 distinct events per cycle for the hand-authored `hero_study` profile, with no Intro→Verse→Chorus build-up that would introduce a temporal confound over a trial's duration (`GROOVEGEN_V1_REPORT.md` §3.3).
- **Knob-invariant**: the bed's symbolic content is identical across all five-knob combinations — the bed never changes when a drum knob moves (`GROOVEGEN_V1_REPORT.md` §3.3; `README.md`).

The DL-generated genre beds (built via the Anticipatory Music Transformer, see §4) inherit the same guarantee by construction: the `dlbed` adapter quantizes the AMT output onto the 16-step grid as a `BedProfile` with `sections=None`, which routes through the same plain-loop path verified for `hero_study` (`README.md`).

### 3.3 The two-timescale genre→tempo→density cascade

The closed-loop BBCI architecture factors the system into two loops running on deliberately different clocks (`ARCHITECTURE_TWO_TIMESCALE.md` §1–§2):

- **Slow loop (offline, GPU-bound).** A neural text-to-music model (MusicGen, in the closed-loop architecture document's framing) renders a small bank of harmonic/timbral bed clips ahead of or between sessions. At playback, beds are trimmed to an integer number of bars, looped, and joined with bar-aligned **equal-power crossfades** (fade-out ∝ cos θ, fade-in ∝ sin θ, so fade_out² + fade_in² = 1 at every sample, avoiding the ~3 dB loudness dip of a linear crossfade) (`ARCHITECTURE_TWO_TIMESCALE.md` §3). This loop never sits inside the real-time control path.
- **Fast loop (online, per-bar, CPU).** A `PatternBuilder` instance builds one bar of drum/groove MIDI at a time from a `GrooveParams` configuration and renders it via FluidSynth, exposing **event density** as the primary, continuously-adjustable actuator while a backbeat anchor (snare on 2 & 4) stays structurally fixed for entrainment (`ARCHITECTURE_TWO_TIMESCALE.md` §4).
- **The bridge — a closed physiological control loop.** PPG, GSR, and respiration are reduced to arousal-relevant features (HR/HRV, SCR/SCL, breathing rate), compared to a target state, and converted by a discrete-time **Proportional-Derivative (PD) controller**, `u(k) = Kp·e(k) + Kd·(e(k)−e(k−1))/Δt`, into a per-bar event-density command (`ARCHITECTURE_TWO_TIMESCALE.md` §5.1).

**Why density, and why the cascade is genre → tempo → density in practice.** Genre is fixed per participant/session (the personalization lever, §3.2 above); within a genre, tempo sits inside the danceable band established by the Sophia analysis (§2.6, decision 2) and is otherwise held constant except when it is itself the swept/controlled variable; and **event density is the only variable the live PD controller is allowed to touch**, because it has a documented **monotonic** (not inverted-U) relationship to both perceived groove and physiological arousal, unlike syncopation (`ARCHITECTURE_TWO_TIMESCALE.md` §5.4, Abstract). This monotonicity is the explicit reason a linear PD law is control-theoretically safe here: a controller driving a non-monotonic plant input can hunt, overshoot into a reversed-response region, or oscillate, because the sign of the local gain isn't fixed — exactly the documented behavior of syncopation's inverted-U (Witek et al. 2014) (`ARCHITECTURE_TWO_TIMESCALE.md` §5.4). Syncopation is retained only as a secondary, hard-clamped "spice" parameter in [0.20, 0.40] that the controller never touches (`ARCHITECTURE_TWO_TIMESCALE.md` §5.3–§5.4).

An integral term is deliberately omitted (PD, not PID) because HRV/SCL are already computed over multi-second sliding windows (a built-in low-pass stage), and there is no persistent steady-state disturbance analogous to, e.g., gravity in a mechanical system that an I-term would classically reject (`ARCHITECTURE_TWO_TIMESCALE.md` §5.2).

**The latency/timescale-matching argument.** The bar-quantized control rate (2.0–2.5 s/bar at 96–120 BPM) is argued not to be a compromise but to be *matched* to the intrinsic multi-second time constants of the autonomic signals being regulated — HR needs a ~2 s minimum block, SCR has a 1–5 s onset latency plus 1–3 s rise time (`ARCHITECTURE_TWO_TIMESCALE.md` §6.2, §6.6). The end-to-end latency budget table places the dominant cost in physiological signal acquisition (stages downstream of acquisition sum to tens of milliseconds, roughly two orders of magnitude below one bar period) (`ARCHITECTURE_TWO_TIMESCALE.md` §6.4). **Important caveat carried forward from that document:** as of its writing, this latency table and the "hybrid" engine's own per-bar entry point were **not yet built or measured** for the now-canonical hybrid engine (`groovegen/hybrid_render.py`) — the two-timescale latency numbers cited above were measured against the `continuous.py` engine, which was subsequently superseded by the hybrid engine after an A/B test (`HYBRID_IMPROVEMENT_ROADMAP.md` Track 4, Track 6.6). Re-deriving these numbers for the hybrid path was flagged as 🔴 PAPER-CRITICAL and, per the roadmap available at time of writing, had not yet been completed.

### 3.4 The publishability constraint: system/method, not efficacy

This is stated in the architecture document and must be preserved verbatim in any future paper drafting: **heart rate (or other physiology) in this system is a SCRIPTED SETPOINT that the controller TRACKS, not a claim about the system's causal effect on emotion.** The document's own control-theoretic framing (§5) never claims the system "regulates emotion" or "lowers HR" as a demonstrated outcome — no human-subject data exists yet, and PD gains are explicitly described as "not yet empirically tuned" pending either simulation against a physiological plant model or in-session tuning data (`ARCHITECTURE_TWO_TIMESCALE.md` §9). The iso-principle (the idea that music should first match, then gradually shift, a listener's current state) is cited **only for the sign of the plant** — i.e., to justify that increasing/decreasing density should push arousal in a predictable direction — not as evidence that the system has been shown to shift emotional state in practice. Any future paper draft should frame all HR/physiology language around "the controller tracks a target trajectory" language, never "the system reduces stress" or equivalent efficacy claims, until real physiological validation exists (`ARCHITECTURE_TWO_TIMESCALE.md` §9 limitations list explicitly flags: no human-subject data, IRB pending, untuned gains, unmeasured haptic latency).

---

## 4. The genre style engine (`genre_styles.py`)

### 4.1 Why genres used to sound alike

The Anticipatory Music Transformer (AMT), the symbolic model used to generate genre beds, was trained on the **Lakh MIDI dataset with no genre labels or text conditioning** (`README.md`; `DL_BED_FEASIBILITY.md`). It is an *infilling* model — it can only embellish MIDI material that is already stylistically suggestive; it cannot turn the word "salsa" into a montuno because it has no text-conditioning pathway at all. The project's earlier seed design held **one sustained block chord per bar for every genre** — identical rhythm, voicing, articulation, and instrument regardless of the target genre — so every genre collapsed to the same flat, piped-piano sound (`README.md`). The lesson: **genre identity has to live in the seed, not in the model**, because the model has no mechanism to inject it on its own.

### 4.2 The `StyleSpec` table

`genre_styles.py` fixes this with a `GENRE_STYLES` table of `StyleSpec`s — one per family — encoding each genre's musical fingerprint, plus `build_style_seed(genre, bars=2)`, which renders a rich, multi-instrument MIDI seed that AMT then embellishes (or that is used directly on CPU) (`README.md`).

| Genre | Tempo | Voicing | Comp style | Comping / instrumentation |
|---|---|---|---|---|
| hip-hop/rap | 90 | dorian min7 open | block | sparse syncopated Rhodes stabs + sub bass |
| R&B/soul | 96 | rootless maj9 | block | lush behind-the-beat neo-soul Rhodes comp |
| pop | 120 | add9 triad | arp | funky plucky clavinet arpeggio over a syncopated fingered bass, modeled on the top-danceability pop in Sophia's data (Billie Jean / Break My Stride family) |
| latin/salsa | 180 (nominal StyleSpec anchor; see §5's note on the live tempo cap) | salsa close | block | piano montuno + bass tumbao locked to a 2-3 clave + congas + horn stabs |
| classic-rock | 94 | power chords | staccato_chug | chunky palm-muted staccato power-chord stabs with space + heavy low pedal (AC/DC "Back in Black") |
| metal | 123 | power chords | staccato_chug | relentless palm-muted minor chug on an open-E pedal (Metallica "Enter Sandman") |

(`README.md`)

The first three (hip-hop/rap, R&B/soul, pop) are the **locked study menu** — the highest-danceability, best-sampled families in Sophia's data. Latin/salsa scored highest on danceability in Sophia's data but is thinly sampled (n = 14) so it stays demo-only rather than entering the controlled study menu; classic-rock and metal are showcase/demo genres for the engine (`README.md`; `GROOVEGEN_V1_REPORT.md` §4).

### 4.3 Comp styles

`comp_style` controls how each chord articulates on the comp grid: `block` (full chord on every step), `sustain_accent` (full chord on strong beats, light stabs on weak), `arp` (one chord-tone at a time, walking the chord — the funky danceable-pop motor), and `staccato_chug` (short, hard, palm-muted stabs with silence between — "the space is the groove" for rock/metal). Pop and rock were specifically rebuilt from their real reference records: pop became a funky plucky clavinet arpeggio (not a buzzy saw lead), tuned to the top-danceability pop profile in Sophia's data, and rock became staccato muted-power-chord swagger rather than a ringing 8th-note wall (`README.md`).

### 4.4 Genre-family danceability ranking (grounding for menu selection)

A genre-family analysis of Sophia's data (`sophia/genre_analysis_results.json`, notebook 04), n = 704 unique tracks, corpus mean danceability ≈ 59.6:

| Genre family | Mean danceability | n tracks | Prevalence | Note |
|---|---|---|---|---|
| Latin | 72.0 | 14 | 2.0% | highest, but thinly sampled |
| Hip-hop/rap | 67.5 | 106 | 15.1% | high danceability, well sampled |
| R&B/soul | 65.5 | 81 | 11.5% | high danceability, well sampled |
| Pop | 61.2 | 288 | 40.9% | familiarity anchor (40% of corpus) |
| Electronic/EDM | 59.0 | — | — | |
| Country/folk | 57.3 | — | — | |
| Rock | 56.5 | — | — | |
| Jazz | 56.0 | — | — | |
| Metal/hardcore | 43.0 | — | — | |

(`GROOVEGEN_V1_REPORT.md` §4)

---

## 5. The recent audio-quality crisis and diagnosis

### 5.1 The specific complaint

The generator's audio output degraded to the point of a user-reported quality crisis, with four distinct symptoms:

1. The audio "sounds bad" after roughly the 19-second mark.
2. Drums are "off" (perceived as disconnected from the bed).
3. A latin/salsa segment "doesn't sound like latin/salsa anymore."
4. MusicGen output "doesn't resemble the reference songs" it was supposed to be anchored to.

### 5.2 The empirical windowed diagnosis

A windowed tempo/onset analysis (librosa) was run on a 39.9 s output clip (`download.wav`):

| t(s) | detected tempo | onset_rate/s | rms |
|---|---|---|---|
| 0–6 | 120 | 8 | steady |
| 9–12 | **199** (tempo-doubling artifact) | 8 | dense/ambiguous |
| 15 | 133 | 7 | **TRANSITION ZONE** |
| 18 | 88 | 5 | |
| 21 | 99 | 6 | unstable |
| 24–33 | 88–110 | 5–7 | |
| 36 | 88 | 6 | |

(`assess/DIAGNOSIS_INPUT.md`)

Key findings from this table: seconds 15–21 are the "sounds bad after 19" zone, where tempo detection swings 133 → 88 → 99 across a transition/seam — that instability is exactly where the audio falls apart perceptually (`assess/DIAGNOSIS_INPUT.md`). The latin bed reads 120 BPM then jumps to 199 BPM (a doubling artifact), with no clear salsa clave/montuno audible — MusicGen-small produced generic dense percussion rather than latin material, matching the user's complaint directly (`assess/DIAGNOSIS_INPUT.md`).

### 5.3 The four code-confirmed root causes

An architectural code audit (`assess/CODE_AUDIT.md`) traced each symptom to specific, cited lines of code:

**Root cause 1 — Prompt fidelity loss (13 MFCCs discarded).** `groovegen/profile_from_songs.py:63-77` extracts a rich per-song feature vector including **13 MFCC coefficients**, spectral centroid mean/std, HPSS harmonic/percussive ratios, onset density, and tempo. But `groovegen/prompt_from_anchor.py:184-221` (`prompt_from_anchor()`) reads only **5 keys** from that vector — none of the 13 MFCC fields are read anywhere in the file (confirmed by grep: "mfcc" appears only in a comment) (`assess/CODE_AUDIT.md`). Each of the 5 surviving features collapses to a categorical bucket via threshold functions (brightness: 3 buckets; drums: 3 buckets; busy/minimal: 2 buckets; harmonic: 3 buckets; genre: 1 of 6 fixed words). Total information surviving the pipeline: **1 continuous number (tempo) + 4 ternary/binary categorical flags + 1 of 6 genre words**, out of roughly 20 numeric features per reference song. This is architecturally why MusicGen's output cannot resemble the reference songs' actual character — the songs' spectral fingerprint never reaches the model (`assess/CODE_AUDIT.md`).

**Root cause 2 — Genre-snap heuristic + latin under-selection.** `nearest_known_genre()` (`prompt_from_anchor.py:77-128`) computes genre distance as `0.4*tempo_dist + 1.0*timbre_dist` against **hand-authored constants**, not a trained classifier — the code's own docstring admits this is "a simple nearest-centroid heuristic, not a trained classifier" because no labeled corpus was available to fit a real MFCC centroid per genre (`assess/CODE_AUDIT.md`). Compounding this, `genre_styles.py:159` sets latin's nominal StyleSpec tempo anchor at 180 BPM, but the live controller caps latin at `tempo_max=140` (`build_notebook_15.py:546`) — since `tempo_dist` is measured against the 180 BPM anchor while the actual committed tempo never exceeds ~140, **latin/salsa can be structurally under-selected by the very tempo term meant to identify it**, letting pop (120 BPM) or metal (123 BPM) out-score it at plausible tempos (`assess/CODE_AUDIT.md`). Separately, the latin prompt vocabulary contains only the generic word "latin/salsa" plus the same 4 generic descriptor slots — no occurrence of "clave," "montuno," "conga," "tumbao," or "horn stabs" anywhere in the MusicGen prompt path, even though `genre_styles.py:167` encodes exactly those words for the symbolic/MIDI seed side. That richer description was simply never routed into the text prompt — a direct, code-level explanation of "generic dense percussion, not latin" (`assess/CODE_AUDIT.md`).

**Root cause 3 — Naive `np.interp` resampling.** `notebooks/extra_transition_cell.py:47-58`'s `_resample_to_tempo()` performed classic turntable-style resampling: `np.interp` stretching/compressing the sample-time axis, which **necessarily pitch-shifts audio** (the original code's own comment admitted this: "Pitch shifts slightly with tempo, like a turntable") (`assess/CODE_AUDIT.md`). It used neither `librosa.effects.time_stretch`, a phase vocoder, nor RubberBand — none of which decouple tempo from pitch. `BAND_TARGET_BPM` hard-coded large steps (latin 128, pop 104, r&b 88, calm 72 — ratios up to ≈1.23), and because resample-induced smear scales with |ratio − 1|, these large steps are a direct, code-confirmed mechanism for the audible degradation in the second-15-to-21 transition zone identified empirically in §5.2 (`assess/CODE_AUDIT.md`).

**Root cause 4 — Drum overlay trusting a doubled detected grid.** `build_notebook_15.py:996-1054` (`build_segment_mix`) detects the bed's tempo/beat grid from the *rendered MusicGen audio* (not the symbolic target) via `hybrid_render.py`'s `analyze_bed()`, then unconditionally slices drum material using that detected grid's timestamps (`assess/CODE_AUDIT.md`). The correction logic (`_octave_snap_grid`) only fires when the detected/expected inter-beat-interval ratio exceeds 1.33 or falls below 0.75; the diagnosis's latin case (detected ~199 vs. expected ~120–140) sits at a ratio of ~1.53–1.65×, past that threshold in principle — but `_fix_octave`'s hard ceiling of `tempo_max=180` (used because no override was passed at the call site) meant a raw ~199 BPM reading only got halved once, to ~99.5 BPM, landing in the wrong octave relative to the true pulse rather than reconciling fully to the expected range. Because `build_segment_mix` unconditionally trusts the detected grid, **a doubled/mis-detected bed tempo directly causes drum bar-boundaries to land at the wrong sample offsets** — the code-level mechanism behind "drums disconnected from the bed" (`assess/CODE_AUDIT.md`).

A fifth audit finding (not a bug, but a feasibility note) confirmed that the existing per-run bed cache (`build_notebook_15.py:969-984`, keyed by `seg{i}_{genre}_{bpm}bpm.wav`) was already naming files in a way compatible with a curated cross-run library — meaning the library idea (§6) required only a surgical change to the lookup logic, not an architectural rewrite (`assess/CODE_AUDIT.md`).

---

## 6. The decision and rationale: curated bed library + RubberBand + reference-anchored prompts + symbolic-latin fallback

### 6.1 The decision

Replace on-the-fly, per-run MusicGen bed generation with a **curated, multi-BPM instrumental bed LIBRARY**, selected by nearest-BPM lookup at runtime, **re-timed with RubberBand** (pitch-preserving time-stretch) to the exact committed tempo, generated using **reference-anchored prompts**, with a **symbolic MIDI+soundfont fallback for latin/salsa** (`assess/BUILD_SPEC.md`; `assess/PATH_RESEARCH.md`).

### 6.2 Why this was chosen over the alternatives

**Alternative 1 — a bigger MusicGen model (medium/large).** Rejected as a primary path. VRAM headroom on the target Colab T4 (15–16 GB) is marginal for musicgen-large (3.3B params, ~12–16 GB, OOM risk on free T4) and musicgen-medium (1.5B, "best trade-off" per Meta but still Western-data-heavy) offers no guaranteed latin-fidelity payoff (`assess/PATH_RESEARCH.md`).

**Alternative 2 — melody or style conditioning (musicgen-melody / musicgen-style).** Considered as a secondary option, not primary. `musicgen-melody`'s `generate_with_chroma()` conditions only on melodic contour extracted from a reference clip — a poor proxy for salsa/latin identity, which lives in rhythm-section interlock (clave, montuno, tumbao), not melody (`assess/PATH_RESEARCH.md`). `musicgen-style` conditions on a short 1.5–4.5 s excerpt's timbral/style features — closer to "sound like this reference," but the window is too short to transmit a full rhythmic pattern (`assess/PATH_RESEARCH.md`). Both remain viable only as an optional secondary layer for pop/R&B/calm, explicitly scoped **out** for latin/salsa given the documented bias evidence (§6.2 below) (`assess/PATH_RESEARCH.md`).

**Why the library approach was ranked #1 instead:**

- **Reproducibility.** A fixed, inspectable library replaces stochastic per-run sampling variance — the same bed is used every time a given genre/BPM slot is requested, which is a stronger property for a reproducible research artifact than live generation (`assess/PATH_RESEARCH.md`).
- **Reviewer-auditable QC.** Every library bed passes through an explicit quality gate before being committed, and the curation step is a manual listen-and-select step a reviewer could in principle audit (`assess/PATH_RESEARCH.md`; `assess/BUILD_REPORT.md`).
- **Direct precedent in the biofeedback-music literature.** Multiple peer-reviewed adaptive/biofeedback music systems use exactly this "curated database + nearest-BPM real-time selection" pattern rather than live generation:
  - The tibial-shock running biofeedback system (Van den Berghe et al., *Scientific Reports*, 2021) used "a music database consisting of seventy-seven tracks with a clear beat in the tempo range of running," with a "smart music player" selecting by BPM and applying tempo shifts "up to ±4% of the steps per minute without pitch shift" ([Nature/Scientific Reports](https://www.nature.com/articles/s41598-021-83538-w)), switching tracks entirely for larger deviations.
  - The HEARTBEATS trail-runner system similarly modulates tempo/timbre of pre-selected material based on biosensor input rather than generating audio live ([PubMed](https://pubmed.ncbi.nlm.nih.gov/32823519/)).
  - A 2022 playback-sequencing paper explicitly buckets a music library into BPM bands and selects within the nearest band — structurally identical to this project's design ([Sensors/PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC8839467/)).
  - The D-Jogger line of research (Moens, Van Dyck et al.) established the general technique of aligning a pre-existing musical corpus's tempo to a biosignal rather than generating new material live ([Frontiers/PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC5133250/)).

  (all cited in `assess/PATH_RESEARCH.md`)

- **Sidesteps MusicGen's documented Western-data bias.** Surveys find Latin American music is part of only the ~5.7–6% non-Western share of training data underlying MusicGen-class models, versus ~94% Western-genre dominance ([arXiv "Missing Melodies"](https://arxiv.org/html/2412.04100v3); [arXiv "Music for All"](https://arxiv.org/html/2502.07328v1)) — a documented, citable structural limitation, not user error, that directly explains the salsa/clave loss finding in §5.2 (`assess/PATH_RESEARCH.md`). Targeted fine-tuning yields only modest gains (MusicGen improved ~4% on Turkish Makam per one study) and can degrade Western-genre performance in the process — not viable inside the Colab-T4, July-31 scope ([MBZUAI/NAACL summary](https://mbzuai.ac.ae/news/identifying-bias-in-generative-music-models-a-new-study-presented-at-naacl/); `assess/PATH_RESEARCH.md`). The literature's own recommendation is explicit: avoid AI generation of genres with sparse training data in favor of transparent alternatives ([arXiv "Missing Melodies"](https://arxiv.org/html/2412.04100v3)).
- **Fits the system/method (not efficacy) framing.** The library approach reframes the paper's contribution around the **assembly/synchronization system** — bed selection, pitch-preserving re-timing, and drum-layer alignment — rather than a generation-quality claim that the evidence says is currently unreliable for at least one target genre (`assess/PATH_RESEARCH.md`).

### 6.3 Time-stretching without pitch artifacts: why RubberBand

`librosa.phase_vocoder` is documented by its own authors as "a simplified implementation... likely to produce many audible artifacts," with RubberBand recommended instead ([librosa docs](https://librosa.org/doc/main/generated/librosa.phase_vocoder.html); `assess/PATH_RESEARCH.md`). `librosa.effects.time_stretch` degrades outside roughly 0.5×–2.0× rate. `pyrubberband` (the Python wrapper for the RubberBand C++ library) is tuned to work well "from tiny deviations... to very extreme stretches," with a crispness parameter (0–6), where crispness 6 suits drum-heavy material (`assess/PATH_RESEARCH.md`). Given the project's BPM band spacing (latin 105–128, pop 88–105, r&b 80–88, calm 70–80), the maximum nearest-neighbor gap is well under 20% — safely inside RubberBand's high-fidelity zone (`assess/PATH_RESEARCH.md`).

### 6.4 The latin nuance: reference-anchored prompts plus a symbolic fallback

A specific, important nuance surfaced during this decision: **naming a well-known reference artist/style in the MusicGen prompt materially improves salsa fidelity, whereas generic genre descriptors do not.** The build spec's prescribed latin/salsa prompt template names a well-known reference explicitly: *"an authentic salsa/latin groove in the style of classic Marc Anthony salsa, at {bpm} BPM, piano montuno locked to a 2-3 son clave, syncopated bass tumbao, congas and timbales, bright horn stabs, no vocals, instrumental"* (`assess/BUILD_SPEC.md`). This is a direct response to root cause 2 (§5.3) — the earlier prompt path never carried this vocabulary into the text prompt at all. Because MusicGen's training-data bias against Latin genres is a documented structural limitation that reference-anchoring alone cannot fully overcome (§6.2), the pipeline also builds a **MIDI+soundfont clave/montuno fallback**: `genre_styles.build_style_seed("latin/salsa", ...)` rendered to audio via FluidSynth, used whenever MusicGen's latin candidates repeatedly fail the quality gate (`assess/BUILD_SPEC.md`; `assess/BUILD_REPORT.md`). This gives the library a clean, honest symbolic salsa option per BPM anchor even when the neural model's output is unreliable for this genre — consistent with the literature's own recommendation to prefer transparent, non-neural alternatives for genres with sparse training data (§6.2).

---

## 7. What was built to implement the decision

Summarized from `assess/BUILD_REPORT.md`, which itself implements the specification in `assess/BUILD_SPEC.md` and addresses the four root causes documented in `assess/CODE_AUDIT.md`. All work was done in `/home/user/workspace/groovegen_project`.

### 7.1 `groovegen/bed_library.py` (new module)

A small, dependency-light, CPU-only library manager:
- `sanitize_genre(genre)` — same regex sanitizer as `generate_and_gate.py` (e.g., `"latin/salsa"` → `"latin-salsa"`, `"r&b/soul"` → `"r-b-soul"`) so library folder names match existing conventions (`assess/BUILD_REPORT.md`).
- `list_library(genre, library_dir=LIBRARY_DIR)` — lists `(bpm, path)` pairs parsed from `{bpm}bpm_{tag}.wav` filenames in a genre folder; returns `[]` if the folder is missing or empty.
- `pick_nearest_bed(genre, target_bpm, library_dir=LIBRARY_DIR)` — returns the library path whose committed BPM is closest to the target, or `None` if nothing exists for that genre.
- `retime_bed(src_path, dst_path, from_bpm, to_bpm, crispness=6)` — re-times via **pyrubberband** as the primary path, with a **librosa `time_stretch` fallback** (emitting an explicit `warnings.warn(...)`, never a silent degrade) if pyrubberband/the `rubberband` CLI is unavailable; handles mono and stereo; skips the stretch entirely when the ratio is negligibly close to 1.0.

(`assess/BUILD_REPORT.md`)

### 7.2 `build_notebook_libbuild.py` → `notebooks/LIB_build_beds.ipynb` (new, 20 cells)

A one-time, GPU-runtime notebook that populates `library/{genre}/{bpm}bpm_{tag}.wav`:
- Setup/install cell (Cython, madmom, a pinned `transformers==4.44.2` + compatible `huggingface_hub`/`tokenizers`, plus `pyrubberband` and `apt-get install -y rubberband-cli fluidsynth fluid-soundfont-gm`), a hub-version guard cell, and the MusicGen model load.
- A `BPM_ANCHORS` config (per-genre lists of target committed tempos to pre-render) and a `PROMPTS` dict of reference-anchored, richly-worded prompts per genre — including the Marc Anthony-anchored latin/salsa prompts described in §6.4, asserted at build time to contain clave/montuno/tumbao vocabulary and the phrase "no vocals" so a prompt regression would be caught immediately (`assess/BUILD_REPORT.md`).
- Candidate generation reuses the **exact same** `measure_tempo_stability` + `QualityGate` machinery already used elsewhere in the project (`QualityGate(max_beat_jitter_ms=45.0, min_pulse_clarity=0.30)`, gated on jitter and pulse clarity only — `grid_err_mean_ms` remains diagnostic-only, preserving the existing gate design) (`assess/BUILD_REPORT.md`). There is explicitly **no raw-reference-song audio fallback** anywhere — only MusicGen instrumental generation or the symbolic-latin path.
- A symbolic-latin fallback cell renders clave/montuno salsa beds via `genre_styles.build_style_seed` → `pretty_midi` → FluidSynth, used when latin candidates repeatedly fail the gate.
- Curation/keep cells print jitter/pulse/grid-error per candidate, expose a `KEEP` dict the user edits by ear, and a commit cell copies the chosen candidates into `library/{genre}/{bpm}bpm_{tag}.wav`.

(`assess/BUILD_REPORT.md`)

### 7.3 `notebooks/15_closed_loop_hr_audio.ipynb` (rebuilt from `build_notebook_15.py`) — library-first lookup

Per-segment bed resolution now tries, in priority order: **(1) library** (nearest-BPM `pick_nearest_bed` + `retime_bed` to the segment's exact committed tempo), **(2)** the existing quality-gated per-run cache, **(3)** `gen_bed` (live MusicGen) as the last resort — the exact priority order specified in the build spec (`assess/BUILD_REPORT.md`; `assess/BUILD_SPEC.md`). A `USE_LIBRARY = True` toggle was added near the existing `USE_CACHED_BEDS` flag. The old `np.interp`-based tempo resampling path (root cause 3, §5.3) is no longer used for this lookup.

### 7.4 The octave-snap drum-grid fix (root cause 4, §5.3)

`hybrid_render.py`'s `_octave_snap_grid` was rewritten after root-causing **two distinct bugs** behind the "199 BPM read for a true ~128 BPM latin bed" example:

1. The old implementation ran the fold decision inside a 2-iteration loop that re-tested its own fixed 1.33/0.75 thresholds against the ratio produced by its own previous fold. Folding once from ratio 1.55 (199 vs. 128) lands at ratio 1.29 — inside the "leave alone" window — so the loop stopped one octave short, at ~99.5 BPM, instead of the intended 128 BPM.
2. Simply widening the thresholds to also catch 1.29 does not fix this — it makes the loop **oscillate** (a corrected value gets treated as newly out-of-range and folds back the other way).

The fix makes the densify/thin/leave-alone decision **once**, directly from the raw pre-fold ratio, with no re-entrant re-test of the post-fold value. Verified test cases (`assess/BUILD_REPORT.md`):

| case | raw BPM | expected BPM | corrected BPM | note |
|---|---|---|---|---|
| audit's doubled-detection case | 199 | 128 | 99.5 | best reachable octave fold (199/128 isn't a power of 2) |
| docstring's own half-time case | 47 | 63 | 94 | matches documented intent |
| clean half-time | 64 | 128 | 128 | exact |
| clean double-time | 256 | 128 | 128 | exact |
| small genuine drift (must NOT over-correct) | 126 | 128 | 126 | left alone |
| montuno drift ~6% (must NOT over-correct) | 101 | 95 | 101 | left alone |
| montuno drift ~16% (must NOT over-correct) | 110 | 95 | 110 | left alone |

**Honest limitation, stated explicitly in the build report:** the residual ~28 BPM gap in the 199-vs-128 case is **not closeable by octave-folding alone**, because 199 and 128 are not exact octave (power-of-2) multiples of each other. The fix gets the detector to the mathematically closest reachable octave and stops the oscillation; fully pinning to 128 in that exact scenario would require `analyze_bed`'s existing `lock_tempo` parameter (unchanged, already implemented) or a better underlying beat-tracker read — both explicitly out of scope for this "minimal change" fix (`assess/BUILD_REPORT.md`).

A companion fix passes a **per-segment tempo band** (`tempo_min=max(30.0, expected_tempo*0.55)`, `tempo_max=expected_tempo*1.45`) to `hr.get_bed_info(...)` instead of relying on the function's hard-coded 70–180 default, so the underlying madmom octave-fold pre-stage stays anchored to the right neighborhood for every genre (not just the pop/rock-centric 70–180 range). The `splice_beds_downbeat_hard_cut` helper's two internal `get_bed_info` calls were updated the same way, since the function's cache key includes `tempo_min`/`tempo_max` and would otherwise silently miss the freshly-populated cache entry (`assess/BUILD_REPORT.md`).

### 7.5 `notebooks/extra_transition_cell.py` — resampling fix

The naive `np.interp`-based `_resample_to_tempo` (root cause 3) was replaced with `_retime_array_to_tempo`, which round-trips the in-memory segment mix through two temporary WAV files and calls `groovegen.bed_library.retime_bed` (RubberBand), preserving pitch while changing duration/tempo. The riser/impact synthesized-transition-FX logic was left unchanged (`assess/BUILD_REPORT.md`).

### 7.6 Verification performed

Offline (no GPU) verification confirmed: `bed_library.py`'s `sanitize_genre`, `list_library`, `pick_nearest_bed`, and `retime_bed` (via both pyrubberband and a forced librosa fallback) all behaved correctly and AST-parsed cleanly; the `_octave_snap_grid` fix passed all seven test cases in the table above, and `analyze_bed()` ran end-to-end against real synthetic click-track audio through the actual madmom backend available in the sandbox; a full segment-loop simulation (synthetic library + a `{"genre": "latin", "tempo_bpm": 121}` target) correctly selected the 120 BPM entry and produced correctly-durationed, non-silent retimed audio; and both rebuilt notebooks (`15_closed_loop_hr_audio.ipynb`, 12 cells; `LIB_build_beds.ipynb`, 20 cells after the Drive-mirror cell was added) passed `nbformat.validate()` and AST-parsing of every code cell (`assess/BUILD_REPORT.md`). **GPU-dependent paths (MusicGen candidate generation itself, and the FluidSynth CLI rendering of the symbolic-latin fallback) were reviewed carefully against existing APIs but not executed end-to-end in the sandbox, since no GPU was available there** — these remain Colab-GPU-verified-only pending an actual run (`assess/BUILD_REPORT.md`).

### 7.7 The fluidsynth-install and Drive-persistence issues surfaced during the first real Colab run

When the user actually ran `LIB_build_beds.ipynb` on Colab, two issues surfaced that are distinct from (and downstream of) the code changes above:

- **Cells 0.1–1.1 succeeded**: all 45 MusicGen candidates generated and passed through the quality gate, with only 5 candidates falling below threshold (still saved for audition); pop and R&B came out particularly clean (jitter often 3–8 ms) (per the session record of that run).
- **The FluidSynth CLI binary failed to install silently** — the install cell's errors were piped to `/dev/null`, so the failure (`fluidsynth CLI: MISSING`) was not surfaced until a diagnostic check was added. This blocks cell 1.2 (the symbolic-latin fallback), which is exactly the fallback path §6.4 depends on for latin/salsa reliability. **FIXED (2026-07-27):** the install cell in `build_notebook_libbuild.py` now runs a visible (non-silenced) `apt-get -qq update` + `apt-get -qq install -y fluidsynth fluid-soundfont-gm` (no `/dev/null` swallowing), so an install failure surfaces immediately instead of silently disabling the fallback.
- **The library is disk-only within a single Colab runtime.** Because `library/` lives on the ephemeral Colab disk, the downstream notebook (`BC_generate_and_closed_loop.ipynb`, which runs the closed-loop Part C with `USE_LIBRARY = True`) must execute in the *same* runtime session that built the library, or the library is lost on disconnect and must be rebuilt from scratch. **FIXED (2026-07-27):** `LIB_build_beds.ipynb` now has a Drive-mirror cell (1.5) that copies `library/` → `/content/drive/MyDrive/GrooveGen/bed_library/` after commit, and `BC_generate_and_closed_loop.ipynb` has an auto-restore cell (0.1b) that repopulates `library/` from that Drive location if the local folder is empty — so a curated library now survives a runtime disconnect and does not need rebuilding every session. Both builders were rebuilt and the notebooks re-validated (`nbformat.validate` + AST-parse of every code cell) on 2026-07-27.

**Status as of this writing (2026-07-27):** the fluidsynth install fix and the Drive-persistence cells are now **implemented in the builders and the notebooks have been rebuilt and validated** (`LIB_build_beds.ipynb` = 20 cells, `BC_generate_and_closed_loop.ipynb` = 22 cells, `15_closed_loop_hr_audio.ipynb` = 12 cells; all pass `nbformat.validate()` and AST-parse of every code cell). What remains is **end-to-end verification on a live Colab GPU run** — i.e., confirming the visible apt-get install actually resolves `fluidsynth CLI: MISSING`, and that a Drive-mirrored library round-trips correctly (mirror in LIB, restore in BC). Those GPU-only confirmations are the only open items on these two fixes.

---

## 8. Current status and open items

### 8.1 What must happen next, in order

1. **Curate the library once, on Colab with a GPU runtime.** `LIB_build_beds.ipynb` must be run to completion — including fixing the FluidSynth install (§7.7), running the symbolic-latin fallback cell, actually listening to and selecting `KEEP` candidates in the audition cells, and running the commit cell so `library/{genre}/{bpm}bpm_*.wav` is populated. Until this commit cell runs, `library/` is empty and `USE_LIBRARY=True` silently falls back to live generation.
2. **Then, and only then, do notebooks A (`A_setup_and_experiment_ui.ipynb`) → BC (`BC_generate_and_closed_loop.ipynb`) consume the library.** BC's Part C invokes the rebuilt nb15 logic, which now tries the library first, retimes via RubberBand to the committed tempo, and falls back to the per-run cache or live generation only if the library has nothing for that genre.
3. **A same-runtime requirement currently exists** for the library to be usable by BC without rebuilding: if the Colab runtime that built the library disconnects before the library is persisted somewhere durable, it must be rebuilt from scratch on the next session (§7.7).

### 8.2 Pending / open items

| Item | Status | Notes |
|---|---|---|
| Refresh `COLAB_RUNBOOK.md` | Pending | Needs to reflect the new one-time library-build step, the fluidsynth install fix, and the now-implemented Drive-persistence cells (LIB 1.5 mirror / BC 0.1b restore). |
| Provenance CSV for the library | Pending | No dedicated provenance-tracking file (prompt used, gate metrics, candidate ID, curator decision, date) for committed library beds was found in the current build; this is implied as necessary for reviewer-auditable QC (§6.2) but not yet built. |
| TEI 2027 paper drafting | Pending | Deadline July 31, 2026 (`HYBRID_IMPROVEMENT_ROADMAP.md`). Several roadmap items are explicitly flagged 🔴 PAPER-CRITICAL and, per the roadmap, unresolved as of its writing: measuring the hybrid engine's own latency table (Track 4.1–4.3, 6.6), instrumenting beat-alignment error on the hybrid path (Track 1.1, 6.1), and formally documenting the hybrid-vs-`continuous.py` A/B decision (Track 6.4) since no write-up of that test's methodology/N/criteria was found in the repository at the time the roadmap was authored. |
| IRB (expedited/exempt, n ≈ 5–8) | Pending | `STAGE1_PROTOCOL.md` describes a phased plan: the full self-report study (n ≥ 40) is deferred to fall semester; a small feasibility/manipulation-check pilot (n ≈ 5) may run sooner pending IRB, to validate the rating instrument and confirm the genre-bed menu/pick/freeze workflow — explicitly **not** powered to test the inverted-U and framed only as feasibility (`STAGE1_PROTOCOL.md` §9). The task brief's figure of n ≈ 5–8 is consistent with, but a slightly wider range than, the n≈5 figure stated in `STAGE1_PROTOCOL.md` — flagged here as the protocol document's own number, not independently re-derived. |
| 12-song personalization pipeline | Referenced in task brief; **not found described in detail** in any source document reviewed (README.md, GROOVEGEN_V1_REPORT.md, STAGE1_PROTOCOL.md, ARCHITECTURE_TWO_TIMESCALE.md, DL_BED_FEASIBILITY.md, HYBRID_IMPROVEMENT_ROADMAP.md, NEXT_STEPS_ROADMAP.md, or the assess/ documents). This is flagged here as an **open item whose design has not yet been written down** anywhere in the reviewed corpus, rather than summarized from a source that does not exist. |
| PD controller gain tuning | Pending | `Kp`, `Kd` not yet empirically tuned; requires either simulation against a physiological plant model or in-session tuning data (`ARCHITECTURE_TWO_TIMESCALE.md` §9). |
| Human-subject validation | Not started | No human-in-the-loop sessions have occurred at the time of the architecture document's writing; all latency/control numbers are engineering estimates and literature citations (`ARCHITECTURE_TWO_TIMESCALE.md` §9). |
| Hybrid-engine per-bar closed-loop entry point | Pending, flagged as possibly THE paper-critical gap | `hybrid_render()` is currently a one-shot batch renderer; a true per-bar `render_aligned_drum_bar()` callable (analogous to the rejected `continuous.py::build_varied_drums`) does not yet exist for the canonical hybrid engine (`HYBRID_IMPROVEMENT_ROADMAP.md` Track 4.1). |

---

## 9. Decision log

| Date (best available) | Decision | Rationale | Source |
|---|---|---|---|
| 2026-06-02 | Adopt Spotify `song_dance` as the sole outcome variable for the Sophia secondary analysis, with explicit caveat that it is not a human groove rating | No per-trial participant groove rating exists in the dataset; `music_condition` is the experimental factor, not a judgment | `sophia/RESULTS_MEMO.md` |
| 2026-06-02 | Promote `hpss_percussive_ratio` and `low_band_energy_ratio` to validated render-stage mix biases | Standardized betas +4.66 and +2.97 respectively, 95% CIs clear of zero, Layer-2 model CV R² = 0.18 ± 0.04 | `sophia/RESULTS_MEMO.md`; `GROOVEGEN_V1_REPORT.md` §4 |
| 2026-06-02 | Adopt the Janata 110–130 BPM band as the system's danceable-tempo target | H4: +9.3 danceability points inband (p < .001, n = 203) | `sophia/RESULTS_MEMO.md` |
| 2026-06-02 | Treat the absence of the Witek syncopation inverted-U in commercial audio as the core motivation for controlled symbolic manipulation, not a failed hypothesis | Quadratic β = +0.22, n.s. — the effect cannot be recovered passively and must be studied parametrically | `sophia/RESULTS_MEMO.md`; `GROOVEGEN_V1_REPORT.md` §4 |
| 2026-06-02 | Do not build a trait-gated/personality-screened system; pursue a stimulus-side approach instead | Trait-moderator mixed model returned a clean null (SM_factor does not moderate the condition gap) | `README.md` |
| ~2026-06-02/03 | Genre-personalize the frozen bed instead of using an arbitrary fixed bed; freeze genre per participant, sweep drum knobs on top | Style-fit/familiarity dominates urge-to-move (Senn et al. 2018, R²≈0.12–0.15) far more than any structural rhythm feature (each ≈0.01) | `README.md`; `GROOVEGEN_V1_REPORT.md` §4; `STAGE1_PROTOCOL.md` §1 |
| 2026-06-02 | Derive the bed's acoustic target profile (120 BPM, 4/4, bass-forward A-Dorian vamp) from Sophia's high-danceability sensory-motor subset (n = 83) rather than an arbitrary vamp | Empirically matches `low_band_energy_ratio` ≈ 0.70, `hpss_harmonic_ratio` ≈ 0.70, valence ≈ 60 | `sophia/BED_FEATURE_PROFILE.md` |
| 2026-06-03 | Order knobs into Tier 1 (density, tempo, beat salience) and Tier 2 (syncopation, swing), with microtiming as a control | Tier 1 has the firmest, most consistent literature support and aligns with Sophia's own results; Tier 2 effects are real but smaller/contested | `GROOVEGEN_V1_REPORT.md` §2.1 |
| 2026-06-03 | Choose the Anticipatory Music Transformer (AMT, symbolic) over MusicGen (audio) as the primary bed generator for the frozen-bed study path | AMT outputs MIDI (fits the pretty_midi pipeline natively, keeps drums quantized, preserves single-isolated-variable control); MusicGen outputs audio, requiring beat-tracking/alignment and reintroducing timbre/loudness variance across beds | `DL_BED_FEASIBILITY.md` |
| 2026-06-03 | Lock the controlled-study genre menu to hip-hop/rap, R&B/soul, pop; keep latin/salsa, classic-rock, metal as demo-only | Highest-danceability, best-sampled families in Sophia's data (n ≥ 81 each); latin scored highest (72.0) but n = 14 is too thin for a study pillar | `GROOVEGEN_V1_REPORT.md` §4 |
| 2026-06-03 | Use `hero_study` (verse-loop-only, `sections=None`) as the study bed, keep the full Intro→Verse→Chorus `hero` song for demo/product only | The constant-bed causal-cleanliness requirement needs a perceptually time-invariant bed; a build-up song structure would confound the swept drum knob over trial duration | `README.md`; `GROOVEGEN_V1_REPORT.md` §3.3 |
| 2026-06 (unspecified) | Build `genre_styles.py`'s `GENRE_STYLES`/`StyleSpec` table so genre identity lives in the MIDI seed | AMT has no text-conditioning path; a single-block-chord seed collapsed all genres to the same flat sound | `README.md` |
| ~2026-06-25 | Reject "realism via raw MusicGen text-to-audio" as the sole path; keep the symbolic layer as the controlled groove layer, add realism only via rendering/mixing on top | MusicGen offers no continuous, trustworthy control over tempo/syncopation/swing/density — raw text-to-audio destroys clean causal attribution | `NEXT_STEPS_ROADMAP.md` §0–§1 |
| 2026-07-07 (roadmap date) | Lock in `hybrid_render.py` (MusicGen bed + genre-idiomatic symbolic drums beat-warped to the bed's detected grid) as the canonical drum engine over `continuous.py`, after an A/B test | User-perceived coherence favored hybrid's bit-identical-bar tiling over `continuous.py`'s per-bar stochastic re-randomization | `HYBRID_IMPROVEMENT_ROADMAP.md` (Track 2 framing; A/B test itself flagged as not yet formally written up — Track 6.4) |
| 2026-07-24 (approx., per assess/ file timestamps) | Diagnose the audio-quality crisis empirically (windowed tempo/onset analysis) before proposing a fix | Needed to localize "sounds bad after sec 19" and the latin tempo-doubling to specific time windows before attributing root causes | `assess/DIAGNOSIS_INPUT.md` |
| 2026-07-24 | Confirm four specific code-level root causes via line-referenced audit rather than acting on the empirical diagnosis alone | Distinguishes symptom (audible degradation) from architectural mechanism (prompt information loss, genre-snap miscalibration, naive resampling, drum-grid trust) so each can be fixed surgically | `assess/CODE_AUDIT.md` |
| 2026-07-24 | Adopt curated multi-BPM bed library + RubberBand re-timing + reference-anchored prompts + symbolic-latin fallback as the fix, over bigger-model and melody/style-conditioning alternatives | Matches documented biofeedback-music precedent; sidesteps MusicGen's documented Western-data training bias for latin/salsa; keeps the paper's system/method framing; RubberBand keeps the project's planned BPM-band gaps inside its high-fidelity zone | `assess/PATH_RESEARCH.md`; `assess/BUILD_SPEC.md` |
| 2026-07-24 | Build `bed_library.py`, `LIB_build_beds.ipynb`, the nb15 library-first lookup, and the `_octave_snap_grid` rewrite; leave `_madmom_beat_grid`/`_fix_octave` untouched | Surgical, minimal-change fix per the audit's own "small, well-isolated change" assessment; testing showed widening `_fix_octave`'s tempo band did not change the reachable-octave outcome | `assess/BUILD_REPORT.md` |
| 2026-07-27 | Diagnose a silent FluidSynth CLI install failure blocking the symbolic-latin fallback during the first live Colab run of `LIB_build_beds.ipynb`; instruct a visible (non-silenced) re-install before proceeding | The original install cell piped errors to `/dev/null`, masking the missing binary; without FluidSynth, the symbolic-latin fallback (§6.4) cannot render, and the default `KEEP` dict would then cause the commit cell to fail for all latin slots | Project session record (turn 208) |
| 2026-07-27 | Propose persisting the curated bed library to Google Drive so it survives a Colab runtime disconnect | `library/` currently lives only on ephemeral Colab disk; BC currently must run in the same runtime that built the library, or the library must be rebuilt from scratch | Project session record (turn 208) — **proposed, not yet confirmed implemented** |

---

## Appendix: source documents referenced

- `groovegen_project/README.md`
- `groovegen_project/sophia/RESULTS_MEMO.md`
- `groovegen_project/sophia/BED_FEATURE_PROFILE.md`
- `groovegen_project/GROOVEGEN_V1_REPORT.md`
- `groovegen_project/STAGE1_PROTOCOL.md`
- `groovegen_project/ARCHITECTURE_TWO_TIMESCALE.md`
- `groovegen_project/DL_BED_FEASIBILITY.md`
- `groovegen_project/HYBRID_IMPROVEMENT_ROADMAP.md`
- `groovegen_project/NEXT_STEPS_ROADMAP.md`
- `assess/DIAGNOSIS_INPUT.md`
- `assess/CODE_AUDIT.md`
- `assess/PATH_RESEARCH.md`
- `assess/BUILD_SPEC.md`
- `assess/BUILD_REPORT.md`
- Project session record, turns 207–208 (Colab run walkthrough; fluidsynth install failure and Drive-persistence proposal)
