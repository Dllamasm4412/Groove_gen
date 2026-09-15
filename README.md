# GrooveGen

GrooveGen is a real-time closed-loop physiological music control system.

The system reads live heart-rate signals from PPG, estimates current physiological state, chooses a genre and tier on an energy ladder, renders symbolic music to audio, and plays continuous crossfaded segments while logging trace rows for later analysis.

This repository is focused on system and method validation for pilot studies, not efficacy claims.

## What It Does

- Acquires heart-rate estimates from live serial PPG.
- Maps control state to a ladder of genre and tier cells.
- Renders symbolic segments through FluidSynth and a fixed SoundFont.
- Crossfades adjacent segments with equal-power overlap.
- Emits structured per-bar traces for reproducibility and post-hoc analysis.
- Supports headless operation through NullPlayer for simulation and debugging.

## Repository Layout

- [groovegen_pilot](groovegen_pilot): active pilot runtime, rendering pipeline, session runners, and control integration.
- [groovegen_project](groovegen_project): broader project code and historical controller work.
- [GrooveGen](GrooveGen): research notes, architecture briefs, and planning artifacts.
- [song_excerpts](song_excerpts): reference materials.
- [soundfonts](soundfonts): SoundFont assets.

## Core Runtime Pipeline

Within [groovegen_pilot](groovegen_pilot), the closed-loop stack is:

1. Heart-rate source
- [serial_ppg_source.py](groovegen_pilot/serial_ppg_source.py)

2. Ladder and controller
- [ladder.py](groovegen_pilot/ladder.py)
- [control.py](groovegen_pilot/control.py)

3. Symbolic renderer
- [segment_renderer.py](groovegen_pilot/segment_renderer.py)

4. Crossfade and playback
- [crossfade.py](groovegen_pilot/crossfade.py)
- [player.py](groovegen_pilot/player.py)
- [renderer_to_player.py](groovegen_pilot/renderer_to_player.py)

5. Session orchestration and tracing
- [run_session_v2.py](groovegen_pilot/run_session_v2.py)

## Frozen Library Workflow

The deterministic library freeze pipeline lives in:

- [freeze_library.py](groovegen_pilot/freeze_library.py)
- [composer/frozen_seeds.py](groovegen_pilot/composer/frozen_seeds.py)

Current frozen family set includes calm, lofi, latin, rock, hiphop, pop, and rnb.

Typical freeze command from [groovegen_pilot](groovegen_pilot):

python freeze_library.py --out renders/frozen_v2

## Gate Personalization Workflow

The pre-session listening gate is implemented in:

- [gate_widget/app.py](groovegen_pilot/gate_widget/app.py)
- [gate_widget/scoring.py](groovegen_pilot/gate_widget/scoring.py)

It collects pairwise preferences and vetoes, computes Bradley-Terry scores, and writes a profile JSON consumed by session tooling.

## Setup

From repository root:

1. Activate the virtual environment.
source .venv/bin/activate

2. Confirm FluidSynth is installed and on path.
fluidsynth --version

3. Ensure a SoundFont exists and pass it explicitly to runtime scripts.

## Pilot Entry Point

Subject-zero minimum viable driver:

- [run_pilot_zero.py](groovegen_pilot/run_pilot_zero.py)

Example run from [groovegen_pilot](groovegen_pilot):

python run_pilot_zero.py --sf2 Musyng_Kite.sf2 --port /dev/cu.usbmodem2023101

## Regression Gates

Run these after non-trivial changes:

python groovegen_pilot/hr_trajectory.py
python groovegen_pilot/test_faults_fixed.py
python groovegen_project/groovegen/pd_controller.py
python groovegen_pilot/tier_mapping.py
python groovegen_pilot/scene.py

## Key Constraints

- System framing is method and infrastructure, not efficacy claims.
- No vocals.
- No neural-network generators in the live control path.
- Live path remains symbolic MIDI plus FluidSynth rendering.
- Toy plant components are for simulation and ablation only, not human claims.
- Sensor truth source is PPG.
- Trace schema evolves additively.

## Essential Project Docs

- [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md)
- [AI_CONTINUATION_CONTEXT.md](AI_CONTINUATION_CONTEXT.md)
- [PROJECT_HISTORY_AND_DECISIONS.md](PROJECT_HISTORY_AND_DECISIONS.md)
- [SENSOR_NOTES.md](SENSOR_NOTES.md)
