"""Installer for crossfade.py v2 — half-bar default (fade_bars=0.5)."""
import base64, gzip, hashlib, sys, shutil
from pathlib import Path

EXPECTED_MD5 = '4834ab679df3cf7d5ef4488f6d000435'
SIZE = 16018
TARGET = Path("groovegen_pilot/crossfade.py")

BLOB = """
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
"""

def main() -> int:
    if not Path("groovegen_pilot").is_dir():
        print("ERROR: run from groove_gen_project/ repo root")
        return 1
    data = gzip.decompress(base64.b64decode(BLOB.strip()))
    got = hashlib.md5(data).hexdigest()
    if got != EXPECTED_MD5:
        print(f"ERROR: MD5 mismatch: expected {EXPECTED_MD5}, got {got}")
        return 1
    if TARGET.exists():
        bak = Path(str(TARGET) + ".bak")
        bak.write_bytes(TARGET.read_bytes())
        print(f"  backed up {TARGET} -> {bak}")
    TARGET.write_bytes(data)
    print(f"  installed {TARGET} ({SIZE} bytes, MD5 {got})")
    pyc = Path("groovegen_pilot/__pycache__")
    if pyc.exists():
        shutil.rmtree(pyc)
        print(f"  cleared {pyc}")
    print("")
    print("New default: half-bar crossfade")
    print("  calm(65)->pop(118): 1.85s (was 3.69s)")
    print("  pop(118)->rnb(100): 1.02s (was 2.03s)")
    print("  rnb(100)->latin(104): 1.20s (was 2.40s)")
    print("")
    print("Optional: hear it once more to sanity-check the shorter fade:")
    print("  python groovegen_pilot/test_crossfade_integration.py --audible --sf2 soundfonts/Musyng_Kite.sf2")
    return 0

if __name__ == "__main__":
    sys.exit(main())