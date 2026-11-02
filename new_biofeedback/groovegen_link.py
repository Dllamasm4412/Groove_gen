"""UDP link between the PPG estimator and GrooveGen (localhost only).

The estimator owns the XIAO serial port and all HR/RR estimation. This link
only publishes its 1 Hz estimates and receives pacing goals:

    estimator -> GrooveGen  (publish, JSON, one datagram per HR update)
        {t_wall, t_ppg, hr_bpm|null, valid, window_hr|null, rr_rpm|null,
         haptic_mode, pacer_state, pace_bpm|null, goal_bpm|null, hr0|null,
         hr_reason, n_hb_sent, goal_source|null, log_stamp}
        t_wall is host time.time() and t_ppg the MCU time of the same update;
        hr_reason is why the HR window was (in)valid; n_hb_sent counts HB
        commands actually written to the XIAO by this process; goal_source is
        'udp' (GrooveGen), 'cli' (--pace-goal-bpm) or null; log_stamp names
        the estimator's ppg_*_<stamp>.csv files.
    GrooveGen -> estimator  (goal port)
        {"goal_bpm": x}    new goal (the pacer applies its own clip/bounds)
        {"keepalive": 1}   controller alive, no change
        {"stop": 1}        end pacing

Watchdog: once any GrooveGen message has arrived, silence for longer than
watchdog_s (time.monotonic) means the controller is lost.
"""

import json
import math
import socket
import time

WATCHDOG_S = 10.0


def parse_host_port(spec):
    """'127.0.0.1:5005' -> ('127.0.0.1', 5005)."""
    host, port = spec.rsplit(":", 1)
    return host, int(port)


def _json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


class GrooveGenLink:
    def __init__(self, publish_addr=None, goal_port=None, watchdog_s=WATCHDOG_S,
                 time_fn=time.monotonic):
        self.publish_addr = publish_addr
        self.watchdog_s = float(watchdog_s)
        self.time_fn = time_fn
        self.last_msg_t = None
        self.n_bad = 0
        self._pub = None
        self._goal = None
        if publish_addr is not None:
            self._pub = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if goal_port is not None:
            self._goal = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._goal.bind(("127.0.0.1", int(goal_port)))
            self._goal.setblocking(False)

    def publish(self, msg):
        if self._pub is None:
            return
        data = json.dumps({k: _json_safe(v) for k, v in msg.items()}).encode()
        try:
            self._pub.sendto(data, self.publish_addr)
        except OSError:
            pass

    def poll(self):
        """Drain pending goal datagrams. Returns 'stop', a goal (float) or None.

        A stop anywhere in the batch wins; otherwise the latest goal. Any
        well-formed message (goal, keepalive or stop) feeds the watchdog;
        malformed datagrams are counted and ignored.
        """
        if self._goal is None:
            return None
        stop, goal = False, None
        while True:
            try:
                data, _ = self._goal.recvfrom(4096)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            try:
                msg = json.loads(data.decode("utf-8"))
                if not isinstance(msg, dict):
                    raise ValueError("not an object")
                if msg.get("stop"):
                    stop = True
                elif "goal_bpm" in msg:
                    value = float(msg["goal_bpm"])
                    if not (math.isfinite(value) and value > 0):
                        raise ValueError("bad goal")
                    goal = value
                elif not msg.get("keepalive"):
                    raise ValueError("unknown message")
            except (ValueError, TypeError, UnicodeDecodeError):
                self.n_bad += 1
                continue
            self.last_msg_t = self.time_fn()
        if stop:
            return "stop"
        return goal

    def watchdog_expired(self):
        return self.last_msg_t is not None and self.time_fn() - self.last_msg_t > self.watchdog_s

    def close(self):
        for sock in (self._pub, self._goal):
            if sock is not None:
                sock.close()
