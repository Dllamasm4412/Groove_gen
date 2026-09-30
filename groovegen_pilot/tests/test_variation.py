"""
Tests for the timbre-preserving drum variation rules (composer/variation.py,
v2a.2; LIVE_GENERATION_PLAN.md section 6.8): op invariants on synthetic bars,
brightness proxy, and per-segment / per-session properties on live cells.
"""

from __future__ import annotations

import copy
import sys
from collections import Counter
from pathlib import Path

import pretty_midi
import pytest

PILOT = Path(__file__).resolve().parent.parent
if str(PILOT) not in sys.path:
    sys.path.insert(0, str(PILOT))

import stimulus_metrics as sm  # noqa: E402
from composer import variation as va  # noqa: E402
from composer.arrangement import BARS, SessionComposer, cell_plan, schedule  # noqa: E402

VISITS = 8
SEEDS = range(12)


def _pm(hits: list[tuple[int, int, int]], bars: int = BARS) -> pretty_midi.PrettyMIDI:
    """Drum-only segment at 120 bpm: (pitch, 16th slot, velocity) repeated in every bar."""
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    inst = pretty_midi.Instrument(program=0, is_drum=True)
    step = 60.0 / 120.0 / 4
    for b in range(bars):
        for pitch, pos, vel in hits:
            t = (b * va.STEPS + pos) * step
            inst.notes.append(pretty_midi.Note(velocity=vel, pitch=pitch, start=t, end=t + step / 2))
    pm.instruments.append(inst)
    return pm


# pop-like bar: protected kick / snare on beats, off-beat hats (closed, open),
# an off-beat ghost snare and clap, an off-beat kick
_BAR = [(36, 0, 100), (38, 4, 96), (36, 8, 100), (38, 12, 96),
        (42, 2, 70), (42, 6, 72), (46, 10, 74), (42, 14, 70),
        (38, 7, 40), (39, 15, 60), (36, 11, 80)]


def _setup(hits=_BAR, genre='pop', relax=0):
    pm = _pm(hits)
    step = va._step_s(pm)
    all_hits = [va._Hit(n, step, genre) for n in pm.instruments[0].notes]
    bars = [[h for h in all_hits if h.bar == b] for b in range(BARS)]
    ctx = va._Ctx(pm, step, {h.note.pitch for h in all_hits}, relax)
    return pm, bars, ctx


def _bar_state(bar):
    return (sorted((h.note.pitch, h.pos, h.note.velocity) for h in bar),
            {h.pos for h in bar})


def _live_cells():
    from stimulus_audit import live_ladder

    ladder, _ = live_ladder('measured')
    return [(c.genre, c.tier) for c in ladder.cells]


def _live_base(genre, tier, visit=0):
    from composer import generate_segment

    s = schedule(1, genre, tier, visit)
    tempo, density = cell_plan(genre, tier)
    return generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=BARS, seed=s.base_seed)


def _drums(pm):
    return [n for i in pm.instruments if i.is_drum for n in i.notes]


# ----------------------------------------------------------------------------
# Brightness proxy
# ----------------------------------------------------------------------------


def test_drum_brightness_proxy():
    assert va.drum_brightness(_pm([(42, 2, 80)])) == pytest.approx(1.0)
    assert va.drum_brightness(_pm([(36, 0, 80)])) == pytest.approx(0.0)
    assert va.drum_brightness(_pm([(42, 2, 60), (36, 0, 60)])) == pytest.approx(0.5)
    assert va.drum_brightness(_pm([(42, 2, 90), (36, 0, 30)])) == pytest.approx(0.75)   # velocity-weighted
    assert va.drum_brightness(_pm([(81, 2, 80)])) == pytest.approx(0.5)                   # unknown voice
    # a hat re-voiced as snare lowers it, a closed -> open hat does not
    assert va.BRIGHTNESS[38] < va.BRIGHTNESS[42] == va.BRIGHTNESS[46]


def test_brightness_classes_cover_every_live_voice(live_voices):
    assert live_voices <= set(va.BRIGHTNESS)


@pytest.fixture(scope='module')
def live_voices():
    return {n.pitch for g, t in _live_cells() for n in _drums(_live_base(g, t))}


# ----------------------------------------------------------------------------
# Op invariants on a synthetic bar
# ----------------------------------------------------------------------------


def test_exchange_keeps_grid_voices_and_velocities():
    _, bars, ctx = _setup()
    cands = va._candidates('cheap', bars[0], range(va.STEPS), ctx)
    exchanges = [c for c in cands if c[0] == 'exchange']
    assert exchanges
    before_notes, before_grid = _bar_state(bars[0])
    for kind, desc, do, undo, changed in exchanges:
        do()
        notes, grid = _bar_state(bars[0])
        assert grid == before_grid                                         # onset slots unchanged
        assert Counter(p for p, _, _ in notes) == Counter(p for p, _, _ in before_notes)
        # each note keeps its velocity: the (pitch, velocity) multiset is unchanged
        assert Counter((p, v) for p, _, v in notes) == Counter((p, v) for p, _, v in before_notes)
        assert all(h.note.pitch not in va.KICK for h in changed)
        assert changed[0].pos != changed[1].pos
        undo()
        assert _bar_state(bars[0]) == (before_notes, before_grid)


def test_family_swaps_stay_in_family_and_base_voices():
    _, bars, ctx = _setup()
    fam = [c for c in va._candidates('cheap', bars[0], range(va.STEPS), ctx) if c[0] == 'family']
    assert fam
    for kind, desc, do, undo, (h,) in fam:
        old = h.note.pitch
        do()
        assert h.note.pitch != old and va.FAMILY[h.note.pitch] == va.FAMILY[old]
        assert h.note.pitch in ctx.voices
        undo()


def test_cross_never_targets_kick_clave_or_crash():
    # base plays kick, clave, crash, snare, rim: cross must pick the rim (brightest non-hat)
    hits = _BAR + [(75, 3, 70), (49, 0, 90), (37, 5, 50)]
    _, bars, ctx = _setup(hits)
    cross = va._candidates('cross', bars[0], range(va.STEPS), ctx)
    assert cross
    for kind, desc, do, undo, (h,) in cross:
        do()
        assert h.note.pitch == 37
        undo()
    assert set(va.CROSS_TARGETS).isdisjoint(va.KICK + (va.CLAVE, va.CRASH))


def test_protected_notes_never_offered():
    _, bars, ctx = _setup()
    for tier in ('cheap', 'move', 'cross'):
        for c in va._candidates(tier, bars[0], range(va.STEPS), ctx):
            assert not any(h.protected for h in c[4])


def test_cross_cap_and_brightness_budget():
    _, bars, ctx = _setup()
    assert ctx.accept('exchange', True)
    ctx.n['cross'] = va.MAX_CROSS
    assert not ctx.accept('cross', True)          # cap reached: optional cross refused
    assert ctx.accept('cross', False)             # a required phrase-end op may exceed it
    ctx.n['cross'] = 0
    darken = [h for h in bars[0] + bars[1] + bars[2] if h.note.pitch == 42]
    for h in darken:
        h.note.pitch = 38
    assert va.drum_brightness(ctx.pm) < ctx.base_bright - va.BRIGHT_DROP
    assert not ctx.accept('cross', True) and not ctx.accept('family', True)
    assert ctx.accept('cross', False)


def test_move_cap_and_feature_budget():
    _, bars, ctx = _setup()
    ctx.n['move'] = ctx.max_moves
    assert not ctx.accept('move', True)
    ctx.n['move'] = 0
    assert ctx.accept('move', True)               # unmodified segment is within budget
    # relax widens the move budget up to the full guard bounds, never beyond
    assert va._Ctx(ctx.pm, ctx.step, ctx.voices, 1).budget_frac == pytest.approx(2 * va.BUDGET_FRAC)
    assert va._Ctx(ctx.pm, ctx.step, ctx.voices, 5).budget_frac == 1.0


# ----------------------------------------------------------------------------
# vary() on live cells
# ----------------------------------------------------------------------------


@pytest.fixture(scope='module')
def live_bases():
    return {(g, t): _live_base(g, t) for g, t in _live_cells()}


def _op_order(info):
    """Ops in the order vary() applied them: phrase ends, other varied bars, extra fill ops."""
    ops = info['drum_ops']
    req = [ops[b][0] for b in reversed(va.PHRASE_ENDS) if ops[b]]
    opt = [o for b, r in enumerate(info['bar_roles']) if r != 'A' and b not in va.PHRASE_ENDS for o in ops[b]]
    return req, opt + ops[va.PHRASE_ENDS[-1]][1:]


@pytest.mark.parametrize('relax', [0, 1, 2])
def test_vary_invariants_on_live_cells(live_bases, relax):
    for (genre, tier), base in live_bases.items():
        snapshot = copy.deepcopy(base)
        for seed in SEEDS:
            pm, info = va.vary(base, genre, seed, relax)
            b, v = _drums(base), _drums(pm)
            assert len(v) == len(b)
            assert Counter(n.velocity for n in v) == Counter(n.velocity for n in b)
            assert {n.pitch for n in v} <= {n.pitch for n in b}
            # no note becomes a kick: kick count per kick voice unchanged
            assert Counter(n.pitch for n in v if n.pitch in va.KICK) == \
                Counter(n.pitch for n in b if n.pitch in va.KICK), (genre, tier, seed)
            # optional ops respect the cross cap left after the required ones
            req, opt = _op_order(info)
            n_req_cross = sum(o.startswith('cross') for o in req)
            n_opt_cross = sum(o.startswith('cross') for o in opt)
            assert n_opt_cross <= max(0, va.MAX_CROSS + relax - n_req_cross), (genre, tier, seed, info)
            assert sum(o.startswith('move') for o in req + opt) <= va.MAX_MOVES + relax
            assert info['drum_ops'][7], (genre, tier, seed)          # bar 8 always varied
        assert sm.midi_sha256(base) == sm.midi_sha256(snapshot)       # base not modified


def test_cheap_ops_preferred_when_available(live_bases):
    """Where the base plays two voices of one timbre family, family swaps and
    exchanges cover the phrase ends and cross-family re-voicing is rare."""
    checked = 0
    for (genre, tier), base in live_bases.items():
        fams = Counter(va.FAMILY[p] for p in {n.pitch for n in _drums(base)} if p in va.FAMILY)
        if max(fams.values(), default=0) < 2:
            continue
        n = Counter()
        for seed in SEEDS:
            _, info = va.vary(base, genre, seed)
            n.update(info['op_counts'])
        assert n['cross'] <= 0.1 * len(SEEDS), (genre, tier, dict(n))
        checked += 1
    assert checked >= 10


# ----------------------------------------------------------------------------
# Session properties
# ----------------------------------------------------------------------------


def test_session_phrase_ends_and_repeat_window(live_bases):
    from composer.arrangement import REPEAT_WINDOW

    sc = SessionComposer(1)
    bad = []
    for genre, tier in live_bases:
        drum_shas, full_shas = [], []
        for v in range(VISITS):
            pm, info = sc.compose(genre, tier, v)
            m = sm.segment_metrics(pm, BARS)
            if info['gen_fallback'] or not (m['phrase_end_bar4_marked'] and m['phrase_end_bar8_marked']):
                bad.append((genre, tier, v, 'fallback/unmarked'))
            if m['drum_sha'] in drum_shas[-REPEAT_WINDOW:]:
                bad.append((genre, tier, v, 'drum repeat'))
            if m['content_sha'] in full_shas:
                bad.append((genre, tier, v, 'full repeat'))
            drum_shas.append(m['drum_sha'])
            full_shas.append(m['content_sha'])
    assert not bad, bad


def test_history_independent_of_call_order():
    a, b = SessionComposer(3), SessionComposer(3)
    for v in range(5):
        a.compose('calm', 1, v)
    pm_b, _ = b.compose('calm', 1, 4)                  # derives visits 0..3 itself
    assert sm.midi_sha256(a.compose('calm', 1, 4)[0]) == sm.midi_sha256(pm_b)
