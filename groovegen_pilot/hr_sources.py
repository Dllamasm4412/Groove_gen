"""
HR sources for GrooveGen closed-loop pilot — M0.5 Step 2.

All sources implement the same protocol:

    HRSource.read() -> HRReading(t_wall, bpm, source_type, is_fresh)

`.read()` is NON-BLOCKING. If no fresh value is available, the last known value
is returned with `is_fresh=False`. The audio loop must never stall on HR.

Every reading carries a `source_type` string. This is the invariant from
SENSOR_NOTES.md that prevents accidental data mixing: real sensor data can
never be labeled as manual or replay.

Sources
-------
    ManualHRInput      — user types BPM in the terminal, daemon thread reads stdin
    ReplaySource       — walks a CSV of (t_seconds, bpm) rows
    SyntheticSineHR    — sinusoidal BPM sweep, no I/O

All three are hardware-free. The Polar H10 / PPG-ESP32 sources will be added
in a later milestone with the SAME .read() contract.
"""

from __future__ import annotations

import csv
import math
import sys
import threading
import time
from pathlib import Path
from typing import NamedTuple, Protocol


# =============================================================================
# Protocol + data class
# =============================================================================

class HRReading(NamedTuple):
    t_wall: float      # UTC seconds when read
    bpm: float         # heart rate; NaN if source has no value yet
    source_type: str   # 'manual' | 'replay' | 'synth_sine' | 'polar_h10' | 'ppg_esp32'
    is_fresh: bool     # False if this is a repeat of the last returned value


class HRSource(Protocol):
    """Non-blocking heart-rate source contract."""
    source_type: str
    def read(self) -> HRReading: ...
    def close(self) -> None: ...


# =============================================================================
# ManualHRInput — daemon-thread stdin reader
# =============================================================================

class ManualHRInput:
    """
    Reads BPM values from stdin in a background daemon thread.

    Usage:
        src = ManualHRInput(initial_bpm=72.0)
        src.start()
        # ... your loop calls src.read() periodically
        # user types '85\\n' at the terminal to update BPM
        src.close()  # (optional; daemon dies with process)

    Input parsing:
      - '85' or '85.5'  -> set BPM
      - 'q' or empty    -> ignored (allows testing without accidental stop)
      - anything else   -> logged to stderr, ignored

    Thread safety: shared BPM is guarded by a Lock. Reads are O(1) and never block.
    """

    source_type = 'manual'

    def __init__(self, initial_bpm: float = 70.0,
                 prompt: str = 'HR> ',
                 out_stream=sys.stderr):
        self._lock = threading.Lock()
        self._bpm = float(initial_bpm)
        self._last_updated = time.time()  # when a NEW value was set
        self._last_read = 0.0             # when read() last returned this value
        self._prompt = prompt
        self._out = out_stream
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> 'ManualHRInput':
        """Launch the stdin-reader thread. Returns self for chaining."""
        if self._thread is not None:
            return self
        self._thread = threading.Thread(
            target=self._stdin_loop, name='ManualHRInput', daemon=True)
        self._thread.start()
        return self

    def _stdin_loop(self) -> None:
        # Print prompt once; user types values on their own line
        print(f'{self._prompt}(type BPM values, e.g. "72"; Ctrl+D to close)',
              file=self._out, flush=True)
        while not self._stop.is_set():
            try:
                line = sys.stdin.readline()
            except (EOFError, KeyboardInterrupt):
                return
            if not line:  # EOF (Ctrl+D)
                return
            line = line.strip()
            if not line or line.lower() == 'q':
                continue
            try:
                new_bpm = float(line)
            except ValueError:
                print(f'  (ignored: {line!r} is not a number)',
                      file=self._out, flush=True)
                continue
            if not (20.0 <= new_bpm <= 220.0):
                print(f'  (ignored: {new_bpm} outside plausible HR range 20-220)',
                      file=self._out, flush=True)
                continue
            with self._lock:
                self._bpm = new_bpm
                self._last_updated = time.time()
            print(f'  HR set to {new_bpm:.1f} BPM', file=self._out, flush=True)

    def set(self, bpm: float) -> None:
        """Programmatic BPM update — useful for tests without stdin."""
        with self._lock:
            self._bpm = float(bpm)
            self._last_updated = time.time()

    def read(self) -> HRReading:
        now = time.time()
        with self._lock:
            bpm = self._bpm
            updated = self._last_updated
            is_fresh = updated > self._last_read
            self._last_read = now
        return HRReading(t_wall=now, bpm=bpm,
                         source_type=self.source_type, is_fresh=is_fresh)

    def close(self) -> None:
        self._stop.set()


# =============================================================================
# ReplaySource — CSV of (t_seconds, bpm) rows
# =============================================================================

class ReplaySource:
    """
    Replays a CSV of `(t_seconds, bpm)` rows.

    CSV format:  first two columns are (t_seconds, bpm). Header optional.
    Additional columns are ignored (so you can point at real sensor traces).

    Modes:
      real_time=True  (default): read() returns the row nearest to
                                 time.time() - t_start.
      real_time=False:           read() advances a virtual clock by dt seconds
                                 per call, taking dt from the CSV row spacing.
                                 Deterministic; useful for CI/headless tests.

    Behavior at end of CSV:
      - loop=False (default): read() keeps returning the last row with is_fresh=False
      - loop=True:            wraps back to row 0
    """

    source_type = 'replay'

    def __init__(self, csv_path: str | Path, *,
                 real_time: bool = True, loop: bool = False):
        self.csv_path = Path(csv_path)
        self.real_time = real_time
        self.loop = loop
        self._rows: list[tuple[float, float]] = self._load(self.csv_path)
        if not self._rows:
            raise ValueError(f'ReplaySource CSV is empty: {self.csv_path}')
        self._t_start: float | None = None
        self._virtual_idx = 0        # only used in real_time=False mode
        self._last_idx = -1

    @staticmethod
    def _load(path: Path) -> list[tuple[float, float]]:
        rows: list[tuple[float, float]] = []
        with open(path, newline='') as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if not row:
                    continue
                # Skip header if first cell isn't numeric
                try:
                    t = float(row[0])
                    bpm = float(row[1])
                except (ValueError, IndexError):
                    if i == 0:
                        continue
                    raise ValueError(
                        f'{path}:{i+1}: expected (t_seconds, bpm), got {row!r}')
                rows.append((t, bpm))
        return rows

    def read(self) -> HRReading:
        now = time.time()
        if self._t_start is None:
            self._t_start = now

        if self.real_time:
            elapsed = now - self._t_start
            idx = self._find_index_for_time(elapsed)
        else:
            idx = self._virtual_idx
            self._virtual_idx = min(self._virtual_idx + 1, len(self._rows) - 1)

        if self.loop and idx >= len(self._rows):
            idx = idx % len(self._rows)

        idx = min(idx, len(self._rows) - 1)
        _, bpm = self._rows[idx]
        is_fresh = idx != self._last_idx
        self._last_idx = idx
        return HRReading(t_wall=now, bpm=float(bpm),
                         source_type=self.source_type, is_fresh=is_fresh)

    def _find_index_for_time(self, elapsed: float) -> int:
        """Return the index of the last row whose t <= elapsed."""
        # Rows may not be uniformly spaced; linear scan is fine at 30-100 rows.
        # For very long traces, this could be a bisect, but M0.5 traces are small.
        idx = 0
        for i, (t, _) in enumerate(self._rows):
            if t <= elapsed:
                idx = i
            else:
                break
        # If elapsed exceeds last row's t, we're past the end
        last_t = self._rows[-1][0]
        if elapsed > last_t and not self.loop:
            return len(self._rows) - 1
        if elapsed > last_t and self.loop:
            # Wrap: idx increments virtually as elapsed keeps growing
            period = last_t if last_t > 0 else 1.0
            wrapped = elapsed % period
            return self._find_index_for_time(wrapped)
        return idx

    def close(self) -> None:
        pass


# =============================================================================
# SyntheticSineHR — sinusoidal BPM sweep
# =============================================================================

class SyntheticSineHR:
    """
    Generates a sinusoidal BPM signal — no I/O, no sensor.

        bpm(t) = mid + amp * sin(2π t / period + phase)
        mid = (bpm_low + bpm_high) / 2
        amp = (bpm_high - bpm_low) / 2

    Perfect for proving the whole ladder responds smoothly to a known drive.
    Sweeping 65->105 over 3 minutes will visit calm/rnb/pop tiers cleanly.

    Modes:
      real_time=True  (default): read() uses time.time() as t
      real_time=False:           read() advances a virtual clock by `dt_virtual`
                                 seconds per call. Deterministic for tests.
    """

    source_type = 'synth_sine'

    def __init__(self, bpm_low: float = 65.0, bpm_high: float = 105.0,
                 period_s: float = 180.0, phase: float = 0.0,
                 *, real_time: bool = True, dt_virtual: float = 1.0):
        if bpm_high <= bpm_low:
            raise ValueError(f'bpm_high ({bpm_high}) must exceed bpm_low ({bpm_low})')
        if period_s <= 0:
            raise ValueError(f'period_s must be positive, got {period_s}')
        self.bpm_low = float(bpm_low)
        self.bpm_high = float(bpm_high)
        self.period_s = float(period_s)
        self.phase = float(phase)
        self.real_time = real_time
        self.dt_virtual = float(dt_virtual)
        self._mid = (bpm_low + bpm_high) / 2
        self._amp = (bpm_high - bpm_low) / 2
        self._t_start: float | None = None
        self._virtual_t = 0.0
        self._last_bpm: float | None = None

    def read(self) -> HRReading:
        now = time.time()
        if self._t_start is None:
            self._t_start = now
        if self.real_time:
            t = now - self._t_start
        else:
            t = self._virtual_t
            self._virtual_t += self.dt_virtual
        bpm = self._mid + self._amp * math.sin(
            2 * math.pi * t / self.period_s + self.phase)
        is_fresh = (self._last_bpm is None) or (bpm != self._last_bpm)
        self._last_bpm = bpm
        return HRReading(t_wall=now, bpm=float(bpm),
                         source_type=self.source_type, is_fresh=is_fresh)

    def close(self) -> None:
        pass


# =============================================================================
# CLI smoke — quick manual sanity check
# =============================================================================

if __name__ == '__main__':
    print('SyntheticSineHR: 60-100 BPM over 4s (deterministic mode)')
    s = SyntheticSineHR(bpm_low=60, bpm_high=100, period_s=4.0,
                        real_time=False, dt_virtual=0.5)
    for _ in range(9):
        r = s.read()
        print(f'  t={s._virtual_t - s.dt_virtual:4.1f}s  bpm={r.bpm:6.2f}  '
              f'type={r.source_type}  fresh={r.is_fresh}')
