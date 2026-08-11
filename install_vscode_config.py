"""Install VS Code workspace config for GrooveGen.

Places three files into <repo>/.vscode/:
  - settings.json     (interpreter, formatter, path config)
  - launch.json       (debug configurations for verify + regression gates)
  - extensions.json   (recommended extensions prompt for VS Code)

Usage:
    python install_vscode_config.py

Prerequisites:
    The three source JSON files must be next to this script:
      vscode_settings.json
      vscode_launch.json
      vscode_extensions.json
"""
from pathlib import Path
import shutil
import sys

REPO = Path("/Users/daniel/Desktop/PhD/groove_gen_project")
HERE = Path(__file__).resolve().parent

sources = {
    "vscode_settings.json": ".vscode/settings.json",
    "vscode_launch.json": ".vscode/launch.json",
    "vscode_extensions.json": ".vscode/extensions.json",
}

if not REPO.exists():
    print(f"ERROR: repo not found: {REPO}")
    sys.exit(1)

(REPO / ".vscode").mkdir(exist_ok=True)

installed = []
missing = []
for src_name, dst_rel in sources.items():
    src = HERE / src_name
    dst = REPO / dst_rel
    if not src.exists():
        missing.append(src_name)
        continue
    if dst.exists():
        backup = dst.with_suffix(dst.suffix + ".bak")
        shutil.copy2(dst, backup)
        print(f"  Existing {dst_rel} backed up to {backup.name}")
    shutil.copy2(src, dst)
    installed.append(dst_rel)

print()
print(f"Installed {len(installed)} config files into {REPO / '.vscode'}:")
for path in installed:
    print(f"  {path}")

if missing:
    print()
    print(f"MISSING source files (were they downloaded to the same folder as this script?):")
    for name in missing:
        print(f"  {name}")
    sys.exit(1)

print()
print("Done. Next steps in VS Code:")
print("  1. Close and reopen the project folder")
print("  2. When prompted, accept 'Install recommended extensions'")
print("  3. Cmd+Shift+P -> 'Python: Select Interpreter' -> pick the .venv one if not auto-picked")
print("  4. F5 to run 'verify_setup.py' in the debugger")
