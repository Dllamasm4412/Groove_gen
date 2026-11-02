"""
Calm development policy (v2c.calm.0) for the shared engine
(composer/develop_engine.py; LIVE_GENERATION_PLAN.md section 6.13).

Opt-in only (SessionComposer(develop=True)); not used by the live runner.

Material
--------
composer._gen_calm plays, per 8-bar segment, a pad chord held every 2 bars
(program 89) and a piano line of one note on every downbeat (program 0, 8
notes, chord tones of the pad's chord, 100-118 + 12 boost, held 1-2 bars).
calm:1 and calm:2 produce the same MIDI (max(2, int(d*8)) = 2 notes per
chord at both densities); that is kept. In v2a.3 the three visits of a
block replay the same line, and the drums (a fixed grid) cycle with period
5 because the drum history window is 4.

Rules (pitch-only)
------------------
- the piano keeps every onset, duration, velocity and the note count; pad,
  drums, programs and tempo are untouched;
- every note is a chord tone of the chord the pad plays in its bar
  (develop_engine.chord_context; no scale assumed: Dadd9 has F#, Gadd9 B,
  Fsus4 Bb);
- each note stays within FAR semitones of the block's base note at that bar;
  no note above the base line's highest note; mean pitch rises at most
  MAX_MEAN_RISE semitones (not brighter or higher over time); no leap
  larger than the base line's largest or MIN_LEAP_CAP, whichever is larger
  (static tier 3-5 lines have a largest leap of 3-4, which would leave
  almost no legal move); no new unison with an overlapping note;
- predicted piano level (composer/levels_calm.py, measured one-bar notes)
  within LEVEL_TOL_DB of the base line: the 77-79 and 92+ zones are ~6 dB
  quieter, so a single move into them shifts the line by ~0.4 dB.

Development (visit v, block b = v // 3, pos = v % 3)
----------------------------------------------------
    pos 0         the block's base line (new chords), unchanged; if it
                  repeats the history window, one tone move instead
    pos 1, b odd  recall: one 2-bar region of the previous block's theme,
                  its pitches (or its interval, from the current first
                  note) snapped to the current bar's chord tones (ties down);
                  a tone move if no region fits
    pos 1         one tone move (bars 1-7): a note moves to a chord tone
                  within NEAR semitones, or, if none, the nearest one within FAR
    pos 2         ending: bar 8 moves to another chord tone within FAR
At most one tone move per visit (the recall replaces it). History: a line
equal to one of the last HISTORY_WINDOW visits, or differing in only one
note from one of them other than the previous visit, is rejected. Gentle
pass: one note of any bar moves to any chord tone within FAR. Fallbacks as
the engine: the previous line with a new ending, then the unchanged base
line.

Drums: DRUM_REPEAT_WINDOW = 12 replaces the v2a.3 window of 4 in develop
mode only (no change to the drum grammar, density or fills); the engine logs
it as drum_repeat_window and any drum fallback in gen_fallback /
novelty_fallback.
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from functools import cache
from statistics import mean
from typing import Optional

import pretty_midi

from composer import develop_engine as de
from composer.develop_engine import ChordContext, DevRecord
from composer.energy_guard import GuardResult
from composer.levels_calm import LEVEL_DB, VELOCITIES

DEV_VERSION = 'v2c.calm.0'
SEED_VERSION = 'v2c.calm.0'
NO_CONTEXT = 'no_line'
DRUM_REPEAT_WINDOW = 12             # develop mode only; v2a.3 REPEAT_WINDOW is 4 (drum period 5)
BLOCK_LEN = 3
BARS = 8
PIANO, PAD = 0, 89                  # GM programs
HISTORY_WINDOW = 12
N_CANDIDATES = 12
NEAR, FAR = 2, 5                    # semitones: preferred and largest tone move
MAX_MEAN_RISE = 0.5                 # semitones: line mean vs the block's base line
MIN_LEAP_CAP = 5                    # semitones: a perfect fourth is always an allowed leap
LEVEL_TOL_DB = 0.2                  # predicted piano level vs the base line (hiphop v2b.1 value)

Line = tuple[int, ...]


@dataclass(frozen=True)
class CalmLine:
    piano: int                      # instrument index of the piano
    harmony: tuple[int, ...]        # pad (and any other comping) tracks
    order: tuple[int, ...]          # piano note indices in bar order
    base: Line                      # the block's base line (one pitch per bar)
    chords: tuple[ChordContext, ...]
    velocities: tuple[int, ...]
    overlaps: tuple[tuple[int, int], ...]   # bar pairs whose notes overlap in time
    max_leap: int


def read_context(src: pretty_midi.PrettyMIDI, sched, tempo: float) -> Optional[CalmLine]:
    """The piano line of src (None unless it is one chord-tone note per bar)."""
    piano = next((i for i, x in enumerate(src.instruments)
                  if not x.is_drum and x.program == PIANO and x.notes), None)
    harmony = tuple(i for i, x in enumerate(src.instruments) if not x.is_drum and x.program == PAD and x.notes)
    if piano is None or not harmony:
        return None
    bar_s = 4 * 60.0 / tempo
    notes = src.instruments[piano].notes
    order = sorted(range(len(notes)), key=lambda j: notes[j].start)
    if [int(round(notes[j].start / bar_s)) for j in order] != list(range(BARS)):
        return None
    chords = de.chord_context(src, harmony, bar_s, BARS)
    base = tuple(notes[j].pitch for j in order)
    if any(c is None or p % 12 not in c.pcs for p, c in zip(base, chords)):
        return None
    overlaps = tuple((a, b) for a in range(BARS) for b in range(a + 1, BARS)
                     if min(notes[order[a]].end, notes[order[b]].end)
                     > max(notes[order[a]].start, notes[order[b]].start))
    return CalmLine(piano=piano, harmony=harmony, order=tuple(order), base=base, chords=tuple(chords),
                    velocities=tuple(notes[j].velocity for j in order), overlaps=overlaps,
                    max_leap=max(MIN_LEAP_CAP, *(abs(b - a) for a, b in zip(base, base[1:]))))


def valid(line: Line, c: CalmLine) -> bool:
    if len(line) != BARS:
        return False
    for p, b, ch in zip(line, c.base, c.chords):
        if p % 12 not in ch.pcs or abs(p - b) > FAR:
            return False
    if max(line) > max(c.base) or mean(line) > mean(c.base) + MAX_MEAN_RISE + 1e-9:
        return False
    if max(abs(b - a) for a, b in zip(line, line[1:])) > c.max_leap:
        return False
    return all(line[a] != line[b] or c.base[a] == c.base[b] for a, b in c.overlaps)


# =============================================================================
# Operations
# =============================================================================


def op_tone(line: Line, c: CalmLine, rng: random.Random, bars=range(BARS - 1)) -> tuple[Line, str]:
    """One note moves to a nearby chord tone of its bar (develop_engine.neighbor_tones)."""
    i = rng.choice(list(bars))
    opts = de.neighbor_tones(line[i], c.chords[i], NEAR, FAR)
    if not opts:
        return line, 'tone:none'
    p = rng.choice(opts)
    return line[:i] + (p,) + line[i + 1:], f'tone@{i + 1}:{p - line[i]:+d}'


def op_wide(line: Line, c: CalmLine, rng: random.Random, bars=(BARS - 1,), tag: str = 'ending') -> tuple[Line, str]:
    """One note (default bar 8: the ending) moves to any other chord tone of its bar within FAR semitones."""
    i = rng.choice(list(bars))
    opts = [p for p in de.chord_tones(c.chords[i], line[i] - FAR, line[i] + FAR) if p != line[i]]
    if not opts:
        return line, f'{tag}:none'
    p = rng.choice(opts)
    return line[:i] + (p,) + line[i + 1:], f'{tag}@{i + 1}:{p - line[i]:+d}'


def snap(pitch: int, ch: ChordContext) -> int:
    """Nearest chord tone (ties down)."""
    return min(de.chord_tones(ch, pitch - 6, pitch + 6), key=lambda p: (abs(p - pitch), p))


def op_recall(line: Line, old: Line, c: CalmLine, rng: random.Random) -> tuple[Line, str]:
    """One 2-bar region of an earlier block's line, adapted to the current chords:
    its pitches snapped to the nearest chord tones ('pitch'), or its interval
    from the region's first note applied to the current first note and
    snapped ('contour'). Regions in rng order; the first valid change is used."""
    for r in rng.sample(range(BARS // 2), BARS // 2):
        a, b = 2 * r, 2 * r + 1
        for kind, pair in (('pitch', (snap(old[a], c.chords[a]), snap(old[b], c.chords[b]))),
                           ('contour', (line[a], snap(line[a] + old[b] - old[a], c.chords[b])))):
            new = line[:a] + pair + line[b + 1:]
            if new != line and valid(new, c):
                return new, f'recall_{kind}@{a + 1}-{b + 1}'
    return line, 'recall:none'


def _with_ending(line: Line, c: CalmLine, rng: random.Random) -> tuple[Line, str]:
    for _ in range(8):
        e, d = op_wide(line, c, rng)
        if e != line and valid(e, c):
            return e, d
    return line, 'ending:none'


def _candidate(c: CalmLine, records: list[DevRecord], visit: int, k: int, rng: random.Random,
               gentle: bool) -> DevRecord:
    block, pos = divmod(visit, BLOCK_LEN)
    if visit == 0 or (pos == 0 and k == 0 and not gentle):
        return DevRecord(motif=c.base, theme=c.base, plan=(c.base,), role='base', ops=())
    if pos == 0:                                   # the base repeats the window: one move instead
        m, d = op_tone(c.base, c, rng)
        return DevRecord(motif=m, theme=m, plan=(m,), role='develop', ops=(d,))
    prev = records[visit - 1]
    if gentle:
        role, (m, d) = 'develop', op_wide(prev.motif, c, rng, range(BARS), 'tone')
    elif pos == 1 and block % 2:
        role, (m, d) = 'recall', op_recall(prev.motif, records[(block - 1) * BLOCK_LEN].theme, c, rng)
        if m == prev.motif:                        # nothing recallable fits these chords
            role, (m, d) = 'develop', op_tone(prev.motif, c, rng)
    elif pos == 1:
        role, (m, d) = 'develop', op_tone(prev.motif, c, rng)
    else:
        role, (m, d) = 'develop', op_wide(prev.motif, c, rng)
    return DevRecord(motif=m, theme=prev.theme, plan=(m,), role=role, ops=(d,))


def hamming(a: Line, b: Line) -> int:
    return sum(x != y for x, y in zip(a, b)) + abs(len(a) - len(b))


def repeats(rec: DevRecord, recent: list[DevRecord], c: CalmLine) -> Optional[str]:
    if rec.motif in {r.motif for r in recent}:
        return 'history'
    if any(hamming(rec.motif, r.motif) <= 1 for r in recent[:-1]):
        return 'near_repeat'
    return None


# =============================================================================
# Level, realization, guard
# =============================================================================


@cache
def note_level(pitch: int, velocity: int) -> float:
    return de.table_level(LEVEL_DB, VELOCITIES, pitch, velocity)


def line_level(line: Line, c: CalmLine) -> float:
    return sum(note_level(p, v) for p, v in zip(line, c.velocities))


def energy_shift(plan: tuple[Line, ...], aux, c: CalmLine) -> dict:
    """Predicted piano level change (dB) and mean / top pitch change vs the base line."""
    line = plan[0]
    return {'level_db': de.db(line_level(line, c), line_level(c.base, c)),
            'mean_rise': round(mean(line) - mean(c.base), 4), 'top_rise': max(line) - max(c.base)}


def energy_cost(shift: dict) -> float:
    return round(max(abs(shift['level_db']) / LEVEL_TOL_DB, max(shift['mean_rise'], 0) / MAX_MEAN_RISE), 6)


def realize(src: pretty_midi.PrettyMIDI, c: CalmLine, plan: tuple[Line, ...]) -> pretty_midi.PrettyMIDI:
    out = copy.deepcopy(src)
    notes = out.instruments[c.piano].notes
    for j, p in zip(c.order, plan[0]):
        notes[j].pitch = p
    return out


def guard(developed: pretty_midi.PrettyMIDI, src: pretty_midi.PrettyMIDI, c: CalmLine) -> GuardResult:
    """Only piano pitches may change; every piano note a chord tone of its bar, none above the base line."""
    def check(pm: pretty_midi.PrettyMIDI) -> list[str]:
        notes = pm.instruments[c.piano].notes
        line = [notes[j].pitch for j in c.order]
        fails = ['off_chord'] if any(p % 12 not in ch.pcs for p, ch in zip(line, c.chords)) else []
        return fails + (['register'] if max(line) > max(c.base) else [])

    return de.guard(developed, src, {c.piano: None}, check, de.MAX_PITCH_SHIFT, BARS)


def _previous(prev: DevRecord, rng: random.Random, c: CalmLine) -> DevRecord:
    """The previous line with a new ending (the base line's at a block start: new chords)."""
    end, d = _with_ending(prev.motif if valid(prev.motif, c) else c.base, c, rng)
    return DevRecord(motif=end, theme=prev.theme, plan=(end,), role='fallback', ops=(d,))


def unchanged_record(c: CalmLine, records: list[DevRecord]) -> DevRecord:
    """The unchanged segment plays the base line; the block theme carries on."""
    theme = records[-1].theme if records and len(records) % BLOCK_LEN else c.base
    return DevRecord(c.base, theme, (c.base,), 'fallback', ())


POLICY = de.Policy(
    dev_version=DEV_VERSION, history_window=HISTORY_WINDOW, n_candidates=N_CANDIDATES,
    candidate=_candidate, valid=lambda rec, c: all(valid(p, c) for p in rec.plan),
    energy=energy_shift, cost=energy_cost, realize=realize, guard=guard,
    previous=_previous, unchanged=unchanged_record, repeats=repeats)


def develop(src: pretty_midi.PrettyMIDI, c: CalmLine, records: list[DevRecord], visit: int,
            seed: int) -> tuple[pretty_midi.PrettyMIDI, DevRecord, dict]:
    return de.select(POLICY, src, c, records, visit, seed)
