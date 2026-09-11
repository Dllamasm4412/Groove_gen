"""Deterministic renderer for the frozen 25-cell library.

Bypasses the (currently broken) segment_renderer.py + composer.py legacy path
and calls each cell's generate_{family}_segment() directly with FROZEN_SEEDS.

MIDI is written via music21; WAV is rendered by shelling out to fluidsynth
using the Musyng_Kite.sf2 in the project root.

Usage:
    python freeze_library.py --out renders/frozen
    python freeze_library.py --out renders/frozen_check
    diff -rq renders/frozen renders/frozen_check   # must be empty

Deterministic contract:
    Same FROZEN_SEEDS + same cell code + same fluidsynth version + same SF2
    => byte-identical MIDI and WAV.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from composer.calm_cell import _TIER_DENSITY_FLOOR as CALM_DENS
from composer.calm_cell import _TIER_TEMPO as CALM_TEMPO
from composer.calm_cell import generate_calm_segment
from composer.frozen_seeds import FROZEN_SEEDS
from composer.hiphop_cell import _TIER_DENSITY_FLOOR as HIPHOP_DENS
from composer.hiphop_cell import _TIER_TEMPO as HIPHOP_TEMPO
from composer.hiphop_cell import generate_hiphop_segment
from composer.latin_cell import _TIER_DENSITY_FLOOR as LATIN_DENS
from composer.latin_cell import _TIER_TEMPO as LATIN_TEMPO
from composer.latin_cell import generate_latin_segment
from composer.lofi_cell import _TIER_DENSITY_FLOOR as LOFI_DENS
from composer.lofi_cell import _TIER_TEMPO as LOFI_TEMPO
from composer.lofi_cell import generate_lofi_segment
from composer.pop_cell import _TIER_DENSITY_FLOOR as POP_DENS
from composer.pop_cell import _TIER_TEMPO as POP_TEMPO
from composer.pop_cell import generate_pop_segment
from composer.rnb_cell import _TIER_DENSITY_FLOOR as RNB_DENS
from composer.rnb_cell import _TIER_TEMPO as RNB_TEMPO
from composer.rnb_cell import generate_rnb_segment
from composer.rock_cell import _TIER_DENSITY_FLOOR as ROCK_DENS
from composer.rock_cell import _TIER_TEMPO as ROCK_TEMPO
from composer.rock_cell import generate_rock_segment

FAMILY = {
    "calm": (generate_calm_segment, CALM_TEMPO, CALM_DENS),
    "lofi": (generate_lofi_segment, LOFI_TEMPO, LOFI_DENS),
    "latin": (generate_latin_segment, LATIN_TEMPO, LATIN_DENS),
    "rock": (generate_rock_segment, ROCK_TEMPO, ROCK_DENS),
    "hiphop": (generate_hiphop_segment, HIPHOP_TEMPO, HIPHOP_DENS),
    "pop": (generate_pop_segment, POP_TEMPO, POP_DENS),
    "rnb": (generate_rnb_segment, RNB_TEMPO, RNB_DENS),
}


def render_midi(family: str, tier: int, seed: int, bars: int, out_dir: Path) -> Path:
    gen, tempo_map, density_map = FAMILY[family]
    tempo = tempo_map[tier]
    density = density_map[tier]
    result = gen(
        tempo_bpm=tempo,
        density=density,
        duration_bars=bars,
        seed=seed,
    )
    midi_path = out_dir / f"{family}_t{tier}.mid"
    # Type dispatch: pop cell returns pretty_midi.PrettyMIDI; others return music21.stream.Score.
    if hasattr(result, "instruments"):  # pretty_midi
        result.write(str(midi_path))
    else:  # music21
        result.write("midi", fp=str(midi_path))
    return midi_path


def render_wav(midi_path: Path, sf2_path: Path, sr: int) -> Path:
    wav_path = midi_path.with_suffix(".wav")
    cmd = [
        "fluidsynth",
        "-ni",
        "-F",
        str(wav_path),
        "-r",
        str(sr),
        "-g",
        "0.8",  # gain
        str(sf2_path),
        str(midi_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"fluidsynth failed for {midi_path.name}:\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )
    if not wav_path.exists():
        raise RuntimeError(f"fluidsynth produced no output at {wav_path}")
    return wav_path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--bars", type=int, default=8, help="Bars per cell (default 8)")
    ap.add_argument("--sf2", default="Musyng_Kite.sf2", help="SoundFont path")
    ap.add_argument("--sr", type=int, default=44100, help="Sample rate")
    ap.add_argument("--midi-only", action="store_true", help="Skip WAV rendering")
    args = ap.parse_args()

    if shutil.which("fluidsynth") is None and not args.midi_only:
        print("ERROR: fluidsynth not on PATH. brew install fluid-synth", file=sys.stderr)
        return 1

    sf2_path = Path(args.sf2).resolve()
    if not sf2_path.exists() and not args.midi_only:
        print(f"ERROR: SoundFont not found at {sf2_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    keys = sorted(FROZEN_SEEDS.keys())
    n = len(keys)
    print(f"Rendering {n} cells to {out_dir} (bars={args.bars}, sr={args.sr})")

    failures: list[tuple[str, int, str]] = []
    for i, (family, tier) in enumerate(keys, 1):
        seed = FROZEN_SEEDS[(family, tier)]
        try:
            midi_path = render_midi(family, tier, seed, args.bars, out_dir)
            if args.midi_only:
                print(f"  [{i:2d}/{n}] {family}_t{tier}  seed={seed}  -> {midi_path.name}")
            else:
                wav_path = render_wav(midi_path, sf2_path, args.sr)
                print(
                    f"  [{i:2d}/{n}] {family}_t{tier}  seed={seed}  -> {midi_path.name} + {wav_path.name}"
                )
        except Exception as e:
            print(
                f"  [{i:2d}/{n}] {family}_t{tier}  FAILED: {type(e).__name__}: {e}", file=sys.stderr
            )
            failures.append((family, tier, str(e)))

    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for family, tier, err in failures:
            print(f"  {family} tier {tier}: {err}", file=sys.stderr)
        return 2

    print(f"\nOK: {n}/{n} cells rendered to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
