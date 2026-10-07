"""Fixtures: a small synthetic stimulus set with the live ladder's genre mix
(fast, no fluidsynth), and helpers to drive a session."""

from __future__ import annotations

import hashlib
import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import stimuli as st  # noqa: E402

# The live ladder's 27 cells in rung order (energy_order_by_ear.json).
LADDER = ['calm:1', 'calm:2', 'lofi:1', 'hiphop:1', 'lofi:2', 'lofi:3', 'hiphop:2', 'latin:1', 'rnb:1',
          'rock:1', 'rnb:2', 'rnb:3', 'latin:2', 'rnb:4', 'latin:3', 'rock:2', 'pop:1', 'pop:2', 'pop:3',
          'hiphop:3', 'pop:4', 'pop:5', 'hiphop:4', 'rock:3', 'hiphop:5', 'rock:4', 'rock:5']
SR = 44100


def write_wav(path: Path, idx: int, n: int = 2205) -> None:
    rng = np.random.default_rng(idx)
    pcm = (rng.standard_normal((n, 2)) * 1000).astype('<i2')
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())


def make_stim_set(folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    specs = [('main', c, 1) for c in LADDER] + [('practice', 'lofi:2', 2), ('practice', 'pop:4', 2),
                                                 ('volume', 'pop:3', 2)]
    rows = []
    for i, (kind, cell, seed) in enumerate(specs):
        sid = 's' + hashlib.sha256(f'test|{kind}|{cell}|{seed}'.encode()).hexdigest()[:7]
        path = folder / f'{sid}.wav'
        write_wav(path, i)
        g, t = cell.split(':')
        row = {'stimulus_id': sid, 'kind': kind, 'file': path.name, 'cell': cell, 'genre': g, 'tier': int(t),
               'bpm': 100.0, 'stim_seed': seed, 'duration_s': 0.05, 'audio_sha256': st.file_sha256(path)}
        if kind == 'main':
            row['rung'] = i
        rows.append(row)
    manifest = {'schema': st.MANIFEST_SCHEMA, 'source_tag': st.SOURCE_TAG,
                'provenance': {'source_commit': '0' * 40}, 'stimuli': rows}
    write_manifest(folder, manifest)
    return manifest


def write_manifest(folder: Path, manifest: dict) -> None:
    (folder / st.MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding='utf-8')


@pytest.fixture
def stim_dir(tmp_path) -> Path:
    d = tmp_path / 'stimuli'
    make_stim_set(d)
    return d


@pytest.fixture
def loaded(stim_dir):
    manifest, sha = st.verify_stimuli(stim_dir)
    return stim_dir, manifest, sha


@pytest.fixture
def new_session(tmp_path, loaded):
    import session_store as ss

    stim_dir, manifest, sha = loaded
    root = tmp_path / 'data'

    def make(code='P001'):
        return ss.Session.create(root, code, manifest, sha, stim_dir, {'test': True})
    make.root = root
    return make


def run_to_trials(sess) -> None:
    sess.advance('welcome')
    sess.advance('instructions')
    sess.volume_played()
    sess.advance('volume')


def do_trial(sess, d=40, c=60):
    seq = sess.meta['next_seq']
    sess.play_start(seq)
    sess.play_end(seq, {'played_s': 0.05})
    return sess.submit(seq, {'danceability': d, 'calming': c, 'touched_danceability': True,
                             'touched_calming': True, 'latency_ms': 1234.5})
