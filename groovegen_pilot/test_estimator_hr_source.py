"""
Loopback test for the estimator <-> GrooveGen UDP link. No serial, no haptics.

Covers EstimatorHRSource (groovegen_pilot) against GrooveGenLink
(new_biofeedback) on 127.0.0.1 ephemeral ports: freshness, stale and invalid
estimates, malformed datagrams, goal/keepalive/stop delivery, "stop wins"
batching, and the estimator-side watchdog on a fake monotonic clock.
Also: the rx log (every good datagram, verbatim, with receive time),
provenance tallies across an estimator restart, a failing log writer that
must not stop HR, and close() while datagrams are still arriving.

Run: python test_estimator_hr_source.py
"""

from __future__ import annotations

import json
import math
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'new_biofeedback'))

from estimator_hr_source import EstimatorHRSource  # noqa: E402
from groovegen_link import GrooveGenLink  # noqa: E402


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_for(cond, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def main() -> int:
    hr_port, goal_port = free_port(), free_port()
    clock = [1000.0]
    src = EstimatorHRSource(listen=('127.0.0.1', hr_port), goal_addr=('127.0.0.1', goal_port),
                            stale_s=3.0, time_fn=lambda: clock[0]).start()
    mono = [0.0]
    link = GrooveGenLink(publish_addr=('127.0.0.1', hr_port), goal_port=goal_port,
                         watchdog_s=10.0, time_fn=lambda: mono[0])
    try:
        # 1. Nothing received yet -> not fresh
        r = src.read()
        assert not r.is_fresh and math.isnan(r.bpm), r
        print('PASS: no estimate yet -> not fresh')

        # 2. Valid estimate published by the estimator side -> fresh
        link.publish({'t_wall': 999.5, 't_ppg': 12.0, 'hr_bpm': 71.25, 'valid': True,
                      'window_hr': float('nan'), 'rr_rpm': 14.0, 'haptic_mode': 'pacing',
                      'pacer_state': 'pacing', 'pace_bpm': 73.0, 'goal_bpm': 77.0, 'hr0': 71.0})
        assert wait_for(lambda: src.n_received == 1)
        r = src.read()
        assert r.is_fresh and r.bpm == 71.25 and r.t_wall == 999.5 and r.source_type == 'ppg_estimator', r
        st = src.haptic_status()
        assert st == {'haptic_mode': 'pacing', 'pacer_state': 'pacing', 'pace_bpm': 73.0,
                      'goal_bpm': 77.0, 'hr0': 71.0, 'rr_rpm': 14.0}, st
        print('PASS: valid estimate -> fresh HRReading; NaN window_hr sent as null; haptic_status fields')

        # 3. Stale after stale_s without new datagrams
        clock[0] += 3.5
        assert not src.read().is_fresh
        print('PASS: no datagram for 3.5 s (> stale_s 3) -> not fresh')

        # 4. Invalid estimate -> not fresh; malformed datagrams ignored
        link.publish({'t_wall': 1003.6, 'hr_bpm': None, 'valid': False})
        raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        raw.sendto(b'not json', ('127.0.0.1', hr_port))
        raw.sendto(b'[1,2]', ('127.0.0.1', hr_port))
        assert wait_for(lambda: src.n_received == 2 and src.n_bad == 2)
        r = src.read()
        assert not r.is_fresh, r
        print('PASS: valid=false -> not fresh; 2 malformed datagrams counted, last good kept')

        # 5. GrooveGen -> estimator: latest goal wins; keepalive feeds watchdog
        assert link.poll() is None and not link.watchdog_expired()
        src.set_goal(80.0)
        src.keepalive()
        src.set_goal(78.5)
        raw.sendto(b'{"goal_bpm": "x"}', ('127.0.0.1', goal_port))
        raw.sendto(b'{"goal_bpm": -3}', ('127.0.0.1', goal_port))
        time.sleep(0.1)
        assert link.poll() == 78.5 and link.n_bad == 2, link.n_bad
        assert link.last_msg_t == 0.0
        print('PASS: goals drained, latest (78.5) returned; bad goals rejected and counted')

        src.keepalive()
        time.sleep(0.05)
        assert link.poll() is None
        mono[0] = 9.9
        assert not link.watchdog_expired()
        mono[0] = 10.5
        assert link.watchdog_expired()
        src.keepalive()
        time.sleep(0.05)
        link.poll()
        assert not link.watchdog_expired()
        print('PASS: watchdog trips after >10 s of silence (monotonic), keepalive resets it')

        # 6. Stop wins over a later goal in the same batch
        src.stop()
        src.set_goal(90.0)
        time.sleep(0.05)
        assert link.poll() == 'stop'
        print('PASS: stop in a batch wins over later goals')
    finally:
        src.close()
        link.close()
    provenance_and_rx_log()
    print('\nALL ESTIMATOR LINK TESTS PASSED')
    return 0


def provenance_and_rx_log() -> None:
    import csv
    hr_port = free_port()
    log_path = Path(tempfile.mkdtemp()) / 'estimator_rx.csv'
    src = EstimatorHRSource(listen=('127.0.0.1', hr_port), stale_s=3.0,
                            rx_log_path=log_path).start()
    link = GrooveGenLink(publish_addr=('127.0.0.1', hr_port))
    raw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def pub(t_ppg, n_hb, stamp, mode='pacing', goal_source='udp'):
        link.publish({'t_wall': time.time(), 't_ppg': t_ppg, 'hr_bpm': 70.0, 'valid': True,
                      'haptic_mode': mode, 'goal_source': goal_source, 'hr_reason': 'ok',
                      'n_hb_sent': n_hb, 'log_stamp': stamp})
    try:
        # Estimator already running when GrooveGen starts: its 5 earlier pulses
        # are not counted; 5 -> 8 counts 3.
        pub(100.0, 5, 'A')
        pub(101.0, 8, 'A')
        raw.sendto(b'not json', ('127.0.0.1', hr_port))
        assert wait_for(lambda: src.n_received == 2 and src.n_bad == 1)
        p1 = src.take_provenance()
        assert p1 == {'haptic_modes': ['pacing'], 'goal_sources': ['udp'], 'log_stamps': ['A'],
                      'n_hb_sent': 3, 'n_received': 2}, p1
        # Then 8 -> 10 on A, and a restarted estimator B (MCU clock ~0) with 2 pulses.
        pub(102.0, 10, 'A')
        pub(0.5, 2, 'B', mode='echo', goal_source=None)
        assert wait_for(lambda: src.n_received == 4)
        p2 = src.take_provenance()
        assert p2['log_stamps'] == ['A', 'B'] and p2['n_hb_sent'] == 4 \
            and p2['haptic_modes'] == ['echo', 'pacing'], p2
        print('PASS: provenance tallies per take; pre-existing pulses excluded; restart counted')

        with log_path.open(newline='') as f:
            rows = list(csv.DictReader(f))
        msgs = [json.loads(r['json']) for r in rows]
        assert [m['t_ppg'] for m in msgs] == [100.0, 101.0, 102.0, 0.5], msgs
        assert all(float(r['rx_wall']) >= m['t_wall'] for r, m in zip(rows, msgs))
        print(f'PASS: rx log has {len(rows)} rows (malformed datagram excluded), t_ppg kept')

        # A failing log writer is counted and HR keeps flowing.
        class Broken:
            def write(self, _):
                raise OSError('disk full')

            def close(self):
                pass
        src._log = Broken()
        pub(103.0, 10, 'A')
        assert wait_for(lambda: src.n_received == 5)
        r = src.read()
        assert r.is_fresh and src.n_log_errors == 1 and src._thread.is_alive(), (r, src.n_log_errors)
        print('PASS: log write failure counted; receive thread alive, HR still fresh')

        # close() while datagrams keep arriving: no exception, file closed.
        src._log = log_path.open('a', newline='')
        stop = threading.Event()

        def spam():
            k = 0
            while not stop.is_set():
                pub(200.0 + k, 10, 'A')
                k += 1
                time.sleep(0.001)
        th = threading.Thread(target=spam)
        th.start()
        time.sleep(0.1)
        f = src._log
        src.close()
        stop.set()
        th.join()
        assert f.closed and src._log is None
        print('PASS: close() under incoming traffic closes the log cleanly')
    finally:
        src.close()
        link.close()
        raw.close()


if __name__ == '__main__':
    sys.exit(main())
