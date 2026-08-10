"""Render the SAME Dorian melody + anthemic-style bass across several candidate
melody timbres so the user can pick by ear. Outputs one WAV per candidate; an
ffmpeg step (run separately) concatenates them into a single labeled MP4.

The bed here is a HYBRID:
  - harmony/melody = the Dorian vamp (Am7 - D/A)  [user likes this]
  - bass groove    = the anthemic profile's pushed/dotted feel  [user likes this]
Only the MELODY program changes between renders; everything else is identical.
"""
import os, sys, warnings
import numpy as np
import pretty_midi

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from groovegen import GrooveParams, PatternBuilder, render_wav, BED_DORIAN
import config

OUT = config.AUDIO_OUT / "melody_compare"
OUT.mkdir(parents=True, exist_ok=True)

# Candidate melody programs (GM, 0-indexed). Names per the user's two picks:
# "warm keys done right" and "guitar".
CANDIDATES = [
    (4,  "Electric Piano (current)"),   # the 80s-ish one, for reference
    (0,  "Warm Grand Piano"),
    (24, "Nylon Guitar"),
    (25, "Steel Acoustic Guitar"),
    (26, "Jazz Electric Guitar"),
    (27, "Clean Electric Guitar"),
]

# Hybrid bed parameters: Dorian harmony + anthemic bass groove.
# We build the Dorian bed but override the bass step pattern + velocity to the
# anthemic feel, and override the melody program per candidate.
ANTHEMIC_BASS_STEPS = (0, 3, 4, 6, 8, 11, 12, 14)   # pushed/dotted
ANTHEMIC_BASS_VEL = 62

COMMON = dict(tempo_bpm=120.0, bars=2, target_seconds=12.0, seed=7,
              event_density=12, swing_amount=1.3, syncopation_level=0.35)


def build_hybrid_pm(melody_program: int) -> pretty_midi.PrettyMIDI:
    """Drums + hybrid bed (Dorian harmony, anthemic bass) with a chosen melody program."""
    params = GrooveParams(with_bed=True, bed_profile=BED_DORIAN.name, **COMMON)
    pb = PatternBuilder(params)
    pm = pb.build_looped()

    # Remove the bed instruments that build_looped added; rebuild them with the
    # anthemic bass groove + chosen melody program, then re-tile.
    drums = [i for i in pm.instruments if i.is_drum]
    pm.instruments = list(drums)

    spb = pb.sec_per_beat
    sixteenth = spb / 4.0
    prof = BED_DORIAN
    bass = pretty_midi.Instrument(program=prof.bass_program, name="bed_bass")
    chords = pretty_midi.Instrument(program=prof.chord_program, name="bed_chords")
    melody = pretty_midi.Instrument(program=melody_program, name="bed_melody")

    for bar in range(len(prof.chords)):
        bar_t = bar * pb.bar_seconds
        root, tones, motif = prof.chords[bar]
        for s in ANTHEMIC_BASS_STEPS:          # anthemic bass groove
            t = pb._grid_step_time(bar_t, s)
            bass.notes.append(pretty_midi.Note(ANTHEMIC_BASS_VEL, root,
                                               t, t + 1.9 * sixteenth))
        t0 = pb._grid_step_time(bar_t, 0)
        for p in tones:
            chords.notes.append(pretty_midi.Note(prof.chord_vel, p,
                                                 t0, t0 + pb.bar_seconds - 0.02))
        for (s, p) in motif:
            t = pb._grid_step_time(bar_t, s)
            melody.notes.append(pretty_midi.Note(prof.melody_vel, p,
                                                 t, t + 1.8 * sixteenth))

    # tile the bed across the full loop
    bed_period = pb.bed_period_seconds
    total = max(n.end for n in drums[0].notes)
    reps = max(1, int(np.ceil(total / bed_period)))
    for proto in (bass, chords, melody):
        inst = pretty_midi.Instrument(program=proto.program, name=proto.name)
        for r in range(reps):
            off = r * bed_period
            for n in proto.notes:
                inst.notes.append(pretty_midi.Note(n.velocity, n.pitch,
                                                   n.start + off, n.end + off))
        pm.instruments.append(inst)
    return pm


if __name__ == "__main__":
    print("Soundfont:", config.find_soundfont())
    for prog, name in CANDIDATES:
        pm = build_hybrid_pm(prog)
        slug = name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        stem = str(OUT / f"mel_{prog:02d}_{slug}.wav")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            meta = render_wav(pm, stem)
        print(f"  prog {prog:3d}  {name:28s} -> {os.path.basename(stem)}  "
              f"({meta['duration_s']}s)")
    print("DONE")
