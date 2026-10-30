"""
Analyze Experiment 1 (remote) ratings from one or more Qualtrics CSV exports.

Usage (from the repository root):
    .venv/bin/python3.12 experiments/music_rating/qualtrics/analyze_ratings.py
    .venv/bin/python3.12 experiments/music_rating/qualtrics/analyze_ratings.py surveys/first_surveys.csv
    ... analyze_ratings.py --include-preview        # also keep Qualtrics preview responses
    ... analyze_ratings.py --all                    # keep every response, ignoring quality flags

Inputs: CSV files or folders of them (default: surveys/). Exports may overlap;
each ResponseId is kept once (the copy in the newest file wins).

Inclusion: by default the importer's suggested_include (normal response, finished,
all 27 clips rated and fully played, headphones "Yes", attention item >= 90,
not straight-lining, not a phone/tablet). Every exclusion is listed with its reason.

Writes study_data/music_rating_qualtrics/analysis_<date>_<time>/ (gitignored):
    report.md             the summary below, in words and tables
    cells.csv             per clip (ladder order): n, mean, median, SD, 95% CI
                          for both ratings, on 0-100 and 0-5, plus the
                          within-participant z-score mean
    genres.csv            the same per genre
    participants.csv      per participant: inclusion and reasons, mean, SD,
                          and Spearman rho of each rating with ladder rung and
                          with presentation position
    ratings_included.csv  the long table actually analyzed
    ladder_ratings.png    cell means vs ladder rung, both ratings
    dance_vs_calm.png     cell means of danceability against calming

The ratings describe each clip as rendered by the locked system, loudness
included; they are not measurements of composition independent of loudness.
With few participants every number here is descriptive.
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy import stats

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
REPO = EXP.parent.parent
for p in (EXP, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import headphone_check as hc  # noqa: E402
import import_qualtrics as iq  # noqa: E402
import stimuli as st  # noqa: E402

DEFAULT_INPUT = REPO / 'surveys'
OUT_ROOT = REPO / 'study_data' / 'music_rating_qualtrics'
SCALES = ('danceability', 'calming')
BOOT = 10_000
SEED = 20261029
RANK_SHIFT = 5           # "off the ladder": rank by mean this far from the expected rank
EXPECTED = {'danceability': +1, 'calming': -1}   # danceability should rise with the rung, calming fall
BOTH_Z = 0.5             # "high/low on both" threshold on within-participant z
MIN_N_INFERENCE = 5      # below this, no CIs across participants are reported

# Categorical genre colors (fixed order, validated for CVD); marker shape is the
# secondary encoding and every point is labeled, so color never carries identity alone.
GENRE_ORDER = ('calm', 'lofi', 'rnb', 'latin', 'pop', 'hiphop', 'rock')
GENRE_COLOR = dict(zip(GENRE_ORDER, ('#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6')))
GENRE_MARKER = dict(zip(GENRE_ORDER, ('o', 's', 'D', '^', 'v', 'P', 'X')))
INK, INK2, GRID = '#1f2933', '#52606d', '#e4e7eb'


# =============================================================================
# Loading
# =============================================================================

def export_files(inputs: list[Path]) -> list[Path]:
    files = []
    for p in inputs:
        files += sorted(p.glob('*.csv')) if p.is_dir() else [p]
    if not files:
        raise SystemExit(f'no CSV exports found in {", ".join(map(str, inputs))}')
    return sorted(set(files), key=lambda f: f.stat().st_mtime)


def load(files: list[Path], manifest: dict, hpm: dict, loop_prefix: str) -> tuple[list, list, list, dict]:
    """(long rows, participants, problems, source file per response); newest copy of a ResponseId wins."""
    per_response: dict[str, tuple[list, dict, list, Path]] = {}
    for f in files:
        header, rows = iq.read_export(f)
        if not any(c.endswith('_dance_1') for c in header):
            print(f'skipping {f.name}: not a music-rating export', file=sys.stderr)
            continue
        for r in rows:
            long_rows, people, problems = iq.import_rows([r], header, manifest, hpm, loop_prefix)
            if people:
                per_response[people[0]['response_id']] = (long_rows, people[0], problems, f)
    long_rows, people, problems, source = [], [], [], {}
    for rid, (lr, p, pr, f) in per_response.items():
        long_rows += lr
        people.append(p)
        problems += pr
        source[rid] = f.name
    return long_rows, people, problems, source


def exclusion_reasons(p: dict, include_preview: bool) -> list[str]:
    out = []
    if p['status'] not in iq.NORMAL_STATUS and not (include_preview and p['status'] in ('1', 'Survey Preview')):
        out.append(f"status {p['status']}")
    if p['finished'] not in iq.FINISHED_YES:
        out.append('not finished')
    if not p['complete_27']:
        out.append(f"{p['n_rated']}/27 clips rated")
    if not p['all_full_play']:
        out.append('a clip not fully played')
    headphones = p['headphone_pass'] if p['headphone_pass'] is not None else p['headphones_self_report']
    if not headphones:
        out.append(f"headphones: {p.get('post_headphones') or 'no answer'}")
    if not p['attention_pass']:
        out.append(f"attention item {p['attention_value']}")
    if p['straightline']:
        out.append('straight-lining')
    if p['mobile']:
        out.append('phone/tablet')
    return out


# =============================================================================
# Statistics
# =============================================================================

def add_z(rows: list[dict]) -> None:
    """Within-participant z-scores, so differences in how people use the scale drop out."""
    by_p: dict[str, list[dict]] = {}
    for t in rows:
        by_p.setdefault(t['response_id'], []).append(t)
    for ts in by_p.values():
        for k in SCALES:
            v = [t[k] for t in ts]
            m, s = statistics.fmean(v), statistics.pstdev(v)
            for t in ts:
                t[f'{k}_z'] = (t[k] - m) / s if s > 0 else 0.0


def boot_ci(values: list[float], rng: np.random.Generator) -> tuple[float | None, float | None]:
    if len(values) < MIN_N_INFERENCE:
        return None, None
    a = np.asarray(values, dtype=float)
    means = a[rng.integers(0, len(a), size=(BOOT, len(a)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def describe(group: list[dict], rng: np.random.Generator) -> dict:
    out: dict = {'n': len(group)}
    for k in SCALES:
        v = [t[k] for t in group]
        lo, hi = boot_ci(v, rng)
        out.update({f'{k}_mean': statistics.fmean(v), f'{k}_median': statistics.median(v),
                    f'{k}_sd': statistics.stdev(v) if len(v) > 1 else None,
                    f'{k}_ci_low': lo, f'{k}_ci_high': hi,
                    f'{k}_mean_0_5': statistics.fmean(v) / 20,
                    f'{k}_z_mean': statistics.fmean(t[f'{k}_z'] for t in group)})
    return out


def rho(x: list[float], y: list[float]) -> float | None:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return None
    return float(stats.spearmanr(x, y).statistic)


def cell_table(rows: list[dict], manifest: dict, rng: np.random.Generator) -> list[dict]:
    out = []
    for s in sorted(st.by_kind(manifest, 'main'), key=lambda s: s['rung']):
        group = [t for t in rows if t['stimulus_id'] == s['stimulus_id']]
        if group:
            out.append({'rung': s['rung'], 'cell': s['cell'], 'genre': s['genre'], 'tier': s['tier'],
                        'bpm': s['bpm'], 'stimulus_id': s['stimulus_id'], **describe(group, rng)})
    last = len(out) - 1
    for k in SCALES:                       # rank of each cell by mean (0 = lowest) and the rank the ladder predicts
        for i, c in enumerate(sorted(out, key=lambda c: c[f'{k}_mean'])):
            c[f'{k}_rank'] = i
        for i, c in enumerate(out):
            c[f'{k}_expected_rank'] = i if EXPECTED[k] > 0 else last - i
    return out


def genre_table(rows: list[dict], rng: np.random.Generator) -> list[dict]:
    out = []
    for g in GENRE_ORDER:
        group = [t for t in rows if t['genre'] == g]
        if group:
            out.append({'genre': g, 'n_cells': len({t['cell'] for t in group}), **describe(group, rng)})
    return out


def participant_table(people: list[dict], rows: list[dict], include_preview: bool, source: dict) -> list[dict]:
    out = []
    for p in people:
        ts = [t for t in rows if t['response_id'] == p['response_id']]
        reasons = exclusion_reasons(p, include_preview)
        row = {'response_id': p['response_id'], 'source_file': source.get(p['response_id'], ''),
               'status': p['status'], 'included': not reasons, 'exclusion_reasons': '; '.join(reasons),
               'n_rated': p['n_rated'], 'duration_min': round(p['duration_s'] / 60, 1) if p['duration_s'] else None,
               'post_headphones': p.get('post_headphones', ''), 'post_volume': p.get('post_volume', ''),
               'post_quiet': p.get('post_quiet', ''), 'attention_value': p['attention_value'],
               'n_replays': p['n_replays'], 'same_genre_adjacent': p['same_genre_adjacent']}
        for k in SCALES:
            v = [t[k] for t in ts]
            row[f'{k}_mean'] = statistics.fmean(v) if v else None
            row[f'{k}_sd'] = statistics.pstdev(v) if len(v) > 1 else None
            row[f'{k}_rho_rung'] = rho([t['rung'] for t in ts], v)
            row[f'{k}_rho_position'] = rho([t['position'] for t in ts if t['position']],
                                            [t[k] for t in ts if t['position']])
        row['rho_dance_calming'] = rho([t['danceability'] for t in ts], [t['calming'] for t in ts])
        out.append(row)
    return out


def group_summary(cells: list[dict], parts: list[dict], rows: list[dict], rng: np.random.Generator) -> dict:
    inc = [p for p in parts if p['included']]
    rungs = [c['rung'] for c in cells]
    g: dict = {'n_participants': len(inc)}
    for k in SCALES:
        g[f'{k}_rho_cellmeans_rung'] = rho(rungs, [c[f'{k}_mean'] for c in cells])
        per = [p[f'{k}_rho_rung'] for p in inc if p[f'{k}_rho_rung'] is not None]
        g[f'{k}_rho_participant_mean'] = statistics.fmean(per) if per else None
        g[f'{k}_rho_participant_ci'] = boot_ci(per, rng)
        g[f'{k}_rho_participant_range'] = (min(per), max(per)) if per else None
        pos = [p[f'{k}_rho_position'] for p in inc if p[f'{k}_rho_position'] is not None]
        g[f'{k}_rho_position_mean'] = statistics.fmean(pos) if pos else None
        g[f'{k}_off_ladder'] = [c for c in cells if abs(c[f'{k}_rank'] - c[f'{k}_expected_rank']) >= RANK_SHIFT]
    g['rho_dance_calming_cellmeans'] = rho([c['danceability_mean'] for c in cells], [c['calming_mean'] for c in cells])
    g['high_both'] = [c for c in cells if c['danceability_z_mean'] > BOTH_Z and c['calming_z_mean'] > BOTH_Z]
    g['low_both'] = [c for c in cells if c['danceability_z_mean'] < -BOTH_Z and c['calming_z_mean'] < -BOTH_Z]
    vecs = {k: _vectors(inc, cells, rows, k) for k in SCALES}
    if all(len(v) >= 2 for v in vecs.values()):   # agreement: mean pairwise rho over the clips
        g['agreement'] = {k: statistics.fmean(r for i, a in enumerate(v) for b in v[i + 1:]
                                              if (r := rho(a, b)) is not None) for k, v in vecs.items()}
    return g


def _vectors(inc: list[dict], cells: list[dict], rows: list[dict], key: str) -> list[list[float]]:
    """Each included participant's ratings in cell (rung) order (complete participants only)."""
    out = []
    for p in inc:
        by = {t['stimulus_id']: t[key] for t in rows if t['response_id'] == p['response_id']}
        if all(c['stimulus_id'] in by for c in cells):
            out.append([by[c['stimulus_id']] for c in cells])
    return out


# =============================================================================
# Figures
# =============================================================================

def _style(ax) -> None:
    ax.spines[['top', 'right']].set_visible(False)
    for side in ('left', 'bottom'):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.grid(axis='y', color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def plot_ladder(cells: list[dict], rows: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(11, 8.2), sharex=True)
    titles = {'danceability': 'How much does this music make you want to move or dance?',
              'calming': 'How calming or relaxing does this music feel?'}
    for ax, k in zip(axes, SCALES):
        _style(ax)
        for t in rows:                                          # individual ratings, recessive
            ax.plot(t['rung'], t[k], 'o', ms=3, color='#9aa5b1', alpha=0.45, zorder=1)
        for c in cells:
            if c[f'{k}_ci_low'] is not None:
                ax.plot([c['rung']] * 2, [c[f'{k}_ci_low'], c[f'{k}_ci_high']], color=INK2, lw=1.2, zorder=2)
            ax.plot(c['rung'], c[f'{k}_mean'], GENRE_MARKER[c['genre']], ms=8, color=GENRE_COLOR[c['genre']],
                    markeredgecolor='white', markeredgewidth=1.5, zorder=3)
        ax.set_ylim(-4, 104)
        ax.set_ylabel(f'{k} (0-100)', color=INK2, fontsize=9)
        ax.set_title(titles[k], loc='left', color=INK, fontsize=10)
    axes[-1].set_xticks([c['rung'] for c in cells], [c['cell'] for c in cells], rotation=60, ha='right')
    axes[-1].set_xlabel('ladder rung (low to high designed energy)', color=INK2, fontsize=9)
    handles = [plt.Line2D([], [], ls='', marker=GENRE_MARKER[g], ms=7, color=GENRE_COLOR[g], label=g)
               for g in GENRE_ORDER if any(c['genre'] == g for c in cells)]
    handles.append(plt.Line2D([], [], ls='', marker='o', ms=4, color='#9aa5b1', label='single rating'))
    fig.legend(handles=handles, loc='upper center', ncol=len(handles), frameon=False, fontsize=8,
               bbox_to_anchor=(0.5, 1.0))
    n = len({t['response_id'] for t in rows})
    fig.text(0.01, 0.005, f'Cell means (marker) of {n} participant(s); bars are 95% bootstrap CIs '
             f'(shown when n >= {MIN_N_INFERENCE}).', color=INK2, fontsize=8)
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor='white')
    plt.close(fig)


LABEL_SPOTS = ((7, 4, 'left', 'bottom'), (7, -4, 'left', 'top'), (-7, 4, 'right', 'bottom'), (-7, -4, 'right', 'top'),
               (0, 8, 'center', 'bottom'), (0, -8, 'center', 'top'), (9, 0, 'left', 'center'), (-9, 0, 'right', 'center'))


def label_points(ax, cells: list[dict]) -> None:
    """Label each point in the spot (offset in points) that overlaps the fewest
    other points and labels placed so far."""
    from matplotlib.transforms import Bbox

    renderer = ax.figure.canvas.get_renderer()
    xy = [ax.transData.transform((c['danceability_mean'], c['calming_mean'])) for c in cells]
    r = 8 * ax.figure.dpi / 72                  # marker half-width in pixels, with some margin
    taken = [Bbox.from_extents(x - r, y - r, x + r, y + r) for x, y in xy]
    for i, c in enumerate(cells):
        best, best_hits = None, None
        for dx, dy, ha, va in LABEL_SPOTS:
            t = ax.annotate(c['cell'], (c['danceability_mean'], c['calming_mean']), xytext=(dx, dy),
                            textcoords='offset points', ha=ha, va=va, fontsize=7, color=INK2)
            box = t.get_window_extent(renderer)
            hits = sum(box.overlaps(b) for j, b in enumerate(taken) if j != i)
            if best_hits is None or hits < best_hits:
                if best is not None:
                    best[0].remove()
                best, best_hits = (t, box), hits
            else:
                t.remove()
        taken.append(best[1])


def plot_dance_calm(cells: list[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7.5, 7))
    _style(ax)
    ax.grid(axis='x', color=GRID, linewidth=0.8)
    for c in cells:
        ax.plot(c['danceability_mean'], c['calming_mean'], GENRE_MARKER[c['genre']], ms=8,
                color=GENRE_COLOR[c['genre']], markeredgecolor='white', markeredgewidth=1.5)
    ax.set_xlim(-4, 104)
    ax.set_ylim(-4, 104)
    ax.set_xlabel('danceability, cell mean (0-100)', color=INK2, fontsize=9)
    ax.set_ylabel('calming, cell mean (0-100)', color=INK2, fontsize=9)
    ax.set_title('Danceability against calming, per clip', loc='left', color=INK, fontsize=10)
    handles = [plt.Line2D([], [], ls='', marker=GENRE_MARKER[g], ms=7, color=GENRE_COLOR[g], label=g)
               for g in GENRE_ORDER if any(c['genre'] == g for c in cells)]
    ax.legend(handles=handles, frameon=False, fontsize=8, loc='upper right')
    fig.tight_layout()
    label_points(ax, cells)
    fig.savefig(path, dpi=150, facecolor='white')
    plt.close(fig)


# =============================================================================
# Output
# =============================================================================

def _fmt(v, nd=1):
    if v is None:
        return '-'
    if isinstance(v, float):
        return f'{v:.{nd}f}'
    return str(v)


def write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(dict.fromkeys(k for r in rows for k in r)) if rows else ['empty']
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()})


def report(files, parts, cells, genres, g, problems, args, sha) -> str:
    inc = [p for p in parts if p['included']]
    small = len(inc) < MIN_N_INFERENCE
    L = ['# Experiment 1 (remote): rating analysis', '',
         f'Generated {datetime.now():%Y-%m-%d %H:%M}. Stimulus manifest `{sha[:12]}`. '
         f'Exports: {", ".join(f.name for f in files)}.', '',
         'The ratings describe each clip as rendered by the locked system, loudness included; they are not '
         'measurements of composition independent of loudness.', '']
    if small:
        L += [f'**Only {len(inc)} participant(s) included.** Everything below is descriptive; confidence intervals '
              f'are shown only from {MIN_N_INFERENCE} participants.', '']
    L += ['## Participants', '', '| response | status | included | reasons | minutes | headphones | volume changed | '
          'dance rho rung | calm rho rung |', '|---|---|---|---|---|---|---|---|---|']
    for p in parts:
        L.append(f"| {p['response_id']} | {p['status']} | {'yes' if p['included'] else 'no'} | "
                 f"{p['exclusion_reasons'] or '-'} | {_fmt(p['duration_min'])} | {p['post_headphones'] or '-'} | "
                 f"{p['post_volume'] or '-'} | {_fmt(p['danceability_rho_rung'], 2)} | {_fmt(p['calming_rho_rung'], 2)} |")
    if args.include_preview:
        L += ['', '_Preview responses were included (`--include-preview`)._']
    if args.all:
        L += ['', '_All responses were included regardless of quality flags (`--all`)._']
    if problems:
        L += ['', f'**Data-integrity problems ({len(problems)}):**', *[f'- {x}' for x in problems]]
    if not inc:
        return '\n'.join(L + ['', 'No participant met the inclusion rules; nothing to analyze.']) + '\n'

    L += ['', '## Does perceived energy follow the ladder?', '',
          'Spearman rho between ladder rung (0 = lowest designed energy) and the rating. Positive for danceability '
          'and negative for calming means the ratings follow the ladder.', '',
          '| | danceability | calming |', '|---|---|---|',
          f"| cell means vs rung | {_fmt(g['danceability_rho_cellmeans_rung'], 2)} | "
          f"{_fmt(g['calming_rho_cellmeans_rung'], 2)} |",
          f"| per participant, mean | {_fmt(g['danceability_rho_participant_mean'], 2)} | "
          f"{_fmt(g['calming_rho_participant_mean'], 2)} |"]
    if not small:
        ci = {k: g[f'{k}_rho_participant_ci'] for k in SCALES}
        L.append(f"| per participant, 95% CI | {_fmt(ci['danceability'][0], 2)} to {_fmt(ci['danceability'][1], 2)} | "
                 f"{_fmt(ci['calming'][0], 2)} to {_fmt(ci['calming'][1], 2)} |")
    rng_d, rng_c = g['danceability_rho_participant_range'], g['calming_rho_participant_range']
    if rng_d and len(inc) > 1:
        L.append(f'| per participant, range | {rng_d[0]:.2f} to {rng_d[1]:.2f} | {rng_c[0]:.2f} to {rng_c[1]:.2f} |')
    L += ['', f"Danceability and calming across clips (cell means): rho = {_fmt(g['rho_dance_calming_cellmeans'], 2)}.",
          f"Order effect (rating vs presentation position, mean per participant): danceability "
          f"{_fmt(g['danceability_rho_position_mean'], 2)}, calming {_fmt(g['calming_rho_position_mean'], 2)}."]
    if 'agreement' in g:
        L.append(f"Agreement between participants (mean pairwise rho over the 27 clips): danceability "
                 f"{_fmt(g['agreement']['danceability'], 2)}, calming {_fmt(g['agreement']['calming'], 2)}.")
    L += ['', '## Clips that depart from the pattern', '',
          f'A clip is listed when its rank by mean rating is at least {RANK_SHIFT} places from the rank its ladder rung '
          'predicts (danceability: rung order; calming: reversed rung order). Ranks count from 1 = lowest rating.', '']
    for k in SCALES:
        off = sorted(g[f'{k}_off_ladder'], key=lambda c: -abs(c[f'{k}_rank'] - c[f'{k}_expected_rank']))
        L.append(f'- **{k}**: ' + (', '.join(
            f"{c['cell']} (expected rank {c[f'{k}_expected_rank'] + 1}, rated rank {c[f'{k}_rank'] + 1})"
            for c in off) or 'none'))
    L.append(f'- **high on both** (z > {BOTH_Z}): ' + (', '.join(c['cell'] for c in g['high_both']) or 'none'))
    L.append(f'- **low on both** (z < -{BOTH_Z}): ' + (', '.join(c['cell'] for c in g['low_both']) or 'none'))
    L += ['', 'With few participants a clip can move many places on one rating.', '',
          '## Per clip (ladder order)', '',
          '| rung | clip | n | dance mean | dance 0-5 | calm mean | calm 0-5 | dance z | calm z |',
          '|---|---|---|---|---|---|---|---|---|']
    for c in cells:
        L.append(f"| {c['rung'] + 1} | {c['cell']} | {c['n']} | {_fmt(c['danceability_mean'])} | "
                 f"{_fmt(c['danceability_mean_0_5'], 2)} | {_fmt(c['calming_mean'])} | {_fmt(c['calming_mean_0_5'], 2)} | "
                 f"{_fmt(c['danceability_z_mean'], 2)} | {_fmt(c['calming_z_mean'], 2)} |")
    L += ['', '## Per genre', '', '| genre | clips | ratings | dance mean | calm mean |', '|---|---|---|---|---|']
    for r in genres:
        L.append(f"| {r['genre']} | {r['n_cells']} | {r['n']} | {_fmt(r['danceability_mean'])} | "
                 f"{_fmt(r['calming_mean'])} |")
    L += ['', '## Figures', '', '![ratings along the ladder](ladder_ratings.png)', '',
          '![danceability against calming](dance_vs_calm.png)', '',
          'z = within-participant z-score (removes differences in how people use the slider). '
          'Full numbers: `cells.csv`, `genres.csv`, `participants.csv`.']
    return '\n'.join(L) + '\n'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('inputs', nargs='*', type=Path, default=[DEFAULT_INPUT], help='CSV exports or folders')
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--include-preview', action='store_true', help='keep Qualtrics preview responses')
    ap.add_argument('--all', action='store_true', help='keep every response, ignoring quality flags')
    ap.add_argument('--loop-prefix', choices=('row', 'position'), default='row')
    ap.add_argument('--stim-dir', type=Path, default=st.STIM_DIR)
    ap.add_argument('--hp-dir', type=Path, default=hc.OUT_DIR)
    args = ap.parse_args(argv)

    manifest, sha = st.load_manifest(args.stim_dir)
    hpm = hc.load_manifest(args.hp_dir)
    files = export_files(args.inputs)
    rows, people, problems, source = load(files, manifest, hpm, args.loop_prefix)
    parts = participant_table(people, rows, args.include_preview, source)
    if args.all:
        for p in parts:
            p['included'] = True
    keep = {p['response_id'] for p in parts if p['included']}
    included = [t for t in rows if t['response_id'] in keep and t['danceability'] is not None
                and t['calming'] is not None]
    add_z(included)
    rng = np.random.default_rng(SEED)
    cells = cell_table(included, manifest, rng) if included else []
    genres = genre_table(included, rng) if included else []
    g = group_summary(cells, parts, included, rng) if included else {}

    out = args.out or OUT_ROOT / f'analysis_{datetime.now():%Y%m%d_%H%M%S}'
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f'{out} already exists and is not empty')
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / 'participants.csv', parts)
    write_csv(out / 'ratings_included.csv', included)
    if included:
        write_csv(out / 'cells.csv', cells)
        write_csv(out / 'genres.csv', genres)
        plot_ladder(cells, included, out / 'ladder_ratings.png')
        plot_dance_calm(cells, out / 'dance_vs_calm.png')
    (out / 'report.md').write_text(report(files, parts, cells, genres, g, problems, args, sha), encoding='utf-8')
    print(f'{len(parts)} response(s), {len(keep)} included; wrote {out}')
    for p in parts:
        if not p['included']:
            print(f"  excluded {p['response_id']}: {p['exclusion_reasons']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
