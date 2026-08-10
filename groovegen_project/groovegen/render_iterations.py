"""Render the 3 song-bed iterations (Sophia-grounded) at 120 BPM.

Each iteration uses an IDENTICAL drum core (the canonical backbeat at a moderate
groove setting) so that only the musical bed differs between songs. This lets
the user compare the three "songs" on equal footing.

Outputs WAV (44.1 kHz, loudness-normalized) for each iteration.
"""
import os
import sys

# Make the project root importable (so `import config` and `import groovegen` work).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from groovegen import GrooveParams, PatternBuilder, render_wav, BED_PROFILES, default_sf2
import config

OUT = str(config.AUDIO_OUT)
os.makedirs(OUT, exist_ok=True)

# A fixed, musical drum setting shared by all three songs (so only the bed
# differs). Moderate density + a touch of swing + mild syncopation = "grooves".
COMMON_KNOBS = dict(
    tempo_bpm=120.0,
    bars=2,
    target_seconds=24.0,
    seed=7,
    event_density=12,
    swing_amount=1.3,
    swing_level="16",
    syncopation_level=0.35,
    microtiming_variance_ms=0.0,
)

print(f"Soundfont: {default_sf2()}")
results = []
for name, prof in BED_PROFILES.items():
    params = GrooveParams(with_bed=True, bed_profile=name, **COMMON_KNOBS)
    pb = PatternBuilder(params)
    pm = pb.build_looped()
    stem = os.path.join(OUT, f"song_{name}")
    pm.write(stem + ".mid")
    meta = render_wav(pm, stem + ".wav")
    results.append((name, prof.desc, meta))
    print(f"\n[{name}] {prof.desc}")
    print(f"  bass_prog={prof.bass_program} chord_prog={prof.chord_program} "
          f"melody_prog={prof.melody_program}")
    print(f"  vels bass/chord/melody = {prof.bass_vel}/{prof.chord_vel}/{prof.melody_vel}")
    print(f"  wav={meta['wav_path']}  dur={meta['duration_s']}s  "
          f"peak={meta['peak_post_norm']}")

print("\nALL 3 ITERATIONS RENDERED OK")
