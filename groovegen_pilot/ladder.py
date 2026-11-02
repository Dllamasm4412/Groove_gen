"""
1-D energy ladder for GrooveGen closed-loop control (M0.5 Step 5.5).

Collapses (genre, tier) into a scalar energy coordinate u in [0, 1] using
audio-feature weights derived from published arousal betas (Gomez &
Danuser 2007, https://www.brainmusic.org/EducationalActivities/Gomez_emotion2007.pdf):

    E_prior = 0.55 * z(RMS)
            + 0.20 * z(onset_density)
            + 0.15 * z(tempo)
            + 0.10 * z(spectral_centroid_proxy)

Weights mirror the 2.14 / 0.46 / 0.43 ordering of sound intensity /
accentuation / tempo in the source. Spectral centroid is an inferred
brightness proxy (not in Gomez-Danuser).

For the pilot, we do NOT have per-cell RMS/onset/centroid measurements
yet — they will land after the composer's mixer exposes them. So we use
a defensible per-(genre, tier) prior derived from GENRE_CFG:

    tempo   -> genre_cfg.tempo_default
    onsets  -> notes_per_sec_target * tier_scale
    RMS     -> proxy from tier + drum-presence (drums add ~+6 dB)
    centroid-> proxy from lead-instrument GM program (guitar > piano > pad)

The ladder is monotone in tier within each genre by construction. Cross-
genre ordering is data-driven (not hard-coded calm < rnb < latin < pop).

Measured ladder (features=...): the per-cell means from
music_features_measured.py (energy_table_v1.json) replace the prior:

    E = 0.40 z(LUFS) + 0.25 z(drum onsets/s) + 0.20 z(played tempo)
      + 0.10 z(spectral centroid) + 0.05 z(spectral flux)

with z over all 35 cells. Cells whose energies differ by less than
tie_band (median within-cell SD of E over melody-bank variants) are not
distinguishable, so within such a tie group they are ordered by played
tempo (then E) and take the group's E values in that order; the set of u
values is unchanged. Stimulus-side measurements only.

By-ear order (ear_ratings=..., measured ladder only): the developer's energy
ratings of the kept cells (energy_by_ear.py) replace the measured order. The
kept cells' measured E values, sorted, are reassigned in rating order (equal
ratings in measured order), so the set of u values, the spacing the
controller and the rotation band were tuned on, is unchanged; only which cell
holds which value follows the ear. Ratings must not fall with tier within a
genre (monotone-in-tier stays an invariant).

Public API
----------
    build_ladder(genre_cfg=None, tier_caps=None, exclude_genres=(),
                 features=None, weights=None, tie_band=0.0,
                 ear_ratings=None) -> Ladder
        Compute the (genre, tier) energy table from a genre config dict.
        tier_caps drops cells the renderer would clamp to a lower tier.
        Returns a Ladder with .cells (sorted low->high), .index(genre, tier),
        .energy(genre, tier), and .neighbors(genre, tier, max_step=1).

    load_energy_table(path) -> (features, weights, tie_band, sha256)
        Read energy_table_v1.json for build_ladder(features=...).

    load_ear_ratings(path) -> (ratings, sha256)
        Read energy_order_by_ear.json for build_ladder(ear_ratings=...).

    Ladder.cells : list[Cell]  where Cell = (rung, genre, tier, u)
    Ladder.by_rung : dict[int, Cell]
    Ladder.by_gt   : dict[(genre, tier), Cell]

Invariants
----------
    - Exactly 5 * len(_GENRES) cells (7 genres x 5 tiers = 35) without
      tier_caps; 29 with segment_renderer.RUNG_TIER_CAP
    - u in [0, 1], min-max normalized after prior / measured energy
    - Monotone in tier within each genre
    - Ladder is FROZEN once built (no mutation)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# =============================================================================
# Feature priors (per genre, tier-independent unless noted)
# =============================================================================
# Values are engineering priors intended to preserve the *rank ordering*
# expected from Stage 1 audio analysis, not to claim measured feature values.

# Lead-instrument brightness proxy — GM program numbers roughly cluster by
# spectral centroid. Higher = brighter.
_BRIGHTNESS = {
    'calm':  40.0,   # pad + piano + strings, dark
    'lofi':  47.0,   # Rhodes EP + bass + soft drums, mellow
    'rnb':   55.0,   # EP + bass + strings, mid
    'pop':   70.0,   # EP + bass + acoustic guitar lead, brighter
    'latin': 65.0,   # nylon guitar + bass, bright but woody
    'hiphop': 58.0,  # piano stabs + electric bass, mid
    'rock':  75.0,   # overdriven electric guitar, brightest
}

# Base loudness proxy (RMS in arbitrary units). Drums add ~6 units.
# These reflect the fact that pop and latin mixes are typically hotter
# than calm; RMS is the dominant arousal term (beta = 2.14).
_RMS_BASE = {
    'calm':  0.35,   # no drums, gentle pad
    'lofi':  0.45,   # soft drums + EP, warm and quiet
    'rnb':   0.55,   # drums + EP, mid-loud
    'pop':   0.72,   # drums + full band, hot
    'latin': 0.68,   # drums + guitar + bass, hot
    'hiphop': 0.66,  # punchy kick/snare at high velocity, sparse top end
    'rock':  0.78,   # backbeat drums + driven guitar, loudest mix
}

# Ladder genre order (cells are re-sorted by energy afterwards).
_GENRES = tuple(_BRIGHTNESS)


def _zscore(vals: list[float]) -> list[float]:
    n = len(vals)
    if n == 0:
        return []
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / max(1, n)
    sd = var ** 0.5 or 1.0
    return [(v - mu) / sd for v in vals]


@dataclass(frozen=True)
class Cell:
    rung: int          # 0..19 after final sort
    genre: str
    tier: int          # 1..5
    u: float           # energy in [0, 1]

    def gt(self) -> tuple[str, int]:
        return (self.genre, self.tier)


@dataclass(frozen=True)
class Ladder:
    cells: tuple[Cell, ...]
    by_rung: dict[int, Cell]
    by_gt: dict[tuple[str, int], Cell]
    # Measured ladder only: tie_band (median within-cell energy SD) in u units
    noise_u: float = 0.0

    def energy(self, genre: str, tier: int) -> float:
        return self.by_gt[(genre, tier)].u

    def index(self, genre: str, tier: int) -> int:
        return self.by_gt[(genre, tier)].rung

    def neighbors(self, genre: str, tier: int, max_step: int = 1) -> list[Cell]:
        """Return cells within +/- max_step rungs (inclusive of current)."""
        c = self.by_gt[(genre, tier)]
        lo = max(0, c.rung - max_step)
        hi = min(len(self.cells) - 1, c.rung + max_step)
        return [self.by_rung[r] for r in range(lo, hi + 1)]

    def summary(self) -> str:
        lines = [
            f'{"rung":>4} {"genre":>6} {"tier":>4} {"u":>6}',
            '-' * 30,
        ]
        for c in self.cells:
            lines.append(f'{c.rung:>4} {c.genre:>6} {c.tier:>4} {c.u:>6.3f}')
        return '\n'.join(lines)


def build_ladder(
    genre_cfg: Optional[dict] = None,
    tier_caps: Optional[dict[str, int]] = None,
    exclude_genres: tuple[str, ...] = (),
    features: Optional[dict[tuple[str, int], dict[str, float]]] = None,
    weights: Optional[dict[str, float]] = None,
    tie_band: float = 0.0,
    ear_ratings: Optional[dict[tuple[str, int], float]] = None,
) -> Ladder:
    """
    Build the energy ladder (35 cells, or fewer with tier_caps).

    Parameters
    ----------
    genre_cfg : dict, optional
        GrooveGen GENRE_CFG. If None, imported from composer.
    tier_caps : dict, optional
        genre -> highest tier kept (e.g. segment_renderer.RUNG_TIER_CAP).
        The renderer clamps tiers above the cap, so those cells would sound
        like a lower tier while sitting higher on the ladder. Capped cells
        are dropped after the monotone correction and before min-max; the
        lowest (calm1) and highest (rock5) cells are kept, so every kept
        cell's u is identical to the full ladder's.
    exclude_genres : tuple of str, optional
        Genres left off the ladder (e.g. the live runner's LIVE_EXCLUDE_GENRES).
        Dropped at the same point as tier_caps, so kept cells keep their u.
    features : dict, optional
        (genre, tier) -> measured feature means (see load_energy_table). If
        given, E is the weighted z-score of these instead of the prior; all
        35 cells are required so z does not depend on tier_caps/exclusion.
    weights : dict, optional
        feature -> weight for the measured E (required with features).
    tie_band : float
        Measured ladder only: kept cells whose E differ by less than this
        (chained) form a tie group ordered by played tempo; 0 disables.
    ear_ratings : dict, optional
        Measured ladder only: (genre, tier) -> by-ear energy rating for
        every kept cell; the kept cells take the measured E values in
        rating order (see module docstring).
    """
    if genre_cfg is None:
        from composer import GENRE_CFG as _CFG
        genre_cfg = _CFG

    if features is not None:
        return _measured_ladder(genre_cfg, tier_caps, exclude_genres,
                                features, weights, tie_band, ear_ratings)
    if ear_ratings is not None:
        raise ValueError('ear_ratings reorder the measured ladder; pass features too')

    # Compute raw feature vectors for each (genre, tier)
    raw = []  # list of (genre, tier, tempo, onset_density, rms, centroid)
    for genre in _GENRES:
        cfg = genre_cfg[genre]
        tempo = float(cfg['tempo_default'])
        nps = float(cfg.get('notes_per_sec_target', 3.0))
        has_drums = bool(cfg.get('include_drums', False))
        bright = _BRIGHTNESS[genre]
        rms_base = _RMS_BASE[genre]
        for tier in range(1, 6):
            # Tier scales density; low tier -> less resolution, less hihat,
            # fewer ornaments. Mapping matches the composer's density scaling.
            tier_scale = 0.4 + 0.15 * (tier - 1)  # 0.40 .. 1.00
            onset_density = nps * tier_scale
            # RMS grows with tier because hihat and accent layers are added
            rms = rms_base * (0.85 + 0.05 * tier)
            centroid = bright * (0.9 + 0.04 * tier)
            raw.append((genre, tier, tempo, onset_density, rms, centroid))

    tempos = [r[2] for r in raw]
    onsets = [r[3] for r in raw]
    rmss = [r[4] for r in raw]
    cents = [r[5] for r in raw]

    z_tempo = _zscore(tempos)
    z_onset = _zscore(onsets)
    z_rms = _zscore(rmss)
    z_cent = _zscore(cents)

    # Gomez-Danuser weighted energy prior
    e_raw = []
    for i in range(len(raw)):
        e = (0.55 * z_rms[i]
             + 0.20 * z_onset[i]
             + 0.15 * z_tempo[i]
             + 0.10 * z_cent[i])
        e_raw.append(e)

    e_map = {(raw[i][0], raw[i][1]): e_raw[i] for i in range(len(raw))}
    corrected = _filter(_monotone(e_map), tier_caps, exclude_genres)
    return _to_ladder(corrected)


def _monotone(e_map: dict[tuple[str, int], float]) -> dict[tuple[str, int], float]:
    # Enforce monotone-in-tier within each genre BEFORE min-max, by adding
    # a small per-tier bump if needed. This preserves the audio-feature
    # ranking across genres while guaranteeing the interface invariant.
    corrected: dict[tuple[str, int], float] = {}
    for genre in _GENRES:
        prev = -1e9
        for tier in range(1, 6):
            e = e_map[(genre, tier)]
            if e <= prev:
                e = prev + 1e-3
            corrected[(genre, tier)] = e
            prev = e
    return corrected


def _filter(corrected, tier_caps, exclude_genres):
    if tier_caps is not None:
        corrected = {
            (g, t): e for (g, t), e in corrected.items() if t <= tier_caps.get(g, 5)
        }
    if exclude_genres:
        if {'calm', 'rock'} & set(exclude_genres):
            raise ValueError('calm and rock hold the ladder endpoints; cannot exclude them')
        corrected = {k: e for k, e in corrected.items() if k[0] not in exclude_genres}
    return corrected


def _to_ladder(corrected: dict[tuple[str, int], float], noise_e: float = 0.0) -> Ladder:
    # Min-max to [0, 1]
    all_e = list(corrected.values())
    lo, hi = min(all_e), max(all_e)
    span = (hi - lo) or 1.0
    u_map = {k: (v - lo) / span for k, v in corrected.items()}

    # Sort into rungs by energy ascending
    sorted_cells = sorted(u_map.items(), key=lambda kv: kv[1])
    cells: list[Cell] = []
    for rung, ((genre, tier), u) in enumerate(sorted_cells):
        cells.append(Cell(rung=rung, genre=genre, tier=tier, u=u))

    by_rung = {c.rung: c for c in cells}
    by_gt = {(c.genre, c.tier): c for c in cells}

    return Ladder(cells=tuple(cells), by_rung=by_rung, by_gt=by_gt, noise_u=noise_e / span)


def _measured_ladder(genre_cfg, tier_caps, exclude_genres, features, weights, tie_band,
                     ear_ratings=None):
    if weights is None:
        raise ValueError('weights are required with features')
    keys = [(g, t) for g in _GENRES for t in range(1, 6)]
    missing = [k for k in keys if k not in features]
    if missing:
        raise ValueError(f'energy table is missing cells: {missing}')
    e_map = {k: 0.0 for k in keys}
    for f, w in weights.items():
        v = [float(features[k][f]) for k in keys]
        m = sum(v) / len(v)
        sd = (sum((x - m) ** 2 for x in v) / len(v)) ** 0.5 or 1.0
        for k, x in zip(keys, v):
            e_map[k] += w * (x - m) / sd
    corrected = _filter(_monotone(e_map), tier_caps, exclude_genres)

    # Tie groups: E ascending, chained while the gap is below tie_band.
    # Within a group, E carries no ordering information, so the group's
    # sorted E values are reassigned in played-tempo order (then E, which
    # keeps tier order within a genre at equal tempo).
    order = sorted(corrected, key=corrected.get)
    groups, cur = [], [order[0]]
    for a, b in zip(order, order[1:]):
        if corrected[b] - corrected[a] < tie_band:
            cur.append(b)
        else:
            groups.append(cur)
            cur = [b]
    groups.append(cur)
    tied: dict[tuple[str, int], float] = {}
    for grp in groups:
        vals = sorted(corrected[k] for k in grp)
        by_tempo = sorted(grp, key=lambda k: (float(features[k]['tempo_bpm']), corrected[k]))
        tied.update(zip(by_tempo, vals))
    for g in {k[0] for k in tied}:
        us = [tied[(g, t)] for t in range(1, 6) if (g, t) in tied]
        if any(a >= b for a, b in zip(us, us[1:])):
            raise ValueError(f'tie ordering broke monotone-in-tier for {g}')
    if ear_ratings is not None:
        tied = _ear_order(tied, ear_ratings)
    return _to_ladder(tied, tie_band)


def _ear_order(e_map: dict[tuple[str, int], float],
               ratings: dict[tuple[str, int], float]) -> dict[tuple[str, int], float]:
    """The sorted E values of e_map reassigned in by-ear rating order (equal
    ratings keep the measured order)."""
    missing = sorted(k for k in e_map if k not in ratings)
    if missing:
        raise ValueError(f'by-ear ratings are missing cells: {missing}')
    for g in sorted({k[0] for k in e_map}):
        rs = [ratings[(g, t)] for t in range(1, 6) if (g, t) in e_map]
        if any(a > b for a, b in zip(rs, rs[1:])):
            raise ValueError(f'by-ear ratings fall with tier for {g}: {rs}')
    order = sorted(e_map, key=lambda k: (float(ratings[k]), e_map[k]))
    return dict(zip(order, sorted(e_map.values())))


def load_energy_table(path):
    """(features, weights, tie_band, sha256 of the file) from a table written
    by music_features_measured.py --table."""
    import hashlib
    import json
    from pathlib import Path

    raw = Path(path).read_bytes()
    table = json.loads(raw)
    features = {}
    for key, vals in table['cells'].items():
        g, t = key.split(':')
        features[(g, int(t))] = vals
    return (features, table['weights'], float(table.get('tie_band_e', 0.0)),
            hashlib.sha256(raw).hexdigest())


def load_ear_ratings(path):
    """(ratings, sha256 of the file) from energy_order_by_ear.json
    (energy_by_ear.py apply)."""
    import hashlib
    import json
    from pathlib import Path

    raw = Path(path).read_bytes()
    ratings = {}
    for key, r in json.loads(raw)['ratings'].items():
        g, t = key.split(':')
        ratings[(g, int(t))] = float(r)
    return ratings, hashlib.sha256(raw).hexdigest()


if __name__ == '__main__':
    L = build_ladder()
    print('=' * 60)
    print(f'Ladder built: {len(L.cells)} cells')
    print('=' * 60)
    print(L.summary())
    # Sanity: monotone in tier within genre
    print()
    print('Monotone-in-tier check:')
    for g in _GENRES:
        us = [L.energy(g, t) for t in range(1, 6)]
        mono = all(us[i] < us[i + 1] for i in range(4))
        print(f'  {g}: {["%.3f" % u for u in us]}  {"PASS" if mono else "FAIL"}')
    # Neighbors sanity
    n = L.neighbors('pop', 3, max_step=2)
    print(f'\nNeighbors of (pop, 3), max_step=2: {[(c.genre, c.tier) for c in n]}')
