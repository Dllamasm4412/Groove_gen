# GrooveGen

A drum-groove generator with a **genre-personalized, deep-learning-generated musical bed**, plus the
secondary analysis of Sophia's dataset that grounds the bed, the knob hierarchy, and the Stage-1
experiment design.

The generator produces short, loopable drum patterns whose groove is controlled by a small set of
interpretable **knobs**, ordered by **evidence strength**:

- **Tier 1 (load-bearing):** event density, tempo (107–126 BPM), beat salience — the firmest groove
  evidence and the winners in our own Sophia analysis. These carry the system's core groove claim.
- **Tier 2 (validated demonstrations):** syncopation (reproduces the canonical inverted-U) and swing
  (contested/novel). Real but smaller effects — swept to demonstrate fidelity, not to anchor the system.

Under the drums sits a musical bed — bass + chords + melody — **generated in the participant's
preferred genre** by a deep-learning symbolic-music model, then
**frozen** so it is identical across every knob setting. Genre is a per-participant constant, not a
manipulated factor, so any change in perceived groove is attributable to the drum manipulation and not
to the bed — that invariance is what makes the planned listening study causally clean.

**Why genre-personalize?** The strongest lesson from Sophia's dataset (and Senn et al. 2018) is that
*style fit and familiarity* dominate the urge-to-move — explaining more variance (R²≈0.12–0.15) than
every structural rhythm feature combined (each R²≈0.01). So we harness that effect via the bed instead
of fighting it with an arbitrary one. See `GROOVEGEN_V1_REPORT.md` §4 ("What we learned from Sophia").

---

## What's in here

```
groovegen_project/
├── README.md                ← you are here
├── config.py                ← central, portable path config (no absolute paths)
├── requirements.txt
│
├── notebooks/               ← Colab-runnable; core study pipeline is 04 → 05 → 06
│   ├── 00_setup.ipynb            environment + soundfont check, audio smoke test
│   ├── 01_sophia_analysis.ipynb  Sophia secondary analysis (Layers 1–2 + trait moderator)
│   ├── 02_bed_design.ipynb       derive the bed profile + inspect the hand-authored beds
│   ├── 03_generate_stimuli.ipynb render the knob stimulus grid (hand-authored bed)
│   ├── 04_genre_analysis.ipynb   ★ rank genres in Sophia's data → lock the study menu (hh/r&b/pop)
│   ├── 05_dl_bed_generation.ipynb★ build a rich genre style-seed → AMT embellishes → freeze to MIDI (GPU)
│   ├── 06_drum_overlay_demo.ipynb★ register a frozen bed + overlay knob-controlled drums + render
│   └── 07_song_generator.ipynb   ★ give top-3 genres → generate 3 FULL SONGS (hero song form), WAV→Drive
│
├── groovegen/               ← the core library (imported by the notebooks)
│   ├── groovegen.py              generator: GrooveParams, PatternBuilder, BedProfile, render
│   ├── dlbed.py              ★   DL-bed adapter: AMT MIDI → frozen BedProfile + build_genre_song
│   ├── genre_styles.py       ★   GENRE STYLE ENGINE: per-genre rich seeds (5 families)
│   ├── build_stimulus_grid.py    builds the experiment stimulus grid + manifest
│   ├── render_iterations.py      renders the demo songs
│   └── bayesopt.py               Stage-2 per-person Bayesian sweet-spot search
│
├── sophia/                  ← secondary-analysis scripts + written memos
│   ├── run_analysis.py           Layers 1 & 2  → analysis_results.json
│   ├── make_plots.py             → outputs/figures/layer1_validation.png, layer2_betas.png
│   ├── trait_moderator_analysis.py → trait_moderator_results.json
│   ├── genre_analysis.py     ★   genre-family danceability ranking → genre_analysis_results.json
│   ├── BED_FEATURE_PROFILE.md     how the bed target was derived from the data
│   └── RESULTS_MEMO.md            written interpretation of the analysis
│
├── data/                   ← input data (Sophia's study)
│   ├── survey_and_music_data_N122.csv
│   ├── track_features.csv
│   └── data_dictionary.csv
│
├── outputs/                ← everything generated (created on first run)
│   ├── audio/                    rendered .wav / .mid / .mp4
│   └── figures/                  rendered .png
│
├── soundfonts/             ← drop FluidR3_GM.sf2 here for best sound (see below)
└── STAGE1_PROTOCOL.md      ← the full Stage-1 study design (hypotheses, power, prereg)
```

---

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

You also need the **FluidSynth** system library (the Python `pyfluidsynth`
package binds to it) and a General-MIDI **soundfont**.

- **Linux:** `sudo apt-get install fluidsynth fluid-soundfont-gm`
- **macOS:** `brew install fluid-synth` and download a soundfont (below)
- **Colab:** `!apt-get install -y fluidsynth fluid-soundfont-gm` (notebook `00` has a ready-made cell)

### 2. Get a good soundfont (this is what fixed the "8-bit" sound)

The tiny default `TimGM6mb.sf2` (6 MB) renders thin and synthetic. Use the full
**FluidR3_GM.sf2** (~148 MB) instead — its sampled instruments sound realistic.

`config.find_soundfont()` looks in this order:

1. `soundfonts/FluidR3_GM.sf2` inside this project ← **recommended: drop it here**
2. `/usr/share/sounds/sf2/FluidR3_GM.sf2` (installed by `fluid-soundfont-gm`)
3. `/usr/share/sounds/sf2/default-GM.sf2`
4. `TimGM6mb.sf2` (low-quality fallback)

To place it in the project:

```bash
# if fluid-soundfont-gm is installed:
cp /usr/share/sounds/sf2/FluidR3_GM.sf2 soundfonts/
# or download it:
# https://archive.org/details/fluidr3-gm-gs  (FluidR3_GM.sf2)
```

### 3. Run the notebooks in order

```bash
jupyter lab    # or: jupyter notebook
```

Open `notebooks/00_setup.ipynb` and run top to bottom, then `01`, `02`, `03`.
Each notebook is self-contained and imports paths from `config.py`, so you can
clone this folder anywhere and it just works.

---

## The genre-personalized DL bed pipeline (notebooks 04 → 05 → 06)

This is the current core of the system — the "A+B" design. Run these three in order, **on Colab with a
GPU runtime for notebook 05** (Runtime → Change runtime type → T4 GPU). 04 and 06 run fine on CPU.

| # | Notebook | What it does | Runtime |
|---|----------|--------------|---------|
| 04 | `04_genre_analysis.ipynb` | Ranks genre families in Sophia's data by danceability; locks the study menu (**hip-hop/rap, R&B/soul, pop**). Writes `sophia/genre_analysis_results.json` + a figure. | CPU |
| 05 | `05_dl_bed_generation.ipynb` | Builds a **rich per-genre style seed** (`genre_styles.build_style_seed`) and lets the **Anticipatory Music Transformer** (Stanford CRFM, Apache-2.0) embellish it; audits and freezes each to `outputs/dl_beds/bed_<genre>.mid`. Falls back to the style seed directly if no GPU. | **GPU** (T4) |
| 06 | `06_drum_overlay_demo.ipynb` | Registers a frozen bed as a GrooveGen `BedProfile` via `dlbed`, overlays the **knob-controlled drums**, and renders a Tier-1 (density) sweep. Embeds audio inline. | CPU |
| 07 | `07_song_generator.ipynb` | **Product/demo notebook.** You give your **top-3 genre families** (5-genre menu); for each, it builds the genre style seed → AMT embellishes → arranges it into a **full song** (Intro→Verse→Chorus→Chorus, the champion-song form) via `dlbed.build_genre_song`, carrying the genre's instrumentation through, overlays Tier-1 drums, and saves **3 song WAVs** to `MyDrive/GrooveGen/songs/`. | **GPU** (T4) |

**Two paths through the DL pipeline.** Notebooks 05→06 are the *study* path: beds are **frozen plain loops** (`sections=None`, knob-invariant) so the only thing that changes across stimuli is the manipulated knob. Notebook 07 is the *demo/product* path: the same AMT bed is arranged into a **full song form** (`build_genre_song`, Intro→Verse→Chorus lift) for listening — not for the controlled experiment.

### The genre style engine (`groovegen/genre_styles.py`)

**Why genres used to sound alike.** The AMT was trained on Lakh MIDI with **no genre labels or text
conditioning** — it cannot turn the word *"salsa"* into a montuno. It only *embellishes* MIDI that is
already stylistically suggestive. The old seed held one **sustained block chord per bar for every
genre** (identical rhythm, voicing, articulation, and instrument), so all genres collapsed to the same
flat piped piano. Genre identity has to live in the **seed**, not the model.

`genre_styles.py` fixes this with a `GENRE_STYLES` table of `StyleSpec`s — one per family — encoding the
musical fingerprint of each genre, and `build_style_seed(genre, bars=2)` renders a rich, multi-instrument
MIDI seed that AMT then embellishes (or that is used directly on CPU). The 6 supported families:

| Genre | Tempo | Voicing | Comp style | Comping / instrumentation |
|-------|-------|---------|-----------|---------------------------|
| **hip-hop/rap** | 90 | dorian min7 open | block | sparse syncopated Rhodes stabs + sub bass |
| **R&B/soul** | 96 | rootless maj9 | block | lush behind-the-beat neo-soul Rhodes comp |
| **pop** | 120 | add9 triad | **arp** | funky plucky **clavinet** arpeggio over a syncopated **fingered bass** — bright, danceable groove modeled on the top-danceability pop in Sophia's data (*Billie Jean / Break My Stride* family) |
| **latin/salsa** | 180 | salsa close | block | piano **montuno** + bass **tumbao** locked to a **2-3 clave** + congas + horn stabs |
| **classic-rock** | 94 | power chords | **staccato_chug** | chunky **palm-muted staccato** power-chord stabs with **space** + heavy low pedal — *AC/DC "Back in Black"* |
| **metal** | 123 | power chords | **staccato_chug** | relentless palm-muted **minor chug** on an open-E pedal — *Metallica "Enter Sandman"* |

The first three are the **locked study menu** (highest danceability in Sophia's data); **latin/salsa**,
**classic-rock**, and **metal** are showcase/demo genres for the engine. (Latin scored highest in Sophia's
data but is thinly sampled, n=14, so it stays demo-only, not in the controlled study menu.) Each seed is
verified to produce a distinct fingerprint — different programs, note density, pitch range, and
percussion/horns for salsa — before it reaches the model.

**Comp styles.** `comp_style` controls how each chord articulates on the comp grid: `block` (full chord on
every step), `sustain_accent` (full chord rings on strong beats, light stabs on weak), `arp` (one chord-tone
at a time, walking the chord — the funky danceable-pop motor), and `staccato_chug` (short, hard, palm-muted stabs with
silence between them — the rock/metal groove where *the space is the groove*). Pop and rock were rebuilt from
their real reference records: pop is a funky plucky clavinet arpeggio (not a buzzy saw lead) tuned to the
top-danceability pop profile in Sophia's data, and rock is staccato muted-power-chord swagger (not a
ringing 8th-note wall).

### Running on Google Colab

Each notebook's first cell is a self-contained Colab bootstrap (installs deps + FluidSynth + the
Anticipatory-Music-Transformer package). To get the project into the session, upload
`groovegen_project_v1.zip` to the Colab file pane and unzip it:

```python
from google.colab import files; files.upload()   # pick groovegen_project_v1.zip
!unzip -q groovegen_project_v1.zip
%cd groovegen_project
```

Then open notebook 04, run top to bottom, and proceed to 05 (GPU) and 06.

### Using the DL-bed adapter directly (Python)

```python
from groovegen import dlbed

# Freeze a generated MIDI bed (from notebook 05) and sweep a Tier-1 knob on top of it:
results = dlbed.render_genre_demo(
    midi_path="outputs/dl_beds/bed_pop.mid",
    genre="pop", tempo=120,
    out_dir="outputs/audio/genre_demo",
    sweep="density",          # "density" (Tier 1) | "tempo" (Tier 1) | "syncopation" | "swing"
    target_seconds=12.0,
)
# Each result row logs the achieved onsets/bar + syncopation index + WAV path.
```

The adapter quantizes the AMT bed onto GrooveGen's 16-step grid as a `BedProfile` with `sections=None`,
so the bed is automatically **time- and knob-invariant** — the same guarantee verified for the
hand-authored study bed. The DL step is a **design-time tool**: generate offline, audit, freeze, then
sweep — never per trial. (Caveat: AMT was trained on Lakh MIDI and can memorize; screen beds against
known songs and frame use as research/non-commercial. See `DL_BED_FEASIBILITY.md`.)

---

## Using the generator directly (Python)

```python
import sys; sys.path.insert(0, "path/to/groovegen_project")
from groovegen import GrooveParams, generate, BED_PROFILES

# Render one stimulus with the "pop_loop" bed
params = GrooveParams(
    tempo_bpm=120.0,
    bars=2,
    target_seconds=24.0,
    event_density=12,        # knob: onsets per bar
    swing_amount=1.3,        # knob: swing ratio (1.0 = straight)
    syncopation_level=0.35,  # knob: 0..1
    with_bed=True,           # embed the constant musical bed
    bed_profile="pop_loop",  # which song bed (see below)
)
meta = generate(params, out_stem="outputs/audio/my_stimulus")
print(meta["wav_path"])
```

### The song beds (`BED_PROFILES`)

All share the Sophia constraints (4/4, ~120 BPM, bass-forward, harmonically
rich, slight positive/major lean) but differ in progression, instrumentation,
and feel. **`hero` is the default** — the chosen "real song" bed:

| key             | progression          | melody        | feel                            |
|-----------------|----------------------|---------------|---------------------------------|
| `hero` **(demo default)** | Am7 – D/A  | grand piano   | Dorian harmony + anthemic pushed bass + warm grand-piano melody; full Intro→Verse→Chorus song |
| `hero_study` **(study bed)** | Am7 – D/A | grand piano | same harmony/bass/timbre as `hero`, but a single **frozen verse loop** — time- & knob-invariant |
| `dorian_vamp`   | Am7 – D/A            | electric piano| cool, modern, hip-hop / r&b     |
| `pop_loop`      | C – G – Am – F       | vibraphone    | warm, uplifting, mainstream pop |
| `anthemic_lift` | Em7 – Cmaj7 – G – D  | electric piano| anthemic, cinematic             |

The `hero` bed combines the elements picked by ear: the Dorian Am7–D/A
progression, the anthemic profile's pushed/dotted bass groove, and a warm
acoustic grand-piano melody (GM program 0) instead of the electric-piano sound.

#### Song form (`hero` only)

The `hero` profile is not a flat loop — it has a **build-up song structure**
driven by melody density (bass + chords stay constant; only the melody changes):

| section | bars | melody                                   |
|---------|------|------------------------------------------|
| Intro   | 2    | none (bass + chords only)                |
| Verse   | 2    | moderately sparse (~2 notes/bar)         |
| Chorus  | 2+2  | dense, higher register — the "lift"      |

This is expressed by the `sections` + `section_motifs` fields on `BedProfile`.
`PatternBuilder.build_bed_song()` renders the full song (then it repeats to fill
`target_seconds`); profiles without `sections` fall back to the classic single
loop via `build_bed_instruments()`. The structured song remains **knob-invariant**
(verified: 120 bed events/song, identical across all drum settings).

#### Demo bed vs study bed (resolved)

The constant-bed assumption in `STAGE1_PROTOCOL.md` requires a perceptually
time-invariant bed so the swept drum knob is the only variable. **Decision: the
study uses the `hero_study` profile** — same harmony, anthemic bass, and
grand-piano timbre as `hero`, but **only the verse section as a constant 2-bar
loop** (`sections=None`, so it routes through the plain `build_bed_instruments()`
path). No intro/chorus build-up → no temporal confound. The full Intro→Verse→
Chorus `hero` song is kept for **demos / product only**.

`STUDY_BED_PROFILE` names the study bed; `build_stimulus_grid.py` uses it for
every stimulus (logged as `bed_profile = hero_study` in the manifest).
`verify_study_bed.py` confirms it is `sections=None`, identical every cycle
(time-invariant), and unchanged across all five-knob combinations (knob-invariant).

Each is a `BedProfile` (see `groovegen/groovegen.py`): a chord loop, a bass
program + groove pattern, a pad program, a melody motif, and a velocity balance.
Velocities are tuned for FluidR3 so the **bass is felt but not overpowering** and
the **melody is clearly audible** — sitting at or just above the bass, with the
pad as a soft cushion underneath, all below the drum kit.

The knobs (`event_density`, `swing_amount`, `syncopation_level`,
`microtiming_variance_ms`, `tempo_bpm`) only affect the drums. The bed is
constant per profile and verified knob-invariant in notebook `02`.

---

## The analysis (notebook `01`, scripts in `sophia/`)

Run against Sophia's 122-participant dataset. The **only** danceability variable
is Spotify `song_dance` (a song constant); there is no per-trial participant
groove rating, so all framing respects that.

- **Layer 1 — groove-proxy validation:** a theory-grounded acoustic groove proxy
  vs `song_dance` (convergent/discriminant), Witek inverted-U on syncopation,
  Janata 110–130 BPM band.
- **Layer 2 — acoustic predictors of `song_dance`:** interpretable standardized
  betas with 95% CIs and song-held-out cross-validation.
- **Trait moderator:** mixed model `song_dance ~ condition * SM_factor + (1|Participant)`.
  Result is a clean **null** — trait sensory-motor reward does not moderate the
  sensory-motor vs self-relevant danceability gap — which motivates a
  stimulus-side (not trait-gated) approach to inducing groove.

See `sophia/RESULTS_MEMO.md` and `sophia/BED_FEATURE_PROFILE.md` for the written
interpretation, and `STAGE1_PROTOCOL.md` for the full study design.

---

## Reproducibility notes

- **No absolute paths.** Everything resolves relative to the project root via
  `config.py`. Clone anywhere.
- **Deterministic.** Renders are seeded; loudness is normalized to −14 LUFS with
  a peak limiter, so relative levels are stable across machines.
- **Single source of truth.** The notebooks call the library/scripts rather than
  re-implementing logic, so notebook output can't drift from the code.
- All four notebooks were executed top-to-bottom with zero errors before shipping.

---

## Stage 2 (later)

`groovegen/bayesopt.py` implements the per-person Bayesian sweet-spot search for
the adaptive/BBCI personalization stage. Stage 1 (this repo) uses a fixed grid
first, so the main effects are cleanly preregisterable. See `STAGE1_PROTOCOL.md`.
