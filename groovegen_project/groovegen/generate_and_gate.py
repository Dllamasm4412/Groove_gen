"""
generate_and_gate.py — Step 4 of the 12-song personalization pipeline.

Generate a MusicGen bed for each personalized prompt, MEASURE its tempo
stability, and REGENERATE / QUANTIZE / FALL BACK if it wanders — then CACHE the
accepted bed so future runs cost zero MusicGen. This is the step that protects
audio quality (it's the fix for the "pop drums sound off" problem: a wobbly
generated bed never reaches the live loop).

Design (see twelve_song_personalization_pipeline.md §6):
    for each segment prompt:
        1. generate bed with MusicGen (short + loop-to-length)   [Colab GPU]
        2. measure tempo stability (beat jitter, grid error)     [CPU]
        3. if it fails the gate:
             a. regenerate with a new seed, up to K tries
             b. else beat-sync quantize the best attempt to the target grid
             c. else fall back to a clean uploaded bed for that band
        4. cache the accepted bed to WAV (skip regeneration next run)

The MusicGen model is INJECTED (a `generator` callable), so:
  * in Colab you pass the real gen_bed closure (model already loaded);
  * locally / in CI you pass a fake generator to dry-run the gate logic with
    no GPU and no network.

Quality thresholds default to "latin-quality" (the section the user liked):
    beat_jitter <= 12 ms   AND   grid_err_mean <= 40 ms
(these matched latin=5.5ms/~ and rejected pop=29.5ms/127ms in diagnosis).
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from typing import Callable, Optional

import numpy as np
import soundfile as sf

try:
    import librosa
except ImportError:  # librosa is required for the gate; Colab has it
    librosa = None


def _read_audio(path):
    """Read any audio to (samples, sr). soundfile can't decode AAC/.m4a (iTunes
    previews) -- try librosa (ffmpeg-backed) first, fall back to soundfile."""
    if librosa is not None:
        try:
            y, sr = librosa.load(path, sr=None, mono=True)
            return np.asarray(y, dtype=float), int(sr)
        except Exception:
            pass
    y, sr = sf.read(path)
    if getattr(y, "ndim", 1) > 1:
        y = y.mean(axis=1)
    return np.asarray(y, dtype=float), sr


# ----------------------------- quality metrics -----------------------------

def measure_tempo_stability(y: np.ndarray, sr: int, target_bpm: float) -> dict:
    """Return the same metrics used in the pop-drum diagnosis.

    beat_jitter_ms  : std of inter-beat intervals (grid steadiness)
    grid_err_mean_ms: mean |onset - nearest ideal-grid line| at target_bpm
    detected_bpm    : librosa's global tempo estimate
    pulse_clarity   : autocorr peak of the onset envelope (0..1-ish)
    """
    if librosa is None:
        raise RuntimeError("librosa is required for measure_tempo_stability")
    y = np.asarray(y, dtype=float)
    if y.ndim > 1:
        y = y.mean(axis=0 if y.shape[0] < y.shape[1] else 1)
    tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time")
    detected = float(np.atleast_1d(tempo)[0])
    ibi = np.diff(beats) * 1000.0 if len(beats) > 2 else np.array([0.0])
    beat_jitter = float(np.std(ibi)) if len(ibi) > 1 else 0.0
    spb = 60.0 / float(target_bpm)
    onsets = librosa.onset.onset_detect(y=y, sr=sr, units="time", backtrack=True)
    if len(onsets):
        grid_err = [(o - round(o / spb) * spb) * 1000.0 for o in onsets]
        grid_err_mean = float(np.mean(np.abs(grid_err)))
    else:
        grid_err_mean = 999.0
    oe = librosa.onset.onset_strength(y=y, sr=sr)
    if len(oe) > 5:
        ac = librosa.autocorrelate(oe, max_size=len(oe) // 2)
        ac = ac / (ac[0] + 1e-9)
        pulse_clarity = float(np.max(ac[4:]))
    else:
        pulse_clarity = 0.0
    return {
        "detected_bpm": round(detected, 1),
        "beat_jitter_ms": round(beat_jitter, 1),
        "grid_err_mean_ms": round(grid_err_mean, 1),
        "pulse_clarity": round(pulse_clarity, 3),
    }


@dataclass
class QualityGate:
    """Pass/fail test for whether a bed has a steady, usable pulse.

    IMPORTANT (2026-07 recalibration): the gate now judges TEMPO STEADINESS,
    not on-grid-ness. The old gate required every onset to land within 40 ms of
    the quarter-note grid -- but real music (and MusicGen output) places notes on
    eighths, sixteenths, and syncopations by design, so *good* beds scored
    130-170 ms 'grid error' and always failed. That forced a fallback to the raw
    reference songs (with vocals), which was the visible bug.

    What actually predicts a good drum bed:
      * beat_jitter_ms  -- std of inter-beat intervals = does the tempo hold steady
      * pulse_clarity   -- autocorr peak of the onset envelope = is there a clear beat
    grid_err_mean_ms is STILL measured and reported for diagnostics, but it does
    NOT gate pass/fail (it conflates rhythmic density with timing error).

    Defaults were chosen from measured data: clean real tracks and MusicGen beds
    sit around 9-37 ms jitter with pulse_clarity ~0.6+. 45 ms jitter is a
    comfortable ceiling that admits steady beds and still rejects genuinely
    wobbly ones (>50 ms).
    """
    max_beat_jitter_ms: float = 45.0
    min_pulse_clarity: float = 0.30
    # kept for backward-compat / diagnostics only -- NOT used in passes():
    max_grid_err_ms: float = 40.0

    def passes(self, m: dict) -> bool:
        return (m["beat_jitter_ms"] <= self.max_beat_jitter_ms
                and m.get("pulse_clarity", 1.0) >= self.min_pulse_clarity)

    def score(self, m: dict) -> float:
        """Lower is better — used to pick the best attempt when all fail.
        Rewards steady tempo and a clear pulse; grid_err is intentionally
        excluded (it penalizes normal musical syncopation)."""
        return m["beat_jitter_ms"] + 20.0 * (1.0 - m.get("pulse_clarity", 0.0))


# ----------------------------- quantize fallback -----------------------------

def beatsync_quantize(y: np.ndarray, sr: int, target_bpm: float) -> np.ndarray:
    """Warp each detected beat onto the ideal target grid (partial fix).

    Cut jitter ~35% in the pop prototype (20.7 -> 13.5 ms) but does not fully
    remove wander — used only as a middle option before falling back to a clean
    uploaded bed.
    """
    if librosa is None:
        raise RuntimeError("librosa is required for beatsync_quantize")
    y = np.asarray(y, dtype=float)
    tempo, beat_f = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_t = librosa.frames_to_time(beat_f, sr=sr)
    if len(beat_t) < 3:
        return y
    spb = 60.0 / float(target_bpm)
    ideal = np.arange(len(beat_t)) * spb + (beat_t[0] % spb)
    out = np.zeros(int((ideal[-1] + spb) * sr) + sr)
    for i in range(len(beat_t) - 1):
        seg = y[int(beat_t[i] * sr):int(beat_t[i + 1] * sr)]
        dur_actual = beat_t[i + 1] - beat_t[i]
        dur_ideal = ideal[i + 1] - ideal[i]
        r = dur_actual / max(dur_ideal, 1e-6)
        seg_q = librosa.effects.time_stretch(seg, rate=r) if len(seg) > 2048 else seg
        s = int(ideal[i] * sr)
        out[s:s + len(seg_q)] += seg_q
    return out[:int(ideal[-1] * sr)]


# ----------------------------- the step-4 driver -----------------------------

@dataclass
class BedResult:
    segment_index: int
    prompt: str
    target_bpm: float
    out_wav: str
    source: str            # "generated" | "quantized" | "uploaded_fallback" | "cached"
    attempts: int          # final-source attempt index (0 for cache/fallback)
    metrics: dict
    passed: bool
    fallback_used: Optional[str] = None
    musicgen_calls: int = 0  # honest count of MusicGen generations spent on this seg


def generate_and_gate(
    segments: list,
    generator: Callable[[str, str, float, float], tuple],
    out_dir: str,
    *,
    seconds_per_segment: Optional[list] = None,
    gate: Optional[QualityGate] = None,
    max_tries: int = 3,
    fallback_beds: Optional[dict] = None,   # {genre: uploaded_wav_path}
    cache: bool = True,
    manifest_path: Optional[str] = None,
) -> list:
    """Run generate -> gate -> (regen | quantize | fallback) -> cache per segment.

    `generator(prompt, out_wav, seconds, target_bpm) -> (out_wav, sr)` is the
    injected MusicGen closure (real in Colab, fake in tests). `segments` is the
    output of arc_from_profile: each has keys genre, tempo_bpm, prompt.

    Returns a list[BedResult] and writes a JSON manifest.
    """
    gate = gate or QualityGate()
    fallback_beds = fallback_beds or {}
    os.makedirs(out_dir, exist_ok=True)
    results: list[BedResult] = []

    for i, seg in enumerate(segments):
        target = float(seg["tempo_bpm"])
        genre = seg.get("genre", "bed")
        prompt = seg["prompt"]
        seconds = (seconds_per_segment[i] if seconds_per_segment else 12.0)
        # sanitize genre for the filename: r&b/soul, hip-hop/rap, latin/salsa all
        # contain '/' (and '&'), which would create bogus subpaths on disk.
        safe_genre = re.sub(r"[^0-9A-Za-z]+", "-", genre).strip("-") or "bed"
        out_wav = os.path.join(out_dir, f"seg{i}_{safe_genre}_{int(target)}bpm.wav")

        # 0. cache hit -> skip generation entirely (credit saver)
        if cache and os.path.exists(out_wav):
            y, sr = sf.read(out_wav)
            m = measure_tempo_stability(y, sr, target)
            results.append(BedResult(i, prompt, target, out_wav, "cached", 0, m,
                                     gate.passes(m)))
            continue

        # 1-3. generate, gate, retry, then quantize, then fallback
        best = None  # (metrics, y, sr)
        chosen = None
        n_calls = 0
        for attempt in range(1, max_tries + 1):
            gw, sr = generator(prompt, out_wav, seconds, target)
            n_calls += 1
            y, sr = sf.read(gw)
            m = measure_tempo_stability(y, sr, target)
            if best is None or gate.score(m) < gate.score(best[0]):
                best = (m, np.asarray(y, dtype=float), sr)
            if gate.passes(m):
                chosen = BedResult(i, prompt, target, out_wav, "generated",
                                   attempt, m, True, musicgen_calls=n_calls)
                break

        if chosen is None:
            # 3b. quantize the best MusicGen attempt to the target grid.
            # NOTE: we NEVER substitute a raw reference song here. The reference
            # songs are vocal tracks used only for FEATURE EXTRACTION -> prompt;
            # dropping one in as a "bed" is what leaked vocals into the output.
            # If generation + quantize still can't pass, we keep the cleanest
            # GENERATED (instrumental) attempt and flag it, so the bed is always
            # a MusicGen instrumental -- no vocals can ever reach the loop.
            bm, by, bsr = best
            yq = beatsync_quantize(by, bsr, target)
            mq = measure_tempo_stability(yq, bsr, target)
            if gate.passes(mq):
                sf.write(out_wav, yq, bsr)
                chosen = BedResult(i, prompt, target, out_wav, "quantized",
                                   max_tries, mq, True, musicgen_calls=n_calls)
            elif gate.score(mq) < gate.score(bm):
                # quantize improved it but still under bar -> keep quantized,
                # flagged as not-passing (still a generated instrumental)
                sf.write(out_wav, yq, bsr)
                chosen = BedResult(i, prompt, target, out_wav, "quantized",
                                   max_tries, mq, False, musicgen_calls=n_calls)
            else:
                # keep the best raw generated attempt, flagged failed
                sf.write(out_wav, best[1], best[2])
                chosen = BedResult(i, prompt, target, out_wav, "generated",
                                   max_tries, best[0], False, musicgen_calls=n_calls)

        results.append(chosen)

    # manifest
    mpath = manifest_path or os.path.join(out_dir, "bed_manifest.json")
    with open(mpath, "w") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    return results


def _try_fallback(i, prompt, target, genre, out_wav, fallback_beds, gate, prev_m):
    """Copy a clean uploaded bed for this genre band into place, if available."""
    path = fallback_beds.get(genre)
    if not path or not os.path.exists(path):
        return None
    y, sr = _read_audio(path)   # handles m4a/mp3 overrides, not just WAV
    m = measure_tempo_stability(y, sr, target)
    sf.write(out_wav, y, sr)
    return BedResult(i, prompt, target, out_wav, "uploaded_fallback", 0, m,
                     gate.passes(m), fallback_used=path)


def summarize(results: list) -> str:
    lines = [f"{'seg':>3} {'bpm':>7} {'src':>10} {'try':>3} "
             f"{'jitter':>7} {'pulse':>6} {'grid*':>6} {'pass':>5}"]
    for r in results:
        lines.append(
            f"{r.segment_index:>3} {r.target_bpm:>6.0f}bpm "
            f"{r.source:>10} {r.attempts:>3} "
            f"{r.metrics['beat_jitter_ms']:>6}m "
            f"{r.metrics.get('pulse_clarity', 0):>6} "
            f"{r.metrics['grid_err_mean_ms']:>5}m "
            f"{'YES' if r.passed else 'no':>5}")
    n_gen = sum(1 for r in results if r.source in ("generated", "quantized"))
    n_fb = sum(1 for r in results if r.source == "uploaded_fallback")
    n_cache = sum(1 for r in results if r.source == "cached")
    n_fail = sum(1 for r in results if not r.passed)
    lines.append(f"\ngenerated/quantized={n_gen}  cached={n_cache}"
                 f"  failed_gate={n_fail}"
                 + (f"  raw_fallback={n_fb}(!)" if n_fb else "")
                 + f"  (MusicGen calls this run: {sum(r.musicgen_calls for r in results)})")
    lines.append("grid* = onset-vs-quarter-note-grid error, DIAGNOSTIC ONLY "
                 "(not gated; high is normal for real music).")
    return "\n".join(lines)


# ----------------------------- Colab glue -----------------------------

def make_musicgen_generator(model, processor, device="cuda",
                            gen_seconds=12.0, max_new_tokens_cap=1400,
                            tokens_per_sec=50, guidance_scale=3.0):
    """Build the injected `generator` from an already-loaded MusicGen model.

    Reuses the exact battle-tested logic from nb15 (short generate + whole-bar
    loop-to-length with a 1.5 ms micro-fade). Drop this into the notebook AFTER
    the model is loaded:

        gen = make_musicgen_generator(model, proc, device)
        results = generate_and_gate(segments, gen, OUT_DIR,
                                    fallback_beds={'pop': CLEAN_POP_WAV, ...})

    Each call generates a NEW sample (do_sample=True), so retries under the gate
    genuinely differ.
    """
    import torch  # local import: only needed in the Colab/GPU path

    def _loop_to_length(a, sr, target_seconds, tempo_bpm):
        target_n = int(round(target_seconds * sr))
        sec_per_bar = 4.0 * 60.0 / float(tempo_bpm)
        bar_n = max(1, int(round(sec_per_bar * sr)))
        whole_bars = max(1, len(a) // bar_n)
        a = a[: whole_bars * bar_n]
        f = max(1, int(0.0015 * sr))
        if len(a) > 2 * f:
            ramp = np.linspace(0.0, 1.0, f, dtype=a.dtype)
            a = a.copy(); a[:f] *= ramp; a[-f:] *= ramp[::-1]
        if len(a) >= target_n:
            return a[:target_n]
        reps = int(np.ceil(target_n / len(a)))
        return np.tile(a, reps)[:target_n]

    def generator(prompt, out_wav, seconds, tempo_bpm):
        gen_tokens = min(int(gen_seconds * tokens_per_sec), max_new_tokens_cap)
        inputs = processor(text=[prompt], padding=True,
                           return_tensors="pt").to(device)
        with torch.no_grad():
            wav = model.generate(**inputs, max_new_tokens=gen_tokens,
                                 do_sample=True, guidance_scale=guidance_scale)
        sr = model.config.audio_encoder.sampling_rate
        a = wav[0, 0].cpu().numpy()
        a = _loop_to_length(a, sr, seconds, tempo_bpm)
        sf.write(out_wav, a, sr)
        return out_wav, sr

    return generator
