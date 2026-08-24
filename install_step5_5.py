"""
install_step5_5.py

Self-installing script that writes the M0.5 Step 5.5 modules into the
GrooveGen repo and runs a smoke test to verify integration.

Run this from ~/Desktop/PhD/groove_gen_project (or wherever the repo lives)
with the venv active:

    cd ~/Desktop/PhD/groove_gen_project
    source .venv/bin/activate
    python install_step5_5.py

It will:
    1. Back up existing files if present (as .bak with timestamp)
    2. Write these modules:
       - ladder.py             (20-cell energy ladder)
       - plant_model.py        (FOPDT plant + population sampler)
       - control.py            (LadderMPC + reference governor + RLS)
       - melody_bank.py        (per-cell seed rotation)
       - simulate.py           (Monte Carlo + CLA metric + CLI)
       - run_session_v2.py     (closed-loop session with controller)
       - test_step5_5.py       (full-stack smoke test)
    3. Ensure hr_trace_ramp_60_110_90.csv exists (creates a fresh one
       if missing)
    4. Ensure numpy + a few stdlib imports work
    5. Run: python test_step5_5.py

Does NOT touch:
    - composer.py             (already at v1.2, MD5 00320e632...)
    - crossfade.py            (Step 5.5a uses fade_bars=0.25 at construction)
    - segment_renderer.py, hr_sources.py, player.py, renderer_to_player.py,
      hr_to_tier.py, run_session.py (v1 kept as fallback)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Module contents live in this workspace next to install_step5_5.py.
# The installer just copies them.
# ---------------------------------------------------------------------------

MODULES = [
    'ladder.py',
    'plant_model.py',
    'control.py',
    'melody_bank.py',
    'simulate.py',
    'run_session_v2.py',
    'test_step5_5.py',
]

WORKSPACE = Path(__file__).parent.resolve()


def _backup_if_exists(dest: Path) -> None:
    if dest.exists():
        ts = time.strftime('%Y%m%d_%H%M%S')
        bak = dest.with_suffix(dest.suffix + f'.bak_{ts}')
        shutil.copy2(dest, bak)
        print(f'  backup: {dest.name} -> {bak.name}')


def _install_here(target_dir: Path) -> None:
    for mod in MODULES:
        src = WORKSPACE / mod
        if not src.exists():
            print(f'  SKIP {mod} (not in workspace)')
            continue
        dest = target_dir / mod
        _backup_if_exists(dest)
        shutil.copy2(src, dest)
        print(f'  wrote {mod}')


def _ensure_hr_csv(target_dir: Path) -> None:
    csv = target_dir / 'hr_trace_ramp_60_110_90.csv'
    if csv.exists():
        print(f'  hr_trace_ramp_60_110_90.csv already present')
        return
    print(f'  writing hr_trace_ramp_60_110_90.csv (fresh 5-min ramp)')
    with open(csv, 'w') as fh:
        fh.write('t_s,bpm\n')
        # 5-min ramp: 60 -> 110 (2 min) -> 80 (3 min), 1 Hz
        for t in range(0, 300):
            if t <= 120:
                bpm = 60.0 + (110.0 - 60.0) * (t / 120.0)
            else:
                bpm = 110.0 - (110.0 - 80.0) * ((t - 120) / 180.0)
            fh.write(f'{t},{bpm:.2f}\n')


def _run_smoke_test(target_dir: Path) -> int:
    print()
    print('=' * 60)
    print('Running smoke test...')
    print('=' * 60)
    env = os.environ.copy()
    env['PYTHONPATH'] = str(target_dir) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run(
        [sys.executable, str(target_dir / 'test_step5_5.py')],
        cwd=str(target_dir),
        env=env,
    )
    return proc.returncode


def main() -> None:
    print('=' * 60)
    print('GrooveGen M0.5 Step 5.5 installer')
    print('=' * 60)

    # Determine target dir:
    # 1. If a positional arg is given, use it.
    # 2. Else if we're in the workspace, install into cwd of the invoker
    #    (assumed to be the repo root).
    if len(sys.argv) > 1:
        target = Path(sys.argv[1]).expanduser().resolve()
    else:
        target = Path.cwd()

    if not target.exists():
        print(f'ERROR: target directory does not exist: {target}')
        sys.exit(1)

    print(f'Target repo: {target}')
    print()

    # Sanity: check we're not overwriting production composer.py etc.
    for critical in ('composer.py', 'crossfade.py', 'segment_renderer.py',
                     'hr_sources.py', 'player.py', 'renderer_to_player.py'):
        if not (target / critical).exists():
            print(f'  WARN: missing critical dep {critical} in target -- '
                  f'you may need to run install_composer_v12.py / step3 / step4 '
                  f'first, or copy them from workspace')

    print()
    print('Writing Step 5.5 modules...')
    _install_here(target)
    _ensure_hr_csv(target)

    # Run smoke test
    rc = _run_smoke_test(target)
    if rc != 0:
        print()
        print(f'SMOKE TEST FAILED (exit {rc})')
        print('The modules were installed but did not run end-to-end.')
        print('Check that numpy is installed and the critical deps above exist.')
        sys.exit(rc)

    print()
    print('=' * 60)
    print('INSTALL + SMOKE TEST OK')
    print('=' * 60)
    print()
    print('Next steps you may want to try:')
    print(f'  python simulate.py --n 200 --target-mode authority')
    print(f'    -> validates controller against 200-subject Monte Carlo')
    print(f'  python test_step5_5.py')
    print(f'    -> re-runs the smoke test')
    print()
    print('Note: In the smoke test, HR comes from a replayed CSV that is')
    print('NOT causally driven by the audio, so g_hat drifts to whatever')
    print('the recorded ramp implies. In a real session (or the Monte Carlo)')
    print('g_hat converges toward the true subject gain -- see:')
    print('  python simulate.py --n 100 --target-mode authority')


if __name__ == '__main__':
    main()
