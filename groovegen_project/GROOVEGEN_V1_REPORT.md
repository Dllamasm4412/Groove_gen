# GrooveGen v1.0 — Technical Report

**Author:** Daniel Llamas — PhD researcher, Electrical/Computer Engineering, CU Boulder (Brain Music Lab / ATLAS)
**Snapshot:** v1.0, 2026-06-03
**Stack:** Python — `pretty_midi` (symbolic) + FluidSynth (FluidR3_GM.sf2 render), `pyloudnorm` (−14 LUFS normalization). No Max/MSP.

---

## 1. What GrooveGen is

GrooveGen is a **parametric, literature-grounded generator of groove stimuli**. It produces short
looped instrumentals in which a small set of *knobs* — quantitative musical parameters known from the
groove literature to drive the urge-to-move — can be set to discrete, validated levels. The system was
built to supply the controlled stimuli for a planned groove-perception study, but it stands on its own
as a reproducible stimulus-generation tool.

The design has two halves that are deliberately kept separate:

1. **A constant harmonic bed** — a fixed 4/4, ~120-BPM bass-and-chord vamp, held identical across all
   stimuli so it cannot confound the manipulation. Its musical feature profile is grounded in a
   secondary analysis of Sophia's dataset (§4).
2. **A knob-controlled drum kit** layered on top of the bed. The drums carry every experimental
   manipulation (density, tempo, beat salience, syncopation, swing, microtiming).

This **"frozen bed + manipulated drums"** architecture is the core methodological idea: it lets a single
musical variable be swept at a time while everything else is held physically constant.

**Two updates since the first draft, both evidence-driven:**

- **The bed is now genre-personalized.** A secondary analysis of Sophia's dataset (§4) found that the
  single strongest correlate of the urge-to-move is not any structural rhythm feature but **genre/style
  fit and familiarity** — consistent with Senn et al. 2018, where style bias explained more variance
  (R²≈0.12) than every structural rhythm feature combined. We therefore generate the bed in the
  participant's preferred genre (menu: **hip-hop/rap, R&B/soul, pop** — the highest-danceability,
  best-sampled families in the dataset). Each participant picks the bed that feels best; we freeze that
  one bed and sweep the drum knobs on top of it. Genre is a per-participant *constant*, not a
  manipulated factor, so it personalizes the stimulus without confounding the knob attribution.
- **The knobs are now ordered by evidence strength** (§2.1), so the system leans on the features with
  the firmest support and treats the weaker-but-interesting ones as validated demonstrations rather
  than load-bearing claims.

---

## 2. The knobs (v1.0 — all levels LOCKED and validated)

Each knob is grounded in a specific empirical literature on groove and calibrated so its four discrete
levels (L0–L3) span the relevant region of the published response curve. Levels were set against
explicit literature target bands and then **verified by automated manipulation checks** that measure the
*achieved* value in the rendered MIDI (not just the requested setting). The targets and citations live
in `groove_knob_literature.md`; the achieved values are logged per stimulus in
`outputs/stimuli_manifest.csv`.

| Knob | Achieved levels (L0/L1/L2/L3) | Literature target | Shape | Primary sources |
|---|---|---|---|---|
| **Syncopation** (Witek index) | **0 / 16 / 32 / 49** | 0–4 / 12–18 / 26–34 / 48–65 | Inverted-U, apex S≈28–32 | Witek et al. 2014; Sioros et al. 2014 |
| **Event density** (onsets/bar) | **5 / 9 / 15 / 25** | 4–6 / 8–10 / 14–16 / 20–24 | Monotonic + | Madison 2011; Senn 2018 |
| **Swing** (swing fraction) | **50% / 56% / 62% / 67%** | 50 / 55–57 / 60–63 / 67% | Sweet zone 60–67% | Friberg & Sundström 2002; Ziereis 2019 |
| **Tempo** (BPM, if swept) | **70 / 95 / 115 / 150** | peak 107–126 | Inverted-U | Etani et al. 2018; Janata 2012 |
| **Microtiming** (ms RMS, control) | **0 / 5.9 / 12.6 / 29.5** | default 0 | quantized ≈ natural; large hurts | Frühauf 2013; Davies 2013; Senn 2016 |

### 2.1 Knob hierarchy by evidence strength

Not all five knobs rest on equally firm ground. Ordering them by how consistently the literature (and
our own Sophia analysis) supports them keeps the system honest about what it can claim:

**Tier 1 — load-bearing (strongest, most consistent evidence).** These are the features we expect to do
most of the groove heavy-lifting, and the ones the system is built around:

- **Event density** — onsets/bar; monotonic-positive within the danceable range (Madison 2011; Senn
  2018). Simple, robust, and the closest structural analog to the *percussiveness* signal that came out
  on top in our Sophia analysis (§4).
- **Tempo** — strongest with a clear inverted-U peaking ~107–126 BPM (Etani et al. 2018; Janata 2012);
  our genre beds sit inside this band by design.
- **Beat salience / pulse clarity** — a clear, well-marked tactus is a precondition for entrainment
  (Madison 2011; Stupacher 2016). The backbeat skeleton (kick 1&3, snare 2&4) holds this stable while
  other knobs perturb around it.

**Tier 2 — validated demonstrations (real effects, but smaller, contested, or condition-dependent).**
The system can sweep these and reproduces their canonical curves, but it does **not** stake its core
groove claim on them:

- **Syncopation** — a genuine, replicated inverted-U (Witek et al. 2014), but the *isolated* effect is
  modest and shrinks sharply once style and density are controlled (Senn et al. 2018, structural-feature
  R²≈0.01). v1.0 reproduces the inverted-U cleanly (S = 0/16/32/49, apex at L2); we treat that
  reproduction as a demonstration of fidelity, not as the primary lever.
- **Swing** — contested and partly novel: several studies find swung or microtiming-exaggerated versions
  *no better or worse* than quantized (Frühauf 2013; Davies 2013; Ziereis 2019). We keep it as a knob to
  enable a clean test, not because the prior is strong.

**Control variable.** *Microtiming* is held at 0 by default. The folk-wisdom that "humanized" timing
feels groovier is not supported — quantized performs at least as well as humanized, and large deviations
hurt (Frühauf 2013; Davies 2013; Senn 2016). It exists as a knob only so the null can be demonstrated.

*Practical consequence for the system:* the genre-personalized bed plus the Tier-1 drum knobs
(density + tempo on a salient backbeat) constitute a defensible groove-induction system on their own.
Syncopation and swing are bonus demonstrations the same generator happens to support — so a strong
system exists even if we never run the syncopation sweep with participants.

**Why the level placement matters.** Earlier iterations of the syncopation knob clustered on the *toe*
of the inverted-U (achieved indices ~0/3/5/9) and never reached the literature sweet spot — and the
index itself physically capped near 9 because it omitted instrument-salience weighting. v1.0 rewrites
the index to the Witek (2014) operationalization (Longuet-Higgins & Lee metric weights × drum-instrument
salience, kick=2.0, snare=1.5, hi-hat excluded, summed over a 2-bar window), which scales onto the
literature's 0–81 range. The recalibrated levels (0/16/32/49) now span the curve, with **L2 = 32 sitting
at the apex** and L3 deliberately past it on the downslope.

---

## 3. Validation: the three things v1.0 actually proves (no human data required)

### 3.1 Manipulation checks — every knob lands in its target band

For each of the five knobs, the swept levels are rendered and the achieved value is measured directly
from the MIDI. The results (logged in the manifest) confirm:

- Syncopation: **S = 0 / 16 / 32 / 49** — inside the literature bands and spanning the inverted-U.
- Density: **5 / 9 / 15 / 25** onsets/bar — squarely inside target bands.
- Swing: **50 / 56 / 62 / 67%** — straddling the 60–67% sweet zone.
- Tempo & microtiming likewise hit their targets.

This is a genuine, citable contribution on its own: *the generator produces stimuli whose measured
musical properties match the values the literature says matter.*

### 3.2 Decorrelation — knobs move independently

When the syncopation knob is swept, **event density stays ~12–14 onsets/bar across all four levels**
(and vice-versa). This decorrelation means an effect attributed to one knob cannot be a hidden
side-effect of another — essential for a clean experimental design.

### 3.3 Frozen study bed — the bed is time-invariant and knob-invariant

The study bed (`hero_study`) was verified to be:
- **Time-invariant**: 216 notes fold to 33 distinct events per cycle (a true constant loop, no
  Intro→Verse→Chorus build-up that would confound a swept knob over the trial duration).
- **Knob-invariant**: identical across all five-knob combinations — the bed never changes when a drum
  knob moves.

A separate structured `hero` song (Intro→Verse→Chorus) exists for **demo/product** use only; the frozen
`hero_study` bed is what the study uses.

### Figure — implemented levels vs. literature curves
`outputs/figures/knob_level_straddle.png` overlays the achieved levels (teal points) on the idealized
literature response curves with recommended bands shaded. It is the single clearest visual evidence that
the knobs are calibrated correctly.

---

## 4. What we learned from Sophia's dataset (and how it shaped the system)

The single most consequential thing the Sophia analysis taught us is **not** about any one rhythm knob
— it is about *who is listening to what*:

> **Genre fit and familiarity dominate the urge-to-move.** Whether a listener grooves to a track
> depends more on whether the music is in a style they like and recognize than on any structural rhythm
> feature we can manipulate. In Senn et al. 2018 (248 patterns, 15 variables), *style bias* explained
> R²≈0.12 of pleasure-to-move — and adding familiarity pushed it to ≈0.15 — while syncopation and
> density each explained only R²≈0.01. The structural knobs are real but small; the personal/cultural
> fit is large.

**Why this reframes the system.** Originally we treated the harmonic bed as a fixed nuisance variable
to be held constant. The Sophia/familiarity finding flips that: the bed is the lever that controls
style fit, so it should be *matched to the participant*, not arbitrary. Hence the genre-personalized
design — generate the bed in the listener's preferred genre, freeze it, and sweep the (smaller but
cleaner) structural knobs on top. We get the large personalization benefit *and* clean knob attribution.

**Which genres to offer.** A genre-family analysis of the dataset (`sophia/genre_analysis_results.json`,
notebook 04) ranked broad families by mean Spotify danceability on n=704 unique tracks (corpus mean
≈59.6):

| Genre family | Mean danceability | n tracks | Prevalence | Note |
|---|---|---|---|---|
| Latin | 72.0 | 14 | 2.0% | highest, but thinly sampled |
| **Hip-hop/rap** | **67.5** | 106 | 15.1% | high danceability, well sampled |
| **R&B/soul** | **65.5** | 81 | 11.5% | high danceability, well sampled |
| **Pop** | **61.2** | 288 | 40.9% | familiarity anchor (40% of corpus) |
| Electronic/EDM | 59.0 | — | — | |
| Country/folk | 57.3 | — | — | |
| Rock | 56.5 | — | — | |
| Jazz | 56.0 | — | — | |
| Metal/hardcore | 43.0 | — | — | |

**Locked study menu: hip-hop/rap, R&B/soul, pop** — the two highest-danceability families with reliable
samples, plus pop as the high-familiarity anchor. Latin scores highest (72.0) but n=14 is too thin to
build a pillar on; we note it as a candidate for a follow-up. The genre menu and per-participant freeze
workflow are implemented in notebooks 04–06 and the `dlbed` adapter.

### 4.1 Where the bed's musical profile comes from

Beyond *which* genre, the bed's acoustic character is derived from a secondary analysis of Sophia's
dataset, so the study sits on top of empirically motivated music.

**Bed feature profile** (high-danceability sensory-motor subset, n=83 tracks, `song_dance` ≥ 70):
120 BPM, 4/4, `low_band_energy_ratio` ≈ 0.70 (bass-forward), `hpss_harmonic_ratio` ≈ 0.70 (prominent
sustained harmony), valence ≈ 60 (slight positive lean). Implemented as a bass-forward **A-Dorian vamp
(Am7 – D/A)** with grand-piano harmony. (Detail: `sophia/BED_FEATURE_PROFILE.md`.)

**Two empirical findings that justify the actuators** (`sophia/RESULTS_MEMO.md`, figures
`layer1_validation.png`, `layer2_betas.png`):

- **Percussiveness and bass are the dominant, robust positive predictors of danceability** in real
  recordings: standardized β = **+4.66** for `hpss_percussive_ratio` and **+2.97** for
  `low_band_energy_ratio` (95% CIs well clear of zero; CV R² = 0.18 ± 0.04, CV Spearman ρ = 0.44). This
  validates promoting those two acoustic dimensions in the generator's render-stage mix.
- **Tempo sweet-spot replicates**: tracks in 110–130 BPM are **+9.3 danceability points** (p < .001),
  matching the tempo-knob design and Janata's danceable band.
- **The Witek syncopation inverted-U does NOT appear** in this naturalistic commercial-audio corpus
  (quadratic β = +0.22, n.s.). This is the scientifically important null: the syncopation effect cannot
  be recovered from passive naturalistic audio and **must** be studied under parametric manipulation —
  which is exactly what GrooveGen's controlled grid provides. This is the cleanest motivation for the
  whole project, not a weakness.

**Honest scope:** R² ≈ 0.18 is a methods/supplementary result, not a standalone prediction paper.

---

## 5. The 20-stimulus grid

`build_stimulus_grid.py` renders the full Stage-1 stimulus set: **5 knobs × 4 levels = 20 stimuli**, all
on the frozen `hero_study` bed, all normalized to −14 LUFS. `outputs/stimuli_manifest.csv` is the
single source of truth — one row per stimulus logging the requested setting, the **achieved**
manipulation-check value, loudness, file paths, and seed. This manifest is what makes the stimulus set
reproducible and auditable.

---

## 6. Project structure

```
groovegen_project/
├── VERSION                      # v1.0 marker
├── README.md
├── GROOVEGEN_V1_REPORT.md       # this report
├── STAGE1_PROTOCOL.md           # §8b locked-knob table, §9 open decisions
├── config.py                    # portable paths, find_soundfont()
├── requirements.txt
├── groovegen/
│   ├── groovegen.py             # core: GrooveParams, PatternBuilder, BedProfile,
│   │                            #   BED_HERO / HERO_STUDY / DORIAN / POP / LIFT,
│   │                            #   syncopation_index (Witek), build_bed_*, render_wav
│   ├── dlbed.py                 # DL-bed adapter: AMT MIDI -> frozen BedProfile + render_genre_demo
│   ├── build_stimulus_grid.py   # renders the 20-stimulus grid + manifest
│   ├── render_iterations.py, bayesopt.py, melody_timbre_compare.py, make_compare_video.py
├── sophia/                      # run_analysis.py, make_plots.py, trait_moderator_analysis.py,
│                                #   genre_analysis.py, BED_FEATURE_PROFILE.md, RESULTS_MEMO.md,
│                                #   genre_analysis_results.json, *.json
├── notebooks/                   # 00_setup, 01_sophia_analysis, 02_bed_design, 03_generate_stimuli,
│                                #   04_genre_analysis, 05_dl_bed_generation, 06_drum_overlay_demo
├── data/                        # survey_and_music_data_N122.csv, track_features.csv, data_dictionary.csv
└── outputs/
    ├── audio/                   # study_bed_frozen.*, song_hero*.*, grid/ (20 stimuli), bed_only_*.wav
    ├── figures/                 # knob_level_straddle.png, layer1_validation.png, layer2_betas.png
    └── stimuli_manifest.csv
```

---

## 7. The genre-personalized DL bed (now built) + roadmap

**Built since the first draft (the "A+B" system):** the hand-authored bed can now be replaced by one
produced by a pretrained deep-learning symbolic-music model — the **Anticipatory Music Transformer**
(Thickstun et al. 2023, Stanford CRFM, Apache-2.0), which emits MIDI and drops straight into the
`pretty_midi` pipeline so the drums stay perfectly quantized. The pipeline is:

1. **Notebook 04** — analyze Sophia's dataset for the top genres → lock the menu (hip-hop/rap, R&B/soul, pop).
2. **Notebook 05** — generate a genre-conditioned bed per menu item with AMT (seeded by a genre
   chord/tempo skeleton, since AMT is symbolic and has no text prompt), audit it, and freeze it to MIDI.
3. **Notebook 06** — the `dlbed` adapter (`groovegen/dlbed.py`) quantizes the frozen bed onto the
   16-step grid as a `BedProfile` with `sections=None`, so it is automatically time- and knob-invariant
   — the same guarantee verified for `hero_study`. It then overlays the knob-controlled drums and
   renders a Tier-1 (density) sweep on top of the chosen-genre bed.

The DL step is a **design-time tool**: beds are generated offline, audited, and frozen — never per
trial — so the study's time-invariance holds. (Memorization caveat: AMT was trained on Lakh MIDI; we
screen beds against known songs and frame use as research/non-commercial. MusicGen remains a
demo-only secondary option — audio output would break the frozen-bed control.) See
`DL_BED_FEASIBILITY.md` for the full model comparison.

**Still on the roadmap:**

- **Human groove-rating study.** The full n≥40 study is deferred to fall. A small **n≈5 feasibility /
  manipulation-check pilot** may run sooner (pending IRB) to validate the rating instrument, confirm
  participants perceive the knob levels as intended, and confirm the genre-bed menu works as a
  per-participant pick.

None of the §3 validation results depend on human data — v1.0 + the genre-personalized DL bed is
publishable now as a system/tools contribution (e.g., NIME, SMC, ICMC, or an ISMIR late-breaking/demo).

---

## 8. Citations (knob calibration)

- Witek, M. A. G., Clarke, E. F., Wallentin, M., Kringelbach, M. L., & Vuust, P. (2014). Syncopation,
  body-movement and pleasure in groove music. *PLOS ONE*, 9(4), e94446.
  https://doi.org/10.1371/journal.pone.0094446
- Sioros, G., Miron, M., Davies, M., Gouyon, F., & Madison, G. (2014). Syncopation creates the sensation
  of groove in synthesized music examples. *Frontiers in Psychology*, 5, 1036.
  https://doi.org/10.3389/fpsyg.2014.01036
- Madison, G., Gouyon, F., Ullén, F., & Hörnström, K. (2011). Modeling the tendency for music to induce
  movement in humans. *Journal of Experimental Psychology: HPP*, 37(5), 1578–1594.
  https://doi.org/10.1037/a0024323
- Senn, O., et al. (2018). Groove in drum patterns. *Music Perception*, 36(2).
  https://doi.org/10.1525/mp.2018.36.2.186
- Etani, T., et al. (2018). Optimal tempo for groove. https://doi.org/10.1080/09298215.2018.1456643
- Janata, P., Tomic, S. T., & Haberman, J. M. (2012). Sensorimotor coupling in music and the psychology
  of the groove. *Journal of Experimental Psychology: General*, 141(1), 54–75.
  https://doi.org/10.1037/a0024208
- Friberg, A., & Sundström, A. (2002). Swing ratios and ensemble timing in jazz performance.
  *Music Perception*, 19(3), 333–349. https://doi.org/10.1525/mp.2002.19.3.333
- Frühauf, J., Kopiez, R., & Platz, F. (2013). Music on the timing grid. *Musicae Scientiae*, 17(2).
  https://doi.org/10.1177/1029864913486794
- Davies, M., Madison, G., Silva, P., & Gouyon, F. (2013). The effect of microtiming deviations on the
  perception of groove. *Music Perception*, 30(5), 497–510. https://doi.org/10.1525/mp.2013.30.5.497
