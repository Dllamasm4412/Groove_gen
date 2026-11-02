---
name: genre-integration
description: Safely inspect, plan, implement, and verify GrooveGen genre adapter and renderer registration changes.
---

# /genre-integration

Purpose
- Integrate or register genres into GrooveGen with minimal, deterministic patches.

When To Use
- Any change wiring genres into GENRE_CFG, generator registries, composer adapters, or segment renderer paths.

Hard Contract Facts
- Existing cell adapters accept:
  - (genre, tempo_bpm, density, duration_bars, seed)
- They return:
  - music21.stream.Score
- Renderer generator entries expect:
  - (tempo_bpm, duration_bars, seed, cfg, density)
- Renderer generator entries must return:
  - pretty_midi.PrettyMIDI
- Use a thin deterministic wrapper.
- Allowed conversion direction only:
  - music21 Score -> temporary MIDI -> pretty_midi
- Never round-trip pretty_midi through music21.
- Do not change frozen cells, frozen seed behavior, or the 8-bar library contract.

Required Workflow
1. Inspect before patching
- Confirm actual signatures in adapters and renderer.
- Identify exact registration sites (GENRE_CFG, _GENERATORS, renderer call path).

2. Plan first
- Provide a file-level minimal patch plan.
- Provide verification commands before any edits.

3. Implement minimally
- Add only required registration/wrapper code.
- Preserve existing defaults and deterministic seed handling.

4. Verify
- Compile changed files.
- Confirm expected GENRE_CFG key count and names.
- Confirm ladder cell count (if required by task).
- Render deterministic smoke artifacts to disposable output.

5. Report
- Show exact commands and outputs summary.
- State what was not tested.

Guardrails
- No architecture rewrites.
- No timing-altering conversions beyond Score -> temp MIDI -> pretty_midi.
- No writes into canonical frozen render directories during verification.

Example Invocation
/genre-integration
First inspect the actual adapter and renderer signatures. Then propose the minimal patch to register hiphop and rock. Do not modify any files until you show the file-level plan and verification commands.
