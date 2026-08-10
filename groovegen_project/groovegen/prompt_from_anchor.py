"""prompt_from_anchor.py — Step 3 of the 12-song personalization pipeline.

Roadmap: `twelve_song_personalization_pipeline.md` §5 ("Prompt
construction"). Turns a (possibly blended) anchor feature dict — as
produced per-segment by `arc_from_profile.arc_from_profile()` — into a
MusicGen text prompt, via the feature -> language template specified in
§5's table:

    tempo_final              -> "at about {N} BPM"
    hpss_percussive_ratio    -> "driving/steady drums" (high) / "sparse
                                 percussion" (low)
    onset_density /
    event_density_on_vs_off  -> "busy" vs "minimal" rhythmic activity
    spectral_centroid_mean   -> "bright" (high) / "warm/dark" (low)
    hpss_harmonic_ratio      -> "rich chords/melody" (high) / "rhythm-forward" (low)
    mfcc cluster             -> nearest genre exemplar, snapped to one of
                                 the 6 known `GENRE_STYLES` words so prompts
                                 stay in MusicGen's competent vocabulary
                                 (spec §5, §9)

This module is CPU-only, offline, has no MusicGen / network dependency —
it only produces the TEXT prompt string that a later (Colab-GPU) step would
hand to MusicGen.
"""
from __future__ import annotations

import numpy as np

from .genre_styles import GENRE_STYLES

__all__ = ["nearest_known_genre", "prompt_from_anchor"]

# The 6 known StyleSpec genre words prompts must snap to (spec §5, §9):
# hip-hop/rap, r&b/soul, pop, latin/salsa, classic-rock, metal.
_KNOWN_GENRES = list(GENRE_STYLES.keys())

# Short, MusicGen-friendly descriptor per known genre (used in the prompt
# text itself, distinct from the internal dict key).
_GENRE_PROMPT_WORD = {
    "hip-hop/rap": "hip-hop/rap",
    "r&b/soul": "r&b/soul",
    "pop": "pop",
    "latin/salsa": "latin/salsa",
    "classic-rock": "classic rock",
    "metal": "metal",
}

# A crude reference MFCC-1..13 centroid per known genre would normally be
# fit from a labeled corpus; we don't have one here, so we fall back to
# each StyleSpec's nominal tempo + its `desc` keyword vibe as the nearest-
# genre proxy signal (tempo distance, tie-broken by percussive/harmonic
# tendencies baked into `_GENRE_TIMBRE_PRIOR`). This keeps the snap fully
# local/free (no training data) while still being anchored to real
# `GENRE_STYLES` values, per spec §5's "reuses GENRE_ENERGY_ORDER / the
# existing genre model" instruction.
_GENRE_TIMBRE_PRIOR = {
    # genre: (percussive_ratio_prior, harmonic_ratio_prior, centroid_prior 0..1 low->bright)
    # Priors are qualitative orderings consistent with each StyleSpec's
    # `desc` (genre_styles.py): hip-hop = sub-heavy/dark, r&b/soul = the
    # lushest/most harmonic + darkest, pop = bright synth/clavinet pluck
    # with a firmly percussive backbone (highest percussive prior of the
    # non-rock genres -- it must not be confused with metal/rock's
    # DISTORTED, not just percussive, timbre), latin/salsa = percussive
    # but warm (piano montuno, not bright synths), classic-rock/metal =
    # brightest + most percussive (distorted guitars read as both bright
    # AND percussive to a spectral/HPSS analysis) -- separated from pop
    # mainly by an even higher percussive prior and lower harmonic prior.
    "hip-hop/rap": (0.55, 0.45, 0.30),
    "r&b/soul": (0.35, 0.65, 0.35),
    "pop": (0.58, 0.42, 0.65),
    "latin/salsa": (0.60, 0.40, 0.55),
    "classic-rock": (0.68, 0.32, 0.75),
    "metal": (0.75, 0.25, 0.80),
}


def nearest_known_genre(anchor: dict, tempo_bpm: float | None = None) -> str:
    """Snap an anchor's features to the nearest of the 6 known StyleSpec words.

    Distance = weighted sum of normalized tempo distance (to each genre's
    `GENRE_STYLES[...].tempo`) and timbre-prior distance (percussive ratio,
    harmonic ratio, and a coarse brightness proxy from
    `spectral_centroid_mean`, all compared against `_GENRE_TIMBRE_PRIOR`).
    This is a simple nearest-centroid heuristic, not a trained classifier —
    consistent with spec §9's honesty note that personalization stays
    *within* MusicGen's existing 6-word vocabulary rather than inventing
    new genres.

    Parameters
    ----------
    anchor : dict
        Feature dict with at least `hpss_percussive_ratio`,
        `hpss_harmonic_ratio`, `spectral_centroid_mean`. `tempo_final` is
        used if `tempo_bpm` is not given separately.
    tempo_bpm : float, optional
        Override tempo (e.g. the segment's already-decided committed
        tempo) instead of `anchor['tempo_final']`.
    """
    tempo = float(tempo_bpm if tempo_bpm is not None else anchor.get("tempo_final", 100.0))
    perc = float(anchor.get("hpss_percussive_ratio", 0.5))
    harm = float(anchor.get("hpss_harmonic_ratio", 0.5))
    # Coarse brightness proxy: squash spectral_centroid_mean (Hz) to ~0..1
    # via a fixed reference range (500-4000 Hz covers the observed range in
    # track_features.csv-style extractions).
    centroid_hz = float(anchor.get("spectral_centroid_mean", 2000.0))
    brightness = float(np.clip((centroid_hz - 500.0) / (4000.0 - 500.0), 0.0, 1.0))

    # Weighting: tempo alone is a weak genre discriminator in the 90-130 BPM
    # band (pop/metal/hip-hop/classic-rock all cluster there), so the
    # timbre signal (percussive/harmonic balance + brightness -- the actual
    # features spec section 5's table maps to genre-ish descriptors) is
    # weighted more heavily than raw tempo distance; tempo still breaks
    # near-ties (e.g. pop vs. hip-hop at a similar timbre balance).
    _TEMPO_WEIGHT = 0.4
    _TIMBRE_WEIGHT = 1.0

    best_genre, best_dist = None, float("inf")
    for genre in _KNOWN_GENRES:
        genre_tempo = GENRE_STYLES[genre].tempo
        perc_prior, harm_prior, bright_prior = _GENRE_TIMBRE_PRIOR[genre]
        tempo_dist = abs(tempo - genre_tempo) / 60.0  # normalize by ~1 octave of tempo range
        timbre_dist = (
            abs(perc - perc_prior) + abs(harm - harm_prior) + abs(brightness - bright_prior)
        )
        dist = _TEMPO_WEIGHT * tempo_dist + _TIMBRE_WEIGHT * timbre_dist
        if dist < best_dist:
            best_dist, best_genre = dist, genre
    return best_genre


def _busy_or_minimal(anchor: dict) -> str:
    """onset_density / event_density_on_vs_off -> 'busy' vs 'minimal'."""
    onset_density = anchor.get("onset_density")
    event_ratio = anchor.get("event_density_on_vs_off")
    score = 0
    votes = 0
    if onset_density is not None and np.isfinite(onset_density):
        votes += 1
        score += 1 if onset_density >= 4.0 else 0  # ~4 onsets/sec is a reasonable busy/sparse split
    if event_ratio is not None and np.isfinite(event_ratio):
        votes += 1
        score += 1 if event_ratio >= 1.0 else 0  # on-beat-dominant vs syncopated/off-heavy
    if votes == 0:
        return "moderately busy"
    return "busy" if score >= (votes / 2.0) else "minimal"


def _drum_descriptor(anchor: dict) -> str:
    """hpss_percussive_ratio -> drum descriptor."""
    perc = anchor.get("hpss_percussive_ratio")
    if perc is None or not np.isfinite(perc):
        return "steady drums"
    if perc >= 0.55:
        return "driving, steady drums"
    if perc <= 0.35:
        return "sparse percussion"
    return "steady drums"


def _brightness_descriptor(anchor: dict) -> str:
    """spectral_centroid_mean -> 'bright' vs 'warm/dark'."""
    centroid_hz = anchor.get("spectral_centroid_mean")
    if centroid_hz is None or not np.isfinite(centroid_hz):
        return "balanced tone"
    if centroid_hz >= 2200.0:
        return "bright"
    if centroid_hz <= 1400.0:
        return "warm, dark"
    return "balanced-tone"


def _harmonic_descriptor(anchor: dict) -> str:
    """hpss_harmonic_ratio -> 'rich chords/melody' vs 'rhythm-forward'."""
    harm = anchor.get("hpss_harmonic_ratio")
    if harm is None or not np.isfinite(harm):
        return "balanced chords and rhythm"
    if harm >= 0.55:
        return "rich chords and melody"
    if harm <= 0.35:
        return "rhythm-forward, groove-led"
    return "balanced chords and rhythm"


def prompt_from_anchor(anchor: dict, tempo_bpm: float) -> str:
    """Render a MusicGen text prompt from an anchor feature dict + tempo.

    Parameters
    ----------
    anchor : dict
        A (possibly blended) feature dict, e.g. one segment's
        `blended_anchor` from `arc_from_profile.arc_from_profile()`. Must
        contain (or gracefully fall back on missing) `hpss_percussive_ratio`,
        `onset_density`, `event_density_on_vs_off`, `spectral_centroid_mean`,
        `hpss_harmonic_ratio`.
    tempo_bpm : float
        The segment's committed tempo in BPM (spec §4: "the controller's
        committed tempo at each segment" — this is deliberately a separate
        argument rather than always reading `anchor['tempo_final']`, since
        the committed/actuated tempo used by `CascadeController` may differ
        slightly from the raw blended anchor's tempo after PD clipping).

    Returns
    -------
    str
        A single MusicGen prompt, e.g. *"a warm, dark r&b/soul groove at
        about 82 BPM, sparse percussion, minimal rhythmic activity,
        rhythm-forward, groove-led"*.
    """
    genre = nearest_known_genre(anchor, tempo_bpm=tempo_bpm)
    genre_word = _GENRE_PROMPT_WORD[genre]

    brightness = _brightness_descriptor(anchor)
    drums = _drum_descriptor(anchor)
    density = _busy_or_minimal(anchor)
    harmonic = _harmonic_descriptor(anchor)

    prompt = (
        f"a {brightness} {genre_word} groove at about {round(tempo_bpm)} BPM, "
        f"{drums}, {density} rhythmic activity, {harmonic}"
    )
    return prompt
