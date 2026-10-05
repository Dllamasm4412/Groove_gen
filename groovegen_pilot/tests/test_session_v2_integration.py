"""
Opt-in v2 generator in the closed-loop session (run_session_v2 segment_source=,
session_generator.SessionSegmentSource; LIVE_GENERATION_PLAN.md section 6.18).
Headless: the live ladder and LadderMPC as run_pilot_zero builds them, a fake
clock, a scripted HR source, a fake renderer (silence of the MIDI's length),
NullPlayer. No audio, no hardware.

A hold, B step up, C step down (real controller); D revisit and E genre
transitions (scripted controller); F restart determinism; G default mode
(v1 bank) unchanged. Plus: the source sees only (genre, tier), tempo agrees for
every live cell, within-segment plan invariance.
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import simulate_session_v2 as sim  # noqa: E402
import stimulus_metrics as sm  # noqa: E402
from composer import GENRE_CFG  # noqa: E402
from composer.arrangement import SessionComposer  # noqa: E402
from control import ControlDecision  # noqa: E402
from crossfade import CrossfadeMixer  # noqa: E402
from hr_sources import HRReading  # noqa: E402
from melody_bank import MelodyBank  # noqa: E402
from player import NullPlayer  # noqa: E402
from run_session_v2 import SessionConfigV2, TraceRowV2, run_session_v2  # noqa: E402
from session_generator import GENERATORS, TRACE_KEYS, SessionSegmentSource  # noqa: E402

SR = 8000
RENDER_S = 1.2                    # fake render latency (clock advance per render)
GEN_COLS = [f for f in TraceRowV2._fields if f.startswith(('gen_', 'motif_'))] + ['dev_version']
PLAN_COLS = ['genre', 'tier', 'rung', 'tempo_bpm', 'seed', 'generator', 'gen_visit_idx',
             'gen_base_seed', 'motif_id', 'motif_selection', 'render_s', 'planned_s']


def live_stack():
    """The ladder and controller run_pilot_zero builds with its default flags."""
    ladder, controller, _ = sim.live_stack()
    return ladder, controller


class Clock:
    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += max(float(s), 0.0)

    def time(self):
        return 1.7e9 + self.t

    def perf(self):
        return self.t


class ScriptedHR:
    """HR = fn(session seconds); None = no reading (stale)."""

    def __init__(self, clock, fn):
        self.clock, self.fn = clock, fn

    def read(self):
        bpm = self.fn(self.clock.perf())
        return None if bpm is None else HRReading(self.clock.time(), float(bpm), 'sim', True)


class FakeRenderer:
    """Silence as long as the segment plus a 1 s release tail; advances the clock
    by RENDER_S per render. Records what it was asked to render."""

    def __init__(self, clock):
        self.clock, self.pms, self.bank_calls = clock, [], []

    def _silence(self, seconds):
        self.clock.sleep(RENDER_S)
        return np.zeros((int((seconds + 1.0) * SR), 2), dtype=np.float32)

    def render_pm(self, pm):
        self.pms.append(sm.midi_sha256(pm))
        return self._silence(pm.get_end_time())

    def render_segment(self, *, genre, tempo_bpm, tier, n_bars, segment_idx):
        self.bank_calls.append((genre, tempo_bpm, tier, n_bars, segment_idx))
        return self._silence(n_bars * 240.0 / tempo_bpm)


class ScriptedController:
    """Plays a fixed cell sequence (D, E): stands in for LadderMPC.step."""

    def __init__(self, ladder, cells):
        self.ladder, self.rungs = ladder, [ladder.index(g, t) for g, t in cells]

    def step(self, *, hr_bpm, hr_target, hr_base, current_rung, arousal_1_9=None):
        r = self.rungs.pop(0)
        c = self.ladder.by_rung[r]
        return ControlDecision(r, c.genre, c.tier, hr_target, hr_target, False, 1.0, 'ok', False,
                               hr_bpm, hr_target - hr_bpm, 'scripted', r)



class SpySource(SessionSegmentSource):
    def next_segment(self, *args, **kwargs):
        self.calls = getattr(self, 'calls', []) + [(args, kwargs)]
        return super().next_segment(*args, **kwargs)


def run(controller, ladder, hr_fn, n, source, initial=('lofi', 3), hr_target=80.0, policy='baseline'):
    clock = Clock()
    renderer = FakeRenderer(clock)
    trace = run_session_v2(
        ScriptedHR(clock, hr_fn), renderer, NullPlayer(), CrossfadeMixer(sample_rate=SR, fade_bars=0.25,
                                                                          fade_mode='tail_out'),
        ladder, controller,
        SessionConfigV2(bars_per_segment=8, sample_rate=SR, fade_bars=0.25, hr_poll_s=1.0,
                        stale_hr_policy=policy, max_segments=n),
        hr_target_bpm=hr_target, hr_baseline_bpm=70.0, initial_rung=ladder.index(*initial),
        segment_source=source, sleep_fn=clock.sleep, time_fn=clock.time, perf_counter_fn=clock.perf)
    df = pd.DataFrame([r._asdict() for r in trace])
    return df, df.groupby('segment_idx').first().reset_index(), renderer


def check_visits(seg):
    """Each cell's visits are 0, 1, 2, ... in session order, wherever they fall."""
    seen = defaultdict(int)
    for g, t, v in zip(seg.genre, seg.tier, seg.gen_visit_idx):
        assert v == seen[(g, t)]
        seen[(g, t)] += 1


def check_common(df, seg, renderer, ladder):
    assert df.groupby('segment_idx')[PLAN_COLS].nunique(dropna=False).max().max() == 1
    assert (seg.generator == 'v2_session').all()
    assert not seg.motif_error.notna().any()
    for g, t, bpm in zip(seg.genre, seg.tier, seg.tempo_bpm):
        assert bpm == float(GENRE_CFG[g].get('tier_tempo', {}).get(t, GENRE_CFG[g]['tempo_default']))
    assert renderer.bank_calls == [] and len(renderer.pms) == len(seg)
    check_visits(seg)
    # MIDI = the cell's k-th visit composed directly (path independence)
    ref = SessionComposer(int(seg.gen_stim_seed.iloc[0]), develop=True)
    for (g, t, v), sha in zip(zip(seg.genre, seg.tier, seg.gen_visit_idx), renderer.pms):
        assert sm.midi_sha256(ref.compose(g, int(t), int(v))[0]) == sha
    assert np.allclose(seg.render_s, RENDER_S)
    assert (seg.queued_ahead_s.iloc[1:] > 0).all()                  # never ran dry


@pytest.fixture(scope='module')
def stack():
    return live_stack()


def test_a_hold(stack):
    """Stale HR, stale_hr_policy='hold' (the runner's): one cell, visits 0..n-1, each
    visit developed, no consecutive repeat."""
    ladder, _ = stack
    _, ctl = live_stack()
    df, seg, rend = run(ctl, ladder, lambda t: None, 8, SessionSegmentSource(1), policy='hold')
    check_common(df, seg, rend, ladder)
    assert set(zip(seg.genre, seg.tier)) == {('lofi', 3)} and (seg.control_mode == 'stale_hold').all()
    assert list(seg.gen_visit_idx) == list(range(8))
    assert seg.dev_version.notna().all() and all(a != b for a, b in zip(rend.pms, rend.pms[1:]))


def test_b_step_up(stack):
    """HR held 10 bpm under target: the controller climbs (then rotates near its
    stall cell, control.py saturation rotation); the source follows."""
    ladder, _ = stack
    _, ctl = live_stack()
    df, seg, rend = run(ctl, ladder, lambda t: 70.0, 12, SessionSegmentSource(1), hr_target=80.0)
    check_common(df, seg, rend, ladder)
    assert seg.cell_u.iloc[-1] > seg.cell_u.iloc[0] and seg.cell_u.iloc[:5].is_monotonic_increasing
    assert len(set(zip(seg.genre, seg.tier))) > 1


def test_c_step_down(stack):
    """HR held 15 bpm over target from a high cell: the controller descends (then
    rotates near its stall cell)."""
    ladder, _ = stack
    _, ctl = live_stack()
    top = ladder.by_rung[len(ladder.cells) - 2]
    df, seg, rend = run(ctl, ladder, lambda t: 95.0, 12, SessionSegmentSource(1),
                        initial=(top.genre, top.tier), hr_target=80.0)
    check_common(df, seg, rend, ladder)
    assert seg.cell_u.iloc[-1] < seg.cell_u.iloc[0] and seg.cell_u.iloc[:5].is_monotonic_decreasing
    assert len(set(zip(seg.genre, seg.tier))) > 1


def test_d_revisit_continues_visits(stack):
    """lofi:3, lofi:3, rnb:3, rnb:3, lofi:3, hiphop:3, lofi:3: lofi continues 0-3."""
    ladder, _ = stack
    cells = [('lofi', 3), ('lofi', 3), ('rnb', 3), ('rnb', 3), ('lofi', 3), ('hiphop', 3), ('lofi', 3)]
    df, seg, rend = run(ScriptedController(ladder, cells), ladder, lambda t: 75.0, len(cells),
                        SessionSegmentSource(2))
    check_common(df, seg, rend, ladder)
    assert list(zip(seg.genre, seg.tier)) == cells
    assert list(seg.gen_visit_idx) == [0, 1, 0, 1, 2, 0, 3]
    assert list(seg.gen_block_idx) == [0, 0, 0, 0, 0, 0, 1]          # lofi visit 3 opens block 1


def test_e_genre_transitions(stack):
    """Calm -> Lo-fi -> R&B -> Pop -> Latin -> Hip-hop -> Rock: every policy (rock has
    none, so no dev_version) and every generator boundary in one session."""
    ladder, _ = stack
    cells = [('calm', 2), ('lofi', 3), ('rnb', 3), ('pop', 3), ('latin', 3), ('hiphop', 3), ('rock', 3)]
    df, seg, rend = run(ScriptedController(ladder, cells), ladder, lambda t: 75.0, len(cells),
                        SessionSegmentSource(1))
    check_common(df, seg, rend, ladder)
    assert list(zip(seg.genre, seg.tier)) == cells
    assert list(seg.motif_policy.fillna('-')) == ['calm', 'lofi', 'rnb', 'pop', 'latin', 'hiphop', '-']
    assert seg.dev_version.iloc[:-1].notna().all() and pd.isna(seg.dev_version.iloc[-1])


def test_f_restart_determinism(stack):
    """Two sessions with the same stim seed and HR play the same MIDI and provenance;
    reset() returns a source to its start; another stim seed differs."""
    ladder, _ = stack
    out = []
    src = SessionSegmentSource(3)
    for s in (src, src, SessionSegmentSource(3), SessionSegmentSource(4)):
        s.reset()
        _, ctl = live_stack()
        _, seg, rend = run(ctl, ladder, lambda t: 72.0 + 0.02 * t, 10, s)
        out.append((rend.pms, seg[['genre', 'tier', 'rung'] + GEN_COLS].to_dict('list')))
    assert out[0] == out[1] == out[2]
    assert out[3][0] != out[0][0]


def test_g_default_mode_unchanged(stack):
    """No segment_source: the v1 bank path, render_segment with melody_bank seeds,
    generator 'v1_bank', every gen_* / motif_* column empty."""
    ladder, _ = stack
    _, ctl = live_stack()
    df, seg, rend = run(ctl, ladder, lambda t: 70.0, 10, None)
    assert rend.pms == [] and len(rend.bank_calls) == 10
    bank = MelodyBank(variants_per_cell=4, base_seed=0)
    assert [c[4] for c in rend.bank_calls] == [bank.seed_for(g, t) for g, t in zip(seg.genre, seg.tier)]
    assert (df.generator == 'v1_bank').all() and df[GEN_COLS].isna().all().all()
    assert df.groupby('segment_idx')[PLAN_COLS].nunique(dropna=False).max().max() == 1


def test_source_sees_only_the_cell(stack):
    """run_session_v2 calls next_segment(genre, tier) positionally, nothing else."""
    ladder, _ = stack
    _, ctl = live_stack()
    src = SpySource(1)
    run(ctl, ladder, lambda t: 70.0, 6, src)
    assert len(src.calls) == 6
    for args, kwargs in src.calls:
        assert kwargs == {} and len(args) == 2
        assert isinstance(args[0], str) and isinstance(args[1], (int, np.integer))


def test_session_generator_imports_no_physiology():
    """session_generator imports only the composer side (tests/test_generator_boundary.py)."""
    from tests.test_generator_boundary import FORBIDDEN

    tree = ast.parse((PILOT / 'session_generator.py').read_text())
    mods = {a.name.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {n.module.split('.')[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not mods & set(FORBIDDEN)


def test_tempo_and_length_agree_on_every_live_cell(stack):
    """For every live ladder cell the composer's tempo is the runner's tempo and the
    MIDI fits what the runner keeps: 8 bars + one crossfade (a tied last bass note
    runs 0.24-0.31 s past bar 8 at lofi:2 / rnb:3, inside the crossfade)."""
    ladder, _ = stack
    for develop in GENERATORS.values():
        sc = SessionComposer(1, develop=develop)
        for c in ladder.cells:
            pm, info = sc.compose(c.genre, c.tier, 0)
            cfg = GENRE_CFG[c.genre]
            bpm = float(cfg.get('tier_tempo', {}).get(c.tier, cfg['tempo_default']))
            assert info['tempo_bpm'] == bpm, (c.genre, c.tier)
            assert pm.get_end_time() <= (8 + 0.25) * 240.0 / bpm + 1e-6, (c.genre, c.tier)


def test_config_and_trace_keys():
    cfg = SessionSegmentSource(5).config()
    assert cfg['generator'] == 'v2c' and cfg['stim_seed'] == 5 and cfg['dev_versions']['latin'] == 'v2c.latin.0'
    assert 'rock' not in cfg['dev_versions']
    assert SessionSegmentSource(5, develop=False).config()['generator'] == 'v2a'
    fields = set(TraceRowV2._fields)
    assert {k if k.startswith(('gen_', 'motif_', 'dev_')) else f'gen_{k}' for k in TRACE_KEYS} <= fields
