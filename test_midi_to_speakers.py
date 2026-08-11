"""test_midi_to_speakers.py — end-to-end audio pipeline smoke test.

Validates the full M1 audio stack:
  symbolic_bed_proto.build_pop() -> MIDI
  render_midi()                  -> subprocess FluidSynth -> WAV
  soundfile.read()               -> numpy float32 stereo
  SoundDevicePlayer              -> speakers

If this runs clean, the entire audio path for M1 works. Only render_segment
(bar batching) remains as new architecture.

Prints timing for each stage so we know where the wall-clock time is spent.
Exit 0 on full success, nonzero on any failure with a clear message.
"""
from __future__ import annotations

import os
import sys
import time
import tempfile

# Make sure our repo root is importable regardless of cwd.
_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_PILOT = os.path.join(_ROOT, "groovegen_pilot")
if _PILOT not in sys.path:
    sys.path.insert(0, _PILOT)

# Real SoundFont path on this machine (override the Colab Linux path baked
# into symbolic_bed_proto.SF2).
SF2_PATH = os.path.join(_ROOT, "soundfonts", "GeneralUser_GS_v1.471.sf2")

import numpy as np
import soundfile as sf

import symbolic_bed_proto as S
from player import SoundDevicePlayer


def main() -> int:
    print("=" * 60)
    print("GrooveGen: MIDI -> FluidSynth -> speakers round-trip test")
    print("=" * 60)

    # ---- stage 0: preflight ----
    if not os.path.exists(SF2_PATH):
        print(f"[FAIL] SoundFont missing: {SF2_PATH}")
        return 1
    print(f"[OK] SoundFont: {SF2_PATH}")

    # ---- stage 1: build MIDI ----
    t0 = time.perf_counter()
    # Short: 4 bars at 104 BPM = ~9.2 seconds of audio. Long enough to hear
    # the whole progression, short enough not to bore you.
    midi = S.build_pop(bpm=104, bars=4)
    n_notes = sum(len(inst.notes) for inst in midi.instruments)
    n_inst = len(midi.instruments)
    build_ms = (time.perf_counter() - t0) * 1000
    print(f"[OK] Built MIDI: {n_inst} instruments, {n_notes} notes "
          f"({build_ms:.1f} ms)")

    # ---- stage 2: render MIDI to WAV via FluidSynth subprocess ----
    with tempfile.TemporaryDirectory() as tmp:
        out_wav = os.path.join(tmp, "pop_test.wav")

        t0 = time.perf_counter()
        # render_midi() writes a "raw" wav in tmp before returning the path.
        # We pass sf2 explicitly to bypass the Linux-path constant in S.SF2.
        raw = S.render_midi(midi, out_wav, sf2=SF2_PATH, sr=44100, gain=0.8)
        render_ms = (time.perf_counter() - t0) * 1000

        if raw is None or not os.path.exists(raw):
            print("[FAIL] FluidSynth render failed. Check S.render_midi output.")
            return 1
        print(f"[OK] Rendered MIDI to WAV: {os.path.basename(raw)} "
              f"({render_ms:.1f} ms)")

        # ---- stage 3: load WAV into numpy ----
        t0 = time.perf_counter()
        audio, sr = sf.read(raw, dtype="float32", always_2d=True)
        load_ms = (time.perf_counter() - t0) * 1000

        n_samples, n_channels = audio.shape
        duration_s = n_samples / sr
        peak = float(np.max(np.abs(audio)))
        rms = float(np.sqrt(np.mean(audio ** 2)))
        print(f"[OK] Loaded WAV: {duration_s:.2f} s, {sr} Hz, "
              f"{n_channels} ch, peak={peak:.3f}, rms={rms:.4f} "
              f"({load_ms:.1f} ms)")

    # ---- stage 4: sanity checks on audio ----
    if sr != 44100:
        print(f"[FAIL] Expected 44100 Hz, got {sr}")
        return 1
    if not np.isfinite(audio).all():
        print("[FAIL] Audio contains NaN or Inf")
        return 1
    if peak == 0.0:
        print("[FAIL] Audio is silent (peak=0)")
        return 1
    if peak > 1.0:
        # Rare but possible after fluidsynth gain=0.8. Clip and warn rather
        # than fail — the smoke test is about the pipeline, not levels.
        print(f"[WARN] Audio peak {peak:.3f} > 1.0, clipping to [-1, 1]")
        audio = np.clip(audio, -1.0, 1.0)

    # Player wants stereo. If soundfile gave us mono, duplicate to stereo.
    if n_channels == 1:
        audio = np.column_stack((audio[:, 0], audio[:, 0]))
        n_channels = 2
        print("[INFO] Duplicated mono to stereo")
    elif n_channels > 2:
        print(f"[FAIL] Unexpected channel count: {n_channels}")
        return 1

    # Player wants contiguous float32. soundfile already gave us float32 but
    # column_stack might have changed layout; force contiguous.
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    # ---- stage 5: play through SoundDevicePlayer ----
    print(f"[INFO] Playing {duration_s:.2f} s through SoundDevicePlayer...")
    print("[INFO] You should hear a short pop bed (piano/bass/pad, no drums).")

    player = SoundDevicePlayer(sample_rate=44100, channels=2)
    t_play = time.perf_counter()
    player.start()
    player.enqueue(audio)
    # Wait for playback to finish. Add a small tail so drain sees the buffer
    # empty. duration + 0.5s covers this cleanly.
    time.sleep(duration_s + 0.5)
    player.stop(drain=True)
    play_ms = (time.perf_counter() - t_play) * 1000

    underruns = player.underruns()
    print(f"[OK] Playback complete ({play_ms:.1f} ms wall, "
          f"underruns={underruns})")

    # ---- summary ----
    print("=" * 60)
    print("PIPELINE TIMING BREAKDOWN")
    print(f"  MIDI build:      {build_ms:>8.1f} ms")
    print(f"  FluidSynth:      {render_ms:>8.1f} ms  "
          f"(subprocess + I/O)")
    print(f"  WAV load:        {load_ms:>8.1f} ms")
    print(f"  Playback wall:   {play_ms:>8.1f} ms  "
          f"(includes {duration_s * 1000:.0f} ms audio)")
    print("=" * 60)

    # Post-audio underruns are expected (the tail of the sleep + drain
    # period counts them; not a real problem, same as player.py smoke test).
    # If underruns > 100, something's actually wrong.
    if underruns > 100:
        print(f"[FAIL] Excessive underruns: {underruns}")
        return 1

    print("[PASS] MIDI-to-speakers round trip complete.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"[FAIL] Exception: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
