"""genre_router.py — free-text / checkbox genre routing to GENRE_PRESETS keys.

Step 2 of GrooveGen: the genre UI lets a user pick known-preset checkboxes
AND type arbitrary free text ("lo-fi, afrobeat, jazz"). This module resolves
any of that text down to one of the keys `genre_presets.list_genres()`
actually understands, so `get_preset()` never sees an unknown genre string.

Resolution order for a single free-text token:
  1. Exact match against a known preset key (e.g. user typed "pop").
  2. Keyword/alias substring match against a small hand-curated alias map
     (e.g. "trap"/"boom bap" -> hip-hop/rap, "lofi"/"chill" -> calm).
  3. Fuzzy nearest match (difflib.get_close_matches) against known keys +
     all aliases, mapped back to its owning preset key.
  4. Fallback: "pop", flagged approx=True so callers can be honest about it.

Every non-exact-key resolution is flagged `approx=True` so the UI can tell
the user "note: 'jazz' was approximately mapped to r&b/soul" instead of
silently pretending it's a perfect match.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

from .genre_presets import list_genres, GENRE_PRESETS

# All genres selectable via checkbox (calm variants excluded from the
# checkbox list in the UI, but still valid preset keys other code can route
# to via free text, e.g. "lofi"/"chill" -> calm).
KNOWN_PRESET_KEYS = list(GENRE_PRESETS.keys())  # 6 core genres
ALL_PRESET_KEYS = list_genres()  # + calm, calm-classical

# ---------------------------------------------------------------------------
# Alias keyword map: preset key -> list of keyword/substrings that should
# route to it. Longer/more-specific aliases first within each list doesn't
# matter for substring matching, but we keep them readable/grouped.
# ---------------------------------------------------------------------------
ALIASES: dict[str, list[str]] = {
    "hip-hop/rap": [
        "hip-hop", "hip hop", "hiphop", "rap", "trap", "boom bap", "boombap",
        "drill", "grime",
    ],
    "r&b/soul": [
        "r&b", "rnb", "r n b", "soul", "neo-soul", "neo soul", "funk",
        "jazz", "smooth jazz", "gospel",
    ],
    "pop": [
        "pop", "edm", "house", "dance", "electro", "electronic", "disco",
        "synth-pop", "synthpop", "afrobeat", "afro-beat", "afrobeats",
        "k-pop", "kpop",
    ],
    "latin/salsa": [
        "salsa", "latin", "reggaeton", "cumbia", "bachata", "merengue",
        "mambo", "tango",
    ],
    "classic-rock": [
        "rock", "classic rock", "classic-rock", "punk", "indie",
        "alternative", "garage rock",
    ],
    "metal": [
        "metal", "thrash", "djent", "death metal", "metalcore", "hardcore",
        "black metal",
    ],
    "calm": [
        "lofi", "lo-fi", "lo fi", "chill", "ambient", "relax", "relaxing",
        "meditation", "sleep", "calm",
    ],
    "calm-classical": [
        "classical", "nocturne", "solo piano", "piano ballad",
    ],
}

# Flat alias -> owning preset key lookup, used for the difflib fallback so a
# fuzzy match against an alias string still resolves to the right preset.
_ALIAS_TO_KEY: dict[str, str] = {}
for _key, _words in ALIASES.items():
    for _w in _words:
        _ALIAS_TO_KEY[_w] = _key
# also let exact preset keys map to themselves in the fuzzy pool
for _key in ALL_PRESET_KEYS:
    _ALIAS_TO_KEY[_key] = _key

_FUZZY_POOL = list(_ALIAS_TO_KEY.keys())

DEFAULT_FALLBACK = "pop"


@dataclass
class RouteResult:
    label: str        # the original text the user typed/selected
    preset_key: str   # resolved GENRE_PRESETS / list_genres() key
    approx: bool       # True if this was not an exact known-key match

    def as_tuple(self) -> tuple[str, str, bool]:
        return (self.label, self.preset_key, self.approx)


def map_free_text_genre(text: str) -> tuple[str, bool]:
    """Map a single free-text genre string to (preset_key, approx).

    approx=False only when the normalized text is an exact known preset key.
    Everything else (alias keyword hit or fuzzy fallback) is approx=True.
    """
    if text is None:
        return DEFAULT_FALLBACK, True
    norm = text.strip().lower()
    if not norm:
        return DEFAULT_FALLBACK, True

    # 1. exact key match
    if norm in ALL_PRESET_KEYS:
        return norm, False

    # 2. keyword/substring alias match (longest alias first so more specific
    #    phrases like "boom bap" win over shorter incidental substrings)
    for key, words in sorted(ALIASES.items(), key=lambda kv: 0):
        for w in sorted(words, key=len, reverse=True):
            if w in norm:
                return key, True

    # 3. fuzzy nearest match against known keys + aliases
    matches = difflib.get_close_matches(norm, _FUZZY_POOL, n=1, cutoff=0.6)
    if matches:
        return _ALIAS_TO_KEY[matches[0]], True

    # also try fuzzy match token-by-token (handles "jazzz" or multi-word
    # noise like "some kind of trap beat")
    for token in norm.replace(",", " ").split():
        matches = difflib.get_close_matches(token, _FUZZY_POOL, n=1, cutoff=0.7)
        if matches:
            return _ALIAS_TO_KEY[matches[0]], True

    # 4. fallback
    return DEFAULT_FALLBACK, True


def route_genres(selected: list[str] | None,
                  free_text: str | None) -> list[tuple[str, str, bool]]:
    """Combine checkbox selections + free-text into a deduped route list.

    Args:
        selected: list of known preset keys chosen via CheckboxGroup (exact
            keys, so always approx=False).
        free_text: comma-separated arbitrary genre text.

    Returns:
        list of (label, preset_key, approx) tuples, in the order first seen,
        deduplicated by preset_key (first label wins for a given key).
    """
    results: list[RouteResult] = []
    seen_keys: set[str] = set()

    for label in (selected or []):
        if not label:
            continue
        key, approx = (label, False) if label in ALL_PRESET_KEYS else map_free_text_genre(label)
        if key not in seen_keys:
            results.append(RouteResult(label=label, preset_key=key, approx=approx))
            seen_keys.add(key)

    if free_text:
        for token in free_text.split(","):
            token = token.strip()
            if not token:
                continue
            key, approx = map_free_text_genre(token)
            if key not in seen_keys:
                results.append(RouteResult(label=token, preset_key=key, approx=approx))
                seen_keys.add(key)

    return [r.as_tuple() for r in results]
