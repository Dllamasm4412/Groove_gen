"""Unit tests for stimulus_metrics.py on small synthetic segments."""

from __future__ import annotations

import sys
from pathlib import Path

import pretty_midi

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402

A, B, C, F = (frozenset({x}) for x in ('a', 'b', 'c', 'fill'))


def test_feature_classes_are_disjoint():
    names = [set(sm.LOCKED_FEATURES), set(sm.BOUNDED_FEATURES), set(sm.BOUNDED_SET_FEATURES)]
    assert not (names[0] & names[1] or names[0] & names[2] or names[1] & names[2])
    assert 'drum_voices' in sm.BOUNDED_SET_FEATURES


def test_bar_period():
    assert sm.bar_period([A] * 8) == 1
    assert sm.bar_period([A, B] * 4) == 2
    assert sm.bar_period([A, B, A, C] * 2) == 4
    assert sm.bar_period([C] + [A] * 7) == 8


def test_phrase_end_constant_loop_unmarked():
    m = sm.phrase_metrics([A] * 8, [A] * 8)
    assert not m['phrase_end_bar4_marked'] and not m['phrase_end_bar8_marked']
    assert not m['phrase_contrast']


def test_phrase_end_two_bar_clave_unmarked():
    m = sm.phrase_metrics([A, B] * 4, [A, B] * 4)
    assert not m['phrase_end_bar4_marked'] and not m['phrase_end_bar8_marked']
    assert m['drum_period'] == 2


def test_phrase_end_bar1_crash_unmarked():
    m = sm.phrase_metrics([C] + [A] * 7, [C] + [A] * 7)
    assert not m['phrase_end_bar4_marked'] and not m['phrase_end_bar8_marked']


def test_phrase_end_fills_marked_even_when_repeated():
    drums = [A, A, A, F, A, A, A, F]
    m = sm.phrase_metrics(drums, drums)
    assert m['phrase_end_bar4_marked'] and m['phrase_end_bar8_marked']


def test_phrase_end_fill_over_clave_marked():
    drums = [A, B, A, B, A, B, A, F]
    m = sm.phrase_metrics(drums, drums)
    assert not m['phrase_end_bar4_marked'] and m['phrase_end_bar8_marked']
    assert m['phrase_contrast']


def test_set_within():
    assert sm.set_within([36, 42], [36, 38, 42])
    assert not sm.set_within([36, 51], [36, 38, 42])


def _segment(drum_pitches_per_bar: list[list[int]], tempo: float = 120.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='drums')
    piano = pretty_midi.Instrument(program=0, name='piano')
    bar_s = 4 * 60.0 / tempo
    for b, pitches in enumerate(drum_pitches_per_bar):
        for p in pitches:
            drums.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=b * bar_s, end=b * bar_s + 0.1))
        piano.notes.append(pretty_midi.Note(velocity=70, pitch=60, start=b * bar_s, end=(b + 1) * bar_s))
    pm.instruments += [drums, piano]
    return pm


def test_segment_metrics_on_synthetic_loop():
    m = sm.segment_metrics(_segment([[36, 42]] * 8))
    assert m['distinct_drum_bars'] == 1
    assert m['max_identical_drum_run'] == 8
    assert m['drum_period'] == 1
    assert m['drum_voices'] == [36, 42]
    assert m['programs'] == [0]
    assert abs(m['played_tempo_bpm'] - 120.0) < 1e-6
    assert m['n_bars'] == 8
    assert 'drum_voices' not in sm.locked_signature(_segment([[36]] * 8))


def test_segment_metrics_detects_fill():
    bars = [[36, 42]] * 7 + [[36, 38, 45, 47]]
    m = sm.segment_metrics(_segment(bars))
    assert m['phrase_end_bar8_marked'] and not m['phrase_end_bar4_marked']
    assert m['distinct_drum_bars'] == 2
    assert m['max_identical_drum_run'] == 7
