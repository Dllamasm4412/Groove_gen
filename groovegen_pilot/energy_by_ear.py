"""
By-ear energy rating of the live ladder cells (developer listening). The
measured ladder put hiphop3 above pop5 (118 -> 90 bpm on an up-step) and, with
the Rock presentation gain counted as energy, rock1 next to pop; the first v2c
live run (2026-10-05) made both moves and the developer heard them as wrong.
With the developer's ratings, run_pilot_zero --ladder ear keeps the measured
u values but assigns them in by-ear order (ladder.build_ladder(ear_ratings=)).

render: one clip per live cell, as live v2c plays it (SessionComposer stim 1,
visits 0 and 1, live renderer incl. the Rock gain, joined with the live
crossfade); each adjacent step of the current measured ladder (visit 0 of the
lower cell, then of the upper); ratings.csv to fill in; LISTENING_NOTES.md.
apply: checks the filled ratings.csv and writes energy_order_by_ear.json,
printing the measured and by-ear ladders and any up-step that lowers tempo.

Usage (render writes only under renders/, gitignored):
    python energy_by_ear.py render --sf2 Musyng_Kite.sf2 --out renders/energy_by_ear/<ts>
    python energy_by_ear.py apply --ratings renders/energy_by_ear/<ts>/ratings.csv \
        [--out energy_order_by_ear.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STIM_SEED = 1
VISITS = (0, 1)
RATINGS_FIELDS = ('cell', 'rating', 'notes')


def live_ladder(ear_ratings=None):
    """The live ladder as run_pilot_zero builds it (measured, tier-capped)."""
    from ladder import build_ladder, load_energy_table
    from run_pilot_zero import ENERGY_TABLE, LIVE_EXCLUDE_GENRES, LIVE_TIER_CAP_OVERRIDES
    from segment_renderer import RUNG_TIER_CAP

    features, weights, tie_band, sha = load_energy_table(ENERGY_TABLE)
    ladder = build_ladder(tier_caps={**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES},
                          exclude_genres=LIVE_EXCLUDE_GENRES, features=features,
                          weights=weights, tie_band=tie_band, ear_ratings=ear_ratings)
    return ladder, features, sha


def cell_name(c) -> str:
    return f'{c.genre}{c.tier}'


def render(args) -> None:
    import numpy as np

    from audition_v2 import SAMPLE_RATE, join_like_live, trim_like_live
    from composer.arrangement import SessionComposer, cell_plan
    from segment_renderer import SymbolicSegmentRenderer, _write_wav

    out = Path(args.out)
    for d in ('cells', 'steps'):
        (out / d).mkdir(parents=True, exist_ok=True)
    ladder, features, sha = live_ladder()
    r = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=SAMPLE_RATE, session_seed=42)
    sc = SessionComposer(STIM_SEED, develop=True)
    audio: dict = {}
    for c in ladder.cells:
        tempo = cell_plan(c.genre, c.tier)[0]
        for v in VISITS:
            pm, _ = sc.compose(c.genre, c.tier, v)
            audio[(c.gt(), v)] = (trim_like_live(r._render_pm_to_audio(pm), tempo), tempo)
        joined, _, _ = join_like_live(*zip(*(audio[(c.gt(), v)] for v in VISITS)))
        _write_wav(out / 'cells' / f'{cell_name(c)}.wav', joined, SAMPLE_RATE)
    for a, b in zip(ladder.cells, ladder.cells[1:]):
        joined, _, _ = join_like_live(*zip(audio[(a.gt(), 0)], audio[(b.gt(), 0)]))
        _write_wav(out / 'steps' / f'{a.rung:02d}_{cell_name(a)}_to_{cell_name(b)}.wav', joined, SAMPLE_RATE)
    with (out / 'ratings.csv').open('w', newline='') as f:
        w = csv.writer(f)
        w.writerow(RATINGS_FIELDS)
        for c in sorted(ladder.cells, key=lambda c: (c.genre, c.tier)):
            w.writerow([f'{c.genre}:{c.tier}', '', ''])
    (out / 'LISTENING_NOTES.md').write_text(notes(ladder, features))
    (out / 'manifest.json').write_text(json.dumps({
        'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'sf2': str(args.sf2),
        'energy_table_sha256': sha, 'stim_seed': STIM_SEED, 'visits': list(VISITS),
        'generator': 'v2c (SessionComposer develop=True), live renderer, audition_v2.join_like_live',
        'measured_ladder': [f'{cell_name(c)}:{c.u:.4f}' for c in ladder.cells]}, indent=1))
    peak = max(float(np.max(np.abs(a))) for a, _ in audio.values())
    print(f'wrote {len(ladder.cells)} cells + {len(ladder.cells) - 1} steps under {out} '
          f'(peak {20 * np.log10(max(peak, 1e-9)):.2f} dBFS)')


def notes(ladder, features) -> str:
    rows = '\n'.join(f'| {c.rung:>2} | {cell_name(c):<8} | {features[c.gt()]["tempo_bpm"]:>5.0f} |'
                     for c in ladder.cells)
    return f"""# By-ear energy rating of the live cells

`cells/` has one clip per live cell (30-60 s: two consecutive v2c visits,
as a live session plays them, Rock with its presentation gain).

1. Listen to the cells in any order and fill `ratings.csv`: one number per
   cell, higher = more energetic to you (e.g. 1-10; decimals and ties are
   fine; a tie means "same energy"). Use `notes` for anything you want kept.
2. Within a genre the rating must not drop with tier (rnb2 >= rnb1, ...).
3. `steps/` holds every adjacent move of the current measured ladder (lower
   cell, then upper). Use them to check pairs you are unsure of: if a step
   sounds like a step down, rate the second cell lower than the first.
4. Then I run `energy_by_ear.py apply` on your file: the live ladder keeps its
   measured u values but assigns them in your order (`--ladder ear`).

Current measured ladder (for reference; the CSV is alphabetical on purpose):

| rung | cell     | tempo |
|------|----------|-------|
{rows}
"""


def read_ratings(path: Path, cells: list[tuple[str, int]]) -> dict[tuple[str, int], float]:
    with Path(path).open(newline='') as f:
        rows = list(csv.DictReader(f))
    ratings, errors = {}, []
    for row in rows:
        key = (row.get('cell') or '').strip()
        if not key:
            continue
        g, _, t = key.partition(':')
        try:
            ratings[(g, int(t))] = float(row['rating'])
        except (TypeError, ValueError):
            errors.append(f'{key}: rating {row.get("rating")!r} is not a number')
    errors += [f'{g}:{t}: not rated' for g, t in cells if (g, t) not in ratings]
    errors += [f'{g}:{t}: not a live cell' for g, t in ratings if (g, t) not in cells]
    if errors:
        raise SystemExit('ratings.csv:\n  ' + '\n  '.join(errors))
    return ratings


def apply(args) -> None:
    measured, features, sha = live_ladder()
    ratings = read_ratings(args.ratings, [c.gt() for c in measured.cells])
    ear, _, _ = live_ladder(ratings)
    raw = Path(args.ratings).read_bytes()
    Path(args.out).write_text(json.dumps({
        'description': "Developer's by-ear energy ratings of the live cells (energy_by_ear.py); "
                       'run_pilot_zero --ladder ear assigns the measured u values in this order.',
        'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'ratings_csv': str(args.ratings),
        'ratings_csv_sha256': hashlib.sha256(raw).hexdigest(),
        'energy_table_sha256': sha,
        'ratings': {f'{g}:{t}': ratings[(g, t)] for g, t in sorted(ratings)},
    }, indent=1) + '\n')
    print(f'{"rung":>4}  {"measured":<10} {"by ear":<10} {"rating":>6} {"tempo":>5}')
    for m, e in zip(measured.cells, ear.cells):
        print(f'{m.rung:>4}  {cell_name(m):<10} {cell_name(e):<10} {ratings[e.gt()]:>6g} '
              f'{features[e.gt()]["tempo_bpm"]:>5.0f}')
    drops = [(a, b) for a, b in zip(ear.cells, ear.cells[1:])
             if features[b.gt()]['tempo_bpm'] < features[a.gt()]['tempo_bpm'] - 0.5]
    print('by-ear up-steps that lower tempo: ' + (', '.join(
        f'{cell_name(a)} -> {cell_name(b)} ({features[a.gt()]["tempo_bpm"]:.0f} -> '
        f'{features[b.gt()]["tempo_bpm"]:.0f})' for a, b in drops) or 'none'))
    print(f'-> {args.out}')


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('render')
    p.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    p.add_argument('--out', required=True)
    p = sub.add_parser('apply')
    p.add_argument('--ratings', required=True)
    p.add_argument('--out', default=str(HERE / 'energy_order_by_ear.json'))
    args = ap.parse_args(argv)
    {'render': render, 'apply': apply}[args.cmd](args)


if __name__ == '__main__':
    main()
