"""
GrooveGen composer — rule-based symbolic MIDI generator.

Public API (locked signature — do not change):

    generate_segment(genre, tempo_bpm=None, density=0.5, duration_bars=8, seed=42,
                     velocity_boost=None) -> pretty_midi.PrettyMIDI

    GENRE_CFG: dict[str, dict]  — per-genre configuration (tempo range, instruments, etc.)

Genres: 'calm', 'lofi', 'pop', 'rnb', 'latin', 'hiphop', 'rock' (the last two
delegate to composer/hiphop_cell.py and composer/rock_cell.py).

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
  - v1.2 second pass on calm mix:
      * calm pad velocity 68 -> 40 (was drowning the piano)
      * calm piano velocity 75-100 -> 100-118 (near max, cuts through)
  - v1.3 wider seed influence (Option 1, non-repetition upgrade):
      * Seed now picks among N idiomatic variants for each genre's
        voicing family, bass pattern, drum ornament template, and
        melodic contour. Same seed still produces bit-identical MIDI
        (determinism preserved), but *different* seeds diverge
        substantially — position-for-position pitch match rate
        target ~40-50% (was 89%).
      * Public API unchanged: generate_segment(genre, tempo_bpm,
        density, duration_bars, seed) still returns PrettyMIDI.
  - v1.4 drum-pattern variants (Move 1, perceptual variety):
      * Pitch match dropped from 89% to 11%, but perceptually pop still
        felt similar because the drum groove was bit-identical across
        seeds. Drums dominate perception; identical drums = same song.
      * v1.4 adds 4 drum-pattern variants per drum-having genre (pop,
        rnb, latin). Seed picks one. All variants within a genre are
        constrained to matched drum-hit count (±15%) and matched
        on-beat/off-beat ratio so percussive_ratio and beat_consistency
        stay in the arousal envelope Sophia's regression assumes.
      * Variants documented in _POP_DRUM_VARIANTS, _RNB_DRUM_VARIANTS,
        _LATIN_DRUM_VARIANTS below.
  - v1.5 latin closed hi-hat (2026-09-25): latin had no hi-hat at any tier
    and measured below its neighbours on the ladder; adds quarter / 8th /
    8th + 16th-pickup hats by density. All other latin notes unchanged.

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
    'lofi': dict(
        # Bridges calm (no drums, arousal ~3.5-4.0) and rnb (full groove,
        # arousal ~5.0-6.1). Warm Rhodes EP, soft bass, gentle drums, slow
        # tempo. Same rule-based scaffold as rnb but softened velocities and
        # slower BPM.
        strategy='rule_based_lofi',
        tempo_default=78, tempo_range=(70, 88),
        key_signature='D minor',
        instruments={'ep': 4, 'bass': 33, 'other': 0},
        include_drums=True, drum_program=0,
        notes_per_sec_target=2.8,
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
    # hiphop and rock delegate to the frozen cell modules (composer/*_cell.py).
    # Those cells derive their internal tier from tempo, so tier_tempo gives
    # the per-tier tempo (copied from the cell's _TIER_TEMPO) for the session
    # loop. velocity_boost=0: the cells are tuned without the +12 boost.
    'hiphop': dict(
        strategy='cell',
        tempo_default=90, tempo_range=(85, 96),
        tier_tempo={1: 85, 2: 87, 3: 90, 4: 93, 5: 96},
        key_signature='minor (seeded)',
        instruments={},  # set by composer/hiphop_cell.py (piano, bass, lead)
        include_drums=True, drum_program=0,
        notes_per_sec_target=4.0,
        velocity_boost=0,
    ),
    'rock': dict(
        strategy='cell',
        tempo_default=120, tempo_range=(110, 130),
        tier_tempo={1: 110, 2: 115, 3: 120, 4: 125, 5: 130},
        key_signature='major (seeded)',
        instruments={},  # set by composer/rock_cell.py (guitar, bass)
        include_drums=True, drum_program=0,
        notes_per_sec_target=4.8,
        velocity_boost=0,
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

    # v1.3: seed picks a rotation of the palette so the chord sequence
    # actually differs across seeds (was: rng.choice already varied but the
    # first chord's identity dominates perceptually)
    palette_base = cfg['chord_palette']
    palette_shift = rng.randint(0, len(palette_base) - 1)
    palette = palette_base[palette_shift:] + palette_base[:palette_shift]
    arp_direction = rng.choice(['up-down', 'down-up', 'up-only', 'zigzag'])

    chords_per_segment = max(2, duration_bars // 2)
    chord_sequence = [rng.choice(palette) for _ in range(chords_per_segment)]
    chord_duration = total_s / chords_per_segment

    for i, chord in enumerate(chord_sequence):
        start = i * chord_duration
        end = start + chord_duration

        # Pad: hold full chord (v1.2: lowered to 40 so piano leads)
        for p in chord_pitches(chord, octave=3):
            if 0 <= p <= 127:
                pad.notes.append(pretty_midi.Note(
                    velocity=40, pitch=p, start=start, end=end))

        # Piano: stepwise arpeggio phrase (melodic, not random)
        # Walk up-then-down through chord tones + one extension.
        # Density controls how many notes fit into the chord's duration.
        arp_tones = chord_pitches(chord, octave=5)
        # Build a melodic contour, direction chosen by seed variant
        if arp_direction == 'up-down':
            contour = arp_tones + [arp_tones[0] + 12] + arp_tones[::-1]
        elif arp_direction == 'down-up':
            contour = arp_tones[::-1] + [arp_tones[0]] + arp_tones
        elif arp_direction == 'up-only':
            contour = arp_tones + [arp_tones[0] + 12] + arp_tones + [arp_tones[-1] + 12]
        else:  # zigzag
            contour = [arp_tones[i % len(arp_tones)] for i in [0, 2, 1, 3, 0, 2]]
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
                velocity=rng.randint(100, 118), pitch=p, start=t,
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

# Four rotating progressions in C major — same tonal center, different flavors
_POP_PROGRESSIONS_C = [
    ['Cmaj7', 'Gmaj',  'Amin7', 'Fmaj7'],   # I-V-vi-IV (classic)
    ['Amin7', 'Fmaj7', 'Cmaj7', 'Gmaj'],    # vi-IV-I-V (axis rotation)
    ['Cmaj7', 'Amin7', 'Fmaj7', 'Gmaj'],    # I-vi-IV-V (50s)
    ['Fmaj7', 'Gmaj',  'Amin7', 'Cmaj7'],   # IV-V-vi-I (ascending)
]

_POP_STAB_PATTERNS = [
    [0.0, 2.5, 3.0],                # v1 syncopated stabs
    [0.0, 1.5, 2.5],                # push-2-and
    [0.0, 2.0, 3.5],                # backbeat plus
    [0.5, 1.5, 2.5, 3.5],           # all offbeats
]

_POP_BASS_PATTERNS = [
    [(0.0, 0), (2.0, 0), (3.5, 0)],           # root only
    [(0.0, 0), (2.0, 0), (3.5, 7)],           # root-root-fifth
    [(0.0, 0), (2.0, 7), (3.5, 0)],           # root-fifth-root
    [(0.0, 0), (1.5, 0), (2.0, 7), (3.5, 0)],  # walking-ish
]

# Pop drum variants (v1.4). Each variant is a callable that takes
# (drums, n_beats, beat_duration) and appends notes. Designs constrained
# to matched hit-count (~28-32 hits per bar including hihat 8ths) and
# strong downbeat/backbeat presence so percussive_ratio and beat_consistency
# stay in the arousal envelope Sophia's regression assumes.
#
# Drum pitches: 36=kick, 38=snare, 39=clap, 42=closed hh, 46=open hh, 44=pedal hh
_POP_DRUM_VARIANTS = ['four_on_floor', 'half_time', 'dembow', 'trap_flavor']


def _apply_pop_drums(drums, variant, duration_bars, beat_duration, sixteenth):
    """Emit drum notes into `drums` per the named pop groove variant."""
    n_beats = int(duration_bars * 4)

    if variant == 'four_on_floor':
        # v1 pattern: kick every beat, clap 2&4, closed hh 8ths, open hh 4-and
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

    elif variant == 'half_time':
        # Half-time feel: heavy snare on 3, kick on 1 & 3-and, ghost kick on 2-and.
        # Hihat 8ths + additional 8th-and ghosts so hit-count sits in band with
        # four_on_floor (target ~120 hits across 8 bars).
        for beat_idx in range(n_beats):
            t = beat_idx * beat_duration
            b = beat_idx % 4
            # Kick on 1 (strong)
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=105, pitch=36, start=t, end=t + 0.1))
            # Kick push on 3-and
            if b == 2:
                drums.notes.append(pretty_midi.Note(
                    velocity=90, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.1))
            # Ghost kick on 2-and (matches Sophia coefficient for kick density)
            if b == 1:
                drums.notes.append(pretty_midi.Note(
                    velocity=70, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.08))
            # Heavy snare on 3
            if b == 2:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=39, start=t, end=t + 0.1))
            # Soft clap on 4 for backbeat presence (keeps beat_consistency in band)
            if b == 3:
                drums.notes.append(pretty_midi.Note(velocity=75, pitch=39, start=t, end=t + 0.08))
            # Hihat 8ths
            drums.notes.append(pretty_midi.Note(velocity=62, pitch=42, start=t, end=t + 0.06))
            drums.notes.append(pretty_midi.Note(
                velocity=55, pitch=42,
                start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.06))

    elif variant == 'dembow':
        # Dembow-adjacent reggaeton feel: kick 1 & 1.75, snare 2 & 4, tight hh 8ths.
        # Downbeat kick still strong — keeps beat_consistency in band.
        for beat_idx in range(n_beats):
            t = beat_idx * beat_duration
            b = beat_idx % 4
            # Kick pattern: 1, 1-and-and (1.75), 3, 3-and-and
            if b == 0 or b == 2:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
                drums.notes.append(pretty_midi.Note(
                    velocity=80, pitch=36,
                    start=t + beat_duration * 0.75, end=t + beat_duration * 0.75 + 0.08))
            # Snare (clap) on 2 & 4
            if b in [1, 3]:
                drums.notes.append(pretty_midi.Note(velocity=95, pitch=39, start=t, end=t + 0.1))
            # Tight closed hh, straight 8ths
            drums.notes.append(pretty_midi.Note(velocity=58, pitch=42, start=t, end=t + 0.05))
            drums.notes.append(pretty_midi.Note(
                velocity=52, pitch=42,
                start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.05))

    elif variant == 'trap_flavor':
        # Trap flavor: kick 1 + syncopated push, snare on 3, hihat 16ths.
        # Hihat 16ths would inflate hit-count — so we alternate 8th/16th
        # per beat to keep total hit-count matched.
        for beat_idx in range(n_beats):
            t = beat_idx * beat_duration
            b = beat_idx % 4
            # Kick on 1 + syncopated push on 2.5
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=105, pitch=36, start=t, end=t + 0.1))
            if b == 1:
                drums.notes.append(pretty_midi.Note(
                    velocity=85, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.08))
            if b == 3:
                drums.notes.append(pretty_midi.Note(
                    velocity=80, pitch=36,
                    start=t + beat_duration * 0.25, end=t + beat_duration * 0.25 + 0.08))
            # Snare on 3 (heavy backbeat rather than 2&4)
            if b == 2:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=38, start=t, end=t + 0.1))
            # Hihat: alternate 8th vs 16th per beat (matched hit count)
            if b % 2 == 0:
                # 8th note grid on this beat
                drums.notes.append(pretty_midi.Note(velocity=58, pitch=42, start=t, end=t + 0.05))
                drums.notes.append(pretty_midi.Note(
                    velocity=50, pitch=42,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.05))
            else:
                # 16th roll on this beat (4 hits)
                for i in range(4):
                    drums.notes.append(pretty_midi.Note(
                        velocity=50 - (i % 2) * 8, pitch=42,
                        start=t + i * sixteenth,
                        end=t + i * sixteenth + 0.04))

    else:
        raise ValueError(f'unknown pop drum variant: {variant!r}')


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

    # v1.3: seed-driven variant selection (Option 1 — wider seed influence)
    prog        = _POP_PROGRESSIONS_C[rng.randint(0, len(_POP_PROGRESSIONS_C) - 1)]
    stabs_off   = _POP_STAB_PATTERNS[rng.randint(0, len(_POP_STAB_PATTERNS) - 1)]
    bass_off    = _POP_BASS_PATTERNS[rng.randint(0, len(_POP_BASS_PATTERNS) - 1)]
    # Lead phrase seed for melodic contour (Markov walk over chord tones)
    contour_walk = rng.choice(['up', 'down', 'zigzag', 'arch'])
    # Section structure over duration (A-A, A-B, A-B-A-B etc.)
    n_sections = max(1, duration_bars // 2)
    section_map = [rng.choice(['A', 'B']) for _ in range(n_sections)]

    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar
        section = section_map[(bar_idx // 2) % len(section_map)]

        # EP: syncopated chord stabs — pattern varies by variant
        # B-section: shifted stabs (sparser feel)
        stab_beats = stabs_off if section == 'A' else stabs_off[:max(2, len(stabs_off) - 1)]
        for st_beat in stab_beats:
            t = bar_start + st_beat * beat_duration
            for p in chord_pitches(chord, octave=4):
                if 0 <= p <= 127:
                    ep.notes.append(pretty_midi.Note(
                        velocity=rng.randint(72, 88), pitch=p, start=t,
                        end=t + beat_duration * 0.4))

        # Bass: variant-selected pattern (root/fifth semitone offsets)
        root = chord_root_pitch(chord, octave=2)
        for beat_off, semitone_off in bass_off:
            t = bar_start + beat_off * beat_duration
            pitch = root + semitone_off
            if 0 <= pitch <= 127:
                bass.notes.append(pretty_midi.Note(
                    velocity=90, pitch=pitch, start=t,
                    end=t + beat_duration * (0.9 if beat_off in [0.0, 2.0] else 0.5)))

        # Lead: density-scaled melodic contour (was random-choice, now walk)
        lead_notes_per_bar = max(2, int(density * 8))
        chord_tones = chord_pitches(chord, octave=5)
        pitch_pool = chord_tones + [chord_tones[0] + 12]
        # Build a contour walk instead of random picks
        if contour_walk == 'up':
            idxs = list(range(len(pitch_pool)))
        elif contour_walk == 'down':
            idxs = list(range(len(pitch_pool)))[::-1]
        elif contour_walk == 'arch':
            idxs = list(range(len(pitch_pool))) + list(range(len(pitch_pool)))[::-1]
        else:  # zigzag
            idxs = [0, 2, 1, 3, 2, len(pitch_pool) - 1]
        idx_start = rng.randint(0, len(idxs) - 1)
        rotated = idxs[idx_start:] + idxs[:idx_start]

        for k in range(lead_notes_per_bar):
            offset_16th = (k * (16 // max(1, lead_notes_per_bar))
                           + rng.randint(0, 2)) % 16
            t = bar_start + offset_16th * sixteenth
            p = pitch_pool[rotated[k % len(rotated)] % len(pitch_pool)]
            if 0 <= p <= 127:
                lead.notes.append(pretty_midi.Note(
                    velocity=rng.randint(65, 82), pitch=p, start=t,
                    end=t + sixteenth * rng.randint(2, 4)))

    # v1.4: seed-selected drum groove variant (Move 1)
    drum_variant = _POP_DRUM_VARIANTS[rng.randint(0, len(_POP_DRUM_VARIANTS) - 1)]
    _apply_pop_drums(drums, drum_variant, duration_bars, beat_duration, sixteenth)

    pm.instruments.extend([ep, bass, lead, drums])
    return pm


# =============================================================================
# Genre 3: RNB (rule-based, density-patched v2)
# Design: D minor, F#min7-Dsus2-Emin7-Cadd9. EP sus voicings + walking bass
# + swung hihat + snare 2&4 with ghost notes. Density controls ornament count.
# =============================================================================

# Four rotating progressions in D minor — same tonal center, different flavors
_RNB_PROGRESSIONS_Dm = [
    ['F#min7', 'Dsus2', 'Emin7', 'Cadd9'],   # v1 (F# min pocket)
    ['Dsus2',  'Cadd9', 'F#min7', 'Emin7'],   # rotation
    ['F#min7', 'Emin7', 'Dsus2',  'Cadd9'],   # descending flavor
    ['Cadd9',  'F#min7', 'Emin7', 'Dsus2'],   # start-on-IV
]

_RNB_BASS_PATTERNS = [
    [(0.0, 0), (1.5, 12), (2.0, 7), (3.0, 0)],   # v1 root-oct-fifth-root
    [(0.0, 0), (2.0, 0),  (3.5, 12)],             # sparse root-plus-octave
    [(0.0, 0), (1.0, 7),  (2.0, 0), (3.0, 5)],    # walk (root-5-root-4)
    [(0.0, 0), (1.5, 7),  (2.5, 12), (3.0, 0)],   # syncopated walking
]

# R&B drum variants (v1.4). All keep snare on 2&4 (backbeat identity) and
# straight-8th hihat (beat_consistency in band). Variation is in kick pattern,
# ghost placement, and hihat accent shape. Hit-count target ~72 per 8 bars.
_RNB_DRUM_VARIANTS = ['neo_soul', 'boom_bap', 'j_dilla', 'gospel_pocket']


def _apply_rnb_drums(drums, variant, duration_bars, beat_duration, sixteenth, density, rng):
    """Emit R&B drum notes per variant. Preserves 2&4 snare + 8th hihat."""
    n_beats = int(duration_bars * 4)

    for beat_idx in range(n_beats):
        t = beat_idx * beat_duration
        b = beat_idx % 4

        # === KICK PATTERN varies by variant ===
        if variant == 'neo_soul':
            # v1 pattern: kick on 1 + 3-and
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
            if b == 2:
                drums.notes.append(pretty_midi.Note(
                    velocity=90, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.1))
        elif variant == 'boom_bap':
            # Boom-bap kick: 1 and 2-and (D'Angelo/Roots pocket)
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=102, pitch=36, start=t, end=t + 0.1))
            if b == 1:
                drums.notes.append(pretty_midi.Note(
                    velocity=88, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.1))
            # Extra kick on 4-e (16th push) for hit-count parity
            if b == 3:
                drums.notes.append(pretty_midi.Note(
                    velocity=75, pitch=36,
                    start=t + sixteenth, end=t + sixteenth + 0.08))
        elif variant == 'j_dilla':
            # Dilla-style loose kick: 1, 2.5, 3.75 with slight timing push
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
            if b == 1:
                drums.notes.append(pretty_midi.Note(
                    velocity=85, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.1))
            if b == 2:
                drums.notes.append(pretty_midi.Note(
                    velocity=78, pitch=36,
                    start=t + beat_duration * 0.75, end=t + beat_duration * 0.75 + 0.08))
        elif variant == 'gospel_pocket':
            # Gospel/pocket: kick 1, 3, plus a 4-and pickup
            if b == 0:
                drums.notes.append(pretty_midi.Note(velocity=100, pitch=36, start=t, end=t + 0.1))
            if b == 2:
                drums.notes.append(pretty_midi.Note(velocity=95, pitch=36, start=t, end=t + 0.1))
            if b == 3:
                drums.notes.append(pretty_midi.Note(
                    velocity=80, pitch=36,
                    start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.08))

        # === SNARE on 2&4 (all variants — R&B identity) ===
        if b in [1, 3]:
            drums.notes.append(pretty_midi.Note(velocity=95, pitch=38, start=t, end=t + 0.1))

        # === HIHAT/CYMBAL 8ths (variant picks the voice, keeps 8th grid for
        # beat_consistency parity) ===
        # Pitches: 42=closed hh, 44=pedal hh, 46=open hh, 51=ride bell
        if variant == 'neo_soul':
            hh_pitch, hh_off_pitch = 42, 42       # v1 closed 8ths
        elif variant == 'boom_bap':
            hh_pitch, hh_off_pitch = 42, 44       # closed / pedal alternating (chop feel)
        elif variant == 'j_dilla':
            hh_pitch, hh_off_pitch = 51, 51       # ride bell 8ths (looser)
        else:  # gospel_pocket
            hh_pitch, hh_off_pitch = 42, 46       # closed / open alternating (church feel)
        drums.notes.append(pretty_midi.Note(
            velocity=55, pitch=hh_pitch, start=t, end=t + 0.05))
        drums.notes.append(pretty_midi.Note(
            velocity=50, pitch=hh_off_pitch,
            start=t + beat_duration * 0.5, end=t + beat_duration * 0.5 + 0.05))

        # === ORNAMENTS density-scaled (matches v1.3 rules) ===
        if density >= 0.6 and b == 3:
            drums.notes.append(pretty_midi.Note(
                velocity=35, pitch=38, start=t - sixteenth * 3,
                end=t - sixteenth * 3 + 0.05))
        if density >= 0.8 and b == 0:
            drums.notes.append(pretty_midi.Note(
                velocity=30, pitch=38, start=t + sixteenth,
                end=t + sixteenth + 0.05))


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

    # v1.3: seed picks progression, bass pattern, and voicing octave
    prog        = _RNB_PROGRESSIONS_Dm[rng.randint(0, len(_RNB_PROGRESSIONS_Dm) - 1)]
    bass_pat    = _RNB_BASS_PATTERNS[rng.randint(0, len(_RNB_BASS_PATTERNS) - 1)]
    ep_octave   = rng.choice([4, 4, 3])   # occasional darker voicing
    color_octave = rng.choice([5, 5, 6])
    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar

        # SKELETON: EP long-held chord (voicing octave varies by variant)
        for p in chord_pitches(chord, octave=ep_octave):
            if 0 <= p <= 127:
                ep.notes.append(pretty_midi.Note(
                    velocity=78, pitch=p, start=bar_start,
                    end=bar_start + seconds_per_bar * 0.95))

        # SKELETON: upper-voice color on beat 3
        color_pitches = chord_pitches(chord, octave=color_octave)[:2]
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

        # SKELETON: bass — variant-selected pattern
        root = chord_root_pitch(chord, octave=2)
        for beat_off, semitone_off in bass_pat:
            t = bar_start + beat_off * beat_duration
            pitch = root + semitone_off
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

    # v1.4: seed-selected drum variant (Move 1)
    drum_variant = _RNB_DRUM_VARIANTS[rng.randint(0, len(_RNB_DRUM_VARIANTS) - 1)]
    _apply_rnb_drums(drums, drum_variant, duration_bars, beat_duration, sixteenth, density, rng)

    pm.instruments.extend([ep, bass, other, drums])
    return pm


# =============================================================================
# Genre 4: LATIN (rule-based, density-patched v2)
# Design: C minor, i-VII-VI-V. Nylon guitar montuno + tumbao bass + clave
# alternating 3-2/2-3 + congas + kick 1&3. Density controls ornament count.
# =============================================================================

# Four rotating progressions in C minor — same tonal center, different flavors
_LATIN_PROGRESSIONS_Cm = [
    ['Cmin', 'A#maj', 'G#maj', 'Gmaj'],   # v1 i-VII-VI-V
    ['Cmin', 'Gmaj',  'A#maj', 'G#maj'],   # i-V-VII-VI (alt cadence)
    ['A#maj', 'G#maj', 'Cmin', 'Gmaj'],   # VII-VI-i-V
    ['Cmin', 'G#maj', 'A#maj', 'Gmaj'],   # i-VI-VII-V
]

_LATIN_CLAVE_STYLES = ['3-2', '2-3', '3-2', '3-2']  # bias toward 3-2 which is more common

# Latin drum variants (v1.4). Clave + kick 1&3 stay fixed (genre identity).
# Variants alter conga articulation and add optional cowbell/timbale voices.
# All variants keep congas at 8th-note density (d>=0.5) or 4-per-bar (d<0.5)
# so beat_consistency stays in band.
_LATIN_DRUM_VARIANTS = ['salsa_classic', 'timba', 'cha_cha', 'songo']


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

    # v1.3: seed picks progression + clave orientation
    prog         = _LATIN_PROGRESSIONS_Cm[rng.randint(0, len(_LATIN_PROGRESSIONS_Cm) - 1)]
    clave_style  = _LATIN_CLAVE_STYLES[rng.randint(0, len(_LATIN_CLAVE_STYLES) - 1)]
    montuno_off  = rng.choice([
        [0.5, 1.5, 2.5, 3.5],
        [0.5, 1.5, 2.0, 3.5],
        [0.5, 1.0, 2.5, 3.5],
    ])
    for bar_idx in range(duration_bars):
        chord = prog[bar_idx % len(prog)]
        bar_start = bar_idx * seconds_per_bar

        # Nylon guitar montuno: density-scaled offbeat count (variant-shuffled)
        # d=0.3 -> 2 offbeats, d=0.6 -> 3, d=0.9 -> 4
        n_off = max(2, min(4, int(round(density * 4)) + 1))
        offbeats = montuno_off[:n_off] if density < 0.9 else montuno_off
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

    # v1.4: seed-selected drum variant (Move 1)
    drum_variant = _LATIN_DRUM_VARIANTS[rng.randint(0, len(_LATIN_DRUM_VARIANTS) - 1)]

    # Drums: skeleton (clave + kick) always; congas scale with density; variant
    # controls conga articulation + optional cowbell/timbale voice.
    # Percussion pitches: 36=kick, 56=cowbell, 60=hi bongo, 63=hi conga,
    # 64=lo conga, 65=hi timbale, 66=lo timbale, 75=clave
    for bar_idx in range(duration_bars):
        bar_start = bar_idx * seconds_per_bar

        # SKELETON: clave alternating — seed picks which side starts
        primary_is_32 = (clave_style == '3-2')
        if (bar_idx % 2 == 0) == primary_is_32:
            clave_positions = [0, 3, 6, 10, 12]  # 3-2
        else:
            clave_positions = [4, 6, 10, 13, 15]  # 2-3
        for pos in clave_positions:
            t = bar_start + pos * sixteenth
            drums.notes.append(pretty_midi.Note(velocity=85, pitch=75, start=t, end=t + 0.05))

        # SKELETON: kick 1 & 3 (all variants)
        for beat_off in [0, 2]:
            t = bar_start + beat_off * beat_duration
            drums.notes.append(pretty_midi.Note(velocity=95, pitch=36, start=t, end=t + 0.1))

        # v1.5 closed hi-hat time-keeper (latin had none at any tier):
        # quarters (d<0.25), 8ths, 8ths + 16th pickups (d>=0.8); velocity
        # rises with density. No rng draws, so every other note is unchanged.
        hat_vel = int(round(50 + 20 * density))
        hat_steps = [0, 4, 8, 12] if density < 0.25 else list(range(0, 16, 2))
        if density >= 0.8:
            hat_steps += [7, 15]
        for step in sorted(hat_steps):
            t = bar_start + step * sixteenth
            drums.notes.append(pretty_midi.Note(
                velocity=hat_vel - (8 if step % 4 else 0), pitch=42,
                start=t, end=t + 0.05))

        # Congas / auxiliary percussion — variant + density scaled
        if density < 0.5:
            # d<0.5: beat-level only (4 congas per bar) — same across variants
            for beat_idx in range(4):
                t = bar_start + beat_idx * beat_duration
                pitch = 63 if beat_idx % 2 == 0 else 64
                drums.notes.append(pretty_midi.Note(
                    velocity=70, pitch=pitch, start=t, end=t + 0.06))
        else:
            # d>=0.5: variant-specific conga articulation, all at 8th-note density
            if drum_variant == 'salsa_classic':
                # v1: alternating hi/lo conga on straight 8ths
                for eighth_idx in range(8):
                    t = bar_start + eighth_idx * eighth
                    pitch = 63 if eighth_idx % 2 == 0 else 64
                    drums.notes.append(pretty_midi.Note(
                        velocity=70, pitch=pitch, start=t, end=t + 0.06))
            elif drum_variant == 'timba':
                # Timba: heavier hi-conga on the & of every beat, lo-conga on downbeats
                # Same total count (8 per bar) but reversed accent pattern.
                for eighth_idx in range(8):
                    t = bar_start + eighth_idx * eighth
                    is_offbeat = eighth_idx % 2 == 1
                    pitch = 63 if is_offbeat else 64  # accent on offbeats
                    vel = 78 if is_offbeat else 62
                    drums.notes.append(pretty_midi.Note(
                        velocity=vel, pitch=pitch, start=t, end=t + 0.06))
            elif drum_variant == 'cha_cha':
                # Cha-cha-cha: bongo bell + conga tumbao emphasis on beat 4
                # 4 bongo hits (1, 2, 3, 4) + 4 conga hits (8th offbeats)
                for beat_idx in range(4):
                    t = bar_start + beat_idx * beat_duration
                    drums.notes.append(pretty_midi.Note(
                        velocity=68, pitch=60, start=t, end=t + 0.05))  # hi bongo
                for eighth_idx in [1, 3, 5, 7]:
                    t = bar_start + eighth_idx * eighth
                    drums.notes.append(pretty_midi.Note(
                        velocity=72, pitch=64, start=t, end=t + 0.06))  # lo conga
            elif drum_variant == 'songo':
                # Songo: cowbell on 1&3, timbale on offbeats, sparse conga
                # (Los Van Van style — more open, driving)
                for beat_off in [0, 2]:
                    t = bar_start + beat_off * beat_duration
                    drums.notes.append(pretty_midi.Note(
                        velocity=80, pitch=56, start=t, end=t + 0.05))  # cowbell
                for eighth_idx in [1, 3, 5, 7]:
                    t = bar_start + eighth_idx * eighth
                    drums.notes.append(pretty_midi.Note(
                        velocity=68, pitch=65, start=t, end=t + 0.05))  # hi timbale
                # Two conga notes for pocket
                for beat_off in [1.5, 3.5]:
                    t = bar_start + beat_off * beat_duration
                    drums.notes.append(pretty_midi.Note(
                        velocity=65, pitch=64, start=t, end=t + 0.05))

            # ORNAMENT: 16th-note syncopated accents (d>=0.8) — same across variants
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

def _gen_lofi(tempo_bpm, duration_bars, seed, cfg, density):
    """Lofi generator: rnb scaffold with softer velocities and lighter drums.

    Delegates to _gen_rnb for the harmonic/rhythmic skeleton, then reduces
    drum velocities and strips hihat density to produce the warm,
    drum-lite feel that fills the calm->rnb arousal gap.
    """
    pm = _gen_rnb(tempo_bpm, duration_bars, seed, cfg, density)
    # Soften: reduce all drum velocities, and drop every other hihat hit
    for inst in pm.instruments:
        if inst.is_drum:
            new_notes = []
            hh_count = 0
            for note in inst.notes:
                if note.pitch == 42:  # closed hihat
                    hh_count += 1
                    if hh_count % 2 == 0:
                        continue  # drop every other hihat
                    note.velocity = max(1, int(note.velocity * 0.55))
                elif note.pitch == 36:  # kick
                    note.velocity = max(1, int(note.velocity * 0.75))
                elif note.pitch == 38:  # snare
                    note.velocity = max(1, int(note.velocity * 0.65))
                else:
                    note.velocity = max(1, int(note.velocity * 0.7))
                new_notes.append(note)
            inst.notes = new_notes
        else:
            # Also soften melodic content slightly for warm feel
            for note in inst.notes:
                note.velocity = max(1, int(note.velocity * 0.85))
    return pm


def _score_to_pm(score) -> pretty_midi.PrettyMIDI:
    """music21 Score -> temporary MIDI -> PrettyMIDI (one direction only)."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        midi_path = Path(td) / 'cell.mid'
        score.write('midi', fp=str(midi_path))
        return pretty_midi.PrettyMIDI(str(midi_path))


def _gen_hiphop(tempo_bpm, duration_bars, seed, cfg, density):
    # Lazy import: composer/__init__.py executes this file, so a top-level
    # import of the package's cell modules would be circular.
    from composer.hiphop_cell import generate_segment_hiphop_adapter
    return _score_to_pm(generate_segment_hiphop_adapter(
        'hiphop', tempo_bpm, density, duration_bars, seed))


def _gen_rock(tempo_bpm, duration_bars, seed, cfg, density):
    from composer.rock_cell import generate_segment_rock_adapter
    return _score_to_pm(generate_segment_rock_adapter(
        'rock', tempo_bpm, density, duration_bars, seed))


_GENERATORS = {
    'calm':   _gen_calm,
    'lofi':   _gen_lofi,
    'pop':    _gen_pop,
    'rnb':    _gen_rnb,
    'latin':  _gen_latin,
    'hiphop': _gen_hiphop,
    'rock':   _gen_rock,
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
    genre : {'calm', 'lofi', 'pop', 'rnb', 'latin', 'hiphop', 'rock'}
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
        None uses the genre's cfg['velocity_boost'], else DEFAULT_VELOCITY_BOOST.

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
    if velocity_boost is None:
        velocity_boost = cfg.get('velocity_boost', DEFAULT_VELOCITY_BOOST)
    boost = velocity_boost
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
