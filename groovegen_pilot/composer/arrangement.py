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
there is no 4-segment rotation. A variation whose drum layer repeats one of
the REPEAT_WINDOW previous visits of the cell, or whose full content repeats
any previous visit, is retried; visit k therefore depends on visits 0..k-1 of
the same cell, which compose() derives itself (in order) when not cached. For hiphop and rock, j counts up from 0 until
the frozen cell would pick the session key for that seed (session key lock,
no transposition); for other genres j = 0.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Optional

import pretty_midi

GEN_VERSION = 'v2a.2'
BLOCK_LEN = 3
BARS = 8
MAX_ATTEMPTS = 12          # variation attempts before falling back to the base segment
RELAX_EVERY = 4            # every RELAX_EVERY failed attempts, vary() gets relax + 1
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
        self._history: dict[tuple, tuple[str, str]] = {}   # (genre, tier, visit) -> (drum_sha, content_sha)

    def _earlier(self, genre: str, tier: int, visit_idx: int) -> list[tuple[str, str]]:
        """(drum_sha, content_sha) of visits 0..visit_idx-1 of the cell, composing
        any that are not cached (so the result does not depend on call order)."""
        for v in range(visit_idx):
            if (genre, int(tier), v) not in self._history:
                self.compose(genre, tier, v)
        return [self._history[(genre, int(tier), v)] for v in range(visit_idx)]

    @staticmethod
    def _structure_failures(pm: pretty_midi.PrettyMIDI, earlier: list[tuple[str, str]]) -> list[str]:
        import stimulus_metrics as sm

        drum = sm.bar_onset_sets(pm, BARS, 'drum')
        drum_sha, content_sha = sm.content_sha(drum), sm.content_sha(sm.bar_onset_sets(pm, BARS))
        fails = [f'bar{e + 1}_unmarked' for e in (3, 7) if not sm._phrase_end_marked(drum, e)]
        if sm.max_identical_run(drum) > MAX_IDENTICAL_RUN:
            fails.append('identical_run')
        if drum_sha in {d for d, _ in earlier[-REPEAT_WINDOW:]}:
            fails.append('drum_repeat')
        if content_sha in {c for _, c in earlier}:
            fails.append('full_repeat')
        return fails

    def compose(self, genre: str, tier: int, visit_idx: int) -> tuple[pretty_midi.PrettyMIDI, dict]:
        import stimulus_metrics as sm
        from composer import generate_segment
        from composer.energy_guard import check
        from composer.variation import vary

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
        # A variation that fails the guard, leaves a phrase end unmarked, or
        # repeats an earlier visit is retried with a derived sub-seed (and,
        # every RELAX_EVERY attempts, looser op caps); if every attempt fails
        # (or the variation code raises), the base segment is used: it is
        # always valid, being a plain composer output.
        out = base
        try:
            for attempt in range(MAX_ATTEMPTS):
                seed = sched.var_seed if attempt == 0 else H('var_attempt', sched.var_seed, attempt)
                varied, vinfo = vary(base, genre, seed, relax=attempt // RELAX_EVERY)
                verdict = check(varied, base, genre)
                verdict.failures += self._structure_failures(varied, earlier)
                verdict.ok = not verdict.failures
                info['gen_attempts'] = attempt + 1
                if verdict.ok:
                    info.update(vinfo, gen_fallback=False, guard_deltas=verdict.deltas)
                    out = varied
                    break
                info['guard_failures'].append(verdict.failures)
        except Exception as exc:  # noqa: BLE001 - any variation bug falls back to base
            info['error'] = repr(exc)
        self._history[(genre, int(tier), int(visit_idx))] = (
            sm.content_sha(sm.bar_onset_sets(out, BARS, 'drum')), sm.content_sha(sm.bar_onset_sets(out, BARS)))
        return out, info
