"""
Stimulus certification, Phase 2b (LIVE_GENERATION_PLAN.md section 6.7):
compares the v1 bank generator with the v2 session generator per live cell,
on MIDI and (with --audio) on rendered audio. Measures only; changes nothing.

Sources (kept separate in every output)
-------
    v1_live     the live bank path: MelodyBank(4, 0) rotation, --visits
                visits per cell (4 distinct segments, then repeats). The
                repetition baseline, and the old 4-seed reference.
    v1_wide     the wider same-cell reference: the unchanged composer at the
                cell's tempo and density for bank variants 0..--wide-variants-1
                (MelodyBank._seed_for_variant through _derive_seed, as
                run_session_v2 seeds it). Variants 0-3 are the v1_live
                segments. Cell envelopes and allowed drum voices come from here;
                the audio envelope uses the first --audio-variants of them.
    v2_base     the base segment of each v2 block (plain composer output at a
                v2 base seed). Used to attribute a v2 miss to the variation
                layer or to the base seed.
    v2_session  SessionComposer(stim_seed), visits 0..--visits-1 per cell,
                for each --stim-seeds value.

Checks (thresholds provisional; constants below)
------
    locked      tempo, tempo-map length, bar count and GM programs equal the
                cell's v1_wide value; with --audio, trimmed render length too.
    voices      drum voices a subset of the v1_wide union (the 4-seed v1_live
                union is reported beside it).
    envelope    each gated MIDI feature (and, with --audio, A1 audio feature)
                inside [min - 0.25 SD, max + 0.25 SD] of v1_wide. For features
                the energy guard bounds, the pad is at least the guard's
                tolerance: v1 does not vary drum_onbeat_ratio at all in calm,
                hiphop, rock and latin (SD 0), and a zero-width envelope
                would reject every guard-approved hat move. A miss is
                attributed to the variation if the segment's base is inside,
                else to the base seed.
    shift       cell mean of v2 vs v1_wide (cell shift) and mean of v2 minus
                its own base (variation shift); A2 limits.
    spread      A3: SD of per-segment energy E (v2) <= 1.25 x v1_wide SD.
    repetition  R1, R2, R3, R4, R6 for v1_live and v2_session over the same
                visits; improvement and section 2 targets.
    key         hiphop / rock key root from the frozen cell's own choice
                (composer.arrangement.cell_key); other genres have fixed keys.
    novelty     A6 novelty balance (plan 6.11): C1 = within a v2 block (visit
                shares the previous visit's base seed), the fraction of the 8
                drum bars whose onset set occurs nowhere in the previous visit.
                Passes if the mean C1 >= 1/8 (one new bar per visit) and the
                OLS slope of the cell means on ladder u (the measured energy
                position), divided by the mean, is within +-0.25. The 0.25 is
                a provisional engineering threshold, not perceptually
                validated. Spearman rho, the within-genre tier trend and the
                bootstrap interval are diagnostics, not gates.
                r4_energy_rho_diagnostic: the old A6 (Spearman u vs mean R4,
                old limit 0.3), diagnostic only. R4 is note-level, so it rises
                with drum density, and over all visits it mostly measures v1
                base-seed change at block boundaries.

Usage (writes only under renders/, never frozen_v2; no audio or MIDI is saved):
    python certify_stimuli.py                                  # MIDI only
    python certify_stimuli.py --audio --sf2 Musyng_Kite.sf2    # + Tier A
    python certify_stimuli.py --cells pop:3,hiphop:1 --visits 6 --wide-variants 16
Outputs in <out> (default renders/certification/<stamp>/):
    certification.csv          one row per segment, all sources
    certification_summary.json per-cell reference, checks and verdicts
    cell_summary.csv           one row per cell (verdict columns)
"""

from __future__ import annotations

import argparse
import csv
import functools
import hashlib
import json
import math
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

import stimulus_metrics as sm
from stimulus_audit import (BARS, FADE_BARS, HERE, ROW_FIELDS, SAMPLE_RATE, BankGenerator,
                            SessionGenerator, _csv_value, _stats, audit_trajectory,
                            code_provenance, live_ladder)

SOURCES = ('v1_live', 'v1_wide', 'v2_base', 'v2_session')
ENV_PAD_SD = 0.25
# MIDI features checked against the cell envelope. Per-role drum rates are
# reported only (plan 4.9: fills re-voice hats as snare / conga by design).
MIDI_GATED = ('drum_rate', 'note_rate', 'drum_onbeat_ratio', 'vel_mean', 'vel_p90',
              'drum_vel_mean', 'pitched_vel_mean', 'pitched_pitch_median',
              'pitched_pitch_p05', 'pitched_pitch_p95')
MIDI_REPORTED = ('drum_low_rate', 'drum_backbeat_rate', 'drum_hats_rate', 'drum_hand_rate')
AUDIO_FIELDS = ('render_ms', 'raw_render_s', 'rendered_s', 'lufs', 'rms_dbfs', 'peak_dbfs',
                'centroid_hz', 'flux', 'low_ratio', 'pulse_clarity', 'energy_e')
AUDIO_GATED = ('lufs', 'centroid_hz', 'flux', 'low_ratio', 'pulse_clarity', 'energy_e')   # A1
MEAN_SHIFT_SD = 0.5            # A2: cell mean shift, in v1_wide SDs
LUFS_SHIFT_LU = 0.5            # A2: LUFS mean shift
E_SPREAD_RATIO = 1.25          # A3
SEG_LUFS_LU = 0.5              # per segment, varied vs its own base (reported)
MAX_FALLBACK_RATE = 0.05
R1_MIN = {'hiphop': 2, 'rock': 2}
R1_MIN_DEFAULT = 3
R2_MAX = 3
DRUM_REPEAT_MIN_VISITS = 5     # no drum-layer repeat within 4 visits of a cell
BAR4_MIN_RATE = 0.5
OLD_A6_R4_MAX_RHO = 0.3        # old R4 A6 limit, reported with the diagnostic only
NOVELTY_MAX_REL_CHANGE = 0.25  # A6: |OLS slope of C1 on u| / mean C1; provisional, not perceptually validated
NOVELTY_MIN_MEAN = 1 / BARS    # A6: mean C1 floor (one new drum bar per visit)
NOVELTY_BOOT = 2000

CERT_FIELDS = list(dict.fromkeys(
    ['source', 'stim_seed', 'key_root'] + ROW_FIELDS
    + ['base_midi_sha256', 'locked_ok', 'voices_outside_live4', 'voices_outside_wide',
       'midi_env_miss', 'midi_env_miss_variation', 'midi_env_miss_base']
    + list(AUDIO_FIELDS)
    + ['audio_env_miss', 'audio_env_miss_variation', 'audio_env_miss_base',
       'd_lufs_vs_base', 'd_centroid_hz_vs_base', 'd_flux_vs_base', 'd_energy_e_vs_base',
       'segment_ok']
    + ['same_base_as_prev', 'new_drum_bar_frac', 'new_drum_patterns', 'changed_drum_bar_frac']))


# =============================================================================
# Pure checks (tested in tests/test_certify_stimuli.py)
# =============================================================================


def _finite(vals: Iterable) -> list[float]:
    out = []
    for v in vals:
        if v is None or isinstance(v, (str, bool)):
            continue
        f = float(v)
        if not math.isnan(f):
            out.append(f)
    return out


def envelope(vals: Iterable, pad_sd: float = ENV_PAD_SD, min_pad: float = 0.0) -> Optional[dict]:
    """[min - pad, max + pad] with pad = max(pad_sd * SD, min_pad); None if no values."""
    v = _finite(vals)
    if not v:
        return None
    sd = float(np.std(v))
    pad = max(pad_sd * sd, min_pad)
    return {'n': len(v), 'mean': float(np.mean(v)), 'sd': sd, 'min': min(v), 'max': max(v),
            'lo': min(v) - pad, 'hi': max(v) + pad, 'pad_floor_applied': min_pad > pad_sd * sd}


def in_envelope(x, env: Optional[dict], eps: float = 1e-9) -> Optional[bool]:
    """None when there is nothing to check (no envelope, or a missing / NaN value)."""
    if env is None or not _finite([x]):
        return None
    return env['lo'] - eps <= float(x) <= env['hi'] + eps


def guard_floor(feature: str, ref_mean: float) -> float:
    """The energy guard's per-segment tolerance for a feature, in its own units (0 if unguarded)."""
    from composer.energy_guard import BOUNDS

    if feature not in BOUNDS:
        return 0.0
    kind, tol = BOUNDS[feature]
    return tol * abs(ref_mean) if kind == 'rel' else tol


def envelope_misses(row: dict, envs: dict) -> list[str]:
    return sorted(f for f, env in envs.items() if in_envelope(row.get(f), env) is False)


def attribute_misses(misses: Iterable[str], base_misses: Iterable[str]) -> tuple[list, list]:
    """(caused by the variation, caused by the base seed): a miss is the base's
    if the segment's own base segment misses the same feature."""
    m, b = set(misses), set(base_misses)
    return sorted(m - b), sorted(m & b)


def shift_check(ref: Optional[dict], seg_vals: Iterable, deltas: Iterable, allowed: float,
                n_bases: int = 0) -> Optional[dict]:
    """Cell shift (v2 mean - reference mean), split into the variation part
    (mean of v2 - own base) and the base part (the rest: which base seeds the
    schedule drew). The variation part must be within `allowed`. The base
    part is sampling of the unchanged composer, so it is flagged only beyond
    both `allowed` and 2 standard errors of a mean of n_bases draws."""
    v, d = _finite(seg_vals), _finite(deltas)
    if ref is None or not v:
        return None
    cell = float(np.mean(v)) - ref['mean']
    var = float(np.mean(d)) if d else 0.0
    sd = ref['sd']
    se = sd / math.sqrt(n_bases) if n_bases else 0.0
    return {'ref_mean': round(ref['mean'], 5), 'ref_sd': round(sd, 5), 'v2_mean': round(float(np.mean(v)), 5),
            'allowed': round(allowed, 5),
            'cell_shift': round(cell, 5), 'cell_shift_sd': round(cell / sd, 3) if sd > 0 else None,
            'cell_ok': abs(cell) <= allowed + 1e-9,
            'variation_shift': round(var, 5), 'variation_shift_sd': round(var / sd, 3) if sd > 0 else None,
            'variation_ok': abs(var) <= allowed + 1e-9,
            'base_shift': round(cell - var, 5), 'n_bases': n_bases, 'base_se': round(se, 5),
            'base_ok': abs(cell - var) <= max(allowed, 2 * se) + 1e-9}


def energy_z_params(table: dict) -> dict[str, tuple[float, float]]:
    """(mean, SD) over the table's cell means per weighted feature, as
    music_features_measured.energy_scores / energy_sd compute them."""
    out = {}
    for f in table['weights']:
        v = np.array([c[f] for c in table['cells'].values()], float)
        out[f] = (float(v.mean()), float(v.std()) or 1.0)
    return out


def segment_energy(feats: dict, z: dict, weights: dict) -> float:
    """Per-segment energy E on the energy table's z scale."""
    return float(sum(w * (float(feats[f]) - z[f][0]) / z[f][1] for f, w in weights.items()))


def rms_dbfs(audio: np.ndarray) -> float:
    x = np.asarray(audio, np.float64)
    return float(20 * np.log10(max(float(np.sqrt(np.mean(x ** 2))), 1e-12)))


def key_changes(keys: Iterable) -> int:
    """Changes between consecutive known keys (None skipped)."""
    k = [x for x in keys if x is not None]
    return sum(1 for a, b in zip(k, k[1:]) if a != b)


def repetition_stats(rows: list[dict]) -> dict:
    """R1-R4, R6 over one source's segments of one cell (R3 within each trajectory)."""
    later = [r for r in rows if r['visit_idx'] > 0]
    r1 = _finite(r['distinct_drum_bars'] for r in rows)
    r2 = _finite(r['max_identical_drum_run'] for r in rows)
    drum_d = _finite(r['drum_repeat_dist_visits'] for r in rows)
    full_d = _finite(r['repeat_dist_visits'] for r in rows)

    def rate(vals):
        v = [bool(x) for x in vals]
        return round(sum(v) / len(v), 4) if v else None

    return {
        'n': len(rows),
        'r1_distinct_drum_bars_mean': round(float(np.mean(r1)), 3) if r1 else None,
        'r1_distinct_drum_bars_min': min(r1, default=None),
        'r2_max_identical_drum_run': max(r2, default=None),
        'r3_exact_repeat_rate': rate(r['repeat_dist_visits'] is not None for r in later),
        'r3_drum_repeat_rate': rate(r['drum_repeat_dist_visits'] is not None for r in later),
        'r3_min_repeat_dist_visits': min(full_d, default=None),
        'r3_min_drum_repeat_dist_visits': min(drum_d, default=None),
        'r4_near_repeat_drum_mean': (round(float(np.mean(_finite(r.get('near_repeat_drum') for r in rows))), 4)
                                     if _finite(r.get('near_repeat_drum') for r in rows) else None),
        'r6_bar8_rate': rate(r['phrase_end_bar8_marked'] for r in rows),
        'r6_bar4_rate': rate(r['phrase_end_bar4_marked'] for r in rows),
    }


def drum_bar_novelty(prev: list[frozenset], cur: list[frozenset]) -> dict:
    """Bar-level drum novelty of a visit against the previous visit to its cell.
    A bar is its drum onset set (track key, pitch, grid pos). new = occurs nowhere
    in prev (shift-tolerant); changed = differs from the same bar of prev."""
    seen = set(prev)
    return {'new_drum_bar_frac': round(sum(b not in seen for b in cur) / len(cur), 4),
            'new_drum_patterns': len(set(cur) - seen),
            'changed_drum_bar_frac': round(sum(a != b for a, b in zip(prev, cur)) / len(cur), 4)}


def novelty_stats(rows: list[dict]) -> dict:
    """Cell means of the bar-level novelty, split by whether the visit shares the
    previous visit's base (within a v2 block) or not (new block; every v1 visit)."""
    later = [r for r in rows if r.get('new_drum_bar_frac') is not None]
    out: dict[str, Any] = {}
    for tag, sel in (('within_block', [r for r in later if r['same_base_as_prev']]),
                     ('new_block', [r for r in later if not r['same_base_as_prev']])):
        out[f'n_{tag}'] = len(sel)
        for k in ('new_drum_bar_frac', 'new_drum_patterns', 'changed_drum_bar_frac'):
            out[f'{tag}_{k}'] = round(float(np.mean([r[k] for r in sel])), 4) if sel else None
    return out


def novelty_balance(per_cell: dict[str, dict]) -> dict:
    """A6 novelty balance (plan 6.11): does within-block drum novelty vary with
    ladder u? per_cell: name -> {'u', 'genre', 'tier', 'values'} (the within-block
    new_drum_bar_frac of each visit). Gated: mean and the OLS change per unit u
    relative to the mean. 'diagnostic' (not gated): Spearman rho, the within-genre
    tier trend (the global slope still reflects genre placement on the ladder),
    u-third means and a bootstrap over visits within cells (fixed seed)."""
    from scipy.stats import spearmanr

    cells = sorted(c for c, d in per_cell.items() if d['values'])
    out: dict[str, Any] = {'criterion': 'A6 novelty balance', 'metric': 'within_block_new_drum_bar_frac',
                           'energy_axis': 'ladder u', 'n_cells': len(cells),
                           'min_mean': NOVELTY_MIN_MEAN, 'max_abs_rel_change': NOVELTY_MAX_REL_CHANGE,
                           'threshold_status': 'provisional engineering threshold, not perceptually validated'}
    if len(cells) < 3:
        return {**out, 'ok': None}
    u = np.array([per_cell[c]['u'] for c in cells])
    vals = [np.asarray(per_cell[c]['values'], float) for c in cells]
    m = np.array([v.mean() for v in vals])

    def rel_change(means):
        return float(np.polyfit(u, means, 1)[0] / means.mean()) if means.mean() > 0 else float('nan')

    rng = np.random.default_rng(0)
    boot = [rel_change(np.array([rng.choice(v, len(v)).mean() for v in vals])) for _ in range(NOVELTY_BOOT)]
    rho = spearmanr(u, m).statistic if len(set(m)) > 1 else float('nan')
    tier_rho, weights = [], []
    for g in sorted({per_cell[c]['genre'] for c in cells}):
        cs_g = [c for c in cells if per_cell[c]['genre'] == g]
        gm = [m[cells.index(c)] for c in cs_g]
        if len(cs_g) >= 3 and len(set(gm)) > 1:
            tier_rho.append(spearmanr([per_cell[c]['tier'] for c in cs_g], gm).statistic)
            weights.append(len(cs_g) - 1)
    rc = rel_change(m)
    lo, hi = u <= np.quantile(u, 1 / 3), u >= np.quantile(u, 2 / 3)
    r = lambda x: None if x is None or math.isnan(x) else round(float(x), 4)
    out.update({
        'mean': r(m.mean()), 'min': r(m.min()), 'max': r(m.max()),
        'min_cell': cells[int(m.argmin())], 'max_cell': cells[int(m.argmax())],
        'rel_change_per_u': r(rc),
        'ok': bool(m.mean() >= NOVELTY_MIN_MEAN and abs(rc) <= NOVELTY_MAX_REL_CHANGE),
        'diagnostic': {
            'rel_change_boot95': [r(np.nanpercentile(boot, 2.5)), r(np.nanpercentile(boot, 97.5))],
            'rho_u': r(rho),
            'within_genre_tier_rho': r(np.average(tier_rho, weights=weights)) if weights else None,
            'low_u_third_mean': r(m[lo].mean()), 'high_u_third_mean': r(m[hi].mean()),
        },
    })
    return out


def repetition_compare(v1: dict, v2: dict, genre: str) -> dict:
    """Per metric: 'improved' / 'unchanged' / 'worse' (v2 vs v1), and v2 targets.
    A metric that is worse but still meets its target is not a regression (for
    example latin's alternating clave has R2 = 1 in v1)."""
    # (key, direction: +1 higher is better, -1 lower is better)
    metrics = (('r1_distinct_drum_bars_mean', 1), ('r2_max_identical_drum_run', -1),
               ('r3_exact_repeat_rate', -1), ('r3_drum_repeat_rate', -1),
               ('r6_bar8_rate', 1), ('r6_bar4_rate', 1))
    status = {}
    for k, sign in metrics:
        a, b = v1.get(k), v2.get(k)
        if a is None or b is None:
            status[k] = None
        else:
            d = sign * (b - a)
            status[k] = 'improved' if d > 1e-9 else 'worse' if d < -1e-9 else 'unchanged'
    md = v2.get('r3_min_drum_repeat_dist_visits')
    targets = {
        'r1': (v2['r1_distinct_drum_bars_min'] or 0) >= R1_MIN.get(genre, R1_MIN_DEFAULT),
        'r2': (v2['r2_max_identical_drum_run'] or 99) <= R2_MAX,
        'r3_full': not v2['r3_exact_repeat_rate'],
        'r3_drum': md is None or md >= DRUM_REPEAT_MIN_VISITS,
        'r6_bar8': v2['r6_bar8_rate'] == 1.0,
        'r6_bar4': (v2['r6_bar4_rate'] or 0) >= BAR4_MIN_RATE,
    }
    target_of = {'r1_distinct_drum_bars_mean': 'r1', 'r2_max_identical_drum_run': 'r2',
                 'r3_exact_repeat_rate': 'r3_full', 'r3_drum_repeat_rate': 'r3_drum',
                 'r6_bar8_rate': 'r6_bar8', 'r6_bar4_rate': 'r6_bar4'}
    regressions = [k for k, s in status.items() if s == 'worse' and not targets[target_of[k]]]
    return {'status': status, 'targets': targets,
            'improved': any(s == 'improved' for s in status.values()) and not regressions,
            'regressions': regressions, 'targets_met': all(targets.values())}


# =============================================================================
# Generation
# =============================================================================


class _Capture:
    """Wraps a generator so audit_trajectory's segments can be rendered afterwards."""

    def __init__(self, gen_cls, store: list):
        self.gen = gen_cls()
        self.store = store
        self.live_path = self.gen.live_path
        self.config = self.gen.config

    def generate(self, genre: str, tier: int):
        pm, plan = self.gen.generate(genre, tier)
        self.store.append(pm)
        return pm, plan


class SeedListGenerator:
    """Plain composer output at the cell's tempo and density for a fixed seed list (v2 bases)."""

    name = 'seed_list'
    live_path = False

    def __init__(self, seeds: list[int]):
        self.seeds = list(seeds)
        self.i = 0
        self.config = {}

    def generate(self, genre: str, tier: int):
        from composer import generate_segment
        from composer.arrangement import cell_plan

        tempo, density = cell_plan(genre, tier)
        seed = self.seeds[self.i]
        self.i += 1
        pm = generate_segment(genre, tempo_bpm=tempo, density=density, duration_bars=BARS, seed=seed)
        return pm, {'planned_tempo_bpm': tempo, 'density': density, 'seed': None, 'composer_seed': seed}


def _run(name: str, source: str, n: int, genre: str, tier: int, gen_cls, stim_seed=None):
    """audit_trajectory over n segments of one cell; rows tagged, plus the MIDI."""
    from composer.arrangement import cell_key

    store: list = []
    rows = audit_trajectory(name, [{'genre': genre, 'tier': tier}] * n,
                            functools.partial(_Capture, gen_cls, store))
    for r in rows:
        r['source'] = source
        r['stim_seed'] = stim_seed
        r['key_root'] = cell_key(genre, tier, r['composer_seed'])
    if source in ('v1_live', 'v2_session'):
        # bar-level novelty vs the previous visit; a v1 bank variant is its own base
        prev = None
        for r, pm in zip(rows, store):
            sets = sm.bar_onset_sets(pm, BARS, 'drum')
            base = r['base_seed'] if r.get('base_seed') is not None else r['composer_seed']
            if prev is not None:
                r['same_base_as_prev'] = base == prev[1]
                r.update(drum_bar_novelty(prev[0], sets))
            prev = (sets, base)
    return rows, store


def generate_cell(genre: str, tier: int, visits: int, wide_variants: int,
                  stim_seeds: list[int], develop: bool = False) -> tuple[list[dict], dict]:
    """All four sources for one cell: rows, and midi_sha256 -> PrettyMIDI."""
    rows: list[dict] = []
    pms: dict = {}

    def add(res):
        r, s = res
        rows.extend(r)
        for row, pm in zip(r, s):
            pms.setdefault(row['midi_sha256'], pm)

    add(_run(f'v1_live:{genre}{tier}', 'v1_live', visits, genre, tier, BankGenerator))
    add(_run(f'v1_wide:{genre}{tier}', 'v1_wide', wide_variants, genre, tier,
             functools.partial(BankGenerator, variants_per_cell=wide_variants)))
    for s in stim_seeds:
        v2, v2_pms = _run(f'v2_s{s}:{genre}{tier}', 'v2_session', visits, genre, tier,
                          functools.partial(SessionGenerator, stim_seed=s, develop=develop), stim_seed=s)
        add((v2, v2_pms))
        bases = list(dict.fromkeys(r['base_seed'] for r in v2))
        add(_run(f'v2_base_s{s}:{genre}{tier}', 'v2_base', len(bases), genre, tier,
                 functools.partial(SeedListGenerator, bases), stim_seed=s))
    return rows, pms


# =============================================================================
# Rendering (--audio)
# =============================================================================

_RENDERER = None


def _init_worker(sf2: str) -> None:
    global _RENDERER
    from segment_renderer import SymbolicSegmentRenderer
    _RENDERER = SymbolicSegmentRenderer(sf2_path=sf2, sr=SAMPLE_RATE, session_seed=42)


def render_one(job: tuple) -> tuple[str, dict]:
    """music_features_measured.measure_one's recipe: render without the
    presentation gain (energy_audio), trim to 8 bars + fade, audio_features.
    The sha check makes sure the rendered MIDI is the one the row describes."""
    from music_features_measured import audio_features, energy_audio

    sha, pm = job
    if sm.midi_sha256(pm) != sha:
        raise RuntimeError(f'MIDI changed in transit: {sha[:12]}')
    t0 = time.perf_counter()
    audio = energy_audio(_RENDERER, pm)
    render_ms = (time.perf_counter() - t0) * 1e3
    bar_s = sm.bar_seconds(sm.played_tempo(pm))
    raw_s = len(audio) / SAMPLE_RATE
    audio = audio[:int(round(BARS * bar_s * SAMPLE_RATE + FADE_BARS * bar_s * SAMPLE_RATE))]
    out = {'render_ms': round(render_ms, 1), 'raw_render_s': round(raw_s, 4),
           'rendered_s': round(len(audio) / SAMPLE_RATE, 4), 'rms_dbfs': rms_dbfs(audio)}
    out.update(audio_features(audio, SAMPLE_RATE))
    return sha, out


def render_all(pms: dict, sf2: str, workers: int) -> dict[str, dict]:
    jobs = sorted(pms.items())
    with ProcessPoolExecutor(workers, initializer=_init_worker, initargs=(sf2,)) as ex:
        return dict(ex.map(render_one, jobs, chunksize=4))


def _file_sha256(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


# =============================================================================
# Per-segment checks
# =============================================================================


def _locked(r: dict) -> str:
    return json.dumps({f: r[f] for f in sm.LOCKED_FEATURES}, sort_keys=True)


def cell_reference(rows: list[dict], audio: bool) -> dict:
    wide = [r for r in rows if r['source'] == 'v1_wide']
    live = [r for r in rows if r['source'] == 'v1_live']
    ref = {
        'n_wide': len(wide),
        'locked': sorted({_locked(r) for r in wide}),
        'voices_live4': sorted({v for r in live for v in r['drum_voices']}),
        'voices_wide': sorted({v for r in wide for v in r['drum_voices']}),
        'midi_env': {},
        'audio_env': {},
    }
    for f in MIDI_GATED + MIDI_REPORTED:
        vals = [r[f] for r in wide]
        m = _finite(vals)
        ref['midi_env'][f] = envelope(vals, min_pad=guard_floor(f, float(np.mean(m))) if m else 0.0)
    if audio:
        wa = [r for r in wide if r.get('lufs') is not None]
        ref['n_wide_audio'] = len(wa)
        ref['rendered_s'] = sorted({r['rendered_s'] for r in wa})
        for f in AUDIO_GATED + ('rms_dbfs', 'render_ms'):
            ref['audio_env'][f] = envelope(r[f] for r in wa)
    return ref


def check_segment(r: dict, ref: dict, base: Optional[dict], audio: bool) -> None:
    """Fills the per-segment check columns of a v2_session or v2_base row."""
    gated_midi = {f: ref['midi_env'][f] for f in MIDI_GATED}
    r['locked_ok'] = _locked(r) in ref['locked'] and bool(r['tempo_matches_plan'])
    r['voices_outside_live4'] = sorted(set(r['drum_voices']) - set(ref['voices_live4']))
    r['voices_outside_wide'] = sorted(set(r['drum_voices']) - set(ref['voices_wide']))
    r['midi_env_miss'] = envelope_misses(r, gated_midi)
    ok = r['locked_ok'] and not r['voices_outside_wide'] and not r['midi_env_miss']
    if base is not None:
        r['base_midi_sha256'] = base['midi_sha256']
        r['midi_env_miss_variation'], r['midi_env_miss_base'] = attribute_misses(
            r['midi_env_miss'], envelope_misses(base, gated_midi))
    if audio:
        gated_audio = {f: ref['audio_env'][f] for f in AUDIO_GATED}
        r['locked_ok'] = r['locked_ok'] and r['rendered_s'] in ref['rendered_s']
        r['audio_env_miss'] = envelope_misses(r, gated_audio)
        ok = ok and r['locked_ok'] and not r['audio_env_miss']
        if base is not None:
            r['audio_env_miss_variation'], r['audio_env_miss_base'] = attribute_misses(
                r['audio_env_miss'], envelope_misses(base, gated_audio))
            for f in ('lufs', 'centroid_hz', 'flux', 'energy_e'):
                r[f'd_{f}_vs_base'] = round(r[f] - base[f], 5)
    if r['source'] == 'v2_session':
        ok = ok and not r['gen_fallback']
    r['segment_ok'] = ok


# =============================================================================
# Per-cell summary
# =============================================================================


def _miss_counts(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        for f in r.get(key) or []:
            out[f] = out.get(f, 0) + 1
    return dict(sorted(out.items()))


def _deltas(v2: list[dict], by_sha: dict, f: str) -> list:
    return [r[f] - by_sha[r['base_midi_sha256']][f] for r in v2
            if _finite([r.get(f)]) and _finite([by_sha[r['base_midi_sha256']].get(f)])]


def _shift_attention(layer: str, f: str, s: dict) -> list[str]:
    out = []
    if not s['variation_ok']:
        out.append(f'{layer} variation shift {f}: {s["variation_shift"]:+g} (allowed {s["allowed"]:g})')
    if not s['base_ok']:
        out.append(f'{layer} base-seed mean shift {f}: {s["base_shift"]:+g} over {s["n_bases"]} bases '
                   f'(allowed {max(s["allowed"], 2 * s["base_se"]):g})')
    return out


def summarize_cell(cell: str, rows: list[dict], ref: dict, audio: bool, tie_band_e: Optional[float]) -> dict:
    genre = cell.split(':')[0]
    live = [r for r in rows if r['source'] == 'v1_live']
    wide = [r for r in rows if r['source'] == 'v1_wide']
    v2 = [r for r in rows if r['source'] == 'v2_session']
    bases = [r for r in rows if r['source'] == 'v2_base']
    by_sha = {r['midi_sha256']: r for r in bases}

    rep_v1, rep_v2 = repetition_stats(live), repetition_stats(v2)
    rep = repetition_compare(rep_v1, rep_v2, genre)
    n_bases = len({r['base_midi_sha256'] for r in v2})

    midi_shift = {}
    for f in MIDI_GATED + MIDI_REPORTED:
        env = ref['midi_env'][f]
        allowed = MEAN_SHIFT_SD * env['sd'] if env else 0.0
        if env and f in MIDI_GATED:
            allowed = max(allowed, 0.5 * guard_floor(f, env['mean']))
        midi_shift[f] = shift_check(env, (r[f] for r in v2), _deltas(v2, by_sha, f), allowed, n_bases)
        if midi_shift[f] is not None:
            midi_shift[f]['gated'] = f in MIDI_GATED
    fallback_rate = round(sum(bool(r['gen_fallback']) for r in v2) / len(v2), 4) if v2 else None

    out: dict[str, Any] = {
        'reference': {
            'n_v1_live': len(live), 'n_v1_live_unique': len({r['midi_sha256'] for r in live}),
            'n_v1_wide': len(wide), 'n_v2_session': len(v2), 'n_v2_base': len(bases),
            'locked': [json.loads(x) for x in ref['locked']],
            'voices_live4': ref['voices_live4'], 'voices_wide': ref['voices_wide'],
            'midi_envelope': {f: {k: round(v, 5) if isinstance(v, float) else v for k, v in e.items()}
                              for f, e in ref['midi_env'].items() if e},
        },
        'repetition': {'v1_live': rep_v1, 'v2_session': rep_v2, **rep},
        'novelty': {'v1_live': novelty_stats(live), 'v2_session': novelty_stats(v2)},
        'midi': {
            'locked_ok_rate': round(sum(bool(r['locked_ok']) for r in v2) / len(v2), 4) if v2 else None,
            'voices_v2': sorted({v for r in v2 for v in r['drum_voices']}),
            'voices_outside_live4': sorted({v for r in v2 for v in r['voices_outside_live4']}),
            'voices_outside_wide': sorted({v for r in v2 for v in r['voices_outside_wide']}),
            'v2_base_voices_outside_live4': sorted({v for r in bases for v in r['voices_outside_live4']}),
            'envelope_miss': _miss_counts(v2, 'midi_env_miss'),
            'envelope_miss_variation': _miss_counts(v2, 'midi_env_miss_variation'),
            'envelope_miss_base': _miss_counts(v2, 'midi_env_miss_base'),
            'v2_base_envelope_miss': _miss_counts(bases, 'midi_env_miss'),
            'shift': midi_shift,
        },
        'fallback_rate': fallback_rate,
        'gen_ms': {'v1_live': _stats(r['gen_ms'] for r in live), 'v2_session': _stats(r['gen_ms'] for r in v2)},
        'segment_ok_rate': round(sum(bool(r['segment_ok']) for r in v2) / len(v2), 4) if v2 else None,
    }

    attention: list[str] = []
    variation_ok = (fallback_rate is not None and fallback_rate <= MAX_FALLBACK_RATE
                    and out['midi']['locked_ok_rate'] == 1.0 and not out['midi']['envelope_miss_variation']
                    and all(s['variation_ok'] for s in midi_shift.values() if s and s['gated']))
    in_range = not out['midi']['voices_outside_wide'] and not out['midi']['envelope_miss']
    if out['midi']['envelope_miss_variation']:
        attention.append(f"MIDI envelope miss caused by variation: {out['midi']['envelope_miss_variation']}")
    if out['midi']['envelope_miss_base']:
        attention.append(f"MIDI envelope miss from base seeds: {out['midi']['envelope_miss_base']}")
    if out['midi']['voices_outside_wide']:
        attention.append(f"drum voices outside the wide reference: {out['midi']['voices_outside_wide']}")
    for f, s in midi_shift.items():
        attention += _shift_attention('MIDI', f, s) if s and s['gated'] else []

    if audio:
        a_shift = {}
        for f in AUDIO_GATED + ('rms_dbfs',):
            env = ref['audio_env'][f]
            if f in ('lufs', 'rms_dbfs'):
                allowed = LUFS_SHIFT_LU
            elif f == 'energy_e' and tie_band_e is not None:
                allowed = tie_band_e / 2
            else:
                allowed = MEAN_SHIFT_SD * env['sd'] if env else 0.0
            a_shift[f] = shift_check(env, (r[f] for r in v2), _deltas(v2, by_sha, f), allowed, n_bases)
        e_ref = ref['audio_env']['energy_e']
        e_v2 = _finite(r['energy_e'] for r in v2)
        a3 = {'v1_wide_sd': round(e_ref['sd'], 5), 'v2_sd': round(float(np.std(e_v2)), 5),
              'ratio': round(float(np.std(e_v2)) / e_ref['sd'], 3) if e_ref['sd'] > 0 else None,
              'ok': float(np.std(e_v2)) <= E_SPREAD_RATIO * e_ref['sd'] + 1e-9}
        d_lufs = _finite(r.get('d_lufs_vs_base') for r in v2)
        d_e = _finite(r.get('d_energy_e_vs_base') for r in v2)
        out['audio'] = {
            'reference': {'n_v1_wide_audio': ref['n_wide_audio'], 'rendered_s': ref['rendered_s'],
                          'envelope': {f: {k: round(v, 5) if isinstance(v, float) else v for k, v in e.items()}
                                       for f, e in ref['audio_env'].items() if e}},
            'rendered_s_v2': sorted({r['rendered_s'] for r in v2}),
            'envelope_miss': _miss_counts(v2, 'audio_env_miss'),
            'envelope_miss_variation': _miss_counts(v2, 'audio_env_miss_variation'),
            'envelope_miss_base': _miss_counts(v2, 'audio_env_miss_base'),
            'v2_base_envelope_miss': _miss_counts(bases, 'audio_env_miss'),
            'shift': a_shift,
            'a3_energy_spread': a3,
            'variation_vs_base': {
                'lufs_abs_max': round(max(map(abs, d_lufs)), 4) if d_lufs else None,
                'lufs_mean': round(float(np.mean(d_lufs)), 4) if d_lufs else None,
                'energy_e_abs_max': round(max(map(abs, d_e)), 5) if d_e else None,
                'n_over_seg_lufs_bound': sum(abs(x) > SEG_LUFS_LU for x in d_lufs),
            },
            'render_ms': {'v1_live': _stats(r['render_ms'] for r in live),
                          'v1_wide': _stats(r['render_ms'] for r in wide if r.get('render_ms') is not None),
                          'v2_session': _stats(r['render_ms'] for r in v2)},
        }
        variation_ok = (variation_ok and not out['audio']['envelope_miss_variation']
                        and all(s['variation_ok'] for s in a_shift.values() if s))
        in_range = in_range and not out['audio']['envelope_miss']
        if out['audio']['envelope_miss_variation']:
            attention.append(f"audio envelope miss caused by variation: {out['audio']['envelope_miss_variation']}")
        if out['audio']['envelope_miss_base']:
            attention.append(f"audio envelope miss from base seeds: {out['audio']['envelope_miss_base']}")
        for f, s in a_shift.items():
            attention += _shift_attention('audio', f, s) if s else []
        if not a3['ok']:
            attention.append(f'A3 energy spread ratio {a3["ratio"]}')
        if out['audio']['variation_vs_base']['n_over_seg_lufs_bound']:
            attention.append(f"{out['audio']['variation_vs_base']['n_over_seg_lufs_bound']} segments with "
                             f"|LUFS - base| > {SEG_LUFS_LU} LU")

    if rep['regressions']:
        attention.append(f"repetition regressions: {rep['regressions']}")
    if not rep['targets_met']:
        attention.append(f"repetition targets missed: {[k for k, v in rep['targets'].items() if not v]}")
    out['verdict'] = {'repetition_improved': rep['improved'], 'repetition_targets_met': rep['targets_met'],
                      'variation_controlled': bool(variation_ok), 'within_cell_range': bool(in_range),
                      'attention': attention}
    return out


def key_continuity(rows: list[dict]) -> dict:
    """Per genre: key roots over the live session order of v1_live and of each v2 stim seed."""
    out = {}
    for g in dict.fromkeys(r['genre'] for r in rows):
        g_rows = [r for r in rows if r['genre'] == g]
        live = [r['key_root'] for r in g_rows if r['source'] == 'v1_live']
        entry = {'key_source': 'frozen cell _resolve_spec' if any(live) else 'fixed by composer',
                 'v1_live': {'keys': sorted({k for k in live if k}), 'changes': key_changes(live)},
                 'v2_session': {}}
        for s in sorted({r['stim_seed'] for r in g_rows if r['source'] == 'v2_session'}):
            ks = [r['key_root'] for r in g_rows if r['source'] == 'v2_session' and r['stim_seed'] == s]
            entry['v2_session'][str(s)] = {'keys': sorted({k for k in ks if k}), 'changes': key_changes(ks)}
        entry['v2_tonal_collections'] = sorted({r['key_name'] for r in g_rows
                                                if r['source'] == 'v2_session' and r['key_name']})
        entry['v2_key_locked'] = all(v['changes'] == 0 for v in entry['v2_session'].values())
        out[g] = entry
    return out


def r4_energy_diagnostic(cells: list, summaries: dict) -> dict:
    """The old A6, diagnostic only: Spearman rho between ladder u and v2 mean R4
    drum similarity. Density- and base-change-confounded (plan 6.11), so it carries
    no pass/fail; A6 is novelty_balance."""
    from scipy.stats import spearmanr

    pairs = [(c.u, summaries[f'{c.genre}:{c.tier}']['repetition']['v2_session']['r4_near_repeat_drum_mean'])
             for c in cells if f'{c.genre}:{c.tier}' in summaries]
    pairs = [(u, r) for u, r in pairs if r is not None]
    if len(pairs) < 3:
        return {'n_cells': len(pairs), 'rho': None, 'old_limit_abs_rho': OLD_A6_R4_MAX_RHO,
                'role': 'diagnostic only, not an acceptance criterion'}
    rho = spearmanr([p[0] for p in pairs], [p[1] for p in pairs]).statistic
    rho = None if rho is None or math.isnan(rho) else round(float(rho), 4)
    return {'n_cells': len(pairs), 'rho': rho, 'old_limit_abs_rho': OLD_A6_R4_MAX_RHO,
            'role': 'diagnostic only, not an acceptance criterion'}


def energy_table_reproduction(rows: list[dict], table: dict, n_variants: int = 8) -> dict:
    """v1_wide variants 0..7 against energy_table_v1.json cell means (same recipe
    and seeds): confirms the render chain here is the one the ladder was measured with."""
    diffs: dict[str, float] = {}
    n_cells = 0
    for cell in dict.fromkeys(r['cell'] for r in rows):
        sel = [r for r in rows if r['cell'] == cell and r['source'] == 'v1_wide'
               and r['visit_idx'] < n_variants and r.get('lufs') is not None]
        if len(sel) < n_variants or cell not in table['cells']:
            continue
        n_cells += 1
        feats = {'lufs': 'lufs', 'drum_rate': 'drum_rate', 'tempo_bpm': 'played_tempo_bpm',
                 'centroid_hz': 'centroid_hz', 'flux': 'flux'}
        for f, col in feats.items():
            d = abs(float(np.mean([r[col] for r in sel])) - table['cells'][cell][f])
            diffs[f] = max(diffs.get(f, 0.0), d)
    return {'n_cells': n_cells, 'max_abs_diff': {f: round(v, 5) for f, v in diffs.items()}}


# =============================================================================
# CLI
# =============================================================================


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--cells', default=None, help='comma list genre:tier (default: the live ladder)')
    ap.add_argument('--visits', type=int, default=12, help='v1_live and v2_session visits per cell')
    ap.add_argument('--stim-seeds', default='1,2', help='comma list of v2 stim seeds')
    ap.add_argument('--wide-variants', type=int, default=128, help='v1_wide bank variants per cell (MIDI)')
    ap.add_argument('--audio', action='store_true', help='render via fluidsynth CLI and run the Tier A checks')
    ap.add_argument('--audio-variants', type=int, default=32, help='v1_wide variants rendered per cell')
    ap.add_argument('--sf2', default=str(HERE / 'Musyng_Kite.sf2'))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--develop', action='store_true', help='v2_session with pitched development (opt-in; develop_engine policy per genre)')
    ap.add_argument('--ladder', choices=('measured', 'prior'), default='measured')
    ap.add_argument('--out', default=None, help='output dir (default renders/certification/<stamp>)')
    args = ap.parse_args(argv)
    args.stim_seeds = [int(s) for s in args.stim_seeds.split(',') if s.strip()]
    if not 4 <= args.wide_variants < 1000:      # MelodyBank seeds overlap the next tier at 1000
        ap.error('--wide-variants must be in 4..999')
    if args.visits < 2:
        ap.error('--visits must be >= 2')
    args.audio_variants = min(args.audio_variants, args.wide_variants)
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    stamp = datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')
    out = Path(args.out) if args.out else HERE / 'renders' / 'certification' / stamp
    if 'frozen_v2' in out.resolve().parts:
        raise SystemExit('refusing to write under frozen_v2')

    ladder, ladder_info = live_ladder(args.ladder)
    if args.cells:
        cells = []
        for c in args.cells.split(','):
            g, t = c.strip().split(':')
            if (g, int(t)) not in ladder.by_gt:
                raise SystemExit(f'{c} is not on the live ladder')
            cells.append(ladder.by_gt[(g, int(t))])
    else:
        cells = list(ladder.cells)
    out.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    rows: list[dict] = []
    pms: dict = {}
    for c in cells:
        r, p = generate_cell(c.genre, c.tier, args.visits, args.wide_variants, args.stim_seeds, args.develop)
        rows += r
        if args.audio:
            need = {x['midi_sha256'] for x in r
                    if x['source'] != 'v1_wide' or x['visit_idx'] < args.audio_variants}
            pms.update({k: v for k, v in p.items() if k in need})
        print(f'  {c.genre}:{c.tier}: {len(r)} segments', file=sys.stderr)
    t_midi = time.perf_counter() - t_start

    table = json.loads(Path(ladder_info.get('energy_table') or HERE / 'energy_table_v1.json').read_text())
    t_audio = None
    if args.audio:
        t0 = time.perf_counter()
        print(f'  rendering {len(pms)} unique segments with {args.workers} workers', file=sys.stderr)
        rendered = render_all(pms, args.sf2, args.workers)
        t_audio = time.perf_counter() - t0
        z, w = energy_z_params(table), table['weights']
        for r in rows:
            a = rendered.get(r['midi_sha256'])
            if a is None:
                continue
            r.update(a)
            r['energy_e'] = segment_energy({'lufs': r['lufs'], 'drum_rate': r['drum_rate'],
                                            'tempo_bpm': r['played_tempo_bpm'],
                                            'centroid_hz': r['centroid_hz'], 'flux': r['flux']}, z, w)

    cell_summaries = {}
    for c in cells:
        name = f'{c.genre}:{c.tier}'
        cr = [r for r in rows if r['cell'] == name]
        ref = cell_reference(cr, args.audio)
        base_by = {(r['stim_seed'], r['composer_seed']): r for r in cr if r['source'] == 'v2_base'}
        for r in cr:
            if r['source'] == 'v2_base':
                check_segment(r, ref, None, args.audio)
        for r in cr:
            if r['source'] == 'v2_session':
                check_segment(r, ref, base_by[(r['stim_seed'], r['composer_seed'])], args.audio)
        cell_summaries[name] = summarize_cell(name, cr, ref, args.audio, table.get('tie_band_e'))

    with (out / 'certification.csv').open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=CERT_FIELDS, extrasaction='ignore')
        wr.writeheader()
        for r in rows:
            wr.writerow({k: _csv_value(r.get(k)) for k in CERT_FIELDS})

    cell_cols = ['cell', 'u', 'repetition_improved', 'repetition_targets_met', 'variation_controlled',
                 'within_cell_range', 'segment_ok_rate', 'fallback_rate', 'r1_v1', 'r1_v2', 'r2_v1', 'r2_v2',
                 'r3_exact_repeat_rate_v1', 'r3_exact_repeat_rate_v2', 'bar8_rate_v1', 'bar8_rate_v2',
                 'voices_outside_live4', 'voices_outside_wide', 'n_attention',
                 'within_block_new_drum_bar_frac', 'new_block_new_drum_bar_frac_v2',
                 'new_block_new_drum_bar_frac_v1']
    with (out / 'cell_summary.csv').open('w', newline='', encoding='utf-8') as f:
        wr = csv.DictWriter(f, fieldnames=cell_cols)
        wr.writeheader()
        for c in cells:
            s = cell_summaries[f'{c.genre}:{c.tier}']
            v1, v2, vd = s['repetition']['v1_live'], s['repetition']['v2_session'], s['verdict']
            wr.writerow({k: _csv_value(v) for k, v in {
                'cell': f'{c.genre}:{c.tier}', 'u': round(c.u, 4),
                'repetition_improved': vd['repetition_improved'],
                'repetition_targets_met': vd['repetition_targets_met'],
                'variation_controlled': vd['variation_controlled'], 'within_cell_range': vd['within_cell_range'],
                'segment_ok_rate': s['segment_ok_rate'], 'fallback_rate': s['fallback_rate'],
                'r1_v1': v1['r1_distinct_drum_bars_mean'], 'r1_v2': v2['r1_distinct_drum_bars_mean'],
                'r2_v1': v1['r2_max_identical_drum_run'], 'r2_v2': v2['r2_max_identical_drum_run'],
                'r3_exact_repeat_rate_v1': v1['r3_exact_repeat_rate'],
                'r3_exact_repeat_rate_v2': v2['r3_exact_repeat_rate'],
                'bar8_rate_v1': v1['r6_bar8_rate'], 'bar8_rate_v2': v2['r6_bar8_rate'],
                'voices_outside_live4': s['midi']['voices_outside_live4'],
                'voices_outside_wide': s['midi']['voices_outside_wide'],
                'n_attention': len(vd['attention']),
                'within_block_new_drum_bar_frac': s['novelty']['v2_session']['within_block_new_drum_bar_frac'],
                'new_block_new_drum_bar_frac_v2': s['novelty']['v2_session']['new_block_new_drum_bar_frac'],
                'new_block_new_drum_bar_frac_v1': s['novelty']['v1_live']['new_block_new_drum_bar_frac'],
                }.items()})

    verdicts = {k: s['verdict'] for k, s in cell_summaries.items()}
    keys = key_continuity(rows)
    r4_diag = r4_energy_diagnostic(cells, cell_summaries)
    a6 = novelty_balance({
        f'{c.genre}:{c.tier}': {'u': c.u, 'genre': c.genre, 'tier': c.tier,
                                'values': [r['new_drum_bar_frac'] for r in rows
                                           if r['cell'] == f'{c.genre}:{c.tier}' and r['source'] == 'v2_session'
                                           and r.get('same_base_as_prev')]}
        for c in cells})
    wide_live_subset = all(
        {r['midi_sha256'] for r in rows if r['cell'] == k and r['source'] == 'v1_live'}
        <= {r['midi_sha256'] for r in rows if r['cell'] == k and r['source'] == 'v1_wide'}
        for k in cell_summaries)
    overall = {
        'n_cells': len(cells),
        'repetition_improved_cells': sum(v['repetition_improved'] for v in verdicts.values()),
        'repetition_targets_met_cells': sum(v['repetition_targets_met'] for v in verdicts.values()),
        'variation_controlled_cells': sum(v['variation_controlled'] for v in verdicts.values()),
        'within_cell_range_cells': sum(v['within_cell_range'] for v in verdicts.values()),
        'repetition_improved': all(v['repetition_improved'] for v in verdicts.values()),
        'variation_controlled': all(v['variation_controlled'] for v in verdicts.values()),
        'within_cell_range': all(v['within_cell_range'] for v in verdicts.values()),
        'key_locked': all(e['v2_key_locked'] for e in keys.values()),
        'a6_novelty_balance': a6['ok'],
        'r4_energy_rho_diagnostic': r4_diag['rho'],    # old A6 statistic, no pass/fail
        'v2_segment_ok_rate': round(float(np.mean([bool(r['segment_ok']) for r in rows
                                                   if r['source'] == 'v2_session'])), 4),
        'v2_fallback_rate': round(float(np.mean([bool(r['gen_fallback']) for r in rows
                                                 if r['source'] == 'v2_session'])), 4),
        'cells_needing_attention': {k: v['attention'] for k, v in verdicts.items() if v['attention']},
    }
    summary = {
        'meta': {
            'tool': 'certify_stimuli.py', 'timestamp': stamp, 'argv': sys.argv[1:] if argv is None else argv,
            'sources': SOURCES, 'visits': args.visits, 'stim_seeds': args.stim_seeds,
            'wide_variants': args.wide_variants, 'audio': args.audio,
            'audio_variants': args.audio_variants if args.audio else None,
            'generator_config': {'v1_live': BankGenerator().config,
                                 'v1_wide': BankGenerator(variants_per_cell=args.wide_variants).config,
                                 'v2_session': [SessionGenerator(s, develop=args.develop).config
                                                for s in args.stim_seeds]},
            'bars_per_segment': BARS, 'ladder': ladder_info, 'cells': [f'{c.genre}:{c.tier}' for c in cells],
            'n_rows': len(rows), 'n_rows_by_source': {s: sum(r['source'] == s for r in rows) for s in SOURCES},
            'n_rendered': len(pms) if args.audio else 0,
            'elapsed_s': {'midi': round(t_midi, 2), 'audio': None if t_audio is None else round(t_audio, 2)},
            'render_workers': args.workers if args.audio else None,
            'python': platform.python_version(), 'code': code_provenance(),
            'soundfont': args.sf2 if args.audio else None,
            'soundfont_sha256': _file_sha256(Path(args.sf2)) if args.audio else None,
            'criteria': {
                'env_pad_sd': ENV_PAD_SD, 'midi_gated': MIDI_GATED, 'midi_reported': MIDI_REPORTED,
                'audio_gated': AUDIO_GATED, 'mean_shift_sd': MEAN_SHIFT_SD, 'lufs_shift_lu': LUFS_SHIFT_LU,
                'e_shift': None if table.get('tie_band_e') is None else table['tie_band_e'] / 2,
                'e_spread_ratio': E_SPREAD_RATIO, 'seg_lufs_lu': SEG_LUFS_LU,
                'max_fallback_rate': MAX_FALLBACK_RATE, 'r1_min': {'default': R1_MIN_DEFAULT, **R1_MIN},
                'r2_max': R2_MAX, 'drum_repeat_min_visits': DRUM_REPEAT_MIN_VISITS,
                'bar4_min_rate': BAR4_MIN_RATE,
                'a6_novelty_balance': {'min_mean': NOVELTY_MIN_MEAN,
                                       'max_abs_rel_change': NOVELTY_MAX_REL_CHANGE,
                                       'threshold_status': 'provisional engineering threshold, '
                                                           'not perceptually validated',
                                       'bootstrap': NOVELTY_BOOT},
                'r4_energy_diagnostic_old_limit_abs_rho': OLD_A6_R4_MAX_RHO,
            },
        },
        'fidelity': {
            'v1_live_subset_of_v1_wide': wide_live_subset,
            'energy_table_reproduction': energy_table_reproduction(rows, table) if args.audio else None,
        },
        'overall': overall,
        'key_continuity': keys,
        'a6_novelty_balance': a6,
        'r4_energy_rho_diagnostic': r4_diag,
        'cells': cell_summaries,
    }
    (out / 'certification_summary.json').write_text(json.dumps(summary, indent=2, default=str), encoding='utf-8')
    print(f'wrote {out / "certification.csv"} ({len(rows)} rows)')
    print(f'wrote {out / "cell_summary.csv"}')
    print(f'wrote {out / "certification_summary.json"}')
    print(json.dumps({k: v for k, v in overall.items() if k != 'cells_needing_attention'}, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
