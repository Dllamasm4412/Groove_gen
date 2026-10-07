"""
Summarize one run_session_v2 session folder (a live run_pilot_zero session or
a simulate_session_v2 output): timing headroom, cells and rungs, controller
direction, rotation, visit-state continuity, development fallbacks, HR
validity, and audio peaks / clipping. Engineering summary only: HR numbers
are reported as tracking, never as an effect of the music.

Audio: a simulated session has session.wav (measured directly). A live session
writes no audio, so --render rebuilds it from the trace (v2c only): every
segment is composed again in trace order with SessionComposer(stim seed) (the
trace's gen_base_seed / motif_id must match), rendered with the current
renderer and joined by the live mixer. If session.wav exists the rebuild is
compared with it.

Usage:
    python summarize_session.py <session_dir> [--render] [--sf2 Musyng_Kite.sf2]
Writes <session_dir>/session_summary.json and prints it.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PLAN_COLS = ('genre', 'tier', 'rung', 'tempo_bpm', 'seed', 'generator', 'gen_visit_idx', 'gen_base_seed',
             'motif_id', 'motif_selection', 'control_mode', 'mpc_rung')
FULL_SCALE = 32767 / 32768
LOW_HEADROOM_S = 0.5


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _stats(v):
    v = [x for x in v if x is not None]
    if not v:
        return None
    a = np.asarray(v, float)
    return {'n': len(v), 'min': round(float(a.min()), 3), 'median': round(float(np.median(a)), 3),
            'mean': round(float(a.mean()), 3), 'max': round(float(a.max()), 3)}


def load(session: Path):
    rows = list(csv.DictReader((session / 'session_trace.csv').open()))
    meta = {}
    for name in ('summary.json', 'manifest.json'):
        if (session / name).exists():
            meta[name] = json.loads((session / name).read_text())
    return rows, meta


def plan_invariance(rows) -> int:
    by: dict[str, dict[str, set]] = {}
    for r in rows:
        d = by.setdefault(r['segment_idx'], {})
        for c in PLAN_COLS:
            if c in r:
                d.setdefault(c, set()).add(r[c])
    return max(len(v) for d in by.values() for v in d.values())


def initial_rung(meta):
    s = meta.get('summary.json', {})
    if 'initial_rung' in s:
        return int(s['initial_rung'])
    return None


def control(segs, first_rung):
    rungs = [int(s['rung']) for s in segs]
    cur = [first_rung] + rungs[:-1]
    out = {'direction_requests': 0, 'direction_violations': 0, 'violations': [], 'holds_on_request': 0}
    jumps_by_mode: dict[str, list[int]] = {}
    for k, (s, c) in enumerate(zip(segs, cur)):
        if c is None:
            continue
        mpc = int(float(s['mpc_rung'])) if s.get('mpc_rung') not in (None, '') else None
        nxt = int(s['rung'])
        mode = s['control_mode']
        jumps_by_mode.setdefault(mode, []).append(abs(nxt - c))
        if mpc is None or mode == 'stale_hold':
            continue
        m = (mpc > c) - (mpc < c)
        if m:
            out['direction_requests'] += 1
            if m * (nxt - c) < 0:
                out['direction_violations'] += 1
                out['violations'].append({'segment': int(s['segment_idx']), 'from': c, 'mpc': mpc, 'to': nxt, 'mode': mode})
            elif nxt == c:
                out['holds_on_request'] += 1
    out['rung_jump_by_mode'] = {m: {'max': max(v), 'counts': dict(sorted(Counter(v).items()))}
                                for m, v in jumps_by_mode.items()}
    jumps = [j for v in jumps_by_mode.values() for j in v]
    out['max_rung_jump'] = max(jumps) if jumps else None
    modes = [s['control_mode'] for s in segs]
    run = best = 0
    for m in modes:
        run = run + 1 if m == 'rotate' else 0
        best = max(best, run)
    out['control_modes'] = dict(Counter(modes))
    out['longest_rotation_run'] = best
    out['saturation_states'] = dict(Counter(s['saturation_state'] for s in segs))
    out['holds'] = sum(a == b for a, b in zip(cur, rungs) if a is not None)
    return out


def visit_state(segs):
    """Each cell's gen_visit_idx must count 0, 1, 2, ... across its visits
    (revisits continue the cell's state)."""
    seen: dict[str, list[int]] = {}
    prev = None
    revisits = 0
    for s in segs:
        cell = f"{s['genre']}{s['tier']}"
        v = s.get('gen_visit_idx')
        if v not in (None, ''):
            seen.setdefault(cell, []).append(int(float(v)))
        if prev is not None and cell != prev and cell in seen and len(seen[cell]) > 1:
            revisits += 1
        prev = cell
    broken = {c: v for c, v in seen.items() if v != list(range(len(v)))}
    return {'cells_with_visit_state': len(seen), 'revisits_after_other_cells': revisits,
            'max_visits_per_cell': max((len(v) for v in seen.values()), default=0),
            'visit_counter_breaks': broken}


def hr_validity(rows, segs, session: Path):
    out = {'segments_fresh_hr': sum(s['hr_is_fresh'] == 'True' for s in segs),
           'segments_stale_hr': sum(s['hr_is_fresh'] != 'True' for s in segs),
           'stale_hold_segments': sum(s['control_mode'] == 'stale_hold' for s in segs),
           'hr_n_fresh_per_segment': _stats([_f(s.get('hr_n_fresh')) for s in segs]),
           'hr_seg_sd_bpm': _stats([_f(s.get('hr_seg_sd_bpm')) for s in segs]),
           'hr_source': sorted({s['hr_source'] for s in segs})}
    polls = session / 'hr_polls.csv'
    if polls.exists():
        p = list(csv.DictReader(polls.open()))
        # accepted = the poll returned a fresh estimator reading (bpm alone also holds stale values)
        valid = [r for r in p if r.get('accepted') == 'True']
        out['hr_polls'] = {'n': len(p), 'accepted': len(valid), 'not_accepted': len(p) - len(valid),
                           'accepted_fraction': round(len(valid) / len(p), 4) if p else None,
                           'decision_polls_not_accepted': sum(r.get('kind') == 'decision' and r.get('accepted') != 'True'
                                                              for r in p)}
    hr = [_f(s['hr_bpm']) for s in segs]
    tgt = [_f(s['hr_target_bpm']) for s in segs]
    gov = [_f(s['governed_r_bpm']) for s in segs]
    raw_err = [abs(h - t) for h, t in zip(hr, tgt) if h is not None and t is not None]
    gov_err = [abs(h - g) for h, g in zip(hr, gov) if h is not None and g is not None]
    out['tracking_note'] = 'tracking of the reference only; not evidence that the music changed HR'
    out['mae_hr_vs_raw_target_bpm'] = round(float(np.mean(raw_err)), 3) if raw_err else None
    out['mae_hr_vs_governed_reference_bpm'] = round(float(np.mean(gov_err)), 3) if gov_err else None
    return out


def development(segs):
    sel = Counter(s.get('motif_selection') or 'none' for s in segs)
    return {'motif_selection': dict(sel),
            'fallback_segments': sel.get('previous', 0) + sel.get('unchanged', 0),
            'motif_errors': sum(bool(s.get('motif_error')) for s in segs),
            'gen_versions': dict(Counter(s.get('gen_version') for s in segs))}


def audio_stats(x):
    a = np.abs(x)
    return {'peak_dbfs': round(float(20 * np.log10(max(a.max(), 1e-12))), 3),
            'n_full_scale': int((a >= FULL_SCALE).sum()), 'n_over_0dbfs': int((a > 1.0).sum())}


def rebuild_audio(segs, stim_seed: int, sf2: str):
    from audition_v2 import SAMPLE_RATE, join_like_live, trim_like_live
    from composer.arrangement import SessionComposer
    from segment_renderer import SymbolicSegmentRenderer

    sc = SessionComposer(stim_seed, develop=True)
    r = SymbolicSegmentRenderer(sf2_path=sf2, sr=SAMPLE_RATE, session_seed=42)
    parts, tempos, per, mismatch = [], [], [], []
    for s in segs:
        pm, info = sc.compose(s['genre'], int(s['tier']), int(float(s['gen_visit_idx'])))
        for k_info, k_trace in (('base_seed', 'gen_base_seed'), ('motif_id', 'motif_id')):
            want, got = s.get(k_trace) or None, info.get(k_info)
            if want is not None and str(got) != str(want).split('.')[0] and str(got) != want:
                mismatch.append({'segment': int(s['segment_idx']), 'field': k_trace, 'trace': want, 'rebuilt': got})
        tempo = float(s['tempo_bpm'])
        a = trim_like_live(r._render_pm_to_audio(pm), tempo)
        parts.append(a)
        tempos.append(tempo)
        per.append({'segment': int(s['segment_idx']), 'cell': f"{s['genre']}{s['tier']}", **audio_stats(a)})
    joined, _, stats = join_like_live(parts, tempos)
    return joined, per, stats, mismatch, r.master_gain_db


def summarize(session: Path, render: bool, sf2: str) -> dict:
    rows, meta = load(session)
    segs = [r for r in rows if r['bar_idx_in_segment'] == '0']
    cells = [f"{s['genre']}{s['tier']}" for s in segs]
    q = [_f(s.get('queued_ahead_s')) for s in segs]
    out = {
        'session': str(session),
        'kind': meta.get('manifest.json', {}).get('kind') or 'live run_pilot_zero session',
        'condition': meta.get('summary.json', {}).get('condition'),
        'n_segments': len(segs),
        'minutes': round((_f(segs[-1]['session_time']) or 0) / 60, 2) if segs else 0,
        'plan_invariance_max_nunique': plan_invariance(rows),
        'timing': {'queued_ahead_s': _stats(q),
                   f'segments_queued_ahead_below_{LOW_HEADROOM_S}s': sum(x is not None and x < LOW_HEADROOM_S for x in q),
                   'segments_queued_ahead_le_0': sum(x is not None and x <= 0 for x in q),
                   'render_s': _stats([_f(s.get('render_s')) for s in segs]),
                   'planned_s': _stats([_f(s.get('planned_s')) for s in segs])},
        'cells': {'sequence': ' '.join(cells), 'distinct': len(set(cells)),
                  'genre_changes': sum(a['genre'] != b['genre'] for a, b in zip(segs, segs[1:])),
                  'rung_range': [min(int(s['rung']) for s in segs), max(int(s['rung']) for s in segs)]},
        'control': control(segs, initial_rung(meta)),
        'visit_state': visit_state(segs),
        'development': development(segs),
        'hr': hr_validity(rows, segs, session),
    }
    s = meta.get('summary.json', {})
    out['config'] = {k: s.get(k) for k in ('ladder_source', 'ear_order_sha256', 'energy_table_sha256',
                                           'rotation_band_u', 'rotation_no_repeat', 'master_gain_db',
                                           'crossfade_tail_scaled', 'generator') if k in s}
    if (session / 'session.wav').exists():
        import soundfile as sf
        x, _ = sf.read(session / 'session.wav', always_2d=True, dtype='float32')
        out['audio_session_wav'] = audio_stats(x)
    if render:
        gens = {s['generator'] for s in segs}
        if gens != {'v2c'} and not all(s.get('gen_visit_idx') for s in segs):
            out['audio_rebuilt'] = {'error': f'rebuild needs v2c segments, trace has {sorted(gens)}'}
        else:
            stim = int(float(segs[0]['gen_stim_seed']))
            joined, per, stats, mismatch, master = rebuild_audio(segs, stim, sf2)
            worst = max(per, key=lambda p: p['peak_dbfs'])
            out['audio_rebuilt'] = {'stim_seed': stim, 'master_gain_db_now': master,
                                    'master_gain_db_in_run': s.get('master_gain_db'),
                                    'composition_mismatches': mismatch, 'joined': audio_stats(joined),
                                    'mixer': stats, 'worst_segment': worst,
                                    'segments_with_full_scale': sum(p['n_full_scale'] > 0 for p in per)}
            if (session / 'session.wav').exists():
                import soundfile as sf
                x, _ = sf.read(session / 'session.wav', always_2d=True, dtype='float32')
                n = min(len(x), len(joined))
                out['audio_rebuilt']['vs_session_wav_max_abs_diff'] = float(np.abs(x[:n] - joined[:n]).max())
                out['audio_rebuilt']['length_frames'] = [len(x), len(joined)]
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('session')
    ap.add_argument('--render', action='store_true', help='rebuild the audio from the trace (v2c)')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    args = ap.parse_args(argv)
    session = Path(args.session)
    out = summarize(session, args.render, args.sf2)
    (session / 'session_summary.json').write_text(json.dumps(out, indent=1, default=str) + '\n')
    print(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    main()
