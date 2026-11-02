"""
HR source fed by the new_biofeedback PPG estimator over localhost UDP.

The estimator (ppg_live_estimator_adaptive_haptics_stable_hr.py) owns the
XIAO serial port and all HR/RR estimation; it publishes one JSON datagram
per 1 Hz HR update (--publish-udp) and accepts pacing goals (--goal-udp).
This class only receives those estimates and, for haptic pacing, sends
goal / keepalive / stop messages back. Protocol: new_biofeedback/groovegen_link.py.

Duck-types the HRSource interface used by run_session_v2 and
run_pilot_zero.collect_baseline: .start(), .read() -> HRReading, .close().

    src = EstimatorHRSource().start()
    r = src.read()          # HRReading(t_wall, bpm, 'ppg_estimator', is_fresh)
    src.haptic_status()     # last published pacer/RR fields
    src.set_goal(78.0); src.keepalive(); src.stop()
    src.take_provenance()   # modes / estimator log stamps / HB sent since last call

rx_log_path, if given, receives every well-formed datagram verbatim
(rx_wall = host receive time, json = the message), so each HR value GrooveGen
saw can be mapped to the estimator's MCU clock (t_ppg) and its ppg_*_<stamp>
files. A logging failure is counted (n_log_errors) and never stops HR.
"""

from __future__ import annotations

import json
import math
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional, Union

from hr_sources import HRReading


class EstimatorHRSource:
    source_type = 'ppg_estimator'

    def __init__(
        self,
        listen: tuple[str, int] = ('127.0.0.1', 5005),
        goal_addr: tuple[str, int] = ('127.0.0.1', 5006),
        stale_s: float = 3.0,
        time_fn: Callable[[], float] = time.time,
        rx_log_path: Union[str, Path, None] = None,
    ):
        self.listen = listen
        self.goal_addr = goal_addr
        self.stale_s = float(stale_s)
        self.time_fn = time_fn
        self._lock = threading.Lock()
        self._last: Optional[dict] = None
        self._last_rx = -math.inf     # time_fn() when _last arrived
        self.n_received = 0
        self.n_bad = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rx: Optional[socket.socket] = None
        self._tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rx_log_path = None if rx_log_path is None else Path(rx_log_path)
        self._log = None
        self.n_log_errors = 0
        # Provenance since the last take_provenance() call.
        self._modes: set = set()
        self._goal_sources: set = set()
        self._stamps: list = []
        self._hb_sent = 0
        self._hb_last: dict = {}      # log_stamp -> last cumulative n_hb_sent

    def start(self) -> 'EstimatorHRSource':
        if self._thread is not None:
            return self
        self._rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rx.bind(self.listen)
        self._rx.settimeout(0.2)
        if self.rx_log_path is not None:
            self._log = self.rx_log_path.open('w', newline='')
            self._log.write('rx_wall,json\n')
            self._log.flush()
        self._thread = threading.Thread(target=self._run, name='estimator-udp', daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                data, _ = self._rx.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                msg = json.loads(data.decode('utf-8'))
                if not isinstance(msg, dict):
                    raise ValueError('not an object')
            except (ValueError, UnicodeDecodeError):
                self.n_bad += 1
                continue
            with self._lock:
                self._last = msg
                self._last_rx = self.time_fn()
                self.n_received += 1
                self._note_provenance(msg)
                self._write_log(self._last_rx, data)

    def _note_provenance(self, msg: dict) -> None:
        mode = msg.get('haptic_mode')
        if mode is not None:
            self._modes.add(str(mode))
        goal_source = msg.get('goal_source')
        if goal_source is not None:
            self._goal_sources.add(str(goal_source))
        stamp = msg.get('log_stamp')
        if stamp is not None and stamp not in self._stamps:
            self._stamps.append(stamp)
        n_hb = msg.get('n_hb_sent')
        if isinstance(n_hb, (int, float)):
            # Cumulative per estimator process. A stamp first seen after other
            # traffic is a (re)started estimator: its pulses all count. The
            # first stamp ever seen counts only pulses sent from now on.
            key = stamp if stamp is not None else ''
            if key not in self._hb_last:
                self._hb_last[key] = int(n_hb) if self.n_received == 1 else 0
            self._hb_sent += max(0, int(n_hb) - self._hb_last[key])
            self._hb_last[key] = int(n_hb)

    def _write_log(self, rx_wall: float, data: bytes) -> None:
        if self._log is None:
            return
        try:
            text = data.decode('utf-8').replace('"', '""')
            self._log.write(f'{rx_wall:.6f},"{text}"\n')
            self._log.flush()
        except Exception:   # never let logging stop HR delivery
            self.n_log_errors += 1

    def take_provenance(self) -> dict:
        """Haptic modes, estimator log stamps and HB commands the estimator
        reported sending since the previous call; resets the tally."""
        with self._lock:
            out = {'haptic_modes': sorted(self._modes),
                   'goal_sources': sorted(self._goal_sources),
                   'log_stamps': list(self._stamps),
                   'n_hb_sent': self._hb_sent,
                   'n_received': self.n_received}
            self._modes = set()
            self._goal_sources = set()
            self._stamps = []
            self._hb_sent = 0
        return out

    def read(self) -> HRReading:
        """Latest estimate; fresh only if valid and received within stale_s."""
        now = self.time_fn()
        with self._lock:
            msg, rx = self._last, self._last_rx
        if msg is None:
            return HRReading(t_wall=now, bpm=float('nan'),
                             source_type=self.source_type, is_fresh=False)
        bpm = msg.get('hr_bpm')
        ok = bool(msg.get('valid')) and bpm is not None and now - rx <= self.stale_s
        bpm = float(bpm) if bpm is not None else float('nan')
        # t_wall is the estimator's publish time (same host clock), so each
        # 1 Hz update has its own timestamp and repeated reads dedupe.
        return HRReading(t_wall=float(msg.get('t_wall', rx)), bpm=bpm,
                         source_type=self.source_type, is_fresh=ok)

    def haptic_status(self) -> dict:
        with self._lock:
            msg = dict(self._last) if self._last else {}
        keys = ('haptic_mode', 'pacer_state', 'pace_bpm', 'goal_bpm', 'hr0', 'rr_rpm')
        return {k: msg.get(k) for k in keys}

    def _send(self, msg: dict) -> None:
        try:
            self._tx.sendto(json.dumps(msg).encode(), self.goal_addr)
        except OSError:
            pass

    def set_goal(self, goal_bpm: float) -> None:
        self._send({'goal_bpm': float(goal_bpm)})

    def keepalive(self) -> None:
        self._send({'keepalive': 1})

    def stop(self) -> None:
        self._send({'stop': 1})

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        for sock in (self._rx, self._tx):
            if sock is not None:
                sock.close()
        with self._lock:
            if self._log is not None:
                self._log.close()
                self._log = None
