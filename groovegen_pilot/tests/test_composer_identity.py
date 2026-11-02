"""
Composer bit-identity regression test (v1 stimulus freeze).

Pins the MIDI bytes the v1 generator produces, so composer.py, the cell
modules, melody_bank.py and the renderer's seed/tier path cannot change the
music silently. Two sets:

  live    every (genre, tier) cell x MelodyBank variant 0-3, through the exact
          live seed chain: MelodyBank.seed_for -> SymbolicSegmentRenderer
          ._derive_seed (session_seed 42) -> RUNG_TIER_CAP -> TIER_TO_DENSITY
          -> generate_segment. These are the segments the live runner plays.
  fixed   every cell x seeds (1, 20003, 77777, 123456789) straight into
          generate_segment, for coverage beyond the bank seeds.

Hashes are sha256 of the bytes pretty_midi writes, so a pretty_midi upgrade
can change them without a musical change; the fixture records the versions it
was made with and a failure message reports both.

Run
---
    cd groovegen_pilot
    ../.venv/bin/python3.12 -m pytest -q tests/test_composer_identity.py

Regenerate (ONLY after an intentional, reviewed change to the v1 generator)
---------------------------------------------------------------------------
    ../.venv/bin/python3.12 tests/test_composer_identity.py --write --force
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import platform
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

FIXTURE = HERE / 'fixtures' / 'composer_identity_v1.json'
SESSION_SEED = 42          # run_pilot_zero.py: SymbolicSegmentRenderer(session_seed=42)
VARIANTS_PER_CELL = 4      # run_session_v2.py: MelodyBank(variants_per_cell=4, base_seed=0)
BANK_BASE_SEED = 0
N_BARS = 8
FIXED_SEEDS = (1, 20003, 77777, 123456789)
TIERS = (1, 2, 3, 4, 5)


def _sha(pm) -> str:
    buf = io.BytesIO()
    pm.write(buf)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def _cell_plan(genre: str, tier: int) -> tuple[float, float]:
    """(tempo, density) exactly as run_session_v2 + render_segment derive them."""
    from composer import GENRE_CFG
    from segment_renderer import RUNG_TIER_CAP, TIER_TO_DENSITY

    cfg = GENRE_CFG[genre]
    tempo = float(cfg.get('tier_tempo', {}).get(tier, cfg['tempo_default']))
    tier_c = max(1, min(int(tier), RUNG_TIER_CAP.get(genre, 5)))
    return tempo, TIER_TO_DENSITY[tier_c]


def compute_live() -> dict[str, dict]:
    from composer import GENRE_CFG, generate_segment
    from melody_bank import MelodyBank
    from segment_renderer import SymbolicSegmentRenderer

    class _Seed:           # _derive_seed only reads self.session_seed
        session_seed = SESSION_SEED

    out = {}
    for genre in GENRE_CFG:
        for tier in TIERS:
            tempo, density = _cell_plan(genre, tier)
            bank = MelodyBank(variants_per_cell=VARIANTS_PER_CELL, base_seed=BANK_BASE_SEED)
            for variant in range(VARIANTS_PER_CELL):
                bank_seed = bank.seed_for(genre, tier)
                composer_seed = SymbolicSegmentRenderer._derive_seed(_Seed, bank_seed)
                pm = generate_segment(genre, tempo_bpm=tempo, density=density,
                                      duration_bars=N_BARS, seed=composer_seed)
                out[f'{genre}:{tier}:v{variant}'] = {
                    'bank_seed': bank_seed, 'composer_seed': composer_seed,
                    'tempo_bpm': tempo, 'density': density, 'sha256': _sha(pm)}
    return out


def compute_fixed() -> dict[str, str]:
    from composer import GENRE_CFG, generate_segment

    out = {}
    for genre in GENRE_CFG:
        for tier in TIERS:
            tempo, density = _cell_plan(genre, tier)
            for seed in FIXED_SEEDS:
                pm = generate_segment(genre, tempo_bpm=tempo, density=density,
                                      duration_bars=N_BARS, seed=seed)
                out[f'{genre}:{tier}:{seed}'] = _sha(pm)
    return out


def _versions() -> dict:
    import numpy
    import pretty_midi
    return {'python': platform.python_version(), 'pretty_midi': pretty_midi.__version__,
            'numpy': numpy.__version__}


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _mismatches(expected: dict, actual: dict, field: str | None) -> list[str]:
    bad = []
    for key in sorted(set(expected) | set(actual)):
        e, a = expected.get(key), actual.get(key)
        if field is not None and e is not None and a is not None:
            if e != a:
                diff = [f for f in e if e[f] != a.get(f)]
                bad.append(f'{key}: {",".join(diff)}')
        elif e != a:
            bad.append(key)
    return bad


def _fail_msg(what: str, bad: list[str], fixture: dict) -> str:
    return (f'{len(bad)} {what} entries differ from {FIXTURE.name} '
            f'(fixture versions {fixture["meta"]["versions"]}, now {_versions()}): '
            + '; '.join(bad[:12]) + (' ...' if len(bad) > 12 else ''))


def test_live_seed_chain_and_midi_identical():
    fixture = _load()
    bad = _mismatches(fixture['live'], compute_live(), field='sha256')
    assert not bad, _fail_msg('live', bad, fixture)


def test_fixed_seed_midi_identical():
    fixture = _load()
    bad = _mismatches(fixture['fixed'], compute_fixed(), field=None)
    assert not bad, _fail_msg('fixed', bad, fixture)


def test_generation_is_order_independent():
    """Same segment regardless of what was generated before it (no global RNG state)."""
    from composer import generate_segment

    tempo, density = _cell_plan('pop', 3)
    first = _sha(generate_segment('pop', tempo_bpm=tempo, density=density,
                                  duration_bars=N_BARS, seed=FIXED_SEEDS[1]))
    for genre in ('latin', 'hiphop', 'rock', 'rnb'):
        t, d = _cell_plan(genre, 4)
        generate_segment(genre, tempo_bpm=t, density=d, duration_bars=N_BARS, seed=7)
    again = _sha(generate_segment('pop', tempo_bpm=tempo, density=density,
                                  duration_bars=N_BARS, seed=FIXED_SEEDS[1]))
    assert first == again
    assert first == _load()['fixed'][f'pop:3:{FIXED_SEEDS[1]}']


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write', action='store_true', help='write the fixture from the current code')
    ap.add_argument('--force', action='store_true', help='overwrite an existing fixture')
    args = ap.parse_args()
    if not args.write:
        ap.error('use pytest to run the checks; --write regenerates the fixture')
    if FIXTURE.exists() and not args.force:
        print(f'{FIXTURE} exists; pass --force to overwrite (only after a reviewed v1 change)')
        return 1
    import subprocess

    def git(*a):
        r = subprocess.run(['git', *a], cwd=PILOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    fixture = {
        'meta': {
            'description': 'v1 composer MIDI sha256 freeze; see tests/test_composer_identity.py',
            'created': _dt.datetime.now().isoformat(timespec='seconds'),
            'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--', '.')),
            'versions': _versions(),
            'session_seed': SESSION_SEED, 'variants_per_cell': VARIANTS_PER_CELL,
            'bank_base_seed': BANK_BASE_SEED, 'n_bars': N_BARS, 'fixed_seeds': list(FIXED_SEEDS),
        },
        'live': compute_live(),
        'fixed': compute_fixed(),
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + '\n')
    print(f'wrote {FIXTURE}: {len(fixture["live"])} live, {len(fixture["fixed"])} fixed')
    return 0


if __name__ == '__main__':
    sys.exit(main())
