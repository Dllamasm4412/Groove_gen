"""
Motif development for the v2b generator (LIVE_GENERATION_PLAN.md section 6.12):
the hiphop policy of the shared development engine (composer/develop_engine.py).

Opt-in only (SessionComposer(develop=True)). Not used by the live runner, and
v1 and the v2a.3 drum layer are unchanged: development runs after drum
selection and touches only the hook notes. The candidate loop, ranking,
history window and fallback chain are develop_engine.select(); this module
supplies the hook rules, ops, level check and guard specifics.

Hook
----
The frozen hiphop cell (composer/hiphop_cell.py) plays one 2-bar right-hand
piano ostinato four times per segment over a tonic-minor pedal (LH octave
stabs and bass on beats 1 and 3), doubled one octave up by the lead track
(tiers 2+). read_hook() reads it back from the MIDI as a Motif: a tuple of
(16th slot in the 2-bar phrase, diatonic step from the RH tonic) in natural
minor. realize() writes a 4-phrase plan back onto the same notes: the i-th
hook note of a phrase takes the i-th motif note, so note count, velocity,
duration and track are unchanged (count- and velocity-neutral by
construction); the lead keeps doubling it with the cell's own fold rule.

Rules (every motif played)
--------------------------
- phrase anchor (slot 0, the tonic downbeat) never changes;
- notes on beats 1 and 3 (slots 0, 8, 16, 24: under the LH stab and bass)
  are chord tones of the pedal, i7 = steps 0, 2, 4, 6;
- steps stay within the base hook's step range +-1 and the cell's RH fold
  range 72..96 (register);
- leaps, including last note -> next phrase's anchor, stay within the base
  hook's largest leap;
- with a lead (tiers 2+), the phrase keeps the base hook's number of notes
  <= FOLD: the lead doubles those an octave up and higher ones in unison, so
  moving notes across FOLD changes the timbre (certification: low_ratio and
  centroid tracked the octave-doubled count, r = -0.82 at hiphop:3);
- onsets are the base hook's: development is pitch-only. v2b.0 drafts also
  moved off-beat 16ths (displacement, anticipated endings); at hiphop:5 every
  visit carrying a displaced onset left the pulse_clarity envelope and every
  pitch-only visit stayed inside it (audio certification, stim seeds 1-2);
- the predicted hook level (RH + lead, from the soundfont's per-pitch table in
  composer/hook_levels.py) stays within LEVEL_TOL_DB of the base hook, in
  total and on / off the beat, and leap motion into off-beat (on-beat) notes
  grows by at most MAX_OFFBEAT_MOTION (MAX_ONBEAT_MOTION) semitones over the
  plan (energy_shift()). The piano's sample zones step by up to ~7 dB
  between adjacent semitones, so a pitch-only change can move LUFS and
  low_ratio; the predicted level tracks them (r = -0.99 low_ratio, 0.92-0.97
  LUFS), register does not. v2b.0 drafts without it: 3 of 48 certified
  segments left the LUFS / low_ratio envelope. Added off-beat motion lowers
  pulse_clarity (hiphop:5, where v2a.3 segments sit at the envelope edge);
  capping it alone moved motion onto the beat, and added on-beat motion
  raises flux at hiphop:3 (pooled v2b runs: 1.2e-4 per semitone, R^2 0.4).

Development (per cell, visit v, block b = v // BLOCK_LEN, pos = v % BLOCK_LEN)
------------------------------------------------------------------------------
    v = 0             theme A = the base hook
    pos 0, b odd      theme = derive(previous theme): new answer bar built
                      from the call bar (sequence or inversion), same rhythm
    pos 0, b even     theme = two ops on the theme two blocks back (return)
    pos 1             one pitch op on the previous visit's motif (A')
    pos 2             one ending / neighbor op on the previous visit's motif (A'')
Phrases in the segment: [M, M, R, E]. R recalls the previous theme's call
bar under M's answer bar at pos 1 of blocks >= 1 (else R = M); E is M with a
varied phrase ending (turnaround, under the bar-8 drum fill).
A motif or a whole plan equal to one of the last HISTORY_WINDOW visits of
the cell is rejected, so the hook cannot cycle within that window; recall is
partial (one bar), so recognition does not need exact repeats. A return is
a transformed recall (two ops on the old theme, one in the gentle pass), never
the old theme verbatim. Of N_CANDIDATES deterministic candidates, those that
pass the rules and the history check go to the energy check; one failing only
that gets up to two balancing scale-step moves (_balance). The passing
candidates are ranked unrepaired first, then by energy cost, then candidate
order; the first that passes guard() is used. If none does, gentle
candidates (less aggressive), then the previous motif with a new ending, then
the unchanged segment are used (motif_fallback; motif_selection says which).
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from functools import cache
from typing import Optional

import pretty_midi

from composer import develop_engine as de
from composer.develop_engine import DevRecord as MotifRecord  # noqa: F401 - the motif record (motif = M)
from composer.energy_guard import GuardResult
from composer.hook_levels import LEVEL_DB, VELOCITIES

DEV_VERSION = 'v2b.1'                # v2b.1: level / motion check in selection (plan 6.12a)
SEED_VERSION = 'v2b.0'               # motif seeds keep the v2b.0 salt: v2b.1 changes selection, not the draws
NO_CONTEXT = 'no_hook'               # motif_error when the segment is not a 4x loop of one phrase
BLOCK_LEN = 3
BARS = 8
NATURAL_MINOR = (0, 2, 3, 5, 7, 8, 10)
CHORD_STEPS = (0, 2, 4, 6)          # i7 over the tonic-minor pedal
PHRASE = 32                         # 16ths in a 2-bar phrase
STRONG = 8                          # slots 0, 8, 16, 24: LH stab + bass
RH_SPLIT = 70                       # the cell folds the RH to 72..96 and the LH stabs to <= 67
RH_RANGE = (72, 96)
LEAD_MAX = 96
FOLD = LEAD_MAX - 12                # RH <= 84: octave-up lead double; above: unison double
HISTORY_WINDOW = 6
N_CANDIDATES = 12
MAX_PITCH_SHIFT = de.MAX_PITCH_SHIFT  # semitones: pitched median / p05 / p95 vs the source segment
LEVEL_TOL_DB = 0.2                  # predicted hook level vs the source segment: total, on-beat, off-beat
MAX_OFFBEAT_MOTION = 4              # semitones: added leap motion into off-beat hook notes, whole plan
MAX_ONBEAT_MOTION = 4               # semitones: the same into on-beat hook notes

Motif = tuple[tuple[int, int], ...]
PITCH_OPS = ('neighbor', 'chord', 'sequence')
CADENCE_OPS = ('ending', 'neighbor')


@dataclass(frozen=True)
class Hook:
    tonic: int                  # MIDI pitch of step 0 (lowest RH tonic >= 72)
    piano: int                  # instrument index of the RH + LH piano
    lead: Optional[int]         # unison-double track (None at tier 1)
    sixteenth: float            # seconds
    motif: Motif                # the base phrase (all phrases are equal)
    lo: int                     # step range
    hi: int
    max_leap: int               # steps


def step_of(pitch: int, tonic: int) -> Optional[int]:
    o, r = divmod(pitch - tonic, 12)
    return 7 * o + NATURAL_MINOR.index(r) if r in NATURAL_MINOR else None


def pitch_of(step: int, tonic: int) -> int:
    o, i = divmod(step, 7)
    return tonic + 12 * o + NATURAL_MINOR[i]


def lead_pitch(p: int) -> int:
    """The cell's lead doubling: one octave up, folded down to <= 96."""
    d = p + 12
    while d > LEAD_MAX:
        d -= 12
    return d


def rh_tonic(key_root: str) -> int:
    """RH tonic of a hiphop key (notated as relative major): lowest pitch >= 72."""
    minor_pc = (pretty_midi.note_name_to_number(f'{key_root}3') - 3) % 12
    return RH_RANGE[0] + (minor_pc - RH_RANGE[0]) % 12


def _hook_tracks(pm: pretty_midi.PrettyMIDI) -> tuple[Optional[int], Optional[int]]:
    piano = lead = None
    for i, inst in enumerate(pm.instruments):
        if inst.is_drum or inst.program != 0 or not inst.notes:
            continue
        ps = [n.pitch for n in inst.notes]
        if min(ps) < RH_SPLIT <= max(ps):
            piano = i
        elif min(ps) >= RH_SPLIT:
            lead = i
    return piano, lead


def _rh_notes(pm: pretty_midi.PrettyMIDI, piano: int) -> list:
    return sorted((n for n in pm.instruments[piano].notes if n.pitch >= RH_SPLIT), key=lambda n: (n.start, n.pitch))


def read_hook(pm: pretty_midi.PrettyMIDI, key_root: str, tempo: float) -> Optional[Hook]:
    """The base hook, or None if the segment is not a 4x loop of one diatonic phrase."""
    piano, lead = _hook_tracks(pm)
    if piano is None:
        return None
    six = 60.0 / tempo / 4
    tonic = rh_tonic(key_root)
    phrases: dict[int, list] = {}
    for n in _rh_notes(pm, piano):
        slot, st = int(round(n.start / six)), step_of(n.pitch, tonic)
        if st is None:
            return None
        phrases.setdefault(slot // PHRASE, []).append((slot % PHRASE, st))
    if sorted(phrases) != list(range(BARS // 2)):
        return None
    motif = tuple(phrases[0])
    if any(tuple(p) != motif for p in phrases.values()) or len({s for s, _ in motif}) != len(motif):
        return None
    steps = [st for _, st in motif]
    return Hook(tonic=tonic, piano=piano, lead=lead, sixteenth=six, motif=motif,
                lo=min(steps) - 1, hi=max(steps) + 1, max_leap=max(_leaps(motif), default=0))


def _leaps(m: Motif) -> list[int]:
    """Step leaps inside the phrase and from its last note to the next anchor."""
    seq = [st for _, st in m] + [m[0][1]]
    return [abs(b - a) for a, b in zip(seq, seq[1:])]


def octave_doubled(m: Motif, hook: Hook) -> int:
    return sum(pitch_of(st, hook.tonic) <= FOLD for _, st in m)


def valid(m: Motif, hook: Hook) -> bool:
    slots = [s for s, _ in m]
    if len(m) != len(hook.motif) or m[0] != hook.motif[0]:
        return False
    if slots != [s for s, _ in hook.motif]:
        return False
    for s, st in m:
        if not hook.lo <= st <= hook.hi or not RH_RANGE[0] <= pitch_of(st, hook.tonic) <= RH_RANGE[1]:
            return False
        if s % STRONG == 0 and st % 7 not in CHORD_STEPS:
            return False
    if hook.lead is not None and octave_doubled(m, hook) != octave_doubled(hook.motif, hook):
        return False
    return max(_leaps(m)) <= hook.max_leap


# =============================================================================
# Operations (count-neutral; validity is checked on the result)
# =============================================================================


def _put(m: Motif, i: int, slot: int, st: int) -> Motif:
    return m[:i] + ((slot, st),) + m[i + 1:]


def op_neighbor(m: Motif, rng: random.Random) -> tuple[Motif, str]:
    """A weak-slot note moves one scale step."""
    i = rng.choice([i for i, (s, _) in enumerate(m) if s % STRONG])
    d = rng.choice((-1, 1))
    return _put(m, i, m[i][0], m[i][1] + d), f'neighbor@{m[i][0]}:{d:+d}'


def _chord_near(st: int, rng: random.Random) -> int:
    return st + rng.choice([d for d in (-2, -1, 1, 2) if (st + d) % 7 in CHORD_STEPS])


def op_chord(m: Motif, rng: random.Random) -> tuple[Motif, str]:
    """A non-anchor note moves to another nearby chord tone."""
    i = rng.randrange(1, len(m))
    new = _chord_near(m[i][1], rng)
    return _put(m, i, m[i][0], new), f'chord@{m[i][0]}:{new - m[i][1]:+d}'


def op_sequence(m: Motif, rng: random.Random) -> tuple[Motif, str]:
    """The notes of one half-bar (2 beats, anchor excluded) move together by a step or two."""
    w = rng.randrange(PHRASE // 8)
    d = rng.choice((-2, -1, 1, 2))
    idx = [i for i, (s, _) in enumerate(m) if i and s // 8 == w]
    if not idx:
        return m, 'sequence:empty'
    out = m
    for i in idx:
        out = _put(out, i, out[i][0], out[i][1] + d)
    return out, f'sequence@{w * 8}:{d:+d}'


def op_ending(m: Motif, rng: random.Random) -> tuple[Motif, str]:
    """One of the last two notes (beat 4 of the answer bar) moves to a nearby chord tone."""
    i = len(m) - rng.choice((1, 2))
    s = m[i][0]
    new = _chord_near(m[i][1], rng)
    return _put(m, i, s, new), f'ending@{s}:{new - m[i][1]:+d}'


OPS = {'neighbor': op_neighbor, 'chord': op_chord, 'sequence': op_sequence, 'ending': op_ending}


def _answer(call: list, kind: str, at: int) -> list:
    """Answer bar built from the call bar with the call's rhythm: 'sequence' starts
    it on step `at`, 'inversion' mirrors its contour downward from `at`; beat-1/3
    notes snap up to the next chord tone (steps 1, 3, 5 -> 2, 4, 6)."""
    c0 = call[0][1]
    ans = [(s + PHRASE // 2, at + st - c0 if kind == 'sequence' else at - (st - c0)) for s, st in call]
    return [(s, st if s % STRONG or st % 7 in CHORD_STEPS else st + 1) for s, st in ans]


def derive(theme: Motif, rng: random.Random, hook: Hook) -> tuple[Motif, str]:
    """A new related phrase: the call bar is kept and the answer bar is rebuilt from
    it (sequence or inversion starting on a chord tone). Every (kind, start) whose
    phrase is valid is a choice; with none, the theme is returned unchanged."""
    call = [x for x in theme if x[0] < PHRASE // 2]
    if len(call) != len(theme) - len(call):
        return theme, 'derive:count'
    options = []
    for kind in ('sequence', 'inversion'):
        for at in range(hook.lo, hook.hi + 1):
            m = tuple(call + _answer(call, kind, at))
            if at % 7 in CHORD_STEPS and m != theme and valid(m, hook):
                options.append((m, f'derive_{kind}@{at}'))
    return rng.choice(options) if options else (theme, 'derive:none')


# =============================================================================
# Realization and guard
# =============================================================================


def realize(pm: pretty_midi.PrettyMIDI, hook: Hook, plan: tuple[Motif, ...]) -> pretty_midi.PrettyMIDI:
    """Copy of pm with phrase k of the hook (and its lead double) playing plan[k]."""
    out = copy.deepcopy(pm)
    six = hook.sixteenth
    lead = {}
    if hook.lead is not None:
        lead = {(int(round(n.start / six)), n.pitch): n for n in out.instruments[hook.lead].notes}
    by_phrase: dict[int, list] = {}
    for n in _rh_notes(out, hook.piano):
        by_phrase.setdefault(int(round(n.start / six)) // PHRASE, []).append(n)
    for k, notes in sorted(by_phrase.items()):
        for n, (slot, st) in zip(notes, plan[k]):
            old = int(round(n.start / six))
            shift = (k * PHRASE + slot - old) * six
            new_pitch = pitch_of(st, hook.tonic)
            ln = lead.get((old, lead_pitch(n.pitch)))
            n.start, n.end, n.pitch = n.start + shift, n.end + shift, new_pitch
            if ln is not None:
                ln.start, ln.end, ln.pitch = ln.start + shift, ln.end + shift, lead_pitch(new_pitch)
    for i in (hook.piano, hook.lead):
        if i is not None:
            out.instruments[i].notes.sort(key=lambda n: (n.start, n.pitch))
    return out


_track_shape, _notes = de.track_shape, de.track_notes


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, hook: Hook) -> GuardResult:
    """Development may move only hook notes (RH + lead), within key and register,
    keeping every track's note count, velocities and durations."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        fails = []
        hook_p = [n.pitch for i in (hook.piano, hook.lead) if i is not None
                  for n in pm.instruments[i].notes if n.pitch >= RH_SPLIT]
        if any(step_of(p, hook.tonic) is None for p in hook_p):
            fails.append('off_key')
        if hook_p and not (RH_RANGE[0] <= min(hook_p) and max(hook_p) <= RH_RANGE[1]):
            fails.append('register')
        return fails

    mutable = {hook.piano: (lambda p: p < RH_SPLIT, 'lh_changed')}
    if hook.lead is not None:
        mutable[hook.lead] = None
    return de.guard(developed, src, mutable, check, MAX_PITCH_SHIFT, BARS)


@cache
def note_level(pitch: int, velocity: int) -> float:
    """Rendered energy of one hook note (linear), from the soundfont table:
    dB interpolated between the measured velocities, pitch clamped to the table."""
    return de.table_level(LEVEL_DB, VELOCITIES, pitch, velocity)


def hook_voices(src: pretty_midi.PrettyMIDI, hook: Hook) -> dict[tuple[int, int], tuple[int, Optional[int]]]:
    """(RH velocity, lead velocity or None) of every hook note, keyed by (phrase, slot)."""
    six, lead = hook.sixteenth, {}
    if hook.lead is not None:
        lead = {(int(round(n.start / six)), n.pitch): n.velocity for n in src.instruments[hook.lead].notes}
    voices = {}
    for n in _rh_notes(src, hook.piano):
        slot = int(round(n.start / six))
        voices[divmod(slot, PHRASE)] = (n.velocity, lead.get((slot, lead_pitch(n.pitch))))
    return voices


def plan_level(plan: tuple[Motif, ...], voices: dict, hook: Hook) -> tuple[float, float]:
    """(on-beat, off-beat) energy of the hook, RH + lead, playing plan (pitch-only,
    so every note keeps its source velocity and onset)."""
    on = off = 0.0
    for k, m in enumerate(plan):
        for slot, st in m:
            v, lv = voices[(k, slot)]
            p = pitch_of(st, hook.tonic)
            e = note_level(p, v) + (note_level(lead_pitch(p), lv) if lv is not None else 0.0)
            if slot % 4 == 0:
                on += e
            else:
                off += e
    return on, off


def offbeat_motion(plan: tuple[Motif, ...], hook: Hook, onbeat: bool = False) -> int:
    """Summed |interval| (semitones) into the off-beat (onbeat: on-beat) hook notes of the plan."""
    seq = [(slot, pitch_of(st, hook.tonic)) for m in plan for slot, st in m]
    return sum(abs(b - a) for (_, a), (slot, b) in zip(seq, seq[1:]) if bool(slot % 4) != onbeat)


def energy_shift(plan: tuple[Motif, ...], voices: dict, hook: Hook) -> dict:
    """Predicted audio-energy change of plan vs the base hook (pitch-only plans).

    level_*: hook level change in dB, total / on-beat / off-beat. The piano's
    sample zones step by up to ~7 dB between adjacent semitones, so this, not
    the register, predicts the segment's LUFS and low_ratio shift
    (certification hiphop:1/3/5: r = 0.92-0.97 and -0.99).
    offbeat_motion: added leap motion into off-beat notes. More spectral
    novelty off the beat lowers pulse_clarity (hiphop:5 sessions r = -0.99;
    single-note ablations: moves that reduce it raise pulse_clarity).
    onbeat_motion: the same into on-beat notes; it tracks flux at hiphop:3."""
    (on, off), (on0, off0) = plan_level(plan, voices, hook), plan_level((hook.motif,) * 4, voices, hook)
    db = de.db
    return {'level_db': db(on + off, on0 + off0), 'level_on_db': db(on, on0), 'level_off_db': db(off, off0),
            'offbeat_motion': offbeat_motion(plan, hook) - offbeat_motion((hook.motif,) * 4, hook),
            'onbeat_motion': offbeat_motion(plan, hook, True) - offbeat_motion((hook.motif,) * 4, hook, True)}


def energy_cost(shift: dict) -> float:
    """<= 1 passes: the largest level change over LEVEL_TOL_DB, or added
    off- / on-beat motion over MAX_OFFBEAT_MOTION / MAX_ONBEAT_MOTION (less
    motion is free)."""
    level = max(abs(shift[k]) for k in ('level_db', 'level_on_db', 'level_off_db'))
    return round(max(level / LEVEL_TOL_DB, max(shift['offbeat_motion'], 0) / MAX_OFFBEAT_MOTION,
                     max(shift.get('onbeat_motion', 0), 0) / MAX_ONBEAT_MOTION), 6)


# =============================================================================
# Development
# =============================================================================


def _with_ending(m: Motif, rng: random.Random, hook: Hook) -> tuple[Motif, str]:
    for _ in range(8):
        e, desc = op_ending(m, rng)
        if e != m and valid(e, hook):
            return e, desc
    return m, 'ending:none'


def _recall(theme: Motif, m: Motif, hook: Hook) -> Optional[Motif]:
    """The theme's call bar under m's answer bar (None if the counts or rules do not allow it)."""
    call = tuple(x for x in theme if x[0] < PHRASE // 2)
    ans = tuple(x for x in m if x[0] >= PHRASE // 2)
    r = call + ans
    return r if r != m and valid(r, hook) else None


def _candidate(hook: Hook, records: list[MotifRecord], visit: int, rng: random.Random,
               gentle: bool = False) -> MotifRecord:
    """gentle: the less aggressive variant tried when no regular candidate passes
    (a return applies one op instead of two; no separate turnaround)."""
    block, pos = divmod(visit, BLOCK_LEN)
    ops: list[str] = []
    if visit == 0:
        role, m = 'base', hook.motif
    elif pos == 0 and block % 2:
        role = 'derive'
        m, d = derive(records[(block - 1) * BLOCK_LEN].theme, rng, hook)
        ops.append(d)
    elif pos == 0:
        role, m = 'return', records[(block - 2) * BLOCK_LEN].theme
        for kind in rng.sample(PITCH_OPS, 1 if gentle else 2):
            m, d = OPS[kind](m, rng)
            ops.append(d)
    else:
        role, m = 'develop', records[visit - 1].motif
        m, d = OPS[rng.choice(PITCH_OPS if pos == 1 else CADENCE_OPS)](m, rng)
        ops.append(d)
    theme = m if pos == 0 else records[visit - 1].theme
    recall = _recall(records[(block - 1) * BLOCK_LEN].theme, m, hook) if pos == 1 and block >= 1 else None
    end = m
    if not gentle:
        end, d = _with_ending(m, rng, hook)
        ops.append(d)
    return MotifRecord(motif=m, theme=theme, plan=(m, m, recall or m, end), role=role, ops=tuple(ops))


def _balance(rec: MotifRecord, hook: Hook, voices: dict, why_not, moves: int = 2) -> Optional[MotifRecord]:
    """Repair for a candidate that fails only the energy check: up to `moves`
    greedy scale-step moves (+-1, +-2) of one non-anchor motif note each,
    applied in every phrase that plays that note, bringing energy_cost to <= 1.
    Each move takes the lowest energy cost, ties to the smaller move and earlier
    note; why_not(rec) re-checks the rules and the history window."""
    m, best = rec.motif, None
    for i in range(1, len(m)):
        slot, st = m[i]
        for d in (1, -1, 2, -2):
            note = (slot, st + d)
            plan = tuple(p[:i] + (note,) + p[i + 1:] if p[i] == m[i] else p for p in rec.plan)
            new = MotifRecord(motif=plan[0], theme=plan[0] if rec.theme == m else rec.theme, plan=plan,
                              role=rec.role, ops=rec.ops + (f'balance@{slot}:{d:+d}',))
            cost = energy_cost(energy_shift(plan, voices, hook))
            if (best is None or cost < best[0]) and why_not(new) is None:
                best = (cost, new)
    if best is None:
        return None
    if best[0] <= 1:
        return best[1]
    return _balance(best[1], hook, voices, why_not, moves - 1) if moves > 1 else None


def _previous(prev: MotifRecord, rng: random.Random, hook: Hook) -> MotifRecord:
    """Fallback: the previous motif with a new ending."""
    end, d = _with_ending(prev.motif, rng, hook)
    return MotifRecord(motif=prev.motif, theme=prev.theme, plan=(prev.motif,) * 3 + (end,),
                       role='fallback', ops=(d,))


def unchanged_record(hook: Hook, records: list[MotifRecord]) -> MotifRecord:
    """Record of a visit that plays the unchanged hook (fallback or error): the
    motif memory carries on from the previous visit."""
    prev = records[-1] if records else MotifRecord(hook.motif, hook.motif, (), '', ())
    return MotifRecord(prev.motif, prev.theme, (hook.motif,) * 4, 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=lambda hook, records, visit, k, rng, gentle: _candidate(hook, records, visit, rng, gentle),
    valid=lambda rec, hook: all(valid(p, hook) for p in rec.plan),
    energy=lambda plan, voices, hook: energy_shift(plan, voices, hook),
    cost=energy_cost, realize=lambda src, hook, plan: realize(src, hook, plan), guard=guard,
    previous=_previous, unchanged=unchanged_record, prepare=hook_voices,
    repair=lambda rec, hook, voices, why_not: _balance(rec, hook, voices, why_not), repair_op='balance')


def read_context(src: pretty_midi.PrettyMIDI, sched, tempo: float) -> Optional[Hook]:
    """Policy entry point: the hook of src (None if it is not a 4x loop)."""
    return read_hook(src, sched.session_key, tempo)


def develop(src: pretty_midi.PrettyMIDI, hook: Hook, records: list[MotifRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, MotifRecord, dict]:
    """Visit `visit` of the cell, given records of visits 0..visit-1 (in order).

    Selection (develop_engine.select): rules -> not in the history window ->
    energy check (energy_cost <= 1: predicted hook level and off-beat motion vs
    the base; a candidate failing only this gets a _balance() repair) ->
    guard() -> lowest cost: unrepaired before repaired, then energy cost, then
    candidate order. If no regular candidate passes, the gentle candidates are
    tried, then the previous motif with a new ending, then the unchanged v2a.3
    segment; motif_selection logs which one was used."""
    return de.select(POLICY, src, hook, records, visit, seed)


motif_id = de.material_id
