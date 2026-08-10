# GrooveGen tool-selection decision — shared context for subagents

## The system (what the tool must serve)
GrooveGen is a closed-loop music system (PhD research, Daniel Llamas, CU Boulder; TEI 2027 system/method paper).
- A controller adjusts DRUM DENSITY **bar-by-bar** (integer 3-20) in real time to track a scripted heart-rate setpoint. Per-bar controllability is THE core contribution.
- Two-timescale architecture: a SLOW "bed" (harmony/melody/bass, fixed per segment) + FAST synthetic drums (varied every bar by the controller).
- Genres needed: latin/salsa, pop, r&b/soul, calm. **Genre identity MUST live in the melodic/harmonic bed** (salsa must sound harmonically like salsa), per the user's hard constraint.
- HARD RULES: instrumental only, NO vocals anywhere. Runs on Google Colab T4 GPU, ONE session at a time. Must be reproducible for a research experiment (stable tempo, lockable grid).

## The problem that triggered this decision
MusicGen (facebook/musicgen-small via HF transformers) was used to generate the BEDS. Measured percussive/harmonic RMS ratio (residual after librosa.effects.harmonic margin=3.0; higher = more percussion):
- Original drum-prompted beds: 0.54-0.88 (percussion-DOMINATED).
- Rewritten "no drums / melodic" prompts (just tested): calm 0.26 (clean), salsa 0.42, r&b 0.71, pop 1.26-3.06 (WORSE).
Conclusion so far: MusicGen cannot separate rhythm from percussion for rhythmic genres; drums are baked in and inseparable. HPSS and Demucs both FAILED to strip drums without destroying melody (melody corr dropped to 0.30-0.60; drums were 44-59% of signal energy).

## The decision
Should GrooveGen KEEP MusicGen for beds, or switch to another approach? The user explicitly asked whether going SYMBOLIC (MIDI) or another tool would be better. Evaluate honestly for THIS system's needs (per-bar drum control + genre-in-the-melody + Colab + reproducibility + no vocals + TEI deadline already passed July 31 2026, so this is now iterating toward a stronger paper, not a same-day scramble).
