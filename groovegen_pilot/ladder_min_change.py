"""
The developer's perceptual live ladder (frozen 2026-10-06): the minimum-change
re-order of the measured ladder under the blind listening relations that
replicated, the listening sets that produced them, and `freeze`, which writes
energy_order_by_ear.json for run_pilot_zero --ladder ear (the only runtime
use; the analysis commands write under renders/ladder_audit/).

Listening (developer, blind, 2026-10-06): 14 boundary pairs (stimulus seed 1,
random playback order), then the six relations that reversed the B-iso
proposal plus the rnb4 / latin2 tie again (seed 2, reversed playback order,
complete 8-bar excerpts). Four relations held in both orders (LISTENING);
latin1 / hiphop2 flipped with play order, pop1 / rock2 went from rock2 higher
to a tie, rnb4 / latin2 went from a tie to latin2 higher. Unstable or tied
comparisons add no constraint: they fall back to the measured order. The
seven first-test relations not replicated already hold in the measured order
and move nothing. Genre is descriptive only; no BPM term is added (tempo is
already weight 0.20 in the measured score and r = 0.83 with the acoustic
terms).

Ladder (`ladder`): the 27 live cells re-ordered so that
  - every within-genre tier order holds (live caps as run_pilot_zero),
  - every relation in LISTENING holds,
and the order moves the current measured ladder as little as possible. Exact
integer program (assignment of cells to rungs, precedence constraints),
solved lexicographically:
  1. minimum total |rung displacement|;
  2. then minimum largest displacement;
  3. then fewest moved cells;
  4. then the order most consistent with the measured energy score (maximum
     sum of E x rung), which makes the answer unique and deterministic.
Every ladder that ties on 1-3 is enumerated and reported (where they differ is
not decided by the data); for LISTENING the optimum is unique (total
displacement 12, largest 3, 9 cells moved) and equals FINAL_ORDER. The u values
stay the measured ones (order-only, as --ladder ear).

Freeze (`freeze`): solves again, checks the result equals FINAL_ORDER, writes
energy_order_by_ear.json (ratings = final rung + 1) and checks that
ladder.build_ladder(ear_ratings=) reproduces FINAL_ORDER with the measured u set.

Replication (`replication`): seven blind pairs (the six reversed relations and
the tie), in the opposite playback order to the first test, new stimulus seed,
live v2c render and mix path (Rock presentation gain included). Each side is
its complete 8-bar segment at native tempo, trimmed as run_session_v2 (8 bars
+ one crossfade) and joined by the live mixer; no stretching or truncation, so
the two sides differ in length when tempo differs. (The first version cut both
sides to the shorter side's 8 bars, leaving the slower cell mid-phrase;
replaced 2026-10-06.) Neutral filenames, items in a seeded shuffled order, key
in a hidden folder.

Usage:
    python ladder_min_change.py freeze                 # writes energy_order_by_ear.json
    python ladder_min_change.py ladder [--out renders/ladder_audit/20261006_min_change]
    python ladder_min_change.py replication [--out renders/ladder_audit/20261006_replication]
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
AUDIT = HERE / 'renders' / 'ladder_audit' / '20261006_audit'

# (lower, upper): relations that held in both blind listening rounds
LISTENING = (
    (('lofi', 1), ('hiphop', 1)), (('rnb', 1), ('rock', 1)),
    (('hiphop', 3), ('pop', 4)), (('hiphop', 4), ('rock', 3)),
)
LISTENING_TIES = ((('rnb', 4), ('latin', 2)),)      # tie, then latin2 higher: no constraint
# First round (stimulus seed 1), decoded from the playback order in boundary_sheet.csv
FIRST_TEST = (
    (('lofi', 1), ('hiphop', 1)), (('lofi', 3), ('rnb', 1)), (('latin', 1), ('hiphop', 2)),
    (('latin', 1), ('rock', 1)), (('rnb', 1), ('rock', 1)), (('latin', 1), ('rnb', 4)),
    (('latin', 3), ('rock', 2)), (('pop', 1), ('rock', 2)), (('latin', 3), ('hiphop', 3)),
    (('hiphop', 3), ('pop', 4)), (('hiphop', 3), ('pop', 5)), (('pop', 5), ('rock', 3)),
    (('hiphop', 4), ('rock', 3)),
)
# Approved by the developer 2026-10-06; frozen unless a live run shows a broken transition
FINAL_ORDER = ('calm1', 'calm2', 'lofi1', 'hiphop1', 'lofi2', 'lofi3', 'hiphop2', 'latin1', 'rnb1', 'rock1',
               'rnb2', 'rnb3', 'latin2', 'rnb4', 'latin3', 'rock2', 'pop1', 'pop2', 'pop3', 'hiphop3',
               'pop4', 'pop5', 'hiphop4', 'rock3', 'hiphop5', 'rock4', 'rock5')
SHARP_BPM_DROP = 10.0
MAX_ALTERNATIVES = 200

# Replication: (original pair number, first heard, second heard) in the first test
REPLICATE = ((1, ('hiphop', 1), ('lofi', 1)), (3, ('latin', 1), ('hiphop', 2)), (5, ('rnb', 1), ('rock', 1)),
             (9, ('pop', 1), ('rock', 2)), (11, ('pop', 4), ('hiphop', 3)), (14, ('rock', 3), ('hiphop', 4)),
             (7, ('latin', 2), ('rnb', 4)))
REPLICATION_STIM_SEED = 2           # first test: energy_by_ear.STIM_SEED = 1
REPLICATION_ORDER_SEED = 20261007


def name(k) -> str:
    return f'{k[0]}{k[1]}'


# =============================================================================
# Ladder
# =============================================================================


def inputs():
    from energy_by_ear import live_ladder
    from ladder_audit import composite, load

    features, weights, tie_band, sha, keys, live, caps = load()
    e_a, _ = composite(features, keys, weights)
    current, _, _ = live_ladder()
    return features, tie_band, sha, e_a, current


def precedence(cells):
    tiers = [((g, t), (g, t + 1)) for g, t in cells if (g, t + 1) in cells]
    return tiers + [p for p in LISTENING if p[0] in cells and p[1] in cells]


def solve(cells, cur, e, extra_cuts=(), fix=None):
    """Lexicographic min-change order. fix = (total, max, moved) to enumerate ties
    (stage 4 skipped). Returns (order, stats) or None."""
    from scipy.optimize import Bounds, LinearConstraint, milp

    n = len(cells)
    idx = {c: i for i, c in enumerate(cells)}
    nx = n * n                                     # x[c, r] at c * n + r; then m (max displacement)
    nv = nx + 1
    disp = np.array([abs(r - cur[c]) for c in cells for r in range(n)], float)
    A, lo, hi = [], [], []

    def row(coefs, a, b):
        v = np.zeros(nv)
        for j, x in coefs:
            v[j] += x
        A.append(v)
        lo.append(a)
        hi.append(b)

    for i in range(n):
        row([(i * n + r, 1) for r in range(n)], 1, 1)          # each cell one rung
        row([(c * n + i, 1) for c in range(n)], 1, 1)          # each rung one cell
    for a, b in precedence(cells):                              # rung(b) - rung(a) >= 1
        row([(idx[b] * n + r, r) for r in range(n)] + [(idx[a] * n + r, -r) for r in range(n)], 1, np.inf)
    for i, c in enumerate(cells):                               # displacement(c) <= m
        row([(i * n + r, abs(r - cur[c])) for r in range(n)] + [(nx, -1)], -np.inf, 0)
    for sol in extra_cuts:                                      # exclude found orders
        row([(idx[c] * n + r, 1) for r, c in enumerate(sol)], -np.inf, n - 1)
    keep = np.zeros(nv)
    for i, c in enumerate(cells):
        keep[i * n + cur[c]] = 1
    integrality = np.r_[np.ones(nx), 0]
    bounds = Bounds(np.zeros(nv), np.r_[np.ones(nx), n])

    def run(obj, more=()):
        cons = [LinearConstraint(np.array(A + [m[0] for m in more]), lo + [m[1] for m in more],
                                 hi + [m[2] for m in more])]
        res = milp(obj, constraints=cons, integrality=integrality, bounds=bounds)
        return res if res.success else None

    total = np.r_[disp, 0]
    mvec = np.r_[np.zeros(nx), 1]
    if fix is None:
        r1 = run(total)
        if r1 is None:
            return None
        t1 = round(r1.fun)
        r2 = run(mvec, [(total, -np.inf, t1)])
        m2 = round(r2.fun)
        r3 = run(-keep, [(total, -np.inf, t1), (mvec, -np.inf, m2)])
        k3 = round(-r3.fun)
        fix_ = (t1, m2, n - k3)
        ev = np.r_[[e[c] * r for c in cells for r in range(n)], 0]
        res = run(-ev, [(total, -np.inf, t1), (mvec, -np.inf, m2), (keep, k3, np.inf)])
    else:
        t1, m2, moved = fix
        fix_ = fix
        res = run(np.zeros(nv), [(total, -np.inf, t1), (mvec, -np.inf, m2), (keep, n - moved, np.inf)])
        if res is None:
            return None
    x = np.round(res.x[:nx]).reshape(n, n)
    order = [None] * n
    for i, c in enumerate(cells):
        order[int(np.argmax(x[i]))] = c
    return order, {'total_displacement': fix_[0], 'max_displacement': fix_[1], 'moved_cells': fix_[2]}


def closure(cells):
    """Transitive closure of the listening + tier precedence (a < b implied)."""
    succ = {c: set() for c in cells}
    for a, b in precedence(cells):
        succ[a].add(b)
    out = {}
    for c in cells:
        seen, stack = set(), [c]
        while stack:
            for d in succ[stack.pop()]:
                if d not in seen:
                    seen.add(d)
                    stack.append(d)
        out[c] = seen
    return out


def ladder(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    features, tie_band, sha, e, current = inputs()
    cells = [c.gt() for c in current.cells]
    cur = {k: i for i, k in enumerate(cells)}
    bpm = {k: float(features[k]['tempo_bpm']) for k in cells}
    biso = json.loads((AUDIT / 'report.json').read_text())['proposed']['order']
    biso_rung = {k: biso.index(name(k)) for k in cells}

    violated = [p for p in precedence(cells) if cur[p[0]] > cur[p[1]]]
    order, stats = solve(cells, cur, e)
    new = {k: i for i, k in enumerate(order)}
    assert len(order) == len(set(order)) == 27 and set(order) == set(cells)
    assert all(new[a] < new[b] for a, b in precedence(cells))

    alts = [order]
    while len(alts) < MAX_ALTERNATIVES:
        r = solve(cells, cur, e, extra_cuts=alts, fix=(stats['total_displacement'], stats['max_displacement'],
                                                        stats['moved_cells']))
        if r is None:
            break
        alts.append(r[0])
    differs = sorted({i for a in alts for i, k in enumerate(a) if k != order[i]})

    # moved cells and the constraints behind each move
    moved = []
    for k in order:
        if new[k] == cur[k]:
            continue
        own = [p for p in violated if k in p]
        why = '; '.join(f'{name(a)} < {name(b)}' + (' (tier)' if a[0] == b[0] else ' (listening)') for a, b in own) \
            or 'shifted to make room (no violated constraint of its own)'
        moved.append({'cell': name(k), 'current_rung': cur[k], 'b_iso_rung': biso_rung[k], 'new_rung': new[k],
                      'displacement': new[k] - cur[k], 'bpm': bpm[k], 'measured_E': round(e[k], 4), 'reason': why})

    # adjacent boundaries
    clo = closure(cells)
    listened = {(a, b) for a, b in LISTENING} | {tuple(p) for p in LISTENING_TIES} | \
        {(b, a) for a, b in LISTENING_TIES}
    bounds = []
    for i, (a, b) in enumerate(zip(order, order[1:])):
        de = e[b] - e[a]
        if (a, b) in listened:
            support = 'tie by ear' if (a, b) in {tuple(p) for p in LISTENING_TIES} | \
                {(y, x) for x, y in LISTENING_TIES} else 'listened'
        elif a[0] == b[0]:
            support = 'tier rule'
        elif b in clo[a]:
            support = 'implied by listening + tier'
        elif de >= 2 * tie_band:
            support = 'measured (>= 2 noise floors)'
        else:
            support = 'none'
        flags = []
        if abs(de) < tie_band:
            flags.append('measured near tie')
        if bpm[b] <= bpm[a] - SHARP_BPM_DROP:
            flags.append(f'bpm {bpm[a]:.0f}->{bpm[b]:.0f}')
        if support == 'none':
            flags.append('unsupported')
        if de <= -tie_band:
            flags.append('measured E falls' + {'listened': ' (listening overrides)',
                                               'tier rule': ' (tier rule overrides)'}.get(support, ''))
        if i in differs or i + 1 in differs:
            flags.append('alternative optimum differs here')
        bounds.append({'rung': i, 'lower': name(a), 'upper': name(b), 'bpm': f'{bpm[a]:.0f}->{bpm[b]:.0f}',
                       'dE': round(de, 4), 'dE_noise_floors': round(de / tie_band, 2), 'support': support,
                       'flags': '; '.join(flags)})

    rows = [{'rung': i, 'cell': name(k), 'genre': k[0], 'tier': k[1], 'bpm': bpm[k], 'measured_E': round(e[k], 4),
             'u': round(current.cells[i].u, 4), 'current_rung': cur[k], 'b_iso_rung': biso_rung[k],
             'displacement': i - cur[k]} for i, k in enumerate(order)]
    with (out / 'min_change_ladder.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with (out / 'boundaries.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(bounds[0]))
        w.writeheader()
        w.writerows(bounds)
    (out / 'min_change_report.json').write_text(json.dumps({
        'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'energy_table_sha256': sha, 'tie_band_e': tie_band,
        'method': __doc__.split('Replication')[0].strip(),
        'listening_constraints': [f'{name(a)} < {name(b)}' for a, b in LISTENING],
        'listening_ties': [f'{name(a)} ~ {name(b)}' for a, b in LISTENING_TIES],
        'violated_in_current': [f'{name(a)} < {name(b)}' for a, b in violated],
        'order': [name(k) for k in order], 'stats': stats, 'moved': moved,
        'alternative_optima': {'count_including_chosen': len(alts), 'capped_at': MAX_ALTERNATIVES,
                               'rungs_that_differ': differs,
                               'orders': [[name(k) for k in a] for a in alts]},
        'tie_pair_rungs': {name(k): new[k] for p in LISTENING_TIES for k in p},
        'boundaries': bounds}, indent=1) + '\n')
    print(json.dumps({'order': [name(k) for k in order], 'stats': stats, 'alternatives': len(alts),
                      'differs': differs}, indent=0))


# =============================================================================
# Replication listening set
# =============================================================================


REPLICATION_FILES = ('LISTENING_NOTES.md', 'replication_sheet.csv', '.key/replication_key.json')


def replication(args) -> None:
    from audition_v2 import BARS, SAMPLE_RATE, join_like_live, trim_like_live
    from composer.arrangement import SessionComposer, cell_plan
    from crossfade import bar_duration_frames
    from energy_by_ear import STIM_SEED
    from segment_renderer import SymbolicSegmentRenderer, _write_wav
    import stimulus_metrics as sm

    out = Path(args.out)
    if out.exists():
        mine = {out / f for f in REPLICATION_FILES} | set(out.glob('item_*.wav'))
        other = [p for p in out.rglob('*') if p.is_file() and p not in mine]
        if other or not args.replace and any(p.exists() for p in mine):
            raise SystemExit(f'{out} has files (other: {other}); pass --replace to overwrite this set only')
        for p in mine:
            p.unlink(missing_ok=True)
    (out / '.key').mkdir(parents=True, exist_ok=True)
    first_sheet = {int(r['pair']): (r['first'], r['second'])
                   for r in csv.DictReader((AUDIT / 'boundary_sheet.csv').open())}
    r = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=SAMPLE_RATE, session_seed=42)
    new_sc, old_sc = SessionComposer(REPLICATION_STIM_SEED, develop=True), SessionComposer(STIM_SEED, develop=True)

    def seg(k):
        """Visit 0 of cell k, rendered and trimmed as run_session_v2 (8 bars + one crossfade)."""
        pm, info = new_sc.compose(k[0], k[1], 0)
        old, _ = old_sc.compose(k[0], k[1], 0)
        tempo = cell_plan(*k)[0]
        bar = bar_duration_frames(tempo, 4, SAMPLE_RATE)
        bar_s = 4 * 60.0 / tempo
        onsets = [n.start for x in pm.instruments for n in x.notes]
        bars_with_notes = sorted({int(t / bar_s + 1e-6) for t in onsets})
        audio = trim_like_live(r._render_pm_to_audio(pm), tempo)
        return {'cell': name(k), 'audio': audio, 'tempo': tempo, 'bar_frames': bar,
                'midi_sha256': sm.midi_sha256(pm), 'differs_from_first_test': sm.midi_sha256(pm) != sm.midi_sha256(old),
                'bars_with_notes': bars_with_notes, 'last_onset_s': round(max(onsets), 3),
                'gen_version': info.get('gen_version'), 'motif_selection': info.get('motif_selection')}

    items = list(REPLICATE)
    random.Random(REPLICATION_ORDER_SEED).shuffle(items)
    sheet, key = [], []
    for i, (pair, a, b) in enumerate(items, 1):
        assert first_sheet[pair] == (name(a), name(b)), (pair, first_sheet[pair])
        first, second = b, a                                   # reversed vs the first test
        sides = [seg(first), seg(second)]
        joined, starts, stats = join_like_live([s['audio'] for s in sides], [s['tempo'] for s in sides])
        fname = f'item_{i:02d}.wav'
        _write_wav(out / fname, joined, SAMPLE_RATE)
        ends = [starts[1], len(joined)]
        parts = []
        for s, st, en in zip(sides, starts, ends):
            phrase = BARS * s['bar_frames']
            ok = s['bars_with_notes'] == list(range(BARS)) and len(s['audio']) >= phrase and en - st >= phrase
            assert ok, (s['cell'], s['bars_with_notes'], len(s['audio']), en - st, phrase)
            parts.append({'cell': s['cell'], 'bpm': s['tempo'], 'bars_rendered': BARS,
                          'bars_with_notes': [x + 1 for x in s['bars_with_notes']],
                          'phrase_s': round(phrase / SAMPLE_RATE, 3),
                          'starts_s': round(st / SAMPLE_RATE, 3), 'heard_s': round((en - st) / SAMPLE_RATE, 3),
                          'complete_8_bar_phrase': ok, 'stim_seed': REPLICATION_STIM_SEED, 'visit': 0,
                          'midi_sha256': s['midi_sha256'], 'differs_from_first_test': s['differs_from_first_test'],
                          'gen_version': s['gen_version'], 'motif_selection': s['motif_selection']})
        sheet.append({'item': i, 'file': fname,
                      'question': 'Does the second complete excerpt feel lower, equal or higher in energy than the first?',
                      'judgement': '', 'notes': ''})
        key.append({'item': i, 'file': fname, 'first': name(first), 'second': name(second),
                    'original_pair': pair, 'original_first': name(a), 'original_second': name(b),
                    'parts': parts, 'total_s': round(len(joined) / SAMPLE_RATE, 3), 'mixer': stats,
                    'peak_dbfs': round(20 * float(np.log10(max(np.max(np.abs(joined)), 1e-9))), 2)})
    with (out / 'replication_sheet.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(sheet[0]))
        w.writeheader()
        w.writerows(sheet)
    (out / '.key' / 'replication_key.json').write_text(json.dumps({
        'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'sf2': str(args.sf2),
        'stim_seed': REPLICATION_STIM_SEED, 'first_test_stim_seed': STIM_SEED, 'visit': 0,
        'item_order_seed': REPLICATION_ORDER_SEED,
        'path': 'SessionComposer(develop=True) v2c visit 0, SymbolicSegmentRenderer._render_pm_to_audio (Rock '
                'gain included), audition_v2.trim_like_live (8 bars + one crossfade, as run_session_v2), '
                'audition_v2.join_like_live (live tail_out mixer); native tempo, no stretch, no truncation',
        'items': key}, indent=1) + '\n')
    (out / 'LISTENING_NOTES.md').write_text(f"""# Replication listening (blind)

{len(items)} files, `item_01.wav` .. `item_{len(items):02d}.wav`. Each plays one
complete musical excerpt, then a second complete excerpt, joined with the
live crossfade. Excerpts play at their own tempo, so the two parts of an item
can differ in length.

For each item, fill `judgement` in `replication_sheet.csv`: does the
**second** excerpt feel `lower`, `equal` or `higher` in energy than the
first? Use `notes` for anything else.

Listen in any order, at one fixed volume, as many times as you like. The key
is in the hidden `.key/` folder; please do not open it until the sheet is
filled.
""")
    print(f'wrote {len(items)} items under {out}')


def freeze(args) -> None:
    """Write energy_order_by_ear.json from the solved order (must equal FINAL_ORDER)."""
    from ladder import build_ladder, load_ear_ratings
    from ladder_audit import load
    from run_pilot_zero import EAR_ORDER

    features, tie_band, sha, e, current = inputs()
    cells = [c.gt() for c in current.cells]
    order, stats = solve(cells, {k: i for i, k in enumerate(cells)}, e)
    if tuple(name(k) for k in order) != FINAL_ORDER:
        raise SystemExit(f'solved order differs from FINAL_ORDER: {[name(k) for k in order]}')
    out = Path(args.out or EAR_ORDER)
    out.write_text(json.dumps({
        'description': "Developer's perceptual live ladder (frozen 2026-10-06): the minimum-change re-order of "
                       'the measured ladder under the blind listening relations that replicated '
                       '(ladder_min_change.py). Ratings are final rung + 1; run_pilot_zero --ladder ear assigns '
                       'the measured u values in this order.',
        'created': time.strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'ladder_min_change.py freeze',
        'energy_table_sha256': sha,
        'listening_relations': [f'{name(a)} < {name(b)}' for a, b in LISTENING],
        'stats': stats,
        'ratings': {f'{k[0]}:{k[1]}': float(i + 1) for i, k in enumerate(order)},
    }, indent=1) + '\n')
    features, weights, tie_band, sha2, keys, live, caps = load()
    ratings, file_sha = load_ear_ratings(out)
    ear = build_ladder(tier_caps=caps, features=features, weights=weights, tie_band=tie_band, ear_ratings=ratings)
    assert tuple(name(c.gt()) for c in ear.cells) == FINAL_ORDER
    assert np.allclose([c.u for c in ear.cells], [c.u for c in current.cells])
    print(f'wrote {out} (sha256 {file_sha[:16]}): {len(ear.cells)} cells, {stats}')


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('ladder')
    p.add_argument('--out', default=str(HERE / 'renders' / 'ladder_audit' / '20261006_min_change'))
    p = sub.add_parser('freeze')
    p.add_argument('--out', default=None, help='default: run_pilot_zero.EAR_ORDER (energy_order_by_ear.json)')
    p = sub.add_parser('replication')
    p.add_argument('--out', default=str(HERE / 'renders' / 'ladder_audit' / '20261006_replication'))
    p.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    p.add_argument('--replace', action='store_true', help='overwrite this replication set (its own files only)')
    args = ap.parse_args(argv)
    {'ladder': ladder, 'freeze': freeze, 'replication': replication}[args.cmd](args)


if __name__ == '__main__':
    main()
