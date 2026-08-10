"""arc_from_profile.py — Step 2 of the 12-song personalization pipeline.

Roadmap: `twelve_song_personalization_pipeline.md` §4 ("Arc definition").
Turns the 3 anchor centroids from `profile_from_songs.build_profile()` into
the 4-segment descending arc that used to be hard-coded as generic
112/98/84 BPM bands (Latin -> Pop -> R&B -> calm). Here the bands AND the
per-segment anchor blend come from the user's OWN taste profile:

    segment 1 (start, highest tempo)  <- anchor_danceable
    segment 2 (mid-high)              <- blend(danceable, enjoyed)
    segment 3 (mid-low)               <- blend(enjoyed, relaxing)
    segment 4 (calm, lowest tempo)    <- anchor_relaxing

Each segment also gets a `genre` field: the nearest of the controller's
`GENRE_ENERGY_ORDER` names (`groovegen.pd_controller.GENRE_ENERGY_ORDER`,
currently `["r&b", "pop", "latin"]`, ascending energy) by tempo distance to
that genre's `GENRE_STYLES` tempo (`groovegen.genre_styles`). This is a
DIFFERENT lookup from `prompt_from_anchor.py`'s "nearest of the 6 known
StyleSpec words" snap (spec §5) — this one only needs to pick which of the
controller's 3 *arc* genres a segment's committed tempo is closest to, so
`CascadeController(genre_order=...)` (see §7, "Live run — unchanged") still
gets a valid short genre name for its `genre_order` tier. `prompt_from_anchor`
separately snaps to the 6 StyleSpec words for MusicGen prompt language.

This module is CPU-only, offline, has no MusicGen / network dependency, and
does not touch `CascadeController`'s internals (spec §7: "No controller
changes").
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .pd_controller import GENRE_ENERGY_ORDER
from .genre_styles import GENRE_STYLES

__all__ = ["nearest_arc_genre", "blend_anchors", "arc_from_profile"]

# Representative tempo for each controller-tier genre (`GENRE_ENERGY_ORDER`
# short names), taken from the corresponding `GENRE_STYLES` full-name entry.
# ("r&b" -> "r&b/soul", "latin" -> "latin/salsa"; "pop" matches directly.)
_ARC_GENRE_TO_STYLE_KEY = {"r&b": "r&b/soul", "pop": "pop", "latin": "latin/salsa"}
_ARC_GENRE_TEMPO = {g: GENRE_STYLES[_ARC_GENRE_TO_STYLE_KEY[g]].tempo for g in GENRE_ENERGY_ORDER}


def nearest_arc_genre(tempo_bpm: float) -> str:
    """Nearest `GENRE_ENERGY_ORDER` name to `tempo_bpm`, by |tempo distance|.

    This is the controller-tier genre (one of `GENRE_ENERGY_ORDER`, e.g.
    `"r&b"`/`"pop"`/`"latin"`), used to seed `CascadeController(genre_order=...)`
    or `reset(initial_genre_idx=...)` with a personalized starting point —
    NOT the 6-word StyleSpec prompt snap (see `prompt_from_anchor.py`).
    """
    return min(_ARC_GENRE_TEMPO, key=lambda g: abs(_ARC_GENRE_TEMPO[g] - tempo_bpm))


def blend_anchors(anchor_a: dict, anchor_b: dict, weight_a: float) -> dict:
    """Linearly blend two centroid dicts: `weight_a * a + (1 - weight_a) * b`.

    Only numeric keys present in BOTH dicts are blended; other keys are
    dropped from the result (a blended anchor is used for tempo/prompt
    derivation only, not re-fed into `build_profile`).
    """
    weight_a = float(np.clip(weight_a, 0.0, 1.0))
    weight_b = 1.0 - weight_a
    keys = set(anchor_a) & set(anchor_b)
    blended = {}
    for k in keys:
        va, vb = anchor_a[k], anchor_b[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            if np.isfinite(va) and np.isfinite(vb):
                blended[k] = weight_a * va + weight_b * vb
    return blended


def arc_from_profile(profile: dict, *, mid_blend_weight: float = 0.5) -> list[dict[str, Any]]:
    """Build the 4-segment personalized arc from a `build_profile()` result.

    Parameters
    ----------
    profile : dict
        Output of `profile_from_songs.build_profile()` — must contain
        `profile['anchors']` with `'danceable'`, `'enjoyed'`, `'relaxing'`
        keys (each a feature-centroid dict containing at least
        `tempo_final`), and `profile['confidence']`.
    mid_blend_weight : float
        Blend weight for the two middle segments' PRIMARY anchor (e.g.
        segment 2 = `mid_blend_weight * danceable + (1 - mid_blend_weight) *
        enjoyed`). Default 0.5 = an even split. Exposed as a parameter
        rather than hard-coded so a caller can weight by confidence if
        desired (this function does not do that automatically, to keep the
        blend simple and auditable — see `anchor_weights` in the output for
        the actual weights used, which the caller/paper can inspect).

    Returns
    -------
    list[dict]
        4 segment dicts, ordered start -> calm, each:
        `{'segment': int, 'tempo_bpm': float, 'genre': str,
          'anchor_weights': {'danceable': float, 'enjoyed': float, 'relaxing': float},
          'blended_anchor': dict}`
        `anchor_weights` always sums to 1.0 across the 3 named anchors (a
        zero weight means that anchor does not contribute to this segment).
        `blended_anchor` is the actual feature dict (tempo + style features)
        to hand to `prompt_from_anchor.prompt_from_anchor()`.
    """
    anchors = profile["anchors"]
    for b in ("danceable", "enjoyed", "relaxing"):
        if b not in anchors:
            raise KeyError(f"profile['anchors'] missing bucket {b!r}")

    danceable, enjoyed, relaxing = anchors["danceable"], anchors["enjoyed"], anchors["relaxing"]

    # Segment 1: pure danceable anchor.
    seg1_anchor = dict(danceable)
    seg1_weights = {"danceable": 1.0, "enjoyed": 0.0, "relaxing": 0.0}

    # Segment 2: blend(danceable, enjoyed).
    w = float(np.clip(mid_blend_weight, 0.0, 1.0))
    seg2_anchor = blend_anchors(danceable, enjoyed, w)
    seg2_weights = {"danceable": w, "enjoyed": 1.0 - w, "relaxing": 0.0}

    # Segment 3: blend(enjoyed, relaxing).
    seg3_anchor = blend_anchors(enjoyed, relaxing, w)
    seg3_weights = {"danceable": 0.0, "enjoyed": w, "relaxing": 1.0 - w}

    # Segment 4: pure relaxing anchor.
    seg4_anchor = dict(relaxing)
    seg4_weights = {"danceable": 0.0, "enjoyed": 0.0, "relaxing": 1.0}

    segments = []
    for i, (anchor, weights) in enumerate(
        [(seg1_anchor, seg1_weights), (seg2_anchor, seg2_weights),
         (seg3_anchor, seg3_weights), (seg4_anchor, seg4_weights)],
        start=1,
    ):
        tempo_bpm = float(anchor["tempo_final"])
        segments.append({
            "segment": i,
            "tempo_bpm": tempo_bpm,
            "genre": nearest_arc_genre(tempo_bpm),
            "anchor_weights": weights,
            "blended_anchor": anchor,
        })

    # Personalized-arc invariant (mirrors the input sanity check in
    # `build_profile`, spec §3/§4): the arc must actually descend from
    # segment 1 to segment 4. We don't silently fix it — just flag it, same
    # spirit as the build_profile sanity report.
    tempos = [s["tempo_bpm"] for s in segments]
    if not all(tempos[i] >= tempos[i + 1] - 1e-6 for i in range(len(tempos) - 1)):
        for s in segments:
            s["arc_monotonic_warning"] = (
                f"Arc tempos {tempos} are not monotonically non-increasing; "
                "check the input profile's sanity flags (spec §3)."
            )

    return segments
