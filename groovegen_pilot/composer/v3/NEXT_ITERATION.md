# v3 hip-hop: before the next iteration

The prototype (`v3.hiphop.0`) is preserved as it is. The next iteration starts
from the developer's listening, not from computational diversity metrics.
This note covers four things:

1. How to re-render the audition on the Mac with Musyng Kite, including the
   loudness calibration.
2. Why the upper levels add little measured drum density and energy.
3. The musical decisions to judge by ear before anything else is built.
4. The remaining risks for the real-time generator interface.

All numbers below were measured on FluidR3_GM, the only soundfont available
when the prototype was built. They are not perceptual results.

## 1. Re-render the audition on the Mac with Musyng Kite

**What this produces:**

- The same compositions, seeds, forms and notes as the FluidR3 package.
- One difference by design: each v3 composition's mix trim (the CC7 channel
  volumes of the melodic parts) is recalibrated on Musyng Kite, so v3 MIDI
  checksums change slightly.
- v2c MIDI is identical.
- `energy_u` becomes directly comparable with the locked energy table,
  because that table was measured on Musyng Kite.

### Step 1: separate worktree

A separate worktree leaves the locked checkout untouched, including its
working files and the Experiment 1 builder. Run these from your existing
checkout, the one that has `.venv/` and `soundfonts/`:

```bash
git fetch origin
```

```bash
git worktree add ../groove_gen_v3 claude/dazzling-brown-qz2gtb
```

### Step 2: reuse the venv and soundfont, and check them

```bash
export GG="$PWD"
```

```bash
cd ../groove_gen_v3 && ln -s "$GG/soundfonts" soundfonts
```

The `soundfonts` link is gitignored. It lets the v3 render test find Musyng Kite.

```bash
shasum -a 256 soundfonts/Musyng_Kite.sf2
```

Expect `ed8c5a34c28b0fbbc805d6bbae74a169582c1881b57219972052e822c7be35f0`, the
locked file pinned by `experiments/music_rating`. Then check the renderer and
the Python packages:

```bash
fluidsynth --version
```

```bash
"$GG/.venv/bin/python3.12" -c "import numpy, scipy, pretty_midi, librosa, pyloudnorm; print('ok')"
```

### Step 3: measure the v3 loudness table (once per soundfont)

```bash
cd groovegen_pilot && "$GG/.venv/bin/python3.12" audition_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --measure-levels
```

**What it measures:**

- Every palette program at five note lengths, and each drum sound.
- The predictor's offset, fitted on 18 uncalibrated v3 segments and 6 v2c
  hip-hop segments.
- The v2c `hiphop:3` loudness, which becomes the level-3 target.

It writes `composer/v3/levels_Musyng_Kite.json` and prints the offset, the
fit residual SD and the target.

**Acceptance:**

- A residual SD around 0.5 dB or less is good (FluidR3 gave 0.38 dB).
- Above about 0.8 dB, the loudness predictor does not fit Musyng Kite. Do not
  use that render to judge loudness, and send me the printout.

### Step 4 (optional): check the calibration

```bash
"$GG/.venv/bin/python3.12" audition_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --calibrate
```

This prints LUFS, drum rate and u per level for v2c and v3, and the solo
loudness of each v3 part at level 3. v3 level 3 should land within about
0.5 LU of v2c tier 3.

### Step 5: render the package

```bash
"$GG/.venv/bin/python3.12" audition_v3.py --sf2 ../soundfonts/Musyng_Kite.sf2 --out ../groovegen_v3_audition_musyng --zip groovegen_v3_audition_musyng.zip
```

**Output:** `../groovegen_v3_audition_musyng/` and
`../groovegen_v3_audition_musyng.zip`, both gitignored.

**What the script checks for you:**

- It stops if `levels_Musyng_Kite.json` does not exist, rather than
  calibrating with the FluidR3 table.
- The package README names the soundfont and the loudness table.
- It says "sha256 matches the locked file" for the project soundfont, and
  flags a table measured on another soundfont.

If you want to separate timbre from recalibration, `--rerender` plays the
FluidR3 package's MIDI unchanged through Musyng Kite:

```bash
"$GG/.venv/bin/python3.12" audition_v3.py --rerender <FluidR3 package dir> --sf2 ../soundfonts/Musyng_Kite.sf2 --out ../groovegen_v3_audition_rerender
```

### Step 6: tests

```bash
"$GG/.venv/bin/python3.12" -m pytest tests/test_v3_hiphop.py -q
```

Expect 29 passed. With the soundfont link in place, the render test runs on
Musyng Kite.

### Step 7: keep the table

`composer/v3/levels_Musyng_Kite.json` is a small calibration file, not audio,
and can be committed to the branch when you choose to. You can also send me
the printout from step 3. When you are done, remove the worktree:

```bash
git -C "$GG" worktree remove ../groove_gen_v3
```

Git refuses while the worktree holds untracked files, such as an uncommitted
`levels_Musyng_Kite.json`, so the table cannot be lost by accident.

## 2. Why the upper levels add little measured drum density and energy

**Method:**

- Medians over 6 v3 compositions × 2 segments, and 2 v2c seeds × 2 visits,
  on FluidR3.
- u is the locked ladder's 0-1 energy scale.
- Contributions are each feature's weight × z-score ÷ the u span.
- v3 is shown at composition tempo (as in the audition) and at tier tempo (as
  the runner would play it).

| | v2c L3 | v2c L4 | v2c L5 | v3 L3 | v3 L4 | v3 L5 | v3 tier-tempo L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|
| tempo (BPM) | 90 | 93 | 96 | 88.5 | 88.5 | 88.5 | 90 | 93 | 96 |
| drum onsets/s | 6.00 | 6.20 | 6.40 | 5.72 | 5.72 | 5.72 | 6.00 | 6.20 | 6.40 |
| LUFS | -20.4 | -18.8 | -18.0 | -20.2 | -19.0 | -18.1 | -20.2 | -18.9 | -18.0 |
| centroid (Hz) | 4929 | 3292 | 3397 | 2790 | 2789 | 2892 | 2809 | 2870 | 2984 |
| **u** | **0.645** | **0.702** | **0.765** | **0.555** | **0.620** | **0.667** | **0.569** | **0.667** | **0.741** |

**Findings:**

- **The drum-rate feature is capped by the 16th-note grid.** It counts
  distinct drum onsets per second in the MIDI, merging hits within 20 ms.
  - From level 3, both generators play hats on every 16th note. The rate is
    then 4 × tempo / 60, and nothing added within the bar can raise it.
  - Clap, tambourine, maracas and crash at L4-L5 land on 16ths already counted.
  - v2c's 6.0 → 6.2 → 6.4 is exactly 16ths at 90 → 93 → 96 BPM. **Its
    drum-rate rise comes from the tier tempo, not from more drums.**
- **Tempo is itself 20% of the energy score.** v2c gains it with every tier.
  The audition holds one tempo per composition, so v3 gets neither the tempo
  term nor the drum-rate rise that tempo drives.
- **The slope is nearly the same; the gap is an offset.**
  - From L3 to L5, u rises +0.120 for v2c and +0.112 for v3.
  - Both rises come almost entirely from loudness: +0.122 and +0.110.
  - v2c's tempo and drum-rate gains (+0.020, +0.021) are cancelled by its
    centroid falling at tiers 4-5 (-0.041).
  - At L3, v3 sits 0.09 below v2c. That is mostly brightness: centroid
    2.8 kHz against 4.9 kHz, -0.057. Flux and drum rate add -0.013 and
    -0.015.
  - At L5 the gap is 0.098: drum rate 0.036, tempo 0.025, flux 0.015,
    centroid 0.014.
- **With tier tempo** (the drop-in source's default), v3 reaches
  0.569 / 0.667 / 0.741. The remaining gap is brightness and flux.
- **The features cannot see layering on the same grid:** clap doubling the
  snare, percussion, counter-line, hook double. Whether L4 and L5 sound more
  intense is a listening question (section 3, item 10), not a metric to tune.

**Correction:** the earlier summary blamed the upper-level gap on the drum
rate staying at 5.72/s. That is part of the gap at L5 and none of the slope.

**Options, deliberately not implemented before listening:**

- A small per-level tempo nudge. This trades composition identity for
  measured energy.
- Brighter upper-level layers: ride, shaker, more open hats, a brighter double.
- 32nd-note hat rolls at L5. This is a trap idiom and may be wrong for boom-bap.
- Leaving it as it is, if L4-L5 already sound more intense.

## 3. Musical decisions to judge by ear before further implementation

Judge timbre on the Musyng Kite render (section 1). Judge structure on either
render. Timestamps refer to the package README's Timelines.

| # | v3 decision | Listen to | Question | What the answer changes |
|---|---|---|---|---|
| 1 | Three sub-styles: boom-bap, soul, dark | A2 and A3 (boom-bap), A1 and B1 (soul), A4 (dark) | Does each read as hip-hop? Is soul's m9/maj9 colour too jazzy? Is dark (A4: near-straight swing, pad chords) still hip-hop? | Keep, retune or drop a sub-style |
| 2 | Instrument palette | Hook: vibraphone (A1, A3), piano (A2, A4), muted guitar (B1). Keys: Rhodes (A1, B1), string stabs (A2), piano (A3), warm pad (A4). Double: flute (A1), celesta (A4) | Does any instrument sound cheap, General-MIDI-like or wrong for the style? | Palette tables per sub-style |
| 3 | Hats on every 16th from L3 (**chosen to match v2c's measured drum rate**) | A1-A4, B1 | Busy or trap-like for boom-bap? | If yes: 8ths at L3 and 16ths only at L4-L5, accepting a lower measured rate |
| 4 | Swing and late snare | A1 (swing 0.59) against A4 (0.50) | Laid-back, or sloppy? | Swing and snare-lag ranges per sub-style |
| 5 | Hook: a 2-bar motif entering at bar 5 (A1 about 0:11) | A1-A4 | Memorable? Audible over the keys? Too repetitive? | Motif cells, hook register and level |
| 6 | Mix: bass +1.5 dB, counter -3 dB, double -6 dB | A1, B1, C2 at L5 | Is the bass boomy? The hook buried? The counter distracting? | Role trims |
| 7 | Development operators | B1 1:56 (ornament), 2:19 (rhythm), 2:42 (return with ornament) | Audible, yet still the same tune? | Operator set and escalation threshold |
| 8 | Contrast and return | B1 0:46 (C), 1:09 (C2), 1:33 (R) | Is the contrast a welcome lift or a different song? Is the return recognisable? | Contrast strength, form templates |
| 9 | Section-end dropout fill (up to about 0.26 s near-silence) | A1 just before 0:46; B1 before 1:33 and 1:56 | An intentional break, or a glitch? | Fill set; dropout length |
| 10 | Level steps change texture and dynamics, not the piece | C1: L2→L3 at 0:23, L3→L4 at 0:46 (**coincides with the contrast section**), L4→L3 at 1:09. C2: one step every ~21 s, L1→L5 | Is each step perceptible and in proportion? Are L1-L2 still the same piece? Is L5 more intense, or only more cluttered? | Layer masks and dynamics per level |
| 11 | One tempo per composition | C1 (84 BPM throughout) against D3 (87/90/93/90) | Do higher levels feel less intense without a tempo rise? | Tempo policy; also the main compatibility question (section 4, item 2) |
| 12 | Darker sound than v2c | A1-A4 against D1-D2 | Is v3 dull, or v2c harsh? | Brighter upper layers or not; this also moves measured energy |
| 13 | Repetition over three minutes | B1 against D4 | Less repetitive, and still coherent? Any fatigue? | Form length; how often material renews |
| 14 | Loudness between compositions | A2 (about 1 LU quieter overall) against A1, A3, A4 | Noticeable? | Calibration target (whole segment against statement) |

**Feedback that will drive the next iteration** (a few lines per sample is
enough):

- **Rank A1-A4** from best to worst, with one reason each.
- **Per sample, 1-5:**
  - sounds like hip-hop;
  - would listen to it for 15 minutes;
  - groove;
  - hook;
  - for C1 and C2 only: still the same piece across levels.
- **Timestamps** of anything that sounds wrong, with a word on why.
- **Your top three problems** across the package.

Priorities for the next iteration come from these answers. The similarity
numbers in `evidence.json` stay secondary.

## 4. Remaining risks for the real-time generator interface

**Verified so far, with tests or measurements in this branch:**

- `V3SegmentSource.next_segment(genre, tier)` returns `(MIDI, info)`.
- It runs inside the unmodified `run_session_v2`, and the tier-tempo
  assertion holds.
- Other genres are byte-identical to `--generator v2c`, including with
  hip-hop visits interleaved.
- The trace's `gen_version` (`v3.hiphop.0`) identifies v3 segments.
- Generation takes about 3 ms per segment. Rendering takes 0.54-0.84 s per
  segment, the same as v2c, against the runner's 3.0 s render lead.

**Not changed:** LadderMPC, the RLS estimator, the plant model, the HR
estimator, the controller configuration, the ladder files
(`energy_table_v1.json`, `energy_order_by_ear.json`), the runner, v1/v2/v2c
and the existing tests.

**Open risks, largest first:**

1. **Energy against the locked ladder.**
   - The ladder places the hip-hop rungs by v2c's measured energy.
   - v3 measures lower on the same soundfont. At tier tempo: L1-L5 =
     0.064 / 0.306 / 0.569 / 0.667 / 0.741, against v2c's 0.119 / 0.351 /
     0.645 / 0.702 / 0.765.
   - The controller would believe a rung energy that v3 does not produce. The
     ladder order against neighbouring genres, the RLS gain estimate and the
     saturation-rotation band (0.03 u) all assume the table.
   - With the ladder locked, live use needs v3 to match v2c's per-tier energy
     on Musyng Kite (a generator-side change). The alternative, re-measuring
     the ladder, is a protocol decision. Measure on Musyng Kite first.
2. **Tempo policy.**
   - The runner requires the tier tempo, so live v3 would change tempo with
     level and ignore each composition's own tempo.
   - The audition used composition tempo, so C1 is not what the live path
     would play.
   - Before deciding, listen to a tier-tempo render of C1; one sample, on
     request. Using composition tempo live would need an opt-in runner change.
3. **Calibration table against the live soundfont.**
   - `HipHopV3Source` loads the FluidR3 table by default, and the source
     cannot know which soundfont the runner uses.
   - A runner on Musyng Kite would apply FluidR3-derived trims.
   - A misspelt or missing table name silently disables calibration.
   - The audition script now refuses both cases; the source does not yet.
     Before any live use: pass the Musyng table explicitly and make a missing
     table an error.
4. **Trace provenance.**
   - The runner labels every session-source segment `generator='v2_session'`;
     only `gen_version` tells v3 apart.
   - The composition id and section role reach the trace as `motif_theme_id`
     and `motif_role`.
   - Level, mix trim, levels table, tempo policy, state digest and MIDI
     checksum do not reach it (`TRACE_KEYS` is fixed); only the session
     summary records `generator: v3`.
   - Recording them would mean appending trace columns, an append-only change
     in the runner, which has not been made.
5. **Composition continuity across genre switches.**
   - v3 advances only on hip-hop visits. Leaving hip-hop and returning resumes
     the same composition mid-form, for example at its contrast section.
   - A composition lasts eight hip-hop segments, however long the time away.
   - No sample interleaves genres or jumps several levels at once (for
     example L1→L4); both are untested by ear.
6. **Experiment 1 guard.**
   - `experiments/music_rating/build_stimuli.py` stops when any non-`.md` file
     under `groovegen_pilot/` differs from `pilot-zero-v2c-locked`. On this
     branch it will stop.
   - That is the guard working: build Experiment 1 stimuli only from the
     locked checkout.
7. **Soundfont of the evidence.** Every number in this branch is from
   FluidR3. Nothing here certifies behaviour on Musyng Kite.
