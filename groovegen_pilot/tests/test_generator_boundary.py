"""
Information boundary of the v2 generator (LIVE_GENERATION_PLAN.md section 5):
its only inputs are (genre, tier, visit_idx) plus stim_seed, it imports no
physiology / controller / participant module, and the k-th visit to a cell
gives the same MIDI whatever path the controller took to get there.
"""

from __future__ import annotations

import inspect
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer.arrangement import SessionComposer  # noqa: E402

FORBIDDEN = ('hr_sources', 'serial_ppg_source', 'estimator_hr_source', 'control',
             'user_descriptor', 'composer_personalization', 'run_session_v2', 'run_pilot_zero')


def _params(fn) -> list[inspect.Parameter]:
    return list(inspect.signature(fn).parameters.values())


def test_signatures_are_closed():
    init = _params(SessionComposer.__init__)
    compose = _params(SessionComposer.compose)
    assert [p.name for p in init] == ['self', 'stim_seed', 'develop']
    # develop selects the generator version (v2b motif development), off by default
    assert init[2].default is False and init[2].annotation in (bool, 'bool')
    assert [p.name for p in compose] == ['self', 'genre', 'tier', 'visit_idx']
    for p in init + compose:
        assert p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD), p


def test_no_physiology_or_controller_imports():
    code = (
        'import json, sys\n'
        f'sys.path.insert(0, {str(PILOT)!r})\n'
        'from composer.arrangement import SessionComposer\n'
        "for sc in (SessionComposer(1), SessionComposer(1, develop=True)):\n"
        "    for g, t in (('pop', 3), ('latin', 2), ('hiphop', 1), ('rock', 2), ('calm', 1)):\n"
        '        sc.compose(g, t, 1)\n'
        f'print(json.dumps(sorted(m for m in {FORBIDDEN!r} if m in sys.modules)))\n'
    )
    out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout.strip().splitlines()[-1]) == []


@pytest.mark.parametrize('develop', [False, True])
def test_path_invariance(develop):
    """Two controller paths over the same cells: per (cell, visit), same MIDI."""
    cells = [('pop', 3), ('rnb', 2), ('hiphop', 1), ('latin', 3)]
    visits = 5

    def run(order):
        sc, seen, out = SessionComposer(3, develop=develop), {}, {}
        for cell in order:
            v = seen.get(cell, 0)
            seen[cell] = v + 1
            out[(cell, v)] = sm.midi_sha256(sc.compose(*cell, v)[0])
        return out

    path_a = [c for c in cells for _ in range(visits)]            # dwell on each cell
    path_b = path_a[:]
    random.Random(0).shuffle(path_b)                               # interleaved
    assert run(path_a) == run(path_b)


@pytest.mark.parametrize('cell, develop', [(('rnb', 2), False), (('hiphop', 3), True)])
def test_later_visit_without_earlier_ones(cell, develop):
    """Jumping straight to visit 5 gives the same MIDI as reaching it in order."""
    direct = SessionComposer(1, develop=develop).compose(*cell, 5)[0]
    sc = SessionComposer(1, develop=develop)
    for v in range(5):
        sc.compose(*cell, v)
    assert sm.midi_sha256(direct) == sm.midi_sha256(sc.compose(*cell, 5)[0])
