"""
Rock timbre / mix calibration -- audition tool. Nothing in the composer,
renderer, session loop or runner imports this file.

Since the 2026-10-05 decision is wired (composer GENRE_CFG['rock']:
drum_velocity_scale, render_gain_db; renderer float + limiter path), composed
Rock already carries drums x1.20 and its render directive: options here now
stack on top of that, so census / package / gains outputs from before the
wiring are not reproducible with this code.

Presentation only: present() copies the composed MIDI and changes the guitar
program, scales drum velocities by one fixed factor (accent ratios kept,
clamped to 1..127) and leaves every pitch, onset, duration, note count,
pitched velocity, bass note, chord and tempo as composed. An optional fixed
Rock output gain (dB) scales the fluidsynth gain (-g); since the wiring,
composed Rock takes the renderer's float + limiter path, so that gain stacks
on the directive's. `gains` renders float + gain + limiter itself. There is
no per-segment normalization.

Every Rock tier composes its guitars with music21 ElectricGuitar(), which
writes program 26 (Musyng Kite "Jazz Guitar") at every tier; rock_cell.py's
docstring (clean 27 / overdriven 30) does not match the MIDI.

Segments are planned exactly as music_features_measured.py (melody-bank
variants, tier tempo, renderer seed), so current-Rock rows reproduce
energy_table_v1.json and a candidate's Rock means can replace the table's in
memory to see where the live ladder would put it (the table is not written).

Usage (writes only under renders/, gitignored):
    python rock_mix_audition.py census --sf2 ../soundfonts/Musyng_Kite.sf2 \
        --out renders/rock_mix/<ts>/census [--variants 8] [--workers 6]
    python rock_mix_audition.py package --sf2 ../soundfonts/Musyng_Kite.sf2 \
        --out renders/rock_mix/<ts>/listen --guitar overdriven --drum-scale 1.10 \
        --drum-scales 1.20 [--master-db 0] [--alt 1.20,-1.0]
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pretty_midi

import music_features_measured as mfm

# Musyng Kite bank-0 presets (read from the sf2 preset headers); None keeps the
# composed program (26, "Jazz Guitar").
GUITARS = {'current': None, 'clean': 27, 'overdriven': 29, 'distortion': 30}
GUITAR_NAMES = {None: 'Jazz Guitar (26, as composed)', 27: 'Clean Guitar', 29: 'Overdriven Guitar',
                30: 'Distortion Guitar'}
DRUM_SCALES = (1.0, 1.10, 1.20)
COMPOSED_GUITAR_PROGRAM = 26

ROCK_CELLS = [('rock', t) for t in range(1, 6)]
# Live-ladder neighbours of each Rock cell (energy_table_v1 + live tier caps).
NEIGHBOURS = {
    1: [('hiphop', 2), ('latin', 1)],
    2: [('latin', 3), ('pop', 1)],
    3: [('pop', 4), ('pop', 5)],
    4: [('hiphop', 4), ('hiphop', 5)],
    5: [('hiphop', 5)],
}
TRANSITIONS = [[('hiphop', 2), ('rock', 1), ('latin', 1)],
               [('latin', 3), ('rock', 2), ('pop', 1)],
               [('pop', 4), ('rock', 3), ('pop', 5)],
               [('hiphop', 4), ('rock', 4), ('hiphop', 5)]]


# =============================================================================
# Presentation (the only thing a candidate changes)
# =============================================================================


def present(pm: pretty_midi.PrettyMIDI, program: int | None = None,
            drum_scale: float = 1.0) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Copy of `pm` with the guitar program replaced and drum velocities scaled.
    Returns (MIDI, stats) with the number of drum notes clamped at 127."""
    out = copy.deepcopy(pm)
    n_clamped = 0
    for inst in out.instruments:
        if inst.is_drum:
            if drum_scale != 1.0:
                for n in inst.notes:
                    v = int(round(n.velocity * drum_scale))
                    n_clamped += v > 127
                    n.velocity = max(1, min(127, v))
        elif program is not None and inst.program == COMPOSED_GUITAR_PROGRAM:
            inst.program = program
    return out, {'n_drum_clamped': int(n_clamped),
                 'n_drum_127': sum(n.velocity == 127 for i in out.instruments if i.is_drum for n in i.notes)}


def render_db(renderer, pm: pretty_midi.PrettyMIDI, db: float = 0.0) -> np.ndarray:
    """Render with the renderer's fixed gain scaled by `db` (fluidsynth -g, so
    the change lands before the 16-bit write)."""
    gain = renderer.gain
    renderer.gain = gain * 10 ** (db / 20)
    try:
        return renderer._render_pm_to_audio(pm)
    finally:
        renderer.gain = gain


LIMIT_CEILING_DB = -1.0
LIMIT_WINDOW_S = 0.02


def render_float(renderer, pm: pretty_midi.PrettyMIDI) -> np.ndarray:
    """Same fluidsynth command as the renderer (gain, rate, sf2) but 32-bit
    float output, so nothing clips inside fluidsynth and a gain can follow."""
    import subprocess
    import tempfile

    import soundfile as sf

    with tempfile.TemporaryDirectory() as td:
        midi_path, wav_path = Path(td) / 'seg.mid', Path(td) / 'seg.wav'
        pm.write(str(midi_path))
        r = subprocess.run(['fluidsynth', '-ni', '-F', str(wav_path), '-O', 'float', '-r', str(renderer.sr),
                            '-g', str(renderer.gain), str(renderer.sf2_path), str(midi_path)],
                           capture_output=True, text=True)
        if r.returncode != 0 or not wav_path.exists():
            raise RuntimeError(f'fluidsynth float render failed:\n{r.stderr}')
        audio, _ = sf.read(str(wav_path), dtype='float32', always_2d=True)
    return audio[:, :2]


def limit(audio: np.ndarray, ceiling_db: float = LIMIT_CEILING_DB,
          window_s: float = LIMIT_WINDOW_S) -> tuple[np.ndarray, dict]:
    """Fixed look-ahead peak limiter, deterministic and stateless across
    segments. Per sample, the gain needed to keep |x| under the ceiling is
    min-filtered over 2W and box-smoothed over W, so the smoothed gain never
    exceeds the need (peaks stay under the ceiling) and dips last ~3W."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    ceil = 10 ** (ceiling_db / 20)
    w = max(1, int(round(window_s * mfm.SR)))
    peak = np.max(np.abs(audio), axis=1)
    need = np.minimum(1.0, ceil / np.maximum(peak, 1e-12))
    g = uniform_filter1d(minimum_filter1d(need, 2 * w + 1, mode='nearest'), w, mode='nearest')
    g = np.minimum(g, need)    # float rounding guard; already <= need by construction
    out = (audio * g[:, None]).astype(np.float32)
    return out, {'max_gr_db': round(float(-20 * np.log10(g.min())), 2),
                 'pct_limited': round(float(100 * np.mean(g < 0.999)), 2)}


def render_gain(renderer, pm: pretty_midi.PrettyMIDI, db: float) -> tuple[np.ndarray, dict]:
    """Float render, fixed Rock gain, fixed limiter."""
    return limit(render_float(renderer, pm) * np.float32(10 ** (db / 20)))


def content_key(pm: pretty_midi.PrettyMIDI) -> tuple:
    """Everything present() must leave alone: per track (is_drum, notes as
    pitch/start/end), pitched velocities, tempo."""
    tracks = []
    for inst in pm.instruments:
        notes = tuple((n.pitch, round(n.start, 6), round(n.end, 6)) +
                      (() if inst.is_drum else (n.velocity,)) for n in inst.notes)
        tracks.append((inst.is_drum, notes))
    return tuple(tracks), tuple(np.round(pm.get_tempo_changes()[1], 6))


# =============================================================================
# Planning, rendering and measuring
# =============================================================================


def compose(genre: str, tier: int, variant: int, renderer) -> tuple[pretty_midi.PrettyMIDI, float]:
    """(MIDI, played tempo) planned as music_features_measured.measure_one."""
    from composer import generate_segment

    tempo, density, bank_seed = mfm.cell_plan(genre, tier, variant)
    pm = generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=mfm.BARS,
                          seed=renderer._derive_seed(bank_seed))
    return pm, float(pm.get_tempo_changes()[1][0])


def cut(audio: np.ndarray, tempo: float) -> np.ndarray:
    bar_s = 60.0 / tempo * mfm.BEATS_PER_BAR
    return audio[:int(round(mfm.BARS * bar_s * mfm.SR + mfm.FADE_BARS * bar_s * mfm.SR))]


def stem(pm: pretty_midi.PrettyMIDI, drums: bool) -> pretty_midi.PrettyMIDI:
    out = copy.deepcopy(pm)
    out.instruments = [i for i in out.instruments if i.is_drum == drums]
    return out


def lufs(audio: np.ndarray) -> float:
    import pyloudnorm as pyln

    return float(pyln.Meter(mfm.SR).integrated_loudness(np.asarray(audio, np.float64)))


def role_velocities(pm: pretty_midi.PrettyMIDI) -> dict:
    out: dict = {}
    for inst in pm.instruments:
        if inst.is_drum:
            for role, pitches in mfm.DRUM_ROLES.items():
                v = [n.velocity for n in inst.notes if n.pitch in pitches]
                if v:
                    out[f'vel_drum_{role}'] = float(np.mean(v))
            out['vel_drum'] = float(np.mean([n.velocity for n in inst.notes]))
        elif inst.notes:
            role = 'bass' if 32 <= inst.program <= 39 else 'pitched'
            out.setdefault(f'_v_{role}', []).extend(n.velocity for n in inst.notes)
    for role in ('bass', 'pitched'):
        if f'_v_{role}' in out:
            out[f'vel_{role}'] = float(np.mean(out.pop(f'_v_{role}')))
    return out


_R = None


def _init(sf2: str) -> None:
    global _R
    from segment_renderer import SymbolicSegmentRenderer

    _R = SymbolicSegmentRenderer(sf2)


def _timed_render(pm, tempo):
    t0 = time.perf_counter()
    audio = _R._render_pm_to_audio(pm)
    return cut(audio, tempo), time.perf_counter() - t0


def measure_job(job: tuple) -> list[dict]:
    """All configs of one (genre, tier, variant): full mixes per (guitar, drum
    scale), drum stems per drum scale, pitched stems per guitar."""
    genre, tier, variant, guitars, scales = job
    pm, tempo = compose(genre, tier, variant, _R)
    dur_s = mfm.BARS * 60.0 / tempo * mfm.BEATS_PER_BAR
    base = {'genre': genre, 'tier': tier, 'variant': variant, 'tempo_bpm': tempo}
    base.update(mfm.midi_features(pm, dur_s))
    drum_lufs = {s: lufs(_timed_render(present(stem(pm, True), None, s)[0], tempo)[0]) for s in scales}
    pitched_lufs = {g: lufs(_timed_render(present(stem(pm, False), GUITARS[g])[0], tempo)[0]) for g in guitars}
    rows = []
    for g in guitars:
        for s in scales:
            p, st = present(pm, GUITARS[g], s)
            audio, render_s = _timed_render(p, tempo)
            row = dict(base, guitar=g, drum_scale=s, render_s=render_s, **st, **role_velocities(p))
            row.update(mfm.audio_features(audio))
            row['drum_stem_lufs'] = drum_lufs[s]
            row['pitched_stem_lufs'] = pitched_lufs[g]
            row['drum_minus_pitched_db'] = drum_lufs[s] - pitched_lufs[g]
            rows.append(row)
    return rows


SUMMARY_FIELDS = ['lufs', 'peak_dbfs', 'centroid_hz', 'flux', 'pulse_clarity', 'low_ratio', 'drum_rate',
                  'drum_stem_lufs', 'pitched_stem_lufs', 'drum_minus_pitched_db', 'vel_drum', 'vel_drum_low',
                  'vel_drum_backbeat', 'vel_drum_hats', 'vel_bass', 'vel_pitched', 'n_drum_127', 'render_s']


def summarize(rows: list[dict]) -> dict:
    groups: dict = {}
    for r in rows:
        groups.setdefault((r['genre'], int(r['tier']), r['guitar'], float(r['drum_scale'])), []).append(r)
    out = {}
    for (g, t, gtr, s), rs in sorted(groups.items()):
        out[f'{g}:{t}|{gtr}|{s:.2f}'] = {
            f: float(np.mean([float(r[f]) for r in rs if r.get(f) not in (None, '')]))
            for f in SUMMARY_FIELDS if any(r.get(f) not in (None, '') for r in rs)}
    return out


def ladder_with(rock_means: dict | None) -> dict:
    """Live ladder (run_pilot_zero defaults) with Rock's table features
    replaced by `rock_means` {tier: features}; the table file is untouched.
    Returns {cell: (rung, u)}."""
    import run_pilot_zero as rpz
    from ladder import build_ladder, load_energy_table
    from segment_renderer import RUNG_TIER_CAP

    features, weights, tie_band, _ = load_energy_table(Path(__file__).resolve().parent / 'energy_table_v1.json')
    features = {k: dict(v) for k, v in features.items()}
    for tier, m in (rock_means or {}).items():
        features[('rock', tier)].update({f: m[f] for f in weights})
    ladder = build_ladder(tier_caps={**RUNG_TIER_CAP, **rpz.LIVE_TIER_CAP_OVERRIDES},
                          exclude_genres=rpz.LIVE_EXCLUDE_GENRES, features=features,
                          weights=weights, tie_band=tie_band)
    return {f'{c.genre}:{c.tier}': (c.rung, round(c.u, 4)) for c in ladder.cells}


def census(args) -> None:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cells = list(ROCK_CELLS) + sorted({c for ns in NEIGHBOURS.values() for c in ns})
    jobs = []
    for g, t in cells:
        rock = g == 'rock'
        for v in range(args.variants):
            jobs.append((g, t, v, list(GUITARS) if rock else ['current'], DRUM_SCALES if rock else (1.0,)))
    with ProcessPoolExecutor(args.workers, initializer=_init, initargs=(args.sf2,)) as ex:
        rows = [r for rs in ex.map(measure_job, jobs) for r in rs]
    fields = sorted({k for r in rows for k in r}, key=lambda k: (k not in ('genre', 'tier', 'variant', 'guitar',
                                                                              'drum_scale'), k))
    with open(out / 'census.csv', 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    summ = summarize(rows)
    table = json.loads((Path(__file__).resolve().parent / 'energy_table_v1.json').read_text())['cells']
    placement = {'table': ladder_with(None)}
    for gtr in GUITARS:
        for s in DRUM_SCALES:
            means = {t: summ[f'rock:{t}|{gtr}|{s:.2f}'] | {'tempo_bpm': table[f'rock:{t}']['tempo_bpm']}
                     for t in range(1, 6)}
            placement[f'{gtr}|{s:.2f}'] = ladder_with(means)
    (out / 'summary.json').write_text(json.dumps({'cells': summ, 'placement': placement,
                                                  'variants': args.variants, 'sf2': str(args.sf2)}, indent=1))
    print(f'wrote {out}/census.csv ({len(rows)} rows), summary.json')


# =============================================================================
# Listening package
# =============================================================================


def render_cell(genre: str, tier: int, variant: int, program=None, drum_scale=1.0, db=0.0):
    pm, tempo = compose(genre, tier, variant, _R)
    if genre == 'rock':
        pm, _ = present(pm, program, drum_scale)
    from audition_v2 import trim_like_live

    return trim_like_live(render_db(_R, pm, db if genre == 'rock' else 0.0), tempo), tempo


def write_join(path: Path, parts: list[tuple[np.ndarray, float]]) -> dict:
    from audition_v2 import join_like_live
    from segment_renderer import _write_wav

    audio, starts, stats = join_like_live([a for a, _ in parts], [t for _, t in parts])
    _write_wav(path, audio, mfm.SR)
    bars = [a[:int(round(mfm.BARS * mfm.BEATS_PER_BAR * 60 / t * mfm.SR))] for a, t in parts]
    return {'file': path.name, 'seconds': round(audio.shape[0] / mfm.SR, 2),
            'segment_lufs': [round(lufs(a), 2) for a in bars],
            'peak_dbfs': round(float(20 * np.log10(max(np.max(np.abs(audio)), 1e-9))), 2),
            'full_scale_samples': int(sum(np.sum(np.abs(a) >= 32767 / 32768) for a, _ in parts)), **stats}


def package(args) -> None:
    out = Path(args.out)
    for d in ('1_timbre', '2_mix', '3_transitions'):
        (out / d).mkdir(parents=True, exist_ok=True)
    _init(args.sf2)
    gp = GUITARS[args.guitar]
    proposed = (args.drum_scale, args.master_db)
    files: dict = {}
    for tier in (3, 1, 5):
        for letter, gtr in zip('ABCD', GUITARS):
            p = out / '1_timbre' / f'rock{tier}_{letter}_{gtr}.wav'
            files[str(p.relative_to(out))] = write_join(p, [render_cell('rock', tier, v, GUITARS[gtr])
                                                            for v in (0, 1)])
    mixes = [(s, 0.0) for s in sorted({1.0, *args.drum_scales, args.drum_scale})]
    for m in (proposed, args.alt):
        if m and m[1] and m not in mixes:
            mixes.append(m)
    for tier in (3, 1, 5):
        for i, (s, db) in enumerate(mixes, 1):
            name = f'{i}_drums_x{s:.2f}' + (f'_rock{db:+.1f}dB' if db else '')
            p = out / '2_mix' / f'rock{tier}_{args.guitar}_{name}.wav'
            files[str(p.relative_to(out))] = write_join(p, [render_cell('rock', tier, v, gp, s, db) for v in (0, 1)])
    versions = [('A_current', None, 1.0, 0.0), ('B_proposed', gp, *proposed)]
    if args.alt:
        versions.append(('C_alternative', gp, *args.alt))
    for seq in TRANSITIONS:
        tag = '_'.join(f'{g}{t}' for g, t in seq)
        for label, prog, s, db in versions:
            p = out / '3_transitions' / f'{tag}_{label}.wav'
            files[str(p.relative_to(out))] = write_join(p, [render_cell(g, t, 0, prog, s, db) for g, t in seq])
    manifest = {'candidate': {'guitar': args.guitar, 'program': gp, 'preset': GUITAR_NAMES[gp],
                              'drum_scale': args.drum_scale, 'rock_master_db': args.master_db},
                'alternative': args.alt and {'drum_scale': args.alt[0], 'rock_master_db': args.alt[1]},
                'guitars': {k: GUITAR_NAMES[v] for k, v in GUITARS.items()},
                'mix_steps': [{'drum_scale': s, 'rock_master_db': db} for s, db in mixes],
                'plan': 'music_features_measured.cell_plan (melody-bank variants 0, 1; transitions variant 0)',
                'join': 'audition_v2.join_like_live (live tail_out crossfade, 8 bars + 0.25 bar)',
                'master_gain': 'fluidsynth -g = 0.8 * 10**(dB/20), Rock segments only',
                'sf2': str(args.sf2), 'files': files}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print(f'wrote {len(files)} WAVs + manifest.json under {out}')


GAIN_SEQUENCES = TRANSITIONS + [[('hiphop', 4), ('rock', 5), ('hiphop', 5)]]


def gains(args) -> None:
    """Rock level audition: each Rock cell between its live neighbours, Rock
    rendered float + fixed gain + limiter (neighbours exactly as live)."""
    from audition_v2 import trim_like_live

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    _init(args.sf2)
    gp = GUITARS[args.guitar]
    files: dict = {}
    for seq in GAIN_SEQUENCES:
        tag = '_'.join(f'{g}{t}' for g, t in seq)
        rock_tier = next(t for g, t in seq if g == 'rock')
        sub = out / f'rock{rock_tier}'
        sub.mkdir(exist_ok=True)
        others = {(g, t): render_cell(g, t, 0) for g, t in seq if g != 'rock'}
        pm0, tempo = compose('rock', rock_tier, 0, _R)
        p = sub / f'{tag}_0_original.wav'
        files[str(p.relative_to(out))] = write_join(p, [others.get(c) or render_cell(*c, 0) for c in seq])
        pm, stats = present(pm0, gp, args.drum_scale)
        for i, db in enumerate(args.gains, 1):
            audio, lim = render_gain(_R, pm, db)
            parts = [others.get(c) or (trim_like_live(audio, tempo), tempo) for c in seq]
            p = sub / f'{tag}_{i}_drums_x{args.drum_scale:.2f}_rock{db:+.0f}dB.wav'
            files[str(p.relative_to(out))] = write_join(p, parts) | {'limiter': lim, **stats}
            print(p.name, files[str(p.relative_to(out))]['segment_lufs'], lim)
    manifest = {'guitar': args.guitar, 'preset': GUITAR_NAMES[gp], 'drum_scale': args.drum_scale,
                'rock_gains_db': args.gains,
                'rock_render': f'fluidsynth -O float (same -g {_R.gain}), x10**(dB/20), look-ahead limiter '
                               f'ceiling {LIMIT_CEILING_DB} dBFS, window {LIMIT_WINDOW_S * 1000:.0f} ms',
                'original': 'Rock exactly as live today (16-bit fluidsynth, composed velocities)',
                'neighbours': 'exactly as live (16-bit fluidsynth); melody-bank variant 0',
                'join': 'audition_v2.join_like_live (live tail_out crossfade)', 'sf2': str(args.sf2),
                'files': files}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=1))
    print(f'wrote {len(files)} WAVs + manifest.json under {out}')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('census')
    c.add_argument('--sf2', required=True)
    c.add_argument('--out', required=True)
    c.add_argument('--variants', type=int, default=8)
    c.add_argument('--workers', type=int, default=6)
    p = sub.add_parser('package')
    p.add_argument('--sf2', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--guitar', choices=list(GUITARS), required=True)
    p.add_argument('--drum-scale', type=float, default=1.0, help='proposed drum scale (transitions)')
    p.add_argument('--drum-scales', type=lambda x: [float(v) for v in x.split(',')], default=[],
                   help='extra drum-scale steps for 2_mix (current x1.00 always included)')
    p.add_argument('--master-db', type=float, default=0.0, help='proposed fixed Rock gain (dB)')
    p.add_argument('--alt', type=lambda x: tuple(float(v) for v in x.split(',')), default=None,
                   help='alternative "drum_scale,master_db" (transitions C, 2_mix)')
    g = sub.add_parser('gains')
    g.add_argument('--sf2', required=True)
    g.add_argument('--out', required=True)
    g.add_argument('--guitar', choices=list(GUITARS), default='current')
    g.add_argument('--drum-scale', type=float, default=1.20)
    g.add_argument('--gains', type=lambda x: [float(v) for v in x.split(',')], default=[0.0, 2.0, 4.0, 6.0])
    args = ap.parse_args()
    {'census': census, 'package': package, 'gains': gains}[args.cmd](args)


if __name__ == '__main__':
    main()
