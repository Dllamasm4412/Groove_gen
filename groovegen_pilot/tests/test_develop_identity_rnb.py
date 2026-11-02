"""
SessionComposer develop-mode MIDI identity freeze for the accepted R&B policy
(rnb v2c.rnb.0; developer listening approved 2026-10-01).

Pins SessionComposer(stim, develop=True) on rnb, tiers 1-5 x stim seeds STIMS x
visits 0..VISITS-1: sha256 plus the development provenance fields, so later genre
policies (pop, ...) or engine changes cannot change the approved output silently.
The approved auditions (renders/audition_v2/v2c_rnb3_s1, v2c_rnb2_s1) are part of
the frozen set. calm / lofi are pinned by tests/test_develop_identity_v2c.py,
hiphop v2b.1 and the v2a.3 default by tests/test_develop_identity.py.

Run
---
    cd groovegen_pilot
    ../.venv/bin/python3.12 -m pytest -q tests/test_develop_identity_rnb.py

Regenerate (ONLY after an intentional, reviewed change to rnb development)
-------------------------------------------------------------------------
    ../.venv/bin/python3.12 tests/test_develop_identity_rnb.py --write --force
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from test_develop_identity import _mismatches, _versions  # noqa: E402
from test_develop_identity_v2c import STIMS, TIERS, VISITS, compute  # noqa: E402

FIXTURE = HERE / 'fixtures' / 'develop_identity_rnb.json'
GENRE = 'rnb'
AUDITIONS = {'v2c_rnb3_s1': (3, 8), 'v2c_rnb2_s1': (2, 8)}


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def test_rnb_develop_midi_and_provenance_identical():
    fixture = _load()
    actual = compute(GENRE)
    assert set(actual) == set(fixture[GENRE])
    bad = _mismatches(fixture[GENRE], actual)
    assert not bad, (f'{len(bad)} rnb entries differ from {FIXTURE.name} (fixture versions '
                     f'{fixture["meta"]["versions"]}, now {_versions()}): ' + '; '.join(bad[:12]))


def test_accepted_auditions_in_fixture():
    fixture = _load()
    for name, (tier, visits) in AUDITIONS.items():
        assert fixture['meta']['accepted_auditions'][name] == [
            fixture[GENRE][f's1:{GENRE}:{tier}:v{v}']['sha256'] for v in range(visits)]


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

    data = compute(GENRE)
    accepted = {}
    for name, (tier, visits) in AUDITIONS.items():
        mine = [data[f's1:{GENRE}:{tier}:v{v}']['sha256'] for v in range(visits)]
        manifest = PILOT / 'renders' / 'audition_v2' / name / 'manifest.csv'
        if manifest.exists():
            with manifest.open() as f:
                rendered = [r['midi_sha256'] for r in csv.DictReader(f) if r['generator'] == 'v2b']
            if rendered != mine:
                print(f'current code does not reproduce the accepted audition {name}; not writing')
                return 1
        accepted[name] = mine
    fixture = {
        'meta': {
            'description': 'SessionComposer develop-mode MIDI sha256 freeze (rnb); '
                           'see tests/test_develop_identity_rnb.py',
            'created': _dt.datetime.now().isoformat(timespec='seconds'),
            'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--', 'composer')),
            'versions': _versions(), 'stims': list(STIMS), 'visits': VISITS, 'tiers': list(TIERS),
            'accepted_auditions': accepted,
        },
        GENRE: data,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + '\n')
    print(f'wrote {FIXTURE}: {len(data)} {GENRE}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
