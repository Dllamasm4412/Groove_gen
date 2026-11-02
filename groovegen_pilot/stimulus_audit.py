"""
Stimulus audit: repetition and controlled-feature baseline for a segment
generator (LIVE_GENERATION_PLAN.md section 7). Measures only; changes nothing.

Generates segments exactly as run_session_v2 does, along rung trajectories,
and records per segment the repetition metrics (R1-R7) and the locked /
bounded features of stimulus_metrics.py. Cross-segment metrics compare each
segment with the previous visit to the same cell (R3-R5) or the previous
segment of the same genre (R7) within its trajectory.

Generators
----------
    bank   v1 live behaviour: MelodyBank(variants_per_cell=4, base_seed=0)
           rotation per cell, SymbolicSegmentRenderer(session_seed=42) seed
           derivation, tier_tempo / tempo_default, RUNG_TIER_CAP density.
    session  v2 controlled variation (composer/arrangement.py SessionComposer,
           --stim-seed): the k-th visit to a cell in a trajectory is visit_idx k.
           Not the live path, so the trace-seed and render-path fidelity
           checks (which replay run_session_v2) are skipped for it.

Trajectories (each starts with a fresh generator, like a new session)
------------
    bank   every live cell visited --visits times in a row (one trajectory
           per cell): multiple visits per cell under bank rotation
    dwell  --dwell-segments consecutive segments on --dwell-cell
    sweep  up and down the live ladder --sweep-cycles times, 1 rung per segment
    trace  the segment sequence of a session_trace.csv (--trace-csv, repeatable);
           the logged seeds are checked against the regenerated ones

Usage (writes only to a disposable directory; never touches renders/frozen_v2):
    python stimulus_audit.py
    python stimulus_audit.py --modes bank,dwell,sweep,trace \
        --trace-csv renders/pilot_zero/daniel_L2_20260928_122951/session_trace.csv
    python stimulus_audit.py --render --sf2 Musyng_Kite.sf2      # adds render_ms
    python stimulus_audit.py --generator session --stim-seed 1 \
        --reference-summary renders/smoke_audit/baseline_v1_20260929/audit_summary.json
Outputs: <out>/audit.csv (one row per segment) and <out>/audit_summary.json.
"""

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import numpy as np

import stimulus_metrics as sm

HERE = Path(__file__).resolve().parent
BARS = 8
FADE_BARS = 0.25
SAMPLE_RATE = 44100


# =============================================================================
# Generators
# =============================================================================


class BankGenerator:
    """v1 live generation, reproduced call for call from run_session_v2.

    run_session_v2: seed = melody_bank.seed_for(genre, tier), then
    renderer.render_segment(..., segment_idx=seed), which derives the composer
    seed with SymbolicSegmentRenderer._derive_seed and clamps the tier with
    RUNG_TIER_CAP before the TIER_TO_DENSITY lookup.
    """

    name = 'bank'
    live_path = True

    def __init__(self, session_seed: int = 42, variants_per_cell: int = 4, base_seed: int = 0):
        from melody_bank import MelodyBank

        self.session_seed = session_seed
        self.bank = MelodyBank(variants_per_cell=variants_per_cell, base_seed=base_seed)
        self.config = {'session_seed': session_seed, 'variants_per_cell': variants_per_cell,
                       'base_seed': base_seed}

    def plan(self, genre: str, tier: int) -> dict:
        from composer import GENRE_CFG
        from segment_renderer import RUNG_TIER_CAP, TIER_TO_DENSITY, SymbolicSegmentRenderer

        cfg = GENRE_CFG[genre]
        tempo = float(cfg.get('tier_tempo', {}).get(tier, cfg['tempo_default']))
        tier_c = max(1, min(int(tier), RUNG_TIER_CAP.get(genre, 5)))
        bank_seed = self.bank.seed_for(genre, tier)
        # The renderer's own derivation, without constructing a renderer
        # (which needs fluidsynth and a soundfont)
        composer_seed = SymbolicSegmentRenderer._derive_seed(self, bank_seed)
        return {'planned_tempo_bpm': tempo, 'density': TIER_TO_DENSITY[tier_c],
                'seed': bank_seed, 'composer_seed': composer_seed}

    def generate(self, genre: str, tier: int):
        from composer import generate_segment

        p = self.plan(genre, tier)
        pm = generate_segment(genre, tempo_bpm=p['planned_tempo_bpm'], density=p['density'],
                              duration_bars=BARS, seed=p['composer_seed'])
        return pm, p


class SessionGenerator:
    """v2 generator (Phase 2a): SessionComposer with a per-cell visit counter."""

    name = 'session'
    live_path = False
    INFO_KEYS = ('base_seed', 'var_seed', 'block_idx', 'session_key', 'form_template',
                 'gen_attempts', 'gen_fallback', 'bar_roles', 'drum_ops')

    def __init__(self, stim_seed: int = 1, develop: bool = False):
        from composer.arrangement import GEN_VERSION, SessionComposer

        self.composer = SessionComposer(stim_seed, develop=develop)
        self.visits: dict[tuple, int] = {}
        self.config = {'stim_seed': stim_seed, 'gen_version': GEN_VERSION}
        if develop:   # v2b motif development (composer/motif.py); absent = v2a.3
            from composer.motif import DEV_VERSION
            self.config.update(develop=True, dev_version=DEV_VERSION)

    def generate(self, genre: str, tier: int):
        cell = (genre, int(tier))
        visit = self.visits.get(cell, 0)
        self.visits[cell] = visit + 1
        pm, info = self.composer.compose(genre, tier, visit)
        plan = {'planned_tempo_bpm': info['tempo_bpm'], 'density': info['density'],
                'seed': None, 'composer_seed': info['base_seed']}
        plan.update({k: info[k] for k in self.INFO_KEYS})
        return pm, plan


GENERATORS = {'bank': BankGenerator, 'session': SessionGenerator}


# =============================================================================
# Trajectories
# =============================================================================


def live_ladder(source: str):
    """The live runner's tier-capped ladder (run_pilot_zero.main)."""
    from ladder import build_ladder, load_energy_table
    from run_pilot_zero import ENERGY_TABLE, LIVE_EXCLUDE_GENRES, LIVE_TIER_CAP_OVERRIDES
    from segment_renderer import RUNG_TIER_CAP

    caps = {**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES}
    if source == 'measured':
        features, weights, tie_band, sha = load_energy_table(ENERGY_TABLE)
        ladder = build_ladder(tier_caps=caps, exclude_genres=LIVE_EXCLUDE_GENRES,
                              features=features, weights=weights, tie_band=tie_band)
        return ladder, {'source': 'measured', 'energy_table': str(ENERGY_TABLE), 'sha256': sha}
    ladder = build_ladder(tier_caps=caps, exclude_genres=LIVE_EXCLUDE_GENRES)
    return ladder, {'source': 'prior'}


def read_trace_segments(path: Path) -> list[dict]:
    """First row of each segment in a session_trace.csv: genre, tier, logged seed."""
    seen: dict[int, dict] = {}
    with path.open(newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            idx = int(row['segment_idx'])
            if idx not in seen:
                seen[idx] = {'genre': row['genre'], 'tier': int(row['tier']),
                             'logged_seed': int(row['seed']) if row.get('seed') else None}
    return [seen[i] for i in sorted(seen)]


def build_trajectories(args, ladder) -> list[tuple[str, list[dict]]]:
    cells = [(c.genre, c.tier) for c in ladder.cells]
    out: list[tuple[str, list[dict]]] = []
    for mode in args.modes:
        if mode == 'bank':
            for g, t in cells:
                out.append((f'bank:{g}{t}', [{'genre': g, 'tier': t}] * args.visits))
        elif mode == 'dwell':
            g, t = args.dwell_cell.split(':')
            if (g, int(t)) not in cells:
                raise SystemExit(f'--dwell-cell {args.dwell_cell} is not on the live ladder')
            out.append((f'dwell:{g}{t}', [{'genre': g, 'tier': int(t)}] * args.dwell_segments))
        elif mode == 'sweep':
            up = list(range(len(cells)))
            path = []
            for _ in range(args.sweep_cycles):
                path += up + up[-2:0:-1]
            path.append(0)
            out.append(('sweep', [{'genre': cells[r][0], 'tier': cells[r][1]} for r in path]))
        elif mode == 'trace':
            for p in args.trace_csv:
                p = Path(p)
                out.append((f'trace:{p.parent.name}', read_trace_segments(p)))
        else:
            raise SystemExit(f'unknown mode {mode!r}')
    return out


# =============================================================================
# Audit
# =============================================================================

ROW_FIELDS = (
    ['trajectory', 'seg_pos', 'genre', 'tier', 'cell', 'visit_idx', 'planned_tempo_bpm',
     'density', 'seed', 'composer_seed', 'logged_seed', 'gen_ms', 'render_ms']
    + ['midi_sha256', 'content_sha', 'drum_sha', 'pitched_sha']
    + ['tempo_matches_plan'] + list(sm.LOCKED_FEATURES)
    + list(sm.BOUNDED_SET_FEATURES) + list(sm.BOUNDED_FEATURES)
    + ['distinct_bars_all', 'distinct_drum_bars', 'distinct_pitched_bars',
       'max_identical_drum_run', 'max_identical_all_run',
       'phrase_end_bar4_marked', 'phrase_end_bar8_marked', 'phrase_contrast',
       'drum_period',
       'key_pc', 'key_name', 'key_fit', 'motif_track']
    + ['repeat_dist_segments', 'repeat_dist_visits', 'drum_repeat_dist_visits',
       'pitched_repeat_dist_visits', 'near_repeat_drum', 'near_repeat_pitched',
       'near_repeat_all', 'motif_distance', 'prev_same_genre_key', 'key_changed']
    + list(SessionGenerator.INFO_KEYS)       # empty for the bank generator
)


def _last_index(history: list[str], value: str) -> Optional[int]:
    for i in range(len(history) - 1, -1, -1):
        if history[i] == value:
            return i
    return None


def audit_trajectory(name: str, segments: list[dict], gen_cls, renderer=None,
                     fidelity: Optional[dict] = None) -> list[dict]:
    gen = gen_cls()
    rows: list[dict] = []
    all_hist: list[str] = []                         # content sha per segment
    cell_hist: dict[tuple, list[dict]] = {}          # previous metrics per cell
    genre_last: dict[str, dict] = {}                 # last segment metrics per genre

    for pos, seg in enumerate(segments):
        genre, tier = seg['genre'], int(seg['tier'])
        cell = (genre, tier)
        t0 = time.perf_counter()
        pm, plan = gen.generate(genre, tier)
        gen_ms = (time.perf_counter() - t0) * 1e3
        m = sm.segment_metrics(pm, BARS)

        render_ms = None
        if renderer is not None:
            t0 = time.perf_counter()
            audio = renderer._render_pm_to_audio(pm)
            render_ms = (time.perf_counter() - t0) * 1e3
            # Live-path fidelity, once per cell: the renderer's own entry point
            # (as run_session_v2 calls it) must give the same audio
            if gen.live_path and fidelity is not None and cell not in fidelity['render_checked']:
                live = renderer.render_segment(genre=genre, tempo_bpm=plan['planned_tempo_bpm'],
                                               tier=tier, n_bars=BARS, segment_idx=plan['seed'])
                fidelity['render_checked'].add(cell)
                if not np.array_equal(live, audio):
                    fidelity['render_mismatch'].append(f'{genre}{tier}')

        prev_visits = cell_hist.setdefault(cell, [])
        visit_idx = len(prev_visits)
        row: dict[str, Any] = {
            'trajectory': name, 'seg_pos': pos, 'genre': genre, 'tier': tier,
            'cell': f'{genre}:{tier}', 'visit_idx': visit_idx,
            **plan, 'logged_seed': seg.get('logged_seed'),
            'gen_ms': round(gen_ms, 2), 'render_ms': None if render_ms is None else round(render_ms, 1),
        }
        row.update({k: v for k, v in m.items() if not k.startswith('_')})
        row['tempo_matches_plan'] = abs(m['played_tempo_bpm'] - plan['planned_tempo_bpm']) < 1e-3

        # R3: exact repeat distance (whole trajectory, and in visits to this cell)
        j = _last_index(all_hist, m['content_sha'])
        row['repeat_dist_segments'] = None if j is None else pos - j
        for key, col in (('content_sha', 'repeat_dist_visits'), ('drum_sha', 'drum_repeat_dist_visits'),
                         ('pitched_sha', 'pitched_repeat_dist_visits')):
            k = _last_index([p[key] for p in prev_visits], m[key])
            row[col] = None if k is None else visit_idx - k

        # R4 / R5 vs the previous visit to this cell
        if prev_visits:
            p = prev_visits[-1]
            row['near_repeat_drum'] = sm.near_repeat_similarity(p['_drum_sets'], m['_drum_sets'])
            row['near_repeat_pitched'] = sm.near_repeat_similarity(p['_pitched_sets'], m['_pitched_sets'])
            row['near_repeat_all'] = sm.near_repeat_similarity(p['_all_sets'], m['_all_sets'])
            row['motif_distance'] = sm.edit_distance_norm(p['_motif'], m['_motif'])
        # R7 vs the previous segment of this genre
        g_prev = genre_last.get(genre)
        if g_prev is not None:
            row['prev_same_genre_key'] = g_prev['key_name']
            row['key_changed'] = g_prev['key_pc'] != m['key_pc']

        all_hist.append(m['content_sha'])
        prev_visits.append(m)
        genre_last[genre] = m
        if gen.live_path and fidelity is not None and seg.get('logged_seed') is not None:
            fidelity['trace_seed_checked'] += 1
            if seg['logged_seed'] != plan['seed']:
                fidelity['trace_seed_mismatch'].append(f'{name}#{pos}')
        rows.append(row)
    return rows


# =============================================================================
# Summary
# =============================================================================


def _num(vals) -> list[float]:
    out = []
    for v in vals:
        if v is None or isinstance(v, str):
            continue
        f = float(v)
        if not math.isnan(f):
            out.append(f)
    return out


def _stats(vals) -> Optional[dict]:
    v = _num(vals)
    if not v:
        return None
    return {'n': len(v), 'mean': round(float(np.mean(v)), 4), 'sd': round(float(np.std(v)), 4),
            'min': round(min(v), 4), 'max': round(max(v), 4)}


def _rate(vals) -> Optional[float]:
    v = [bool(x) for x in vals if x is not None]
    return round(sum(v) / len(v), 4) if v else None


def repetition_block(rows: list[dict]) -> dict:
    return {
        'distinct_drum_bars': _stats(r['distinct_drum_bars'] for r in rows),
        'distinct_pitched_bars': _stats(r['distinct_pitched_bars'] for r in rows),
        'distinct_bars_all': _stats(r['distinct_bars_all'] for r in rows),
        'max_identical_drum_run': _stats(r['max_identical_drum_run'] for r in rows),
        'phrase_end_bar4_rate': _rate(r['phrase_end_bar4_marked'] for r in rows),
        'phrase_end_bar8_rate': _rate(r['phrase_end_bar8_marked'] for r in rows),
        'phrase_contrast_rate': _rate(r['phrase_contrast'] for r in rows),
        'drum_period': _stats(r['drum_period'] for r in rows),
        'exact_repeat_rate': _rate(r['repeat_dist_visits'] is not None for r in rows if r['visit_idx'] > 0),
        'min_repeat_dist_visits': min(_num(r['repeat_dist_visits'] for r in rows), default=None),
        'min_drum_repeat_dist_visits': min(_num(r['drum_repeat_dist_visits'] for r in rows), default=None),
        'min_repeat_dist_segments': min(_num(r['repeat_dist_segments'] for r in rows), default=None),
        'near_repeat_drum': _stats(r.get('near_repeat_drum') for r in rows),
        'near_repeat_pitched': _stats(r.get('near_repeat_pitched') for r in rows),
        'near_repeat_all': _stats(r.get('near_repeat_all') for r in rows),
        'motif_distance': _stats(r.get('motif_distance') for r in rows),
        'motif_exact_reuse_rate': _rate(r['motif_distance'] == 0 for r in rows
                                        if r.get('motif_distance') is not None),
        'key_change_rate': _rate(r.get('key_changed') for r in rows),
    }


def reference_sets(path: str) -> dict[str, dict[str, list]]:
    """Per-cell allowed sets (BOUNDED_SET_FEATURES) from an earlier audit_summary.json."""
    ref = json.loads(Path(path).read_text(encoding='utf-8'))
    return {cell: {f: v['union'] for f, v in c.get('bounded_set', {}).items()}
            for cell, c in ref['cells'].items()}


def summarize(rows: list[dict], reference: Optional[dict] = None) -> dict:
    cells: dict[str, dict] = {}
    for cell in dict.fromkeys(r['cell'] for r in rows):
        cr = [r for r in rows if r['cell'] == cell]
        # Locked / bounded features over unique segments (a repeated segment
        # would otherwise be counted once per visit)
        uniq = list({r['midi_sha256']: r for r in cr}.values())
        locked = {}
        for f in sm.LOCKED_FEATURES:
            vals = sorted({json.dumps(r[f]) for r in uniq})
            locked[f] = {'n_distinct': len(vals), 'values': [json.loads(v) for v in vals]}
        locked['tempo_matches_plan'] = all(r['tempo_matches_plan'] for r in cr)
        bounded_set = {}
        for f in sm.BOUNDED_SET_FEATURES:
            vals = sorted({json.dumps(r[f]) for r in uniq})
            union = sorted({v for r in uniq for v in r[f]})
            bounded_set[f] = {'union': union, 'n_distinct': len(vals),
                              'values': [json.loads(v) for v in vals]}
            allowed = (reference or {}).get(cell, {}).get(f)
            if allowed is not None:
                bounded_set[f]['reference'] = allowed
                bounded_set[f]['within_reference'] = all(sm.set_within(r[f], allowed) for r in cr)
                bounded_set[f]['outside_reference'] = sorted(set(union) - set(allowed))
        cells[cell] = {
            'n_segments': len(cr), 'n_unique_segments': len(uniq),
            'locked': locked,
            'locked_stable': all(v['n_distinct'] == 1 for k, v in locked.items() if isinstance(v, dict))
                             and locked['tempo_matches_plan'],
            'bounded_set': bounded_set,
            'bounded': {f: _stats(r[f] for r in uniq) for f in sm.BOUNDED_FEATURES},
            'repetition': repetition_block(cr),
            'gen_ms': _stats(r['gen_ms'] for r in cr),
            'gen_fallback_rate': _rate(r.get('gen_fallback') for r in cr),
            'render_ms': _stats(r['render_ms'] for r in cr),
        }
    trajectories = {}
    for name in dict.fromkeys(r['trajectory'] for r in rows):
        tr = [r for r in rows if r['trajectory'] == name]
        trajectories[name] = {'n_segments': len(tr), 'n_cells': len({r['cell'] for r in tr}),
                              'repetition': repetition_block(tr)}
    genres: dict[str, dict] = {}
    for g in dict.fromkeys(r['genre'] for r in rows):
        gr = [r for r in rows if r['genre'] == g]
        genres[g] = {'keys_seen': sorted({r['key_name'] for r in gr if r['key_name']}),
                     'key_change_rate': _rate(r.get('key_changed') for r in gr),
                     'distinct_drum_bars': _stats(r['distinct_drum_bars'] for r in gr)}
    return {'cells': cells, 'trajectories': trajectories, 'genres': genres}


def code_provenance() -> dict:
    def git(*a):
        try:
            return subprocess.run(['git', *a], cwd=HERE, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except Exception:
            return None
    files = {}
    for f in ('composer.py', 'melody_bank.py', 'segment_renderer.py', 'stimulus_metrics.py',
              'stimulus_audit.py', 'composer/hiphop_cell.py', 'composer/rock_cell.py',
              'composer/arrangement.py', 'composer/variation.py', 'composer/energy_guard.py'):
        p = HERE / f
        files[f] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else None
    status = git('status', '--porcelain', '--', '.')
    return {'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(status) if status is not None else None, 'file_sha256_16': files}


def _csv_value(v):
    if isinstance(v, (list, tuple, dict)):
        return json.dumps(v)
    if isinstance(v, float):
        return '' if math.isnan(v) else round(v, 6)
    return '' if v is None else v


# =============================================================================
# CLI
# =============================================================================


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--generator', choices=sorted(GENERATORS), default='bank')
    ap.add_argument('--stim-seed', type=int, default=1, help='session generator: stimulus seed')
    ap.add_argument('--modes', default='bank,dwell,sweep',
                    help='comma list of bank,dwell,sweep,trace (default bank,dwell,sweep)')
    ap.add_argument('--visits', type=int, default=8, help='bank mode: visits per cell')
    ap.add_argument('--dwell-cell', default='pop:3', help='dwell mode cell genre:tier')
    ap.add_argument('--dwell-segments', type=int, default=24)
    ap.add_argument('--sweep-cycles', type=int, default=2)
    ap.add_argument('--trace-csv', action='append', default=[], help='session_trace.csv (repeatable)')
    ap.add_argument('--ladder', choices=('measured', 'prior'), default='measured')
    ap.add_argument('--render', action='store_true', help='render via fluidsynth CLI for render_ms')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    ap.add_argument('--reference-summary', default=None,
                    help='earlier audit_summary.json whose per-cell sets bound this run '
                         '(e.g. the v1 bank audit when auditing v2)')
    ap.add_argument('--out', default=None, help='output dir (default renders/smoke_audit/<stamp>)')
    args = ap.parse_args(argv)
    args.modes = [m.strip() for m in args.modes.split(',') if m.strip()]
    if 'trace' in args.modes and not args.trace_csv:
        ap.error('--modes trace needs at least one --trace-csv')
    if args.trace_csv and 'trace' not in args.modes:
        args.modes.append('trace')
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else HERE / 'renders' / 'smoke_audit' / stamp
    if 'frozen_v2' in out.resolve().parts:
        raise SystemExit('refusing to write under frozen_v2')
    out.mkdir(parents=True, exist_ok=True)

    ladder, ladder_info = live_ladder(args.ladder)
    trajectories = build_trajectories(args, ladder)

    renderer = None
    if args.render:
        from segment_renderer import SymbolicSegmentRenderer
        renderer = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=SAMPLE_RATE, session_seed=42)
    fidelity = {'trace_seed_checked': 0, 'trace_seed_mismatch': [],
                'render_checked': set(), 'render_mismatch': []}

    gen_kwargs = {'stim_seed': args.stim_seed} if args.generator == 'session' else {}
    gen_cls = functools.partial(GENERATORS[args.generator], **gen_kwargs)
    t_start = time.perf_counter()
    rows: list[dict] = []
    for name, segs in trajectories:
        rows += audit_trajectory(name, segs, gen_cls, renderer, fidelity)
        print(f'  {name}: {len(segs)} segments', file=sys.stderr)
    elapsed = time.perf_counter() - t_start

    with (out / 'audit.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=ROW_FIELDS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: _csv_value(r.get(k)) for k in ROW_FIELDS})

    summary = {
        'meta': {
            'tool': 'stimulus_audit.py', 'timestamp': stamp, 'argv': sys.argv[1:],
            'generator': args.generator, 'generator_config': gen_cls().config,
            'modes': args.modes, 'bars_per_segment': BARS, 'grid_per_bar': sm.GRID_PER_BAR,
            'ladder': ladder_info, 'ladder_cells': [f'{c.genre}:{c.tier}' for c in ladder.cells],
            'n_segments': len(rows), 'elapsed_s': round(elapsed, 2),
            'python': platform.python_version(), 'code': code_provenance(),
            'soundfont': args.sf2 if args.render else None,
            'reference_summary': args.reference_summary,
        },
        'feature_classes': {'locked': sm.LOCKED_FEATURES, 'bounded': sm.BOUNDED_FEATURES,
                            'bounded_set': sm.BOUNDED_SET_FEATURES,
                            'free': sm.FREE_FEATURES, 'repetition_metrics': sm.REPETITION_METRICS},
        'fidelity': {
            'trace_seed_checked': fidelity['trace_seed_checked'],
            'trace_seed_mismatch': fidelity['trace_seed_mismatch'],
            'render_path_checked_cells': len(fidelity['render_checked']),
            'render_path_mismatch': fidelity['render_mismatch'],
        },
        **summarize(rows, reference_sets(args.reference_summary) if args.reference_summary else None),
    }
    (out / 'audit_summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f'wrote {out / "audit.csv"} ({len(rows)} rows)')
    print(f'wrote {out / "audit_summary.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
