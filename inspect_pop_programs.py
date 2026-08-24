"""inspect_pop_programs.py — find what GM program numbers the pop builder emits.

The 'sounds 80s' complaint is likely because the pop builder is emitting
GM synth-lead/synth-pad programs (60-95 range). Real pop uses piano (0-7),
electric piano (4-7), bass (32-39). This script reveals which.

Run from repo root:
    python inspect_pop_programs.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

REPO = Path("/Users/daniel/Desktop/PhD/groove_gen_project")

# Files most likely to contain pop program choices.
TARGETS = [
    REPO / "groovegen_pilot" / "symbolic_bed_proto.py",
    REPO / "symbolic_bed_proto.py",
    REPO / "groovegen_pilot" / "genre_styles.py",
    REPO / "genre_styles.py",
    REPO / "pop_variety_lib.py",
    REPO / "style_packs.py",
    REPO / "groovegen_pilot" / "renderer.py",
]

# GM program-number lookup for the ranges we care about most.
GM_FAMILIES = {
    (0, 7): "Piano family (0=Acoustic Grand, 4=E.Piano 1, 5=E.Piano 2)",
    (8, 15): "Chromatic percussion (Celesta, Vibraphone, Marimba)",
    (16, 23): "Organ family (Hammond etc.)",
    (24, 31): "Guitar family (24=Nylon, 25=Steel, 27=Clean Electric)",
    (32, 39): "Bass family (32=Acoustic, 33=Fingered E.Bass, 34=Picked E.Bass, 38=Synth Bass 1)",
    (40, 47): "Strings",
    (48, 55): "Ensemble (48=Strings, 50=Synth Strings 1, 52=Choir Aahs)",
    (56, 63): "Brass",
    (64, 71): "Reed",
    (72, 79): "Pipe",
    (80, 87): "Synth Lead (80=Square, 81=Saw, 82=Calliope) — CLASSIC 80s",
    (88, 95): "Synth Pad (88=New Age, 89=Warm, 90=Polysynth, 91=Choir) — CLASSIC 80s",
    (96, 103): "Synth Effects",
}


def classify(pn: int) -> str:
    for (lo, hi), name in GM_FAMILIES.items():
        if lo <= pn <= hi:
            return name
    return "unknown"


def scan_file(path: Path) -> None:
    if not path.exists():
        return
    print(f"\n{'=' * 70}")
    print(f"FILE: {path}")
    print("=" * 70)

    text = path.read_text()
    lines = text.splitlines()

    # Look for GM program assignments and instrument names.
    patterns = [
        (r"program\s*=\s*(\d+)", "program="),
        (r"\.program\s*=\s*(\d+)", ".program="),
        (r"program_change\s*\(\s*(\d+)", "program_change("),
        (r"instrument\s*=\s*(\d+)", "instrument="),
        (r"gm_program\s*=\s*(\d+)", "gm_program="),
        (r"\bpop\b", "'pop' keyword"),
        (r"synth[_ ]?pad|synth[_ ]?lead|warm[_ ]?pad|square[_ ]?lead", "synth-family instrument name"),
        (r"\bpiano\b|electric[_ ]?piano|e[_ ]?piano|\brhodes\b", "piano-family instrument name"),
    ]

    found_any = False
    for i, line in enumerate(lines, start=1):
        line_stripped = line.strip()
        # Skip pure comment/docstring lines? Actually include them, might reveal intent.
        for pat, label in patterns:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                found_any = True
                extra = ""
                if m.groups():
                    try:
                        pn = int(m.group(1))
                        extra = f"  <-- GM {pn}: {classify(pn)}"
                    except ValueError:
                        pass
                print(f"  {i:4d} [{label}]: {line_stripped}{extra}")
                break  # avoid double-printing when multiple patterns match

    if not found_any:
        print("  (no program-number or instrument-name references found)")


def main() -> int:
    print("Scanning pop-related files for GM program numbers and instrument names")
    for t in TARGETS:
        scan_file(t)
    print()
    print("=" * 70)
    print("Reference — GM program families:")
    for (lo, hi), name in GM_FAMILIES.items():
        print(f"  {lo:3d}-{hi:3d}: {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
