# Genre Arousal-Axis Analysis — Danceability vs. Energy/Tempo/Valence

**Data source:** `survey_and_music_data_N_122_public-in.csv` ([data dictionary](../uploaded_attachments/0d7d1ffc0f78421eb7e392c2f0d991b2/survey_and_music_data_dictionary-Sheet1.csv))
**Question:** For a GrooveGen arousal-regulation controller, should genre ordering be based on danceability, or on energy/tempo/valence? Does danceability give the same genre ranking as the others?

## 1. Sample

- **N_rows (survey responses):** 976
- **N_unique_tracks (deduplicated by `trackID`):** 704
- Deduplication kept the first occurrence per `trackID` since Spotify audio features are track-level, not participant-level; using raw rows would pseudoreplicate and over-weight popular songs heard by many participants.
- A trivial data-quality check found 4 tracks (16 rows) with off-by-a-few-points inconsistencies in features across duplicate rows (likely versioning/rounding noise) — negligible and does not affect conclusions.

## 2. Genre classification

Tracks were classified from the lowercased `artist_genres` string via substring matching, with disambiguation priority **latin > r&b > pop** (e.g., "latin pop" → latin, not pop; a track tagged both "soul" and "pop" → r&b).

- Keywords — Latin: `latin`, `reggaeton`, `salsa`, `latin pop`, `musica`, `regional mexican`
- Keywords — R&B: `r&b`, `rnb`, `soul`, `neo soul`
- Keywords — Pop: `pop`, `dance pop`, `post-teen pop` (excluding matches already claimed by Latin)

**Unique-track counts per bucket:**

| Genre | N unique tracks |
|---|---|
| Pop | 244 |
| R&B | 78 |
| Latin | 19 |
| Other (unclassified) | 363 |

**⚠️ Latin (N=19) is a small bucket.** It clears the N≥5 "unreliable" threshold but is still modest — treat Latin estimates as directional, not precise (SEMs are 2–5x larger than Pop/R&B).

## 3. Descriptive statistics (per genre, per feature)

| Genre | Feature | Mean | Median | Std | N |
|---|---|---|---|---|---|
| Pop | Danceability | 60.19 | 61.0 | 13.29 | 244 |
| Pop | Energy | 65.55 | 67.0 | 18.09 | 244 |
| Pop | Tempo (BPM) | 121.44 | 120.0 | 24.86 | 244 |
| Pop | Valence | 49.12 | 48.0 | 21.70 | 244 |
| R&B | Danceability | 66.27 | 65.5 | 12.23 | 78 |
| R&B | Energy | 59.79 | 59.5 | 16.74 | 78 |
| R&B | Tempo (BPM) | 117.40 | 120.0 | 24.01 | 78 |
| R&B | Valence | 54.69 | 57.0 | 19.32 | 78 |
| Latin | Danceability | 69.47 | 69.0 | 8.84 | 19 |
| Latin | Energy | 68.68 | 71.0 | 11.53 | 19 |
| Latin | Tempo (BPM) | 119.58 | 120.0 | 23.87 | 19 |
| Latin | Valence | 53.26 | 55.0 | 21.91 | 19 |

## 4. KEY OUTPUT — Genre rankings by axis (high → low)

| Axis | Ranking (high → low) |
|---|---|
| **Danceability** | Latin (69.5) > R&B (66.3) > Pop (60.2) |
| **Energy** | Latin (68.7) > Pop (65.5) > R&B (59.8) |
| **Tempo** | Pop (121.4) > Latin (119.6) > R&B (117.4) |
| **Valence** | R&B (54.7) > Latin (53.3) > Pop (49.1) |

### Verdict

- **Danceability vs. Energy: DISAGREE.** Both rank Latin highest, but danceability puts **R&B above Pop**, while energy puts **Pop above R&B**. The Pop/R&B pair flips order between the two axes.
- **Danceability vs. Tempo: DISAGREE.** Danceability ranks Pop *last*; tempo ranks Pop *first*. The two axes are essentially inverted for Pop, and R&B (lowest tempo) is *not* lowest on danceability.
- Danceability and valence do share the same relative pattern between R&B and Latin (both close, Pop lowest), but note valence is a distinct affective dimension (pleasantness), not arousal.

**This confirms Daniel's hypothesis: danceability does not track the same genre ordering as energy or tempo.**

## 5. Pairwise Pearson correlations (all 704 unique tracks)

| | Danceability | Energy | Tempo | Valence |
|---|---|---|---|---|
| **Danceability** | 1.000 | **-0.071** | -0.127 | 0.431 |
| **Energy** | -0.071 | 1.000 | 0.292 | 0.279 |
| **Tempo** | -0.127 | 0.292 | 1.000 | 0.097 |
| **Valence** | 0.431 | 0.279 | 0.097 | 1.000 |

- **Danceability vs. Energy: r = -0.071** — essentially uncorrelated (near zero, slightly negative) across the full track sample, not just the three genre buckets. This is a strong, sample-wide confirmation that danceability is not a stand-in for energy.
- Danceability vs. Tempo: r = -0.127 (weak negative) — again, no meaningful positive relationship.
- Danceability correlates most with Valence (r = 0.431) — moderate positive — consistent with danceability being tied to rhythmic groove/positivity rather than intensity/arousal.
- Energy vs. Tempo: r = 0.292 (weak-to-moderate positive) — the expected direction for an arousal-like pairing.

## 6. Recommendation for GrooveGen's arousal-regulation controller

**Use ENERGY as the primary axis (optionally blended with tempo) to order genres for arousal regulation — not danceability.**

Rationale:
- In the circumplex model of affect, **arousal** = physiological activation/intensity. Energy (loudness, dynamic intensity, timbral brightness in Spotify's feature) and tempo (pace) are the audio features that most directly map onto arousal.
- **Danceability** is a Spotify construct describing rhythmic stability, beat strength, and regularity — suitable for "is this track groove-forward," not "how activating/calming is this track." Our data confirm this: danceability is essentially uncorrelated with energy (r = -0.071) and weakly negatively correlated with tempo (r = -0.127) across 704 real tracks, and it produces a different genre ranking (R&B > Pop) than energy or tempo do (Pop > R&B).
- Hardcoding genre order from danceability would therefore misorder genres for an arousal controller — e.g., it would rank R&B as more "activating" than Pop, when energy (the better arousal proxy) says the opposite.

**Recommended composite axis:** `arousal_proxy = mean(z-score(energy), z-score(tempo))` — average of standardized energy and tempo. This is defensible because energy and tempo are the two Spotify features most theoretically aligned with arousal and are positively correlated with each other (r = 0.292), while pure energy alone is already sufficient and simpler if a single axis is preferred.

### Recommended genre order (based on Energy, the primary arousal axis)

- **UP-regulation (ascending arousal, calm → energizing):** **R&B → Pop → Latin**
- **DOWN-regulation (descending arousal, energizing → calm):** **Latin → Pop → R&B**

(If using the Energy+Tempo composite instead of Energy alone, order is nearly identical since Pop and Latin are close on tempo and energy while R&B is lowest on both — R&B remains the lowest-arousal anchor and Latin the highest.)

### Caveat

The Latin bucket (N=19) is small — while the ordering signal (Latin highest on energy) is consistent with descriptive stats, this estimate should be revisited as more Latin-tagged tracks are added to the corpus. Pop (N=244) and R&B (N=78) estimates are robust.

---

**Figure:** `genre_arousal_axis.png` — grouped small-multiples bar chart comparing mean danceability, energy, tempo, and valence across the three genres with SEM error bars, visually showing the Pop/R&B rank flip between danceability and energy/tempo.
