# KNOWN ISSUES (M1 acceptable, revisit for M2):
# 1. stop(drain=True) has no timeout — a wedged audio device could hang shutdown.
#    Add a 10-second timeout with a graceful break if we hit real issues.
# 2. The audio callback acquires a threading.Lock (_buffer_lock) briefly. This is
#    a soft violation of "no blocking in callback" but has not caused audible
#    dropouts in smoke tests. Revisit if underruns spike under load.
# 3. underruns counter includes callback invocations after audio has ended but
#    before stop() is called. This is not a real underrun — it's just silence.
#    Filter out post-final-chunk callbacks before reporting.


from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from queue import Empty, Queue

import numpy as np

try:
    import sounddevice as sd
except Exception:  # pragma: no cover - optional runtime dependency
    sd = None


def _validate_audio(audio: np.ndarray, channels: int) -> None:
    """Validate audio data for a player channel layout."""
    if not isinstance(audio, np.ndarray):
        raise ValueError("audio must be a numpy.ndarray")
    if audio.dtype != np.float32:
        raise ValueError("audio dtype must be float32")

    if channels == 1:
        if audio.ndim != 1:
            raise ValueError("mono audio must have shape (n,)")
        n_samples = audio.shape[0]
    elif channels == 2:
        if audio.ndim != 2 or audio.shape[1] != 2:
            raise ValueError("stereo audio must have shape (n, 2)")
        n_samples = audio.shape[0]
    else:
        raise ValueError("channels must be 1 or 2")

    if n_samples <= 0:
        raise ValueError("audio must contain at least one sample")
    if not np.isfinite(audio).all():
        raise ValueError("audio contains NaN or Inf")
    if np.abs(audio).max() > 1.0:
        raise ValueError("audio amplitude must be within [-1.0, 1.0]")


class PlayerBase(ABC):
    """Common interface for audio players."""

    sample_rate: int
    channels: int

    @abstractmethod
    def enqueue(self, audio: np.ndarray) -> None:
        """Queue audio for playback."""

    @abstractmethod
    def start(self) -> None:
        """Start the player."""

    @abstractmethod
    def stop(self, drain: bool = True) -> None:
        """Stop the player and optionally drain pending audio."""

    @abstractmethod
    def is_running(self) -> bool:
        """Return whether the player is active."""

    @abstractmethod
    def underruns(self) -> int:
        """Return the number of underruns."""


class SoundDevicePlayer(PlayerBase):
    """Queue-backed real-time playback through sounddevice."""

    def __init__(
        self,
        sample_rate: int = 44100,
        channels: int = 2,
        blocksize: int = 1024,
        queue_maxsize: int = 2,
        device=None,
    ) -> None:
        """Create a queue-backed device player."""
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        self.sample_rate: int = int(sample_rate)
        self.channels: int = int(channels)
        self.blocksize: int = int(blocksize)
        self.queue_maxsize: int = int(queue_maxsize)
        self.device = device

        self._audio_queue: Queue[np.ndarray] = Queue(maxsize=self.queue_maxsize)
        self._audio_buffer: deque[np.ndarray] = deque()
        self._buffer_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._running_event = threading.Event()
        self._feeder_thread: threading.Thread | None = None
        self._output_stream = None
        self._start_time: float | None = None
        self._underrun_count = 0
        self._samples_played = 0
        self._last_stop_summary = ""

    def enqueue(self, audio: np.ndarray) -> None:
        """Validate and queue audio blocks for playback."""
        _validate_audio(audio, self.channels)
        self._audio_queue.put(audio)

    def start(self) -> None:
        """Start the feeder thread and audio stream if not already running."""
        if self.is_running():
            return

        if sd is None:
            raise RuntimeError("sounddevice is required for SoundDevicePlayer")

        self._stop_event.clear()
        self._running_event.set()
        self._start_time = time.perf_counter()

        if self._feeder_thread is None or not self._feeder_thread.is_alive():
            self._feeder_thread = threading.Thread(target=self._feeder_loop, daemon=True)
            self._feeder_thread.start()

        self._output_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            blocksize=self.blocksize,
            dtype="float32",
            device=self.device,
            callback=self._audio_callback,
        )
        self._output_stream.start()

    def stop(self, drain: bool = True) -> None:
        """Stop playback and optionally drain queued audio before shutdown."""
        self._stop_event.set()

        if drain:
            deadline = time.monotonic() + 10.0
            while True:
                q_empty = self._audio_queue.empty()
                with self._buffer_lock:
                    d_empty = len(self._audio_buffer) == 0
                if q_empty and d_empty:
                    break
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.01)
        else:
            while True:
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.task_done()
                except Empty:
                    break
            with self._buffer_lock:
                self._audio_buffer.clear()

        if self._output_stream is not None:
            try:
                self._output_stream.stop()
            except Exception:
                pass
            try:
                self._output_stream.close()
            except Exception:
                pass
            self._output_stream = None

        if self._feeder_thread is not None and self._feeder_thread.is_alive():
            self._feeder_thread.join(timeout=1.0)

        self._running_event.clear()
        wall_seconds = 0.0 if self._start_time is None else time.perf_counter() - self._start_time
        self._last_stop_summary = (
            f"samples_played={self._samples_played}, "
            f"underruns={self._underrun_count}, "
            f"wall_seconds={wall_seconds:.6f}"
        )

    def is_running(self) -> bool:
        """Return whether the device stream is active."""
        return self._running_event.is_set()

    def underruns(self) -> int:
        """Return the number of callback underruns."""
        return int(self._underrun_count)

    def _feeder_loop(self) -> None:
        """Move queued chunks into the internal audio buffer."""
        while True:
            if self._stop_event.is_set() and self._audio_queue.empty() and not self._audio_buffer:
                break

            try:
                chunk = self._audio_queue.get(timeout=0.01)
            except Empty:
                continue

            if chunk is None:
                self._audio_queue.task_done()
                break

            with self._buffer_lock:
                self._audio_buffer.append(chunk)
            self._audio_queue.task_done()

    def _audio_callback(self, outdata: np.ndarray, frames: int, time_info, status) -> None:
        """Fill output blocks from the internal deque without blocking."""
        outdata.fill(0.0)

        written = 0
        while written < frames and self._audio_buffer:
            with self._buffer_lock:
                chunk = self._audio_buffer.popleft()

            if chunk is None or chunk.size == 0:
                continue

            if self.channels == 1:
                n_copy = min(frames - written, chunk.shape[0])
                outdata[written : written + n_copy, 0] = chunk[:n_copy]
                written += n_copy
                if n_copy < chunk.shape[0]:
                    with self._buffer_lock:
                        self._audio_buffer.appendleft(chunk[n_copy:])
            else:
                n_copy = min(frames - written, chunk.shape[0])
                outdata[written : written + n_copy, :] = chunk[:n_copy, :]
                written += n_copy
                if n_copy < chunk.shape[0]:
                    with self._buffer_lock:
                        self._audio_buffer.appendleft(chunk[n_copy:, :])

        if written < frames:
            self._underrun_count += 1

        self._samples_played += frames


class NullPlayer(PlayerBase):
    """Headless player used for tests and non-audio environments."""

    def __init__(self, sample_rate: int = 44100, channels: int = 2) -> None:
        """Create a null player with bookkeeping only."""
        if channels not in (1, 2):
            raise ValueError("channels must be 1 or 2")
        self.sample_rate: int = int(sample_rate)
        self.channels: int = int(channels)
        self._running_event = threading.Event()
        self._first_enqueue_time: float | None = None
        self.total_samples_received = 0
        self.total_chunks_received = 0
        self.total_wall_seconds = 0.0

    def enqueue(self, audio: np.ndarray) -> None:
        """Validate audio and record a chunk without producing sound."""
        _validate_audio(audio, self.channels)

        if self._first_enqueue_time is None:
            self._first_enqueue_time = time.monotonic()

        self.total_samples_received += int(audio.shape[0])
        self.total_chunks_received += 1
        self.total_wall_seconds = time.monotonic() - self._first_enqueue_time

    def start(self) -> None:
        """Set the running flag for the null player."""
        self._running_event.set()

    def stop(self, drain: bool = True) -> None:
        """Clear the running flag; drain is ignored in null mode."""
        self._running_event.clear()
        if self._first_enqueue_time is not None:
            self.total_wall_seconds = time.monotonic() - self._first_enqueue_time

    def is_running(self) -> bool:
        """Return whether the null player is active."""
        return self._running_event.is_set()

    def underruns(self) -> int:
        """Null players never underrun."""
        return 0


if __name__ == "__main__":
    import time as _time

    try:
        sample_rate = 44100
        duration_seconds = 2.0
        tone_seconds = np.arange(0, duration_seconds, 1.0 / sample_rate, dtype=np.float32)
        tone = 0.3 * np.sin(2.0 * np.pi * 440.0 * tone_seconds)
        stereo_tone = np.stack([tone, tone], axis=1).astype(np.float32)

        sound_player = SoundDevicePlayer()
        sound_player.start()
        sound_player.enqueue(stereo_tone)
        _time.sleep(2.5)
        sound_player.stop(drain=True)
        print(f"SoundDevicePlayer underruns={sound_player.underruns()}")

        null_player = NullPlayer()
        null_player.start()
        null_player.enqueue(stereo_tone)
        null_player.stop()
        assert null_player.total_samples_received == 88200
        print(
            "NullPlayer summary: "
            f"samples={null_player.total_samples_received}, "
            f"chunks={null_player.total_chunks_received}, "
            f"wall_seconds={null_player.total_wall_seconds:.6f}"
        )

        print("[PASS] player smoke test")
        raise SystemExit(0)
    except Exception as exc:  # pragma: no cover - smoke test only
        print(f"[FAIL] {exc}")
        raise SystemExit(1)
