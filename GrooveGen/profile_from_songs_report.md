# GrooveGen 12-Song Personalization Pipeline — Steps 1-3 Report

Implements steps 1-3 of `/home/user/workspace/twelve_song_personalization_pipeline.md`
("What to build, in order", §8): the FREE/LOCAL, CPU-only, no-network,
no-MusicGen portion of the pipeline.

## Files delivered

- `/home/user/workspace/groovegen_project/groovegen/profile_from_songs.py`
  — `extract_features(audio_path) -> dict`, `build_profile(song_paths) -> dict`
- `/home/user/workspace/groovegen_project/groovegen/arc_from_profile.py`
  — `arc_from_profile(profile) -> list[dict]`, `nearest_arc_genre()`, `blend_anchors()`
- `/home/user/workspace/groovegen_project/groovegen/prompt_from_anchor.py`
  — `prompt_from_anchor(anchor, tempo_bpm) -> str`, `nearest_known_genre()`
- `/home/user/workspace/test_pipeline.py` — end-to-end smoke test on 12 fabricated songs
- `/home/user/workspace/test_pipeline_output.txt` — captured run output (also pasted below)

All three modules follow the existing package's style (module docstring
explaining the "why", `from __future__ import annotations`, `__all__`,
heavy inline documentation of design choices, numpy for numerics). They
import `GENRE_ENERGY_ORDER` from `groovegen.pd_controller` and
`GENRE_STYLES` from `groovegen.genre_styles` — no controller code was
modified (spec §7: "No controller changes").

## Feature coverage vs. `track_features.csv` (52-column schema)

`extract_features()` targets the exact column names used in
`track_features.csv`, but only implements the features the design spec
(§§2-3, §5) actually says this pipeline needs — not a byte-for-byte
reimplementation of the original (unseen) extractor's internals.

**Implemented (matches spec §§2-3/§5's named features, column names match the CSV):**

| Column | Notes |
|---|---|
| `tempo_final` | via `librosa.beat.beat_track` |
| `beat_ibi_mean`, `beat_consistency` | derived from beat-track inter-beat intervals (1/(1+CV) proxy) |
| `plp_mean`, `plp_std` | `librosa.beat.plp` |
| `onset_count`, `onset_density` | `librosa.onset.onset_detect` |
| `event_density_on_vs_off` | on-beat vs. off-beat onset-strength mass ratio (name-matched proxy, not the original algorithm) |
| `rms_mean`, `rms_std` | `librosa.feature.rms` |
| `spectral_centroid_mean`, `spectral_centroid_std` | `librosa.feature.spectral_centroid` |
| `spectral_rolloff_mean` | `librosa.feature.spectral_rolloff` |
| `spectral_flatness_mean` | `librosa.feature.spectral_flatness` |
| `zero_crossing_rate_mean` | `librosa.feature.zero_crossing_rate` |
| `mfcc_1_mean` … `mfcc_13_mean` | `librosa.feature.mfcc(n_mfcc=13)` |
| `hpss_harmonic_ratio`, `hpss_percussive_ratio` | energy split from `librosa.effects.hpss` |
| `sub_band_energy_ratio`, `low_band_energy_ratio` | STFT band-energy fractions below 250 Hz / 500 Hz |
| `tempo_primary_source`, `feature_extractor_version` | metadata, set to this module's own values |

**Intentionally NOT reimplemented** (present in `track_features.csv` but never named as required by spec §§2-3/§5 — noted in the module docstring so it's an explicit, documented gap, not a silent omission):

- `tempo_librosa`, `tempo_folded`, `beat_count` (superseded by `tempo_final`/`beat_ibi_mean` for this pipeline's purposes)
- `beat_this_*` columns (`beat_this_beat_count`, `beat_this_used`, `beat_this_tempo`, `beat_this_tempo_folded`, `beat_this_beat_consistency`) — these come from the BeatThis alternate beat tracker, a separate model dependency not needed by anything in spec §§2-3/§5
- `downbeat_count`, `downbeat_consistency`, `meter_estimate` — meter/downbeat analysis, not named as needed
- `lhl_syncopation_mean`, `lhl_syncopation_std`, `n_bars_analyzed` — syncopation-over-bars analysis, not named as needed
- `error` — original extractor's per-row error/exception column (not applicable here)

This covers all ~15+ features spec §§2-3 explicitly names (the "Arousal-relevant subset" and "Style/timbre subset") plus everything §5's prompt-template table references, which was the task's fallback instruction ("If matching all 52 exactly is impractical, implement the ~15 features named in spec sections 2-3").

## Design choices worth flagging

1. **Robust centroids are medians**, per spec §3, computed over `AROUSAL_FEATURES` (7 features) + `STYLE_FEATURES` (mfcc_1..13 + spectral_flatness_mean + hpss_harmonic_ratio + low_band_energy_ratio) — exactly the two subsets spec §3 names.
2. **Confidence weight** = `size_factor(bucket_n / 6) * stability_factor(1/(1+mean_CoV))`, clipped to `[0.05, 1.0]`. This is a documented heuristic (see docstring in `profile_from_songs.py`), not a calibrated statistical estimator — consistent with the spec's instruction to "report them honestly" and treat low-n buckets as soft priors (§1, §9).
3. **Input sanity checks** (§3) flag: (a) a "danceable" track that is both slow AND sparse relative to its own bucket's median, (b) a "relaxing" track that is both fast AND percussive relative to its own bucket's median, (c) danceable-centroid-tempo ≤ relaxing-centroid-tempo (arc can't descend). All three are implemented and exercised in the test (one deliberately mislabeled "danceable" track triggers flag (a)).
4. **Arc segments** (§4) use `GENRE_ENERGY_ORDER` (`groovegen.pd_controller`, short names `"r&b"/"pop"/"latin"`) for the controller-tier `genre` field — picked by nearest tempo to each arc genre's representative `GENRE_STYLES` tempo. This is intentionally a *different* lookup from the prompt's 6-word snap (see next point), because `CascadeController(genre_order=...)` only accepts the 3 short names.
5. **Prompt genre snap** (§5) picks the nearest of the 6 full `GENRE_STYLES` keys (`hip-hop/rap`, `r&b/soul`, `pop`, `latin/salsa`, `classic-rock`, `metal`) using a blend of tempo distance and a timbre-prior distance (percussive ratio, harmonic ratio, brightness) documented inline in `prompt_from_anchor.py`. Tuned so a bright, ~60% percussive, ~120 BPM danceable anchor snaps to `pop` (not `metal`/`classic-rock`, which share similar tempo but are distinguished by even higher percussive/brightness priors in the heuristic).
6. **Prompt template** implements every row of spec §5's table: tempo → "at about N BPM"; `hpss_percussive_ratio` → "driving, steady drums" / "sparse percussion"; `onset_density` + `event_density_on_vs_off` → "busy"/"minimal"; `spectral_centroid_mean` → "bright"/"warm, dark"; `hpss_harmonic_ratio` → "rich chords and melody"/"rhythm-forward, groove-led".

## Test run (synthetic 12-song input: 6 danceable incl. 1 deliberate mislabel, 2 enjoyed, 4 relaxing)

Full command: `python3 /home/user/workspace/test_pipeline.py`. No exceptions; also independently smoke-tested `extract_features()` against a real synthetic 120 BPM click-tone WAV (tempo detected ≈117.5 BPM, `hpss_percussive_ratio`≈0.71 — sane values for a percussive click track).

```
==============================================================================
STEP 1: profile_from_songs.build_profile()
==============================================================================

-- Bucket sizes --
{
  "danceable": 6,
  "enjoyed": 2,
  "relaxing": 4
}

-- Confidence weights (f(bucket_n, within-bucket variance)) --
{
  "danceable": 0.8303326561423447,
  "enjoyed": 0.32570403221719696,
  "relaxing": 0.6332144406603836
}

-- Centroids (median, robust) — arousal-relevant subset only --

  [danceable]
    tempo_final                  = 122.5000
    onset_density                = 5.6500
    rms_mean                     = 0.1850
    spectral_centroid_mean       = 2550.0000
    hpss_percussive_ratio        = 0.5900
    event_density_on_vs_off      = 1.3250
    plp_mean                     = 0.2950

  [enjoyed]
    tempo_final                  = 98.0000
    onset_density                = 3.6500
    rms_mean                     = 0.1375
    spectral_centroid_mean       = 1975.0000
    hpss_percussive_ratio        = 0.4400
    event_density_on_vs_off      = 0.9750
    plp_mean                     = 0.2150

  [relaxing]
    tempo_final                  = 71.0000
    onset_density                = 1.7000
    rms_mean                     = 0.0790
    spectral_centroid_mean       = 1290.0000
    hpss_percussive_ratio        = 0.2700
    event_density_on_vs_off      = 0.4850
    plp_mean                     = 0.1075

-- Sanity-check results --
  danceable_gt_relaxing_tempo: True
  ok (no flags at all):        False
  Flags:
    - bucket='danceable' index=5 trackID='danceable_06_MISLABELED_ballad'
      reason: tempo=78.0 BPM (bucket median 122.5), onset_density=1.90 (bucket median 5.65) — looks slow/sparse for a 'danceable' pick.

==============================================================================
STEP 2: arc_from_profile.arc_from_profile()
==============================================================================

  Segment 1: tempo=122.5 BPM, arc_genre='pop'
    anchor_weights: {'danceable': 1.0, 'enjoyed': 0.0, 'relaxing': 0.0}

  Segment 2: tempo=110.2 BPM, arc_genre='pop'
    anchor_weights: {'danceable': 0.5, 'enjoyed': 0.5, 'relaxing': 0.0}

  Segment 3: tempo=84.5 BPM, arc_genre='r&b'
    anchor_weights: {'danceable': 0.0, 'enjoyed': 0.5, 'relaxing': 0.5}

  Segment 4: tempo=71.0 BPM, arc_genre='r&b'
    anchor_weights: {'danceable': 0.0, 'enjoyed': 0.0, 'relaxing': 1.0}

  Full tempo band: [122.5, 110.2, 84.5, 71.0] BPM (monotonically non-increasing: True)

==============================================================================
STEP 3: prompt_from_anchor.prompt_from_anchor()
==============================================================================

  Segment 1 (122 BPM, arc_genre=pop):
    "a bright pop groove at about 122 BPM, driving, steady drums, busy rhythmic activity, balanced chords and rhythm"

  Segment 2 (110 BPM, arc_genre=pop):
    "a bright pop groove at about 110 BPM, steady drums, busy rhythmic activity, balanced chords and rhythm"

  Segment 3 (84 BPM, arc_genre=r&b):
    "a balanced-tone r&b/soul groove at about 84 BPM, steady drums, minimal rhythmic activity, rich chords and melody"

  Segment 4 (71 BPM, arc_genre=r&b):
    "a warm, dark r&b/soul groove at about 71 BPM, sparse percussion, minimal rhythmic activity, rich chords and melody"

==============================================================================
SUMMARY
==============================================================================
  Sanity ok: False  (expected False: the synthetic set includes 1 deliberate mislabel)
  Arc tempos descend: True
  Generated 4 prompts, one per arc segment.

End-to-end run completed with no exceptions.
```

## What's next (out of scope here, per spec §8)

- Step 4, `generate_and_gate.py` (MusicGen generate + tempo-stability gate + WAV cache) — requires Colab GPU, one-time per user.
- Step 5, wiring the cached beds into nb15's segment loop — local/free but depends on step 4's cached output existing.
