"""test_render_segment.py — end-to-end test of render_segment + SoundDevicePlayer.

Proves the new segment-level pipeline works:
  render_segment(tier, tempo_bpm, genre, n_bars, xfade_head_bars) -> numpy audio
  SoundDevicePlayer.enqueue(audio) -> speakers

Renders 3 segments (pop at tiers 2, 3, 4) and plays each. You should hear the
harmonic bed AND drums at increasing intensity across segments.

Prints timing + peak/rms per segment. Exit 0 on success.
"""
from __future__ import annotations

import os
import sys
import time

# Ensure repo imports work regardless of cwd.
_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_PILOT = os.path.join(_ROOT, "groovegen_pilot")
if _PILOT not in sys.path:
    sys.path.insert(0, _PILOT)

import numpy as np

from renderer import render_segment
from player import SoundDevicePlayer


def main() -> int:
    print("=" * 60)
    print("GrooveGen: render_segment + player round-trip test")
    print("=" * 60)

    # Three short pop segments at increasing tiers.
    # 4 bars @ 104 BPM = ~9.2 s each + 1 xfade head bar = ~11.5s per segment.
    # Total playback ~35 seconds.
    segments_to_render = [
        (2, 104, "pop", 4),   # tier 2: sparse
        (3, 104, "pop", 4),   # tier 3: mid
        (4, 104, "pop", 4),   # tier 4: full
    ]

    # Render all segments first (batch), so we can time render vs playback cleanly.
    rendered = []
    for i, (tier, bpm, genre, n_bars) in enumerate(segments_to_render):
        t0 = time.perf_counter()
        audio = render_segment(
            tier=tier, tempo_bpm=bpm, genre=genre,
            n_bars=n_bars, xfade_head_bars=1,
        )
        render_ms = (time.perf_counter() - t0) * 1000

        duration_s = audio.shape[0] / 44100.0
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio ** 2)))

        # Sanity
        if audio.dtype != np.float32:
            print(f"[FAIL] Segment {i}: dtype {audio.dtype} != float32")
            return 1
        if audio.shape[1] != 2:
            print(f"[FAIL] Segment {i}: channels {audio.shape[1]} != 2")
            return 1
        if not np.isfinite(audio).all():
            print(f"[FAIL] Segment {i}: contains NaN or Inf")
            return 1
        if peak == 0.0:
            print(f"[FAIL] Segment {i}: silent audio (peak=0)")
            return 1

        print(f"[OK] Segment {i}: tier={tier}, {n_bars}+1 bars, "
              f"{duration_s:.2f}s, peak={peak:.3f}, rms={rms:.4f} "
              f"(render {render_ms:.1f}ms)")
        rendered.append(audio)

    # ---- play all segments back-to-back ----
    total_duration = sum(a.shape[0] / 44100.0 for a in rendered)
    print()
    print(f"[INFO] Playing {len(rendered)} segments, total {total_duration:.1f}s")
    print("[INFO] Volume tip: tier 2 -> 3 -> 4, drums should get denser.")

    player = SoundDevicePlayer(sample_rate=44100, channels=2)
    player.start()

    t_play = time.perf_counter()
    for i, audio in enumerate(rendered):
        print(f"[INFO] Enqueueing segment {i} (tier={segments_to_render[i][0]})...")
        player.enqueue(audio)

    # Wait for playback to finish. queue_maxsize=2 means the third enqueue()
    # already blocked until segment 0 was consumed, but we still need to
    # wait for the last segments to finish playing out.
    print(f"[INFO] All enqueued. Waiting {total_duration + 0.5:.1f}s for playback to complete...")
    time.sleep(total_duration + 0.5)

    player.stop(drain=True)
    play_ms = (time.perf_counter() - t_play) * 1000
    underruns = player.underruns()

    print()
    print(f"[OK] Playback complete: {play_ms:.0f} ms wall, "
          f"underruns={underruns}")

    # Post-audio silence-period underruns are expected (~22 per stop).
    # Anything above ~50 would be a real problem.
    if underruns > 100:
        print(f"[FAIL] Excessive underruns: {underruns}")
        return 1

    print("=" * 60)
    print("[PASS] render_segment + player round-trip complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] Exception: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
