"""
SessionComposer MIDI identity freeze (v2a.3 default and hiphop v2b.1 develop).

Pins the MIDI bytes of the accepted v2 generator states, so refactoring the
development machinery (composer/develop_engine.py) or adding genre policies
cannot change them silently:

  default   SessionComposer(stim) (v2a.3), every (genre, tier) cell x visits
            0..DEFAULT_VISITS-1, stim seed 1.
  hiphop    SessionComposer(stim, develop=True) on hiphop (v2b.1, checkpoint
            2bdf0e9), tiers 1-5 x stim seeds HIPHOP_STIMS x visits
            0..HIPHOP_VISITS-1: sha256 plus the motif provenance fields.

Hashes are sha256 of the bytes pretty_midi writes (stimulus_metrics.midi_sha256);
the fixture records the versions it was made with.

Run
---
    cd groovegen_pilot
    ../.venv/bin/python3.12 -m pytest -q tests/test_develop_identity.py

Regenerate (ONLY after an intentional, reviewed change to v2a.3 or hiphop v2b.1)
-------------------------------------------------------------------------------
    ../.venv/bin/python3.12 tests/test_develop_identity.py --write --force
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import platform
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

FIXTURE = HERE / 'fixtures' / 'develop_identity_v2b1.json'
DEFAULT_STIM = 1
DEFAULT_VISITS = 4
HIPHOP_STIMS = (1, 2, 19)
HIPHOP_VISITS = 12
TIERS = (1, 2, 3, 4, 5)
MOTIF_FIELDS = ('gen_version', 'dev_version', 'motif_role', 'motif_ops', 'motif_id', 'motif_theme_id',
                'motif_plan', 'motif_selection', 'motif_fallback', 'motif_candidate_idx', 'motif_candidates',
                'motif_error')


def compute_default() -> dict[str, str]:
    import stimulus_metrics as sm
    from composer import GENRE_CFG
    from composer.arrangement import SessionComposer

    comp, out = SessionComposer(DEFAULT_STIM), {}
    for genre in GENRE_CFG:
        for tier in TIERS:
            for v in range(DEFAULT_VISITS):
                out[f'{genre}:{tier}:v{v}'] = sm.midi_sha256(comp.compose(genre, tier, v)[0])
    return out


def compute_hiphop(stims=HIPHOP_STIMS, tiers=TIERS, visits=HIPHOP_VISITS) -> dict[str, dict]:
    import stimulus_metrics as sm
    from composer.arrangement import SessionComposer

    out = {}
    for stim in stims:
        comp = SessionComposer(stim, develop=True)
        for tier in tiers:
            for v in range(visits):
                pm, info = comp.compose('hiphop', tier, v)
                out[f's{stim}:hiphop:{tier}:v{v}'] = {'sha256': sm.midi_sha256(pm),
                                                     **{f: info.get(f) for f in MOTIF_FIELDS}}
    return out


def _versions() -> dict:
    import numpy
    import pretty_midi
    return {'python': platform.python_version(), 'pretty_midi': pretty_midi.__version__,
            'numpy': numpy.__version__}


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _mismatches(expected: dict, actual: dict) -> list[str]:
    bad = []
    for key in sorted(actual):
        e, a = expected.get(key), json.loads(json.dumps(actual[key]))
        if e != a:
            bad.append(key if not isinstance(e, dict) else f'{key}: {",".join(f for f in e if e[f] != a.get(f))}')
    return bad


def _fail_msg(what: str, bad: list[str], fixture: dict) -> str:
    return (f'{len(bad)} {what} entries differ from {FIXTURE.name} '
            f'(fixture versions {fixture["meta"]["versions"]}, now {_versions()}): '
            + '; '.join(bad[:12]) + (' ...' if len(bad) > 12 else ''))


def test_default_v2a3_midi_identical():
    fixture = _load()
    actual = compute_default()
    assert set(actual) == set(fixture['default'])
    bad = _mismatches(fixture['default'], actual)
    assert not bad, _fail_msg('default', bad, fixture)


def test_hiphop_v2b1_develop_midi_and_provenance_identical():
    fixture = _load()
    actual = compute_hiphop()
    assert set(actual) == set(fixture['hiphop'])
    bad = _mismatches(fixture['hiphop'], actual)
    assert not bad, _fail_msg('hiphop', bad, fixture)


def test_hiphop_accepted_audition_hashes_in_fixture():
    """The accepted v2b.1 audition (renders/audition_v2/v2b1_hiphop3_s1, hiphop:3 x8,
    stim 1) is part of the frozen set."""
    fixture = _load()
    assert fixture['meta']['accepted_audition_hiphop3_s1'] == [
        fixture['hiphop'][f's1:hiphop:3:v{v}']['sha256'] for v in range(8)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--write', action='store_true', help='write the fixture from the current code')
    ap.add_argument('--force', action='store_true', help='overwrite an existing fixture')
    args = ap.parse_args()
    if not args.write:
        ap.error('use pytest to run the checks; --write regenerates the fixture')
    if FIXTURE.exists() and not args.force:
        print(f'{FIXTURE} exists; pass --force to overwrite (only after a reviewed change)')
        return 1
    import csv
    import subprocess

    def git(*a):
        r = subprocess.run(['git', *a], cwd=PILOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None

    hiphop = compute_hiphop()
    accepted = None
    manifest = PILOT / 'renders' / 'audition_v2' / 'v2b1_hiphop3_s1' / 'manifest.csv'
    if manifest.exists():
        with manifest.open() as f:
            accepted = [r['midi_sha256'] for r in csv.DictReader(f)]
        mine = [hiphop[f's1:hiphop:3:v{v}']['sha256'] for v in range(len(accepted))]
        if mine != accepted:
            print('current code does not reproduce the accepted v2b.1 audition; not writing')
            return 1
    fixture = {
        'meta': {
            'description': 'SessionComposer MIDI sha256 freeze; see tests/test_develop_identity.py',
            'created': _dt.datetime.now().isoformat(timespec='seconds'),
            'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--', 'composer')),
            'versions': _versions(), 'default_stim': DEFAULT_STIM, 'default_visits': DEFAULT_VISITS,
            'hiphop_stims': list(HIPHOP_STIMS), 'hiphop_visits': HIPHOP_VISITS,
            'accepted_audition_hiphop3_s1': accepted,
        },
        'default': compute_default(),
        'hiphop': hiphop,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + '\n')
    print(f'wrote {FIXTURE}: {len(fixture["default"])} default, {len(fixture["hiphop"])} hiphop')
    return 0


if __name__ == '__main__':
    sys.exit(main())
