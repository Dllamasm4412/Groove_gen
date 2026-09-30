"""
Tests for certify_stimuli.py: the envelope / attribution / shift / energy
calculations on small synthetic inputs, the key source it relies on, and one
tiny MIDI-only end-to-end run. No rendering (fluidsynth) needed.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import certify_stimuli as cs  # noqa: E402


def test_envelope_pad_and_floor():
    env = cs.envelope([1.0, 2.0, 3.0])
    sd = float(np.std([1, 2, 3]))
    assert env['lo'] == pytest.approx(1 - 0.25 * sd) and env['hi'] == pytest.approx(3 + 0.25 * sd)
    assert not env['pad_floor_applied']
    # zero spread: the floor (guard tolerance) keeps the envelope from collapsing to a point
    flat = cs.envelope([0.5, 0.5, 0.5], min_pad=0.05)
    assert (flat['lo'], flat['hi']) == pytest.approx((0.45, 0.55)) and flat['pad_floor_applied']
    assert cs.envelope([]) is None
    assert cs.envelope([float('nan'), None, 2.0])['n'] == 1


def test_in_envelope():
    env = cs.envelope([1.0, 3.0], pad_sd=0.0)
    assert cs.in_envelope(1.0, env) and cs.in_envelope(3.0, env)
    assert cs.in_envelope(3.01, env) is False
    assert cs.in_envelope(float('nan'), env) is None
    assert cs.in_envelope(2.0, None) is None


def test_guard_floor_follows_energy_guard_bounds():
    from composer.energy_guard import BOUNDS

    assert BOUNDS['drum_rate'][0] == 'rel'
    assert cs.guard_floor('drum_rate', 2.0) == pytest.approx(2.0 * BOUNDS['drum_rate'][1])
    assert cs.guard_floor('drum_onbeat_ratio', 0.7) == BOUNDS['drum_onbeat_ratio'][1]
    assert cs.guard_floor('pitched_pitch_median', 60.0) == 0.0


def test_attribute_misses():
    var, base = cs.attribute_misses(['flux', 'lufs', 'centroid_hz'], ['lufs'])
    assert var == ['centroid_hz', 'flux'] and base == ['lufs']


def test_shift_check_splits_variation_and_base_parts():
    ref = {'mean': 10.0, 'sd': 2.0}
    s = cs.shift_check(ref, [11.0, 11.0], deltas=[0.2, 0.2], allowed=0.5, n_bases=4)
    assert s['cell_shift'] == pytest.approx(1.0)
    assert s['variation_shift'] == pytest.approx(0.2) and s['variation_ok']
    assert s['base_shift'] == pytest.approx(0.8)
    assert s['base_se'] == pytest.approx(1.0) and s['base_ok']       # 0.8 <= 2 SE = 2.0
    s = cs.shift_check(ref, [14.0], deltas=[0.6], allowed=0.5, n_bases=4)
    assert not s['variation_ok'] and not s['base_ok']                  # base part 3.4 > 2.0
    assert cs.shift_check(None, [1.0], [], 0.5) is None


def test_segment_energy_matches_energy_scores():
    """Per-segment E applied to a cell's means gives the table's own cell energy."""
    from music_features_measured import energy_scores

    table = json.loads((PILOT / 'energy_table_v1.json').read_text())
    z = cs.energy_z_params(table)
    ref = energy_scores(table['cells'], weights=table['weights'])
    for cell, means in table['cells'].items():
        assert cs.segment_energy(means, z, table['weights']) == pytest.approx(ref[cell], abs=1e-9)


def test_rms_dbfs():
    t = np.arange(44100) / 44100
    sine = np.stack([np.sin(2 * np.pi * 440 * t)] * 2, axis=1)
    assert cs.rms_dbfs(sine) == pytest.approx(-3.0103, abs=1e-3)
    assert cs.rms_dbfs(np.zeros((10, 2))) == pytest.approx(-240.0)


def test_key_changes():
    assert cs.key_changes(['C', 'C', None, 'C']) == 0
    assert cs.key_changes(['A', 'C', 'A', None]) == 2
    assert cs.key_changes([None, None]) == 0


def _rep_row(visit, distinct, run, rep=None, drum_rep=None, bar8=True, bar4=True, near=None):
    return {'visit_idx': visit, 'distinct_drum_bars': distinct, 'max_identical_drum_run': run,
            'repeat_dist_visits': rep, 'drum_repeat_dist_visits': drum_rep,
            'phrase_end_bar8_marked': bar8, 'phrase_end_bar4_marked': bar4, 'near_repeat_drum': near}


def test_repetition_stats_and_compare():
    # v1: bank rotation, 1 distinct bar, repeats after 4 visits
    v1 = cs.repetition_stats([_rep_row(v, 1, 8, rep=4 if v >= 4 else None, drum_rep=4 if v >= 4 else None,
                                       bar8=False, bar4=False) for v in range(6)])
    assert v1['r3_exact_repeat_rate'] == pytest.approx(2 / 5) and v1['r3_min_drum_repeat_dist_visits'] == 4
    v2 = cs.repetition_stats([_rep_row(v, 4, 2, near=0.8 if v else None) for v in range(6)])
    c = cs.repetition_compare(v1, v2, 'pop')
    assert c['improved'] and c['targets_met'] and not c['regressions']
    assert set(c['status'].values()) == {'improved'}

    # latin: v1 alternating clave has R2 = 1; v2 R2 = 2 is worse but within target -> not a regression
    v1_latin = cs.repetition_stats([_rep_row(v, 2, 1, bar8=False, bar4=False) for v in range(6)])
    v2_latin = cs.repetition_stats([_rep_row(v, 4, 2) for v in range(6)])
    c = cs.repetition_compare(v1_latin, v2_latin, 'latin')
    assert c['status']['r2_max_identical_drum_run'] == 'worse'
    assert c['improved'] and not c['regressions']

    # hiphop / rock need R1 >= 2 only; a v2 run of 4 identical bars misses R2
    v2_bad = cs.repetition_stats([_rep_row(v, 2, 4) for v in range(6)])
    c = cs.repetition_compare(v1, v2_bad, 'hiphop')
    assert c['targets']['r1'] and not c['targets']['r2'] and not c['targets_met']


def test_check_segment_attribution():
    ref = {
        'locked': [json.dumps({'played_tempo_bpm': 100.0, 'n_tempo_changes': 1, 'n_bars': 8,
                               'programs': [0, 33]}, sort_keys=True)],
        'voices_live4': [36, 38, 42], 'voices_wide': [36, 38, 42, 46],
        'midi_env': {f: None for f in cs.MIDI_GATED},
    }
    ref['midi_env']['drum_rate'] = cs.envelope([4.0, 5.0], pad_sd=0.0)
    ref['midi_env']['vel_mean'] = cs.envelope([60.0, 70.0], pad_sd=0.0)
    base = {'midi_sha256': 'b', 'drum_rate': 4.5, 'vel_mean': 75.0}
    row = {'source': 'v2_session', 'played_tempo_bpm': 100.0, 'n_tempo_changes': 1, 'n_bars': 8,
           'programs': [0, 33], 'tempo_matches_plan': True, 'drum_voices': [36, 38, 46],
           'drum_rate': 5.2, 'vel_mean': 75.0, 'gen_fallback': False}
    cs.check_segment(row, ref, base, audio=False)
    assert row['locked_ok']
    assert row['voices_outside_live4'] == [46] and row['voices_outside_wide'] == []
    assert row['midi_env_miss'] == ['drum_rate', 'vel_mean']
    assert row['midi_env_miss_variation'] == ['drum_rate']      # base inside, varied outside
    assert row['midi_env_miss_base'] == ['vel_mean']            # base already outside
    assert row['segment_ok'] is False


def test_cell_key_matches_frozen_cell_for_v1_bank_seeds():
    """key_root for v1 rows uses cell_key on the derived composer seed; pin it
    to the key the frozen cell records when generating from that seed."""
    from composer import GENRE_CFG
    from composer.arrangement import BARS, cell_key, cell_plan
    from composer.hiphop_cell import generate_hiphop_segment
    from composer.rock_cell import generate_rock_segment
    from stimulus_audit import BankGenerator

    for genre, tier, gen in (('hiphop', 3, generate_hiphop_segment), ('rock', 2, generate_rock_segment)):
        bank = BankGenerator()
        lo, hi = GENRE_CFG[genre]['tempo_range']
        tempo, density = cell_plan(genre, tier)
        for _ in range(3):
            seed = bank.plan(genre, tier)['composer_seed']      # advances the rotation
            score = gen(tempo_bpm=max(lo, min(hi, tempo)), density=density, duration_bars=BARS, seed=seed)
            assert cell_key(genre, tier, seed) == getattr(score.metadata, f'groovegen_{genre}_spec')['key_root']


def test_end_to_end_midi_only(tmp_path):
    out = tmp_path / 'cert'
    assert cs.main(['--cells', 'pop:3,hiphop:1', '--visits', '4', '--wide-variants', '6',
                    '--stim-seeds', '1', '--out', str(out)]) == 0
    with (out / 'certification.csv').open() as f:
        rows = list(csv.DictReader(f))
    assert {r['source'] for r in rows} == set(cs.SOURCES)
    assert sum(r['source'] == 'v1_wide' for r in rows) == 2 * 6
    assert sum(r['source'] == 'v2_session' for r in rows) == 2 * 4
    for cell in ('pop:3', 'hiphop:1'):
        live = {r['midi_sha256'] for r in rows if r['cell'] == cell and r['source'] == 'v1_live'}
        wide = {r['midi_sha256'] for r in rows if r['cell'] == cell and r['source'] == 'v1_wide'}
        assert live <= wide
    assert all(r['lufs'] == '' and r['render_ms'] == '' for r in rows)        # no audio without --audio
    v2 = [r for r in rows if r['source'] == 'v2_session']
    assert all(r['base_midi_sha256'] and r['segment_ok'] in ('True', 'False') for r in v2)
    assert {r['key_root'] for r in v2 if r['genre'] == 'hiphop'} != {''}

    s = json.loads((out / 'certification_summary.json').read_text())
    assert s['fidelity']['v1_live_subset_of_v1_wide'] is True
    assert set(s['cells']) == {'pop:3', 'hiphop:1'}
    for c in s['cells'].values():
        assert set(c['verdict']) == {'repetition_improved', 'repetition_targets_met',
                                     'variation_controlled', 'within_cell_range', 'attention'}
    assert s['key_continuity']['hiphop']['v2_key_locked'] is True
    assert (out / 'cell_summary.csv').exists()
    assert not [p for p in out.rglob('*') if p.suffix in ('.mid', '.midi', '.wav')]


def test_refuses_frozen_v2(tmp_path):
    with pytest.raises(SystemExit):
        cs.main(['--cells', 'pop:3', '--out', str(tmp_path / 'frozen_v2' / 'x')])


def test_rejects_wide_variants_past_tier_offset():
    with pytest.raises(SystemExit):
        cs.parse_args(['--wide-variants', '1000'])
    assert cs.parse_args([]).wide_variants == 128
