# Bed feature profile — derived from Sophia's high-danceability sensory-motor tracks

**Purpose:** empirically ground the constant musical bed used in the Stage-1 groove study,
instead of an arbitrary vamp. We extract the *aggregate musical feature profile* of the
songs participants selected **for sensory-motor (structural/groove) appreciation** that
**also scored high on danceability**, then design the bed deterministically to match that
profile. No commercial audio is regenerated — only abstract feature targets are used
(copyright- and confound-safe).

## Target population

- Source: Sophia dataset, `music_condition == "sensory-motor"`, unique tracks (n = 224).
- High-danceability subset: top tercile of `song_dance` within sensory-motor → **n = 83
  tracks** (`song_dance` ≥ 70).

## Extracted profile (median · mean · IQR)

| Feature | Median | Mean | IQR | Bed design implication |
|---|---|---|---|---|
| `song_dance` | 76 | 76.7 | [72, 81] | (selection criterion) |
| `song_energy` | 70 | 67.7 | [58, 78] | moderate-high energy bed |
| `song_valence` | 60 | 59.1 | [46, 76] | slight **major/positive** lean (66% > 50) |
| `song_bpm` / `tempo_final` | **120** | ~119 | [105, 130] | **fix bed + study tempo at ~120 BPM** |
| `meter_estimate` | **4.0** | 3.8 | [4, 4] | **4/4** |
| `hpss_harmonic_ratio` | **0.7** | 0.7 | [0.6, 0.8] | harmonic content is *prominent* → a real bass+chord bed is justified (not a thin pad) |
| `low_band_energy_ratio` | **0.7** | 0.7 | [0.6, 0.8] | **bass-forward**; put energy in the low register |
| `hpss_percussive_ratio` | 0.3 | 0.3 | [0.2, 0.4] | percussion is the minority of energy in these mixes → bed can carry real weight |
| `beat_consistency` | 1.0 | 1.0 | [1.0, 1.0] | metronomic, loop-stable pulse |
| `onset_density` | 4.5 | 4.6 | [4.1, 5.2] | moderate event rate (the *bed* stays simple; drums carry density manipulation) |

**Top genres** (high-dance SM subset): pop (20), hip-hop (13), r&b (9), rap (7), trap (6),
art-pop / k-pop / synth-pop / pop-rap (5 each), soul / dance (4). → **loop-based, bass-forward,
harmonically simple popular-music idioms.**

## Bed design decisions (deterministic, matched to profile)

1. **Tempo:** 120 BPM (median of the subset; also matches Janata's danceable band and your
   Sophia H4 replication). This becomes the **fixed tempo** for Stage 1 — tempo is held
   constant so the 3 manipulated knobs (syncopation, density, swing) are unconfounded.
2. **Meter:** 4/4, 16-step grid (unchanged).
3. **Mode:** slight major/positive lean (valence median 60). To stay groove-neutral and avoid
   an over-bright bed, use a **modal/ambiguous progression** that isn't strongly major or
   minor — e.g. a Dorian or mixolydian-flavored vamp, or a I–vi loop. Chosen below: a
   **i–VII–VI–VII (Aeolian) loop** is too dark given valence 60; instead use a
   **I–V–vi–IV-adjacent or a static Dorian groove** (bright but not saccharine). Final pick:
   **A Dorian vamp (Am7 – D/A)** — bass stays on A (strong low-band anchor), the D chord adds
   the bright Dorian 6th, giving the "positive but cool" feel of pop/r&b/hip-hop without a
   bright major tonic. Loopable, harmonically simple, genre-appropriate.
4. **Bass-forward:** prominent fingered-bass root pulse in a low octave (matches
   `low_band_energy_ratio` 0.7). Bass is the loudest bed element.
5. **Harmonic prominence:** real sustained chords (electric-piano/pad), not a thin drone
   (matches `hpss_harmonic_ratio` 0.7). Bed sits clearly in the mix but still under the kit so
   the drum manipulation remains the perceptual figure.
6. **Simplicity:** the bed stays metronomic and low-event-rate (`beat_consistency` 1.0,
   `onset_density` ~4.5) so it never competes with the drum density/syncopation manipulation.

## Methods sentence (for the paper)

> "The constant harmonic bed was parameterized to match the central tendencies of tracks
> participants selected for sensory-motor appreciation and that scored in the top tercile of
> Spotify danceability (n = 83): a 4/4, 120-BPM, bass-forward Dorian vamp with prominent
> sustained harmony (median `low_band_energy_ratio` = 0.70, `hpss_harmonic_ratio` = 0.70).
> No commercial recordings were reproduced; only aggregate acoustic feature targets informed
> the synthesized bed."

## Honest limitations

- The dataset has **no key/mode or chord-progression labels**; mode is inferred indirectly
  from valence (a weak heuristic) and genre. The bed is therefore *informed by* the profile,
  not a precise reconstruction. This is fine for a deliberately-neutral constant bed and is
  stated as such.
- The bed is one fixed instrumental; it represents the *central tendency*, not the full
  diversity of the subset. That is by design (it must be constant across stimuli).
