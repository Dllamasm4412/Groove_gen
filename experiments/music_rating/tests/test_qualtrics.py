"""Qualtrics build (remote): headphone sounds, sound links, the generated .qsf
survey (structure, scripts, blinding) and the export importer."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

QDIR = Path(__file__).resolve().parent.parent / 'qualtrics'
if str(QDIR) not in sys.path:
    sys.path.insert(0, str(QDIR))

import build_qsf as bq  # noqa: E402
import headphone_check as hc  # noqa: E402
import import_qualtrics as iq  # noqa: E402
import prepare_qualtrics as pq  # noqa: E402

import stimuli as st  # noqa: E402

FORBIDDEN = [*st.GENRES, 'genre', 'tier', 'bpm', 'tempo', 'rung', 'ladder', 'cell', 'energy']


@pytest.fixture(scope='module')
def hp_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp('hp')
    hc.build(d)
    return d


def read_pcm(path):
    with wave.open(str(path)) as wf:
        return np.frombuffer(wf.readframes(wf.getnframes()), '<i2').reshape(-1, 2)


# ---- headphone check --------------------------------------------------------------

def test_headphone_build_is_deterministic(hp_dir, tmp_path):
    hc.build(tmp_path)
    for t in hc.load_manifest(hp_dir)['trials']:
        assert (hp_dir / t['file']).read_bytes() == (tmp_path / t['file']).read_bytes()


def test_headphone_answers_balanced_and_signal_correct(hp_dir):
    m = hc.load_manifest(hp_dir)
    assert sorted(t['answer'] for t in m['trials']) == [1, 1, 2, 2, 3, 3]
    n, g = int(hc.INTERVAL_S * hc.SR), int(hc.GAP_S * hc.SR)
    for t in m['trials']:
        x = read_pcm(hp_dir / t['file']).astype(float)
        for i, s in enumerate((0, n + g, 2 * (n + g)), 1):
            left, right = x[s:s + n, 0], x[s:s + n, 1]
            if i != t['answer']:
                assert np.array_equal(left, right)                      # diotic
                continue
            d = np.abs(np.fft.rfft(left - right)) ** 2
            f = np.fft.rfftfreq(n, 1 / hc.SR)
            band = (f >= hc.HP_F0 * (1 - hc.HP_HALF_BW) - 2) & (f <= hc.HP_F0 * (1 + hc.HP_HALF_BW) + 2)
            assert d[band].sum() / d.sum() > 0.98                       # ears differ only in the HP band
        assert np.abs(x).max() < 0.5 * 32768


# ---- sound links -----------------------------------------------------------------------

def fake_urls(snd):
    return [{'id': s['id'], 'kind': s['kind'], 'file': f"{s['id']}.wav",
             'url': f"https://example.qualtrics.com/File.php?F=F_{hashlib.sha1(s['id'].encode()).hexdigest()[:10]}"}
            for s in snd]


def test_sounds_and_loop_rows(stim_dir, hp_dir, tmp_path):
    snd = pq.sounds(stim_dir, hp_dir)
    assert len(snd) == 36 and len({s['id'] for s in snd}) == 36
    manifest, _ = st.load_manifest(stim_dir)
    rows = pq.main_rows(manifest)
    assert rows == sorted(rows) and len(rows) == 27
    assert set(rows) == {s['stimulus_id'] for s in st.by_kind(manifest, 'main')}
    assert pq.cmd_files(tmp_path / 'deploy', stim_dir, hp_dir) == 0
    assert len(list((tmp_path / 'deploy' / 'upload').glob('*.wav'))) == 36


def test_url_problems(stim_dir, hp_dir):
    snd = pq.sounds(stim_dir, hp_dir)
    rows = fake_urls(snd)
    assert pq.url_problems(rows, snd) == []
    bad = [dict(r) for r in rows]
    bad[0]['url'] = ''
    bad[1]['url'] = bad[2]['url']
    bad[3]['url'] = 'http://insecure.example/x.wav'
    bad.pop()
    out = '\n'.join(pq.url_problems(bad, snd))
    for needle in ('no url', 'same url', 'https://', 'missing from'):
        assert needle in out


def test_url_download_check(stim_dir, hp_dir):
    snd = pq.sounds(stim_dir, hp_dir)
    rows = fake_urls(snd)
    data = {r['url']: s['path'].read_bytes() for r, s in zip(rows, snd)}
    assert pq.url_problems(rows, snd, fetch=data.__getitem__) == []
    swapped = dict(data)
    swapped[rows[0]['url']], swapped[rows[1]['url']] = data[rows[1]['url']], data[rows[0]['url']]
    out = pq.url_problems(rows, snd, fetch=swapped.__getitem__)
    assert len(out) == 2 and all('differs' in x for x in out)

    def broken(url):
        raise OSError('timeout')
    assert all('download failed' in x for x in pq.url_problems(rows, snd, fetch=broken))


# ---- generated survey ---------------------------------------------------------------------

@pytest.fixture(params=[False, True], ids=['no_hp_check', 'hp_check'])
def qsf(request, stim_dir, hp_dir, tmp_path, monkeypatch):
    if not bq.TEMPLATE.exists():
        pytest.skip('no Qualtrics template export')
    snd = pq.sounds(stim_dir, hp_dir)
    rows = pq.rows_from_base(snd, 'https://example.github.io/stim')
    files = {r['url']: s['path'].read_bytes() for r, s in zip(rows, snd)}
    monkeypatch.setattr(pq, 'http_fetch', files.__getitem__)
    out = tmp_path / 'deploy'
    assert pq.cmd_qsf(out, stim_dir, hp_dir, download=True, base_url='https://example.github.io/stim/',
                      headphone_check=request.param) == 0
    return json.loads((out / pq.QSF_NAME).read_text()), out, rows, hc.load_manifest(hp_dir), request.param


def parts(survey):
    els = survey['SurveyElements']
    one = {e['Element']: e['Payload'] for e in els if e['Element'] != 'SQ'}
    qs = {e['PrimaryAttribute']: e['Payload'] for e in els if e['Element'] == 'SQ'}
    return one['BL'], one['FL'], qs


def test_qsf_structure(qsf, stim_dir):
    survey, out, _, hpm, with_hp = qsf
    blocks, flow, qs = parts(survey)
    refs = [x['QuestionID'] for b in blocks for x in b['BlockElements'] if x['Type'] == 'Question']
    assert sorted(refs) == sorted(qs) and len(refs) == len(set(refs))           # every question placed once
    tags = [q['DataExportTag'] for q in qs.values()]
    assert len(tags) == len(set(tags))
    for need in ('dance', 'calming', 'rt', 'p_dance', 'p_calming', 'attn', 'consent', 'volume', *iq.POST):
        assert need in tags
    assert all((h in tags) == with_hp for h in iq.HP_TAGS)
    assert ('headphones' in {b['Description'] for b in blocks}) == with_hp
    assert all(re.fullmatch(r'BL_[0-9A-Za-z]{15}', b['ID']) for b in blocks)
    by_name = {b['Description']: b for b in blocks}
    manifest, _ = st.load_manifest(stim_dir)
    main = by_name['main']['Options']
    assert main['Looping'] == 'Static' and main['LoopingOptions']['Randomization'] == 'All'
    assert [v['1'] for v in main['LoopingOptions']['Static'].values()] == pq.main_rows(manifest)
    prac = by_name['practice']['Options']['LoopingOptions']
    assert prac['Randomization'] == 'None' and [v['1'] for v in prac['Static'].values()] == pq.practice_rows(manifest)
    flat = []

    def walk(f):
        for x in f:
            flat.append(x)
            walk(x.get('Flow', []))
    walk(flow['Flow'])
    ids = [x['FlowID'] for x in flat]
    assert len(ids) == len(set(ids)) and flow['Properties']['Count'] == max(int(i[3:]) for i in ids)
    in_flow = {x['ID'] for x in flat if x['Type'] in ('Block', 'Standard')}
    assert in_flow == {b['ID'] for b in blocks if b['Type'] != 'Trash'}
    declared = {e['Field'] for x in flat if x['Type'] == 'EmbeddedData' for e in x['EmbeddedData']}
    assert {f'__js_t_{i}' for i in pq.main_rows(manifest) + pq.practice_rows(manifest)} <= declared
    assert {'pid', '__js_pos', '__js_vol', '__js_device'} <= declared
    assert ('hp_wrong' in declared) == with_hp
    hp_branches = [x for x in flat if x['Type'] == 'Branch' and x['Description'].endswith('wrong')]
    answers = [t['answer'] for t in hpm['trials']] if with_hp else []
    assert [b['BranchLogic']['0']['0']['ChoiceLocator'].rsplit('/', 1)[1] for b in hp_branches] == [str(a) for a in answers]
    assert any(x['Type'] == 'EndSurvey' for x in flat)                    # consent branch either way
    for q in (q for q in qs.values() if q['QuestionType'] == 'Slider'):
        c = q['Configuration']
        assert (c['CSSliderMin'], c['CSSliderMax'], c['GridLines'], c['ShowValue']) == (0, 100, 5, False)
        assert q['Validation']['Settings']['ForceResponse'] == 'ON'
    brk = next(q for q in qs.values() if q['DataExportTag'] == 'break')
    assert brk['DisplayLogic']['0']['0']['RightOperand'] == str(bq.BREAK_AFTER_MAIN)
    assert json.loads((out / 'build.json').read_text())['urls_checked_by_download'] is True


def test_qsf_scripts_are_valid_and_carry_links(qsf):
    survey, _, rows, _, with_hp = qsf
    _, _, qs = parts(survey)
    scripts = {q['DataExportTag']: q['QuestionJS'] for q in qs.values() if q.get('QuestionJS')}
    assert {'listen', 'p_listen', 'volume', 'break', 'dance', 'calming', *(iq.HP_TAGS if with_hp else [])} <= set(scripts)
    urls = json.loads(re.search(r'var URLS = (\{.*?\});', scripts['listen']).group(1))
    assert urls == {r['id']: r['url'] for r in rows}
    if shutil.which('node'):
        for tag, js in scripts.items():
            r = subprocess.run(['node', '--check', '--input-type=commonjs', '-'], input=js, capture_output=True,
                               text=True)
            assert r.returncode == 0, (tag, r.stderr[:300])
    assert '${lm://Field/1}' in scripts['listen'] and '"main"' in scripts['listen']
    assert '"practice"' in scripts['p_listen']


def test_qsf_participant_text_is_blind(qsf):
    survey, _, _, _, _ = qsf
    _, _, qs = parts(survey)
    for q in qs.values():
        visible = ' '.join([q['QuestionText'], *[c['Display'] for c in (q.get('Choices') or {}).values()],
                            *[c['Display'] for c in (q.get('Labels') or {}).values()]]).lower()
        js = (q.get('QuestionJS') or '').lower()
        for word in FORBIDDEN:
            assert not re.search(rf'\b{re.escape(word)}\b', visible), (q['DataExportTag'], word)
            assert not re.search(rf'\b{re.escape(word)}\b', js), (q['DataExportTag'], word)


def test_qsf_refuses_bad_links(stim_dir, hp_dir, tmp_path, monkeypatch):
    if not bq.TEMPLATE.exists():
        pytest.skip('no Qualtrics template export')
    snd = pq.sounds(stim_dir, hp_dir)
    rows = pq.rows_from_base(snd, 'https://example.github.io/stim')
    files = {r['url']: s['path'].read_bytes() for r, s in zip(rows, snd)}
    files[rows[5]['url']] = b'not the frozen file'
    monkeypatch.setattr(pq, 'http_fetch', files.__getitem__)
    with pytest.raises(SystemExit, match='differs'):
        pq.cmd_qsf(tmp_path / 'deploy', stim_dir, hp_dir, download=True, base_url='https://example.github.io/stim')
    with pytest.raises(SystemExit, match='https'):
        pq.rows_from_base(snd, 'http://example.org/s')


# ---- importer --------------------------------------------------------------------------

def export_csv(path, manifest, hp_manifest, people, prefix='row', with_hp=True):
    """A Qualtrics-style export: header, question-text row, ImportId row, then responses.
    prefix='row' numbers loop columns by loop-table row, 'position' by presentation order."""
    table = pq.main_rows(manifest)
    stim = {s['stimulus_id']: s for s in st.by_kind(manifest, 'main')}
    cols = ['StartDate', 'EndDate', 'Status', 'Progress', 'Duration (in seconds)', 'Finished', 'ResponseId',
            'pid', *([f'hp{i}' for i in range(1, 7)] if with_hp else []), 'attn_1', *iq.POST, '__js_vol', '__js_device', '__js_pos',
            *[f'__js_t_{s}' for s in table]]
    for k in range(1, 28):
        cols += [f'{k}_dance_1', f'{k}_calming_1', f'{k}_rt_First Click', f'{k}_rt_Page Submit']
    answers = {t['id']: t['answer'] for t in hp_manifest['trials']}
    rows = []
    for p in people:
        r = {c: '' for c in cols}
        r.update({'StartDate': '2026-10-13 10:00:00', 'Status': p.get('status', '0'), 'Progress': '100',
                  'Duration (in seconds)': '700', 'Finished': p.get('finished', '1'), 'ResponseId': p['rid'],
                  'pid': p['rid'].lower(), '__js_vol': '2', 'attn_1': str(p.get('attn', 100)),
                  '__js_device': json.dumps({'ua': p.get('ua', 'Mozilla/5.0 (Macintosh) Chrome/150')}),
                  'post_headphones': p.get('headphones', '1')})
        for i in range(1, 7 if with_hp else 1):
            h = f'hp{i}'
            r[h] = str(answers[h] if i > p.get('hp_wrong', 0) else answers[h] % 3 + 1)
        order = table[:]
        random.Random(p['rid']).shuffle(order)
        for pos, sid in enumerate(order[:p.get('n', 27)], 1):
            k = table.index(sid) + 1 if prefix == 'row' else pos
            s = stim[sid]
            if not (p.get('drop_record') and pos == 1):
                r[f'__js_t_{sid}'] = json.dumps({'v': 2, 'sid': sid, 'pos': pos, 'kind': 'main', 'plays': 1,
                                                 'pauses': [], 'stalls': 0, 'dur_s': s['duration_s'],
                                                 'played_s': s['duration_s'] - p.get('short', 0), 'complete': True,
                                                 'errors': [], 'start': 'a', 'end': 'b'})
            r[f'{k}_dance_1'] = str(pos if p.get('verify') else p.get('flat', s['rung'] * 3))
            r[f'{k}_calming_1'] = str(p.get('flat', 100 - s['rung'] * 3))
            r[f'{k}_rt_Page Submit'] = '4.2'
        rows.append(r)
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow({c: f'question text {c}' for c in cols} | {'ResponseId': 'Response ID'})
        w.writerow({c: json.dumps({'ImportId': c}) for c in cols} | {'ResponseId': '{"ImportId":"_recordId"}'})
        w.writerows(rows)


def run_import(tmp_path, stim_dir, hp_dir, people, prefix='row', mode='row', with_hp=True):
    manifest, _ = st.load_manifest(stim_dir)
    hpm = hc.load_manifest(hp_dir)
    path = tmp_path / 'export.csv'
    export_csv(path, manifest, hpm, people, prefix, with_hp)
    header, rows = iq.read_export(path)
    return iq.import_rows(rows, header, manifest, hpm, mode)


@pytest.mark.parametrize('prefix', ['row', 'position'])
def test_import_maps_ratings_to_the_played_clip(tmp_path, stim_dir, hp_dir, prefix):
    long_rows, people, problems = run_import(tmp_path, stim_dir, hp_dir, [{'rid': 'R_good'}], prefix, prefix)
    assert problems == [] and len(long_rows) == 27
    for t in long_rows:                                           # export encodes dance = rung*3
        assert t['danceability'] == t['rung'] * 3 and t['calming'] == 100 - t['rung'] * 3
        assert t['danceability_0_5'] == t['danceability'] / 20 and t['full_play']
    assert sorted(t['position'] for t in long_rows) == list(range(1, 28))
    p = people[0]
    assert p['complete_27'] and p['headphone_pass'] and p['attention_pass'] and p['suggested_include']


def test_verify_identifies_loop_numbering(tmp_path, stim_dir, hp_dir):
    manifest, _ = st.load_manifest(stim_dir)
    for prefix in ('row', 'position'):
        path = tmp_path / f'v_{prefix}.csv'
        export_csv(path, manifest, hc.load_manifest(hp_dir), [{'rid': 'R_v', 'verify': True}], prefix)
        header, rows = iq.read_export(path)
        text = iq.verify(rows, header, manifest, 'R_v')
        other = 'position' if prefix == 'row' else 'row'
        assert f'--loop-prefix {prefix}: 27/27' in text and f'--loop-prefix {other}: 27/27' not in text


def test_import_flags(tmp_path, stim_dir, hp_dir):
    people_in = [
        {'rid': 'R_hp', 'hp_wrong': 2},              # 4/6 correct
        {'rid': 'R_attn', 'attn': 40},
        {'rid': 'R_flat', 'flat': 50},
        {'rid': 'R_part', 'n': 10, 'finished': '0'},
        {'rid': 'R_short', 'short': 2.0},
        {'rid': 'R_prev', 'status': '1'},
        {'rid': 'R_phone', 'ua': 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0)'},
    ]
    _, people, problems = run_import(tmp_path, stim_dir, hp_dir, people_in)
    by = {p['response_id']: p for p in people}
    assert by['R_hp']['headphone_correct'] == 4 and not by['R_hp']['headphone_pass']
    assert not by['R_attn']['attention_pass']
    assert by['R_flat']['straightline']
    assert by['R_part']['n_rated'] == 10 and not by['R_part']['complete_27']
    assert not by['R_short']['all_full_play']
    assert by['R_prev']['complete_27'] and not by['R_prev']['suggested_include']
    assert by['R_phone']['mobile']
    assert not any(p['suggested_include'] for p in people)
    assert problems == []


def test_import_reports_missing_record(tmp_path, stim_dir, hp_dir):
    long_rows, people, problems = run_import(tmp_path, stim_dir, hp_dir, [{'rid': 'R_x', 'drop_record': True}])
    assert len(problems) == 1 and 'no play record' in problems[0]
    assert len(long_rows) == 27 and not people[0]['all_full_play']


def test_import_cli_refuses_overwrite(tmp_path, stim_dir, hp_dir):
    manifest, _ = st.load_manifest(stim_dir)
    export_csv(tmp_path / 'e.csv', manifest, hc.load_manifest(hp_dir), [{'rid': 'R_1'}])
    args = [str(tmp_path / 'e.csv'), '--out', str(tmp_path / 'o'), '--stim-dir', str(stim_dir), '--hp-dir', str(hp_dir)]
    assert iq.main(args) == 0
    assert (tmp_path / 'o' / 'ratings_long.csv').exists()
    with pytest.raises(SystemExit, match='already exists'):
        iq.main(args)


def test_player_source_has_no_condition_words():
    for f in ('gg_qualtrics.js', 'gg_qualtrics.css'):
        text = (QDIR / f).read_text().lower()
        for word in FORBIDDEN:
            assert not re.search(rf'\b{re.escape(word)}\b', text), (f, word)


def test_import_without_headphone_check_uses_self_report(tmp_path, stim_dir, hp_dir):
    people_in = [{'rid': 'R_yes'}, {'rid': 'R_no', 'headphones': '2'}, {'rid': 'R_part', 'headphones': '3'}]
    _, people, problems = run_import(tmp_path, stim_dir, hp_dir, people_in, with_hp=False)
    by = {p['response_id']: p for p in people}
    assert problems == []
    assert all(p['headphone_correct'] is None and p['headphone_pass'] is None for p in people)
    assert by['R_yes']['headphones_self_report'] and by['R_yes']['suggested_include']
    assert not by['R_no']['suggested_include'] and not by['R_part']['suggested_include']


def test_import_accepts_choice_text_export(tmp_path, stim_dir, hp_dir):
    people_in = [{'rid': 'R_txt', 'headphones': 'Yes', 'status': 'IP Address', 'finished': 'True'},
                 {'rid': 'R_prev', 'headphones': 'Yes', 'status': 'Survey Preview', 'finished': 'True'}]
    _, people, problems = run_import(tmp_path, stim_dir, hp_dir, people_in, with_hp=False)
    by = {p['response_id']: p for p in people}
    assert problems == [] and by['R_txt']['suggested_include'] and not by['R_prev']['suggested_include']


def test_analysis_end_to_end(tmp_path, stim_dir, hp_dir):
    import analyze_ratings as ar

    manifest, _ = st.load_manifest(stim_dir)
    hpm = hc.load_manifest(hp_dir)
    people = [{'rid': f'R_{i}'} for i in range(6)] + [{'rid': 'R_prev', 'status': 'Survey Preview'}]
    export_csv(tmp_path / 'a.csv', manifest, hpm, people[:4], with_hp=False)
    export_csv(tmp_path / 'b.csv', manifest, hpm, people[3:], with_hp=False)      # R_3 in both files
    out = tmp_path / 'out'
    args = [str(tmp_path), '--out', str(out), '--stim-dir', str(stim_dir), '--hp-dir', str(hp_dir)]
    assert ar.main(args) == 0
    parts = list(csv.DictReader((out / 'participants.csv').open()))
    assert len(parts) == 7                                                        # R_3 kept once
    assert {p['response_id'] for p in parts if p['included'] == 'True'} == {f'R_{i}' for i in range(6)}
    cells = list(csv.DictReader((out / 'cells.csv').open()))
    assert [int(c['rung']) for c in cells] == list(range(27)) and all(c['n'] == '6' for c in cells)
    assert all(c['danceability_ci_low'] for c in cells)                          # CIs from 5 participants
    report = (out / 'report.md').read_text()
    assert '| cell means vs rung | 1.00 | -1.00 |' in report                     # export encodes dance = rung*3
    assert '- **danceability**: none' in report and '- **calming**: none' in report
    assert (out / 'ladder_ratings.png').stat().st_size > 10_000
    with pytest.raises(SystemExit, match='not empty'):
        ar.main(args)
