"""
Smoke test for HR sources — M0.5 Step 2.

Run
---
    cd /Users/daniel/Desktop/PhD/groove_gen_project/
    python groovegen_pilot/test_hr_sources.py

What it checks
--------------
    1. HRReading fields present and typed
    2. SyntheticSineHR: deterministic sweep visits low, mid, high correctly
    3. SyntheticSineHR: real_time mode advances with wall clock
    4. ReplaySource: parses a small CSV with header
    5. ReplaySource: deterministic mode walks rows in order
    6. ReplaySource: real_time mode picks nearest row for elapsed time
    7. ReplaySource: loop=True wraps at end
    8. ManualHRInput: programmatic .set() updates BPM
    9. ManualHRInput: .read() returns is_fresh=True after set, False on repeat
   10. source_type invariant: each source labels itself correctly

Deliberately excluded (needs interactive terminal):
    - stdin thread behavior of ManualHRInput
"""

from __future__ import annotations

import math
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from hr_sources import (
    HRReading,
    ManualHRInput,
    ReplaySource,
    SyntheticSineHR,
)


def _pass(msg: str) -> None:
    print(f'  [PASS] {msg}')


def _fail(msg: str) -> None:
    print(f'  [FAIL] {msg}')


def main() -> int:
    print('=' * 60)
    print('HR sources — M0.5 Step 2 smoke test')
    print('=' * 60)

    fails = 0

    # ---- 1. HRReading shape ----
    print('\n1. HRReading structure')
    r = HRReading(t_wall=123.0, bpm=72.0, source_type='manual', is_fresh=True)
    if r.t_wall == 123.0 and r.bpm == 72.0 and r.source_type == 'manual' and r.is_fresh:
        _pass('fields present and typed')
    else:
        _fail(f'bad HRReading: {r}')
        fails += 1

    # ---- 2. SyntheticSineHR deterministic sweep ----
    print('\n2. SyntheticSineHR — deterministic sweep (60-100, period=4s)')
    s = SyntheticSineHR(bpm_low=60, bpm_high=100, period_s=4.0,
                        real_time=False, dt_virtual=1.0)
    r0 = s.read()  # t=0  -> mid
    r1 = s.read()  # t=1  -> high
    r2 = s.read()  # t=2  -> mid
    r3 = s.read()  # t=3  -> low
    ok = (
        abs(r0.bpm - 80.0) < 0.01 and
        abs(r1.bpm - 100.0) < 0.01 and
        abs(r2.bpm - 80.0) < 0.5 and    # sin(pi) ~ 0 with float wobble
        abs(r3.bpm - 60.0) < 0.01
    )
    if ok:
        _pass(f'sweep hits mid/high/mid/low: '
              f'{r0.bpm:.1f}, {r1.bpm:.1f}, {r2.bpm:.1f}, {r3.bpm:.1f}')
    else:
        _fail(f'sweep values off: {r0.bpm}, {r1.bpm}, {r2.bpm}, {r3.bpm}')
        fails += 1

    # ---- 3. SyntheticSineHR real-time mode ----
    print('\n3. SyntheticSineHR — real_time mode advances with wall clock')
    s_rt = SyntheticSineHR(bpm_low=60, bpm_high=100, period_s=2.0, real_time=True)
    ra = s_rt.read()
    time.sleep(0.3)
    rb = s_rt.read()
    if ra.bpm != rb.bpm and abs(rb.t_wall - ra.t_wall - 0.3) < 0.1:
        _pass(f'value changed after 300ms sleep (delta={rb.bpm - ra.bpm:+.1f} BPM)')
    else:
        _fail(f'real_time mode not advancing: {ra} -> {rb}')
        fails += 1

    # ---- 4-7. ReplaySource ----
    print('\n4. ReplaySource — CSV parsing (header + rows)')
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / 'hr_trace.csv'
        csv_path.write_text('t_sec,bpm\n'
                            '0,60\n'
                            '2,80\n'
                            '4,100\n'
                            '6,80\n'
                            '8,60\n')
        try:
            rp = ReplaySource(csv_path, real_time=False)
            _pass(f'parsed 5 rows from CSV with header')
        except Exception as e:
            _fail(f'CSV parse failed: {e}')
            return fails + 1

        print('\n5. ReplaySource — deterministic mode walks rows')
        vals = [rp.read().bpm for _ in range(5)]
        if vals == [60.0, 80.0, 100.0, 80.0, 60.0]:
            _pass(f'walked: {vals}')
        else:
            _fail(f'expected [60,80,100,80,60], got {vals}')
            fails += 1

        # After exhaustion, deterministic mode clamps at last row
        v_after = [rp.read().bpm for _ in range(2)]
        fresh_after = [rp.read().is_fresh for _ in range(1)]
        if v_after == [60.0, 60.0] and not fresh_after[0]:
            _pass('clamps at last row with is_fresh=False after exhaustion')
        else:
            _fail(f'exhaustion behavior wrong: values={v_after}, fresh={fresh_after}')
            fails += 1

        print('\n6. ReplaySource — real_time mode picks by elapsed')
        rp_rt = ReplaySource(csv_path, real_time=True)
        r_start = rp_rt.read()   # elapsed ~0 -> row 0 (60)
        time.sleep(2.1)
        r_mid = rp_rt.read()     # elapsed ~2.1 -> row 1 (80)
        if r_start.bpm == 60.0 and r_mid.bpm == 80.0:
            _pass(f'real_time picks by elapsed: t=0 -> {r_start.bpm}, '
                  f't=2.1 -> {r_mid.bpm}')
        else:
            _fail(f'expected 60 then 80, got {r_start.bpm} then {r_mid.bpm}')
            fails += 1

        print('\n7. ReplaySource — loop=True wraps at end')
        rp_loop = ReplaySource(csv_path, real_time=False, loop=True)
        for _ in range(5):
            rp_loop.read()
        # Should wrap: virtual_idx already clamped, so build a fresh looping source
        # differently; test the real-time wrap instead
        rp_loop2 = ReplaySource(csv_path, real_time=True, loop=True)
        rp_loop2._t_start = time.time() - 9.0  # simulate 9s elapsed (past 8s trace)
        r_wrap = rp_loop2.read()
        # 9 % 8 = 1s -> row at t<=1 is row 0 (60 BPM)
        if r_wrap.bpm == 60.0:
            _pass(f'wrapped: 9s elapsed on 8s trace -> {r_wrap.bpm} BPM')
        else:
            _fail(f'wrap failed: expected 60 (row 0 at t=1), got {r_wrap.bpm}')
            fails += 1

    # ---- 8-9. ManualHRInput (no stdin, programmatic set) ----
    print('\n8. ManualHRInput — programmatic .set()')
    m = ManualHRInput(initial_bpm=70.0)
    r_init = m.read()
    m.set(88.0)
    r_after = m.read()
    if r_init.bpm == 70.0 and r_after.bpm == 88.0:
        _pass(f'set() updates BPM: {r_init.bpm} -> {r_after.bpm}')
    else:
        _fail(f'expected 70 then 88, got {r_init.bpm} then {r_after.bpm}')
        fails += 1

    print('\n9. ManualHRInput — is_fresh flag semantics')
    m2 = ManualHRInput(initial_bpm=70.0)
    m2.set(90.0)
    r_fresh = m2.read()       # just set, should be fresh
    r_stale = m2.read()       # no new set, should be stale
    if r_fresh.is_fresh and not r_stale.is_fresh:
        _pass('is_fresh=True after set, False on repeat read')
    else:
        _fail(f'is_fresh wrong: fresh={r_fresh.is_fresh}, stale={r_stale.is_fresh}')
        fails += 1

    # ---- 10. source_type invariant ----
    print('\n10. source_type invariant — no cross-contamination')
    types_seen = set()
    types_seen.add(SyntheticSineHR().read().source_type)
    types_seen.add(ManualHRInput().read().source_type)
    with tempfile.TemporaryDirectory() as td:
        csv_path = Path(td) / 'x.csv'
        csv_path.write_text('0,60\n1,70\n')
        types_seen.add(ReplaySource(csv_path).read().source_type)
    expected = {'synth_sine', 'manual', 'replay'}
    if types_seen == expected:
        _pass(f'all three sources tag correctly: {sorted(types_seen)}')
    else:
        _fail(f'expected {expected}, got {types_seen}')
        fails += 1

    print('\n' + '=' * 60)
    if fails == 0:
        print('ALL CHECKS PASSED')
    else:
        print(f'{fails} FAILURE(S) — see above')
    print('=' * 60)
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
