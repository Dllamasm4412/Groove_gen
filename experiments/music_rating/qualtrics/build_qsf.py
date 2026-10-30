"""
Generate the complete Experiment 1 (remote) survey as a Qualtrics .qsf file.

The account-specific parts (survey entry, branding/skin, options, response
set) come from a template exported from the researcher's own account
(template/GG_template.qsf). Questions, blocks, loops and flow follow the
formats in that export; the branch and display-logic conditions follow the
standard .qsf format (they are not in the template, so check them after import).

Every question's JavaScript carries the full player (gg_qualtrics.js with the
sound links filled in), so nothing goes in the survey header.

Called by `prepare_qualtrics.py qsf`; see QUALTRICS_BUILD.md.
"""

from __future__ import annotations

import copy
import hashlib
import html
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / 'template' / 'GG_template.qsf'
SURVEY_NAME = 'GrooveGen music rating (remote)'
BREAK_AFTER_MAIN = 14
HP_MAX_WRONG = 1          # screen out at 2 or more wrong (pass = at least 5 of 6)

Q_DANCE = 'How much does this music make you want to move or dance?'
Q_CALM = 'How calming or relaxing does this music feel?'
SLOT = '<div class="gg-slot">If no Play button appears within a few seconds, please reload the page.</div>'

TEXT = {
    'consent': '<p><b>[CONSENT INFORMATION: replace this paragraph with the approved consent text.]</b></p>',
    'consent_q': 'Do you agree to take part in this study?',
    'instructions': (
        '<p><b>Instructions</b></p>'
        '<p>You will hear 29 short music clips: 2 practice clips, then 27 clips for the study. Each clip lasts '
        'about 8 to 16 seconds and plays once.</p>'
        f'<p>After each clip, please answer two questions by moving each slider:</p><ol><li>{Q_DANCE}</li>'
        f'<li>{Q_CALM}</li></ol>'
        '<p>There are no right or wrong answers; we are interested in your own impression of each clip on its own.</p>'
        '<p>Please use a laptop or desktop computer, wear headphones, stay in a quiet place, and keep the volume the '
        'same throughout. Halfway through there is a short break. You can stop at any time by closing this page.</p>'),
    'volume': (
        '<p><b>Headphones and volume</b></p><p>Please put on your headphones. Press <b>Play sample</b> and adjust '
        "your computer's volume so the music is clearly audible and comfortable. You can play the sample as often "
        'as you like.</p><p>Please do not change the volume after this step.</p>'),
    'hp_intro': (
        '<p><b>Sound check</b></p><p>In each of the next 6 questions you will hear three noise sounds, numbered 1, '
        '2 and 3. One of them contains a faint tone. Choose the number of the sound with the tone.</p>'
        '<p>This check only works with headphones.</p>'),
    'hp_q': 'Which sound contained the faint tone?',
    'screenout': (
        '<p>Thank you. Unfortunately the sound check indicates that headphones are not being used, which this '
        'study requires. The survey ends here.</p>'),
    'practice_end': '<p>Practice is over. The study clips start now.</p>',
    'break': (
        '<p><b>Short break</b></p><p>You are halfway through. Take a moment to rest if you like, then continue.</p>'
        '<p>Please keep your headphones on and leave the volume as it is.</p>'),
    'attn': 'To show that you are reading the questions, please move this slider all the way to the right.',
}
POST = [
    ('post_headphones', 'Did you use headphones or earphones for the whole survey?', ['Yes', 'No', 'Part of the time']),
    ('post_volume', 'Did you change the volume after the setup step?', ['No', 'Yes, a little', 'Yes, a lot']),
    ('post_quiet', 'Were you in a quiet place?', ['Yes', 'Mostly', 'No']),
]
POST_TEXT = ('post_problems', 'Did you have any technical problems, for example sounds that did not play? (optional)')


def _fill(src: str, marker: str, value: str) -> str:
    pat = re.compile(r'/\*' + marker + r'\*/.*?/\*END\*/', re.S)
    if len(pat.findall(src)) != 1:
        raise ValueError(f'marker {marker} not found exactly once')
    return pat.sub(lambda _: value, src)


def player_js(urls: dict[str, str], config: dict, build: str) -> str:
    js = (HERE / 'gg_qualtrics.js').read_text(encoding='utf-8')
    css = (HERE / 'gg_qualtrics.css').read_text(encoding='utf-8')
    js = _fill(js, 'BUILD', json.dumps(build))
    js = _fill(js, 'URLS', json.dumps(urls, sort_keys=True))
    js = _fill(js, 'CONFIG', json.dumps(config, sort_keys=True))
    return _fill(js, 'CSS', json.dumps(css))


def _onload(call: str) -> str:
    return ('Qualtrics.SurveyEngine.addOnload(function () {\n  ' + call + '\n});\n'
            'Qualtrics.SurveyEngine.addOnUnload(function () {\n  if (window.GG) { GG.stopAll(); }\n});\n')


def _plain(text: str) -> str:
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).split())[:100] or 'text'


class Survey:
    """Collects questions, blocks and flow in .qsf form."""

    def __init__(self, lib: str):
        self.lib = lib
        self.questions: list[dict] = []
        self.blocks: list[dict] = []
        self.flow: list[dict] = []
        self._fl = 1
        self.tags: set[str] = set()

    def fid(self) -> str:
        self._fl += 1
        return f'FL_{self._fl}'

    def _q(self, tag: str, payload: dict, js: str | None = None) -> str:
        if tag in self.tags:
            raise ValueError(f'duplicate export tag {tag}')
        self.tags.add(tag)
        qid = f'QID{len(self.questions) + 1}'
        text = payload['QuestionText']
        base = {'QuestionText': text, 'DefaultChoices': False, 'DataExportTag': tag, 'QuestionID': qid,
                'DataVisibility': {'Private': False, 'Hidden': False},
                'QuestionDescription': _plain(text), 'GradingData': [], 'Language': []}
        base.update(payload)
        base['Configuration'] = {'QuestionDescriptionOption': 'UseText', **payload.get('Configuration', {})}
        if js is not None:
            base['QuestionJS'] = self.lib + '\n' + js
        self.questions.append(base)
        return qid

    def text(self, tag: str, html_text: str, js: str | None = None) -> str:
        return self._q(tag, {'QuestionText': html_text, 'QuestionType': 'DB', 'Selector': 'TB', 'ChoiceOrder': [],
                             'Validation': {'Settings': {'Type': 'None'}}, 'NextChoiceId': 4, 'NextAnswerId': 1}, js)

    def mc(self, tag: str, text: str, choices: list[str], force: bool = True, js: str | None = None) -> str:
        keys = [str(i) for i in range(1, len(choices) + 1)]
        return self._q(tag, {
            'QuestionText': text, 'QuestionType': 'MC', 'Selector': 'SAVR', 'SubSelector': 'TX',
            'Choices': {k: {'Display': c} for k, c in zip(keys, choices)}, 'ChoiceOrder': keys,
            'Validation': {'Settings': {'ForceResponse': 'ON', 'ForceResponseType': 'ON', 'Type': 'None'} if force
                           else {'ForceResponse': 'OFF', 'Type': 'None'}},
            'NextChoiceId': len(choices) + 1, 'NextAnswerId': 1}, js)

    def slider(self, tag: str, text: str, left: str, right: str) -> str:
        return self._q(tag, {
            'QuestionText': text, 'QuestionType': 'Slider', 'Selector': 'HSLIDER',
            'Configuration': {'TextPosition': 'above', 'CSSliderMin': 0, 'CSSliderMax': 100, 'GridLines': 5,
                              'SnapToGrid': False, 'NumDecimals': '0', 'ShowValue': False, 'CustomStart': False,
                              'NotApplicable': False, 'MobileFirst': True},
            'Choices': {'1': {'Display': ''}}, 'ChoiceOrder': [1],
            'Validation': {'Settings': {'ForceResponse': 'ON', 'ForceResponseType': 'ON', 'Type': 'None'}},
            'NextChoiceId': 2, 'NextAnswerId': 3,
            'Labels': {'1': {'Display': left}, '2': {'Display': right}}, 'ChoiceDataExportTags': False},
            _onload('if (window.GG) { GG.slider(this); }'))

    def timing(self, tag: str) -> str:
        return self._q(tag, {
            'QuestionText': 'Timing', 'QuestionType': 'Timing', 'Selector': 'PageTimer',
            'Configuration': {'MinSeconds': '0', 'MaxSeconds': '0'},
            'Choices': {'1': {'Display': 'First Click'}, '2': {'Display': 'Last Click'},
                        '3': {'Display': 'Page Submit'}, '4': {'Display': 'Click Count'}},
            'NextChoiceId': 52, 'NextAnswerId': 1})

    def entry(self, tag: str, text: str) -> str:
        return self._q(tag, {'QuestionText': text, 'QuestionType': 'TE', 'Selector': 'SL',
                             'Validation': {'Settings': {'ForceResponse': 'OFF', 'Type': 'None'}},
                             'NextChoiceId': 2, 'NextAnswerId': 1, 'SearchSource': {'AllowFreeResponse': 'false'}})

    def block(self, name: str, pages: list[list[str]], loop: list[str] | None = None,
              randomize: bool = False, in_flow: bool = True) -> str:
        bid = block_id(f'{len(self.blocks)}|{name}')
        elements = []
        for i, page in enumerate(pages):
            if i:
                elements.append({'Type': 'Page Break'})
            elements += [{'Type': 'Question', 'QuestionID': q} for q in page]
        b = {'Type': 'Default' if not self.blocks else 'Standard', 'Description': name, 'ID': bid,
             'BlockElements': elements,
             'Options': {'BlockLocking': 'false', 'RandomizeQuestions': 'false', 'BlockVisibility': 'Expanded'}}
        if loop is not None:
            b['Options'].update({'Looping': 'Static', 'LoopingOptions': {
                'Static': {str(i + 1): {'1': v} for i, v in enumerate(loop)},
                'Randomization': 'All' if randomize else 'None'}})
        self.blocks.append(b)
        if in_flow:
            self.flow.append(self.flow_block(bid))
        return bid

    def flow_block(self, bid: str) -> dict:
        kind = 'Block' if bid == self.blocks[0]['ID'] else 'Standard'
        return {'Type': kind, 'ID': bid, 'FlowID': self.fid(), 'Autofill': []}


def block_id(key: str) -> str:
    """Deterministic block ID in Qualtrics' format (BL_ + 15 letters/digits)."""
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    n = int(hashlib.sha256(f'gg|{key}'.encode()).hexdigest(), 16)
    out = ''
    for _ in range(15):
        n, r = divmod(n, len(alphabet))
        out += alphabet[r]
    return 'BL_' + out


def choice_expr(qid: str, choice: str, operator: str) -> dict:
    loc = f'q://{qid}/SelectableChoice/{choice}'
    return {'LogicType': 'Question', 'QuestionID': qid, 'QuestionIsInLoop': 'no', 'ChoiceLocator': loc,
            'Operator': operator, 'QuestionIDFromLocator': qid, 'LeftOperand': loc, 'Type': 'Expression',
            'Description': f'If {qid} choice {choice} is {operator}'}


def field_expr(field: str, operator: str, value: str) -> dict:
    return {'LogicType': 'EmbeddedField', 'LeftOperand': field, 'Operator': operator, 'RightOperand': value,
            'Type': 'Expression', 'Description': f'If {field} {operator} {value}'}


def logic(expr: dict) -> dict:
    return {'0': {'0': expr, 'Type': 'If'}, 'Type': 'BooleanExpression'}


def embedded(fields: list[tuple[str, str | None]]) -> list[dict]:
    """(field, value): value None declares a field filled later (by script or URL)."""
    out = []
    for f, v in fields:
        e = {'Description': f, 'Type': 'Recipient' if v is None else 'Custom', 'Field': f, 'VariableType': 'String',
             'DataVisibility': [], 'AnalyzeText': False}
        if v is not None:
            e['Value'] = v
        out.append(e)
    return out


def build(template: dict, *, urls: dict[str, str], main_ids: list[str], practice_ids: list[str],
          volume_id: str, hp_ids: list[str], hp_answers: list[int], hp_times: list, build_id: str,
          headphone_check: bool = False) -> dict:
    """The survey. headphone_check adds the Huggins-pitch screen with screen-out
    (off by default: researcher decision 2026-10-13, headphones by instruction
    and self-report only)."""
    config = {'volume': volume_id, 'hp': hp_ids, 'hpTimes': hp_times, 'nMain': len(main_ids),
              'nPractice': len(practice_ids)}
    s = Survey(player_js(urls, config, build_id))
    sv = template['SurveyEntry']['SurveyID']

    # Flow header: recruitment ID, script data fields (and the headphone counter)
    script_fields = ['__js_pos', '__js_vol', '__js_device'] + [f'__js_t_{i}' for i in practice_ids + main_ids]
    s.flow.append({'Type': 'EmbeddedData', 'FlowID': s.fid(),
                   'EmbeddedData': embedded([('pid', None)] + [(f, None) for f in script_fields])})
    if headphone_check:
        s.flow.append({'Type': 'EmbeddedData', 'FlowID': s.fid(), 'EmbeddedData': embedded([('hp_wrong', '0')])})

    c_text = s.text('consent_text', TEXT['consent'])
    c_q = s.mc('consent', TEXT['consent_q'], ['I agree to take part', 'I do not agree'])
    s.block('consent', [[c_text, c_q]])
    s.flow.append({'Type': 'Branch', 'FlowID': s.fid(), 'Description': 'No consent',
                   'BranchLogic': logic(choice_expr(c_q, '2', 'Selected')),
                   'Flow': [{'Type': 'EndSurvey', 'FlowID': s.fid()}]})

    s.block('instructions', [[s.text('instructions', TEXT['instructions'])]])
    s.block('volume', [[s.text('volume', TEXT['volume'] + SLOT, _onload('if (window.GG) { GG.volume(this); }'))]])

    if headphone_check:
        hp_pages = [[s.text('hp_intro', TEXT['hp_intro'])]]
        hp_q = []
        for n in range(1, len(hp_ids) + 1):
            hp_q.append(s.mc(f'hp{n}', TEXT['hp_q'] + SLOT, ['1', '2', '3'],
                             js=_onload(f'if (window.GG) {{ GG.hp(this, {n}); }}')))
            hp_pages.append([hp_q[-1]])
        s.block('headphones', hp_pages)
        for qid, ans in zip(hp_q, hp_answers):
            s.flow.append({'Type': 'Branch', 'FlowID': s.fid(), 'Description': f'{qid} wrong',
                           'BranchLogic': logic(choice_expr(qid, str(ans), 'NotSelected')),
                           'Flow': [{'Type': 'EmbeddedData', 'FlowID': s.fid(),
                                     'EmbeddedData': embedded([('hp_wrong', '$e{ e://Field/hp_wrong + 1 }')])}]})
        screen = s.block('screenout', [[s.text('screenout', TEXT['screenout'])]], in_flow=False)
        s.flow.append({'Type': 'Branch', 'FlowID': s.fid(), 'Description': 'Headphone check failed',
                       'BranchLogic': logic(field_expr('hp_wrong', 'GreaterThan', str(HP_MAX_WRONG))),
                       'Flow': [s.flow_block(screen), {'Type': 'EndSurvey', 'FlowID': s.fid()}]})

    def trial_pages(prefix: str, kind: str) -> list[list[str]]:
        listen = s.text(f'{prefix}listen', SLOT, _onload(
            'if (window.GG) { GG.trial(this, "${lm://Field/1}", "${lm://CurrentLoopNumber}", "' + kind + '"); }'))
        return [[listen], [s.slider(f'{prefix}dance', Q_DANCE, 'Not at all', 'Extremely'),
                           s.slider(f'{prefix}calming', Q_CALM, 'Not at all calming', 'Extremely calming'),
                           s.timing(f'{prefix}rt')]]

    s.block('practice', trial_pages('p_', 'practice'), loop=practice_ids)
    s.block('practice_end', [[s.text('practice_end', TEXT['practice_end'])]])
    main_pages = trial_pages('', 'main')
    brk = s.text('break', TEXT['break'], _onload(
        f'if (window.GG) {{ GG.breakAt(this, "${{lm://CurrentLoopNumber}}", {BREAK_AFTER_MAIN}); }}'))
    s.questions[-1]['DisplayLogic'] = {**logic(field_expr('__js_pos', 'EqualTo', str(BREAK_AFTER_MAIN))),
                                       'inPage': False}
    s.block('main', main_pages + [[brk]], loop=main_ids, randomize=True)

    final = [[s.slider('attn', TEXT['attn'], 'Not at all', 'Extremely')]]
    final.append([s.mc(tag, text, opts) for tag, text, opts in POST] + [s.entry(*POST_TEXT)])
    s.block('final', final)

    s.blocks.append({'Type': 'Trash', 'Description': 'Trash / Unused Questions', 'ID': block_id('trash'),
                     'BlockElements': []})

    def element(kind: str, primary, payload, secondary=None, tertiary=None) -> dict:
        return {'SurveyID': sv, 'Element': kind, 'PrimaryAttribute': primary, 'SecondaryAttribute': secondary,
                'TertiaryAttribute': tertiary, 'Payload': payload}

    by_kind = {e['Element']: e for e in template['SurveyElements']}
    options = copy.deepcopy(by_kind['SO']['Payload'])
    options.update({'BackButton': 'false', 'Header': '', 'Footer': '', 'ProgressBarDisplay': 'None'})
    entry = copy.deepcopy(template['SurveyEntry'])
    entry.update({'SurveyName': SURVEY_NAME, 'SurveyStatus': 'Inactive'})
    elements = [
        element('BL', 'Survey Blocks', s.blocks),
        element('FL', 'Survey Flow', {'Type': 'Root', 'FlowID': 'FL_1', 'Flow': s.flow,
                                      'Properties': {'Count': s._fl}}),
        element('PROJ', 'CORE', by_kind['PROJ']['Payload'], tertiary=by_kind['PROJ']['TertiaryAttribute']),
        element('QC', 'Survey Question Count', None, secondary=str(len(s.questions))),
        copy.deepcopy(by_kind['RS']),
        copy.deepcopy(by_kind['SCO']),
        element('SO', 'Survey Options', options),
        *[element('SQ', q['QuestionID'], q, secondary=q['QuestionDescription']) for q in s.questions],
        element('STAT', 'Survey Statistics', by_kind['STAT']['Payload']),
    ]
    return {'SurveyEntry': entry, 'SurveyElements': elements}
