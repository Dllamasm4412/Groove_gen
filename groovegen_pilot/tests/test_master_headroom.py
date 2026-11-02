"""
Fixed master attenuation (segment_renderer.MASTER_GAIN_DB, 2026-10-06): one
value on every rendered segment, inside fluidsynth for the 16-bit path and
after the limiter for Rock, so relative levels are unchanged; energy
measurement renders the reference level, so the energy table reproduces.
The hiphop:5 segment that peaked highest in the clipping audit (bank variant
6, +1.49 dBFS in float) no longer reaches full scale.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

SF2 = PILOT.parent / 'soundfonts' / 'Musyng_Kite.sf2'
pytestmark = pytest.mark.skipif(not SF2.exists() or shutil.which('fluidsynth') is None,
                                reason='needs fluidsynth + sf2')
FULL_SCALE = 32767 / 32768


@pytest.fixture(scope='module')
def renderer():
    from segment_renderer import SymbolicSegmentRenderer

    return SymbolicSegmentRenderer(str(SF2))


def _bank(renderer, genre, tier, variant):
    from composer import generate_segment
    from music_features_measured import cell_plan

    tempo, density, seed = cell_plan(genre, tier, variant)
    return generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=8,
                            seed=renderer._derive_seed(seed))


def _db(x):
    return 20 * np.log10(np.abs(x).max())


def test_master_value():
    from segment_renderer import MASTER_GAIN_DB, SymbolicSegmentRenderer

    assert MASTER_GAIN_DB == -2.5
    assert SymbolicSegmentRenderer(str(SF2)).master_gain_db == -2.5


def test_worst_audited_segment_no_longer_clips(renderer):
    pm = _bank(renderer, 'hiphop', 5, 6)
    ref = renderer._render_pm_to_audio(pm, master=False)
    out = renderer._render_pm_to_audio(pm)
    assert (np.abs(ref) >= FULL_SCALE).sum() > 0                  # clipped before
    assert (np.abs(out) >= FULL_SCALE).sum() == 0 and _db(out) <= -1.0 + 0.05


def test_master_is_one_gain_for_every_path(renderer):
    """16-bit path: the attenuated render equals the float render scaled by the
    master to 16-bit precision; Rock: exactly the reference render scaled."""
    from composer import generate_segment
    from composer.arrangement import cell_plan

    k = 10 ** (renderer.master_gain_db / 20)
    pm = _bank(renderer, 'pop', 3, 0)
    flt = renderer._fluidsynth(pm, ['-O', 'float'])
    assert np.abs(renderer._render_pm_to_audio(pm) - flt * k).max() < 2 / 32768
    tempo, density = cell_plan('rock', 5)
    rock = generate_segment('rock', tempo_bpm=tempo, density=density, duration_bars=8, seed=7)
    ref = renderer._render_pm_to_audio(rock, master=False)
    assert np.allclose(renderer._render_pm_to_audio(rock), ref * np.float32(k), atol=1e-7)
    assert _db(ref) == pytest.approx(-1.0, abs=0.01)              # Rock limiter ceiling at reference level


def test_energy_measurement_uses_the_reference_level(renderer):
    """energy_audio renders without the master, so the table's audio features
    are those of the reference level (re-measuring reproduces the table)."""
    from music_features_measured import energy_audio

    pm = _bank(renderer, 'hiphop', 4, 0)
    assert np.array_equal(energy_audio(renderer, pm), renderer._render_pm_to_audio(pm, master=False))
