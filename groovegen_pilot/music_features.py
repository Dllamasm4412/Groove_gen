"""
Deterministic MIR feature vectors per ladder cell (M0.6 Step 1).

Design rationale
----------------
The v1 sim collapsed all musical content into a single scalar `u`. That
made it structurally impossible to show a music -> arousal effect: two
different genres with the same u produced identical plant behavior.

This module maps each (genre, tier) ladder cell to a 7-dim MIR feature
vector anchored on Sophia_Study (2026):

    tempo_bpm            - tempo band effect (Sophia: 110-130 BPM +9.3
                            pts danceability; Janata 2012 tactus band)
    percussive_ratio     - HPSS percussive/total ratio (Sophia beta = +4.66,
                            strongest positive predictor of danceability)
    low_band_energy      - sub-250Hz energy ratio (Sophia beta = +2.97)
    beat_consistency     - inter-onset regularity 0..1 (Sophia beta = +1.35;
                            here it also reduces arousal noise)
    onset_density        - onsets per second (Sophia n.s., kept as covariate)
    syncopation          - LHL syncopation proxy (Sophia n.s. in commercial
                            audio; Witek 2014 requires controlled stimuli)
    spectral_flatness    - noise-like timbre (Sophia beta = -1.23)

These are STIMULUS-SIDE priors, not measured composer outputs. A separate
composer-validation run (music_features_measured.py) will measure real
composer outputs and confirm they land near these priors.

Public API
----------
    MIRFeatures                        (frozen dataclass)
    feature_vector_for(cell)           -> MIRFeatures
    build_feature_bank(ladder)         -> dict[int, MIRFeatures]
    print_feature_bank(fb)             debug pretty-print
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ladder import Cell, Ladder


# =============================================================================
# Per-genre base MIR profiles anchored on Sophia_Study genre-family findings
# =============================================================================
#
# Values reflect a mix of Sophia's high-dance sensory-motor subset profile
# (n=83: 120 BPM, low_band ~= 0.70, harmonic ~= 0.70, moderate onset density
# ~= 4.5) and genre-family medians from her table (Table in the memo:
# pop 61.2, rnb 65.5, hip-hop 67.5, latin 72.0). We use calm as a
# "designed-lower-arousal" family with piano/pad focus, low bass, low
# percussion, high harmonic content.
#
# These are TIER-1 (mid-tier) values. Tier scaling below adjusts them
# monotonically per rung.

# Priors refit 2026-08-16 (Step 2 composer validation) against measured
# librosa features from actual composer+TimGM6mb rendered output over all
# 25 ladder cells. Rank order across genres is preserved. Absolute
# magnitudes reflect what our composer actually produces, not the Sophia
# corpus of commercial recordings. See measured_vs_prior_report.md and
# DEVIATIONS.md v2.2 for the refit rationale.
_GENRE_BASE = {
    # Calm: piano/pad bed, no drums. Measured mean across calm-1..5:
    # tempo 64.6, perc 0.05, low 0.58, beat 0.98, onset 1.14, sync 0.21,
    # flat 0.002.
    'calm': dict(
        tempo_bpm=65.0,
        percussive_ratio=0.05,
        low_band_energy=0.58,
        beat_consistency=0.98,
        onset_density=1.15,
        syncopation=0.21,
        spectral_flatness=0.005,
    ),
    # Lofi: bridges calm and rnb. Warm Rhodes-EP + soft bass + soft drums.
    # Measured mean: tempo 78.3, perc 0.09, low 0.66, beat 0.99, onset 2.23,
    # sync 0.50, flat 0.002.
    'lofi': dict(
        tempo_bpm=78.0,
        percussive_ratio=0.09,
        low_band_energy=0.66,
        beat_consistency=0.99,
        onset_density=2.25,
        syncopation=0.50,
        spectral_flatness=0.005,
    ),
    # R&B / soul: Sophia family, groove-heavy bass-forward. Measured mean:
    # tempo 99.4, perc 0.13, low 0.64, beat 0.98, onset 3.17, sync 0.57,
    # flat 0.005. Note: composer produces cleaner audio than Sophia's real
    # recordings; absolute perc is lower than commercial-recording priors
    # but rank order across our genres is preserved.
    'rnb': dict(
        tempo_bpm=100.0,
        percussive_ratio=0.13,
        low_band_energy=0.64,
        beat_consistency=0.98,
        onset_density=3.20,
        syncopation=0.57,
        spectral_flatness=0.005,
    ),
    # Pop: Sophia family, brighter timbre from acoustic-guitar lead.
    # Measured mean: tempo 117.5, perc 0.23, low 0.58, beat 0.98,
    # onset 3.28, sync 0.58, flat 0.023.
    'pop': dict(
        tempo_bpm=118.0,
        percussive_ratio=0.23,
        low_band_energy=0.58,
        beat_consistency=0.98,
        onset_density=3.30,
        syncopation=0.58,
        spectral_flatness=0.023,
    ),
    # Latin: Sophia's highest-dance family. Measured mean: tempo 103.4,
    # perc 0.23, low 0.54, beat 0.96, onset 3.28, sync 0.65, flat 0.002.
    # Highest syncopation as expected.
    'latin': dict(
        tempo_bpm=103.0,
        percussive_ratio=0.23,
        low_band_energy=0.54,
        beat_consistency=0.96,
        onset_density=3.30,
        syncopation=0.65,
        spectral_flatness=0.005,
    ),
}


# Tier scaling: tier 1 = 40% of tier-3 intensity, tier 5 = 100%.
# Matches the composer's density scaling (tier_scale = 0.4 + 0.15*(tier-1)).
# We interpret this as: higher tiers add drum layers, more onsets, more
# bass, more percussive weight, and a modest bump in tempo. Beat
# consistency and spectral flatness barely move with tier.
def _tier_scale(tier: int) -> float:
    return 0.4 + 0.15 * (tier - 1)  # 0.40, 0.55, 0.70, 0.85, 1.00


@dataclass(frozen=True)
class MIRFeatures:
    """One MIR feature vector for one ladder cell."""
    tempo_bpm: float
    percussive_ratio: float   # 0..1
    low_band_energy: float    # 0..1
    beat_consistency: float   # 0..1
    onset_density: float      # onsets/sec
    syncopation: float        # 0..1
    spectral_flatness: float  # 0..1

    def as_dict(self) -> dict:
        return {
            'tempo_bpm': self.tempo_bpm,
            'percussive_ratio': self.percussive_ratio,
            'low_band_energy': self.low_band_energy,
            'beat_consistency': self.beat_consistency,
            'onset_density': self.onset_density,
            'syncopation': self.syncopation,
            'spectral_flatness': self.spectral_flatness,
        }


def feature_vector_for(cell: Cell) -> MIRFeatures:
    """Compute deterministic MIR features for one ladder cell."""
    base = _GENRE_BASE[cell.genre]
    ts = _tier_scale(cell.tier)

    # Tempo grows modestly with tier: +/- 6 BPM across tiers 1..5
    tempo = base['tempo_bpm'] + 3.0 * (cell.tier - 3)

    # Percussive ratio and onset density grow strongly with tier
    perc = min(0.90, base['percussive_ratio'] * (0.6 + 0.5 * ts))
    onsets = base['onset_density'] * (0.5 + 0.7 * ts)

    # Bass content grows moderately with tier (kick weight increases)
    bass = min(0.90, base['low_band_energy'] * (0.75 + 0.35 * ts))

    # Beat consistency: very slight tier growth (steadier at high tier
    # because drums are locked to grid; low tier has more rubato feel).
    beat_c = min(0.97, base['beat_consistency'] + 0.03 * (cell.tier - 3))

    # Syncopation grows slightly with tier (more hihat/kick displacement)
    sync = min(0.85, base['syncopation'] * (0.7 + 0.5 * ts))

    # Spectral flatness barely moves with tier (timbre is genre-defined)
    flat = base['spectral_flatness'] * (0.9 + 0.1 * ts)

    return MIRFeatures(
        tempo_bpm=float(tempo),
        percussive_ratio=float(perc),
        low_band_energy=float(bass),
        beat_consistency=float(beat_c),
        onset_density=float(onsets),
        syncopation=float(sync),
        spectral_flatness=float(flat),
    )


def build_feature_bank(ladder: Ladder) -> dict[int, MIRFeatures]:
    """One MIRFeatures per rung, keyed by rung index."""
    return {c.rung: feature_vector_for(c) for c in ladder.cells}


def print_feature_bank(fb: dict[int, MIRFeatures]) -> None:
    hdr = f'{"rung":>4} {"cell":>10} {"tempo":>6} {"perc":>6} {"bass":>6} ' \
          f'{"beat":>6} {"onset":>6} {"sync":>6} {"flat":>6}'
    print(hdr)
    print('-' * len(hdr))
    for rung in sorted(fb):
        f = fb[rung]
        print(f'{rung:>4} {"":<10} {f.tempo_bpm:>6.1f} {f.percussive_ratio:>6.2f} '
              f'{f.low_band_energy:>6.2f} {f.beat_consistency:>6.2f} '
              f'{f.onset_density:>6.2f} {f.syncopation:>6.2f} '
              f'{f.spectral_flatness:>6.2f}')


if __name__ == '__main__':
    from ladder import build_ladder
    L = build_ladder()
    fb = build_feature_bank(L)
    hdr = f'{"rung":>4} {"cell":>10} {"tempo":>6} {"perc":>6} {"bass":>6} ' \
          f'{"beat":>6} {"onset":>6} {"sync":>6} {"flat":>6}'
    print(hdr)
    print('-' * len(hdr))
    for c in L.cells:
        f = fb[c.rung]
        label = f'{c.genre}-{c.tier}'
        print(f'{c.rung:>4} {label:>10} {f.tempo_bpm:>6.1f} {f.percussive_ratio:>6.2f} '
              f'{f.low_band_energy:>6.2f} {f.beat_consistency:>6.2f} '
              f'{f.onset_density:>6.2f} {f.syncopation:>6.2f} '
              f'{f.spectral_flatness:>6.2f}')

    # Sanity: latin-5 should have highest percussive+bass, calm-1 lowest
    fb_latin5 = fb[L.by_gt[('latin', 5)].rung]
    fb_calm1 = fb[L.by_gt[('calm', 1)].rung]
    assert fb_latin5.percussive_ratio > fb_calm1.percussive_ratio
    assert fb_latin5.low_band_energy > fb_calm1.low_band_energy
    assert fb_latin5.onset_density > fb_calm1.onset_density
    print('\nSANITY: latin-5 > calm-1 on percussive/bass/onset ... OK')
