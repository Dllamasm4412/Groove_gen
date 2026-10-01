"""
Tests for audition_v2.py: cell parsing, deterministic planning, generation
through the unchanged generators, output naming, manifest contents, and the
live join configuration. Rendering is replaced by a fake (no fluidsynth).
"""

from __future__ import annotations

import csv
import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import audition_v2 as av  # noqa: E402
import stimulus_metrics as sm  # noqa: E402


def _fake_render(pms):
    """8 bars of a quiet tone plus a 2 s release, per segment; render_ms 0."""
    out = []
    for pm in pms:
        n = int((pm.get_end_time() + 2.0) * av.SAMPLE_RATE)
        tone = 0.1 * np.sin(2 * np.pi * 220 * np.arange(n) / av.SAMPLE_RATE)
        out.append((np.stack([tone, tone], axis=1).astype(np.float32), 0.0))
    return out


def test_parse_cell_and_invalid_cells():
    assert av.parse_cell('HipHop:3') == ('hiphop', 3)
    assert av.parse_cells('calm:2, rock:5') == [('calm', 2), ('rock', 5)]
    for bad in ('hiphop', 'hiphop:x', ':3', 'a:b:c'):
        with pytest.raises(ValueError):
            av.parse_cell(bad)
    with pytest.raises(ValueError, match='not on the live ladder'):
        av.parse_cell('latin:5', valid={('latin', 3)})
    with pytest.raises(ValueError):
        av.parse_cells(' , ')


def test_plan_dwell_sequence_and_presets():
    d = av.plan_audition('dwell', [('hiphop', 3)], 8)
    assert d.cells == (('hiphop', 3),) * 8 and d.label() == 'dwell_hiphop3_x8'
    s = av.plan_audition('sequence', [('calm', 2), ('pop', 3)], 2)
    assert s.cells == (('calm', 2), ('calm', 2), ('pop', 3), ('pop', 3))
    assert s.label() == 'sequence_calm2-pop3_x2'
    with pytest.raises(ValueError):
        av.plan_audition('dwell', [('calm', 2), ('pop', 3)], 2)
    with pytest.raises(ValueError):
        av.plan_audition('sequence', [('calm', 2)], 0)
    initial = av.plan_preset('initial')
    assert [a.label() for a in initial] == [
        'dwell_hiphop3_x8', 'dwell_rock3_x8', 'dwell_calm2_x8', 'dwell_rnb4_x6', 'dwell_latin2_x6',
        'sequence_calm2-lofi2-rnb2-pop3-latin3-hiphop3-rock3']
    assert [a.cells[0] for a in av.plan_preset('problem')] == [av.parse_cell(c) for c in av.PROBLEM_CELLS]
    assert av.plan_preset('initial') == initial                       # deterministic
    with pytest.raises(ValueError):
        av.plan_preset('nope')


def test_output_naming():
    d = av.plan_audition('dwell', [('rock', 5)], 4)
    assert av.wav_name(d, 3, 'v2', 1) == '03_dwell_rock5_x4_v2_s1.wav'
    assert av.wav_name(d, 4, 'v1', 1) == '04_dwell_rock5_x4_v1.wav'     # v1 does not use stim_seed
    long = av.plan_audition('sequence', [('calm', 1), ('calm', 2), ('lofi', 1), ('lofi', 2), ('lofi', 3),
                                         ('rnb', 1), ('rnb', 2), ('rnb', 3), ('rnb', 4), ('pop', 1),
                                         ('pop', 2)], 1)
    assert long.label().startswith('sequence_calm1_to_pop2_11cells_') and len(long.label()) < 60


def test_generation_is_the_unchanged_generators_and_deterministic():
    from composer.arrangement import GEN_VERSION, SessionComposer
    from stimulus_audit import BankGenerator

    # a revisit inside a sequence continues the cell's visit count
    aud = av.plan_audition('sequence', [('hiphop', 3), ('calm', 2), ('hiphop', 3)], 1)
    v2 = av.generate(aud, 'v2', 1)
    assert [r['visit_idx'] for _, r in v2] == [0, 0, 1]
    ref = SessionComposer(1)
    assert [r['midi_sha256'] for _, r in v2] == [
        sm.midi_sha256(ref.compose(g, t, v)[0]) for g, t, v in (('hiphop', 3, 0), ('calm', 2, 0), ('hiphop', 3, 1))]
    assert all(r['gen_version'] == GEN_VERSION for _, r in v2)
    assert [r['midi_sha256'] for _, r in av.generate(aud, 'v2', 1)] == [r['midi_sha256'] for _, r in v2]
    assert [r['midi_sha256'] for _, r in av.generate(aud, 'v2', 2)] != [r['midi_sha256'] for _, r in v2]
    # novelty vs the previous visit to the same cell only
    assert 'new_drum_bar_frac' not in v2[1][1] and v2[2][1]['same_base_as_prev'] is True

    bank = BankGenerator()
    v1 = av.generate(aud, 'v1', 1)
    assert [r['midi_sha256'] for _, r in v1] == [
        sm.midi_sha256(bank.generate(g, t)[0]) for g, t in aud.cells]
    assert v1[2][1]['same_base_as_prev'] is False                      # bank rotates seeds


def test_join_uses_the_live_trim_and_mixer():
    import inspect

    import run_pilot_zero
    import run_session_v2

    assert 'CrossfadeMixer(fade_bars=0.25, fade_mode="tail_out")' in inspect.getsource(run_pilot_zero)
    assert (av.FADE_BARS, av.LIVE_FADE_MODE, av.BARS) == (0.25, 'tail_out', 8)
    assert 'audition_v2' not in inspect.getsource(run_session_v2) + inspect.getsource(run_pilot_zero)
    bar = av.bar_duration_frames(90.0, 4, av.SAMPLE_RATE)
    a = np.zeros((20 * bar, 2), np.float32)
    assert av.trim_like_live(a, 90.0).shape[0] == 8 * bar + round(bar * 0.25)
    segs = [av.trim_like_live(a, 90.0)] * 3
    joined, starts, _ = av.join_like_live(segs, [90.0] * 3)
    assert starts == [0, 8 * bar, 16 * bar] and joined.shape[0] == 24 * bar + round(bar * 0.25)


def test_main_writes_wav_manifest_and_notes(tmp_path):
    out = tmp_path / 'aud'
    assert av.main(['--mode', 'dwell', '--cell', 'calm:2', '--visits', '4', '--generator', 'both',
                    '--out', str(out)], render=_fake_render) == 0
    wavs = sorted(p.name for p in out.glob('*.wav'))
    assert wavs == ['01_dwell_calm2_x4_v1.wav', '02_dwell_calm2_x4_v2_s1.wav']
    with wave.open(str(out / wavs[1])) as w:
        assert w.getnchannels() == 2 and w.getframerate() == av.SAMPLE_RATE and w.getnframes() > 0
    with (out / 'manifest.csv').open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 8 and tuple(rows[0]) == av.MANIFEST_FIELDS
    v2 = [r for r in rows if r['generator'] == 'v2']
    assert [r['visit_idx'] for r in v2] == ['0', '1', '2', '3']
    assert all(r['stim_seed'] == '1' and r['gen_version'] and r['midi_sha256'] and r['var_seed'] for r in v2)
    assert [float(r['start_s']) for r in v2] == sorted(float(r['start_s']) for r in v2)
    assert v2[1]['same_base_as_prev'] == 'True' and v2[3]['same_base_as_prev'] == 'False'   # block of 3
    meta = json.loads((out / 'manifest.json').read_text())
    assert meta['meta']['join']['fade_mode'] == 'tail_out' and meta['meta']['stim_seed'] == 1
    assert [a['n_segments'] for a in meta['auditions']] == [4, 4]
    notes = (out / 'LISTENING_NOTES.md').read_text()
    assert '### Long dwell' in notes and '02_dwell_calm2_x4_v2_s1.wav' in notes
    assert not (out / 'segments').exists()


def test_main_rejects_invalid_cells_and_frozen_out(tmp_path):
    with pytest.raises(SystemExit):
        av.main(['--mode', 'dwell', '--cell', 'latin:5', '--out', str(tmp_path / 'a')], render=_fake_render)
    with pytest.raises(SystemExit):
        av.main(['--mode', 'sequence', '--cells', 'calm:2,polka:1', '--out', str(tmp_path / 'b')],
                render=_fake_render)
    with pytest.raises(SystemExit):
        av.main(['--mode', 'dwell', '--cell', 'calm:2', '--out', str(tmp_path / 'frozen_v2' / 'x')],
                render=_fake_render)
    with pytest.raises(SystemExit):
        av.parse_args(['--mode', 'dwell', '--cell', 'calm:2', '--workers', '6'])
    with pytest.raises(SystemExit):
        av.parse_args(['--preset', 'initial', '--mode', 'dwell'])
