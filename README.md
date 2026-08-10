# GrooveGen

GrooveGen is a closed-loop system that generates a musical bed and steers it in real time from a listener's heart rate. A control loop reads the listener's HR, converts it to a normalized arousal value, compares it to a scripted reference trajectory, and adjusts the music to track that reference.

## Current milestone

M1: closed loop running end-to-end on live PPG, with clean 15-minute runs in each direction (up-reg and down-reg), zero deadline misses, and within-segment plan invariance holding.

M1 build order:
1. player.py — SoundDevicePlayer plus NullPlayer, dependency-injectable.
2. renderer.render_segment plus crossfade — one MIDI render and one FluidSynth call with equal-power downbeat-aligned crossfades.
3. Nested run_session — control once per segment while tracing once per bar.

## Handoff docs

- [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) — project overview, system description, and the current pilot plan.
- [AI_CONTINUATION_CONTEXT.md](AI_CONTINUATION_CONTEXT.md) — code interfaces, invariants, and development rules.
- [PROJECT_HISTORY_AND_DECISIONS.md](PROJECT_HISTORY_AND_DECISIONS.md) — chronology of design decisions and reversals.
- [VENUE_RECOMMENDATION.md](VENUE_RECOMMENDATION.md) — venue recommendation for the paper submission effort.

## Quickstart

Activate the virtual environment:

```bash
source ~/GrooveGen/.venv/bin/activate
```

Run the full regression gate set:

```bash
python groovegen_pilot/hr_trajectory.py
python groovegen_pilot/test_faults_fixed.py
python groovegen_project/groovegen/pd_controller.py
python groovegen_pilot/tier_mapping.py
python groovegen_pilot/scene.py
```

## Runtime targets

- Dev machine: MacBook Pro M5
- Pilot machine: Mac Studio M4 Max
- Sim/CI: either machine, using NullPlayer

## Locked constraints

- Contribution is system/method, not efficacy.
- No vocals, ever.
- No neural networks in the live control path; symbolic MIDI + FluidSynth only.
- The toy plant is fabricated and is for offline use only.
- The sensor is a PPG source, not Polar H10.
- Reuse the validated CascadeController unchanged.
