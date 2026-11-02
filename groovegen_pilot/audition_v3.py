"""
v3 audition: renders the hip-hop v3 listening samples (Tests A-D) for developer
listening. Engineering material, not study stimuli; nothing here is used by
the live runner.

Generation uses the generators unchanged: v3 via composer/v3/source.py
(HipHopV3Source, tempo one per composition) and v2c via
session_generator.SessionSegmentSource(develop=True), the live v2c path.
Rendering uses SymbolicSegmentRenderer._render_pm_to_audio (FluidSynth CLI,
gain 0.8, master -2.5 dB, no normalisation) and the live join
(audition_v2.trim_like_live + join_like_live: 8 bars + a quarter-bar
tail_out crossfade). Features are measured as music_features_measured builds
the energy table (energy_audio at the reference level, 8 bars + fade, the same
audio and MIDI features, the table's z parameters, u over the live ladder).

Usage:
    python audition_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --out ../groovegen_v3_audition
    python audition_v3.py --sf2 <sf2> --calibrate             # level loudness vs v2c, mix balance
    python audition_v3.py --rerender <audition dir> --sf2 <sf2> --out <dir>   # same MIDI, other soundfont
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from statistics import fmean, median

import numpy as np
import pretty_midi

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import audition_v2 as av2  # noqa: E402
from music_features_measured import (ENERGY_WEIGHTS, FADE_BARS, SR, audio_features,  # noqa: E402
                                     energy_audio, midi_features)
from segment_renderer import SymbolicSegmentRenderer  # noqa: E402

BARS = 8
ENERGY_TABLE = HERE / 'energy_table_v1.json'
EAR_ORDER = HERE / 'energy_order_by_ear.json'

# Each sample: id, test, generator, stim seed, the tier / level per segment, and what it shows.
SAMPLES = (
    dict(id='A1', test='A', generator='v3', stim_seed=1, levels=(3, 3, 3),
         about='Composition 1 of stim seed 1 at level 3 (opening, statement, first development).'),
    dict(id='A2', test='A', generator='v3', stim_seed=2, levels=(3, 3, 3),
         about='Composition 1 of stim seed 2 at level 3.'),
    dict(id='A3', test='A', generator='v3', stim_seed=3, levels=(3, 3, 3),
         about='Composition 1 of stim seed 3 at level 3.'),
    dict(id='A4', test='A', generator='v3', stim_seed=4, levels=(3, 3, 3),
         about='Composition 1 of stim seed 4 at level 3.'),
    dict(id='B1', test='B', generator='v3', stim_seed=5, levels=(3,) * 8,
         about='One full composition at level 3: opening, statement, variations, contrast, return, close.'),
    dict(id='C1', test='C', generator='v3', stim_seed=1, levels=(2, 3, 4, 3),
         about='The A1 composition with intensity L2 -> L3 -> L4 -> L3 (one segment each).'),
    dict(id='C2', test='C', generator='v3', stim_seed=3, levels=(1, 2, 3, 4, 5),
         about='The A3 composition stepping through all five levels L1 -> L5.'),
    dict(id='D1', test='D', generator='v2c', stim_seed=1, levels=(3, 3, 3),
         about='Locked v2c, hiphop:3, three consecutive visits (stim seed 1); counterpart of A1-A4.'),
    dict(id='D2', test='D', generator='v2c', stim_seed=2, levels=(3, 3, 3),
         about='Locked v2c, hiphop:3, three visits, stim seed 2: what changes across v2c seeds.'),
    dict(id='D3', test='D', generator='v2c', stim_seed=1, levels=(2, 3, 4, 3),
         about='Locked v2c, hiphop:2 -> 3 -> 4 -> 3 (tempo follows the tier: 87/90/93/90 BPM); counterpart of C1.'),
    dict(id='D4', test='D', generator='v2c', stim_seed=1, levels=(3,) * 8,
         about='Locked v2c, hiphop:3, eight consecutive visits; counterpart of B1.'),
)


# =============================================================================
# Generation
# =============================================================================


def generate(sample: dict) -> list[tuple[pretty_midi.PrettyMIDI, dict]]:
    if sample['generator'] == 'v3':
        from composer.v3.source import HipHopV3Source

        src = HipHopV3Source(sample['stim_seed'], tempo_policy='composition')
    else:
        from session_generator import SessionSegmentSource

        src = SessionSegmentSource(sample['stim_seed'], develop=True)
    return [src.next_segment('hiphop', lv) for lv in sample['levels']]


# =============================================================================
# Measurement (the energy-table recipe)
# =============================================================================


def energy_scale() -> dict:
    """z parameters over the table's cells and the live ladder's E range (u = 0..1)."""
    tab = json.loads(ENERGY_TABLE.read_text())
    cells = tab['cells']
    w = tab['weights']
    z = {f: (float(np.mean([c[f] for c in cells.values()])), float(np.std([c[f] for c in cells.values()]))) for f in w}
    live = list(json.loads(EAR_ORDER.read_text())['ratings'])
    e = {k: sum(w[f] * (cells[k][f] - z[f][0]) / z[f][1] for f in w) for k in live}
    return {'weights': w, 'z': z, 'e_min': min(e.values()), 'e_max': max(e.values())}


def energy_u(feat: dict, scale: dict) -> tuple[float, float]:
    e = sum(wt * (feat[f] - scale['z'][f][0]) / scale['z'][f][1] for f, wt in scale['weights'].items())
    return e, (e - scale['e_min']) / (scale['e_max'] - scale['e_min'])


def measure_segment(renderer, pm: pretty_midi.PrettyMIDI, scale: dict) -> dict:
    tempo = float(pm.get_tempo_changes()[1][0])
    bar_s = 240.0 / tempo
    dur_s = BARS * bar_s
    audio = energy_audio(renderer, pm)[:int(round(BARS * bar_s * SR + FADE_BARS * bar_s * SR))]
    feat = {'tempo_bpm': tempo, **midi_features(pm, dur_s), **audio_features(audio)}
    feat['energy_e'], feat['energy_u'] = energy_u(feat, scale)
    return {k: (round(v, 5) if isinstance(v, float) else v) for k, v in feat.items()}


def whole_file_features(audio: np.ndarray) -> dict:
    import pyloudnorm as pyln

    x = np.asarray(audio, np.float64)
    return {'lufs_integrated': round(float(pyln.Meter(SR).integrated_loudness(x)), 3),
            'peak_dbfs': round(float(20 * np.log10(max(np.max(np.abs(x)), 1e-9))), 3),
            'duration_s': round(x.shape[0] / SR, 3)}


# =============================================================================
# Output helpers
# =============================================================================


def combined_midi(pms: list[pretty_midi.PrettyMIDI]) -> pretty_midi.PrettyMIDI | None:
    """All segments of a constant-tempo sample in one MIDI file (segment i starts
    at i x 8 bars, as in the joined audio); None if the tempo changes."""
    tempi = {round(float(pm.get_tempo_changes()[1][0]), 6) for pm in pms}
    if len(tempi) != 1:
        return None
    tempo = tempi.pop()
    seg_s = BARS * 240.0 / tempo
    out = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    tracks: dict[tuple, pretty_midi.Instrument] = {}
    for i, pm in enumerate(pms):
        for inst in pm.instruments:
            key = (inst.name, inst.program, inst.is_drum)
            if key not in tracks:
                tracks[key] = pretty_midi.Instrument(program=inst.program, is_drum=inst.is_drum, name=inst.name)
            off = i * seg_s
            for n in inst.notes:
                tracks[key].notes.append(pretty_midi.Note(n.velocity, n.pitch, n.start + off, n.end + off))
    out.instruments = list(tracks.values())
    return out


def level_tag(levels) -> str:
    """'L3x3' for a constant level, 'L2-L3-L4-L3' for a sequence."""
    if len(set(levels)) == 1:
        return f'L{levels[0]}x{len(levels)}'
    return '-'.join(f'L{x}' for x in levels)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    import wave

    with wave.open(str(path), 'rb') as wf:
        sr, ch, n = wf.getframerate(), wf.getnchannels(), wf.getnframes()
        x = np.frombuffer(wf.readframes(n), dtype=np.int16).reshape(-1, ch).astype(np.float32) / 32768.0
    return x, sr


def environment(sf2: Path) -> dict:
    fs = subprocess.run(['fluidsynth', '--version'], capture_output=True, text=True).stdout.splitlines()
    try:
        git = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, cwd=HERE).stdout.strip()
        dirty = bool(subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no', '--', '.'],
                                    capture_output=True, text=True, cwd=HERE).stdout.strip())
    except OSError:
        git, dirty = None, None
    return {'fluidsynth': fs[0] if fs else None, 'soundfont': sf2.name, 'soundfont_sha256': sha256(sf2),
            'python': platform.python_version(), 'numpy': np.__version__, 'pretty_midi': pretty_midi.__version__
            if hasattr(pretty_midi, '__version__') else None, 'platform': platform.platform(), 'git_head': git,
            'git_dirty': dirty}


# =============================================================================
# Render one sample
# =============================================================================


def render_sample(sample: dict, segments: list[tuple[pretty_midi.PrettyMIDI, dict]], renderer, scale: dict,
                  out: Path) -> dict:
    sid = sample['id']
    seg_dir = out / 'midi' / sid
    seg_dir.mkdir(parents=True, exist_ok=True)
    audios, tempos, rows = [], [], []
    t = 0.0
    for i, (pm, info) in enumerate(segments):
        tempo = float(pm.get_tempo_changes()[1][0])
        t0 = time.perf_counter()
        audio = renderer._render_pm_to_audio(pm)
        render_s = time.perf_counter() - t0
        audios.append(av2.trim_like_live(audio, tempo))
        tempos.append(tempo)
        midi_path = seg_dir / f'{sid}_seg{i + 1:02d}.mid'
        pm.write(str(midi_path))
        feat = measure_segment(renderer, pm, scale)
        row = {'sample': sid, 'seg': i + 1, 'start_s': round(t, 3), 'level_or_tier': sample['levels'][i],
               'midi': str(midi_path.relative_to(out)), 'midi_sha256': sha256(midi_path),
               'render_s': round(render_s, 3)}
        if sample['generator'] == 'v3':
            row.update({k: info.get(k) for k in ('composition_id', 'substyle', 'key', 'comp_tempo_bpm', 'swing', 'role',
                                                 'section_idx', 'op', 'fills', 'loop_a', 'loop_b', 'palette',
                                                 'bass_style', 'comp_style', 'form', 'ops', 'cells')})
            row['seeds'] = f"base {info['base_seed']} segment {info['var_seed']}"
        else:
            row.update({'composition_id': f"v2c-base-{info['base_seed']}", 'role': f"block {info['block_idx']} "
                        f"pos {info['pos_in_block']}", 'op': '+'.join(info.get('motif_ops') or []),
                        'seeds': f"base {info['base_seed']} var {info['var_seed']}",
                        'gen_version': info.get('gen_version'), 'dev_version': info.get('dev_version')})
        row.update(feat)
        rows.append(row)
        t += BARS * 240.0 / tempo
    joined, starts, stats = av2.join_like_live(audios, tempos)
    wav = out / 'wav' / f"{sid}_{sample['generator']}_{level_tag(sample['levels'])}.wav"
    wav.parent.mkdir(parents=True, exist_ok=True)
    av2._write_wav(wav, joined)
    comb = combined_midi([pm for pm, _ in segments])
    comb_path = None
    if comb is not None:
        comb_path = out / 'midi' / f'{wav.stem}.mid'
        comb.write(str(comb_path))
    check, sr = read_wav(wav)
    whole = whole_file_features(check)
    expected = sum(BARS * 240.0 / tp for tp in tempos)
    summary = {**{k: sample[k] for k in ('id', 'test', 'generator', 'stim_seed', 'levels', 'about')},
               'wav': str(wav.relative_to(out)), 'wav_sha256': sha256(wav),
               'midi_combined': str(comb_path.relative_to(out)) if comb_path else None,
               'segments': len(segments), 'tempo_bpm': sorted(set(tempos)),
               'expected_music_s': round(expected, 3), 'sample_rate': sr, **whole,
               'mixer': stats, 'segment_starts_s': [round(s / SR, 3) for s in starts]}
    for f in ('lufs', 'drum_rate', 'note_rate', 'centroid_hz', 'flux', 'pulse_clarity', 'energy_u'):
        summary[f'mean_{f}'] = round(fmean(r[f] for r in rows), 4)
    return {'summary': summary, 'rows': rows}


# =============================================================================
# Computational evidence (supporting, not perceptual)
# =============================================================================


def _bar_chroma(wav: Path, starts_s: list[float], tempos: list[float]) -> np.ndarray:
    """Mean chroma per bar of the rendered audio (bars from the known segment starts)."""
    import librosa

    x, sr = read_wav(wav)
    mono = x.mean(axis=1)
    chroma = librosa.feature.chroma_stft(y=mono, sr=sr, hop_length=1024)
    fps = sr / 1024
    bars = []
    for t0, tempo in zip(starts_s, tempos):
        bar_s = 240.0 / tempo
        for b in range(BARS):
            a, z = int((t0 + b * bar_s) * fps), int((t0 + (b + 1) * bar_s) * fps)
            v = chroma[:, a:z].mean(axis=1)
            bars.append(v / (np.linalg.norm(v) + 1e-9))
    return np.array(bars)


def _key_invariant_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Mean per-bar chroma cosine, maximised over the 12 transpositions of b."""
    n = min(len(a), len(b))
    return max(float(np.mean(np.sum(a[:n] * np.roll(b[:n], k, axis=1), axis=1))) for k in range(12))


def _drum_profile(midis: list[Path]) -> np.ndarray:
    """16th-grid onset histograms of kick, backbeat and hats over a sample's segments."""
    prof = np.zeros((3, 16))
    roles = ((35, 36), (37, 38, 39, 40), (42, 44, 46))
    for path in midis:
        pm = pretty_midi.PrettyMIDI(str(path))
        step = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
        for inst in pm.instruments:
            if inst.is_drum:
                for n in inst.notes:
                    for r, pitches in enumerate(roles):
                        if n.pitch in pitches:
                            prof[r, int(round(n.start / step)) % 16] += 1
    return prof.ravel() / (np.linalg.norm(prof) + 1e-9)


def _melody_ngrams(midis: list[Path], generator: str) -> set:
    """Transposition-invariant 3-note interval + onset-gap n-grams of the lead line."""
    names = ('hook',) if generator == 'v3' else ('Piano',)
    grams = set()
    for path in midis:
        pm = pretty_midi.PrettyMIDI(str(path))
        step = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
        notes = sorted((n for i in pm.instruments if i.name in names for n in i.notes), key=lambda n: n.start)
        top = {}
        for n in notes:                                  # top voice per onset
            k = int(round(n.start / step))
            top[k] = max(top.get(k, 0), n.pitch)
        seq = sorted(top.items())
        for (s0, p0), (s1, p1), (s2, p2) in zip(seq, seq[1:], seq[2:]):
            grams.add((p1 - p0, p2 - p1, s1 - s0, s2 - s1))
    return grams


def evidence(out: Path, manifest: dict) -> dict:
    """Pairwise similarity of the fixed-level samples (A1-A4 vs D1/D2) in harmony
    (rendered audio, key-invariant), drums and melody (MIDI), and the bar-level
    self-similarity structure of the long samples (B1 vs D4)."""
    samples = {s['id']: s for s in manifest['samples']}
    rows = {s['id']: [r for r in manifest['segments'] if r['sample'] == s['id']] for s in manifest['samples']}

    def tempos(sid):
        return [r['tempo_bpm'] for r in rows[sid]]

    chroma = {sid: _bar_chroma(out / s['wav'], s['segment_starts_s'], tempos(sid)) for sid, s in samples.items()}
    drums = {sid: _drum_profile([out / r['midi'] for r in rows[sid]]) for sid in samples}
    melody = {sid: _melody_ngrams([out / r['midi'] for r in rows[sid]], s['generator']) for sid, s in samples.items()}
    pairs = []
    for group in (('A1', 'A2', 'A3', 'A4'), ('D1', 'D2')):
        for a, b in [(x, y) for i, x in enumerate(group) for y in group[i + 1:]]:
            if a in samples and b in samples:
                jac = len(melody[a] & melody[b]) / max(1, len(melody[a] | melody[b]))
                pairs.append({'pair': f'{a}-{b}', 'harmony_key_invariant': round(_key_invariant_similarity(
                    chroma[a], chroma[b]), 3), 'drum_pattern': round(float(drums[a] @ drums[b]), 3),
                    'melody_ngram_jaccard': round(jac, 3)})
    form = {}
    for sid in ('B1', 'D4'):
        if sid not in samples:
            continue
        c = chroma[sid]
        seg = [c[i * BARS:(i + 1) * BARS] for i in range(len(c) // BARS)]
        sim = np.array([[float(np.mean(np.sum(x * y, axis=1))) for y in seg] for x in seg])
        roles = [r.get('role') for r in rows[sid]]
        off = sim[~np.eye(len(seg), dtype=bool)]
        form[sid] = {'roles': roles, 'segment_similarity': np.round(sim, 3).tolist(),
                     'mean_offdiag': round(float(off.mean()), 3), 'min_offdiag': round(float(off.min()), 3)}
    ev = {'pairs': pairs, 'form': form,
          'note': 'Computational similarity only (1 = identical). Harmony: per-bar chroma of the rendered audio, '
                  'best over 12 transpositions. Drums: 16th-grid kick / backbeat / hat histograms. Melody: '
                  'Jaccard overlap of transposition-invariant 3-note interval-and-rhythm n-grams of the lead line.'}
    (out / 'evidence.json').write_text(json.dumps(ev, indent=1))
    return ev


# =============================================================================
# README
# =============================================================================


def readme(manifest: dict) -> str:
    env = manifest['environment']
    lines = [
        '# GrooveGen v3 hip-hop audition',
        '',
        f"Generated {manifest['created']} by `groovegen_pilot/audition_v3.py` (git {env['git_head']}).",
        '',
        '## Read first: soundfont',
        '',
        f"Rendered with **{env['soundfont']}** (sha256 `{env['soundfont_sha256'][:16]}...`), "
        f"**not** the project's `Musyng_Kite.sf2`, which was not obtainable in the build environment. "
        'v2c and v3 samples use the same soundfont, so they compare fairly with each other, but '
        'timbre and absolute loudness differ from the locked system. Energy values (`energy_u`) '
        'use the locked table\'s scale but are measured on this soundfont, so compare them '
        'between samples here, not with the table. To hear the same MIDI through Musyng Kite:',
        '',
        '```',
        'cd groovegen_pilot',
        '../.venv/bin/python3.12 audition_v3.py --rerender ../groovegen_v3_audition '
        '--sf2 ../soundfonts/Musyng_Kite.sf2 --out ../groovegen_v3_audition_musyng',
        '```',
        '',
        f"FluidSynth: {env['fluidsynth']}. Every render: gain 0.8, master -2.5 dB, no normalisation, "
        'segments joined as the live runner joins them (8 bars + quarter-bar tail_out crossfade). '
        'Intensity differences are preserved; nothing is loudness-normalised.',
        '',
        '## How to listen',
        '',
        '| Question | Listen to | Listen for |',
        '|---|---|---|',
        '| Are v3 compositions really different, at the same intensity? | A1, A2, A3, A4, then D1 and D2 | '
        'Different chords, hook, bass line, drum feel and instruments in A1-A4; D1 vs D2 is the same piece '
        'in another key. Still recognisably hip-hop in every one? |',
        '| Does a composition develop? | B1 (about 3 min), then D4 | The hook enters at bar 5 of the first '
        'segment and is answered and varied later; a contrast section brings new chords and the answer on '
        'another instrument; the original hook returns. Roles and timestamps in Timelines below. |',
        '| Does intensity change without losing the piece? | C1 vs D3, and C2 | Drums, layers and dynamics '
        'follow the level while the hook, chords, tempo and groove stay. D3 also changes tempo each step. |',
        '',
        'These files were generated and measured, **not listened to**: the build environment has no audio '
        'perception. The rule checks and measurements below are supporting evidence only.',
        '',
        '## Samples',
        '',
        '| Sample | File | Generator | Seed | Levels / tiers | Duration | BPM | LUFS | Drums/s | u | What it shows |',
        '|---|---|---|---|---|---|---|---|---|---|---|',
    ]
    for s in manifest['samples']:
        lv = ' '.join(f'L{x}' for x in s['levels'])
        lines.append(f"| {s['id']} | `{s['wav']}` | {s['generator']} | {s['stim_seed']} | {lv} | "
                     f"{s['duration_s']:.1f} s | {'/'.join(f'{t:g}' for t in s['tempo_bpm'])} | "
                     f"{s['lufs_integrated']:.1f} | {s['mean_drum_rate']:.2f} | {s['mean_energy_u']:.2f} | {s['about']} |")
    lines += ['', '## Timelines', '']
    for s in manifest['samples']:
        rows = [r for r in manifest['segments'] if r['sample'] == s['id']]
        lines.append(f"**{s['id']}** ({s['generator']})")
        lines.append('')
        if s['generator'] == 'v3':
            r0 = rows[0]
            lines.append(f"Composition `{r0['composition_id']}`: {r0['substyle']}, {r0['key']}, "
                         f"{r0['comp_tempo_bpm']:g} BPM, swing {r0['swing']}, loop A `{r0['loop_a']}`, "
                         f"loop B `{r0['loop_b']}`, palette {r0['palette']}, bass {r0['bass_style']}, "
                         f"keys {r0['comp_style']}, hook cells {r0['cells']}, form {r0['form']}.")
            lines.append('')
        for r in rows:
            t = r['start_s']
            desc = (f"role {r['role']}" + (f", development `{r['op']}`" if r.get('op') else '')
                    + (f", fills {r['fills']}" if r.get('fills') else ''))
            lines.append(f"- {int(t // 60)}:{t % 60:04.1f} segment {r['seg']} ({'L' if s['generator'] == 'v3' else 'tier '}"
                         f"{r['level_or_tier']}): {desc}; LUFS {r['lufs']:.1f}, drums {r['drum_rate']:.2f}/s, "
                         f"u {r['energy_u']:.2f}")
        lines.append('')
    ev = manifest.get('evidence')
    if ev:
        lines += ['## Computational evidence (supporting only; not a substitute for listening)', '',
                  ev['note'], '',
                  '| Pair | Harmony (key-invariant) | Drum pattern | Melody n-gram overlap |', '|---|---|---|---|']
        lines += [f"| {p['pair']} | {p['harmony_key_invariant']:.3f} | {p['drum_pattern']:.3f} | "
                  f"{p['melody_ngram_jaccard']:.3f} |" for p in ev['pairs']]
        for sid, f in ev['form'].items():
            lines += ['', f"{sid} segment-to-segment harmonic similarity (roles {', '.join(map(str, f['roles']))}): "
                      f"mean off-diagonal {f['mean_offdiag']}, minimum {f['min_offdiag']}."]
        lines.append('')
    lines += [
        '## Files',
        '',
        '- `wav/`: one joined 16-bit, 44.1 kHz stereo WAV per sample.',
        '- `midi/<sample>/`: the MIDI of every segment, exactly as rendered; `midi/<wav name>.mid`: all '
        'segments of a constant-tempo sample in one file (D3 changes tempo, so only per-segment files).',
        '- `manifest.json` / `segments.csv`: seeds, configuration, provenance and the measured features of '
        'every segment (energy-table recipe: LUFS, drum onset rate, tempo, spectral centroid, flux, pulse '
        'clarity, energy E and u).',
        '',
        '## Limits',
        '',
        '- Developer-listening material, not study stimuli. Nothing here is perceptually validated.',
        '- Features are stimulus measurements, not listener responses.',
    ]
    return '\n'.join(lines) + '\n'


# =============================================================================
# Modes
# =============================================================================


def run(sf2: Path, out: Path, only: set | None = None, zip_name: str | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    renderer = SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)
    scale = energy_scale()
    summaries, rows = [], []
    for sample in SAMPLES:
        if only and sample['id'] not in only:
            continue
        res = render_sample(sample, generate(sample), renderer, scale, out)
        summaries.append(res['summary'])
        rows += res['rows']
        s = res['summary']
        print(f"{s['id']}: {s['wav']} {s['duration_s']:.1f}s LUFS {s['lufs_integrated']:.1f} "
              f"drums {s['mean_drum_rate']:.2f}/s u {s['mean_energy_u']:.2f}", flush=True)
    manifest = {'created': time.strftime('%Y-%m-%d %H:%M:%S'), 'environment': environment(sf2),
                'energy_scale': {'source': ENERGY_TABLE.name, 'e_min': scale['e_min'], 'e_max': scale['e_max']},
                'samples': summaries, 'segments': rows}
    if not only:
        manifest['evidence'] = evidence(out, manifest)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1, default=str))
    keys = sorted({k for r in rows for k in r})
    with open(out / 'segments.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    (out / 'README.md').write_text(readme(manifest))
    if zip_name:
        zp = out.parent / zip_name
        with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.rglob('*')):
                if p.is_file():
                    z.write(p, Path(out.name) / p.relative_to(out))
        print('zip', zp, f'{zp.stat().st_size / 1e6:.1f} MB')
    return manifest


def rerender(src: Path, sf2: Path, out: Path) -> None:
    """Re-render the saved segment MIDI of an audition with another soundfont."""
    manifest = json.loads((src / 'manifest.json').read_text())
    renderer = SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)
    scale = energy_scale()
    for s in manifest['samples']:
        rows = [r for r in manifest['segments'] if r['sample'] == s['id']]
        segs = [(pretty_midi.PrettyMIDI(str(src / r['midi'])), {}) for r in rows]
        audios = [av2.trim_like_live(renderer._render_pm_to_audio(pm), float(pm.get_tempo_changes()[1][0]))
                  for pm, _ in segs]
        joined, _, _ = av2.join_like_live(audios, [float(pm.get_tempo_changes()[1][0]) for pm, _ in segs])
        wav = out / s['wav']
        wav.parent.mkdir(parents=True, exist_ok=True)
        av2._write_wav(wav, joined)
        us = [measure_segment(renderer, pm, scale)['energy_u'] for pm, _ in segs]
        print(f"{s['id']}: {wav} u {fmean(us):.2f}")


def calibrate(sf2: Path) -> None:
    """Per-level loudness / drum rate / u of v3 against the v2c hip-hop tiers on
    this soundfont, and the loudness of each v3 part (mix balance)."""
    from composer.v3.hiphop import plan_segment, realize
    from composer.v3.source import HipHopV3Source
    from session_generator import SessionSegmentSource
    from dataclasses import replace

    renderer = SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)
    scale = energy_scale()
    print('level  v2c LUFS  v3 LUFS   v2c drums/s  v3 drums/s   v2c u   v3 u')
    for lv in range(1, 6):
        v2 = []
        for stim in (1, 2):
            src = SessionSegmentSource(stim, develop=True)
            v2 += [measure_segment(renderer, src.next_segment('hiphop', lv)[0], scale) for _ in range(2)]
        v3 = []
        for stim in range(1, 7):
            st = HipHopV3Source(stim).current_state()
            for o in (1, 2):
                v3.append(measure_segment(renderer, realize(plan_segment(replace(st, ordinal=o), lv)), scale))
        f = lambda rows, k: median(r[k] for r in rows)
        print(f"L{lv}    {f(v2, 'lufs'):7.2f}  {f(v3, 'lufs'):7.2f}   {f(v2, 'drum_rate'):8.2f}   {f(v3, 'drum_rate'):8.2f}"
              f"    {f(v2, 'energy_u'):6.3f}  {f(v3, 'energy_u'):6.3f}", flush=True)
    print('\nmix balance at L3 (LUFS of each part rendered alone, median over compositions)')
    parts: dict[str, list] = {}
    for stim in range(1, 7):
        st = HipHopV3Source(stim).current_state()
        pm = realize(plan_segment(replace(st, ordinal=1), 3))
        for inst in pm.instruments:
            solo = pretty_midi.PrettyMIDI(initial_tempo=float(pm.get_tempo_changes()[1][0]))
            solo.instruments = [inst]
            a = energy_audio(renderer, solo)
            parts.setdefault(inst.name, []).append(audio_features(a)['lufs'])
    for k, v in parts.items():
        print(f'  {k:8} {median(v):7.2f} LUFS  (range {min(v):.1f} .. {max(v):.1f})')


def measure_levels(sf2: Path) -> Path:
    """Write composer/v3/levels_<sf2 stem>.json: reference loudness of each palette
    program at several note lengths, of each drum pitch, the predictor's offset
    fitted on rendered v3 and v2c segments, and the v2c hip-hop:3 loudness (the
    level-3 target), all on this soundfont."""
    from dataclasses import replace

    from composer.v3 import hiphop as hh
    from composer.v3 import levels as lv
    from composer.v3.source import HipHopV3Source
    from session_generator import SessionSegmentSource

    renderer = SymbolicSegmentRenderer(str(sf2), sr=SR, session_seed=42)

    def phrase(prog, pitch, dur, drum=False):
        # 16 notes, 2 per second, cycling 8 pitches so long notes never overlap
        # their own key (FluidSynth would end both at the first note-off)
        cycle = (0,) if drum else (0, 3, 7, 10, 12, 10, 7, 3) if pitch < 50 else (0, 3, 7, 10, 12, 15, 19, 22)
        pm = pretty_midi.PrettyMIDI(initial_tempo=120)
        inst = pretty_midi.Instrument(program=prog, is_drum=drum)
        inst.notes = [pretty_midi.Note(90, pitch + cycle[k % len(cycle)], k / lv.REF_RATE, k / lv.REF_RATE + dur)
                      for k in range(16)]
        pm.instruments = [inst]
        return audio_features(energy_audio(renderer, pm))['lufs']

    programs = sorted({p for sub in hh.SUBSTYLES.values() for pal in sub['palettes'] for p in pal.values()})
    centre = {**{p: 67 for p in programs}, 32: 40, 33: 40, 38: 40, 4: 60, 48: 60, 49: 60, 89: 60}
    table = {'soundfont': sf2.name, 'soundfont_sha256': sha256(sf2), 'ref_rate': lv.REF_RATE,
             'programs': {p: {d: round(phrase(p, centre[p], d), 3) for d in (0.1, 0.35, 1.0, 1.9, 3.5)}
                          for p in programs},
             'drums': {p: round(phrase(0, p, 0.1, drum=True), 3) for p in (36, 37, 38, 39, 40, 42, 44, 46, 49, 54, 70)}}
    table['program_default'] = float(np.median([c[0.35] for c in table['programs'].values()]))
    table['drum_default'] = float(np.median(list(table['drums'].values())))
    table['offset_db'] = 0.0
    # offset: rendered minus predicted over a calibration set (uncalibrated v3 + v2c segments)
    t = {**table, 'programs': {int(k): v for k, v in table['programs'].items()}}
    pairs = []
    for stim in range(1, 7):
        st = HipHopV3Source(stim, calibrate=False).current_state()
        for o, lvl in ((1, 3), (2, 2), (3, 4)):
            pm = hh.realize(hh.plan_segment(replace(st, ordinal=o), lvl))
            dur = BARS * 240.0 / st.spec.tempo
            pairs.append((audio_features(energy_audio(renderer, pm))['lufs'], lv.predict_lufs(pm, dur, t)))
    v2 = []
    for stim in (1, 2):
        src = SessionSegmentSource(stim, develop=True)
        for _ in range(3):
            pm = src.next_segment('hiphop', 3)[0]
            dur = BARS * 240.0 / float(pm.get_tempo_changes()[1][0])
            rendered = audio_features(energy_audio(renderer, pm))['lufs']
            v2.append(rendered)
            pairs.append((rendered, lv.predict_lufs(pm, dur, t)))
    resid = [a - b for a, b in pairs]
    table['offset_db'] = round(float(np.median(resid)), 3)
    table['fit_residual_sd_db'] = round(float(np.std(np.array(resid) - table['offset_db'])), 3)
    table['target_lufs_l3'] = round(float(np.mean(v2)), 3)
    out = HERE / 'composer' / 'v3' / f'levels_{sf2.stem}.json'
    out.write_text(json.dumps(table, indent=1))
    print(f"{out}: offset {table['offset_db']} dB, residual SD {table['fit_residual_sd_db']} dB, "
          f"v2c hiphop:3 target {table['target_lufs_l3']} LUFS")
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--sf2', required=True, type=Path)
    p.add_argument('--out', type=Path, default=HERE.parent / 'groovegen_v3_audition')
    p.add_argument('--only', default=None, help='comma-separated sample ids')
    p.add_argument('--zip', default=None, help='also write this zip next to --out')
    p.add_argument('--calibrate', action='store_true')
    p.add_argument('--measure-levels', action='store_true')
    p.add_argument('--rerender', type=Path, default=None)
    args = p.parse_args(argv)
    if args.measure_levels:
        measure_levels(args.sf2)
    elif args.calibrate:
        calibrate(args.sf2)
    elif args.rerender:
        rerender(args.rerender, args.sf2, args.out)
    else:
        run(args.sf2, args.out, set(args.only.split(',')) if args.only else None, args.zip)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
