# Controlled variation for live generation: revised plan

Status: planning document, revision 2 (2026-09-29). No code changed.
Revision 1 (2026-09-28) covered overall feasibility. This revision narrows the
goal to **controlled variation**: remove obvious looping and repetition while
every genre/tier cell keeps the musical characteristics the study depends on.
Numbers marked *measured* come from throwaway probes on the current tree.
Numbers marked *provisional* are proposals to be fixed from the Phase 1 audit.

---

## 1. Goal and starting point

**Goal.** Inside the cell the controller selects, produce music that doesn't
loop audibly and doesn't repeat across visits, while tempo, instrumentation,
rhythmic feel, drum density, loudness and register stay within the cell's
measured envelope. Novelty for its own sake is not a goal. Variation is
allowed only where it can't move the cell's energy.

**What the current generator does** (the facts the design builds on):

| Fact | Where | Consequence |
|---|---|---|
| The live runner already composes per segment. `MelodyBank` limits each cell to 4 seeds. | `run_session_v2.py` step 3-4, `melody_bank.py` `seed_for` | The live repertoire is 27 cells x 4 = 108 fixed segments. |
| Each generator picks **one** drum variant per segment from its own RNG and writes it for all 8 bars. | `composer.py` `_gen_pop` (`_POP_DRUM_VARIANTS[rng.randint(...)]` then `_apply_pop_drums`), same pattern in `_gen_rnb`, `_gen_latin`; `_gen_lofi` wraps `_gen_rnb` | Drums repeat bar for bar. *Measured:* 1 distinct drum bar in 8 for calm, lofi, rnb, pop, hiphop and rock; 2 for latin. |
| No fills exist anywhere except a crash on bar 1 in rock at higher tiers. | `rock_cell.py` `rock_drum_pattern` (`_TIER_CRASH_ON`) | Phrase ends aren't marked, so 8 bars read as one loop. |
| hiphop and rock draw their key from 5 options with the segment seed (first `rng.choice` in `_resolve_spec`). calm, lofi, rnb, pop and latin have fixed keys. | `hiphop_cell.py` `_resolve_spec` (`["A","C","G","F","D"]`), `rock_cell.py` `_resolve_spec` (`["C","D","E","G","A"]`) | Consecutive same-cell segments can jump key. *Measured:* first bass notes B, A, F#, E across hiphop3 variants 0-3. |
| hiphop and rock are a 2-bar ostinato repeated by design. | `hiphop_cell.py` (2-bar phrase comment near line 362), `rock_cell.py` | *Measured:* 3 distinct bars in 8. The loop is idiomatic, so vary the phrase ends, not the body. |
| Segments are independent: each one re-draws progression, bass pattern, voicing and motif. | `_gen_*` all start from `random.Random(seed)` | There is no development and no recall; every segment is a "new song" in the same style. |
| Cell energy was measured on bank seeds only. | `music_features_measured.py` (`cell_plan`, `measure_one`, `energy_sd`), `energy_table_v1.json` (`tie_band_e = 0.0457`, per-cell `energy_sd`) | Any new content must be shown to fall inside that measured distribution. |

`symbolic_bed_proto.py`, which is open in the editor, is not in the live
path. It is imported only by legacy scripts (`symbolic_tiers_demo.py`,
`ab_render_pop.py`). The live chord, bass and drum rules are in `composer.py`,
`composer/*_cell.py`, `composer/patterns.py` and `composer/voicings.py`. This
plan adds no chord or harmony logic, so the "no new harmony.py" rule isn't
touched.

---

## 2. Definition: what "non-repetitive" means here

All metrics are computed on MIDI, so they are fast, deterministic and don't
depend on the renderer. An **onset** is `(pitch, position on a 48-per-bar
grid)` within a bar. Velocity is excluded, so accent-only changes don't count
as variation. **Drum layer** means drum notes; **pitched layer** means all
non-drum notes. The **motif track** is the melodic line per genre:

| genre | motif track (instrument name in the generated MIDI) |
|---|---|
| calm | `piano` |
| lofi, rnb | `keys` |
| pop | `lead` |
| latin | `nylon` |
| hiphop | `Sampler` (ostinato) |
| rock | `Electric G` |

| # | Metric | Definition | Baseline | Target (provisional) |
|---|---|---|---|---|
| R1 | Distinct drum bars per segment | Number of unique drum-bar onset sets among the 8 bars | *measured* 1 (6 cells), 2 (latin) | >= 3 for calm, lofi, rnb, pop, latin; >= 2 for hiphop and rock |
| R2 | Longest identical drum run | Longest run of consecutive bars with identical drum onset sets | 8 (inferred from R1 = 1) | <= 3 |
| R3 | Exact repeat distance | Within a session, the minimum number of segments between two segments with identical full-MIDI sha256. Also reported per layer (drum sha, pitched sha). | 4 same-cell visits (rotation period) | Full segment: no repeat within a 15-min session. Drum layer: no repeat within 4 visits of the cell. |
| R4 | Near-repeat similarity | For segments a and b of the same cell, `S(a,b)` = mean over bars of b of the maximum Jaccard similarity to any bar of a (shift-tolerant, so it catches a loop that reappears elsewhere). Reported per layer. | From the audit | Next visit in the same block: drums 0.6-0.9 (groove kept, not identical), pitched <= 0.85. New block: pitched <= 0.5. |
| R5 | Motif reuse vs variation | Motif signature = first 2 bars of the motif track as (interval sequence, onset grid), transposition-invariant. `d` = normalized edit distance between two segments' signatures. Reuse: `d <= 0.3`. Exact reuse: `d = 0`. | From the audit (expected: reuse only by chance) | Same block: reuse rate >= 0.8, exact reuse = 0. Different blocks: reuse rate <= 0.2. |
| R6 | Phrase-level variation | Phrase = bars 1-4 and 5-8. (a) Phrase-end marking: bar 4 or 8 drum onsets differ from both of the two bars before it (lags 1 and 2, so a 2-bar clave or a bar-1 crash is not a fill). The audit also reports `drum_period` (smallest repeat period in {1, 2, 4}, else 8). (b) Phrase contrast: the phrase 1 and phrase 2 signatures differ. | (a) 0 (no fills). (b) From the audit. | (a) Bar 8 marked in 100% of segments, bar 4 in >= 50%. (b) >= 90% of segments. |
| R7 | Tonal continuity | Tonal collection = the major-scale transposition that best fits the segment's pitched pitch-class histogram (relative major and minor count as the same collection). Count collection changes between consecutive segments of the same genre. | ~0 for fixed-key genres, frequent for hiphop and rock (the audit confirms) | 0 changes within a same-genre run |

R1-R2 and R6 address looping within a segment. R3-R5 address repetition
across visits. R7 is a continuity constraint, which balances the other
metrics. The targets set a **band** rather than a maximum: variation has to
stay low enough that the cell remains recognizably itself.

---

## 3. Definition: what must stay controlled

### 3.1 Locked (identical to the base generator, checked exactly)

| Feature | Source of truth | Check |
|---|---|---|
| Tempo (planned = played) | `GENRE_CFG[g]['tier_tempo'][tier]` or `tempo_default`, as `run_session_v2` computes it | `pm.get_tempo_changes()` has one tempo, equal to the planned tempo |
| Meter, bars per segment | 4/4, `SessionConfigV2.bars_per_segment = 8` | Segment length = 8 bars |
| Instrument set (GM programs and track count) | Base generator output. *Measured:* calm {0 piano, 89 pad}; lofi and rnb {0, 4, 33}; pop {4, 25, 33}; latin {0, 24, 33}; hiphop {0, 0, 33}; rock {26, 33} | Variant program multiset = base program multiset |
| Drum voice set (bounded set, not locked; see note below) | Per-cell allowed set = union over the v1 bank variants (`audit_summary.json` `cells[*].bounded_set.drum_voices.union`), plus the genre's fill voices (section 4.4) | Variant voices are a subset of the allowed set (`stimulus_audit.py --reference-summary <v1 audit>`) |
| Genre skeleton notes | Section 4.3 table (for example latin clave 75 and kick on beats 1 and 3; rnb snare on 2 and 4; pop and rock backbeat) | Protected notes present, unmoved, same velocity |
| Tier and density | `TIER_TO_DENSITY` after `RUNG_TIER_CAP` and `LIVE_TIER_CAP_OVERRIDES` | Base generated with exactly this density |
| Feel | Straight or swung as the base generates; no swing or quantize changes | Onset grid positions come only from the op catalog |
| Key within a genre | Fixed key (calm, lofi, rnb, pop, latin); session key (hiphop, rock, section 4.6) | R7 = 0 |
| Render chain | FluidSynth CLI, `Musyng_Kite.sf2`, fixed gain 0.8, same trim and crossfade | Unchanged code path |

*Note (baseline audit, 2026-09-29):* the drum voice set is not constant
within a cell in v1. `_gen_pop`, `_gen_rnb` and `_gen_latin` pick a drum
variant per seed, and the variants use different voices (for example ride 51
vs hats 42/44/46, clap 39 vs snare 38, conga 63 vs cowbell 56 / timbale 65).
The variants differ in lofi1-3, rnb1-4, pop1-5, latin3 and latin5. It is
therefore a bounded-set feature (`BOUNDED_SET_FEATURES` in
`stimulus_metrics.py`): v2 may use any voice v1 already plays in that cell,
and nothing outside that set except the listed fill voices.
| No vocals | GM 52-54, 85, 91 banned | Program check |

### 3.2 Bounded (may move, within a tolerance of the base segment and inside the cell envelope)

| Feature | Measure (reuse existing code) | Per-segment bound (provisional) |
|---|---|---|
| Drum onset rate | `music_features_measured.midi_features` -> `drum_rate` (20 ms merge) | Within +-4% of the base segment and inside the cell envelope |
| Per-role drum rates (low, backbeat, hats, hand) | `midi_features` -> `drum_*_rate` (`DRUM_ROLES`) | Within +-8% of base per role |
| On-beat/off-beat drum ratio | New, in `stimulus_metrics` (the constraint v1.4 used) | Within +-0.05 of base |
| All-note onset rate | `midi_features` -> `note_rate` | Within +-5% of base |
| Velocity per instrument | New: mean and 90th percentile | Mean change within +-2, 90th percentile change <= +3 |
| Register per instrument | New: median pitch and pitch range | Median within +-2 semitones; range inside the base range +-2 |
| LUFS, centroid, flux, low_ratio, pulse_clarity (audio) | `music_features_measured.audio_features` | Inside the cell's audio envelope (section 6.3) |
| Per-segment energy E | `energy_sd`'s z parameters applied to one render | Inside the cell's E envelope |

### 3.3 Freely variable (the only places variation is created)

- Drum micro-variation within a bar, using count-neutral ops from the catalog
  (section 4.3).
- Phrase-end fills at bars 4 and 8, which replace notes rather than add them.
- Which of the genre's existing progressions, bass patterns, voicing octaves,
  arpeggio directions and stab patterns the base seed picks. These are the
  listed options in `composer.py` (`_POP_PROGRESSIONS_C`,
  `_POP_BASS_PATTERNS`, `_POP_STAB_PATTERNS`, `_RNB_PROGRESSIONS_Dm`,
  `_RNB_BASS_PATTERNS`, `_LATIN_PROGRESSIONS_Cm`, calm `arp_direction`, and
  so on). They stay subject to the bounded checks, because the bass patterns
  differ in note count.
- Motif transformations on the motif track: rhythmic displacement by an
  eighth, neighbor-tone ornament with a matched note count, contour
  inversion snapped to chord tones. This is Phase 2c (section 4.5).
- Phrase endings of pitched parts: hold vs. restate on bar 8 with the same
  note count.

---

## 4. Variation layer design

### 4.1 Architecture: base + variation, two independent seeds

```
cell (genre, tier)  +  visit_idx  +  stim_seed        <- the only inputs
        |
        v
arrangement.schedule(...)  -> base_seed, var_seed, block_idx, pos_in_block
        |
        v
composer.generate_segment(genre, tempo, density, 8, seed=base_seed)   UNCHANGED
        |   (PrettyMIDI "base": exactly what the bank generator would produce for base_seed)
        v
variation.apply(base, VariationPlan(var_seed, genre, tier, pos_in_block))
        |   post-generation transforms on PrettyMIDI with their own RNG
        v
energy_guard.check(varied, base, envelope[cell])  -> ok, or next var sub-seed, then fallback
        v
PrettyMIDI -> existing SymbolicSegmentRenderer CLI path -> mixer -> player
```

Why this approach:
- **`composer.py` and the frozen cells don't change at all** in Phase 2a.
  The base generator's RNG stream is never touched, so the bit-identity
  regression is automatic.
- The same variation code covers all 7 genres, including frozen hiphop and
  rock, because it works on their PrettyMIDI output after `_score_to_pm`.
  There is no music21 round trip.
- Every variation is an explicit, logged op with a declared onset change, so
  the energy effect can be checked op by op.

### 4.2 Deterministic open seed schedule with motif memory (`composer/arrangement.py`)

```
visit_idx   = segments already played in this cell this session (0, 1, 2, ...)
block_idx   = visit_idx // L                  L = 3 (provisional), the same for every cell
pos_in_block= visit_idx %  L
base_seed   = H("base", stim_seed, genre, tier, block_idx, gen_version)
var_seed    = H("var",  stim_seed, genre, tier, visit_idx, gen_version)
H           = int.from_bytes(blake2b(repr(args).encode(), digest_size=4).digest(), "big")
```

- **Motif memory = block reuse.** The L visits in a block share `base_seed`,
  so they share progression, bass pattern, voicing and motif. They differ in
  `var_seed`: drum micro-variation, fills and (in Phase 2c) motif
  transformations. Consecutive visits sound like A, A', A'', then B. If the
  controller leaves the cell and comes back, the next visit continues the
  same block, which recalls earlier material rather than starting over.
- **Open:** block `k` always gets a new base seed, so there is no 4-segment
  rotation.
- **Participant-matched:** content depends only on (cell, `visit_idx`,
  `stim_seed`), so the k-th visit to pop3 is identical for every
  participant, as it is today.
- **Enumerable:** for a session capped at `max_segments` (`run_pilot_zero`
  computes 75 for a 15-min phase schedule), the full set of segments a
  participant could hear is 27 cells x 75 visits. It can be pre-certified
  (section 6.4).
- `L` is the same for every cell, so the amount of novelty doesn't depend
  on the cell (section 5).

### 4.3 Per-bar drum variation (`composer/variation.py`)

**Form template per 8-bar segment**, shared by all genres, chosen by
`var_seed` from a small list:

```
bars:   1  2  3  4  | 5  6  7  8
T1:     A  A  A' Fs | A  A  A' F
T2:     A  A' A  A  | A  A' A  F
T3:     A  A  A  Fs | A  A' A  F
A  = base bar (unchanged)
A' = base bar + 1-2 micro-ops
Fs = short fill (last beat)
F  = phrase-end fill (last 1-2 beats)
```

Every template gives R1 >= 3, R2 <= 3, and R6(a) at bar 8 by construction.

**Micro-op catalog.** Every op is count-neutral or declares its onset change,
and never touches protected notes:

| Op | Effect | Onset change | Genres |
|---|---|---|---|
| `hat_open_swap` | One closed-hat (42) note becomes an open hat (46) | 0 | Genres that already use 46 (lofi, rnb, hiphop) |
| `kick_anticipate` | Move a non-skeleton kick one 16th earlier | 0 | pop, rnb, lofi, hiphop (tier >= 3 already has a 16th pickup), rock |
| `ghost_shift` | Move one ghost snare (low velocity 38) to a neighboring 16th | 0 | rnb, lofi |
| `hat_skip_add` | Drop one hat and add one at another position in the same bar | 0 | All genres with hats |
| `conga_articulation` | Swap one open or muted conga note (63 <-> 64) or bongo 60 | 0 | latin |
| `accent_rotate` | Rotate the hat accent pattern; mean velocity change = 0 | 0 (not counted in R1) | All |

**Protected skeleton** (read from the base, never modified):

| genre | protected drum notes |
|---|---|
| calm | all kick 36 and rim 37 |
| lofi, rnb | snare 38 on beats 2 and 4; kick on beat 1 |
| pop | clap/snare 39/38 on beats 2 and 4; kick on beat 1 |
| latin | all clave 75; kick 36 on beats 1 and 3 |
| hiphop | kick slots 0 and 10; snare slots 4 and 12 (from `hiphop_drum_pattern`) |
| rock | kick on beats 1 and 3; snare on beats 2 and 4; crash 49 on bar 1 |

### 4.4 Phrase-end fills

Fills are **replacements**. A fill clears the non-protected drum notes in its
window (bar 4 or 8, last 1-2 beats) and writes a fill pattern with the same
onset count, +-1. Fill voices are limited to voices the genre already uses,
plus toms (45, 47, 48, 50) for pop, rock and hiphop only:

| genre | fill vocabulary |
|---|---|
| calm | rim 37 pickup (1-2 notes); bar 8 only |
| lofi, rnb | snare ghost roll (38, low velocity) and open-hat lift (46) |
| pop | snare 16ths, or clap 39 + tom run |
| latin | timbale 65 cascade (cascara-style) or conga 63/64 run; clave untouched |
| hiphop | snare/kick 16th stutter (38/36); 16th hats are already present at tier 3+ |
| rock | tom run 50/48/47/45 or snare 16ths; crash 49 on the next bar 1 is already in the base at crash tiers |

Toms add 4 new voices to pop, hiphop and rock. They count as bounded (hand
and "other" role drum rate). If the audit shows a timbre (centroid/flux)
shift, pop and hiphop fall back to snare-only fills.

### 4.5 Motif memory and motif variation

- **Phase 2a (no pitch changes):** block reuse (section 4.2) provides motif
  memory. R5 reuse comes from the shared base seed, and exact reuse is
  broken by the drum layer and fills. Pitched parts are unchanged from base.
- **Phase 2c (optional, after 2b certification):** motif-track ops in
  `variation.py`, only for `pos_in_block >= 1`:
  - `displace_eighth`: shift one bar of the motif by an eighth (count 0).
  - `neighbor_ornament`: replace one long note with a neighbor-tone pair and
    remove one note elsewhere (count 0).
  - `bar8_cadence`: end the motif on the chord root instead of restating it.
  Chord tones per bar are inferred from the base's comping track
  pitch-class set; no harmony module is needed. Pitch checks: every
  transformed pitch belongs to the tonal collection, and register stays
  within the section 3.2 bound.

### 4.6 Session key lock (hiphop, rock) without editing frozen cells

Don't transpose, because transposition moves register and centroid. Instead,
**filter base seeds**:

```
session_key[g] = choice(key list of g, seeded by H("key", stim_seed, g))
base_seed(block k) = first H("base", stim_seed, g, tier, k, j) for j = 0, 1, ...
                     whose cell key == session_key[g]
```

The cell's key is the first `rng.choice` on `random.Random(seed)` inside
`_resolve_spec`, so `variation.cell_key(genre, seed)` can call the cell's
`_resolve_spec` read-only (or read the generated score's metadata). A test
pins `cell_key` against real generated output so any future cell change
fails loudly. The expected number of draws is 5, and computing the key alone
costs microseconds. Every hiphop and rock tier then shares one key per
session, and each segment is still an unmodified output of the frozen cell.

### 4.7 Cross-segment continuity

| Continuity | Mechanism | Metric |
|---|---|---|
| Key within a genre | Fixed-key genres already; session key lock for hiphop and rock | R7 |
| Harmony and motif within a block | Shared `base_seed` | R4, R5 |
| Groove family within a block | Base drum variant comes from `base_seed`, so it is the same across the block | R4 drums in 0.6-0.9 |
| Loudness at boundaries | Bounded velocity + audio envelope | Boundary check (section 6.3, A4) |
| Cross-genre moves | Not smoothed. Genre change is the control action, and its key and timbre change is part of the cell. | Out of scope; logged |

### 4.8 Energy guard and fallback (`composer/energy_guard.py`)

For each candidate:
1. Locked checks (section 3.1) must pass exactly.
2. Bounded MIDI checks (section 3.2) must pass against both the base segment
   and the cell envelope.
3. On failure, retry with sub-seed `H(var_seed, attempt)`, up to 4 attempts.
4. If all attempts fail, use the base segment (`fallback=True`). It is
   always valid, because it is a bank-generator output.

The retries are deterministic, so they are reproducible and appear in the
manifest.

### 4.9 Phase 2a as implemented (2026-09-29): deviations from 4.3-4.8

Implemented in `composer/arrangement.py`, `composer/variation.py` and
`composer/energy_guard.py`; not wired into the runner. `composer.py` and
the frozen cells are unchanged (`test_composer_identity.py` still passes).
Where the code differs from sections 4.3-4.8:

- **Protected notes come from the base segment, not the 4.3 table.** The
  rule: every clave 75 and crash 49; kick and snare/clap/rim on quarter-note
  beats; all of calm's 36/37; hiphop's slot-10 kick. The table was wrong
  for pop (its snare is on beat 3, not beats 2 and 4).
- **Micro-op catalog**:
  - `hat_shift`, `kick_shift` and `ghost_shift` move one non-protected note
    by one 16th;
  - `hat_swap` (42/46) and `hand_swap` (63/64) run only if the base already
    plays both voices;
  - `revoice` is the last resort for bars where nothing else fits: it
    re-voices one hat or hand note in place, before slot 8.
  - `accent_rotate` and `hat_skip_add` are not implemented.
  - Every op is count-neutral and velocity-multiset-neutral.
- **Move budget.** A 16th move can merge or split onsets and change the
  on-beat share. Each candidate move is therefore evaluated with the
  guard's own feature code and kept only if every section 3.2 MIDI bound
  stays within 80% of its tolerance.
  - Without the budget, the first smoke run fell back on 8.6% of segments:
    all of calm1-2, where one hat shift moves the on-beat share by 0.06.
  - With it, fallback is 0%.
  - The +-0.05 on-beat bound is kept. The bank's within-cell spread gives no
    grounds to widen it: calm, hiphop, rock and latin have SD 0 across 24
    seeds.
- **Fills re-voice in place.** They keep the positions, count and velocity
  multiset, with velocities re-ordered into a crescendo. A fill uses only
  voices the base already plays.
  - No toms in 2a (section 4.4 toms are deferred until the Tier A timbre
    check).
  - A fill counts only notes whose pitch actually changes. An empty fill
    window gets micro-ops instead.
- **Per-role drum rates are reported, not gated.** Fills re-voice hats as
  snare or conga by design, and the energy table does not use role rates.
  Their effect is judged on audio (Tier A).
- **Guard.** It checks the following against the base segment:
  - locked features identical;
  - drum voices a subset of the base's voices;
  - pitched tracks identical;
  - protected notes present;
  - drum note count equal;
  - section 3.2 MIDI bounds.

  It also rejects a variation that exactly repeats an earlier visit in its
  block. Earlier visits are recomputed from the schedule, so the result
  stays path-independent. The cell-envelope check is left to certification
  (Phase 3).
- **Reference sets.** Against the v1 bank audit's per-cell drum-voice sets,
  7 cells show "outside reference" voices (for example pop:3 +46,
  rnb:3 +44/51).
  - The cause is the new base seeds, not the variation: pop3 over 40
    arbitrary seeds uses 36, 38, 39, 42 and 46.
  - The v1 reference covers only 4 seeds per cell. Certification should
    build the voice envelope from many seeds.

Evidence (stim_seed 1, `stimulus_audit.py --generator session`, 345
segments):
- 0 fallbacks;
- locked features stable in every cell;
- R1 >= 3 distinct drum bars in every segment;
- R2 max run 3;
- bar 8 marked in 100% of segments;
- 0 exact repeats within a cell.

---

## 5. Keeping the study valid

**Information boundary.** The generator's whole input is `(genre, tier,
visit_idx, stim_seed, gen_version)`. Tempo and density are derived inside
from the cell, exactly as today. It does not receive HR, HR history, target,
baseline, controller state, arousal ratings, haptic state or participant ID.
The controller (`LadderMPC.step`/`hold`) keeps sole authority over
rung, genre and tier. The generator only adds variation inside the chosen
cell.

Enforced in code, not only by convention:
- `SessionComposer.compose(genre: str, tier: int, visit_idx: int)` is the
  only public entry point. `stim_seed` is fixed at construction. There is no
  `**kwargs`.
- `test_generator_boundary.py`:
  - (a) signature check;
  - (b) import-graph check: `composer/arrangement.py`, `composer/variation.py`
    and `composer/energy_guard.py` import none of `hr_sources`,
    `serial_ppg_source`, `estimator_hr_source`, `control`,
    `user_descriptor`, `composer_personalization`;
  - (c) path-invariance: run `run_session_v2` headless with two different
    `ReplaySource` HR traces. Every segment keyed by (cell, `visit_idx`) must
    have the same MIDI sha in both runs.

**What HR can still affect.** HR affects which cells are visited and how
often, and therefore which `visit_idx` values are reached. That is the
control action, and it is the same indirect path the 4-seed rotation has
today. It is documented, not removed.

**Novelty can't be a hidden second actuator.**
- `L`, the form templates and the fill rate are the same for every cell.
- Acceptance check: across cells, Spearman correlation between cell `u` and
  mean R4 similarity has |rho| < 0.3. Otherwise novelty co-varies with energy
  and would confound the ladder.

**Participant matching and yoking.**
- `stim_seed` is a protocol constant; it can be counterbalanced across a
  small fixed set if the protocol says so.
- A yoked or replay condition replays the same (cell, `visit_idx`)
  sequence, and so gets exactly the same MIDI.

**Framing.** Methods text: "within-cell variation is generated by a fixed,
energy-certified rule set; the controller's action is the cell." No claim
that the music responds to the participant beyond cell selection. Keep the
"tracks the arousal reference" wording.

---

## 6. Validation plan

### 6.1 Tier M (MIDI-side, seconds, runs on every change)

| Check | How |
|---|---|
| M1 bit-identity | `tests/test_composer_identity.py` against `tests/fixtures/composer_identity_v1.json`: 35 cells x bank variants 0-3 through the live seed chain, plus 35 cells x 4 fixed seeds. Base path untouched. |
| M2 locked features | For every candidate: tempo, program multiset, skeleton notes, 8-bar length; drum voices a subset of the cell's allowed set (plus fill voices) |
| M3 bounded features | Section 3.2 MIDI bounds against the base segment and the cell's MIDI envelope |
| M4 repetition metrics | R1-R7 over synthetic trajectories (section 7) meet the section 2 targets |
| M5 determinism | Same inputs give the same sha, in one process and across two processes |
| M6 boundary | `test_generator_boundary.py` (section 5) |

### 6.2 Cell envelopes (built once from the bank generator, Phase 1)

Render bank seeds for variants 0-31 per live cell with
`MelodyBank._seed_for_variant` (the existing live and measured variants 0-7
plus 24 more of the same generator). For each feature f in sections 3.2 and
`ENERGY_WEIGHTS`:

`envelope[c][f] = [min - 0.25 SD, max + 0.25 SD]` over the 32 bank renders.

Also store the mean and SD. Written to `stim_envelope_bank_v1.json` with the
code sha and soundfont sha.

### 6.3 Tier A (rendered audio, minutes, required before study use)

Render through the unchanged CLI path using `music_features_measured`'s
`measure_one` recipe (render, trim to 8 bars + fade, then `audio_features`).

| Check | Criterion (provisional) |
|---|---|
| A1 per segment | LUFS, centroid, flux, low_ratio, pulse_clarity and per-segment E inside `envelope[c]` |
| A2 per cell mean | LUFS mean shift <= 0.5 LU; E mean shift <= `tie_band_e`/2 (~0.023); each feature's mean shift <= 0.5 bank SD |
| A3 per cell spread | Within-cell SD of E <= 1.25 x bank SD (`energy_sd`) |
| A4 boundary loudness | Short-term loudness (3 s windows) across consecutive same-cell segment joins within 1.5 LU (compared against the bank baseline) |
| A5 ladder | `build_ladder` on the variation table gives the same rung order as `energy_table_v1.json`, allowing swaps only inside existing tie groups |
| A6 novelty/energy independence | Spearman |rho|(u, mean R4) < 0.3 |

### 6.4 Pre-certification manifest (the "prove it first" step)

The schedule is enumerable (section 4.2), so every segment a participant
could hear is generated, rendered and checked **before** a session:

```
certify_stimuli.py --stim-seed S --max-visits 75 --sf2 ... --out stim_manifests/
  -> stim_manifest_S_<gen_version>.json:
     {cell, visit_idx} -> base_seed, var_seed, attempts, fallback, plan_id,
                          midi_sha256, MIDI features, audio features, E, pass
     + envelope sha, code sha, soundfont sha, summary of A1-A6
```

This covers 27 cells x 75 visits = 2025 renders. At ~0.7 s each across 8
processes, that is about 3 min. At runtime, `SessionComposer` regenerates
each segment live (~30 ms) and checks its sha against the manifest:
- if the sha matches and the entry passed, it plays;
- if the sha mismatches or the entry is missing, it plays the base segment,
  logs `gen_fallback`, and warns.

The runner refuses `--generator session` without a manifest whose
`gen_version` and envelope sha match. Manifests are small JSON with no audio
or participant data. I recommend versioning them (your call).

### 6.5 Tier S (session-level, no participant)

1. Headless `run_session_v2` with `ReplaySource` on
   `hr_trace_ramp_60_110_90.csv`, `NullPlayer` and an injected clock
   (`test_run_session.py` pattern). Checks: plan invariance
   `df.groupby('segment_idx')[plan_cols].nunique().max() == 1`, 100%
   manifest sha hits, and R1-R7 on the actual session.
2. Real-clock 15-min headless run: `render_ms` distribution, minimum
   `deadline_slack_s` >= 1.0 s, 0 underruns.
3. `replay_session.py`: 100% MIDI sha match.
4. Regression gates: `hr_trajectory.py`, `test_faults_fixed.py`,
   `pd_controller.py`, `tier_mapping.py`, `scene.py`,
   `test_segment_renderer.py`, `test_crossfade_integration.py`.

### 6.6 Tier L (developer listening, engineering only)

Blind A/B per cell, developer only: bank segment vs. varied segment from the
same cell, in random order. Two questions: "same condition?" and "does it
loop?". This is a sanity check with n = 1. It is not evidence and can't
override A1-A6.

### 6.7 Phase 2b certification (`certify_stimuli.py`, 2026-09-30)

What it does: for each live cell, generates four sources and checks the
v2 session generator against the v1 bank generator. It changes nothing in
the live path and writes only to `renders/certification/<stamp>/`
(`certification.csv`, `certification_summary.json`, `cell_summary.csv`;
no audio or MIDI kept).

| Source | What | Used for |
|---|---|---|
| `v1_live` | Bank rotation, `MelodyBank(4, 0)`, 12 visits | Repetition baseline; the old 4-seed voice set |
| `v1_wide` | Same composer, bank variants 0-127 (MIDI), 0-31 rendered | Cell envelopes and the allowed drum-voice set |
| `v2_base` | The base segment of each v2 block | Attributing a miss to the variation or to the base seed |
| `v2_session` | `SessionComposer`, stim seeds 1 and 2, 12 visits | Under test |

Certified at MIDI level (every run):
- **Locked:** tempo, tempo-map length, bar count and GM programs equal the
  `v1_wide` value.
- **Drum voices,** classified three ways: in the 4-seed set; outside it but
  in the wide same-cell set; outside both (truly unexpected).
- **Envelope:** each section 3.2 MIDI feature inside `[min - 0.25 SD,
  max + 0.25 SD]` of `v1_wide`. The pad is at least the guard tolerance,
  because v1 does not vary `drum_onbeat_ratio` in calm, hiphop, rock and
  latin (SD 0).
- **Cell mean shift, split in two:**
  - the variation part (v2 minus its own base), limited to max(0.5 SD,
    half the guard tolerance);
  - the base-seed part (the rest), flagged only beyond both that limit and
    2 standard errors of the block count.
- **Repetition:** R1, R2, R3 (full and drum layer), R4 and R6, v1 against
  v2, with an improved / unchanged / worse status per metric.
- **Key continuity:** hiphop and rock keys come from the frozen cell's own
  `_resolve_spec`.
- **Fallback rate.**
- **A6:** Spearman rho of ladder u against v2 R4.

Certified at rendered-audio level (`--audio`; the `measure_one` recipe:
FluidSynth CLI, trim to 8 bars plus fade):
- rendered duration (locked);
- **A1:** LUFS, centroid, flux, low_ratio, pulse_clarity and per-segment E
  inside the `v1_wide` envelope;
- **A2:** mean shifts (LUFS 0.5 LU, E `tie_band_e`/2, others 0.5 SD), split
  into variation and base-seed parts;
- **A3:** E spread;
- per-segment |LUFS - base|;
- RMS dBFS and render time, reported only.
- A fidelity check reproduces `energy_table_v1.json` from `v1_wide`
  variants 0-7.

**Run 2026-09-30** (`certify_stimuli.py --audio`, 27 cells, 4644 rows,
1710 renders; MIDI 80 s, audio 676 s with 6 workers):
- **Fidelity:** energy table reproduced exactly (max diff 0 for LUFS,
  drum_rate, centroid and flux; tempo 1.3e-4). `v1_live` is a subset of
  `v1_wide`.
- **Repetition improved in 27 of 27 cells:**
  - mean R1 1.19 to 4.46 distinct drum bars;
  - R2 max 8 to 3;
  - exact-repeat rate 0.73-0.91 to at most 0.046;
  - bar 8 marked 0% to 100%.
  - Targets were met in 24 cells. The misses:
    - calm:1 had one drum-layer repeat 3 visits apart, across a block
      boundary;
    - hiphop:1 marked bar 4 in 46% (target 50%);
    - hiphop:5 had one full repeat 8 visits apart: two different base
      seeds gave the same segment.
  - R4 drum similarity is 0.76-0.96, above the 0.6-0.9 band in most
    cells.
- **Locked features:** 100% of v2 segments pass, including rendered
  duration. No fallbacks. Keys: 0 changes in v2 for both stim seeds,
  against 46 (hiphop) and 47 (rock) in v1.
- **Drum voices:** v2 uses no voice outside the wide reference (0 truly
  unexpected). The earlier "outside reference" voices are all in the wide
  same-cell set: lofi:3 +44, rnb:1 +44, rnb:3 +44/51, latin:3 +60,
  pop:2/4 +38, pop:3/5 +46. The 4-seed reference was too narrow.
- **MIDI envelope:** 0 misses caused by the variation, 9 caused by base
  seeds.
  - The variation mean shift is over its limit for `drum_onbeat_ratio` in
    calm:1, calm:2 and hiphop:1 (-0.031 against 0.025, which is half the
    guard tolerance; each segment stays within the guard). It is also over
    for `note_rate` in rock:1 and rock:2 (about +0.098 against 0.092-0.096).
- **Audio: loudness is preserved, but brightness and pulse clarity are
  lowered.**
  - LUFS vs own base: at most 0.07 LU.
  - E variation shift: over `tie_band_e`/2 only in hiphop:3 (-0.030) and
    hiphop:4 (-0.023).
  - Centroid drops in every genre: hiphop mean -228 Hz (up to -440), rock
    -133, latin -120, rnb -95, lofi -54, pop -50, calm -26.
  - Pulse clarity drops by 0.005-0.03.
  - The cause is the fills. Centroid falls by 11-34 Hz per hat re-voiced
    as snare 38 or kick 36, or as conga in latin. hiphop averages 7.2
    re-voiced notes per segment.
  - A3 fails for latin:2 (1.26) and rock:5 (1.36).
- **A6** rho = 0.10, pass.
- **Verdict:** only pop:1-5 pass the variation-controlled check. So:
  - v2 is **not ready for live integration**;
  - the variation needs an audio-aware fill budget before the next
    certification pass.

Pending before live integration:
1. **Fill timbre:**
   - cap re-voiced notes per segment;
   - drop kick 36 as a fill target;
   - prefer snare / rim / clap;
   - or add a centroid proxy to the move budget.
   Then re-certify.
2. Resolve the 3 repetition-target misses and decide the R4 band.
3. Decide whether the per-cell limits hold where `v1_wide` has almost no
   spread; hiphop and rock pulse-clarity SDs are near 0.
4. Section 6.4 manifest, 6.5 Tier S and 6.6 Tier L.

---

## 7. First implementation task: `groovegen_pilot/stimulus_audit.py`

This changes no behavior. It measures the current system so that every later
change is compared against numbers rather than impressions.

**Files**
- `groovegen_pilot/stimulus_metrics.py` (new, pure functions; the future
  energy guard reuses them):
  - `bar_onset_sets(pm, tempo, layer)`
  - `distinct_bars(sets)`, `max_identical_run(sets)`
  - `near_repeat_similarity(a_sets, b_sets)` (R4)
  - `motif_signature(pm, genre)`, `motif_distance(a, b)` (R5)
  - `phrase_metrics(sets)` (R6)
  - `tonal_collection(pm)` (R7)
  - `bounded_features(pm, tempo)`: wraps
    `music_features_measured.midi_features` and adds on/off-beat ratio,
    velocity mean and 90th percentile, register median and range per
    instrument
  - `locked_signature(pm)`: tempo, program multiset (drum voice set moved
    to `bounded_set_features(pm)` after the baseline audit)
- `groovegen_pilot/stimulus_audit.py` (new CLI).

**Inputs**
```
--generator bank                (only mode for now; 'session' added in Phase 2)
--cells live                    (the 27-cell ladder: build_ladder(tier_caps={**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES}))
--variants 32                   (bank seeds via MelodyBank._seed_for_variant)
--trajectories dwell,sweep,traces
--audio / --no-audio            (default --no-audio; --audio reuses measure_one's render + audio_features)
--sf2 ../soundfonts/Musyng_Kite.sf2
--out renders/smoke_audit/<stamp>/   (never frozen_v2)
```

Trajectories:
- `dwell`: 12 consecutive segments in each cell.
- `sweep`: calm1 up to the top and back down, 1 rung per segment.
- `traces`: rung sequences read from local session traces in
  `renders/pilot_zero/*/session_trace.csv`, which include Stage 0 and v01/v02
  runs. They are gitignored and read-only; only the rung column is used.

For each trajectory, `MelodyBank(4, 0)` assigns seeds in visit order, exactly
as `run_session_v2` does.

**Outputs**
- `segments.csv`: one row per generated segment. Columns: cell, variant,
  seed, sha (full, drum, pitched); R1, R2, R6; the bounded features; locked
  signature; `gen_ms`; and `render_ms` plus audio features when `--audio` is
  set.
- `trajectories.csv`: per trajectory and segment: R3 distance, R4 vs. the
  previous same-cell visit, R5 distance, R7 collection change.
- `summary.json`: per-cell baselines for R1-R7, bounded-feature mean, SD,
  min and max, and locked-feature stability (expect 0 variation). Includes
  code sha, soundfont sha and argument echo.
- `stim_envelope_bank_v1.json` (only with `--audio`): the section 6.2
  envelopes.

**Done when**
1. `--no-audio` runs over all 27 cells x 32 variants in under 2 min, and
   `--audio` in under ~15 min with a process pool, as in
   `music_features_measured.main`.
2. It reproduces the section 1 measurements (R1: 1 distinct drum bar for 6
   cells and 2 for latin; hiphop and rock 3 distinct bars overall; hiphop
   key change across variants).
3. The locked signature is constant within every cell across all 32 bank
   variants. If it isn't, that is a finding about the current generator that
   the plan has to absorb before Phase 2.
4. Verified per the `groovegen-verify` skill: `py_compile`, the run
   commands, and the output paths shown.

**The task after that:** the M1 bit-identity sha list (`test_composer_identity.py`), then Phase 2a.

---

## 8. Phases (revised)

| Phase | Content | Exit gate |
|---|---|---|
| 1 Audit | `stimulus_metrics.py`, `stimulus_audit.py`, bank envelopes, `test_composer_identity.py` | Section 7 done; targets in section 2 and bounds in section 3 re-set from the measured baseline |
| 2a Drum variation + schedule | `composer/arrangement.py` (schedule, blocks, session key lock), `composer/variation.py` (form templates, micro-ops, fills, skeleton table), `composer/energy_guard.py` | Tier M passes; R1, R2, R3, R6, R7 targets met; fallback < 5% |
| 2b Certification tooling | `certify_stimuli.py`: v1 bank vs v2 session per live cell, MIDI + Tier A, wide same-cell reference (section 6.7) | Tool and tests in place; findings recorded in section 6.7 |
| 2c Motif ops (optional) | Motif-track ops in `variation.py` | Tier M passes; R5 targets met; A2 still holds |
| 3 Certification | `certify_stimuli.py`, manifest; Tier A | A1-A6 pass for the manifest |
| 4 Runner integration | `segment_renderer.py`: public `render_midi(pm)` wrapping `_render_pm_to_audio`. `run_session_v2.py`: `SessionConfigV2.generator` (`'bank'` default), per-cell visit counter, `SessionComposer` branch at steps 3-4, appended `TraceRowV2` fields. `run_pilot_zero.py`: `--generator`, `--stim-seed`, `--stim-manifest`, MIDI saved to `session_dir/midi/`, summary provenance. | Tier S passes; plan invariance holds |
| 5 Replay | `replay_session.py`; yoked replay from (cell, `visit_idx`) | 100% sha match |
| 6 Comparison (developer) | Tier L; paired bank vs. session developer runs with the same `--phases` | Section 10 criteria; `DEVIATIONS.md` entry before any participant use |

Appended `TraceRowV2` fields (append-only, with defaults):
- per segment: `generator`, `gen_version`, `stim_seed`, `visit_idx`,
  `block_idx`, `base_seed`, `var_seed`, `gen_attempts`, `gen_fallback`,
  `form_template`, `midi_sha256`, `manifest_hit`, `render_ms`,
  `deadline_slack_s`;
- per bar (the only bar-varying fields): `bar_role` (`A`/`A'`/`Fs`/`F`),
  `drum_ops`.

The existing `seed` column keeps its meaning (the seed passed to the
generator, now `base_seed`), so plan columns are unchanged.

Not touched: `control.py`, `ladder.py` logic, `composer.py`, the frozen
cells, `FROZEN_SEEDS`, `trace_schema.py`, `renders/frozen_v2/`, the
CascadeController.

---

## 9. Risks (variation-specific)

| Risk | Cause | Mitigation |
|---|---|---|
| Variation shifts cell energy | Fills add hits; toms add new voices; op velocities not zero-mean | Replacement fills, count-neutral ops, bounded checks per segment, audio certification, snare-only fallback vocabulary |
| Cell identity erodes ("doesn't sound like rnb3 anymore") | Too many ops per bar; protected notes incomplete | Section 4.3 skeleton table; R4 lower bound (drums >= 0.6); Tier L "same condition?" check |
| Repetition still audible | Variation lands only on bars 4 and 8; the ostinato genres stay loops | R1 and R2 targets; block form A, A', A''; R4 upper bound; Tier L "does it loop?" |
| Novelty confounds energy | Some genres have richer op catalogs | Same `L` and templates for every cell; A6 correlation check |
| Path dependence misread as personalization | `visit_idx` depends on the controller path | Documented in section 5; path-invariance test; content is fixed per (cell, visit) |
| Frozen-cell drift breaks key lock | A future edit to `_resolve_spec` | `cell_key` pinned by a test against generated output |
| Stale certification | Composer, cell or soundfont change after certifying | Manifest stores code, soundfont and envelope shas; the runner refuses on mismatch; sha checked every segment at runtime |
| Timing | Guard retries at runtime | Retries are deterministic and pre-computed in the manifest; runtime is regenerate (~30 ms) plus sha compare |
| Crash in the variation code | Bug in ops | `compose` catches its own errors and falls back to base with `gen_fallback` logged; the session continues |
| Protocol scope | The IRB draft may describe a fixed stimulus library (I haven't read the .docx) | `/research-protocol-check` before participant use; `DEVIATIONS.md` entry |

---

## 10. Acceptance criteria

1. **Backward compatibility:** M1 bit-identity holds; `--generator bank`
   sessions are unchanged.
2. **Locked features:** 100% of certified segments pass M2.
3. **Bounded features:** 100% of certified segments pass M3 and A1; gate
   fallback < 5% of manifest entries.
4. **Cell energy preserved:** A2, A3 and A5 hold for every live cell.
5. **Non-repetition:** R1, R2, R3, R6 and R7 targets met across all
   certified segments and in the Tier S sessions; R4 and R5 bands met in
   the `dwell` and `traces` trajectories.
6. **Validity:** `test_generator_boundary.py` passes (signature, imports,
   path invariance); A6 |rho| < 0.3.
7. **Reproducibility:** manifest sha hit rate is 100% in Tier S;
   `replay_session.py` gives a 100% match.
8. **Timing:** 0 underruns and minimum slack >= 1.0 s in a 15-min real-clock
   headless run.
9. **Regression gates pass**, and plan invariance holds.
10. **Scope:** research-protocol-check recorded; `DEVIATIONS.md` updated
    before any non-developer session.

---

## 11. Notes

- FastJEV doesn't exist in this repo. The fast loop is the `groovegen-verify`
  skill plus Tier M checks (seconds) and headless `run_session_v2` with an
  injected clock.
- The provisional thresholds in sections 2, 3.2 and 6.3 are starting
  proposals. Phase 1 replaces them with values tied to the measured bank
  baseline, and the replacements should be recorded in this file.
