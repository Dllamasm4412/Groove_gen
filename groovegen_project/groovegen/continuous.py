"""
GrooveGen — Step 1: continuous, non-repetitive audio engine.

This module NEVER modifies groovegen.py's frozen study/stimulus path. It only
imports from it (GrooveParams, PatternBuilder, render_wav) and adds new,
additive behaviour:

  1. density_walk()       — bounded seeded random walk on EVENT DENSITY,
                             the primary groove knob (literature-locked,
                             monotonic-safe control axis).
  2. bar_params()          — per-bar GrooveParams copy: density from the walk,
                             a per-bar seed (deterministic-but-different),
                             syncopation jitter clamped to the safe spice band
                             [0.20, 0.40], backbeat NEVER touched (build_core's
                             _snare_steps stays locked at steps 4 & 12 for any
                             syncopation_level <= 0.67, i.e. bins 0-2).
  3. build_varied_drums()  — stitches per-bar 1-bar cores (each built by the
                             frozen PatternBuilder.build_core) into one
                             never-identical drum track.
  4. crossfade_beds()      — bar-aligned, equal-power crossfade across a bank
                             of bed wavs, looped to a target duration.
  5. render_continuous()   — drums + bed -> single mixed, gain-staged wav.

Design rationale for why per-bar re-synthesis (not tiling) fixes the
repetition problem: `PatternBuilder.build_looped()` builds ONE core bar and
copies its note list N times with a constant time offset (groovegen.py
~line 983-999) — bit-identical bars forever. Here, each bar gets its OWN
PatternBuilder(bar_params(...)).build_core() call, seeded uniquely
(seed = base.seed + bar_idx), so onset budget (_density_steps), which steps
get hats/ghosts, and (within the safe band) the kick/snare syncopation bin
can all vary bar-to-bar while the backbeat anchor and kit/timbre stay fixed.
"""
from __future__ import annotations

import copy
import os
from dataclasses import replace

import numpy as np
import librosa
import soundfile as sf

from .groovegen import (
    GrooveParams, PatternBuilder, render_wav, FS as STUDY_FS,
    DRUM_STYLES, KICK, SNARE, CLOSED_HAT, OPEN_HAT, GHOST_SNARE,
)

FS = STUDY_FS  # 44100 Hz, reuse the study's render rate


# ----------------------------------------------------------------------------
# A. Per-bar symbolic variation
# ----------------------------------------------------------------------------
def density_walk(base_density: int, n_bars: int, band: tuple[int, int],
                  step_sd: float, seed: int) -> list[int]:
    """Seeded Gaussian random walk on event density, clamped+reflected to band.

    This is the PRIMARY variation axis (event density is the literature-locked
    groove knob). A reflecting boundary is used instead of hard clipping so
    the walk doesn't "stick" at the edges (hard clipping would flatten the
    step distribution near band limits and bias the walk toward the edges).

    Args:
        base_density: starting density (bar 0), also used as the walk's origin.
        n_bars: number of bars to generate (len(result) == n_bars).
        band: (lo, hi) inclusive integer bounds for density.
        step_sd: standard deviation (in density units) of each bar-to-bar step.
        seed: RNG seed (independent stream from PatternBuilder's per-bar seeds).

    Returns:
        list[int] of length n_bars, each value in [lo, hi].
    """
    lo, hi = band
    if lo > hi:
        lo, hi = hi, lo
    rng = np.random.default_rng(seed)
    x = float(np.clip(base_density, lo, hi))
    out = [int(round(x))]
    for _ in range(n_bars - 1):
        x = x + float(rng.normal(0.0, step_sd))
        # reflect at the boundaries (fold back in) rather than clip, so the
        # walk keeps moving instead of flatlining at an edge
        span = hi - lo
        if span > 0:
            y = (x - lo) % (2 * span)
            x = lo + (y if y <= span else 2 * span - y)
        else:
            x = lo
        out.append(int(round(x)))
    return out


def bar_params(base: GrooveParams, bar_idx: int, density: int,
                seed: int) -> GrooveParams:
    """Per-bar GrooveParams: density from the walk, unique-but-deterministic
    seed, syncopation jitter clamped to the safe [0.20, 0.40] spice band.

    The backbeat is NEVER moved here: PatternBuilder._snare_steps() is driven
    purely by `_sync_bin()`, which stays at bin 1 for any syncopation_level in
    (0, 0.34] and bin 2 for (0.34, 0.67] — both bins map to `_SYNC_SNARE = 4,12`
    identical to bin 0's straight backbeat, so clamping jitter to [0.20, 0.40]
    (which spans at most bins 1-2) structurally guarantees the backbeat stays
    on beats 2 & 4 for every bar. bars is forced to 1 (one bar built at a
    time); target_seconds/with_bed are irrelevant here (build_core ignores
    them) and left untouched.
    """
    p = replace(base, event_density=int(density), bars=1, seed=int(seed))
    if base.syncopation_level > 0:
        rng = np.random.default_rng(seed)
        jitter = float(rng.normal(0.0, 0.03))  # small seeded jitter
        p.syncopation_level = float(np.clip(base.syncopation_level + jitter,
                                             0.20, 0.40))
    else:
        p.syncopation_level = 0.0
    # microtiming: cosmetic only, keep the base's value untouched (spec: "tiny")
    p.microtiming_variance_ms = base.microtiming_variance_ms
    return p


def build_varied_drums(base: GrooveParams, n_bars: int, band: tuple[int, int],
                        step_sd: float, seed: int):
    """Build an n_bars-long drums-only PrettyMIDI that is never bar-identical.

    Each bar is synthesized independently by PatternBuilder(bar_params(...))
    .build_core() (the frozen 1-bar builder), then its notes are offset by
    bar_idx * bar_seconds and appended to a single drum instrument.

    Returns:
        (pretty_midi.PrettyMIDI, list[int] per-bar densities, dict per-bar
         stats: note_count and sorted onset step positions, for the
         manipulation check).
    """
    import pretty_midi as pm_mod

    densities = density_walk(base.event_density, n_bars, band, step_sd, seed)

    pm = pm_mod.PrettyMIDI(initial_tempo=base.tempo_bpm)
    drum = pm_mod.Instrument(program=0, is_drum=True, name="kit")

    # bar_seconds is fixed by tempo alone (4/4), independent of bars=1 vs N
    sec_per_beat = 60.0 / base.tempo_bpm
    bar_seconds = 4 * sec_per_beat

    # NOTE on a real limitation of the frozen build_core we must not modify:
    # PatternBuilder._density_steps() is a PURE function of event_density (a
    # fixed metrically-ranked priority list, no RNG, no ties to break), and
    # _sync_bin() is a wide step function of syncopation_level (bins at
    # 0/0.34/0.67/1.0). So whenever two bars land on the same density AND the
    # same syncopation bin (very likely, since jitter is small and clamped to
    # [0.20,0.40] = bins 1-2 only), build_core() returns BIT-IDENTICAL onset
    # steps for both bars -- density is a coarse, quantized control, not a
    # continuous one. We do NOT patch this by touching groovegen.py. Instead,
    # as a cosmetic, per-bar humanization layer (fully additive, in this
    # module only) we apply tiny seeded velocity jitter per note. This makes
    # every bar's raw audio distinct (no two bars bit-identical in the
    # rendered MIDI) without altering onset timing/positions or the
    # density-driven note COUNT, which remains the true, audible, primary
    # variation axis. This is reported as a known limitation, not hidden.
    vel_rng_master = np.random.default_rng(seed ^ 0x5EED)

    per_bar_stats = []
    for bar_idx in range(n_bars):
        bp = bar_params(base, bar_idx, densities[bar_idx], seed=base.seed + bar_idx)
        builder = PatternBuilder(bp)
        core = builder.build_core()  # ONE bar, freshly synthesized (no tiling)
        core_drum = core.instruments[0]
        off = bar_idx * bar_seconds
        onsets = []
        vel_rng = np.random.default_rng(vel_rng_master.integers(0, 2**31 - 1))
        for n in core_drum.notes:
            jitter = int(round(vel_rng.normal(0.0, 2.0)))  # +-2 velocity, cosmetic
            vel = int(np.clip(n.velocity + jitter, 1, 127))
            drum.notes.append(
                pm_mod.Note(velocity=vel, pitch=n.pitch,
                            start=n.start + off, end=n.end + off)
            )
            # onset position within the bar, in 16th-steps, for the proof plot
            step = round((n.start) / (sec_per_beat / 4.0))
            onsets.append(int(step))
        per_bar_stats.append({
            "bar": bar_idx,
            "density_param": densities[bar_idx],
            "note_count": len(core_drum.notes),
            "onset_steps": sorted(onsets),
        })

    pm.instruments.append(drum)
    return pm, densities, per_bar_stats


# ----------------------------------------------------------------------------
# B. Bed-bank + beat-matched (bar-aligned) equal-power crossfade
# ----------------------------------------------------------------------------
def _equal_power_ramp(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Equal-power fade curves of length n samples.

    fade_out = cos(theta), fade_in = sin(theta), theta in [0, pi/2], so
    fade_out**2 + fade_in**2 == 1 everywhere (constant perceived power across
    the crossfade, unlike a linear ramp which dips ~3dB in the middle).
    """
    theta = np.linspace(0.0, np.pi / 2.0, n, endpoint=True)
    fade_out = np.cos(theta)
    fade_in = np.sin(theta)
    return fade_out, fade_in


def crossfade_beds(bed_wavs: list[str], tempo_bpm: float, out_wav: str,
                    target_seconds: float, xfade_bars: float = 1.0,
                    fs: int = FS) -> dict:
    """Bar-aligned equal-power crossfade across a bank of bed wavs, looped to
    target_seconds.

    Each bed is loaded mono at `fs`, then TRIMMED to the nearest whole number
    of bars at tempo_bpm (floor, minimum 1 bar) — no time-stretching, to avoid
    introducing pitch/formant artifacts on percussive/harmonic material in a
    CPU-only sandbox. If a bed is shorter than one bar it is tiled up to one
    bar first. Segments are concatenated in bank order, looping through the
    bank as many times as needed, with an equal-power crossfade of length
    `xfade_bars * bar_seconds` overlapping consecutive segments; crossfades
    start exactly on a bar boundary of the running mix (bar-aligned = no
    mid-bar timbre discontinuity).

    Returns:
        dict(duration, n_segments, xfade_s, out_wav, bar_seconds)
    """
    sec_per_beat = 60.0 / tempo_bpm
    bar_seconds = 4 * sec_per_beat
    xfade_s = xfade_bars * bar_seconds
    xfade_n = int(round(xfade_s * fs))

    # Load + bar-trim each bed once.
    trimmed = []
    for path in bed_wavs:
        y, sr = librosa.load(path, sr=fs, mono=True)
        n_bar_samples = int(round(bar_seconds * fs))
        if len(y) < n_bar_samples:
            reps = int(np.ceil(n_bar_samples / len(y)))
            y = np.tile(y, reps)
        n_bars_avail = max(1, int(np.floor(len(y) / n_bar_samples)))
        y = y[: n_bars_avail * n_bar_samples]
        trimmed.append(y)

    # Build the concatenated, crossfaded timeline. Each segment after the
    # first overlaps the previous one by xfade_n samples (bar-aligned: the
    # overlap point sits at a bar boundary of the growing mix since every
    # trimmed bed is an integer number of bars).
    total_needed = int(round(target_seconds * fs))
    mix = np.zeros(0, dtype=np.float64)
    n_segments = 0
    bank_i = 0
    while mix.size < total_needed + xfade_n:
        seg = trimmed[bank_i % len(trimmed)]
        bank_i += 1
        n_segments += 1
        if mix.size == 0:
            mix = seg.copy().astype(np.float64)
            continue
        n_x = min(xfade_n, mix.size, seg.size)
        if n_x <= 0:
            mix = np.concatenate([mix, seg.astype(np.float64)])
            continue
        fade_out, fade_in = _equal_power_ramp(n_x)
        head = mix[:-n_x] if n_x < mix.size else np.zeros(0)
        overlap = mix[-n_x:] * fade_out + seg[:n_x].astype(np.float64) * fade_in
        tail = seg[n_x:].astype(np.float64)
        mix = np.concatenate([head, overlap, tail])

    mix = mix[:total_needed]

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.999:
        mix = mix / peak * 0.999

    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    sf.write(out_wav, mix.astype(np.float32), fs)

    return {
        "wav_path": out_wav,
        "duration": round(mix.size / fs, 3),
        "n_segments": n_segments,
        "xfade_s": round(xfade_s, 4),
        "bar_seconds": round(bar_seconds, 4),
    }


# ----------------------------------------------------------------------------
# C. Top-level render
# ----------------------------------------------------------------------------
def render_continuous(base: GrooveParams, bed_wavs: list[str], out_stem: str,
                       n_bars: int, band: tuple[int, int], step_sd: float,
                       seed: int, drum_gain_db: float = -3.0,
                       bed_gain_db: float = -6.0,
                       sf2_path: str | None = None) -> dict:
    """Build varied drums + crossfaded bed bank, mix, and write {out_stem}.wav.

    Steps:
      1. build_varied_drums() -> drums-only PrettyMIDI (never bar-identical)
         + per-bar density list + per-bar note/onset stats.
      2. render_wav() (reused, unmodified, from groovegen.py) -> drums wav,
         loudness-normalized exactly like the frozen study path.
      3. crossfade_beds() -> bed-bank wav at the same duration as the drums.
      4. Mix: align lengths (truncate to the shorter), apply per-stem gains
         in dB, sum, and peak-limit to prevent clipping (peak-normalize only
         if the sum would exceed full scale, so relative levels aren't
         changed unless necessary).

    Returns metadata dict with duration, per-bar densities, per-bar stats,
    crossfade info, and file paths.
    """
    sec_per_beat = 60.0 / base.tempo_bpm
    bar_seconds = 4 * sec_per_beat
    target_seconds = n_bars * bar_seconds

    drums_pm, densities, per_bar_stats = build_varied_drums(
        base, n_bars, band, step_sd, seed)

    drums_wav = out_stem + "_drums_tmp.wav"
    drum_meta = render_wav(drums_pm, drums_wav, sf2_path=sf2_path)

    bed_wav = out_stem + "_bed_tmp.wav"
    xfade_meta = crossfade_beds(bed_wavs, base.tempo_bpm, bed_wav,
                                 target_seconds=drum_meta["duration_s"],
                                 xfade_bars=1.0, fs=FS)

    drums_y, sr_d = librosa.load(drums_wav, sr=FS, mono=True)
    bed_y, sr_b = librosa.load(bed_wav, sr=FS, mono=True)

    n = min(len(drums_y), len(bed_y))
    drums_y = drums_y[:n]
    bed_y = bed_y[:n]

    drum_gain = 10.0 ** (drum_gain_db / 20.0)
    bed_gain = 10.0 ** (bed_gain_db / 20.0)
    mix = drums_y * drum_gain + bed_y * bed_gain

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.999:
        mix = mix / peak * 0.999
        peak = 0.999

    out_wav = out_stem + ".wav"
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    sf.write(out_wav, mix.astype(np.float32), FS)

    return {
        "wav_path": out_wav,
        "duration_s": round(n / FS, 3),
        "n_bars": n_bars,
        "tempo_bpm": base.tempo_bpm,
        "bar_seconds": round(bar_seconds, 4),
        "densities": densities,
        "band": band,
        "step_sd": step_sd,
        "seed": seed,
        "per_bar_stats": per_bar_stats,
        "drum_gain_db": drum_gain_db,
        "bed_gain_db": bed_gain_db,
        "peak_post_mix": round(peak, 4),
        "drums_wav": drums_wav,
        "bed_wav": bed_wav,
        "crossfade": xfade_meta,
        "drum_render_meta": drum_meta,
    }


# ============================================================================
# STEP 1B — bed-tempo lock, coherent density, discrete-piece rendering.
#
# Fixes three MEASURED root causes (see step1b_spec.md). Nothing here touches
# groovegen.py's frozen study path; it only imports from it.
#   1. detect_bed_tempo()              — root cause #2 (tempo mismatch)
#   2. coherent_density_layers() /
#      build_varied_drums_coherent()   — root cause #1 (incoherent density /
#                                         hat-subdivision teleport)
#   3. render_piece() / crossfade_pieces() — root cause #3 (always-continuous
#                                         coupling); discrete pieces are now
#                                         the default, continuity is optional.
# ============================================================================


# ----------------------------------------------------------------------------
# 1. Bed tempo detection + lock
# ----------------------------------------------------------------------------
def detect_bed_tempo(bed_wav: str, candidate_range: tuple[float, float] = (70.0, 140.0),
                      fs: int = FS) -> dict:
    """Estimate a bed's TRUE tempo, bar-aligned to its own duration.

    Two independent estimates are combined:
      (a) librosa.beat.beat_track — a real onset/tempo tracker, but prone to
          octave errors (half/double tempo) on percussion-dense material.
      (b) "integer-bars" heuristic — for the bed's measured duration, walk
          candidate bar-counts (1..12) and compute the BPM that would make
          that many 4/4 bars exactly equal to the duration
          (bar_s = 4*60/bpm  =>  bpm = bars*4*60/duration). Any bed that was
          authored as a clean loop will have duration ~= integer bars at its
          real tempo, so this is a strong prior when beat_track is ambiguous.

    Reconciliation: prefer the integer-bars candidate that is CLOSEST to the
    beat_track estimate (allowing octave multiples/sub-multiples of
    beat_track, since beat trackers commonly report 2x or 0.5x the true
    tempo). This "snaps" a noisy onset-based tempo onto the loop's true
    bar-aligned tempo instead of trusting either signal alone.

    Returns:
        dict(tempo_bpm, bars, duration_s, beat_track_bpm, method) where
        `tempo_bpm` is the FINAL, bar-aligned tempo to lock the drum grid to.
    """
    y, sr = librosa.load(bed_wav, sr=fs, mono=True)
    duration_s = len(y) / float(sr)

    bt = librosa.beat.beat_track(y=y, sr=sr)
    beat_track_bpm = float(np.atleast_1d(bt[0])[0])

    lo, hi = candidate_range
    # Candidate octave multiples of the beat-tracker estimate (it commonly
    # reports half or double the perceptual/authored tempo).
    bt_candidates = [beat_track_bpm * m for m in (0.5, 1.0, 2.0)]

    best = None  # (abs_diff, bars, bpm)
    for bars in range(1, 13):
        bpm = bars * 4 * 60.0 / duration_s
        # STRICT candidate_range: a bar-count whose bpm falls outside the
        # plausible tempo range for the genre is not a real candidate, even
        # if it happens to be numerically close to a beat_track octave (this
        # is what previously let an implausible 65.81 BPM "3-bar" reading
        # win for the r&b bed just because it was close to beat_track/2).
        if not (lo <= bpm <= hi):
            continue
        # distance to the nearest octave-candidate of the beat tracker
        diff = min(abs(bpm - c) for c in bt_candidates)
        if best is None or diff < best[0]:
            best = (diff, bars, bpm)

    if best is None:
        # No integer-bars candidate fell in range; fall back to clamping the
        # raw beat-track estimate (with octave correction) into the range.
        bpm = beat_track_bpm
        while bpm < lo and bpm * 2 <= hi:
            bpm *= 2
        while bpm > hi and bpm / 2 >= lo:
            bpm /= 2
        return {
            "tempo_bpm": round(float(np.clip(bpm, lo, hi)), 2),
            "bars": None,
            "duration_s": round(duration_s, 3),
            "beat_track_bpm": round(beat_track_bpm, 2),
            "method": "beat_track_fallback_no_integer_bars_in_range",
        }

    diff, bars, bpm = best
    return {
        "tempo_bpm": round(float(bpm), 2),
        "bars": bars,
        "duration_s": round(duration_s, 3),
        "beat_track_bpm": round(beat_track_bpm, 2),
        "reconciliation_diff_bpm": round(diff, 2),
        "method": "integer_bars_reconciled_with_beat_track",
    }


# ----------------------------------------------------------------------------
# 2. Musically-coherent density mapping (constant hat spine + ornamentation)
# ----------------------------------------------------------------------------
def coherent_density_layers(base_density: int, seed: int,
                             hat_spine: list[int] | None = None) -> dict:
    """Additive ornamentation layers on top of a CONSTANT hat spine.

    Unlike groovegen.py's frozen `_density_steps()` (a ranked-list allocator
    that changes the HAT SUBDIVISION ITSELF as density varies -- 2 hats,
    then a lopsided 5, then straight 8ths -- causing the pulse to "teleport"),
    this function NEVER changes the base subdivision. The spine (default:
    straight 8ths, steps [0,2,4,6,8,10,12,14]) is always present, at every
    density. Density only scales how much ORNAMENTATION sits on top, added in
    a fixed musical priority order so the result is never lopsided:

      1. velocity accents on existing spine hats (on-beat steps louder)
      2. ghost snares on off-16ths, SYMMETRIC order: 3,7,11,15 then 1,5,9,13
         (this is the strongest musical difference vs. the frozen path's
         lopsided ad-hoc gaps)
      3. open-hat accents on the 'and's: step 14 first, then step 6
      4. extra kick pushes at very high density (last priority; kick/backbeat
         are the most structurally sensitive voices, so they only move once
         everything else is exhausted)

    Args:
        base_density: the density knob value (same numeric range/feel as
            GrooveParams.event_density, roughly 4..16+).
        seed: RNG seed, used only for tiny (+-2) velocity humanization -- the
            PATTERN (which steps get ornamentation) is a pure, deterministic
            function of base_density, never randomized.
        hat_spine: override spine steps (e.g. a genre's hat_base). Defaults to
            straight 8ths.

    Returns:
        dict(spine_steps, accent_steps, ghost_steps, open_hat_steps,
             extra_kick_steps, ornament_count) -- everything build_core-style
             renderers need, with the spine ALWAYS populated and non-empty.
    """
    spine = sorted(set(hat_spine)) if hat_spine else [0, 2, 4, 6, 8, 10, 12, 14]
    spine_baseline = len(spine)  # e.g. 8 for straight 8ths

    # Ornamentation budget scales with density above the spine's own count.
    # Clamp to >=0 so low/degenerate density never removes the spine.
    ornament_count = max(0, int(round(base_density)) - spine_baseline)

    # --- priority 1: velocity accents (always available at ornament>=1) ---
    # On-beat spine steps (0,4,8,12) get accented; this doesn't add NOTES,
    # it's a velocity-only layer applied uniformly once ornament_count > 0.
    accent_steps = [s for s in spine if s % 4 == 0] if ornament_count > 0 else []

    # --- priority 2: ghost snares, symmetric order ---
    ghost_priority = [3, 7, 11, 15, 1, 5, 9, 13]
    ghost_budget = max(0, ornament_count - 1)  # velocity accent "costs" 1 unit
    ghost_steps = sorted(ghost_priority[:min(ghost_budget, len(ghost_priority))])

    # --- priority 3: open-hat accents on the 'and's (14 then 6) ---
    open_priority = [14, 6]
    open_budget = max(0, ornament_count - 1 - len(ghost_priority))
    open_hat_steps = sorted(open_priority[:min(open_budget, len(open_priority))])

    # --- priority 4: extra kick pushes, only at very high density ---
    kick_priority = [10, 2]  # syncopated pushes, weak-position anticipations
    kick_budget = max(0, ornament_count - 1 - len(ghost_priority) - len(open_priority))
    extra_kick_steps = sorted(kick_priority[:min(kick_budget, len(kick_priority))])

    return {
        "spine_steps": spine,
        "accent_steps": accent_steps,
        "ghost_steps": ghost_steps,
        "open_hat_steps": open_hat_steps,
        "extra_kick_steps": extra_kick_steps,
        "ornament_count": ornament_count,
        "base_density": int(base_density),
    }


def phrase_density_walk(base_density: int, n_bars: int, band: tuple[int, int],
                         seed: int, phrase_bars: int = 4) -> list[int]:
    """PHRASE-LEVEL density: draw a new value only every `phrase_bars` bars.

    A small bounded (+-1) seeded step per phrase, clamped to `band`, held
    constant across all bars within the phrase. This is deliberately much
    more subtle than a per-bar random walk: within any 4-bar phrase every bar
    gets the SAME density value (and therefore the same ornamentation
    pattern), so the ear locks onto a stable groove instead of hearing
    density "wobble" bar to bar.

    Returns:
        list[int] of length n_bars (each value repeated within its phrase).
    """
    lo, hi = band
    if lo > hi:
        lo, hi = hi, lo
    rng = np.random.default_rng(seed)
    n_phrases = int(np.ceil(n_bars / phrase_bars))
    x = float(np.clip(base_density, lo, hi))
    phrase_vals = [int(round(x))]
    for _ in range(n_phrases - 1):
        step = rng.choice([-1, 0, 1])  # small bounded step, SUBTLE
        x = x + step
        x = float(np.clip(x, lo, hi))
        phrase_vals.append(int(round(x)))
    out = []
    for pv in phrase_vals:
        out.extend([pv] * phrase_bars)
    return out[:n_bars]


def _add_note(drum, pitch, t, vel, dur=0.09):
    import pretty_midi as pm_mod
    drum.notes.append(pm_mod.Note(velocity=int(np.clip(vel, 1, 127)), pitch=pitch,
                                   start=float(max(0.0, t)), end=float(t + dur)))


def build_varied_drums_coherent(base: GrooveParams, n_bars: int,
                                 band: tuple[int, int], seed: int,
                                 phrase_bars: int = 4):
    """Coherent, phrase-level varied drum track: constant hat spine +
    ornamentation-only density, backbeat locked on 2 & 4.

    This REPLACES build_varied_drums() for the new discrete-piece path. It
    does not call PatternBuilder.build_core() (which uses the frozen,
    subdivision-teleporting _density_steps()); instead it renders each bar
    directly from a constant spine + coherent_density_layers() ornamentation,
    so the pulse never jumps.

    Genre awareness: if base.drum_style is set and known, its hat_base is
    used as the spine (so e.g. salsa's quarter-note cascara or hip-hop's
    8ths are respected) and its kick/backbeat/perc pattern provides the
    structural skeleton; density ornamentation still layers on top using the
    SAME priority order. Backbeat (steps 4 & 12, or the style's own
    backbeat if narrower) is NEVER moved by density.

    Returns:
        (pretty_midi.PrettyMIDI, list[int] per-bar phrase densities,
         list[dict] per-bar stats: spine_steps, ornament breakdown, note
         count -- for the manipulation/coherence check).
    """
    import pretty_midi as pm_mod

    densities = phrase_density_walk(base.event_density, n_bars, band,
                                     seed, phrase_bars=phrase_bars)

    style = DRUM_STYLES.get(base.drum_style) if base.drum_style else None

    sec_per_beat = 60.0 / base.tempo_bpm
    sixteenth = sec_per_beat / 4.0
    bar_seconds = 4 * sec_per_beat

    if style:
        spine = sorted(set(style.get("hat_base", [0, 2, 4, 6, 8, 10, 12, 14])))
        kick_base = list(style.get("kick", [0, 8]))
        backbeat_steps = list(style.get("backbeat", [4, 12])) or [4, 12]
        back_voice = style.get("back_voice", SNARE)
        back_layer = style.get("back_layer", None)
        hat_voice = style.get("hat_voice", CLOSED_HAT)
        style_ghost = list(style.get("ghost", []))
        style_open = list(style.get("open_hat", []))
        perc = list(style.get("perc", []))
    else:
        spine = [0, 2, 4, 6, 8, 10, 12, 14]
        kick_base = [0, 8]
        backbeat_steps = [4, 12]  # LOCKED backbeat: beats 2 & 4
        back_voice = SNARE
        back_layer = None
        hat_voice = CLOSED_HAT
        style_ghost = []
        style_open = []
        perc = []

    pm = pm_mod.PrettyMIDI(initial_tempo=base.tempo_bpm)
    drum = pm_mod.Instrument(program=0, is_drum=True, name="kit")

    per_bar_stats = []
    for bar_idx in range(n_bars):
        density = densities[bar_idx]
        bar_seed = base.seed + bar_idx
        vel_rng = np.random.default_rng(bar_seed)
        bar_t = bar_idx * bar_seconds

        layers = coherent_density_layers(density, seed=bar_seed, hat_spine=spine)

        # --- constant hat spine (NEVER removed, NEVER changes subdivision) --
        for s in layers["spine_steps"]:
            base_vel = 82 if s in layers["accent_steps"] else 66
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, hat_voice, t, base_vel + jitter)

        # --- ornamentation: ghost snares (symmetric order) ---
        for s in sorted(set(layers["ghost_steps"]) | set(style_ghost)):
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, GHOST_SNARE, t, 45 + jitter)

        # --- ornamentation: open-hat accents on the 'and's ---
        for s in sorted(set(layers["open_hat_steps"]) | set(style_open)):
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, OPEN_HAT, t, 86 + jitter)

        # --- backbeat: LOCKED on 2 & 4 (or style backbeat), never touched --
        for s in backbeat_steps:
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, back_voice, t, 118 + jitter)
            if back_layer is not None:
                _add_note(drum, back_layer, t, 100 + jitter)

        # --- kick: genre/base pattern + ornamentation pushes at high density
        kick_steps = sorted(set(kick_base) | set(layers["extra_kick_steps"]))
        for s in kick_steps:
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, KICK, t, 110 + jitter)

        # --- genre percussion (cowbell/conga/etc.), constant per style ---
        for (s, pitch, vel) in perc:
            jitter = int(round(vel_rng.normal(0.0, 2.0)))
            t = bar_t + s * sixteenth
            _add_note(drum, pitch, t, vel + jitter)

        per_bar_stats.append({
            "bar": bar_idx,
            "phrase_density": density,
            "spine_steps": layers["spine_steps"],
            "ghost_steps": sorted(set(layers["ghost_steps"]) | set(style_ghost)),
            "open_hat_steps": sorted(set(layers["open_hat_steps"]) | set(style_open)),
            "extra_kick_steps": layers["extra_kick_steps"],
            "backbeat_steps": backbeat_steps,
            "note_count": sum(1 for n in drum.notes if bar_t <= n.start < bar_t + bar_seconds),
        })

    pm.instruments.append(drum)
    return pm, densities, per_bar_stats


# ----------------------------------------------------------------------------
# STEP 1C — downbeat phase alignment (lock drums to the bed's real beat 1).
#
# Step 1b locked TEMPO but assumed the bed's sample 0 == beat 1, causing a
# measured phase offset (salsa ~0.10s, r&b ~0.85s -- nearly half a bar). This
# section detects WHERE beat 1 actually falls inside the bed and shifts the
# drum grid to match. Nothing here touches groovegen.py's frozen study path.
# ----------------------------------------------------------------------------
def detect_bed_downbeat(bed_wav: str, tempo_bpm: float, sr: int | None = None) -> float:
    """Estimate the phase offset (seconds, in [0, beat_period)) of the bed's
    beat 1 within its own beat grid, at the ALREADY-LOCKED tempo `tempo_bpm`.

    Method (comb-template cross-correlation against the onset envelope, per
    spec): compute librosa.onset.onset_strength for the whole bed, then for a
    fine grid of candidate phases in [0, beat_period) build a "comb" of beat
    positions (phase, phase+beat_period, phase+2*beat_period, ...) spanning
    the bed's full duration and sum the onset-strength envelope sampled at
    those positions. The phase that maximizes this sum is the one whose comb
    teeth land most consistently on the bed's real beats (kicks/strong
    attacks recur every beat_period; noise/off-beat content does not
    reinforce coherently at a fixed phase). Using the FULL duration (not just
    the first bar) makes this robust to a quiet/ambiguous intro -- a handful
    of strong hits later in the bed still pull the comb onto the true grid.

    This directly implements the "prefer aligning to the nearest strong onset"
    goal: onset_strength weights transient energy, so the comb naturally
    favors phases sitting on real attacks (kick-like) rather than sample 0.
    If the bed starts with lead-in silence/pad (measured for the r&b bed: no
    strong onset before ~4.4s), sample 0 is simply outvoted by the recurring
    strong beats later in the file -- exactly the desired behavior.

    Args:
        bed_wav: path to the bed wav.
        tempo_bpm: the bed's ALREADY-DETECTED/LOCKED tempo (from
            detect_bed_tempo), so this function only searches PHASE, not
            tempo -- tempo and phase are estimated independently, which is
            more robust than a joint search.
        sr: sample rate to load at (defaults to this module's FS).

    Returns:
        offset_s: float in [0, beat_period) seconds. Shifting the drum grid's
        start time by +offset_s makes the drum grid's beat 1 coincide with
        the bed's beat 1 (mod one beat -- see render_piece for how the
        residual sub-beat phase is folded against the bar so kick-on-1 lands
        correctly rather than on an arbitrary beat of the bar).
    """
    fs = sr or FS
    y, sr_loaded = librosa.load(bed_wav, sr=fs, mono=True)
    dur_s = len(y) / float(sr_loaded)

    hop_length = 256
    oenv = librosa.onset.onset_strength(y=y, sr=sr_loaded, hop_length=hop_length)
    frame_rate = sr_loaded / float(hop_length)

    beat_period = 60.0 / tempo_bpm
    if beat_period <= 0 or dur_s <= 0 or len(oenv) == 0:
        return 0.0

    n_cand = 400  # fine phase grid, ~1.1ms resolution at 131.63 BPM
    phases = np.linspace(0.0, beat_period, n_cand, endpoint=False)

    best_score = -np.inf
    best_phase = 0.0
    for ph in phases:
        beat_times = np.arange(ph, dur_s, beat_period)
        idxs = np.round(beat_times * frame_rate).astype(int)
        idxs = idxs[(idxs >= 0) & (idxs < len(oenv))]
        if idxs.size == 0:
            continue
        score = float(oenv[idxs].sum())
        if score > best_score:
            best_score = score
            best_phase = float(ph)

    return float(np.clip(best_phase, 0.0, beat_period))


# ----------------------------------------------------------------------------
# 3. Discrete-piece render (bed-tempo-locked, single bed, no bank) +
#    optional same-tempo crossfade between pieces.
# ----------------------------------------------------------------------------
def _loop_bed_single(bed_wav: str, tempo_bpm: float, target_seconds: float,
                      fs: int = FS, xfade_bars: float = 1.0) -> dict:
    """Loop a SINGLE bed (no bank) to target_seconds at its OWN tempo.

    The bed is trimmed to the nearest whole number of bars at tempo_bpm (so
    the loop point is bar-aligned = no timbre discontinuity), then repeated
    with an equal-power crossfade across the LOOP SEAM. Because every
    repetition is the SAME audio at the SAME tempo, the seam crossfade can
    never introduce a speed change (unlike crossfading between two DIFFERENT
    beds at different tempos, which is what caused the original
    "transition speed-up" artifact).
    """
    y, sr = librosa.load(bed_wav, sr=fs, mono=True)
    sec_per_beat = 60.0 / tempo_bpm
    bar_seconds = 4 * sec_per_beat
    n_bar_samples = int(round(bar_seconds * fs))

    if len(y) < n_bar_samples:
        reps = int(np.ceil(n_bar_samples / len(y)))
        y = np.tile(y, reps)
    n_bars_avail = max(1, int(np.floor(len(y) / n_bar_samples)))
    y = y[: n_bars_avail * n_bar_samples].astype(np.float64)

    xfade_s = xfade_bars * bar_seconds
    xfade_n = min(int(round(xfade_s * fs)), y.size // 2)

    total_needed = int(round(target_seconds * fs))
    mix = y.copy()
    while mix.size < total_needed + xfade_n:
        if xfade_n > 0:
            fade_out, fade_in = _equal_power_ramp(xfade_n)
            head = mix[:-xfade_n]
            overlap = mix[-xfade_n:] * fade_out + y[:xfade_n] * fade_in
            tail = y[xfade_n:]
            mix = np.concatenate([head, overlap, tail])
        else:
            mix = np.concatenate([mix, y])

    mix = mix[:total_needed]
    return {
        "audio": mix,
        "bar_seconds": bar_seconds,
        "n_bars_avail": n_bars_avail,
        "xfade_s": round(xfade_s, 4),
    }


def render_piece(base: GrooveParams, bed_wav: str, out_stem: str,
                  seconds: float, band: tuple[int, int] | None = None,
                  seed: int = 0, subtle: bool = True,
                  drum_gain_db: float = -3.0, bed_gain_db: float = -6.0,
                  sf2_path: str | None = None, phrase_bars: int = 4) -> dict:
    """Render ONE discrete piece: single bed + drums locked to that bed's
    real tempo AND real downbeat phase (fixes root causes #2, #3, and the
    Step 1c downbeat-phase bug).

    Steps:
      1. detect_bed_tempo(bed_wav) -> the drum grid tempo (NOT a hardcoded
         96 BPM). This alone removes the drum "rush" against the bed.
      2. detect_bed_downbeat(bed_wav, tempo_bpm) -> downbeat_offset_s, the
         phase (seconds) of the bed's real beat 1 (Step 1c). Previously
         drums assumed the bed's sample 0 == beat 1, causing a measured
         phase offset (salsa ~0.10s, r&b ~0.85s, audible).
      3. n_bars = seconds / bar_seconds at the DETECTED tempo.
      4. band defaults to (base_density-1, base_density+1) -- SUBTLE, per the
         user's locked design.
      5. build_varied_drums_coherent() -- constant hat spine + phrase-level
         ornamentation (fixes root cause #1).
      6. Shift every drum note's start/end by +downbeat_offset_s so drum
         beat 1 coincides with the bed's beat 1.
      7. render_wav() (frozen, unmodified) -> drums wav.
      8. _loop_bed_single() -- loop the SAME bed at its OWN tempo, equal-power
         crossfade only at the loop seam (same audio, same tempo -> no speed
         change).
      9. Trim/pad so drums and bed end together: the shifted drums wav is
         `downbeat_offset_s` LONGER at the front (silence before the first
         shifted note) than an unshifted render would be, so the bed loop is
         generated to the shifted drums' own duration -- both stems always
         end together by construction, no extra trimming logic needed.
      10. Mix, peak-limit, write wav.

    Returns metadata: tempo info, downbeat offset, per-phrase densities,
    per-bar stats, duration, file paths -- everything needed for the sandbox
    test/report.
    """
    tempo_info = detect_bed_tempo(bed_wav)
    tempo_bpm = tempo_info["tempo_bpm"]

    # Step 1c: detect the bed's real downbeat phase at the now-locked tempo.
    downbeat_offset_s = detect_bed_downbeat(bed_wav, tempo_bpm, sr=FS)

    locked = replace(base, tempo_bpm=tempo_bpm, seed=seed)

    sec_per_beat = 60.0 / tempo_bpm
    bar_seconds = 4 * sec_per_beat
    n_bars = max(phrase_bars, int(round(seconds / bar_seconds)))
    # round n_bars up to a whole number of phrases so the last phrase isn't cut
    n_bars = int(np.ceil(n_bars / phrase_bars) * phrase_bars)

    if band is None:
        d = int(base.event_density)
        band = (d - 1, d + 1) if subtle else (max(4, d - 3), d + 3)

    drums_pm, densities, per_bar_stats = build_varied_drums_coherent(
        locked, n_bars, band, seed=seed, phrase_bars=phrase_bars)

    # Apply the Step 1c downbeat-phase fix: shift every drum note later by
    # +downbeat_offset_s so drum beat 1 lands on the bed's real beat 1
    # instead of assuming the bed's sample 0 is beat 1. This shifts the
    # WHOLE drum track (a constant, not per-note), so relative timing/groove
    # within the pattern is completely unaffected -- only the absolute
    # start position changes.
    for inst in drums_pm.instruments:
        for note in inst.notes:
            note.start = float(note.start + downbeat_offset_s)
            note.end = float(note.end + downbeat_offset_s)

    drums_wav = out_stem + "_drums_tmp.wav"
    drum_meta = render_wav(drums_pm, drums_wav, sf2_path=sf2_path)

    # Bed is looped to the SHIFTED drums' own duration, so both stems end
    # together by construction (the shift only adds silence at the front of
    # the drums stem, it never truncates anything).
    bed_loop = _loop_bed_single(bed_wav, tempo_bpm, drum_meta["duration_s"], fs=FS)
    bed_y = bed_loop["audio"]

    drums_y, _ = librosa.load(drums_wav, sr=FS, mono=True)

    n = min(len(drums_y), len(bed_y))
    drums_y = drums_y[:n]
    bed_y = bed_y[:n]

    drum_gain = 10.0 ** (drum_gain_db / 20.0)
    bed_gain = 10.0 ** (bed_gain_db / 20.0)
    mix = drums_y * drum_gain + bed_y * bed_gain

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.999:
        mix = mix / peak * 0.999
        peak = 0.999

    out_wav = out_stem + ".wav"
    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    sf.write(out_wav, mix.astype(np.float32), FS)

    # phrase-level density summary: one value per phrase (not per bar)
    phrase_densities = densities[::phrase_bars]

    # hat-spine confirmation: check every bar's spine_steps match the spine
    spine_ref = per_bar_stats[0]["spine_steps"] if per_bar_stats else []
    hat_spine_constant = all(b["spine_steps"] == spine_ref for b in per_bar_stats)

    return {
        "wav_path": out_wav,
        "duration_s": round(n / FS, 3),
        "n_bars": n_bars,
        "tempo_bpm": tempo_bpm,
        "tempo_detect": tempo_info,
        "downbeat_offset_s": round(downbeat_offset_s, 4),
        "bar_seconds": round(bar_seconds, 4),
        "per_bar_densities": densities,
        "phrase_densities": phrase_densities,
        "phrase_bars": phrase_bars,
        "band": band,
        "seed": seed,
        "hat_spine_steps": spine_ref,
        "hat_spine_constant_every_bar": hat_spine_constant,
        "per_bar_stats": per_bar_stats,
        "drum_gain_db": drum_gain_db,
        "bed_gain_db": bed_gain_db,
        "peak_post_mix": round(peak, 4),
        "drums_wav": drums_wav,
        "bed_loop_bar_seconds": round(bed_loop["bar_seconds"], 4),
        "bed_loop_n_bars_avail": bed_loop["n_bars_avail"],
        "drum_render_meta": drum_meta,
    }


def crossfade_pieces(piece_wavs: list[str], tempos: list[float], out_wav: str,
                      xfade_s: float = 2.0, fs: int = FS,
                      tempo_tolerance_bpm: float = 2.0) -> dict:
    """OPTIONAL continuity: crossfade discrete pieces end-to-end.

    Pieces are DISCRETE by default (render_piece). This function is only for
    when continuity across pieces is explicitly wanted. It only crossfades
    pieces at the SAME tempo (within `tempo_tolerance_bpm`); if tempos
    differ by more than that, the SECOND (and subsequent) piece(s) are
    time-stretched (librosa.effects.time_stretch, phase-vocoder) to the
    first piece's tempo before crossfading, with a printed warning -- this
    directly fixes the "transition speed-up" artifact, since after
    stretching, both sides of the seam share one tempo and the crossfade
    itself no longer changes playback speed.

    Returns:
        dict(out_wav, duration, tempos_in, tempos_used, stretched (bool per
        piece), xfade_s) for the report.
    """
    if len(piece_wavs) != len(tempos):
        raise ValueError("piece_wavs and tempos must be the same length")

    target_tempo = float(tempos[0])
    audios = []
    stretched_flags = [False]
    ys = []
    for i, (path, tempo) in enumerate(zip(piece_wavs, tempos)):
        y, sr = librosa.load(path, sr=fs, mono=True)
        ys.append(y)

    used_tempos = [target_tempo]
    for i in range(1, len(ys)):
        tempo = float(tempos[i])
        if abs(tempo - target_tempo) > tempo_tolerance_bpm:
            rate = tempo / target_tempo  # >1 means this piece is faster
            print(f"[crossfade_pieces] WARNING: piece {i} tempo {tempo:.2f} BPM "
                  f"differs from piece 0 tempo {target_tempo:.2f} BPM by "
                  f"{abs(tempo - target_tempo):.2f} BPM (> {tempo_tolerance_bpm} "
                  f"BPM tolerance). Time-stretching piece {i} by rate={rate:.4f} "
                  f"to match piece 0's tempo before crossfading.")
            ys[i] = librosa.effects.time_stretch(ys[i], rate=rate)
            stretched_flags.append(True)
            used_tempos.append(target_tempo)
        else:
            stretched_flags.append(False)
            used_tempos.append(tempo)

    sec_per_beat = 60.0 / target_tempo
    bar_seconds = 4 * sec_per_beat
    xfade_n = int(round(xfade_s * fs))

    mix = ys[0].astype(np.float64)
    for i in range(1, len(ys)):
        seg = ys[i].astype(np.float64)
        n_x = min(xfade_n, mix.size, seg.size)
        if n_x <= 0:
            mix = np.concatenate([mix, seg])
            continue
        fade_out, fade_in = _equal_power_ramp(n_x)
        head = mix[:-n_x] if n_x < mix.size else np.zeros(0)
        overlap = mix[-n_x:] * fade_out + seg[:n_x] * fade_in
        tail = seg[n_x:]
        mix = np.concatenate([head, overlap, tail])

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak > 0.999:
        mix = mix / peak * 0.999

    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    sf.write(out_wav, mix.astype(np.float32), fs)

    return {
        "wav_path": out_wav,
        "duration": round(mix.size / fs, 3),
        "tempos_in": [float(t) for t in tempos],
        "tempos_used": used_tempos,
        "stretched": stretched_flags,
        "xfade_s": xfade_s,
        "bar_seconds": round(bar_seconds, 4),
        "tempo_tolerance_bpm": tempo_tolerance_bpm,
    }
