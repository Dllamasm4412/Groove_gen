# GrooveGen — Integration Roadmap: Symbolic Generator → Control System → UI

_Last updated: 2026-08-03. Scope: wire the now-validated symbolic pipeline (r&b/latin/pop
beds + intensity-tier drums + per-instrument soundfont routing) into the existing controller
and experiment UI, so a full closed-loop session runs end to end._

This is a **systems-integration** plan, not new research. The three pieces already exist in
isolation. The work is making them talk to each other through clean, stable interfaces so the
per-bar closed-loop control paper has one coherent runnable pipeline behind it.

---

## Where each piece stands today

| Layer | Status | Lives in |
|---|---|---|
| **Symbolic bed generator** | ✅ Validated by ear (r&b, latin "amazing"; pop rhythm fixed; supersaw timbre = Colab nb16) | `symbolic_bed_proto.py`, `pop_funk_v3.py`, `symbolic_from_profile.py`, `symbolic_tiers_demo.py` |
| **Intensity-tier drum engine** | ✅ L1–L5 designed, monotonic, humanized | `symbolic_tiers_demo.py` (`drum_bar_tier`) |
| **Feature→symbolic adapter** | ✅ Demoed on 3 track_features.csv rows | `symbolic_from_profile.py` (`map_profile`) |
| **Per-instrument soundfont routing** | ✅ Proven on Colab (nb16): supersaw chops + 909 drums + EP bass | `nb16_supersaw_pop.ipynb` (routing table) |
| **PD / cascade controller** | ✅ Exists; genre outer loop + tempo/density inner | `groovegen/pd_controller.py` |
| **Session render loop** | ⚠️ Exists but calls the OLD (neural/hybrid) render path | `groovegen/session_render.py` |
| **Experiment UI** | ⚠️ Exists; not yet wired to the symbolic renderer or tiers | `groovegen/app_experiment.py` |
| **HR setpoint source** | ✅ Scripted setpoint (per the locked paper framing) | `groovegen/hr_source.py` |

**The gap:** the controller and UI still drive the *old* neural/hybrid renderer. The symbolic
generator + tiers + soundfont routing are better and validated, but they're not the thing the
closed loop actually calls yet. This roadmap closes that gap in four phases.

---

## Design principle that makes this clean

The controller must **never** know about MIDI, soundfonts, or note grids. It only emits two
things per bar:

```
controller.step(hr_setpoint, hr_measured)  ->  (intensity_tier: int 1..5, tempo_bpm: float)
```

Everything below that — which tier maps to which drum pattern, which instrument uses which SF2,
how the bed is voiced — is the **renderer's** job, hidden behind one function. That separation is
what keeps the control contribution (the paper) clean and testable, and lets you swap patches or
add genres without touching the loop. This is the single most important architectural rule here.

---

## Phase 1 — Consolidate the renderer behind one interface (foundation)

**Goal:** one module, `groovegen/render_symbolic.py`, that turns *(genre, tier, tempo, bar_index)*
into audio, with the soundfont routing table baked in.

Concrete steps:
1. Create `groovegen/render_symbolic.py` exposing:
   ```python
   SOUNDFONT_ROUTING = {          # from nb16, the validated routing
       "chop":  "Unison.SF2",         # supersaw pop chops
       "bass":  "GeneralUser.sf2",
       "drums": "909_drum_sf.sf2",
       "keys":  "GeneralUser.sf2",
       "salsa_piano": "GeneralUser.sf2",
   }
   def render_bar(genre, tier, tempo_bpm, bar_index, seed=None) -> np.ndarray  # stereo bar of audio
   def render_session(tier_sequence, tempo_sequence, genre) -> np.ndarray      # concat of bars
   ```
2. Move `render_with_sf` (per-instrument SF2 rendering) + the stem-mix + pump/compress polish out
   of `nb16` and `mix_drums_louder.py` into this module. Single source of truth.
3. Fold in `symbolic_bed_proto.build_*` (bed voicings) and `symbolic_tiers_demo.drum_bar_tier`
   (drums) as the note-writers `render_bar` calls.
4. **Bake in the drum-level fix** the user asked for (drums up ~+6 dB, compressed) as the default mix.
5. Add a `SOUNDFONT_DIR` config + a `download_soundfonts()` helper (the nb16 downloader) so it works
   on Colab and locally.

**Exit test:** `render_session([3,3,4,4,5], [110]*5, "pop")` produces a coherent 5-bar clip with
supersaw chops + loud 909 drums, verified with `volumedetect` (mean_volume ≠ -inf).

---

## Phase 2 — Point the controller at the symbolic renderer

**Goal:** the closed loop drives tiers, not raw density; renders through Phase-1 module.

Concrete steps:
1. In `pd_controller.py`, confirm the inner-loop output is the **intensity tier (1–5)**, not raw
   drum density. (Tiers are monotonic → PD sign-stable; this was the locked decision.) Rename/clamp
   the output to `tier ∈ {1..5}` if it still emits continuous density.
2. Keep tempo + loudness as the continuous fine-trims layered on top of the discrete tier.
3. Replace the render call inside `session_render.py` so each bar does:
   ```python
   tier, tempo = controller.step(setpoint[b], hr_measured[b])
   audio_bar   = render_symbolic.render_bar(genre, tier, tempo, b)
   ```
   (Delete / archive the old neural/hybrid render path from the loop — keep it in the repo for the
   ablation table, but it's no longer the default.)
4. **Keep groove/syncopation FIXED per tier** (inverted-U, non-monotonic — can't track a setpoint).
   Only tier/tempo/loudness move with HR. This preserves the monotonic control guarantee.

**Exit test:** a scripted HR setpoint ramp (up-reg then down-reg) produces a tier sequence that
tracks it monotonically, rendered as one continuous audio file. Reuse the cascade up/down-reg
timeseries plots you already have (`cascade_upreg_timeseries`, `cascade_downreg_timeseries`) to
show tracking.

---

## Phase 3 — Wire the feature→symbolic adapter + VARIETY (personalization from user songs)

**NEW (2026-08-04):** non-repetition is now built. `pop_variety_lib.py` provides a per-genre
**library** (multiple progressions, arp/riff motifs, stab grids, tier arcs) + a **procedural
generator** (`make_pop_song(profile, character, seed_salt)`) that transposes, jitters tempo,
picks/rotates the arp motif, and varies grid/ghost density from a seed derived from the track
profile. `render_variety.py` turns a spec into audio. Result: each user-suggested song yields
a DIFFERENT matching pop song, and re-runs with a new salt give fresh variations. r&b/latin
libraries still TODO (same pattern). Character (pad_pluck / plucky_keys, user-chosen) passes
through as a program that the Colab soundfont routing maps to a modern patch.

**NEW (2026-08-04) ANY-GENRE architecture:** generalized so the system handles *any* genre
the user provides, not a fixed set. Three modules:
  - `genre_agnostic_core.py` -- derives ALL params (progression pool, stab grid, arp shape,
    transpose, tier arc, drum_gain) from the audio-FEATURE profile alone. Every mapping is a
    documented, monotonic function of a feature (brightness->register, syncopation->grid
    busyness, harmonic/percussive ratio->arp activity + drum gain, onset density->tier arc,
    mode->major/minor prog pool). Works for afrobeat/bossa/drill/k-pop/anything because it
    uses real audio evidence, never a guessed genre name. Defensible for the paper.
  - `style_packs.py` -- curated OVERRIDES for pop/rnb/latin/calm (fuzzy-normalized registry,
    e.g. 'R&B'->rnb). A pack calls the core then patches genre-specific bits (rnb 7th chords +
    laid-back tiers, latin son-clave grid + drums forward, calm sparse/quiet/slow).
  - `generate_any_genre.py` -- SINGLE ENTRY POINT `make_song(profile, genre, character, salt)`:
    known genre -> pack, unknown -> generic fallback. Returns a spec render_variety can play.
    `salt` gives non-repetition. Also sets drum_genre (latin->salsa clave, else pop).
  Decision (user, 2026-08-04): unknown genres use the profile-driven GENERIC FALLBACK (not
  ask-user, not name-based lookup) -- robust, no hallucinated theory. Demos: pop (pack) +
  afrobeat/bossa (fallback) in groovegen_any_genre_demo.mp4, all balanced & audible.
  TODO: author rnb/latin/calm pack DETAILS more fully; genre-specific drum feels beyond salsa;
  fold make_song into nb16 so any-genre runs with the modern Colab timbre.

**NEW (2026-08-04) MULTI-ENGINE taxonomy + ROCK/METAL engine + coverage analysis:**
  AI council (Opus/GPT/Gemini) + soundfont research settled how far genre-agnostic can go.
  Key insight: genres are many but ACCOMPANIMENT IDIOMS are few. "Most people" = ~6 writing
  engines + ~8 sound sets (only 4 timbre-critical). Full analysis in
  `genre_coverage_feasibility_memo.md`; verified free SF2 URLs in `soundfont_research.md`.
  - Engine target (by tag share): STAB/COMP (have, ~37%) -> RIFF/POWER (built today, ~18%)
    -> SPARSE-TRAP (~7%) -> LOOP/SUSTAIN EDM (~5%) -> STRUM country (~10%) -> KEYS/JAZZ (cut first).
  - `rock_metal_engine.py` = RIFF/POWER engine: power dyads (root+5+oct, NO 3rd on distortion),
    palm-mute chug grid (tiers 1-5), gallop, unison bass, minor/Phrygian riff moves.
    `render_rock.py` renders it (GM prog 30 proxy locally). Demo: groovegen_rock_metal_engine.mp4.
  - `style_packs.py` now has ENGINE_ROUTES + engine_for(genre): rock/metal/punk/thrash route to
    the dedicated RIFF engine, NOT the STAB/COMP param packs (different idiom, different spec).
  - HONEST LIMITATION (unanimous council): SF2 distorted guitar is a PROXY, NOT study-grade.
    Real tone needs post-FluidSynth DSP: tanh soft-clip -> cabinet IR -> noise gate (~150 lines,
    `guitar_amp_dsp.py`, TODO). Until then, metal timbre = documented known limitation.
  - PAPER scope recommendation: 3 engines/4 packs (pop-funk + rock-riff + trap + EDM, ~60%),
    claim = controllability across idioms (per-bar tier-tracking error), NOT coverage.
  - PRODUCT build order (80/20): trap -> EDM -> rock+DSP -> country-strum -> keys/jazz.
    Trap = best ROI (808 = sine+glide) and a new structural archetype.
  - License flag: Arachno soundfont is NON-COMMERCIAL only -- do not bundle if GrooveGen ships.


**Goal:** a user's recommended song sets the *scene* (genre, starting tier, tempo, brightness),
then the controller takes over per bar. This is the "make our songs look like the ones they
suggested" behavior the user liked.

Concrete steps:
1. On session start, take the user's chosen track → `profile_from_songs.py` (52-feature extractor)
   → `symbolic_from_profile.map_profile(feat)` → `{genre, bpm, start_tier, transpose, ...}`.
2. Feed that as the controller's **initial condition** (scene): genre + start_tier + tempo. The
   controller then closed-loops from there.
3. Cache the profile so re-runs are deterministic (provenance CSV — still an open to-do).
4. **Guardrail:** feature→scene mapping is a once-per-session scene selector, NOT a per-bar control
   lever (genre-morph mid-session is confounded — locked decision). Adapter sets the start; the
   validated tier/tempo controller does the moment-to-moment work.

**Exit test:** feed 3 different track_features.csv rows → 3 sessions that start in the right genre
(r&b / pop / salsa) at a sensible tier, each then tracking the same HR setpoint.

---

## Phase 4 — Connect the experiment UI

**Goal:** `app_experiment.py` runs a full session on the validated pipeline, no code edits needed
by a participant/operator.

Concrete steps:
1. UI inputs → session config: (a) pick/confirm the user's anchor song, (b) show detected scene
   from Phase 3, (c) start/stop, (d) live HR-setpoint vs measured trace.
2. UI calls `session_render.render_session(...)` (now the symbolic path) and streams audio.
3. Surface the **tier** and **tempo** the controller is choosing per bar as a live readout — this
   is the demoable "system" artifact for the paper/talk.
4. Log everything to `experiment_trace.csv` (setpoint, measured, tier, tempo, genre, bar) for the
   analysis + figures.

**Exit test:** operator opens the UI, picks a song, hits start, and a full closed-loop session
plays with a live tier/tempo/HR readout and a complete trace CSV at the end.

---

## Sequencing & honest effort estimate

| Phase | Effort | Risk | Blocker if skipped |
|---|---|---|---|
| 1 — consolidate renderer | ~1 focused day | low (all code exists, just relocating) | everything downstream is unstable |
| 2 — controller → renderer | ~1 day | medium (tier clamp + loop swap) | no closed loop |
| 3 — feature adapter wire | ~half day | low (adapter demoed) | no personalization |
| 4 — UI wire | ~1 day | medium (streaming audio + live readout) | no demoable system |

**Recommended order is strictly 1→2→3→4.** Phase 1 is the keystone: once the renderer is one clean
function, 2–4 are just wiring. Do **not** start Phase 4 UI polish before Phase 1, or you'll wire the
UI to a moving target.

---

## What stays OUT of scope (deliberately, until after the paper)

- **Learned feature→(rhythm-template, articulation, voicing) mapping** — fine-tuning a pretrained
  symbolic model (MMM / Anticipatory) on user MIDI. This is the sharpened "future work" the user
  endorsed but chose to defer. Today's pop lesson refined it: the model should select **rhythm
  templates**, not just scalar parameters. File as the paper's Future Work section.
- **JASCO neural pop bed** — the spike notebook exists but is unrun; it's an alternative to the
  symbolic bed, not required for integration. Keep as an ablation option.
- **Training a generator from scratch** — rejected (data scale). Not revisiting.

---

## Immediate next actions (pick one)

1. **Build Phase 1 now** — I create `render_symbolic.py`, migrate the render/mix/routing code, and
   prove `render_session` end-to-end in the sandbox (GM patches) + leave the supersaw path for Colab.
2. **Run nb16 first** — you confirm on Colab that supersaw+909 actually fixes the pop *timbre* (rhythm
   is already fixed), then we lock the routing table before Phase 1 hardens it.
3. **Refresh the stale docs** (`COLAB_RUNBOOK.md`, `HOW_TO_RUN.md`) alongside Phase 1 so the runbook
   matches the new pipeline.

My recommendation: **do #2 then #1.** Confirm the timbre fix on Colab (5 min), so Phase 1 bakes in a
routing table you've actually heard and approved — rather than hardening a guess.
