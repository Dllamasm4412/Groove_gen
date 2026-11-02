"""
Calm development policy v2c.calm.0 (composer/dev_calm.py): determinism, legal
chord tones, pitch-only changes, register limits, long-history anti-repeat,
the 12-visit drum window and fallback provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path
from statistics import mean

import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import dev_calm as dc  # noqa: E402
from composer.arrangement import SessionComposer  # noqa: E402

VISITS = 12
CASES = [(1, 2), (2, 1), (19, 2)]        # (stim seed, tier)


def _run(stim: int, tier: int, monkeypatch) -> list[dict]:
    """Each visit's source segment, context, developed segment, record and info."""
    seen = []
    orig = dc.develop

    def spy(src, ctx, records, visit, seed):
        out = orig(src, ctx, records, visit, seed)
        seen.append({'src': src, 'ctx': ctx, 'out': out[0], 'rec': out[1]})
        return out
    monkeypatch.setattr(dc, 'develop', spy)
    comp = SessionComposer(stim, develop=True)
    for v in range(VISITS):
        _, info = comp.compose('calm', tier, v)
        assert 'motif_error' not in info, info.get('motif_error')
        seen[v]['info'] = info
    return seen


def _piano(pm, c):
    notes = pm.instruments[c.piano].notes
    return [notes[j] for j in c.order]


@pytest.fixture(scope='module')
def runs():
    out = {}
    for case in CASES:
        mp = pytest.MonkeyPatch()
        try:
            out[case] = _run(*case, mp)
        finally:
            mp.undo()
    return out


def test_deterministic():
    a, b = SessionComposer(19, develop=True), SessionComposer(19, develop=True)
    for v in range(VISITS):
        assert sm.midi_sha256(a.compose('calm', 2, v)[0]) == sm.midi_sha256(b.compose('calm', 2, v)[0])


@pytest.mark.parametrize('case', CASES)
def test_pitch_only_and_legal(runs, case):
    for s in runs[case]:
        c, src, out = s['ctx'], s['src'], s['out']
        for i, (a, b) in enumerate(zip(out.instruments, src.instruments)):
            na = sorted((n.start, n.end, n.velocity) for n in a.notes)
            nb = sorted((n.start, n.end, n.velocity) for n in b.notes)
            assert na == nb and a.program == b.program and a.is_drum == b.is_drum
            if i != c.piano:
                assert [(n.pitch, n.start, n.end, n.velocity) for n in a.notes] == \
                       [(n.pitch, n.start, n.end, n.velocity) for n in b.notes]
        line = [n.pitch for n in _piano(out, c)]
        assert all(p % 12 in ch.pcs for p, ch in zip(line, c.chords)), 'off-chord note'
        assert all(abs(p - b) <= dc.FAR for p, b in zip(line, c.base))
        assert max(line) <= max(c.base) and mean(line) <= mean(c.base) + dc.MAX_MEAN_RISE + 1e-9
        assert max(abs(b - a) for a, b in zip(line, line[1:])) <= c.max_leap


@pytest.mark.parametrize('case', CASES)
def test_at_most_one_change_from_previous_within_block(runs, case):
    seq = runs[case]
    for v in range(1, VISITS):
        if v % dc.BLOCK_LEN == 0:
            continue
        prev, cur = seq[v - 1]['rec'].motif, seq[v]['rec'].motif
        moved = sum(a != b for a, b in zip(prev, cur))
        role = seq[v]['rec'].role
        assert moved <= (2 if role == 'recall' else 1), (v, role, prev, cur)


@pytest.mark.parametrize('case', CASES)
def test_long_history_anti_repeat(runs, case):
    """No developed line repeats one of the last HISTORY_WINDOW lines exactly, or one
    of them other than the previous visit's within one note; fallbacks are logged."""
    seq = runs[case]
    for v, s in enumerate(seq):
        if s['info']['motif_selection'] not in ('candidate', 'gentle') or v == 0:
            continue
        recent = [x['rec'].motif for x in seq[max(0, v - dc.HISTORY_WINDOW):v]]
        m = s['rec'].motif
        assert m not in recent
        assert not any(dc.hamming(m, r) <= 1 for r in recent[:-1])
    hard = sum(s['info']['motif_selection'] in ('previous', 'unchanged') for s in seq)
    assert hard <= 2


@pytest.mark.parametrize('case', CASES)
def test_drum_window_twelve(runs, case):
    seq = runs[case]
    shas = [sm.content_sha(sm.bar_onset_sets(s['out'], 8, 'drum')) for s in seq]
    assert len(set(shas)) == VISITS, 'a drum layer recurred within 12 visits'
    assert all(s['info']['drum_repeat_window'] == dc.DRUM_REPEAT_WINDOW == 12 for s in seq)
    assert not any(s['info']['gen_fallback'] for s in seq)


@pytest.mark.parametrize('case', CASES)
def test_fallback_provenance(runs, case):
    for s in runs[case]:
        sel, rec = s['info']['motif_selection'], s['rec']
        if sel == 'unchanged':
            assert sm.midi_sha256(s['out']) == sm.midi_sha256(s['src']) and rec.motif == s['ctx'].base
            assert s['info']['motif_fallback'] is True
        else:
            assert [n.pitch for n in _piano(s['out'], s['ctx'])] == list(rec.motif)


def test_read_context_rejects_foreign_material():
    pm, info = SessionComposer(1).compose('lofi', 3, 0)
    assert dc.read_context(pm, None, info['tempo_bpm']) is None
