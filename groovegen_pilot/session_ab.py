"""Same-seed A/B: closed-loop session with vs. without user_descriptor.

Runs run_session_v2 twice against a canned HR replay trace, once with the
descriptor disabled and once with your descriptor loaded. Same seed, same
initial rung, same target, same HR trace, same everything else.

Compares the two rung trajectories and prints where the personalization
tiebreak moved a decision. Optionally writes audio to WAV files so you can
A/B listen.

Usage
-----
Dry run (no audio, fast; still runs the full controller):
    python session_ab.py --descriptor my_descriptor.json --no-audio

With audio to disk (listen in your DAW / VLC):
    python session_ab.py --descriptor my_descriptor.json \
        --wav-a session_none.wav --wav-b session_desc.wav

With live playback (uses SoundDevicePlayer if available):
    python session_ab.py --descriptor my_descriptor.json --play

Notes
-----
- Uses ReplaySource with a canned HR trace CSV (default:
  hr_trace_ramp_60_110_90.csv) so both runs see IDENTICAL HR readings.
- max_segments defaults to 12 (~2 minutes of session at 8 bars/segment).
- Sets a fixed random seed for reproducibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

import numpy as np


def build_controller(ladder, descriptor):
    from control import LadderMPC, ControllerConfig
    cfg = ControllerConfig(
        arousal_mode='arousal_primary',
        user_descriptor=descriptor,
    )
    return LadderMPC(ladder, cfg)


def build_hr_source(csv_path: str):
    """ReplaySource backed by the canned HR ramp CSV."""
    from hr_sources import ReplaySource
    return ReplaySource(csv_path=csv_path)


class _ConstantArousalSource:
    """Fake arousal source that reports a fixed value forever.
    Matches the .poll() -> object with .value, .t_wall, .source_type
    contract expected by run_session_v2."""
    def __init__(self, value: float):
        self.value = float(value)

    def poll(self):
        import time as _t
        from types import SimpleNamespace
        return SimpleNamespace(
            value=self.value,
            t_wall=_t.time(),
            source_type='constant-arousal-ab',
        )


def build_player(want_audio: bool, sr: int):
    from player import NullPlayer
    if want_audio:
        try:
            from player import SoundDevicePlayer
            return SoundDevicePlayer(sample_rate=sr, channels=2)
        except Exception as e:
            print(f'  (SoundDevicePlayer unavailable: {e}; falling back to NullPlayer)')
    return NullPlayer(sample_rate=sr, channels=2)


def run_one(label: str, descriptor, args, wav_out: Optional[Path]) -> list:
    """Run one session and return the list of (seg_idx, rung, genre) tuples."""
    from ladder import build_ladder
    from segment_renderer import SymbolicSegmentRenderer
    from crossfade import CrossfadeMixer
    from run_session_v2 import run_session_v2, SessionConfigV2, TraceRowV2

    L = build_ladder()
    ctrl = build_controller(L, descriptor)

    sr = args.sample_rate
    renderer = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=sr,
                                       session_seed=42)
    player = build_player(args.play, sr)
    mixer = CrossfadeMixer(fade_bars=args.fade_bars)

    hr_source = build_hr_source(args.hr_trace)

    cfg = SessionConfigV2(
        sample_rate=sr,
        bars_per_segment=args.bars,
        fade_bars=args.fade_bars,
        max_segments=args.segments,
    )

    # Capture rendered audio for optional WAV write. We do this by patching
    # renderer.render_segment to also stash its output.
    captured: list[np.ndarray] = []
    if wav_out is not None:
        original = renderer.render_segment
        def _wrapped(*a, **kw):
            out = original(*a, **kw)
            captured.append(out.copy() if hasattr(out, 'copy') else out)
            return out
        renderer.render_segment = _wrapped  # type: ignore

    # Optional constant-arousal source, so arousal_primary mode has a
    # real signal to close the loop on. Without this the controller
    # holds the initial rung because arousal_1_9=None => zero error.
    arousal_source = None
    if args.arousal_report is not None:
        arousal_source = _ConstantArousalSource(args.arousal_report)

    print(f'\n[{label}] running {args.segments} segments...')
    trace = run_session_v2(
        hr_source=hr_source,
        renderer=renderer,
        player=player,
        mixer=mixer,
        ladder=L,
        controller=ctrl,
        config=cfg,
        hr_target_bpm=args.arousal_target,   # arousal_primary: 1-9 target
        hr_baseline_bpm=5.0,                  # arousal-primary neutral baseline
        initial_rung=args.initial_rung,
        arousal_source=arousal_source,
    )

    # Extract rung trajectory
    rungs: list[tuple[int, int, str]] = []
    for seg_idx, row in enumerate(trace):
        # TraceRowV2 fields vary; pull rung/genre defensively
        rung = getattr(row, 'rung', None)
        genre = getattr(row, 'genre', None)
        if rung is None:
            rung = int(getattr(row, 'next_rung', -1))
        if genre is None:
            cell = next((c for c in L.cells if c.rung == rung), None)
            genre = cell.genre if cell else '?'
        rungs.append((seg_idx, int(rung), str(genre)))

    if wav_out is not None and captured:
        try:
            import soundfile as sf
            audio = np.concatenate(captured, axis=0)
            sf.write(str(wav_out), audio, sr)
            print(f'[{label}] wrote {wav_out} ({audio.shape[0]/sr:.1f}s)')
        except ImportError:
            print(f'[{label}] soundfile not available, skipping WAV write')
        except Exception as e:
            print(f'[{label}] WAV write failed: {e}')

    return rungs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--descriptor', required=True,
                    help='Path to my_descriptor.json')
    ap.add_argument('--hr-trace', default='hr_trace_ramp_60_110_90.csv',
                    help='HR trace CSV for ReplaySource (default: canned ramp)')
    ap.add_argument('--segments', type=int, default=12,
                    help='max_segments (default 12 = ~2 min)')
    ap.add_argument('--bars', type=int, default=8,
                    help='bars_per_segment (default 8)')
    ap.add_argument('--fade-bars', type=float, default=0.5,
                    help='crossfade in bars (default 0.5 = half-bar)')
    ap.add_argument('--sample-rate', type=int, default=44100)
    ap.add_argument('--sf2', type=str,
                    default='soundfonts/Musyng_Kite.sf2',
                    help='Soundfont path for SymbolicSegmentRenderer')
    ap.add_argument('--initial-rung', type=int, default=14,
                    help='seed rung; 14 sits in the pop/latin/rnb interleave')
    ap.add_argument('--arousal-target', type=float, default=6.0,
                    help='Russell 1-9 arousal target for arousal_primary mode. '
                         'Passed to controller as hr_target; hr_baseline is set '
                         'to the neutral midpoint (5.0). Use ~6-7 to sit the '
                         'controller in the pop/latin/rnb interleave.')
    ap.add_argument('--arousal-report', type=float, default=None,
                    help='If set, feed this constant arousal value into '
                         'run_session_v2 via a synthetic arousal_source. '
                         'Default: no arousal source (controller runs cold '
                         'with only HR).')
    ap.add_argument('--wav-a', type=str, default=None,
                    help='Write the descriptor=None run to this WAV')
    ap.add_argument('--wav-b', type=str, default=None,
                    help='Write the descriptor=YOURS run to this WAV')
    ap.add_argument('--play', action='store_true',
                    help='Use SoundDevicePlayer (live playback)')
    ap.add_argument('--no-audio', action='store_true',
                    help='Alias for skipping live playback (default already off)')
    args = ap.parse_args()

    # Load descriptor
    from user_descriptor import UserDescriptor
    try:
        desc = UserDescriptor.load(args.descriptor)
    except FileNotFoundError:
        print(f'ERROR: descriptor not found: {args.descriptor}')
        print('  Build one first: python build_my_descriptor.py')
        return 1

    print(f'Loaded descriptor from {args.descriptor}')
    print(f'  target_arousal: {desc.target_arousal:.3f}')
    print(f'  genre_weights:  {desc.genre_weights}')
    print(f'  provenance:     n_songs={desc.provenance.get("n_songs")}')

    # Run A: no descriptor
    wav_a = Path(args.wav_a) if args.wav_a else None
    rungs_a = run_one('A: descriptor=None', None, args, wav_a)

    # Run B: with descriptor
    wav_b = Path(args.wav_b) if args.wav_b else None
    rungs_b = run_one('B: descriptor=YOURS', desc, args, wav_b)

    # Compare
    print('\n' + '=' * 70)
    print('COMPARISON')
    print('=' * 70)
    print(f'  {"seg":>3s}  {"A rung":>7s} {"A genre":>8s}  '
          f'{"B rung":>7s} {"B genre":>8s}  {"diff":>6s}')
    diffs = 0
    for (i, ra, ga), (_, rb, gb) in zip(rungs_a, rungs_b):
        marker = ''
        if ra != rb:
            diffs += 1
            marker = '*'
        print(f'  {i:>3d}  {ra:>7d} {ga:>8s}  {rb:>7d} {gb:>8s}  {marker:>6s}')

    a_families = [g for _, _, g in rungs_a]
    b_families = [g for _, _, g in rungs_b]
    n = len(a_families)
    def pct(genres, target):
        return sum(1 for g in genres if g in target) / n * 100.0
    print(f'\n  Segments differing: {diffs}/{n}')
    print(f'  A pop+latin: {pct(a_families, ("pop","latin")):.0f}%')
    print(f'  B pop+latin: {pct(b_families, ("pop","latin")):.0f}%')
    top = max(desc.genre_weights.items(), key=lambda kv: kv[1])
    print(f'  Top descriptor family: {top[0]} ({top[1]:.2f})')

    return 0


if __name__ == '__main__':
    sys.exit(main())
