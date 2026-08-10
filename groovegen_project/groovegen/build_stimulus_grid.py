"""
Step 5 — Stimulus-grid export + manifest.

Generates the single-knob-sweep stimulus set for the perturbation pilot:
hold 4 knobs at reference (center) values, sweep 1 knob across its 4
literature-derived levels. 5 knobs x 4 levels = 20 core conditions.

For each stimulus we render audio + MIDI AND recompute the actual achieved
features (onset count, syncopation index, realized microtiming RMS, swing
fraction) as a MANIPULATION CHECK, written to stimuli_manifest.csv. This is
what lets the experiment trust that "knob set to L2" actually produced the
intended musical change.

Usage:
    python3 groovegen/build_stimulus_grid.py
"""
from __future__ import annotations

import csv
import os
import sys

# Make the project root importable (so `import config` and `import groovegen` work).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from groovegen import GrooveParams, PatternBuilder, generate, STUDY_BED_PROFILE  # type: ignore
import config

OUT_DIR = str(config.AUDIO_OUT / "grid")
MANIFEST = str(config.OUTPUTS / "stimuli_manifest.csv")

# Reference (center) values — the baseline "groovy" condition. Chosen from the
# literature sweet spots: 115 BPM, medium density, light swing, medium
# syncopation, quantized timing.
REFERENCE = dict(
    tempo_bpm=115.0,
    event_density=12,
    swing_amount=1.3,       # ~57% (light swing)
    syncopation_level=0.5,  # sweet spot
    microtiming_variance_ms=0.0,
)

# Literature-derived 4-level sweeps (see groove_knob_literature.md).
SWEEPS = {
    "tempo_bpm":               [70.0, 95.0, 115.0, 150.0],
    "event_density":           [4, 8, 14, 24],
    "swing_amount":            [1.0, 1.25, 1.6, 2.0],   # 50% / 56% / 62% / 67%
    "syncopation_level":       [0.0, 0.25, 0.5, 1.0],
    "microtiming_variance_ms": [0.0, 7.0, 15.0, 35.0],
}

TARGET_SECONDS = 30.0  # pilot stimulus length


def swing_fraction(r: float) -> float:
    return 0.5 if r <= 1.0 else r / (1.0 + r)


def build_grid():
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = []
    for knob, levels in SWEEPS.items():
        for li, val in enumerate(levels):
            params_kwargs = dict(REFERENCE)
            params_kwargs[knob] = val
            params_kwargs["target_seconds"] = TARGET_SECONDS
            params_kwargs["seed"] = 0  # fixed seed -> reproducible stimuli
            # STUDY stimuli use the FROZEN single-section (verse) bed so the
            # bed is time- AND knob-invariant; the only thing that varies
            # across the grid is the swept knob. (The full Intro->Verse->
            # Chorus hero SONG is for demos/product, not the experiment.)
            params_kwargs["with_bed"] = True
            params_kwargs["bed_profile"] = STUDY_BED_PROFILE
            p = GrooveParams(**params_kwargs)

            stim_id = f"{knob}_L{li}"
            stem = os.path.join(OUT_DIR, stim_id)
            meta = generate(p, out_stem=stem)

            # manipulation checks (recompute achieved features from the pattern)
            pb = PatternBuilder(p)
            pb.build_core()  # populates realized jitters
            achieved_density = pb.onset_count_per_bar()
            achieved_sync = pb.syncopation_index()
            achieved_mt_rms = pb.realized_microtiming_rms_ms()

            rows.append({
                "stimulus_id": stim_id,
                "swept_knob": knob,
                "level_index": li,
                # commanded knob values
                "tempo_bpm": p.tempo_bpm,
                "event_density": p.event_density,
                "swing_amount": p.swing_amount,
                "swing_fraction": round(swing_fraction(p.swing_amount), 3),
                "syncopation_level": p.syncopation_level,
                "microtiming_variance_ms": p.microtiming_variance_ms,
                "with_bed": p.with_bed,  # fixed bass+chords+melody (constant across all stimuli)
                "bed_profile": p.bed_profile,  # frozen single-section study bed
                "seed": p.seed,
                # achieved (manipulation-check) values
                "achieved_onsets_per_bar": achieved_density,
                "achieved_syncopation_index": achieved_sync,
                "achieved_microtiming_rms_ms": round(achieved_mt_rms, 2),
                # render metadata
                "duration_s": meta["duration_s"],
                "measured_lufs_pre_norm": meta["measured_lufs_pre_norm"],
                "target_lufs": meta["target_lufs"],
                "peak_post_norm": meta["peak_post_norm"],
                "wav_path": meta["wav_path"],
                "mid_path": meta["mid_path"],
            })

    fieldnames = list(rows[0].keys())
    with open(MANIFEST, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    rows = build_grid()
    print(f"Built {len(rows)} stimuli -> {OUT_DIR}")
    print(f"Manifest -> {MANIFEST}\n")
    # quick manipulation-check summary
    print("Manipulation checks (swept knob -> achieved feature across levels):")
    for knob in SWEEPS:
        sub = [r for r in rows if r["swept_knob"] == knob]
        if knob == "event_density":
            vals = [r["achieved_onsets_per_bar"] for r in sub]
        elif knob == "syncopation_level":
            vals = [r["achieved_syncopation_index"] for r in sub]
        elif knob == "microtiming_variance_ms":
            vals = [r["achieved_microtiming_rms_ms"] for r in sub]
        elif knob == "swing_amount":
            vals = [r["swing_fraction"] for r in sub]
        else:
            vals = [r["tempo_bpm"] for r in sub]
        print(f"  {knob:24s} -> {vals}")
