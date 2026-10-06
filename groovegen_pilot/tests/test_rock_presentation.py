"""
Rock presentation (composer._gen_rock + renderer directive path): drum
velocities x drum_velocity_scale and a per-tier render gain with a fixed peak
limiter. The composition is unchanged, other genres carry no directive and
render exactly as before.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

from composer import GENRE_CFG, RENDER_DIRECTIVE, generate_segment, render_directive  # noqa: E402
from composer import _composer_legacy as legacy  # noqa: E402
from composer.arrangement import SessionComposer, cell_plan  # noqa: E402
from segment_renderer import LIMIT_CEILING_DBFS, limit_peaks  # noqa: E402

SF2 = PILOT.parent / 'soundfonts' / 'Musyng_Kite.sf2'
CFG = GENRE_CFG['rock']
CASES = [(t, s) for t in range(1, 6) for s in (3, 101, 977)]


def _rock(tier, seed):
    tempo, density = cell_plan('rock', tier)
    return generate_segment('rock', tempo_bpm=tempo, density=density, duration_bars=8, seed=seed)


def _composed(tier, seed):
    """The frozen cell's MIDI before presentation."""
    from composer.rock_cell import generate_segment_rock_adapter
    tempo, density = cell_plan('rock', tier)
    return legacy._score_to_pm(generate_segment_rock_adapter('rock', tempo, density, 8, seed))


def _notes(inst, vel=True):
    return [(n.pitch, round(n.start, 6), round(n.end, 6)) + ((n.velocity,) if vel else ()) for n in inst.notes]


@pytest.mark.parametrize('tier,seed', CASES)
def test_only_drum_velocities_change(tier, seed):
    out, base = _rock(tier, seed), _composed(tier, seed)
    assert [(i.program, i.is_drum, i.name) for i in out.instruments] == \
           [(i.program, i.is_drum, i.name) for i in base.instruments]
    assert np.array_equal(out.get_tempo_changes()[1], base.get_tempo_changes()[1])
    for a, b in zip(out.instruments, base.instruments):
        if not a.is_drum:
            assert _notes(a) == _notes(b)
            continue
        assert _notes(a, vel=False) == _notes(b, vel=False)
        want = [max(1, min(127, round(n.velocity * CFG['drum_velocity_scale']))) for n in b.notes]
        assert [n.velocity for n in a.notes] == want
        assert all(1 <= n.velocity <= 127 for n in a.notes)


@pytest.mark.parametrize('tier,seed', CASES)
def test_directive_carries_the_tier_gain(tier, seed):
    pm = _rock(tier, seed)
    assert render_directive(pm) == CFG['render_gain_db'][tier]
    assert sum(ev.text.startswith(RENDER_DIRECTIVE) for ev in pm.text_events) == 1


def test_choices_as_decided():
    assert CFG['drum_velocity_scale'] == 1.20
    assert sorted(CFG['render_gain_db']) == [1, 2, 3, 4, 5]
    assert sorted({i.program for i in _rock(5, 3).instruments if not i.is_drum}) == [26, 33]


@pytest.mark.parametrize('genre', [g for g in GENRE_CFG if g != 'rock'])
def test_other_genres_carry_no_directive(genre):
    for tier in (1, 3, 5):
        tempo, density = cell_plan(genre, tier)
        pm = generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=8, seed=11)
        assert render_directive(pm) is None


def test_v2c_rock_keeps_presentation():
    sc = SessionComposer(1, develop=True)
    for tier in (1, 5):
        pm, _ = sc.compose('rock', tier, 0)
        assert render_directive(pm) == CFG['render_gain_db'][tier]
        assert max(n.velocity for i in pm.instruments if i.is_drum for n in i.notes) <= 127


def test_rock_is_deterministic():
    a, b = _rock(4, 101), _rock(4, 101)
    assert [_notes(i) for i in a.instruments] == [_notes(i) for i in b.instruments]
    assert [e.text for e in a.text_events] == [e.text for e in b.text_events]


# ---- limiter (synthetic audio, no fluidsynth) ----

def _noise(peak, n=44100 * 2, seed=0):
    x = np.random.default_rng(seed).standard_normal((n, 2)).astype(np.float32)
    return x / np.abs(x).max() * peak


def test_limiter_keeps_peaks_under_ceiling():
    ceil = 10 ** (LIMIT_CEILING_DBFS / 20)
    for peak in (1.0, 2.0, 4.0):
        y = limit_peaks(_noise(peak), 44100)
        assert np.abs(y).max() <= ceil + 1e-6
        assert y.dtype == np.float32


def test_limiter_passes_quiet_audio_untouched():
    x = _noise(0.5)
    assert np.array_equal(limit_peaks(x, 44100), x)


def test_limiter_is_deterministic_and_only_attenuates():
    x = _noise(3.0, seed=4)
    y1, y2 = limit_peaks(x, 44100), limit_peaks(x, 44100)
    assert np.array_equal(y1, y2)
    assert np.all(np.abs(y1) <= np.abs(x) + 1e-7)


# ---- renderer (needs fluidsynth + the soundfont) ----

@pytest.fixture(scope='module')
def renderer():
    if not SF2.exists():
        pytest.skip('soundfont not present')
    from segment_renderer import SymbolicSegmentRenderer
    return SymbolicSegmentRenderer(SF2)


def test_rock_render_stays_under_ceiling(renderer):
    a = renderer._render_pm_to_audio(_rock(5, 3))
    assert a.dtype == np.float32 and a.shape[1] == 2
    assert np.abs(a).max() <= 10 ** (LIMIT_CEILING_DBFS / 20) + 1e-6
    assert np.array_equal(a, renderer._render_pm_to_audio(_rock(5, 3)))


def test_rock_gain_applies(renderer, monkeypatch):
    pm = _rock(1, 3)
    base = renderer._render_pm_to_audio(pm)
    for ev in pm.text_events:
        if ev.text.startswith(RENDER_DIRECTIVE):
            ev.text = f"{RENDER_DIRECTIVE} gain_db={CFG['render_gain_db'][1] + 2:+.2f}"
    louder = renderer._render_pm_to_audio(pm)
    rms = lambda x: float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))  # noqa: E731
    assert 20 * np.log10(rms(louder) / rms(base)) == pytest.approx(2.0, abs=0.3)


def test_tier_tempo_matches_the_frozen_cell():
    """_gen_rock picks the gain tier as the cell picks its tier (nearest tier tempo)."""
    from composer.rock_cell import _TIER_TEMPO
    assert CFG['tier_tempo'] == _TIER_TEMPO
