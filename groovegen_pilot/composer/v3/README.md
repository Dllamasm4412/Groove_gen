# v3 generator prototype (hip-hop only)

Opt-in, auditionable prototype of the v3 composition model described in
`MUSIC_GENERATION_V3_REVISED_IMPLEMENTATION_PLAN.md`. It is a development
artifact for listening tests on the developer, not a locked stimulus.

**Untouched by this package:** LadderMPC and its control law, the RLS
estimator, the plant model, the HR estimator, the controller configuration,
the locked ladder, the v1/v2/v2c generators, the runner, and existing tests.
Nothing imports v3 unless asked to: the default live path (`--generator bank`
or `v2c`) is unchanged.

## What it does

- **One composition at a time.** `create_spec` draws a CompositionSpec:
  - sub-style (boombap, soul or dark), key and mode, tempo and swing;
  - two chord loops from a per-sub-style transition grammar;
  - a two-bar hook motif and its answer, built from rhythm cells plus a
    constrained diatonic walk and fitted to the chords;
  - kick patterns, hat mask, bass and comping styles, an instrument palette,
    and a form template.

  Retired loops and hooks are never reused within a session.
- **A form, not a loop.** Each segment (8 bars) has a role in the form:
  - S1 / S: statement; V / V2: variation;
  - C / C2: contrast (second loop, the hook doubled on another instrument);
  - R / R2: return (original loop and instrument).

  Development operators (sequence, inversion, displacement, ornament,
  fragment, rhythm) are applied with an audible-difference check, escalating
  to the next operator if the realised line barely changes.
- **Levels change texture, not identity.** L1-L5 (the ladder tier) select
  layer masks and drum and melodic dynamics. Harmony, hook, groove and tempo
  stay the composition's own.
- **One shared plan.** A SegmentPlan is realised in dependency order:
  harmony, then drums, bass, hook, comping, and counter / double. Every part
  reads one swing grid. Bass locks to the kick and chord changes. The counter
  and comping stay under the hook.
- **Loudness.** A MIDI loudness predictor (`levels.py` plus
  `levels_FluidR3_GM.json`) gives each composition a mix trim, so that
  level 3 lands on the v2c hip-hop tier-3 loudness.
- **State commits on enqueue.** `peek(level)` is pure; `next_segment` commits.
  The same `stim_seed` always replays the same session.

## Files

| File | Role |
|---|---|
| `theory.py` | chords, modes, avoid-note rule, voicing, the swing `Grid` |
| `state.py` | CompositionSpec, CompositionState, SegmentPlan |
| `hiphop.py` | sub-style tables, composition creation, development, planning, realisation, calibration |
| `levels.py`, `levels_FluidR3_GM.json` | MIDI loudness predictor and its measured table |
| `checks.py` | rule checks (`rule_violations`) and transposition-invariant identity |
| `source.py` | `HipHopV3Source` (hip-hop only) and `V3SegmentSource` (drop-in for `SessionSegmentSource`: hip-hop from v3, other genres from v2c) |
| `../../audition_v3.py` | renders, measures and packages the audition samples (Tests A-D) |
| `../../tests/test_v3_hiphop.py` | 29 tests |
| `NEXT_ITERATION.md` | Musyng Kite re-render steps, upper-level energy, listening agenda, interface risks |

## Running

From `groovegen_pilot/`:

```
python -m pytest tests/test_v3_hiphop.py -q
python audition_v3.py --sf2 /path/to/FluidR3_GM.sf2 --zip groovegen_v3_audition.zip
python audition_v3.py --sf2 /path/to/other.sf2 --measure-levels   # new soundfont: measure its loudness table first
python audition_v3.py --sf2 /path/to/other.sf2 --out ../groovegen_v3_audition_other
```

v3 calibrates with `levels_<sf2 stem>.json`. The audition stops when that
table is missing, unless `--levels <name>` names another one on purpose. The
audition output (`groovegen_v3_audition*/`, `*.zip`) is gitignored. For the
Mac with Musyng Kite, follow `NEXT_ITERATION.md` section 1.

To use v3 inside the runner, pass `V3SegmentSource(stim_seed)` where
`run_session_v2` takes a SessionSegmentSource. The runner is not changed and
has no CLI flag for v3; `test_runs_inside_the_unmodified_session_runner`
shows the call.

## Known limits

- **Tempo policy.** `run_session_v2` asserts that each segment's tempo is the
  GENRE_CFG tier tempo. `V3SegmentSource` therefore defaults to
  `tempo_policy='tier'`. The musically preferred `'composition'` policy (one
  tempo per piece, used in the audition) needs an opt-in runner change that
  this prototype does not make.
- **Soundfont.** Renders and the loudness table use FluidR3_GM, because the
  live soundfont (Musyng Kite) was not available in the build environment.
  Re-run `--measure-levels` on the live soundfont before any comparison.
- **Measured energy.** From L3 to L5, v3 rises about as much as v2c. It sits
  lower because it is darker (spectral centroid about 2.8 kHz against
  4.9 kHz) and, at composition tempo, misses the tempo-driven gains. See
  `NEXT_ITERATION.md` section 2. The live ladder's energy table does not
  include v3.
- **Calibration in the source.** `HipHopV3Source` loads the FluidR3 table by
  default, and a missing table name plays uncalibrated. See
  `NEXT_ITERATION.md` section 4.
- **Size.** `hiphop.py` is about 1050 lines, over the plan's 900-line budget.
- **Evidence.** Rule checks and audio measurements show that the parts agree
  with the plan. They are not evidence of musical quality, which needs
  listening.
