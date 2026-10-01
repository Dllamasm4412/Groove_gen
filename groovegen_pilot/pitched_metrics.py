"""
MIDI-side pitched and whole-segment repetition metrics for the v2b generator
(LIVE_GENERATION_PLAN.md section 6.12). Debug / certification tooling, not in
the live path.

The question is "does the complete musical material repeat?", not only the
drums. Per segment (melody = skyline of the top-line track, the motif carrier;
bass = the pitched track with the most notes below BASS_BELOW, lowest median
on a tie; not the tier-4+ sub-bass, which only mirrors beats 1 and 3):
  melody_rate, melody_median / p05 / p95, melody_max_leap, bass_rate,
  bass_root_share (bass notes on beats 1 and 3 on the most common such pitch
  class), melody_phrases (distinct 2-bar melody phrases in the segment).
Per visit against the previous visit of the cell:
  pitched_new_bar_frac / whole_new_bar_frac: share of the 8 bars (pitched
  layer / all layers) whose onset set occurs nowhere in the previous visit
  (C1 of plan 6.11 on other layers); pitched_r4 / whole_r4 / bass_r4: drum
  R4's near-repeat similarity on that layer; melody_exact; melody_pitch_sim
  (Jaccard of (slot, pitch)); melody_rhythm_sim (Jaccard of onset slots);
  melody_contour_sim (1 - normalized edit distance of the up/down/same
  contour).
Per session (all visits of a cell):
  pitched_window_repeats / whole_window_repeats: visits whose pitched / full
  content equals one of the WINDOW previous visits (exact cycles);
  melody_phrase_variety: distinct 2-bar melody phrases / phrases played;
  ending_variety: distinct bar-8 melody endings / visits.

usage (from groovegen_pilot/):
    python pitched_metrics.py --cells hiphop:1,hiphop:3,hiphop:5 --visits 8 --stim-seeds 1,2
compares v2a.3 (SessionComposer) with v2b (develop=True) and checks that the
drum layer is identical.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import numpy as np
import pretty_midi

import stimulus_metrics as sm

BARS = 8
SLOTS_PER_BAR = 16
WINDOW = 6
BASS_BELOW = 48


def _slot(t: float, tempo: float) -> int:
    return int(round(t / (60.0 / tempo / 4)))


def _line(pm: pretty_midi.PrettyMIDI, track: Optional[int], top: bool) -> list[tuple[int, int]]:
    """(16th slot, pitch) per onset of one track: highest (top) or lowest note per slot."""
    if track is None:
        return []
    tempo = sm.played_tempo(pm)
    pick: dict[int, int] = {}
    for n in pm.instruments[track].notes:
        s = _slot(n.start, tempo)
        if 0 <= s < BARS * SLOTS_PER_BAR:
            pick[s] = max(pick.get(s, -1), n.pitch) if top else min(pick.get(s, 999), n.pitch)
    return sorted(pick.items())


def bass_track(pm: pretty_midi.PrettyMIDI) -> Optional[int]:
    best, best_key = None, None
    for i, inst in enumerate(pm.instruments):
        if not inst.is_drum and inst.notes:
            key = (-sum(n.pitch < BASS_BELOW for n in inst.notes), float(np.median([n.pitch for n in inst.notes])))
            if best_key is None or key < best_key:
                best, best_key = i, key
    return best


def melody_line(pm: pretty_midi.PrettyMIDI) -> list[tuple[int, int]]:
    return _line(pm, sm.top_line_track(pm), top=True)


def bass_line(pm: pretty_midi.PrettyMIDI) -> list[tuple[int, int]]:
    return _line(pm, bass_track(pm), top=False)


def phrases(line: list[tuple[int, int]], bars: int = 2) -> list[tuple]:
    n = bars * SLOTS_PER_BAR
    out: list[list] = [[] for _ in range(BARS // bars)]
    for s, p in line:
        out[s // n].append((s % n, p))
    return [tuple(x) for x in out]


def _contour(line: list[tuple[int, int]]) -> tuple:
    return tuple(int(np.sign(b[1] - a[1])) for a, b in zip(line, line[1:]))


def _jaccard(a, b) -> float:
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 1.0


def segment_features(pm: pretty_midi.PrettyMIDI) -> dict:
    dur = BARS * sm.bar_seconds(sm.played_tempo(pm))
    mel, bass = melody_line(pm), bass_line(pm)
    mp = [p for _, p in mel]
    down = [p % 12 for s, p in bass if s % 8 == 0]
    root = Counter(down).most_common(1)[0][0] if down else None
    return {
        'melody_rate': round(len(mel) / dur, 4),
        'melody_median': float(np.median(mp)) if mp else None,
        'melody_p05': float(np.percentile(mp, 5)) if mp else None,
        'melody_p95': float(np.percentile(mp, 95)) if mp else None,
        'melody_max_leap': max((abs(b - a) for a, b in zip(mp, mp[1:])), default=0),
        'melody_phrases': len(set(phrases(mel))),
        'bass_rate': round(len(bass) / dur, 4),
        'bass_root_share': round(sum(pc == root for pc in down) / len(down), 4) if down else None,
    }


def _new_bar_frac(prev: list[frozenset], cur: list[frozenset]) -> float:
    seen = set(prev)
    return sum(b not in seen for b in cur) / len(cur)


def _bass_sets(pm: pretty_midi.PrettyMIDI) -> list[frozenset]:
    bars: list[set] = [set() for _ in range(BARS)]
    for s, p in bass_line(pm):
        bars[s // SLOTS_PER_BAR].add((p, s % SLOTS_PER_BAR))
    return [frozenset(b) for b in bars]


def visit_compare(prev: pretty_midi.PrettyMIDI, cur: pretty_midi.PrettyMIDI) -> dict:
    pp, pc = sm.bar_onset_sets(prev, BARS, 'pitched'), sm.bar_onset_sets(cur, BARS, 'pitched')
    wp, wc = sm.bar_onset_sets(prev, BARS, 'all'), sm.bar_onset_sets(cur, BARS, 'all')
    mp, mc = melody_line(prev), melody_line(cur)
    ca, cb = _contour(mp), _contour(mc)
    return {
        'pitched_new_bar_frac': _new_bar_frac(pp, pc),
        'pitched_r4': round(sm.near_repeat_similarity(pp, pc), 4),
        'whole_new_bar_frac': _new_bar_frac(wp, wc),
        'whole_r4': round(sm.near_repeat_similarity(wp, wc), 4),
        'melody_exact': mp == mc,
        'melody_pitch_sim': round(_jaccard(mp, mc), 4),
        'melody_rhythm_sim': round(_jaccard([s for s, _ in mp], [s for s, _ in mc]), 4),
        'melody_contour_sim': round(1 - sm.edit_distance_norm(ca, cb), 4),
        'bass_r4': round(sm.near_repeat_similarity(_bass_sets(prev), _bass_sets(cur)), 4),
        'bass_exact': bass_line(prev) == bass_line(cur),
    }


def session_rows(pms: list[pretty_midi.PrettyMIDI]) -> list[dict]:
    """One row per visit: segment features, comparison with the previous visit, window repeats."""
    rows, pshas, wshas = [], [], []
    for v, pm in enumerate(pms):
        psha = sm.content_sha(sm.bar_onset_sets(pm, BARS, 'pitched'))
        wsha = sm.content_sha(sm.bar_onset_sets(pm, BARS, 'all'))
        row = {'visit_idx': v, **segment_features(pm),
               'pitched_window_repeat': psha in pshas[-WINDOW:], 'whole_window_repeat': wsha in wshas[-WINDOW:]}
        if v:
            row.update(visit_compare(pms[v - 1], pm))
        rows.append(row)
        pshas.append(psha)
        wshas.append(wsha)
    return rows


def session_summary(pms: list[pretty_midi.PrettyMIDI], rows: Optional[list[dict]] = None) -> dict:
    rows = rows or session_rows(pms)
    mel = [phrases(melody_line(pm)) for pm in pms]
    ends = [tuple((s, p) for s, p in melody_line(pm) if s >= (BARS - 1) * SLOTS_PER_BAR + 8) for pm in pms]
    later = rows[1:]

    def mean(k):
        x = [r[k] for r in later if r.get(k) is not None]
        return round(float(np.mean(x)), 4) if x else None

    return {
        'visits': len(pms),
        'pitched_window_repeats': sum(r['pitched_window_repeat'] for r in rows),
        'whole_window_repeats': sum(r['whole_window_repeat'] for r in rows),
        'melody_exact_prev': sum(bool(r['melody_exact']) for r in later),
        'melody_phrase_variety': round(len({p for m in mel for p in m}) / sum(len(m) for m in mel), 4),
        'ending_variety': round(len(set(ends)) / len(ends), 4),
        **{k: mean(k) for k in ('pitched_new_bar_frac', 'whole_new_bar_frac', 'pitched_r4', 'whole_r4',
                                'melody_pitch_sim', 'melody_rhythm_sim', 'melody_contour_sim', 'bass_r4')},
        **{f'{k}_range': (min(r[k] for r in rows), max(r[k] for r in rows))
           for k in ('melody_rate', 'melody_median', 'melody_max_leap', 'bass_rate')},
    }


# =============================================================================
# CLI: v2a.3 vs v2b
# =============================================================================

SUMMARY_COLS = ('pitched_window_repeats', 'whole_window_repeats', 'melody_exact_prev', 'melody_phrase_variety',
                'ending_variety', 'pitched_new_bar_frac', 'whole_new_bar_frac', 'pitched_r4', 'whole_r4',
                'melody_pitch_sim', 'melody_contour_sim', 'bass_r4')


def compare(cells: list[tuple[str, int]], visits: int, stim_seeds: list[int]) -> tuple[list[dict], list[dict]]:
    from composer.arrangement import SessionComposer

    summaries, rows = [], []
    for seed in stim_seeds:
        gens = {'v2a.3': SessionComposer(seed), 'v2b': SessionComposer(seed, develop=True)}
        for g, t in cells:
            segs = {k: [c.compose(g, t, v) for v in range(visits)] for k, c in gens.items()}
            drum_same = all(sm.bar_onset_sets(a, BARS, 'drum') == sm.bar_onset_sets(b, BARS, 'drum')
                            for (a, _), (b, _) in zip(segs['v2a.3'], segs['v2b']))
            for k, ss in segs.items():
                pms = [pm for pm, _ in ss]
                r = session_rows(pms)
                for row, (_, info) in zip(r, ss):
                    row.update(version=k, stim_seed=seed, cell=f'{g}:{t}', motif_role=info.get('motif_role'),
                               motif_fallback=info.get('motif_fallback'))
                rows.extend(r)
                summaries.append({'version': k, 'stim_seed': seed, 'cell': f'{g}:{t}', 'drum_identical': drum_same,
                                  **session_summary(pms, r)})
    return summaries, rows


def main(argv=None) -> int:
    from audition_v2 import parse_cells

    ap = argparse.ArgumentParser(description='v2a.3 vs v2b pitched / whole-segment repetition (MIDI only)')
    ap.add_argument('--cells', default='hiphop:1,hiphop:3,hiphop:5')
    ap.add_argument('--visits', type=int, default=8)
    ap.add_argument('--stim-seeds', default='1,2')
    ap.add_argument('--csv', default=None, help='optional per-visit CSV')
    args = ap.parse_args(argv)
    summaries, rows = compare(parse_cells(args.cells), args.visits, [int(s) for s in args.stim_seeds.split(',')])
    print('cell       seed version ' + ' '.join(f'{c[:12]:>12s}' for c in SUMMARY_COLS) + '  drums_same')
    for s in summaries:
        print(f'{s["cell"]:10s} {s["stim_seed"]:4d} {s["version"]:7s} '
              + ' '.join(f'{str(s[c])[:12]:>12s}' for c in SUMMARY_COLS) + f'  {s["drum_identical"]}')
    print('ranges (v2a.3 -> v2b): ' + '; '.join(
        f'{s["cell"]} s{s["stim_seed"]} {s["version"]}: rate {s["melody_rate_range"]} median {s["melody_median_range"]} '
        f'leap {s["melody_max_leap_range"]}' for s in summaries))
    if args.csv:
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with Path(args.csv).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
    return 0


if __name__ == '__main__':
    sys.exit(main())
