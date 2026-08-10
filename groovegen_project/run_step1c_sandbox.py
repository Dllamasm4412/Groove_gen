"""
Step 1c sandbox test — see /Users/daniel/Desktop/PhD/groove_gen_project/step1c_spec.md.
Run from groovegen_project/ so `groovegen` package imports resolve.
"""
import json
import os
import subprocess
import sys

import numpy as np
import librosa

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from groovegen.groovegen import GrooveParams
from groovegen.continuous import detect_bed_tempo, detect_bed_downbeat, render_piece

SALSA_BED = "/Users/daniel/Desktop/PhD/groove_gen_project/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav"
RNB_BED = "/Users/daniel/Desktop/PhD/groove_gen_project/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav"
OUT_DIR = "/Users/daniel/Desktop/PhD/groove_gen_project/step1c_outputs"
os.makedirs(OUT_DIR, exist_ok=True)

FS = 44100
report = {}


def measure_residual_offset(drums_wav, bed_wav, tempo_bpm, sr=FS):
    """SAME method as Step 1b's report: cross-correlate the onset-strength
    envelope of the rendered DRUM track against the ORIGINAL bed wav, over
    the first bar, and report the lag (seconds) of peak correlation.

    Positive lag = drums lag behind the bed; negative = drums lead the bed.
    """
    drums_y, _ = librosa.load(drums_wav, sr=sr, mono=True)
    bed_y, _ = librosa.load(bed_wav, sr=sr, mono=True)

    bar_seconds = 4 * 60.0 / tempo_bpm
    n = int(round(bar_seconds * sr))
    n = min(n, len(drums_y), len(bed_y))
    d = drums_y[:n]
    b = bed_y[:n]

    hop = 256
    de = librosa.onset.onset_strength(y=d, sr=sr, hop_length=hop)
    be = librosa.onset.onset_strength(y=b, sr=sr, hop_length=hop)
    m = min(len(de), len(be))
    de = de[:m] - de[:m].mean()
    be = be[:m] - be[:m].mean()

    xc = np.correlate(be, de, mode="full")
    lag_frames = np.argmax(xc) - (m - 1)
    lag_s = lag_frames * hop / sr
    return float(lag_s)


def ffmpeg_volumedetect(wav_path):
    cmd = ["ffmpeg", "-i", wav_path, "-af", "volumedetect", "-f", "null", "-"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    mean_v = max_v = None
    for line in res.stderr.splitlines():
        if "mean_volume" in line:
            mean_v = line.strip().split(":")[-1].strip()
        if "max_volume" in line:
            max_v = line.strip().split(":")[-1].strip()
    return {"mean_volume": mean_v, "max_volume": max_v}


# --- (a) detect_bed_downbeat for both beds (at their Step-1b-locked tempo) ---
print("=" * 70)
print("(a) detect_bed_downbeat")
salsa_tempo = detect_bed_tempo(SALSA_BED)["tempo_bpm"]
rnb_tempo = detect_bed_tempo(RNB_BED)["tempo_bpm"]
salsa_offset = detect_bed_downbeat(SALSA_BED, salsa_tempo)
rnb_offset = detect_bed_downbeat(RNB_BED, rnb_tempo)
print(f"salsa: tempo={salsa_tempo:.2f} BPM  downbeat_offset={salsa_offset:.4f} s")
print(f"rnb:   tempo={rnb_tempo:.2f} BPM  downbeat_offset={rnb_offset:.4f} s")
report["downbeat_detect"] = {
    "salsa": {"tempo_bpm": salsa_tempo, "downbeat_offset_s": salsa_offset},
    "rnb": {"tempo_bpm": rnb_tempo, "downbeat_offset_s": rnb_offset},
}

# --- (b) re-render both discrete pieces WITH the alignment fix ---
print("=" * 70)
print("(b) render_piece salsa + rnb (with Step 1c fix)")

base_salsa = GrooveParams(
    tempo_bpm=96.0,  # placeholder; render_piece overrides with detected tempo
    event_density=7,
    drum_style="latin/salsa",
    bed_profile="hero_study",
    with_bed=False,
)
piece_salsa = render_piece(
    base_salsa, SALSA_BED, out_stem=os.path.join(OUT_DIR, "piece_salsa"),
    seconds=16.0, seed=1, subtle=True,
)
print("piece_salsa tempo_bpm:", piece_salsa["tempo_bpm"])
print("piece_salsa downbeat_offset_s:", piece_salsa["downbeat_offset_s"])
print("piece_salsa duration_s:", piece_salsa["duration_s"])

base_rnb = GrooveParams(
    tempo_bpm=96.0,
    event_density=6,
    drum_style="r&b/soul",
    bed_profile="hero_study",
    with_bed=False,
)
piece_rnb = render_piece(
    base_rnb, RNB_BED, out_stem=os.path.join(OUT_DIR, "piece_rnb"),
    seconds=16.0, seed=2, subtle=True,
)
print("piece_rnb tempo_bpm:", piece_rnb["tempo_bpm"])
print("piece_rnb downbeat_offset_s:", piece_rnb["downbeat_offset_s"])
print("piece_rnb duration_s:", piece_rnb["duration_s"])

report["piece_salsa"] = {k: v for k, v in piece_salsa.items()
                          if k not in ("per_bar_stats",)}
report["piece_rnb"] = {k: v for k, v in piece_rnb.items()
                        if k not in ("per_bar_stats",)}

# --- (c) residual drum-vs-bed onset offset AFTER the fix ---
print("=" * 70)
print("(c) residual offset measurement (drums_tmp wav vs ORIGINAL bed, first bar)")
salsa_residual = measure_residual_offset(
    piece_salsa["drums_wav"], SALSA_BED, piece_salsa["tempo_bpm"])
rnb_residual = measure_residual_offset(
    piece_rnb["drums_wav"], RNB_BED, piece_rnb["tempo_bpm"])
print(f"salsa residual offset AFTER fix: {salsa_residual:+.4f} s  "
      f"(before fix was ~0.10 s)")
print(f"rnb   residual offset AFTER fix: {rnb_residual:+.4f} s  "
      f"(before fix was ~0.85 s)")
report["residual_offset_after_fix"] = {
    "salsa_s": salsa_residual,
    "rnb_s": rnb_residual,
    "salsa_before_fix_s": 0.10,
    "rnb_before_fix_s": 0.85,
    "target_abs_s": 0.05,
    "salsa_pass": abs(salsa_residual) < 0.05,
    "rnb_pass": abs(rnb_residual) < 0.05,
}

# --- (d) ffmpeg volumedetect ---
print("=" * 70)
print("(d) ffmpeg volumedetect")
salsa_vol = ffmpeg_volumedetect(piece_salsa["wav_path"])
rnb_vol = ffmpeg_volumedetect(piece_rnb["wav_path"])
print("piece_salsa volumedetect:", salsa_vol)
print("piece_rnb volumedetect:", rnb_vol)
report["volumedetect"] = {"piece_salsa": salsa_vol, "piece_rnb": rnb_vol}

# --- (e) confirm r&b alignment ---
print("=" * 70)
print("(e) r&b alignment fixed?", abs(rnb_residual) < 0.05,
      f"(residual {rnb_residual:+.4f}s, was ~0.85s)")
report["rnb_alignment_fixed"] = bool(abs(rnb_residual) < 0.05)

with open(os.path.join(OUT_DIR, "step1c_report.json"), "w") as f:
    json.dump(report, f, indent=2, default=str)

print("=" * 70)
print("DONE. Report written to", os.path.join(OUT_DIR, "step1c_report.json"))
