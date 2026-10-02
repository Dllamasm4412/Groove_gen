"""
Tests for v2b motif development (composer/motif.py, SessionComposer(develop=True))
and pitched_metrics.py: the hook round-trip in every key and tier, transformation
validity, the motif guard, determinism, drum identity with v2a.3, opt-in scope
(default composer and non-hiphop cells unchanged), the motif history window and
register / rate stability.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import pitched_metrics as pmx  # noqa: E402
import stimulus_metrics as sm  # noqa: E402
from composer import motif as mo  # noqa: E402
from composer.arrangement import BARS, GEN_VERSION, SessionComposer, session_key  # noqa: E402

KEY_SEEDS = {'G': 1, 'D': 3, 'A': 5, 'F': 9, 'C': 19}     # stim_seed -> hiphop session key
TIERS = (1, 2, 3, 4, 5)


def _hook(stim_seed: int, tier: int, visit: int = 0):
    pm, info = SessionComposer(stim_seed).compose('hiphop', tier, visit)
    return pm, mo.read_hook(pm, session_key(stim_seed, 'hiphop'), info['tempo_bpm'])


def _onsets(pm):
    return [sorted(round(n.start, 6) for n in inst.notes) for inst in pm.instruments if not inst.is_drum]


@pytest.mark.parametrize('key', sorted(KEY_SEEDS))
def test_hook_round_trip_every_key_and_tier(key):
    assert session_key(KEY_SEEDS[key], 'hiphop') == key
    for tier in TIERS:
        pm, hook = _hook(KEY_SEEDS[key], tier)
        assert hook is not None and mo.valid(hook.motif, hook), (key, tier)
        assert (hook.lead is None) == (tier == 1)
        same = mo.realize(pm, hook, (hook.motif,) * 4)
        assert sm.content_sha(sm.bar_onset_sets(same, BARS, 'all')) == \
            sm.content_sha(sm.bar_onset_sets(pm, BARS, 'all'))
        assert mo.guard(same, pm, hook).ok


def test_ops_are_count_neutral_and_derive_is_valid():
    for tier in (1, 3, 5):
        _, hook = _hook(1, tier)
        for k in range(40):
            rng = random.Random(k)
            for name, op in mo.OPS.items():
                m, _ = op(hook.motif, rng)
                assert len(m) == len(hook.motif), name
            m, how = mo.derive(hook.motif, rng, hook)
            assert how != 'derive:none' and m != hook.motif and mo.valid(m, hook), (tier, how)


def test_guard_rejects_bass_velocity_offkey_and_lh_changes():
    pm, hook = _hook(1, 3)
    bass = next(i for i, inst in enumerate(pm.instruments) if not inst.is_drum and inst.program == 33)

    def mutated(fn):
        out = mo.realize(pm, hook, (hook.motif,) * 4)
        fn(out)
        return mo.guard(out, pm, hook)

    def first_rh(out):
        return next(n for n in out.instruments[hook.piano].notes if n.pitch >= mo.RH_SPLIT)

    def first_lh(out):
        return next(n for n in out.instruments[hook.piano].notes if n.pitch < mo.RH_SPLIT)

    def offkey(out):
        n = first_rh(out)
        n.pitch += 1 if mo.step_of(n.pitch + 1, hook.tonic) is None else -1

    def velocity(out):
        first_rh(out).velocity = min(127, first_rh(out).velocity + 9)

    def bass_move(out):
        out.instruments[bass].notes[0].pitch += 2

    def lh_move(out):
        first_lh(out).pitch -= 2

    for fn in (offkey, velocity, bass_move, lh_move):
        verdict = mutated(fn)
        assert not verdict.ok and verdict.failures, fn.__name__


def test_default_composer_is_v2a3():
    for v in range(4):
        _, info = SessionComposer(1).compose('hiphop', 3, v)
        assert info['gen_version'] == GEN_VERSION
        assert not any(k.startswith('motif_') or k == 'dev_version' for k in info)


def test_develop_is_deterministic_and_keeps_v2a3_drums():
    base, dev, dev2 = SessionComposer(1), SessionComposer(1, develop=True), SessionComposer(1, develop=True)
    changed = 0
    for v in range(9):
        b, _ = base.compose('hiphop', 3, v)
        d, info = dev.compose('hiphop', 3, v)
        assert sm.midi_sha256(d) == sm.midi_sha256(dev2.compose('hiphop', 3, v)[0])
        assert sm.bar_onset_sets(d, BARS, 'drum') == sm.bar_onset_sets(b, BARS, 'drum')
        assert _onsets(d) == _onsets(b)                     # pitch-only: every pitched onset is kept
        assert info['gen_version'] == f'{GEN_VERSION}+{mo.DEV_VERSION}' and 'motif_error' not in info
        changed += sm.bar_onset_sets(d, BARS, 'pitched') != sm.bar_onset_sets(b, BARS, 'pitched')
    assert changed >= 6


@pytest.mark.parametrize('cell', [('rnb', 4), ('pop', 3), ('latin', 2), ('rock', 3)])
def test_develop_leaves_other_genres_byte_identical(cell):
    base, dev = SessionComposer(1), SessionComposer(1, develop=True)
    for v in range(4):
        (b, bi), (d, di) = base.compose(*cell, v), dev.compose(*cell, v)
        assert sm.midi_sha256(b) == sm.midi_sha256(d) and bi == di


@pytest.mark.parametrize('stim_seed', [1, 19])
def test_motif_history_window_and_stability(stim_seed):
    for tier in (1, 3, 5):
        comp = SessionComposer(stim_seed, develop=True)
        ref = SessionComposer(stim_seed)
        plans, fallbacks = [], 0
        for v in range(12):
            d, info = comp.compose('hiphop', tier, v)
            b, _ = ref.compose('hiphop', tier, v)
            rec = comp._motifs[('hiphop', tier, v)]
            if v and not info['motif_fallback']:
                window = plans[-mo.HISTORY_WINDOW:]
                assert rec.plan not in window and rec.motif not in [p[0] for p in window], (tier, v)
            fallbacks += bool(info['motif_fallback'])
            plans.append(rec.plan)
            fd, fb = pmx.segment_features(d), pmx.segment_features(b)
            assert fd['melody_rate'] == fb['melody_rate'] and fd['bass_rate'] == fb['bass_rate']
            assert abs(fd['melody_median'] - fb['melody_median']) <= 3
            assert sm.bar_onset_sets(d, BARS, 'pitched') and len(d.instruments) == len(b.instruments)
        assert fallbacks <= 1, (tier, fallbacks)


def test_development_error_keeps_the_drum_varied_segment(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('boom')

    monkeypatch.setattr(mo, 'develop', boom)
    b, _ = SessionComposer(1).compose('hiphop', 3, 1)
    d, info = SessionComposer(1, develop=True).compose('hiphop', 3, 1)
    assert sm.midi_sha256(d) == sm.midi_sha256(b)
    assert info['motif_fallback'] and 'boom' in info['motif_error']


def test_pitched_metrics_sanity():
    b0, _ = SessionComposer(1).compose('hiphop', 3, 0)
    same = pmx.visit_compare(b0, b0)
    assert same['melody_exact'] and same['bass_exact'] and same['pitched_r4'] == 1.0
    assert same['pitched_new_bar_frac'] == 0.0 and same['melody_contour_sim'] == 1.0
    comp = SessionComposer(1, develop=True)
    pms = [comp.compose('hiphop', 3, v)[0] for v in range(6)]
    s = pmx.session_summary(pms)
    assert s['pitched_window_repeats'] == 0 and s['melody_exact_prev'] == 0 and s['bass_r4'] == 1.0
    f = pmx.segment_features(b0)
    assert f['melody_rate'] > 0 and f['bass_root_share'] is not None


def _realized_level(pm, hook):
    on = off = 0.0
    notes = [n for n in pm.instruments[hook.piano].notes if n.pitch >= mo.RH_SPLIT]
    if hook.lead is not None:
        notes += pm.instruments[hook.lead].notes
    for n in notes:
        e = mo.note_level(n.pitch, n.velocity)
        if int(round(n.start / hook.sixteenth)) % 4 == 0:
            on += e
        else:
            off += e
    return on, off


@pytest.mark.parametrize('tier', [1, 3, 5])
def test_plan_level_matches_the_realized_midi(tier):
    comp = SessionComposer(1, develop=True)
    for v in range(6):
        pm, _ = comp.compose('hiphop', tier, v)
        b, bi = SessionComposer(1).compose('hiphop', tier, v)
        hook = mo.read_hook(b, session_key(1, 'hiphop'), bi['tempo_bpm'])
        plan = comp._motifs[('hiphop', tier, v)].plan
        assert mo.plan_level(plan, mo.hook_voices(b, hook), hook) == pytest.approx(_realized_level(pm, hook), rel=1e-9)


def test_hook_level_table_matches_the_soundfont():
    import hashlib

    from composer import hook_levels
    sf2 = PILOT / hook_levels.SOUNDFONT
    if not sf2.exists():
        pytest.skip('soundfont not present')
    assert hashlib.sha256(sf2.read_bytes()).hexdigest() == hook_levels.SOUNDFONT_SHA256
    assert set(hook_levels.LEVEL_DB) >= set(range(mo.RH_RANGE[0], mo.RH_RANGE[1] + 1))
    assert mo.note_level(76, 90) > mo.note_level(79, 90) * 2          # the quiet 77-79 zone the guard exists for


@pytest.mark.parametrize('stim_seed', [1, 2])
def test_selection_respects_the_energy_check_and_logs_it(stim_seed):
    kinds = {'candidate', 'gentle', 'previous', 'unchanged'}
    for tier in (1, 3, 5):
        comp = SessionComposer(stim_seed, develop=True)
        for v in range(9):
            _, info = comp.compose('hiphop', tier, v)
            assert info['motif_selection'] in kinds
            assert info['motif_fallback'] == (info['motif_selection'] in ('previous', 'unchanged'))
            assert mo.energy_cost(info['motif_energy']) <= 1, (tier, v, info['motif_energy'])


@pytest.mark.parametrize('cell, stim_seed, visit', [(1, 1, 3), (5, 1, 2), (3, 2, 6), (5, 2, 6), (5, 2, 7)])
def test_v2b0_audio_miss_segments_now_predict_in_tolerance(cell, stim_seed, visit):
    """The five v2b.0 segments that left the audio envelope (plan 6.12) at the default reference."""
    comp = SessionComposer(stim_seed, develop=True)
    _, info = comp.compose('hiphop', cell, visit)
    assert mo.energy_cost(info['motif_energy']) <= 1


def test_balance_repairs_a_level_shift_with_a_valid_motif():
    pm, hook = _hook(1, 3)
    voices = mo.hook_voices(pm, hook)
    tried = repaired = 0
    for k in range(60):
        m, _ = mo.OPS['chord'](hook.motif, random.Random(k))
        rec = mo.MotifRecord(m, m, (m,) * 4, 'develop', ('chord',))
        if not mo.valid(m, hook) or mo.energy_cost(mo.energy_shift(rec.plan, voices, hook)) <= 1:
            continue
        tried += 1
        fixed = mo._balance(rec, hook, voices, lambda r: None if all(mo.valid(p, hook) for p in r.plan) else 'rules')
        if fixed is not None:
            repaired += 1
            assert mo.energy_cost(mo.energy_shift(fixed.plan, voices, hook)) <= 1
            assert all(mo.valid(p, hook) for p in fixed.plan) and fixed.ops[-1].startswith('balance')
    assert tried and repaired >= tried // 2
