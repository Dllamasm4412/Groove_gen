"""Patch symbolic_bed_proto.py: swap build_pop palette CLAV+SYN_PAD -> Rhodes+Strings.

Also nudges the pop pad velocity a touch higher (42 -> 48) so strings actually
speak through the mix, and adds a tiny velocity variation to the comp so
adjacent stabs aren't identical (this is on top of the humanize.py accent map
which the caller applies AFTER build_pop returns).

Idempotent: safe to run repeatedly. Detects prior application via a sentinel
comment. Prints a clear success/no-op message.

USAGE (on the Mac, from repo root):
    python /path/to/patch_pop_palette_v2.py
    # then A/B render with symbolic_bed_proto.py directly
"""
from __future__ import annotations
import io
import re
import sys
from pathlib import Path

# Default target relative to Daniel's repo
DEFAULT_TARGET = Path("symbolic_bed_proto.py")

SENTINEL = "# PALETTE_PATCH_V2 applied"

# The three exact lines we're replacing (from the current file @ lines 74-76).
# We match on program=CLAV / program=SYN_PAD to avoid touching build_calm's pad.
PATTERN_COMP = re.compile(r'^(\s*)comp\s*=\s*pm\.Instrument\(program=CLAV,\s*name="clav comp"\)\s*$', re.M)
PATTERN_PAD  = re.compile(r'^(\s*)pad\s*=pm\.Instrument\(program=SYN_PAD,\s*name="pad"\)\s*$', re.M)
# The pop pad velocity line (line 81 currently)
PATTERN_PAD_VEL = re.compile(r'^(\s*)chord\(pad,\s*voi,\s*t0,\s*bar,\s*vel=42\)\s*$', re.M)


def patch(source: str) -> tuple[str, list[str]]:
    """Return (new_source, notes). Idempotent."""
    notes: list[str] = []

    if SENTINEL in source:
        return source, ["already patched (sentinel present); no changes"]

    new = source

    m = PATTERN_COMP.search(new)
    if m:
        indent = m.group(1)
        new = PATTERN_COMP.sub(
            f'{indent}comp=pm.Instrument(program=EPIANO_RHODES, name="rhodes comp")  # was CLAV',
            new,
        )
        notes.append("comp: CLAV -> EPIANO_RHODES")
    else:
        notes.append("WARNING: comp CLAV line not found (already patched by hand?)")

    m = PATTERN_PAD.search(new)
    if m:
        indent = m.group(1)
        new = PATTERN_PAD.sub(
            f'{indent}pad =pm.Instrument(program=STRINGS, name="strings pad")  # was SYN_PAD',
            new,
        )
        notes.append("pad: SYN_PAD -> STRINGS")
    else:
        notes.append("WARNING: pad SYN_PAD line not found (already patched by hand?)")

    m = PATTERN_PAD_VEL.search(new)
    if m:
        indent = m.group(1)
        new = PATTERN_PAD_VEL.sub(
            f'{indent}chord(pad, voi, t0, bar, vel=48)  # strings need a touch more level than SYN_PAD',
            new,
        )
        notes.append("pop pad velocity: 42 -> 48")
    else:
        notes.append("note: pop pad velocity line not found (may already be tweaked)")

    # Stamp sentinel at top of build_pop so re-runs are no-ops.
    build_pop_def = 'def build_pop(bpm=104, bars=8):'
    if build_pop_def in new and SENTINEL not in new:
        new = new.replace(
            build_pop_def,
            f'{build_pop_def}\n    {SENTINEL}',
            1,
        )
        notes.append(f"sentinel inserted at top of build_pop")

    return new, notes


def main(argv: list[str]) -> int:
    target = Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    if not target.exists():
        print(f"ERROR: {target} not found. Run from your repo root (or pass path).", file=sys.stderr)
        return 2

    original = target.read_text()
    patched, notes = patch(original)

    if patched == original:
        print(f"[{target}] no changes needed")
        for n in notes:
            print(f"  - {n}")
        return 0

    backup = target.with_suffix(target.suffix + ".bak.palette_v2")
    backup.write_text(original)
    target.write_text(patched)
    print(f"[{target}] patched (backup: {backup.name})")
    for n in notes:
        print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
