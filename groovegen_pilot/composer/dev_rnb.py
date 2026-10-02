"""
R&B development policy (v2c.rnb.0) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.14).

Opt-in only (SessionComposer(develop=True)); not used by the live runner.

Material
--------
composer._gen_rnb (lofi is the same scaffold softened): per bar one EP chord
(program 4, held 0.95 bar; progressions are orders of F#min7, Dsus2, Emin7,
Cadd9, a 4-bar loop played twice), bass (program 33, seed-picked pattern), and
a 'keys' track (program 0): a beat-3 color dyad (velocity 65, 1.5 beats,
octave 5 or 6) and, at density >= 0.5 (rnb:3-5), int(d * 4) off-beat stabs
(0.4 beats, octave 5). Both dyads are root + 3rd (root + 2nd on sus2) in every
bar, so the keys repeat a 4-bar loop twice per segment, and in v2a.3 the keys
of a block's three visits are identical. The keys are read with
dev_lofi.read_context (same tracks, same EP stacking).

Source statistics (rnb:1-4, stim seeds 1/2/19, 12 visits; the lofi scaffold,
so the same distribution): top-voice leaps 0/2/3/5; 2-3 legal dyads per bar;
pitched p95 and median of every v2a.3 segment within 0.8-1.5 semitones of
its v1 envelope edge, low-register segments (color octave 5) at the floor,
high-register ones (octave 6) at the ceiling.

Rules (pitch-only, keys only)
-----------------------------
- every keys note keeps its onset, duration, velocity; the note count, EP,
  bass, drums, programs and tempo are untouched;
- a bar's dyad is two adjacent tones of the chord as the EP stacks it, a 2nd
  to a 4th apart: root+3rd, 3rd+5th, 5th+7th only where the EP plays a 7th
  (F#min7, Emin7); the color dyad and the bar's stabs take the same dyad, each
  in the octave nearest its own source register (dev_lofi.place);
- top voice (the color dyad's upper note): within FAR of the source in every
  bar, no bar above the source's highest, mean within MAX_MEAN_SHIFT of the
  source's either way, leaps between bars at most max(MAX_LEAP, the source's
  leap there; the source's largest is 5);
- a developed voicing never repeats its bars 1-4 in bars 5-8 (the source's
  4-bar loop);
- predicted keys level (composer/levels_rnb_color.py, levels_rnb_stab.py,
  measured with the note lengths rnb plays) within LEVEL_TOL_DB of the source;
- guard: the segment's pitched p95 and median never move outward, i.e. toward
  the envelope edge the source sits on (see above): with the color dyad in the
  lower octave p95 is not lowered, in the upper octave not raised; with the EP
  in the lower octave the median is not lowered, in the upper not raised.
  Inward moves (toward the other register's values) are allowed.

Development (visit v, block b = v // 3, pos = v % 3; two ops per developed visit)
--------------------------------------------------------------------------------
    pos 0         the block's source voicing (allowed to recur)
    pos 1         hook + answer: bars 1-4 re-voiced so the top voice follows a
                  3-step contour (up / down / same) other than the source's;
                  in odd blocks the previous block's hook contour (recall);
                  bars 5-8 answer it: the same contour with its last step
                  changed, realised with the same chords; candidate k takes
                  the k-th contour / realisation
    pos 2         ending (bar 8 re-voiced) + bar 4 or one bar of 1-7
History over HISTORY_WINDOW visits, developed voicings only: exact repeats,
near repeats (one bar off a visit other than the previous one), and phrase
endings (the bar-4 / bar-8 pair of a developed visit). Gentle pass: one bar
re-voiced. Fallbacks as the engine: the previous voicing with a new ending,
then the source voicing.
"""

from __future__ import annotations

import random
from functools import cache
from itertools import product
from statistics import mean
from typing import Optional

import pretty_midi

import stimulus_metrics as sm
from composer import develop_engine as de
from composer import levels_rnb_color, levels_rnb_stab
from composer.dev_lofi import LofiKeys, bar_options, place, read_context, realize, stab_voicing, _chains, _pcs
from composer.develop_engine import DevRecord
from composer.energy_guard import GuardResult

DEV_VERSION = 'v2c.rnb.0'
SEED_VERSION = 'v2c.rnb.0'
NO_CONTEXT = 'no_keys'
BLOCK_LEN = 3
BARS = 8
HALF = 4
HISTORY_WINDOW = 6                  # two blocks
N_CANDIDATES = 12
FAR = 5                             # semitones: top voice vs the source, per bar (largest legal move)
MAX_LEAP = 5                        # semitones: the source's largest top-voice leap
MAX_MEAN_SHIFT = 1.0                # semitones: top-voice mean vs the source, up or down
# Predicted keys level vs the source. Not the hiphop / lofi 0.2: rnb develops two bars or
# more per visit and rnb:1-2 keys are 8 colour dyads, so 0.2 rejected most hooks there
# (12/36 rnb:1 visits unchanged). Over 495 rendered rule-valid rnb:1-4 candidates the
# predicted level tracks the segment (r +0.79..+0.94 with dLUFS, -0.93..-0.97 with
# d low_ratio) but the effect is small: |dLUFS| <= 0.07, |d low_ratio| <= 0.009 up to
# 1.1 dB predicted (plan section 6.14). A candidate filter, not a certification
# tolerance: rendered developed segments moved <= 0.037 LU; envelopes unchanged.
LEVEL_TOL_DB = 0.5
# _gen_rnb picks the color dyad octave from {5, 6} and the EP octave from {3, 4}; the
# v2a.3 segments' pitched p95 sits on its v1 envelope floor with the lower color octave
# and on its ceiling with the upper one, the pitched median likewise with the EP octave.
UPPER_COLOR = 72                    # lowest color note in octave 6 (C)
UPPER_EP = 48                       # lowest EP note in octave 4 (C)
CONTOURS = tuple(product((-1, 0, 1), repeat=HALF - 1))

Dyad = tuple[int, int]
Voicing = tuple[Dyad, ...]

__all__ = ['DEV_VERSION', 'SEED_VERSION', 'NO_CONTEXT', 'read_context', 'develop', 'unchanged_record', 'POLICY']


def _tops(v: Voicing) -> list[int]:
    return [d[1] for d in v]


def contour(v: Voicing, start: int) -> tuple[int, ...]:
    """Up / down / same steps of the top voice within the half starting at bar `start`."""
    t = _tops(v)
    return tuple((t[b] > t[b - 1]) - (t[b] < t[b - 1]) for b in range(start + 1, start + HALF))


def max_leaps(c: LofiKeys) -> tuple[int, ...]:
    t = _tops(c.base)
    return tuple(max(MAX_LEAP, abs(b - a)) for a, b in zip(t, t[1:]))


def looped(v: Voicing) -> bool:
    return v[:HALF] == v[HALF:]


def valid(v: Voicing, c: LofiKeys) -> bool:
    if len(v) != BARS:
        return False
    for b, (d, s) in enumerate(zip(v, c.base)):
        if d != s and (_pcs(d) not in c.options[b] or d != place(_pcs(d), s)):
            return False
        if abs(d[1] - s[1]) > FAR:
            return False
    tops, base = _tops(v), _tops(c.base)
    if max(tops) > max(base) or abs(mean(tops) - mean(base)) > MAX_MEAN_SHIFT + 1e-9:
        return False
    return all(abs(b - a) <= m for a, b, m in zip(tops, tops[1:], max_leaps(c)))


def _valid_record(rec: DevRecord, c: LofiKeys) -> bool:
    return all(valid(p, c) for p in rec.plan) and (rec.role == 'base' or not looped(rec.motif))


# =============================================================================
# Operations
# =============================================================================


def op_bar(v: Voicing, c: LofiKeys, rng: random.Random, bars, tag: str) -> tuple[Voicing, str]:
    """One bar (drawn from `bars`) takes another of its legal dyads."""
    b = rng.choice(list(bars))
    opts = [d for d in bar_options(c, b) if d != v[b]]
    if not opts:
        return v, f'{tag}:none'
    d = rng.choice(opts)
    return v[:b] + (d,) + v[b + 1:], f'{tag}@{b + 1}:{d[0]}-{d[1]}'


def realisations(v: Voicing, c: LofiKeys, start: int, want: tuple[int, ...]) -> list[Voicing]:
    """The half at `start` re-voiced with its bars' dyads so the top voice follows
    `want` exactly (valid voicings only); least top motion from v first."""
    out = []
    for ch in _chains(c, range(start, start + HALF)):
        new = v[:start] + ch + v[start + HALF:]
        if contour(new, start) == want and new != v and valid(new, c):
            out.append((sum(abs(a[1] - b[1]) for a, b in zip(new, v)), new))
    return [new for _, new in sorted(out)]


def answer(v: Voicing, c: LofiKeys, hook: tuple[int, ...], rng: random.Random) -> tuple[Voicing, str]:
    """Bars 5-8 follow the hook contour with its last step changed (never bars 1-4 again)."""
    wants = [hook[:-1] + (s,) for s in (-1, 0, 1) if s != hook[-1]]
    rng.shuffle(wants)
    for want in wants:
        for new in realisations(v, c, HALF, want):
            if not looped(new) and valid(new, c):
                return new, 'answer@5-8:' + ''.join('+0-'[1 - s] for s in want)
    return v, 'answer:none'


def hook_contours(v: Voicing, c: LofiKeys, records: list[DevRecord], block: int) -> list[tuple[int, ...]]:
    """The contours other than the source's bars 1-4 contour that the bars' dyads can
    realise from v; in odd blocks the previous block's hook contour first (recall)."""
    src = contour(c.base, 0)
    out = [h for h in CONTOURS if h != src and realisations(v, c, 0, h)]
    if block % 2 and len(records) >= (block - 1) * BLOCK_LEN + 2:
        old = records[(block - 1) * BLOCK_LEN + 1].theme
        if old in out:
            out.remove(old)
            out.insert(0, old)
    return out


def _candidate(c: LofiKeys, records: list[DevRecord], visit: int, k: int, rng: random.Random,
               gentle: bool) -> DevRecord:
    block, pos = divmod(visit, BLOCK_LEN)
    if pos == 0:
        return DevRecord(motif=c.base, theme=contour(c.base, 0), plan=(c.base,), role='base', ops=())
    prev = records[visit - 1]
    if gentle:
        m, d = op_bar(prev.motif, c, rng, range(BARS), 'voice')
        return DevRecord(motif=m, theme=prev.theme, plan=(m,), role='develop', ops=(d,))
    if pos == 2:
        m, d1 = op_bar(prev.motif, c, rng, (BARS - 1,), 'ending')
        if rng.random() < 0.5:
            m, d2 = op_bar(m, c, rng, (HALF - 1,), 'bar4')
        else:
            m, d2 = op_bar(m, c, rng, range(BARS - 1), 'voice')
        return DevRecord(motif=m, theme=prev.theme, plan=(m,), role='develop', ops=(d1, d2))
    # pos 1: hook on bars 1-4 + answer on bars 5-8
    hooks = hook_contours(prev.motif, c, records, block)
    recall = block % 2 == 1 and k < N_CANDIDATES // 2 and hooks and hooks[0] == records[(block - 1) * BLOCK_LEN + 1].theme
    hook = hooks[0] if recall else rng.choice(hooks)
    real = realisations(prev.motif, c, 0, hook) if hooks else []
    if not real:
        m, d = op_bar(prev.motif, c, rng, range(HALF), 'voice')
        return DevRecord(motif=m, theme=prev.theme, plan=(m,), role='develop', ops=(d, 'hook:none'))
    m = real[(k if recall else rng.randrange(len(real))) % len(real)]
    tag = ('recall' if recall else 'hook') + '@1-4:' + ''.join('+0-'[1 - s] for s in hook)
    m, d2 = answer(m, c, hook, rng)
    return DevRecord(motif=m, theme=hook, plan=(m,), role='recall' if recall else 'develop', ops=(tag, d2))


def hamming(a: Voicing, b: Voicing) -> int:
    return sum(x != y for x, y in zip(a, b))


def repeats(rec: DevRecord, recent: list[DevRecord], c: LofiKeys) -> Optional[str]:
    """Developed voicings only: exact, near (one bar off a visit before the previous)
    and phrase-ending (bar 4 / bar 8 pair of a developed visit) history."""
    if rec.role == 'base':
        return None
    v = rec.motif
    if v in {r.motif for r in recent}:
        return 'history'
    if any(hamming(v, r.motif) <= 1 for r in recent[:-1]):
        return 'near'
    if (v[HALF - 1], v[BARS - 1]) in {(r.motif[HALF - 1], r.motif[BARS - 1]) for r in recent if r.role != 'base'}:
        return 'ending'
    return None


# =============================================================================
# Level, guard
# =============================================================================


@cache
def color_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_rnb_color.LEVEL_DB, levels_rnb_color.VELOCITIES, pitch, velocity)


@cache
def stab_level(pitch: int, velocity: int) -> float:
    return de.table_level(levels_rnb_stab.LEVEL_DB, levels_rnb_stab.VELOCITIES, pitch, velocity)


def keys_level(v: Voicing, c: LofiKeys) -> float:
    vel = c.velocities
    total = sum(color_level(p, vel[j]) for d, idx in zip(v, c.color) for p, j in zip(d, idx))
    for sv, si in zip(stab_voicing(v, c), c.stabs):
        total += sum(stab_level(p, vel[j]) for d, idx in zip(sv, si) for p, j in zip(d, idx))
    return total


def energy_shift(plan: tuple[Voicing, ...], aux, c: LofiKeys) -> dict:
    """Predicted keys level change (dB) and top-voice mean / top change vs the source."""
    v = plan[0]
    tops, base = _tops(v), _tops(c.base)
    return {'level_db': de.db(keys_level(v, c), keys_level(c.base, c)),
            'mean_shift': round(mean(tops) - mean(base), 4), 'top_rise': max(tops) - max(base)}


def energy_cost(shift: dict) -> float:
    return round(max(abs(shift['level_db']) / LEVEL_TOL_DB, abs(shift['mean_shift']) / MAX_MEAN_SHIFT), 6)


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: LofiKeys) -> GuardResult:
    """Only keys pitches may change; every keys note a tone of its bar's EP chord; no
    keys note above the source's highest; pitched p95 and median not moved outward."""
    ep_low = min(n.pitch for i in c.harmony for n in src.instruments[i].notes)
    outward = {'pitched_pitch_p95': 1 if min(d[0] for d in c.base) >= UPPER_COLOR else -1,
               'pitched_pitch_median': 1 if ep_low >= UPPER_EP else -1}

    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.keys].notes
        bad = any(notes[j].pitch % 12 not in ch.pcs
                  for ch, ci, si in zip(c.chords, c.color, c.stabs) for j in ci + tuple(x for d in si for x in d))
        top = max(notes[ci[1]].pitch for ci in c.color) > max(d[1] for d in c.base)
        a, b = sm.bounded_features(pm, BARS), sm.bounded_features(src, BARS)
        moved = [f'{f}_outward' for f, sign in outward.items() if sign * (a[f] - b[f]) > 1e-9]
        return (['off_chord'] if bad else []) + (['register'] if top else []) + moved

    return de.guard(developed, src, {c.keys: None}, check, de.MAX_PITCH_SHIFT, BARS)


def _previous(prev: DevRecord, rng: random.Random, c: LofiKeys) -> DevRecord:
    """The previous voicing with a new ending (the source's at a block start: new chords)."""
    v = prev.motif if valid(prev.motif, c) else c.base
    for _ in range(8):
        e, d = op_bar(v, c, rng, (BARS - 1,), 'ending')
        if e != v and valid(e, c) and not looped(e):
            return DevRecord(motif=e, theme=prev.theme, plan=(e,), role='fallback', ops=(d,))
    return DevRecord(motif=v, theme=prev.theme, plan=(v,), role='fallback', ops=('ending:none',))


def unchanged_record(c: LofiKeys, records: list[DevRecord]) -> DevRecord:
    """The unchanged segment plays the source voicing; the block hook carries on."""
    theme = records[-1].theme if records and len(records) % BLOCK_LEN else contour(c.base, 0)
    return DevRecord(c.base, theme, (c.base,), 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=_candidate, valid=_valid_record,
    energy=energy_shift, cost=energy_cost, realize=realize, guard=guard,
    previous=_previous, unchanged=unchanged_record, repeats=repeats)


def develop(src: pretty_midi.PrettyMIDI, c: LofiKeys, records: list[DevRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    return de.select(POLICY, src, c, records, visit, seed)
