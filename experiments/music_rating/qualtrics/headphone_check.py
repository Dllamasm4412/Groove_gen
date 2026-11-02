"""
Headphone screening sounds for the remote study: a Huggins-pitch (HP) test
after Milne et al. (2021, Behavior Research Methods, "An online headphone
screening test based on dichotic pitch").

Each trial is one stereo WAV with three 1 s white-noise intervals (0.5 s
gaps). Two intervals are diotic (identical noise in both ears). In the third,
a narrow band around HP_F0 is phase-inverted in the right channel only. Over
headphones this produces a faint tone; over loudspeakers the channels mix in
the air and it is largely inaudible. The participant reports which interval
held the tone.

The parameters below are this implementation's reading of the paper; the
researcher should confirm them against the paper and check by ear (tone
audible on headphones, not on laptop speakers) before use. Sounds are
generated here (deterministic seed), not copied from the paper's materials.

Usage (from the repository root):
    .venv/bin/python experiments/music_rating/qualtrics/headphone_check.py build
writes qualtrics/headphone/hp1..hp6.wav (gitignored), manifest.json and
answer_key.csv; refuses to overwrite an existing manifest. `verify` rebuilds
in a temporary folder and requires identical bytes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / 'headphone'
SCHEMA = 'groovegen-headphone-check/1'

SR = 44100
HP_F0 = 600.0            # Hz, centre of the phase-inverted band
HP_HALF_BW = 0.06        # band = HP_F0 * (1 +/- 6 %)
INTERVAL_S = 1.0
GAP_S = 0.5
RAMP_S = 0.02            # raised-cosine on/offset per interval
RMS_DBFS = -23.0         # per channel; in the range of the music clips' loudness
N_TRIALS = 6
SEED = 20261012
PASS_MIN_CORRECT = 5     # of 6; researcher decision (confirm against Milne et al. 2021)


def _ramp(n: int) -> np.ndarray:
    r = int(RAMP_S * SR)
    env = np.ones(n)
    up = 0.5 - 0.5 * np.cos(np.pi * np.arange(r) / r)
    env[:r], env[n - r:] = up, up[::-1]
    return env


def interval(rng: np.random.Generator, huggins: bool) -> np.ndarray:
    """(n, 2) float: diotic noise, or noise with the HP band inverted in the right ear."""
    n = int(INTERVAL_S * SR)
    left = rng.standard_normal(n)
    right = left.copy()
    if huggins:
        spec = np.fft.rfft(left)
        f = np.fft.rfftfreq(n, 1 / SR)
        band = (f >= HP_F0 * (1 - HP_HALF_BW)) & (f <= HP_F0 * (1 + HP_HALF_BW))
        spec[band] *= -1
        right = np.fft.irfft(spec, n)
    gain = 10 ** (RMS_DBFS / 20) / np.sqrt(np.mean(left ** 2))
    env = _ramp(n) * gain
    return np.stack([left * env, right * env], axis=1)


def answer_positions(rng: np.random.Generator) -> list[int]:
    """Interval (1-3) holding the tone in each trial; each position twice."""
    pos = [1, 2, 3] * (N_TRIALS // 3)
    rng.shuffle(pos)
    return pos


def trial_audio(rng: np.random.Generator, answer: int) -> np.ndarray:
    gap = np.zeros((int(GAP_S * SR), 2))
    parts = []
    for i in (1, 2, 3):
        parts.append(interval(rng, huggins=i == answer))
        if i < 3:
            parts.append(gap)
    return np.concatenate(parts)


def to_pcm16(x: np.ndarray) -> bytes:
    if np.max(np.abs(x)) >= 0.99:
        raise ValueError('headphone check sound would clip')
    return np.round(x * 32767).astype('<i2').tobytes()


def write_wav(path: Path, x: np.ndarray) -> None:
    with wave.open(str(path), 'wb') as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(to_pcm16(x))


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(out: Path) -> dict:
    rng = np.random.default_rng(SEED)
    answers = answer_positions(rng)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for n, ans in enumerate(answers, 1):
        path = out / f'hp{n}.wav'
        write_wav(path, trial_audio(rng, ans))
        rows.append({'id': f'hp{n}', 'file': path.name, 'answer': ans, 'audio_sha256': sha256(path)})
    manifest = {
        'schema': SCHEMA, 'method': 'Huggins pitch after Milne et al. (2021)',
        'params': {'sr': SR, 'hp_f0_hz': HP_F0, 'hp_half_bandwidth': HP_HALF_BW, 'interval_s': INTERVAL_S,
                   'gap_s': GAP_S, 'ramp_s': RAMP_S, 'rms_dbfs': RMS_DBFS, 'seed': SEED,
                   'interval_times_s': [[0, 1], [1.5, 2.5], [3, 4]]},
        'pass_min_correct': PASS_MIN_CORRECT, 'trials': rows,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n', encoding='utf-8')
    with (out / 'answer_key.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['question', 'correct_choice'])
        w.writerows([[r['id'], r['answer']] for r in rows])
    return manifest


def load_manifest(folder: Path = OUT_DIR) -> dict:
    path = Path(folder) / 'manifest.json'
    if not path.exists():
        raise SystemExit(f'no headphone manifest at {path}; run headphone_check.py build')
    return json.loads(path.read_text(encoding='utf-8'))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('command', choices=('build', 'verify'))
    ap.add_argument('--out', type=Path, default=OUT_DIR)
    args = ap.parse_args(argv)
    if args.command == 'build':
        if (args.out / 'manifest.json').exists():
            raise SystemExit(f'{args.out} already has a manifest; use verify')
        m = build(args.out)
        print(f"wrote {len(m['trials'])} trials to {args.out}; answers {[t['answer'] for t in m['trials']]}")
        return 0
    want = load_manifest(args.out)
    with tempfile.TemporaryDirectory() as td:
        got = build(Path(td))
    bad = [t['id'] for t, g in zip(want['trials'], got['trials']) if t != g]
    for t in want['trials']:
        if sha256(args.out / t['file']) != t['audio_sha256']:
            bad.append(f"{t['id']} file")
    if bad or want['params'] != got['params']:
        raise SystemExit(f'headphone check differs from a fresh build: {bad or "params"}')
    print(f"headphone check: {len(want['trials'])} files match manifest and regenerate identically")
    return 0


if __name__ == '__main__':
    sys.exit(main())
