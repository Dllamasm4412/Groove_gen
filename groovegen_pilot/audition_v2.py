"""
v2 audition harness: renders listening sequences from the real generators for
developer listening (engineering only; not a study stimulus, not the live path).

Each audition is a fresh session: a new SessionComposer(stim_seed) (v2) or
BankGenerator (v1, the live bank rotation as stimulus_audit reproduces it), so
the k-th visit to a cell in an audition is visit_idx k. Generation reuses the
generators unchanged; rendering uses SymbolicSegmentRenderer._render_pm_to_audio
(FluidSynth CLI, fixed gain 0.8, no normalization); segments are joined as the
live runner joins them: run_session_v2's trim (8 bars + one crossfade) and
CrossfadeMixer(fade_bars=0.25, fade_mode='tail_out') from run_pilot_zero.
Differences from live playback (no HR, no controller, no gaps) are listed in
LISTENING_NOTES.md.

Modes
-----
    dwell     --cell C --visits N: N consecutive visits to one cell
    sequence  --cells A,B,... --visits-per-cell K: each cell K visits in order
    preset    --preset NAME: a fixed list of auditions (PRESETS)

--generator v2 (default) | v1 | both (A/B: the same trajectory through each).

Usage (writes only under renders/, which is gitignored):
    python audition_v2.py --mode dwell --cell hiphop:3 --visits 8 --stim-seed 1
    python audition_v2.py --mode sequence --cells calm:2,lofi:2,rnb:2,pop:3 --visits-per-cell 1
    python audition_v2.py --preset problem --generator both
    python audition_v2.py --preset initial
Outputs in <out> (default renders/audition_v2/<stamp>/):
    <name>.wav            one joined WAV per audition and generator
    manifest.csv          one row per segment (provenance, novelty, timing)
    manifest.json         run metadata and per-audition summary
    LISTENING_NOTES.md    segment timestamps and the listening checklist
    segments/             per-segment trimmed WAVs, only with --segment-wavs
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

import stimulus_metrics as sm
from crossfade import CrossfadeMixer, bar_duration_frames
from run_session_v2 import SessionConfigV2

HERE = Path(__file__).resolve().parent
LIVE = SessionConfigV2()
BARS = LIVE.bars_per_segment
SAMPLE_RATE = LIVE.sample_rate
FADE_BARS = LIVE.fade_bars
LIVE_FADE_MODE = 'tail_out'          # run_pilot_zero: CrossfadeMixer(fade_bars=0.25, fade_mode="tail_out")

DWELL_CELLS = ('calm:2', 'rnb:4', 'pop:3', 'latin:2', 'hiphop:1', 'hiphop:3', 'hiphop:5',
               'rock:1', 'rock:3', 'rock:5')
LADDER_SEQUENCE = ('calm:2', 'lofi:2', 'rnb:2', 'pop:3', 'latin:3', 'hiphop:3', 'rock:3')
PROBLEM_CELLS = ('calm:1', 'calm:2', 'hiphop:1', 'hiphop:3', 'rock:1', 'rock:3', 'rock:5')


@dataclass(frozen=True)
class Audition:
    mode: str                         # 'dwell' | 'sequence'
    cells: tuple                      # ((genre, tier), ...) in play order, one entry per segment

    def label(self) -> str:
        names = list(dict.fromkeys(f'{g}{t}' for g, t in self.cells))
        if self.mode == 'dwell':
            return f'dwell_{names[0]}_x{len(self.cells)}'
        joined = '-'.join(names)
        if len('sequence_' + joined) > 60:
            joined = f'{names[0]}_to_{names[-1]}_{len(names)}cells_' \
                     + hashlib.sha1('-'.join(names).encode()).hexdigest()[:6]
        k = len(self.cells) // len(names)
        return f'sequence_{joined}' + (f'_x{k}' if k > 1 else '')


PRESETS: dict[str, list[tuple]] = {
    # (mode, cells, visits per cell)
    'initial': [('dwell', ('hiphop:3',), 8), ('dwell', ('rock:3',), 8), ('dwell', ('calm:2',), 8),
                ('dwell', ('rnb:4',), 6), ('dwell', ('latin:2',), 6), ('sequence', LADDER_SEQUENCE, 1)],
    'problem': [('dwell', (c,), 8) for c in PROBLEM_CELLS],
    'dwell_all': [('dwell', (c,), 8) for c in DWELL_CELLS],
    'ladder': [('sequence', LADDER_SEQUENCE, 1)],
}


# =============================================================================
# Planning (pure)
# =============================================================================


def parse_cell(text: str, valid: Optional[set] = None) -> tuple[str, int]:
    """'genre:tier' -> (genre, tier); with valid, the cell must be on the live ladder."""
    parts = text.strip().split(':')
    if len(parts) != 2 or not parts[0] or not parts[1].isdigit():
        raise ValueError(f'bad cell {text!r}: expected genre:tier, e.g. hiphop:3')
    cell = (parts[0].lower(), int(parts[1]))
    if valid is not None and cell not in valid:
        raise ValueError(f'{text} is not on the live ladder')
    return cell


def parse_cells(text: str, valid: Optional[set] = None) -> list[tuple[str, int]]:
    cells = [parse_cell(c, valid) for c in text.split(',') if c.strip()]
    if not cells:
        raise ValueError('empty cell list')
    return cells


def plan_audition(mode: str, cells: list[tuple[str, int]], visits: int) -> Audition:
    """dwell: visits segments of cells[0]; sequence: each cell visits times, in order."""
    if visits < 1:
        raise ValueError(f'visits must be >= 1, got {visits}')
    if mode == 'dwell':
        if len(cells) != 1:
            raise ValueError('dwell takes exactly one cell')
        return Audition('dwell', tuple(cells) * visits)
    if mode == 'sequence':
        return Audition('sequence', tuple(c for c in cells for _ in range(visits)))
    raise ValueError(f'unknown mode {mode!r}')


def plan_preset(name: str, valid: Optional[set] = None) -> list[Audition]:
    if name not in PRESETS:
        raise ValueError(f'unknown preset {name!r}; choose from {sorted(PRESETS)}')
    return [plan_audition(mode, [parse_cell(c, valid) for c in cells], n) for mode, cells, n in PRESETS[name]]


def wav_name(audition: Audition, idx: int, generator: str, stim_seed: int) -> str:
    seed = f'_s{stim_seed}' if generator == 'v2' else ''
    return f'{idx:02d}_{audition.label()}_{generator}{seed}.wav'


# =============================================================================
# Generation (the real generators, unchanged)
# =============================================================================


def generate(audition: Audition, generator: str, stim_seed: int) -> list[tuple[Any, dict]]:
    """(PrettyMIDI, row) per segment, from a fresh generator (a new session)."""
    from composer.arrangement import SessionComposer, cell_plan
    from stimulus_audit import BankGenerator

    comp = SessionComposer(stim_seed) if generator == 'v2' else None
    bank = BankGenerator() if generator == 'v1' else None
    visits: dict[tuple, int] = {}
    prev_drum: dict[tuple, tuple] = {}
    out = []
    for i, (g, t) in enumerate(audition.cells):
        v = visits.get((g, t), 0)
        visits[(g, t)] = v + 1
        row: dict[str, Any] = {'seg_idx': i, 'genre': g, 'tier': t, 'cell': f'{g}:{t}', 'visit_idx': v,
                               'generator': generator}
        if generator == 'v2':
            pm, info = comp.compose(g, t, v)
            ops = info.get('drum_ops') or []
            row.update({
                'stim_seed': stim_seed, 'gen_version': info['gen_version'],
                'tempo_bpm': info['tempo_bpm'], 'density': info['density'],
                'base_seed': info['base_seed'], 'var_seed': info['var_seed'], 'block_idx': info['block_idx'],
                'pos_in_block': info['pos_in_block'], 'gen_candidates': info['gen_candidates'],
                'gen_candidate_idx': info['gen_candidate_idx'], 'gen_sub_seed': info['gen_sub_seed'],
                'novelty_rejections': info['novelty_rejections'], 'novelty_fallback': info['novelty_fallback'],
                'gen_fallback': info['gen_fallback'], 'op_cost': info.get('op_cost'),
                'n_drum_ops': sum(len(x) for x in ops), 'form_template': info.get('form_template'),
                'novelty_r4_prev': info['novelty_r4_prev'], 'novelty_r4_base': info['novelty_r4_base'],
            })
            base_id = info['base_seed']
        else:
            pm, plan = bank.generate(g, t)
            tempo, density = cell_plan(g, t)
            row.update({'stim_seed': None, 'gen_version': 'v1', 'tempo_bpm': tempo, 'density': density,
                        'bank_seed': plan['seed'], 'composer_seed': plan['composer_seed']})
            base_id = plan['composer_seed']
        drum = sm.bar_onset_sets(pm, BARS, 'drum')
        row['midi_sha256'] = sm.midi_sha256(pm)
        row['drum_sha'] = sm.content_sha(drum)
        # novelty vs the previous visit to this cell (certification's C1 and R4)
        if (g, t) in prev_drum:
            from certify_stimuli import drum_bar_novelty

            p_drum, p_base = prev_drum[(g, t)]
            row['same_base_as_prev'] = base_id == p_base
            row['near_repeat_drum'] = round(sm.near_repeat_similarity(p_drum, drum), 4)
            row.update(drum_bar_novelty(p_drum, drum))
        prev_drum[(g, t)] = (drum, base_id)
        out.append((pm, row))
    return out


# =============================================================================
# Rendering and joining (live trim + live mixer)
# =============================================================================


def trim_like_live(audio: np.ndarray, tempo_bpm: float) -> np.ndarray:
    """run_session_v2 trim_render_tail: keep the bars plus one crossfade of release."""
    bar = bar_duration_frames(tempo_bpm, LIVE.beats_per_bar, SAMPLE_RATE)
    return audio[:BARS * bar + int(round(bar * FADE_BARS))]


def join_like_live(segments: list[np.ndarray], tempos: list[float]) -> tuple[np.ndarray, list[int], dict]:
    """Push trimmed segments through the live mixer. Returns the joined audio, the
    start frame of each segment in it, and mixer stats."""
    mixer = CrossfadeMixer(sample_rate=SAMPLE_RATE, beats_per_bar=LIVE.beats_per_bar,
                           fade_bars=FADE_BARS, fade_mode=LIVE_FADE_MODE)
    parts, starts, n = [], [], 0
    for a, tempo in zip(segments, tempos):
        starts.append(n)                 # tail_out: the segment's downbeat starts the emitted block
        e = mixer.push(a, tempo_bpm=tempo)
        parts.append(e)
        n += e.shape[0]
    parts.append(mixer.flush())
    stats = {'n_tail_scaled': mixer.n_tail_scaled, 'min_tail_scale': round(mixer.min_tail_scale, 4)}
    return np.concatenate(parts, axis=0).astype(np.float32), starts, stats


_RENDERER = None


def _init_worker(sf2: str) -> None:
    global _RENDERER
    from segment_renderer import SymbolicSegmentRenderer
    _RENDERER = SymbolicSegmentRenderer(sf2_path=sf2, sr=SAMPLE_RATE, session_seed=42)


def _render_one(pm) -> tuple[np.ndarray, float]:
    t0 = time.perf_counter()
    audio = _RENDERER._render_pm_to_audio(pm)
    return audio, (time.perf_counter() - t0) * 1e3


def fluidsynth_renderer(sf2: str, workers: int) -> Callable:
    """render(pms) -> [(audio, render_ms)], in order, through SymbolicSegmentRenderer."""
    def render(pms):
        if workers <= 1:
            _init_worker(sf2)
            return [_render_one(pm) for pm in pms]
        with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(sf2,)) as ex:
            return list(ex.map(_render_one, pms))
    return render


def _write_wav(path: Path, audio: np.ndarray) -> None:
    from segment_renderer import _write_wav as write
    write(path, audio, SAMPLE_RATE)


# =============================================================================
# Run
# =============================================================================

MANIFEST_FIELDS = (
    'audition', 'wav', 'seg_idx', 'start_s', 'start_mmss', 'duration_s', 'render_ms',
    'generator', 'genre', 'tier', 'cell', 'visit_idx', 'stim_seed', 'gen_version', 'tempo_bpm', 'density',
    'base_seed', 'var_seed', 'block_idx', 'pos_in_block', 'bank_seed', 'composer_seed',
    'gen_candidates', 'gen_candidate_idx', 'gen_sub_seed', 'novelty_rejections', 'novelty_fallback',
    'gen_fallback', 'op_cost', 'n_drum_ops', 'form_template',
    'same_base_as_prev', 'near_repeat_drum', 'novelty_r4_prev', 'novelty_r4_base',
    'new_drum_bar_frac', 'new_drum_patterns', 'changed_drum_bar_frac',
    'midi_sha256', 'drum_sha')


def _mmss(s: float) -> str:
    return f'{int(s // 60)}:{s % 60:04.1f}'


def run_auditions(auditions: list[Audition], generators: list[str], stim_seed: int, out: Path,
                  render: Callable, segment_wavs: bool = False) -> dict:
    """Generate, render, join and write every audition; returns the manifest summary."""
    if 'frozen_v2' in out.resolve().parts:
        raise SystemExit('refusing to write under frozen_v2')
    out.mkdir(parents=True, exist_ok=True)
    rows, summary = [], []
    idx = 0
    for aud in auditions:
        for gen in generators:
            idx += 1
            name = wav_name(aud, idx, gen, stim_seed)
            segs = generate(aud, gen, stim_seed)
            rendered = render([pm for pm, _ in segs])
            trimmed = [trim_like_live(a, r['tempo_bpm']) for (a, _), (_, r) in zip(rendered, segs)]
            audio, starts, mix = join_like_live(trimmed, [r['tempo_bpm'] for _, r in segs])
            _write_wav(out / name, audio)
            for (pm, r), (_, ms), a, st in zip(segs, rendered, trimmed, starts):
                r.update(audition=name[:-4], wav=name, start_s=round(st / SAMPLE_RATE, 3),
                         start_mmss=_mmss(st / SAMPLE_RATE), duration_s=round(a.shape[0] / SAMPLE_RATE, 3),
                         render_ms=round(ms, 1))
                if segment_wavs:
                    (out / 'segments').mkdir(exist_ok=True)
                    _write_wav(out / 'segments' / f'{name[:-4]}_seg{r["seg_idx"]:02d}.wav', a)
                rows.append(r)
            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            summary.append({'wav': name, 'mode': aud.mode, 'generator': gen,
                            'cells': list(dict.fromkeys(f'{g}:{t}' for g, t in aud.cells)),
                            'n_segments': len(segs), 'duration_s': round(audio.shape[0] / SAMPLE_RATE, 2),
                            'peak': round(peak, 4), 'n_clipped': int(np.sum(np.abs(audio) >= 1.0)), **mix,
                            'gen_fallbacks': sum(bool(r.get('gen_fallback')) for _, r in segs),
                            'novelty_fallbacks': sum(bool(r.get('novelty_fallback')) for _, r in segs)})
            print(f'  {name}: {len(segs)} segments, {summary[-1]["duration_s"]:.1f} s', file=sys.stderr)
    with (out / 'manifest.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS, extrasaction='ignore')
        w.writeheader()
        for r in rows:
            w.writerow({k: '' if r.get(k) is None else r.get(k) for k in MANIFEST_FIELDS})
    (out / 'LISTENING_NOTES.md').write_text(listening_notes(summary, rows, stim_seed), encoding='utf-8')
    return {'auditions': summary, 'rows': rows}


def listening_notes(summary: list[dict], rows: list[dict], stim_seed: int) -> str:
    lines = ['# v2 listening notes', '',
             f'Developer listening, engineering only. stim_seed {stim_seed}. Each WAV is a fresh session.', '',
             '## Auditions', '', '| WAV | mode | cells | segments | duration |', '|---|---|---|---|---|']
    for s in summary:
        lines.append(f"| `{s['wav']}` | {s['mode']} | {', '.join(s['cells'])} | {s['n_segments']} "
                     f"| {_mmss(s['duration_s'])} |")
    lines += ['', '## Segment start times', '',
              'v = visit index in the cell; "same base" = variation of the previous visit\'s base '
              '(else a new block); new bars = C1, drum bars not heard in the previous visit.', '']
    for s in summary:
        lines += [f"`{s['wav']}`", '', '| seg | start | cell | v | same base | new bars | notes |',
                  '|---|---|---|---|---|---|---|']
        for r in (r for r in rows if r['wav'] == s['wav']):
            sb = {True: 'yes', False: 'no'}.get(r.get('same_base_as_prev'), '-')
            nb = '-' if r.get('new_drum_bar_frac') is None else f"{round(r['new_drum_bar_frac'] * BARS)}/{BARS}"
            lines.append(f"| {r['seg_idx']} | {r['start_mmss']} | {r['cell']} | {r['visit_idx']} | {sb} | {nb} | |")
        lines.append('')
    lines += [
        '## Checklist', '',
        '### Long dwell',
        '- Does this feel like the same short loop repeating?',
        '- Does each 8-bar segment feel connected to the previous one?',
        '- Are the phrase-end changes noticeable but not distracting?',
        '- Does the groove identity remain stable?',
        '- Does any variation sound mechanically inserted?', '',
        '### Timbre',
        '- Do fills suddenly become darker or brighter?',
        '- Are cymbal / open-hat changes noticeable?',
        '- Do snare / rim / conga substitutions sound natural?',
        '- Does anything sound like an audio glitch rather than intentional variation?', '',
        '### Musical coherence',
        '- Does the key / progression feel continuous?',
        '- Does it feel like one piece developing?',
        '- Are transitions between segments obvious? (new blocks: "same base" = no)', '',
        '### Energy',
        '- Within one cell, does intensity feel reasonably stable?',
        '- Across the ladder sequence, does perceived energy generally increase?', '',
        '### Overall',
        '- Which cells still sound repetitive?',
        '- Which cells sound over-varied?',
        '- Which changes sound musical versus algorithmic?', '',
        '## Differences from live playback', '',
        '- Same generator, renderer call, soundfont, trim and tail_out crossfade as the live runner.',
        '- No HR, controller or player: segments follow the fixed audition order, back to back.',
        '- Live, render time can leave short gaps at boundaries (inter-segment gap not yet '
        'confirmed live); this file has none.',
        '- v2 is not wired live. Live visit indices depend on the controller path; here each WAV is '
        'a fresh session, so visit k is the k-th visit to the cell in that WAV.',
        '- The WAV is written as 16-bit PCM, clipped at full scale (the live player gets float32).',
        '']
    return '\n'.join(lines)


def _file_sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--mode', choices=('dwell', 'sequence'), default=None)
    ap.add_argument('--preset', choices=sorted(PRESETS), default=None)
    ap.add_argument('--cell', default=None, help='dwell: genre:tier')
    ap.add_argument('--cells', default=None, help='sequence: comma list of genre:tier')
    ap.add_argument('--visits', type=int, default=8, help='dwell: visits to the cell')
    ap.add_argument('--visits-per-cell', type=int, default=1, help='sequence: consecutive visits per cell')
    ap.add_argument('--stim-seed', type=int, default=1)
    ap.add_argument('--generator', choices=('v2', 'v1', 'both'), default='v2')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    ap.add_argument('--workers', type=int, default=2)
    ap.add_argument('--segment-wavs', action='store_true', help='also save each trimmed segment')
    ap.add_argument('--out', default=None, help='output dir (default renders/audition_v2/<stamp>)')
    args = ap.parse_args(argv)
    if (args.mode is None) == (args.preset is None):
        ap.error('give exactly one of --mode or --preset')
    if args.mode == 'dwell' and not args.cell:
        ap.error('--mode dwell needs --cell')
    if args.mode == 'sequence' and not args.cells:
        ap.error('--mode sequence needs --cells')
    if not 1 <= args.workers <= 3:
        ap.error('--workers must be 1..3 (keeps the machine usable)')
    return args


def build_auditions(args, valid: Optional[set]) -> list[Audition]:
    try:
        if args.preset:
            return plan_preset(args.preset, valid)
        if args.mode == 'dwell':
            return [plan_audition('dwell', [parse_cell(args.cell, valid)], args.visits)]
        return [plan_audition('sequence', parse_cells(args.cells, valid), args.visits_per_cell)]
    except ValueError as exc:
        raise SystemExit(f'audition_v2: {exc}') from exc


def main(argv=None, render: Optional[Callable] = None) -> int:
    from stimulus_audit import code_provenance, live_ladder

    args = parse_args(argv)
    ladder, ladder_info = live_ladder('measured')
    auditions = build_auditions(args, {(c.genre, c.tier) for c in ladder.cells})
    generators = ['v1', 'v2'] if args.generator == 'both' else [args.generator]
    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else HERE / 'renders' / 'audition_v2' / stamp
    if render is None:
        if not Path(args.sf2).exists():
            raise SystemExit(f'soundfont not found: {args.sf2}')
        render = fluidsynth_renderer(args.sf2, args.workers)
    t0 = time.perf_counter()
    res = run_auditions(auditions, generators, args.stim_seed, out, render, args.segment_wavs)
    from composer.arrangement import GEN_VERSION
    meta = {
        'tool': 'audition_v2.py', 'timestamp': stamp, 'argv': sys.argv[1:] if argv is None else argv,
        'stim_seed': args.stim_seed, 'generators': generators, 'gen_version': GEN_VERSION,
        'join': {'bars_per_segment': BARS, 'fade_bars': FADE_BARS, 'fade_mode': LIVE_FADE_MODE,
                 'trim': 'run_session_v2 trim_render_tail', 'sample_rate': SAMPLE_RATE},
        'soundfont': args.sf2, 'soundfont_sha256': _file_sha256(Path(args.sf2)),
        'ladder': ladder_info, 'workers': args.workers, 'elapsed_s': round(time.perf_counter() - t0, 1),
        'python': platform.python_version(), 'code': code_provenance(),
    }
    (out / 'manifest.json').write_text(json.dumps({'meta': meta, 'auditions': res['auditions']}, indent=2,
                                                  default=str), encoding='utf-8')
    print(f'wrote {out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
