"""inspect_pop_palette.py — verify pop-palette wiring before we patch it.

Two questions:
1. What symbols exist in symbolic_bed_proto.py that we can use?
   (AC_PIANO, EPIANO_RHODES, STRINGS, etc.)
2. How does renderer.py actually USE the pop dict palette? Does it read
   comp/bass/pad by name, or something else?
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path("/Users/daniel/Desktop/PhD/groove_gen_project")


def scan_constants() -> None:
    path = REPO / "symbolic_bed_proto.py"
    print("=" * 70)
    print(f"CONSTANTS in {path.name} (top of file, all GM program symbols)")
    print("=" * 70)
    text = path.read_text()
    for i, line in enumerate(text.splitlines(), start=1):
        # Look for CONSTANT = <digit>
        if re.match(r"^[A-Z][A-Z_0-9]*\s*=\s*\d+", line):
            print(f"  {i:4d}: {line}")
        # Also lines with multiple constants on one line
        elif re.search(r"[A-Z][A-Z_0-9]+\s*=\s*\d+;\s*[A-Z]", line):
            print(f"  {i:4d}: {line}")


def scan_palette_usage() -> None:
    path = REPO / "groovegen_pilot" / "renderer.py"
    print()
    print("=" * 70)
    print(f"PALETTE USAGE in {path.name}")
    print("=" * 70)
    text = path.read_text()
    lines = text.splitlines()

    # Find the whole GENRE_PROGRAMS or similar dict block and any reads of it.
    in_dict = False
    for i, line in enumerate(lines, start=1):
        # Print any line containing 'comp', 'bass', 'pad' near a genre key
        if re.search(r"comp\s*=|bass\s*=|pad\s*=", line):
            print(f"  {i:4d}: {line}")
        elif re.search(r"\[.comp.\]|\[.bass.\]|\[.pad.\]", line):
            print(f"  {i:4d}: {line}")
        elif re.search(r"GENRE_PROGRAMS|genre_programs|PROGRAMS_BY_GENRE", line):
            print(f"  {i:4d}: {line}")


def scan_build_pop_signature() -> None:
    """build_pop is what actually consumes the palette. See what it expects."""
    path = REPO / "symbolic_bed_proto.py"
    print()
    print("=" * 70)
    print(f"build_pop() and neighbors in {path.name}")
    print("=" * 70)
    text = path.read_text()
    lines = text.splitlines()
    # Print any 'def build_' function signature + a few lines.
    for i, line in enumerate(lines, start=1):
        if re.search(r"^def build_", line):
            # Print signature + next 8 lines to see how it uses programs.
            for j in range(i - 1, min(i + 8, len(lines))):
                print(f"  {j+1:4d}: {lines[j]}")
            print()


def main() -> int:
    scan_constants()
    scan_palette_usage()
    scan_build_pop_signature()
    return 0


if __name__ == "__main__":
    sys.exit(main())
