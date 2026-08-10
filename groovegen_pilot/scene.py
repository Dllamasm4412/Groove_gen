"""scene.py — once-per-session SCENE selector (Phase 3 wired early, per council).

Turns a user's anchor-song feature row into the session's INITIAL CONDITIONS:
genre, starting tempo, starting tier, transpose. This is a scene selector, NOT a
per-bar control lever — genre-morph mid-session is a locked-out confound. The
validated tier/tempo controller does all moment-to-moment work from here.

Reuses the validated adapter symbolic_from_profile.map_profile(). We normalize
its genre label to the renderer's genre vocab and expose a clean Scene dataclass
that SessionConfig can be built from.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass

_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import symbolic_from_profile as sfp
from renderer import _norm_genre


@dataclass
class Scene:
    genre: str          # normalized to renderer vocab: pop|r&b|latin|calm
    bpm: float
    start_tier: int     # 1..5
    transpose: int      # semitones (reporting; applied to bed if desired)
    chord_richness: str
    source: dict        # raw features that produced this scene (provenance)


def scene_from_features(feat: dict) -> Scene:
    """Map one track_features.csv row (dict) -> Scene initial conditions."""
    p = sfp.map_profile(feat)
    return Scene(
        genre=_norm_genre(p["genre"]),
        bpm=float(p["bpm"]),
        start_tier=int(p["start_tier"]),
        transpose=int(p.get("transpose", 0)),
        chord_richness=str(p.get("chord_richness", "triad")),
        source=dict(p.get("_src", {})),
    )


if __name__ == "__main__":
    # exercise with 3 synthetic feature rows spanning genres
    rows = [
        dict(tempo_final=128, spectral_centroid_mean=2600, hpss_harmonic_ratio=0.5,
             hpss_percussive_ratio=0.5, onset_density=7, lhl_syncopation_mean=0.9),  # latin-ish
        dict(tempo_final=104, spectral_centroid_mean=2000, hpss_harmonic_ratio=0.6,
             hpss_percussive_ratio=0.4, onset_density=5, lhl_syncopation_mean=0.5),  # pop
        dict(tempo_final=74, spectral_centroid_mean=1400, hpss_harmonic_ratio=0.85,
             hpss_percussive_ratio=0.15, onset_density=2, lhl_syncopation_mean=0.2),  # calm
    ]
    for r in rows:
        s = scene_from_features(r)
        print(f"{s.genre:6s} bpm={s.bpm:5.1f} tier={s.start_tier} "
              f"transpose={s.transpose:+d} rich={s.chord_richness}  src={s.source}")
