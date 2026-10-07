"""
Frozen stimulus set for Experiment 1 (music perception rating): manifest
loading and integrity checks. No GrooveGen imports: the participant app only
reads the frozen WAVs and the hidden manifest (build_stimuli.py writes both).

The manifest is researcher-only. It maps opaque stimulus IDs to cells; the
participant app never serves it, and WAV files are named only by stimulus ID.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
STIM_DIR = HERE / 'stimuli'
MANIFEST_NAME = 'manifest.json'
MANIFEST_SCHEMA = 'groovegen-music-rating-stimuli/1'
SOURCE_TAG = 'pilot-zero-v2c-locked'

N_MAIN = 27          # every live ladder cell exactly once
N_PRACTICE = 2
N_VOLUME = 1         # headphone / volume check clip
KINDS = {'main': N_MAIN, 'practice': N_PRACTICE, 'volume': N_VOLUME}
GENRES = ('calm', 'lofi', 'rnb', 'pop', 'latin', 'hiphop', 'rock')

# Only these RIFF chunks may appear in a stimulus WAV (no LIST/INFO metadata).
ALLOWED_WAV_CHUNKS = {b'fmt ', b'data'}


class StimulusError(RuntimeError):
    """The frozen stimulus set is missing, altered or inconsistent."""


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def wav_chunk_ids(path: Path) -> list[bytes]:
    data = Path(path).read_bytes()
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise StimulusError(f'{Path(path).name}: not a RIFF/WAVE file')
    ids, i = [], 12
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], int.from_bytes(data[i + 4:i + 8], 'little')
        ids.append(cid)
        i += 8 + size + (size & 1)
    return ids


def load_manifest(stim_dir: Path = STIM_DIR) -> tuple[dict, str]:
    """(manifest, sha256 of manifest.json bytes)."""
    path = Path(stim_dir) / MANIFEST_NAME
    if not path.exists():
        raise StimulusError(f'no manifest at {path}; run build_stimuli.py build first')
    raw = path.read_bytes()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def manifest_problems(manifest: dict, stim_dir: Path, check_audio: bool = True) -> list[str]:
    """Every integrity problem found (empty list = the set is intact)."""
    stim_dir = Path(stim_dir)
    out: list[str] = []
    if manifest.get('schema') != MANIFEST_SCHEMA:
        out.append(f"schema {manifest.get('schema')!r} != {MANIFEST_SCHEMA!r}")
    if manifest.get('source_tag') != SOURCE_TAG:
        out.append(f"source_tag {manifest.get('source_tag')!r} != {SOURCE_TAG!r}")
    stims = manifest.get('stimuli') or []
    for kind, n in KINDS.items():
        got = sum(s.get('kind') == kind for s in stims)
        if got != n:
            out.append(f'{got} {kind} stimuli, expected {n}')
    unknown = {s.get('kind') for s in stims} - set(KINDS)
    if unknown:
        out.append(f'unknown stimulus kinds {sorted(map(str, unknown))}')
    ids = [s.get('stimulus_id') for s in stims]
    dup_ids = sorted({i for i in ids if ids.count(i) > 1}, key=str)
    if dup_ids:
        out.append(f'duplicate stimulus_id {dup_ids}')
    main = [s for s in stims if s.get('kind') == 'main']
    cells = [s.get('cell') for s in main]
    dup_cells = sorted({c for c in cells if cells.count(c) > 1}, key=str)
    if dup_cells:
        out.append(f'duplicate main cells {dup_cells}')
    rungs = sorted(s.get('rung', -1) for s in main)
    if rungs != list(range(len(main))):
        out.append(f'main rungs are not 0..{len(main) - 1} exactly once')
    hashes = [s.get('audio_sha256') for s in stims]
    if len(set(hashes)) != len(hashes):
        out.append('two stimuli have identical audio')
    for s in stims:
        sid, fname = s.get('stimulus_id'), s.get('file')
        if fname != f'{sid}.wav':
            out.append(f'{sid}: file {fname!r} is not named by stimulus ID')
            continue
        if any(g in fname.lower() for g in GENRES):
            out.append(f'{sid}: file name {fname!r} is descriptive')
        path = stim_dir / fname
        if not path.exists():
            out.append(f'{sid}: missing {fname}')
            continue
        if not check_audio:
            continue
        if file_sha256(path) != s.get('audio_sha256'):
            out.append(f'{sid}: audio sha256 mismatch ({fname})')
        try:
            extra = set(wav_chunk_ids(path)) - ALLOWED_WAV_CHUNKS
        except StimulusError as exc:
            out.append(str(exc))
            continue
        if extra:
            out.append(f'{sid}: WAV carries metadata chunks {sorted(e.decode(errors="replace") for e in extra)}')
    listed = {s.get('file') for s in stims}
    stray = sorted(p.name for p in stim_dir.glob('*.wav') if p.name not in listed)
    if stray:
        out.append(f'unlisted WAV files in {stim_dir}: {stray}')
    return out


def verify_stimuli(stim_dir: Path = STIM_DIR, check_audio: bool = True) -> tuple[dict, str]:
    """Load the manifest and refuse (StimulusError) unless the set is intact."""
    manifest, sha = load_manifest(stim_dir)
    problems = manifest_problems(manifest, stim_dir, check_audio)
    if problems:
        raise StimulusError('stimulus set failed integrity check:\n  ' + '\n  '.join(problems))
    return manifest, sha


def by_kind(manifest: dict, kind: str) -> list[dict]:
    return [s for s in manifest['stimuli'] if s['kind'] == kind]
