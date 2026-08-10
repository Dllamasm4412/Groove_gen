# GrooveGen Stage 1 — Controlled groove-induction study (protocol draft)

**Authors (intended):** Daniel Llamas, Sophia [—], [advisor] · Brain Music Lab / ATLAS, CU Boulder
**Status:** draft for refinement with Sophia & advisor · **Version:** 0.1 · 2026-06-02
**Outcome (Stage 1):** self-report groove ratings. PPG + respiration deferred to Stage 2.

---

## 1. Research questions & hypotheses

The generator produces drum patterns whose groove-relevant features are independently
controllable. Stage 1 asks **which symbolic drum features causally drive felt groove**, on top of a
**bed generated in each participant's preferred genre** (the design's personalization lever).

**Why genre-personalize the bed.** The strongest lesson from Sophia's dataset (and Senn et al. 2018)
is that *style fit and familiarity* dominate the urge-to-move — explaining far more variance (R²≈0.12,
≈0.15 with familiarity) than any structural rhythm feature (syncopation, density each R²≈0.01). Rather
than fight this with an arbitrary fixed bed, we harness it: each participant reports their top genres,
we present a short **menu of pre-generated genre beds (hip-hop/rap, R&B/soul, pop)**, they pick the one
that feels best, and we **freeze that single bed** for the whole session. Genre is therefore a
**per-participant constant**, not a manipulated factor — it personalizes the stimulus (large effect)
while keeping the knob attribution perfectly clean (the bed never changes within a participant).

**Manipulated drum knobs, ordered by evidence strength:**
- **Tier 1 (primary, load-bearing):** event density and tempo, on a salient backbeat — the features
  with the firmest, most consistent groove evidence (Madison 2011; Etani 2018) and the winners in our
  own Sophia analysis. These carry the core groove claim.
- **Tier 2 (validated demonstrations):** syncopation (reproduces the canonical inverted-U; Witek 2014)
  and swing (contested/novel; Frühauf 2013). Real but smaller/condition-dependent effects — swept to
  demonstrate fidelity, not to anchor the system.

**Held constant:** the chosen genre bed (frozen, time- & knob-invariant); microtiming = 0 (quantized,
the control knob); timbre, kit, loudness (−14 LUFS), loop length. Tempo is fixed at the chosen genre's
danceable value within trials when not the swept knob.

| # | Hypothesis | Basis | Predicted form |
|---|---|---|---|
| **H1 (Tier 1)** | Event density → groove **increases then plateaus/declines** | Madison 2011; Senn 2018; our Layer-2 (`hpss_percussive_ratio` dominant) | monotone-to-saturating |
| **H2 (Tier 1)** | Tempo → groove follows an **inverted-U peaking ~107–126 BPM** | Etani 2018; Janata 2012; our Layer-1 replication (+9.3 pts in 110–130) | quadratic, danceable-band peak |
| **H3 (Tier 2)** | Syncopation → groove follows an **inverted-U** | Witek 2014; Sioros 2014 | quadratic, peak at moderate syncopation; *expected smaller than Tier 1* |
| **H4 (Tier 2)** | Swing → groove effect is **small and possibly null/negative** | Frühauf 2013 (quantized ≥ swung); contested | flat or slight decline; *challenges folk belief* |
| **H5 (personalization)** | Letting participants pick their genre bed **raises baseline groove** vs a mismatched bed | Senn 2018 style-bias dominance; Sophia genre analysis | chosen-genre bed > non-preferred bed (manipulation/feasibility check) |
| **H6 (exploratory)** | Individual differences (eBMRQ-SM) predict each person's sweet-spot | weak per Sophia trait null | small / null — motivates stimulus-side approach |

**The novelty hooks are H2/H5.** Promoting tempo and density to Tier 1 lets the system stake its groove
claim on the firmest evidence, while the genre-personalized bed (H5) is the design's distinctive
contribution: it operationalizes the style-fit/familiarity finding as a controllable, per-participant
stimulus choice rather than an uncontrolled nuisance.

---

## 2. Design

**Within-subjects.** Each participant runs on **their own chosen genre bed**, held constant for the
whole session, so every rated difference is attributable to a drum knob — not the bed.

### Step 0 — Genre selection (per participant, once)
The participant reports their top musical genres; we present a short **menu of 3 pre-generated,
pre-audited genre beds** (hip-hop/rap, R&B/soul, pop — the highest-danceability, best-sampled families
in Sophia's data) and they pick the one that feels best. That bed is **frozen** (`sections=None`,
time- & knob-invariant) and used for all subsequent trials. *Optional H5 check:* present one
non-preferred bed in a small anchor block to confirm the chosen bed rates higher.

### Part A — Tier-1 single-knob sweeps (primary)
The two Tier-1 knobs swept across **4 levels** on the frozen chosen-genre bed, the other held at
reference:
- **Event density: 4 / 8 / 14 / 24** (achieved ≈ 5 / 9 / 15 / 25 onsets/bar) — the primary arm.
- **Tempo: 70 / 95 / 115 / 150 BPM** (inverted-U around the 107–126 danceable band).

`2 Tier-1 knobs × 4 levels = 8 core stimuli`, reference (center) cells shared.
Reference cell: density = 8, tempo = 115, syncopation = 0.0, swing = 1.0, microtiming = 0.

### Part B — Tier-2 demonstration sweeps (secondary)
The two Tier-2 knobs swept across **4 levels** on the same frozen bed, to demonstrate the generator
reproduces their canonical curves (not to anchor the system's groove claim):
- **Syncopation: 0.0 / 0.25 / 0.5 / 1.0** (achieved Witek index 0 / 16 / 32 / 49; inverted-U span).
- **Swing: 1.0 / 1.25 / 1.6 / 2.0** (50% / 56% / 62% / 67%).

`2 Tier-2 knobs × 4 levels = 8 stimuli`, shared reference.

### Part C (optional) — focused density × syncopation factorial
The Tier-1 × Tier-2 interaction most worth resolving — **density × syncopation** — crossed at
**3 levels each** (low/med/high): `3 × 3 = 9 stimuli`.

**Total unique stimuli ≈ 8 (A) + 8 (B) + 9 (C) − shared reference cells ≈ 22–25 stimuli.**
At a 12 s loop + ~6 s rating, with 2 repetitions for reliability, that is ≈ 22 × 18 s × 2 ≈ 13 min of
trials + breaks → a comfortable single ~40 min session. Dropping Part C keeps it tighter for the pilot.

**Randomization:** stimulus order fully randomized per participant; Tier-1 (Part A) is the
pre-registered primary block; 2 presentations per stimulus (compute within-subject reliability / ICC).

---

## 3. Stimuli

Generated by GrooveGen (`groovegen.py`), deterministic + seeded → fully reproducible. Every
stimulus rendered FluidSynth → loudness-normalized to −14 LUFS (no loudness confound).
**Manipulation checks logged per stimulus** (`stimuli_manifest.csv`): achieved onsets/bar,
syncopation index (Longuet-Higgins & Lee / Witek), realized swing fraction.

**The chosen genre bed** (per participant): one of three pre-generated, pre-audited **genre beds**
produced by the Anticipatory Music Transformer (notebook 05) and frozen via the `dlbed` adapter
(notebook 06): hip-hop/rap (~112 BPM), R&B/soul (~104 BPM), or pop (~120 BPM). The participant picks
one in Step 0; that single bed is used for every trial. Each bed is a 4/4, bass-forward vamp whose
acoustic profile follows Sophia's high-danceability sensory-motor subset (see
`sophia/BED_FEATURE_PROFILE.md`): bass-forward (`low_band_energy_ratio` ≈ 0.70), prominent sustained
harmony (`hpss_harmonic_ratio` ≈ 0.70). The hand-authored `hero_study` profile
(`STUDY_BED_PROFILE` in code) remains available as a non-DL fallback for smoke tests.

**Why a single frozen bed per participant, not a manipulated one?** The experiment must isolate the
causal effect of each drum knob on groove. A bed that changed across trials (or ramped over time)
would inject an uncontrolled confound: a rating could reflect the bed rather than the knob. Freezing
the chosen bed to one time-invariant loop makes it perceptually constant within a participant, so the
swept knob is the only thing that changes. The structured hero song (Intro→Verse→Chorus) and the AMT
generation step are **design-time tools** — beds are generated and audited offline, never per trial.

**Frozen-bed guarantee** — the `dlbed` adapter builds every genre bed with `sections=None` (plain loop
path), giving identical symbolic content every cycle (time-invariant) and a bed signature unchanged
across every combination of the five knobs (knob-invariant) — the same property verified for
`hero_study` in `verify_study_bed.py`. The manifest logs the chosen `bed_profile` (e.g. `dlgen_pop`)
for every stimulus.

---

## 4. Measures

**Primary — groove self-report.** After each stimulus, validated items on a continuous slider
(0–100) or 7-point Likert:
- **Wanting-to-move / urge to move** (the core PLUMM/Janata groove item).
- **Pleasure / enjoyment** (groove = move + pleasure, per Janata 2012).
- Composite **groove score** = mean(z(move), z(pleasure)) (preregistered).

**Secondary / covariates:**
- Per-stimulus: perceived complexity, familiarity (control), tempo-appropriateness.
- Per-person (once): **eBMRQ** incl. Sensory-Motor subscale (reuse Sophia's instrument),
  musical training, BFI (optional), demographics.

**Stage 2 add-ons (not collected now):** PPG (HR/HRV, pulse-amplitude), respiration rate/depth;
optional accelerometer for spontaneous movement.

---

## 5. Analysis plan (preregistered)

Unit = trial; random intercept per participant (and per stimulus where estimable).

- **H1 (syncopation inverted-U):** mixed model `groove ~ poly(syncopation,2) + (1|P)`; test the
  negative quadratic. Report peak location + 95% CI.
- **H2 (density):** mixed model with linear + quadratic density; test monotone-saturating shape.
- **H3 (swing):** mixed model linear/quadratic swing; **pre-register that we may find null** —
  report equivalence test (TOST) so a null is informative, not ambiguous.
- **H4 (bed interaction):** `groove ~ syncopation*bed + density*bed + (1|P)`; the
  syncopation:bed and density:bed interactions test whether harmonic context reshapes the
  curves. Drums-only serves as the built-in replication anchor.
- **Part B interaction:** `groove ~ syncopation*density + (1|P)` (both factorized), 3×3.
- **H5 (individual differences, exploratory):** add eBMRQ-SM as a person-level moderator of the
  syncopation/density slopes; report effect sizes + CIs (expected small per Sophia trait null).
- **Manipulation checks:** confirm achieved syncopation index / onsets-per-bar / swing fraction
  track commanded levels monotonically (already verified in `stimuli_manifest.csv`).
- **Reliability:** ICC across the 2 presentations of each stimulus; exclude participants with
  ICC < .3 (inattentive), preregistered.
- Multiple-comparison control: Holm across the primary H1–H4 family.

---

## 6. Power

Within-subject (repeated-measures) design; each participant rates every cell ×2.

- At **n = 36**, 80% power to detect a paired contrast of **dz ≈ 0.48** (e.g. trough-vs-peak of
  the inverted-U) — comfortably below typical groove effect sizes (Witek/Janata report medium-
  to-large within-subject effects).
- At **n = 40**, power ≈ .87 for a medium dz = 0.50.
- **Recommended target: n = 36–40 completers** (recruit ~44 for ~10% exclusion). This matches
  in-lab groove-rating norms (Senn et al. used dozens in-lab; Witek 2014 n = 66 online).
- RM-ANOVA main-effect check: with within-subject correlation r ≈ .5, n = 36 gives >80% power
  for a medium f = 0.25.

(Power computed with `statsmodels`; full script `sophia/` workspace. Between-subject ANOVA
upper bound would be ~179, but the within-subject design is far more efficient — the paired/RM
numbers above are the operative ones.)

---

## 7. Procedure

1. Consent, headphone check, volume calibration (fixed playback level).
2. eBMRQ + brief questionnaires.
3. Practice trials (2–3 non-analyzed stimuli) to anchor the rating scale.
4. Main blocks (bed / drums-only counterbalanced), stimuli randomized, 2 reps each.
5. Short breaks every ~6 min.
6. Debrief. ~45 min total.

---

## 8. What this earns toward the generator / product

- **Causal feature map:** which knobs (and shapes) drive felt groove → the design targets for
  the generation system.
- **Bed-context finding (H4):** whether features must be tuned differently inside a real song
  vs bare drums → directly informs the *product* (which generates full songs).
- **Stage 2 bridge:** the same stimuli + protocol extend to PPG/respiration (physiological
  groove markers) and to the **Bayesian per-person sweet-spot** loop (already built) for
  adaptive/BBCI personalization.

---

## 8b. Locked knob levels (calibrated to the groove literature)

Each knob uses **4 levels**. Levels were calibrated against the recommended ranges in
`groove_knob_literature.md` and **verified against the rendered audio** via the manipulation-check
columns in `stimuli_manifest.csv` (see `knob_level_straddle_check.py` for the level-vs-literature
plot, `outputs/figures/knob_level_straddle.png`).

Knobs are grouped by **evidence tier** (§1): Tier 1 (density, tempo) carries the system's groove claim;
Tier 2 (syncopation, swing) are validated demonstrations; microtiming is the control.

| Tier | Knob | L0 | L1 | L2 | L3 | Achieved (manifest) | Literature target | Source |
|------|------|----|----|----|----|---------------------|-------------------|--------|
| **1** | **Event density** (onsets/bar) | sparse | standard | dense | very dense | **5 / 9 / 15 / 25** | 4–6 / 8–10 / 14–16 / 20–24 | Madison et al. 2011; Senn et al. 2018 |
| **1** | **Tempo** (BPM) | slow | mid | danceable | fast | **70 / 95 / 115 / 150** | peak 107–126 | Etani et al. 2018; Janata et al. 2012 |
| **2** | **Syncopation** (Witek index, salience-weighted, 2-bar) | straight | light | sweet spot | heavy | **0 / 16 / 32 / 49** | 0–4 / 12–18 / 26–34 / 48–65 | Witek et al. 2014; Sioros et al. 2014 |
| **2** | **Swing** (swing fraction) | straight | light | funk sweet spot | triplet shuffle | **50% / 56% / 62% / 67%** | 50 / 55–57 / 60–63 / 67% | Friberg & Sundström 2002; Ziereis et al. 2019 |
| ctrl | **Microtiming** (ms RMS) | 0 | 5.9 | 12.6 | 29.5 | as set | default 0 (quantized ≥ humanized) | Frühauf 2013; Davies 2013; Senn 2016 |

Notes:
- **Syncopation L2 (S=32) sits at the inverted-U apex (~28–32)**; L0/L1 climb the rising limb and L3
  occupies the high shoulder — so the design can recover the inverted-U shape (the whole point of the
  manipulation). Earlier levels topped out at S=9 (toe of the curve only); recalibrated 2026-06-03.
- The syncopation **index now weights drum-instrument salience** (bass drum > snare; hi-hat excluded)
  per Witek et al. 2014 — this is what places the index on the literature's 0–81 scale.
- Syncopation is **decorrelated from density**: onsets/bar stays ~12–14 across all four syncopation
  levels (manifest), so a syncopation effect cannot be a disguised density effect.
- **Tempo is now a Tier-1 primary knob** (promoted from secondary): the danceable-band inverted-U is
  among the firmest groove findings, so it carries part of the core claim rather than being held fixed.
  Within a participant it is fixed at the chosen genre's danceable value except in its own sweep.
- **Microtiming** remains the control knob (defaults to 0); included only to demonstrate the
  quantized-≥-humanized null.

## 9. Open decisions for Sophia / advisor

1. Rating instrument: continuous slider vs Likert; exact item wording (adopt a published groove
   scale verbatim for comparability — recommend Janata PLUMM items).
2. Final n target and recruitment source (lab pool vs Prolific online).
   **Phased plan (2026-06):** the full self-report study (n >= 40) is **deferred to fall semester**.
   A small **feasibility / manipulation-check pilot (n ~ 5)** may run sooner (pending IRB) to validate
   the rating instrument, confirm participants perceive the knob levels as intended, and confirm the
   genre-bed menu / pick / freeze workflow runs smoothly; it is NOT powered to test the inverted-U and
   would be framed explicitly as feasibility. The summer deliverable is the **system/methods paper**
   (GrooveGen generator + manipulation-check validation + genre-personalized DL bed), no human data.

**Decisions now settled by the evidence-tiered, genre-personalized redesign:**

3. ~~Which 3rd knob (swing vs tempo)?~~ **Resolved:** both are kept, but re-tiered — tempo joins
   density as Tier-1 primary; syncopation and swing are Tier-2 demonstrations. The system no longer
   hinges on the swing/syncopation result. (Knob levels remain locked — see §8b.)
4. ~~Bed-presence as a ×2 factor?~~ **Resolved:** dropped. The bed is no longer a manipulated factor;
   it is a **per-participant constant** chosen from the genre menu and frozen. (An optional single
   non-preferred-bed anchor block can test H5 without making the bed a full factor.)

**Still open:**

5. Exact genre-bed audit criteria before a bed enters the menu (onset sparsity ceiling, key/tempo
   tolerance, memorization screen against known songs).
6. IRB amendment scope (Stage 1 self-report only; Stage 2 physio as separate amendment).

---

### Key citations
Witek et al. 2014, *PLOS ONE* — https://doi.org/10.1371/journal.pone.0094446 ·
Janata et al. 2012, *JEP:General* — https://doi.org/10.1037/a0024208 ·
Senn et al. 2018, *PLOS ONE* — https://doi.org/10.1371/journal.pone.0199604 ·
Frühauf et al. 2013, *Musicae Scientiae* — https://doi.org/10.1177/1029864913486793 ·
Sioros et al. 2014, *Frontiers in Psychology* — https://doi.org/10.3389/fpsyg.2014.01036
