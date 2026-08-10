"""
hr_source.py — pluggable heart-rate input for the GrooveGen experiment UI.

The experiment UI drives the CascadeController from a heart-rate signal. Today
that signal is typed in by hand (running simulations / dry experiments). Later it
will come from an ESP32 + DigiRobot PPG sensor over a serial port. Both are the
SAME interface, so the UI code never changes — you just swap the source.

    source = TextInputHRSource()          # now: manual / simulation
    source = SerialHRSource("/dev/ttyUSB0")  # later: ESP32 + PPG

Every source yields a HeartRateReading(bpm, timestamp). The UI converts bpm ->
arousal (0..1) via HRArousalMapper before handing it to the controller.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class HeartRateReading:
    """One heart-rate sample."""
    bpm: float
    timestamp: float = field(default_factory=time.time)


class HRSource:
    """Abstract heart-rate source. Subclasses implement `read()`.

    This is the seam between the UI/controller and the physical world. The UI
    only ever calls `read()`; it does not care whether the number came from a
    text box or a PPG sensor.
    """

    name: str = "abstract"

    def start(self) -> None:
        """Open the source (serial port, etc.). No-op for manual input."""

    def stop(self) -> None:
        """Close the source. No-op for manual input."""

    def read(self) -> Optional[HeartRateReading]:
        """Return the latest reading, or None if nothing is available yet."""
        raise NotImplementedError

    @property
    def available(self) -> bool:
        """Whether this source can currently produce readings."""
        return True


class TextInputHRSource(HRSource):
    """Manual heart-rate source: the UI pushes typed values into it.

    Used for simulations and dry experiments right now. `push(bpm)` is called by
    the UI text box; `read()` returns the most recently pushed value.
    """

    name = "manual (text input)"

    def __init__(self, initial_bpm: float = 70.0):
        self._latest = HeartRateReading(bpm=float(initial_bpm))

    def push(self, bpm: float) -> HeartRateReading:
        """UI calls this when the user types a new HR value."""
        self._latest = HeartRateReading(bpm=float(bpm))
        return self._latest

    def read(self) -> Optional[HeartRateReading]:
        return self._latest


class SerialHRSource(HRSource):
    """ESP32 + DigiRobot PPG heart-rate source over a serial port.

    STUB for now — wired but not required until the hardware is connected. It
    expects the ESP32 to print one BPM value per line (e.g. "72.5\\n"). Reading
    is done on a background thread so a slow/blocking serial read never stalls
    the UI; `read()` returns the most recent parsed value.

    Firmware contract (keep the ESP32 sketch simple):
        Serial.println(bpm);   // one float per line, newline-terminated

    When you get the hardware:
        pip install pyserial
        source = SerialHRSource(port="/dev/ttyUSB0", baudrate=115200)
        source.start()
    """

    name = "ESP32 + PPG (serial)"

    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200,
                 timeout: float = 1.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._latest: Optional[HeartRateReading] = None
        self._serial = None
        self._thread = None
        self._running = False

    def start(self) -> None:
        try:
            import serial  # pyserial, imported lazily so it's not a hard dep
        except ImportError as e:
            raise RuntimeError(
                "SerialHRSource needs pyserial: pip install pyserial"
            ) from e
        import threading
        self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

    def _reader_loop(self) -> None:
        while self._running and self._serial is not None:
            try:
                line = self._serial.readline().decode("utf-8", "ignore").strip()
                if not line:
                    continue
                bpm = float(line)
                if 20.0 <= bpm <= 240.0:  # sanity gate on PPG noise
                    self._latest = HeartRateReading(bpm=bpm)
            except (ValueError, UnicodeDecodeError):
                continue  # skip garbled line
            except Exception:
                break

    def stop(self) -> None:
        self._running = False
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

    def read(self) -> Optional[HeartRateReading]:
        return self._latest

    @property
    def available(self) -> bool:
        return self._serial is not None and self._running


class HRArousalMapper:
    """Map heart rate (BPM) -> arousal (0..1) for the CascadeController.

    The controller works in normalized arousal space, not raw BPM. We map BPM
    linearly between a per-subject resting HR (-> arousal 0) and max/target HR
    (-> arousal 1), then clip. Resting/max are configurable in the UI so each
    participant can be calibrated.

    arousal = clip((bpm - resting_hr) / (max_hr - resting_hr), 0, 1)
    """

    def __init__(self, resting_hr: float = 60.0, max_hr: float = 120.0):
        self.set_range(resting_hr, max_hr)

    def set_range(self, resting_hr: float, max_hr: float) -> None:
        if max_hr <= resting_hr:
            raise ValueError("max_hr must be > resting_hr")
        self.resting_hr = float(resting_hr)
        self.max_hr = float(max_hr)

    def to_arousal(self, bpm: float) -> float:
        a = (float(bpm) - self.resting_hr) / (self.max_hr - self.resting_hr)
        return float(min(1.0, max(0.0, a)))

    def to_bpm(self, arousal: float) -> float:
        """Inverse map — useful for showing a setpoint HR from a target arousal."""
        return self.resting_hr + float(arousal) * (self.max_hr - self.resting_hr)
