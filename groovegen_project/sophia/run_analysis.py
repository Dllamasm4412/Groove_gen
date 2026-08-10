"""
Sophia secondary analysis — Phase 5, Layers 1 & 2 (per phase0 preregistration).

CORRECTED FRAMING (per Daniel's Phase 1 audit):
  - NO participant groove/dance-urge rating exists in the dataset.
  - 'music_condition' (self-relevant / sensory-motor / peer / computer) is the
    experimental FACTOR, not a per-trial dance judgment.
  - The only dance variable is Spotify 'song_dance' (0-100), a song-constant.
  - Unit of analysis = unique tracks (dedup on trackID).

Layer 1 — groove_proxy validation (theory-grounded, unit-weighted, z-scored):
  H1 convergent : corr(groove_proxy, song_dance) >= 0.50
  H2 discriminant: corr(groove_proxy, song_dance) > corr(groove_proxy, song_energy)
  H3 Witek      : inverted-U of song_dance on syncopation (neg quadratic term)
  H4 Janata     : song_dance peaks in ~110-130 BPM band (segmented look)

Layer 2 — acoustic predictors of song_dance:
  - 7-feature linear regression (interpretable betas + 95% CI), song-held-out CV
  - permutation feature importance
All effect sizes reported with bootstrap / CV CIs. No p-value-only claims.
"""
import json, warnings, sys, os
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.model_selection import KFold
from sklearn.preprocessing import StandardScaler
warnings.filterwarnings("ignore")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

FEAT = str(config.TRACK_FEATURES_CSV)
SURV = str(config.SURVEY_CSV)
OUT = str(config.ANALYSIS_JSON)
RNG = np.random.default_rng(0)


def boot_ci(x, y, fn, n=5000):
    """Bootstrap 95% CI for a 2-sample statistic fn(x,y)."""
    idx = np.arange(len(x))
    vals = []
    for _ in range(n):
        b = RNG.choice(idx, len(idx), replace=True)
        vals.append(fn(x[b], y[b]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main():
    feats = pd.read_csv(FEAT)
    surv = pd.read_csv(SURV)

    # song-level Spotify metadata (one row per unique track)
    meta_cols = ["trackID", "song_dance", "song_energy", "song_valence",
                 "song_bpm", "song_popularity", "artist_genres"]
    meta = surv[meta_cols].drop_duplicates(subset="trackID").reset_index(drop=True)

    df = feats.merge(meta, on="trackID", how="left")
    df = df.dropna(subset=["song_dance"]).reset_index(drop=True)

    results = {"data": {}}
    results["data"]["n_feature_tracks"] = int(len(feats))
    results["data"]["n_unique_songs_in_survey"] = int(surv["trackID"].nunique())
    results["data"]["n_merged_with_song_dance"] = int(len(df))
    results["data"]["song_dance_range"] = [float(df.song_dance.min()), float(df.song_dance.max())]
    results["data"]["song_dance_mean_sd"] = [float(df.song_dance.mean()), float(df.song_dance.std())]

    # ---- build groove_proxy (unit weights, z-scored, k=0) ----
    def z(s):
        return (s - s.mean()) / s.std(ddof=0)
    comp = {
        "beat_consistency": z(df["beat_consistency"]),
        "plp_mean": z(df["plp_mean"]),
        "hpss_percussive_ratio": z(df["hpss_percussive_ratio"]),
        "low_band_energy_ratio": z(df["low_band_energy_ratio"]),
    }
    z_sync = z(df["lhl_syncopation_mean"])
    df["groove_proxy"] = (comp["beat_consistency"] + comp["plp_mean"]
                          + comp["hpss_percussive_ratio"] + comp["low_band_energy_ratio"]
                          - (z_sync - 0.0) ** 2)
    df = df.dropna(subset=["groove_proxy"]).reset_index(drop=True)

    gp = df["groove_proxy"].values
    sd = df["song_dance"].values.astype(float)
    se = df["song_energy"].values.astype(float)
    # recompute z_sync on the SAME cleaned df so all arrays align
    z_sync = z(df["lhl_syncopation_mean"])

    # ===== LAYER 1 =====
    L1 = {}
    # H1 convergent
    r_dance = stats.pearsonr(gp, sd)[0]
    rho_dance = stats.spearmanr(gp, sd)[0]
    ci_r = boot_ci(gp, sd, lambda a, b: stats.pearsonr(a, b)[0])
    L1["H1_convergent"] = {
        "pearson_r": round(float(r_dance), 4),
        "pearson_95ci": [round(ci_r[0], 4), round(ci_r[1], 4)],
        "spearman_rho": round(float(rho_dance), 4),
        "threshold": 0.50,
        "pass": bool(r_dance >= 0.50),
    }
    # H2 discriminant
    r_energy = stats.pearsonr(gp, se)[0]
    L1["H2_discriminant"] = {
        "r_groove_dance": round(float(r_dance), 4),
        "r_groove_energy": round(float(r_energy), 4),
        "pass": bool(abs(r_dance) > abs(r_energy)),
    }
    # H3 Witek inverted-U: regress song_dance on z_sync + z_sync^2
    X3 = np.column_stack([z_sync.values, z_sync.values ** 2])
    m3 = LinearRegression().fit(X3, sd)
    # significance of quadratic term via OLS stats
    import statsmodels.api as sm
    Xc = sm.add_constant(X3)
    ols3 = sm.OLS(sd, Xc).fit()
    L1["H3_witek_invertedU"] = {
        "linear_beta": round(float(ols3.params[1]), 4),
        "quadratic_beta": round(float(ols3.params[2]), 4),
        "quadratic_p": round(float(ols3.pvalues[2]), 4),
        "quadratic_negative": bool(ols3.params[2] < 0),
        "pass": bool(ols3.params[2] < 0 and ols3.pvalues[2] < 0.05),
        "note": "Inverted-U requires NEGATIVE, significant quadratic term.",
    }
    # H4 Janata tempo band: mean song_dance inside vs outside 110-130 BPM
    bpm = df["song_bpm"].values.astype(float)
    inband = (bpm >= 110) & (bpm <= 130)
    L1["H4_janata_tempoband"] = {
        "n_in_110_130": int(inband.sum()),
        "mean_dance_inband": round(float(sd[inband].mean()), 2) if inband.sum() else None,
        "mean_dance_outband": round(float(sd[~inband].mean()), 2),
        "diff": round(float(sd[inband].mean() - sd[~inband].mean()), 2) if inband.sum() else None,
        "t_test_p": round(float(stats.ttest_ind(sd[inband], sd[~inband], equal_var=False)[1]), 4) if inband.sum() else None,
    }
    results["layer1"] = L1

    # ===== LAYER 2: acoustic predictors of song_dance =====
    # prereg 7-feature set; substitute names present in this file:
    #   onset_rate -> onset_density ; spectral_flux_mean -> spectral_flatness_mean (noted)
    L2_FEATURES = ["tempo_final", "lhl_syncopation_mean", "hpss_percussive_ratio",
                   "onset_density", "beat_consistency", "low_band_energy_ratio",
                   "spectral_flatness_mean"]
    sub = df.dropna(subset=L2_FEATURES + ["song_dance"]).reset_index(drop=True)
    X = sub[L2_FEATURES].values
    y = sub["song_dance"].values.astype(float)
    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    # in-sample interpretable OLS with CIs
    Xc2 = sm.add_constant(Xs)
    ols2 = sm.OLS(y, Xc2).fit()
    betas = {}
    for i, f in enumerate(L2_FEATURES):
        ci = ols2.conf_int()[i + 1]
        betas[f] = {"beta_std": round(float(ols2.params[i + 1]), 3),
                    "95ci": [round(float(ci[0]), 3), round(float(ci[1]), 3)],
                    "p": round(float(ols2.pvalues[i + 1]), 4)}
    # song-held-out CV R2 (each track is its own group => plain KFold on unique tracks)
    kf = KFold(n_splits=10, shuffle=True, random_state=0)
    r2s, rhos = [], []
    for tr, te in kf.split(Xs):
        m = LinearRegression().fit(Xs[tr], y[tr])
        pred = m.predict(Xs[te])
        ss_res = np.sum((y[te] - pred) ** 2)
        ss_tot = np.sum((y[te] - y[tr].mean()) ** 2)
        r2s.append(1 - ss_res / ss_tot)
        rhos.append(stats.spearmanr(y[te], pred)[0])
    results["layer2"] = {
        "n_tracks": int(len(sub)),
        "features_used": L2_FEATURES,
        "feature_name_substitutions": {
            "onset_rate->onset_density": "prereg name not in file; using onset_density",
            "spectral_flux_mean->spectral_flatness_mean": "spectral_flux not extracted; flatness used as proxy timbre feature"},
        "in_sample_R2": round(float(ols2.rsquared), 4),
        "in_sample_adjR2": round(float(ols2.rsquared_adj), 4),
        "cv_R2_mean": round(float(np.mean(r2s)), 4),
        "cv_R2_sd": round(float(np.std(r2s)), 4),
        "cv_spearman_mean": round(float(np.mean(rhos)), 4),
        "cv_spearman_sd": round(float(np.std(rhos)), 4),
        "standardized_betas": betas,
    }

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
