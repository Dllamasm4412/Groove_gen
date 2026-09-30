"""
Session arrangement for the v2 controlled-variation generator
(LIVE_GENERATION_PLAN.md sections 4.1, 4.2, 4.6 and 5). Not used by the live
runner; the v1 bank path (MelodyBank -> generate_segment) is unchanged.

Information boundary
--------------------
The generator's whole input is (genre, tier, visit_idx), plus stim_seed and
GEN_VERSION fixed at construction. Tempo and density come from the cell
exactly as run_session_v2 derives them. It never receives HR, targets,
baseline, controller state or participant data: the controller chooses the
cell, the generator only varies material inside it.

Seed schedule
-------------
    block_idx, pos_in_block = divmod(visit_idx, BLOCK_LEN)
    base_seed = H('base', stim_seed, genre, tier, block_idx, j, GEN_VERSION)
    var_seed  = H('var',  stim_seed, genre, tier, visit_idx, GEN_VERSION)

The BLOCK_LEN visits of a block share base_seed (progression, bass, voicing,
motif, groove family: motif memory) and differ in var_seed (drum variation
and fills, composer/variation.py). Block k always gets a new base seed, so
there is no 4-segment rotation. For hiphop and rock, j counts up from 0 until
the frozen cell would pick the session key for that seed (session key lock,
no transposition); for other genres j = 0.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Optional

import pretty_midi

GEN_VERSION = 'v2a.1'
BLOCK_LEN = 3
BARS = 8
MAX_ATTEMPTS = 4           # variation attempts before falling back to the base segment
KEY_LOCK_GENRES = ('hiphop', 'rock')
MAX_KEY_DRAWS = 64         # 5 keys per cell -> expected 5 draws; P(64 misses) ~ 1e-6


def H(*args) -> int:
    """32-bit deterministic hash of the argument tuple (stable across processes)."""
    return int.from_bytes(hashlib.blake2b(repr(args).encode(), digest_size=4).digest(), 'big')


def cell_plan(genre: str, tier: int) -> tuple[float, float]:
    """(tempo, density) exactly as run_session_v2 + SymbolicSegmentRenderer derive them."""
    from composer import GENRE_CFG
    from segment_renderer import RUNG_TIER_CAP, TIER_TO_DENSITY

    cfg = GENRE_CFG[genre]
    tempo = float(cfg.get('tier_tempo', {}).get(tier, cfg['tempo_default']))
    tier_c = max(1, min(int(tier), RUNG_TIER_CAP.get(genre, 5)))
    return tempo, TIER_TO_DENSITY[tier_c]


def cell_key(genre: str, tier: int, seed: int) -> Optional[str]:
    """Key root the frozen hiphop / rock cell picks for this seed (None for other genres).

    Calls the cell's own _resolve_spec read-only, so it follows any change to
    the cell's key choice; tests pin it against generated output.
    """
    if genre == 'hiphop':
        from composer.hiphop_cell import _resolve_spec
    elif genre == 'rock':
        from composer.rock_cell import _resolve_spec
    else:
        return None
    from composer import GENRE_CFG

    tempo, density = cell_plan(genre, tier)
    lo, hi = GENRE_CFG[genre]['tempo_range']
    return _resolve_spec(max(lo, min(hi, tempo)), density, BARS, seed).key_root


def session_key(stim_seed: int, genre: str, gen_version: str = GEN_VERSION) -> Optional[str]:
    """One key per genre per stim_seed, drawn with the cell's own key distribution."""
    if genre not in KEY_LOCK_GENRES:
        return None
    return cell_key(genre, 1, H('key', stim_seed, genre, gen_version))


@dataclass(frozen=True)
class SegmentSchedule:
    visit_idx: int
    block_idx: int
    pos_in_block: int
    base_seed: int
    var_seed: int
    session_key: Optional[str]
    key_draws: int


def schedule(stim_seed: int, genre: str, tier: int, visit_idx: int,
             gen_version: str = GEN_VERSION) -> SegmentSchedule:
    if visit_idx < 0:
        raise ValueError(f'visit_idx must be >= 0, got {visit_idx}')
    block_idx, pos_in_block = divmod(int(visit_idx), BLOCK_LEN)
    want = session_key(stim_seed, genre, gen_version)
    for j in range(MAX_KEY_DRAWS):
        base_seed = H('base', stim_seed, genre, int(tier), block_idx, j, gen_version)
        if want is None or cell_key(genre, tier, base_seed) == want:
            break
    else:
        raise RuntimeError(f'no {genre} base seed in key {want} after {MAX_KEY_DRAWS} draws')
    return SegmentSchedule(
        visit_idx=int(visit_idx), block_idx=block_idx, pos_in_block=pos_in_block,
        base_seed=base_seed, var_seed=H('var', stim_seed, genre, int(tier), int(visit_idx), gen_version),
        session_key=want, key_draws=j + 1,
    )


class SessionComposer:
    """v2 generator: base segment from the unchanged composer + guarded drum variation.

    compose(genre, tier, visit_idx) is the only public entry point; stim_seed
    is fixed at construction. Content depends only on (stim_seed, genre,
    tier, visit_idx, GEN_VERSION), so the k-th visit to a cell is the same
    MIDI for every participant and every controller path.
    """

    def __init__(self, stim_seed: int):
        self.stim_seed = int(stim_seed)
        self.gen_version = GEN_VERSION
        self._drum_sigs: dict[tuple, tuple] = {}     # (genre, tier, visit) -> drum notes

    def _block_sigs(self, genre: str, tier: int, sched: SegmentSchedule) -> set:
        """Drum content of the earlier visits in this block (recomputed if not
        cached, so the result does not depend on which visits ran before)."""
        out = set()
        for v in range(sched.visit_idx - sched.pos_in_block, sched.visit_idx):
            if (genre, int(tier), v) not in self._drum_sigs:
                self.compose(genre, tier, v)
            out.add(self._drum_sigs[(genre, int(tier), v)])
        return out

    def compose(self, genre: str, tier: int, visit_idx: int) -> tuple[pretty_midi.PrettyMIDI, dict]:
        from composer import generate_segment
        from composer.energy_guard import _drum_notes, check
        from composer.variation import vary

        sched = schedule(self.stim_seed, genre, tier, visit_idx, self.gen_version)
        earlier = self._block_sigs(genre, tier, sched)
        tempo, density = cell_plan(genre, tier)
        base = generate_segment(genre, tempo_bpm=tempo, density=density,
                                duration_bars=BARS, seed=sched.base_seed)
        info: dict = {
            'generator': 'session', 'gen_version': self.gen_version, 'stim_seed': self.stim_seed,
            'genre': genre, 'tier': int(tier), 'tempo_bpm': tempo, 'density': density,
            **asdict(sched), 'gen_attempts': 0, 'gen_fallback': True, 'form_template': None,
            'bar_roles': None, 'drum_ops': None, 'guard_failures': [], 'error': None,
        }
        # A variation that fails the guard, or repeats an earlier visit of its
        # block exactly, is retried with a derived sub-seed; if every attempt
        # fails (or the variation code raises), the base segment is used: it
        # is always valid, being a plain composer output.
        out = base
        try:
            for attempt in range(MAX_ATTEMPTS):
                seed = sched.var_seed if attempt == 0 else H('var_attempt', sched.var_seed, attempt)
                varied, vinfo = vary(base, genre, seed)
                verdict = check(varied, base, genre)
                if tuple(_drum_notes(varied)) in earlier:
                    verdict.ok = False
                    verdict.failures.append('repeat_in_block')
                info['gen_attempts'] = attempt + 1
                if verdict.ok:
                    info.update(vinfo, gen_fallback=False, guard_deltas=verdict.deltas)
                    out = varied
                    break
                info['guard_failures'].append(verdict.failures)
        except Exception as exc:  # noqa: BLE001 - any variation bug falls back to base
            info['error'] = repr(exc)
        self._drum_sigs[(genre, int(tier), int(visit_idx))] = tuple(_drum_notes(out))
        return out, info
