"""Installer for test_render_play_integration.py v2 — false-positive underrun fix."""
import base64, gzip, hashlib, sys, shutil
from pathlib import Path

EXPECTED_MD5 = '138e667b9ca078d8be510e052c33c423'
SIZE = 9073
TARGET = Path("groovegen_pilot/test_render_play_integration.py")

BLOB = """
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
kC4Qw9DRLOn2nH9LpKuvFb3B/wC8wGGFcSMAAA==
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
    print("Re-run audible test:")
    print("  python groovegen_pilot/test_render_play_integration.py --audible --sf2 soundfonts/Musyng_Kite.sf2")
    return 0

if __name__ == "__main__":
    sys.exit(main())