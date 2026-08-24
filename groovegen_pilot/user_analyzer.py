"""GrooveGen M1 — User Analyzer.

Takes 12 songs from the user (uploaded files and/or URLs) and produces one
librosa MIRFeatures record per song, in the same 7-field schema the arousal
plant already consumes.

Design boundary:
    - Whole-track features only, no source separation (Demucs skipped).
      Rationale: for A+B personalization we only need a per-song descriptor
      to compute (a) predicted arousal via ArousalPlantConfig.contribution and
      (b) nearest-family classification. Neither needs stem-separated
      features, and Demucs adds ~1 min/song of GPU cost we do not need.
    - HPSS is used for percussive_ratio, which is the strongest positive
      predictor in Sophia's regression. This is cheap on CPU (~1 sec/song).
    - Feature scales match music_features.MIRFeatures exactly:
        tempo_bpm         float
        percussive_ratio  float 0..1
        low_band_energy   float 0..1
        beat_consistency  float 0..1
        onset_density     onsets/sec
        syncopation       float 0..1
        spectral_flatness float 0..1

URL support: yt-dlp handles YouTube, SoundCloud, and direct MP3/WAV links.
Downloaded audio is stashed under a per-run temp dir; caller is responsible
for cleanup if desired.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import librosa
import numpy as np

from music_features import MIRFeatures

SUPPORTED_AUDIO_EXT = {'.mp3', '.wav', '.flac', '.m4a', '.aac', '.ogg', '.opus'}
EXPECTED_SONG_COUNT = 12
DEFAULT_ANALYZE_SR = 22_050
DEFAULT_ANALYZE_DURATION_S = 60.0  # analyze at most 60s per song for speed


@dataclass(frozen=True)
class SongResult:
    """One song's contribution to the user's descriptor."""
    source: str          # original path or URL
    resolved_path: str   # local path used for analysis
    duration_s: float
    features: MIRFeatures


def _is_url(s: str) -> bool:
    return s.startswith(('http://', 'https://'))


def _download_url(url: str, out_dir: Path) -> Path:
    """Download the audio track for a URL via yt-dlp. Returns the local path.

    Uses `-x --audio-format wav` so downstream librosa loading is simple. If
    ffmpeg is missing yt-dlp will still write the source container.
    """
    out_template = str(out_dir / '%(id)s.%(ext)s')
    cmd = [
        'yt-dlp',
        '-x',
        '--audio-format', 'wav',
        '--audio-quality', '0',
        '--no-playlist',
        '--quiet',
        '--no-warnings',
        '-o', out_template,
        url,
    ]
    subprocess.run(cmd, check=True)
    # yt-dlp writes exactly one file per URL when --no-playlist is set.
    wavs = list(out_dir.glob('*.wav'))
    if not wavs:
        # fall back: any file just created
        wavs = sorted(out_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if not wavs:
            raise RuntimeError(f'yt-dlp produced no output for {url}')
    # Return the most recently created audio file in out_dir
    return sorted(wavs, key=lambda p: p.stat().st_mtime)[-1]


def resolve_inputs(sources: Sequence[str],
                   *,
                   work_dir: Path | None = None,
                   expected: int = EXPECTED_SONG_COUNT) -> list[tuple[str, Path]]:
    """Turn a mixed list of file paths and URLs into local audio paths.

    Returns list of (original_source, local_path). Raises if the count is not
    exactly `expected` after resolution.
    """
    if len(sources) != expected:
        raise ValueError(
            f'Expected exactly {expected} songs, got {len(sources)}. '
            f'A+B personalization is defined against a 12-song intake; '
            f'shorter lists produce underpowered genre histograms.'
        )
    work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix='gg_user_'))
    work_dir.mkdir(parents=True, exist_ok=True)

    resolved: list[tuple[str, Path]] = []
    for src in sources:
        src = src.strip()
        if _is_url(src):
            per_url_dir = work_dir / f'url_{len(resolved):02d}'
            per_url_dir.mkdir(exist_ok=True)
            local = _download_url(src, per_url_dir)
        else:
            p = Path(src).expanduser().resolve()
            if not p.exists():
                raise FileNotFoundError(f'Song file not found: {p}')
            if p.suffix.lower() not in SUPPORTED_AUDIO_EXT:
                raise ValueError(
                    f'Unsupported audio extension {p.suffix!r} for {p}. '
                    f'Supported: {sorted(SUPPORTED_AUDIO_EXT)}'
                )
            local = p
        resolved.append((src, local))
    return resolved


# =============================================================================
# Feature extraction
# =============================================================================

def _load_mono(path: Path,
               sr: int = DEFAULT_ANALYZE_SR,
               duration: float = DEFAULT_ANALYZE_DURATION_S) -> tuple[np.ndarray, int]:
    y, sr = librosa.load(str(path), sr=sr, mono=True, duration=duration)
    if y.size == 0:
        raise RuntimeError(f'librosa loaded 0 samples from {path}')
    return y, sr


def _tempo_bpm(y: np.ndarray, sr: int) -> float:
    tempo, _ = librosa.beat.beat_track(y=y, sr=sr, units='time')
    # librosa returns np.ndarray in newer versions
    return float(np.atleast_1d(tempo)[0])


def _percussive_ratio(y: np.ndarray) -> float:
    """Ratio of RMS energy in the percussive component to total (HPSS)."""
    y_h, y_p = librosa.effects.hpss(y, margin=1.0)
    rms_p = float(np.sqrt(np.mean(y_p ** 2)) + 1e-12)
    rms_t = float(np.sqrt(np.mean(y ** 2)) + 1e-12)
    return min(1.0, max(0.0, rms_p / rms_t))


def _low_band_energy(y: np.ndarray, sr: int, cutoff_hz: float = 250.0) -> float:
    """Fraction of spectral energy below `cutoff_hz` (bass content proxy)."""
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=512)) ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    low_mask = freqs <= cutoff_hz
    e_low = float(S[low_mask, :].sum())
    e_tot = float(S.sum() + 1e-12)
    return min(1.0, max(0.0, e_low / e_tot))


def _beat_consistency(y: np.ndarray, sr: int) -> float:
    """1 - normalized std of inter-beat intervals. Steady pulse -> ~1."""
    _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    if len(beat_frames) < 4:
        return 0.5
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    ibi = np.diff(beat_times)
    if len(ibi) < 2 or float(np.mean(ibi)) <= 0:
        return 0.5
    cv = float(np.std(ibi) / (np.mean(ibi) + 1e-12))
    return float(max(0.0, min(1.0, 1.0 - cv)))


def _onset_density(y: np.ndarray, sr: int) -> float:
    """Onsets per second."""
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames')
    dur = float(len(y) / sr)
    if dur <= 0:
        return 0.0
    return float(len(onset_frames) / dur)


def _syncopation(y: np.ndarray, sr: int) -> float:
    """Fraction of onsets falling off the metrical grid (off-beat).

    Cheap approximation of syncopation. Aligns onsets to detected beats;
    onsets within a 1/8-beat tolerance of a beat are 'on-grid', the rest
    contribute to syncopation. Not a Witek score, but the same rank sense.
    """
    tempo, beat_times = librosa.beat.beat_track(y=y, sr=sr, units='time')
    onset_times = librosa.onset.onset_detect(y=y, sr=sr, units='time')
    if len(onset_times) == 0 or len(beat_times) < 2:
        return 0.3
    # Tolerance: 1/8 of the beat period
    beat_period = float(np.median(np.diff(beat_times)))
    tol = 0.125 * beat_period
    off_grid = 0
    for t in onset_times:
        # Nearest beat time
        idx = int(np.argmin(np.abs(beat_times - t)))
        if abs(beat_times[idx] - t) > tol:
            off_grid += 1
    return float(min(1.0, off_grid / max(1, len(onset_times))))


def _spectral_flatness(y: np.ndarray) -> float:
    """Mean spectral flatness across frames (0 = tonal, 1 = white noise)."""
    sf = librosa.feature.spectral_flatness(y=y)
    return float(np.clip(np.mean(sf), 0.0, 1.0))


def analyze_song(path: Path,
                 *,
                 sr: int = DEFAULT_ANALYZE_SR,
                 duration: float = DEFAULT_ANALYZE_DURATION_S) -> MIRFeatures:
    """Extract the 7-field MIRFeatures from one audio file."""
    y, sr_out = _load_mono(path, sr=sr, duration=duration)
    return MIRFeatures(
        tempo_bpm=_tempo_bpm(y, sr_out),
        percussive_ratio=_percussive_ratio(y),
        low_band_energy=_low_band_energy(y, sr_out),
        beat_consistency=_beat_consistency(y, sr_out),
        onset_density=_onset_density(y, sr_out),
        syncopation=_syncopation(y, sr_out),
        spectral_flatness=_spectral_flatness(y),
    )


def analyze_batch(sources: Sequence[str],
                  *,
                  work_dir: Path | None = None,
                  expected: int = EXPECTED_SONG_COUNT,
                  keep_temp: bool = False) -> list[SongResult]:
    """Resolve inputs and analyze each song. Returns 12 SongResult rows.

    If `keep_temp` is False and we created a temp work dir for URL downloads,
    it is removed after analysis. Files supplied as paths are never touched.
    """
    created_temp = work_dir is None
    work_dir = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix='gg_user_'))
    try:
        resolved = resolve_inputs(sources, work_dir=work_dir, expected=expected)
        results: list[SongResult] = []
        for src, path in resolved:
            y_len_s = float(librosa.get_duration(path=str(path)))
            feats = analyze_song(path)
            results.append(SongResult(
                source=src,
                resolved_path=str(path),
                duration_s=y_len_s,
                features=feats,
            ))
        return results
    finally:
        if created_temp and not keep_temp:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print('usage: python user_analyzer.py <song1> <song2> ... <song12>')
        print('       (files or URLs; must be exactly 12)')
        sys.exit(1)
    rows = analyze_batch(sys.argv[1:])
    print(f'Analyzed {len(rows)} songs:')
    for i, r in enumerate(rows):
        f = r.features
        print(f'  [{i+1:2d}] tempo={f.tempo_bpm:5.1f}  perc={f.percussive_ratio:.2f}  '
              f'low={f.low_band_energy:.2f}  beat={f.beat_consistency:.2f}  '
              f'onset={f.onset_density:.2f}  sync={f.syncopation:.2f}  '
              f'flat={f.spectral_flatness:.3f}  ({Path(r.source).name})')
