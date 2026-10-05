"""
Opt-in v2 segment source for the closed-loop runner (run_session_v2
segment_source=; run_pilot_zero --generator v2a | v2c; LIVE_GENERATION_PLAN.md
section 6.18). Without it the runner plays the v1 bank exactly as before.

One SessionComposer per session plus a per-cell visit counter: a revisit
continues that cell's visits (lofi:3, lofi:3, rnb:3, lofi:3 -> lofi:3 visits
0, 1, 2), so a cell's k-th visit is the same MIDI whatever path the controller
took (composer/arrangement.py; tests/test_generator_boundary.py). The source
sees only the cell the controller chose: no HR, target, error, gains, identity
or physiological history. reset() starts the session over (a fresh composer:
same stim seed, same MIDI).
"""

from __future__ import annotations

from typing import Any

import pretty_midi

GENERATORS = {'v2a': False, 'v2c': True}      # --generator name -> SessionComposer(develop=)

# SessionComposer info -> trace columns (run_session_v2.TraceRowV2)
TRACE_KEYS = ('gen_version', 'dev_version', 'stim_seed', 'visit_idx', 'block_idx', 'pos_in_block',
              'base_seed', 'var_seed', 'motif_selection', 'motif_role', 'motif_id', 'motif_theme_id')


class SessionSegmentSource:
    """next_segment(genre, tier) -> (MIDI, info) for the runner's chosen cell."""

    def __init__(self, stim_seed: int = 1, develop: bool = True):
        self.stim_seed = int(stim_seed)
        self.develop = bool(develop)
        self.reset()

    def reset(self) -> None:
        from composer.arrangement import SessionComposer

        self.composer = SessionComposer(self.stim_seed, develop=self.develop)
        self.visits: dict[tuple[str, int], int] = {}

    def next_segment(self, genre: str, tier: int) -> tuple[pretty_midi.PrettyMIDI, dict[str, Any]]:
        cell = (genre, int(tier))
        visit = self.visits.get(cell, 0)
        self.visits[cell] = visit + 1
        return self.composer.compose(genre, int(tier), visit)

    def config(self) -> dict[str, Any]:
        from composer import develop_engine as de
        from composer.arrangement import GEN_VERSION

        out: dict[str, Any] = {'generator': 'v2c' if self.develop else 'v2a', 'stim_seed': self.stim_seed,
                               'gen_version': GEN_VERSION, 'develop': self.develop}
        if self.develop:
            out['dev_versions'] = {g: de.policy_module(g).DEV_VERSION for g in de.POLICIES}
        return out


def trace_fields(info: dict[str, Any]) -> dict[str, Any]:
    """The per-segment provenance columns from a SessionComposer info dict."""
    out = {f'gen_{k}' if k in ('stim_seed', 'visit_idx', 'block_idx', 'pos_in_block', 'base_seed', 'var_seed')
           else k: info.get(k) for k in TRACE_KEYS}
    out['motif_ops'] = ';'.join(info.get('motif_ops') or ()) or None
    out['motif_policy'] = info['genre'] if info.get('dev_version') else None
    out['motif_error'] = info.get('motif_error')
    return out
