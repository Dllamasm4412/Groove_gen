"""
Latin development policy v2c.latin.1 (composer/dev_latin.py): determinism,
anchor (bars 1-2 kept), legal voicings (each triad keeps its pitch classes,
closed, inside the window, uniform per bar except the ending triad), unchanged
percussion / onsets / durations / velocities / counts / tempo, exact pitched
p05 / median / p95, smoothed top line, predicted level, exact / near / ending
history, fallback chain and rate, provenance; piano and bass (v2c.latin.1):
chord tones inside their windows, bars 1-2 kept, the realized notes are the
recorded patterns, both patterns change every visit.
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
from composer import dev_latin as dl  # noqa: E402
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
            orig = dl.develop

            def spy(src, ctx, records, visit, seed, orig=orig, seen=seen):
                res = orig(src, ctx, records, visit, seed)
                seen.append({'src': src, 'ctx': ctx, 'out': res[0], 'rec': res[1]})
                return res
            mp.setattr(dl, 'develop', spy)
            dev, ref = SessionComposer(stim, develop=True), SessionComposer(stim)
            for v in range(VISITS):
                _, info = dev.compose('latin', tier, v)
                assert 'motif_error' not in info, info.get('motif_error')
                seen[v].update(info=info, ref=ref.compose('latin', tier, v)[0])
            mp.undo()
            out[(stim, tier)] = seen
    finally:
        mp.undo()
    return out


def test_deterministic():
    a, b = SessionComposer(2, develop=True), SessionComposer(2, develop=True)
    for v in range(VISITS):
        (pa, ia), (pb, ib) = a.compose('latin', 3, v), b.compose('latin', 3, v)
        assert sm.midi_sha256(pa) == sm.midi_sha256(pb) and ia == ib


@pytest.mark.parametrize('case', CASES)
def test_version_and_provenance(runs, case):
    for s in runs[case]:
        info = s['info']
        assert info['dev_version'] == dl.DEV_VERSION == 'v2c.latin.1'
        assert info['gen_version'] == f'{GEN_VERSION}+{dl.DEV_VERSION}'
        assert info['motif_selection'] in ('candidate', 'gentle') + FALLBACKS
        assert info['motif_role'] == s['rec'].role and info['motif_ops'] == list(s['rec'].ops)


@pytest.mark.parametrize('case', CASES)
def test_only_pitched_pitches_change(runs, case):
    """Source = the v2a.3 segment: percussion verbatim; nylon, piano and bass keep
    onsets, durations, velocities, count and program; tempo unchanged."""
    for s in runs[case]:
        assert sm.midi_sha256(s['src']) == sm.midi_sha256(s['ref'])
        c = s['ctx']
        assert c.accomp is not None
        assert len(s['out'].instruments) == len(s['src'].instruments)
        for i, (a, b) in enumerate(zip(s['out'].instruments, s['src'].instruments)):
            assert (a.program, a.is_drum, a.name) == (b.program, b.is_drum, b.name)
            assert [(n.start, n.end, n.velocity) for n in a.notes] == [(n.start, n.end, n.velocity) for n in b.notes]
            if i not in (c.nylon, c.accomp.bass, c.accomp.piano):
                assert [n.pitch for n in a.notes] == [n.pitch for n in b.notes]
        assert s['out'].instruments[c.nylon].program == dl.NYLON
        assert sm.played_tempo(s['out']) == sm.played_tempo(s['src'])


@pytest.mark.parametrize('case', CASES)
def test_realized_line_is_the_record(runs, case):
    for s in runs[case]:
        c, notes = s['ctx'], s['out'].instruments[s['ctx'].nylon].notes
        assert tuple(tuple(tuple(notes[j].pitch for j in g) for g in gs) for gs in c.idx) == s['rec'].motif


@pytest.mark.parametrize('case', CASES)
def test_anchor_and_legal_voicings(runs, case):
    """Bars 1-2 are the source's; every triad is a closed voicing of its bar's chord
    inside the window; one voicing per bar except bar 8's last triad."""
    for s in runs[case]:
        c, m = s['ctx'], s['rec'].motif
        assert m[:2] == c.base[:2]
        for bar, ch in zip(m, c.chords):
            for t in bar:
                assert frozenset(p % 12 for p in t) == ch and len(t) == 3
                assert t[-1] - t[0] < 12 and c.lo <= t[0] and t[-1] <= c.hi
        assert all(len(set(bar)) == 1 for bar in m[:-1]) and len(set(m[-1][:-1])) == 1


@pytest.mark.parametrize('case', CASES)
def test_register_and_top_line(runs, case):
    """Pitched p05 / median / p95 exactly the source's (zero-width envelopes); nylon
    mean within MAX_MEAN_SHIFT; top-voice leaps no larger, on average no larger."""
    for s in runs[case]:
        c, m = s['ctx'], s['rec'].motif
        a, b = sm.bounded_features(s['out'], dl.BARS), sm.bounded_features(s['src'], dl.BARS)
        for f in ('pitched_pitch_p05', 'pitched_pitch_median', 'pitched_pitch_p95'):
            assert a[f] == b[f]
        assert (a['pitched_pitch_p05'], a['pitched_pitch_median'], a['pitched_pitch_p95']) == \
            pytest.approx(dl.register(m, c))
        assert abs(mean(dl._flat(m)) - mean(dl._flat(c.base))) <= dl.MAX_MEAN_SHIFT + 1e-9
        assert max(dl.top_leaps(m)) <= max(dl.top_leaps(c.base))
        assert mean(dl.top_leaps(m)) <= mean(dl.top_leaps(c.base)) + dl.LEAP_SLACK + 1e-9
        assert dl.guard(s['out'], s['src'], c).ok


@pytest.mark.parametrize('case', CASES)
def test_predicted_level(runs, case):
    for s in runs[case]:
        if s['info']['motif_selection'] in ('candidate', 'gentle'):
            assert abs(dl.energy_shift(s['rec'].plan, None, s['ctx'])['level_db']) <= dl.LEVEL_TOL_DB + 1e-9


def test_level_table_pinned():
    from composer import levels_latin_nylon as lv

    assert lv.PROGRAM == dl.NYLON == 24
    assert 84 in lv.VELOCITIES and 85 in lv.VELOCITIES          # the sf2 velocity-layer switch
    assert min(lv.LEVEL_DB) <= 46 and max(lv.LEVEL_DB) >= 67    # the window (48-65 +- REG_SLACK)


@pytest.mark.parametrize('case', CASES)
def test_history(runs, case):
    seq = runs[case]
    for v, s in enumerate(seq):
        rec, sel = s['rec'], s['info']['motif_selection']
        if v == 0 or sel not in ('candidate', 'gentle'):
            continue
        recent = [x['rec'] for x in seq[max(0, v - dl.HISTORY_WINDOW):v]]
        assert rec.motif not in {r.motif for r in recent}
        if rec.role == 'theme':
            continue
        assert all(dl.hamming(rec.motif, r.motif) > 1 for r in recent[:-1])
        assert dl.endings(rec.motif) not in {dl.endings(r.motif) for r in recent[-dl.ENDING_WINDOW:]}


def test_develops_every_visit(runs):
    """No visit repeats its predecessor's nylon; most bar-8 endings change."""
    for seq in runs.values():
        lines = [s['rec'].motif for s in seq]
        assert all(a != b for a, b in zip(lines, lines[1:]))
        assert sum(a[-1] != b[-1] for a, b in zip(lines, lines[1:])) >= (VISITS - 1) * 2 // 3


def test_repeats_rules():
    c = None
    t, u, w = (55, 60, 63), (60, 63, 67), (51, 55, 60)
    mk = lambda m, role='develop': dl.DevRecord(motif=m, theme=(), plan=(m,), role=role, ops=())  # noqa: E731
    base = ((t, t),) * 8
    a = ((t, t),) * 7 + ((t, u),)
    b = ((t, t),) * 2 + ((t, u),) + ((t, t),) * 4 + ((t, u),)
    e = ((t, t),) * 4 + ((w, w),) * 3 + ((t, u),)
    assert dl.repeats(mk(base, 'theme'), [mk(a)], c) is None
    assert dl.repeats(mk(a), [mk(a)], c) == 'history'
    assert dl.repeats(mk(b), [mk(a), mk(base)], c) == 'near'                     # one triad off an older visit
    assert dl.repeats(mk(e), [mk(a)], c) == 'ending'                             # same bar-4 / bar-8 endings


def test_fallback_chain_and_rate(runs):
    sel = [s['info']['motif_selection'] for seq in runs.values() for s in seq]
    for seq in runs.values():
        for s in seq:
            if s['info']['motif_selection'] == 'unchanged':     # the nylon; piano and bass still develop
                n = s['ctx'].nylon
                assert [x.pitch for x in s['out'].instruments[n].notes] == [x.pitch for x in s['src'].instruments[n].notes]
                assert s['rec'].motif == s['ctx'].base
            if s['info']['motif_selection'] == 'previous':
                assert s['rec'].role == 'fallback'
    # measured 7 / 180 visits over latin:1-5 x stims 1, 2, 19 (6 previous, 1 unchanged)
    assert sum(x in FALLBACKS for x in sel) <= len(sel) // 10


def _bar_of(c, track: int, j: int) -> int:
    at = c.accomp.bass_at if track == c.accomp.bass else c.accomp.piano_at
    return next(b for b, bar in enumerate(at) for _, x in bar if j == x or (isinstance(x, tuple) and j in x))


@pytest.mark.parametrize('case', CASES)
def test_accompaniment_is_the_record(runs, case):
    """Every visit records one bass and one piano pattern with their span; the
    realized piano and bass are those patterns over that span and the source's
    elsewhere (bars 1-2 always); chord tones inside the windows."""
    for s in runs[case]:
        c, ops = s['ctx'], s['rec'].ops
        pair = dl._accomp_of(s['rec'])
        assert pair is not None, ops
        span = next(op for op in ops if op.startswith('bass:')).split('@')[1]
        assert span == next(op for op in ops if op.startswith('piano:')).split('@')[1]
        lo, hi = (int(x) - 1 for x in span.split('-'))
        bars = tuple(range(lo, hi + 1))
        assert bars in set(dl.ACCOMP_SPANS.values()) and 0 not in bars and 1 not in bars
        for track, line in ((c.accomp.bass, dl.bass_line(s['src'], c, pair[0], bars)),
                            (c.accomp.piano, dl.piano_line(s['src'], c, pair[1], bars))):
            assert line and all(_bar_of(c, track, j) in bars for j in line)
            got = [n.pitch for n in s['out'].instruments[track].notes]
            assert got == [line.get(j, n.pitch) for j, n in enumerate(s['src'].instruments[track].notes)]
        assert dl.accomp_failures(s['out'], c) == []


def test_accompaniment_changes_every_visit(runs):
    """Bass and piano patterns both differ from the previous visit's, the pair from
    the previous block's worth of visits, and the played piano and bass differ
    from the previous visit's. With balanced() pairs only, the HISTORY_WINDOW
    pair rule relaxes now and then (measured: 1 repeat in 108 visits, 4 visits
    apart)."""
    window_repeats = 0
    for seq in runs.values():
        pairs = [dl._accomp_of(s['rec']) for s in seq]
        for v in range(1, len(seq)):
            assert pairs[v][0] != pairs[v - 1][0] and pairs[v][1] != pairs[v - 1][1]
            assert pairs[v] not in pairs[max(0, v - dl.BLOCK_LEN):v]
            window_repeats += pairs[v] in pairs[max(0, v - dl.HISTORY_WINDOW):v]
            c = seq[v]['ctx']
            for track in (c.accomp.bass, c.accomp.piano):
                assert [n.pitch for n in seq[v]['out'].instruments[track].notes] != \
                    [n.pitch for n in seq[v - 1]['out'].instruments[track].notes]
    assert window_repeats <= 2


def test_played_pairs_are_balanced(runs):
    """Every played pair's predicted dLUFS / dlow_ratio is inside the tolerances,
    and no pair includes a pattern without a measured effect."""
    assert set(dl.BASS_PATTERNS) | set(dl.PIANO_PATTERNS) == set(dl.ACCOMP_EFFECT)
    for seq in runs.values():
        for s in seq:
            bp, pp = dl._accomp_of(s['rec'])
            lo, hi = (int(x) - 1 for x in next(op for op in s['rec'].ops if op.startswith('bass:')).split('@')[1].split('-'))
            assert dl.balanced(bp, pp, range(lo, hi + 1))


def test_accompaniment_patterns():
    """The tumbao and dyad patterns on one bar (latin:1 stim 1 bar 3): pitch
    classes and placement (nearest the source note inside the window)."""
    pm, info = SessionComposer(1).compose('latin', 1, 0)
    c = dl.read_context(pm, None, info['tempo_bpm'])
    bass, piano = pm.instruments[c.accomp.bass].notes, pm.instruments[c.accomp.piano].notes
    b = 2
    at = dict(c.accomp.bass_at[b])
    src = {beat: bass[j].pitch for beat, j in at.items()}
    nxt = bass[dict(c.accomp.bass_at[b + 1])[0.0]].pitch
    swap = dl.bass_line(pm, c, 'swap', (b,))
    assert (swap[at[1.5]], swap[at[2.0]]) == (src[2.0], src[1.5])
    assert dl.bass_line(pm, c, 'anticipate', (b,)) == {at[3.5]: nxt}
    assert dl.bass_line(pm, c, 'anticipate', (7,)) == {}                     # bar 8: nothing to anticipate
    assert dl.bass_line(pm, c, 'octave', (b,)) == {at[3.5]: src[0.0] + 12}
    both = dl.bass_line(pm, c, 'swap+anticipate', (b,))
    assert both == {**swap, at[3.5]: nxt}
    r, t, f = dl._degrees(src[0.0], c.chords[b])
    (_, (lo, hi)), (_, (lo2, hi2)) = c.accomp.piano_at[b][:2]
    move = dl.piano_line(pm, c, 'R3>5R', (b,))
    assert (move[lo] % 12, move[hi] % 12) == (r, t) and (move[lo2] % 12, move[hi2] % 12) == (f, r)
    assert (move[lo], move[hi]) == (piano[lo].pitch, piano[hi].pitch)        # R3 is the source dyad
    up = dl.piano_line(pm, c, '35', (b,))
    assert (up[lo] % 12, up[hi] % 12) == (t, f) and up[lo] == up[lo2]


def test_accompaniment_guard_rejects_wrong_notes():
    pm, info = SessionComposer(1).compose('latin', 1, 0)
    c = dl.read_context(pm, None, info['tempo_bpm'])
    bad = dl.copy.deepcopy(pm)
    _, (lo, _) = c.accomp.piano_at[3][0]
    bad.instruments[c.accomp.piano].notes[lo].pitch += 1
    assert 'piano_chord' in dl.guard(bad, pm, c).failures
    bad = dl.copy.deepcopy(pm)
    j = dict(c.accomp.bass_at[3])[1.5]
    bad.instruments[c.accomp.bass].notes[j].pitch += 12
    assert 'bass_window' in dl.guard(bad, pm, c).failures


def test_read_context_rejects_foreign_material():
    pm, info = SessionComposer(1).compose('calm', 2, 0)
    assert dl.read_context(pm, None, info['tempo_bpm']) is None
