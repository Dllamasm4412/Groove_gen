# GrooveGen v3: how the generator was updated and how it works

Report date: 2026-11-02. Branch `claude/dazzling-brown-qz2gtb`, draft PR #1 (not merged).
Generator versions described: `v3.hiphop.0` (hip-hop) and `v3.genres.1` (calm, lo-fi, R&B, pop, Latin, rock).

## 1. Summary

GrooveGen v3 is a new, opt-in music generator that sits beside the locked v2c generator. It does not
replace it. The physiological controller, the locked ladder and the live runner are unchanged.

What v3 changes is how a piece of music is made.

- **v2c** builds each 8-bar segment from a genre "cell" and then varies it.
- **v3** first decides a composition: its key, chord progression, melody, groove and instruments. It
  then writes each segment from that composition, at whatever intensity the configuration asks for.

The work went through four steps:

1. **Hip-hop v3:** a full composition model with form, development and five intensity levels. You
   listened to two packages of examples and were happy with their quality and variety.
2. **Multi-genre v3** (`genres.py`): 8-bar statements for the six other genres. Each genre has its
   own harmony, rhythm, instruments and bass-drum relationship.
3. **A candidate corpus** of 27 excerpts for the Qualtrics danceability study (IRB 26-0684), one per
   original study condition.
4. **A revision after your listening of that corpus.** Rock was rewritten as riff-based hard rock,
   and pop tier 1 was re-arranged.

All audio so far is rendered with FluidR3_GM, because Musyng Kite is not available in the build
environment. Section 9 has the one-command Musyng Kite render for the Mac.

## 2. Where we started: v2c

The locked v2c system (`pilot-zero-v2c-locked`) works like this:

- **The ladder.** The live controller (LadderMPC) chooses a cell: a genre and a tier, from a ladder
  of 27 cells ordered by a composite energy score. That score weights rendered loudness 0.40, drum
  onset rate 0.25, tempo 0.20, spectral centroid 0.10 and flux 0.05, then re-orders the cells by ear.
- **Per-genre cells.** Each genre has its own generator. The tier maps to a density value
  (0.15 to 0.95), and for hip-hop and rock also to a tempo.
- **Segments.** `SessionComposer` makes each 8-bar segment from a base seed per cell. It varies the
  drums and develops a motif under novelty guards.

Limits that motivated v3:

- **Same material across seeds.** Different stim seeds often give the same material transposed. Two
  hip-hop v2c seeds scored 0.996 on harmonic similarity and shared 47-75% of their melodic phrases.
- **No sense of a piece.** A "piece" is a loop with variations. There is no statement, contrast and
  return.
- **Weak rhythmic difference between tiers in some genres.** In the original 8-bar segments these
  tier pairs share almost the same drum part: calm 1-2, R&B 1-2, hip-hop 4-5, and rock 1-2, 2-3 and
  3-4. There, the tier difference is mostly loudness and tempo.

## 3. How v3 works

### 3.1 Identity and realisation are separate

Every v3 generator has two stages.

| Stage | Decides | Depends on |
|---|---|---|
| **Composition** (`create_spec`) | key and mode, chord progression, a two-bar melodic motif, groove variant, instrument palette, swing; for hip-hop also sub-style, a second chord loop, form and development operators; for rock a guitar riff | the seed only |
| **Realisation** (`realize`) | which instruments play, how many notes per bar, drum pattern density, dynamics; tempo where the configuration defines it | the tier / level |

Because identity depends only on the seed, the same composition can be played at any intensity. The
melody, chords and groove stay recognisable while the texture changes. The same seed always gives
the same MIDI, byte for byte.

### 3.2 Harmony

Each genre has a progression grammar: a set of 4-bar progressions per mode, with weights.

- **Pop:** I-V-vi-IV and relatives, with occasional add9 and maj7 colours.
- **R&B:** Dorian and minor ninth-chord vamps.
- **Lo-fi:** ii-V-I with extended chords.
- **Latin:** harmonic minor with V7, and son-montuno major progressions.
- **Calm:** add9 and maj7 chords with slow harmonic rhythm.
- **Rock:** Aeolian and Mixolydian power-chord progressions.
- **Hip-hop:** a transition grammar per sub-style (boom-bap, soul, dark) that builds two loops.

An 8-bar excerpt plays the progression, then its first two bars again. Bar 7 is a cadence chord and
bar 8 the tonic, so every excerpt is a closed phrase.

### 3.3 Melody

1. **Motif.** A two-bar motif is built from rhythm cells specific to the genre. Pop uses syncopated
   8ths, R&B 16th-note syncopations, Latin anticipations, calm long notes, rock 8th-note riff
   rhythms. Pitches come from a constrained diatonic walk: mostly steps, a leap is followed by a step
   back, no three repeated notes.
2. **Second bar.** The second bar sequences, varies or answers the first. A motif is kept only if,
   once fitted to the chords, it is a singable line whose two bars differ.
3. **Fitting to the chords.** Notes on the beat land on chord tones. Other notes avoid clashing
   semitones (the "avoid-note rule"). The fitting keeps the motif's intended up/down contour, so
   snapping to chord tones never flattens it into repeated notes.
4. **Leap limit** (six genres). Any interval wider than a major sixth is refitted within that
   distance, so phrases have no octave jumps. Leaps over a sixth fell from 5% to under 0.1% of
   intervals.
5. **The statement.** The 8 bars are motif, open answer (ending on the 2nd or 5th), motif, closed
   cadence (ending on the tonic, held). This is the same statement shape you approved in hip-hop.

### 3.4 Rhythm, bass and accompaniment by genre

| Genre | Drums / percussion | Bass and its relation to the drums | Accompaniment | Typical instruments |
|---|---|---|---|---|
| **Hip-hop** | boom-bap kick patterns per composition, backbeat with snare lag, 16th hats with accents from level 3, ghost notes, clap and percussion at level 4-5 | locked to the kick and the chord changes, pickups into changes | stabs, held chords or neo-soul comping, kept below the melody | piano / Rhodes / strings / pad, vibraphone or piano hook |
| **Pop** | backbeat with three kick variants; 8th then 16th hats; claps, tambourine; four-on-the-floor at tier 5 | locked to the kick, octave pops and approach notes at higher tiers | half-note strums up to 8th-note piano pulse, pad at tier 4-5 | piano or Rhodes, acoustic guitar, finger or synth bass |
| **R&B** | straight half-time feel (snare on beat 3), 16th hats, ghost snares, triplet and 32nd hat rolls at tier 4-5 | synth sub-bass on the kick with a semitone approach into each change | rootless 3-5-7-9 voicings, syncopated stabs, pad at tier 4 | Rhodes, synth bass, vibraphone / flute / guitar / alto sax lead |
| **Lo-fi** | soft swung boom-bap, late snare, ghost notes, shaker at tier 3 | upright bass, loose walking figures | rolled rootless voicings played late, broken-chord arpeggio at tier 3 | Rhodes or piano, upright bass, vibraphone / guitar / flute / muted trumpet |
| **Latin** | son clave (2-3 or 3-2), maracas, then conga tumbao and guiro, bongos and soft bombo, cowbell, timbale fills | tumbao: the 5th on the "and" of 2 and the next chord's root anticipated on beat 4 | block chords on the clave, then piano montuno (offbeat-accented, octaves at tier 3+) | piano, acoustic bass, flute / trumpet / nylon guitar |
| **Calm** | the original calm condition's light pulse (soft kick, hats, rim) well under the piano | piano left-hand roots and fifths | rolled chords (tier 1), flowing broken chords (tier 2) | piano, with piano, flute or strings melody |
| **Rock** (v3.genres.1) | stadium backbeat: kick and snare, 8th hats then ride and bell, crashes, tom fills | picked bass on the riff's chord hits (tier 1-2), driving 8ths (tier 3+) | the riff itself (section 4), a second guitar from tier 3 | overdriven / distortion guitars, picked bass, lead guitar at tier 4-5 |

### 3.5 Tiers and levels

The tier is the configuration's intensity. Across genres it follows one plan, carried out in each
genre's own idiom:

| Tier | What it adds |
|---|---|
| 1 | The genre's skeleton: basic beat, simple bass, sustained or sparse accompaniment. Hip-hop plays only the melody's main notes here; pop now plays the full melody. |
| 2 | The full basic groove and bass figure. |
| 3 | The genre's characteristic subdivision (16th hats, montuno, palm-muted second guitar), ghost notes, fills. |
| 4 | An extra percussion layer, a busier bass, a pad, counter-line or lead answer. |
| 5 | The fullest texture: second percussion layer, crashes, a doubled hook or full lead, the most active bass. |

**Tempo is the configuration's, not the generator's:** constant per genre for calm, lo-fi, R&B, pop
and Latin, rising with tier for hip-hop and rock (`GENRE_CFG` tier tempos).

### 3.6 Mix and loudness

- **Within a piece:** each role has a channel level (MIDI CC7) per genre, with a per-instrument trim.
  These were set from solo-part loudness measurements towards conventional balances. For example,
  pop and rock drums sit level with the lead, R&B bass is on top, and lo-fi drums are soft but
  present. Rock guitars are panned left and right with the lead in the centre. The tables are fixed
  in code, so the MIDI does not depend on the soundfont.
- **Hip-hop:** a MIDI loudness predictor (`levels.py`) calibrates each composition's mix to the v2c
  hip-hop tier-3 loudness.
- **In the study corpus:** each excerpt is then scaled by one static gain, so its integrated loudness
  equals that of the original condition's 8-bar segment (section 5).

### 3.7 Rule checks

Every excerpt is checked automatically. The checks cover:

- tempo, and no vocal instrument programs;
- note ranges and overlapping repeats of the same note;
- the genre's drum backbone in every bar, at the tiers where it applies;
- bass on chord tones, starting on the root;
- melody: notes on the beat are chord tones, and the melody and the phrase both end on the tonic;
- accompaniment on chord tones of the current or anticipated chord;
- rock riffs within the chord root's blues-pentatonic set.

Result: 0 violations across 880 excerpts (40 seeds × every tier of the six genres) and 58 hip-hop
segments. These checks show the parts agree with each other. They cannot show the music is good;
listening does that.

## 4. Rock after your feedback (v3.genres.1)

You found S03 (rock, tier 1) and S04 (pop, tier 1) poor. You asked for rock in the spirit of
"Back in Black", "Enter Sandman", "Thunderstruck" and "Rock You Like a Hurricane".

**What was wrong:**

- **Rock tier 1** was clean jazz-guitar triads strummed in half notes, with a slow lead holding only
  the melody's main notes. That is closer to a country ballad than rock.
- **Pop tier 1** had whole-note acoustic-guitar strums, a side-stick beat and the same held-notes-only
  melody. That melody jumped between the same two notes a sixth apart, and the arrangement was so
  thin it needed +9.5 dB to reach its condition's loudness.

**What rock is now.** Driven guitars play a generated two-bar riff at every tier, transposed to each
chord. The riff comes from one of four techniques of that tradition:

| Riff type | Technique |
|---|---|
| space | power-chord stabs with rests, a minor-pentatonic run into the next bar |
| drive | power chords on every 8th note, a lick at the end of the second bar |
| chug | palm-muted 8ths with syncopated power-chord accents and a dark passing note (flat second or flat fifth) |
| pedal16 | the low root on every other 16th note with a moving pentatonic line in between |

The tier builds the arrangement:

| Tier | Arrangement |
|---|---|
| 1 | An intro form of the riff over a plain backbeat |
| 2 | The full riff, 8th-note hats |
| 3 | A second guitar under the riff, crash accents, a fill |
| 4 | Ride cymbal drive, a lead guitar answering the riff in bars 3-4 and 7-8 |
| 5 | Stadium texture: crashes, tom fills, the lead guitar carrying a melodic hook throughout |

The riffs and hooks are newly generated from these techniques. **No riff, melody or arrangement of
those songs is reproduced**, as the study's rule against copying recognisable commercial material
requires. Driven guitars, a stadium backbeat, pedal-point riffs, palm-muted chugs and melodic minor
hooks are the shared style; the notes are new.

**Pop tier 1 now:** the full melody, a soft snare on 2 and 4, and half-note strums.

**What stayed the same:** the rock tempos (110-130 BPM by tier, the configuration's), the seeds, the
selection rule and loudness matching. Every other excerpt is byte-identical to the version you heard
(21 of 27). Only S03, S04, S05, S14, S21 and S24 changed.

## 5. The candidate corpus pipeline

`experiments/qualtrics_v3_candidate/build_candidate.py` builds the corpus in eight steps:

1. **Conditions.** It reads the 27 conditions of the original study from
   `experiments/music_rating/stimuli/manifest.json`, read only: genre × tier, ladder rung, tempo.
2. **The original material.** For each condition it regenerates the original 8-bar v2c segment and
   checks its MIDI hash against the frozen manifest. All 27 match.
3. **Candidates.** Candidate k uses seed = first 4 bytes of
   sha256("qualtrics-27-v3-candidate-1|genre|tier|k").
4. **Screening, technical only.** Rule checks; peak at or below −1 dBFS after loudness matching; no
   silence over 0.5 s inside the music; under 50% phrase overlap with excerpts already chosen. The
   first passing candidate is kept. No listening or danceability measure is used, and candidate 0
   passed for every condition.
5. **Rendering.** The same path as the original stimuli: FluidSynth, gain 0.8, master −2.5 dB; 8 bars
   plus a quarter-bar release fade; a 3 ms fade-in.
6. **Loudness.** One static gain matches the original condition's 8-bar loudness on the same
   soundfont. The locked limiter applies only if needed; it was not needed.
7. **Measurement.** Tempo; loudness and peak; drum, hat and bass density; bass-on-kick share; an
   off-beat index; spectral centroid, flux and pulse clarity; the composite energy score; and the
   corpus-named features (percussive ratio, pulse, bass band, onset density). The corpus-named
   features use the repository's re-implementation of the corpus extractor, so they are approximate.
8. **Packaging.**
   - `A_qualtrics_mp3/S01-S27.mp3`, neutral names, no tags;
   - WAV masters, MIDI sources and internal 10 s previews;
   - the original conditions as 8-bar references, and candidate practice and volume clips;
   - `E_analysis/`: answer key, measurements, generation log, QC report, condition audit, design and
     confound notes, protocol differences, Qualtrics mapping, listening sheet, revision history.

**Results for v3.1:**

- **Files:** 27/27 pass every file check. Durations 15.2-30.5 s, peaks −11.5 to −1.8 dBFS, loudness
  −27.9 to −14.2 LUFS, as in the original configurations.
- **Within each genre,** every tier step adds rhythmic activity or layering. Two steps barely raise
  the energy score: R&B 3→4 and rock 2→3. In both, the original higher-tier condition is no louder than
  the one below (R&B tier 4 is about 1 LU quieter), and the excerpts inherit that loudness.
- **Across the 27,** the energy score follows the ladder rung (Spearman 0.83; the original segments
  give 0.96).
- **Distinctness:** no two excerpts share more than 6% of their melodic phrases.

None of this measures perceived danceability. That is what the participants' ratings are for.

## 6. Compatibility with the real-time system

- **Not changed:** LadderMPC, RLS, the plant model, the HR estimator, the controller configuration,
  the locked ladder, the live runner and the v1/v2/v2c generators. The original study's stimuli,
  manifest and Qualtrics files are untouched.
- **Live path:** it does not import `genres.py` (a test checks this).
- **Hip-hop drop-in:** `V3SegmentSource` can replace `SessionSegmentSource` in the runner; hip-hop
  then comes from v3, everything else from v2c.
- **Byte-identical earlier outputs:** the theory tables gained new entries only. The first audition
  package re-renders byte-identically.
- **Not yet live-ready.** The six new genres compose single 8-bar statements; their compositions do
  not yet develop across segments the way hip-hop does. v3 hip-hop measures lower than v2c on the
  ladder's energy score, so live use would need either matching energy or a ladder decision.

## 7. Evidence and its limits

| Evidence | What it shows | What it does not show |
|---|---|---|
| Rule checks (0 violations) | parts agree with each other and the chords | that the music is good |
| Distinctness (≤ 6% phrase overlap, distinct motifs for every seed) | different seeds give different material | that the differences are interesting |
| Per-tier measurements | the intended rhythmic and layering differences are present | that listeners feel them |
| Your listening of v3.0 | most excerpts sound good; S03 and S04 did not | the revised rock and pop tier 1 (not heard yet) |
| Byte-identity checks | earlier approved material is preserved | anything about new material |

## 8. Known limitations and next steps

1. **Listen to the six revised excerpts** (before/after MP3s in `listening/changed_since_.../`).
2. **Render with Musyng Kite** and re-check the mix. The part balances were set on FluidR3.
3. **Decide the intended-danceability coding before enrolment.** The recommendation is the
   within-genre tier with genre in the model (`E_analysis/README.md`, section 3).
4. **Practice and volume clips, and an IRB check** on replacing the stimuli.
5. **Later:** form development across segments for the six new genres, so they can run live like
   hip-hop. `genres.py` (about 1,260 lines) should be split by genre before that.

## 9. Files and commands

| File | Role |
|---|---|
| `groovegen_pilot/composer/v3/hiphop.py`, `state.py`, `source.py`, `levels.py`, `checks.py` | hip-hop v3: composition model, live-compatible source, loudness calibration, rule checks |
| `groovegen_pilot/composer/v3/theory.py` | chords, modes, voicing, swing grid, melody fitting helpers |
| `groovegen_pilot/composer/v3/genres.py` | the six other genres (v3.genres.1) and their rule checks |
| `groovegen_pilot/audition_v3.py`, `listening_eval_v3.py` | the two hip-hop listening packages |
| `experiments/qualtrics_v3_candidate/` | the candidate corpus builder, reports and tests |
| `groovegen_pilot/tests/test_v3_*.py`, `experiments/qualtrics_v3_candidate/tests/` | 60 tests: 50 for v3, 10 for the builder |

Rebuild the candidate corpus from the repository root:

```bash
python experiments/qualtrics_v3_candidate/build_candidate.py build --sf2 /path/to/soundfont.sf2 --zip
```

Render the same 27 MIDI files with Musyng Kite on the Mac. It needs `ffmpeg`, and the v3.1 package
(the listening ZIP is enough) unzipped in the repository root:

```bash
.venv/bin/python3.12 experiments/qualtrics_v3_candidate/build_candidate.py build --sf2 soundfonts/Musyng_Kite.sf2 --selection groovegen_qualtrics_27_candidate_v3.1_FluidR3_GM_PRELIMINARY/E_analysis/stimulus_manifest.json --zip
```
