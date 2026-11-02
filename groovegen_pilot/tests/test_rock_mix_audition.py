"""
Rock timbre / mix candidate (rock_mix_audition.py): present() changes only
the guitar program and drum velocities; every musical property of the
composed Rock MIDI is preserved, and nothing live imports the candidate.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import rock_mix_audition as rma  # noqa: E402
from composer import generate_segment  # noqa: E402
from composer.arrangement import SessionComposer, cell_plan  # noqa: E402

CASES = [(t, s) for t in range(1, 6) for s in (3, 101, 977)]


def _rock(tier: int, seed: int):
    tempo, density = cell_plan('rock', tier)
    return generate_segment('rock', tempo_bpm=tempo, density=density, duration_bars=8, seed=seed)


def _drum_vels(pm):
    return [n.velocity for i in pm.instruments if i.is_drum for n in i.notes]


@pytest.mark.parametrize('tier,seed', CASES)
def test_rock_composes_program_26_at_every_tier(tier, seed):
    pm = _rock(tier, seed)
    progs = sorted({i.program for i in pm.instruments if not i.is_drum})
    assert progs == [26, 33]


@pytest.mark.parametrize('tier,seed', CASES)
@pytest.mark.parametrize('guitar', list(rma.GUITARS))
@pytest.mark.parametrize('scale', rma.DRUM_SCALES)
def test_present_keeps_musical_content(tier, seed, guitar, scale):
    pm = _rock(tier, seed)
    out, stats = rma.present(pm, rma.GUITARS[guitar], scale)
    assert rma.content_key(out) == rma.content_key(pm)
    assert [(i.name, i.is_drum) for i in out.instruments] == [(i.name, i.is_drum) for i in pm.instruments]
    want = rma.GUITARS[guitar] or 26
    for a, b in zip(pm.instruments, out.instruments):
        assert b.program == (want if (not a.is_drum and a.program == 26) else a.program)
    vin, vout = _drum_vels(pm), _drum_vels(out)
    assert all(1 <= v <= 127 for v in vout)
    assert vout == [max(1, min(127, round(v * scale))) for v in vin]
    # accents keep their order (monotone map)
    assert all((a < b) <= (c <= d) for a, b, c, d in
               ((vin[i], vin[j], vout[i], vout[j]) for i in range(0, len(vin), 7) for j in range(0, len(vin), 11)))
    assert stats['n_drum_127'] == sum(v == 127 for v in vout)
    # input untouched
    assert rma.content_key(pm) == rma.content_key(_rock(tier, seed)) and _drum_vels(pm) == _drum_vels(_rock(tier, seed))


def test_present_is_deterministic():
    pm = _rock(5, 101)
    a, _ = rma.present(pm, 29, 1.2)
    b, _ = rma.present(pm, 29, 1.2)
    assert rma.content_key(a) == rma.content_key(b) and _drum_vels(a) == _drum_vels(b)
    assert [i.program for i in a.instruments] == [i.program for i in b.instruments]


def test_identity_present_is_a_noop():
    pm = _rock(3, 3)
    out, stats = rma.present(pm)
    assert rma.content_key(out) == rma.content_key(pm) and _drum_vels(out) == _drum_vels(pm)
    assert [i.program for i in out.instruments] == [i.program for i in pm.instruments]
    assert stats['n_drum_clamped'] == 0


def test_session_composer_rock_keeps_content():
    sc = SessionComposer(1, develop=True)
    for tier in (1, 3, 5):
        pm, _ = sc.compose('rock', tier, 0)
        out, _ = rma.present(pm, 30, 1.1)
        assert rma.content_key(out) == rma.content_key(pm)


def test_no_velocity_overflow_at_top_scale():
    pm = _rock(5, 3)
    out, stats = rma.present(pm, 30, max(rma.DRUM_SCALES))
    assert max(_drum_vels(out)) <= 127 and min(_drum_vels(out)) >= 1
    assert stats['n_drum_clamped'] == sum(round(v * max(rma.DRUM_SCALES)) > 127 for v in _drum_vels(pm))


def test_candidate_not_imported_by_live_code():
    out = subprocess.run(['grep', '-rlE', r'^\s*(import|from) rock_mix_audition', '--include=*.py', str(PILOT)],
                         capture_output=True, text=True).stdout.split()
    assert [p for p in out if not Path(p).name.startswith('test_')] == []
