"""Sophia secondary analysis (co-authored): does trait Sensory-Motor music-reward
(eBMRQ SM_factor) MODERATE the danceability gap between a participant's
sensory-motor picks and their self-relevant picks?

Hypothesis (your idea):
  People high in trait Sensory-Motor reward should show a LARGER danceability
  gap (SM picks >> SR picks) than people low in the trait. I.e. trait SM
  predicts the within-person SM-vs-SR difference in song danceability.

Design: 122 participants x (2 sensory-motor + 2 self-relevant) trials.
Unit = trial. Proper test = linear mixed model with random intercept per
participant:  song_dance ~ condition * SM_factor_c  + (1 | Participant)
where condition is sensory-motor(1) vs self-relevant(0), SM_factor_c is
person-mean-centered trait. The condition:SM_factor interaction IS the
moderation test.

We also report the simpler, transparent version: per-participant gap
(mean SM dance - mean SR dance) regressed on SM_factor.
"""
import sys, os
import pandas as pd
import numpy as np
import statsmodels.formula.api as smf
from scipy import stats
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

SURVEY = str(config.SURVEY_CSV)

df = pd.read_csv(SURVEY)
# keep only the two participant-selected conditions
d = df[df.music_condition.isin(["sensory-motor", "self-relevant"])].copy()
d["cond_sm"] = (d.music_condition == "sensory-motor").astype(int)

# trait moderators of interest
d = d.dropna(subset=["song_dance", "SM_factor", "Participant"])

results = {}

# ---- (1) Linear mixed model: the proper moderation test ----
# center AND standardize SM_factor (T-score) for interpretable, well-scaled betas
d["SM_z"] = (d["SM_factor"] - d["SM_factor"].mean()) / d["SM_factor"].std()
md = smf.mixedlm("song_dance ~ cond_sm * SM_z", d, groups=d["Participant"])
try:
    mfit = md.fit(method="powell", reml=True, maxiter=2000)
except Exception:
    mfit = md.fit(method="cg", reml=True, maxiter=2000)
print("=== Linear mixed model: song_dance ~ condition * SM_factor + (1|P) ===")
print(mfit.summary().tables[1])

inter_beta = mfit.params.get("cond_sm:SM_z", float("nan"))
inter_p = mfit.pvalues.get("cond_sm:SM_z", float("nan"))
cond_beta = mfit.params.get("cond_sm", float("nan"))
cond_p = mfit.pvalues.get("cond_sm", float("nan"))
results["mixedlm"] = {
    "condition_main_beta": round(float(cond_beta), 3),
    "condition_main_p": round(float(cond_p), 4),
    "interaction_cond_x_SMfactor_beta_per_SD": round(float(inter_beta), 4),
    "interaction_p": round(float(inter_p), 4),
    "n_trials": int(len(d)),
    "n_participants": int(d.Participant.nunique()),
}

# ---- (2) Transparent per-participant gap regression ----
g = (d.groupby(["Participant", "music_condition"])["song_dance"].mean()
       .unstack("music_condition"))
g = g.dropna(subset=["sensory-motor", "self-relevant"])
g["gap"] = g["sensory-motor"] - g["self-relevant"]
trait = d.groupby("Participant")["SM_factor"].first()
g = g.join(trait)
r, p = stats.pearsonr(g["SM_factor"], g["gap"])
sr, sp = stats.spearmanr(g["SM_factor"], g["gap"])
print("\n=== Per-participant: gap (SM dance - SR dance) vs trait SM_factor ===")
print(f"  n participants with both conditions: {len(g)}")
print(f"  mean gap = {g['gap'].mean():.2f} (SD {g['gap'].std():.2f})")
print(f"  Pearson r(SM_factor, gap) = {r:.3f}, p = {p:.4f}")
print(f"  Spearman rho = {sr:.3f}, p = {sp:.4f}")
results["per_participant_gap"] = {
    "n": int(len(g)),
    "mean_gap": round(float(g["gap"].mean()), 2),
    "sd_gap": round(float(g["gap"].std()), 2),
    "pearson_r": round(float(r), 3), "pearson_p": round(float(p), 4),
    "spearman_rho": round(float(sr), 3), "spearman_p": round(float(sp), 4),
}

# ---- (3) sensitivity: same with SM_raw and with eBMRQ overall, plus song_energy outcome ----
extra = {}
for trait_col in ["SM_raw", "SM_factor", "eBMRQ_factor"]:
    tt = d.groupby("Participant")[trait_col].first()
    gg = g.drop(columns=[c for c in ["SM_factor"] if c in g.columns]).join(tt, how="left")
    rr, pp = stats.pearsonr(gg[trait_col], gg["gap"])
    extra[f"gap_vs_{trait_col}"] = {"pearson_r": round(float(rr), 3), "p": round(float(pp), 4)}
results["sensitivity"] = extra

with open(str(config.TRAIT_MODERATOR_JSON), "w") as f:
    json.dump(results, f, indent=2)
print("\nSaved trait_moderator_results.json")
print(json.dumps(results, indent=2))
