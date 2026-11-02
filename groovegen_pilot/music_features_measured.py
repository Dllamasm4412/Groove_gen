"""
Measured energy features per ladder cell (the composer-validation run that
music_features.py refers to). Stimulus-side measurements only: they describe
what the renderer plays, not how a listener responds.

Each (genre, tier) cell is rendered exactly as run_session_v2 plays it
(tier_tempo / tempo_default, RUNG_TIER_CAP clamp, MelodyBank(base_seed=0)
seeds, 8 bars + quarter-bar fade) for several melody-bank variants; variants
0-3 are the ones a live session uses.

Features (source, literature):
    lufs           integrated loudness, ITU-R BS.1770 (audio; intensity is the
                   strongest arousal cue: Gomez & Danuser 2007, Schubert 2004)
    drum_rate      distinct drum onsets/s, 20 ms merge (MIDI; accentuation /
                   event density: Gomez & Danuser 2007, Madison et al. 2011)
    tempo_bpm      played tempo (MIDI; Juslin & Laukka 2003,
                   Gabrielsson & Lindstrom 2010)
    centroid_hz    mean spectral centroid (audio; brightness: Eerola,
                   Lartillot & Toiviainen 2009, Yang et al. 2008)
    flux           mean onset strength / spectral flux (audio; same sources)
Reported only (no weight): per-role drum rates (low / backbeat / hats /
hand percussion), all-note onset rate, sub-250 Hz energy ratio, pulse
clarity, sample peak.

ENERGY_WEIGHTS follow the literature's rank order (intensity > rhythmic
density > tempo > timbre); none of the sources gives coefficients on these
scales, so the weights are checked by a perturbation test, not taken as betas.

Usage (writes to a disposable directory; never touches renders/frozen_v2):
    python music_features_measured.py --sf2 ../soundfonts/Musyng_Kite.sf2 \
        --out renders/smoke_audit/energy_<ts> [--variants 8] [--table energy_table_v1.json]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ENERGY_WEIGHTS = {'lufs': 0.40, 'drum_rate': 0.25, 'tempo_bpm': 0.20,
                  'centroid_hz': 0.10, 'flux': 0.05}

DRUM_ROLES = {
    'low': (35, 36),
    'backbeat': (37, 38, 39, 40),
    'hats': (42, 44, 46, 49, 51, 52, 53, 55, 57, 59),
}
ONSET_MERGE_S = 0.02
BARS = 8
BEATS_PER_BAR = 4
FADE_BARS = 0.25
SR = 44100

FIELDS = ['genre', 'tier', 'variant', 'seed', 'tempo_bpm', 'lufs', 'peak_dbfs',
          'drum_rate', 'drum_low_rate', 'drum_backbeat_rate', 'drum_hats_rate',
          'drum_hand_rate', 'note_rate', 'centroid_hz', 'flux', 'low_ratio',
          'pulse_clarity']


def _onset_rate(times, dur_s):
    t = np.sort(np.asarray([x for x in times if x < dur_s - 1e-6], float))
    if len(t) == 0:
        return 0.0
    n = 1 + int(np.sum(np.diff(t) > ONSET_MERGE_S))
    return n / dur_s


def midi_features(pm, dur_s):
    drums = [n for inst in pm.instruments if inst.is_drum for n in inst.notes]
    known = {p for ps in DRUM_ROLES.values() for p in ps}
    out = {'drum_rate': _onset_rate([n.start for n in drums], dur_s)}
    for role, pitches in DRUM_ROLES.items():
        out[f'drum_{role}_rate'] = _onset_rate(
            [n.start for n in drums if n.pitch in pitches], dur_s)
    out['drum_hand_rate'] = _onset_rate(
        [n.start for n in drums if n.pitch not in known], dur_s)
    out['note_rate'] = _onset_rate(
        [n.start for inst in pm.instruments for n in inst.notes], dur_s)
    return out


def audio_features(audio, sr=SR):
    import librosa
    import pyloudnorm as pyln

    x = np.asarray(audio, np.float64)
    mono = x.mean(axis=1).astype(np.float32)
    out = {'lufs': float(pyln.Meter(sr).integrated_loudness(x)),
           'peak_dbfs': float(20 * np.log10(max(np.max(np.abs(x)), 1e-9)))}
    S = np.abs(librosa.stft(mono, n_fft=2048, hop_length=512))
    out['centroid_hz'] = float(np.mean(librosa.feature.spectral_centroid(S=S, sr=sr)))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    power = S ** 2
    out['low_ratio'] = float(power[freqs < 250].sum() / max(power.sum(), 1e-12))
    env = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=512)
    out['flux'] = float(np.mean(env))
    # Pulse clarity: max normalized autocorrelation of the onset envelope at
    # lags for 40-200 bpm (Lartillot et al. 2008, simplified).
    e = env - env.mean()
    ac = np.correlate(e, e, 'full')[len(e) - 1:]
    fps = sr / 512
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 40)
    out['pulse_clarity'] = float(np.max(ac[lo:hi]) / ac[0]) if ac[0] > 0 else 0.0
    return out


def cell_plan(genre, tier, variant):
    """(tempo, density, render seed, melody-bank seed) exactly as run_session_v2."""
    from composer import GENRE_CFG
    from melody_bank import MelodyBank
    from segment_renderer import RUNG_TIER_CAP, TIER_TO_DENSITY

    cfg = GENRE_CFG[genre]
    tempo = float(cfg.get('tier_tempo', {}).get(tier, cfg['tempo_default']))
    bank_seed = MelodyBank(variants_per_cell=4, base_seed=0)._seed_for_variant(genre, tier, variant)
    tier_c = max(1, min(tier, RUNG_TIER_CAP.get(genre, 5)))
    return tempo, TIER_TO_DENSITY[tier_c], bank_seed


def energy_audio(renderer, pm):
    """Render a segment for energy measurement: as played, minus the
    presentation gain and the master attenuation (segment_renderer.
    MASTER_GAIN_DB, one output level for every segment, so it carries no
    energy information; measuring at the reference level keeps the table,
    and so the ladder and certification envelopes, unchanged).

    The Rock render gain (composer.render_directive) is a loudness match by
    ear (developer listening, 2026-10-05), not extra energy; metered as
    energy it lifted rock:1 next to pop1 on the live ladder and the first
    v2c live run rotated pop -> rock1 (2026-10-05). The directive is dropped,
    so the segment takes the plain render (equal to the float render at
    0 dB to -95 dB); the composition, Rock's drum velocity scale included,
    is measured unchanged."""
    import copy
    from composer import RENDER_DIRECTIVE, render_directive

    if render_directive(pm) is not None:
        pm = copy.deepcopy(pm)
        pm.text_events = [e for e in pm.text_events
                          if not e.text.startswith(RENDER_DIRECTIVE)]
    return renderer._render_pm_to_audio(pm, master=False)


def measure_one(args):
    genre, tier, variant, sf2 = args
    from composer import generate_segment
    from segment_renderer import SymbolicSegmentRenderer

    r = SymbolicSegmentRenderer(sf2)
    tempo, density, bank_seed = cell_plan(genre, tier, variant)
    pm = generate_segment(genre, tempo_bpm=tempo, density=density,
                          duration_bars=BARS, seed=r._derive_seed(bank_seed))
    played_tempo = float(pm.get_tempo_changes()[1][0])
    bar_s = 60.0 / played_tempo * BEATS_PER_BAR
    dur_s = BARS * bar_s
    audio = energy_audio(r, pm)
    audio = audio[:int(round(BARS * bar_s * SR + FADE_BARS * bar_s * SR))]
    row = {'genre': genre, 'tier': tier, 'variant': variant, 'seed': bank_seed,
           'tempo_bpm': played_tempo}
    row.update(midi_features(pm, dur_s))
    row.update(audio_features(audio))
    return row


def cell_means(rows):
    out = {}
    for r in rows:
        out.setdefault((r['genre'], int(r['tier'])), []).append(r)
    return {k: {f: float(np.mean([float(r[f]) for r in v])) for f in FIELDS[4:]}
            for k, v in sorted(out.items())}


def energy_scores(means, weights=ENERGY_WEIGHTS):
    """Weighted z-score energy per cell (z over all cells in `means`)."""
    keys = list(means)
    e = np.zeros(len(keys))
    for f, w in weights.items():
        v = np.array([means[k][f] for k in keys])
        sd = v.std() or 1.0
        e += w * (v - v.mean()) / sd
    return dict(zip(keys, e.tolist()))


def energy_sd(rows, means, weights=ENERGY_WEIGHTS):
    """Within-cell SD (over variants) of per-render energy, using the z
    parameters of energy_scores (mean/SD over the cell means)."""
    keys = list(means)
    z = {f: (np.mean([means[k][f] for k in keys]),
             np.std([means[k][f] for k in keys]) or 1.0) for f in weights}
    per = {}
    for r in rows:
        e = sum(w * (float(r[f]) - z[f][0]) / z[f][1] for f, w in weights.items())
        per.setdefault((r['genre'], int(r['tier'])), []).append(e)
    return {k: float(np.std(v)) for k, v in per.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sf2', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--variants', type=int, default=8)
    ap.add_argument('--genres', default=None, help='comma list (default all)')
    ap.add_argument('--table', default=None, help='write cell-mean table JSON here')
    ap.add_argument('--workers', type=int, default=6)
    args = ap.parse_args()

    from composer import GENRE_CFG
    genres = args.genres.split(',') if args.genres else sorted(GENRE_CFG)
    jobs = [(g, t, v, args.sf2) for g in genres for t in range(1, 6)
            for v in range(args.variants)]
    with ProcessPoolExecutor(args.workers) as ex:
        rows = list(ex.map(measure_one, jobs))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    per_render = out / 'renders.csv'
    with per_render.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f'{r[k]:.6g}' if isinstance(r[k], float) else r[k]) for k in FIELDS})
    digest = hashlib.sha256(per_render.read_bytes()).hexdigest()
    print(f'{len(rows)} renders -> {per_render} sha256 {digest[:16]}')

    if args.table:
        means = cell_means(rows)
        sds = energy_sd(rows, means)
        table = {
            'description': 'Measured per-cell energy features (music_features_measured.py); '
                           'cell means over melody-bank variants. Stimulus-side only.',
            'excludes': 'presentation render gain (composer.render_directive; see energy_audio)',
            'weights': ENERGY_WEIGHTS,
            'variants': args.variants,
            'renders_sha256': digest,
            # Noise band for ladder tie ordering: median within-cell energy SD.
            'tie_band_e': round(float(np.median(list(sds.values()))), 5),
            'cells': {f'{g}:{t}': {**{k: round(v, 5) for k, v in m.items()},
                                   'energy_sd': round(sds[(g, t)], 5)}
                      for (g, t), m in means.items()},
        }
        Path(args.table).write_text(json.dumps(table, indent=1) + '\n')
        print(f'table -> {args.table}')


if __name__ == '__main__':
    main()
