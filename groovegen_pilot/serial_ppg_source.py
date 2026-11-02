"""
SerialPPGSource — live HR source from DFRobot PPG via XIAO SAMD21.

Reads raw PPG at 100 Hz from a serial port streaming CSV rows in the
format:

    time_ms,raw_ppg,clipped

Bandpass-filters the buffered signal (0.5-5 Hz), detects pulse peaks,
computes HR from median inter-beat interval, and exposes the current
estimate via the HRSource protocol.

Design notes
------------
- Runs a daemon reader thread that continuously drains the serial port
  and appends samples to a bounded buffer. The main thread's read()
  is O(1) — never blocks on I/O.
- HR is (re)computed on demand from the last `hr_window_s` seconds
  of buffered PPG. This means the first HR reading is available after
  ~5 seconds of streaming (need enough peaks to median).
- Clipped samples are counted but not removed; if the clip fraction
  in a window exceeds `max_clip_frac`, the reading is flagged
  is_fresh=False so downstream code can degrade gracefully.
- No respiration extraction here (deferred to a later module).

Usage
-----
    from serial_ppg_source import SerialPPGSource
    src = SerialPPGSource(port='/dev/tty.usbmodem11201',
                          baud=115200).start()
    time.sleep(6)  # wait for buffer to fill
    r = src.read()
    print(r.bpm, r.is_fresh)
    src.close()

Fits the same interface as ReplaySource / SyntheticSineHR, so
`run_session_v2()` accepts it as `hr_source=`.
"""
from __future__ import annotations

import sys
import threading
import time
from collections import deque
from typing import Optional

import numpy as np

# Local import — must match hr_sources.HRReading exactly
from hr_sources import HRReading


class SerialPPGSource:
    """Non-blocking HR source from live PPG serial stream."""

    source_type = 'ppg_dfrobot'

    def __init__(
        self,
        port: str = '/dev/tty.usbmodem11201',
        baud: int = 115200,
        fs_expected: float = 100.0,
        buffer_s: float = 20.0,
        hr_window_s: float = 10.0,
        min_hr_bpm: float = 40.0,
        max_hr_bpm: float = 180.0,
        max_clip_frac: float = 0.10,
        initial_bpm: float = 70.0,
    ):
        self.port = port
        self.baud = baud
        self.fs_expected = fs_expected
        self.buffer_len = int(buffer_s * fs_expected)
        self.hr_window_samples = int(hr_window_s * fs_expected)
        self.min_hr_bpm = min_hr_bpm
        self.max_hr_bpm = max_hr_bpm
        self.max_clip_frac = max_clip_frac
        self._initial_bpm = initial_bpm

        # Bounded ring buffer of (t_ms, raw_ppg, clipped)
        self._buf: deque = deque(maxlen=self.buffer_len)
        self._buf_lock = threading.Lock()

        # Reader thread
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._serial = None

        # Cached HR state
        self._last_bpm = float(initial_bpm)
        self._last_hr_compute_wall = 0.0
        self._last_returned_wall = 0.0
        self._compute_interval_s = 1.0  # re-estimate at most 1 Hz

        # Health counters (read externally for diagnostics)
        self.n_samples = 0
        self.n_dropped = 0
        self.n_bad_rows = 0

    # -------- lifecycle -----------------------------------------------------

    def start(self) -> 'SerialPPGSource':
        """Open the serial port and start the reader thread."""
        if self._thread is not None:
            return self
        import serial  # noqa: F401 — imported here so module loads without pyserial

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=1.0)
        except Exception as e:
            raise RuntimeError(
                f'SerialPPGSource: failed to open {self.port} @ {self.baud} '
                f'({type(e).__name__}: {e})'
            ) from e

        # Flush stale bytes / partial first line
        self._serial.reset_input_buffer()
        try:
            self._serial.readline()
        except Exception:
            pass

        self._thread = threading.Thread(
            target=self._reader_loop,
            name='SerialPPGSource',
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    # -------- reader thread -------------------------------------------------

    def _reader_loop(self) -> None:
        ser = self._serial
        while not self._stop.is_set():
            try:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
            except Exception:
                # Serial hiccup — brief wait, then retry
                time.sleep(0.05)
                continue
            if not line:
                continue
            parts = line.split(',')
            if len(parts) != 3:
                self.n_bad_rows += 1
                continue
            try:
                t_ms = int(parts[0])
                ppg = int(parts[1])
                clip = int(parts[2])
            except ValueError:
                self.n_bad_rows += 1
                continue
            with self._buf_lock:
                if len(self._buf) == self.buffer_len:
                    self.n_dropped += 1  # oldest sample about to be evicted
                self._buf.append((t_ms, ppg, clip))
            self.n_samples += 1

    # -------- HR estimation -------------------------------------------------

    def _current_hr(self) -> tuple[float, bool]:
        """Recompute HR from the latest `hr_window_samples` of buffered PPG.

        Returns (bpm, is_fresh). is_fresh=False when signal quality is
        insufficient (buffer too short, too much clipping, no plausible
        peak).
        """
        with self._buf_lock:
            snapshot = list(self._buf)[-self.hr_window_samples:]
        if len(snapshot) < int(self.fs_expected * 3):
            # Need >= 3 seconds
            return (self._last_bpm, False)

        arr = np.array(snapshot, dtype=np.float64)
        t_ms = arr[:, 0]
        ppg = arr[:, 1]
        clip = arr[:, 2]

        # Clipping check
        clip_frac = float(np.mean(clip))
        if clip_frac > self.max_clip_frac:
            return (self._last_bpm, False)

        # Actual fs from timestamps (guards against USB jitter)
        duration_s = (t_ms[-1] - t_ms[0]) / 1000.0
        if duration_s <= 0:
            return (self._last_bpm, False)
        fs = len(ppg) / duration_s

        # Bandpass 0.5-5 Hz
        try:
            from scipy.signal import butter, filtfilt, find_peaks
        except ImportError:
            return (self._last_bpm, False)

        nyq = fs / 2.0
        lo = 0.5 / nyq
        hi = min(5.0, nyq * 0.95) / nyq
        if hi <= lo:
            return (self._last_bpm, False)
        try:
            b, a = butter(3, [lo, hi], btype='band')
            filt = filtfilt(b, a, ppg - np.mean(ppg))
        except Exception:
            return (self._last_bpm, False)

        # Peak detection: require min_distance ~ 60/max_hr seconds between peaks
        min_dist_samples = int(fs * 60.0 / self.max_hr_bpm)
        # Height threshold = ~50th percentile above zero (pulses are prominent)
        threshold = np.std(filt) * 0.5
        peaks, _ = find_peaks(filt, distance=min_dist_samples, height=threshold)
        if len(peaks) < 3:
            return (self._last_bpm, False)

        # Convert peak indices to times (ms), then IBIs
        peak_times_ms = t_ms[peaks]
        ibis_ms = np.diff(peak_times_ms)
        # Median IBI is robust to occasional missed/extra peaks
        median_ibi_ms = float(np.median(ibis_ms))
        if median_ibi_ms <= 0:
            return (self._last_bpm, False)
        bpm = 60000.0 / median_ibi_ms

        # Sanity clamp
        if bpm < self.min_hr_bpm or bpm > self.max_hr_bpm:
            return (self._last_bpm, False)

        return (float(bpm), True)

    # -------- public read() -------------------------------------------------

    def read(self) -> HRReading:
        """Return the current HR reading. Never blocks.

        Reuses cached HR estimate within `_compute_interval_s` to keep
        the caller's loop cheap. Refreshes past that interval.
        """
        now = time.time()
        if now - self._last_hr_compute_wall >= self._compute_interval_s:
            bpm, ok = self._current_hr()
            self._last_hr_compute_wall = now
            if ok:
                # New estimate — mark fresh once
                is_fresh = (bpm != self._last_bpm) or (self._last_returned_wall < self._last_hr_compute_wall)
                self._last_bpm = bpm
                self._last_returned_wall = now
                return HRReading(t_wall=now, bpm=bpm,
                                 source_type=self.source_type, is_fresh=is_fresh)
            # Not fresh — return last known
            return HRReading(t_wall=now, bpm=self._last_bpm,
                             source_type=self.source_type, is_fresh=False)
        # Cached read
        return HRReading(t_wall=now, bpm=self._last_bpm,
                         source_type=self.source_type, is_fresh=False)

    # -------- diagnostics ---------------------------------------------------

    def health(self) -> dict:
        with self._buf_lock:
            buf_len = len(self._buf)
            recent = list(self._buf)[-int(self.fs_expected * 5):]
        if not recent:
            return {
                'buffered_samples': buf_len,
                'n_samples': self.n_samples,
                'n_dropped': self.n_dropped,
                'n_bad_rows': self.n_bad_rows,
            }
        arr = np.array(recent, dtype=np.float64)
        clip_frac = float(np.mean(arr[:, 2]))
        return {
            'buffered_samples': buf_len,
            'n_samples': self.n_samples,
            'n_dropped': self.n_dropped,
            'n_bad_rows': self.n_bad_rows,
            'recent_clip_frac': clip_frac,
            'recent_ppg_min': int(np.min(arr[:, 1])),
            'recent_ppg_max': int(np.max(arr[:, 1])),
            'last_hr_bpm': self._last_bpm,
        }


# ---------------------------------------------------------------------------
# Standalone smoke test
# ---------------------------------------------------------------------------

def main() -> int:
    """Reads live PPG for --duration seconds and prints BPM once per second."""
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', default='/dev/tty.usbmodem11201')
    ap.add_argument('--baud', type=int, default=115200)
    ap.add_argument('--duration', type=float, default=60.0)
    args = ap.parse_args()

    print(f'Opening {args.port} @ {args.baud}...')
    src = SerialPPGSource(port=args.port, baud=args.baud).start()
    print('Streaming. First HR available after ~5s. Ctrl-C to stop early.')
    print()
    print(f'{"t":>6s}  {"bpm":>6s}  {"fresh":>5s}  {"buf":>5s}  '
          f'{"clip%":>6s}  {"n_bad":>6s}')

    t_start = time.time()
    try:
        while time.time() - t_start < args.duration:
            time.sleep(1.0)
            r = src.read()
            h = src.health()
            clip_pct = h.get('recent_clip_frac', 0.0) * 100
            print(f'{time.time() - t_start:6.1f}  '
                  f'{r.bpm:6.1f}  '
                  f'{str(r.is_fresh):>5s}  '
                  f'{h["buffered_samples"]:5d}  '
                  f'{clip_pct:6.2f}  '
                  f'{h["n_bad_rows"]:6d}')
    except KeyboardInterrupt:
        pass
    finally:
        src.close()
    print()
    print('Final health:', src.health())
    return 0


if __name__ == '__main__':
    sys.exit(main())
