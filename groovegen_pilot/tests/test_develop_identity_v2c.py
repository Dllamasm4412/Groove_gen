"""
SessionComposer develop-mode MIDI identity freeze for the accepted v2c policies
(calm v2c.calm.0, lofi v2c.lofi.0; developer listening approved 2026-10-01).

Pins SessionComposer(stim, develop=True) on calm and lofi, tiers 1-5 x stim
seeds STIMS x visits 0..VISITS-1: sha256 plus the development provenance
fields, so later genre policies (rnb, ...) or engine changes cannot change the
approved output silently. The approved auditions (renders/audition_v2/
v2c_calm2_s1, v2c_lofi3_s1, v2c_lofi2_s1) are part of the frozen set.
hiphop v2b.1 and the v2a.3 default are pinned by tests/test_develop_identity.py.

Run
---
    cd groovegen_pilot
    ../.venv/bin/python3.12 -m pytest -q tests/test_develop_identity_v2c.py

Regenerate (ONLY after an intentional, reviewed change to calm or lofi development)
-----------------------------------------------------------------------------------
    ../.venv/bin/python3.12 tests/test_develop_identity_v2c.py --write --force
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

from test_develop_identity import MOTIF_FIELDS, _mismatches, _versions  # noqa: E402

FIXTURE = HERE / 'fixtures' / 'develop_identity_v2c.json'
GENRES = ('calm', 'lofi')
STIMS = (1, 2, 19)
VISITS = 12
TIERS = (1, 2, 3, 4, 5)
FIELDS = MOTIF_FIELDS + ('drum_repeat_window',)
AUDITIONS = {'v2c_calm2_s1': ('calm', 2, 12), 'v2c_lofi3_s1': ('lofi', 3, 8), 'v2c_lofi2_s1': ('lofi', 2, 8)}


def compute(genre: str, stims=STIMS, tiers=TIERS, visits=VISITS) -> dict[str, dict]:
    import stimulus_metrics as sm
    from composer.arrangement import SessionComposer

    out = {}
    for stim in stims:
        comp = SessionComposer(stim, develop=True)
        for tier in tiers:
            for v in range(visits):
                pm, info = comp.compose(genre, tier, v)
                out[f's{stim}:{genre}:{tier}:v{v}'] = {'sha256': sm.midi_sha256(pm),
                                                      **{f: info.get(f) for f in FIELDS}}
    return out


def _load() -> dict:
    return json.loads(FIXTURE.read_text())


def _check(genre: str) -> None:
    fixture = _load()
    actual = compute(genre)
    assert set(actual) == set(fixture[genre])
    bad = _mismatches(fixture[genre], actual)
    assert not bad, (f'{len(bad)} {genre} entries differ from {FIXTURE.name} (fixture versions '
                     f'{fixture["meta"]["versions"]}, now {_versions()}): ' + '; '.join(bad[:12]))


def test_calm_v2c_develop_midi_and_provenance_identical():
    _check('calm')


def test_lofi_v2c_develop_midi_and_provenance_identical():
    _check('lofi')


def test_accepted_auditions_in_fixture():
    fixture = _load()
    for name, (genre, tier, visits) in AUDITIONS.items():
        assert fixture['meta']['accepted_auditions'][name] == [
            fixture[genre][f's1:{genre}:{tier}:v{v}']['sha256'] for v in range(visits)]


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

    data = {g: compute(g) for g in GENRES}
    accepted = {}
    for name, (genre, tier, visits) in AUDITIONS.items():
        mine = [data[genre][f's1:{genre}:{tier}:v{v}']['sha256'] for v in range(visits)]
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
            'description': 'SessionComposer develop-mode MIDI sha256 freeze (calm, lofi); '
                           'see tests/test_develop_identity_v2c.py',
            'created': _dt.datetime.now().isoformat(timespec='seconds'),
            'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--', 'composer')),
            'versions': _versions(), 'stims': list(STIMS), 'visits': VISITS, 'tiers': list(TIERS),
            'accepted_auditions': accepted,
        },
        **data,
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + '\n')
    print(f'wrote {FIXTURE}: ' + ', '.join(f'{len(data[g])} {g}' for g in GENRES))
    return 0


if __name__ == '__main__':
    sys.exit(main())
