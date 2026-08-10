"""bed_library.py — curated, BPM-tagged bed library manager.

Why this module exists (systems framing, see /Users/daniel/Desktop/PhD/groove_gen_project/assess/PATH_RESEARCH.md
section 3): on-the-fly MusicGen generation gives stochastic, unauditable quality per
run, and MusicGen's training-data bias makes latin/salsa structurally unreliable
(arXiv "Missing Melodies" — non-Western genres are ~5-6% of typical training corpora).
Adaptive/biofeedback-music systems in the literature (Van den Berghe et al. 2021,
Scientific Reports; the BPM-bucketed player in PMC8839467) solve this the same way we
do here: curate a small, fixed, human-vetted library of tracks keyed by BPM, then pick
the nearest-BPM entry at runtime and RE-TIME it (pitch-preserving) to the exact
committed tempo, rather than generating or naively resampling. This decouples
generation-quality risk (stochastic MusicGen sampling) from the real-time control loop
that actually needs to be reliable every run.

Layout on disk:
    library/{genre}/{bpm}bpm_{tag}.wav
where `genre` is sanitized with the SAME regex generate_and_gate.py already uses for
cache filenames, so a bed produced by the curation notebook (LIB_build_beds.ipynb) and
one looked up here always agree on the folder name for a given genre string (e.g.
"r&b/soul" -> "r-b-soul", "latin/salsa" -> "latin-salsa").

Kept dependency-light and CPU-only: numpy + soundfile always; librosa only as the
time-stretch FALLBACK path (already a hard dependency of the rest of groovegen, so this
adds nothing new); pyrubberband is imported lazily inside retime_bed so a machine
without the `rubberband` CLI binary can still import this module and use list_library /
pick_nearest_bed (e.g. for offline unit tests, or a stripped-down inference box).
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import warnings

import numpy as np
import soundfile as sf

# Same sanitizer as generate_and_gate.py's out_wav naming (line ~218 there) —
# keeping it identical (not just similar) is what lets the curation notebook's
# output folder names and this module's lookup folder names always agree.
_GENRE_SANITIZE_RE = re.compile(r"[^0-9A-Za-z]+")

LIBRARY_DIR = "library"


def sanitize_genre(genre: str) -> str:
    """Turn a free-text genre label into a filesystem-safe folder name.

    Identical regex to generate_and_gate.py's `safe_genre` so both sides of the
    library (the offline curation notebook that WRITES it, and this module that
    READS it) never disagree about where a genre's beds live.
    """
    return _GENRE_SANITIZE_RE.sub("-", str(genre)).strip("-") or "bed"


# A bed filename is "{bpm}bpm_{tag}.wav", e.g. "128bpm_cand2.wav" or
# "104.5bpm_symbolic.wav". bpm may be an int or float; tag is free text (no
# further structure assumed) so curators can name kept files descriptively.
_BPM_FROM_NAME_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)bpm_", re.IGNORECASE)


def list_library(genre: str, library_dir: str = LIBRARY_DIR) -> list[tuple[float, str]]:
    """Scan `library_dir/{sanitized genre}/` and return [(bpm, path), ...].

    Returns an empty list (not an error) if the genre folder doesn't exist or has
    no parseable *.wav files — callers (pick_nearest_bed, and the nb15 runtime
    lookup) use an empty result as the signal to fall back to gen_bed.
    """
    folder = os.path.join(library_dir, sanitize_genre(genre))
    if not os.path.isdir(folder):
        return []
    out: list[tuple[float, str]] = []
    for path in sorted(glob.glob(os.path.join(folder, "*.wav"))):
        m = _BPM_FROM_NAME_RE.match(os.path.basename(path))
        if not m:
            continue  # skip files that don't follow the {bpm}bpm_{tag}.wav convention
        out.append((float(m.group(1)), path))
    return out


def pick_nearest_bed(genre: str, target_bpm: float,
                      library_dir: str = LIBRARY_DIR) -> str | None:
    """Return the library bed whose tagged BPM is closest to `target_bpm`.

    None if the genre folder is empty/missing — the caller's cue to fall back
    to on-the-fly generation (gen_bed) as the last resort, per BUILD_SPEC.
    """
    entries = list_library(genre, library_dir=library_dir)
    if not entries:
        return None
    bpm, path = min(entries, key=lambda e: abs(e[0] - float(target_bpm)))
    return path


# ----------------------------------------------------------------------------
# Re-timing: pitch-preserving tempo change (RubberBand, librosa fallback)
# ----------------------------------------------------------------------------
def retime_bed(src_wav: str, out_wav: str, from_bpm: float, to_bpm: float,
               crispness: int = 6, tiny_ratio_eps: float = 0.01) -> str:
    """Re-time `src_wav` from `from_bpm` to `to_bpm`, PRESERVING pitch, and
    write the result to `out_wav`.

    Why pitch-preserving matters here (see CODE_AUDIT.md finding #3): the old
    path (`extra_transition_cell._resample_to_tempo`) is literal sample-rate
    resampling — it changes duration by stretching the time AXIS, which is
    mathematically identical to a turntable speed change and therefore
    unavoidably pitch-shifts the audio. A phase-vocoder/RubberBand time-stretch
    instead re-synthesizes the signal at the new duration while re-imposing the
    original pitch, so a 128->104 BPM re-time (a ~19% stretch, well inside
    RubberBand's high-fidelity zone per PATH_RESEARCH.md section 4) sounds like
    the same bed played slower, not a slowed-down record.

    rate = to_bpm / from_bpm passed to pyrubberband.time_stretch: rate > 1
    means "play faster" (shorter output), rate < 1 means "play slower" (longer
    output) — this matches librosa.effects.time_stretch's `rate` convention too,
    so the fallback path below takes literally the same rate value.

    crispness (0-6, RubberBand's own "--crisp" parameter) trades transient
    sharpness against smoothness; 6 (the max) keeps drum transients articulate
    rather than smeared, which matters far more for a drum-carrying bed than
    for e.g. a sustained pad.

    FALLBACK: if pyrubberband is not importable, OR the `rubberband` CLI binary
    it shells out to is missing (pyrubberband raises on missing binary only at
    call time, not import time), we fall back to librosa.effects.time_stretch
    and print a WARNING — librosa's stretch uses a simplified phase vocoder
    that librosa's own docs call "likely to produce many audible artifacts"
    (PATH_RESEARCH.md section 4), so this must never be a SILENT substitution.

    Guard: if the requested change is tiny (<1% by default), just copy the
    file — time-stretching a near-1.0 ratio buys nothing and only risks
    introducing artifacts from the stretch algorithm for free.
    """
    from_bpm = float(from_bpm)
    to_bpm = float(to_bpm)
    if from_bpm <= 0 or to_bpm <= 0:
        raise ValueError(f"bpm values must be positive, got from_bpm={from_bpm} to_bpm={to_bpm}")

    if abs(to_bpm - from_bpm) / from_bpm < tiny_ratio_eps:
        if os.path.abspath(src_wav) != os.path.abspath(out_wav):
            shutil.copyfile(src_wav, out_wav)
        return out_wav

    rate = to_bpm / from_bpm
    y, sr = sf.read(src_wav)
    multi = y.ndim > 1
    y = np.asarray(y, dtype=np.float64)  # both backends prefer float64 internally

    try:
        import pyrubberband as pyrb
        # pyrubberband takes the SAME layout soundfile.read returns:
        # (n_samples,) mono or (n_samples, n_channels) multi -- no transpose needed.
        y_out = pyrb.time_stretch(y, sr, rate=rate, rbargs={"--crisp": str(int(crispness))})
    except Exception as e:
        warnings.warn(
            f"[bed_library.retime_bed] pyrubberband/rubberband-cli unavailable "
            f"({type(e).__name__}: {e}) -- falling back to librosa.effects.time_stretch. "
            f"This is a LOWER-QUALITY path (librosa's own docs describe its phase "
            f"vocoder as producing audible artifacts); install with "
            f"`pip install pyrubberband && apt-get install -y rubberband-cli` for "
            f"production-quality re-timing.",
            RuntimeWarning,
        )
        import librosa
        # librosa.effects.time_stretch wants the OPPOSITE multichannel layout
        # ((channels, samples), or mono 1-D) -- transpose only on this path.
        if multi:
            y_out = np.stack([librosa.effects.time_stretch(ch, rate=rate) for ch in y.T]).T
        else:
            y_out = librosa.effects.time_stretch(y, rate=rate)

    y_out = np.asarray(y_out, dtype=np.float32)
    if not np.all(np.isfinite(y_out)):
        raise RuntimeError(
            f"retime_bed produced non-finite samples ({src_wav} {from_bpm}->{to_bpm} bpm)")

    sf.write(out_wav, y_out, sr)
    return out_wav
