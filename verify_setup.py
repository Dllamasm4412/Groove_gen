#!/usr/bin/env python3
"""Verify the local GrooveGen setup for M1 readiness."""

from __future__ import annotations

import importlib
import importlib.metadata as importlib_metadata
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import sounddevice  # type: ignore
except Exception:  # pragma: no cover - optional import path
    sounddevice = None

ROOT = Path(__file__).resolve().parent
SOUNDFONT_PATH = ROOT / "soundfonts" / "GeneralUser_GS_v1.471.sf2"
SOUNDFONT_URL = "https://www.schristiancollins.com/generaluser.php"
REGRESSION_COMMANDS = [
    [sys.executable, "groovegen_pilot/hr_trajectory.py"],
    [sys.executable, "groovegen_pilot/test_faults_fixed.py"],
    [sys.executable, "groovegen_project/groovegen/pd_controller.py"],
    [sys.executable, "groovegen_pilot/tier_mapping.py"],
    [sys.executable, "groovegen_pilot/scene.py"],
]


def colorize(text: str, ok: bool, pending: bool = False) -> str:
    """Return ANSI-colored text for the console."""
    if pending:
        return f"\033[33m{text}\033[0m"
    return f"\033[32m{text}\033[0m" if ok else f"\033[31m{text}\033[0m"


def print_section(title: str) -> None:
    """Print a section header."""
    print(f"\n{title}")
    print("-" * len(title))


def check_python_version() -> Tuple[bool, str]:
    """Check that Python is 3.12.x."""
    version = sys.version.split()[0]
    ok = bool(re.match(r"3\.12\.\d+", version))
    return ok, f"Detected Python {version}"


def check_venv() -> Tuple[bool, str]:
    """Check that the process is running inside a virtual environment."""
    ok = sys.prefix != sys.base_prefix
    venv_path = sys.prefix
    return ok, f"Venv path: {venv_path}"


def check_fluidsynth() -> Tuple[bool, str]:
    """Check for the Fluidsynth binary and capture its version."""
    path = shutil.which("fluidsynth")
    if not path:
        return False, "fluidsynth binary not found"
    try:
        result = subprocess.run(
            ["fluidsynth", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return False, f"fluidsynth version probe failed: {exc}"

    version_text = "unknown"
    if result.stdout:
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", result.stdout)
        if match:
            version_text = match.group(1)
    elif result.stderr:
        match = re.search(r"(\d+\.\d+(?:\.\d+)?)", result.stderr)
        if match:
            version_text = match.group(1)
    return True, f"Path: {path}; version: {version_text}"


def check_soundfont() -> Tuple[bool, bool, str]:
    """Check for the required SoundFont file, but treat it as pending if missing."""
    if SOUNDFONT_PATH.exists():
        return True, False, f"Found {SOUNDFONT_PATH}"
    return False, True, f"Missing; download from {SOUNDFONT_URL}"


def check_python_packages() -> Tuple[List[str], List[str]]:
    """Import required Python packages and report their versions."""
    successes: List[str] = []
    failures: List[str] = []
    packages = [
        ("pretty_midi", "pretty_midi"),
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("scipy", "scipy"),
        ("sounddevice", "sounddevice"),
        ("bleak", "bleak"),
        ("fluidsynth", "pyfluidsynth"),
    ]

    for module_name, package_name in packages:
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: import failed ({exc})")
            continue

        version: Optional[str] = None
        try:
            version = importlib_metadata.version(package_name)
        except Exception:
            version = getattr(module, "__version__", None)

        if version:
            successes.append(f"{module_name}: {version}")
        else:
            successes.append(f"{module_name}: imported")

    return successes, failures


def check_audio_devices() -> Tuple[bool, List[str]]:
    """Query output-capable audio devices without opening a stream."""
    if sounddevice is None:
        return False, ["sounddevice import failed"]

    try:
        devices = sounddevice.query_devices()
    except Exception as exc:
        return False, [f"audio device query failed: {exc}"]

    lines: List[str] = []
    for device in devices:
        if isinstance(device, dict):
            name = device.get("name", "unknown")
            max_output_channels = device.get("max_output_channels", 0)
            sample_rate = device.get("default_samplerate", "unknown")
        else:
            name = getattr(device, "name", "unknown")
            max_output_channels = getattr(device, "max_output_channels", 0)
            sample_rate = getattr(device, "default_samplerate", "unknown")

        if int(max_output_channels or 0) > 0:
            lines.append(f"{name}: sample rate {sample_rate}")

    if not lines:
        return False, ["no output-capable devices detected"]
    return True, lines


def run_regression_gate(command: List[str], label: str) -> Tuple[bool, str]:
    """Run a single regression gate and capture diagnostics."""
    try:
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "timed out after 30s"
    except Exception as exc:
        return False, f"launch failed: {exc}"

    if completed.returncode == 0:
        return True, "passed"

    stderr_tail = "\n".join((completed.stderr or "").splitlines()[-20:])
    if stderr_tail:
        return False, f"exit code {completed.returncode}\n{stderr_tail}"
    return False, f"exit code {completed.returncode}"


def render_box(title: str, ok: bool) -> None:
    """Print a simple ANSI-colored box for the final summary."""
    if ok:
        color = "\033[32m"
    else:
        color = "\033[31m"
    reset = "\033[0m"
    border = "+" + "-" * (len(title) + 2) + "+"
    print(color + border + reset)
    print(color + f"| {title} |" + reset)
    print(color + border + reset)


def main() -> int:
    """Run all verification checks and print a final status summary."""
    failures: List[str] = []
    pending: List[str] = []

    print_section("1. Python version check")
    ok, message = check_python_version()
    print(colorize("PASS" if ok else "FAIL", ok) + f": {message}")
    if not ok:
        failures.append("Python version is not 3.12.x")

    print_section("2. Venv sanity")
    ok, message = check_venv()
    print(colorize("PASS" if ok else "FAIL", ok) + f": {message}")
    if not ok:
        failures.append("Not running inside a virtual environment")

    print_section("3. FluidSynth binary check")
    ok, message = check_fluidsynth()
    print(colorize("PASS" if ok else "FAIL", ok) + f": {message}")
    if not ok:
        failures.append("Fluidsynth binary check failed")

    print_section("4. SoundFont check")
    ok, pending_flag, message = check_soundfont()
    if pending_flag:
        print(colorize("PENDING", True, pending=True) + f": {message}")
        pending.append("SoundFont missing; manual download pending")
    else:
        print(colorize("PASS", ok) + f": {message}")
        if not ok:
            failures.append("SoundFont check failed")

    print_section("5. Python package import check")
    successes, import_failures = check_python_packages()
    for item in successes:
        print(colorize("PASS", True) + f": {item}")
    for item in import_failures:
        print(colorize("FAIL", False) + f": {item}")
        failures.append(item)

    print_section("6. Audio output devices")
    ok, device_lines = check_audio_devices()
    if ok:
        print(colorize("PASS", True) + ": output-capable devices")
        for line in device_lines:
            print(f"  - {line}")
    else:
        print(colorize("FAIL", False) + f": {device_lines[0]}")
        failures.append("Audio device query failed")

    print_section("7. Regression gates")
    for index, command in enumerate(REGRESSION_COMMANDS, start=1):
        label = command[-1]
        ok, detail = run_regression_gate(command, label)
        marker = colorize("PASS", ok) if ok else colorize("FAIL", False)
        print(f"{marker}: {label}")
        if not ok:
            failures.append(f"{label}: {detail}")
            if detail:
                print(f"  diagnosis: {detail}")

    print_section("8. Final summary")
    if not failures:
        render_box("READY FOR M1", True)
        return 0

    render_box("NOT READY", False)
    for index, failure in enumerate(failures, start=1):
        print(f"{index}. {failure}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
