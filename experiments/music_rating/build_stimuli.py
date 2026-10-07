"""
Build or verify the frozen Experiment 1 stimulus set from the locked GrooveGen
system (pilot-zero-v2c-locked). Offline tool for the researcher; participants
never run it, and the participant app never generates music.

One stimulus per live ladder cell (27), exactly what the live runner plays as
the first segment of a session in that cell:
    --generator v2c --ladder ear --stim-seed 1, a fresh SessionSegmentSource
    (visit 0), SymbolicSegmentRenderer.render_pm (Musyng_Kite.sf2, gain 0.8,
    Rock presentation, -2.5 dB master), run_session_v2's trim (8 bars plus one
    quarter-bar of release), and the live tail_out fade on that quarter bar.
Each cell comes from its own fresh session, so a stimulus does not depend on
which cells were rendered before it. Practice and volume-check clips use the
same path with stim seed 2 (material not in the main set).

The generator, ladder, renderer and soundfont are imported and used
unchanged; build refuses to run if any tracked non-doc file under
groovegen_pilot/ differs from the locked tag or the soundfont hash differs.

Usage (from the repository root):
    .venv/bin/python experiments/music_rating/build_stimuli.py build
    .venv/bin/python experiments/music_rating/build_stimuli.py verify
    .venv/bin/python experiments/music_rating/build_stimuli.py archive --out DIR
build writes experiments/music_rating/stimuli/<id>.wav (gitignored) and
manifest.json, and refuses to write into a folder that already has a manifest.
verify checks the frozen files against the manifest, then re-renders every
stimulus into a temporary folder and requires identical MIDI and audio hashes.
archive checks the files, then writes DIR/music-rating-stimuli-<manifest sha12>.tar
(30 WAVs, manifest.json, MANIFEST_SHA256, SOURCE_TAG, SHA256SUMS) and a
matching .sha256 next to it, for storage outside Git. The tar is deterministic
(sorted members, fixed mtime/owner), so re-archiving gives the same bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PILOT = REPO / 'groovegen_pilot'
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import stimuli as st  # noqa: E402

SF2 = REPO / 'soundfonts' / 'Musyng_Kite.sf2'
LOCKED_SF2_SHA256 = 'ed8c5a34c28b0fbbc805d6bbae74a169582c1881b57219972052e822c7be35f0'
STIM_SEED = 1                      # locked live default (RELEASE_pilot_zero_v2c_rc2.md)
PRACTICE_STIM_SEED = 2             # different material for practice / volume clips
PRACTICE_CELLS = ('lofi:2', 'pop:4')
VOLUME_CELL = 'pop:3'
SAMPLE_RATE = 44100
PEAK_CEILING_DBFS = -1.0           # every stimulus must stay at or below this
MASTER_TOLERANCE_DB = 0.05


# =============================================================================
# Provenance
# =============================================================================

def _git(*args: str) -> str:
    return subprocess.run(['git', *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def locked_code_changes(changed: list[str]) -> list[str]:
    """Changed paths that matter: everything under groovegen_pilot/ except docs."""
    return [p for p in changed if p.startswith('groovegen_pilot/') and not p.endswith('.md')]


def provenance() -> dict[str, Any]:
    """Refuses (SystemExit) unless the locked code and soundfont are unchanged."""
    tag_commit = _git('rev-parse', f'{st.SOURCE_TAG}^{{commit}}')
    head = _git('rev-parse', 'HEAD')
    if subprocess.run(['git', 'merge-base', '--is-ancestor', tag_commit, head], cwd=REPO).returncode != 0:
        raise SystemExit(f'HEAD {head[:8]} does not descend from {st.SOURCE_TAG}')
    changed = locked_code_changes(_git('diff', '--name-only', tag_commit, '--', 'groovegen_pilot').splitlines())
    if changed:
        raise SystemExit(f'locked code differs from {st.SOURCE_TAG}: {changed}')
    if not SF2.exists() or st.file_sha256(SF2) != LOCKED_SF2_SHA256:
        raise SystemExit(f'soundfont missing or not the locked file: {SF2}')
    fs = subprocess.run(['fluidsynth', '--version'], capture_output=True, text=True).stdout
    import pretty_midi
    return {
        'source_tag': st.SOURCE_TAG, 'source_commit': tag_commit, 'build_head': head,
        'build_branch': _git('branch', '--show-current'), 'locked_code_unchanged': True,
        'soundfont': {'file': str(SF2.relative_to(REPO)), 'sha256': LOCKED_SF2_SHA256},
        'fluidsynth': next((ln.split()[-1] for ln in fs.splitlines() if 'runtime version' in ln), fs.strip()),
        'python': platform.python_version(), 'numpy': np.__version__, 'pretty_midi': pretty_midi.__version__,
        'platform': platform.platform(),
    }


# =============================================================================
# Rendering (locked modules, unchanged)
# =============================================================================

def live_cells() -> tuple[list[Any], dict[str, Any]]:
    """(the live 27-cell ladder in rung order, ladder info) as run_pilot_zero --ladder ear builds it."""
    from run_pilot_zero import EAR_ORDER, ENERGY_TABLE, build_live_ladder

    ladder, et_sha, eo_sha = build_live_ladder(
        argparse.Namespace(ladder='ear', energy_table=ENERGY_TABLE, ear_order=EAR_ORDER))
    return list(ladder.cells), {'source': 'ear', 'energy_table_sha256': et_sha, 'ear_order_sha256': eo_sha,
                                'n_cells': len(ladder.cells)}


def finish_clip(audio: np.ndarray, tempo_bpm: float) -> np.ndarray:
    """run_session_v2 trim (8 bars + one crossfade of release), then the live
    tail_out fade (CrossfadeMixer gain_out) over that last quarter bar."""
    from crossfade import _equal_power_gains, bar_duration_frames
    from run_session_v2 import SessionConfigV2

    cfg = SessionConfigV2()
    bar = bar_duration_frames(tempo_bpm, cfg.beats_per_bar, SAMPLE_RATE)
    fade = int(round(bar * cfg.fade_bars))
    clip = audio[:cfg.bars_per_segment * bar + fade].astype(np.float32, copy=True)
    fade = min(fade, clip.shape[0])
    clip[clip.shape[0] - fade:] *= _equal_power_gains(fade)[0][:, None]
    return clip


def _rms_db(a: np.ndarray) -> float:
    return float(20 * np.log10(max(np.sqrt(np.mean(np.square(a, dtype=np.float64))), 1e-12)))


def read_pcm16(path: Path) -> np.ndarray:
    with wave.open(str(path), 'rb') as wf:
        if wf.getsampwidth() != 2 or wf.getnchannels() != 2 or wf.getframerate() != SAMPLE_RATE:
            raise ValueError(f'{path.name}: expected 16-bit stereo {SAMPLE_RATE} Hz')
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype='<i2').reshape(-1, 2)


def clip_stats(pcm: np.ndarray) -> dict[str, Any]:
    """Level checks on the written 16-bit file."""
    x = pcm.astype(np.float64) / 32768.0
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    import pyloudnorm
    return {
        'n_frames': int(pcm.shape[0]), 'duration_s': round(pcm.shape[0] / SAMPLE_RATE, 3),
        'peak_dbfs': round(20 * np.log10(max(peak, 1e-12)), 3), 'rms_dbfs': round(_rms_db(x), 3),
        'lufs': round(float(pyloudnorm.Meter(SAMPLE_RATE).integrated_loudness(x)), 2),
        'n_full_scale': int(np.sum(np.abs(pcm.astype(np.int32)) >= 32767)),
    }


def stimulus_id(kind: str, cell: str, seed: int) -> str:
    return 's' + hashlib.sha256(f'{st.SOURCE_TAG}|{kind}|{cell}|seed{seed}'.encode()).hexdigest()[:7]


def render_one(renderer, kind: str, genre: str, tier: int, seed: int, out_dir: Path) -> dict[str, Any]:
    from segment_renderer import MASTER_GAIN_DB, _write_wav
    from session_generator import SessionSegmentSource
    from stimulus_metrics import midi_sha256

    pm, info = SessionSegmentSource(seed, develop=True).next_segment(genre, tier)   # fresh session, visit 0
    tempo = float(info['tempo_bpm'])
    clip = finish_clip(renderer.render_pm(pm), tempo)
    ref = finish_clip(renderer._render_pm_to_audio(pm, master=False), tempo)
    cell = f'{genre}:{tier}'
    sid = stimulus_id(kind, cell, seed)
    path = out_dir / f'{sid}.wav'
    _write_wav(path, clip, SAMPLE_RATE)
    row = {
        'stimulus_id': sid, 'kind': kind, 'file': path.name, 'cell': cell, 'genre': genre, 'tier': tier,
        'bpm': tempo, 'n_bars': 8, 'stim_seed': seed, 'visit_idx': info['visit_idx'],
        'gen_version': info['gen_version'], 'dev_version': info.get('dev_version'),
        'midi_sha256': midi_sha256(pm), 'audio_sha256': st.file_sha256(path),
        **clip_stats(read_pcm16(path)),
        'master_gain_db': MASTER_GAIN_DB,
        'master_gain_db_measured': round(_rms_db(clip) - _rms_db(ref), 3),
    }
    return row


def level_problems(row: dict[str, Any], master_gain_db: float) -> list[str]:
    sid, out = row['stimulus_id'], []
    if row['n_full_scale']:
        out.append(f"{sid}: {row['n_full_scale']} full-scale samples")
    if row['peak_dbfs'] > PEAK_CEILING_DBFS:
        out.append(f"{sid}: peak {row['peak_dbfs']} dBFS above {PEAK_CEILING_DBFS}")
    if abs(row['master_gain_db_measured'] - master_gain_db) > MASTER_TOLERANCE_DB:
        out.append(f"{sid}: measured master {row['master_gain_db_measured']} dB, expected {master_gain_db}")
    return out


def plan(cells: list[Any]) -> list[tuple[str, str, int, int, Any]]:
    """(kind, genre, tier, seed, ladder cell or None) for every stimulus, in manifest order."""
    out = [('main', c.genre, c.tier, STIM_SEED, c) for c in cells]
    for kind, spec in [('practice', c) for c in PRACTICE_CELLS] + [('volume', VOLUME_CELL)]:
        g, t = spec.split(':')
        out.append((kind, g, int(t), PRACTICE_STIM_SEED, None))
    return out


def render_all(out_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    from segment_renderer import MASTER_GAIN_DB, SymbolicSegmentRenderer

    renderer = SymbolicSegmentRenderer(sf2_path=SF2, sr=SAMPLE_RATE, session_seed=42)
    cells, ladder_info = live_cells()
    if len(cells) != st.N_MAIN:
        raise SystemExit(f'live ladder has {len(cells)} cells, expected {st.N_MAIN}')
    rows, problems = [], []
    for kind, g, t, seed, cell in plan(cells):
        row = render_one(renderer, kind, g, t, seed, out_dir)
        if cell is not None:
            row.update(rung=cell.rung, ladder_u=round(float(cell.u), 4))
        rows.append(row)
        problems += level_problems(row, MASTER_GAIN_DB)
        print(f"  {row['stimulus_id']} {kind:8} {row['cell']:9} {row['bpm']:6.1f} bpm {row['duration_s']:6.2f} s "
              f"peak {row['peak_dbfs']:6.2f} dBFS master {row['master_gain_db_measured']:+.2f} dB", file=sys.stderr)
    main_midi = {r['cell']: r['midi_sha256'] for r in rows if r['kind'] == 'main'}
    for r in rows:
        if r['kind'] != 'main' and r['midi_sha256'] == main_midi.get(r['cell']):
            problems.append(f"{r['stimulus_id']}: {r['kind']} clip repeats the main stimulus of {r['cell']}")
    if problems:
        raise SystemExit('stimulus checks failed:\n  ' + '\n  '.join(problems))
    from session_generator import SessionSegmentSource
    render_info = {
        'sample_rate': SAMPLE_RATE, 'format': 'PCM 16-bit stereo WAV, no metadata chunks',
        'n_bars': 8, 'tail': '0.25 bar of release, live tail_out equal-power fade',
        'renderer': 'SymbolicSegmentRenderer.render_pm (gain 0.8)', 'master_gain_db': MASTER_GAIN_DB,
        'peak_ceiling_dbfs': PEAK_CEILING_DBFS, 'loudness_normalization': 'none (locked levels)',
        'generator': SessionSegmentSource(STIM_SEED, develop=True).config(),
        'main_stimulus': 'fresh session per cell, visit 0', 'practice_stim_seed': PRACTICE_STIM_SEED,
        'practice_cells': list(PRACTICE_CELLS), 'volume_cell': VOLUME_CELL,
    }
    return rows, render_info, ladder_info


# =============================================================================
# Commands
# =============================================================================

def cmd_build(out_dir: Path) -> int:
    if (out_dir / st.MANIFEST_NAME).exists():
        raise SystemExit(f'{out_dir} is already frozen (manifest.json exists); use verify, or build elsewhere')
    if any(out_dir.glob('*.wav')):
        raise SystemExit(f'{out_dir} has WAV files but no manifest; move them away first')
    prov = provenance()
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, render_info, ladder_info = render_all(out_dir)
    manifest = {
        'schema': st.MANIFEST_SCHEMA, 'source_tag': st.SOURCE_TAG, 'stim_seed': STIM_SEED,
        'built_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
        'provenance': prov, 'ladder': ladder_info, 'render': render_info, 'stimuli': rows,
    }
    (out_dir / st.MANIFEST_NAME).write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    _, sha = st.verify_stimuli(out_dir)
    print(f'froze {len(rows)} stimuli in {out_dir}; manifest sha256 {sha}')
    return 0


def cmd_verify(stim_dir: Path) -> int:
    manifest, sha = st.verify_stimuli(stim_dir)
    print(f'files: {len(manifest["stimuli"])} stimuli match manifest {sha[:16]}')
    prov = provenance()
    for key in ('source_commit', 'fluidsynth'):
        if prov[key] != manifest['provenance'][key]:
            raise SystemExit(f'{key} {prov[key]} differs from the build ({manifest["provenance"][key]})')
    with tempfile.TemporaryDirectory() as td:
        rows, _, _ = render_all(Path(td))
    want = {s['stimulus_id']: s for s in manifest['stimuli']}
    bad = [f"{r['stimulus_id']}: {k}" for r in rows for k in ('midi_sha256', 'audio_sha256')
           if want.get(r['stimulus_id'], {}).get(k) != r[k]]
    if bad or set(want) != {r['stimulus_id'] for r in rows}:
        raise SystemExit('regeneration differs from the frozen set:\n  ' + '\n  '.join(bad or ['stimulus IDs differ']))
    print(f'regeneration: {len(rows)} stimuli byte-identical (MIDI and audio)')
    return 0


def cmd_archive(stim_dir: Path, out: Path) -> int:
    import io
    import tarfile

    manifest, sha = st.verify_stimuli(stim_dir)
    name = f'music-rating-stimuli-{sha[:12]}'
    tar_path = Path(out) / f'{name}.tar'
    if tar_path.exists():
        raise SystemExit(f'{tar_path} already exists; not overwriting')
    files = {s['file']: (stim_dir / s['file']).read_bytes() for s in manifest['stimuli']}
    files['manifest.json'] = (stim_dir / st.MANIFEST_NAME).read_bytes()
    files['MANIFEST_SHA256'] = f'{sha}  manifest.json\n'.encode()
    files['SOURCE_TAG'] = (f"{st.SOURCE_TAG}\n{manifest['provenance']['source_commit']}\n").encode()
    files['SHA256SUMS'] = ''.join(f'{hashlib.sha256(b).hexdigest()}  {n}\n'
                                  for n, b in sorted(files.items())).encode()
    Path(out).mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, 'x', format=tarfile.USTAR_FORMAT) as tf:
        for n in sorted(files):
            info = tarfile.TarInfo(f'{name}/{n}')
            info.size, info.mtime, info.mode = len(files[n]), 0, 0o444
            tf.addfile(info, io.BytesIO(files[n]))
    tar_sha = st.file_sha256(tar_path)
    (Path(out) / f'{name}.tar.sha256').write_text(f'{tar_sha}  {tar_path.name}\n', encoding='utf-8')
    print(f'{tar_path}  ({len(manifest["stimuli"])} WAVs + manifest)\ntar sha256 {tar_sha}\nmanifest sha256 {sha}')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('command', choices=('build', 'verify', 'archive'))
    ap.add_argument('--stim-dir', type=Path, default=st.STIM_DIR)
    ap.add_argument('--out', type=Path, help='archive: destination folder (outside the repository)')
    args = ap.parse_args(argv)
    if args.command == 'archive':
        if args.out is None:
            ap.error('archive needs --out')
        return cmd_archive(args.stim_dir, args.out)
    if args.command == 'build':
        return cmd_build(args.stim_dir)
    return cmd_verify(args.stim_dir)


if __name__ == '__main__':
    sys.exit(main())
