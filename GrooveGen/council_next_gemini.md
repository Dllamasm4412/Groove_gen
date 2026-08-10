# Model: Gemini 3.1 Pro

## 1. Best next move RIGHT NOW
**Depth (integration).** Stop adding genres immediately. The core claim of your system/method paper is *per-bar closed-loop control*, not "a universal genre generator." You cannot write a paper or run an n=5–8 pilot without an end-to-end working system. Prove the control claim first. Breadth is a distraction that risks you ending up with a collection of loose scripts rather than a validated research artifact.

## 2. Minimum genre set
**Pop/RnB/Latin + Rock-proxy is entirely sufficient.** For an n=5–8 pilot, your goal is to show the *system* adapts to diverse anchor songs, not to perfectly satisfy every musical taste on earth. As long as you have 2–3 distinct stylistic categories to prove the feature→scene adapter maps correctly and the controller drives them monotonically, your methodology holds. Trap and EDM are explicitly "future work" for the discussion section. 

## 3. Integration plan critique
The 1→2→3→4 sequence is logically sound, but it misses a critical step. **The highest-risk hidden landmine is state management and timing (latency) across the closed loop.** When you connect the controller to the renderer (Phase 2), jitter or state desync will break the exact "per-bar" latency claim you are trying to make. 
*Sequence tweak:* Insert a **Phase 2.5: Headless Stress Test**. Run the closed loop purely in code (no UI, mock HR data) for hundreds of bars to verify timing precision, sign-stability, and monotonic tier transitions before you touch the UI.

## 4. Code consolidation
**Do not do a massive refactor.** Tidy-up work on 90 scripts is a procrastination trap. 
*Concrete strategy:* Create a single `groovegen/` directory. Move *only* the verified files needed for the final pipeline (the renderer, controller, feature adapter, genre agnostic core, existing style packs, and UI scaffold) into it. Dump the remaining ~75 diagnostic/one-off scripts into an `archive/` or `scratch/` folder and ignore them completely. Fix imports only for the core pipeline.

## 5. UI scope for the pilot
**An operator-only dashboard.** The minimum viable UI is a single screen for *you* (the operator). It needs:
1. Start/Stop session button.
2. Live readout/plot of Current HR vs. Target HR Setpoint.
3. Live readout of system state (Current Tier L1-L5, Tempo, Loudness).
4. Auto-saving of the trace CSV at session end.
Participant-facing UI beyond a blank screen or a basic prompt is a complete distraction. The paper's outcome relies entirely on the CSV trace to generate figures; the UI just needs to capture that CSV reliably.

## 6. What NOT to do in the next 2–3 weeks
* **Do NOT build Trap or EDM engines.**
* **Do NOT write the 150-line DSP chain for the Rock engine.** The GM proxy is fine for proving control.
* **Do NOT over-engineer the UI.** No participant-facing visualizations or heavy web frameworks.
* **Do NOT attempt an efficacy trial.** Stick strictly to the scripted HR setpoint tracking.
