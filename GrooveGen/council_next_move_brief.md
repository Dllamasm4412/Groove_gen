# Council brief: GrooveGen — best next move + full integration plan

You are advising Daniel Llamas, a PhD student (Cognitive Science / HCI, CU Boulder) building **GrooveGen**, a real-time adaptive music system for a biofeedback study. He values HONEST TECHNICAL PUSHBACK over agreement. Give a clear recommendation and say what you'd NOT do.

## The contribution (LOCKED — do not re-litigate)
- **System/METHOD paper**, not an efficacy trial. Claim = **per-bar closed-loop control of a symbolic music "bed"**: a PD/cascade controller adjusts musical INTENSITY TIERS (L1–L5, monotonic) + tempo/loudness fine-trims each bar to track a HEART-RATE setpoint. n≈5–8 pilot.
- Bed = SYMBOLIC (MIDI → FluidSynth + free SF2), NOT neural audio. Neural audio (MusicGen/JASCO) is rejected because it breaks per-bar latency/control = the contribution.
- NO VOCALS anywhere. HR = scripted setpoint the controller TRACKS (not an efficacy claim).
- Runs on **Google Colab, T4 GPU, ONE session at a time**, Python 3.12.

## What EXISTS today (verified this session)
- **Renderer:** `symbolic_bed_proto.render_midi()` (FluidSynth + polish), `symbolic_tiers_demo.drum_bar_tier()` (tier-based drums; pop + salsa feels).
- **Controller:** `pd_controller.py` (CascadeController) — validated in sim (tracks setpoint, sign-stable).
- **Feature→scene adapter:** `profile_from_songs.py` (52-feature extractor) + `symbolic_from_profile.map_profile()` — maps a user's anchor song to {genre, bpm, start_tier, transpose,...}. Demoed, not wired into the live loop.
- **Genre system (built this session):** `genre_agnostic_core.py` (derives all params from audio features — works for ANY genre), `style_packs.py` (curated packs: pop/rnb/latin/calm + rock ENGINE_ROUTES), `generate_any_genre.make_song()` (single entry point), `rock_metal_engine.py` (RIFF/POWER engine — power chords, palm-mute chugs), `pop_variety_lib.py` + `render_variety.py` (non-repetition).
- **UI:** `app_experiment.py` / `groovegen_ui_app_staged.py` (experiment UI scaffold — NOT wired to the validated pipeline yet), `session_render.py`.
- **Notebooks:** ABC_full_pipeline, A_setup_and_experiment_ui, BC_generate_and_closed_loop, 15_closed_loop_hr_audio, nb16_supersaw_pop, LIB_build_beds.
- **Genre engines status:** STAB/COMP (pop/funk/r&b/latin) = done. RIFF/POWER (rock/metal) = writing engine done, timbre is a GM PROXY (needs a ~150-line waveshaper+cabinet-IR+gate DSP chain to be study-grade). Trap + EDM engines NOT built.
- **CODE HEALTH ISSUE:** ~90 loose scripts in workspace root vs a cleaner `groovegen_project/groovegen/` package. Lots of one-off diag/build scripts. The "real" pipeline is partly in root, partly in the package — NOT yet one clean importable path.

## Existing 4-phase roadmap (already written)
- Phase 1: consolidate renderer behind ONE interface (~1 day, low risk) — KEYSTONE.
- Phase 2: point controller at the symbolic renderer, real closed loop (~1 day, medium).
- Phase 3: wire feature→scene adapter as session initial-condition (~half day, low).
- Phase 4: wire experiment UI to the validated pipeline w/ live tier/tempo/HR readout + trace CSV (~1 day, medium).

## Two open threads competing for "next"
- **(A) BREADTH:** build more genre engines (council previously said trap→EDM before rock; rock timbre needs DSP).
- **(B) DEPTH/INTEGRATION:** stop adding genres, consolidate the scattered code into ONE working closed-loop system with the UI, so there's an actual runnable artifact for the paper/IRB/pilot.

## QUESTIONS — answer each explicitly
1. **Best next move RIGHT NOW** — breadth (more engines) or depth (integrate what exists)? Be decisive and justify against the paper's actual claim and the n≈5–8 pilot timeline.
2. **Minimum genre set** the integrated system must ship with to be defensible for the pilot. Is pop + rock-proxy enough, or must trap/EDM land first?
3. **Integration plan critique:** is the 1→2→3→4 order right? What's the highest-risk hidden landmine in going from "scattered scripts" to "one runnable UI-driven closed-loop system"? What would you sequence differently?
4. **Code consolidation:** how aggressively to refactor the ~90 loose scripts now vs. after the pilot? Concrete strategy.
5. **UI scope for the pilot:** what is the MINIMUM UI that lets an operator run a participant session + produce the trace CSV/figures? What UI work is a distraction from the paper?
6. **What NOT to do** in the next 2–3 weeks.

Answer concisely but concretely. Prefix the file with your model name.
