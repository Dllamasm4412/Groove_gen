"""
Live-ladder audit and candidate perceptual ladders (analysis only; changes
nothing in the live path). Writes under renders/ladder_audit/<stamp>/.

Inputs: energy_table_v1.json (measured features, presentation gain excluded),
the live tier caps, and the developer's ordinal genre prior
    calm < lofi < rnb < hiphop < latin < pop < rock
(order only; no distances).

Candidates (each scored on all 35 cells, z over 35 as the live ladder, then the
live pipeline: monotone-in-tier bump, tier caps, near-tie groups ordered by
tempo, min-max):
    A        the current measured E (LUFS .40, drum rate .25, tempo .20,
             centroid .10, flux .05); reproduces the live ladder exactly
    A0       A without its tempo term (acoustic only; diagnostic)
    B-lin    A + lambda * prior rank (sensitivity over lambda)
    B-iso    A + a per-genre constant offset: the least-squares smallest shift
             of the genre mean E that puts the genre means in prior order,
             separated by at least `margin` (isotonic regression, PAV)
    C        tempo weight w_t (0.1 .. 0.4) + the B-iso offset
    D        A0 + w_r * the part of tempo NOT predicted by the acoustic
             features (OLS residual) + the B-iso offset
    E        LUFS centred within genre (genre-level loudness treated as mix
             level, as the Rock gain; tier loudness kept), with / without B-iso
    R        rank-based: mean of the E percentile and the prior percentile

Usage:
    python ladder_audit.py [--out renders/ladder_audit/<stamp>]
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PRIOR = ('calm', 'lofi', 'rnb', 'hiphop', 'latin', 'pop', 'rock')
RANK = {g: i for i, g in enumerate(PRIOR)}
FEATS = ('lufs', 'drum_rate', 'tempo_bpm', 'centroid_hz', 'flux')
EXTRA = ('pulse_clarity', 'note_rate', 'low_ratio')
FOCUS = (('rnb', 4), ('rnb', 5), ('latin', 1), ('latin', 2), ('hiphop', 3), ('hiphop', 5), ('pop', 1), ('pop', 5),
         ('rock', 1))
SHARP_BPM_DROP = 10.0


# =============================================================================
# Inputs
# =============================================================================


def load():
    from ladder import _GENRES, load_energy_table
    from run_pilot_zero import ENERGY_TABLE, LIVE_TIER_CAP_OVERRIDES
    from segment_renderer import RUNG_TIER_CAP

    features, weights, tie_band, sha = load_energy_table(ENERGY_TABLE)
    keys = [(g, t) for g in _GENRES for t in range(1, 6)]
    caps = {**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES}
    live = [k for k in keys if k[1] <= caps.get(k[0], 5)]
    return features, weights, tie_band, sha, keys, live, caps


def zmap(features, keys, f):
    v = np.array([float(features[k][f]) for k in keys])
    sd = v.std() or 1.0
    return dict(zip(keys, (v - v.mean()) / sd))


def composite(features, keys, weights):
    z = {f: zmap(features, keys, f) for f in weights}
    return {k: sum(w * z[f][k] for f, w in weights.items()) for k in keys}, z


# =============================================================================
# Ladder pipeline (as ladder._measured_ladder, with any score)
# =============================================================================


def ladder_from(score, features, tie_band, caps, keep_u=None):
    """The live pipeline on a 35-cell score. keep_u: assign these sorted u values
    in the score's order instead of min-max (order-only, as --ladder ear)."""
    from ladder import _filter, _monotone, _to_ladder

    corrected = _filter(_monotone(score), caps, ())
    order = sorted(corrected, key=corrected.get)
    groups, cur = [], [order[0]]
    for a, b in zip(order, order[1:]):
        if corrected[b] - corrected[a] < tie_band:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)
    tied = {}
    for grp in groups:
        vals = sorted(corrected[k] for k in grp)
        tied.update(zip(sorted(grp, key=lambda k: (float(features[k]['tempo_bpm']), corrected[k])), vals))
    if keep_u is not None:
        order = sorted(tied, key=tied.get)
        tied = dict(zip(order, sorted(keep_u)))
        return _to_ladder(tied, 0.0), tied
    return _to_ladder(tied, tie_band), tied


def pav(y, w):
    """Weighted isotonic (non-decreasing) regression, pool adjacent violators."""
    blocks = [[float(v), float(x), 1] for v, x in zip(y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0] + 1e-12:
            a, b = blocks[i], blocks[i + 1]
            wt = a[1] + b[1]
            blocks[i] = [(a[0] * a[1] + b[0] * b[1]) / wt, wt, a[2] + b[2]]
            del blocks[i + 1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [b[0] for b in blocks for _ in range(b[2])]


def genre_offsets(score, keys, margin, cells=None):
    """Per-genre constants: the least-squares smallest change of the genre mean
    score that makes the means non-decreasing in prior order with gaps >= margin."""
    cells = keys if cells is None else cells
    m = [np.mean([score[k] for k in cells if k[0] == g]) for g in PRIOR]
    n = [sum(k[0] == g for k in cells) for g in PRIOR]
    fit = pav([x - margin * i for i, x in enumerate(m)], n)
    return {g: (fit[i] + margin * i) - m[i] for i, g in enumerate(PRIOR)}


def shifted(score, off):
    return {k: v + off[k[0]] for k, v in score.items()}


# =============================================================================
# Metrics
# =============================================================================


def kendall(a, b):
    from scipy.stats import kendalltau
    return float(kendalltau(a, b).statistic)


def describe(name, lad, features, e_a, tie_band, score_used, ref_order):
    cells = [c.gt() for c in lad.cells]
    bpm = [float(features[k]['tempo_bpm']) for k in cells]
    rungs = {k: i for i, k in enumerate(cells)}
    mean_rung = {g: np.mean([rungs[k] for k in cells if k[0] == g]) for g in PRIOR}
    genre_order = sorted(PRIOR, key=mean_rung.get)
    steps = []
    for i, (a, b) in enumerate(zip(cells, cells[1:])):
        flags = []
        if bpm[i + 1] < bpm[i] - SHARP_BPM_DROP:
            flags.append(f'bpm {bpm[i]:.0f}->{bpm[i + 1]:.0f}')
        if e_a[b] < e_a[a] - tie_band:
            flags.append(f'measured E falls {e_a[b] - e_a[a]:+.3f}')
        if RANK[b[0]] < RANK[a[0]]:
            flags.append('genre prior backward')
        if score_used is not None and abs(score_used[b] - score_used[a]) < tie_band:
            flags.append('near tie')
        steps.append((i, a, b, flags))
    pos = {k: rungs.get(k) for k in FOCUS}
    return {
        'name': name, 'cells': cells, 'bpm': bpm, 'u': [c.u for c in lad.cells],
        'genre_mean_rung_order': genre_order, 'genre_order_ok': genre_order == list(PRIOR),
        'tau_prior': kendall([RANK[k[0]] for k in cells], range(len(cells))),
        'tau_vs_current': kendall([ref_order.index(k) for k in cells], range(len(cells))),
        'moved': sum(ref_order.index(k) != i for i, k in enumerate(cells)),
        'max_move': max(abs(ref_order.index(k) - i) for i, k in enumerate(cells)),
        'sharp_bpm_drops': sum(any(f.startswith('bpm') for f in s[3]) for s in steps),
        'e_falls': sum(any(f.startswith('measured') for f in s[3]) for s in steps),
        'prior_backward': sum('genre prior backward' in s[3] for s in steps),
        'near_ties': sum('near tie' in s[3] for s in steps),
        'steps': steps, 'focus': pos, 'mean_rung': mean_rung,
    }


def name(k):
    return f'{k[0]}{k[1]}'


# =============================================================================
# Main
# =============================================================================


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', default=None)
    ap.add_argument('--render-boundaries', action='store_true', help='also render the boundary listening package')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    args = ap.parse_args(argv)
    out = Path(args.out or HERE / 'renders' / 'ladder_audit' / time.strftime('%Y%m%d_%H%M%S'))
    out.mkdir(parents=True, exist_ok=True)

    from run_pilot_zero import ENERGY_TABLE

    features, weights, tie_band, sha, keys, live, caps = load()
    e_a, z = composite(features, keys, weights)
    zx = {f: zmap(features, keys, f) for f in EXTRA}
    acoustic_w = {f: w for f, w in weights.items() if f != 'tempo_bpm'}
    e_a0, _ = composite(features, keys, acoustic_w)
    rep = {'energy_table_sha256': sha, 'weights': weights, 'tie_band_e': tie_band, 'prior': PRIOR}

    # --- current ladder reproduced ------------------------------------------
    from energy_by_ear import live_ladder
    current, _, _ = live_ladder()
    lad_a, tied_a = ladder_from(e_a, features, tie_band, caps)
    assert [c.gt() for c in lad_a.cells] == [c.gt() for c in current.cells], 'A does not reproduce the live ladder'
    assert np.allclose([c.u for c in lad_a.cells], [c.u for c in current.cells])
    cur_order = [c.gt() for c in current.cells]
    cur_u = [c.u for c in current.cells]

    # --- Step 1: per-cell audit table ----------------------------------------
    with (out / 'step1_cell_audit.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['rung', 'cell', 'genre', 'tier', 'bpm', 'u', 'E', 'E_tie_ordered']
                   + [f'contrib_{x}' for x in weights] + [f'z_{x}' for x in EXTRA] + ['genre_prior_rank'])
        for c in current.cells:
            k = c.gt()
            w.writerow([c.rung, name(k), k[0], k[1], features[k]['tempo_bpm'], round(c.u, 4), round(e_a[k], 4),
                        round(tied_a[k], 4)] + [round(wt * z[x][k], 4) for x, wt in weights.items()]
                       + [round(zx[x][k], 3) for x in EXTRA] + [RANK[k[0]] + 1])

    # --- Step 1b: BPM representation -----------------------------------------
    def corr(a, b):
        from scipy.stats import pearsonr, spearmanr
        return round(float(pearsonr(a, b).statistic), 3), round(float(spearmanr(a, b).statistic), 3)

    bpm = {k: float(features[k]['tempo_bpm']) for k in keys}
    bpm_rep = {}
    for label, ks in (('35_cells', keys), ('27_live', live)):
        t = [bpm[k] for k in ks]
        rows = {f: corr(t, [float(features[k][f]) for k in ks])
                for f in ('lufs', 'drum_rate', 'centroid_hz', 'flux', 'pulse_clarity', 'note_rate', 'low_ratio')}
        rows['E_acoustic (A0)'] = corr(t, [e_a0[k] for k in ks])
        rows['E (A, incl. tempo)'] = corr(t, [e_a[k] for k in ks])

        def r2(cols):
            X = np.column_stack([np.ones(len(ks))] + [[float(features[k][c]) for k in ks] for c in cols])
            y = np.array(t)
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            res = y - X @ beta
            return round(1 - res.var() / y.var(), 3)
        gm = {g: np.mean([bpm[k] for k in ks if k[0] == g]) for g in PRIOR}
        eta2 = 1 - sum((bpm[k] - gm[k[0]]) ** 2 for k in ks) / sum((bpm[k] - np.mean(t)) ** 2 for k in ks)
        bpm_rep[label] = {
            'pearson_spearman_with_bpm': rows,
            'R2_bpm_from_E_features(lufs,drum_rate,centroid,flux)': r2(['lufs', 'drum_rate', 'centroid_hz', 'flux']),
            'R2_bpm_from_rhythm(drum_rate,note_rate,flux,pulse_clarity)': r2(['drum_rate', 'note_rate', 'flux', 'pulse_clarity']),
            'R2_bpm_from_all_7': r2(['lufs', 'drum_rate', 'centroid_hz', 'flux', 'pulse_clarity', 'note_rate', 'low_ratio']),
            'eta2_bpm_by_genre': round(float(eta2), 3),
        }
    ev = np.array([e_a[k] for k in keys])
    tt = np.array([weights['tempo_bpm'] * z['tempo_bpm'][k] for k in keys])
    bpm_rep['tempo_term_share_of_E_variance'] = round(float(np.cov(tt, ev)[0, 1] / ev.var(ddof=1)), 3)
    bpm_rep['bpm_by_genre_tier'] = {g: [bpm[(g, t)] for t in range(1, 6)] for g in PRIOR}
    rep['bpm'] = bpm_rep

    # tempo residual (D): OLS of tempo z on the acoustic E features
    X = np.column_stack([np.ones(len(keys))] + [[z[f][k] for k in keys] for f in acoustic_w])
    y = np.array([z['tempo_bpm'][k] for k in keys])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    resid_z = dict(zip(keys, resid / (resid.std() or 1.0)))
    rep['tempo_residual_R2'] = round(float(1 - resid.var() / y.var()), 3)

    # --- Step 1c: tier separation ---------------------------------------------
    tiers = {}
    for g in PRIOR:
        ts = [t for t in range(1, 6) if (g, t) in live]
        steps = [round(e_a[(g, t + 1)] - e_a[(g, t)], 4) for t in ts[:-1]]
        tiers[g] = {'live_tiers': ts, 'E_steps': steps,
                    'below_tie_band': [f'{g}{t}->{g}{t + 1}' for t, s in zip(ts, steps) if s < tie_band],
                    'tier_E_corr': round(float(np.corrcoef(ts, [e_a[(g, t)] for t in ts])[0, 1]), 3) if len(ts) > 2 else None}
        def rel(f, g=g, ts=ts):
            return round(float(features[(g, ts[-1])][f]) - float(features[(g, ts[0])][f]), 3)
        tiers[g]['top_minus_bottom'] = {f: rel(f) for f in ('lufs', 'drum_rate', 'tempo_bpm', 'centroid_hz', 'flux')}
    rep['tiers'] = tiers

    # --- Step 5: candidates -----------------------------------------------------
    cands = {}

    def add(label, score, note, keep=True):
        lad, tied = ladder_from(score, features, tie_band, caps)
        d = describe(label, lad, features, e_a, tie_band, tied, cur_order)
        d['note'] = note
        d['u_gaps'] = {'median': round(float(np.median(np.diff(d['u']))), 4), 'max': round(float(np.max(np.diff(d['u']))), 4),
                       'noise_u': round(lad.noise_u, 4)}
        d['score'] = tied
        if keep:
            cands[label] = d
        return d

    add('A', e_a, 'current measured E (tempo weight .20)')
    add('A0', e_a0, 'acoustic only (tempo weight 0)')
    for lam in (0.05, 0.1, 0.2, 0.3):
        add(f'B-lin {lam}', {k: v + lam * RANK[k[0]] for k, v in e_a.items()}, f'A + {lam} x prior rank')
    margins = (0.0, tie_band, 2 * tie_band, 0.1, 0.2)
    iso = {}
    for mg in margins:
        off = genre_offsets(e_a, keys, mg)
        iso[mg] = off
        add(f'B-iso m={mg:.3f}', shifted(e_a, off), f'A + minimal genre offsets, margin {mg:.3f}')
    off_live = genre_offsets(e_a, keys, tie_band, cells=live)
    add('B-iso(live means) m=tie', shifted(e_a, off_live), 'offsets fitted on live-cell genre means')
    for wt in (0.1, 0.3, 0.4):
        ww = {**weights, 'tempo_bpm': wt}
        e_c, _ = composite(features, keys, ww)
        add(f'C w_t={wt}', shifted(e_c, genre_offsets(e_c, keys, tie_band)), f'tempo weight {wt} + B-iso (margin tie)')
        add(f'C0 w_t={wt}', e_c, f'tempo weight {wt}, no genre prior')
    for wr in (0.1, 0.2, 0.3):
        e_d = {k: e_a0[k] + wr * resid_z[k] for k in keys}
        add(f'D w_r={wr}', shifted(e_d, genre_offsets(e_d, keys, tie_band)), f'A0 + {wr} x tempo residual + B-iso')
    lz = z['lufs']
    gl = {g: np.mean([lz[k] for k in keys if k[0] == g]) for g in PRIOR}
    e_e = {k: v - weights['lufs'] * gl[k[0]] for k, v in e_a.items()}
    add('E', e_e, 'LUFS centred within genre, no prior')
    add('E+iso', shifted(e_e, genre_offsets(e_e, keys, tie_band)), 'LUFS centred within genre + B-iso (margin tie)')
    pct_e = {k: i / (len(keys) - 1) for i, k in enumerate(sorted(keys, key=e_a.get))}
    add('R', {k: 0.5 * pct_e[k] + 0.5 * RANK[k[0]] / 6 for k in keys}, 'mean of E percentile and prior percentile')

    # --- Proposed: B-iso, margin = tie band, order-only (keeps the current u set)
    prop_off = iso[tie_band]
    prop_score = shifted(e_a, prop_off)
    lad_p, tied_p = ladder_from(prop_score, features, tie_band, caps, keep_u=cur_u)
    lad_p_minmax, _ = ladder_from(prop_score, features, tie_band, caps)
    assert [c.gt() for c in lad_p.cells] == [c.gt() for c in lad_p_minmax.cells]
    prop = describe('proposed', lad_p, features, e_a, tie_band, ladder_from(prop_score, features, tie_band, caps)[1], cur_order)
    rep['proposed'] = {'method': 'B-iso, margin = tie_band, order-only (current u set)',
                       'genre_offsets_E': {g: round(v, 4) for g, v in prop_off.items()},
                       'order': [name(k) for k in prop['cells']],
                       'minmax_u_gaps': {'median': round(float(np.median(np.diff([c.u for c in lad_p_minmax.cells]))), 4),
                                         'max': round(float(np.max(np.diff([c.u for c in lad_p_minmax.cells]))), 4),
                                         'noise_u': round(lad_p_minmax.noise_u, 4)},
                       'current_u_gaps': {'median': round(float(np.median(np.diff(cur_u))), 4),
                                          'max': round(float(np.max(np.diff(cur_u))), 4), 'noise_u': round(current.noise_u, 4)}}
    # 35-cell placement (rnb5, latin4-5 are not live)
    full = sorted(keys, key=lambda k: _mono35(prop_score)[k])
    rep['proposed']['order_35_cells'] = [name(k) for k in full]
    rep['proposed']['order_35_cells_A'] = [name(k) for k in sorted(keys, key=lambda k: _mono35(e_a)[k])]

    # ratings file that reproduces the proposed order through --ladder ear
    ear_json = {'description': 'Proposed perceptual ladder (ladder_audit.py B-iso, margin = tie band) expressed '
                               'as by-ear ratings; review only, not applied.',
                'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'energy_table_sha256': sha,
                'ratings': {f'{k[0]}:{k[1]}': float(i + 1) for i, k in enumerate(prop['cells'])}}
    (out / 'proposed_as_ear_ratings.json').write_text(json.dumps(ear_json, indent=1) + '\n')
    from ladder import build_ladder
    ear_check = build_ladder(tier_caps=caps, features=features, weights=weights, tie_band=tie_band,
                             ear_ratings={(k.split(':')[0], int(k.split(':')[1])): v for k, v in ear_json['ratings'].items()})
    assert [c.gt() for c in ear_check.cells] == prop['cells'], '--ladder ear does not reproduce the proposal'
    assert np.allclose([c.u for c in ear_check.cells], cur_u)

    # --- write -------------------------------------------------------------------
    summary = []
    for d in list(cands.values()) + [prop]:
        summary.append({k: d[k] for k in ('name', 'genre_order_ok', 'genre_mean_rung_order', 'tau_prior', 'tau_vs_current',
                                          'moved', 'max_move', 'sharp_bpm_drops', 'e_falls', 'prior_backward', 'near_ties')}
                       | {'focus': {name(k): v for k, v in d['focus'].items()}, 'note': d.get('note', '')})
    rep['candidates'] = summary
    with (out / 'candidate_summary.csv').open('w', newline='') as f:
        w = csv.writer(f)
        cols = ['name', 'genre_order_ok', 'tau_prior', 'tau_vs_current', 'moved', 'max_move', 'sharp_bpm_drops',
                'e_falls', 'prior_backward', 'near_ties']
        w.writerow(cols + [f'rung_{name(k)}' for k in FOCUS] + ['genre_mean_rung_order', 'note'])
        for x in summary:
            w.writerow([round(x[c], 3) if isinstance(x[c], float) else x[c] for c in cols]
                       + [x['focus'][name(k)] for k in FOCUS] + [' '.join(x['genre_mean_rung_order']), x['note']])
    (out / 'report.json').write_text(json.dumps(rep, indent=1, default=str) + '\n')
    with (out / 'candidate_ladders.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['candidate', 'rung', 'cell', 'genre', 'tier', 'bpm', 'E_measured', 'prior_rank', 'score', 'flags_into_next'])
        for d in list(cands.values()) + [prop]:
            sc = d.get('score') or tied_p
            flags = {s[0]: '; '.join(s[3]) for s in d['steps']}
            for i, k in enumerate(d['cells']):
                w.writerow([d['name'], i, name(k), k[0], k[1], features[k]['tempo_bpm'], round(e_a[k], 4), RANK[k[0]] + 1,
                            round(sc[k], 4), flags.get(i, '')])
    (out / 'proposed_ladder.md').write_text(ladder_md(prop, features, e_a, prop_score, cur_order, tie_band))
    # integrity: every live cell once, tiers ascending within each genre
    pc = prop['cells']
    assert len(pc) == len(set(pc)) == len(live) and set(pc) == set(live)
    assert all(pc.index((g, t)) < pc.index((g, t + 1)) for g, t in live if (g, t + 1) in live)
    rep['proposed']['integrity'] = f'{len(pc)} live cells, no duplicates or missing, tiers ascending in every genre'

    # --- Step 10: synthetic controller comparison ---------------------------------
    from run_pilot_zero import EAR_ORDER
    _TEMPO.update({k: float(features[k]['tempo_bpm']) for k in keys})
    ladders = {'measured (current default)': current}
    if EAR_ORDER.exists():
        from ladder import load_ear_ratings
        ladders['ear (energy_order_by_ear.json)'] = build_ladder(
            tier_caps=caps, features=features, weights=weights, tie_band=tie_band,
            ear_ratings=load_ear_ratings(EAR_ORDER)[0])
    ladders['proposed (B-iso, order-only)'] = ear_check
    rep['sim'] = {'ear_ladder': 'present' if EAR_ORDER.exists() else
                  f'{EAR_ORDER.name} does not exist (ratings pending): --ladder ear would fail; not simulated',
                  'summary': simulate(ladders, out)}
    (out / 'report.json').write_text(json.dumps(rep, indent=1, default=str) + '\n')
    if args.render_boundaries:
        render_boundaries(prop['cells'], args.sf2, out)
    print(json.dumps({'out': str(out), 'proposed': rep['proposed']['order']}, indent=0))
    return out


# =============================================================================
# Boundary listening package
# =============================================================================

# Ambiguous boundaries of the proposed ladder, by the categories asked for
# (cross-genre steps that flip vs the measured order, move against the genre
# prior, drop tempo sharply, or are near ties). (lower, upper) in proposed order.
BOUNDARIES = (
    (('hiphop', 1), ('lofi', 1), 'low hip-hop below lo-fi (prior backward)'),
    (('lofi', 3), ('rnb', 1), 'high lo-fi vs low R&B'),
    (('hiphop', 2), ('latin', 1), 'hip-hop -> low Latin (adjacent)'),
    (('latin', 1), ('rock', 1), 'low Latin -> low Rock (adjacent)'),
    (('rock', 1), ('rnb', 1), 'low Rock below low R&B (prior backward)'),
    (('latin', 1), ('rnb', 4), 'top live R&B vs low Latin (rnb5 is not live)'),
    (('rnb', 4), ('latin', 2), 'top R&B -> Latin 2 (near tie; swapped vs measured)'),
    (('latin', 3), ('rock', 2), 'high Latin -> Rock 2 (adjacent)'),
    (('rock', 2), ('pop', 1), 'Rock 2 below low Pop (prior backward)'),
    (('latin', 3), ('hiphop', 3), 'high Latin vs high hip-hop (prior says Latin higher)'),
    (('pop', 4), ('hiphop', 3), 'Pop 4 -> hip-hop 3 (118 -> 90 bpm)'),
    (('hiphop', 3), ('pop', 5), 'hip-hop 3 -> Pop 5 (swapped vs measured)'),
    (('pop', 5), ('rock', 3), 'high Pop -> Rock 3 (swapped vs measured)'),
    (('rock', 3), ('hiphop', 4), 'Rock 3 -> hip-hop 4 (120 -> 93 bpm, prior backward)'),
)
SHEET_FIELDS = ('pair', 'file', 'first', 'second', 'question', 'judgement', 'notes')


def render_boundaries(order, sf2: str, out: Path, seed: int = 20261006) -> Path:
    """One clip per boundary: visit 0 of each cell as live v2c plays it (live
    renderer incl. the Rock gain, live crossfade), in a seeded random order so
    the proposed direction is not implied; sheet.csv to fill in."""
    import random

    from audition_v2 import SAMPLE_RATE, join_like_live, trim_like_live
    from composer.arrangement import SessionComposer, cell_plan
    from energy_by_ear import STIM_SEED
    from segment_renderer import SymbolicSegmentRenderer, _write_wav

    d = out / 'boundaries'
    d.mkdir(parents=True, exist_ok=True)
    r = SymbolicSegmentRenderer(sf2_path=sf2, sr=SAMPLE_RATE, session_seed=42)
    sc = SessionComposer(STIM_SEED, develop=True)
    cache = {}

    def clip(k):
        if k not in cache:
            pm, _ = sc.compose(k[0], k[1], 0)
            tempo = cell_plan(*k)[0]
            cache[k] = (trim_like_live(r._render_pm_to_audio(pm), tempo), tempo)
        return cache[k]

    rng = random.Random(seed)
    rows = []
    for i, (lo, hi, ctx) in enumerate(BOUNDARIES, 1):
        assert order.index(lo) < order.index(hi), (lo, hi)
        first, second = (lo, hi) if rng.random() < 0.5 else (hi, lo)
        fname = f'{i:02d}_{name(first)}_then_{name(second)}.wav'
        joined, _, _ = join_like_live(*zip(clip(first), clip(second)))
        _write_wav(d / fname, joined, SAMPLE_RATE)
        rows.append({'pair': i, 'file': f'boundaries/{fname}', 'first': name(first), 'second': name(second),
                     'question': 'second clip vs first: lower / equal / higher', 'judgement': '', 'notes': ''})
    with (out / 'boundary_sheet.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=SHEET_FIELDS)
        w.writeheader()
        w.writerows(rows)
    key = [{'pair': x['pair'], 'proposed_lower': name(lo), 'proposed_upper': name(hi),
            'proposed_rungs': f'{order.index(lo)} < {order.index(hi)}', 'why': ctx}
           for x, (lo, hi, ctx) in zip(rows, BOUNDARIES)]
    (out / 'boundary_key.json').write_text(json.dumps(key, indent=1) + '\n')
    return d


# =============================================================================
# Synthetic controller comparison (engineering only)
# =============================================================================

# Synthetic first-order HR plants (plant_model.FOPDTPlant; NOT a model of the
# developer and not evidence of any human response): a responder that can reach
# the up target, and a weak responder that saturates the top of the ladder.
SIM_SUBJECTS = {'responder K=14': 14.0, 'weak responder K=3': 3.0}
SIM_BASELINE = 72.0
SIM_SEGMENTS = 40
SIM_UP, SIM_DOWN = 10.0, -4.0          # run_pilot_zero default phases: up +10, then down -4


def simulate(ladders: dict, out: Path, seed: int = 7) -> list[dict]:
    """Each ladder under the same synthetic plant, noise stream and target
    schedule (up for the first half, down for the second), with the live
    controller config (1 rung per segment, rotation on, band 2x noise_u,
    rotation_no_repeat default). Segment length = 8 bars at the cell's tempo."""
    import random

    from control import ControllerConfig, LadderMPC
    from plant_model import FOPDTPlant, Subject

    rows, summary = [], []
    for subj, K in SIM_SUBJECTS.items():
        for lname, lad in ladders.items():
            ctrl = LadderMPC(lad, ControllerConfig(max_step_per_segment=1, saturation_rotation=True,
                                                   rotation_band_u=2.0 * lad.noise_u))
            plant = FOPDTPlant(Subject(SIM_BASELINE, K, 60.0, 1, 1.0, 'synthetic'), dt=18.0,
                               noise_sigma=1.0, rng=random.Random(seed))
            rung, hr, seq = lad.index('lofi', 3), SIM_BASELINE, []
            for k in range(SIM_SEGMENTS):
                target = SIM_BASELINE + (SIM_UP if k < SIM_SEGMENTS // 2 else SIM_DOWN)
                d = ctrl.step(hr_bpm=hr, hr_target=target, hr_base=SIM_BASELINE, current_rung=rung)
                cell = lad.by_rung[d.next_rung]
                plant.dt = 8 * 4 * 60.0 / features_tempo(cell.gt())
                hr = plant.step(cell.u)
                seq.append(cell)
                rows.append({'subject': subj, 'ladder': lname, 'seg': k, 'target': target, 'rung': d.next_rung,
                             'cell': name(cell.gt()), 'u': round(cell.u, 4), 'mode': d.control_mode,
                             'saturation': d.saturation_state, 'hr_after': hr,
                             'abs_err_raw': round(abs(hr - target), 3),
                             'abs_err_governed': round(abs(hr - d.governed_r), 3)})
                rung = d.next_rung
            cells = [name(c.gt()) for c in seq]
            moves = [b.rung - a.rung for a, b in zip(seq, seq[1:])]
            summary.append({'subject': subj, 'ladder': lname, 'cells': ' '.join(cells),
                            'up_steps': sum(m > 0 for m in moves), 'down_steps': sum(m < 0 for m in moves),
                            'holds': sum(m == 0 for m in moves), 'max_step': max(abs(m) for m in moves),
                            'rotations': sum(r['mode'] == 'rotate' for r in rows[-SIM_SEGMENTS:]),
                            'genre_changes': sum(a.genre != b.genre for a, b in zip(seq, seq[1:])),
                            'distinct_cells': len(set(cells)),
                            'mae_raw': round(np.mean([r['abs_err_raw'] for r in rows[-SIM_SEGMENTS:]]), 3),
                            'mae_governed': round(np.mean([r['abs_err_governed'] for r in rows[-SIM_SEGMENTS:]]), 3),
                            'u_sequence_sha': hash_list([r['u'] for r in rows[-SIM_SEGMENTS:]])})
    with (out / 'sim_segments.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (out / 'sim_summary.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    return summary


_TEMPO: dict = {}


def features_tempo(k):
    return _TEMPO[k]


def hash_list(xs) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(xs).encode()).hexdigest()[:12]


def _mono35(score):
    from ladder import _monotone
    return _monotone(score)


def ladder_md(d, features, e_a, score, cur_order, tie_band):
    rows = ['| rung | cell | BPM | measured E | prior rank | composite | was rung | into next |',
            '|---:|---|---:|---:|---:|---:|---:|---|']
    flags = {s[0]: '; '.join(s[3]) for s in d['steps']}
    for i, k in enumerate(d['cells']):
        rows.append(f"| {i} | {name(k)} | {features[k]['tempo_bpm']:.0f} | {e_a[k]:+.3f} | {RANK[k[0]] + 1} | "
                    f"{score[k]:+.3f} | {cur_order.index(k)} | {flags.get(i, '')} |")
    return '# Proposed ladder (B-iso, margin = tie band, order-only)\n\n' + '\n'.join(rows) + '\n'


if __name__ == '__main__':
    main()
