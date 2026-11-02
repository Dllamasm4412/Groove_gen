"""
Candidate 27-excerpt corpus (GrooveGen v3) for the Qualtrics study "Perceived
Danceability and Calming Quality of Computer-Generated Music" (IRB 26-0684).

A separately versioned CANDIDATE set. It never writes to experiments/music_rating
(the original study's frozen stimuli, manifest and Qualtrics files are only
read) and it never touches the live survey.

The 27 conditions are the original study's: the 27 main stimuli of
experiments/music_rating/stimuli/manifest.json (one per live ladder cell,
genre x tier). For each condition this script

  1. regenerates the original condition's full 8-bar v2c segment (stim seed 1,
     visit 0) and checks its MIDI hash against the frozen manifest, so the
     original condition material is reproduced exactly;
  2. generates v3 candidates (deterministic seeds; hip-hop from the approved v3
     hip-hop generator, the six other genres from composer/v3/genres.py) at the
     condition's genre, tier and tempo;
  3. screens candidates in seed order on technical criteria only (rule checks,
     no clipping after loudness matching, no internal silence, duration, not a
     near-duplicate of an excerpt already selected) and keeps the FIRST that
     passes; nothing about danceability or calmness is used to select;
  4. renders it like the original stimuli (SymbolicSegmentRenderer.render_pm:
     FluidSynth, gain 0.8, master -2.5 dB), cut to 8 bars plus a quarter-bar
     equal-power release fade (the live tail_out), with a 3 ms fade-in;
  5. matches its integrated loudness to the original condition's 8-bar v2c
     segment rendered the same way on the same soundfont (loudness is part of
     the original configurations; the locked peak limiter is applied only if a
     matched excerpt would exceed -1 dBFS, and is recorded);
  6. measures the delivered audio and the MIDI, and writes the package.

Usage (repository root):
    python experiments/qualtrics_v3_candidate/build_candidate.py build --sf2 <sf2> --zip
    # on the Mac, with the same MIDI as a preliminary package (no re-screening):
    python experiments/qualtrics_v3_candidate/build_candidate.py build --sf2 soundfonts/Musyng_Kite.sf2 \\
        --selection <preliminary package>/E_analysis/stimulus_manifest.json --zip
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import time
import wave
import zipfile
from pathlib import Path
from statistics import fmean, median

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PILOT = REPO / 'groovegen_pilot'
for p in (PILOT, REPO / 'groovegen_project' / 'groovegen', HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import audition_v3 as a3  # noqa: E402
from music_features_measured import SR, audio_features  # noqa: E402

ORIGINAL_MANIFEST = REPO / 'experiments' / 'music_rating' / 'stimuli' / 'manifest.json'
ENERGY_TABLE = PILOT / 'energy_table_v1.json'
CORPUS_VERSION = 'qualtrics-27-candidate-v3.0'
SEED_SALT = 'qualtrics-27-v3-candidate-1'
ID_SALT = 'qualtrics-27-v3-ids-1'
N_CANDIDATES = 4
CLIP_BARS = 8
FADE_BARS = 0.25
FADE_IN_S = 0.003
PREVIEW_TARGET_S = 10.0
PEAK_CEILING_DBFS = -1.0
MAX_INTERNAL_QUIET_S = 0.5
NEAR_DUP_MELODY = 0.5
PRACTICE = (('practice', 'lofi:2'), ('practice', 'pop:4'), ('volume', 'pop:3'))   # the original study's cells
MP3_KBPS = 192
LOCKED_SF2_SHA256 = a3.LOCKED_SF2_SHA256


def H(*parts) -> int:
    return int.from_bytes(hashlib.sha256('|'.join(map(str, parts)).encode()).digest()[:4], 'big')


def sha256(path: Path) -> str:
    return a3.sha256(path)


# =============================================================================
# Conditions (read-only from the original study)
# =============================================================================


def load_conditions() -> tuple[list[dict], dict]:
    m = json.loads(ORIGINAL_MANIFEST.read_text())
    main = sorted((s for s in m['stimuli'] if s['kind'] == 'main'), key=lambda s: s['rung'])
    assert len(main) == 27, len(main)
    et = json.loads(ENERGY_TABLE.read_text())['cells']
    conds = []
    for s in main:
        e = et[s['cell']]
        conds.append({
            'condition_id': s['cell'], 'genre': s['genre'], 'tier': s['tier'], 'ladder_rung': s['rung'],
            'ladder_u': s['ladder_u'], 'tempo_bpm': s['bpm'], 'original_stimulus_id': s['stimulus_id'],
            'original_clip_bars': s['n_bars'], 'original_clip_duration_s': s['duration_s'],
            'original_clip_lufs_musyng': s['lufs'], 'original_gen_version': s['gen_version'],
            'original_segment_midi_sha256': s['segment_midi_sha256'],
            'table_lufs_musyng': e['lufs'], 'table_drum_rate': e['drum_rate'], 'table_centroid_hz': e['centroid_hz'],
            'table_flux': e['flux'], 'table_pulse_clarity': e['pulse_clarity'], 'table_note_rate': e['note_rate'],
            'table_drum_hats_rate': e['drum_hats_rate'], 'table_drum_backbeat_rate': e['drum_backbeat_rate'],
        })
    return conds, {'source': str(ORIGINAL_MANIFEST.relative_to(REPO)),
                   'sha256': hashlib.sha256(ORIGINAL_MANIFEST.read_bytes()).hexdigest(),
                   'built_at': m.get('built_at'), 'source_commit': m['provenance']['source_commit']}


def tier_density(genre: str, tier: int) -> float:
    from segment_renderer import RUNG_TIER_CAP, TIER_TO_DENSITY

    return TIER_TO_DENSITY[max(1, min(int(tier), RUNG_TIER_CAP.get(genre, 5)))]


# =============================================================================
# Generation
# =============================================================================


def v2c_segment(genre: str, tier: int, stim_seed: int = 1):
    from session_generator import SessionSegmentSource

    pm, info = SessionSegmentSource(stim_seed, develop=True).next_segment(genre, tier)
    return pm, info


def v3_candidate(genre: str, tier: int, k: int):
    from composer.v3.genres import compose_excerpt

    seed = H(SEED_SALT, genre, tier, k)
    pm, info, spec = compose_excerpt(genre, tier, seed)
    return seed, pm, info, spec


def v3_rules(genre: str, tier: int, pm, spec) -> list[str]:
    if genre == 'hiphop':
        from composer.v3.checks import rule_violations

        return rule_violations(pm, spec, float(pm.get_tempo_changes()[1][0]))
    from composer.v3.genres import rule_violations

    return rule_violations(pm, spec, tier)


# =============================================================================
# Audio
# =============================================================================


def bar_frames(tempo: float) -> int:
    from crossfade import bar_duration_frames

    return bar_duration_frames(tempo, 4, SR)


def finish(raw: np.ndarray, tempo: float, n_bars: int) -> np.ndarray:
    """The bars plus a quarter bar of release with the live tail_out
    equal-power fade, and a 3 ms raised-cosine fade-in (no click at the start)."""
    from crossfade import _equal_power_gains

    bar = bar_frames(tempo)
    fade = int(round(bar * FADE_BARS))
    clip = raw[:n_bars * bar + fade].astype(np.float32, copy=True)
    fade = min(fade, clip.shape[0])
    clip[clip.shape[0] - fade:] *= _equal_power_gains(fade)[0][:, None]
    n_in = int(FADE_IN_S * SR)
    clip[:n_in] *= (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n_in)))[:, None].astype(np.float32)
    return clip


def lufs(x: np.ndarray) -> float:
    import pyloudnorm as pyln

    return float(pyln.Meter(SR).integrated_loudness(np.asarray(x, np.float64)))


def peak_dbfs(x: np.ndarray) -> float:
    return float(20 * np.log10(max(float(np.max(np.abs(x))), 1e-12)))


def match_level(clip: np.ndarray, target: float) -> tuple[np.ndarray, dict]:
    from segment_renderer import limit_peaks

    before = lufs(clip)
    gain = target - before
    out = (clip * np.float32(10 ** (gain / 20))).astype(np.float32)
    limited = peak_dbfs(out) > PEAK_CEILING_DBFS
    if limited:
        out = limit_peaks(out, SR, PEAK_CEILING_DBFS)
    return out, {'lufs_before_match': round(before, 3), 'match_gain_db': round(gain, 3), 'limiter_applied': limited,
                 'lufs_after_match': round(lufs(out), 3)}


def longest_internal_quiet_s(x: np.ndarray, tempo: float, floor_db: float = -60.0) -> float:
    """Longest run below floor_db inside the music (the final release excluded)."""
    end = CLIP_BARS * bar_frames(tempo)
    win = int(0.01 * SR)
    seg = x[:end]
    n = seg.shape[0] // win
    env = np.abs(seg[:n * win]).max(axis=1).reshape(n, win).max(axis=1)
    best = run = 0
    for q in env < 10 ** (floor_db / 20):
        run = run + 1 if q else 0
        best = max(best, run)
    return best * 0.01


def write_wav(path: Path, audio: np.ndarray) -> None:
    from segment_renderer import _write_wav

    path.parent.mkdir(parents=True, exist_ok=True)
    _write_wav(path, audio, SR)


def read_wav(path: Path) -> np.ndarray:
    return a3.read_wav(path)[0]


def mp3(wav: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(wav), '-map_metadata', '-1', '-id3v2_version', '0',
                    '-write_id3v1', '0', '-codec:a', 'libmp3lame', '-b:a', f'{MP3_KBPS}k', '-ar', str(SR),
                    str(out)], check=True)


def probe_s(path: Path) -> float:
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0',
                          str(path)], capture_output=True, text=True).stdout.strip()
    return float(out) if out else -1.0


# =============================================================================
# Measurement
# =============================================================================

KICKS, SNARES, HATS = (35, 36), (37, 38, 39, 40), (42, 44, 46)


def midi_rhythm(pm, tempo: float) -> dict:
    """Rhythm features from the MIDI (8 bars). offbeat_index: mean metrical
    depth of kick, snare and bass onsets (0 on a beat, 1 on an off-beat 8th,
    2 on a 16th); a simple syncopation measure, not the corpus's LHL index."""
    step = 60.0 / tempo / 4
    drums = [n for i in pm.instruments if i.is_drum for n in i.notes]
    bass_names = ('bass', 'Electric Bass', 'piano_lh')
    bass = [n for i in pm.instruments if not i.is_drum and (i.name in bass_names or i.program in (32, 33, 34, 38, 39))
            for n in i.notes]
    dur = CLIP_BARS * 4 * 60.0 / tempo
    onsets = sorted({round(n.start / 0.02) for n in drums})

    def depth(t):
        k = int(round(t / step)) % 16
        return 0 if k % 4 == 0 else 1 if k % 2 == 0 else 2
    core = [n.start for n in drums if n.pitch in KICKS + SNARES] + [n.start for n in bass]
    kicks = [n.start for n in drums if n.pitch in KICKS]
    lock = (sum(any(abs(b.start - k) < 0.03 for k in kicks) for b in bass) / len(bass)) if bass and kicks else None
    return {'drum_onsets_per_s': round(len(onsets) / dur, 3), 'drum_notes_per_bar': round(len(drums) / CLIP_BARS, 2),
            'drum_sounds': len({n.pitch for n in drums}), 'hat_notes_per_bar': round(sum(n.pitch in HATS for n in drums) / CLIP_BARS, 2),
            'bass_notes_per_bar': round(len(bass) / CLIP_BARS, 2), 'bass_on_kick_share': None if lock is None else round(lock, 3),
            'offbeat_index': round(fmean(depth(t) for t in core), 3) if core else None,
            'parts': len([i for i in pm.instruments if i.notes]),
            'notes_per_s': round(sum(len(i.notes) for i in pm.instruments) / dur, 3)}


def audio_measures(x: np.ndarray, path: Path, scale: dict, drum_rate: float, tempo: float) -> dict:
    """Delivered-audio features and the composite energy score with the
    delivered loudness (LUFS + 2.5 dB = the table's reference level, which
    excludes the -2.5 dB master)."""
    import librosa

    f = audio_features(x)
    mono = np.asarray(x, np.float32).mean(axis=1)
    est = float(np.atleast_1d(librosa.beat.beat_track(y=mono, sr=SR)[0])[0])
    feat = {'tempo_bpm': tempo, 'lufs': f['lufs'] + 2.5, 'drum_rate': drum_rate, 'centroid_hz': f['centroid_hz'],
            'flux': f['flux']}
    e, u = a3.energy_u(feat, scale)
    corpus = {}
    try:
        from profile_from_songs import extract_features

        cf = extract_features(str(path), sr=22050, duration=None)
        corpus = {f'corpus_{k}': round(float(cf[k]), 4) for k in
                  ('tempo_final', 'onset_density', 'plp_mean', 'beat_consistency', 'hpss_percussive_ratio',
                   'low_band_energy_ratio', 'spectral_centroid_mean') if k in cf}
    except Exception as exc:   # the corpus-named features are supplementary
        corpus = {'corpus_features_error': repr(exc)[:120]}
    return {'lufs_integrated': round(f['lufs'], 3), 'peak_dbfs': round(f['peak_dbfs'], 3),
            'centroid_hz': round(f['centroid_hz'], 1), 'flux': round(f['flux'], 4),
            'pulse_clarity': round(f['pulse_clarity'], 4), 'low_ratio': round(f['low_ratio'], 4),
            'tempo_estimated_bpm': round(est, 2), 'energy_e_delivered': round(e, 4), 'energy_u_delivered': round(u, 4),
            **corpus}


# =============================================================================
# Screening and selection
# =============================================================================


def lead_ngrams(pm) -> set:
    tempo = float(pm.get_tempo_changes()[1][0])
    step = 60.0 / tempo / 4
    lead = [i for i in pm.instruments if i.name in ('lead', 'hook')]
    top: dict[int, int] = {}
    for n in (n for i in lead for n in i.notes):
        k = int(round(n.start / step))
        top[k] = max(top.get(k, 0), n.pitch)
    seq = sorted(top.items())
    return {(p1 - p0, p2 - p1, s1 - s0, s2 - s1) for (s0, p0), (s1, p1), (s2, p2) in zip(seq, seq[1:], seq[2:])}


def screen(renderer, cond: dict, k: int, target: float, selected: list[dict]) -> dict:
    genre, tier = cond['genre'], cond['tier']
    seed, pm, info, spec = v3_candidate(genre, tier, k)
    tempo = float(info['tempo_bpm'])
    reasons = []
    viol = v3_rules(genre, tier, pm, spec)
    if viol:
        reasons.append('rule_violations:' + ';'.join(viol[:4]))
    raw = renderer.render_pm(pm)
    clip, lvl = match_level(finish(raw, tempo, CLIP_BARS), target)
    pk = peak_dbfs(clip)
    if pk > PEAK_CEILING_DBFS + 0.01:
        reasons.append(f'peak {pk:.2f} dBFS')
    if lvl['limiter_applied'] and lvl['lufs_after_match'] < target - 1.0:
        reasons.append(f"limiter cost {target - lvl['lufs_after_match']:.1f} LU")
    quiet = longest_internal_quiet_s(clip, tempo)
    if quiet > MAX_INTERNAL_QUIET_S:
        reasons.append(f'internal silence {quiet:.2f} s')
    grams = lead_ngrams(pm)
    for s in selected:
        j = len(grams & s['_grams']) / max(len(grams | s['_grams']), 1)
        if j >= NEAR_DUP_MELODY:
            reasons.append(f"melody near-duplicate of {s['condition_id']} (n-gram overlap {j:.2f})")
    return {'k': k, 'seed': seed, 'pm': pm, 'info': info, 'raw': raw, 'clip': clip, 'level': lvl, 'quiet_s': quiet,
            'peak_dbfs': round(pk, 3), 'violations': viol, 'reasons': reasons, '_grams': grams, 'tempo': tempo}


def neutral_ids(conditions: list[dict]) -> dict[str, str]:
    order = sorted(conditions, key=lambda c: H(ID_SALT, c['condition_id']))
    return {c['condition_id']: f'S{i + 1:02d}' for i, c in enumerate(order)}


def preview_bars(tempo: float) -> int:
    bar_s = 240.0 / tempo
    return max(2, min(CLIP_BARS, int(round(PREVIEW_TARGET_S / bar_s))))


# =============================================================================
# Build
# =============================================================================


def environment(sf2: Path) -> dict:
    git = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True).stdout.strip()  # noqa: E731
    fs = subprocess.run(['fluidsynth', '--version'], capture_output=True, text=True).stdout.splitlines()
    import pretty_midi
    return {'soundfont': sf2.name, 'soundfont_sha256': sha256(sf2), 'soundfont_is_locked_musyng': sha256(sf2) == LOCKED_SF2_SHA256,
            'fluidsynth': fs[0] if fs else None, 'git_head': git('rev-parse', 'HEAD'),
            'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--untracked-files=no')),
            'python': platform.python_version(), 'numpy': np.__version__, 'pretty_midi': pretty_midi.__version__,
            'platform': platform.platform()}


def build(sf2: Path, out: Path | None, make_zip: bool, selection: Path | None) -> Path:
    from segment_renderer import SymbolicSegmentRenderer
    from stimulus_metrics import midi_sha256
    from composer.v3.genres import GEN_VERSION as GENRES_VERSION
    from composer.v3 import GEN_VERSION as HIPHOP_VERSION

    env = environment(sf2)
    label = sf2.stem + ('' if env['soundfont_is_locked_musyng'] else '_PRELIMINARY')
    out = out or REPO / f'groovegen_qualtrics_27_candidate_v3_{label}'
    if out.exists():
        shutil.rmtree(out)
    dirs = {k: out / v for k, v in {'A': 'A_qualtrics_mp3', 'B': 'B_wav_masters', 'C': 'C_midi_sources',
                                    'D': 'D_internal_previews_10s', 'E': 'E_analysis', 'F': 'F_reference_original_v2c_8bar',
                                    'G': 'G_candidate_practice_volume', 'L': 'listening'}.items()}
    for d in dirs.values():
        d.mkdir(parents=True)
    renderer = SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)
    scale = a3.energy_scale()
    conds, cond_src = load_conditions()
    ids = neutral_ids(conds)
    fixed = None
    if selection:
        fixed = {r['condition_id']: r for r in json.loads(selection.read_text())['stimuli']}

    rows, log, audit = [], [], []
    selected: list[dict] = []
    # screening order: ladder order (fixed); selection never looks at ratings or "danceability"
    for cond in conds:
        genre, tier, cell = cond['genre'], cond['tier'], cond['condition_id']
        # original condition: the full 8-bar v2c segment, reproduced and rendered the same way
        opm, oinfo = v2c_segment(genre, tier)
        osha = midi_sha256(opm)
        otempo = float(oinfo['tempo_bpm'])
        oclip = finish(renderer.render_pm(opm), otempo, CLIP_BARS)
        target = lufs(oclip)
        ref_wav = dirs['F'] / f'{ids[cell]}_original_v2c_8bar.wav'
        write_wav(ref_wav, oclip)
        (dirs['F'] / 'midi').mkdir(exist_ok=True)
        opm.write(str(dirs['F'] / 'midi' / f'{ids[cell]}_original_v2c_8bar.mid'))
        o_rh = midi_rhythm(opm, otempo)
        o_audio = audio_measures(read_wav(ref_wav), ref_wav, scale, o_rh['drum_onsets_per_s'], otempo)
        audit.append({**cond, 'density_v2c': tier_density(genre, tier),
                      'original_segment_reproduced': osha == cond['original_segment_midi_sha256'],
                      **{f'orig8_{k}': v for k, v in o_rh.items()},
                      **{f'orig8_{k}': v for k, v in o_audio.items() if not k.startswith('corpus_')},
                      'orig8_lufs_target': round(target, 3), 'orig8_reference_wav': str(ref_wav.relative_to(out)),
                      'orig8_reference_sha256': sha256(ref_wav),
                      **{f'orig8_{k}': v for k, v in o_audio.items() if k.startswith('corpus_')}})
        # v3 candidates
        chosen = None
        ks = [fixed[cell]['candidate_k']] if fixed else range(N_CANDIDATES)
        for k in ks:
            c = screen(renderer, cond, k, target, selected)
            log.append({'condition_id': cell, 'stimulus_id': ids[cell], 'candidate_k': k, 'seed': c['seed'],
                        'generator': c['info'].get('gen_version'), 'composition_id': c['info'].get('composition_id'),
                        'midi_sha256': midi_sha256(c['pm']), 'rule_violations': len(c['violations']),
                        'peak_dbfs_after_match': c['peak_dbfs'], 'limiter_applied': c['level']['limiter_applied'],
                        'match_gain_db': c['level']['match_gain_db'], 'internal_quiet_s': c['quiet_s'],
                        'passed': not c['reasons'], 'rejection_reasons': ' | '.join(c['reasons']),
                        'selected': False})
            if fixed:
                if midi_sha256(c['pm']) != fixed[cell]['midi_sha256']:
                    raise SystemExit(f'{cell}: regenerated MIDI differs from the selection file; not the same corpus')
                chosen = c
                break
            if not c['reasons']:
                chosen = c
                break
        if chosen is None:
            raise SystemExit(f'{cell}: no candidate passed screening; see the log')
        log[-1]['selected'] = True
        selected.append({'condition_id': cell, '_grams': chosen['_grams']})
        sid = ids[cell]
        wav = dirs['B'] / f'{sid}.wav'
        write_wav(wav, chosen['clip'])
        midi_path = dirs['C'] / f'{sid}.mid'
        chosen['pm'].write(str(midi_path))
        # internal preview: the first whole bars nearest 10 s, same level, quarter-bar fade
        nb = preview_bars(chosen['tempo'])
        prev = finish(chosen['raw'], chosen['tempo'], nb) * np.float32(10 ** (chosen['level']['match_gain_db'] / 20))
        if chosen['level']['limiter_applied']:
            from segment_renderer import limit_peaks
            prev = limit_peaks(prev, SR, PEAK_CEILING_DBFS)
        pwav = dirs['D'] / f'{sid}_INTERNAL_PREVIEW_{nb}bars.wav'
        write_wav(pwav, prev)
        x = read_wav(wav)
        rh = midi_rhythm(chosen['pm'], chosen['tempo'])
        am = audio_measures(x, wav, scale, rh['drum_onsets_per_s'], chosen['tempo'])
        ref_energy = a3.measure_segment(renderer, chosen['pm'], scale)
        info = chosen['info']
        rows.append({
            'stimulus_id': sid, 'condition_id': cell, 'genre': genre, 'tier': tier,
            'ladder_rung': cond['ladder_rung'], 'ladder_u': cond['ladder_u'],
            'intended_danceability_level': None,
            'intended_danceability_source': 'NOT DEFINED in the protocol or study files; see E_analysis/README.md '
                                            '"Intended danceability". Candidate codings are given as separate columns.',
            'coding_within_genre_tier': tier, 'coding_energy_ladder_rung': cond['ladder_rung'],
            'generator': 'v3', 'generator_version': HIPHOP_VERSION if genre == 'hiphop' else GENRES_VERSION,
            'seed': chosen['seed'], 'candidate_k': chosen['k'], 'composition_id': info.get('composition_id'),
            'tempo_bpm': chosen['tempo'], 'key': info.get('key'), 'substyle_or_mode': info.get('substyle') or info.get('mode'),
            'progression': info.get('progression') or f"{info.get('loop_a')} | {info.get('loop_b')}",
            'palette': info.get('palette'), 'groove': info.get('groove') or info.get('bass_style'),
            'section_role': info.get('role'), 'midi_file': str(midi_path.relative_to(out)), 'midi_sha256': midi_sha256(chosen['pm']),
            'wav_file': str(wav.relative_to(out)), 'wav_sha256': sha256(wav),
            'mp3_file': f"{dirs['A'].name}/{sid}.mp3",
            'preview_file': str(pwav.relative_to(out)), 'preview_bars': nb,
            'duration_s': round(x.shape[0] / SR, 3), 'bars': CLIP_BARS,
            'loudness_target_lufs': round(target, 3), **chosen['level'],
            'internal_quiet_s': chosen['quiet_s'], **rh, **am,
            'energy_u_midi_reference': ref_energy['energy_u'], 'lufs_midi_reference': ref_energy['lufs'],
            'soundfont': env['soundfont'], 'soundfont_sha256': env['soundfont_sha256'], 'source_commit': env['git_head'],
            'status': 'candidate (not frozen; not approved for participant use)',
        })
        print(f"{sid} {cell:9} k={chosen['k']} {info.get('gen_version')} {chosen['tempo']:g} BPM "
              f"LUFS {am['lufs_integrated']:.1f} (target {target:.1f}) gain {chosen['level']['match_gain_db']:+.1f} "
              f"drums {rh['drum_onsets_per_s']:.2f}/s u {am['energy_u_delivered']:.2f}", flush=True)

    # candidate practice and volume clips (not part of the 27; the original ones are not replaced)
    practice_rows = []
    for j, (kind, cell) in enumerate(PRACTICE):
        g, t = cell.split(':')
        t = int(t)
        opm, oinfo = v2c_segment(g, t, stim_seed=2)
        target = lufs(finish(renderer.render_pm(opm), float(oinfo['tempo_bpm']), CLIP_BARS))
        from composer.v3.genres import compose_excerpt
        seed = H(SEED_SALT, 'practice', kind, cell, j)
        pm, info, spec = compose_excerpt(g, t, seed)
        tempo = float(info['tempo_bpm'])
        clip, lvl = match_level(finish(renderer.render_pm(pm), tempo, CLIP_BARS), target)
        name = f"{kind.upper()}_{j + 1}" if kind == 'practice' else 'VOLUME'
        w = dirs['G'] / f'{name}.wav'
        write_wav(w, clip)
        pm.write(str(dirs['G'] / f'{name}.mid'))
        mp3(w, dirs['G'] / f'{name}.mp3')
        practice_rows.append({'file': w.name, 'kind': kind, 'condition_like': cell, 'seed': seed,
                              'generator_version': info.get('gen_version'), 'duration_s': round(clip.shape[0] / SR, 3),
                              'lufs': round(lufs(clip), 2), 'peak_dbfs': round(peak_dbfs(clip), 2),
                              'wav_sha256': sha256(w), 'midi_sha256': midi_sha256(pm), **lvl})

    # MP3s, verification, listening helpers
    verification = []
    for r in rows:
        wav = out / r['wav_file']
        m = out / r['mp3_file']
        mp3(wav, m)
        mp3(out / r['preview_file'], dirs['L'] / 'previews_mp3' / (Path(r['preview_file']).stem + '.mp3'))
        r['mp3_sha256'] = sha256(m)
        verification.append(verify(wav, m, r))
    write_listening(dirs['L'], rows, out)
    bad = [v for v in verification if not v['ok']]

    from qc_report import write_reports
    write_reports(out, dirs, rows, log, audit, practice_rows, verification, env, cond_src, label)
    if make_zip:
        zip_package(out)
    if bad:
        raise SystemExit(f'verification failed: {[v["stimulus_id"] for v in bad]}')
    return out


def verify(wav: Path, mp3_path: Path, r: dict) -> dict:
    with wave.open(str(wav)) as w:
        fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        frames = w.getnframes()
    x = read_wav(wav)
    dur = frames / SR
    tempo = r['tempo_bpm']
    expected = CLIP_BARS * bar_frames(tempo) + int(round(bar_frames(tempo) * FADE_BARS))
    data = wav.read_bytes()
    chunks = []
    i = 12
    while i + 8 <= len(data):
        chunks.append(data[i:i + 4].decode(errors='replace'))
        size = int.from_bytes(data[i + 4:i + 8], 'little')
        i += 8 + size + (size & 1)
    mdur = probe_s(mp3_path)
    first_ms = float(np.max(np.abs(x[:int(0.001 * SR)])))
    checks = {
        'wav_pcm16_stereo_44k1': fmt == (2, 2, 44100),
        'wav_no_metadata_chunks': set(chunks) <= {'fmt ', 'data'},
        'duration_exact': frames == expected,
        'duration_15_to_31_s': 15.0 <= dur <= 31.0,
        'peak_at_or_below_-1_dBFS': peak_dbfs(x) <= PEAK_CEILING_DBFS + 0.01,
        'no_full_scale_samples': int(np.sum(np.abs(x) >= 32767 / 32768)) == 0,
        'no_internal_silence': longest_internal_quiet_s(x, tempo) <= MAX_INTERNAL_QUIET_S,
        'starts_without_click': first_ms < 0.05,
        'ends_faded': float(np.max(np.abs(x[-int(0.005 * SR):]))) < 0.01,
        'finite': bool(np.isfinite(x).all()),
        'mp3_decodes_and_matches_duration': abs(mdur - dur) < 0.12,
    }
    return {'stimulus_id': r['stimulus_id'], 'ok': all(checks.values()), 'duration_s': round(dur, 3),
            'mp3_duration_s': round(mdur, 3), **checks}


def write_listening(d: Path, rows: list[dict], out: Path) -> None:
    """A playlist in stimulus-ID order and one continuous file with 3 s gaps."""
    srt = sorted(rows, key=lambda r: r['stimulus_id'])
    (d / 'playlist_S01-S27.m3u').write_text('#EXTM3U\n' + ''.join(
        f"#EXTINF:{int(round(r['duration_s']))},{r['stimulus_id']}\n../{r['mp3_file']}\n" for r in srt))
    gap = np.zeros((3 * SR, 2), np.float32)
    parts = []
    for r in srt:
        parts += [read_wav(out / r['wav_file']), gap]
    allwav = d / 'all_27_in_ID_order_3s_gaps.wav'
    write_wav(allwav, np.concatenate(parts))
    mp3(allwav, allwav.with_suffix('.mp3'))
    allwav.unlink()


def zip_package(out: Path) -> None:
    full = out.parent / f'{out.name}.zip'
    listen = out.parent / f'{out.name}_listening.zip'
    with zipfile.ZipFile(full, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            if p.is_file():
                z.write(p, Path(out.name) / p.relative_to(out))
    keep = ('A_qualtrics_mp3', 'E_analysis', 'listening')
    with zipfile.ZipFile(listen, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob('*')):
            rel = p.relative_to(out)
            if p.is_file() and (len(rel.parts) == 1 or rel.parts[0] in keep
                                or (rel.parts[0] == 'G_candidate_practice_volume' and p.suffix == '.mp3')):
                z.write(p, Path(out.name) / rel)
    for zp in (full, listen):
        with zipfile.ZipFile(zp) as z:
            assert z.testzip() is None, zp
        print('zip', zp, f'{zp.stat().st_size / 1e6:.1f} MB', flush=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = p.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--sf2', required=True, type=Path)
    b.add_argument('--out', type=Path, default=None)
    b.add_argument('--zip', action='store_true')
    b.add_argument('--selection', type=Path, default=None,
                   help='stimulus_manifest.json of an earlier package: same seeds and MIDI, no re-screening')
    a = p.parse_args(argv)
    if a.cmd == 'build':
        build(a.sf2, a.out, a.zip, a.selection)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
