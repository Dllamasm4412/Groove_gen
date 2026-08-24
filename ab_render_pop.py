"""A/B/C render for GrooveGen Days 1-2 evaluation.

Renders three variants of the pop bed to WAV so the ear can judge whether the
palette + humanization pass measurably fixes the "still sounds 80s" complaint:

    A. BASELINE      -- current build_pop as-is (CLAV comp + SYN_PAD, no humanize)
    B. PALETTE ONLY  -- Rhodes comp + Strings pad, still uniform velocities
    C. FULL          -- Palette + deterministic humanization (accents+jitter+swing)

All three render through the SAME soundfont (Musyng Kite by default; override
with --sf2). This isolates composition/arrangement/velocity changes from
soundfont differences.

USAGE (on the Mac, from repo root, venv activated):
    python /path/to/ab_render_pop.py                # Musyng Kite default
    python /path/to/ab_render_pop.py --sf2 soundfonts/Musyng_Kite.sf2
    python /path/to/ab_render_pop.py --sf2 /usr/local/share/soundfonts/FluidR3_GM.sf2
    python /path/to/ab_render_pop.py --bars 8 --out /tmp/ab_pop
    python /path/to/ab_render_pop.py --seed 42     # humanization seed

Outputs to --out directory (default: symbolic_out/ab_pop):
    pop_A_baseline.wav
    pop_A_baseline.mid
    pop_B_palette.wav
    pop_B_palette.mid
    pop_C_full.wav
    pop_C_full.mid
    ab_summary.json        # per-variant note counts, humanize summary

Requires humanize.py and symbolic_bed_proto.py importable from CWD or PYTHONPATH.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path


def _import_bed():
    """Import symbolic_bed_proto without executing its __main__ block."""
    try:
        import symbolic_bed_proto as bed  # noqa: F401
        return bed
    except ModuleNotFoundError as e:
        print(f"ERROR: could not import symbolic_bed_proto ({e}).", file=sys.stderr)
        print("Run this script from your GrooveGen repo root, or add it to PYTHONPATH.", file=sys.stderr)
        sys.exit(2)


def _import_humanize():
    try:
        import humanize as hz
        return hz
    except ModuleNotFoundError as e:
        print(f"ERROR: could not import humanize ({e}).", file=sys.stderr)
        print("Drop humanize.py next to symbolic_bed_proto.py, then rerun.", file=sys.stderr)
        sys.exit(2)


def build_baseline(bed, bpm: int, bars: int):
    """Build the pop bed with the ORIGINAL CLAV+SYN_PAD palette, regardless of
    whether the file has been patched. We do this by monkey-injecting the
    program numbers into a local build_pop copy that references the module's
    GM constants."""
    import pretty_midi as pm
    spb = 60.0 / bpm
    bar = spb * 4
    m = pm.PrettyMIDI(initial_tempo=bpm)
    comp = pm.Instrument(program=bed.CLAV, name="clav comp")
    bass = pm.Instrument(program=bed.FINGER_BASS, name="bass")
    pad = pm.Instrument(program=bed.SYN_PAD, name="pad")
    prog = [([60, 64, 67], 48), ([55, 59, 62], 43), ([57, 60, 64], 45), ([53, 57, 60], 41)]
    comp_off = [0.5, 1.0, 1.5, 2.5, 3.0, 3.5]
    for b in range(bars):
        t0 = b * bar
        voi, root = prog[b % 4]
        bed.chord(pad, voi, t0, bar, vel=42)
        for off in comp_off:
            bed.chord(comp, [v + 12 for v in voi], t0 + off * spb, spb * 0.35, vel=70)
        for beat in range(4):
            bed.note(bass, root - 12, t0 + beat * spb, spb * 0.5, vel=88)
        bed.note(bass, root - 12 + 7, t0 + 3.5 * spb, spb * 0.4, vel=80)
    for i in (pad, comp, bass):
        m.instruments.append(i)
    return m


def build_palette(bed, bpm: int, bars: int):
    """Build with the patched palette (Rhodes+Strings, vel=48 on strings),
    still uniform velocities (no humanize)."""
    import pretty_midi as pm
    spb = 60.0 / bpm
    bar = spb * 4
    m = pm.PrettyMIDI(initial_tempo=bpm)
    comp = pm.Instrument(program=bed.EPIANO_RHODES, name="rhodes comp")
    bass = pm.Instrument(program=bed.FINGER_BASS, name="bass")
    pad = pm.Instrument(program=bed.STRINGS, name="strings pad")
    prog = [([60, 64, 67], 48), ([55, 59, 62], 43), ([57, 60, 64], 45), ([53, 57, 60], 41)]
    comp_off = [0.5, 1.0, 1.5, 2.5, 3.0, 3.5]
    for b in range(bars):
        t0 = b * bar
        voi, root = prog[b % 4]
        bed.chord(pad, voi, t0, bar, vel=48)
        for off in comp_off:
            bed.chord(comp, [v + 12 for v in voi], t0 + off * spb, spb * 0.35, vel=70)
        for beat in range(4):
            bed.note(bass, root - 12, t0 + beat * spb, spb * 0.5, vel=88)
        bed.note(bass, root - 12 + 7, t0 + 3.5 * spb, spb * 0.4, vel=80)
    for i in (pad, comp, bass):
        m.instruments.append(i)
    return m


def _note_count(midi) -> int:
    return sum(len(i.notes) for i in midi.instruments)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf2", default="soundfonts/Musyng_Kite.sf2",
                    help="Soundfont path (default: soundfonts/Musyng_Kite.sf2)")
    ap.add_argument("--bpm", type=int, default=104)
    ap.add_argument("--bars", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="symbolic_out/ab_pop")
    args = ap.parse_args()

    if not Path(args.sf2).exists():
        print(f"ERROR: soundfont not found at {args.sf2}", file=sys.stderr)
        return 2

    bed = _import_bed()
    hz = _import_humanize()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    variants = {
        "A_baseline": build_baseline(bed, args.bpm, args.bars),
        "B_palette":  build_palette(bed, args.bpm, args.bars),
        "C_full":     build_palette(bed, args.bpm, args.bars),
    }

    summary = {"seed": args.seed, "bpm": args.bpm, "bars": args.bars,
               "sf2": str(Path(args.sf2).resolve()), "variants": {}}

    # Apply humanization to variant C only.
    hz_summary = hz.humanize(variants["C_full"], seed=args.seed, params=hz.HumanizeParams.POP())

    for name, midi in variants.items():
        mid_path = out_dir / f"pop_{name}.mid"
        wav_path = out_dir / f"pop_{name}.wav"
        midi.write(str(mid_path))
        raw = bed.render_midi(midi, str(wav_path), sf2=args.sf2)
        if not raw:
            print(f"[{name}] fluidsynth failed", file=sys.stderr)
            continue
        # Polish with the same params for fair comparison (normalize=True is fine
        # for standalone A/B listening; we do NOT chain into the segment pipeline here).
        pol = bed.polish(raw, str(wav_path))
        summary["variants"][name] = {
            "mid": str(mid_path),
            "wav": str(wav_path),
            "notes": _note_count(midi),
            "instruments": [i.name for i in midi.instruments],
        }
        # Cleanup the intermediate _raw.wav that render_midi writes alongside
        raw_path = Path(raw)
        if raw_path.exists() and raw_path != Path(wav_path):
            try:
                raw_path.unlink()
            except Exception:
                pass
        print(f"[{name}] rendered -> {wav_path.name}  ({summary['variants'][name]['notes']} notes)")

    summary["variants"]["C_full"]["humanize"] = hz_summary

    with open(out_dir / "ab_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\nA/B/C summary -> {out_dir / 'ab_summary.json'}")
    print(f"\nListen in order: A -> B -> C. Note whether:")
    print(f"  * A -> B: the palette change alone removes the CLAV/SYN_PAD 80s signature")
    print(f"  * B -> C: humanization adds perceptible 'breath' vs mechanical stab uniformity")
    return 0


if __name__ == "__main__":
    sys.exit(main())
