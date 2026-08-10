"""
groovegen.session_render
========================

Render an ARBITRARY closed-loop *session trace* (the bar-by-bar rows the
experiment UI produces) to a single audio file, reusing the exact same bed
sourcing + drum overlay + splice machinery as notebook 15's hero pipeline.

WHY THIS EXISTS
---------------
nb15's own render block is hard-wired to the scripted 64-bar hero descent: it
asserts EXACTLY 4-5 segments in the order [latin, pop, r&b, calm] spanning all
four tempo bands. An interactive session (the operator types heart rates and
steps) produces WHATEVER arc the operator drove -- often 1 genre, a handful of
bars. Feeding that into nb15's block trips its assertions immediately.

This module keeps nb15's hero pipeline untouched and provides a RELAXED
renderer for the UI: segment on genre-band change, allow 1..N segments in any
order, render each with the library-bed path (pick_nearest_bed -> retime ->
per-bar drum overlay), then splice consecutive segments on their downbeats.

HONEST SCOPE (unchanged): this renders the audio arc that the operator-driven
control loop produced. It is a SYSTEM/METHOD artifact, not an efficacy claim.
Heart rate is the input the controller tracks; the plant is not modeled here.

The bed source is the CURATED LIBRARY only (USE_LIBRARY path). No MusicGen at
render time, no raw-song fallback. Every bed is a human-vetted library clip
retimed to the segment's committed tempo. If the library has no bed for a
band, that segment is skipped with a logged warning rather than silently
substituting an ungated clip.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from typing import Callable, List, Dict, Optional

import numpy as np
import soundfile as sf

from groovegen import hybrid_render as hr
from groovegen.bed_library import pick_nearest_bed, retime_bed


# ---- band derivation: identical thresholds to nb15 / app_experiment ----------
def genre_from_tempo(bpm: float) -> str:
    if bpm >= 112:
        return "latin"
    if bpm >= 98:
        return "pop"
    if bpm >= 84:
        return "r&b"
    return "calm"


# nb15 constants, mirrored so this module is import-cycle free and standalone.
GENRE_TO_LIBRARY_KEY = {"latin": "latin/salsa", "pop": "pop", "r&b": "r&b/soul", "calm": "calm"}
GENRE_TO_STYLE = {"r&b": "r&b", "pop": "pop", "latin": "latin", "calm": "r&b"}
GENRE_DISPLAY_LABEL = {
    "latin": "latin/salsa",
    "pop": "pop",
    "r&b": "r&b/soul",
    "calm": "calm (sparse low-tempo R&B/soul)",
}
CALM_DENSITY_FLOOR = 3
CALM_DENSITY_CEIL = 4


# ---------------------------------------------------------------------------
# Splice cluster -- copied VERBATIM from build_notebook_15.py (lines 708-790)
# so this module is fully self-contained and works standalone (the originals
# live only in the nb15 builder-emitted namespace, not in the groovegen pkg).
# Keep in sync with nb15 if that splice logic ever changes.
# ---------------------------------------------------------------------------
def _last_complete_downbeat_idx(bed_grid, sec_per_bar, downbeat_s, duration_s):
    """Index into bed_grid of the LAST downbeat that starts a full bar which
    still fits entirely inside the bed audio."""
    grid = np.asarray(bed_grid)
    start_idx = int(np.argmin(np.abs(grid - downbeat_s)))
    bar_indices = list(range(start_idx, len(grid), 4))
    best = bar_indices[0]
    for bi in bar_indices:
        if grid[bi] + sec_per_bar <= duration_s + 1e-6:
            best = bi
        else:
            break
    return best


def _first_downbeat_idx_splice(bed_grid, downbeat_s):
    """nb15's simple first-downbeat index (nearest grid entry). Used by the
    splice; distinct from first_downbeat_idx() below which rounds to a bar."""
    grid = np.asarray(bed_grid)
    return int(np.argmin(np.abs(grid - downbeat_s)))


def _micro_fade(y, sr, ms=1.5, side="both"):
    """Tiny linear micro-fade (default 1.5ms) to prevent a click at a hard cut."""
    n = max(1, int(round(sr * ms / 1000.0)))
    n = min(n, len(y) // 4 if len(y) >= 4 else len(y))
    y = y.copy()
    if n <= 0:
        return y
    if side in ("in", "both"):
        y[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)
    if side in ("out", "both"):
        y[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return y


def _splice_beds_downbeat_hard_cut(bed_wav_a, bed_wav_b, out_wav,
                                   expected_tempo_a=None, expected_tempo_b=None):
    """Downbeat-aligned hard cut with 1.5ms micro-fades (no crossfade overlap).
    Verbatim from nb15."""
    def _band(expected):
        if expected is None:
            return 70.0, 180.0
        e = float(expected)
        return max(30.0, e * 0.55), e * 1.45
    tmin_a, tmax_a = _band(expected_tempo_a)
    tmin_b, tmax_b = _band(expected_tempo_b)
    # suppress_bed_drums=True: strip the library bed's baked-in MusicGen drums
    # so ONLY the overlaid synthetic groove is heard (see get_bed_info docstring).
    info_a = hr.get_bed_info(bed_wav_a, expected_tempo=expected_tempo_a,
                             tempo_min=tmin_a, tempo_max=tmax_a,
                             suppress_bed_drums=True)
    info_b = hr.get_bed_info(bed_wav_b, expected_tempo=expected_tempo_b,
                             tempo_min=tmin_b, tempo_max=tmax_b,
                             suppress_bed_drums=True)
    sr = info_a["sr"]
    assert info_b["sr"] == sr, "beds must share sample rate"
    cut_idx_a = _last_complete_downbeat_idx(
        info_a["bed_grid"], info_a["sec_per_bar"], info_a["downbeat_s"], info_a["duration_s"])
    cut_sample_a = int(round(info_a["bed_grid"][cut_idx_a] * sr))
    start_idx_b = _first_downbeat_idx_splice(info_b["bed_grid"], info_b["downbeat_s"])
    start_sample_b = int(round(info_b["bed_grid"][start_idx_b] * sr))
    seg_a = _micro_fade(info_a["y"][:cut_sample_a], sr, ms=1.5, side="out")
    seg_b = _micro_fade(info_b["y"][start_sample_b:], sr, ms=1.5, side="in")
    out = np.concatenate([seg_a, seg_b]).astype(np.float32)
    sf.write(out_wav, out, sr)
    return dict(out_wav=out_wav, sr=sr, seam_sample=len(seg_a))


def segment_trace(trace: List[Dict]) -> List[Dict]:
    """Split a bar-by-bar trace into contiguous same-genre segments.

    trace rows need at least 'tempo_bpm' and 'density'. Genre is DERIVED from
    committed tempo (band edges 112/98/84), exactly like nb15. Returns a list
    of dict(start_bar, end_bar, genre, tempo_bpm) where tempo_bpm is the tempo
    at the START of the segment (the tempo the bed is retimed to).

    Unlike nb15 there are NO count/order assertions: an interactive session may
    legitimately be a single band or any ordering of bands.
    """
    n = len(trace)
    if n == 0:
        return []
    committed_tempo = [int(round(float(t["tempo_bpm"]))) for t in trace]
    committed_genre = [genre_from_tempo(bpm) for bpm in committed_tempo]
    segments: List[Dict] = []
    seg_start = 0
    for i in range(1, n + 1):
        at_end = (i == n)
        genre_changed = (not at_end) and (committed_genre[i] != committed_genre[seg_start])
        if at_end or genre_changed:
            segments.append(dict(
                start_bar=seg_start,
                end_bar=i,
                genre=committed_genre[seg_start],
                tempo_bpm=committed_tempo[seg_start],
            ))
            seg_start = i
    return segments


def _build_segment_mix(seg: Dict, info: Dict, trace: List[Dict]) -> np.ndarray:
    """Per-bar drum overlay on a segment's bed. Verbatim logic from nb15's
    build_segment_mix (bed on top, drums under, calm density clamp, latin
    drum trim), just parameterized by the passed-in trace."""
    sr = info["sr"]
    sec_per_bar = info["sec_per_bar"]
    bed_grid = np.asarray(info["bed_grid"])
    bars_in_seg = trace[seg["start_bar"]:seg["end_bar"]]

    if seg["genre"] == "calm":
        densities_needed_raw = [int(np.clip(int(t["density"]), CALM_DENSITY_FLOOR, CALM_DENSITY_CEIL))
                                for t in bars_in_seg]
    else:
        densities_needed_raw = [int(t["density"]) for t in bars_in_seg]
    densities_needed = sorted(set(densities_needed_raw))

    drum_by_density = {}
    for d in densities_needed:
        res = hr.render_aligned_drums(info, drum_style=GENRE_TO_STYLE[seg["genre"]],
                                      event_density=int(d), seed=0)
        drum_by_density[d] = res["drums"]

    bed_y = info["y"]
    # match nb15's build_segment_mix EXACTLY: it uses the simple
    # first_downbeat_idx (nearest grid entry), not a bar-rounded one.
    start_idx = _first_downbeat_idx_splice(bed_grid, info["downbeat_s"])
    mixed = np.zeros_like(bed_y)
    n_bars_seg = len(bars_in_seg)
    for k in range(n_bars_seg):
        if start_idx + 4 * (k + 1) < len(bed_grid):
            t0 = bed_grid[start_idx + 4 * k]
            t1 = bed_grid[start_idx + 4 * (k + 1)]
        else:
            t0 = bed_grid[start_idx + 4 * k] if start_idx + 4 * k < len(bed_grid) else k * sec_per_bar
            t1 = t0 + sec_per_bar
        i0 = int(round(t0 * sr))
        i1 = int(round(t1 * sr))
        i1 = min(i1, len(bed_y))
        if i0 >= i1:
            continue
        d = densities_needed_raw[k]
        drum_chunk = drum_by_density[d][i0:i1]
        n = min(i1 - i0, len(drum_chunk))
        mixed[i0:i0 + n] += drum_chunk[:n]

    drum_gain = 0.62
    if seg["genre"] == "latin":
        drum_gain *= 0.84
    mix = 1.0 * bed_y + drum_gain * mixed
    m = np.abs(mix).max()
    if m > 1e-9:
        mix = (mix / m * 0.95).astype(np.float32)
    return mix.astype(np.float32)


def render_session(trace: List[Dict],
                   out_wav: str,
                   library_dir: str = "library",
                   log: Optional[Callable[[str], None]] = None) -> Optional[str]:
    """Render an interactive session trace to a single WAV file.

    Parameters
    ----------
    trace : list of dict with 'tempo_bpm' and 'density' (the UI's session.trace)
    out_wav : output path for the assembled audio
    library_dir : bed library root (matches bed_library.LIBRARY_DIR default)
    log : optional callback for progress messages (UI status box / print)

    Returns the path to out_wav on success, or None if nothing renderable
    (empty trace, or no library bed for any segment's band).
    """
    def _log(m):
        if log:
            log(m)
        else:
            print(m)

    if not trace:
        _log("[render] empty trace -- step the controller first.")
        return None

    segments = segment_trace(trace)
    _log(f"[render] {len(trace)} bars -> {len(segments)} segment(s):")
    for s in segments:
        _log(f"    bars[{s['start_bar']}:{s['end_bar']}) "
             f"{GENRE_DISPLAY_LABEL[s['genre']]} ~{s['tempo_bpm']} bpm")

    workdir = tempfile.mkdtemp(prefix="gg_session_")
    seg_infos: List[Dict] = []
    kept_segments: List[Dict] = []
    kept_mix_wavs: List[str] = []

    for i, seg in enumerate(segments):
        lib_genre = GENRE_TO_LIBRARY_KEY[seg["genre"]]
        lib_hit = pick_nearest_bed(lib_genre, seg["tempo_bpm"], library_dir=library_dir)
        if lib_hit is None:
            _log(f"[render] [{i+1}/{len(segments)}] no library bed for '{lib_genre}' "
                 f"@ ~{seg['tempo_bpm']}bpm -- SKIPPING this segment.")
            continue
        lib_bpm = float(os.path.basename(lib_hit).split("bpm_")[0])
        bed_wav = os.path.join(workdir, f"seg{i}_{seg['genre'].replace('/', '-')}_{seg['tempo_bpm']}bpm.wav")
        retime_bed(lib_hit, bed_wav, from_bpm=lib_bpm, to_bpm=float(seg["tempo_bpm"]))
        _log(f"[render] [{i+1}/{len(segments)}] {GENRE_DISPLAY_LABEL[seg['genre']]}: "
             f"library {os.path.basename(lib_hit)} @ {lib_bpm:.0f}bpm -> retimed to {seg['tempo_bpm']}bpm")

        _exp_t = float(seg["tempo_bpm"])
        # suppress_bed_drums=True: strip the bed's baked-in MusicGen drums so the
        # overlaid controllable synthetic drums are the only rhythmic layer.
        info = hr.get_bed_info(bed_wav, expected_tempo=_exp_t,
                               tempo_min=max(30.0, _exp_t * 0.55),
                               tempo_max=_exp_t * 1.45,
                               suppress_bed_drums=True)
        mix = _build_segment_mix(seg, info, trace)
        mix_wav = os.path.join(workdir, f"_mix_{i}.wav")
        sf.write(mix_wav, mix, info["sr"])
        seg_infos.append(info)
        kept_segments.append(seg)
        kept_mix_wavs.append(mix_wav)

    if not kept_mix_wavs:
        _log("[render] no renderable segments (library empty for every band). "
             "Build the bed library first (LIB_build_beds).")
        return None

    SR = seg_infos[0]["sr"]
    assert all(info["sr"] == SR for info in seg_infos), "sample rates differ across segments"

    if len(kept_mix_wavs) == 1:
        shutil.copy(kept_mix_wavs[0], out_wav)
    else:
        current = kept_mix_wavs[0]
        for i in range(1, len(kept_mix_wavs)):
            nxt = os.path.join(workdir, f"_chain_{i}.wav")
            _splice_beds_downbeat_hard_cut(
                current, kept_mix_wavs[i], nxt,
                expected_tempo_a=float(kept_segments[i - 1]["tempo_bpm"]),
                expected_tempo_b=float(kept_segments[i]["tempo_bpm"]),
            )
            current = nxt
        shutil.copy(current, out_wav)

    y, _sr = sf.read(out_wav)
    dur = len(y) / float(SR)
    _log(f"[render] done -> {out_wav}  ({dur:.1f}s, {len(kept_mix_wavs)} segment(s), sr={SR})")
    return out_wav
