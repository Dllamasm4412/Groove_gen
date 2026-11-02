"""
v3 listening evaluation: renders the second GrooveGen v3 hip-hop listening
package (Tests A-E) for the developer's ears. Engineering material, not study
stimuli. Nothing here is used by the live runner, and nothing here changes a
generator: v3 comes from composer/v3 unchanged (HipHopV3Source, or its own
plan_segment/realize for Test D), v2c from session_generator.SessionSegmentSource
(develop=True), the live v2c path.

Tests (sample choices are fixed rules, made before anything was heard):
  A  five v3 compositions at level 3: seeds 101-105 as they came, the first
     three sections of each composition's form (about 1 min each)
  B  two whole v3 compositions at level 3 (8 sections, about 3 min): the first
     seed from 201 whose composition is boom-bap (209) and the first that is
     dark (204); the first package's long sample was soul
  C  the first package's C1 (seed 1, L2-L3-L4-L3) at its own constant tempo
     and at the tier tempos the live runner requires (87/90/93/90 BPM)
  D  one section held (A1's statement, form position 2) while only the level
     changes, L1-L5, and the same section at L3 five times (control)
  E  three blind v2c / v3 pairs at hip-hop tiers 3, 2 and 4: v3 at tier tempo
     (the runner-compatible policy), three segments each, the v3 file gain-
     matched to the v2c file's integrated loudness; X / Y assignment from a
     fixed hash; identities only in after_listening/E_answer_key.*

Rendering is the audition's: SymbolicSegmentRenderer (FluidSynth, gain 0.8,
master -2.5 dB), segments trimmed and joined as the live runner joins them;
features are the energy-table recipe (audition_v3.measure_segment). v3 is
calibrated with composer/v3/levels_<sf2 stem>.json, which must have been
measured on this exact soundfont file.

Usage (from groovegen_pilot/):
    python audition_v3.py --sf2 <sf2> --measure-levels       # once per soundfont
    python listening_eval_v3.py --sf2 <sf2> --zip
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import shutil
import subprocess
import sys
import time
import wave
import zipfile
from dataclasses import replace
from pathlib import Path
from statistics import fmean

import numpy as np
import pretty_midi

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audition_v2 as av2  # noqa: E402
import audition_v3 as a3  # noqa: E402
from music_features_measured import SR  # noqa: E402

PACKAGE = 'groovegen_v3_listening_evaluation'
BARS = 8
BLIND_SALT = 'groovegen-v3-listening-1'
MP3_KBPS = 192

FOLDERS = {'A': 'A_different_compositions', 'B': 'B_long_form', 'C': 'C_tempo', 'D': 'D_intensity',
           'E': 'E_blind_pairs'}

SAMPLES = (
    *(dict(id=f'A{i}', test='A', make='v3', seed=100 + i, levels=(3, 3, 3), tempo='composition')
      for i in range(1, 6)),
    dict(id='B1', test='B', make='v3', seed=209, levels=(3,) * 8, tempo='composition'),
    dict(id='B2', test='B', make='v3', seed=204, levels=(3,) * 8, tempo='composition'),
    dict(id='C1-constant', test='C', make='v3', seed=1, levels=(2, 3, 4, 3), tempo='composition'),
    dict(id='C1-tier', test='C', make='v3', seed=1, levels=(2, 3, 4, 3), tempo='tier'),
    dict(id='D-ramp', test='D', make='v3-held', seed=101, ordinal=1, levels=(1, 2, 3, 4, 5)),
    dict(id='D-steady', test='D', make='v3-held', seed=101, ordinal=1, levels=(3,) * 5),
)
PAIRS = (dict(id='E1', tier=3, seed=301), dict(id='E2', tier=2, seed=302), dict(id='E3', tier=4, seed=303))
E_SEGMENTS = 3


# =============================================================================
# Generation (generators unchanged; this only chooses what to ask them for)
# =============================================================================


def gen_v3(seed: int, levels, tempo: str, table: str) -> list[tuple]:
    """Consecutive segments of the stim seed's session, as the runner would get them."""
    from composer.v3.source import HipHopV3Source

    src = HipHopV3Source(seed, tempo_policy=tempo, levels_table=table)
    out = []
    for lv in levels:
        plan = src.peek(lv)[1]['plan']            # the plan of the segment next_segment commits
        pm, info = src.next_segment('hiphop', lv)
        out.append((pm, info, plan))
    return out


def gen_v3_held(seed: int, ordinal: int, levels, table: str) -> list[tuple]:
    """One section of the seed's first composition (form position `ordinal`)
    realised at each level in turn: harmony, hook, fills and form position stay,
    only the level's layers and dynamics change (plan_segment is level-invariant
    except for its layers)."""
    from composer.v3.hiphop import plan_segment, realize, segment_info
    from composer.v3.source import HipHopV3Source

    state = HipHopV3Source(seed, tempo_policy='composition', levels_table=table).current_state()
    held = replace(state, ordinal=ordinal)
    out = []
    for lv in levels:
        plan = plan_segment(held, lv)
        info = {**segment_info(plan), 'generator': 'v3', 'tempo_bpm': state.spec.tempo, 'stim_seed': seed,
                'base_seed': state.spec.seed, 'var_seed': plan.seed, 'mix_trim_db': state.spec.mix_trim_db,
                'tempo_policy': 'composition', 'levels_table': table, 'held_ordinal': ordinal}
        out.append((realize(plan), info, plan))
    return out


def gen_v2c(seed: int, tier: int, n: int) -> list[tuple]:
    from session_generator import SessionSegmentSource

    src = SessionSegmentSource(seed, develop=True)
    out = []
    for _ in range(n):
        pm, info = src.next_segment('hiphop', tier)
        out.append((pm, {'tier': tier, **info}, None))
    return out


def generate(sample: dict, table: str) -> list[tuple]:
    if sample['make'] == 'v3-held':
        return gen_v3_held(sample['seed'], sample['ordinal'], sample['levels'], table)
    return gen_v3(sample['seed'], sample['levels'], sample['tempo'], table)


def blind_assignments(pair_ids) -> dict[str, dict[str, str]]:
    """Which generator is X and which is Y in each pair: v3 is X in some pairs
    and Y in others (never the same side throughout, which would give it away);
    which of the mixed patterns is a fixed hash, not a choice."""
    n = len(pair_ids)
    patterns = [bits for bits in itertools.product((True, False), repeat=n) if 0 < sum(bits) < n]
    pick = patterns[int.from_bytes(hashlib.sha256(BLIND_SALT.encode()).digest()[:4], 'big') % len(patterns)]
    return {pid: {'X': 'v3' if v3x else 'v2c', 'Y': 'v2c' if v3x else 'v3'} for pid, v3x in zip(pair_ids, pick)}


# =============================================================================
# Rendering and measurement
# =============================================================================


def describe(info: dict) -> dict:
    if info.get('generator') == 'v3':
        keys = ('gen_version', 'composition_id', 'substyle', 'key', 'comp_tempo_bpm', 'swing', 'role', 'op',
                'fills', 'loop_a', 'loop_b', 'palette', 'bass_style', 'comp_style', 'form', 'cells', 'level',
                'mix_trim_db', 'levels_table', 'tempo_policy', 'held_ordinal')
        return {'generator': 'v3', **{k: info.get(k) for k in keys if k in info},
                'seeds': f"stim {info.get('stim_seed')} base {info['base_seed']} segment {info['var_seed']}"}
    return {'generator': 'v2c', 'gen_version': info.get('gen_version'), 'dev_version': info.get('dev_version'),
            'tier': info.get('tier'), 'role': f"block {info['block_idx']} pos {info['pos_in_block']}",
            'op': '+'.join(info.get('motif_ops') or []),
            'seeds': f"stim {info.get('stim_seed')} base {info['base_seed']} var {info['var_seed']}"}


def render(segments: list[tuple], renderer, scale: dict, wav: Path, midi_dir: Path, root: Path,
           match_lufs: float | None = None, midi_name: str | None = None) -> dict:
    """Render, join like the live runner, write the WAV and per-segment MIDI,
    measure. With match_lufs, a static gain brings the file to that integrated
    loudness (blind pairs only); both levels are recorded."""
    from composer.v3.checks import rule_violations

    midi_dir.mkdir(parents=True, exist_ok=True)
    midi_name = midi_name or wav.stem
    audios, tempos, rows = [], [], []
    t = 0.0
    for i, (pm, info, plan) in enumerate(segments):
        tempo = float(pm.get_tempo_changes()[1][0])
        audios.append(av2.trim_like_live(renderer._render_pm_to_audio(pm), tempo))
        tempos.append(tempo)
        mp = midi_dir / f'{midi_name}_seg{i + 1:02d}.mid'
        pm.write(str(mp))
        row = {'seg': i + 1, 'start_s': round(t, 3), 'midi': str(mp.relative_to(root)),
               'midi_sha256': a3.sha256(mp), **describe(info), **a3.measure_segment(renderer, pm, scale)}
        if plan is not None:
            row['rule_violations'] = rule_violations(pm, plan, tempo)
        rows.append(row)
        t += BARS * 240.0 / tempo
    joined, starts, stats = av2.join_like_live(audios, tempos)
    as_rendered = a3.whole_file_features(joined)
    gain_db = 0.0
    if match_lufs is not None:
        gain_db = round(match_lufs - as_rendered['lufs_integrated'], 3)
        joined = joined * np.float32(10 ** (gain_db / 20))
    wav.parent.mkdir(parents=True, exist_ok=True)
    av2._write_wav(wav, joined)
    comb = a3.combined_midi([s[0] for s in segments])
    comb_path = None
    if comb is not None:
        comb_path = midi_dir / f'{midi_name}.mid'
        comb.write(str(comb_path))
    presented = a3.whole_file_features(a3.read_wav(wav)[0])
    summary = {'wav': str(wav.relative_to(root)), 'wav_sha256': a3.sha256(wav),
               'midi_combined': str(comb_path.relative_to(root)) if comb_path else None,
               'segments': len(segments), 'tempo_bpm_per_segment': tempos,
               'expected_music_s': round(t, 3),
               'expected_file_s': round(t + av2.FADE_BARS * 240.0 / tempos[-1], 3),
               'segment_starts_s': [round(s / SR, 3) for s in starts], 'mixer': stats,
               'lufs_integrated_as_rendered': as_rendered['lufs_integrated'], 'presentation_gain_db': gain_db,
               **presented}
    for f in ('lufs', 'drum_rate', 'centroid_hz', 'flux', 'pulse_clarity', 'low_ratio', 'energy_u'):
        summary[f'mean_{f}'] = round(fmean(r[f] for r in rows), 4)
    return {'summary': summary, 'rows': rows, 'pms': [s[0] for s in segments],
            'plans': [s[2] for s in segments]}


def mp3_copy(wav: Path, mp3: Path) -> None:
    mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-map_metadata', '-1', '-codec:a',
                    'libmp3lame', '-b:a', f'{MP3_KBPS}k', str(mp3)], check=True)


# =============================================================================
# Verification
# =============================================================================


def _longest_quiet_s(x: np.ndarray, sr: int, floor_db: float = -60.0) -> float:
    win = int(0.01 * sr)
    n = x.shape[0] // win
    env = np.abs(x[:n * win]).max(axis=1).reshape(n, win).max(axis=1)
    quiet = env < 10 ** (floor_db / 20)
    best = run = 0
    for q in quiet:
        run = run + 1 if q else 0
        best = max(best, run)
    return best * 0.01


def verify_wav(path: Path, expected_s: float) -> dict:
    with wave.open(str(path)) as w:
        ch, width, sr, frames = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
    x, _ = a3.read_wav(path)
    dur = frames / sr
    checks = {'format_16bit_44k1_stereo': (ch, width, sr) == (2, 2, 44100),
              'duration_matches': abs(dur - expected_s) < 0.05,
              'finite': bool(np.isfinite(x).all()),
              'not_clipped': float(np.max(np.abs(x))) < 0.999,
              'not_silent': float(np.max(np.abs(x))) > 0.01}
    return {'ok': all(checks.values()), **checks, 'duration_s': round(dur, 3),
            'longest_quiet_s_below_-60dBFS': round(_longest_quiet_s(x, sr), 2)}


def verify_mp3(path: Path, wav_s: float) -> dict:
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                          str(path)], capture_output=True, text=True).stdout.strip()
    dur = float(out) if out else -1.0
    return {'ok': abs(dur - wav_s) < 0.15, 'duration_s': round(dur, 3)}


# =============================================================================
# Technical observations (supporting only; not listening)
# =============================================================================

KICKS = (35, 36)


def _tracks(pm, generator):
    bass = [i for i in pm.instruments if i.name in ('bass', 'Electric Bass')]
    if generator == 'v3':
        lead = [i for i in pm.instruments if i.name == 'hook']
    else:   # v2c: the 'Sampler' lead doubles the piano hook; sub-bass / pad Samplers sit lower
        samplers = [i for i in pm.instruments if i.name == 'Sampler' and i.notes]
        lead = sorted(samplers, key=lambda i: -fmean(n.pitch for n in i.notes))[:1]
    return bass, lead


def bass_kick_lock(pms, generator) -> dict:
    """Share of bass onsets within 30 ms of a kick, and of kicks with a bass onset."""
    b_hit = b_all = k_hit = k_all = 0
    for pm in pms:
        kicks = [n.start for i in pm.instruments if i.is_drum for n in i.notes if n.pitch in KICKS]
        bass = [n.start for i in _tracks(pm, generator)[0] for n in i.notes]
        b_all += len(bass)
        k_all += len(kicks)
        b_hit += sum(any(abs(b - k) < 0.03 for k in kicks) for b in bass)
        k_hit += sum(any(abs(b - k) < 0.03 for b in bass) for k in kicks)
    return {'bass_on_kick': round(b_hit / max(b_all, 1), 3), 'kicks_with_bass': round(k_hit / max(k_all, 1), 3)}


def bar_patterns(pms, generator) -> list:
    """Transposition-invariant lead-line pattern of every bar: (16th step,
    pitch relative to the bar's first note) of the top voice; None = no lead."""
    pats = []
    for pm in pms:
        step = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
        lead = _tracks(pm, generator)[1]
        top: dict[int, int] = {}
        for n in (n for i in lead for n in i.notes):
            k = int(round(n.start / step))
            top[k] = max(top.get(k, 0), n.pitch)
        for bar in range(BARS):
            notes = sorted((k - bar * 16, p) for k, p in top.items() if bar * 16 <= k < (bar + 1) * 16)
            pats.append(tuple((s, p - notes[0][1]) for s, p in notes) if notes else None)
    return pats


def repetition(pats) -> dict:
    sounding = [p for p in pats if p]
    seen, repeats = set(), 0
    for p in sounding:
        repeats += p in seen
        seen.add(p)
    return {'bars_with_lead': len(sounding), 'distinct_bar_patterns': len(seen),
            'bars_repeating_an_earlier_bar': round(repeats / max(len(sounding), 1), 3)}


def drum_density(pm) -> dict:
    tempo = float(pm.get_tempo_changes()[1][0])
    bar_s = 240.0 / tempo
    drums = [n for i in pm.instruments if i.is_drum for n in i.notes]
    onsets = sorted({round(n.start / 0.02) for n in drums})
    parts = {i.name: round(len(i.notes) / BARS, 1) for i in pm.instruments}
    return {'drum_notes_per_bar': round(len(drums) / BARS, 1), 'distinct_drum_onsets_per_bar':
            round(len(onsets) / BARS, 1), 'drum_sounds': sorted({n.pitch for n in drums}),
            'notes_per_bar_by_part': parts, 'bar_s': round(bar_s, 3)}


def energy_terms(row: dict, scale: dict) -> dict:
    span = scale['e_max'] - scale['e_min']
    return {f: round(w * (row[f] - scale['z'][f][0]) / scale['z'][f][1] / span, 3)
            for f, w in scale['weights'].items()}


def _segment_chroma(root: Path, s: dict) -> np.ndarray:
    bars = a3._bar_chroma(root / s['wav'], s['segment_starts_s'], s['tempo_bpm_per_segment'])
    return bars.reshape(-1, BARS, 12).mean(axis=1)


def _cos(a, b, transpose=True) -> float:
    a, b = a / (np.linalg.norm(a) + 1e-9), b / (np.linalg.norm(b) + 1e-9)
    return round(max(float(a @ np.roll(b, k)) for k in (range(12) if transpose else (0,))), 3)


def analyse(root: Path, results: dict, pair_results: dict, scale: dict) -> dict:
    from composer.v3.checks import identity_differences
    from composer.v3.source import HipHopV3Source

    S = {k: v['summary'] for k, v in results.items()}
    R = {k: v['rows'] for k, v in results.items()}
    out: dict = {'note': 'Computed from MIDI and rendered audio. Supporting evidence only; nothing here is a '
                 'listening result.'}

    # 1. do different seeds give different music? (Test A)
    a_ids = [s['id'] for s in SAMPLES if s['test'] == 'A']
    specs = {sid: HipHopV3Source(next(s['seed'] for s in SAMPLES if s['id'] == sid)).current_state().spec
             for sid in a_ids}
    chroma = {sid: a3._bar_chroma(root / S[sid]['wav'], S[sid]['segment_starts_s'],
                                  S[sid]['tempo_bpm_per_segment']) for sid in a_ids}
    drums = {sid: a3._drum_profile([root / r['midi'] for r in R[sid]]) for sid in a_ids}
    melody = {sid: a3._melody_ngrams([root / r['midi'] for r in R[sid]], 'v3') for sid in a_ids}
    pairs = []
    for i, x in enumerate(a_ids):
        for y in a_ids[i + 1:]:
            pairs.append({'pair': f'{x}-{y}', 'harmony_key_invariant': round(a3._key_invariant_similarity(
                chroma[x], chroma[y]), 3), 'drum_pattern': round(float(drums[x] @ drums[y]), 3),
                'melody_ngram_jaccard': round(len(melody[x] & melody[y]) / max(len(melody[x] | melody[y]), 1), 3),
                'identity_fields_that_differ': identity_differences(specs[x], specs[y])})
    v2c = {pid: next(r for r in pair_results[pid]['parts'] if r['generator'] == 'v2c') for pid in pair_results}
    v2c_pairs = []
    ids = list(v2c)
    for i, x in enumerate(ids):
        for y in ids[i + 1:]:
            cx = a3._bar_chroma(root / v2c[x]['summary']['wav'], v2c[x]['summary']['segment_starts_s'],
                                v2c[x]['summary']['tempo_bpm_per_segment'])
            cy = a3._bar_chroma(root / v2c[y]['summary']['wav'], v2c[y]['summary']['segment_starts_s'],
                                v2c[y]['summary']['tempo_bpm_per_segment'])
            mx = a3._melody_ngrams([root / r['midi'] for r in v2c[x]['rows']], 'v2c')
            my = a3._melody_ngrams([root / r['midi'] for r in v2c[y]['rows']], 'v2c')
            v2c_pairs.append({'pair': f'v2c seed {pair_results[x]["seed"]} (tier {pair_results[x]["tier"]}) - '
                              f'seed {pair_results[y]["seed"]} (tier {pair_results[y]["tier"]})',
                              'harmony_key_invariant': round(a3._key_invariant_similarity(cx, cy), 3),
                              'melody_ngram_jaccard': round(len(mx & my) / max(len(mx | my), 1), 3)})
    out['seed_differences'] = {'v3_test_A': pairs, 'v2c_reference_test_E': v2c_pairs}

    # 2. melodic repetition (bar-level lead patterns)
    rep = {sid: repetition(bar_patterns(results[sid]['pms'], 'v3')) for sid in a_ids + ['B1', 'B2']}
    for pid, pr in pair_results.items():
        for part in pr['parts']:
            rep[f"{pid} {part['generator']}"] = repetition(bar_patterns(part['pms'], part['generator']))
    out['melodic_repetition'] = rep

    # 3. drum density and parts by level (Test D ramp; v2c tiers from Test E)
    out['density_by_level'] = {
        'v3 D-ramp': [{'level': lv, **drum_density(pm)} for lv, pm in zip((1, 2, 3, 4, 5), results['D-ramp']['pms'])],
        'v2c (Test E, first segment)': [{'tier': pr['tier'], **drum_density(next(
            p for p in pr['parts'] if p['generator'] == 'v2c')['pms'][0])} for pr in pair_results.values()]}

    # 4. bass / drum coordination
    lock = {sid: bass_kick_lock(results[sid]['pms'], 'v3') for sid in results}
    for pid, pr in pair_results.items():
        for part in pr['parts']:
            lock[f"{pid} {part['generator']}"] = bass_kick_lock(part['pms'], part['generator'])
    out['bass_kick_lock'] = lock

    # 5. section changes in the long pieces (segment chroma, key-invariant off; same key)
    long = {}
    for sid in ('B1', 'B2'):
        ch = _segment_chroma(root, S[sid])
        roles = [r['role'] for r in R[sid]]
        long[sid] = {'roles': roles, 'consecutive_similarity': [_cos(ch[i], ch[i + 1], False) for i in range(len(ch) - 1)],
                     'similarity_to_statement': {f'{i + 1}:{roles[i]}': _cos(ch[1], ch[i], False)
                                                 for i in range(len(ch))},
                     'ops': [r.get('op') or '' for r in R[sid]]}
    out['section_changes'] = long

    # 6-7. identity at low levels, difference at high levels (Test D ramp)
    ramp, steady = results['D-ramp'], results['D-steady']
    ch = _segment_chroma(root, S['D-ramp'])
    hooks = [{(round(n.start, 2), n.pitch) for i in pm.instruments if i.name == 'hook' for n in i.notes}
             for pm in ramp['pms']]
    ref = hooks[2]
    out['levels_D_ramp'] = [{
        'level': lv, 'lufs': r['lufs'], 'drum_rate': r['drum_rate'], 'centroid_hz': round(r['centroid_hz']),
        'energy_u': r['energy_u'], 'energy_terms': energy_terms(r, scale),
        'parts': sorted(i.name for i in pm.instruments if i.notes),
        'hook_notes': len(h), 'hook_notes_shared_with_L3': round(len(h & ref) / max(len(ref), 1), 3),
        'chroma_similarity_to_L3': _cos(ch[k], ch[2], False)}
        for k, (lv, r, pm, h) in enumerate(zip((1, 2, 3, 4, 5), ramp['rows'], ramp['pms'], hooks))]
    out['levels_D_steady_identical_segments'] = len({r['midi_sha256'] for r in steady['rows']}) == 1

    # 8. tempo comparison (Test C): same notes?
    c, t = results['C1-constant']['pms'], results['C1-tier']['pms']

    def steps(pm):
        q = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
        return sorted((i.name, int(round(n.start / q)), n.pitch, n.velocity) for i in pm.instruments for n in i.notes)
    out['tempo_C'] = {
        'same_notes_per_segment': [steps(a) == steps(b) for a, b in zip(c, t)],
        'durations_s': {k: S[k]['duration_s'] for k in ('C1-constant', 'C1-tier')},
        'lufs_integrated': {k: S[k]['lufs_integrated'] for k in ('C1-constant', 'C1-tier')},
        'energy_u_per_segment': {k: [r['energy_u'] for r in R[k]] for k in ('C1-constant', 'C1-tier')},
        'drum_rate_per_segment': {k: [r['drum_rate'] for r in R[k]] for k in ('C1-constant', 'C1-tier')}}

    # rule checks over every v3 segment
    viol = [(sid, r['seg'], v) for sid, rr in R.items() for r in rr for v in r.get('rule_violations') or []]
    for pid, pr in pair_results.items():
        for part in pr['parts']:
            viol += [(pid, r['seg'], v) for r in part['rows'] for v in r.get('rule_violations') or []]
    out['rule_violations'] = {'v3_segments_checked': sum(len(rr) for rr in R.values()) + len(pair_results) * E_SEGMENTS,
                              'violations': viol}
    return out


# =============================================================================
# Documents
# =============================================================================


def _mmss(t: float) -> str:
    return f'{int(t // 60)}:{t % 60:04.1f}'


def readme(env: dict, results: dict, pair_results: dict, locked: bool, sf_label: str) -> str:
    S = {k: v['summary'] for k, v in results.items()}
    if locked:
        banner = (f"Rendered with the project soundfont **{env['soundfont']}** (sha256 matches the locked file), "
                  f"v3 calibrated with `levels_{env['levels_table']}.json` measured on it.")
    else:
        banner = (f"**PRELIMINARY: rendered with {env['soundfont']}, not Musyng Kite.** Musyng Kite was not "
                  'available in the environment that built this package. v2c and v3 use the same soundfont, so '
                  'the comparisons are fair to each other, but instrument timbre and balance will differ from the '
                  'live system: judge timbre and mix on the Musyng Kite render (see "Render with Musyng Kite" '
                  'below); composition, groove, development and intensity changes can be judged here.')
    lines = [
        f'# GrooveGen v3 listening evaluation ({sf_label})', '',
        banner, '',
        'Nobody has listened to these files yet: they were generated, rendered and checked by software only. '
        'The listening judgements are yours.', '',
        '## Listening order', '',
        '1. **E: blind pairs** first, before the other tests make the two generators\' sounds familiar.',
        '2. **A**, then **B** (first pass: do not open `after_listening/` yet), then **C**, then **D**.',
        '3. Fill in `feedback_form.md` (or `feedback_form.csv` and `feedback_pairs.csv`).',
        '4. Then open `after_listening/`: the E answer key, the section timelines of B, sample details, '
        'measurements and technical notes. Listen to B again with its timeline if useful.', '',
        'WAV files are the originals; `mp3/` has the same files as 192 kbps MP3 for convenience. Every file is '
        'at its rendered level (only the E pairs are loudness-matched; see the answer key), so keep the volume '
        'fixed within a test.', '',
        '## Test E: v2c against v3, blind', '',
        '| Pair | Files | Tier / tempo | Duration |', '|---|---|---|---|']
    for pid, pr in pair_results.items():
        d = pr['parts'][0]['summary']
        lines.append(f"| {pid} | `{FOLDERS['E']}/{pid}-X.wav`, `{pid}-Y.wav` | {pr['tier']} / "
                     f"{d['tempo_bpm_per_segment'][0]:g} BPM | {d['duration_s']:.0f} s each |")
    lines += [
        '', 'In each pair one file is the locked v2c generator and one is v3, at the same hip-hop tier, tempo, '
        'length (three 8-bar segments) and integrated loudness. Blinding is partial: if you recognise a '
        'generator by its instruments, note that too.', '',
        '- Which holds your interest longer? Which sounds more repetitive?',
        '- Groove: which makes you want to move? Which drums, bass and keys lock together better?',
        '- Melody and harmony: which varies more, and does the variation make sense?',
        '- Instrumental coherence: do the instruments sound like one band?',
        '- Overall, which would you rather hear for 15 minutes?', '',
        '## Test A: different compositions at the same intensity', '',
        '| File | Duration | Tempo |', '|---|---|---|']
    for s in SAMPLES:
        if s['test'] == 'A':
            lines.append(f"| `{FOLDERS['A']}/{s['id']}.wav` | {S[s['id']]['duration_s']:.0f} s | "
                         f"{S[s['id']]['tempo_bpm_per_segment'][0]:g} BPM |")
    lines += [
        '', 'Five v3 compositions at level 3 (seeds 101-105, taken as they came, not picked by ear). Each is the '
        'first three 8-bar sections of a longer piece, so a little over a minute: two sections would stop '
        'before the piece starts to develop.', '',
        '- Are these five different pieces, or one piece re-dressed? Which two sound most alike?',
        '- Does each sound like hip-hop? Which would you keep, which would you drop?',
        '- Is there a melodic idea you remember afterwards?',
        '- Drums: do the hi-hats feel busy, and does the groove feel laid-back or stiff?', '',
        '## Test B: long-term development', '',
        f"`{FOLDERS['B']}/B1.wav` ({_mmss(S['B1']['duration_s'])}) and `B2.wav` ({_mmss(S['B2']['duration_s'])}), "
        'two whole compositions at level 3.', '',
        '- Does it sound like one evolving piece, or a series of 8-bar loops?',
        '- Note the times where something new happens, where an earlier idea comes back, and where you got bored.',
        '- Do the transitions feel natural?', '',
        'The intended sections are in `after_listening/B_timelines.md`; read them after the first pass.', '',
        '## Test C: constant tempo against tier tempo', '',
        f"`{FOLDERS['C']}/C1-constant.wav` ({S['C1-constant']['duration_s']:.0f} s) and `C1-tier.wav` "
        f"({S['C1-tier']['duration_s']:.0f} s): the same composition, sections and notes, intensity L2 -> L3 -> "
        f"L4 -> L3 (one 8-bar segment each). C1-constant stays at the composition's "
        f"{S['C1-constant']['tempo_bpm_per_segment'][0]:g} BPM; C1-tier follows the tier tempos the live runner "
        f"requires ({'/'.join(f'{x:g}' for x in S['C1-tier']['tempo_bpm_per_segment'])} BPM), so it is also "
        'faster overall. This is the first package\'s C1.', '',
        '- Do the tempo steps in C1-tier feel natural, or like a jolt?',
        '- Which feels more like one coherent piece? Which conveys the intensity change better?', '',
        '## Test D: intensity without structural change', '',
        f"`{FOLDERS['D']}/D-ramp.wav` and `D-steady.wav`: one 8-bar section of A1's composition played five "
        'times. In D-ramp only the intensity level changes, one step per 8 bars: L1 -> L2 -> L3 -> L4 -> L5. '
        'D-steady is the same section at L3 all five times: a control with deliberately literal repetition, '
        'not how v3 normally plays.', '',
        '- Is each step audible? Which steps are too small or too big?',
        '- Does L1 still sound like the same piece? Is L5 more intense, or only busier?',
        '- Does the change feel like intensity, or like the piece moving on?', '',
        '## Feedback', '',
        '`feedback_form.md` has the questions and rating scales; `feedback_form.csv` (per sample) and '
        '`feedback_pairs.csv` (per comparison) are the same as spreadsheets. Timestamps of anything that sounds '
        'wrong are the most useful part.', '',
        '## Render with Musyng Kite (on the Mac)', '',
        'From `groovegen_pilot/` in a checkout of the v3 branch, with Musyng Kite at `../soundfonts/`:', '',
        '```bash', 'python audition_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --measure-levels', '```', '',
        '```bash', 'python listening_eval_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --zip', '```', '',
        'The first command measures v3\'s loudness calibration on Musyng Kite (once). The second renders this '
        'package with the same seeds and sections; only v3\'s mix trims (from the calibration) and the E '
        'loudness-match gains change. Full steps: `groovegen_pilot/composer/v3/NEXT_ITERATION.md` section 1.', '',
        '## Files', '',
        '- `A_...` to `E_...`: one WAV per sample (16-bit, 44.1 kHz stereo); per-segment and combined MIDI in '
        '`midi/` (not for E: the E MIDI reveals the generator and is in `after_listening/E_midi/`).',
        '- `mp3/`: listening copies.',
        '- `after_listening/`: `E_answer_key.md` / `.json`, `B_timelines.md`, `sample_details.md`, '
        '`manifest.json`, `segments.csv`, `verification.json`, `technical_notes.md`, `analysis.json`.', '',
        f"Generator commit {env['git_head'][:10]}, FluidSynth {env['fluidsynth']}, soundfont {env['soundfont']} "
        f"(sha256 {env['soundfont_sha256'][:16]}...).", '']
    return '\n'.join(lines)


FORM_CRITERIA = ('musical_quality', 'groove', 'distinctiveness', 'development', 'overall')
PAIR_CRITERIA = ('musical_interest', 'less_repetitive', 'groove', 'melodic_harmonic_variation',
                 'instrumental_coherence', 'overall_preference')


def feedback_files(out: Path, pair_ids) -> None:
    sample_ids = [s['id'] for s in SAMPLES] + [f'{p}-{xy}' for p in pair_ids for xy in 'XY']
    with open(out / 'feedback_form.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['sample', *[f'{c}_1to5' for c in FORM_CRITERIA], 'sounds_like_hiphop_1to5',
                    'timestamps_and_notes'])
        w.writerows([[sid] + [''] * (len(FORM_CRITERIA) + 2) for sid in sample_ids])
    with open(out / 'feedback_pairs.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['comparison', 'criterion', 'preferred', 'strength_1to3', 'notes'])
        for p in pair_ids:
            w.writerows([[p, c, 'X / Y / none', '', ''] for c in PAIR_CRITERIA])
        w.writerows([['C', c, 'constant / tier / none', '', ''] for c in
                     ('more_coherent', 'intensity_change_clearer', 'overall_preference')])
        w.writerow(['C', 'tier_tempo_steps_feel_natural', 'yes / no', '', ''])
        for step in ('L1-L2', 'L2-L3', 'L3-L4', 'L4-L5'):
            w.writerow(['D-ramp', f'step_{step}', 'too small / right / too big', '', ''])
        w.writerows([['D-ramp', 'L1_keeps_identity', '1-5', '', ''],
                     ['D-ramp', 'L5_more_intense_or_only_busier', 'intense / busier', '', '']])
    md = ['# Feedback form', '',
          'Scales: 1 = poor, 3 = acceptable, 5 = excellent. Leave blank what you cannot judge. Timestamps of '
          'anything that sounds wrong (a clash, a stiff fill, a jarring transition, a boring stretch) are the '
          'most useful input.', '',
          '## Per sample', '',
          '| Sample | Quality | Groove | Distinctive | Development | Overall | Sounds like hip-hop | Timestamps / notes |',
          '|---|---|---|---|---|---|---|---|']
    md += [f'| {sid} | | | | | | | |' for sid in sample_ids]
    md += ['', '## Comparisons', '',
           'E pairs: for each criterion write X, Y or none, and a strength (1 slight, 2 clear, 3 strong).', '',
           '| Pair | Interest | Less repetitive | Groove | Melodic/harmonic variation | Coherence | Overall |',
           '|---|---|---|---|---|---|---|']
    md += [f'| {p} | | | | | | |' for p in pair_ids]
    md += ['', 'C: which is more coherent, constant or tier? Which conveys the intensity change better? Do the '
           'tier-tempo steps feel natural?', '', '- ', '',
           'D-ramp: each step too small / right / too big? L1-L2: , L2-L3: , L3-L4: , L4-L5: . Does L1 keep the '
           'piece\'s identity (1-5)? Is L5 more intense or only busier?', '', '- ', '',
           '## Top three problems', '', '1. ', '2. ', '3. ', '',
           '## Rank A1-A5, best to worst, one reason each', '', '1. ', '']
    (out / 'feedback_form.md').write_text('\n'.join(md))


def timelines(results: dict, ids) -> str:
    lines = []
    for sid in ids:
        res = results[sid]
        s, rows = res['summary'], res['rows']
        r0 = rows[0]
        lines += [f'## {sid}', '']
        if r0['generator'] == 'v3':
            lines += [f"Composition `{r0['composition_id']}`: {r0['substyle']}, {r0['key']}, "
                      f"{r0['comp_tempo_bpm']:g} BPM, swing {r0['swing']}; loop A `{r0['loop_a']}`, loop B "
                      f"`{r0['loop_b']}`; instruments {r0['palette']} (GM programs); bass {r0['bass_style']}, "
                      f"keys {r0['comp_style']}; form {r0['form']}.", '']
        for r, t in zip(rows, s['segment_starts_s']):
            what = f"level L{r['level']}" if r['generator'] == 'v3' else f"tier {r['tier']}"
            dev = f", development `{r['op']}`" if r.get('op') else ''
            fills = f", fills {r['fills']}" if r.get('fills') else ''
            lines.append(f"- {_mmss(t)} segment {r['seg']} ({what}, {r['tempo_bpm']:g} BPM): role {r['role']}"
                         f"{dev}{fills}. LUFS {r['lufs']:.1f}, drums {r['drum_rate']:.2f}/s, "
                         f"centroid {r['centroid_hz']:.0f} Hz, u {r['energy_u']:.2f}")
        lines += ['', f"File: {s['duration_s']:.1f} s, integrated {s['lufs_integrated']:.1f} LUFS, peak "
                  f"{s['peak_dbfs']:.1f} dBFS.", '']
    return '\n'.join(lines)


ROLE_GLOSS = ('Roles: S1 opening (groove, the hook enters at bar 5), S statement, V / V2 variation of the hook, '
              'C contrast (second chord loop, the answer phrase on another instrument), C2 contrast continued '
              '(back towards the first loop), R / R2 return of the statement (R2 closes the piece).')


def technical_notes(an: dict) -> str:
    L = ['# Technical notes (supporting only)', '', an['note'], '',
         '## Do different seeds give different music? (Test A, v3)', '',
         '| Pair | Harmony (key-invariant chroma) | Drum pattern | Melody n-gram overlap | Identity fields that differ |',
         '|---|---|---|---|---|']
    L += [f"| {p['pair']} | {p['harmony_key_invariant']} | {p['drum_pattern']} | {p['melody_ngram_jaccard']} | "
          f"{', '.join(p['identity_fields_that_differ'])} |" for p in an['seed_differences']['v3_test_A']]
    L += ['', 'v2c reference (Test E v2c files, different seeds and tiers):', '']
    L += [f"- {p['pair']}: harmony {p['harmony_key_invariant']}, melody n-gram overlap {p['melody_ngram_jaccard']}"
          for p in an['seed_differences']['v2c_reference_test_E']]
    L += ['', '## Melodic repetition (bar-level lead patterns, transposition-invariant)', '',
          '| Sample | Bars with lead | Distinct bar patterns | Bars repeating an earlier bar |', '|---|---|---|---|']
    L += [f"| {k} | {v['bars_with_lead']} | {v['distinct_bar_patterns']} | {v['bars_repeating_an_earlier_bar']} |"
          for k, v in an['melodic_repetition'].items()]
    L += ['', '## Drum density by level', '',
          '| Source | Level / tier | Drum notes per bar | Distinct drum onsets per bar | Drum sounds |',
          '|---|---|---|---|---|']
    for k, rows in an['density_by_level'].items():
        for r in rows:
            L.append(f"| {k} | {r.get('level', r.get('tier'))} | {r['drum_notes_per_bar']} | "
                     f"{r['distinct_drum_onsets_per_bar']} | {r['drum_sounds']} |")
    L += ['', '## Bass and kick', '', '| Sample | Bass onsets on a kick | Kicks with a bass onset |', '|---|---|---|']
    L += [f"| {k} | {v['bass_on_kick']} | {v['kicks_with_bass']} |" for k, v in an['bass_kick_lock'].items()]
    L += ['', '## Section changes in the long pieces (segment chroma cosine, same key)', '', ROLE_GLOSS, '']
    for sid, v in an['section_changes'].items():
        L += [f"- {sid} roles {'-'.join(v['roles'])}; consecutive similarity {v['consecutive_similarity']}; "
              f"similarity to the statement {v['similarity_to_statement']}; developments {v['ops']}"]
    L += ['', '## Intensity levels with the section held (Test D ramp)', '',
          '| Level | LUFS | Drums/s | Centroid Hz | u | u terms (lufs, drums, tempo, centroid, flux) | Parts | '
          'Hook notes | Hook shared with L3 | Chroma vs L3 |', '|---|---|---|---|---|---|---|---|---|---|']
    for r in an['levels_D_ramp']:
        t = r['energy_terms']
        L.append(f"| L{r['level']} | {r['lufs']:.1f} | {r['drum_rate']:.2f} | {r['centroid_hz']} | "
                 f"{r['energy_u']:.3f} | {', '.join(str(v) for v in t.values())} | {', '.join(r['parts'])} | "
                 f"{r['hook_notes']} | {r['hook_notes_shared_with_L3']} | {r['chroma_similarity_to_L3']} |")
    L += ['', f"D-steady segments byte-identical: {an['levels_D_steady_identical_segments']}.", '',
          '## Tempo (Test C)', '', f"```\n{json.dumps(an['tempo_C'], indent=1)}\n```", '',
          '## Rule checks', '',
          f"{an['rule_violations']['v3_segments_checked']} v3 segments checked, "
          f"{len(an['rule_violations']['violations'])} violations: {an['rule_violations']['violations']}", '']
    return '\n'.join(L)


# =============================================================================
# Run
# =============================================================================


def run(sf2: Path, out: Path | None, levels: str | None, make_zip: bool, only: set | None = None) -> Path:
    table = a3.levels_table_for(sf2, levels)
    env = a3.environment(sf2, table)
    if levels is None and env.get('levels_table_soundfont_sha256') != env['soundfont_sha256']:
        raise SystemExit(f'levels_{table}.json was measured on a different file than {sf2} (sha256 differs). '
                         f'Re-measure: python audition_v3.py --sf2 {sf2} --measure-levels')
    locked = env['soundfont_sha256'] == a3.LOCKED_SF2_SHA256
    sf_label = sf2.stem + ('' if locked else '_PRELIMINARY')
    out = out or HERE.parent / f'{PACKAGE}_{sf_label}'
    if out.exists():
        shutil.rmtree(out)
    after = out / 'after_listening'
    after.mkdir(parents=True)
    renderer = a3.SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)
    scale = a3.energy_scale()

    results: dict = {}
    for s in SAMPLES:
        if only and s['test'] not in only:
            continue
        folder = out / FOLDERS[s['test']]
        res = render(generate(s, table), renderer, scale, folder / f"{s['id']}.wav", folder / 'midi' / s['id'], out)
        res['summary'].update({k: s[k] for k in ('id', 'test', 'make', 'seed', 'levels')},
                              tempo_policy=s.get('tempo', 'composition'))
        results[s['id']] = res
        print(f"{s['id']}: {res['summary']['duration_s']:.1f}s LUFS {res['summary']['lufs_integrated']:.1f} "
              f"drums {res['summary']['mean_drum_rate']:.2f}/s u {res['summary']['mean_energy_u']:.2f}", flush=True)

    pair_results: dict = {}
    assignments = blind_assignments([p['id'] for p in PAIRS])
    for p in PAIRS if not only or 'E' in only else ():
        folder = out / FOLDERS['E']
        tmp = after / 'E_midi' / p['id']
        v2 = render(gen_v2c(p['seed'], p['tier'], E_SEGMENTS), renderer, scale, folder / f"{p['id']}-tmp-a.wav",
                    tmp / 'v2c', out, midi_name=f"{p['id']}_v2c")
        v3 = render(gen_v3(p['seed'], (p['tier'],) * E_SEGMENTS, 'tier', table), renderer, scale,
                    folder / f"{p['id']}-tmp-b.wav", tmp / 'v3', out,
                    match_lufs=v2['summary']['lufs_integrated'], midi_name=f"{p['id']}_v3")
        assign = assignments[p['id']]
        parts = []
        for label, gen in assign.items():
            res = v3 if gen == 'v3' else v2
            final = folder / f"{p['id']}-{label}.wav"
            (out / res['summary']['wav']).rename(final)
            res['summary']['wav'] = str(final.relative_to(out))
            res['summary']['wav_sha256'] = a3.sha256(final)
            res.update(generator=gen, label=label)
            parts.append(res)
        pair_results[p['id']] = {**p, 'assignment': assign, 'parts': parts}
        print(f"{p['id']}: X={assign['X']} Y={assign['Y']} (v3 gain {v3['summary']['presentation_gain_db']:+.2f} dB)",
              flush=True)

    # MP3 copies and verification
    verification = {}
    entries = [(k, r['summary']) for k, r in results.items()]
    entries += [(f"{pid}-{part['label']}", part['summary']) for pid, pr in pair_results.items() for part in pr['parts']]
    for name, s in entries:
        wav = out / s['wav']
        mp3 = out / 'mp3' / Path(s['wav']).with_suffix('.mp3')
        mp3_copy(wav, mp3)
        s['mp3'] = str(mp3.relative_to(out))
        v = verify_wav(wav, s['expected_file_s'])
        v['mp3'] = verify_mp3(mp3, v['duration_s'])
        verification[name] = v
    (after / 'verification.json').write_text(json.dumps(verification, indent=1))
    bad = [k for k, v in verification.items() if not (v['ok'] and v['mp3']['ok'])]

    # documents
    analysis = analyse(out, results, pair_results, scale) if not only else {}
    clean = lambda r: {k: v for k, v in r.items() if k not in ('pms', 'plans')}  # noqa: E731
    manifest = {'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'environment': env, 'soundfont_is_locked_file': locked,
                'energy_scale': {'source': a3.ENERGY_TABLE.name, 'e_min': scale['e_min'], 'e_max': scale['e_max']},
                'selection_rules': __doc__.split('Tests (')[1].split('Rendering is')[0].strip(),
                'samples': {k: {'summary': r['summary'], 'segments': r['rows']} for k, r in results.items()},
                'blind_pairs': {pid: {'tier': pr['tier'], 'files': [part['summary']['wav'] for part in pr['parts']],
                                      'see': 'E_answer_key.json'} for pid, pr in pair_results.items()},
                'verification_failures': bad}
    (after / 'manifest.json').write_text(json.dumps(manifest, indent=1, default=str))
    key = {pid: {'tier': pr['tier'], 'seed': pr['seed'], 'assignment': pr['assignment'],
                 'blind_rule': f'mixed X/Y patterns over the pairs, pattern index = first 4 bytes of '
                               f'sha256("{BLIND_SALT}") mod the number of patterns',
                 'parts': [{'label': part['label'], 'generator': part['generator'], **clean(part)} for part in pr['parts']]}
           for pid, pr in pair_results.items()}
    (after / 'E_answer_key.json').write_text(json.dumps(key, indent=1, default=str))
    ak = ['# Test E answer key', '', 'Open after rating the pairs.', '',
          '| Pair | Tier | X | Y | v3 presentation gain | Matched |', '|---|---|---|---|---|---|']
    for pid, pr in pair_results.items():
        v3s = next(p for p in pr['parts'] if p['generator'] == 'v3')['summary']
        v2s = next(p for p in pr['parts'] if p['generator'] == 'v2c')['summary']
        ak.append(f"| {pid} | {pr['tier']} | {pr['assignment']['X']} | {pr['assignment']['Y']} | "
                  f"{v3s['presentation_gain_db']:+.2f} dB | {v3s['lufs_integrated']:.2f} / {v2s['lufs_integrated']:.2f} "
                  f"LUFS (v3 / v2c), {v3s['duration_s']:.1f} / {v2s['duration_s']:.1f} s |")
    ak += ['', '**Matched:** hip-hop tier and intended intensity, tempo (both at the tier tempo; v3 uses the '
           'runner-compatible tier tempo policy), length (three 8-bar segments), soundfont and render settings, '
           'integrated loudness (static gain on the v3 file only; the v2c file is as rendered).', '',
           '**Not matched:** musical content and mechanism (v2c develops a fixed cell motif; v3 composes a piece '
           'with sections), instruments (v2c piano, electric bass, piano lead; v3 a palette per sub-style), '
           'brightness (v3 is darker), sub-style, and drum activity at low tiers (see the measurements below). '
           'The same seed number does not mean related music.', '']
    for pid, pr in pair_results.items():
        ak += [f'## {pid}', '']
        for part in pr['parts']:
            s = part['summary']
            ak.append(f"- {part['label']} = {part['generator']}: {s['wav']}, LUFS {s['lufs_integrated']:.2f} "
                      f"(as rendered {s['lufs_integrated_as_rendered']:.2f}), drums {s['mean_drum_rate']:.2f}/s, "
                      f"centroid {s['mean_centroid_hz']:.0f} Hz, u {s['mean_energy_u']:.2f}, MIDI in "
                      f"`after_listening/E_midi/{pid}/{part['generator']}/`")
        ak.append('')
    ak.append(timelines({f"{pid} {p['label']} ({p['generator']})": p for pid, pr in pair_results.items()
                         for p in pr['parts']}, [f"{pid} {p['label']} ({p['generator']})"
                                                 for pid, pr in pair_results.items() for p in pr['parts']]))
    (after / 'E_answer_key.md').write_text('\n'.join(ak))
    b_ids = [k for k in results if k.startswith('B')]
    (after / 'B_timelines.md').write_text('# Test B timelines (read after the first listening pass)\n\n'
                                          + ROLE_GLOSS + '\n\n' + timelines(results, b_ids))
    other = [k for k in results if not k.startswith('B')]
    (after / 'sample_details.md').write_text('# Sample details (Tests A, C, D)\n\n' + ROLE_GLOSS + '\n\n'
                                             + timelines(results, other))
    rows = [{'sample': k, **{kk: vv for kk, vv in r.items() if kk != 'rule_violations'}}
            for k, res in results.items() for r in res['rows']]
    with open(after / 'segments.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader()
        w.writerows(rows)
    if analysis:
        (after / 'analysis.json').write_text(json.dumps(analysis, indent=1, default=str))
        (after / 'technical_notes.md').write_text(technical_notes(analysis))
    (after / 'README.md').write_text('# After listening\n\nAnswer key, timelines, measurements and technical notes. '
                                     'Open after the first listening pass.\n')
    feedback_files(out, list(pair_results))
    (out / 'README.md').write_text(readme(env, results, pair_results, locked, sf_label))
    print('verification failures:', bad or 'none', flush=True)

    if make_zip:
        full = out.parent / f'{out.name}.zip'
        listen = out.parent / f'{out.name}_mp3.zip'
        with zipfile.ZipFile(full, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():
                    z.write(p, Path(out.name) / p.relative_to(out))
        with zipfile.ZipFile(listen, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob('*')):
                rel = p.relative_to(out)
                if p.is_file() and (rel.parts[0] in ('mp3', 'after_listening') or len(rel.parts) == 1):
                    z.write(p, Path(out.name) / rel)
        for zp in (full, listen):
            with zipfile.ZipFile(zp) as z:
                assert z.testzip() is None, zp
            print('zip', zp, f'{zp.stat().st_size / 1e6:.1f} MB', flush=True)
    if bad:
        raise SystemExit(f'verification failed: {bad}')
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--sf2', required=True, type=Path)
    p.add_argument('--out', type=Path, default=None,
                   help=f'default: ../{PACKAGE}_<soundfont>[_PRELIMINARY] next to groovegen_pilot/')
    p.add_argument('--levels', default=None, help='v3 loudness table (default: the one measured on --sf2)')
    p.add_argument('--zip', action='store_true', help='also write <out>.zip (everything) and <out>_mp3.zip')
    p.add_argument('--only', default=None, help='comma-separated test letters (development only; no analysis)')
    args = p.parse_args(argv)
    run(args.sf2, args.out, args.levels, args.zip, set(args.only.split(',')) if args.only else None)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
