"""
Offline closed-loop session with real FluidSynth audio and a scripted HR
trajectory (engineering only; no PPG, no hardware, no playback;
LIVE_GENERATION_PLAN.md section 6.18).

Runs run_session_v2 exactly as run_pilot_zero wires it with its default flags
(live ladder from run_pilot_zero.build_live_ladder, --ladder measured by default
or ear / prior, LadderMPC, SessionConfigV2 with 1 Hz HR polls and
stale_hr_policy='hold', CrossfadeMixer tail_out, SymbolicSegmentRenderer
session_seed=42) and --generator bank | v2a | v2c. The player is a NullPlayer
that keeps every enqueued block, so the WAV is the stream the live player
would have been given.

The HR is a fixed function of session time (SCRIPTED_HR); it does not respond
to the music and is not a physiological model. --hr plant instead drives a
synthetic first-order HR from the chosen cell's energy, to exercise up / down
movement and both saturations (engineering only; not a model of any person). The session runs on a fake
clock that advances --clock-render-s per render, so the trace and WAV are
deterministic; the real compose and FluidSynth times are measured separately
(timing.csv) and compared with SessionConfigV2.render_lead_s: the loop wakes
render_lead_s before the queue runs dry, so a segment whose compose + render
takes longer than that would leave a gap live.

Usage (writes only under renders/, which is gitignored):
    python simulate_session_v2.py --sf2 ../soundfonts/Musyng_Kite.sf2 --generator v2c
    python simulate_session_v2.py --sf2 ... --generator bank --no-wav
    python simulate_session_v2.py --sf2 ... --sweep 3    # every live cell x 3 visits, timing only
Outputs in <out> (default renders/integration_v2/<stamp>_<generator>/):
    session.wav  session_trace.csv  timing.csv  manifest.json  LISTENING_NOTES.md
    timing_sweep.csv (--sweep)
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Optional

import numpy as np

from hr_sources import HRReading

HERE = Path(__file__).resolve().parent
BASELINE_BPM = 72.0
PHASES = 'up:10:6,down:-4:6'
STALE = (450.0, 470.0)              # seconds with no HR (exercises stale_hold)
PROVENANCE_FILES = ('run_session_v2.py', 'run_pilot_zero.py', 'session_generator.py', 'segment_renderer.py',
                    'control.py', 'ladder.py', 'energy_table_v1.json', 'composer/arrangement.py',
                    'composer/develop_engine.py', 'composer/motif.py', 'composer/dev_calm.py',
                    'composer/dev_lofi.py', 'composer/dev_rnb.py', 'composer/dev_pop.py',
                    'composer/dev_latin.py', 'simulate_session_v2.py')


def SCRIPTED_HR(t: float) -> Optional[float]:
    """Baseline 72; up to 80 by 4 min and 82 by 6 min, down to 69 by 10 min, a
    1.2 bpm 53 s wobble, no reading during STALE."""
    if STALE[0] <= t < STALE[1]:
        return None
    knots = ((0, 72.0), (60, 72.0), (240, 80.0), (360, 82.0), (600, 69.0), (1e9, 69.0))
    for (t0, h0), (t1, h1) in zip(knots, knots[1:]):
        if t < t1:
            return h0 + (h1 - h0) * (t - t0) / (t1 - t0) + 1.2 * math.sin(2 * math.pi * t / 53.0)
    return None


def live_args(extra: tuple = ()) -> argparse.Namespace:
    """run_pilot_zero's flags at their defaults."""
    import run_pilot_zero as rpz

    argv, sys.argv = sys.argv, ['run_pilot_zero.py', '--sf2', 'unused.sf2', *extra]
    try:
        return rpz.parse_args()
    finally:
        sys.argv = argv


def live_stack(ladder_mode: str = 'measured'):
    """(ladder, controller, energy table sha256, ear order sha256) as
    run_pilot_zero builds them (build_live_ladder, live_rotation_band_u) with
    its default flags and --ladder ladder_mode."""
    import run_pilot_zero as rpz
    from control import ControllerConfig, LadderMPC

    args = live_args(('--ladder', ladder_mode))
    ladder, sha, ear_sha = rpz.build_live_ladder(args)
    controller = LadderMPC(ladder, ControllerConfig(
        max_step_per_segment=args.max_step_per_segment, saturation_rotation=args.saturation_rotation,
        rotation_band_u=rpz.live_rotation_band_u(args, ladder), target_relaxation=args.target_relaxation,
        max_du_per_segment=args.max_du_per_segment))
    return ladder, controller, sha, ear_sha


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += max(float(s), 0.0)

    def time(self):
        return 1.7e9 + self.t

    def perf(self):
        return self.t


class ScriptedHRSource:
    def __init__(self, clock, fn=SCRIPTED_HR):
        self.clock, self.fn = clock, fn

    def read(self):
        bpm = self.fn(self.clock.perf())
        return None if bpm is None else HRReading(self.clock.time(), float(bpm), 'scripted', True)


class PlantHRSource:
    """Synthetic first-order HR that follows the energy u of the cell the
    controller chose (engineering only: exercises up / down movement and both
    saturations; not a model of any person, not efficacy evidence). The input
    is the latest decision made at least PLANT_LEAD_S earlier (a decision
    precedes its bars by about render_lead_s)."""

    PLANT_LEAD_S = 3.0

    def __init__(self, clock, ladder, initial_rung, k_bpm, tau_s=60.0, noise_bpm=0.3, seed=7):
        import random

        self.clock, self.ladder, self.k, self.tau = clock, ladder, k_bpm, tau_s
        self.decisions = [(-1e9, ladder.by_rung[initial_rung].u)]
        self.hr, self.t, self.noise, self.rng = BASELINE_BPM, 0.0, noise_bpm, random.Random(seed)

    def wrap(self, controller):
        step = controller.step

        def recorded(*a, **kw):
            d = step(*a, **kw)
            self.decisions.append((self.clock.perf(), self.ladder.by_rung[d.next_rung].u))
            return d
        controller.step = recorded
        return controller

    def _u(self, t):
        return [u for td, u in self.decisions if td <= t - self.PLANT_LEAD_S][-1]

    def read(self):
        now = self.clock.perf()
        while self.t < now:
            dt = min(1.0, now - self.t)
            self.t += dt
            target = BASELINE_BPM + self.k * self._u(self.t)
            self.hr += (1.0 - math.exp(-dt / self.tau)) * (target - self.hr)
        return HRReading(self.clock.time(), self.hr + self.rng.gauss(0.0, self.noise), 'plant', True)


class TimedRenderer:
    """The real renderer; records each render's wall time and advances the fake clock
    by a fixed amount instead."""

    def __init__(self, renderer, clock, clock_render_s):
        self.r, self.clock, self.cost, self.times = renderer, clock, clock_render_s, []

    def _timed(self, fn, *a, **k):
        t0 = time.perf_counter()
        out = fn(*a, **k)
        self.times.append(time.perf_counter() - t0)
        self.clock.sleep(self.cost)
        return out

    def render_pm(self, pm):
        return self._timed(self.r.render_pm, pm)

    def render_segment(self, **kw):
        return self._timed(self.r.render_segment, **kw)


class TimedSource:
    """SessionSegmentSource wrapper that records the compose wall time."""

    def __init__(self, source):
        self.s, self.times = source, []

    def next_segment(self, genre, tier):
        t0 = time.perf_counter()
        out = self.s.next_segment(genre, tier)
        self.times.append(time.perf_counter() - t0)
        return out


def capture_player(sample_rate):
    from player import NullPlayer

    class CapturePlayer(NullPlayer):
        def __init__(self):
            super().__init__(sample_rate=sample_rate)
            self.blocks = []

        def enqueue(self, audio):
            super().enqueue(audio)
            self.blocks.append(np.array(audio, dtype=np.float32))

    return CapturePlayer()


def _sha(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def _git() -> dict[str, Any]:
    def run(*a):
        return subprocess.run(['git', *a], cwd=HERE, capture_output=True, text=True).stdout.strip()
    return {'head': run('rev-parse', 'HEAD'), 'branch': run('rev-parse', '--abbrev-ref', 'HEAD'),
            'dirty_files': [ln[3:] for ln in run('status', '--porcelain', '--', *PROVENANCE_FILES).splitlines()]}


def _mmss(s: float) -> str:
    return f'{int(s // 60)}:{s % 60:04.1f}'


def stats(xs) -> dict[str, float]:
    a = np.asarray(xs, dtype=float)
    return {'n': int(a.size), 'mean': round(float(a.mean()), 3), 'p95': round(float(np.percentile(a, 95)), 3),
            'max': round(float(a.max()), 3)}


def simulate(args, out: Path) -> tuple[dict[str, Any], list[dict]]:
    import run_pilot_zero as rpz
    from crossfade import CrossfadeMixer
    from run_session_v2 import SessionConfigV2, run_session_v2
    from segment_renderer import SymbolicSegmentRenderer, _write_wav
    from session_generator import GENERATORS, SessionSegmentSource

    ladder, controller, table_sha, ear_sha = live_stack(args.ladder)
    clock = FakeClock()
    renderer = TimedRenderer(SymbolicSegmentRenderer(sf2_path=args.sf2, sr=44100, session_seed=42),
                             clock, args.clock_render_s)
    source = None
    if args.generator != 'bank':
        source = TimedSource(SessionSegmentSource(args.stim_seed, develop=GENERATORS[args.generator]))
    player = capture_player(44100)
    phases = rpz.parse_phases(args.phases)
    minutes = sum(p[2] for p in phases)
    # run_pilot_zero's SessionConfigV2 and mixer (phase schedule: 12 s cap per segment)
    cfg = SessionConfigV2(bars_per_segment=8, sample_rate=44100, fade_bars=0.25, hr_poll_s=1.0,
                          stale_hr_policy='hold', haptic_pacing=False, max_segments=int(minutes * 60 / 12))
    mixer = CrossfadeMixer(fade_bars=0.25, fade_mode='tail_out')
    genre0, tier0 = live_args().initial_cell.split(':')
    initial = ladder.index(genre0, int(tier0))
    if args.hr == 'plant':
        hr_source = PlantHRSource(clock, ladder, initial, args.plant_k)
        controller = hr_source.wrap(controller)
    else:
        hr_source = ScriptedHRSource(clock)
    trace = run_session_v2(
        hr_source, renderer, player, mixer, ladder, controller, cfg,
        hr_target_bpm=BASELINE_BPM + phases[0][1], hr_baseline_bpm=BASELINE_BPM, initial_rung=initial,
        target_schedule=rpz.make_target_schedule(phases, BASELINE_BPM), segment_source=source,
        sleep_fn=clock.sleep, time_fn=clock.time, perf_counter_fn=clock.perf)

    rows = [r._asdict() for r in trace]
    with (out / 'session_trace.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    segs = [r for r in rows if r['bar_idx_in_segment'] == 0]
    compose = source.times if source else [0.0] * len(segs)
    timing = []
    for r, c, rt in zip(segs, compose, renderer.times):
        total = c + rt
        timing.append({'segment_idx': r['segment_idx'], 'start_s': round(r['session_time'], 3),
                       'start_mmss': _mmss(r['session_time']), 'cell': f"{r['genre']}:{r['tier']}",
                       'gen_visit_idx': r['gen_visit_idx'], 'motif_selection': r['motif_selection'],
                       'dev_version': r['dev_version'], 'phase': r['phase'],
                       'hr_bpm': None if r['hr_bpm'] is None else round(r['hr_bpm'], 2),
                       'hr_target_bpm': r['hr_target_bpm'], 'control_mode': r['control_mode'],
                       'planned_s': round(r['planned_s'], 3), 'compose_s': round(c, 3),
                       'fluidsynth_s': round(rt, 3), 'total_s': round(total, 3),
                       'lead_ratio': round(total / cfg.render_lead_s, 3)})
    with (out / 'timing.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(timing[0]))
        w.writeheader()
        w.writerows(timing)

    audio = np.concatenate(player.blocks) if player.blocks else np.zeros((0, 2), np.float32)
    wav = out / 'session.wav'
    if not args.no_wav:
        _write_wav(wav, audio, 44100)
    totals = [t['total_s'] for t in timing]
    slow = max(timing, key=lambda t: t['total_s'])
    by_cell: dict[str, list[float]] = {}
    for t in timing:
        by_cell.setdefault(t['cell'], []).append(t['total_s'])
    return {
        'kind': 'offline simulated closed-loop session (scripted HR; not a participant session)',
        'command': ' '.join([Path(sys.executable).name, *sys.argv]),
        'created': datetime.now().astimezone().isoformat(timespec='seconds'),
        'generator': source.s.config() if source else {'generator': 'bank'},
        'hr': ({'source': 'SCRIPTED_HR (fixed function of time; does not respond to the music)',
                'stale_window_s': STALE} if args.hr == 'scripted' else
               {'source': f'PlantHRSource (synthetic first-order, K={args.plant_k} bpm at u=1, tau 60 s; '
                          'engineering only, not a model of any person)'})
              | {'baseline_bpm': BASELINE_BPM, 'phases': args.phases},
        'runner_config': {'session_config': cfg.__dict__, 'mixer': 'CrossfadeMixer(fade_bars=0.25, tail_out)',
                          'initial_cell': live_args().initial_cell, 'ladder': args.ladder,
                          'energy_table_sha256': table_sha, 'ear_order_sha256': ear_sha,
                          'controller': {k: v for k, v in controller.cfg.__dict__.items() if k != 'user_descriptor'}, 'ladder_cells': [f'{c.genre}{c.tier}:{c.u:.4f}'
                                                                              for c in ladder.cells]},
        'clock_render_s': args.clock_render_s,
        'sf2': {'path': str(Path(args.sf2).resolve()), 'bytes': Path(args.sf2).stat().st_size},
        'n_segments': len(segs), 'cells_visited': len(by_cell),
        'control_modes': sorted({t['control_mode'] for t in timing}),
        'motif_selection_counts': {k: sum(str(t['motif_selection']) == k for t in timing)
                                   for k in sorted({str(t['motif_selection']) for t in timing})},
        'wav': None if args.no_wav else {'path': str(wav), 'sha256': _sha(wav),
                                         'seconds': round(audio.shape[0] / 44100, 3),
                                         'peak': round(float(np.abs(audio).max()), 4)},
        'timing_s': {'compose': stats(compose), 'fluidsynth': stats(renderer.times), 'total': stats(totals),
                     'render_lead_s': cfg.render_lead_s,
                     'max_lead_ratio': round(max(totals) / cfg.render_lead_s, 3),
                     'segments_over_lead': sum(t > cfg.render_lead_s for t in totals),
                     'slowest_segment': slow,
                     'slowest_cell_mean': max(((c, round(mean(v), 3)) for c, v in by_cell.items()),
                                              key=lambda x: x[1])},
        'git': _git(),
        'source_sha256': {p: _sha(HERE / p) for p in PROVENANCE_FILES},
        'python': platform.python_version(),
    }, timing


def sweep(args, out: Path) -> dict[str, Any]:
    """Compose + FluidSynth time for every live cell x visits 0..n-1 (fresh source)."""
    from segment_renderer import SymbolicSegmentRenderer
    from session_generator import GENERATORS, SessionSegmentSource

    ladder = live_stack(args.ladder)[0]
    renderer = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=44100, session_seed=42)
    src = SessionSegmentSource(args.stim_seed, develop=GENERATORS[args.generator])
    rows = []
    for v in range(args.sweep):
        for c in ladder.cells:
            t0 = time.perf_counter()
            pm, info = src.next_segment(c.genre, c.tier)
            t1 = time.perf_counter()
            renderer.render_pm(pm)
            t2 = time.perf_counter()
            rows.append({'cell': f'{c.genre}:{c.tier}', 'visit': v, 'compose_s': round(t1 - t0, 3),
                         'fluidsynth_s': round(t2 - t1, 3), 'total_s': round(t2 - t0, 3),
                         'motif_selection': info.get('motif_selection')})
    with (out / 'timing_sweep.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    cells: dict[str, list[float]] = {}
    for r in rows:
        cells.setdefault(r['cell'], []).append(r['total_s'])
    worst = sorted(((round(mean(v), 3), round(max(v), 3), c) for c, v in cells.items()), reverse=True)[:5]
    return {'sweep_visits': args.sweep, 'n': len(rows), 'total': stats([r['total_s'] for r in rows]),
            'compose': stats([r['compose_s'] for r in rows]), 'fluidsynth': stats([r['fluidsynth_s'] for r in rows]),
            'slowest_cells_mean_max': worst,
            'over_lead_3s': sum(r['total_s'] > 3.0 for r in rows)}


def listening_notes(m: dict[str, Any], timing: list[dict]) -> str:
    lines = [
        '# Integration audition: simulated closed-loop session',
        '',
        f"Generator: {m['generator']}  ",
        f"HR: {m['hr']['source']}; baseline {m['hr']['baseline_bpm']} bpm, phases {m['hr']['phases']}"
        + (f", no HR during {m['hr']['stale_window_s'][0]:.0f}-{m['hr']['stale_window_s'][1]:.0f} s.  "
           if 'stale_window_s' in m['hr'] else '.  '),
        'The controller, ladder, mixer and renderer are the live runner\'s (default flags). The HR is '
        'scripted or synthetic, so this file shows how the music follows the controller\'s cell '
        'choices; it is not evidence of any effect on a listener.',
        '',
        'Differences from a live session: no PPG, no haptics, fake clock (no real gaps; real render '
        'times are in timing.csv), the WAV is the queued stream (live, a late render would add silence).',
        '',
        '## Segments',
        '',
        '| seg | start | cell | visit | selection | phase | HR | target | mode |',
        '|---|---|---|---|---|---|---|---|---|',
    ]
    for t in timing:
        lines.append(f"| {t['segment_idx']} | {t['start_mmss']} | {t['cell']} | {t['gen_visit_idx']} | "
                     f"{t['motif_selection'] or '-'} | {t['phase']} | {t['hr_bpm'] if t['hr_bpm'] is not None else '--'} | "
                     f"{t['hr_target_bpm']:.0f} | {t['control_mode']} |")
    lines += [
        '',
        '## Listen for',
        '',
        '- Do cell changes (genre or tier) sound like deliberate transitions, or like cuts?',
        '- On a revisit (visit > 0 after time in other cells), does the cell sound like the same piece continuing?',
        '- While a cell holds (several segments in a row, including the stale-HR hold), does it develop or loop?',
        '- Any gap, click or level jump at a segment boundary? (note the start time)',
        '- Does the energy order of the cells the controller walks through match what you hear?',
        '- Latin and Rock: technically validated; developer listening pending.',
        '',
    ]
    return '\n'.join(lines)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    p.add_argument('--sf2', required=True)
    p.add_argument('--generator', default='v2c', choices=('bank', 'v2a', 'v2c'))
    p.add_argument('--stim-seed', type=int, default=1)
    p.add_argument('--phases', default=PHASES)
    p.add_argument('--hr', default='scripted', choices=('scripted', 'plant'),
                   help='scripted: fixed HR(t); plant: synthetic first-order HR driven by the chosen cell')
    p.add_argument('--plant-k', type=float, default=14.0, help='--hr plant: HR rise (bpm) at u = 1')
    p.add_argument('--ladder', default='measured', choices=('measured', 'ear', 'prior'),
                   help='as run_pilot_zero --ladder (ear: energy_order_by_ear.json)')
    p.add_argument('--clock-render-s', type=float, default=1.5,
                   help='fake-clock time charged per render (keeps the run deterministic)')
    p.add_argument('--no-wav', action='store_true')
    p.add_argument('--sweep', type=int, default=0, help='timing sweep: every live cell x N visits, no session')
    p.add_argument('--out', default=None)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else HERE / 'renders' / 'integration_v2' / f'{stamp}_{args.generator}'
    out.mkdir(parents=True, exist_ok=True)
    if args.sweep:
        if args.generator == 'bank':
            raise SystemExit('ERROR: --sweep needs --generator v2a or v2c')
        s = sweep(args, out)
        (out / 'timing_sweep.json').write_text(json.dumps(s, indent=2))
        print(json.dumps(s, indent=2))
        return 0
    m, timing = simulate(args, out)
    (out / 'manifest.json').write_text(json.dumps(m, indent=2, default=str))
    (out / 'LISTENING_NOTES.md').write_text(listening_notes(m, timing))
    print(json.dumps({k: m[k] for k in ('n_segments', 'cells_visited', 'control_modes',
                                        'motif_selection_counts', 'wav', 'timing_s')}, indent=2, default=str))
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
