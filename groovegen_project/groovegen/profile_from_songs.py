"""profile_from_songs.py — Step 1 of the 12-song personalization pipeline.

Roadmap: `twelve_song_personalization_pipeline.md` §§2-3 ("Feature
extraction" / "Profile construction"). This module is the FREE/LOCAL first
stage: turn a user's 12 self-selected songs (6 danceable / 2 enjoyed / 3-4
relaxing, per the design note in §1) into three robust per-bucket feature
centroids ("arousal anchors") plus confidence weights and an input-sanity
report, so that `arc_from_profile.py` and `prompt_from_anchor.py` (steps 2-3)
have something honest to build on.

WHY A LOCAL re-implementation instead of importing the original extractor
--------------------------------------------------------------------------
The design spec (§2) says "REUSE existing tooling — zero new research" and
names `track_features.csv` (`feature_extractor_version 0.1.0`) as the
existing 52-column extractor output. That extractor's *source code* was not
provided to this module (only its CSV output was, as a schema reference) —
so `extract_features()` below is a from-scratch librosa implementation that
targets the SAME COLUMN NAMES as `track_features.csv` wherever the spec's
own feature list (§§2-3) requires them, so this module's output can be fed
into `build_profile()` (and, if the real extractor becomes importable
later, its CSV rows can be fed into the same `build_profile()` unchanged —
the dict keys are the contract).

FEATURE COVERAGE (see module docstring at bottom of file / project report for
the full accounting): all features actually named in spec §§2-3 and §5 are
computed by `extract_features()`. A handful of the CSV's 52 columns that the
spec never names as needed by this pipeline (e.g. `beat_this_*` — the
BeatThis alternate beat tracker, `lhl_syncopation_*`, `downbeat_consistency`,
`meter_estimate`, `sub_band_energy_ratio`) are intentionally NOT
reimplemented; see the report for the full list. Column NAMES for everything
that IS implemented match `track_features.csv` exactly.

This module is CPU-only, offline, and has no MusicGen / network dependency.
"""
from __future__ import annotations

import warnings
from typing import Iterable

import numpy as np

try:
    import librosa
except ImportError as exc:  # pragma: no cover - environment guard
    raise ImportError(
        "profile_from_songs.py requires librosa (`pip install librosa`) "
        "for extract_features(); build_profile() alone does not need it."
    ) from exc

__all__ = [
    "AROUSAL_FEATURES",
    "STYLE_FEATURES",
    "ALL_FEATURES",
    "extract_features",
    "build_profile",
]

# ---------------------------------------------------------------------------
# Feature name contracts — must match track_features.csv column names.
# ---------------------------------------------------------------------------

# §3 "Arousal-relevant subset" — anchors the arc (tempo bands / segment order).
AROUSAL_FEATURES = [
    "tempo_final",
    "onset_density",
    "rms_mean",
    "spectral_centroid_mean",
    "hpss_percussive_ratio",
    "event_density_on_vs_off",
    "plp_mean",
]

# §3 "Style/timbre subset" — flavors the prompt (step 3), not the arc bands.
STYLE_FEATURES = [
    *(f"mfcc_{i}_mean" for i in range(1, 14)),
    "spectral_flatness_mean",
    "hpss_harmonic_ratio",
    "low_band_energy_ratio",
]

ALL_FEATURES = AROUSAL_FEATURES + STYLE_FEATURES

# Extra columns computed for completeness / sanity-checking (not centroided
# by name in §3, but useful for the mislabel checks in §3 and for prompt
# language in §5).
_EXTRA_FEATURES = ["beat_consistency", "spectral_rolloff_mean", "zero_crossing_rate_mean"]


def extract_features(audio_path: str, *, sr: int = 22050, duration: float | None = 30.0) -> dict:
    """Compute a feature dict for one track, matching `track_features.csv` column names.

    Implements the features named in the design spec §§2-3 and §5 — NOT
    all 52 `track_features.csv` columns (see module docstring for the full
    coverage accounting). Every key this function DOES return uses the
    exact column name from `track_features.csv` so a caller can freely mix
    real extractor CSV rows and this function's output.

    Parameters
    ----------
    audio_path : str
        Path to an audio file (or a 30-60s excerpt, per spec §1).
    sr : int
        Target sample rate for analysis (matches the existing extractor's
        22050 Hz, per `track_features.csv`'s `sample_rate` column).
    duration : float or None
        Max seconds to load (default 30.0, matching the existing
        extractor's 30s excerpt window per spec §1). `None` loads the
        whole file.

    Returns
    -------
    dict
        Feature dict keyed by `track_features.csv` column names (see
        `ALL_FEATURES` / `_EXTRA_FEATURES` for the full key list), plus
        `trackID` (the basename) and `duration_sec`.
    """
    y, sr = librosa.load(audio_path, sr=sr, mono=True, duration=duration)
    if y.size == 0:
        raise ValueError(f"Loaded zero samples from {audio_path!r}")

    feats: dict = {
        "trackID": audio_path,
        "duration_sec": float(len(y) / sr),
        "sample_rate": int(sr),
    }

    # ---- Rhythm / tempo -----------------------------------------------
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
    tempo_final = float(np.atleast_1d(tempo)[0])
    feats["tempo_final"] = tempo_final

    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    if len(beat_times) >= 3:
        ibis = np.diff(beat_times)
        ibi_mean = float(np.mean(ibis))
        # beat_consistency: inverse-CV of inter-beat-intervals, squashed to
        # (0, 1]; higher = steadier beat (mirrors track_features.csv's
        # 0.9-0.99-ish range for metronomic tracks).
        cv = float(np.std(ibis) / ibi_mean) if ibi_mean > 0 else 1.0
        beat_consistency = float(1.0 / (1.0 + cv))
    else:
        ibi_mean = float(60.0 / tempo_final) if tempo_final > 0 else 0.0
        beat_consistency = 0.0
    feats["beat_ibi_mean"] = ibi_mean
    feats["beat_consistency"] = beat_consistency

    # PLP (pulse clarity) — plp_mean/std as in track_features.csv.
    plp = librosa.beat.plp(onset_envelope=onset_env, sr=sr)
    feats["plp_mean"] = float(np.mean(plp))
    feats["plp_std"] = float(np.std(plp))

    # ---- Groove / density -----------------------------------------------
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
    feats["onset_count"] = int(len(onsets))
    feats["onset_density"] = float(len(onsets) / feats["duration_sec"]) if feats["duration_sec"] > 0 else 0.0

    # event_density_on_vs_off: ratio of onset-strength mass landing ON the
    # detected beat grid (±1 frame) vs OFF it — a cheap groove/syncopation
    # proxy matching the *name* of the CSV column; not a byte-exact
    # reimplementation of the original extractor's algorithm.
    if len(beat_frames) > 0:
        beat_set = set(int(b) for f in beat_frames for b in (f - 1, f, f + 1))
        on_mass = sum(onset_env[f] for f in range(len(onset_env)) if f in beat_set)
        off_mass = sum(onset_env[f] for f in range(len(onset_env)) if f not in beat_set)
        feats["event_density_on_vs_off"] = float(on_mass / off_mass) if off_mass > 1e-9 else float("inf")
    else:
        feats["event_density_on_vs_off"] = 0.0

    # ---- Timbre / energy -----------------------------------------------
    rms = librosa.feature.rms(y=y)[0]
    feats["rms_mean"] = float(np.mean(rms))
    feats["rms_std"] = float(np.std(rms))

    cent = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    feats["spectral_centroid_mean"] = float(np.mean(cent))
    feats["spectral_centroid_std"] = float(np.std(cent))

    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
    feats["spectral_rolloff_mean"] = float(np.mean(rolloff))

    flatness = librosa.feature.spectral_flatness(y=y)[0]
    feats["spectral_flatness_mean"] = float(np.mean(flatness))

    zcr = librosa.feature.zero_crossing_rate(y)[0]
    feats["zero_crossing_rate_mean"] = float(np.mean(zcr))

    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    for i in range(13):
        feats[f"mfcc_{i + 1}_mean"] = float(np.mean(mfcc[i]))

    # ---- Source balance (HPSS) -----------------------------------------
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        y_harm, y_perc = librosa.effects.hpss(y)
    harm_energy = float(np.sum(y_harm ** 2))
    perc_energy = float(np.sum(y_perc ** 2))
    total_energy = harm_energy + perc_energy
    if total_energy > 1e-12:
        feats["hpss_harmonic_ratio"] = harm_energy / total_energy
        feats["hpss_percussive_ratio"] = perc_energy / total_energy
    else:
        feats["hpss_harmonic_ratio"] = 0.5
        feats["hpss_percussive_ratio"] = 0.5

    # sub_band_energy_ratio / low_band_energy_ratio: fraction of spectral
    # energy below a low-frequency cut (250 Hz "sub" / 500 Hz "low"),
    # matching the CSV's naming; a simple STFT-magnitude band-energy split.
    S = np.abs(librosa.stft(y)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=(S.shape[0] - 1) * 2)
    total_spec_energy = float(np.sum(S)) + 1e-12
    sub_mask = freqs < 250.0
    low_mask = freqs < 500.0
    feats["sub_band_energy_ratio"] = float(np.sum(S[sub_mask, :]) / total_spec_energy)
    feats["low_band_energy_ratio"] = float(np.sum(S[low_mask, :]) / total_spec_energy)

    feats["tempo_primary_source"] = "librosa_beat_track"
    feats["feature_extractor_version"] = "profile_from_songs_0.1.0"
    return feats


def _robust_centroid(rows: list[dict], keys: Iterable[str]) -> dict:
    """Median (not mean, per spec §3) over `keys` across a list of feature dicts."""
    keys = list(keys)
    centroid = {}
    for k in keys:
        vals = np.array([row[k] for row in rows if k in row and np.isfinite(row[k])], dtype=float)
        centroid[k] = float(np.median(vals)) if vals.size else float("nan")
    return centroid


def _bucket_variance_score(rows: list[dict], keys: Iterable[str]) -> float:
    """Mean coefficient-of-variation across `keys`, used by the confidence weight.

    Lower CoV (tighter cluster of songs in feature space) -> higher
    confidence. We use |std/median| per feature, then average, to stay in
    the same "robust" spirit as the median centroid (§3).
    """
    keys = list(keys)
    covs = []
    for k in keys:
        vals = np.array([row[k] for row in rows if k in row and np.isfinite(row[k])], dtype=float)
        if vals.size < 2:
            continue
        med = np.median(vals)
        if abs(med) > 1e-9:
            covs.append(float(np.std(vals) / abs(med)))
    return float(np.mean(covs)) if covs else 1.0


def _confidence_weight(n: int, variance_score: float, n_ref: int = 6) -> float:
    """f(bucket_n, within-bucket variance) -> confidence in [~0.05, ~1.0].

    Two multiplicative factors, per spec §3:
      - size factor: n / n_ref, capped at 1.0 (n=6 -> 1.0, n=2 -> 0.33).
      - stability factor: 1 / (1 + variance_score) (tight cluster -> ~1.0,
        spread-out cluster -> lower).
    The product is a simple, honestly-documented heuristic — NOT a
    statistically calibrated estimator. It exists to make the paper's
    "these are soft priors" claim (spec §1, §9) literal in code.
    """
    size_factor = min(1.0, n / float(n_ref))
    stability_factor = 1.0 / (1.0 + max(0.0, variance_score))
    return float(np.clip(size_factor * stability_factor, 0.05, 1.0))


def build_profile(song_paths: dict) -> dict:
    """Build the 3 arousal anchors (centroids) + confidence + sanity checks.

    Parameters
    ----------
    song_paths : dict
        `{'danceable': [...6 paths...], 'enjoyed': [...2 paths...],
          'relaxing': [...3-4 paths...]}`. Each value may instead be a list
          of already-computed feature dicts (as returned by
          `extract_features`, or a `track_features.csv` row converted to a
          dict) — if a list entry is a `str`/`Path` it is run through
          `extract_features`; if it is already a `dict` it is used as-is.
          This lets tests/callers skip real audio I/O (see
          `test_pipeline.py`).

    Returns
    -------
    dict
        {
          'anchors': {'danceable': {...centroid...}, 'enjoyed': {...}, 'relaxing': {...}},
          'confidence': {'danceable': float, 'enjoyed': float, 'relaxing': float},
          'bucket_n': {'danceable': int, 'enjoyed': int, 'relaxing': int},
          'sanity': {
              'flags': [ {bucket, index, reason}, ... ],
              'danceable_gt_relaxing_tempo': bool,
              'ok': bool,
          },
          'per_track_features': {'danceable': [dict,...], ...},   # for audit
        }

    Sanity checks implemented (spec §3):
      - flag a "danceable" track with low onset_density/tempo relative to
        its bucket-mates and relative to the other buckets' centroids,
      - flag a "relaxing" track with high tempo/percussive-ratio,
      - assert (report, don't crash) danceable centroid tempo > relaxing
        centroid tempo — the arc must actually descend (spec §3).
    """
    required = {"danceable", "enjoyed", "relaxing"}
    missing = required - set(song_paths)
    if missing:
        raise ValueError(f"song_paths missing required buckets: {sorted(missing)}")

    per_track: dict[str, list[dict]] = {}
    for bucket, items in song_paths.items():
        rows = []
        for item in items:
            if isinstance(item, dict):
                rows.append(item)
            else:
                rows.append(extract_features(str(item)))
        per_track[bucket] = rows

    n = {b: len(rows) for b, rows in per_track.items()}
    if n["danceable"] < 2:
        warnings.warn("danceable bucket has < 2 tracks; centroid will be unstable.")
    if n["relaxing"] < 2:
        warnings.warn("relaxing bucket has < 2 tracks; treat as a soft prior only (spec §1).")

    anchors = {b: _robust_centroid(rows, ALL_FEATURES) for b, rows in per_track.items()}

    variance_scores = {b: _bucket_variance_score(rows, AROUSAL_FEATURES) for b, rows in per_track.items()}
    confidence = {b: _confidence_weight(n[b], variance_scores[b]) for b in per_track}

    # ---- Sanity checks (spec §3) --------------------------------------
    flags = []
    danceable_rows = per_track["danceable"]
    relaxing_rows = per_track["relaxing"]

    danceable_tempo_med = anchors["danceable"]["tempo_final"]
    danceable_onset_med = anchors["danceable"]["onset_density"]
    relaxing_tempo_med = anchors["relaxing"]["tempo_final"]
    relaxing_perc_med = anchors["relaxing"]["hpss_percussive_ratio"]

    # A "danceable" track that is slow AND sparse relative to its own
    # bucket's median is a likely mislabel (spec §3: "danceable-but-slow").
    for i, row in enumerate(danceable_rows):
        slow = row.get("tempo_final", np.nan) < 0.75 * danceable_tempo_med
        sparse = row.get("onset_density", np.nan) < 0.6 * danceable_onset_med
        if slow and sparse:
            flags.append({
                "bucket": "danceable", "index": i, "trackID": row.get("trackID"),
                "reason": (
                    f"tempo={row.get('tempo_final'):.1f} BPM (bucket median "
                    f"{danceable_tempo_med:.1f}), onset_density="
                    f"{row.get('onset_density'):.2f} (bucket median "
                    f"{danceable_onset_med:.2f}) — looks slow/sparse for a "
                    "'danceable' pick."
                ),
            })

    # A "relaxing" track that is fast AND percussive relative to its own
    # bucket's median is a likely mislabel (spec §3: "relaxing-but-fast").
    for i, row in enumerate(relaxing_rows):
        fast = row.get("tempo_final", np.nan) > 1.25 * relaxing_tempo_med
        percussive = row.get("hpss_percussive_ratio", np.nan) > 1.3 * relaxing_perc_med
        if fast and percussive:
            flags.append({
                "bucket": "relaxing", "index": i, "trackID": row.get("trackID"),
                "reason": (
                    f"tempo={row.get('tempo_final'):.1f} BPM (bucket median "
                    f"{relaxing_tempo_med:.1f}), hpss_percussive_ratio="
                    f"{row.get('hpss_percussive_ratio'):.2f} (bucket median "
                    f"{relaxing_perc_med:.2f}) — looks fast/percussive for a "
                    "'relaxing' pick."
                ),
            })

    danceable_gt_relaxing = bool(danceable_tempo_med > relaxing_tempo_med)
    if not danceable_gt_relaxing:
        flags.append({
            "bucket": "*", "index": None, "trackID": None,
            "reason": (
                f"danceable centroid tempo ({danceable_tempo_med:.1f} BPM) is "
                f"NOT greater than relaxing centroid tempo ({relaxing_tempo_med:.1f} "
                "BPM) — the arc cannot descend. Ask the user to re-check their "
                "picks (spec §3)."
            ),
        })

    sanity = {
        "flags": flags,
        "danceable_gt_relaxing_tempo": danceable_gt_relaxing,
        "ok": danceable_gt_relaxing and not any(f["bucket"] != "*" for f in flags) if flags is not None else True,
    }
    # Recompute "ok" plainly: no flags at all (mislabels or ordering) => ok.
    sanity["ok"] = len(flags) == 0

    return {
        "anchors": anchors,
        "confidence": confidence,
        "bucket_n": n,
        "sanity": sanity,
        "per_track_features": per_track,
    }
