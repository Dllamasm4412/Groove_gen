"""
GrooveGen composer — rule-based symbolic MIDI generator.

Public API (locked signature — do not change):

    generate_segment(genre, tempo_bpm=None, density=0.5, duration_bars=8, seed=42,
                     velocity_boost=None) -> pretty_midi.PrettyMIDI

    GENRE_CFG: dict[str, dict]  — per-genre configuration (tempo range, instruments, etc.)

Genres: 'calm', 'pop', 'rnb', 'latin'.

History
-------
Consolidated Stage 2 composer, four iterations:
  - v3 all-rule-based composer (dropped MIDI-GPT; Colab Cell 6 v3)
  - Cell 6b sound tweaks (pop lead = acoustic guitar GM 25, +12 velocity boost)
  - Cell 6c density patch (density now scales ornaments in rnb + latin)
  - v1.1 sound polish from Musyng render feedback:
      * calm: piano louder + stepwise melodic arpeggio (was random picks)
      * calm: drums louder (kick +15, rim +20, hh +20)
      * rnb: hihat = straight 8ths at all densities (was swung 16ths)

Verified on bank_v1: 108 segments generated, density spread ~68-78% across
d=0.3/0.6/0.9 for all four genres. Bank_v1 was generated with pre-v1.1 rules;
any NEW renders from this module will use v1.1 sound.

Design principle: density scales ORNAMENTS, not skeleton. The base groove
(chord holds, bass root pattern, kick/snare skeleton) is always present so
every output is musically coherent. Higher density adds hihat resolution,
ghost notes, offbeat guitar hits, syncopated accents.
"""

from __future__ import annotations

import random
import pretty_midi


# =============================================================================
# Genre configuration
# =============================================================================

GENRE_CFG: dict[str, dict] = {
    'calm': dict(
        strategy='rule_based_ambient',
        tempo_default=65, tempo_range=(60, 70),
        key_signature='F major',
        instruments={'pad': 89, 'piano': 0, 'strings': 48},
        chord_palette=['Fmaj', 'Fsus4', 'Fadd9', 'Gadd9', 'Emin7', 'Dadd9'],
        include_drums=False,
        notes_per_sec_target=2.5,
    ),
    'rnb': dict(
        strategy='rule_based',
        tempo_default=100, tempo_range=(90, 115),
        key_signature='D minor',
        instruments={'ep': 4, 'bass': 33, 'other': 0},
        include_drums=True, drum_program=0,
        notes_per_sec_target=3.5,
    ),
    'pop': dict(
        strategy='rule_based',
        tempo_default=118, tempo_range=(100, 130),
        key_signature='C major',
        # 6b tweak: acoustic guitar (GM 25) as lead — softer than 80s square
        instruments={'ep': 4, 'bass': 33, 'other': 25},
        include_drums=True, drum_program=0,
        notes_per_sec_target=4.0,
    ),
    'latin': dict(
        strategy='rule_based',
        tempo_default=104, tempo_range=(95, 120),
        key_signature='C minor',
        instruments={'nylon_guitar': 24, 'bass': 33, 'other': 0},
        include_drums=True, drum_program=0,
        notes_per_sec_target=4.6,
    ),
}


# =============================================================================
# Chord helpers
# =============================================================================

_ROOT_PC = {'C': 0, 'C#': 1, 'D': 2, 'D#': 3, 'E': 4, 'F': 5, 'F#': 6,
            'G': 7, 'G#': 8, 'A': 9, 'A#': 10, 'B': 11}

_QUAL_INTERVALS = {
    'maj':   [0, 4, 7],
    'min':   [0, 3, 7],
    'sus4':  [0, 5, 7],
    'sus2':  [0, 2, 7],
    'add9':  [0, 4, 7, 14],
    'madd9': [0, 3, 7, 14],
    'maj7':  [0, 4, 7, 11],
    'min7':  [0, 3, 7, 10],
    '7':     [0, 4, 7, 10],
    '6':     [0, 4, 7, 9],
    'm6':    [0, 3, 7, 9],
}


def _split_chord(chord_str: str) -> tuple[str, str]:
    if len(chord_str) >= 2 and chord_str[1] == '#':
        return chord_str[:2], chord_str[2:]
    return chord_str[:1], chord_str[1:]


def chord_pitches(chord_str: str, octave: int = 4) -> list[int]:
    root, qual = _split_chord(chord_str)
    pc = _ROOT_PC.get(root)
    intervals = _QUAL_INTERVALS.get(qual, [0, 4, 7])
    if pc is None:
        return []
    base = 12 * octave + pc
    return [base + iv for iv in intervals]


def chord_root_pitch(chord_str: str, octave: int = 2) -> int:
    root, _ = _split_chord(chord_str)
    pc = _ROOT_PC.get(root, 0)
    return 12 * octave + pc


# =============================================================================
# Genre 1: CALM (rule-based ambient)
# =============================================================================

def _gen_calm(tempo_bpm, duration_bars, seed, cfg, density):
    """
    Calm: ambient pad + stepwise melodic piano + soft drums.

    v1.1 tweaks (from user feedback on Musyng renders):
      - Piano is now a stepwise arpeggio phrase (up-down through chord tones),
        not random note-picks. Sounds like a melody, not a shuffle.
      - Piano velocity 75-100 (was 55-80).
      - Drum velocities bumped: kick 70->85, rim 45->65, hh 35->55.
    """
    rng = random.Random(seed)
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    seconds_per_bar = 4 * 60 / tempo_bpm
    beat_duration = seconds_per_bar / 4
    total_s = duration_bars * seconds_per_bar

    pad = pretty_midi.Instrument(program=cfg['instruments']['pad'], name='pad')
    piano = pretty_midi.Instrument(program=cfg['instruments']['piano'], name='piano')
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='drums')

    palette = cfg['chord_palette']
    chords_per_segment = max(2, duration_bars // 2)
    chord_sequence = [rng.choice(palette) for _ in range(chords_per_segment)]
    chord_duration = total_s / chords_per_segment

    for i, chord in enumerate(chord_sequence):
        start = i * chord_duration
        end = start + chord_duration

        # Pad: hold full chord for the duration
        for p in chord_pitches(chord, octave=3):
            if 0 <= p <= 127:
                pad.notes.append(pretty_midi.Note(
                    velocity=68, pitch=p, start=start, end=end))

        # Piano: stepwise arpeggio phrase (melodic, not random)
        # Walk up-then-down through chord tones + one extension.
        # Density controls how many notes fit into the chord's duration.
        arp_tones = chord_pitches(chord, octave=5)
        # Build a melodic contour: up then down, with an octave leap for variety
        contour = arp_tones + [arp_tones[0] + 12] + arp_tones[::-1]
        # Rotate start position deterministically per chord for variety across bars
        start_offset = rng.randint(0, len(contour) - 1)
        contour = contour[start_offset:] + contour[:start_offset]

        n_notes = max(2, int(density * 8))
        # Space notes evenly across the chord duration, ~half-note to eighth-note rhythm
        step = chord_duration / n_notes
        for j in range(n_notes):
            p = contour[j % len(contour)]
            if not (0 <= p <= 127):
                continue
            t = start + j * step + rng.uniform(-0.03, 0.03)  # tiny humanization
            # Overlapping tail creates flowing feel; last note holds through chord end
            hold = step * rng.uniform(1.4, 2.2) if j < n_notes - 1 else (end - t)
            piano.notes.append(pretty_midi.Note(
                velocity=rng.randint(75, 100), pitch=p, start=t,
                end=min(end, t + max(0.15, hold))))

    # Soft drums: kick 1&3, rim 3, hh every beat -- louder than v1
    n_beats = int(duration_bars * 4)
    for beat_idx in range(n_beats):
        t = beat_idx * beat_duration
        b = beat_idx % 4
        if b == 0:
            drums.notes.append(pretty_midi.Note(velocity=85, pitch=36, start=t, end=t + 0.1))
        elif b == 2:
            drums.notes.append(pretty_midi.Note(velocity=70, pitch=36, start=t, end=t + 0.1))
            drums.notes.append(pretty_midi.Note(velocity=65, pitch=37, start=t, end=t + 0.1))
        drums.notes.append(pretty_midi.Note(velocity=55, pitch=42, start=t, end=t + 0.08))

    pm.instruments.extend([pad, piano, drums])
    return pm


# =============================================================================
# Genre 2: POP (rule-based)
# Design: I-V-vi-IV in C major. EP chord stabs + syncopated bass + acoustic
# guitar lead + 4-on-floor drums with clap on 2/4.
# =============================================================================

_POP_PROGRESSION_C = ['Cmaj7', 'Gmaj', 'Amin7', 'Fmaj7']


def _gen_pop(tempo_bpm, duration_bars, seed, cfg, density):
    rng = random.Random(seed)
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    seconds_per_bar = 4 * 60 / tempo_bpm
    beat_duration = seconds_per_bar / 4
    sixteenth = beat_duration / 4

    ep = pretty_midi.Instrument(program=cfg['instruments']['ep'], name='ep')
    bass = pretty_midi.Instrument(program=cfg['instruments']['bass'], name='bass')
    lead = pretty_midi.Instrument(program=cfg['instruments']['other'], name='lead')
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='drums')

    prog = _POP_PROGRESSION_C
    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar

        # EP: syncopated chord stabs on beats 1, 2.5, 4
        stab_times = [0.0, 2.5 * beat_duration, 3.0 * beat_duration]
        for st_off in stab_times:
            t = bar_start + st_off
            for p in chord_pitches(chord, octave=4):
                if 0 <= p <= 127:
                    ep.notes.append(pretty_midi.Note(
                        velocity=rng.randint(72, 88), pitch=p, start=t,
                        end=t + beat_duration * 0.4))

        # Bass: root pattern
        root = chord_root_pitch(chord, octave=2)
        for beat_off in [0.0, 2.0, 3.5]:
            t = bar_start + beat_off * beat_duration
            bass.notes.append(pretty_midi.Note(
                velocity=90, pitch=root, start=t,
                end=t + beat_duration * (0.9 if beat_off in [0.0, 2.0] else 0.5)))

        # Lead: density-scaled melodic hook
        lead_notes_per_bar = max(2, int(density * 8))
        lead_pitches = chord_pitches(chord, octave=5) + [chord_pitches(chord, octave=5)[0] + 12]
        for _ in range(lead_notes_per_bar):
            offset_16th = rng.randint(0, 15)
            t = bar_start + offset_16th * sixteenth
            p = rng.choice(lead_pitches)
            if 0 <= p <= 127:
                lead.notes.append(pretty_midi.Note(
                    velocity=rng.randint(65, 82), pitch=p, start=t,
                    end=t + sixteenth * rng.randint(2, 4)))

    # 4-on-floor kick, clap 2&4, closed hh every 8th, open hh on 4-and
    n_beats = int(duration_bars * 4)
    for beat_idx in range(n_beats):
        t = beat_idx * beat_duration
        b = beat_idx % 4
        drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
        if b in [1, 3]:
            drums.notes.append(pretty_midi.Note(velocity=95, pitch=39, start=t, end=t + 0.1))
        drums.notes.append(pretty_midi.Note(velocity=60, pitch=42, start=t, end=t + 0.06))
        drums.notes.append(pretty_midi.Note(
            velocity=55, pitch=42,
            start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.06))
        if b == 3:
            drums.notes.append(pretty_midi.Note(
                velocity=70, pitch=46,
                start=t + beat_duration * 0.5, end=t + beat_duration * 0.6))

    pm.instruments.extend([ep, bass, lead, drums])
    return pm


# =============================================================================
# Genre 3: RNB (rule-based, density-patched v2)
# Design: D minor, F#min7-Dsus2-Emin7-Cadd9. EP sus voicings + walking bass
# + swung hihat + snare 2&4 with ghost notes. Density controls ornament count.
# =============================================================================

_RNB_PROGRESSION_Dm = ['F#min7', 'Dsus2', 'Emin7', 'Cadd9']


def _gen_rnb(tempo_bpm, duration_bars, seed, cfg, density):
    rng = random.Random(seed)
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    seconds_per_bar = 4 * 60 / tempo_bpm
    beat_duration = seconds_per_bar / 4
    sixteenth = beat_duration / 4

    ep = pretty_midi.Instrument(program=cfg['instruments']['ep'], name='ep')
    bass = pretty_midi.Instrument(program=cfg['instruments']['bass'], name='bass')
    other = pretty_midi.Instrument(program=cfg['instruments']['other'], name='keys')
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='drums')

    prog = _RNB_PROGRESSION_Dm
    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar

        # SKELETON: EP long-held chord
        for p in chord_pitches(chord, octave=4):
            if 0 <= p <= 127:
                ep.notes.append(pretty_midi.Note(
                    velocity=78, pitch=p, start=bar_start,
                    end=bar_start + seconds_per_bar * 0.95))

        # SKELETON: upper-voice color on beat 3
        color_pitches = chord_pitches(chord, octave=5)[:2]
        t3 = bar_start + 2 * beat_duration
        for p in color_pitches:
            if 0 <= p <= 127:
                other.notes.append(pretty_midi.Note(
                    velocity=65, pitch=p, start=t3,
                    end=t3 + beat_duration * 1.5))

        # ORNAMENT: extra keys stabs on offbeats (d>=0.5)
        if density >= 0.5:
            n_extra = int(density * 4)
            available_offbeats = [0.5, 1.5, 2.5, 3.5]
            picks = rng.sample(available_offbeats, min(n_extra, len(available_offbeats)))
            for off in picks:
                t = bar_start + off * beat_duration
                for p in chord_pitches(chord, octave=5)[:2]:
                    if 0 <= p <= 127:
                        other.notes.append(pretty_midi.Note(
                            velocity=rng.randint(55, 70), pitch=p, start=t,
                            end=t + beat_duration * 0.4))

        # SKELETON: bass root pattern
        root = chord_root_pitch(chord, octave=2)
        pitches_5th = chord_pitches(chord, octave=2)
        fifth = pitches_5th[2] if len(pitches_5th) >= 3 else root + 7
        bass_pattern = [(0.0, root), (1.5, root + 12), (2.0, fifth), (3.0, root)]
        for beat_off, pitch in bass_pattern:
            t = bar_start + beat_off * beat_duration
            if 0 <= pitch <= 127:
                bass.notes.append(pretty_midi.Note(
                    velocity=88, pitch=pitch, start=t,
                    end=t + beat_duration * 0.9))

        # ORNAMENT: bass grace note (d>=0.7)
        if density >= 0.7:
            t = bar_start + 3.75 * beat_duration
            grace = root + rng.choice([-1, 1, 2])
            if 0 <= grace <= 127:
                bass.notes.append(pretty_midi.Note(
                    velocity=70, pitch=grace, start=t,
                    end=t + sixteenth * 0.9))

    # Drums: skeleton always; hihat is now straight 8ths at ALL densities.
    # v1.1 change: dropped swung 16th hihat (user found it busy). Density now
    # scales ONLY ghost snares and bass grace notes, NOT hihat resolution.
    n_beats = int(duration_bars * 4)
    for beat_idx in range(n_beats):
        t = beat_idx * beat_duration
        b = beat_idx % 4
        # SKELETON: kick
        if b == 0:
            drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
        if b == 2:
            drums.notes.append(pretty_midi.Note(
                velocity=90, pitch=36,
                start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.1))
        # SKELETON: snare 2&4
        if b in [1, 3]:
            drums.notes.append(pretty_midi.Note(velocity=95, pitch=38, start=t, end=t + 0.1))

        # Hihat: straight 8ths (downbeat + offbeat of each beat)
        drums.notes.append(pretty_midi.Note(
            velocity=55, pitch=42, start=t, end=t + 0.05))
        drums.notes.append(pretty_midi.Note(
            velocity=50, pitch=42,
            start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.05))

        # ORNAMENT: ghost snares
        if density >= 0.6 and b == 3:
            drums.notes.append(pretty_midi.Note(
                velocity=35, pitch=38, start=t - sixteenth * 3,
                end=t - sixteenth * 3 + 0.05))
        if density >= 0.8 and b == 0:
            drums.notes.append(pretty_midi.Note(
                velocity=30, pitch=38, start=t + sixteenth,
                end=t + sixteenth + 0.05))

    pm.instruments.extend([ep, bass, other, drums])
    return pm


# =============================================================================
# Genre 4: LATIN (rule-based, density-patched v2)
# Design: C minor, i-VII-VI-V. Nylon guitar montuno + tumbao bass + clave
# alternating 3-2/2-3 + congas + kick 1&3. Density controls ornament count.
# =============================================================================

_LATIN_PROGRESSION_Cm = ['Cmin', 'A#maj', 'G#maj', 'Gmaj']


def _gen_latin(tempo_bpm, duration_bars, seed, cfg, density):
    rng = random.Random(seed)
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo_bpm)
    seconds_per_bar = 4 * 60 / tempo_bpm
    beat_duration = seconds_per_bar / 4
    eighth = beat_duration / 2
    sixteenth = beat_duration / 4

    guitar = pretty_midi.Instrument(program=cfg['instruments']['nylon_guitar'], name='nylon')
    bass = pretty_midi.Instrument(program=cfg['instruments']['bass'], name='bass')
    other = pretty_midi.Instrument(program=cfg['instruments']['other'], name='piano')
    drums = pretty_midi.Instrument(program=0, is_drum=True, name='perc')

    prog = _LATIN_PROGRESSION_Cm
    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar

        # Nylon guitar montuno: density-scaled offbeat count
        # d=0.3 -> 2 offbeats, d=0.6 -> 3, d=0.9 -> 4
        all_offbeats = [0.5, 1.5, 2.5, 3.5]
        n_off = max(2, min(4, int(round(density * 4)) + 1))
        offbeats = all_offbeats[:n_off] if density < 0.9 else all_offbeats
        upper_voicing = chord_pitches(chord, octave=4)
        for off in offbeats:
            t = bar_start + off * beat_duration
            for p in upper_voicing[:3]:
                if 0 <= p <= 127:
                    guitar.notes.append(pretty_midi.Note(
                        velocity=rng.randint(70, 85), pitch=p, start=t,
                        end=t + eighth * 0.9))

        # SKELETON: piano on beats 1, 3
        piano_voicing = chord_pitches(chord, octave=5)[:2]
        for beat_off in [0.0, 2.0]:
            t = bar_start + beat_off * beat_duration
            for p in piano_voicing:
                if 0 <= p <= 127:
                    other.notes.append(pretty_midi.Note(
                        velocity=65, pitch=p, start=t,
                        end=t + beat_duration * 1.3))

        # ORNAMENT: piano fill on beat 4 (d>=0.7)
        if density >= 0.7:
            t = bar_start + 3.0 * beat_duration
            for p in piano_voicing:
                if 0 <= p <= 127:
                    other.notes.append(pretty_midi.Note(
                        velocity=60, pitch=p, start=t,
                        end=t + beat_duration * 0.7))

        # SKELETON: tumbao bass
        root = chord_root_pitch(chord, octave=2)
        fifth_arr = chord_pitches(chord, octave=2)
        fifth = fifth_arr[2] if len(fifth_arr) >= 3 else root + 7
        tumbao = [(0.0, root, 0.5), (1.5, root + 12, 0.5),
                  (2.0, fifth, 1.0), (3.5, root, 0.5)]
        for beat_off, pitch, hold_beats in tumbao:
            t = bar_start + beat_off * beat_duration
            if 0 <= pitch <= 127:
                bass.notes.append(pretty_midi.Note(
                    velocity=92, pitch=pitch, start=t,
                    end=t + beat_duration * hold_beats * 0.9))

        # ORNAMENT: bass syncopation (d>=0.6)
        if density >= 0.6:
            t = bar_start + 2.75 * beat_duration
            if 0 <= root + 12 <= 127:
                bass.notes.append(pretty_midi.Note(
                    velocity=78, pitch=root + 12, start=t,
                    end=t + sixteenth * 0.9))

    # Drums: skeleton (clave + kick) always; congas scale with density
    for bar_idx in range(duration_bars):
        bar_start = bar_idx * seconds_per_bar

        # SKELETON: clave 3-2 / 2-3 alternating
        if bar_idx % 2 == 0:
            clave_positions = [0, 3, 6, 10, 12]  # 3-2
        else:
            clave_positions = [4, 6, 10, 13, 15]  # 2-3
        for pos in clave_positions:
            t = bar_start + pos * sixteenth
            drums.notes.append(pretty_midi.Note(velocity=85, pitch=75, start=t, end=t + 0.05))

        # SKELETON: kick 1 & 3
        for beat_off in [0, 2]:
            t = bar_start + beat_off * beat_duration
            drums.notes.append(pretty_midi.Note(velocity=95, pitch=36, start=t, end=t + 0.1))

        # Congas — density-scaled
        if density < 0.5:
            # d<0.5: beat-level only (4 congas per bar)
            for beat_idx in range(4):
                t = bar_start + beat_idx * beat_duration
                pitch = 63 if beat_idx % 2 == 0 else 64
                drums.notes.append(pretty_midi.Note(
                    velocity=70, pitch=pitch, start=t, end=t + 0.06))
        else:
            # d>=0.5: 8th-note congas
            for eighth_idx in range(8):
                t = bar_start + eighth_idx * eighth
                pitch = 63 if eighth_idx % 2 == 0 else 64
                drums.notes.append(pretty_midi.Note(
                    velocity=70, pitch=pitch, start=t, end=t + 0.06))
            # ORNAMENT: 16th-note syncopated accents (d>=0.8)
            if density >= 0.8:
                for sixteenth_pos in [3, 7, 11, 15]:
                    t = bar_start + sixteenth_pos * sixteenth
                    drums.notes.append(pretty_midi.Note(
                        velocity=55, pitch=64, start=t, end=t + 0.05))

    pm.instruments.extend([guitar, bass, other, drums])
    return pm


# =============================================================================
# Dispatch + public API
# =============================================================================

_GENERATORS = {
    'calm':  _gen_calm,
    'pop':   _gen_pop,
    'rnb':   _gen_rnb,
    'latin': _gen_latin,
}

# Velocity boost applied to all melodic (non-drum) tracks post-generation.
# From Cell 6b — raises perceived loudness without touching drum dynamics.
DEFAULT_VELOCITY_BOOST = 12


def generate_segment(genre: str, tempo_bpm: int | None = None,
                     density: float = 0.5, duration_bars: int = 8,
                     seed: int = 42,
                     velocity_boost: int | None = None) -> pretty_midi.PrettyMIDI:
    """
    Generate one MIDI segment. Deterministic given (genre, tempo, density, seed).

    Parameters
    ----------
    genre : {'calm', 'pop', 'rnb', 'latin'}
    tempo_bpm : int | None
        Clamped to the genre's tempo_range. If None, uses genre's tempo_default.
    density : float in [0, 1]
        Controls ornament count (not skeleton). Skeleton always present.
    duration_bars : int
        Length in 4/4 bars. 8 is the standard M0.5 segment length.
    seed : int
        RNG seed — same seed produces bit-identical MIDI.
    velocity_boost : int | None
        Added to every non-drum note's velocity (clamped at 127).
        None uses DEFAULT_VELOCITY_BOOST.

    Returns
    -------
    pretty_midi.PrettyMIDI
    """
    assert genre in GENRE_CFG, f'unknown genre {genre!r}; known: {list(GENRE_CFG)}'
    cfg = GENRE_CFG[genre]

    if tempo_bpm is None:
        tempo_bpm = cfg['tempo_default']
    lo, hi = cfg['tempo_range']
    tempo_bpm = max(lo, min(hi, tempo_bpm))

    pm = _GENERATORS[genre](tempo_bpm, duration_bars, seed, cfg, density)

    # Post-gen velocity boost (drums untouched)
    boost = DEFAULT_VELOCITY_BOOST if velocity_boost is None else velocity_boost
    if boost != 0:
        for inst in pm.instruments:
            if inst.is_drum:
                continue
            for note in inst.notes:
                note.velocity = min(127, note.velocity + boost)

    return pm


if __name__ == '__main__':
    # Smoke test — generate one of each genre and print stats.
    for g in ['calm', 'pop', 'rnb', 'latin']:
        pm = generate_segment(g, density=0.6, duration_bars=8, seed=42)
        n_notes = sum(len(i.notes) for i in pm.instruments)
        dur = pm.get_end_time()
        print(f'{g:6}: {n_notes:4d} notes, {dur:.2f}s, {n_notes/dur:.1f} notes/s')
