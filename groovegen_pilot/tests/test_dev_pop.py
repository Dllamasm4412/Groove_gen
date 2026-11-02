"""
Pop development policy v2c.pop.0 (composer/dev_pop.py): determinism, theme
anchoring (bars 1-2 kept, bars 5-6 restate them on theme visits), legal
transformations (chord tones of the bar's pool, the source's register),
bounded contour / leaps, unchanged EP / bass / drums / onsets / durations /
velocities / counts / tempo, pitched median / p95, predicted level, exact / near
/ ending history, fallback chain and rate, provenance.
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
from composer import dev_pop as dp  # noqa: E402
from composer import develop_engine as de  # noqa: E402
from composer.arrangement import GEN_VERSION, SessionComposer  # noqa: E402

VISITS = 12
CASES = [(1, 3), (2, 3), (19, 3), (1, 1), (2, 2), (19, 4), (1, 5)]   # (stim seed, tier)
FALLBACKS = ('previous', 'unchanged')


@pytest.fixture(scope='module')
def runs():
    mp = pytest.MonkeyPatch()
    out = {}
    try:
        for stim, tier in CASES:
            seen = []
            orig = dp.develop

            def spy(src, ctx, records, visit, seed, orig=orig, seen=seen):
                res = orig(src, ctx, records, visit, seed)
                seen.append({'src': src, 'ctx': ctx, 'out': res[0], 'rec': res[1]})
                return res
            mp.setattr(dp, 'develop', spy)
            dev, ref = SessionComposer(stim, develop=True), SessionComposer(stim)
            for v in range(VISITS):
                _, info = dev.compose('pop', tier, v)
                assert 'motif_error' not in info, info.get('motif_error')
                seen[v].update(info=info, ref=ref.compose('pop', tier, v)[0])
            mp.undo()
            out[(stim, tier)] = seen
    finally:
        mp.undo()
    return out


def test_deterministic():
    a, b = SessionComposer(2, develop=True), SessionComposer(2, develop=True)
    for v in range(VISITS):
        (pa, ia), (pb, ib) = a.compose('pop', 3, v), b.compose('pop', 3, v)
        assert sm.midi_sha256(pa) == sm.midi_sha256(pb) and ia == ib


@pytest.mark.parametrize('case', CASES)
def test_version_and_provenance(runs, case):
    for s in runs[case]:
        info = s['info']
        assert info['dev_version'] == dp.DEV_VERSION == 'v2c.pop.0'
        assert info['gen_version'] == f'{GEN_VERSION}+{dp.DEV_VERSION}'
        assert info['motif_selection'] in ('candidate', 'gentle') + FALLBACKS
        assert info['motif_role'] == s['rec'].role and info['motif_ops'] == list(s['rec'].ops)
        assert info['motif_theme_id'] == de.material_id(dp.theme_of(s['ctx'].base, s['ctx']))


@pytest.mark.parametrize('case', CASES)
def test_only_lead_pitches_change(runs, case):
    """Source = the v2a.3 segment: EP, bass and drums verbatim; the lead keeps onsets,
    durations, velocities, count and program; tempo unchanged."""
    for s in runs[case]:
        assert sm.midi_sha256(s['src']) == sm.midi_sha256(s['ref'])
        c = s['ctx']
        assert len(s['out'].instruments) == len(s['src'].instruments)
        for i, (a, b) in enumerate(zip(s['out'].instruments, s['src'].instruments)):
            assert (a.program, a.is_drum, a.name) == (b.program, b.is_drum, b.name)
            assert [(n.start, n.end, n.velocity) for n in a.notes] == [(n.start, n.end, n.velocity) for n in b.notes]
            if i != c.lead:
                assert [n.pitch for n in a.notes] == [n.pitch for n in b.notes]
        assert sm.played_tempo(s['out']) == sm.played_tempo(s['src'])


@pytest.mark.parametrize('case', CASES)
def test_realized_line_is_the_record(runs, case):
    for s in runs[case]:
        c, notes = s['ctx'], s['out'].instruments[s['ctx'].lead].notes
        assert tuple(tuple(notes[j].pitch for j in idx) for idx in c.idx) == s['rec'].motif


@pytest.mark.parametrize('case', CASES)
def test_theme_anchor_and_return(runs, case):
    """Bars 1-2 are always the source's; a theme visit restates them on bars 5-6 (same
    chords), except notes repaired because they would sound in unison with an
    overlapping note."""
    for v, s in enumerate(runs[case]):
        c, m = s['ctx'], s['rec'].motif
        assert m[:2] == c.base[:2]
        assert c.chords[0].pcs == c.chords[4].pcs and c.chords[1].pcs == c.chords[5].pcs
        if v % dp.BLOCK_LEN == 0 and s['info']['motif_selection'] == 'candidate':
            assert s['rec'].role == 'theme' and s['rec'].ops[0] == 'return@5-6'
            assert m[4:6] == dp.theme_line(c)[4:6]
            raw = dp._flat(dp.place_theme(c.base, c, dp.theme_of(c.base, c)))
            f, n = dp._flat(m), len(m[0])
            for i in range(4 * n, 6 * n):
                if f[i] != raw[i]:
                    assert any(raw[i] == raw[j] for a, b in c.overlaps if i in (a, b) for j in (a, b) if j != i)


def test_theme_recurs_and_recall_happens(runs):
    seqs = list(runs.values())
    returned = sum(s['rec'].motif[4:6] == s['rec'].motif[:2] for seq in seqs for s in seq)
    assert returned >= len(seqs) * VISITS // 2
    assert any(s['rec'].role == 'recall' for seq in seqs for s in seq)


@pytest.mark.parametrize('case', CASES)
def test_chord_tones_in_pool_and_register(runs, case):
    for s in runs[case]:
        c, m = s['ctx'], s['rec'].motif
        assert all(p in pool and p % 12 in ch.pcs for bar, pool, ch in zip(m, c.pools, c.chords) for p in bar)
        f, fb = dp._flat(m), dp._flat(c.base)
        assert max(f) <= max(fb) and abs(mean(f) - mean(fb)) <= dp.MAX_MEAN_SHIFT + 1e-9


@pytest.mark.parametrize('case', CASES)
def test_bounded_contour_and_leaps(runs, case):
    for s in runs[case]:
        c, m = s['ctx'], s['rec'].motif
        assert all(abs(m[b + 1][0] - m[b][-1]) <= c.max_cross[b] for b in range(dp.BARS - 1))
        assert max(c.max_cross) >= dp.MAX_LEAP_X
        assert mean(dp.leaps(m)) <= mean(dp.leaps(c.base)) + dp.LEAP_SLACK + 1e-9
        f, fb = dp._flat(m), dp._flat(c.base)
        assert not any(f[a] == f[b] and fb[a] != fb[b] for a, b in c.overlaps)     # no new unison


@pytest.mark.parametrize('case', CASES)
def test_register_features_and_guard(runs, case):
    for s in runs[case]:
        a, b = sm.bounded_features(s['out'], dp.BARS), sm.bounded_features(s['src'], dp.BARS)
        assert a['pitched_pitch_median'] == b['pitched_pitch_median']
        assert b['pitched_pitch_p95'] - de.MAX_PITCH_SHIFT - 1e-9 <= a['pitched_pitch_p95'] <= b['pitched_pitch_p95'] + 1e-9
        assert (a['pitched_pitch_median'], a['pitched_pitch_p95']) == pytest.approx(dp.register(s['rec'].motif, s['ctx']))
        assert dp.guard(s['out'], s['src'], s['ctx']).ok


@pytest.mark.parametrize('case', CASES)
def test_predicted_level(runs, case):
    for s in runs[case]:
        if s['info']['motif_selection'] in ('candidate', 'gentle'):
            assert abs(dp.energy_shift(s['rec'].plan, None, s['ctx'])['level_db']) <= dp.LEVEL_TOL_DB + 1e-9


def test_level_table_pinned():
    from composer import levels_pop_lead as lv

    assert lv.PROGRAM == dp.LEAD == 25
    assert 77 in lv.VELOCITIES and 78 in lv.VELOCITIES          # the sf2 velocity-layer switch
    assert min(lv.LEVEL_DB) <= 60 and max(lv.LEVEL_DB) >= 81    # the generator's pitch range


@pytest.mark.parametrize('case', CASES)
def test_history(runs, case):
    seq = runs[case]
    for v, s in enumerate(seq):
        rec, sel = s['rec'], s['info']['motif_selection']
        if v % dp.BLOCK_LEN == 0 or sel not in ('candidate', 'gentle'):
            continue
        recent = [x['rec'] for x in seq[max(0, v - dp.HISTORY_WINDOW):v]]
        assert rec.motif not in {r.motif for r in recent}
        assert all(dp.hamming(rec.motif, r.motif) > 1 for r in recent[:-1])
        assert dp.endings(rec.motif) not in {dp.endings(r.motif) for r in recent}


def test_repeats_rules():
    c = None
    base = ((60, 64),) * 8
    mk = lambda m, role='develop': dp.DevRecord(motif=m, theme=(), plan=(m,), role=role, ops=())  # noqa: E731
    a = ((60, 64),) * 7 + ((60, 67),)
    b = ((64, 64),) + a[1:]
    e = ((60, 64),) * 3 + ((67, 64),) * 4 + ((60, 67),)
    assert dp.repeats(mk(base, 'theme'), [mk(base, 'theme')], c) is None         # the theme statement may recur
    assert dp.repeats(mk(a), [mk(a)], c) == 'history'
    assert dp.repeats(mk(b), [mk(a), mk(base)], c) == 'near'                     # one note off an older visit
    assert dp.repeats(mk(e), [mk(a)], c) == 'ending'                             # same bar-4 / bar-8 endings
    assert dp.repeats(mk(b), [mk(base)], c) is None


def test_fallback_chain_and_rate(runs):
    sel = [s['info']['motif_selection'] for seq in runs.values() for s in seq]
    for seq in runs.values():
        for s in seq:
            if s['info']['motif_selection'] == 'unchanged':
                assert sm.midi_sha256(s['out']) == sm.midi_sha256(s['src']) and s['rec'].motif == s['ctx'].base
            if s['info']['motif_selection'] == 'previous':
                assert s['rec'].role == 'fallback' and len(s['rec'].ops) <= 2
    # measured 11 / 180 visits over pop:1-5 x stims 1, 2, 19 (8 previous, 3 unchanged)
    assert sum(x in FALLBACKS for x in sel) <= len(sel) // 10


def test_read_context_rejects_foreign_material():
    pm, info = SessionComposer(1).compose('calm', 2, 0)
    assert dp.read_context(pm, None, info['tempo_bpm']) is None
