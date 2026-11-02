"""
Per-operation audio attribution for the v2 drum variation (debug / certification
only; LIVE_GENERATION_PLAN.md section 6.8). Not imported by the live path.

For each cell, composes the v2 session segments exactly as certify_stimuli.py
does (SessionComposer, stim seeds, visits), then renders:
  - each segment's own base and the varied segment;
  - the base with ONE logged op applied (every op of every segment), so each
    op's audio effect is measured alone against the same base;
  - probes (--probes K): up to K candidate ops of every op subtype drawn from
    the base's own candidates, independent of what the generator chose.

Every row records op kind / subtype, bar, voices, onsets, family change, the
drum_brightness delta, and the centroid / flux / pulse_clarity / LUFS / E
deltas vs the base, plus the same deltas in units of the cell's certification
allowance (read from a certification_summary.json, --cert).

    python op_attribution.py --cells hiphop:3,rock:5 --probes 3
writes renders/op_attribution/<stamp>/ops.csv and prints a per-subtype summary.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import certify_stimuli as cs  # noqa: E402
import stimulus_metrics as sm  # noqa: E402
from composer import variation as va  # noqa: E402

FEATS = ('centroid_hz', 'flux', 'pulse_clarity', 'lufs', 'energy_e')
_OP = re.compile(r'^(exchange|family|cross|grid_move|move):(.*)$')


def parse_op(desc: str) -> dict:
    """Structured form of a vary() drum_ops string."""
    kind, body = _OP.match(desc).groups()
    if kind == 'exchange':
        pa, a, pb, b = map(int, re.match(r'(\d+)@(\d+)<>(\d+)@(\d+)', body).groups())
        return {'kind': kind, 'notes': [(pa, a, b), (pb, b, a)], 'from_voice': pa, 'to_voice': pb,
                'from_pos': a, 'to_pos': b, 'subtype': f'exchange {min(pa, pb)}<>{max(pa, pb)}'}
    if kind in ('move', 'grid_move'):
        p, pos, d = re.match(r'(\d+)@(\d+)([+-]1)', body).groups()
        p, pos, d = int(p), int(pos), int(d)
        return {'kind': kind, 'notes': [(p, pos, pos + d)], 'from_voice': p, 'to_voice': p,
                'from_pos': pos, 'to_pos': pos + d, 'subtype': f'{kind} {p}'}
    old, new, pos = map(int, re.match(r'(\d+)>(\d+)@(\d+)', body).groups())
    return {'kind': kind, 'repitch': (old, new, pos), 'from_voice': old, 'to_voice': new,
            'from_pos': pos, 'to_pos': pos, 'subtype': f'{kind} {old}>{new}'}


def apply_op(base, genre: str, bar: int, op: dict):
    """Copy of base with the single op applied (the op's notes are at their base slots)."""
    pm = copy.deepcopy(base)
    step = va._step_s(pm)
    hits = {(h.bar, h.pos, h.note.pitch): h for h in
            (va._Hit(n, step, genre) for i in pm.instruments if i.is_drum for n in i.notes)}
    if 'repitch' in op:
        old, new, pos = op['repitch']
        hits[(bar, pos, old)].note.pitch = new
    else:
        for p, frm, to in op['notes']:
            va._move(hits[(bar, frm, p)], to - frm, step)
    for i in pm.instruments:
        if i.is_drum:
            i.notes.sort(key=lambda n: (n.start, n.pitch))
    return pm


def probe_ops(base, genre: str, k: int, seed: int) -> list[tuple[int, str]]:
    """Up to k (bar, desc) candidates per subtype from the base itself (bars 4 and 8)."""
    step = va._step_s(base)
    pm = copy.deepcopy(base)
    hits = [va._Hit(n, step, genre) for i in pm.instruments if i.is_drum for n in i.notes]
    ctx = va._Ctx(pm, step, {h.note.pitch for h in hits}, 0)
    by_sub = defaultdict(list)
    for b in va.PHRASE_ENDS:
        bar = [h for h in hits if h.bar == b]
        for tier in va.TIERS:
            for kind, desc, *_ in va._candidates(tier, bar, range(va.STEPS), ctx):
                d = f'{kind}:{desc}'
                by_sub[parse_op(d)['subtype']].append((b, d))
    rng = random.Random(seed)
    out = []
    for sub in sorted(by_sub):
        c = by_sub[sub]
        rng.shuffle(c)
        out += c[:k]
    return out


def main(argv=None) -> int:
    from composer import generate_segment
    from composer.arrangement import BARS, SessionComposer, cell_plan

    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--cells', required=True)
    ap.add_argument('--visits', type=int, default=12)
    ap.add_argument('--stim-seeds', default='1,2')
    ap.add_argument('--probes', type=int, default=0, help='candidate probes per subtype per base')
    ap.add_argument('--cert', default=None, help='certification_summary.json for allowances (default: latest audio run)')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--out', default=None)
    args = ap.parse_args(argv)
    cells = [(g, int(t)) for g, t in (c.split(':') for c in args.cells.split(','))]
    seeds = [int(s) for s in args.stim_seeds.split(',')]

    cert = Path(args.cert) if args.cert else max(
        (p for p in (HERE / 'renders' / 'certification').glob('*/certification_summary.json')
         if any('audio' in c for c in json.loads(p.read_text())['cells'].values())),
        key=lambda p: p.parent.name)
    summary = json.loads(cert.read_text())['cells']
    table = json.loads((HERE / 'energy_table_v1.json').read_text())
    z = cs.energy_z_params(table)

    rows, pms = [], {}
    for genre, tier in cells:
        tempo, dens = cell_plan(genre, tier)
        for ss in seeds:
            sc = SessionComposer(ss)
            for v in range(args.visits):
                pm, info = sc.compose(genre, tier, v)
                base = generate_segment(genre, tempo_bpm=tempo, density=dens, duration_bars=BARS,
                                        seed=info['base_seed'])
                bsha = sm.midi_sha256(base)
                pms[bsha] = base
                ctx = {'cell': f'{genre}:{tier}', 'genre': genre, 'stim_seed': ss, 'visit_idx': v,
                       'base_sha': bsha, 'b_bright': va.drum_brightness(base)}
                variants = [('segment', None, None, pm)]
                for b, ops in enumerate(info.get('drum_ops') or []):
                    for d in ops:
                        variants.append(('op', b, d, apply_op(base, genre, b, parse_op(d))))
                if args.probes and v % 3 == 0 and ss == seeds[0]:   # one probe set per base, first stim seed
                    for b, d in probe_ops(base, genre, args.probes, hash((ss, v)) & 0xffff):
                        variants.append(('probe', b, d, apply_op(base, genre, b, parse_op(d))))
                for src, b, d, vpm in variants:
                    sha = sm.midi_sha256(vpm)
                    pms[sha] = vpm
                    op = parse_op(d) if d else {}
                    rows.append({**ctx, 'source': src, 'bar': b, 'op': d, 'kind': op.get('kind'),
                                 'subtype': op.get('subtype'), 'from_voice': op.get('from_voice'),
                                 'to_voice': op.get('to_voice'), 'from_pos': op.get('from_pos'),
                                 'to_pos': op.get('to_pos'),
                                 'family_change': (va.FAMILY.get(op['from_voice']) != va.FAMILY.get(op['to_voice'])
                                                   if op and op['kind'] != 'exchange' else False),
                                 'sha': sha, 'd_bright': round(va.drum_brightness(vpm) - ctx['b_bright'], 5)})
    print(f'rendering {len(pms)} unique segments for {len(rows)} rows', flush=True)
    feats = cs.render_all(pms, args.sf2, args.workers)
    for sha, f in feats.items():             # certify_stimuli's per-segment E
        pm = pms[sha]
        f['energy_e'] = cs.segment_energy(
            {'lufs': f['lufs'], 'drum_rate': sm.bounded_features(pm, BARS)['drum_rate'],
             'tempo_bpm': sm.played_tempo(pm), 'centroid_hz': f['centroid_hz'], 'flux': f['flux']},
            z, table['weights'])

    for r in rows:
        fv, fb = feats[r['sha']], feats[r['base_sha']]
        allowed = {f: (summary[r['cell']]['audio']['shift'].get(f) or {}).get('allowed') for f in FEATS}
        for f in FEATS:
            if fv.get(f) is None or fb.get(f) is None:
                continue
            r[f'd_{f}'] = fv[f] - fb[f]
            if allowed.get(f):
                r[f'x_{f}'] = r[f'd_{f}'] / allowed[f]

    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else HERE / 'renders' / 'op_attribution' / stamp
    out.mkdir(parents=True, exist_ok=True)
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with (out / 'ops.csv').open('w', newline='') as fh:
        w = csv.DictWriter(fh, keys)
        w.writeheader()
        w.writerows(rows)
    print(f'wrote {out / "ops.csv"} (allowances from {cert.parent.name})')
    print_summary(rows)
    return 0


def print_summary(rows: list[dict]) -> None:
    """Mean effect per (cell, source, subtype) in allowance units; segment rows give the total."""
    grp = defaultdict(list)
    for r in rows:
        grp[(r['cell'], r['source'], r['subtype'] or '(whole segment)')].append(r)
    xs = ('centroid_hz', 'flux', 'pulse_clarity')
    print(f"{'cell':9s} {'source':8s} {'subtype':22s} {'n':>4s} {'ops/seg':>7s} "
          + ' '.join(f'{f[:8]:>9s}' for f in xs) + f" {'lufs':>7s} {'bright':>8s}   (x allowance per op)")
    nseg = defaultdict(int)
    for r in rows:
        if r['source'] == 'segment':
            nseg[r['cell']] += 1
    for (cell, src, sub), rs in sorted(grp.items()):
        vals = [np.mean([r.get(f'x_{f}', np.nan) for r in rs]) for f in xs]
        per_seg = len(rs) / nseg[cell] if src == 'op' else float('nan')
        print(f'{cell:9s} {src:8s} {sub:22s} {len(rs):4d} {per_seg:7.2f} '
              + ' '.join(f'{x:+9.2f}' for x in vals)
              + f" {np.mean([r.get('d_lufs', np.nan) for r in rs]):+7.3f} {np.mean([r['d_bright'] for r in rs]):+8.4f}")


if __name__ == '__main__':
    raise SystemExit(main())
