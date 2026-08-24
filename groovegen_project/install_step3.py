"""
Installer for M0.5 Step 3 files:
  - renderer_to_player.py       (bridge)
  - test_render_play_integration.py (test)

Usage:
    cd /Users/daniel/Desktop/PhD/groove_gen_project/
    python install_step3.py

Backs up existing files to *.bak. Verifies MD5 after write.
"""
import base64, gzip, hashlib, sys, shutil
from pathlib import Path

FILES = [
    ('groovegen_pilot/renderer_to_player.py', '24e96933baba5cbb8aeeea10d8c5d184', 5282,
     """
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
     """),
    ('groovegen_pilot/test_render_play_integration.py', '9852126cf97498b45405de46ca818cd7', 7908,
     """
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
63+/M4HM5B4AAA==
     """),
]

def main() -> int:
    if not Path("groovegen_pilot").is_dir():
        print("ERROR: run from groove_gen_project/ repo root")
        print(f"  cwd: {Path.cwd()}")
        return 1
    for dst, expected_md5, size, blob in FILES:
        data = gzip.decompress(base64.b64decode(blob.strip()))
        got_md5 = hashlib.md5(data).hexdigest()
        if got_md5 != expected_md5:
            print(f"ERROR: MD5 mismatch for {dst}: expected {expected_md5}, got {got_md5}")
            return 1
        p = Path(dst)
        if p.exists():
            bak = Path(str(p) + ".bak")
            bak.write_bytes(p.read_bytes())
            print(f"  backed up {p} -> {bak}")
        p.write_bytes(data)
        print(f"  installed {p} ({size} bytes, MD5 {got_md5})")
    pyc = Path("groovegen_pilot/__pycache__")
    if pyc.exists():
        shutil.rmtree(pyc)
        print(f"  cleared {pyc}")
    print("")
    print("OK. Run headless smoke test:")
    print("  python groovegen_pilot/test_render_play_integration.py --sf2 soundfonts/Musyng_Kite.sf2")
    print("")
    print("Then run audible test to hear all four genres back-to-back:")
    print("  python groovegen_pilot/test_render_play_integration.py --audible --sf2 soundfonts/Musyng_Kite.sf2")
    return 0

if __name__ == "__main__":
    sys.exit(main())