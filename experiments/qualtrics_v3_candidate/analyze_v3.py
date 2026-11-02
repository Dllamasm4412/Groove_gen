"""
Pre-specified analysis of the v3 candidate study (draft: the researcher adopts
or edits it before enrolment). Runs on the output of import_v3_export.py.

Primary (danceability, confirmatory direction: higher intended danceability ->
higher desire-to-move ratings):
    danceability ~ intended_danceability + C(genre) + (1 | participant)
    intended_danceability = within-genre tier (danceability_coding.py); genre as
    fixed effects, so the slope comes from comparisons within genres.
  Sensitivity S1: crossed random intercepts for participant and stimulus (one
    composition per condition: the stimulus intercept absorbs composition identity).
  Sensitivity S2: + delivered loudness (LUFS) as a covariate (loudness rises
    with tier in several genres; tier and loudness cannot be fully separated).
  Sensitivity S3: suggested_include responses only vs all complete responses.
  Descriptive: the tier slope within each genre.

Secondary (calming, exploratory, no directional hypothesis):
  per-excerpt mean, median, SD and 95% CI; by genre and tier; the
  danceability-calming association (within each participant, and across
  excerpt means); excerpts rated high on both scales (rule fixed in advance:
  excerpt mean >= 60 on both, and top third of excerpt means on both); and
  Spearman correlations of excerpt-mean calming with the measured features
  (Holm-adjusted, descriptive; associations, not effects of features).

Usage (repository root):
    python experiments/qualtrics_v3_candidate/analyze_v3.py <import dir>
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEATURES = ('lufs_integrated', 'tempo_bpm', 'drum_onsets_per_s', 'notes_per_s', 'bass_notes_per_bar',
            'offbeat_index', 'centroid_hz', 'flux', 'pulse_clarity', 'energy_u_delivered')
HIGH_ABS = 60.0


def _fit(formula: str, df: pd.DataFrame, crossed: bool = False):
    import statsmodels.formula.api as smf

    if crossed:
        d = df.assign(_one=1)
        m = smf.mixedlm(formula, d, groups='_one', re_formula='0',
                        vc_formula={'participant': '0 + C(participant)', 'stimulus': '0 + C(stimulus_id)'})
    else:
        m = smf.mixedlm(formula, df, groups='participant')
    # statsmodels' lbfgs can fail outright from its zero random-effect start (LinAlgError) instead of falling
    # back, so each optimizer is tried in turn; the one used is recorded with the result.
    errors = []
    for method in ('lbfgs', 'bfgs', 'powell', 'nm'):
        try:
            res = m.fit(reml=True, method=method)
        except (np.linalg.LinAlgError, ValueError) as e:
            errors.append(f'{method}: {type(e).__name__}')
            continue
        res.gg_method = method
        res.gg_failed = errors
        return res
    raise RuntimeError(f'no optimizer converged for {formula!r}: {errors}')


def _coef(res, name: str) -> dict:
    ci = res.conf_int().loc[name]
    return {'estimate': round(float(res.params[name]), 3), 'se': round(float(res.bse[name]), 3),
            'ci95': [round(float(ci[0]), 3), round(float(ci[1]), 3)], 'p': float(res.pvalues[name]),
            'converged': bool(getattr(res, 'converged', True)), 'optimizer': getattr(res, 'gg_method', ''),
            'optimizers_failed': getattr(res, 'gg_failed', [])}


def primary(df: pd.DataFrame) -> dict:
    out = {}
    f = 'danceability ~ intended_danceability + C(genre)'
    out['primary'] = _coef(_fit(f, df), 'intended_danceability')
    out['S1_crossed_participant_stimulus'] = _coef(_fit(f, df, crossed=True), 'intended_danceability')
    out['S2_plus_loudness'] = _coef(_fit(f + ' + lufs_integrated', df), 'intended_danceability')
    inc = df[df['suggested_include']]
    if inc['participant'].nunique() >= 2 and len(inc) < len(df):
        out['S3_suggested_include_only'] = _coef(_fit(f, inc), 'intended_danceability')
    slopes = {}
    for g, d in df.groupby('genre'):
        if d['intended_danceability'].nunique() < 2:
            continue
        y = d['danceability'] - d.groupby('participant')['danceability'].transform('mean')
        x = d['intended_danceability'] - d['intended_danceability'].mean()
        slopes[g] = round(float((x * y).sum() / (x * x).sum()), 3)
    out['within_genre_slopes_descriptive'] = slopes
    return out


def _ci(x: pd.Series) -> tuple[float, float]:
    from scipy import stats

    n = x.count()
    if n < 2:
        return (math.nan, math.nan)
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / math.sqrt(n)
    return (round(x.mean() - h, 2), round(x.mean() + h, 2))


def secondary(df: pd.DataFrame, stim_cols: list[str]) -> dict:
    from scipy import stats

    by = df.groupby('stimulus_id')
    s = pd.DataFrame({
        'calming_mean': by['calming'].mean().round(2), 'calming_median': by['calming'].median(),
        'calming_sd': by['calming'].std().round(2),
        'danceability_mean': by['danceability'].mean().round(2), 'danceability_median': by['danceability'].median(),
        'danceability_sd': by['danceability'].std().round(2), 'n': by['calming'].count()})
    s['calming_ci95'] = [_ci(g['calming']) for _, g in by]
    s['danceability_ci95'] = [_ci(g['danceability']) for _, g in by]
    meta = df.drop_duplicates('stimulus_id').set_index('stimulus_id')[stim_cols]
    s = s.join(meta)
    within = []
    for _, d in df.groupby('participant'):
        if d['calming'].nunique() > 1 and d['danceability'].nunique() > 1:
            within.append(stats.spearmanr(d['danceability'], d['calming']).statistic)
    q = s['calming_mean'].quantile(2 / 3), s['danceability_mean'].quantile(2 / 3)
    feats = []
    for f in FEATURES:
        if f in s and s[f].nunique() > 1:          # a feature constant across excerpts has no association to test
            r = stats.spearmanr(s[f], s['calming_mean'])
            feats.append({'feature': f, 'spearman_rho': round(float(r.statistic), 3), 'p': float(r.pvalue)})
    ps = sorted(range(len(feats)), key=lambda i: feats[i]['p'])
    m = len(feats)
    running = 0.0
    for rank, i in enumerate(ps):
        running = max(running, min(1.0, (m - rank) * feats[i]['p']))
        feats[i]['p_holm'] = round(running, 4)
    return {
        'per_excerpt': s.reset_index().to_dict('records'),
        'by_genre': df.groupby('genre')[['calming', 'danceability']].mean().round(2).to_dict('index'),
        'by_genre_tier': {f'{g}:{t}': v for (g, t), v in
                          df.groupby(['genre', 'tier'])[['calming', 'danceability']].mean().round(2).to_dict('index').items()},
        'within_participant_spearman': {'median': None if not within else round(float(np.median(within)), 3),
                                        'iqr': None if not within else [round(float(np.percentile(within, 25)), 3),
                                                                        round(float(np.percentile(within, 75)), 3)],
                                        'n_participants': len(within),
                                        'share_positive': None if not within else round(float(np.mean(np.array(within) > 0)), 3)},
        'excerpt_mean_spearman': round(float(stats.spearmanr(s['danceability_mean'], s['calming_mean']).statistic), 3),
        'high_on_both_absolute_60': sorted(s.index[(s['calming_mean'] >= HIGH_ABS) & (s['danceability_mean'] >= HIGH_ABS)]),
        'high_on_both_top_third': sorted(s.index[(s['calming_mean'] >= q[0]) & (s['danceability_mean'] >= q[1])]),
        'calming_feature_associations': feats,
    }


def report(res: dict, n_people: int, n_rows: int) -> str:
    p = res['primary']
    L = ['# v3 candidate study: analysis output', '',
         f'{n_people} participants, {n_rows} participant x excerpt ratings.', '',
         '## Primary: intended danceability and desire to move', '',
         '| Model | Slope per tier (0-100 scale) | 95% CI | p | Converged (optimizer) |', '|---|---|---|---|---|']
    for k, v in p.items():
        if isinstance(v, dict) and 'estimate' in v:
            L.append(f"| {k} | {v['estimate']} | {v['ci95'][0]} to {v['ci95'][1]} | {v['p']:.3g} | "
                     f"{'yes' if v['converged'] else 'NO'} ({v['optimizer']}) |")
    L += ['', f"Within-genre slopes (descriptive): {p['within_genre_slopes_descriptive']}", '',
          'One composition per condition: tier, composition and (in several genres) loudness change together, so '
          'the slope describes these configurations, not the effect of any single musical feature.', '',
          '## Secondary (exploratory): calming', '']
    s = res['secondary']
    L += [f"Danceability-calming association: median within-participant Spearman "
          f"{s['within_participant_spearman']['median']} (IQR {s['within_participant_spearman']['iqr']}, "
          f"{s['within_participant_spearman']['share_positive']} of participants positive); across excerpt means "
          f"{s['excerpt_mean_spearman']}.",
          f"Excerpts with mean >= 60 on both: {s['high_on_both_absolute_60'] or 'none'}; in the top third on both: "
          f"{s['high_on_both_top_third'] or 'none'}.", '',
          '| Feature | Spearman with excerpt-mean calming | p (Holm) |', '|---|---|---|']
    L += [f"| {f['feature']} | {f['spearman_rho']} | {f['p_holm']} |" for f in s['calming_feature_associations']]
    L += ['', 'Exploratory: associations across 27 excerpts, not evidence that a feature causes relaxation.', '']
    return '\n'.join(L)


def run(import_dir: Path, out: Path | None = None) -> dict:
    df = pd.read_csv(import_dir / 'ratings_long.csv')
    people = pd.read_csv(import_dir / 'participants.csv')
    df = df.merge(people[['participant', 'suggested_include']], on='participant', how='left')
    df = df.dropna(subset=['danceability', 'calming', 'intended_danceability'])
    df['intended_danceability'] = df['intended_danceability'].astype(float)
    res = {'primary': primary(df),
           'secondary': secondary(df, ['condition_id', 'genre', 'tier', *[f for f in FEATURES if f in df]])}
    out = out or import_dir
    (out / 'analysis_results.json').write_text(json.dumps(res, indent=1, default=str))
    (out / 'analysis_report.md').write_text(report(res, df['participant'].nunique(), len(df)))
    pd.DataFrame(res['secondary']['per_excerpt']).to_csv(out / 'excerpt_summary.csv', index=False)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('import_dir', type=Path)
    a = ap.parse_args(argv)
    run(a.import_dir)
    print(f'wrote {a.import_dir / "analysis_report.md"}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
