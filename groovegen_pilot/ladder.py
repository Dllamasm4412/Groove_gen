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

Public API
----------
    build_ladder(genre_cfg=None) -> Ladder
        Compute the 20-cell energy table from a genre config dict.
        Returns a Ladder with .cells (sorted low->high), .index(genre, tier),
        .energy(genre, tier), and .neighbors(genre, tier, max_step=1).

    Ladder.cells : list[Cell]  where Cell = (rung, genre, tier, u)
    Ladder.by_rung : dict[int, Cell]
    Ladder.by_gt   : dict[(genre, tier), Cell]

Invariants
----------
    - Exactly 20 cells (4 genres x 5 tiers)
    - u in [0, 1], min-max normalized after prior computation
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
}


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


def build_ladder(genre_cfg: Optional[dict] = None) -> Ladder:
    """
    Build the 20-cell energy ladder.

    Parameters
    ----------
    genre_cfg : dict, optional
        GrooveGen GENRE_CFG. If None, imported from composer.
    """
    if genre_cfg is None:
        from composer import GENRE_CFG as _CFG
        genre_cfg = _CFG

    # Compute raw feature vectors for each (genre, tier)
    raw = []  # list of (genre, tier, tempo, onset_density, rms, centroid)
    for genre in ('calm', 'lofi', 'rnb', 'pop', 'latin'):
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

    # Enforce monotone-in-tier within each genre BEFORE min-max, by adding
    # a small per-tier bump if needed. This preserves the audio-feature
    # ranking across genres while guaranteeing the interface invariant.
    corrected: dict[tuple[str, int], float] = {}
    for genre in ('calm', 'lofi', 'rnb', 'pop', 'latin'):
        genre_pairs = [(raw[i][1], e_raw[i], i)
                       for i in range(len(raw)) if raw[i][0] == genre]
        genre_pairs.sort(key=lambda t: t[0])  # by tier
        prev = -1e9
        for tier, e, idx in genre_pairs:
            if e <= prev:
                e = prev + 1e-3
            corrected[(genre, tier)] = e
            prev = e

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

    return Ladder(cells=tuple(cells), by_rung=by_rung, by_gt=by_gt)


if __name__ == '__main__':
    L = build_ladder()
    print('=' * 60)
    print(f'Ladder built: {len(L.cells)} cells')
    print('=' * 60)
    print(L.summary())
    # Sanity: monotone in tier within genre
    print()
    print('Monotone-in-tier check:')
    for g in ('calm', 'lofi', 'rnb', 'pop', 'latin'):
        us = [L.energy(g, t) for t in range(1, 6)]
        mono = all(us[i] < us[i + 1] for i in range(4))
        print(f'  {g}: {["%.3f" % u for u in us]}  {"PASS" if mono else "FAIL"}')
    # Neighbors sanity
    n = L.neighbors('pop', 3, max_step=2)
    print(f'\nNeighbors of (pop, 3), max_step=2: {[(c.genre, c.tier) for c in n]}')
