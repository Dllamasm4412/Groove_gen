"""
Smoke test for SymbolicSegmentRenderer — proves M0.5 Step 1 works on your Mac.

Prerequisites (one-time)
------------------------
    brew install fluid-synth
    pip install pretty_midi numpy

Run
---
    cd /Users/daniel/Desktop/PhD/groove_gen_project/
    python groovegen_pilot/test_segment_renderer.py

What it checks
--------------
    1. composer.py and segment_renderer.py import cleanly
    2. fluidsynth is on PATH
    3. Musyng_Kite.sf2 is at the expected location
    4. All four genres render to non-silent stereo audio
    5. Genre alias 'r&b' resolves to 'rnb'
    6. Determinism: same session_seed + same segment_idx == bit-identical audio
    7. Ladder cap: calm@tier=5 renders same audio as calm@tier=2

Outputs
-------
    ./renderer_smoke_out/<genre>_tier<T>.wav   — six WAVs, listen to any of them.
    Console:                                    PASS/FAIL for each check.
"""

from __future__ import annotations

import sys
from pathlib import Path
import numpy as np

# Repo layout assumption: this test lives in groovegen_pilot/ next to
# composer.py and segment_renderer.py. Adjust if you place them elsewhere.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from segment_renderer import SymbolicSegmentRenderer, _norm_genre, _write_wav
from composer import GENRE_CFG


# Expected repo layout: soundfont at repo root
REPO_ROOT = HERE.parent
DEFAULT_SF2 = REPO_ROOT / 'Musyng_Kite.sf2'


def _pass(msg: str) -> None:
    print(f'  [PASS] {msg}')


def _fail(msg: str) -> None:
    print(f'  [FAIL] {msg}')


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--sf2', default=str(DEFAULT_SF2),
                   help=f'Path to Musyng_Kite.sf2 (default: {DEFAULT_SF2})')
    p.add_argument('--out-dir', default=str(HERE / 'renderer_smoke_out'))
    args = p.parse_args()

    sf2_path = Path(args.sf2)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)

    print('=' * 60)
    print('SymbolicSegmentRenderer — M0.5 Step 1 smoke test')
    print('=' * 60)
    print(f'  sf2: {sf2_path}')
    print(f'  out: {out_dir}\n')

    fails = 0

    # ---- 1. Sanity: soundfont exists ----
    print('1. Preflight')
    if not sf2_path.exists():
        _fail(f'soundfont not found at {sf2_path}')
        print('     Fix: move Musyng_Kite.sf2 to your repo root, or pass --sf2 PATH')
        return 1
    _pass(f'soundfont found ({sf2_path.stat().st_size / 1e6:.0f} MB)')

    # ---- 2. Construction ----
    print('\n2. Construction')
    try:
        r = SymbolicSegmentRenderer(sf2_path=sf2_path, session_seed=42)
        _pass('renderer constructed (fluidsynth OK, sf2 OK)')
    except (FileNotFoundError, RuntimeError) as e:
        _fail(f'construction failed: {e}')
        return 1

    # ---- 3. Per-genre render ----
    print('\n3. Per-genre render (tier=3, 8 bars)')
    genres = ['calm', 'pop', 'rnb', 'latin']
    for g in genres:
        cfg = GENRE_CFG[g]
        tempo = cfg['tempo_default']
        try:
            audio = r.render_segment(g, tempo_bpm=tempo, tier=3, n_bars=8,
                                     segment_idx=hash(g) & 0xFFFF)
        except Exception as e:
            _fail(f'{g}: render raised {type(e).__name__}: {e}')
            fails += 1
            continue
        # Check shape and non-silence
        if audio.ndim != 2 or audio.shape[1] != 2 or audio.dtype != np.float32:
            _fail(f'{g}: bad shape/dtype {audio.shape} {audio.dtype}')
            fails += 1
            continue
        peak = float(np.max(np.abs(audio)))
        if peak < 0.01:
            _fail(f'{g}: audio silent (peak={peak:.4f})')
            fails += 1
            continue
        rms = float(np.sqrt(np.mean(audio ** 2)))
        out_path = out_dir / f'{g}_tier3.wav'
        _write_wav(out_path, audio, r.sr)
        _pass(f'{g:6}: {audio.shape[0]:>8} samples, peak={peak:.3f} rms={rms:.3f} -> {out_path.name}')

    # ---- 4. Genre alias ----
    print('\n4. Genre alias')
    try:
        norm = _norm_genre('r&b')
        assert norm == 'rnb', f'r&b normalized to {norm!r}, expected rnb'
        _pass("'r&b' -> 'rnb'")
    except Exception as e:
        _fail(str(e))
        fails += 1

    # ---- 5. Determinism ----
    print('\n5. Determinism')
    a1 = r.render_segment('pop', tempo_bpm=118, tier=3, n_bars=4, segment_idx=999)
    a2 = r.render_segment('pop', tempo_bpm=118, tier=3, n_bars=4, segment_idx=999)
    if np.array_equal(a1, a2):
        _pass('same (session_seed, segment_idx) -> bit-identical audio')
    else:
        max_diff = float(np.max(np.abs(a1 - a2)))
        _fail(f'non-deterministic: max sample diff = {max_diff:.6f}')
        fails += 1

    # ---- 6. Ladder cap (calm@5 must == calm@2) ----
    print('\n6. Ladder monotonicity (RUNG_TIER_CAP)')
    a_calm5 = r.render_segment('calm', tempo_bpm=65, tier=5, n_bars=4, segment_idx=1)
    a_calm2 = r.render_segment('calm', tempo_bpm=65, tier=2, n_bars=4, segment_idx=1)
    if np.array_equal(a_calm5, a_calm2):
        _pass('calm@tier=5 clamped to calm@tier=2 (ladder invariant holds)')
    else:
        _fail('calm@5 != calm@2 — RUNG_TIER_CAP not applied')
        fails += 1

    # ---- Summary ----
    print('\n' + '=' * 60)
    if fails == 0:
        print('ALL CHECKS PASSED')
        print('=' * 60)
        print(f'\nListen to any WAV in {out_dir}:')
        print(f'  open {out_dir}')
        return 0
    else:
        print(f'{fails} FAILURE(S) — see above')
        print('=' * 60)
        return 1


if __name__ == '__main__':
    sys.exit(main())
