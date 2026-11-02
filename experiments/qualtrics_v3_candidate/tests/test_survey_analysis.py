"""
Draft survey, import mapping, analysis and coding: self-contained tests.

The real survey file is not in the repository (QSF files are gitignored there),
so these tests make a stand-in "existing survey" with the same builder
(experiments/music_rating/qualtrics/build_qsf.py) and a minimal template. Set
GG_ORIGINAL_QSF to the real GrooveGen_music_rating.qsf to also test that the
builder reproduces it byte for byte.
"""

from __future__ import annotations

import csv
import hashlib
import os
import random
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

import survey_v3 as sv  # noqa: E402
import import_v3_export as iv  # noqa: E402
import danceability_coding as dc  # noqa: E402

OLD_MAIN = [f's{hashlib.sha256(str(i).encode()).hexdigest()[:7]}' for i in range(27)]


def _template() -> dict:
    sid = 'SV_test'
    el = lambda kind, payload, **kw: {'SurveyID': sid, 'Element': kind, 'PrimaryAttribute': kind,  # noqa: E731
                                      'SecondaryAttribute': None, 'TertiaryAttribute': kw.get('tertiary'),
                                      'Payload': payload}
    return {'SurveyEntry': {'SurveyID': sid, 'SurveyName': 'x', 'SurveyStatus': 'Inactive'},
            'SurveyElements': [el('SO', {'BackButton': 'false', 'PartialData': '+1 week'}), el('RS', {}),
                               el('SCO', {}), el('PROJ', {}, tertiary='1.1.0'), el('STAT', {})]}


@pytest.fixture()
def original(tmp_path) -> Path:
    urls = {i: f'https://example.org/old/{i}.wav' for i in OLD_MAIN + ['pr1', 'pr2', 'vol', 'hp1']}
    q = sv.bq.build(_template(), urls=urls, main_ids=sorted(OLD_MAIN), practice_ids=['pr1', 'pr2'], volume_id='vol',
                    hp_ids=['hp1'], hp_answers=[1], hp_times=[[0, 1], [1.5, 2.5], [3, 4]], build_id='old-build')
    p = tmp_path / 'original.qsf'
    p.write_text(sv.dumps(q))
    return p


def _manifest() -> dict:
    return {'corpus_version': 'qualtrics-27-candidate-v3.1',
            'stimuli': [{'stimulus_id': f'S{k:02d}', 'mp3_file': f'A_qualtrics_mp3/S{k:02d}.mp3',
                         'mp3_sha256': hashlib.sha256(str(k).encode()).hexdigest()} for k in range(1, 28)]}


def test_builder_reproduces_its_own_output(original):
    assert sv.reproduces(original)


@pytest.mark.skipif(not os.environ.get('GG_ORIGINAL_QSF'), reason='set GG_ORIGINAL_QSF to the real survey file')
def test_builder_reproduces_the_real_existing_survey():
    assert sv.reproduces(Path(os.environ['GG_ORIGINAL_QSF']))


@pytest.mark.parametrize('practice', ['original', 'v3'])
def test_draft_passes_every_check_except_the_consent_placeholder(original, practice):
    orig, _ = sv.load(original)
    draft, params = sv.build_draft(original, _manifest(), 'https://example.org/v3/', practice,
                                   {'practice': [('P01', 'PRACTICE_1.mp3'), ('P02', 'PRACTICE_2.mp3')],
                                    'volume': ('V01', 'VOLUME.mp3')})
    checks = sv.validate(draft, params, _manifest(), orig)
    failed = [c['check'] for c in checks if not c['passed']]
    assert failed == ['consent text is the approved document (NOT a placeholder)']
    assert len(checks) >= 30


def test_draft_changes_only_what_is_documented(original):
    orig, _ = sv.load(original)
    draft, _ = sv.build_draft(original, _manifest(), 'https://example.org/v3/')
    diff = sv.diff_summary(orig, draft)
    allowed = ('question added: age18', 'question script changed', 'question text changed: instructions',
               'block contents changed: consent', 'block options changed: main', 'survey flow changed',
               'survey entry changed')
    assert diff and all(d.startswith(allowed) for d in diff), diff


@pytest.mark.parametrize('prefix', ['row', 'position'])
def test_every_rating_maps_to_the_presented_stimulus(original, tmp_path, prefix):
    _, params = sv.build_draft(original, _manifest(), 'https://example.org/v3/')
    path = tmp_path / 'export.csv'
    path.write_text(sv.simulated_export(params, n=9, prefix=prefix))
    header, rows = iv.iq.read_export(path)
    stim = {r['stimulus_id']: {'genre': 'g', 'tier': 1} for r in _manifest()['stimuli']}
    long_rows, people, problems = iv.import_rows(rows, header, stim, {}, prefix)
    assert len(people) == 9 and len(long_rows) == 9 * 27 and not problems
    assert all(int(x['stimulus_id'][1:]) == x['danceability'] and x['calming'] == 100 - x['position']
               for x in long_rows)
    assert all(not x['stimulus_id'].startswith('P') for x in long_rows)      # practice never enters the table


def test_verify_finds_the_numbering_from_a_test_response(original, tmp_path):
    _, params = sv.build_draft(original, _manifest(), 'https://example.org/v3/')
    text = sv.simulated_export(params, n=1, prefix='position')
    # a tester sets dance = the clip number shown (the position)
    lines = list(csv.reader(text.splitlines()))
    head, data = lines[0], lines[3]
    for k in range(1, 28):
        i = head.index(f'{k}_dance_1')
        data[i] = str(k)
    path = tmp_path / 'verify.csv'
    with path.open('w', newline='') as f:
        csv.writer(f).writerows(lines[:3] + [data])
    header, rows = iv.iq.read_export(path)
    stim = {r['stimulus_id']: {'genre': 'g', 'tier': 1} for r in _manifest()['stimuli']}
    out = iv.verify(rows, header, stim, rows[0]['ResponseId'])
    assert '--loop-prefix position: 27/27' in out and '--loop-prefix row: 27/27' not in out


def test_analysis_runs_and_recovers_a_simulated_tier_effect(tmp_path):
    pytest.importorskip('statsmodels')
    import analyze_v3 as av

    rng = random.Random(3)
    genres = {'pop': 5, 'rock': 5, 'hiphop': 5, 'rnb': 4, 'lofi': 3, 'latin': 3, 'calm': 2}
    stims = [(f'S{i + 1:02d}', g, t) for i, (g, t) in enumerate((g, t) for g, n in genres.items() for t in range(1, n + 1))]
    long_rows, people = [], []
    for p in range(16):
        base = rng.gauss(0, 8)
        people.append({'participant': f'P{p:03d}', 'suggested_include': p != 0})
        for sid, g, t in stims:
            d = 30 + 6 * t + base + rng.gauss(0, 10)
            c = 70 - 4 * t + rng.gauss(0, 10)
            long_rows.append({'participant': f'P{p:03d}', 'stimulus_id': sid, 'condition_id': f'{g}:{t}', 'genre': g,
                              'tier': t, 'intended_danceability': t, 'danceability': d, 'calming': c,
                              'lufs_integrated': -25 + t + {'pop': 0.4, 'rock': -0.6}.get(g, 0) * (t % 2), 'tempo_bpm': 100, 'drum_onsets_per_s': t,
                              'notes_per_s': 2 * t, 'bass_notes_per_bar': t, 'offbeat_index': 0.1 * t,
                              'centroid_hz': 2000 + 100 * t, 'flux': 1, 'pulse_clarity': 0.8,
                              'energy_u_delivered': 0.2 * t})
    iv.write_csv(tmp_path / 'ratings_long.csv', long_rows)
    iv.write_csv(tmp_path / 'participants.csv', people)
    res = av.run(tmp_path)
    est = res['primary']['primary']['estimate']
    assert 4 < est < 8 and res['primary']['primary']['ci95'][0] > 0
    assert 'S1_crossed_participant_stimulus' in res['primary'] and 'S2_plus_loudness' in res['primary']
    assert res['secondary']['within_participant_spearman']['median'] < 0
    assert all(v['converged'] for v in res['primary'].values() if isinstance(v, dict) and 'converged' in v)
    assert (tmp_path / 'analysis_report.md').exists()


def test_step_classes_separate_groove_tempo_and_loudness():
    base = {'drum_notes_per_bar': 12, 'drum_onsets_per_s': 4.0, 'bass_notes_per_bar': 4, 'parts': 3,
            'notes_per_s': 8.0, 'lufs_integrated': -20, 'offbeat_index': 0.3, 'tempo_bpm': 120,
            'energy_u_delivered': 0.5}
    louder = {**base, 'lufs_integrated': -17}
    faster = {**base, 'tempo_bpm': 130, 'drum_onsets_per_s': 4.0 * 130 / 120, 'notes_per_s': 8.0 * 130 / 120}
    denser = {**base, 'drum_notes_per_bar': 16, 'drum_onsets_per_s': 5.0}
    assert dc.step_class(base, louder)[0] == 'mainly loudness'
    assert dc.step_class(base, faster)[0] == 'tempo mainly'
    assert dc.step_class(base, denser)[0] == 'groove-related change, loudness about equal'
