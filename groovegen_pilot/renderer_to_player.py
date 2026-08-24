"""
Renderer -> Player bridge for GrooveGen closed-loop pilot (M0.5 Step 3).

The SymbolicSegmentRenderer emits arbitrary-length stereo float32 buffers
(one per segment, ~15-30s). The Player (SoundDevicePlayer / NullPlayer)
consumes them via .enqueue(). SoundDevicePlayer's audio callback pulls
`blocksize` frames at a time from its internal deque.

We slice each segment into `blocksize`-sized chunks BEFORE enqueue so:
  - stop(drain=False) has fine-grained latency (single blocksize, ~23ms)
  - the feeder queue can bound at queue_maxsize chunks (~46ms of audio)
    instead of holding a whole 30s segment in memory
  - Player invariants (float32, [-1,1], correct shape) are re-validated per
    chunk by the Player's internal _validate_audio — mismatches fail loudly
    at enqueue time, not at playback time

Public API
----------
    enqueue_segment(player, audio, chunk_frames=None) -> int
        Slice `audio` into chunks and push through `player.enqueue()`.
        Returns the number of chunks enqueued.

    render_and_play(renderer, player, *args, chunk_frames=None, **kwargs) -> np.ndarray
        Convenience: renderer.render_segment(*args, **kwargs) -> player.
        Returns the raw audio (useful for logging peak/rms per segment).

Contract
--------
    - `audio` must be stereo float32 shape (n_samples, 2), values in [-1, 1].
    - `chunk_frames` defaults to `player.blocksize` if available, else 1024.
    - The last chunk may be short (<chunk_frames) — that's fine, the Player's
      audio callback handles partial-frame appendleft internally.
    - No silence-padding: we push the audio as-is. Crossfade (Step 4) will
      overlap adjacent segments, but at this step segments play back-to-back
      with a hard boundary.
"""

from __future__ import annotations

import numpy as np


def enqueue_segment(player, audio: np.ndarray,
                    chunk_frames: int | None = None) -> int:
    """
    Slice `audio` into `chunk_frames`-sized chunks and enqueue via `player`.

    Parameters
    ----------
    player : PlayerBase
        Any object with .enqueue(np.ndarray) and (optionally) .blocksize.
    audio : np.ndarray, shape (n_samples, 2), dtype float32
        Stereo audio. Values expected in [-1, 1] (Player validates).
    chunk_frames : int | None
        Slice size. Defaults to player.blocksize if present, else 1024.

    Returns
    -------
    int
        Number of chunks enqueued.

    Raises
    ------
    ValueError
        If audio has wrong shape/dtype, or if chunk_frames <= 0.
    """
    if not isinstance(audio, np.ndarray):
        raise ValueError(f'audio must be numpy.ndarray, got {type(audio)}')
    if audio.dtype != np.float32:
        raise ValueError(f'audio dtype must be float32, got {audio.dtype}')
    if audio.ndim != 2 or audio.shape[1] != 2:
        raise ValueError(f'audio must be stereo shape (n, 2), got {audio.shape}')

    if chunk_frames is None:
        chunk_frames = getattr(player, 'blocksize', 1024)
    if chunk_frames <= 0:
        raise ValueError(f'chunk_frames must be positive, got {chunk_frames}')

    n_samples = audio.shape[0]
    n_chunks = 0
    for start in range(0, n_samples, chunk_frames):
        chunk = audio[start:start + chunk_frames]
        # Ensure contiguous — a view of a slice can be non-contiguous in some
        # numpy configurations, and sounddevice wants contiguous buffers.
        if not chunk.flags['C_CONTIGUOUS']:
            chunk = np.ascontiguousarray(chunk)
        player.enqueue(chunk)
        n_chunks += 1

    return n_chunks


def render_and_play(renderer, player,
                    genre: str, tempo_bpm: int, tier: int, n_bars: int,
                    *, segment_idx: int = 0,
                    chunk_frames: int | None = None) -> np.ndarray:
    """
    Convenience: render one segment, enqueue through the player, return audio.

    Parameters
    ----------
    renderer : SymbolicSegmentRenderer
    player   : PlayerBase (SoundDevicePlayer or NullPlayer)
    genre, tempo_bpm, tier, n_bars, segment_idx : passed to renderer.render_segment
    chunk_frames : override for slicing size (default: player.blocksize)

    Returns
    -------
    np.ndarray, shape (n_samples, 2), float32
        The rendered audio (also enqueued to the player).
    """
    audio = renderer.render_segment(
        genre=genre, tempo_bpm=tempo_bpm, tier=tier,
        n_bars=n_bars, segment_idx=segment_idx)
    enqueue_segment(player, audio, chunk_frames=chunk_frames)
    return audio


if __name__ == '__main__':
    # Tiny self-test with a synthetic buffer (no renderer needed)
    class _FakePlayer:
        def __init__(self, blocksize=1024):
            self.blocksize = blocksize
            self.chunks = []
        def enqueue(self, audio):
            self.chunks.append(audio.shape[0])

    n = 44100 * 2  # 2 seconds
    audio = (0.1 * np.sin(np.linspace(0, 100, n))).astype(np.float32)
    stereo = np.stack([audio, audio], axis=1)

    p = _FakePlayer(blocksize=1024)
    n_chunks = enqueue_segment(p, stereo)
    total = sum(p.chunks)
    print(f'enqueued {n_chunks} chunks, {total} total frames '
          f'(expected {n}, chunks[-1]={p.chunks[-1]})')
    assert total == n
    assert n_chunks == (n + 1023) // 1024
    print('OK')
