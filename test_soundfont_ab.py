"""test_soundfont_ab.py — A/B compare GeneralUser GS vs Musyng Kite.

Renders pop tier 3 with BOTH soundfonts, saves both WAVs to symbolic_out/,
plays them back-to-back with a short silence between so you can hear the
difference immediately.

Files written (for later re-listening):
  symbolic_out/ab_generaluser_pop_t3.wav
  symbolic_out/ab_musyng_pop_t3.wav

Prints render timing for each.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure repo imports work regardless of cwd.
_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_PILOT = os.path.join(_ROOT, "groovegen_pilot")
if _PILOT not in sys.path:
    sys.path.insert(0, _PILOT)

import numpy as np
import soundfile as sf

from renderer import render_segment
from player import SoundDevicePlayer

SOUNDFONTS = {
    "generaluser": "/Users/daniel/Desktop/PhD/groove_gen_project/soundfonts/GeneralUser_GS_v1.471.sf2",
    "musyng":      "/Users/daniel/Desktop/PhD/groove_gen_project/soundfonts/Musyng_Kite.sf2",
}

OUT_DIR = Path(_ROOT) / "symbolic_out"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Fixed segment parameters so both renders are identical composition-wise.
TIER = 3
TEMPO_BPM = 104
GENRE = "pop"
N_BARS = 4
XFADE_HEAD_BARS = 1
SR = 44100


def render_one(label: str, sf2_path: str) -> tuple[np.ndarray, float]:
    """Render pop tier 3 with the given soundfont. Returns (audio, render_ms)."""
    if not Path(sf2_path).exists():
        print(f"[FAIL] {label}: soundfont not found at {sf2_path}")
        sys.exit(1)

    print(f"[INFO] Rendering {label} ({Path(sf2_path).name})...")
    t0 = time.perf_counter()
    audio = render_segment(
        tier=TIER,
        tempo_bpm=TEMPO_BPM,
        genre=GENRE,
        n_bars=N_BARS,
        xfade_head_bars=XFADE_HEAD_BARS,
        sf2=sf2_path,
        sr=SR,
    )
    render_ms = (time.perf_counter() - t0) * 1000

    # Sanity checks.
    if audio.dtype != np.float32:
        print(f"[FAIL] {label}: dtype {audio.dtype} != float32")
        sys.exit(1)
    if audio.shape[1] != 2:
        print(f"[FAIL] {label}: channels {audio.shape[1]} != 2")
        sys.exit(1)
    if not np.isfinite(audio).all():
        print(f"[FAIL] {label}: contains NaN or Inf")
        sys.exit(1)
    if float(np.max(np.abs(audio))) == 0.0:
        print(f"[FAIL] {label}: silent audio (peak=0)")
        sys.exit(1)

    duration_s = audio.shape[0] / SR
    peak = float(np.max(np.abs(audio)))
    rms = float(np.sqrt(np.mean(audio ** 2)))
    print(f"[OK]   {label}: {duration_s:.2f}s, peak={peak:.3f}, rms={rms:.4f} "
          f"(render {render_ms:.0f}ms)")

    return audio, render_ms


def main() -> int:
    print("=" * 60)
    print("SoundFont A/B: GeneralUser GS vs Musyng Kite")
    print(f"  Segment: {GENRE} tier={TIER} @ {TEMPO_BPM} BPM, "
          f"{N_BARS}+{XFADE_HEAD_BARS} bars")
    print("=" * 60)

    # Render both.
    audio_gu, ms_gu = render_one("generaluser", SOUNDFONTS["generaluser"])
    audio_mk, ms_mk = render_one("musyng",       SOUNDFONTS["musyng"])

    # Save both for later listening/comparison.
    path_gu = OUT_DIR / "ab_generaluser_pop_t3.wav"
    path_mk = OUT_DIR / "ab_musyng_pop_t3.wav"
    sf.write(str(path_gu), audio_gu, SR)
    sf.write(str(path_mk), audio_mk, SR)
    print()
    print(f"[SAVED] {path_gu}")
    print(f"[SAVED] {path_mk}")

    # Playback: GeneralUser first, then Musyng, with a clear announcement gap.
    print()
    print("=" * 60)
    print("Playback: GeneralUser first, then 1.5s silence, then Musyng")
    print("Listen for: piano richness, bass warmth, overall 'mechanical' feel")
    print("=" * 60)

    duration_gu = audio_gu.shape[0] / SR
    duration_mk = audio_mk.shape[0] / SR
    silence = np.zeros((int(1.5 * SR), 2), dtype=np.float32)

    player = SoundDevicePlayer(sample_rate=SR, channels=2)
    player.start()

    print(f"[PLAY] GeneralUser GS ({duration_gu:.1f}s)...")
    player.enqueue(audio_gu)
    time.sleep(duration_gu + 0.2)

    print("[PLAY] --- 1.5s silence ---")
    player.enqueue(silence)
    time.sleep(1.7)

    print(f"[PLAY] Musyng Kite ({duration_mk:.1f}s)...")
    player.enqueue(audio_mk)
    time.sleep(duration_mk + 0.5)

    player.stop(drain=True)
    underruns = player.underruns()

    print()
    print("=" * 60)
    print(f"Render timings: GeneralUser {ms_gu:.0f}ms | Musyng {ms_mk:.0f}ms")
    print(f"Underruns: {underruns} (post-audio silence expected ~22, "
          f">100 = real problem)")
    print()
    print("Files saved for re-listening:")
    print(f"  open {path_gu}")
    print(f"  open {path_mk}")
    print("=" * 60)
    print("[DONE] A/B complete. Decide: Musyng better / same / worse?")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] Exception: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
