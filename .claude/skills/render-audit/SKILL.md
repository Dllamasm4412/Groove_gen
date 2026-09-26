---
name: render-audit
description: Audit GrooveGen MIDI and audio rendering without modifying frozen assets or automatically playing audio.
---

# /render-audit

Purpose
- Audit music/rendering-impact changes for deterministic correctness and technical output quality signals.

When To Use
- Any change affecting generation, MIDI rendering, WAV rendering, soundfont use, mixing, player behavior, tempo handling, or crossfades.

Core Rules
- Preserve renders/frozen_v2/ and the 8-bar contract.
- Use deterministic seeds.
- Render only to isolated smoke/output directories.
- Do not overwrite canonical frozen outputs.
- Do not change Musyng_Kite.sf2 path, gain, sample rate, or renderer defaults unless explicitly requested.
- Distinguish render success from musical quality; quality requires human listening judgment.

Required Audit Steps
1. Inputs and scope
- List changed files that can affect render/audio behavior.
- Declare deterministic seed and exact render parameters.

2. Render smoke artifacts
- Write outputs to disposable path (example: groovegen_pilot/renders/smoke_audit/<timestamp>/).
- Keep each render short and deterministic.

3. Inspect generated MIDI/WAV properties
- Duration
- Tempo map (and abrupt changes)
- Note counts
- Instrument programs/channels
- Velocity range
- Empty tracks
- Clipping risk indicators (if measurable)

4. Playback command handoff
- Provide afplay commands for one WAV at a time.
- Do not auto-start playback.

5. Report
- Command list, artifact paths, measurements, pass/fail checks, limitations.

Output Template
- Scope
- Commands Run
- Artifact Paths
- MIDI/WAV Inspection Results
- afplay Commands (manual)
- Limitations / Human Listening Required

Example Invocation
/render-audit
Audit the output of this change for latin and hiphop tier 3. Render isolated WAV smoke artifacts, inspect duration/tempo/instruments, give me two afplay commands, and do not overwrite frozen renders.
