"""inspect_renderer.py — quick inspection of render_segment signature and SF2 handling.

Run from repo root:
    python inspect_renderer.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path("/Users/daniel/Desktop/PhD/groove_gen_project")
RENDERER = REPO / "groovegen_pilot" / "renderer.py"


def main() -> int:
    if not RENDERER.exists():
        print(f"[FAIL] {RENDERER} not found")
        return 1

    text = RENDERER.read_text()
    lines = text.splitlines()

    print(f"[INFO] Inspecting {RENDERER}")
    print(f"[INFO] Total lines: {len(lines)}")
    print()

    # Find render_segment signature (may span multiple lines).
    print("=" * 60)
    print("render_segment() signature")
    print("=" * 60)
    in_sig = False
    sig_lines: list[str] = []
    for i, line in enumerate(lines, start=1):
        if re.search(r"^def render_segment\b", line):
            in_sig = True
        if in_sig:
            sig_lines.append(f"{i:4d}: {line}")
            if ") -> " in line or line.rstrip().endswith(":"):
                # signature likely ended
                if line.rstrip().endswith(":"):
                    break
    for s in sig_lines:
        print(s)
    print()

    # Find all SF2_DEFAULT / sf2_path / sf2= references.
    print("=" * 60)
    print("SF2 / soundfont references")
    print("=" * 60)
    patterns = [r"SF2_DEFAULT", r"sf2_path", r"sf2=", r"soundfont", r"\.sf2"]
    for i, line in enumerate(lines, start=1):
        if any(re.search(p, line, re.IGNORECASE) for p in patterns):
            print(f"{i:4d}: {line}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
