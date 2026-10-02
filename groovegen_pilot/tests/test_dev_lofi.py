"""
Lo-fi development policy v2c.lofi.0 (composer/dev_lofi.py): determinism,
chord-compatible guide-tone dyads, unchanged bass / EP / drums / onsets /
durations / velocities / counts, bounded top-voice contour, pitched p95 not
lowered, history.
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
from composer import dev_lofi as dl  # noqa: E402
from composer.arrangement import SessionComposer  # noqa: E402

VISITS = 12
CASES = [(1, 3), (2, 3), (1, 2), (19, 2)]   # (stim seed, tier)


@pytest.fixture(scope='module')
def runs():
    mp = pytest.MonkeyPatch()
    out = {}
    try:
        for stim, tier in CASES:
            seen = []
            orig = dl.develop

            def spy(src, ctx, records, visit, seed, orig=orig, seen=seen):
                res = orig(src, ctx, records, visit, seed)
                seen.append({'src': src, 'ctx': ctx, 'out': res[0], 'rec': res[1]})
                return res
            mp.setattr(dl, 'develop', spy)
            dev, ref = SessionComposer(stim, develop=True), SessionComposer(stim)
            for v in range(VISITS):
                _, info = dev.compose('lofi', tier, v)
                assert 'motif_error' not in info, info.get('motif_error')
                seen[v].update(info=info, ref=ref.compose('lofi', tier, v)[0])
            mp.undo()
            out[(stim, tier)] = seen
    finally:
        mp.undo()
    return out


def test_deterministic():
    a, b = SessionComposer(2, develop=True), SessionComposer(2, develop=True)
    for v in range(VISITS):
        assert sm.midi_sha256(a.compose('lofi', 3, v)[0]) == sm.midi_sha256(b.compose('lofi', 3, v)[0])


@pytest.mark.parametrize('case', CASES)
def test_only_keys_pitches_change(runs, case):
    """Source = the v2a.3 segment (lofi keeps the v2a.3 drum window): EP, bass and
    drums verbatim; keys keep onsets, durations, velocities and count."""
    for s in runs[case]:
        assert sm.midi_sha256(s['src']) == sm.midi_sha256(s['ref'])
        c = s['ctx']
        for i, (a, b) in enumerate(zip(s['out'].instruments, s['src'].instruments)):
            na = [(n.start, n.end, n.velocity) for n in a.notes]
            assert na == [(n.start, n.end, n.velocity) for n in b.notes]
            if i != c.keys:
                assert [n.pitch for n in a.notes] == [n.pitch for n in b.notes]


@pytest.mark.parametrize('case', CASES)
def test_chord_compatible_dyads(runs, case):
    for s in runs[case]:
        c, notes = s['ctx'], s['out'].instruments[s['ctx'].keys].notes
        for b in range(dl.BARS):
            for idx in (c.color[b],) + c.stabs[b]:
                lo, hi = (notes[j].pitch for j in idx)
                assert lo % 12 in c.chords[b].pcs and hi % 12 in c.chords[b].pcs
                assert (lo % 12, hi - lo) in c.options[b] or (lo, hi) in ((c.base[b],) + c.stab_base[b])
        # stabs carry their bar's dyad
        for b in range(dl.BARS):
            col = tuple(notes[j].pitch % 12 for j in c.color[b])
            assert all(tuple(notes[j].pitch % 12 for j in idx) == col for idx in c.stabs[b])


def test_no_seventh_added_where_ep_has_none(runs):
    for seq in runs.values():
        for s in seq:
            c, notes = s['ctx'], s['out'].instruments[s['ctx'].keys].notes
            for b in range(dl.BARS):
                assert {notes[j].pitch % 12 for j in c.color[b]} <= c.chords[b].pcs


@pytest.mark.parametrize('case', CASES)
def test_bounded_top_voice(runs, case):
    for s in runs[case]:
        c, v = s['ctx'], s['rec'].motif
        tops, base = [d[1] for d in v], [d[1] for d in c.base]
        assert max(tops) <= max(base) and abs(mean(tops) - mean(base)) <= dl.MAX_MEAN_RISE + 1e-9
        assert all(abs(t - b) <= dl.FAR for t, b in zip(tops, base))
        assert all(abs(b - a) <= m for a, b, m in zip(tops, tops[1:], c.max_leaps))
        assert all(m == max(dl.MAX_LEAP, abs(b - a)) for a, b, m in zip(base, base[1:], c.max_leaps))


@pytest.mark.parametrize('case', CASES)
def test_pitched_p95_not_lowered(runs, case):
    """The lofi:3 v2a.3 bases sit on the v1 pitched_pitch_p95 envelope floor."""
    for s in runs[case]:
        p95 = lambda pm: sm.bounded_features(pm, dl.BARS)['pitched_pitch_p95']  # noqa: E731
        assert p95(s['out']) >= p95(s['src']) - 1e-9


@pytest.mark.parametrize('case', CASES)
def test_history_and_one_op(runs, case):
    seq = runs[case]
    for v, s in enumerate(seq):
        rec, sel = s['rec'], s['info']['motif_selection']
        if v % dl.BLOCK_LEN == 0:
            assert rec.role == 'base' and rec.motif == s['ctx'].base
            continue
        assert len(rec.ops) <= 1
        if sel in ('candidate', 'gentle'):
            recent = [x['rec'].motif for x in seq[max(0, v - dl.HISTORY_WINDOW):v]]
            assert rec.motif not in recent
            prev = seq[v - 1]['rec'].motif
            changed = [b for b in range(dl.BARS) if rec.motif[b] != prev[b]]
            assert changed and (rec.role == 'recall' or rec.ops[0].startswith('guide') or len(changed) == 1)
            if rec.role == 'recall' or rec.ops[0].startswith('guide'):
                assert min(changed) >= 4
    assert sum(s['info']['motif_selection'] in ('previous', 'unchanged') for s in seq) <= 2


def test_read_context_rejects_foreign_material():
    pm, info = SessionComposer(1).compose('calm', 2, 0)
    assert dl.read_context(pm, None, info['tempo_bpm']) is None
