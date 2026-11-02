"""
Segment sources for the v3 prototype (opt-in; nothing in the live runner uses them yet).

HipHopV3Source.next_segment('hiphop', tier) -> (PrettyMIDI, info)
    Plays a sequence of compositions. Each composition keeps its identity
    (CompositionSpec) across its form; the requested tier selects the level
    (layers, densities, dynamics) of the next segment only. When a form ends,
    the next composition starts, kept distinct from the ones already played
    (no reuse of their chord loops or hook motifs).

V3SegmentSource
    Drop-in for session_generator.SessionSegmentSource: hip-hop cells play
    v3, every other genre plays the unchanged v2c generator. With
    tempo_policy='tier' (default) the segment tempo is the hip-hop tier tempo
    in GENRE_CFG, which is what run_session_v2 asserts today; 'composition'
    keeps one tempo per composition (musically preferable; the runner needs
    an opt-in change to accept it, see the implementation plan, phase 5).

Content is a pure function of (stim_seed, GEN_VERSION, levels requested so
far): peek() realises a hypothetical next segment without committing it.
"""

from __future__ import annotations

from typing import Any

import pretty_midi

from composer.arrangement import H
from composer.v3 import GEN_VERSION
from composer.v3.hiphop import calibrate_spec, create_spec, plan_segment, realize, segment_info
from composer.v3.levels import DEFAULT_TABLE, load_table
from composer.v3.state import CompositionState, SegmentRecord

TEMPO_POLICIES = ('tier', 'composition')


def _tier_tempo(level: int) -> float:
    from composer import GENRE_CFG

    return float(GENRE_CFG['hiphop']['tier_tempo'][level])


class HipHopV3Source:
    """calibrate=True levels each composition's melodic parts so its level-3
    statement is predicted to meet the loudness target of the levels table
    (composer/v3/levels_<table>.json, measured per soundfont); without a table
    the compositions play uncalibrated and info['levels_table'] is None."""

    def __init__(self, stim_seed: int = 1, tempo_policy: str = 'composition', calibrate: bool = True,
                 levels_table: str = DEFAULT_TABLE):
        if tempo_policy not in TEMPO_POLICIES:
            raise ValueError(f'tempo_policy must be one of {TEMPO_POLICIES}')
        self.stim_seed = int(stim_seed)
        self.tempo_policy = tempo_policy
        self.table_name = levels_table
        self.table = load_table(levels_table) if calibrate else None
        self.reset()

    def reset(self) -> None:
        self.state: CompositionState | None = None
        self.n_compositions = 0
        self.visits = 0
        self.retired_loops: set = set()
        self.retired_motifs: set = set()
        self.last_substyle: str | None = None

    def _new_composition(self) -> CompositionState:
        idx = self.n_compositions
        seed = H('v3', 'hiphop', self.stim_seed, idx, GEN_VERSION)
        spec = create_spec(idx, seed, self.retired_loops, self.retired_motifs, self.last_substyle)
        if self.table is not None:
            spec = calibrate_spec(spec, self.table)
        self.n_compositions += 1
        self.retired_loops |= {spec.loop_a.romans(), spec.loop_b.romans()}
        self.retired_motifs |= {spec.motif.signature(), spec.answer.signature()}
        self.last_substyle = spec.substyle
        return CompositionState(spec)

    def current_state(self) -> CompositionState:
        if self.state is None or self.state.done:
            self.state = self._new_composition()
        return self.state

    def peek(self, level: int) -> tuple[pretty_midi.PrettyMIDI, dict[str, Any]]:
        """The next segment at `level` without committing it (state unchanged)."""
        state = self.current_state()
        level = max(1, min(5, int(level)))
        plan = plan_segment(state, level)
        tempo = _tier_tempo(level) if self.tempo_policy == 'tier' else state.spec.tempo
        pm = realize(plan, tempo)
        info = segment_info(plan)
        info.update(tempo_bpm=tempo, plan=plan)
        return pm, info

    def next_segment(self, genre: str, tier: int) -> tuple[pretty_midi.PrettyMIDI, dict[str, Any]]:
        if genre != 'hiphop':
            raise ValueError(f'HipHopV3Source plays hip-hop only, got {genre!r}')
        import stimulus_metrics as sm

        state = self.current_state()
        pm, info = self.peek(tier)
        plan = info.pop('plan')
        sha = sm.midi_sha256(pm)
        self.state = state.commit(SegmentRecord(plan.ordinal, plan.level, plan.role, plan.op, sha))
        info.update({
            'generator': 'v3', 'genre': 'hiphop', 'tier': int(tier), 'stim_seed': self.stim_seed,
            'visit_idx': self.visits, 'block_idx': state.spec.index, 'pos_in_block': plan.ordinal,
            'base_seed': state.spec.seed, 'var_seed': plan.seed, 'density': None,
            'motif_role': plan.role, 'motif_id': f'{H("motif", state.spec.motif.signature()):08x}',
            'motif_theme_id': state.spec.comp_id, 'motif_ops': [plan.op] if plan.op else [],
            'dev_version': None, 'midi_sha256': sha, 'tempo_policy': self.tempo_policy,
            'state_digest': self.state.digest(), 'mix_trim_db': state.spec.mix_trim_db,
            'levels_table': self.table_name if self.table is not None else None,
        })
        self.visits += 1
        return pm, info


class V3SegmentSource:
    """SessionSegmentSource-compatible: hip-hop from v3, other genres from v2c."""

    def __init__(self, stim_seed: int = 1, tempo_policy: str = 'tier'):
        self.stim_seed = int(stim_seed)
        self.tempo_policy = tempo_policy
        self.reset()

    def reset(self) -> None:
        from session_generator import SessionSegmentSource

        self.hiphop = HipHopV3Source(self.stim_seed, self.tempo_policy)
        self.fallback = SessionSegmentSource(self.stim_seed, develop=True)

    def next_segment(self, genre: str, tier: int):
        if genre == 'hiphop':
            return self.hiphop.next_segment(genre, tier)
        return self.fallback.next_segment(genre, tier)

    def config(self) -> dict[str, Any]:
        return {'generator': 'v3', 'stim_seed': self.stim_seed, 'gen_version': GEN_VERSION,
                'tempo_policy': self.tempo_policy, 'other_genres': self.fallback.config()}
