"""
Draft Qualtrics survey for the v3 candidate stimuli, made from the EXISTING
survey (GrooveGen_music_rating.qsf), never replacing it.

The existing .qsf is exactly what experiments/music_rating/qualtrics/build_qsf.py
generated (its sha256 is the one recorded in deploy/build.json). This module
first proves that: it reads the build parameters out of the existing file
(sound links, player config, build ID, loop rows) and rebuilds it with the same
builder, requiring a byte-identical result. It then builds the draft with the
same builder and the v3 stimulus parameters, and applies a short list of
documented edits (EDITS). Nothing else in the survey changes: wording of both
rating questions, sliders, loops, randomisation, player script, break, final
questions, options and branding are the builder's.

The draft is never uploaded anywhere; importing it into Qualtrics, hosting the
sound files and the live tests are the researcher's steps (survey_test_plan.md).

Usage (repository root):
    python experiments/qualtrics_v3_candidate/survey_v3.py build --original GrooveGen_music_rating.qsf \\
        --package <candidate package dir> [--base-url URL] [--out DIR]
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
QDIR = REPO / 'experiments' / 'music_rating' / 'qualtrics'
for p in (QDIR, QDIR.parent, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import build_qsf as bq  # noqa: E402  (read-only use of the original builder)

DEFAULT_BASE_URL = 'https://dllamasm4412.github.io/audio_files/groovegen_v3.1/'
DRAFT_NAME = 'GrooveGen music rating (remote) - v3 candidate DRAFT'
N_MAIN = 27
OLD_DURATION = 'about 8 to 16 seconds'
NEW_DURATION = 'about 15 to 30 seconds'
AGE_TAG = 'age18'
AGE_TEXT = 'Are you 18 years of age or older?'
AGE_CHOICES = ['Yes, I am 18 or older', 'No, I am under 18']

EDITS = [
    ('E1', 'Instructions: clip duration "about 8 to 16 seconds" -> "about 15 to 30 seconds"',
     'The submitted protocol describes eight-bar excerpts of about 15-30 s; the v3 excerpts are 15.2-30.5 s.',
     'participant-facing'),
    ('E2', f'Consent page: an age question "{AGE_TEXT}" ({AGE_CHOICES[0]} / {AGE_CHOICES[1]}), forced response; '
           '"under 18" ends the survey',
     'The protocol: "The first survey screen will present the approved remote consent text and ask participants '
     'to confirm that they are at least 18. Those who decline or are under 18 will exit." The existing survey asks '
     'only for agreement. The wording is a draft: use the approved consent document\'s wording if it has one.',
     'participant-facing'),
    ('E3', 'Embedded data: "pid" removed; "stim_set" and "survey_version" added (fixed values)',
     'The protocol collects no identifiers or linkage codes; a pid filled from a link parameter could become one. '
     'stim_set records in every response which stimulus set was presented.', 'data only'),
    ('E4', f'Survey name: "{DRAFT_NAME}"', 'So the draft cannot be confused with the existing survey.', 'internal'),
    ('E5', 'Stimulus mapping: main loop rows S01-S27 (row k = S<k>), sound links to the v3 MP3s, player '
           'records __js_t_S01 ... __js_t_S27, new build ID',
     'The v3 candidate set; row k of the loop table is stimulus S<k>, so export columns k_dance_1 / k_calming_1 '
     'name the stimulus directly.', 'stimuli'),
]


# =============================================================================
# Reading the existing survey
# =============================================================================


def load(path: Path) -> tuple[dict, str]:
    raw = Path(path).read_text(encoding='utf-8')
    return json.loads(raw), raw


def player_params(q: dict) -> dict:
    """BUILD, URLS and CONFIG as filled into the player script, and the loop rows."""
    js = next(e['Payload']['QuestionJS'] for e in q['SurveyElements']
              if e['Element'] == 'SQ' and 'GG.volume' in (e['Payload'].get('QuestionJS') or ''))

    def get(name):
        return json.loads(re.search(r'var ' + name + r' = (.*?);\n', js).group(1))
    blocks = next(e for e in q['SurveyElements'] if e['Element'] == 'BL')['Payload']
    loops = {b['Description']: [v['1'] for _, v in sorted(b['Options']['LoopingOptions']['Static'].items(),
                                                          key=lambda kv: int(kv[0]))]
             for b in blocks if b.get('Options', {}).get('LoopingOptions')}
    return {'build': get('BUILD'), 'urls': get('URLS'), 'config': get('CONFIG'), 'main': loops['main'],
            'practice': loops['practice']}


def rebuild(template: dict, urls: dict, main_ids: list, practice_ids: list, volume_id: str, config: dict,
            build_id: str) -> dict:
    return bq.build(template, urls=urls, main_ids=main_ids, practice_ids=practice_ids, volume_id=volume_id,
                    hp_ids=config['hp'], hp_answers=[1] * len(config['hp']), hp_times=config['hpTimes'],
                    build_id=build_id)


def dumps(survey: dict) -> str:
    return json.dumps(survey, indent=1) + '\n'      # the format prepare_qualtrics.py writes


def reproduces(original_path: Path) -> bool:
    q, raw = load(original_path)
    p = player_params(q)
    return dumps(rebuild(q, p['urls'], p['main'], p['practice'], p['config']['volume'], p['config'],
                         p['build'])) == raw


# =============================================================================
# The draft
# =============================================================================


def _sq(q: dict, qid: str) -> dict:
    return next(e for e in q['SurveyElements'] if e['Element'] == 'SQ' and e['Payload']['QuestionID'] == qid)


def _by_tag(q: dict, tag: str) -> dict:
    return next(e['Payload'] for e in q['SurveyElements']
                if e['Element'] == 'SQ' and e['Payload'].get('DataExportTag') == tag)


def apply_edits(q: dict, stim_set: str, survey_version: str) -> dict:
    q = copy.deepcopy(q)
    els = q['SurveyElements']
    sv = q['SurveyEntry']['SurveyID']
    # E1 instructions duration
    ins = _by_tag(q, 'instructions')
    if OLD_DURATION not in ins['QuestionText']:
        raise ValueError('instructions text changed; E1 needs review')
    ins['QuestionText'] = ins['QuestionText'].replace(OLD_DURATION, NEW_DURATION)
    ins['QuestionDescription'] = bq._plain(ins['QuestionText'])
    _sq(q, ins['QuestionID'])['SecondaryAttribute'] = ins['QuestionDescription']
    # E2 age confirmation on the consent page, with its own exit
    consent = _by_tag(q, 'consent')
    n_q = sum(e['Element'] == 'SQ' for e in els)
    qid = f'QID{n_q + 1}'
    age = copy.deepcopy(consent)
    age.update({'QuestionText': AGE_TEXT, 'DataExportTag': AGE_TAG, 'QuestionID': qid,
                'QuestionDescription': bq._plain(AGE_TEXT),
                'Choices': {str(i + 1): {'Display': c} for i, c in enumerate(AGE_CHOICES)},
                'ChoiceOrder': [str(i + 1) for i in range(len(AGE_CHOICES))], 'NextChoiceId': len(AGE_CHOICES) + 1})
    last_sq = max(i for i, e in enumerate(els) if e['Element'] == 'SQ')
    els.insert(last_sq + 1, {'SurveyID': sv, 'Element': 'SQ', 'PrimaryAttribute': qid,
                             'SecondaryAttribute': age['QuestionDescription'], 'TertiaryAttribute': None,
                             'Payload': age})
    next(e for e in els if e['Element'] == 'QC')['SecondaryAttribute'] = str(n_q + 1)
    blocks = next(e for e in els if e['Element'] == 'BL')['Payload']
    cblock = next(b for b in blocks if any(x.get('QuestionID') == consent['QuestionID']
                                           for x in b['BlockElements']))
    i = next(k for k, x in enumerate(cblock['BlockElements']) if x.get('QuestionID') == consent['QuestionID'])
    cblock['BlockElements'].insert(i + 1, {'Type': 'Question', 'QuestionID': qid})
    flow = next(e for e in els if e['Element'] == 'FL')['Payload']
    count = flow['Properties']['Count']
    b_at = next(k for k, f in enumerate(flow['Flow']) if f['Type'] == 'Branch'
                and consent['QuestionID'] in json.dumps(f['BranchLogic']))
    flow['Flow'].insert(b_at + 1, {'Type': 'Branch', 'FlowID': f'FL_{count + 1}', 'Description': 'Under 18',
                                   'BranchLogic': bq.logic(bq.choice_expr(qid, '2', 'Selected')),
                                   'Flow': [{'Type': 'EndSurvey', 'FlowID': f'FL_{count + 2}'}]})
    flow['Properties']['Count'] = count + 2
    # E3 embedded data
    ed = next(f for f in flow['Flow'] if f['Type'] == 'EmbeddedData')
    ed['EmbeddedData'] = [x for x in ed['EmbeddedData'] if x['Field'] != 'pid']
    ed['EmbeddedData'] += bq.embedded([('stim_set', stim_set), ('survey_version', survey_version)])
    # E4 name
    q['SurveyEntry']['SurveyName'] = DRAFT_NAME
    return q


def build_draft(original_path: Path, manifest: dict, base_url: str, practice: str = 'original',
                v3_practice: dict | None = None) -> tuple[dict, dict]:
    """(draft survey, parameters). practice='original' keeps the existing practice
    and volume clips and their links; 'v3' uses the candidate practice / volume
    clips (needs v3_practice = {'practice': [(id, file)], 'volume': (id, file)})."""
    q, _ = load(original_path)
    p = player_params(q)
    stim = sorted(manifest['stimuli'], key=lambda r: r['stimulus_id'])
    main_ids = [r['stimulus_id'] for r in stim]
    if main_ids != [f'S{k:02d}' for k in range(1, N_MAIN + 1)]:
        raise ValueError('the package does not hold S01-S27')
    urls = {k: v for k, v in p['urls'].items() if k.startswith('hp')}       # headphone sounds (check off) kept as-is
    urls.update({r['stimulus_id']: base_url + Path(r['mp3_file']).name for r in stim})
    if practice == 'original':
        practice_ids, volume_id = p['practice'], p['config']['volume']
        for k in practice_ids + [volume_id]:
            urls[k] = p['urls'][k]
    else:
        practice_ids = [i for i, _ in v3_practice['practice']]
        volume_id = v3_practice['volume'][0]
        for i, f in v3_practice['practice'] + [v3_practice['volume']]:
            urls[i] = base_url + f
    sha12 = hashlib.sha256(json.dumps([[r['stimulus_id'], r['mp3_sha256']] for r in stim]).encode()).hexdigest()[:12]
    build = f"music-rating-remote-v3draft-1.0+stim.{sha12}+practice.{practice}"
    survey = rebuild(q, urls, main_ids, practice_ids, volume_id, p['config'], build)
    survey = apply_edits(survey, f"{manifest['corpus_version']}|{sha12}", build)
    return survey, {'build': build, 'urls': urls, 'main': main_ids, 'practice': practice_ids, 'volume': volume_id,
                    'config': {**p['config'], 'volume': volume_id, 'nPractice': len(practice_ids)}, 'sha12': sha12,
                    'practice_mode': practice}


# =============================================================================
# Validation
# =============================================================================


def _payloads(q: dict) -> dict[str, dict]:
    return {e['Payload']['QuestionID']: e['Payload'] for e in q['SurveyElements'] if e['Element'] == 'SQ'}


def validate(q: dict, params: dict, manifest: dict, original: dict) -> list[dict]:
    """Automated structural checks of a draft. Each item: check, passed, detail."""
    out = []

    def check(name, ok, detail=''):
        out.append({'check': name, 'passed': bool(ok), 'detail': detail})
    els = q['SurveyElements']
    kinds = [e['Element'] for e in els]
    qs = _payloads(q)
    tags = [p.get('DataExportTag') for p in qs.values()]
    check('required elements present (BL, FL, SO, QC, SQ)', all(k in kinds for k in ('BL', 'FL', 'SO', 'QC', 'SQ')))
    check('question count element matches questions',
          next(e for e in els if e['Element'] == 'QC')['SecondaryAttribute'] == str(len(qs)), f'{len(qs)} questions')
    check('question IDs and export tags unique', len(set(qs)) == len(qs) and len(set(tags)) == len(tags))
    blocks = next(e for e in els if e['Element'] == 'BL')['Payload']
    used = [x['QuestionID'] for b in blocks for x in b['BlockElements'] if x.get('Type') == 'Question']
    check('every block question exists and every question is in a block', set(used) == set(qs) and
          len(used) == len(set(used)))
    flow = next(e for e in els if e['Element'] == 'FL')['Payload']
    fl_ids, fl_blocks = [], []

    def walk(f):
        for x in f.get('Flow', []):
            fl_ids.append(x['FlowID'])
            if x['Type'] in ('Block', 'Standard'):
                fl_blocks.append(x['ID'])
            walk(x)
    walk(flow)
    bids = {b['ID'] for b in blocks if b['Type'] != 'Trash'}
    check('flow IDs unique and flow count covers them', len(fl_ids) == len(set(fl_ids)) and
          max(int(i.split('_')[1]) for i in fl_ids) <= flow['Properties']['Count'])
    check('every non-trash block is in the flow exactly once', sorted(fl_blocks) == sorted(bids))
    by_desc = {b['Description']: b for b in blocks}
    order = [next(b['Description'] for b in blocks if b['ID'] == i) for i in fl_blocks]
    check('block order: consent, instructions, volume, practice, practice_end, main, final',
          order == ['consent', 'instructions', 'volume', 'practice', 'practice_end', 'main', 'final'], str(order))
    tag_of = {p['QuestionID']: p.get('DataExportTag') for p in qs.values()}
    first = [tag_of[x['QuestionID']] for x in by_desc['consent']['BlockElements'] if x.get('Type') == 'Question']
    check('first page: consent text, consent question, age question', first == ['consent_text', 'consent', AGE_TAG],
          str(first))
    branches = [x for x in flow['Flow'] if x['Type'] == 'Branch']
    qid_of = {v: k for k, v in tag_of.items()}

    def ends_on(qtag, choice):
        return any(qid_of[qtag] in json.dumps(b['BranchLogic']) and f'SelectableChoice/{choice}' in
                   json.dumps(b['BranchLogic']) and b['Flow'][0]['Type'] == 'EndSurvey' for b in branches)
    check('"I do not agree" ends the survey', ends_on('consent', 2))
    check('"under 18" ends the survey', ends_on(AGE_TAG, 2))
    check('both exits come before the instructions', all(flow['Flow'].index(b) < flow['Flow'].index(
        next(x for x in flow['Flow'] if x.get('ID') == by_desc['instructions']['ID'])) for b in branches))
    consent_text = qs[qid_of['consent_text']]['QuestionText']
    check('consent text is the approved document (NOT a placeholder)', 'replace this paragraph' not in consent_text,
          'placeholder still in place: insert the approved consent text before use')
    ins = qs[qid_of['instructions']]['QuestionText']
    check('instructions give the protocol duration (about 15 to 30 seconds)', NEW_DURATION in ins and
          OLD_DURATION not in ins)
    main = by_desc['main']['Options']['LoopingOptions']
    rows = [v['1'] for _, v in sorted(main['Static'].items(), key=lambda kv: int(kv[0]))]
    check('main loop: 27 rows, S01-S27, each exactly once, row k = S<k>',
          rows == [f'S{k:02d}' for k in range(1, N_MAIN + 1)])
    check('main loop order randomised', main.get('Randomization') == 'All')
    prac = by_desc['practice']['Options']['LoopingOptions']
    prows = [v['1'] for _, v in sorted(prac['Static'].items(), key=lambda kv: int(kv[0]))]
    check('practice loop: 2 rows, fixed order, not among the 27', len(prows) == 2 and prac.get('Randomization') ==
          'None' and not set(prows) & set(rows), str(prows))
    for pfx, blk in (('', 'main'), ('p_', 'practice')):
        bq_ids = [x['QuestionID'] for x in by_desc[blk]['BlockElements'] if x.get('Type') == 'Question']
        btags = [tag_of[i] for i in bq_ids]
        need = [f'{pfx}listen', f'{pfx}dance', f'{pfx}calming', f'{pfx}rt']
        check(f'{blk}: listening page then both sliders and the timer', btags[:4] == need, str(btags))
        lj = qs[qid_of[f'{pfx}listen']].get('QuestionJS', '')
        kind = 'main' if blk == 'main' else 'practice'
        check(f'{blk}: player reads the loop field and the loop number',
              f'GG.trial(this, "${{lm://Field/1}}", "${{lm://CurrentLoopNumber}}", "{kind}")' in lj)
        for tag, text, lo, hi in ((f'{pfx}dance', bq.Q_DANCE, 'Not at all', 'Extremely'),
                                  (f'{pfx}calming', bq.Q_CALM, 'Not at all calming', 'Extremely calming')):
            s = qs[qid_of[tag]]
            c = s.get('Configuration', {})
            check(f'{tag}: exact wording, 0-100, end labels "{lo}" / "{hi}", forced response',
                  s['QuestionText'] == text and c.get('CSSliderMin') == 0 and c.get('CSSliderMax') == 100 and
                  s['Labels']['1']['Display'] == lo and s['Labels']['2']['Display'] == hi and
                  s['Validation']['Settings'].get('ForceResponse') == 'ON')
    urls = params['urls']
    ids = rows + prows + [params['volume']]
    check('every presented sound has a link', all(i in urls for i in ids))
    by_sid = {r['stimulus_id']: r for r in manifest['stimuli']}
    check('main links point at S<k>.mp3 of this package', all(urls[s].endswith('/' + Path(by_sid[s]['mp3_file']).name)
                                                              for s in rows))
    check('links are https', all(urls[i].startswith('https://') for i in ids))
    js_all = {p.get('QuestionJS') for p in qs.values() if p.get('QuestionJS')}
    libs = {j.split('\nQualtrics.SurveyEngine.addOnload')[0] for j in js_all}
    check('one player script, identical in every question', len(libs) == 1)
    expected = bq.player_js(urls, params['config'], params['build'])
    check('player script is the repository source with only links, config and build filled in',
          libs == {expected})
    ed = [x['Field'] for f in flow['Flow'] if f['Type'] == 'EmbeddedData' for x in f['EmbeddedData']]
    check('play records declared for every presented clip', all(f'__js_t_{i}' in ed for i in rows + prows))
    check('position, volume and device fields declared', all(f in ed for f in ('__js_pos', '__js_vol', '__js_device')))
    check('no "pid" field; stim_set and survey_version present', 'pid' not in ed and 'stim_set' in ed and
          'survey_version' in ed)
    brk = qs[qid_of['break']]
    check('break page shown after clip 14 only', json.dumps(brk.get('DisplayLogic', {})).count('"14"') == 1)
    old = {v['1'] for b in next(e for e in original['SurveyElements'] if e['Element'] == 'BL')['Payload']
           if b.get('Description') == 'main' for v in b['Options']['LoopingOptions']['Static'].values()}
    text = json.dumps(q)
    check('no original main-stimulus ID left anywhere in the draft', not any(o in text for o in old),
          f'{len(old)} original IDs searched')
    node = shutil.which('node')
    if node:
        bad = []
        for j in js_all:
            r = subprocess.run([node, '--check', '-'], input=j, capture_output=True, text=True)
            if r.returncode:
                bad.append(r.stderr[:200])
        check('every question script parses (node --check)', not bad, '; '.join(bad))
    so = next(e for e in els if e['Element'] == 'SO')['Payload']
    check('back button off (a clip cannot be re-rated after leaving it)', so.get('BackButton') == 'false')
    return out


# =============================================================================
# Simulated export (tests the import mapping; it is not a Qualtrics test)
# =============================================================================


def simulated_export(params: dict, n: int = 12, seed: int = 7, prefix: str = 'row') -> str:
    """A CSV in the shape of a Qualtrics export of the draft: three header rows,
    loop columns <k>_dance_1 / <k>_calming_1 / <k>_rt_Page Submit numbered by
    loop row (or by position), practice columns, play records __js_t_<id>.
    Each simulated participant sets dance = the stimulus number and calming =
    100 - position, so a correct import can be checked exactly."""
    rng = random.Random(seed)
    main, prac = params['main'], params['practice']
    cols = ['StartDate', 'EndDate', 'Status', 'Progress', 'Duration (in seconds)', 'Finished', 'RecordedDate',
            'ResponseId', 'consent', AGE_TAG]
    for k in range(1, len(prac) + 1):
        cols += [f'{k}_p_dance_1', f'{k}_p_calming_1', f'{k}_p_rt_Page Submit']
    for k in range(1, len(main) + 1):
        cols += [f'{k}_dance_1', f'{k}_calming_1', f'{k}_rt_First Click', f'{k}_rt_Page Submit']
    cols += ['attn_1', 'post_headphones', 'post_volume', 'post_quiet', 'post_problems', '__js_pos', '__js_vol',
             '__js_device'] + [f'__js_t_{i}' for i in prac + main] + ['stim_set', 'survey_version']
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    w.writerow(['Response ID' if c == 'ResponseId' else c for c in cols])      # question-text row
    w.writerow(['{"ImportId":"%s"}' % c for c in cols])
    for p in range(n):
        order = list(main)
        rng.shuffle(order)
        pos = {sid: i + 1 for i, sid in enumerate(order)}
        row = {'Status': '0', 'Progress': '100', 'Finished': '1', 'ResponseId': f'R_sim{p:03d}', 'consent': '1',
               AGE_TAG: '1', 'attn_1': '100', 'post_headphones': '1', 'post_volume': '1', 'post_quiet': '1',
               '__js_pos': '27', '__js_vol': '2', '__js_device': json.dumps({'ua': 'Mozilla/5.0 (Macintosh)'}),
               'stim_set': 'sim', 'survey_version': params['build']}
        for i, sid in enumerate(prac):
            row[f'__js_t_{sid}'] = json.dumps({'sid': sid, 'pos': i + 1, 'kind': 'practice', 'plays': 1,
                                               'complete': True, 'dur_s': 20.0, 'played_s': 20.0, 'errors': []})
            row[f'{i + 1}_p_dance_1'], row[f'{i + 1}_p_calming_1'] = '50', '50'
        for sid in main:
            k = main.index(sid) + 1 if prefix == 'row' else pos[sid]
            row[f'{k}_dance_1'] = str(int(sid[1:]))
            row[f'{k}_calming_1'] = str(100 - pos[sid])
            row[f'{k}_rt_Page Submit'] = '6.5'
            row[f'__js_t_{sid}'] = json.dumps({'sid': sid, 'pos': pos[sid], 'kind': 'main', 'plays': 1,
                                               'complete': True, 'dur_s': 20.0, 'played_s': 20.0, 'errors': []})
        w.writerow([row.get(c, '') for c in cols])
    return buf.getvalue()


def diff_summary(original: dict, draft: dict) -> list[str]:
    """What differs between the existing survey and the draft, by element."""
    out = []
    oq, dq = _payloads(original), _payloads(draft)
    otag = {p['DataExportTag']: p for p in oq.values()}
    dtag = {p['DataExportTag']: p for p in dq.values()}
    for t in sorted(set(dtag) - set(otag)):
        out.append(f'question added: {t} ({dtag[t]["QuestionID"]})')
    for t in sorted(set(otag) - set(dtag)):
        out.append(f'question removed: {t}')
    for t in sorted(set(otag) & set(dtag)):
        a, b = otag[t], dtag[t]
        if a['QuestionText'] != b['QuestionText']:
            out.append(f'question text changed: {t}')
        ja, jb = a.get('QuestionJS', ''), b.get('QuestionJS', '')
        if ja != jb:
            out.append(f'question script changed: {t} (player links / config / build only)')
        for k in sorted(set(a) | set(b)):
            if k not in ('QuestionText', 'QuestionJS', 'QuestionDescription') and a.get(k) != b.get(k):
                out.append(f'question setting changed: {t}.{k}')
    ob = {b['Description']: b for b in next(e for e in original['SurveyElements'] if e['Element'] == 'BL')['Payload']}
    db = {b['Description']: b for b in next(e for e in draft['SurveyElements'] if e['Element'] == 'BL')['Payload']}
    for name in sorted(set(ob) | set(db)):
        a, b = ob.get(name), db.get(name)
        if a is None or b is None:
            out.append(f'block {"added" if a is None else "removed"}: {name}')
            continue
        if a['BlockElements'] != b['BlockElements']:
            out.append(f'block contents changed: {name}')
        if a.get('Options') != b.get('Options'):
            out.append(f'block options changed: {name} (loop rows)')
    fo = next(e for e in original['SurveyElements'] if e['Element'] == 'FL')['Payload']
    fd = next(e for e in draft['SurveyElements'] if e['Element'] == 'FL')['Payload']
    if fo != fd:
        out.append('survey flow changed: embedded-data fields and the under-18 branch')
    for kind in ('SO', 'RS', 'SCO', 'PROJ', 'STAT'):
        a = next((e for e in original['SurveyElements'] if e['Element'] == kind), None)
        b = next((e for e in draft['SurveyElements'] if e['Element'] == kind), None)
        if a != b:
            out.append(f'{kind} changed')
    if original['SurveyEntry'] != draft['SurveyEntry']:
        out.append('survey entry changed: name')
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--original', required=True, type=Path)
    b.add_argument('--package', required=True, type=Path)
    b.add_argument('--base-url', default=DEFAULT_BASE_URL)
    b.add_argument('--out', type=Path, default=None)
    a = ap.parse_args(argv)
    from finalize_candidate import write_survey_drafts
    write_survey_drafts(a.original, a.package, a.out or a.package / 'H_qualtrics_draft', a.base_url)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
