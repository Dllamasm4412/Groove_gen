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
| A6 novelty balance (6.11) | Within-block new drum-bar share C1: mean >= 1/8 and \|OLS slope on u\| / mean <= 0.25 (provisional). The old Spearman(u, mean R4) is reported as a diagnostic only |

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
- **A6:** novelty balance (6.11). The old Spearman rho of ladder u against v2
  R4 is reported as `r4_energy_rho_diagnostic`, with no pass/fail.

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

### 6.8 Timbre-preserving variation (v2a.2, 2026-09-30)

Item 1 of the 6.7 pending list. Changes `composer/variation.py` and
`composer/arrangement.py` (`GEN_VERSION` `v2a.2`). `energy_guard.py` now
also reports a `drum_brightness` delta, which is not gated. v1,
`composer.py`, the frozen cells, the controller and `run_session_v2` are
unchanged. v2 is still not wired into the live runner.

**Evidence behind the design:**
- **Voice brightness:** each voice was rendered alone through
  Musyng_Kite. Centroids: hats 42/44/46 8.3-9.7 kHz, ride 51 6.2 kHz,
  rim 37 2.8 kHz, clap 39 2.2 kHz, snare 38 0.5 kHz, congas 62-64
  0.2-0.7 kHz, kick 36 0.1 kHz.
- **v2a.1 re-voicing:** 5.1 notes per segment were re-voiced, 4.75 of them
  across timbre families and 1.29 into kick 36. The worst genre was
  hiphop, at 8.2.
- **Single-edit probes** (effect of one edit on the rendered audio):
  - A 16th move raises the centroid slightly but lowers pulse clarity by
    0.001-0.03.
  - An in-place hat-to-snare change keeps pulse clarity and lowers the
    centroid by 10-30 Hz per note.

**Algorithm:**
- Every op keeps the note count and each note's velocity, and writes only
  voices the base already plays.
- Ops, cheapest first:
  1. **exchange:** two nearby non-kick notes of different voices trade
     slots, so the onset grid and voice mix are unchanged.
  2. **family:** in-place swap within a timbre family (hats/ride;
     snare/rim/clap; conga, bongo and timbale articulations).
  3. **move:** a ±1 16th shift, at most 1 per segment, within 0.4 of the
     guard bounds.
  4. **cross:** an in-place re-voice to the brightest snare-family or hand
     voice, never kick, clave or crash. At most 2 per segment, and
     `drum_brightness` (velocity-weighted classes 1 / 0.6 / 0.3 / 0) may
     fall at most 0.01.
- **Phrase ends:** bars 4 and 8 always get one op. Only there may a
  family or cross op exceed the cross cap and brightness budget; the
  feature budget is never exceeded.
- **Other bars:** the other A' bars and the second bar-8 op get an op only
  within budget. A note changed once is not changed again.
- **Templates:** T2 now varies bar 4. Crescendo and fill styles are
  removed.
- **Session:** a variation is retried, up to 12 attempts, if it:
  - fails the guard;
  - leaves bar 4 or 8 unmarked;
  - has more than 3 identical bars in a row;
  - repeats a drum layer from the previous 4 visits, or full content from
    any earlier visit.

  Every 4 failed attempts, `relax` raises the move and cross caps and the
  brightness and move budgets.

**Re-voicing, v2a.1 to v2a.2** (per segment; 27 cells, stim seeds 1-2, 12
visits):

| | v2a.1 | v2a.2 |
|---|---|---|
| Notes re-voiced | 5.11 | 1.98 |
| Cross-family | 4.75 | 0.85 |
| Into kick | 1.29 | 0 |
| New onset slots | 1.30 | 0.53 |
| `drum_brightness` change | -0.026 | -0.005 |

Per genre, cross-family notes went from 2.4 to 2.5 in calm, 7.4 to 0.6 in
hiphop, 4.5 to 0.8 in rock and 4.5 to 0.03 in latin.

**Certification, MIDI only (run 20260930_122048):**
- Repetition targets met in 27 of 27 cells (24 before). Fallback rate 0.
- Variation-controlled at MIDI level in 26 cells. The exception is
  hiphop:1: on-beat share shifts -0.027 against an allowance of 0.025.
- All within-cell-range misses come from base seeds.

**Certification with audio (run 20260930_122337):**

| Measure | v2a.1 | v2a.2 |
|---|---|---|
| Repetition targets met | 24/27 | 27/27 |
| Mean R1 (distinct drum bars) | 4.46 | 4.03 |
| Max R2 (identical bars in a row) | 3 | 3 |
| Exact-repeat rate, max | 0.045 | 0 |
| Bar 4 marked, lowest cell | 46% | 100% |
| Bar 8 marked, lowest cell | 100% | 100% |
| Minimum drum-repeat distance (visits) | 3 | 5 |
| R4 range | 0.76-0.96 | 0.77-0.98 |
| Centroid variation shift, mean | -111 Hz | -13 Hz |
| Centroid variation shift, range | -334 to -12 Hz | -54 to +16 Hz |
| Pulse clarity variation shift, mean | -0.015 | -0.003 |
| Pulse clarity variation shift, min | -0.030 | -0.017 |
| LUFS variation shift, max |·| | 0.046 LU | 0.006 LU |
| E variation shift, max |·| | 0.030 | 0.0085 |
| Variation-controlled cells | 5 | 8 (lofi:1-3, latin:3, pop:1-3, pop:5) |

The E limit is 0.023. The centroid is still slightly lower on average
(22 of 27 cells below 0), but only 3 cells exceed their allowance.

**Still failing variation-controlled (19 cells):**

| Cells | What fails | Why | Kind |
|---|---|---|---|
| calm:1, calm:2 | Centroid -31 Hz (allowed 7.5) | The only free voice is the on-beat hat. A move breaks the on-beat limit (1/32 > 0.025) and pulse clarity (4x); a rim costs 2x the centroid allowance. No single edit fits. | Envelope |
| hiphop:1 | On-beat share -0.027 (allowed 0.025); pulse -0.0064 (allowed 0.0057) | Same structure as calm: all hats are on the beat | Envelope |
| rock:1-4, rnb:4 | Pulse shift | rock allows 0.001-0.002; one 16th move costs 0.0014-0.01. The other option, 2 hat-to-snare edits, costs about 50 Hz against a 25-45 Hz allowance. | Mostly envelope. rnb:4 (-0.017 vs 0.013) needs a look at its exchanges. |
| hiphop:3-5 | Flux about -0.006 (allowed 0.004-0.005) | Family swaps are mostly 42>46; the open hat's sustain is the likely cause, not yet isolated | Generator |
| rock:5 | Centroid -54 Hz, flux, pulse | Not yet isolated | Generator |
| latin:2 | Pulse -0.007 (allowed 0.0025) | Also misses A3 | Mixed |
| hiphop:2, latin:1, rnb:1-3, pop:4 | 1-6 segments outside the envelope; all cell shifts pass | | Borderline |

**Envelope evidence:** in calm, hiphop, rock and latin:1-2, the v1 drum
layer does not change with the seed. So the `v1_wide` SDs of centroid,
pulse clarity and flux measure only pitched variation, and any drum change
at all can exceed 0.5 SD. The limits were not changed. Whether they apply
to a drum-only variation is a decision for the protocol.

Pending (replaces 6.7 items 1-2):
1. **Generator:**
   - weight family swaps toward 46>42 (or neutral) and re-check flux in
     hiphop:3-5;
   - isolate rock:5's centroid and rnb:4's pulse effect.
2. **Decision on the limits:**
   - in drum-seed-invariant cells, either keep them and accept that calm,
     hiphop:1 and rock:1-4 cannot vary their drums;
   - or set them from a drum-perturbation reference.

### 6.9 Per-op attribution and ring-preserving variation (v2a.3, 2026-09-30)

#### Method

`op_attribution.py` (debug only) renders each op a segment logged, applied alone
to that segment's base. It also renders probe ops drawn from the base's own
candidates. It reports each op's centroid, flux, pulse, LUFS and E delta in units
of the cell's certification allowance.

#### Causes, per op, in allowance units (x)

- **Open-hat choke (hiphop:3-5, rock:5).**
  - GM plays 42/44/46 in one exclusive class, so a closed or pedal hat cuts a
    ringing open hat.
  - Ops that create, remove or move a 46, or change the hat that cuts it:
    - family 42>46: flux -0.4 to -0.7;
    - family 46>42: centroid -0.9 to -2.1;
    - exchange 42<>46: centroid -0.3 to -1.1.
  - These gave all of the hiphop:3-5 flux drop and all of rock:5's drift.
  - The 46>42 direction trades flux for centroid, so it is not a fix.
- **Cross-family exchange (rnb:4).** 38<>42, 38<>51 and 38<>46 move the snare
  accent: pulse -0.5 to -0.9 per op.
- **Regular-lane moves (latin:2, rock).** A 16th move of a note on a straight
  8th-note hat line costs pulse -3 to -11 per op. latin:2 made these moves because
  vary() searched every tier inside the fill window before any cheap op in the
  rest of the bar (a loop-order defect).
- **hiphop:1 and rock:1-4 have no low-cost op.** Every available op costs about
  1x of some allowance: cross 42>38 costs centroid -0.8 to -1.1, a grid move costs
  pulse -1.4 (hiphop:1) or -4.9 (rock:3).

#### Rules (composer/variation.py)

1. Every op keeps `open_hat_rings` (open-hat onset, next choking hat) unchanged.
   A last-resort pass on required phrase ends may waive this for exchange and
   family ops; it is counted as `ring_break`. It exists for lofi and rnb bases with
   a 46 on every off-beat, where only kick moves are ring-safe and there were 1-3
   fallbacks per 24 segments.
2. Exchanges are allowed only within one timbre family.
3. A move of a note in an evenly spaced run of 3 of its lane is a `grid_move`
   (capped at MAX_MOVES). Other moves are limited by the feature budget only.
4. Tier order is exchange, move, family, grid_move, cross, with tiers as the outer
   loop and windows as the inner loop.
5. Cross is allowed only on phrase ends at relax 0. Without optional cross on
   retries, hiphop:3 fell back in 18 of 24 segments.

#### Results (full audio run `20260930_133905`)

| Measure | v2a.2 (`20260930_122337`) | v2a.3 |
|---|---|---|
| Repetition targets | 27/27 | 27/27 |
| Fallback | 0 | 0 |
| Variation-controlled cells | 8 | 12 |
| within_cell_range cells | 6 | 8 |
| Segment ok rate | 0.73 | 0.81 |
| Flux: shift-fail cells / variation envelope misses | 4 / 38 | 0 / 14 |
| Pulse: shift-fail cells / variation envelope misses | 9 / 70 | 4 / 42 |
| Centroid: mean shift / max \|shift\| / shift-fail cells | -13 Hz / 54 Hz / 3 | -6 Hz / 31 Hz / 2 |
| Centroid variation envelope misses | 26 | 29 (latin:1, latin:2) |
| LUFS max \|shift\| (allowance 0.5) | 0.006 LU | 0.022 LU |
| E max \|shift\| (allowance 0.023) | 0.0085 | 0.0114 |
| a6 novelty rho (limit 0.3) | 0.08 | 0.40 (fails) |

- Newly variation-controlled: hiphop:4, rnb:1, rnb:2, rnb:4 and pop:4.
- latin:3 is no longer variation-controlled (2 flux envelope misses).

#### Open issues

- **a6.** The ring rule leaves hiphop:3-5 with ops only on the one rim note per
  bar, so consecutive visits reuse bar patterns: R4 rose 0.96 -> 0.99.
  - Restoring their v2a.2 R4 alone gives rho 0.29.
  - Optional cross at relax 0 did not help (rho 0.398), because the rim ops win
    the tier order.
  - Novelty there needs hat-lane changes (ring breaks cost flux; crosses cost
    about -0.5x centroid each) or a novelty criterion in SessionComposer.
    Decision pending.
- **latin:1-3.** Every op is a same-family conga exchange 63<>64 (4.7 per
  segment, +0.14x centroid each), so the centroid shift accumulates. The family
  op 63>64 costs 0.00x. Putting exchange first follows the stated priority; the
  evidence favours mixing exchange and family ops for congas.
- **Envelope classification.** rock:1-4, hiphop:1 and calm's pulse and centroid
  allowances come from v1 drums that do not vary with the seed, so they reflect
  pitched variation only (rock pulse allowance 0.001-0.002). These failures are
  unavoidable under those limits, not generator defects. They are the same limits
  question as 6.8 item 2.

### 6.10 Op cost and bounded novelty (v2a.3, 2026-09-30)

#### Op cost (composer/variation.py)

- Ops are chosen by cost level, not tier: `COST` = exchange 1, move 2,
  family 3, grid_move 4, cross 5 (plus 5 per ring break). Ops of equal cost
  share one shuffled pool, and each level tries the fill window before the
  whole bar.
- A family swap between articulations of one hand drum (conga, bongo,
  timbale) costs 1, the same as an exchange. Evidence: latin 63>64 costs 0.00x
  centroid, while repeated 63<>64 exchanges cost +0.14x each. This is a
  drum-family rule, not a genre rule. latin:1-2 now make about 3 articulation
  swaps and 1.2 exchanges per segment (before: 4.7 exchanges).

#### Novelty (composer/arrangement.py)

- `SessionComposer` draws up to 12 candidates in 3 rounds of 4. Round r uses
  relax r. Candidates are sub-seeds of var_seed, so the draw is deterministic
  from (stim seed, genre, tier, visit, gen version). The previous visit of the
  cell is recomputed from the schedule.
- A candidate is valid if:
  - both phrase ends are marked;
  - it has no identical run and no drum or full repeat;
  - it passes the energy guard.
- The novelty range is drum R4 against the previous visit of the same cell
  <= `R4_PREV_MAX` = 0.97, the same for every cell. Evidence: the v2a.2
  within-block R4 (same base, previous visit) had median 0.962 and p75 0.969.
  There is no floor: one op moves R4 by an amount that depends on the bar's
  onset count (about 0.78 for 8 onsets per bar, 0.91 for 22), so a floor would
  bind only the sparse cells. The number of varied bars and the energy guard
  already bound how much a visit changes.
- The chosen candidate is the in-range one with the lowest op cost, ties broken
  by index. If no round has an in-range candidate, the valid candidate nearest
  the range is used (`novelty_fallback`). If none is valid, the base is used.
- `vary(avoid=, fresh=)`: at equal cost, a candidate prefers bar patterns the
  previous visit did not play. From round 1 (`fresh`), it prefers them over
  cheaper ops, except that novelty never buys a cross: allowing that doubled
  hiphop:3-5's crosses and moved centroid -17 -> -40 Hz (allowed 36).
- Logged fields: gen_candidates, gen_candidate_idx, gen_sub_seed,
  novelty_rejections, novelty_fallback, novelty_r4_prev, novelty_r4_base,
  op_cost, fresh_bars.

#### Results (full audio `20260930_143933`, full MIDI `20260930_143529`)

| Measure | v2a.3 before novelty (`20260930_133905`) | v2a.3 with novelty |
|---|---|---|
| Repetition targets / fallback | 27/27 / 0 | 27/27 / 0 |
| Variation-controlled cells (audio) | 12 | 11 |
| Variation-controlled cells (MIDI) | 26 | 26 |
| Segment ok rate | 0.81 | 0.82 |
| Within-block R4 q50 / q95 / exact 1.0 | 0.971 / 1.0 / 10% | 0.962 / 0.971 / 0% |
| Centroid: mean shift / shift-fail cells / envelope misses | -6 Hz / 2 / 29 | -8 Hz / 3 / 11 |
| Flux: shift-fail cells / envelope misses | 0 / 14 | 0 / 8 |
| Pulse: shift-fail cells / envelope misses | 4 / 42 | 6 / 41 |
| LUFS max \|shift\| / E max \|shift\| | 0.022 LU / 0.011 | 0.022 LU / 0.012 |
| a6 rho (limit 0.3) | 0.40 | 0.43 (fails) |

- Cells that changed:
  - latin:3 is now variation-controlled.
  - latin:2 centroid envelope misses fell 14 -> 2.
  - rnb:4 (1 E miss) and pop:3 (1 pulse miss) are no longer variation-controlled.
  - hiphop:1 and rock:1 pulse shifts now fail. Their op mix is unchanged (one
    cross and one grid move per segment); different grid moves were picked.
  - latin:1-2 gained low_ratio envelope misses (8); their shifts are inside the
    allowance.
- hiphop:3-5 R4 against the previous visit:
  - hiphop:4-5: 0.99 -> 0.971.
  - hiphop:3: still 0.989, with novelty_fallback in 16/24 segments. Its only
    ring-safe, non-cross ops touch the one rim note per bar.

#### Why a6 still fails

- a6 correlates u with mean R4, where the mean includes the first visit of each
  block (new base). Two properties of v1 cells drive that correlation, not the
  variation:
  1. **Cross-block R4 is set by the base.** lofi, rnb and pop drums change with
     the seed (cross-block R4 0.28-0.78). calm, hiphop, rock and latin drums do
     not (0.93-0.98), and they hold most of the high-u cells.
  2. **R4 per op depends on density.** Onsets per bar vs u: rho +0.63. One op in
     a 24-onset hiphop bar changes R4 less than one op in a 7-onset calm bar.
- A count-based novelty measure is independent of energy: new bar patterns per
  visit (within block) vs u has rho +0.10 (1.1-3.3 per visit; hiphop:3 is the
  lowest at 1.1).
- Classification: a certification-metric issue (a6 measures base seed-invariance
  and density, not novelty), plus the hiphop:3 constraint below. **The old a6
  still fails (0.43 vs 0.3) at this checkpoint.** Decision (2026-09-30): the
  generator is not changed to pass it; a6 stays as a diagnostic, and a revised
  novelty-balance metric is reviewed as a separate change. The a6 limit is
  unchanged.

#### Remaining failures, classified

- **hiphop:3 novelty: meaningful drum variation constrained by the available
  audio-safe degrees of freedom** (not a generator defect; decided 2026-09-30).
  Open-hat changes cost flux and cross-family swaps cost centroid, so no further
  crosses are spent on it. Future novelty for this cell may come from non-drum
  dimensions (motif, bass, voicing, melody, phrase development), not in v2a.3.
- **Certification / reference envelope:**
  - calm:1-2, hiphop:1 and rock:1-5 (pulse / centroid; the v1 drums are
    seed-invariant, pulse allowance 0.001-0.006);
  - a6 (reviewed in 6.11);
  - single-segment envelope misses in rnb:3, rnb:4, pop:3, hiphop:2, hiphop:3
    and hiphop:5, where every shift is inside its allowance.
- **Generator defect:** none identified. latin:1-2 E / flux / low_ratio
  envelope misses (3-5 each) come with all shifts inside the allowance. They
  are listed for the envelope review, not fixed here.

### 6.11 A6 review: novelty balance (2026-09-30)

Question: does the amount of new musical material vary systematically with
cell energy? Evaluated on regenerated v2a.3 MIDI (identical to the saved
certification rows; no audio). v2a.2 (079d2ba) serves as the positive control:
it spent more ops in dense, high-energy cells.

#### Why the old a6 is confounded

- R4 is a note-level Jaccard. One op changes a smaller share of a 24-onset
  bar than of a 7-onset bar, so R4 rises with density (hits/bar vs u: +0.68).
  v2a.3 spends about the same number of ops per visit in every cell (ops/visit
  vs u -0.01; ops/hit vs u -0.67). R4 reads that as less novelty at high energy.
- Over all visits, R4 is dominated by block boundaries, where the base changes.
  How much the drums change with the seed is a v1 composer property:
  - lofi, rnb and pop drums change with the seed;
  - calm, hiphop, rock and latin drums do not.
  R4 (all visits) vs v1 base change: rho -0.85.
- The old a6 is wrong in both directions. v2a.2 passed (+0.08) while its
  within-block new material rose with u (+0.57, +69% of the mean per unit u).
  v2a.3 fails (+0.43) while its new material is flat (-7%).
- Same-base R4 for v2a.3 has rho +0.70, but its cell means span only
  0.920-0.986 (+4% of the mean per unit u). Spearman ranks near-constant values
  and magnifies a small density effect.
- With 27 cells, the permutation null puts the 95th percentile of |rho| at
  0.38, so the 0.3 limit lies inside noise.

#### Candidates

Each candidate is computed per visit against the previous visit of the cell,
then meaned per cell. "Within block" means the visit has the same base as the
previous one. The columns are Spearman rho over 27 cells for v2a.3, and the
v2a.2 rho vs u.

| Metric (v2a.3, within block) | mean [min, max] | u | tier | hits/bar | base chg | v2a.2 u |
|---|---|---|---|---|---|---|
| A old a6: R4, all visits | 0.900 [0.764, 0.983] | +0.43 | +0.19 | +0.18 | -0.85 | +0.08 |
| B R4 | 0.954 [0.920, 0.986] | +0.70 | +0.46 | +0.50 | -0.29 | +0.00 |
| C1 new drum-bar fraction | 0.274 [0.148, 0.422] | -0.33 | -0.31 | +0.09 | +0.22 | +0.57 |
| C2 distinct new drum patterns | 2.06 [1.12, 3.31] | +0.10 | -0.14 | +0.42 | +0.23 | +0.59 |
| D changed drum-bar fraction (aligned) | 0.370 [0.242, 0.492] | -0.16 | +0.01 | +0.27 | +0.16 | +0.42 |
| E onset change (sym. diff. / onsets) | 0.049 [0.025, 0.094] | -0.82 | -0.42 | -0.75 | +0.19 | -0.29 |
| F1 new bar fraction, all layers | 0.347 [0.188, 0.477] | -0.36 | -0.13 | +0.10 | +0.36 | +0.42 |
| F2 new drum bars vs last 4 visits | 0.166 [0.062, 0.359] | +0.09 | -0.04 | +0.32 | +0.51 | +0.52 |

- **Effect size**, as the OLS slope of the cell mean on u divided by the mean,
  with a 95% bootstrap interval over visits:

  | Metric | v2a.3 | v2a.2 |
  |---|---|---|
  | C1 | -0.07 [-0.18, +0.04] | +0.69 [+0.57, +0.81] |
  | C2 | +0.16 [+0.07, +0.24] | +0.69 |
  | D | -0.20 [-0.34, -0.06] | +0.36 |

- **New-block novelty** (v1 base change) is a genre property:
  - C1 at block boundaries vs v1 base change: +0.76;
  - C1 at block boundaries vs u: -0.20.
  It is reported per cell and not attributed to the generator.
- **Ops normalized by opportunity** (E in the brief) is diagnostic only. It
  rewards more edits and does not measure what is heard.
- **Genre and tier:**
  - The C1 rho of -0.33 comes from genre composition. calm, lofi and latin sit
    at low u with 0.28-0.37; rock and hiphop sit at high u with 0.25.
  - Within genres the tier trend is flat (weighted within-genre tier rho
    -0.12; rock 0.24-0.27 across five tiers).
  - Low-u third 0.273, high-u third 0.257.
  - Lowest cell: hiphop:3 (0.148, the constraint in 6.10). Highest: latin:3
    (0.422).

#### Choice

C1 is the **within-block new drum-bar fraction**: the share of the 8 drum bars
whose onset set (track, pitch, grid position) occurs nowhere in the previous
visit, over visits that share the previous visit's base seed.
- It measures new material directly and is shift-tolerant. A bar that reappears
  elsewhere does not count, whereas D counts it.
- It counts per bar, so a new pattern heard twice counts twice: it is the share
  of listening time that is new. C2 counts it once, and C2 is more
  density-tied (+0.42 vs +0.09).
- It is the least density-tied bar-level measure, it excludes the base-seed
  change, it is deterministic from MIDI, and it detects v2a.2's
  energy-allocated novelty.

#### A6 criterion: novelty balance (adopted 2026-09-30)

| Part | Rule | Evidence |
|---|---|---|
| Evaluable | Mean C1 >= 1/8 (one new bar per visit) | Below this, a ratio to the mean is meaningless. v2a.3 has a mean of 0.274 |
| Balance | \|OLS slope of C1 on u (the measured energy position)\| / mean C1 <= 0.25 | v2a.2 +0.69 fails; v2a.3 -0.07 passes. The bootstrap half-width is about 0.11, and 0.25 is about half a bar per visit across the full u range at the v2a.3 mean |

- Reported beside the criterion, not gated:
  - Spearman rho vs u;
  - the within-genre tier rho;
  - the low- and high-u third means;
  - the bootstrap interval;
  - new-block C1 for v1 and v2.
- The criterion is two-sided and does not reward more edits.
- **Limitations:**
  - **The 0.25 limit is a provisional engineering threshold, not a perceptually
    validated value.** It is set from one positive control (v2a.2) and one
    candidate (v2a.3), not from listener data. It is neither tightened nor
    loosened at this stage.
  - C1 covers drums only; non-drum novelty (6.10 future work) is not measured.
  - u is the ladder position, so genre composition along u still enters the
    slope. The within-genre tier rho is reported to show this.
- **v2a.3 result:**
  - full MIDI run, `certify_stimuli.py`, 20260930_192025 (values identical to 190950, before
    the key renames);
  - mean 0.274; rel_change_per_u -0.074 [-0.179, +0.039]; rho_u -0.33;
    within-genre tier rho -0.12;
  - **A6 passes** (`overall.a6_novelty_balance = true`);
  - the old R4 statistic is unchanged at 0.4262.
- **Status: adopted by the user on 2026-09-30 as the A6 criterion.**
  - Output keys: `a6_novelty_balance` (the gated parts are `mean` and
    `rel_change_per_u`; `diagnostic` holds rho, the within-genre tier trend, the
    u-third means and the bootstrap) and `overall.a6_novelty_balance`.
  - The old A6 is `r4_energy_rho_diagnostic`: a rho with the old 0.3 limit for
    reference and no `ok` field. It is not a novelty pass/fail.
  - The within-genre tier trend stays a diagnostic. It is not a gate, because
    the global slope still reflects genre placement on the ladder.
- No generator change is needed. The v2a.3 novelty generator is not modified
  further.

### 6.12 Stateful melodic development (v2b, first slice, 2026-09-30)

- **Problem.** v2a.3 varies drums only. Its pitched material (stim_seed 1, 8 visits, 27 cells):
  - pitched R4 = 1.0 within every block in every cell;
  - hiphop:1-5 play one pitched content over all 8 visits: the frozen cell's 2-bar RH
    ostinato x4, and the session key lock removes the key draw, the only pitched
    seed dependence;
  - latin:1, latin:2 and rock:3 repeat one exact cross-block pitched content;
  - calm, pop, rnb and lofi get new pitched material per block.
- **Design** (`composer/motif.py`, opt-in `SessionComposer(stim_seed, develop=True)`,
  hiphop only, `DEV_VERSION` v2b.0, v2b.1 since 6.12a):
  - Development runs after drum selection. The drum history and all v2a.3 seeds are
    unchanged, so drums are byte-identical to v2a.3.
  - `read_hook` reads the ostinato back from the MIDI as (16th slot, diatonic step)
    pairs. `realize` writes a 4-phrase plan [M, M, R, E] onto the same notes, and the
    lead keeps the cell's own fold rule. Note count, velocities, durations, tracks,
    LH, bass and drums are unchanged by construction.
  - The motif seed is H('motif', stim_seed, genre, tier, visit_idx, SEED_VERSION),
    where SEED_VERSION stays 'v2b.0' for v2b.1.
    State is the cell's previous motif records, so there are no physiological inputs
    (generator boundary test extended).
- **Rules** (every motif):
  - anchor unchanged;
  - beats 1/3 on i7 chord tones;
  - steps within the base hook's step range +-1 and RH 72..96;
  - leaps within the base hook's largest leap;
  - onsets equal the base hook's (pitch-only);
  - with a lead, each phrase keeps the base number of notes <= 84 (octave-doubled).
- **Schedule** (block = 3 visits):
  - visit 0: the base hook with a varied ending;
  - pos 1: one pitch op (neighbor, chord, sequence), with a one-bar recall of the
    previous theme in phrase 3;
  - pos 2: an ending or neighbor op;
  - new block, odd: derive (call bar kept, answer bar rebuilt as a sequence or
    inversion on a chord tone);
  - new block, even: return to the theme of two blocks back with two pitch ops.
- **Selection.** A motif or plan seen in the last 6 visits of the cell is rejected.
  Of 12 deterministic candidates, the first that passes the rules, the history check
  and the motif guard is used. The guard checks locked signature, per-track shape,
  LH/bass/drums unchanged, diatonic hook, energy-guard bounds, and pitched
  median/p05/p95 within +-2 semitones. Otherwise the previous motif is kept, with an
  ending.
- **Two audio findings (durable).** Both come from certification at the default
  reference: hiphop:1/3/5, 8 visits, stim seeds 1-2.
  1. **Lead fold.** The lead doubles RH notes <= 84 an octave up and higher ones in
     unison. Moving notes across 84 changes the spectrum: Δlow_ratio vs Δ(octave-doubled
     count) r = -0.82 at hiphop:3 and -0.69 at hiphop:5, with drafts losing about 3
     octave-doubled notes per segment. The per-phrase count rule fixes it.
  2. **Onset displacement.** Moving off-beat 16ths, or anticipating the last note,
     moves pulse_clarity: at hiphop:5 every visit with a displaced onset missed the
     envelope and every pitch-only visit passed. The first slice is therefore
     pitch-only.

     | version | segment_ok | variation-controlled cells |
     |---|---|---|
     | v2a.3 | 0.958 | 1/3 |
     | draft with displacement | 0.688 | 0/3 |
     | draft + fold rule | 0.667 | 0/3 (hiphop:5 0.31) |
     | pitch-only (final) | 0.854 | 0/3 |

- **Result, pitch-only** (MIDI, hiphop:1/3/5, stim seeds 1-2, 8 visits, v2a.3 -> v2b):

  | Metric | v2a.3 | v2b |
  |---|---|---|
  | pitched window repeats | 7 | 0 |
  | melody exact vs previous visit | 7 | 0 |
  | melody phrase variety | 0.03 | 0.47-0.53 |
  | ending variety | 0.125 | 0.75-1.0 |
  | pitched new bar frac | 0 | 0.54-0.71 |
  | pitched R4 | 1.0 | 0.83-0.91 |
  | melody contour similarity | 1.0 | 0.84-0.96 |

  Unchanged: melody rate, bass (bass R4 1.0), drums, max leap. Melody median moves
  within -1.5..+3.5 semitones.
- **Audio** (same runs), mean per cell:
  - |ΔLUFS| <= 0.05 dB, centroid +-15 Hz, flux <= 0.0012, pulse_clarity <= 0.001;
  - low_ratio -0.003..+0.006, the largest shift (hiphop:5).
  - 5/48 segments newly miss the envelope:
    - one LUFS miss (+0.24 dB);
    - two pulse_clarity misses (each <= 0.003);
    - two low_ratio misses (+0.014, +0.023, on 'return' visits).

    All five sit at envelope edges that v2a.3 already approaches. RH register only
    partly predicts low_ratio (r 0.37-0.54), so there is no MIDI guard for it yet.
- **Status: experimental first slice.** Not audio-certified (5/48 tested segments
  newly outside the current reference envelopes) and not ready for live integration.
  v2b remains opt-in (`develop=True`), hiphop-only, and is not wired live. Developer
  listening (hiphop:3 x8, stim_seed 1) found v2b meaningfully less repetitive than
  v2a.3; the architecture is kept (listening is recorded, not used as certification).
  - Census: 360 visits (6 stim seeds x tiers 1-5 x 12): 0 errors, 11 fallbacks (3.1%).
  - Derive options per (key, tier): 1-4.
  - Other genres are not started; bass development was prototyped and rejected (6.12b).

#### 6.12a Step A: the five v2b.0 misses (symbolic level check, 2026-09-30)

- **Cause (durable).** The hook's piano (Musyng_Kite, program 0) is built from sample
  zones whose levels step by up to ~7 dB between adjacent semitones (77-79 and 92-97
  are quiet). A pitch-only change therefore moves segment LUFS and low_ratio at fixed
  note count, velocity and duration. A measured per-(pitch, velocity) table
  (`composer/hook_levels.py`, `measure_hook_levels.py`, sha-pinned to the soundfont)
  predicts the shifts from MIDI: r 0.92-0.97 for LUFS and r -0.99 for low_ratio.
  - Per miss:
    - hiphop:1 s1 v3 LUFS: notes moved into loud zones;
    - hiphop:3 s2 v6 and hiphop:5 s2 v6 low_ratio: hook level fell into the quiet
      77-79 zone;
    - hiphop:5 s1 v2 and s2 v7 pulse: development on bases already within 0.0005
      of the lower edge.
- **Rule (v2b.1).** The predicted hook level stays
  within +-0.2 dB, in total and on- and off-beat separately. Summed melodic motion
  into off-beat notes and into on-beat notes is capped at +4 semitones each versus
  the cell hook. Capping off-beat motion alone moved motion onto the beat, and
  on-beat motion raises flux at hiphop:3.
- **Selection order:**
  1. rules;
  2. history;
  3. level and motion check;
  4. lowest cost;
  5. guard.

  If nothing passes, it tries a two-move balance repair, then the gentle pass, then
  the previous motif, then the motif unchanged. Fallbacks are logged in
  `motif_selection`.
- **Result** (hiphop:1/3/5, seeds 1-2, 8 visits):
  - LUFS and low_ratio misses: 0 (were 3).
  - Max |Δ| vs v2a.3: LUFS 0.09 dB (was 0.24) and low_ratio 0.009 (was 0.024).
  - segment_ok: 0.896 (v2a.3 0.958, v2b.0 0.854).
  - Census (360 visits): fallback 1.1%.
  - Novelty kept: window repeats 0, phrase variety 0.47-0.53, ending variety
    0.63-1.0.
- **Residuals, justified** (thresholds unchanged; kept for the envelope-policy review):
  - The hiphop:1 pulse_clarity variation-shift failure (-0.00936 vs 0.00567) is
    inherited from v2a.3 (-0.00984). It is not a v2b regression.
  - Pulse misses at hiphop:3 (1 new, beside 2 inherited) and hiphop:5 (2) sit on
    bases within 0.0009 of the edge. hiphop:3/5 v2a.3 already sits at that edge
    because of the v2a.3 drum variation.
  - The hiphop:3 flux variation shift is 0.00397 against 0.00359 allowed (v2a.3
    alone 0.0026). Across pooled runs, Δflux ≈ -0.0091 x Δhook-level dB + 0.0011
    (R² 0.66). The intercept is the cost of introducing real pitched development, and
    centring the level removes the +0.04 dB that had masked it. Melodic development
    is not reduced to remove it.
- **Version.** These rules are v2b.1 (`DEV_VERSION`). Motif seeds keep the v2b.0
  salt (`SEED_VERSION`), so v2b.1 MIDI equals the certified and auditioned Step A
  output (48/48 certification segments, 8/8 audition segments).

#### 6.12b Bass development: prototyped and rejected (design decision, 2026-10-01)

- **Prototype** (hiphop tiers 3-5, experimental `vb.0`, removed, not active). It was
  pitch-only development of bars 4 and 8 within the frozen cell's bass grammar:
  - the grammar: tonic on 16ths 0 and 8; at tiers 3+, a ghost tonic on 16th 6 and a
    b7 approach on 16th 15; the same bar on every visit;
  - kept: roots, rhythm, velocities and register;
  - a measured bass level check;
  - coupling to the motif's return / derive roles.

  It reduced exact bass repetition of the previous visit from 7 to 0-1 per 8-visit
  session, with no LUFS / low_ratio misses.
- **Decision.** In the developer A/B listening (hiphop:3 x8, stim_seed 1: v2a.3 /
  melody / melody + bass), the bass variation did not add enough perceptual benefit
  to justify the extra variation and complexity. It is rejected. In v2b.1 the bass
  stays the cell's original, stable line and acts as the compositional anchor under
  the developing melody.
- **Durable soundfont facts**, for any later bass work:
  - the Musyng_Kite bass (program 33) switches velocity layer between 100 and 101
    (up to -8 dB);
  - it has no sample below MIDI 26 at velocity <= 100;
  - moving the hiphop ghost note to 16th 10 cost pulse_clarity -0.018 at hiphop:3.

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
| Novelty confounds energy | Some genres have richer op catalogs | Same `L` and templates for every cell; novelty balance check (6.11) |
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
