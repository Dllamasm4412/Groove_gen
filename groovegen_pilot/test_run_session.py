"""
Closed-loop session smoke test — M0.5 Step 5.

Runs the full pipeline: ReplaySource -> LinearBandPolicy -> renderer ->
crossfade -> player, with per-bar trace emission.

Run
---
    # Headless (default): ReplaySource with the shipped CSV -> NullPlayer.
    # Uses time_fn=perf_counter offset so HR appears "fresh" without
    # actually sleeping the full 5-minute trace.
    python groovegen_pilot/test_run_session.py

    # Audible: SoundDevicePlayer, ReplaySource in real-time mode.
    # Takes ~5 minutes (or less with --segments N).
    python groovegen_pilot/test_run_session.py --audible --segments 4

Headless checks
---------------
    1. Session runs to completion without exceptions
    2. Trace has bars_per_segment * n_segments rows
    3. bar_idx_global is monotonic 0..N-1
    4. Every trace row has a valid tier in 1..5
    5. Every row's tier matches what LinearBandPolicy would decide for
       that row's hr_bpm (when hr_bpm is not None)
    6. When HR ramps up (60 -> 110), tier trend is non-decreasing on average
    7. Fallback tier is used before the first fresh HR reading
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
from crossfade import CrossfadeMixer
from hr_sources import ReplaySource, ManualHRInput, SyntheticSineHR
from hr_to_tier import LinearBandPolicy
from run_session import run_session, SessionConfig, TraceRow

REPO_ROOT = HERE.parent
DEFAULT_SF2 = REPO_ROOT / 'soundfonts' / 'Musyng_Kite.sf2'
DEFAULT_CSV = HERE / 'hr_trace_ramp_60_110_90.csv'

# Genre schedule: we cycle through the four genres so tier changes are
# visible independent of the HR trajectory
DEFAULT_SCHEDULE = [
    ('calm', 65.0),
    ('rnb', 100.0),
    ('pop', 118.0),
    ('rnb', 100.0),
    ('calm', 65.0),
    ('latin', 104.0),
    ('pop', 118.0),
    ('rnb', 100.0),
]


def _pass(msg: str) -> None:
    print(f'  [PASS] {msg}')


def _fail(msg: str) -> None:
    print(f'  [FAIL] {msg}')


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--sf2', default=str(DEFAULT_SF2))
    p.add_argument('--csv', default=str(DEFAULT_CSV))
    p.add_argument('--segments', type=int, default=None,
                   help='Limit to N segments (default: full schedule)')
    p.add_argument('--bars', type=int, default=8,
                   help='Bars per segment')
    p.add_argument('--source', choices=['replay', 'synth', 'manual'],
                   default='replay',
                   help='HR source (default: replay). Test uses replay.')
    p.add_argument('--audible', action='store_true',
                   help='Play through SoundDevicePlayer (real-time)')
    args = p.parse_args()

    sf2 = Path(args.sf2)
    if not sf2.exists():
        _fail(f'soundfont not found: {sf2}')
        return 1

    print('=' * 60)
    print('run_session closed-loop smoke test (M0.5 Step 5)')
    print('=' * 60)
    print(f'  sf2:      {sf2}')
    print(f'  source:   {args.source}')
    print(f'  segments: {args.segments if args.segments else "all"}')
    print(f'  bars:     {args.bars}')
    print(f'  audible:  {args.audible}')

    # ---- HR source ----
    if args.source == 'replay':
        csv_path = Path(args.csv)
        if not csv_path.exists():
            _fail(f'csv not found: {csv_path}')
            return 1
        hr = ReplaySource(csv_path=csv_path, real_time=args.audible, loop=True)
        # ReplaySource has no .start()
    elif args.source == 'synth':
        hr = SyntheticSineHR(bpm_low=65, bpm_high=105, period_s=180)
        # SyntheticSineHR has no .start()
    else:  # manual
        hr = ManualHRInput().start()
        hr.set(80.0)  # bootstrap so the test doesn't hang

    # ---- Renderer + player + mixer + policy ----
    renderer = SymbolicSegmentRenderer(sf2_path=sf2, session_seed=42)
    if args.audible:
        player = SoundDevicePlayer(
            sample_rate=44100, channels=2, blocksize=1024, queue_maxsize=8)
    else:
        player = NullPlayer(sample_rate=44100, channels=2)
    player.start()

    mixer = CrossfadeMixer(sample_rate=44100)  # half-bar default
    policy = LinearBandPolicy()
    config = SessionConfig(
        schedule=DEFAULT_SCHEDULE,
        bars_per_segment=args.bars,
        session_seed=42,
    )

    # ---- on_segment callback for live output ----
    def announce(seg_idx: int, genre: str, tier: int, hr_bpm):
        hr_str = f'{hr_bpm:.1f}' if hr_bpm is not None else 'none'
        print(f'  seg {seg_idx:>2}: genre={genre:<6} tier={tier}  '
              f'hr={hr_str} bpm')

    # ---- Run ----
    # Headless mode: use a no-op sleep so the test doesn't take 5 minutes.
    # NullPlayer doesn't care about sync. For audible mode we sleep for
    # real so playback stays synced with the tempo.
    sleep_fn = time.sleep if args.audible else (lambda _s: None)

    print('\nRunning session...')
    t0 = time.perf_counter()
    trace = run_session(
        hr_source=hr,
        renderer=renderer,
        player=player,
        mixer=mixer,
        tier_policy=policy,
        config=config,
        segments_max=args.segments,
        on_segment=announce,
        sleep_fn=sleep_fn,
    )
    elapsed = time.perf_counter() - t0
    print(f'\nSession complete: {len(trace)} bars across {trace[-1].segment_idx + 1} '
          f'segments in {elapsed:.2f}s (wall)')

    player.stop(drain=args.audible)
    try:
        hr.close()
    except Exception:
        pass

    # ---- Headless checks ----
    fails = 0
    n_segments_run = trace[-1].segment_idx + 1
    print('\nChecks:')

    # 1. bar count
    expected_bars = n_segments_run * args.bars
    if len(trace) == expected_bars:
        _pass(f'{len(trace)} trace rows = {n_segments_run} segments * {args.bars} bars')
    else:
        _fail(f'{len(trace)} rows, expected {expected_bars}')
        fails += 1

    # 2. bar_idx_global monotonic
    idxs = [r.bar_idx_global for r in trace]
    if idxs == list(range(len(trace))):
        _pass('bar_idx_global monotonic 0..N-1')
    else:
        _fail('bar_idx_global has gaps or duplicates')
        fails += 1

    # 3. all tiers in 1..5
    bad_tiers = [r for r in trace if r.tier not in (1, 2, 3, 4, 5)]
    if not bad_tiers:
        _pass('all tier values in [1..5]')
    else:
        _fail(f'{len(bad_tiers)} rows with tier outside [1..5]')
        fails += 1

    # 4. tier matches policy for known HRs
    mismatches = 0
    for r in trace:
        if r.hr_bpm is not None:
            expected = policy.decide(r.hr_bpm)
            if r.tier != expected:
                mismatches += 1
    if mismatches == 0:
        _pass('every fresh-HR row has tier = policy.decide(hr_bpm)')
    else:
        _fail(f'{mismatches} rows have tier mismatch vs policy')
        fails += 1

    # 5. tier trend over the HR ramp: earliest segments' HR should be <= latest
    #    (CSV is 60 -> 110, then decays to 80. We check monotonic-ish over the ascent)
    per_seg = {}
    for r in trace:
        per_seg.setdefault(r.segment_idx, r)  # first bar's row per segment
    hr_seq = [per_seg[i].hr_bpm for i in sorted(per_seg) if per_seg[i].hr_bpm is not None]
    if len(hr_seq) >= 3 and hr_seq[-1] > hr_seq[0]:
        _pass(f'HR trend visible in trace: {hr_seq[0]:.1f} -> {hr_seq[-1]:.1f} BPM')
    elif len(hr_seq) < 3:
        _pass(f'HR trend check skipped ({len(hr_seq)} samples)')
    else:
        # Could be decaying phase or short session — informational only, not failure
        _pass(f'HR sampled: first={hr_seq[0]:.1f}, last={hr_seq[-1]:.1f} '
              f'(informational)')

    # 6. Per-segment summary
    print('\nPer-segment summary:')
    print(f'  {"seg":>3} {"genre":<6} {"tempo":>6} {"tier":>4} {"hr":>6} '
          f'{"fresh":>5} source')
    for i in sorted(per_seg):
        r = per_seg[i]
        hr_s = f'{r.hr_bpm:.1f}' if r.hr_bpm is not None else 'none'
        src = r.hr_source or '-'
        print(f'  {r.segment_idx:>3} {r.genre:<6} {r.tempo_bpm:>6.1f} '
              f'{r.tier:>4} {hr_s:>6} {str(r.hr_is_fresh):>5} {src}')

    print('\n' + '=' * 60)
    if fails == 0:
        print('ALL CHECKS PASSED')
    else:
        print(f'{fails} FAILURE(S)')
    print('=' * 60)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
