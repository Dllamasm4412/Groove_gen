"""Build a UserDescriptor from Daniel's 12 seed songs (M1).

Run from inside groovegen_pilot/ with the .venv active:

    python build_my_descriptor.py

Requires yt-dlp and ffmpeg on PATH. Skips downloads that already exist
in ./my_songs/ so you can re-run cheaply.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from user_analyzer import analyze_batch
from user_descriptor import build_descriptor

SONGS_DIR = Path("my_songs")
DESCRIPTOR_OUT = Path("my_descriptor.json")

# 12 seed songs — 3 calm, 3 R&B, 4 pop (dropped fHI8X4OXluQ), 3 latin
# Ordered as: 3 calm, 3 R&B, 3 pop, 3 latin.
SEED = [
    # ---- calm ----
    ("calm_1", "https://www.youtube.com/watch?v=fX5t6boRMnw"),
    ("calm_2", "https://www.youtube.com/watch?v=YyJ8krOGr_A"),
    ("calm_3", "https://www.youtube.com/watch?v=qNYHC9k1Oe8"),
    # ---- R&B ----
    ("rnb_1", "https://www.youtube.com/watch?v=mrV8kK5t0V8"),
    ("rnb_2", "https://www.youtube.com/watch?v=1ipRd0WgB0c"),
    ("rnb_3", "https://www.youtube.com/watch?v=crWbG90dChw"),
    # ---- pop ----
    ("pop_1", "https://www.youtube.com/watch?v=eVli-tstM5E"),
    ("pop_2", "https://www.youtube.com/watch?v=ZbZSe6N_BXs"),
    ("pop_3", "https://www.youtube.com/watch?v=Z4A9ZZo_rAE"),
    # ---- latin ----
    ("latin_1", "https://www.youtube.com/watch?v=n8F55puGHIs"),
    ("latin_2", "https://www.youtube.com/watch?v=YXnjy5YlDwk"),
    ("latin_3", "https://www.youtube.com/watch?v=0nBFWzpWXuM"),
]


def have(binary: str) -> bool:
    from shutil import which

    return which(binary) is not None


def download(label: str, url: str, out_dir: Path) -> Path:
    """Download a single URL as WAV. Returns the file path.
    Skips if a WAV with this label already exists."""
    out_dir.mkdir(parents=True, exist_ok=True)

    wav_path = out_dir / f"{label}.wav"
    if wav_path.exists() and wav_path.stat().st_size > 0:
        print(f"  [skip] {label}: WAV already exists")
        return wav_path

    for existing in out_dir.glob(f"{label}.*"):
        if existing.suffix.lower() in (".wav", ".m4a", ".mp3", ".opus") and existing.stat().st_size > 0:
            return existing

    # yt-dlp will pick the best audio and convert via ffmpeg
    out_template = str(out_dir / f"{label}.%(ext)s")

    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--cookies-from-browser",
        "chrome",
        "--rm-cache-dir",
        "--extractor-args",
        "youtube:player_client=default,-android_vr",
        "--sleep-interval",
        "6",
        "--max-sleep-interval",
        "10",
        "-x",
        "--audio-format",
        "wav",
        "--no-playlist",
        "-o",
        out_template,
        url,
    ]
    print(f"  [download] {label} <- {url}")
    subprocess.run(cmd, check=True)

    # yt-dlp writes label.wav
    if wav_path.exists() and wav_path.stat().st_size > 0:
        return wav_path

    # fall back to whatever it landed on
    for cand in out_dir.glob(f"{label}.*"):
        if cand.suffix.lower() in (".wav", ".m4a", ".mp3", ".opus") and cand.stat().st_size > 0:
            return cand
    raise RuntimeError(f"download failed: {label}")


def main() -> int:
    if not have("ffmpeg"):
        print("ERROR: ffmpeg not on PATH. Install it and retry.")
        print("  macOS: brew install ffmpeg")
        return 1

    try:
        subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        print("ERROR: yt_dlp is not installed in the active .venv.")
        print("  Activate the project venv and install: python -m pip install yt-dlp")
        return 1

    print(f"Downloading {len(SEED)} songs into ./{SONGS_DIR}/ ...")
    paths: list[str] = []
    failed_downloads: list[dict[str, object]] = []
    successful_count = 0

    for idx, (label, url) in enumerate(SEED, start=1):
        genre = label.split("_")[0]
        wav_path = SONGS_DIR / f"{label}.wav"

        if wav_path.exists() and wav_path.stat().st_size > 0:
            print(f"  [skip] {label}: WAV already exists")
            paths.append(str(wav_path))
            successful_count += 1
        else:
            try:
                path = download(label, url, SONGS_DIR)
                if not path.exists() or path.stat().st_size == 0:
                    raise RuntimeError(f"{label} did not produce a usable WAV")
                paths.append(str(path))
                successful_count += 1
            except (subprocess.CalledProcessError, RuntimeError) as e:
                print(f"  [skip] {label}: download failed; continuing.")
                failed_downloads.append({
                    "id": label,
                    "genre": genre,
                    "url": url,
                    "error": str(e),
                })
                continue

        if idx < len(SEED):
            time.sleep(6)

    if failed_downloads:
        print("\nSkipped downloads:")
        for item in failed_downloads:
            print(f"  - {item['id']} ({item['genre']}): {item['url']}")
    else:
        print("\nAll songs downloaded successfully.")

    if not paths:
        print("No usable WAVs were produced. Exiting before descriptor build.")
        return 2

    genre_counts = {}
    for label in (Path(p).stem for p in paths):
        genre = label.split("_")[0]
        genre_counts[genre] = genre_counts.get(genre, 0) + 1

    for genre in ("calm", "rnb", "pop", "latin"):
        if genre_counts.get(genre, 0) < 3:
            print(f"WARNING: genre '{genre}' has only {genre_counts.get(genre, 0)} usable WAVs; consider replacing a missing source.")

    print(f"Built descriptor from {successful_count} successful tracks.")
    print("\nAnalyzing (whole-track librosa MIR, ~5s/song)...")
    results = analyze_batch(paths)

    print("\nPer-song MIR summary:")
    print(
        f"  {'label':10s} {'tempo':>6s} {'perc':>6s} {'low':>6s} "
        f"{'beat':>6s} {'onset':>6s} {'sync':>6s} {'flat':>6s}"
    )
    for (label, _), r in zip(SEED, results):
        f = r.features
        print(
            f"  {label:10s} {f.tempo_bpm:6.1f} {f.percussive_ratio:6.3f} "
            f"{f.low_band_energy:6.3f} {f.beat_consistency:6.3f} "
            f"{f.onset_density:6.3f} {f.syncopation:6.3f} "
            f"{f.spectral_flatness:6.3f}"
        )

    print("\nBuilding descriptor...")
    features = [r.features for r in results]
    desc = build_descriptor(features)

    print(f"\n  target_arousal (Russell 1-9): {desc.target_arousal:.3f}")
    print("  genre_weights:")
    for fam in ("calm", "lofi", "rnb", "pop", "latin"):
        w = desc.genre_weights.get(fam, 0.0)
        bar = "#" * int(round(w * 40))
        print(f"    {fam:6s} {w:5.3f}  {bar}")

    desc.save(str(DESCRIPTOR_OUT))
    print(f"\nSaved -> {DESCRIPTOR_OUT.resolve()}")
    print("\nLoad it in a session with:")
    print("  from user_descriptor import UserDescriptor")
    print(f"  desc = UserDescriptor.load('{DESCRIPTOR_OUT}')")
    print("  cfg = ControllerConfig(arousal_mode='arousal_primary', user_descriptor=desc)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
