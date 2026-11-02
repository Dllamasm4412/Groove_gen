"""
R&B development policy v2c.rnb.0 (composer/dev_rnb.py): determinism,
chord-compatible guide-tone dyads, 7ths only where the EP plays them, unchanged
bass / EP / drums / onsets / durations / velocities / counts, bounded top-voice
motion, no 4-bar loop, pitched p95 / median not moved outward, predicted level,
exact / near / ending history, at most two ops, fallback chain, provenance.
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
from composer import dev_rnb as dr  # noqa: E402
from composer.arrangement import GEN_VERSION, SessionComposer  # noqa: E402

VISITS = 12
CASES = [(1, 3), (2, 3), (19, 3), (1, 1), (2, 2), (19, 4)]   # (stim seed, tier)
FALLBACKS = ('previous', 'unchanged')


@pytest.fixture(scope='module')
def runs():
    mp = pytest.MonkeyPatch()
    out = {}
    try:
        for stim, tier in CASES:
            seen = []
            orig = dr.develop

            def spy(src, ctx, records, visit, seed, orig=orig, seen=seen):
                res = orig(src, ctx, records, visit, seed)
                seen.append({'src': src, 'ctx': ctx, 'out': res[0], 'rec': res[1]})
                return res
            mp.setattr(dr, 'develop', spy)
            dev, ref = SessionComposer(stim, develop=True), SessionComposer(stim)
            for v in range(VISITS):
                _, info = dev.compose('rnb', tier, v)
                assert 'motif_error' not in info, info.get('motif_error')
                seen[v].update(info=info, ref=ref.compose('rnb', tier, v)[0])
            mp.undo()
            out[(stim, tier)] = seen
    finally:
        mp.undo()
    return out


def test_deterministic():
    a, b = SessionComposer(2, develop=True), SessionComposer(2, develop=True)
    for v in range(VISITS):
        (pa, ia), (pb, ib) = a.compose('rnb', 3, v), b.compose('rnb', 3, v)
        assert sm.midi_sha256(pa) == sm.midi_sha256(pb) and ia == ib


@pytest.mark.parametrize('case', CASES)
def test_version_and_provenance(runs, case):
    for s in runs[case]:
        info = s['info']
        assert info['dev_version'] == dr.DEV_VERSION == 'v2c.rnb.0'
        assert info['gen_version'] == f'{GEN_VERSION}+{dr.DEV_VERSION}'
        assert info['motif_selection'] in ('candidate', 'gentle') + FALLBACKS
        assert info['motif_role'] == s['rec'].role and info['motif_ops'] == list(s['rec'].ops)


@pytest.mark.parametrize('case', CASES)
def test_only_keys_pitches_change(runs, case):
    """Source = the v2a.3 segment: EP, bass and drums verbatim; keys keep onsets,
    durations, velocities and count."""
    for s in runs[case]:
        assert sm.midi_sha256(s['src']) == sm.midi_sha256(s['ref'])
        c = s['ctx']
        assert len(s['out'].instruments) == len(s['src'].instruments)
        for i, (a, b) in enumerate(zip(s['out'].instruments, s['src'].instruments)):
            assert (a.program, a.is_drum) == (b.program, b.is_drum)
            assert [(n.start, n.end, n.velocity) for n in a.notes] == [(n.start, n.end, n.velocity) for n in b.notes]
            if i != c.keys:
                assert [n.pitch for n in a.notes] == [n.pitch for n in b.notes]
        assert sm.played_tempo(s['out']) == sm.played_tempo(s['src'])


@pytest.mark.parametrize('case', CASES)
def test_chord_compatible_dyads(runs, case):
    for s in runs[case]:
        c, notes = s['ctx'], s['out'].instruments[s['ctx'].keys].notes
        for b in range(dr.BARS):
            col = tuple(notes[j].pitch for j in c.color[b])
            assert all(p % 12 in c.chords[b].pcs for p in col)
            assert (col[0] % 12, col[1] - col[0]) in c.options[b] or col == c.base[b]
            # stabs carry their bar's dyad
            assert all(tuple(notes[j].pitch % 12 for j in idx) == tuple(p % 12 for p in col) for idx in c.stabs[b])


def test_sevenths_only_where_the_ep_plays_them(runs):
    used = 0
    for seq in runs.values():
        for s in seq:
            c, notes = s['ctx'], s['out'].instruments[s['ctx'].keys].notes
            for b in range(dr.BARS):
                ch = c.chords[b]
                sevenths = {(ch.root + 10) % 12, (ch.root + 11) % 12}
                for j in c.color[b] + tuple(x for idx in c.stabs[b] for x in idx):
                    if notes[j].pitch % 12 in sevenths:
                        assert notes[j].pitch % 12 in ch.pcs
                        used += 1
    assert used > 0        # the 5th + 7th dyad is reachable


@pytest.mark.parametrize('case', CASES)
def test_smooth_bounded_top_voice(runs, case):
    for s in runs[case]:
        c, v = s['ctx'], s['rec'].motif
        tops, base = [d[1] for d in v], [d[1] for d in c.base]
        assert max(tops) <= max(base) and abs(mean(tops) - mean(base)) <= dr.MAX_MEAN_SHIFT + 1e-9
        assert all(abs(t - b) <= dr.FAR for t, b in zip(tops, base))
        assert all(abs(b - a) <= m for a, b, m in zip(tops, tops[1:], dr.max_leaps(c)))
        assert max(dr.max_leaps(c)) == dr.MAX_LEAP


@pytest.mark.parametrize('case', CASES)
def test_developed_never_loops_and_keeps_register(runs, case):
    for s in runs[case]:
        rec, c = s['rec'], s['ctx']
        if rec.motif != c.base:
            assert not dr.looped(rec.motif)
        assert dr.guard(s['out'], s['src'], c).ok


@pytest.mark.parametrize('case', CASES)
def test_predicted_level(runs, case):
    for s in runs[case]:
        if s['info']['motif_selection'] in ('candidate', 'gentle'):
            assert abs(dr.energy_shift(s['rec'].plan, None, s['ctx'])['level_db']) <= dr.LEVEL_TOL_DB + 1e-9


@pytest.mark.parametrize('case', CASES)
def test_history_and_two_ops(runs, case):
    seq = runs[case]
    for v, s in enumerate(seq):
        rec, sel = s['rec'], s['info']['motif_selection']
        if v % dr.BLOCK_LEN == 0:
            assert rec.role == 'base' and rec.motif == s['ctx'].base and sel == 'candidate'
            continue
        assert len(rec.ops) <= 2
        if sel in ('candidate', 'gentle'):
            recent = [x['rec'] for x in seq[max(0, v - dr.HISTORY_WINDOW):v]]
            assert rec.motif not in {r.motif for r in recent}
            assert all(dr.hamming(rec.motif, r.motif) > 1 for r in recent[:-1])
            assert (rec.motif[3], rec.motif[7]) not in {(r.motif[3], r.motif[7]) for r in recent if r.role != 'base'}
            assert rec.motif != seq[v - 1]['rec'].motif


def test_repeats_rules():
    c = type('C', (), {})()
    base = ((64, 67),) * 8
    mk = lambda m, role='develop': dr.DevRecord(motif=m, theme=(0, 0, 0), plan=(m,), role=role, ops=())  # noqa: E731
    a = ((64, 67),) * 7 + ((62, 66),)
    b = ((60, 64),) + a[1:]
    assert dr.repeats(mk(base, 'base'), [mk(base, 'base')], c) is None          # the source may recur
    assert dr.repeats(mk(a), [mk(a)], c) == 'history'
    assert dr.repeats(mk(b), [mk(a), mk(base, 'base')], c) == 'near'            # one bar off an older visit
    assert dr.repeats(mk(b), [mk(a)], c) == 'ending'                             # one bar off the previous: ending
    assert dr.repeats(mk(b), [mk(base, 'base'), mk(a, 'base')], c) is None


def test_fallback_chain_and_rate(runs):
    sel = [s['info']['motif_selection'] for seq in runs.values() for v, s in enumerate(seq) if v % dr.BLOCK_LEN]
    for seq in runs.values():
        for s in seq:
            if s['info']['motif_selection'] == 'unchanged':
                assert sm.midi_sha256(s['out']) == sm.midi_sha256(s['src']) and s['rec'].motif == s['ctx'].base
            if s['info']['motif_selection'] == 'previous':
                assert s['rec'].role == 'fallback' and len(s['rec'].ops) == 1
    # measured 8 / 48 developed visits here (the worst seeds: rnb:1 s1, rnb:2 s2; 11 / 96 over
    # rnb:1-4 x stims 1, 2, 19): the strict p95 guard on high-register rnb:1-2 segments
    assert sum(x in FALLBACKS for x in sel) <= len(sel) // 5


def test_read_context_rejects_foreign_material():
    pm, info = SessionComposer(1).compose('calm', 2, 0)
    assert dr.read_context(pm, None, info['tempo_bpm']) is None
