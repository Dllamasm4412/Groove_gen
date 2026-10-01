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
motif, groove family: motif memory) and differ in var_seed (drum variation and
fills, composer/variation.py). Block k always gets a new base seed, so there
is no 4-segment rotation. A variation whose drum layer repeats one of the
REPEAT_WINDOW previous visits of the cell, or whose full content repeats any
previous visit, is rejected; visit k therefore depends on visits 0..k-1 of the
same cell, which compose() derives itself (in order) when not cached. For
hiphop and rock, j counts up from 0 until the frozen cell would pick the
session key for that seed (session key lock, no transposition); for other
genres j = 0.

Novelty (v2a.3, plan section 6.10)
----------------------------------
compose() draws RELAX_EVERY candidate variations per round (sub-seeds of
var_seed, round r at relax r; every candidate prefers, at equal op cost, bars
the previous visit of the cell did not play, and from round 1 prefers them
over cheaper ops, crosses excepted) and keeps those whose drum layer has near-
repeat similarity (stimulus_metrics R4) to the previous visit of the cell at
most R4_PREV_MAX, the same bound for every cell. There is no R4 floor: R4 of
one op scales with the bar's onset count (about 0.78 in an 8-onset bar, 0.91
in a 22-onset one), so a floor would bind only the sparse, low-energy cells;
the A bars left as base, one op per varied bar and the energy guard bound how
far a variation moves. Of those, the lowest op cost (variation.COST) that
passes the energy guard is used. If no round has one, the valid candidate
nearest the range is used (novelty_fallback); if none is valid, the base.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Optional

import pretty_midi

GEN_VERSION = 'v2a.3'
BLOCK_LEN = 3
BARS = 8
MAX_ATTEMPTS = 12          # candidate variations before falling back to the base segment
RELAX_EVERY = 4            # candidates per round; round r uses relax r
# Novelty range (drum R4). 0.97 = the 75th percentile of v2a.2's within-block
# R4 (previous visit on the same base; median 0.962): at most 0.97 asks for
# at least that much new drum material every visit, in every cell.
R4_PREV_MAX = 0.97
REPEAT_WINDOW = 4          # no drum-layer repeat within this many earlier visits
MAX_IDENTICAL_RUN = 3      # identical consecutive drum bars (certification R2)
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


def _novelty_gap(c: dict) -> float:
    """How far a candidate's drum R4 lies outside the novelty range (0 = inside)."""
    return 0.0 if c['r4_prev'] is None else max(0.0, c['r4_prev'] - R4_PREV_MAX)


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
        self._history: dict[tuple, tuple] = {}   # (genre, tier, visit) -> (drum_sha, content_sha, drum bar sets, bar signatures)

    def _earlier(self, genre: str, tier: int, visit_idx: int) -> list[tuple]:
        """(drum_sha, content_sha, drum bar sets, bar signatures) of visits 0..visit_idx-1 of the cell, composing
        any that are not cached (so the result does not depend on call order)."""
        for v in range(visit_idx):
            if (genre, int(tier), v) not in self._history:
                self.compose(genre, tier, v)
        return [self._history[(genre, int(tier), v)] for v in range(visit_idx)]

    @staticmethod
    def _structure_failures(pm: pretty_midi.PrettyMIDI, earlier: list[tuple], drum: list) -> list[str]:
        import stimulus_metrics as sm

        drum_sha, content_sha = sm.content_sha(drum), sm.content_sha(sm.bar_onset_sets(pm, BARS))
        fails = [f'bar{e + 1}_unmarked' for e in (3, 7) if not sm._phrase_end_marked(drum, e)]
        if sm.max_identical_run(drum) > MAX_IDENTICAL_RUN:
            fails.append('identical_run')
        if drum_sha in {e[0] for e in earlier[-REPEAT_WINDOW:]}:
            fails.append('drum_repeat')
        if content_sha in {e[1] for e in earlier}:
            fails.append('full_repeat')
        return fails

    @staticmethod
    def _first_passing(cands: list[dict], base, genre: str, info: dict, sort: bool = True) -> Optional[dict]:
        """First candidate (by op cost, then index) that passes the energy guard."""
        from composer.energy_guard import check

        for c in (sorted(cands, key=lambda c: (c['vinfo']['op_cost'], c['k'])) if sort else cands):
            if c['verdict'] is None:
                c['verdict'] = check(c['pm'], base, genre)
                if not c['verdict'].ok:
                    info['guard_failures'].append(c['verdict'].failures)
            if c['verdict'].ok:
                return c
        return None

    def compose(self, genre: str, tier: int, visit_idx: int) -> tuple[pretty_midi.PrettyMIDI, dict]:
        import stimulus_metrics as sm
        from composer import generate_segment
        from composer.variation import bar_signatures, vary

        sched = schedule(self.stim_seed, genre, tier, visit_idx, self.gen_version)
        earlier = self._earlier(genre, tier, sched.visit_idx)
        tempo, density = cell_plan(genre, tier)
        base = generate_segment(genre, tempo_bpm=tempo, density=density,
                                duration_bars=BARS, seed=sched.base_seed)
        info: dict = {
            'generator': 'session', 'gen_version': self.gen_version, 'stim_seed': self.stim_seed,
            'genre': genre, 'tier': int(tier), 'tempo_bpm': tempo, 'density': density,
            **asdict(sched), 'gen_attempts': 0, 'gen_fallback': True, 'form_template': None,
            'bar_roles': None, 'drum_ops': None, 'guard_failures': [], 'error': None,
        }
        # Candidates that leave a phrase end unmarked or repeat an earlier visit
        # are dropped, then those outside the novelty range; the cheapest
        # remaining one that passes the guard wins. Any exception falls back
        # to the base segment: it is always valid, being a plain composer output.
        info.update(gen_candidates=0, gen_candidate_idx=None, gen_sub_seed=None, novelty_rejections=0,
                    novelty_fallback=False, novelty_r4_prev=None, novelty_r4_base=None)
        out = base
        try:
            prev, avoid = earlier[-1][2:] if earlier else (None, frozenset())
            base_drum = sm.bar_onset_sets(base, BARS, 'drum')
            cands, chosen = [], None
            for rnd in range(MAX_ATTEMPTS // RELAX_EVERY):
                pool = []
                for k in range(rnd * RELAX_EVERY, (rnd + 1) * RELAX_EVERY):
                    seed = sched.var_seed if k == 0 else H('var_attempt', sched.var_seed, k)
                    varied, vinfo = vary(base, genre, seed, relax=rnd, avoid=avoid, fresh=rnd >= 1)
                    drum = sm.bar_onset_sets(varied, BARS, 'drum')
                    c = {'k': k, 'seed': seed, 'relax': rnd, 'pm': varied, 'vinfo': vinfo, 'verdict': None,
                         'fails': self._structure_failures(varied, earlier, drum),
                         'r4_prev': None if prev is None else sm.near_repeat_similarity(prev, drum),
                         'r4_base': sm.near_repeat_similarity(base_drum, drum)}
                    cands.append(c)
                    if c['fails']:
                        info['guard_failures'].append(c['fails'])
                    elif _novelty_gap(c) > 0:
                        info['novelty_rejections'] += 1
                    else:
                        pool.append(c)
                chosen = self._first_passing(pool, base, genre, info)
                if chosen is not None:
                    break
            if chosen is None:
                valid = sorted((c for c in cands if not c['fails']),
                               key=lambda c: (_novelty_gap(c), c['relax'], c['vinfo']['op_cost'], c['k']))
                chosen = self._first_passing(valid, base, genre, info, sort=False)
                info['novelty_fallback'] = chosen is not None
            info['gen_candidates'] = info['gen_attempts'] = len(cands)
            if chosen is not None:
                out = chosen['pm']
                info.update(chosen['vinfo'], gen_fallback=False, guard_deltas=chosen['verdict'].deltas,
                            gen_candidate_idx=chosen['k'], gen_sub_seed=chosen['seed'],
                            novelty_r4_prev=None if chosen['r4_prev'] is None else round(chosen['r4_prev'], 4),
                            novelty_r4_base=round(chosen['r4_base'], 4))
        except Exception as exc:  # noqa: BLE001 - any variation bug falls back to base
            info['error'] = repr(exc)
        drum = sm.bar_onset_sets(out, BARS, 'drum')
        self._history[(genre, int(tier), int(visit_idx))] = (
            sm.content_sha(drum), sm.content_sha(sm.bar_onset_sets(out, BARS)), drum, bar_signatures(out, genre))
        return out, info
