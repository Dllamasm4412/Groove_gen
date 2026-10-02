"""
Shared pitched-development engine (composer/develop_engine.py): policy
dispatch, default-off scope, determinism, the generic guard, chord context and
the fallback chain. hiphop v2b.1 byte-identity is in test_develop_identity.py.
"""

from __future__ import annotations

import copy
import random
import sys
from pathlib import Path

import pretty_midi
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import develop_engine as de  # noqa: E402
from composer.arrangement import REPEAT_WINDOW, SessionComposer  # noqa: E402

DEV_KEYS = ('dev_version', 'motif_selection', 'motif_role', 'motif_error', 'drum_repeat_window')


@pytest.mark.parametrize('genre', sorted(de.POLICIES))
def test_policy_dispatch(genre):
    pol = de.policy_module(genre)
    for name in ('DEV_VERSION', 'SEED_VERSION', 'NO_CONTEXT', 'read_context', 'develop', 'unchanged_record'):
        assert hasattr(pol, name), f'{genre} policy lacks {name}'
    assert isinstance(pol.POLICY, de.Policy) and pol.POLICY.dev_version == pol.DEV_VERSION


def test_policy_versions_distinct():
    versions = {g: de.policy_module(g).DEV_VERSION for g in de.POLICIES}
    assert versions == {'hiphop': 'v2b.1', 'calm': 'v2c.calm.0', 'lofi': 'v2c.lofi.0'}
    assert de.policy_module('hiphop').SEED_VERSION == 'v2b.0'      # hiphop seeds preserved


def test_unregistered_genre_has_no_policy():
    assert de.policy_module('rnb') is None
    comp = SessionComposer(1, develop=True)
    assert comp._policy('rnb') is None and comp._policy('pop') is None


@pytest.mark.parametrize('cell', [('calm', 2), ('lofi', 3), ('hiphop', 3)])
def test_default_off(cell):
    """SessionComposer(stim) never develops or logs development fields."""
    for v in range(3):
        _, info = SessionComposer(1).compose(*cell, v)
        assert not any(k in info for k in DEV_KEYS)
        assert '+' not in info['gen_version']


@pytest.mark.parametrize('cell', [('calm', 2), ('lofi', 3)])
def test_develop_deterministic_and_labelled(cell):
    a, b = SessionComposer(2, develop=True), SessionComposer(2, develop=True)
    pol = de.policy_module(cell[0])
    for v in range(6):
        (pa, ia), (pb, ib) = a.compose(*cell, v), b.compose(*cell, v)
        assert sm.midi_sha256(pa) == sm.midi_sha256(pb) and ia == ib
        assert ia['dev_version'] == pol.DEV_VERSION and ia['gen_version'].endswith('+' + pol.DEV_VERSION)
        assert ia['drum_repeat_window'] == getattr(pol, 'DRUM_REPEAT_WINDOW', REPEAT_WINDOW)


def test_develop_out_of_order_visit_equals_in_order():
    """Composing visit 5 first fills visits 0-4 from history: same MIDI as in order."""
    a, b = SessionComposer(1, develop=True), SessionComposer(1, develop=True)
    seq = [a.compose('lofi', 3, v)[0] for v in range(6)]
    assert sm.midi_sha256(b.compose('lofi', 3, 5)[0]) == sm.midi_sha256(seq[5])


# --- generic guard ------------------------------------------------------------


def _toy() -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=90)
    for prog, pitches in ((0, (60, 64, 67, 72)), (33, (36, 36, 43, 36))):
        inst = pretty_midi.Instrument(program=prog)
        for i, p in enumerate(pitches):
            inst.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=i * 0.5, end=i * 0.5 + 0.4))
        pm.instruments.append(inst)
    drum = pretty_midi.Instrument(program=0, is_drum=True)
    drum.notes = [pretty_midi.Note(velocity=100, pitch=36, start=i * 0.5, end=i * 0.5 + 0.1) for i in range(4)]
    pm.instruments.append(drum)
    return pm


def test_generic_guard_scope():
    src = _toy()
    ok = copy.deepcopy(src)
    ok.instruments[0].notes[1].pitch = 65
    assert not [f for f in de.guard(ok, src, {0: None}).failures if not f.startswith('pitched_pitch')]
    bad = copy.deepcopy(src)
    bad.instruments[1].notes[0].pitch = 38                   # a locked (non-mutable) track
    assert 'track[1]_changed' in de.guard(bad, src, {0: None}).failures
    vel = copy.deepcopy(src)
    vel.instruments[0].notes[0].velocity = 100               # velocities are part of the shape
    assert 'shape[0]' in de.guard(vel, src, {0: None}).failures
    part = copy.deepcopy(src)
    part.instruments[0].notes[0].pitch = 59                  # below the keep split
    assert 'lh_changed' in de.guard(part, src, {0: (lambda p: p < 62, 'lh_changed')}).failures


# --- chord context ------------------------------------------------------------


def test_chord_context_reads_held_notes_only():
    pm = pretty_midi.PrettyMIDI(initial_tempo=60)
    pad = pretty_midi.Instrument(program=89)
    for p in (50, 54, 57):                                    # D major held the whole bar
        pad.notes.append(pretty_midi.Note(velocity=80, pitch=p, start=0.0, end=4.0))
    pad.notes.append(pretty_midi.Note(velocity=80, pitch=61, start=0.0, end=1.0))   # passing, < half bar
    pm.instruments.append(pad)
    (ctx,) = de.chord_context(pm, (0,), 4.0, bars=1)
    assert ctx.pcs == frozenset({2, 6, 9}) and ctx.root == 2 and ctx.bass == 50
    assert de.chord_tones(ctx, 60, 67) == [62, 66]
    assert de.neighbor_tones(62, ctx, near=2, far=5) == [66, 57]   # no step: nearest per side


# --- fallback chain -----------------------------------------------------------


def _policy(valid=True, guard_ok=True, prev_ok=True):
    rec = lambda m: de.DevRecord(motif=m, theme=(0,), plan=(m,), role='develop', ops=('x',))  # noqa: E731
    from composer.energy_guard import GuardResult
    return de.Policy(
        dev_version='t', history_window=4, n_candidates=3,
        candidate=lambda ctx, records, visit, k, rng, gentle: rec((visit, k, gentle)),
        valid=lambda r, ctx: valid, energy=lambda plan, aux, ctx: {}, cost=lambda s: 0.0,
        realize=lambda src, ctx, plan: src, guard=lambda out, src, ctx: GuardResult(ok=guard_ok, failures=[]),
        previous=lambda prev, rng, ctx: rec(('prev',) if prev_ok else prev.motif),
        unchanged=lambda ctx, records: de.DevRecord((0,), (0,), ((0,),), 'fallback', ()))


def test_select_fallback_chain():
    src, prior = _toy(), [de.DevRecord((9,), (0,), ((9,),), 'base', ())]
    _, rec, info = de.select(_policy(), src, None, prior, 1, 7)
    assert info['motif_selection'] == 'candidate' and rec.motif == (1, 0, False)
    _, rec, info = de.select(_policy(valid=False), src, None, prior, 1, 7)
    assert info['motif_selection'] == 'previous' and info['motif_candidates'] == 6
    _, rec, info = de.select(_policy(valid=False, prev_ok=False), src, None, prior, 1, 7)
    assert info['motif_selection'] == 'unchanged' and rec.role == 'fallback'


def test_select_is_seed_deterministic():
    draws = []

    def cand(ctx, records, visit, k, rng, gentle):
        draws.append(rng.random())
        return de.DevRecord((k,), (0,), ((k,),), 'develop', ())
    pol = de.Policy(**{**_policy().__dict__, 'candidate': cand})
    de.select(pol, _toy(), None, [], 1, 11)
    first = list(draws)
    draws.clear()
    de.select(pol, _toy(), None, [], 1, 11)
    assert draws == first and first[0] == random.Random((11 << 8) | 0).random()
