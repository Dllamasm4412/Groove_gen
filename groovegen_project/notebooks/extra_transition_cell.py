# ===========================================================================
# EXTRA CELL -- bigger tempo steps + musical transition sound at each seam
# ---------------------------------------------------------------------------
# Paste this AFTER Part C / nb15 has finished (it reuses the cached beds and
# the in-memory `seg_mixes`, `segments`, `OUT_DIR`, `SR`, and the
# `splice_beds_downbeat_hard_cut` helpers that nb15 already defined). It does
# NOT call MusicGen and does NOT need the GPU -- it just re-assembles the beds
# you already generated, with two changes:
#
#   1) BIGGER, DELIBERATE TEMPO STEPS. The stock arc lets the committed tempo
#      drift only a few BPM inside each genre band, so the audible jump at a
#      seam can be small (e.g. 82 -> 84). Here we SNAP each segment to a fixed
#      per-band target so consecutive segments are ~16-20 BPM apart, giving
#      clean, perceptible steps (latin 128 -> pop 104 -> r&b 88 -> calm 72).
#      RE-TIMING NOW USES RubberBand (groovegen.bed_library.retime_bed), NOT
#      raw np.interp resampling -- see CODE_AUDIT.md finding #3: linear
#      resampling changes duration by literally stretching the sample-time
#      axis, which necessarily pitch-shifts the audio (a turntable-speed
#      effect); RubberBand re-synthesizes at the new duration while holding
#      pitch fixed, so a ~19-23% step (128->104, 104->88, 88->72) sounds like
#      the same bed played at a different tempo, not a slowed-down record.
#
#   2) A SYNTHESIZED TRANSITION SOUND across each seam. Instead of a bare hard
#      cut, a short noise "riser" swells over the last beat of the outgoing
#      segment and resolves on a soft downbeat "impact" as the next segment
#      starts. It is fully synthesized (no samples), so it stays on-brand for a
#      generative system and masks the tempo change musically. Toggle style
#      below: "riser" (recommended), "sweep" (subtler), "impact_only", or
#      "none" (fall back to the stock hard cut).
# ===========================================================================
import os
import numpy as np
import soundfile as sf
from groovegen.bed_library import retime_bed

# ---- knobs you can tweak ---------------------------------------------------
STEP_MODE      = "snap"     # "snap" = force big even steps; "keep" = leave committed tempos
BAND_TARGET_BPM = {          # per-genre snapped target (only used when STEP_MODE=="snap")
    "latin": 128.0,
    "pop":   104.0,
    "r&b":    88.0,
    "calm":   72.0,
}
TRANSITION_STYLE = "riser"  # "riser" | "sweep" | "impact_only" | "none"
TRANSITION_GAIN  = 0.35     # 0..1 loudness of the transition fx relative to the mix
RISER_BEATS      = 4.0      # how long the swell lasts, in beats of the OUTGOING segment
OUT_FULL_WAV     = os.path.join(OUT_DIR, "15_full_audio_bigsteps_fx.wav")

rng = np.random.default_rng(7)


# ---- helpers ---------------------------------------------------------------
def _retime_array_to_tempo(y, sr, from_bpm, to_bpm, tmp_dir):
    """Re-time an in-memory array via groovegen.bed_library.retime_bed
    (RubberBand, pitch-preserving -- see module docstring there for why this
    replaced np.interp resampling). retime_bed operates on files, so we
    round-trip through two temp WAVs; this whole extra-cell script is a
    CPU-only post-process, so the extra disk I/O is negligible next to the
    MusicGen generation cost already paid earlier in the notebook."""
    src = os.path.join(tmp_dir, f"_pre_retime_{from_bpm:.1f}.wav")
    dst = os.path.join(tmp_dir, f"_post_retime_{from_bpm:.1f}_to_{to_bpm:.1f}.wav")
    sf.write(src, y.astype(np.float32), sr)
    retime_bed(src, dst, from_bpm=from_bpm, to_bpm=to_bpm, crispness=6)
    y_out, sr_out = sf.read(dst)
    assert sr_out == sr, "retime_bed must not change sample rate"
    return y_out.astype(np.float32)


def _riser(sr, dur_s, gain, kind="riser"):
    """Synthesized transition FX (no samples).
      riser       : filtered white-noise swell, amplitude 0->1, brightening.
      sweep       : sine that sweeps up in pitch (a 'whoosh').
      impact_only : a single soft low 'boom' (returned as the tail only).
    """
    n = max(1, int(round(dur_s * sr)))
    t = np.arange(n) / sr
    env = np.linspace(0.0, 1.0, n) ** 2.0            # slow-in swell
    if kind == "sweep":
        f0, f1 = 200.0, 4000.0
        inst = f0 * (f1 / f0) ** (t / max(t[-1], 1e-6))
        phase = 2 * np.pi * np.cumsum(inst) / sr
        y = np.sin(phase) * env
    elif kind == "impact_only":
        y = np.zeros(n)
    else:  # "riser": white noise, high-passed-ish by differencing, swelling
        noise = rng.standard_normal(n)
        noise = np.diff(noise, prepend=noise[:1])    # crude brightening
        y = noise * env
    y = y / (np.max(np.abs(y)) + 1e-9)
    return (y * gain).astype(np.float32)


def _impact(sr, to_bpm, gain):
    """A short soft downbeat 'impact' -- a low sine thump with a fast decay.
    Length = one beat of the incoming tempo so it sits on the new downbeat."""
    beat_s = 60.0 / float(to_bpm)
    n = max(1, int(round(beat_s * sr)))
    t = np.arange(n) / sr
    f = 70.0                                          # sub/low thump
    body = np.sin(2 * np.pi * f * t) * np.exp(-t * 9.0)
    click = rng.standard_normal(n) * np.exp(-t * 40.0) * 0.3
    y = body + click
    y = y / (np.max(np.abs(y)) + 1e-9)
    return (y * gain).astype(np.float32)


def _overlay_tail(base, fx):
    """Add `fx` onto the END of `base` (aligned to base's last sample)."""
    out = base.copy().astype(np.float32)
    m = min(len(fx), len(out))
    out[-m:] += fx[-m:]
    return out


def _overlay_head(base, fx):
    """Add `fx` onto the START of `base`."""
    out = base.copy().astype(np.float32)
    m = min(len(fx), len(out))
    out[:m] += fx[:m]
    return out


# ---- 1) optionally re-time each segment mix to snapped big-step tempos ------
mixes = [np.asarray(m, dtype=np.float32) for m in seg_mixes]
step_tempos = []
for i, seg in enumerate(segments):
    src_bpm = float(seg["tempo_bpm"])
    if STEP_MODE == "snap":
        tgt_bpm = BAND_TARGET_BPM.get(seg["genre"], src_bpm)
    else:
        tgt_bpm = src_bpm
    step_tempos.append(tgt_bpm)
    mixes[i] = _retime_array_to_tempo(mixes[i], SR, src_bpm, tgt_bpm, OUT_DIR)

print("segment tempo steps (bpm):")
prev = None
for i, (seg, bpm) in enumerate(zip(segments, step_tempos)):
    jump = "" if prev is None else f"   (step {bpm - prev:+.0f} bpm)"
    print(f"  seg{i} {seg['genre']:5s}  {bpm:5.0f} bpm{jump}")
    prev = bpm


# ---- 2) add the transition FX at each seam, then hard-cut splice ------------
# We bake the FX directly into the segment mixes (riser onto the TAIL of the
# outgoing seg; impact onto the HEAD of the incoming seg) BEFORE the existing
# downbeat hard-cut splice runs. That way the proven splice logic is untouched
# and the FX simply rides across the seam it already makes.
if TRANSITION_STYLE != "none" and len(mixes) > 1:
    for i in range(len(mixes) - 1):
        out_bpm = step_tempos[i]
        in_bpm  = step_tempos[i + 1]
        beat_s  = 60.0 / out_bpm
        riser_dur = RISER_BEATS * beat_s
        if TRANSITION_STYLE in ("riser", "sweep"):
            fx = _riser(SR, riser_dur, TRANSITION_GAIN, kind=TRANSITION_STYLE)
            mixes[i] = _overlay_tail(mixes[i], fx)
        # soft downbeat impact on the incoming segment (all styles except none)
        imp = _impact(SR, in_bpm, TRANSITION_GAIN * 0.9)
        mixes[i + 1] = _overlay_head(mixes[i + 1], imp)

# write the (possibly re-timed + fx'd) mixes back out for the file-based splice
fx_wavs = []
for i, m in enumerate(mixes):
    p = os.path.join(OUT_DIR, f"_mix_fx_{i}.wav")
    # guard against clipping introduced by the overlay
    peak = np.max(np.abs(m)) + 1e-9
    if peak > 0.99:
        m = m * (0.99 / peak)
    sf.write(p, m.astype(np.float32), SR)
    fx_wavs.append(p)

if len(fx_wavs) == 1:
    import shutil
    shutil.copy(fx_wavs[0], OUT_FULL_WAV)
else:
    current = fx_wavs[0]
    for i in range(1, len(fx_wavs)):
        nxt = os.path.join(OUT_DIR, f"_chain_fx_{i}.wav")
        splice_beds_downbeat_hard_cut(
            current, fx_wavs[i], nxt,
            expected_tempo_a=float(step_tempos[i - 1]),
            expected_tempo_b=float(step_tempos[i]),
        )
        current = nxt
    import shutil
    shutil.copy(current, OUT_FULL_WAV)

y, sr = sf.read(OUT_FULL_WAV)
print(f"\nFULL AUDIO (big steps + '{TRANSITION_STYLE}' transitions): {OUT_FULL_WAV}")
print(f"  dur={len(y)/sr:.2f}s  max={np.abs(y).max():.3f}  "
      f"rms={np.sqrt(np.mean(y.astype(np.float64)**2)):.4f}")
assert np.abs(y).max() > 0, "full audio is silent"
assert np.all(np.isfinite(y)), "non-finite samples"
from IPython.display import Audio, display
display(Audio(OUT_FULL_WAV))
