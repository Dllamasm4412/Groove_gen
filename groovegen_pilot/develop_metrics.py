"""
MIDI-side before/after metrics for the v2c pitched development policies
(Calm v2c.calm.0, Lo-fi v2c.lofi.0; LIVE_GENERATION_PLAN.md section 6.13).
Debug / certification tooling, not in the live path.

Compares SessionComposer(stim) (v2a.3) with SessionComposer(stim, develop=True)
over the visits of a cell. The developed material is one track: the calm piano
line (one note per bar) or the lofi keys (color dyads and stabs). Per session:

  exact_prev        visits whose developed track equals the previous visit's
  exact_window      visits whose developed track equals one of the earlier
                    visits in the session (any distance)
  near_window       visits differing from an earlier visit other than the
                    previous one (not equal) in one bar only (calm: one bar's
                    pitch; lofi: one bar's keys); one move from the previous
                    visit is the development step itself
  ending_prev       visits whose bar-8 material equals the previous visit's
  ending_variety    distinct bar-8 material / visits
  distinct          distinct developed tracks / visits
  pitched_window    visits whose pitched layer (all pitched tracks, onsets
                    and pitches) equals one of the pitched_metrics.WINDOW
                    previous visits (pitched-bar recurrence)
  pitched_new_bar   mean share of pitched bars not in the previous visit
  drum_distinct     distinct drum layers / visits; drum_min_gap = shortest
                    distance between two visits with the same drum layer
  fallback          visits where development fell back (gentle / previous /
                    unchanged; 'gentle' is still a valid one-move candidate)
  mean_shift / top_shift: developed track mean / top pitch, last visit of a
                    block minus its first (not brighter or higher over time)
Lofi adds voicing_variety (distinct (chord, dyad) pairs / chords played),
top_contour_sim (mean contour similarity of the per-bar top voice with the
previous visit) and identity checks (bass, drums, EP, onsets, durations,
velocities, note counts) between the two versions.

usage (from groovegen_pilot/):
    python develop_metrics.py --cells calm:1,calm:2 --visits 12 --stim-seeds 1,2,19
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import numpy as np

import pitched_metrics as pmx
import stimulus_metrics as sm

BARS = 8


def calm_bars(pm) -> list[tuple]:
    """Calm piano pitch per bar (one note per downbeat)."""
    inst = next(x for x in pm.instruments if not x.is_drum and x.program == 0 and x.notes)
    return [(n.pitch,) for n in sorted(inst.notes, key=lambda n: n.start)]


def lofi_bars(pm) -> list[tuple]:
    """Lofi keys notes per bar, as sorted (slot, pitch) pairs."""
    inst = next(x for x in pm.instruments if not x.is_drum and x.name == 'keys')
    bar_s = sm.bar_seconds(sm.played_tempo(pm))
    out: list[list] = [[] for _ in range(BARS)]
    for n in inst.notes:
        b = int(n.start // bar_s + 1e-6)
        if 0 <= b < BARS:
            out[b].append((int(round((n.start - b * bar_s) / bar_s * 16)), n.pitch))
    return [tuple(sorted(x)) for x in out]


def top_voice(bars: list[tuple]) -> list[int]:
    return [max(p for _, p in b) if b and isinstance(b[0], tuple) else max(b) for b in bars]


def _contour(line: list[int]) -> tuple:
    return tuple(int(np.sign(b - a)) for a, b in zip(line, line[1:]))


def lofi_chords(pm) -> list[frozenset]:
    """Pitch classes of the EP (program 4) chord per bar."""
    inst = next(x for x in pm.instruments if not x.is_drum and x.program == 4)
    bar_s = sm.bar_seconds(sm.played_tempo(pm))
    out: list[set] = [set() for _ in range(BARS)]
    for n in inst.notes:
        b = int(n.start // bar_s + 1e-6)
        if 0 <= b < BARS:
            out[b].add(n.pitch % 12)
    return [frozenset(x) for x in out]


def _fixed(pm, genre: str) -> tuple:
    """What development must leave alone: the other pitched tracks verbatim and the
    developed track's onsets, durations, velocities and count; drums separately
    (calm develop mode widens the drum history window on purpose)."""
    dev = (lambda x: x.program == 0) if genre == 'calm' else (lambda x: x.name == 'keys')
    other, drums, shape = [], [], None
    for x in pm.instruments:
        notes = sorted((round(n.start, 6), round(n.end, 6), n.velocity, n.pitch) for n in x.notes)
        if not x.is_drum and dev(x) and x.notes:
            shape = [n[:3] for n in notes]
        else:
            (drums if x.is_drum else other).append((x.program, x.name, notes))
    return (tuple(other), tuple(shape or ())), tuple(drums)


def session(genre: str, segs: list) -> dict:
    get = calm_bars if genre == 'calm' else lofi_bars
    pms = [pm for pm, _ in segs]
    lines = [tuple(get(pm)) for pm in pms]
    rows = pmx.session_rows(pms)
    drums = [sm.content_sha(sm.bar_onset_sets(pm, BARS, 'drum')) for pm in pms]
    gaps = [b - a for a in range(len(drums)) for b in range(a + 1, len(drums)) if drums[a] == drums[b]]
    near = sum(any(x != y and sum(p != q for p, q in zip(x, y)) <= 1 for y in lines[:max(v - 1, 0)])
               for v, x in enumerate(lines))
    sel = Counter(info.get('motif_selection') for _, info in segs)
    tops = [top_voice(line) for line in lines]
    shifts = [(float(np.mean(tops[v])) - float(np.mean(tops[v - v % 3])), max(tops[v]) - max(tops[v - v % 3]))
              for v in range(len(lines))]
    out = {
        'visits': len(lines),
        'exact_prev': sum(lines[v] == lines[v - 1] for v in range(1, len(lines))),
        'exact_window': sum(x in lines[:v] for v, x in enumerate(lines)),
        'near_window': near,
        'ending_prev': sum(lines[v][-1] == lines[v - 1][-1] for v in range(1, len(lines))),
        'ending_variety': round(len({x[-1] for x in lines}) / len(lines), 3),
        'distinct': round(len(set(lines)) / len(lines), 3),
        'pitched_window': sum(r['pitched_window_repeat'] for r in rows),
        'pitched_new_bar': round(float(np.mean([r['pitched_new_bar_frac'] for r in rows[1:]])), 3),
        'drum_distinct': round(len(set(drums)) / len(drums), 3),
        'drum_min_gap': min(gaps) if gaps else None,
        'fallback': sum(sel[k] for k in ('gentle', 'previous', 'unchanged')),
        'fallback_hard': sel['previous'] + sel['unchanged'],
        'mean_shift_max': round(max(s for s, _ in shifts), 2),
        'top_shift_max': max(t for _, t in shifts),
    }
    if genre == 'lofi':
        chords = [lofi_chords(pm) for pm in pms]
        pairs = [(c, tuple(p for _, p in b)) for cs, line in zip(chords, lines) for c, b in zip(cs, line)]
        out['voicing_variety'] = round(len(set(pairs)) / len({c for c, _ in pairs}), 3)
        out['top_contour_sim'] = round(float(np.mean([1 - sm.edit_distance_norm(_contour(tops[v - 1]),
                                                                                  _contour(tops[v]))
                                                      for v in range(1, len(tops))])), 3)
    return out


COLS = ('exact_prev', 'exact_window', 'near_window', 'ending_prev', 'ending_variety', 'distinct',
        'pitched_window', 'pitched_new_bar', 'drum_distinct', 'drum_min_gap', 'fallback', 'fallback_hard',
        'mean_shift_max', 'top_shift_max')


def compare(cells, visits: int, stim_seeds: list[int]) -> list[dict]:
    from composer.arrangement import SessionComposer

    out = []
    for seed in stim_seeds:
        gens = {'v2a.3': SessionComposer(seed), 'develop': SessionComposer(seed, develop=True)}
        for g, t in cells:
            segs = {k: [c.compose(g, t, v) for v in range(visits)] for k, c in gens.items()}
            fx = [(_fixed(a, g), _fixed(b, g)) for (a, _), (b, _) in zip(segs['v2a.3'], segs['develop'])]
            for k, ss in segs.items():
                out.append({'cell': f'{g}:{t}', 'stim_seed': seed, 'version': k,
                            'dev_version': ss[-1][1].get('dev_version') if k == 'develop' else '-',
                            'fixed_identical': sum(x[0] == y[0] for x, y in fx),
                            'drum_identical': sum(x[1] == y[1] for x, y in fx), **session(g, ss)})
    return out


def main(argv=None) -> int:
    from audition_v2 import parse_cells

    ap = argparse.ArgumentParser(description='v2a.3 vs develop (v2c) pitched repetition, MIDI only')
    ap.add_argument('--cells', default='calm:2')
    ap.add_argument('--visits', type=int, default=12)
    ap.add_argument('--stim-seeds', default='1,2,19')
    args = ap.parse_args(argv)
    rows = compare(parse_cells(args.cells), args.visits, [int(s) for s in args.stim_seeds.split(',')])
    extra = [c for c in ('voicing_variety', 'top_contour_sim') if c in rows[0]]
    cols = COLS + tuple(extra)
    print('cell     seed version ' + ' '.join(f'{c[:11]:>11s}' for c in cols) + '  fixed_same drums_same')
    for r in rows:
        print(f'{r["cell"]:8s} {r["stim_seed"]:4d} {r["version"]:7s} '
              + ' '.join(f'{str(r[c]):>11s}' for c in cols) + f'  {r["fixed_identical"]:>7d}/{r["visits"]} {r["drum_identical"]:>7d}/{r["visits"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
