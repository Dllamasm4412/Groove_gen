# Sophia Secondary Analysis — Results (Phase 5, Layers 1 & 2)

**Run date:** 2026-06-02 · **N = 643 unique tracks** (644 with audio features, 1 dropped for missing `beat_consistency`).
**Target:** Spotify `song_dance` (0–100). There is **no participant groove/dance-urge rating** in the dataset (confirmed in the data dictionary: `music_condition` is the experimental factor; `sensory-motor` is one of its four levels, not a per-trial judgment). All claims are song-level.

---

## Layer 1 — `groove_proxy` validation

`groove_proxy` = unit-weighted z-sum of `beat_consistency + plp_mean + hpss_percussive_ratio + low_band_energy_ratio − z(lhl_syncopation_mean)²` (k = 0).

| Hypothesis | Result | Pre-reg threshold | Verdict |
|---|---|---|---|
| **H1 convergent** — corr(groove_proxy, song_dance) | Pearson r = **0.22** [0.10, 0.38]; Spearman ρ = **0.40** | r ≥ 0.50 | **FAIL** (Pearson); ρ is moderate |
| **H2 discriminant** — r(dance) > r(energy) | r_dance = 0.22 > r_energy = 0.17 | — | **PASS** (weakly) |
| **H3 Witek inverted-U** — neg. quadratic on syncopation | quadratic β = **+0.22**, p = 0.21 | β < 0, p < .05 | **FAIL** — no inverted-U |
| **H4 Janata tempo band** — dance peaks 110–130 BPM | inband mean 66.1 vs 56.8, **+9.3 pts, p < .001** (n=203 inband) | — | **PASS** (clear) |

**Interpretation.** The theory-grounded proxy shows a *modest* monotone association with Spotify danceability (ρ ≈ 0.40) — below the pre-registered r ≥ 0.50 bar on the linear metric. The Spearman/Pearson gap (0.40 vs 0.22) is driven partly by a few extreme-syncopation tracks whose quadratic penalty produces very negative proxy values; rank-based ρ is the more trustworthy reading here.
- **H3 is the scientifically important null:** there is **no inverted-U of syncopation** on Spotify danceability in this naturalistic corpus — if anything the quadratic bends slightly *upward*. This is consistent with the literature caveat that the Witek inverted-U is robust for *controlled drum patterns* but does **not** reliably transfer to commercial full-mix recordings (cf. the 2024 Senn null-replication concern already noted in the knob literature).
- **H4 replicates Janata's tempo sweet-spot** cleanly: tracks in 110–130 BPM are ~9 points more danceable. This is the single strongest, most portable finding.

---

## Layer 2 — Acoustic predictors of `song_dance`

7-feature standardized OLS, 10-fold song-held-out CV.
**Substitutions** (prereg names absent from `track_features.csv`): `onset_rate → onset_density`; `spectral_flux_mean → spectral_flatness_mean`.

- **Cross-validated R² = 0.18 ± 0.04**; **CV Spearman ρ = 0.44 ± 0.05**; in-sample adj. R² = 0.19.
- Standardized betas (95% CI), strongest first:

| Feature | β (std) | 95% CI | Direction |
|---|---|---|---|
| **hpss_percussive_ratio** | **+4.66** | [3.57, 5.74] | more drum-driven → more danceable |
| **low_band_energy_ratio** | **+2.97** | [1.98, 3.97] | more bass → more danceable |
| **beat_consistency** | +1.35 | [0.33, 2.37] | steadier pulse → more danceable |
| onset_density | +0.70 | [−0.30, 1.69] | n.s. |
| lhl_syncopation_mean | −0.57 | [−1.59, 0.45] | n.s. |
| spectral_flatness_mean | −1.23 | [−2.37, −0.10] | noisier timbre → less danceable |
| **tempo_final** | **−2.23** | [−3.23, −1.24] | (sign reflects corpus tempo skew; see note) |

**Interpretation.** Audio structure explains a **real but modest** ~18% of danceability variance out-of-sample — squarely in the "weak but credible" range the prereg anticipated (familiarity/style alone explains ~15% per Senn 2018). The two features your project already promoted to render-stage mix biases — **`hpss_percussive_ratio` and `low_band_energy_ratio` — are the dominant, robust positive predictors**, with CIs well clear of zero. That is the key validation for the main generator: these two acoustic dimensions are worth manipulating. The negative `tempo_final` beta is a corpus-tempo-distribution artifact (most tracks already sit above the danceable band), not evidence that slower = groovier — H4's segmented result is the correct tempo read.

---

## What this means for the main GrooveGen project

1. **Validated actuators.** `hpss_percussive_ratio` and `low_band_energy_ratio` credibly track danceability in real recordings → justified as render-stage mix biases in the symbolic generator. ✔
2. **Tempo sweet-spot confirmed** (110–130 BPM) → matches your knob design (`tempo_bpm` inverted-U, peak ~100–126). ✔
3. **Syncopation does NOT show the Witek inverted-U in commercial audio** → *strengthens the rationale for the controlled symbolic perturbation pilot*. You cannot recover the syncopation effect from passive naturalistic audio; it must be studied under parametric manipulation (Track B grid). This is a feature, not a bug — it's the cleanest motivation for the whole BBCI project.
4. **Honest scope:** R² ≈ 0.18 is a methods-note / supplementary-evidence result, not a standalone predictions paper. Frame as "commercial-audio features partially recover danceability; groove must be induced via controlled manipulation."

## Caveats
- Outcome is Spotify's proprietary `song_dance`, not human groove. The Senn-2018 external check (248 drum patterns, 665 raters) remains the recommended upgrade to claim human-groove validity.
- Two feature-name substitutions noted above; re-run with `spectral_flux` if/when extracted.
- eBMRQ-Sensorimotor (`SM_factor`) trait-moderator analysis (Layer 4) NOT run here — needs the per-instance survey join; available on request.

**Artifacts:** `analysis_results.json` (full numbers), `layer1_validation.png`, `layer2_betas.png`, `run_analysis.py` (reproducible).
