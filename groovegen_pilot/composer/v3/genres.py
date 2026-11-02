"""
v3 multi-genre excerpt composer (opt-in, version v3.genres.0).

Composes one 8-bar statement (the protocol's "eight-bar musical phrase") for a
(genre, tier) configuration. Hip-hop is the approved v3 hip-hop generator
(composer/v3/hiphop.py, its statement section at level = tier, tier tempo).
The six other genres are written here, each with its own

  - harmony: a 4-bar progression grammar per mode family, played twice, the
    second half cadencing to the tonic (a closed 8-bar phrase);
  - rhythm: a drum / percussion pattern library per tier (calm: the original
    calm configuration's light pulse, mixed under the piano);
  - bass: a figure that follows the genre's bass-drum relationship
    (pop / rock lock to the kick, R&B syncopates around it, Latin anticipates
    the next chord in tumbao, lo-fi walks loosely, calm holds a pedal);
  - comping: piano / EP / guitar / montuno patterns per tier;
  - melody: a 2-bar motif from genre-specific rhythm cells and a constrained
    diatonic walk, fitted to the chords (strong notes on chord tones) and
    stated as motif, open answer, motif, closed cadence (the v3 statement);
  - instrumentation: a few palettes per genre, building on the instruments
    the developer chose by ear for the locked cells (calm: piano first;
    lo-fi: Rhodes and upright bass; R&B: Rhodes and synth sub-bass,
    straight half-time 16ths; pop: acoustic-guitar lead; Latin: montuno piano,
    tumbao bass, percussion built shaker -> clave -> congas -> cowbell ->
    timbales; rock (v3.genres.1): riff-based hard rock on driven guitars at
    every tier, after the stadium / melodic hard-rock style the developer
    asked for - riffs and hooks are generated, no song is reproduced).

The composition (key, harmony, palette, groove variant, motif) depends only on
the seed; the tier changes only the realisation (layers, rhythmic activity,
dynamics) and, where the configuration defines it, the tempo. The tempo of
every (genre, tier) is GENRE_CFG's, so an excerpt keeps its condition's tempo.

Only for offline excerpts (no form development across segments for these six
genres yet); the live runner never imports this module.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional

import pretty_midi

from composer.arrangement import H
from composer.v3.hiphop import _Part, _chord_at, _close, _sound_line, _walk
from composer.v3.state import Motif, MotifNote
from composer.v3.theory import (BARS, MODES, STEPS_PER_BAR, Chord, Grid, degree_to_midi, directed, lead_voice,
                                melodic_pcs, place, weighted)

GEN_VERSION = 'v3.genres.1'
# v3.genres.1 (2026-11-02, after the developer's listening of the candidate corpus): rock rewritten as
# riff-based hard rock; pop tier 1 re-arranged. Every other genre and pop tiers 2-5 are byte-identical to
# v3.genres.0.
GENRES = ('calm', 'lofi', 'rnb', 'pop', 'latin', 'rock')
VOCAL_PROGRAMS = {52, 53, 54, 85, 91}

# GM drum notes
KICK, SIDE, SNARE, CLAP = 36, 37, 38, 39
CH, PEDAL, OH, CRASH, RIDE, BELL = 42, 44, 46, 49, 51, 53
TAMB, COWBELL, HBONGO, LBONGO, MCONGA, OCONGA, LCONGA = 54, 56, 60, 61, 62, 63, 64
HTIMB, LTIMB, MARACAS, GUIRO_S, GUIRO_L, CLAVES = 65, 66, 70, 73, 74, 75
LTOM, MTOM, HTOM = 45, 47, 50

SEG = BARS * STEPS_PER_BAR
TIER_DYN = {1: -10, 2: -5, 3: 0, 4: 4, 5: 8}        # melodic velocity offset per tier


# =============================================================================
# Styles: harmony, palettes, melody cells, feel
# =============================================================================

def _L(*bars):
    """A 4-bar loop: each bar a (roman, quality) or a tuple of two (half-bar change)."""
    return tuple(b if isinstance(b[0], tuple) else (b,) for b in bars)


STYLES: dict[str, dict] = {
    'pop': dict(
        modes={'ionian': 4, 'mixolydian': 1},
        loops={
            'ionian': {_L(('I', 'M'), ('V', 'M'), ('vi', 'm'), ('IV', 'M')): 3,
                       _L(('vi', 'm'), ('IV', 'M'), ('I', 'M'), ('V', 'M')): 3,
                       _L(('I', 'M'), ('vi', 'm'), ('IV', 'M'), ('V', 'M')): 2,
                       _L(('IV', 'M'), ('I', 'M'), ('V', 'M'), ('vi', 'm')): 2,
                       _L(('I', 'M'), ('IV', 'M'), ('vi', 'm'), ('V', 'M')): 2,
                       _L((('I', 'M'), ('V', 'M')), (('vi', 'm'), ('IV', 'M')), ('I', 'M'), ('V', 'M')): 1},
            'mixolydian': {_L(('I', 'M'), ('bVII', 'M'), ('IV', 'M'), ('I', 'M')): 2,
                           _L(('I', 'M'), ('IV', 'M'), ('bVII', 'M'), ('IV', 'M')): 1}},
        colors={'I': {'M': 3, 'add9': 1}, 'IV': {'M': 3, 'maj7': 1}, 'vi': {'m': 3, 'm7': 1}},
        cadence={'ionian': (('V', 'M'), ('IV', 'M')), 'mixolydian': (('bVII', 'M'), ('IV', 'M'))},
        tonic={'ionian': ('I', 'M'), 'mixolydian': ('I', 'M')},
        keys=(0, 2, 4, 5, 7, 9, 10), swing=(0.5, 0.5),
        palettes=({'comp': 4, 'bass': 33, 'lead': 25, 'pad': 89},
                  {'comp': 0, 'bass': 33, 'lead': 25, 'pad': 48},
                  {'comp': 25, 'bass': 38, 'lead': 0, 'pad': 89},
                  {'comp': 4, 'bass': 38, 'lead': 0, 'pad': 48}),
        grooves=('a', 'b', 'c'),
        cells={'p1': ((0, 2), (2, 2), (4, 4), (10, 2), (12, 4)), 'p2': ((2, 2), (4, 2), (6, 2), (8, 6)),
               'p3': ((0, 3), (3, 3), (6, 2), (8, 8)), 'p4': ((4, 2), (6, 2), (8, 2), (10, 2), (12, 4)),
               'p5': ((0, 4), (4, 4), (8, 2), (10, 6)), 'p6': ((0, 2), (3, 1), (4, 2), (8, 2), (11, 1), (12, 4)),
               'p7': ((2, 2), (6, 2), (8, 4), (14, 2))},
    ),
    'rock': dict(
        # Riff-based hard rock in the stadium-rock / heavy-melodic tradition the developer named
        # (driving straight-8th backbeat, power-chord riffs with space, pedal-point 16th riffs,
        # palm-muted chugs, melodic lead hooks at the top tiers). Riffs and hooks are generated from
        # these techniques; no existing song's riff, melody or arrangement is reproduced.
        modes={'aeolian': 3, 'mixolydian': 3, 'dorian': 1},
        loops={
            'aeolian': {_L(('i', 'm'), ('i', 'm'), ('bVII', 'M'), ('bVI', 'M')): 3,
                        _L(('i', 'm'), ('bVI', 'M'), ('bVII', 'M'), ('i', 'm')): 2,
                        _L(('i', 'm'), ('bIII', 'M'), ('bVII', 'M'), ('i', 'm')): 2,
                        _L(('i', 'm'), ('i', 'm'), ('iv', 'm'), ('bVII', 'M')): 1},
            'mixolydian': {_L(('I', 'M'), ('bVII', 'M'), ('IV', 'M'), ('I', 'M')): 3,
                           _L(('I', 'M'), ('I', 'M'), ('bVII', 'M'), ('IV', 'M')): 2,
                           _L(('I', 'M'), ('IV', 'M'), ('I', 'M'), ('bVII', 'M')): 2},
            'dorian': {_L(('i', 'm'), ('IV', 'M'), ('i', 'm'), ('IV', 'M')): 1,
                       _L(('i', 'm'), ('bVII', 'M'), ('IV', 'M'), ('i', 'm')): 1}},
        colors={},
        cadence={'aeolian': (('bVII', 'M'), ('bVI', 'M')), 'dorian': (('bVII', 'M'), ('IV', 'M')),
                 'mixolydian': (('bVII', 'M'), ('IV', 'M'))},
        tonic={'aeolian': ('i', 'm'), 'dorian': ('i', 'm'), 'mixolydian': ('I', 'M')},
        keys=(4, 4, 9, 9, 11, 2, 7, 0), swing=(0.5, 0.5),
        palettes=({'riff': 29, 'bed': 30, 'lead': 29, 'bass': 34},
                  {'riff': 30, 'bed': 29, 'lead': 30, 'bass': 34},
                  {'riff': 29, 'bed': 29, 'lead': 30, 'bass': 33}),
        grooves=('a', 'b', 'c'),
        riffs={'space': 3, 'drive': 2, 'chug': 2, 'pedal16': 2},
        cells={'r1': ((0, 2), (2, 2), (4, 2), (6, 2), (8, 4), (12, 4)), 'r2': ((0, 4), (6, 2), (8, 2), (10, 2), (12, 4)),
               'r3': ((0, 2), (3, 3), (6, 2), (8, 8)), 'r4': ((2, 2), (4, 2), (6, 2), (8, 2), (10, 6)),
               'r5': ((0, 6), (6, 2), (8, 6), (14, 2)), 'r6': ((0, 3), (3, 3), (6, 4), (12, 4))},
        pentatonic=True,
    ),
    'latin': dict(
        modes={'harmonic': 3, 'ionian': 2},
        loops={
            'harmonic': {_L(('i', 'm'), ('iv', 'm'), ('V', '7'), ('i', 'm')): 3,
                         _L(('i', 'm'), ('i', 'm'), ('V', '7'), ('V', '7')): 2,
                         _L(('i', 'm'), ('bVII', 'M'), ('bVI', 'M'), ('V', '7')): 2,
                         _L((('i', 'm'), ('iv', 'm')), (('V', '7'), ('i', 'm')), (('i', 'm'), ('iv', 'm')),
                            ('V', '7')): 1},
            'ionian': {_L(('I', 'M'), ('IV', 'M'), ('V', '7'), ('IV', 'M')): 3,
                       _L(('ii', 'm7'), ('V', '7'), ('I', 'M'), ('I', 'M')): 2,
                       _L((('I', 'M'), ('IV', 'M')), (('V', '7'), ('IV', 'M')), (('I', 'M'), ('IV', 'M')),
                          ('V', '7')): 2}},
        colors={'I': {'M': 3, '6': 1}},
        cadence={'harmonic': (('V', '7'),), 'ionian': (('V', '7'),)},
        tonic={'harmonic': ('i', 'm'), 'ionian': ('I', 'M')},
        keys=(0, 2, 5, 7, 9, 10), swing=(0.5, 0.5),
        palettes=({'comp': 0, 'bass': 32, 'lead': 73},
                  {'comp': 0, 'bass': 33, 'lead': 56},
                  {'comp': 0, 'bass': 32, 'lead': 24},
                  {'comp': 24, 'bass': 32, 'lead': 73}),
        grooves=('son32', 'son23'),
        cells={'l1': ((2, 2), (6, 2), (8, 2), (11, 3), (14, 2)), 'l2': ((0, 3), (3, 3), (6, 2), (10, 2), (12, 4)),
               'l3': ((0, 2), (2, 2), (4, 2), (7, 1), (8, 4), (14, 2)), 'l4': ((3, 1), (4, 2), (6, 2), (8, 2), (10, 2), (12, 4)),
               'l5': ((0, 4), (6, 2), (8, 2), (12, 2), (14, 2))},
    ),
    'rnb': dict(
        modes={'dorian': 3, 'aeolian': 2, 'ionian': 2},
        loops={
            'dorian': {_L(('i', 'm9'), ('i', 'm9'), ('IV', '9'), ('IV', '9')): 3,
                       _L(('i', 'm9'), ('IV', '9'), ('i', 'm9'), ('IV', '9')): 2,
                       _L(('i', 'm9'), ('bVII', 'maj7'), ('IV', '9'), ('IV', '9')): 1},
            'aeolian': {_L(('i', 'm9'), ('iv', 'm9'), ('bVII', '9'), ('bIII', 'maj7')): 3,
                        _L(('iv', 'm9'), ('bVII', '9'), ('bIII', 'maj9'), ('bVI', 'maj7')): 2,
                        _L(('i', 'm7'), ('bVI', 'maj7'), ('iv', 'm9'), ('bVII', '9')): 2},
            'ionian': {_L(('I', 'maj9'), ('iii', 'm7'), ('IV', 'maj9'), ('V', '9sus4')): 2,
                       _L(('ii', 'm9'), ('V', '9'), ('I', 'maj9'), ('vi', 'm9')): 2,
                       _L(('IV', 'maj9'), ('iii', 'm7'), ('vi', 'm9'), ('ii', 'm9')): 2}},
        colors={},
        cadence={'dorian': (('IV', '9'), ('bVII', '9')), 'aeolian': (('bVII', '9'), ('iv', 'm9')),
                 'ionian': (('V', '9sus4'), ('ii', 'm9'))},
        tonic={'dorian': ('i', 'm9'), 'aeolian': ('i', 'm9'), 'ionian': ('I', 'maj9')},
        keys=(0, 2, 3, 5, 7, 8, 10), swing=(0.5, 0.53),
        palettes=({'comp': 4, 'bass': 38, 'lead': 11, 'pad': 89},
                  {'comp': 5, 'bass': 39, 'lead': 73, 'pad': 89},
                  {'comp': 4, 'bass': 33, 'lead': 26, 'pad': 49},
                  {'comp': 4, 'bass': 39, 'lead': 65, 'pad': 89}),
        grooves=('a', 'b', 'c'),
        cells={'b1': ((0, 3), (3, 1), (4, 4), (10, 2), (12, 4)), 'b2': ((2, 1), (3, 1), (4, 2), (7, 1), (8, 6)),
               'b3': ((0, 2), (3, 2), (6, 2), (9, 1), (10, 6)), 'b4': ((4, 3), (7, 1), (8, 2), (11, 1), (12, 4)),
               'b5': ((0, 6), (6, 1), (7, 1), (8, 8)), 'b6': ((1, 1), (2, 2), (6, 2), (8, 2), (11, 5))},
    ),
    'lofi': dict(
        modes={'ionian': 2, 'dorian': 2, 'aeolian': 1},
        loops={
            'ionian': {_L(('ii', 'm9'), ('V', '9'), ('I', 'maj9'), ('vi', 'm9')): 3,
                       _L(('I', 'maj7'), ('vi', 'm7'), ('ii', 'm9'), ('V', '9')): 2,
                       _L(('IV', 'maj9'), ('iii', 'm7'), ('ii', 'm9'), ('I', 'maj9')): 2,
                       _L(('I', 'maj9'), ('IV', 'maj9'), ('I', 'maj9'), ('IV', 'maj9')): 1},
            'dorian': {_L(('i', 'm9'), ('IV', '9'), ('i', 'm9'), ('IV', '9')): 2,
                       _L(('i', 'm9'), ('iv', 'm9'), ('bVII', '9'), ('bIII', 'maj7')): 2},
            'aeolian': {_L(('i', 'm7'), ('bVI', 'maj7'), ('iv', 'm9'), ('V', '7b9')): 2,
                        _L(('iv', 'm9'), ('bVII', '9'), ('i', 'm9'), ('i', 'm9')): 1}},
        colors={},
        cadence={'ionian': (('V', '9'), ('ii', 'm9')), 'dorian': (('IV', '9'), ('bVII', '9')),
                 'aeolian': (('V', '7b9'), ('bVII', '9'))},
        tonic={'ionian': ('I', 'maj9'), 'dorian': ('i', 'm9'), 'aeolian': ('i', 'm9')},
        keys=(0, 2, 3, 5, 7, 8, 10), swing=(0.58, 0.63),
        palettes=({'comp': 4, 'bass': 32, 'lead': 11, 'pad': 89},
                  {'comp': 4, 'bass': 32, 'lead': 26, 'pad': 89},
                  {'comp': 0, 'bass': 32, 'lead': 73, 'pad': 89},
                  {'comp': 4, 'bass': 33, 'lead': 59, 'pad': 89}),
        grooves=('a', 'b', 'c'),
        cells={'f1': ((0, 6), (6, 2), (8, 8)), 'f2': ((2, 2), (4, 4), (10, 2), (12, 4)),
               'f3': ((0, 3), (4, 2), (7, 1), (8, 8)), 'f4': ((4, 4), (10, 2), (12, 4)),
               'f5': ((0, 2), (2, 2), (4, 8), (14, 2))},
    ),
    'calm': dict(
        modes={'ionian': 4, 'lydian': 1},
        loops={
            'ionian': {_L(('I', 'add9'), ('IV', 'maj7'), ('vi', 'm7'), ('IV', 'maj7')): 3,
                       _L(('I', 'maj7'), ('IV', 'maj7'), ('I', 'maj7'), ('IV', 'maj7')): 2,
                       _L(('I', 'add9'), ('iii', 'm7'), ('IV', 'maj7'), ('I', 'add9')): 2,
                       _L(('vi', 'm7'), ('IV', 'maj7'), ('I', 'add9'), ('V', 'sus4')): 2,
                       _L(('I', 'add9'), ('V', 'sus4'), ('vi', 'm7'), ('IV', 'maj7')): 2},
            'lydian': {_L(('I', 'maj7'), ('II', 'M'), ('I', 'maj7'), ('II', 'M')): 1}},
        colors={},
        cadence={'ionian': (('IV', 'maj7'), ('V', 'sus4')), 'lydian': (('II', 'M'),)},
        tonic={'ionian': ('I', 'add9'), 'lydian': ('I', 'maj7')},
        keys=(0, 2, 3, 5, 7, 8, 10), swing=(0.5, 0.5),
        palettes=({'comp': 0, 'bass': 0, 'lead': 0},
                  {'comp': 0, 'bass': 0, 'lead': 73},
                  {'comp': 0, 'bass': 0, 'lead': 49}),
        grooves=('rolled', 'flowing'),
        cells={'k1': ((0, 8), (8, 4), (12, 4)), 'k2': ((0, 4), (4, 4), (8, 8)), 'k3': ((2, 2), (4, 6), (10, 6)),
               'k4': ((0, 6), (6, 2), (8, 8)), 'k5': ((4, 4), (8, 4), (12, 4))},
    ),
}

# Melody register per program (lowest, highest MIDI pitch) and the comping
# register per program.
LEAD_RANGE = {25: (55, 79), 0: (62, 86), 29: (62, 86), 30: (62, 86), 27: (55, 79), 18: (60, 84), 73: (67, 91), 56: (58, 82),
              24: (55, 79), 11: (62, 86), 26: (55, 79), 65: (58, 82), 59: (60, 84), 49: (62, 84)}
COMP_RANGE = {4: (52, 76), 5: (52, 76), 0: (50, 76), 25: (50, 74), 24: (50, 74), 27: (50, 74), 26: (50, 74),
              29: (40, 64), 30: (40, 64)}
CALM_LEAD_RANGE = {0: (72, 91), 73: (67, 91), 49: (62, 86)}

# Per-program loudness trim (dB) so parts balance (measured on FluidR3_GM;
# fixed here so the MIDI does not depend on the soundfont); channel volume
# CC7 follows 40*log10(cc/100), the law levels.py uses.
PROGRAM_TRIM_DB = {0: 3.0, 4: -1.5, 5: -1.0, 11: 2.0, 18: -3.0, 24: 2.0, 25: 1.0, 26: 1.0, 27: 0.0, 29: -3.0,
                   30: -4.0, 32: 1.0, 33: 0.0, 34: 0.0, 38: -2.0, 39: -2.0, 48: -1.0, 49: 0.0, 56: -1.0, 59: 0.0,
                   65: -1.0, 73: 0.0, 89: -3.0}
# Mix per genre: each role's channel level in dB (drums included). Set from
# solo-part loudness measured on FluidR3_GM at tier 3 (2026-11-02) towards
# conventional balances: pop / rock drums level with the lead, R&B bass on top,
# lo-fi drums soft but present, Latin montuno close to the melody, calm piano
# accompaniment under the melody.
GENRE_MIX = {
    'pop': {'lead': -3.0, 'comp': -4.5, 'bass': -2.5, 'pad': -12.0, 'drums': 0.0},
    'rock': {'lead': -2.5, 'riff': -4.0, 'bed': -2.0, 'bass': -2.5, 'drums': 1.0},
    'rnb': {'lead': 0.0, 'comp': -6.0, 'bass': -4.0, 'pad': -12.0, 'drums': 0.0},
    'lofi': {'lead': -6.3, 'comp': -6.0, 'arp': -4.0, 'bass': -2.5, 'pad': -12.0, 'drums': 3.0},
    'latin': {'lead': -3.0, 'comp': -2.0, 'bass': -2.5, 'drums': 1.5},
    'calm': {'lead': -3.0, 'comp': -4.0, 'lh': -3.5, 'drums': -10.0},
}


def _cc(db: float) -> int:
    return int(max(20, min(127, round(100 * 10 ** (db / 40)))))


def channel_volume(program: int, role: str, genre: str) -> int:
    if role == 'drums':
        return _cc(GENRE_MIX[genre].get('drums', 0.0))
    return _cc(GENRE_MIX[genre].get(role, -6.0) + PROGRAM_TRIM_DB.get(program, 0.0))


# =============================================================================
# Composition (identity: depends on the seed only)
# =============================================================================


@dataclass(frozen=True)
class ExcerptSpec:
    genre: str
    seed: int
    key_pc: int
    mode: str
    loop: tuple                # the 4-bar progression: per bar, ((roman, quality), ...)
    cadence: tuple             # bars 7 and 8: ((roman, quality),) each
    palette: tuple             # ((role, program), ...)
    groove: str
    swing: float
    motif: Motif
    mel_range: tuple[int, int]
    mel_tonic: int
    riff: tuple = ()           # rock: the 2-bar guitar riff, ((step, dur, kind, interval), ...)
    riff_family: str = ''      # rock: space | drive | chug | pedal16

    def program(self, role: str) -> Optional[int]:
        return dict(self.palette).get(role)

    def harmony(self) -> tuple[tuple[int, Chord], ...]:
        """(global 16th step, chord) changes over the 8 bars: the loop, then the
        loop's first two bars, the cadence chord and the tonic."""
        bars = list(self.loop) + list(self.loop[:2]) + [self.cadence[0], self.cadence[1]]
        out = []
        for b, bar in enumerate(bars):
            for i, (roman, q) in enumerate(bar):
                out.append((b * STEPS_PER_BAR + i * 8, Chord(roman, q)))
        merged = [out[0]]
        for s, c in out[1:]:
            if c != merged[-1][1]:
                merged.append((s, c))
        return tuple(merged)

    def name(self) -> str:
        return f'{self.genre}-{self.seed:08x}'


def _rng(*key) -> random.Random:
    return random.Random(H(*key))


def _color(rng, colors: dict, roman: str, q: str) -> str:
    opts = colors.get(roman)
    return weighted(rng, opts) if opts and q in opts else q


def _cell_notes(cells: dict, name: str, offset: int):
    return [(offset + s, d, i == 0 or s % 4 == 0) for i, (s, d) in enumerate(cells[name])]


def make_motif(rng, cells: dict, fit) -> Motif:
    """2-bar motif from the genre's cells (as hiphop.make_motif: the second bar
    sequences, varies or answers the first); kept only if its realisation over
    the first chord is a sound line whose two bars differ."""
    names = sorted(cells)
    best = None
    for _ in range(80):
        c1 = rng.choice(names)
        form = weighted(rng, {'sequence': 3, 'vary': 3, 'contrast': 2})
        c2 = c1 if form != 'contrast' else rng.choice([c for c in names if c != c1] or [c1])
        bar1, bar2 = _cell_notes(cells, c1, 0), _cell_notes(cells, c2, 16)
        d1 = _walk(rng, len(bar1), weighted(rng, {0: 1, 2: 1.5, 4: 2}))
        if form == 'sequence':
            d2 = [d + weighted(rng, {-2: 2, 2: 2, 3: 1, -3: 1}) for d in d1]
        elif form == 'vary':
            d2 = list(d1)
            d2[-1] += rng.choice((-3, -2, 2, 3))
            if len(d2) >= 3:
                d2[-2] += rng.choice((-1, 1))
        else:
            d2 = _walk(rng, len(bar2), d1[-1] + rng.choice((-2, -1, 1, 2)))
        degs = _close(d1 + d2)
        m = Motif(tuple(MotifNote(s, d, g, strong) for (s, d, strong), g in zip(bar1 + bar2, degs)), (c1, c2))
        pitches = [p for _, p in fit(m)]
        half = sum(1 for n in m.notes if n.step < 16)
        differ = pitches[:half] != pitches[half:] or c1 != c2
        if _sound_line(pitches) and differ:
            return m
        best = best or (m if differ else None)
    return best or m


def create_spec(genre: str, seed: int) -> ExcerptSpec:
    if genre not in STYLES:
        raise ValueError(f'genres.py composes {GENRES}, not {genre!r}')
    st = STYLES[genre]
    rng = _rng('v3genre', genre, seed)
    mode = weighted(rng, st['modes'])
    loop = weighted(rng, st['loops'][mode])
    loop = tuple(tuple((r, _color(rng, st['colors'], r, q)) for r, q in bar) for bar in loop)
    # bar 7 cadences (avoiding a repeat of bar 6's chord), bar 8 is the tonic
    bar6 = loop[1][-1]
    pre = next((c for c in st['cadence'][mode] if c != bar6), st['cadence'][mode][0])
    cadence = ((pre,), (st['tonic'][mode],))
    key_pc = rng.choice(st['keys'])
    palette = rng.choice(st['palettes'])
    groove = rng.choice(st['grooves'])
    lo_sw, hi_sw = st['swing']
    swing = round(rng.uniform(lo_sw, hi_sw), 3) if hi_sw > lo_sw else lo_sw
    lead = palette['lead']
    lo, hi = (CALM_LEAD_RANGE if genre == 'calm' else LEAD_RANGE)[lead]
    tonic = lo + 5 + (key_pc - (lo + 5)) % 12          # the key's tonic a fourth or more above the floor
    spec = ExcerptSpec(genre, seed, key_pc, mode, loop, cadence, tuple(sorted(palette.items())), groove, swing,
                       Motif((), ()), (lo, hi), tonic)
    harm = spec.harmony()
    motif = make_motif(rng, st['cells'], lambda m: fit_line(spec, m.notes, lambda s: _chord_at(harm, s)))
    spec = replace(spec, motif=motif)
    if genre == 'rock':
        family = weighted(rng, st['riffs'])
        spec = replace(spec, riff=make_riff(rng, family), riff_family=family)
    return spec


# =============================================================================
# Rock riffs
# =============================================================================

# Intervals above the chord root a riff may use: minor-pentatonic with the blue note (6) and, for
# the heavy chug riffs, the flat second (1). Major chords take the same minor-pentatonic colour,
# the blues-rock sound.
RIFF_IV = (0, 3, 5, 6, 7, 10, 12)


def thin_riff(riff: tuple, family: str) -> tuple:
    """The level-1 (intro) form of a riff: 8th-note drives and chugs keep their
    accents on the beat, pedal riffs keep the moving line at 8th-note speed,
    stab riffs (already sparse) are unchanged."""
    if family == 'drive':
        return tuple(e for e in riff if e[2] != 'P' or e[0] % 4 == 0)
    if family == 'chug':
        return tuple(e for e in riff if e[2] != 'M' or e[0] % 4 == 0)
    if family == 'pedal16':
        out = []
        for st, dur, kind, iv in riff:
            if st % 4 == 0:
                out.append((st, 1.8, kind, iv))
            elif st % 4 == 1:
                out.append((st + 1, 1.8, kind, iv))       # the line note moves onto the off-beat 8th
        return tuple(out)
    return riff


def make_riff(rng, family: str) -> tuple:
    """A 2-bar riff: (step 0-31, duration in 16ths, kind, interval) with kind P a
    power chord, M a palm-muted root and fifth, N a single note `interval`
    semitones above the chord root, D the low root as a pedal."""
    ev = []
    if family == 'space':           # power-chord stabs with rests, a pentatonic run into the next bar
        for b0 in (0, 16):
            ev.append((b0, 1.5, 'P', 0))
            ev.append((b0 + rng.choice((3, 6)), rng.choice((1.5, 2.5)), 'P', 0))
            if rng.random() < 0.5:
                ev.append((b0 + 8, 1.5, 'P', 0))
            run = rng.choice(((10, 7, 5, 3), (3, 5, 6, 7), (12, 10, 7, 5), (0, 3, 5, 7)))
            start = rng.choice((12, 11)) if b0 == 0 else rng.choice((12, 10))
            for k, iv in enumerate(run):
                if b0 + start + k < b0 + 16:
                    ev.append((b0 + start + k, 0.9, 'N', iv))
    elif family == 'drive':         # stadium 8ths: power chords on every 8th, a lick at the end of bar 2
        for st in range(0, 32, 2):
            if st < 28:
                ev.append((st, 1.7, 'P', 0))
        lick = rng.choice(((7, 5, 3, 0), (10, 7, 5, 3), (3, 5, 7, 10)))
        for k, iv in enumerate(lick):
            ev.append((28 + k, 0.9, 'N', iv))
    elif family == 'chug':          # palm-muted pulse with syncopated power-chord accents and a dark passing note
        accents = rng.choice(((0, 6, 10), (0, 3, 10, 14), (0, 6, 12)))
        for st in range(0, 32, 2):
            ev.append((st, 1.7, 'P', 0) if st % 16 in accents else (st, 0.7, 'M', 0))
        ev = [e for e in ev if e[0] != 30] + [(30, 0.9, 'N', rng.choice((1, 6))), (31, 0.9, 'N', 0)]
    else:                           # pedal16: the low root on every other 16th, a moving line in between
        line = rng.choice(((12, 10, 7, 10), (7, 10, 12, 10), (12, 7, 10, 5), (3, 5, 7, 5)))
        ladder = (0, 3, 5, 7, 10, 12, 15)
        shift = -1 if line[0] > 5 else 1            # the second half of each bar moves one pentatonic step

        def moved(iv):
            return ladder[max(0, min(len(ladder) - 1, ladder.index(iv) + shift))]
        k = 0
        for st in range(32):
            if st % 2 == 0:
                ev.append((st, 0.8, 'P' if st % 16 == 0 else 'D', 0))
            else:
                iv = line[k % len(line)]
                ev.append((st, 0.8, 'N', iv if (st // 8) % 2 == 0 else moved(iv)))
                k += 1
    return tuple(sorted(ev))


# =============================================================================
# Melody
# =============================================================================


PENTA = {'aeolian': (0, 3, 5, 7, 10), 'dorian': (0, 3, 5, 7, 10), 'mixolydian': (0, 2, 4, 7, 9),
         'ionian': (0, 2, 4, 7, 9)}


def _allowed(spec: ExcerptSpec, chord: Chord, strong: bool) -> frozenset[int]:
    allowed = chord.core_pcs(spec.key_pc) if strong else melodic_pcs(chord, spec.key_pc, spec.mode)
    if STYLES[spec.genre].get('pentatonic') and not strong and spec.mode in PENTA:
        penta = {(spec.key_pc + i) % 12 for i in PENTA[spec.mode]}
        allowed = frozenset(allowed & (penta | set(chord.pcs(spec.key_pc)))) or allowed
    return allowed


MAX_LEAP = 9       # a major sixth: wider leaps are refitted to the nearest allowed pitch within it


def fit_line(spec: ExcerptSpec, notes, chord_at, prev=None, prev_deg=None) -> list[tuple[int, int]]:
    """As hiphop.fit_line (strong notes on chord tones, contour kept), plus a leap
    limit: a fitted note more than a major sixth from the previous one moves to
    the nearest allowed pitch within that distance, in the intended direction
    when there is one (no octave displacements inside a phrase)."""
    out = []
    lo, hi = spec.mel_range
    for n in notes:
        c = chord_at(n.step)
        raw = degree_to_midi(n.deg, spec.key_pc, spec.mode, spec.mel_tonic)
        direction = 0 if prev_deg is None else (n.deg > prev_deg) - (n.deg < prev_deg)
        allowed = _allowed(spec, c, n.strong)
        p = directed(raw, prev, direction, allowed, lo, hi)
        if prev is not None and abs(p - prev) > MAX_LEAP:
            near = [q for q in range(lo, hi + 1) if q % 12 in allowed and abs(q - prev) <= MAX_LEAP]
            same_dir = [q for q in near if direction and (q - prev) * direction > 0]
            if near:
                p = min(same_dir or near, key=lambda q: (abs(q - raw), q))
        out.append((n.step, p))
        prev, prev_deg = p, n.deg
    return out


def _ending(m: Motif, targets: tuple[int, ...], hold: bool) -> Motif:
    notes = list(m.notes)
    last = notes[-1]
    deg = min(targets, key=lambda t: (abs(t - last.deg), t))
    dur = (32 - last.step) if hold else last.dur
    notes[-1] = MotifNote(last.step, max(1, min(dur, 32 - last.step)), deg, True)
    return Motif(tuple(notes), m.cells)


def melody_units(spec: ExcerptSpec) -> tuple[Motif, ...]:
    """The statement: motif, open answer (ends on the 2nd / 5th), motif, closed
    cadence (ends on the tonic, held)."""
    m = spec.motif
    return m, _ending(m, (1, 4, -3, 8), False), m, _ending(m, (0, 7, -7), True)


def melody_notes(spec: ExcerptSpec) -> list[tuple[int, float, int, bool]]:
    """(global step, duration in 16ths, pitch, strong) of the 8-bar melody."""
    harm = spec.harmony()
    out, prev, prev_deg = [], None, None
    for u, unit in enumerate(melody_units(spec)):
        line = fit_line(spec, unit.notes, lambda s, u=u: _chord_at(harm, u * 32 + s), prev, prev_deg)
        if u == 3:      # the cadence lands on the tonic: the one nearest the line's approach
            lo, hi = spec.mel_range
            before = line[-2][1] if len(line) > 1 else line[-1][1]
            tonics = [p for p in range(lo, hi + 1) if p % 12 == spec.key_pc]
            line[-1] = (line[-1][0], min(tonics, key=lambda p: (abs(p - before), p)))
        for n, (_, p) in zip(unit.notes, line):
            out.append((u * 32 + n.step, n.dur, p, n.strong))
        prev, prev_deg = line[-1][1], unit.notes[-1].deg
    return out


# =============================================================================
# Realisation helpers
# =============================================================================


class Ctx:
    def __init__(self, spec: ExcerptSpec, tier: int, tempo: float):
        self.spec, self.tier, self.tempo = spec, int(tier), float(tempo)
        self.grid = Grid(self.tempo, spec.swing)
        self.end = self.grid.seg_s
        self.harm = spec.harmony()
        self.rng = _rng('v3genre-real', spec.genre, spec.seed, tier)

    def chord(self, step: float) -> Chord:
        return _chord_at(self.harm, step)

    def note(self, part: _Part, pitch: int, step: float, dur: float, vel: float, lag: float = 0.0,
             jitter: float = 0.0) -> None:
        t = self.grid.t(step) + lag + (self.rng.uniform(-jitter, jitter) if jitter else 0.0)
        t = max(0.0, t)
        part.add(pitch, t, t + dur * self.grid.step_s, vel + self.rng.randint(-3, 3), self.end)

    def changes(self) -> list[int]:
        return [s for s, _ in self.harm]

    def root(self, step: float, lo: int = 31, hi: int = 45) -> int:
        return place(self.chord(step).root_pc(self.spec.key_pc), lo, hi, (lo + hi) / 2)


def _melodic_part(spec: ExcerptSpec, role: str, name: Optional[str] = None) -> _Part:
    prog = spec.program(role)
    return _Part(prog, name or role)


def _drums_part() -> _Part:
    return _Part(0, 'drums', is_drum=True)


def _voicing(ctx: Ctx, chord: Chord, prev, lo: int, hi: int, rootless: bool = False):
    pcs = chord.pcs(ctx.spec.key_pc)
    if rootless and len(pcs) >= 4:
        pcs = pcs[1:]                       # drop the root (3rd, 5th, 7th, tension), the bass has it
    pcs = pcs[:5]
    return lead_voice(pcs, prev, lo, hi, (lo + hi) / 2)


def _comp_hits(ctx: Ctx, part: _Part, pattern, lo: int, hi: int, vel: float, rootless=False, strum=0.0,
               anticip=True, lag=0.0) -> None:
    """Chord hits per bar at (step, dur, accent): each hit voices the chord at
    its step; a hit at step 14-15 anticipates the next bar's chord."""
    prev = None
    for bar in range(BARS):
        for step, dur, acc in pattern:
            g = bar * 16 + step
            chord = ctx.chord(g + 2 if anticip and step >= 14 and bar < BARS - 1 else g)
            v = _voicing(ctx, chord, prev, lo, hi, rootless)
            prev = v
            for i, p in enumerate(v):
                ctx.note(part, p, g, dur, vel * acc, lag=lag + i * strum, jitter=0.004)


def _bass_line(ctx: Ctx, part: _Part, hits, vel: float, lo: int = 31, hi: int = 45, lag=0.0) -> None:
    """hits: per bar (step, dur, degree) with degree 'R' root, '5' fifth, '8'
    octave, 'A' chromatic approach to the next chord's root, 'N' the next
    chord's root (anticipation)."""
    for bar in range(BARS):
        for step, dur, deg in hits(bar):
            if bar == BARS - 1 and deg in 'AN':     # the phrase ends on its own root, no lead-in
                if deg == 'A':
                    continue
                deg = 'R'
            g = bar * 16 + step
            root = ctx.root(g, lo, hi)
            if deg == 'R':
                p = root
            elif deg == '5':
                p = root + 7 if root + 7 <= hi + 2 else root - 5
            elif deg == '8':
                p = root + 12 if root + 12 <= hi + 12 else root
            elif deg == 'N':
                p = ctx.root(min((bar + 1) * 16, SEG - 1), lo, hi)
            else:   # 'A': a semitone below the next root
                nr = ctx.root(min((bar + 1) * 16, SEG - 1), lo, hi)
                p = nr - 1 if nr - 1 >= lo - 2 else nr + 1
            ctx.note(part, p, g, dur, vel, lag=lag, jitter=0.003)


def _melody(ctx: Ctx, part: _Part, vel: float, anchor: bool = False, lag: float = 0.0,
            articulation: float = 0.9, ornament: bool = False, octave: int = 0) -> None:
    notes = melody_notes(ctx.spec)
    if anchor:      # level 1: the strong notes only, held until the next one
        strong = [n for n in notes if n[3]]
        notes = [(g, (strong[i + 1][0] - g) if i + 1 < len(strong) else d, p, s)
                 for i, (g, d, p, s) in enumerate(strong)]
    for i, (g, d, p, strong) in enumerate(notes):
        accent = 1.0 if strong else 0.88
        if ornament and d >= 4 and g % 32 >= 8 and i % 3 == 1:     # a 16th upper-neighbour pickup
            ctx.note(part, p + 2 if (p + 2) % 12 in melodic_pcs(ctx.chord(g), ctx.spec.key_pc, ctx.spec.mode)
                     else p + 1, g - 0.5, 0.45, vel * 0.7, lag=lag)
        ctx.note(part, p + 12 * octave, g, max(0.5, d * articulation), vel * accent, lag=lag, jitter=0.006)


def _finish(spec: ExcerptSpec, tempo: float, parts: list[tuple[_Part, str]],
            pans: Optional[dict] = None) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    for part, role in parts:
        inst = part.finish()
        if not inst.notes:
            continue
        inst.control_changes.append(pretty_midi.ControlChange(7, channel_volume(inst.program, role, spec.genre), 0.0))
        if pans and role in pans:
            inst.control_changes.append(pretty_midi.ControlChange(10, pans[role], 0.0))
        pm.instruments.append(inst)
    return pm


# =============================================================================
# Genre realisations (tier -> layers, rhythmic activity, dynamics)
# =============================================================================


def _pop(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    T, sp, g = ctx.tier, ctx.spec, ctx.spec.groove
    dyn = TIER_DYN[T]
    dr = _drums_part()
    var = {'a': (0, 8, 10), 'b': (0, 6, 8), 'c': (0, 3, 8, 11)}[g]
    for bar in range(BARS):
        b0, last = bar * 16, bar == BARS - 1
        fill = bar in (3, 7) and T >= 3
        if T == 1:
            kicks = (0, 8)
        elif T == 2:
            kicks = var if bar % 2 else (0, 8)
        elif T in (3, 4):
            kicks = var + ((14,) if bar in (3, 7) and T == 4 else ())
        else:
            kicks = (0, 4, 8, 12) + ((14,) if bar == 7 else ())
        for s in kicks:
            ctx.note(dr, KICK, b0 + s, 0.6, (78, 86, 96, 100, 104)[T - 1])
        for s in (4, 12):
            if last and fill and s == 12:
                continue
            ctx.note(dr, SNARE, b0 + s, 0.8, (70, 84, 90, 94, 98)[T - 1])
            if T >= 3:
                ctx.note(dr, CLAP, b0 + s, 0.6, (0, 0, 66, 74, 84)[T - 1])
        if T == 1:
            hats = [(s, 42, CH) for s in (0, 4, 8, 12)]
        elif T in (2, 3):
            hats = [(s, (62 if s % 4 == 0 else 54) + 6 * (T - 2), CH) for s in range(0, 16, 2)]
            if T == 3 and bar in (3, 7):
                hats[-1] = (14, 64, OH)
        elif T == 4:
            hats = [(s, 66 if s % 4 == 0 else 58 if s % 2 == 0 else 44, CH) for s in range(16)]
        else:
            hats = [(s, 60, CH) for s in (0, 4, 8, 12)] + [(s, 72, OH) for s in (2, 6, 10, 14)]
        for s, v, p in hats:
            if fill and last and s >= 12:
                continue
            ctx.note(dr, p, b0 + s, 1.4 if p == OH else 0.5, v)
        if T >= 4:
            for s in ((4, 12) if T == 4 else range(1, 16, 2)):
                ctx.note(dr, TAMB, b0 + s, 0.5, 50 if T == 4 else 40)
        if (T == 4 and bar == 0) or (T == 5 and bar in (0, 4)):
            ctx.note(dr, CRASH, b0, 4, 84)
        if fill and last:
            for k, (s, p) in enumerate(((12, SNARE), (13, SNARE), (14, SNARE), (15, SNARE)) if T == 3 else
                                       ((12, HTOM), (13, HTOM), (14, MTOM), (15, LTOM))):
                ctx.note(dr, p, b0 + s, 0.6, 62 + 8 * k)
    bass = _melodic_part(sp, 'bass')
    figs = {1: lambda b: ((0, 7.5, 'R'), (8, 7.5, 'R')),
            2: lambda b: ((0, 3.5, 'R'), (4, 3.5, 'R'), (8, 3.5, 'R'), (12, 3.5, 'R')),
            3: lambda b: tuple((s, 1.6, 'R') for s in var) + ((14, 1.6, '8'),),
            4: lambda b: ((0, 1.6, 'R'), (2, 1.2, 'R'), (4, 1.6, 'R'), (6, 1.2, '8'), (8, 1.6, 'R'),
                          (10, 1.2, 'R'), (12, 1.6, 'R'), (15, 0.9, 'A')),
            5: lambda b: tuple((s, 1.5, 'R' if s % 4 == 0 else '8') for s in range(0, 16, 2))}
    _bass_line(ctx, bass, figs[T], 90 + dyn)
    comp_prog = sp.program('comp')
    lo, hi = COMP_RANGE.get(comp_prog, (52, 76))
    comp = _melodic_part(sp, 'comp')
    pats = {1: ((0, 7.5, 0.95), (8, 7.5, 0.85)), 2: ((0, 7.5, 0.9), (8, 7.5, 0.8)),
            3: ((0, 5.5, 1.0), (6, 1.8, 0.8), (8, 5.5, 0.9), (14, 1.8, 0.8)),
            4: tuple((s, 1.6, 1.0 if s in (0, 6, 8, 14) else 0.75) for s in range(0, 16, 2)),
            5: tuple((s, 1.6, 1.0 if s in (0, 6, 8, 14) else 0.8) for s in range(0, 16, 2))}
    _comp_hits(ctx, comp, pats[T], lo, hi, 70 + dyn, strum=0.012 if comp_prog == 25 else 0.0)
    lead = _melodic_part(sp, 'lead')
    _melody(ctx, lead, 90 + dyn, anchor=False, articulation=0.85)     # v3.genres.1: the full melody at every tier
    parts = [(dr, 'drums'), (bass, 'bass'), (comp, 'comp'), (lead, 'lead')]
    if T >= 4:
        pad = _Part(sp.program('pad'), 'pad')
        _comp_hits(ctx, pad, ((0, 15.8, 1.0),), 55, 79, 54 + dyn)
        parts.append((pad, 'pad'))
    return _finish(sp, ctx.tempo, parts)


def _rock(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    """Riff-based hard rock. Every tier is driven-guitar rock; the tier sets how
    much is going on: 1 the riff over a plain backbeat (an intro), 2 the full
    riff and 8th-note hats, 3 a second guitar under the riff, 4 a lead guitar
    answering the riff and ride-cymbal drive, 5 the full stadium texture with
    the lead hook throughout, crashes and tom fills."""
    T, sp, g = ctx.tier, ctx.spec, ctx.spec.groove
    dyn = TIER_DYN[T]
    dr = _drums_part()
    var = {'a': (0, 8, 10), 'b': (0, 6, 8), 'c': (0, 8, 10, 14)}[g]
    for bar in range(BARS):
        b0, last = bar * 16, bar == BARS - 1
        fill = last and T >= 3
        kicks = {1: (0, 8), 2: (0, 8) + ((10,) if bar % 2 else ()), 3: var,
                 4: var + ((3,) if bar % 2 else ()), 5: (0, 2, 8, 10)}[T]
        for s in kicks:
            if not (fill and s >= 12):
                ctx.note(dr, KICK, b0 + s, 0.6, (86, 92, 100, 104, 110)[T - 1])
        for s in (4, 12):
            if not (fill and s == 12):
                ctx.note(dr, SNARE, b0 + s, 0.9, (88, 96, 104, 108, 112)[T - 1])
        if T >= 4 and bar % 2 == 1:
            ctx.note(dr, SNARE, b0 + 15, 0.4, 40)
        if T == 1:
            cym = [(s, CH, 60 if s % 8 == 0 else 52) for s in (0, 4, 8, 12)]
        elif T in (2, 3):
            cym = [(s, CH, (66 if s % 4 == 0 else 56) + 4 * (T - 2)) for s in range(0, 16, 2)]
            if T == 3 and bar in (3, 7):
                cym[-1] = (14, OH, 70)
        else:
            cym = [(s, RIDE, 76 if s % 4 == 0 else 66) for s in range(0, 16, 2)]
            if T == 5:
                cym += [(s, BELL, 64) for s in (0, 4, 8, 12)]
        for s, p, v in cym:
            if not (fill and s >= 12):
                ctx.note(dr, p, b0 + s, 1.4 if p == OH else 0.6, v)
        crash = {2: (0,), 3: (0, 4), 4: (0, 4), 5: (0, 2, 4, 6)}.get(T, ())
        if bar in crash:
            ctx.note(dr, CRASH, b0, 6, 90 + 2 * T)
        if fill or (T >= 4 and bar == 3):
            seq = ((12, SNARE), (13, SNARE), (14, SNARE), (15, SNARE)) if T == 3 else \
                  ((12, HTOM), (13, HTOM), (14, MTOM), (15, LTOM)) if bar == 3 else \
                  ((8, HTOM), (9, HTOM), (10, MTOM), (11, MTOM), (12, LTOM), (13, LTOM), (14, SNARE), (15, SNARE))
            for k, (s, p) in enumerate(seq):
                ctx.note(dr, p, b0 + s, 0.5, 74 + 4 * k)
    # the riff: low register, transposed to each chord; level 1 plays its intro form (thin_riff)
    riff = _Part(sp.program('riff'), 'riff')
    roots = []
    events = thin_riff(sp.riff, sp.riff_family) if T == 1 else sp.riff
    for rep in range(BARS // 2):
        for step, dur, kind, iv in events:
            gs = rep * 32 + step
            if gs >= SEG:
                continue
            chord = ctx.chord(gs + 2 if step % 16 >= 14 and kind == 'P' and gs + 2 < SEG and rep * 32 + step >= 0
                              and (gs // 16) < BARS - 1 else gs)
            r = place(chord.root_pc(sp.key_pc), 40, 51, 45)
            v = {'P': 92, 'M': 76, 'N': 86, 'D': 78}[kind] + dyn
            if kind == 'P':
                notes = (r, r + 7, r + 12)
                roots.append((gs, r))
            elif kind == 'M':
                notes = (r, r + 7)
                roots.append((gs, r))
            elif kind == 'D':
                notes = (r,)
            else:
                notes = (r + iv if r + iv <= 64 else r + iv - 12,)
            for p in notes:
                ctx.note(riff, p, gs, dur, v, jitter=0.003)
    parts = [(dr, 'drums'), (riff, 'riff')]
    # second guitar (level 3 up): palm-muted 8ths under stab / pedal riffs, held power chords under 8th riffs
    if T >= 3:
        bed = _Part(sp.program('bed'), 'bed')
        busy = any(k in ('M',) for _, _, k, _ in sp.riff) or sum(k == 'P' for _, _, k, _ in sp.riff) >= 10
        for bar in range(BARS):
            b0 = bar * 16
            r = place(ctx.chord(b0).root_pc(sp.key_pc), 40, 51, 45)
            if busy:
                for s, d in ((0, 7.5), (8, 7.5)) if T < 5 else ((s, 1.7) for s in range(0, 16, 2)):
                    for p in (r, r + 7, r + 12):
                        ctx.note(bed, p, b0 + s, d, 76 + dyn, jitter=0.004)
            else:
                for s in range(0, 16, 2):
                    for p in (r, r + 7):
                        ctx.note(bed, p, b0 + s, 0.7 if T < 5 else 1.7, 72 + dyn, jitter=0.004)
        parts.append((bed, 'bed'))
    # bass: picked roots locked to the riff's chord hits (level 1-2), driving 8ths (level 3 up)
    bass = _melodic_part(sp, 'bass')
    if T <= 2:
        hits = sorted(set(roots))
        for i, (gs, r) in enumerate(hits):
            nxt = hits[i + 1][0] if i + 1 < len(hits) else SEG
            ctx.note(bass, r - 12 if r - 12 >= 28 else r, gs, max(0.8, min(nxt - gs - 0.3, 6)), 90 + dyn, jitter=0.003)
    else:
        figs = {3: lambda b: tuple((s, 1.7, 'R') for s in range(0, 16, 2)),
                4: lambda b: tuple((s, 1.7, '8' if s in (6, 14) else 'R') for s in range(0, 14, 2)) + ((14, 1.7, 'A'),),
                5: lambda b: tuple((s, 1.6, '8' if s in (6, 10) else 'R') for s in range(0, 14, 2)) + ((14, 1.6, 'A'),)}
        _bass_line(ctx, bass, figs[T], 94 + dyn, lo=28, hi=43)
    parts.append((bass, 'bass'))
    # lead guitar: answers the riff in bars 3-4 and 7-8 (level 4), the melodic hook throughout (level 5)
    if T >= 4:
        lead = _Part(sp.program('lead'), 'lead')
        if T == 4:
            keep = [n for n in melody_notes(sp) if (n[0] // 32) % 2 == 1]
            for g_, d, p, strong in keep:
                ctx.note(lead, p, g_, max(0.5, d * 0.85), (90 if strong else 80) + dyn, jitter=0.005)
        else:
            _melody(ctx, lead, 92 + dyn, articulation=0.9)
        parts.append((lead, 'lead'))
    return _finish(sp, ctx.tempo, parts, pans={'riff': 40, 'bed': 88, 'lead': 64})


SON_CLAVE = {'son32': (0, 6, 12, 20, 24), 'son23': (4, 8, 16, 22, 28)}


def _latin(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    T, sp = ctx.tier, ctx.spec
    dyn = TIER_DYN[T]
    dr = _drums_part()
    clave = SON_CLAVE[sp.groove]
    for bar in range(BARS):
        b0, last = bar * 16, bar == BARS - 1
        for s in range(0, 16, 2):                                       # maracas / shaker
            ctx.note(dr, MARACAS, b0 + s, 0.4, (40, 44, 48, 50, 52)[T - 1] + (8 if s % 4 == 0 else 0))
        if T >= 1:
            for s in (k - (bar % 2) * 16 for k in clave if (bar % 2) * 16 <= k < (bar % 2 + 1) * 16):
                ctx.note(dr, CLAVES, b0 + s, 0.4, (46, 64, 72, 76, 78)[T - 1])
        if T >= 2:                                                       # conga tumbao
            ctx.note(dr, MCONGA, b0 + 4, 0.4, 70 + dyn)
            ctx.note(dr, OCONGA, b0 + 12, 0.5, 74 + dyn)
            ctx.note(dr, OCONGA, b0 + 14, 0.5, 70 + dyn)
            if T >= 3:
                ctx.note(dr, LCONGA, b0 + 6, 0.5, 64 + dyn)
            ctx.note(dr, GUIRO_L, b0 + 0, 1.5, 50 + dyn)
            for s in (2, 3, 8, 10, 11):
                ctx.note(dr, GUIRO_S, b0 + s, 0.4, 44 + dyn)
        if T >= 3:                                                       # bongo martillo + soft bombo
            for s in range(0, 16, 2):
                ctx.note(dr, LBONGO if s in (6, 14) else HBONGO, b0 + s, 0.4, (64 if s in (6, 14) else 50) + dyn)
            ctx.note(dr, KICK, b0 + (6 if bar % 2 else 12), 0.5, 66 + dyn)
        if T >= 4:
            for s in (0, 4, 8, 12):
                ctx.note(dr, COWBELL, b0 + s, 0.5, 72 if s % 8 == 0 else 62)
        if T == 5 and bar in (3, 7):
            for k, s in enumerate((12, 13, 14, 15)):
                ctx.note(dr, HTIMB if k < 2 else LTIMB, b0 + s, 0.4, 76 + 4 * k)
        if T == 5 and bar == 0:
            ctx.note(dr, CRASH, b0, 4, 80)
        del last
    bass = _melodic_part(sp, 'bass')
    figs = {1: lambda b: (((0, 11.5, 'R'),) if b == 0 else ((0, 5.5, 'R'),)) + ((12, 3.8, 'N'),),
            2: lambda b: (((0, 5.5, 'R'),) if b == 0 else ()) + ((6, 5.5, '5'), (12, 3.8, 'N')),
            3: lambda b: (((0, 5.5, 'R'),) if b == 0 else ()) + ((6, 3.5, '5'), (10, 1.6, 'R'), (12, 3.8, 'N')),
            4: lambda b: (((0, 5.5, 'R'),) if b == 0 else ()) + ((6, 3.5, '5'), (10, 1.6, '8'), (12, 3.8, 'N')),
            5: lambda b: (((0, 3.5, 'R'),) if b == 0 else ((3, 1.0, 'R'),)) + ((6, 3.5, '5'), (10, 1.6, '8'),
                                                                              (12, 3.8, 'N'))}
    _bass_line(ctx, bass, figs[T], 92 + dyn, lo=31, hi=45)
    comp = _melodic_part(sp, 'comp')
    cprog = sp.program('comp')
    if T == 1:                                                           # block chords on the clave
        pat_by_bar = lambda bar: tuple((k - (bar % 2) * 16, 1.8, 1.0) for k in clave  # noqa: E731
                                       if (bar % 2) * 16 <= k < (bar % 2 + 1) * 16)
        for bar in range(BARS):
            for step, dur, acc in pat_by_bar(bar):
                v = _voicing(ctx, ctx.chord(bar * 16 + step), None, 55, 76)
                for p in v:
                    ctx.note(comp, p, bar * 16 + step, dur, (66 + dyn) * acc, jitter=0.004)
    else:
        _montuno(ctx, comp, octaves=T >= 3 and cprog == 0, vel=74 + dyn, pickups=T >= 4)
    lead = _melodic_part(sp, 'lead')
    _melody(ctx, lead, 88 + dyn, anchor=T == 1, articulation=0.85, ornament=T >= 3)
    return _finish(sp, ctx.tempo, [(dr, 'drums'), (bass, 'bass'), (comp, 'comp'), (lead, 'lead')])


MONTUNO_STEPS = (0, 4, 6, 10, 12, 14)        # guajeo-like 8th-note figure with offbeat accents


def _montuno(ctx: Ctx, part: _Part, octaves: bool, vel: float, pickups: bool) -> None:
    sp = ctx.spec
    k = 0
    for bar in range(BARS):
        for s in MONTUNO_STEPS + ((15,) if pickups and bar % 2 else ()):
            g = bar * 16 + s
            chord = ctx.chord(g + 2 if s >= 14 and bar < BARS - 1 else g)
            tones = sorted({place(pc, 64, 76, 70) for pc in chord.core_pcs(sp.key_pc)})
            top = tones[k % len(tones)] if (k // len(tones)) % 2 == 0 else tones[-1 - k % len(tones)]
            k += 1
            acc = 1.0 if s in (4, 10, 14) else 0.85
            ctx.note(part, top, g, 1.6, vel * acc, jitter=0.003)
            if octaves:
                ctx.note(part, top - 12, g, 1.6, vel * acc * 0.85, jitter=0.003)
            if s in (0, 6, 12):
                inner = [t for t in tones if t < top]
                if inner:
                    ctx.note(part, inner[-1] - (12 if octaves else 0), g, 1.6, vel * 0.7)


def _rnb(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    T, sp, g = ctx.tier, ctx.spec, ctx.spec.groove
    dyn = TIER_DYN[T]
    dr = _drums_part()
    var = {'a': (0, 10, 11), 'b': (0, 3, 10), 'c': (0, 7, 10)}[g]
    for bar in range(BARS):
        b0 = bar * 16
        kicks = {1: (0, 10), 2: var, 3: var, 4: var + ((14,) if bar % 2 else ()), 5: var + (14,)}[T]
        for s in kicks:
            ctx.note(dr, KICK, b0 + s, 0.6, (70, 82, 92, 96, 100)[T - 1])
        if T == 1:
            ctx.note(dr, SIDE, b0 + 8, 0.6, 70)
        else:
            ctx.note(dr, SNARE, b0 + 8, 0.8, (0, 82, 90, 94, 98)[T - 1])
            if T >= 3:
                ctx.note(dr, CLAP, b0 + 8, 0.6, (0, 0, 60, 70, 80)[T - 1])
                for s in (6, 14):
                    ctx.note(dr, SNARE, b0 + s, 0.4, 30)
        if T <= 2:
            for s in range(0, 16, 2):
                ctx.note(dr, CH, b0 + s, 0.5, (46, 54)[T - 1] + (6 if s % 4 == 0 else 0))
        else:
            for s in range(16):
                if T >= 4 and s >= 12 and bar % 2 == 1:
                    continue
                ctx.note(dr, CH, b0 + s, 0.4, 58 if s % 4 == 0 else 50 if s % 2 == 0 else 38)
            if T >= 4 and bar % 2 == 1:                              # triplet / 32nd roll into the next bar
                sub = (12, 12 + 4 / 3, 12 + 8 / 3) if T == 4 else tuple(12 + 0.5 * i for i in range(8))
                for i, s in enumerate(sub):
                    ctx.note(dr, CH, b0 + s, 0.25, 44 + 3 * i)
        if T >= 4:
            for s in range(1, 16, 2):
                ctx.note(dr, MARACAS, b0 + s, 0.3, 30)
            if bar % 2 == 1:
                ctx.note(dr, OH, b0 + 14, 1.2, 56)
        if T == 5 and bar == 0:
            ctx.note(dr, CRASH, b0, 4, 76)
    bass = _melodic_part(sp, 'bass')

    def kick_bass(bar, extra=(), approach=False):
        ks = {1: (0, 10), 2: var, 3: var, 4: var, 5: var}[T]
        hits = sorted(set(ks) | set(extra))
        end = 15 if approach and bar < BARS - 1 else 16
        out = []
        for i, s in enumerate(hits):
            nxt = hits[i + 1] if i + 1 < len(hits) else end
            out.append((s, max(0.8, nxt - s - 0.4), 'R'))
        return tuple(out) + (((15, 0.8, 'A'),) if approach else ())
    figs = {1: lambda b: ((0, 9.5, 'R'), (10, 5.5, 'R')),
            2: lambda b: kick_bass(b),
            3: lambda b: kick_bass(b, (6,), True),
            4: lambda b: kick_bass(b, (6, 13), True),
            5: lambda b: kick_bass(b, (3, 6, 13), True)}
    _bass_line(ctx, bass, figs[T], 92 + dyn, lo=28, hi=43)
    comp = _melodic_part(sp, 'comp')
    pats = {1: ((0, 15.5, 0.85),), 2: ((0, 5.5, 1.0), (10, 3.5, 0.8)),
            3: ((0, 2.5, 1.0), (6, 1.8, 0.8), (10, 1.8, 0.85), (14, 1.8, 0.8)),
            4: ((0, 2.5, 1.0), (6, 1.8, 0.8), (10, 1.8, 0.85), (14, 1.8, 0.8)),
            5: ((0, 2.5, 1.0), (3, 1.2, 0.7), (6, 1.8, 0.8), (10, 1.8, 0.85), (14, 1.8, 0.8))}
    _comp_hits(ctx, comp, pats[T], 52, 76, 70 + dyn, rootless=True)
    lead = _melodic_part(sp, 'lead')
    _melody(ctx, lead, 88 + dyn, anchor=T == 1, articulation=0.9, ornament=T >= 3)
    parts = [(dr, 'drums'), (bass, 'bass'), (comp, 'comp'), (lead, 'lead')]
    if T >= 4:
        pad = _Part(sp.program('pad'), 'pad')
        _comp_hits(ctx, pad, ((0, 15.8, 1.0),), 55, 79, 52 + dyn, rootless=True)
        parts.append((pad, 'pad'))
    return _finish(sp, ctx.tempo, parts)


def _lofi(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    T, sp, g = ctx.tier, ctx.spec, ctx.spec.groove
    dyn = TIER_DYN[T]
    lag_snare, lag_keys = 0.020, 0.016
    dr = _drums_part()
    var = {'a': (0, 10), 'b': (0, 7, 10), 'c': (0, 3, 10)}[g]
    for bar in range(BARS):
        b0 = bar * 16
        kicks = {1: (0, 10), 2: var, 3: var}.get(T, var + (14,))
        for s in kicks:
            ctx.note(dr, KICK, b0 + s, 0.6, (64, 72, 78, 82, 86)[T - 1])
        for s in (4, 12):
            ctx.note(dr, SIDE if T == 1 else SNARE, b0 + s, 0.8, (52, 64, 70, 74, 78)[T - 1], lag=lag_snare)
        for s in range(0, 16, 2):
            ctx.note(dr, CH, b0 + s, 0.5, (32, 40, 46, 50, 54)[T - 1] + (6 if s % 4 == 0 else 0))
        if T >= 2:
            ctx.note(dr, SNARE, b0 + 15, 0.3, 22 + 2 * T, lag=lag_snare)     # ghost into the downbeat
        if T >= 3:
            for s in range(1, 16, 2):
                ctx.note(dr, MARACAS, b0 + s, 0.3, 24 + 2 * T)
            if bar in (3, 7):
                ctx.note(dr, OH, b0 + 14, 1.2, 40)
    bass = _melodic_part(sp, 'bass')
    figs = {1: lambda b: ((0, 7.5, 'R'), (10, 4.5, 'R')),
            2: lambda b: ((0, 6.5, 'R'), (8, 1.6, '5'), (10, 4.5, 'R')),
            3: lambda b: ((0, 5.5, 'R'), (6, 1.6, '5'), (8, 1.6, '8'), (10, 3.5, 'R'), (14, 1.6, 'A'))}
    _bass_line(ctx, bass, figs.get(T, figs[3]), 84 + dyn, lo=28, hi=43, lag=0.010)
    comp = _melodic_part(sp, 'comp')
    pats = {1: ((0, 15.5, 0.85),), 2: ((0, 7.5, 0.95), (10, 5.5, 0.8))}
    _comp_hits(ctx, comp, pats.get(T, pats[2]), 52, 76, 66 + dyn, rootless=True, strum=0.022, lag=lag_keys)
    parts = [(dr, 'drums'), (bass, 'bass'), (comp, 'comp')]
    if T >= 3:          # broken-chord arpeggio in the upper register
        arp = _Part(sp.program('comp'), 'arp')
        for bar in range(BARS):
            tones = sorted({place(pc, 67, 84, 75) for pc in ctx.chord(bar * 16).pcs(sp.key_pc)})
            order = tones + tones[-2:0:-1]
            for i, s in enumerate(range(0, 16, 2)):
                ctx.note(arp, order[i % len(order)], bar * 16 + s, 1.8, 50 + dyn, lag=lag_keys, jitter=0.006)
        parts.append((arp, 'arp'))
    lead = _melodic_part(sp, 'lead')
    _melody(ctx, lead, 84 + dyn, anchor=T == 1, lag=0.010, articulation=0.95)
    parts.append((lead, 'lead'))
    if T >= 4:
        pad = _Part(sp.program('pad'), 'pad')
        _comp_hits(ctx, pad, ((0, 15.8, 1.0),), 55, 79, 48 + dyn, rootless=True)
        parts.append((pad, 'pad'))
    return _finish(sp, ctx.tempo, parts)


def _calm(ctx: Ctx) -> pretty_midi.PrettyMIDI:
    T, sp = ctx.tier, ctx.spec
    dyn = TIER_DYN[T]
    # the original calm configuration's light pulse (kick, quarter hats, rim on beat 3), mixed well under the piano
    dr = _drums_part()
    for bar in range(BARS):
        b0 = bar * 16
        ctx.note(dr, KICK, b0, 0.6, 64)
        if T >= 2:
            ctx.note(dr, KICK, b0 + 8, 0.6, 52)
        ctx.note(dr, SIDE, b0 + 8, 0.6, 46)
        for s in ((0, 4, 8, 12) if T == 1 else range(0, 16, 2)):
            ctx.note(dr, CH, b0 + s, 0.4, (40 if s % 4 == 0 else 28))
    rh = _Part(sp.program('comp'), 'piano_rh')
    lh = _Part(sp.program('bass'), 'piano_lh')
    for bar in range(BARS):
        b0 = bar * 16
        chord = ctx.chord(b0)
        root = ctx.root(b0, 36, 50)
        ctx.note(lh, root, b0, 15.5, 62 + dyn)
        if T >= 2:
            ctx.note(lh, root + 7 if root + 7 <= 55 else root - 5, b0 + 8, 7.5, 52 + dyn)
        tones = sorted({place(pc, 55, 74, 64) for pc in chord.pcs(sp.key_pc)})
        if T == 1:          # rolled chord on beat 1, re-rolled softly on beat 3
            for i, p in enumerate(tones):
                ctx.note(rh, p, b0, 15.5 - i * 0.4, 58 + dyn - 2 * i, lag=0.045 * i)
            for i, p in enumerate(tones[1:]):
                ctx.note(rh, p, b0 + 8, 7.5, 44 + dyn, lag=0.05 * i)
        else:               # flowing broken chord in 8ths
            order = tones + tones[-2:0:-1]
            for i, s in enumerate(range(0, 16, 2)):
                ctx.note(rh, order[i % len(order)], b0 + s, 3.5, (56 if s % 8 == 0 else 48) + dyn, jitter=0.008)
    lead = _melodic_part(sp, 'lead')
    _melody(ctx, lead, 70 + dyn, anchor=T == 1, articulation=1.0)
    return _finish(sp, ctx.tempo, [(dr, 'drums'), (lh, 'lh'), (rh, 'comp'), (lead, 'lead')])


REALIZE = {'pop': _pop, 'rock': _rock, 'latin': _latin, 'rnb': _rnb, 'lofi': _lofi, 'calm': _calm}


def tier_tempo(genre: str, tier: int) -> float:
    from composer import GENRE_CFG

    cfg = GENRE_CFG[genre]
    return float(cfg.get('tier_tempo', {}).get(int(tier), cfg['tempo_default']))


def realize(spec: ExcerptSpec, tier: int, tempo: Optional[float] = None) -> pretty_midi.PrettyMIDI:
    return REALIZE[spec.genre](Ctx(spec, tier, tempo or tier_tempo(spec.genre, tier)))


def excerpt_info(spec: ExcerptSpec, tier: int, tempo: float) -> dict:
    names = lambda bars: '-'.join('/'.join(Chord(r, q).name(spec.key_pc) for r, q in bar)  # noqa: E731
                                  for bar in bars)
    return {'generator': 'v3', 'gen_version': GEN_VERSION, 'genre': spec.genre, 'tier': int(tier),
            'seed': spec.seed, 'composition_id': spec.name(), 'tempo_bpm': float(tempo),
            'key': f"{'C C# D Eb E F F# G Ab A Bb B'.split()[spec.key_pc]} {spec.mode}", 'mode': spec.mode,
            'swing': spec.swing, 'progression': names(spec.loop), 'cadence': names(spec.cadence),
            'palette': ','.join(f'{r}:{p}' for r, p in spec.palette), 'groove': spec.groove,
            'motif_cells': '/'.join(spec.motif.cells), 'role': 'S', 'bars': BARS}


# =============================================================================
# Excerpt API (all seven genres)
# =============================================================================


def compose_excerpt(genre: str, tier: int, seed: int) -> tuple[pretty_midi.PrettyMIDI, dict, object]:
    """(MIDI, info, spec or plan) of one 8-bar statement for a (genre, tier)
    condition at the condition's tempo. Hip-hop is the approved v3 hip-hop
    generator's statement section (form position 2) at level = tier."""
    if genre == 'hiphop':
        from composer.v3.hiphop import plan_segment, realize as hh_realize, segment_info
        from composer.v3.source import HipHopV3Source

        state = HipHopV3Source(seed, tempo_policy='tier').current_state()
        plan = plan_segment(replace(state, ordinal=1), int(tier))
        tempo = tier_tempo('hiphop', tier)
        info = {**segment_info(plan), 'generator': 'v3', 'genre': 'hiphop', 'tier': int(tier), 'seed': seed,
                'tempo_bpm': tempo, 'mix_trim_db': state.spec.mix_trim_db, 'levels_table': 'FluidR3_GM'}
        return hh_realize(plan, tempo), info, plan
    spec = create_spec(genre, seed)
    tempo = tier_tempo(genre, tier)
    return realize(spec, tier, tempo), excerpt_info(spec, tier, tempo), spec


# =============================================================================
# Rule checks (structural; not evidence of musical quality)
# =============================================================================

RANGES = {'bass': (24, 57), 'comp': (36, 88), 'lead': (48, 100), 'pad': (40, 88), 'arp': (55, 96),
          'guitar': (36, 84), 'piano_rh': (48, 96), 'piano_lh': (28, 62), 'riff': (36, 76), 'bed': (36, 70)}
BACKBONE = {   # (drum pitch, steps in bar that must sound in every bar, from tier)
    'pop': ((KICK, (0,), 1), (SNARE, (4, 12), 2)),
    'rock': ((KICK, (0,), 1), (SNARE, (4, 12), 1)),
    'rnb': ((KICK, (0,), 1), (SNARE, (8,), 2), (SIDE, (8,), 1)),
    'lofi': ((KICK, (0,), 1),),
    'latin': ((MARACAS, (0,), 1), (OCONGA, (12,), 2)),
    'calm': ((KICK, (0,), 1), (SIDE, (8,), 1)),
}


def rule_violations(pm: pretty_midi.PrettyMIDI, spec: ExcerptSpec, tier: int) -> list[str]:
    tempo = tier_tempo(spec.genre, tier)
    grid = Grid(tempo, spec.swing)
    bad: list[str] = []
    tempi = pm.get_tempo_changes()[1]
    if len(tempi) != 1 or abs(tempi[0] - tempo) > 1e-6:
        bad.append('tempo')
    inst = {i.name: i for i in pm.instruments}
    for i in pm.instruments:
        if not i.is_drum and i.program in VOCAL_PROGRAMS:
            bad.append(f'vocal_program:{i.name}')
        lo, hi = RANGES.get(i.name, (0, 127))
        by_pitch: dict = {}
        for n in i.notes:
            if not (1 <= n.velocity <= 127) or n.end <= n.start or n.start < 0 or n.end > grid.seg_s + 1e-6:
                bad.append(f'note_invalid:{i.name}')
                break
            if not i.is_drum and not lo <= n.pitch <= hi:
                bad.append(f'range:{i.name}:{n.pitch}')
                break
            by_pitch.setdefault(n.pitch, []).append(n)
        for ns in by_pitch.values():
            ns.sort(key=lambda n: n.start)
            if any(a.end > b.start + 1e-6 for a, b in zip(ns, ns[1:])):
                bad.append(f'same_pitch_overlap:{i.name}')
                break
    if 'drums' not in inst:
        bad.append('missing:drums')
    needs = ('bass',) if spec.genre != 'calm' else ('piano_lh',)
    needs += ('riff',) if spec.genre == 'rock' else ()
    needs += ('lead',) if spec.genre != 'rock' or tier >= 4 else ()
    for need in needs:
        if need not in inst:
            bad.append(f'missing:{need}')
    if bad and any(b.startswith('missing') for b in bad):
        return bad
    steps = [grid.t(s) for s in range(SEG + 1)]

    def step_of(t):
        k = min(range(len(steps)), key=lambda j: abs(steps[j] - t))
        return k if abs(steps[k] - t) < 0.035 else None
    # drum backbone
    if 'drums' in inst:
        on = {}
        for n in inst['drums'].notes:
            k = step_of(n.start)
            if k is not None:
                on.setdefault(n.pitch, set()).add(k)
        for pitch, req, from_tier in BACKBONE[spec.genre]:
            if tier < from_tier or (pitch == SIDE and tier >= 2 and spec.genre == 'rnb'):
                continue
            for bar in range(BARS):
                for s in req:
                    if bar * 16 + s not in on.get(pitch, set()) and not (bar == BARS - 1 and s >= 12):
                        bad.append(f'backbone:{pitch}@bar{bar + 1}:{s}')
    harm = spec.harmony()

    def pcs_around(k, anticip=True):
        pcs = set(_chord_at(harm, k).pcs(spec.key_pc))
        if anticip and k % 16 >= 12:
            pcs |= set(_chord_at(harm, min(k - k % 16 + 16, SEG - 1)).pcs(spec.key_pc))
        return pcs
    # bass: chord tones (approach notes at steps 13-15 allowed), the root at bar 1
    bass = inst.get('bass') or inst.get('piano_lh')
    for n in bass.notes:
        k = step_of(n.start)
        if k is None or k % 16 >= 13:
            continue
        if n.pitch % 12 not in pcs_around(k):
            bad.append(f'bass_not_chord_tone:{k}')
            break
    first = min(bass.notes, key=lambda n: n.start)
    if first.pitch % 12 != _chord_at(harm, 0).root_pc(spec.key_pc):
        bad.append('bass_first_not_root')
    # melody: strong notes on chord tones, the last note the tonic
    for g, d, p, strong in melody_notes(spec):
        c = _chord_at(harm, g)
        if strong and p % 12 not in c.core_pcs(spec.key_pc):
            bad.append(f'melody_strong_not_chord_tone:{g}')
        elif p % 12 not in melodic_pcs(c, spec.key_pc, spec.mode) | set(c.pcs(spec.key_pc)):
            bad.append(f'melody_avoid_note:{g}')
    if melody_notes(spec)[-1][2] % 12 != spec.key_pc:
        bad.append('melody_does_not_close_on_tonic')
    if _chord_at(harm, SEG - 1).root_pc(spec.key_pc) != spec.key_pc:
        bad.append('phrase_does_not_end_on_tonic')
    # comping: chord tones of the current or anticipated chord
    for name in ('comp', 'guitar', 'pad', 'arp', 'piano_rh', 'bed'):
        if name not in inst:
            continue
        for n in inst[name].notes:
            k = step_of(n.start)
            if k is not None and n.pitch % 12 not in pcs_around(k):
                bad.append(f'{name}_not_chord_tone:{k}')
                break
    # rock riff: power chords and riff notes from the chord root's blues-pentatonic set
    if 'riff' in inst:
        for n in inst['riff'].notes:
            k = step_of(n.start)
            if k is None:
                continue
            roots = {_chord_at(harm, k).root_pc(spec.key_pc)}
            if k % 16 >= 12:
                roots.add(_chord_at(harm, min(k - k % 16 + 16, SEG - 1)).root_pc(spec.key_pc))
            if not any((n.pitch - r) % 12 in {0, 1, 3, 5, 6, 7, 10} for r in roots):
                bad.append(f'riff_out_of_scale:{k}')
                break
    return bad
