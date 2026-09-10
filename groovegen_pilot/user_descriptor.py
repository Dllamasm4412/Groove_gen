"""GrooveGen M1 — User Descriptor.

Turns 12 per-song MIRFeatures into the 6-float personalization payload the
CascadeController consumes.

Design commitments (locked with user, 2026-08-17):
    - Only two things are estimated from 12 songs: a scalar target arousal
      and a 5-way genre affinity vector. These are the only quantities
      12-song intake can support without overreach.
    - Target arousal is computed using ArousalPlantConfig.contribution(),
      which uses Sophia's commercial-audio-anchored midpoints. This is the
      "option A" bridge: user features live in Sophia's feature space; the
      ladder lives in the composer's measured space; the 1-9 arousal scalar
      is the interlingua.
    - Composer internals stay untouched. Personalization only reaches the
      controller.

Wiring:
    - target_arousal  --> default reference when no subjective poll yet.
    - genre_weights   --> tiebreaker among MPC candidates within one
                          dead-zone-width of the best predicted arousal.

Feature is dormant in the fielded N=400 preregistered study. See
DEVIATIONS.md v2.3 for the rationale.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable, Optional

import numpy as np

from music_arousal_plant import ArousalPlantConfig
from music_features import MIRFeatures, _GENRE_BASE

FAMILIES: tuple[str, ...] = ('calm', 'lofi', 'rnb', 'pop', 'latin')

# Normalization scales for genre-classification distance. Each feature is
# divided by its scale so cross-feature distances are comparable. The scales
# match the per-feature ranges seen across _GENRE_BASE.
_NORM_SCALES: dict[str, float] = {
    'tempo_bpm': 60.0,        # calm 65 -> pop 118
    'percussive_ratio': 0.25, # calm 0.05 -> pop 0.23
    'low_band_energy': 0.15,  # calm 0.58 -> lofi 0.66
    'beat_consistency': 0.05, # near-flat across families
    'onset_density': 3.0,     # calm 1.15 -> pop 3.30
    'syncopation': 0.5,       # calm 0.21 -> latin 0.65
    'spectral_flatness': 0.02,
}


@dataclass(frozen=True)
class UserDescriptor:
    """Personalization payload consumed by the CascadeController.

    Attributes
    ----------
    target_arousal
        Median predicted arousal across the user's 12 songs, in Russell 1..9.
        Used as the controller's default reference target when no arousal
        poll has arrived yet.
    genre_weights
        Nonnegative weights over the 5 families, summing to 1. Used as an
        MPC tiebreaker: when the top candidates are within one dead-zone-
        width of the best predicted arousal, prefer the one whose family
        has the higher weight.
    provenance
        Small provenance blob: n_songs, timestamp, feature medians, class
        counts. Purely informational; not consumed by the controller.
    """
    target_arousal: float
    genre_weights: dict[str, float]
    provenance: dict = field(default_factory=dict)

    # --- convenience --------------------------------------------------------

    def weight_for(self, genre: str) -> float:
        return float(self.genre_weights.get(genre, 0.0))

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json())

    @classmethod
    def load(cls, path: str | Path) -> 'UserDescriptor':
        d = json.loads(Path(path).read_text())
        return cls(**d)


# =============================================================================
# Genre classification
# =============================================================================

def _norm_vec(mir: MIRFeatures) -> np.ndarray:
    d = mir.as_dict()
    return np.array([d[k] / _NORM_SCALES[k] for k in _NORM_SCALES], dtype=float)


def _family_centroid_norm(family: str) -> np.ndarray:
    base = _GENRE_BASE[family]
    return np.array([base[k] / _NORM_SCALES[k] for k in _NORM_SCALES], dtype=float)


def classify_song(mir: MIRFeatures) -> str:
    """Nearest family in normalized MIR space."""
    v = _norm_vec(mir)
    best_family = FAMILIES[0]
    best_d = float('inf')
    for fam in FAMILIES:
        c = _family_centroid_norm(fam)
        d = float(np.linalg.norm(v - c))
        if d < best_d:
            best_d = d
            best_family = fam
    return best_family


# =============================================================================
# Descriptor construction
# =============================================================================

def _median_target_arousal(features: Iterable[MIRFeatures]) -> float:
    cfg = ArousalPlantConfig()
    vals = [cfg.contribution(f) for f in features]
    med = float(np.median(vals))
    return float(min(cfg.arousal_max, max(cfg.arousal_min, med)))


def _genre_histogram(features: Iterable[MIRFeatures]) -> tuple[dict[str, float], dict[str, int], list[str]]:
    counts = {fam: 0 for fam in FAMILIES}
    assignments: list[str] = []
    for mir in features:
        fam = classify_song(mir)
        counts[fam] += 1
        assignments.append(fam)
    total = sum(counts.values()) or 1
    weights = {fam: counts[fam] / total for fam in FAMILIES}
    return weights, counts, assignments


def _feature_medians(features: list[MIRFeatures]) -> dict[str, float]:
    if not features:
        return {}
    keys = list(features[0].as_dict().keys())
    out = {}
    for k in keys:
        vals = [f.as_dict()[k] for f in features]
        out[k] = float(np.median(vals))
    return out


def build_descriptor(features: list[MIRFeatures],
                     labels: Optional[list[str]] = None,
                     *,
                     expected: int = 12,
                     min_songs: int = 8) -> UserDescriptor:
    """Build the 6-float personalization payload from N per-song features.

    Parameters
    ----------
    features
        Per-song MIRFeatures. Must contain between `min_songs` and `expected`
        rows inclusive. Fewer than `expected` is tolerated to accommodate
        exploratory intake where a URL fails to download; the descriptor is
        still built but `provenance['n_songs_short_of_expected']` is set so
        the caller can flag it.
    expected
        Nominal song count (12) for A+B intake. Determines when the
        `short_of_expected` provenance flag is raised.
    min_songs
        Minimum song count. Below this the histogram is too noisy to be
        meaningful and we refuse to build. Defaults to 8.
    """
    n = len(features)
    if n > expected:
        raise ValueError(
            f'build_descriptor expects at most {expected} songs, got {n}.'
        )
    if n < min_songs:
        raise ValueError(
            f'build_descriptor requires at least {min_songs} songs '
            f'(nominal={expected}), got {n}. Retry with more successful tracks.'
        )
    tgt = _median_target_arousal(features)
    weights, counts, assignments = _genre_histogram(features)
    prov = {
        'n_songs': n,
        'n_songs_nominal': expected,
        'n_songs_short_of_expected': max(0, expected - n),
        'built_at_epoch_s': time.time(),
        'feature_medians': _feature_medians(features),
        'family_counts': counts,
    }
    # Per-song rows for downstream personalization (composer tempo bias).
    # Only included if caller provides labels (family prefix determines
    # which family's tempo_default to bias). Also carries the family the
    # MIR classifier assigned this song to, so you can see when seed labels
    # (e.g. 'rnb_1') diverge from what the features say ('pop').
    if labels is not None:
        if len(labels) != n:
            raise ValueError(
                f'labels length {len(labels)} != features length {n}'
            )
        prov['per_song'] = [
            {'label': lbl, 'assigned_family': assn, **f.as_dict()}
            for lbl, assn, f in zip(labels, assignments, features)
        ]
    return UserDescriptor(
        target_arousal=tgt,
        genre_weights=weights,
        provenance=prov,
    )


if __name__ == '__main__':
    # tiny self-demo using ladder cells as fake "user songs"
    from ladder import build_ladder
    L = build_ladder()
    fake_features = []
    # pretend the user listens to 3 pop + 3 latin + 3 rnb + 2 lofi + 1 calm
    genre_menu = ['pop']*3 + ['latin']*3 + ['rnb']*3 + ['lofi']*2 + ['calm']*1
    from music_features import feature_vector_for
    for g in genre_menu:
        # pick tier-3 cell of that genre
        cell = next(c for c in L.cells if c.genre == g and c.tier == 3)
        fake_features.append(feature_vector_for(cell))
    desc = build_descriptor(fake_features)
    print(desc.to_json())
