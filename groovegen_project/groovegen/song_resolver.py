"""song_resolver.py -- resolve "song name + artist" -> a local audio clip.

Instead of hand-uploading 12 mp3s, the user lists song name + artist per bucket
(danceable / enjoyed / relaxing). This module looks each one up on the PUBLIC
iTunes Search API (https://itunes.apple.com/search) -- NO Apple developer
account, NO API key, NO auth -- downloads the LEGAL 30-second `previewUrl` it
returns, and saves it to songs/<bucket>N.wav (transcoded from the AAC preview).

Why this and not Spotify features / YouTube:
  * Spotify audio-features API was deprecated for new apps (Nov 2024).
  * YouTube full-track download violates YouTube ToS -- unacceptable for a
    published paper + IRB study.
  * The 30s iTunes preview is a legal clip; we run the SAME feature extractor
    (profile_from_songs) on it that we'd run on an uploaded file, so profiles
    stay consistent with the manual-upload path.

HONEST LIMITS (surfaced to the user, not hidden):
  * 30 seconds only. Track-level features (tempo, energy, valence) are stable
    over a preview, but if a song has a very different intro vs drop, the
    preview window (Apple picks a representative ~middle section) may catch the
    "wrong" part. We print detected tempo/RMS per track so the user can sanity
    check before generation.
  * Coverage: obscure / very new / regional tracks may have no preview. Those
    are reported as MISSES so the user can hand-supply just those files.
  * Matching: a naive top hit can be a cover/remix (e.g. "Despecha Rosalia" ->
    a KIDZ BOP cover). We rank by artist-name similarity and DOWN-weight
    remix/live/karaoke/cover versions to prefer the canonical recording.
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request

ITUNES_SEARCH = "https://itunes.apple.com/search"
_UA = {"User-Agent": "Mozilla/5.0 (GrooveGen research; contact via notebook)"}

# versions we'd rather NOT pick when a cleaner original exists
_DISPREFER = re.compile(
    r"\b(remix|live|karaoke|cover|instrumental|sped up|slowed|8d|mixed|"
    r"tribute|made famous|originally performed)\b",
    re.IGNORECASE,
)


def _http_json(url: str, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _simplify(text: str) -> str:
    """Strip parentheses/brackets and 'feat.'/'ft.' credits that often prevent
    a match (e.g. 'Levitating (feat. DaBaby)' -> 'Levitating'). Also drops a
    trailing ' - ...' suffix. Returns a cleaner query fragment."""
    t = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", text)            # remove (...) [...] {...}
    t = re.sub(r"\b(feat\.?|ft\.?|featuring|with)\b.*", " ", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+-\s+.*$", " ", t)                         # drop ' - remaster' etc
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _search(term: str, limit: int = 15) -> list[dict]:
    q = urllib.parse.urlencode(
        {"term": term, "media": "music", "entity": "song", "limit": limit}
    )
    try:
        data = _http_json(f"{ITUNES_SEARCH}?{q}")
    except Exception as e:  # network / rate-limit -> treat as no results
        print(f"    [warn] iTunes lookup failed for {term!r}: {e}")
        return []
    return [x for x in data.get("results", []) if x.get("previewUrl")]


def _rank(results: list[dict], want_artist: str, want_title: str) -> list[dict]:
    """Rank candidates: artist match first, title match, prefer non-remix."""
    wa, wt = want_artist.lower().strip(), want_title.lower().strip()

    def score(x: dict) -> tuple:
        a = (x.get("artistName") or "").lower()
        t = (x.get("trackName") or "").lower()
        artist_sim = difflib.SequenceMatcher(None, a, wa).ratio() if wa else 0.0
        title_sim = difflib.SequenceMatcher(None, t, wt).ratio() if wt else 0.0
        # penalize remix/live/cover so the canonical version wins ties
        clean = 0.0 if _DISPREFER.search(t) else 1.0
        return (round(artist_sim, 3), clean, round(title_sim, 3))

    return sorted(results, key=score, reverse=True)


def _to_wav(src: str, dst_wav: str, sr: int = 44100) -> None:
    """Transcode any audio file to 16-bit PCM WAV at `dst_wav`.

    Prefers ffmpeg (present on Colab). Falls back to librosa+soundfile if ffmpeg
    isn't on PATH. Raises on total failure so the caller can report a miss.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        proc = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", src,
             "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", dst_wav],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        if proc.returncode == 0 and os.path.exists(dst_wav) and os.path.getsize(dst_wav) > 0:
            return
        # fall through to the library path if ffmpeg somehow produced nothing
    # library fallback (audioread decodes AAC/.m4a via its own backends)
    import librosa
    import soundfile as sf
    y, _sr = librosa.load(src, sr=sr, mono=True)
    sf.write(dst_wav, y, sr, subtype="PCM_16")
    if not (os.path.exists(dst_wav) and os.path.getsize(dst_wav) > 0):
        raise RuntimeError(f"transcode to WAV produced no output: {dst_wav}")


def resolve_one(
    name: str,
    artist: str,
    *,
    out_path: str,
    download: bool = True,
) -> dict | None:
    """Look up one 'name by artist', pick the best canonical match, download
    its 30s preview to out_path. Returns a report dict, or None on miss."""
    # Try progressively simpler queries before declaring a miss:
    #   1) exact "title artist"
    #   2) simplified title (strip parentheses/feat.) + artist
    #   3) simplified title + simplified artist
    #   4) simplified title alone (last resort; artist ranking still applied)
    simp_name = _simplify(name)
    simp_artist = _simplify(artist)
    query_variants = [f"{name} {artist}".strip()]
    for q in (f"{simp_name} {artist}".strip(),
              f"{simp_name} {simp_artist}".strip(),
              simp_name):
        if q and q not in query_variants:
            query_variants.append(q)

    results, term = [], query_variants[0]
    for i, q in enumerate(query_variants):
        results = _search(q)
        if results:
            term = q
            if i > 0:
                print(f"    (retry) matched on simplified query {q!r}")
            break
    if not results:
        return None
    best = _rank(results, artist, name)[0]
    rep = {
        "query": term,
        "matched_artist": best.get("artistName"),
        "matched_title": best.get("trackName"),
        "itunes_genre": best.get("primaryGenreName"),
        "preview_url": best.get("previewUrl"),
        "out_path": out_path,
        "downloaded": False,
        "dispreferred_version": bool(_DISPREFER.search(best.get("trackName", ""))),
    }
    if download:
        try:
            req = urllib.request.Request(best["previewUrl"], headers=_UA)
            with urllib.request.urlopen(req, timeout=25) as r:
                blob = r.read()
            os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
            # iTunes previews arrive as AAC/.m4a. Transcode to WAV on download so
            # every downstream tool (soundfile-based or otherwise) can read it and
            # the 'Format not recognised' class of bug can't recur.
            with tempfile.NamedTemporaryFile(suffix=".m4a", delete=False) as tf:
                tf.write(blob)
                tmp_m4a = tf.name
            try:
                _to_wav(tmp_m4a, out_path)
            finally:
                try:
                    os.remove(tmp_m4a)
                except OSError:
                    pass
            rep["downloaded"] = True
            rep["out_path"] = out_path
            rep["bytes"] = os.path.getsize(out_path)
        except Exception as e:
            print(f"    [warn] preview download/transcode failed for {term!r}: {e}")
            return None
    return rep


def _quick_probe(path: str) -> dict:
    """Detected tempo + loudness so the user can sanity-check the preview
    window. Best-effort: returns {} if librosa isn't importable."""
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(path, sr=None, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        return {
            "detected_bpm": round(float(np.atleast_1d(tempo)[0]), 1),
            "duration_s": round(len(y) / sr, 1),
            "rms": round(float(np.sqrt(np.mean(y ** 2))), 3),
        }
    except Exception:
        return {}


def resolve_songs(
    requests: dict[str, list[tuple[str, str]]],
    *,
    out_dir: str = "songs",
    probe: bool = True,
) -> tuple[dict[str, list[str]], list[dict]]:
    """Resolve a bucketed set of (name, artist) pairs into local clips.

    Args:
        requests: {"danceable": [("Levitating","Dua Lipa"), ...],
                   "enjoyed":   [...], "relaxing": [...]}
        out_dir:  where to save clips (default "songs").
        probe:    if True, print detected tempo/RMS per resolved clip.

    Returns:
        (song_paths, misses)
        song_paths -> {bucket: [local_path, ...]}  (feed straight to build_profile)
        misses     -> [{"bucket","name","artist"}] for anything not found, so the
                      user can hand-supply just those files.
    """
    os.makedirs(out_dir, exist_ok=True)
    song_paths: dict[str, list[str]] = {b: [] for b in requests}
    misses: list[dict] = []

    print("Resolving songs via iTunes Search API (public, no account/key)...\n")
    for bucket, pairs in requests.items():
        for i, (name, artist) in enumerate(pairs, 1):
            # previews arrive as AAC but are transcoded to WAV on download so
            # every downstream reader is happy -> save as .wav
            out_path = os.path.join(out_dir, f"{bucket}{i}.wav")
            rep = resolve_one(name, artist, out_path=out_path)
            if rep is None or not rep.get("downloaded"):
                print(f"  [{bucket}] MISS  {name!r} by {artist!r} "
                      f"-- no preview found; upload this one manually")
                misses.append({"bucket": bucket, "name": name, "artist": artist})
                continue
            song_paths[bucket].append(out_path)
            line = (f"  [{bucket}] OK    {rep['matched_artist']} - "
                    f"{rep['matched_title']}  ({rep['itunes_genre']})")
            if rep["dispreferred_version"]:
                line += "  [!] looks like a remix/live/cover -- verify"
            print(line)
            if probe:
                pr = _quick_probe(out_path)
                if pr:
                    print(f"           preview: {pr['duration_s']}s | "
                          f"~{pr['detected_bpm']:.0f} bpm | rms {pr['rms']}")

    # transparent summary
    n_ok = sum(len(v) for v in song_paths.values())
    print(f"\nResolved {n_ok} clip(s); {len(misses)} miss(es).")
    if misses:
        print("MISSES -- save these into songs/ yourself, named "
              "<bucket><N> (e.g. danceable3.mp3), then re-run B.1:")
        for m in misses:
            print(f"   - {m['bucket']}: {m['name']} by {m['artist']}")
    return song_paths, misses
