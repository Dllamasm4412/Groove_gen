"""
v3 hip-hop prototype (composer/v3): determinism, MIDI validity, musical rules,
identity across levels, development across segments, runner compatibility and
the generator boundary. These are software and rule checks; they say nothing
about how the music sounds.
"""

from __future__ import annotations

import ast
import itertools
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import GENRE_CFG  # noqa: E402
from composer.v3 import hiphop as hh  # noqa: E402
from composer.v3.checks import identity_differences, rule_violations  # noqa: E402
from composer.v3.levels import load_table, predict_lufs  # noqa: E402
from composer.v3.source import HipHopV3Source, V3SegmentSource  # noqa: E402
from composer.v3.state import CompositionState  # noqa: E402
from composer.v3.theory import BARS, STEPS_PER_BAR, Grid  # noqa: E402

VOCAL = {52, 53, 54, 85, 91}


def shas(src, levels):
    return [sm.midi_sha256(src.next_segment('hiphop', lv)[0]) for lv in levels]


def at(state, ordinal):
    return replace(state, ordinal=ordinal)


# ----------------------------------------------------------------------------- determinism


def test_same_seed_and_levels_give_identical_midi_across_compositions():
    levels = [3, 2, 4, 5, 1, 3, 3, 3, 4, 2]          # crosses into the second composition
    assert shas(HipHopV3Source(7), levels) == shas(HipHopV3Source(7), levels)


def test_peek_never_changes_what_is_committed():
    plain = HipHopV3Source(3)
    spied = HipHopV3Source(3)
    out_a, out_b = [], []
    for lv in (3, 4, 2, 3, 5, 3, 1, 3, 3):
        for other in (1, 5):
            spied.peek(other)                      # a hypothetical branch
        out_a.append(sm.midi_sha256(plain.next_segment('hiphop', lv)[0]))
        out_b.append(sm.midi_sha256(spied.next_segment('hiphop', lv)[0]))
    assert out_a == out_b


def test_reset_replays_the_session():
    src = HipHopV3Source(11)
    first = shas(src, [3] * 5)
    src.reset()
    assert shas(src, [3] * 5) == first


# ----------------------------------------------------------------------------- diversity


def test_compositions_differ_beyond_key_and_tempo():
    specs = [HipHopV3Source(s).current_state().spec for s in range(1, 13)]
    for a, b in itertools.combinations(specs, 2):
        diff = identity_differences(a, b)        # key and tempo are excluded from identity
        assert len(diff) >= 3, (a.comp_id, b.comp_id, diff)
    assert len({s.motif.signature() for s in specs}) == len(specs)
    assert len({s.loop_a.signature() for s in specs}) >= 10
    assert len({s.substyle for s in specs}) == 3


def test_next_composition_reuses_no_loop_or_hook():
    src = HipHopV3Source(2)
    first = src.current_state().spec
    for _ in first.form:
        src.next_segment('hiphop', 3)
    second = src.current_state().spec
    assert second.comp_id != first.comp_id
    assert second.motif.signature() not in {first.motif.signature(), first.answer.signature()}
    assert second.loop_a.romans() not in {first.loop_a.romans(), first.loop_b.romans()}
    assert second.substyle != first.substyle or len(identity_differences(first, second)) >= 4


# ----------------------------------------------------------------------------- validity and rules


@pytest.mark.parametrize('stim', range(1, 7))
def test_every_segment_is_valid_midi_and_keeps_the_rules(stim):
    st = HipHopV3Source(stim).current_state()
    spec = st.spec
    seg_s = BARS * 240.0 / spec.tempo
    for o in range(len(spec.form)):
        for lv in range(1, 6):
            plan = hh.plan_segment(at(st, o), lv)
            pm = hh.realize(plan)
            assert rule_violations(pm, plan, spec.tempo) == [], (stim, o, lv)
            assert pm.get_end_time() <= seg_s + 1e-6
            assert not any(i.program in VOCAL for i in pm.instruments if not i.is_drum)
            names = {i.name for i in pm.instruments}
            assert {'drums', 'bass', 'chords'} <= names


def test_tempo_policy_tier_uses_the_runner_tempo():
    src = HipHopV3Source(1, tempo_policy='tier')
    for lv in (1, 2, 3, 4, 5):
        pm, info = src.next_segment('hiphop', lv)
        assert info['tempo_bpm'] == GENRE_CFG['hiphop']['tier_tempo'][lv]
        assert abs(pm.get_tempo_changes()[1][0] - info['tempo_bpm']) < 1e-6


# ----------------------------------------------------------------------------- identity across levels


@pytest.mark.parametrize('stim', (1, 2, 3, 4))
def test_levels_change_texture_not_identity(stim):
    st = HipHopV3Source(stim).current_state()
    spec = st.spec
    grid = Grid(spec.tempo, spec.swing)
    for o in range(len(spec.form)):
        plans = {lv: hh.plan_segment(at(st, o), lv) for lv in range(1, 6)}
        pms = {lv: hh.realize(p) for lv, p in plans.items()}
        # same harmony, hook content, fills and role at every level
        assert len({(p.harmony, p.hook_units, p.fills, p.role) for p in plans.values()}) == 1
        # one tempo; the core instruments keep their programs
        assert len({round(pm.get_tempo_changes()[1][0], 6) for pm in pms.values()}) == 1
        core = [{(i.name, i.program) for i in pm.instruments if i.name in ('bass', 'chords', 'hook')}
                for pm in pms.values()]
        assert all(c == core[2] or c <= core[2] for c in core)
        # the level-1 hook is the anchor notes of the full hook
        anchors = {(g, p) for g, p, _, strong in hh.hook_notes(plans[1]) if strong}
        full = {(g, p) for g, p, _, _ in hh.hook_notes(plans[3])}
        assert anchors <= full
        # kick on every downbeat at every level
        for pm in pms.values():
            kicks = [n.start for i in pm.instruments if i.is_drum for n in i.notes if n.pitch == hh.KICK]
            for bar in range(BARS):
                assert any(abs(k - grid.t(bar * STEPS_PER_BAR)) < 1e-6 for k in kicks)
        # activity rises with level
        drums = [sum(len(i.notes) for i in pms[lv].instruments if i.is_drum) for lv in range(1, 6)]
        notes = [sum(len(i.notes) for i in pms[lv].instruments) for lv in range(1, 6)]
        assert drums[0] < drums[1] < drums[2] <= drums[3] <= drums[4]
        assert notes == sorted(notes)


# ----------------------------------------------------------------------------- development across segments


def _hook_line(plan):
    return tuple((g, p) for g, p, _, _ in hh.hook_notes(plan))


@pytest.mark.parametrize('stim', (1, 3, 5, 8))
def test_form_develops_and_returns(stim):
    st = HipHopV3Source(stim).current_state()
    spec = st.spec
    plans = [hh.plan_segment(at(st, o), 3) for o in range(len(spec.form))]
    roles = [p.role for p in plans]
    assert tuple(roles) == spec.form and roles[0] == 'S1' and roles[-1] == 'R2'
    by_role = {p.role: p for p in plans}
    statement = _hook_line(by_role['S'])
    # the return restates the theme (re-orchestrated), the variation changes it audibly
    assert _hook_line(by_role['R']) == statement
    assert by_role['R'].hook_units[0] is spec.motif
    v = set(_hook_line(by_role['V']))
    assert len(v - set(statement)) / len(v) >= 0.3
    # the contrast moves to the second loop, a second motif and the second lead voice;
    # the return brings back the original lead voice
    c_romans = {ch.roman for _, ch in by_role['C'].harmony}
    assert c_romans <= set(spec.loop_b.romans())
    assert by_role['C'].hook_units[0] is spec.answer
    lead = lambda p: next(i.program for i in hh.realize(p).instruments if i.name == 'hook')   # noqa: E731
    assert lead(by_role['C']) == spec.program('double')
    assert lead(by_role['R']) == lead(by_role['S']) == spec.program('hook')
    # within a statement: the open and closed endings are audibly different from the theme
    s = by_role['S']
    units = [tuple(x for x in _hook_line(s) if u * 32 <= x[0] < u * 32 + 32) for u in range(4)]
    shift = lambda xs, k: tuple((g - k, p) for g, p in xs)     # noqa: E731
    assert shift(units[1], 32) != units[0] and shift(units[3], 96) != units[0]
    # consecutive segments never repeat literally
    midis = [sm.midi_sha256(hh.realize(p)) for p in plans]
    assert all(a != b for a, b in zip(midis, midis[1:]))


def test_the_theme_has_two_different_bars():
    for stim in range(1, 13):
        spec = HipHopV3Source(stim).current_state().spec
        line = hh.fit_line(spec.motif.notes, spec.loop_a.bars[0][0][1], spec.key_pc, spec.mode,
                           spec.hook_tonic, *spec.hook_range)
        bar1 = [(s, p) for s, p in line if s < 16]
        bar2 = [(s - 16, p) for s, p in line if s >= 16]
        assert bar1 != bar2, spec.comp_id


def test_state_changes_only_on_commit():
    src = HipHopV3Source(4)
    before = src.current_state()
    src.peek(5)
    assert src.current_state() is before and before.ordinal == 0
    src.next_segment('hiphop', 3)
    assert src.current_state().ordinal == 1 and len(src.current_state().ledger) == 1


# ----------------------------------------------------------------------------- loudness calibration


def test_levels_table_is_pinned_and_calibration_is_bounded():
    table = load_table()
    assert table is not None and len(table['soundfont_sha256']) == 64 and table['fit_residual_sd_db'] < 1.0
    for stim in range(1, 9):
        spec = HipHopV3Source(stim).current_state().spec
        lo, hi = hh.MIX_TRIM_RANGE
        assert lo <= spec.mix_trim_db <= hi
        o = spec.form.index('S')
        pm = hh.realize(hh.plan_segment(CompositionState(spec, ordinal=o), 3))
        pred = predict_lufs(pm, BARS * 240.0 / spec.tempo, table)
        assert abs(pred - table['target_lufs_l3']) < 0.75


# ----------------------------------------------------------------------------- interface and boundary


def test_drop_in_source_matches_v2c_for_other_genres():
    from session_generator import SessionSegmentSource, trace_fields

    v3, v2c = V3SegmentSource(5), SessionSegmentSource(5, develop=True)
    for g, t in (('lofi', 3), ('pop', 3), ('rock', 2), ('lofi', 3)):
        assert sm.midi_sha256(v3.next_segment(g, t)[0]) == sm.midi_sha256(v2c.next_segment(g, t)[0])
    pm, info = v3.next_segment('hiphop', 3)
    assert info['generator'] == 'v3' and isinstance(info['base_seed'], int)
    assert info['tempo_bpm'] == GENRE_CFG['hiphop']['tier_tempo'][3]
    fields = trace_fields(info)
    assert fields['motif_role'] == info['role'] and fields['gen_visit_idx'] == 0


def test_runs_inside_the_unmodified_session_runner():
    pytest.importorskip('pandas')
    import test_session_v2_integration as it

    ladder, _ = it.live_stack()
    cells = [('hiphop', 3), ('hiphop', 4), ('lofi', 3), ('hiphop', 3), ('hiphop', 2), ('rock', 1), ('hiphop', 3)]
    df, seg, renderer = it.run(it.ScriptedController(ladder, cells), ladder, lambda t: 72.0,
                               len(cells), V3SegmentSource(1), initial=cells[0])
    assert list(zip(seg.genre, seg.tier)) == cells
    hip = seg[seg.genre == 'hiphop']
    assert list(hip.generator) == ['v2_session'] * len(hip)       # the runner's label for any segment source
    assert hip.gen_visit_idx.tolist() == list(range(len(hip)))
    assert df.groupby('segment_idx')[it.PLAN_COLS].nunique(dropna=False).max().max() == 1


def test_generator_imports_no_physiology_or_controller():
    banned = {'hr_sources', 'serial_ppg_source', 'estimator_hr_source', 'control', 'user_descriptor',
              'run_session_v2', 'run_pilot_zero', 'hr_trajectory', 'plant_model'}
    for path in (PILOT / 'composer' / 'v3').glob('*.py'):
        tree = ast.parse(path.read_text())
        mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        mods |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not {m.split('.')[0] for m in mods} & banned, path.name
    # session_generator is imported lazily by V3SegmentSource for the v2c fallback only
    assert 'session_generator' not in (PILOT / 'composer' / 'v3' / 'hiphop.py').read_text()


# ----------------------------------------------------------------------------- rendering


def _soundfont():
    for p in (PILOT.parent / 'soundfonts' / 'Musyng_Kite.sf2', Path('/usr/share/sounds/sf2/FluidR3_GM.sf2')):
        if p.exists():
            return p
    return None


@pytest.mark.skipif(shutil.which('fluidsynth') is None or _soundfont() is None, reason='needs fluidsynth + sf2')
def test_a_segment_renders_to_nonempty_audio_of_the_right_length():
    from segment_renderer import SymbolicSegmentRenderer

    pm, info = HipHopV3Source(1).next_segment('hiphop', 3)
    audio = SymbolicSegmentRenderer(str(_soundfont()), sr=44100, session_seed=42)._render_pm_to_audio(pm)
    seg_s = BARS * 240.0 / info['tempo_bpm']
    assert audio.shape[1] == 2 and audio.shape[0] >= int(seg_s * 44100)
    assert np.isfinite(audio).all() and 0.01 < float(np.abs(audio).max()) < 1.0
