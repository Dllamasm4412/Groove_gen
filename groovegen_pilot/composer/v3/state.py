"""
Persistent composition state and the shared per-segment plan (frozen data).

CompositionSpec   the composition's identity, fixed for its lifetime: key,
                  tempo, swing, palette, harmonic loops, groove, bass and
                  comping styles, motifs and form.
CompositionState  spec + position in the form + a ledger of committed
                  segments. It changes only through commit(); planning and
                  realisation never mutate it, so a hypothetical segment
                  (peek) cannot alter what is played later.
SegmentPlan       the shared musical plan for one 8-bar segment that every
                  instrument realises: harmony per step, hook content per
                  2-bar unit, fills, active layers and the section role.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace
from typing import Optional

from composer.v3.theory import SEG_STEPS, STEPS_PER_BAR, Chord


@dataclass(frozen=True)
class MotifNote:
    step: int            # onset within a 2-bar unit (0..31)
    dur: float           # length in 16ths
    deg: int             # diatonic degree from the tonic, before fitting to the chord
    strong: bool         # lands on a beat or opens a rhythmic cell: fitted to a chord tone


@dataclass(frozen=True)
class Motif:
    notes: tuple[MotifNote, ...]
    cells: tuple[str, ...]

    def rhythm(self) -> tuple[int, ...]:
        return tuple(n.step for n in self.notes)

    def contour(self) -> tuple[int, ...]:
        """Degree intervals between consecutive notes (transposition-invariant)."""
        d = [n.deg for n in self.notes]
        return tuple(b - a for a, b in zip(d, d[1:]))

    def signature(self) -> tuple:
        return self.rhythm(), self.contour()


@dataclass(frozen=True)
class Loop:
    """A 4-bar harmonic loop: per bar, (step in bar, chord) changes."""

    bars: tuple[tuple[tuple[int, Chord], ...], ...]

    def romans(self) -> tuple[str, ...]:
        return tuple(c.roman for bar in self.bars for _, c in bar)

    def signature(self) -> tuple:
        return tuple((s, c.roman, c.quality) for bar in self.bars for s, c in bar)


@dataclass(frozen=True)
class CompositionSpec:
    comp_id: str
    index: int                       # 0, 1, 2 ... within the session
    seed: int
    substyle: str                    # 'boombap' | 'soul' | 'dark'
    tempo: float
    swing: float
    snare_lag_s: float               # laid-back backbeat (microtiming identity)
    key_pc: int
    mode: str
    palette: tuple[tuple[str, int], ...]   # (role, GM program)
    loop_a: Loop
    loop_b: Loop
    kick_a: tuple[int, ...]          # kick steps, odd bars of each 2-bar groove unit
    kick_b: tuple[int, ...]          # even bars
    hat_mask: tuple[int, ...]        # 16th hat steps at level 3+
    open_hats: tuple[int, ...]       # open-hat steps (second bar of each unit)
    ghosts: tuple[int, ...]          # ghost-snare steps (level 3+)
    snare_pitch: int
    bass_style: str                  # 'lock' | 'lock_octave' | 'walk' | 'sustain'
    comp_style: str                  # 'stabs' | 'neo' | 'held'
    comp_rhythm: tuple[tuple[int, float], ...]   # (step in 2-bar unit, length) for stabs/neo
    motif: Motif                     # theme M
    answer: Motif                    # contrast motif N
    hook_tonic: int                  # MIDI pitch of degree 0 in the hook register
    hook_range: tuple[int, int]
    form: tuple[str, ...]            # role per segment
    ops: tuple[str, ...]             # development operators for the V sections, in order
    mix_trim_db: float = 0.0         # melodic level so level 3 meets the loudness target (levels.py)

    def program(self, role: str) -> int:
        return dict(self.palette)[role]


@dataclass(frozen=True)
class SegmentRecord:
    ordinal: int
    level: int
    role: str
    op: str
    midi_sha: str


@dataclass(frozen=True)
class CompositionState:
    spec: CompositionSpec
    ordinal: int = 0
    ledger: tuple[SegmentRecord, ...] = ()

    @property
    def done(self) -> bool:
        return self.ordinal >= len(self.spec.form)

    def commit(self, record: SegmentRecord) -> 'CompositionState':
        return replace(self, ordinal=self.ordinal + 1, ledger=self.ledger + (record,))

    def digest(self) -> str:
        return hashlib.blake2b(repr((self.spec.comp_id, self.ordinal,
                                     tuple((r.level, r.midi_sha) for r in self.ledger))).encode(),
                               digest_size=8).hexdigest()


@dataclass(frozen=True)
class SegmentPlan:
    spec: CompositionSpec
    level: int
    ordinal: int
    role: str
    section_idx: int
    first_of_section: bool
    last_of_section: bool
    harmony: tuple[tuple[int, Chord], ...]          # (global step, chord) changes over 8 bars
    hook_units: tuple[Optional[Motif], ...]          # 4 two-bar units; None = the hook rests
    op: str                                          # development operator applied (or '')
    fills: tuple[str, str]                           # bar 4 and bar 8 drum fills
    layers: frozenset[str] = field(default_factory=frozenset)
    seed: int = 0

    def chord_at(self, step: float) -> Chord:
        cur = self.harmony[0][1]
        for s, c in self.harmony:
            if s <= step + 1e-9:
                cur = c
            else:
                break
        return cur

    def changes(self) -> tuple[int, ...]:
        return tuple(s for s, _ in self.harmony)

    @staticmethod
    def harmony_from(loops: tuple[Loop, Loop]) -> tuple[tuple[int, Chord], ...]:
        """Two 4-bar loops back to back as global (step, chord) changes, merged
        where a chord simply continues across the join."""
        out: list[tuple[int, Chord]] = []
        for half, loop in enumerate(loops):
            for b, bar in enumerate(loop.bars):
                for s, c in bar:
                    step = (half * 4 + b) * STEPS_PER_BAR + s
                    if not out or out[-1][1] != c:
                        out.append((step, c))
        assert out and out[0][0] == 0 and out[-1][0] < SEG_STEPS
        return tuple(out)
