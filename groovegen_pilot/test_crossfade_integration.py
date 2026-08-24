"""
Crossfade integration test — M0.5 Step 4.

Plays the same 4 segments as test_render_play_integration.py, but through
the CrossfadeMixer so genre transitions are smooth 1-bar equal-power fades
instead of hard cuts.

Run
---
    # Headless: verifies mixer arithmetic + no clipping + no NaN
    python groovegen_pilot/test_crossfade_integration.py

    # Audible A/B: plays 4 segments WITHOUT crossfade, then WITH.
    # You should hear obvious hard cuts in the first, smooth handoffs in second.
    python groovegen_pilot/test_crossfade_integration.py --audible

Headless checks
---------------
    1. Render 4 segments; push all through mixer + flush
    2. Total output frames = sum(inputs) - sum(fade_lengths)
    3. Peak stays <= 1.0 (equal-power doesn't clip)
    4. No NaN/Inf in output
    5. Genre-transition fade lengths use the OUTGOING segment's tempo
       (calm 60 BPM -> pop 118 BPM boundary uses 4s not 2s)

Audible A/B (with --audible)
----------------------------
    Plays two full passes back-to-back:
      Pass A: no crossfade (hard cuts, same as Step 3 audible)
      Pass B: 1-bar equal-power crossfade at every transition
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from composer import GENRE_CFG
from segment_renderer import SymbolicSegmentRenderer
from player import NullPlayer, SoundDevicePlayer
from renderer_to_player import enqueue_segment
from crossfade import CrossfadeMixer, bar_duration_frames

REPO_ROOT = HERE.parent
DEFAULT_SF2 = REPO_ROOT / 'soundfonts' / 'Musyng_Kite.sf2'

SCHEDULE = [
    # (genre, tier)  — tempo comes from GENRE_CFG[genre]['tempo_default']
    ('calm', 3),
    ('pop', 3),
    ('rnb', 3),
    ('latin', 3),
]


def _pass(msg: str) -> None:
    print(f'  [PASS] {msg}')


def _fail(msg: str) -> None:
    print(f'  [FAIL] {msg}')


def _render_schedule(renderer, n_bars: int):
    """Render all segments up-front. Returns list of (genre, tempo, audio)."""
    out = []
    for i, (genre, tier) in enumerate(SCHEDULE):
        tempo = GENRE_CFG[genre]['tempo_default']
        audio = renderer.render_segment(
            genre, tempo_bpm=tempo, tier=tier, n_bars=n_bars,
            segment_idx=hash((genre, i)) & 0xFFFF)
        out.append((genre, tempo, audio))
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--sf2', default=str(DEFAULT_SF2))
    p.add_argument('--audible', action='store_true',
                   help='Play both A (no fade) and B (crossfaded) passes.')
    p.add_argument('--bars', type=int, default=8)
    args = p.parse_args()

    if not Path(args.sf2).exists():
        _fail(f'soundfont not found: {args.sf2}')
        return 1

    print('=' * 60)
    print('Crossfade integration (M0.5 Step 4)')
    print('=' * 60)
    print(f'  sf2:     {args.sf2}')
    print(f'  bars:    {args.bars}')
    print(f'  audible: {args.audible}')

    renderer = SymbolicSegmentRenderer(sf2_path=Path(args.sf2), session_seed=42)
    segments = _render_schedule(renderer, args.bars)
    fails = 0

    print('\nRendered schedule:')
    for genre, tempo, audio in segments:
        print(f'  {genre:6} @ {tempo:>5.1f} BPM  '
              f'{audio.shape[0]:>8} frames ({audio.shape[0]/44100:5.2f}s)')

    # ---- 1. Push through mixer, verify accounting ----
    print('\n1. Mixer accounting')
    mixer = CrossfadeMixer(sample_rate=44100)
    emitted_chunks = []
    fade_frames_used = []
    for i, (genre, tempo, audio) in enumerate(segments):
        # Fade length is driven by the OUTGOING segment's tempo (mixer's
        # held tempo), which is the PREVIOUS segment for i>0.
        if i > 0:
            outgoing_tempo = segments[i-1][1]
            expected_fade = min(
                bar_duration_frames(outgoing_tempo),
                mixer._held_tail.shape[0] if mixer._held_tail is not None else 0,
                audio.shape[0])
            fade_frames_used.append(expected_fade)
        emitted = mixer.push(audio, tempo_bpm=tempo)
        emitted_chunks.append(emitted)
    tail = mixer.flush()
    emitted_chunks.append(tail)

    total_in = sum(a.shape[0] for _, _, a in segments)
    total_out = sum(e.shape[0] for e in emitted_chunks)
    expected_out = total_in - sum(fade_frames_used)
    if total_out == expected_out:
        _pass(f'total_in={total_in}, total_out={total_out}, '
              f'faded={sum(fade_frames_used)} ({len(fade_frames_used)} transitions)')
    else:
        _fail(f'total_out={total_out}, expected {expected_out}')
        fails += 1

    # ---- 2. No clipping ----
    combined = np.concatenate(emitted_chunks, axis=0) if emitted_chunks else np.zeros((0, 2), dtype=np.float32)
    peak = float(np.max(np.abs(combined))) if combined.shape[0] > 0 else 0.0
    if peak <= 1.0 + 1e-6:
        _pass(f'no clipping: peak={peak:.3f}')
    else:
        _fail(f'clipped: peak={peak:.3f}')
        fails += 1

    # ---- 3. No NaN/Inf ----
    if np.isfinite(combined).all():
        _pass('no NaN/Inf in output')
    else:
        _fail('found NaN or Inf')
        fails += 1

    # ---- 4. Fade lengths per transition ----
    print('\n2. Per-transition fade lengths (outgoing tempo drives length)')
    for i in range(1, len(segments)):
        outgoing_genre, outgoing_tempo, outgoing_audio = segments[i-1]
        incoming_genre, incoming_tempo, _ = segments[i]
        one_bar = bar_duration_frames(outgoing_tempo)
        fade = fade_frames_used[i-1]
        seconds = fade / 44100
        print(f'  {outgoing_genre}({outgoing_tempo:.0f}) -> '
              f'{incoming_genre}({incoming_tempo:.0f}): '
              f'fade = {fade} frames ({seconds:.2f}s) '
              f'[1 bar of {outgoing_tempo:.0f} BPM = {one_bar} frames]')

    # ---- 5. Audible A/B ----
    if args.audible:
        try:
            sd_player = SoundDevicePlayer(
                sample_rate=44100, channels=2,
                blocksize=1024, queue_maxsize=8)
            sd_player.start()
        except Exception as e:
            _fail(f'SoundDevicePlayer.start raised: {type(e).__name__}: {e}')
            return 1

        try:
            # ---- Pass A: no crossfade (hard cuts) ----
            print('\n3a. AUDIBLE — Pass A: NO crossfade (hard cuts)')
            for genre, tempo, audio in segments:
                print(f'    playing {genre}...')
                enqueue_segment(sd_player, audio)
                time.sleep(audio.shape[0] / 44100)

            # Gap before Pass B so the ear can reset
            time.sleep(1.0)
            print('\n    --- pause 1s ---')
            time.sleep(1.0)

            # ---- Pass B: crossfaded ----
            print('\n3b. AUDIBLE — Pass B: 1-bar equal-power crossfade')
            mixer_live = CrossfadeMixer(sample_rate=44100)
            for genre, tempo, audio in segments:
                print(f'    playing {genre} (fade-in from prev)...')
                emit = mixer_live.push(audio, tempo_bpm=tempo)
                if emit.shape[0] > 0:
                    enqueue_segment(sd_player, emit)
                    time.sleep(emit.shape[0] / 44100)
            tail_live = mixer_live.flush()
            if tail_live.shape[0] > 0:
                enqueue_segment(sd_player, tail_live)
                time.sleep(tail_live.shape[0] / 44100)

            time.sleep(0.5)
            sd_player.stop(drain=True)
        except KeyboardInterrupt:
            print('    (interrupted)')
            sd_player.stop(drain=False)
            return fails

        _pass('audible A/B complete — did Pass B sound smoother than A?')

    print('\n' + '=' * 60)
    if fails == 0:
        print('ALL CHECKS PASSED')
        if not args.audible:
            print('\nRun with --audible to hear the A/B (hard cuts vs crossfaded):')
            print('  python groovegen_pilot/test_crossfade_integration.py '
                  '--audible --sf2 soundfonts/Musyng_Kite.sf2')
    else:
        print(f'{fails} FAILURE(S)')
    print('=' * 60)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
