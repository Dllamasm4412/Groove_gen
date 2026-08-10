"""
auto_fallback.py -- pick clean fallback beds automatically from the user's own
uploaded songs, so the caller does not have to hand-supply a clean WAV per genre.

WHY: generate_and_gate() replaces a wobbly MusicGen bed with a clean fallback only
if one is provided per genre band. Pop is the usual gap (no clean pop bed on hand).
Rather than invent a bed, we REUSE a real uploaded song: pick the candidate whose
tempo is closest to the target band and whose measured tempo stability is best
(lowest jitter + grid error), optionally time-stretched onto the exact target BPM.

This is honest: the fallback is a real, measured-clean audio clip the user chose,
not a synthetic placeholder. Selection is by the SAME metrics the quality gate uses.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np
import soundfile as sf

from .generate_and_gate import measure_tempo_stability, QualityGate

# Tempo windows per genre band (BPM). Matches the project's genre_from_tempo
# convention: latin >=112, pop 98-112, r&b 84-98, calm <84. Windows are a bit
# wider than the hard bands so a nearby clean track can still qualify.
GENRE_TEMPO_WINDOW = {
    "latin": (108, 140),
    "pop":   (96, 116),
    "r&b":   (82, 100),
    "calm":  (60, 88),
}
GENRE_TARGET_BPM = {"latin": 122, "pop": 106, "r&b": 92, "calm": 76}


def _load_mono(path: str):
    """Load any audio (wav/flac/ogg AND m4a/mp3/aac) as mono float.

    soundfile alone can't read AAC/.m4a (the format iTunes previews come in) --
    it raises 'Format not recognised'. librosa.load goes through audioread/ffmpeg,
    which handles those. Try librosa first, fall back to soundfile.
    """
    try:
        import librosa
        y, sr = librosa.load(path, sr=None, mono=True)  # ffmpeg-backed for m4a/mp3
        return np.asarray(y, dtype=float), int(sr)
    except Exception:
        y, sr = sf.read(path)
        if getattr(y, "ndim", 1) > 1:
            y = y.mean(axis=1)
        return np.asarray(y, dtype=float), sr


def _time_stretch(y: np.ndarray, sr: int, rate: float) -> np.ndarray:
    """rate>1 -> faster/shorter. Uses librosa if available; else resample fallback."""
    if abs(rate - 1.0) < 1e-3:
        return y
    try:
        import librosa
        return librosa.effects.time_stretch(y.astype(np.float32), rate=rate)
    except Exception:
        # crude fallback: linear resample (changes pitch, but keeps grid usable)
        n = max(1, int(round(len(y) / rate)))
        xp = np.linspace(0, len(y) - 1, num=n)
        return np.interp(xp, np.arange(len(y)), y).astype(np.float32)


def score_candidate(path: str, target_bpm: float) -> dict:
    """Measure how clean a candidate is at the target tempo (lower is cleaner)."""
    y, sr = _load_mono(path)
    m = measure_tempo_stability(y, sr, target_bpm)
    return {"path": path, "sr": sr, "n": len(y), **m,
            "clean_score": m["beat_jitter_ms"] + m["grid_err_mean_ms"]}


def choose_fallback(
    candidate_paths: list,
    genre: str,
    *,
    out_wav: Optional[str] = None,
    target_bpm: Optional[float] = None,
    gate: Optional[QualityGate] = None,
    stretch_to_target: bool = True,
    prefer_in_window: bool = True,
) -> Optional[dict]:
    """Pick the cleanest candidate for `genre` and (optionally) write it stretched
    to the target BPM at `out_wav`.

    Returns a dict {path, out_wav, detected_bpm, beat_jitter_ms, grid_err_mean_ms,
    clean_score, passes_gate, stretched_rate} for the winner, or None if no
    candidate could be scored.

    Strategy:
      1. Score every candidate at the genre's target BPM (same metrics as the gate).
      2. Prefer candidates whose detected tempo already falls in the genre window
         (less stretching = fewer artifacts), then break ties by clean_score.
      3. Optionally time-stretch the winner onto the exact target BPM and write it.
    """
    if not candidate_paths:
        return None
    tgt = float(target_bpm if target_bpm is not None
                else GENRE_TARGET_BPM.get(genre, 100))
    lo, hi = GENRE_TEMPO_WINDOW.get(genre, (tgt * 0.9, tgt * 1.1))
    gate = gate or QualityGate()

    scored = []
    for p in candidate_paths:
        if not os.path.exists(p):
            continue
        try:
            scored.append(score_candidate(p, tgt))
        except Exception as e:
            print(f"  [auto_fallback] skip {os.path.basename(p)}: {e}")
    if not scored:
        return None

    def sort_key(s):
        in_win = 0 if (lo <= s["detected_bpm"] <= hi) else 1
        # if we prefer in-window, that dominates; else pure cleanliness
        return (in_win, s["clean_score"]) if prefer_in_window else (s["clean_score"],)

    scored.sort(key=sort_key)
    win = scored[0]

    rate = 1.0
    if stretch_to_target and win["detected_bpm"] > 0:
        # librosa.effects.time_stretch(rate): rate>1 => faster/higher BPM,
        # rate<1 => slower/lower BPM. To retune detected d BPM to target tgt,
        # the correct factor is tgt/d (VERIFIED empirically: d=120,tgt=100 ->
        # rate 0.83 gives ~103 bpm; the inverse d/tgt=1.2 wrongly gave ~143).
        rate = tgt / win["detected_bpm"]

    result = {
        "path": win["path"],
        "genre": genre,
        "target_bpm": tgt,
        "detected_bpm": win["detected_bpm"],
        "beat_jitter_ms": win["beat_jitter_ms"],
        "grid_err_mean_ms": win["grid_err_mean_ms"],
        "clean_score": round(win["clean_score"], 1),
        "passes_gate": gate.passes(win),
        "stretched_rate": round(rate, 3),
        "out_wav": None,
    }

    if out_wav is not None:
        y, sr = _load_mono(win["path"])
        if stretch_to_target and abs(rate - 1.0) >= 1e-3:
            y = _time_stretch(y, sr, rate)
        m = np.abs(y).max()
        if m > 1e-9:
            y = (y / m * 0.95).astype(np.float32)
        os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
        sf.write(out_wav, y, sr)
        result["out_wav"] = out_wav

    return result


def auto_fallback_beds(
    song_paths: dict,
    genres: list,
    out_dir: str,
    *,
    gate: Optional[QualityGate] = None,
    stretch_to_target: bool = True,
) -> dict:
    """Build a {genre: clean_wav_path} dict from the user's uploaded songs.

    `song_paths` is the same bucket dict used for the profile
    ({'danceable':[...], 'enjoyed':[...], 'relaxing':[...]}). All songs are pooled
    as candidates; for each requested genre we pick the cleanest fit and write
    <out_dir>/fallback_<genre>.wav.

    Returns {genre: out_wav} suitable to pass as generate_and_gate(fallback_beds=...).
    Prints a short report so the choice is transparent, not magic.
    """
    gate = gate or QualityGate()
    pool = []
    for bucket in song_paths.values():
        pool.extend(bucket)
    pool = [p for p in pool if os.path.exists(p)]

    chosen = {}
    print("=== auto fallback selection (from your uploaded songs) ===")
    print("  (picks the CLEANEST available real song per genre; 'best-effort' means")
    print("   it beat every alternative but still measures above the strict gate --")
    print("   a real fallback, just not guaranteed gate-passing. Provide a hand-picked")
    print("   clean WAV to override any genre you're unhappy with.)")
    for g in genres:
        out_wav = os.path.join(out_dir, f"fallback_{g.replace('&','n')}.wav")
        r = choose_fallback(pool, g, out_wav=out_wav, gate=gate,
                            stretch_to_target=stretch_to_target)
        if r is None:
            print(f"  {g:6s}: no candidate available")
            continue
        chosen[g] = r["out_wav"]
        tag = "PASSES gate" if r["passes_gate"] else "best-effort (fails gate)"
        print(f"  {g:6s}: {os.path.basename(r['path'])}  "
              f"det={r['detected_bpm']}bpm -> {r['target_bpm']:.0f}bpm "
              f"(rate {r['stretched_rate']})  jitter={r['beat_jitter_ms']}ms "
              f"grid={r['grid_err_mean_ms']}ms  {tag}")
    return chosen
