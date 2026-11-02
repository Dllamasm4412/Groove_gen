"""
composer/v3/genres.py (v3.genres.0): the six non-hip-hop v3 styles used for the
candidate excerpt corpus. Software and rule checks only; they say nothing about
how the music sounds.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import GENRE_CFG  # noqa: E402
from composer.v3 import genres as G  # noqa: E402

CAPS = {'calm': 2, 'lofi': 3, 'rnb': 4, 'pop': 5, 'latin': 3, 'rock': 5}


def test_deterministic():
    for genre in G.GENRES:
        a = G.compose_excerpt(genre, 2, 12345)[0]
        b = G.compose_excerpt(genre, 2, 12345)[0]
        assert sm.midi_sha256(a) == sm.midi_sha256(b)


@pytest.mark.parametrize('genre', G.GENRES)
def test_every_tier_passes_the_rule_checks(genre):
    for seed in range(1, 16):
        spec = G.create_spec(genre, seed)
        for tier in range(1, CAPS[genre] + 1):
            pm = G.realize(spec, tier)
            assert G.rule_violations(pm, spec, tier) == [], (genre, seed, tier)
            assert not {i.program for i in pm.instruments if not i.is_drum} & G.VOCAL_PROGRAMS


def test_tempo_is_the_configuration_tempo():
    for genre, cap in CAPS.items():
        for tier in range(1, cap + 1):
            pm, info, _ = G.compose_excerpt(genre, tier, 7)
            cfg = GENRE_CFG[genre]
            want = float(cfg.get('tier_tempo', {}).get(tier, cfg['tempo_default']))
            assert info['tempo_bpm'] == want
            assert abs(pm.get_tempo_changes()[1][0] - want) < 1e-6


def test_tier_changes_realisation_not_composition():
    for genre, cap in CAPS.items():
        spec = G.create_spec(genre, 99)
        lo, hi = G.realize(spec, 1), G.realize(spec, cap)

        def notes(pm, drums):
            return sum(len(i.notes) for i in pm.instruments if i.is_drum == drums)
        assert notes(hi, True) > notes(lo, True), genre          # more rhythmic activity at the top tier
        assert G.melody_notes(spec) == G.melody_notes(G.create_spec(genre, 99))
        assert spec.harmony()[-1][1].root_pc(spec.key_pc) == spec.key_pc     # the phrase closes on the tonic


def test_compositions_differ_across_seeds():
    for genre in G.GENRES:
        specs = [G.create_spec(genre, s) for s in range(1, 21)]
        assert len({s.motif.signature() for s in specs}) == 20
        assert len({s.loop for s in specs}) >= 4


def test_no_octave_leaps_inside_a_phrase():
    big = total = 0
    for genre in G.GENRES:
        for seed in range(1, 21):
            ps = [p for _, _, p, _ in G.melody_notes(G.create_spec(genre, seed))]
            total += len(ps) - 1
            big += sum(abs(b - a) >= 12 for a, b in zip(ps, ps[1:]))
    assert big == 0 and total > 1000


def test_hiphop_excerpt_is_the_v3_hiphop_statement():
    from composer.v3.hiphop import plan_segment, realize
    from composer.v3.source import HipHopV3Source

    pm, info, plan = G.compose_excerpt('hiphop', 3, 4242)
    state = HipHopV3Source(4242, tempo_policy='tier').current_state()
    ref = realize(plan_segment(replace(state, ordinal=1), 3), 90.0)
    assert sm.midi_sha256(pm) == sm.midi_sha256(ref) and info['role'] == 'S' and info['tempo_bpm'] == 90.0


def test_live_path_does_not_import_genres():
    for name in ('run_session_v2.py', 'run_pilot_zero.py', 'control.py', 'session_generator.py', 'segment_renderer.py'):
        src = (PILOT / name).read_text()
        assert 'composer.v3.genres' not in src and 'from composer.v3 import genres' not in src, name
