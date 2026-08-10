## Sensor identity

- Sensor make and model: TODO
- Connection method: TODO (BLE / USB / other)
- Firmware / SDK version if known: TODO

## Data stream

- Output stream contents: TODO (choose one and expand: IBI intervals in ms / smoothed BPM at N Hz / raw PPG waveform at N Hz / other)
- Update rate: TODO
- Fields consumed by HRSource: TODO (list the exact field names)
- Sample data snippet (first 5 lines of a raw capture): TODO

## Noise-floor SD measurement

- Date: TODO
- Machine used for measurement: TODO (MacBook Pro M5 / Mac Studio M4 Max)
- Conditions: 5 min seated quiet, headphones off, phone silenced
- Sample source: hr_bpm_smoothed logged at 1 Hz
- Measured SD: TODO BPM
- Decision on deadband: TODO (keep ±3 / widen to ±4 / widen to ±5 / widen smoothing window to N seconds)
- Rationale for decision: TODO

## Motion artifact behavior

- Observed artifact rate at rest: TODO
- Observed artifact rate during light gestures: TODO
- Recovery time after artifact: TODO
- Notes on sensor placement sensitivity: TODO

## Known failure modes

- TODO
- TODO
- TODO

## Runtime machine notes

- Dev machine (MacBook Pro M5):
  - Bluetooth adapter working: TODO (yes/no)
  - Python bleak permission granted: TODO
  - First-inspection date: TODO
  - Notes: TODO
- Pilot machine (Mac Studio M4 Max):
  - Bluetooth adapter working: TODO
  - Python bleak permission granted: TODO
  - First-inspection date: TODO
  - Notes: TODO

## BLE permission granted to

- TODO (name the exact binary that received the permission: VS Code / Terminal / iTerm / Python launcher / other)

## Alternative HR input modes for dev and demo

- ManualHRInput: keyboard-driven BPM value, thread-safe, duck-types HRSource. Use for debugging the music-generation pipeline independently of the sensor stack. Planned build: M0.5 milestone in Phase C-0 (see AI_CONTINUATION_CONTEXT.md and the current M1 plan).
- ReplaySource: replays a recorded PPG CSV into HRSource at real time. Use for reproducible dev runs. Planned build: same phase as ManualHRInput.
- Synthetic plant (existing, do not extend): the fabricated dual_lever_plant_step in the offline simulation path. Offline ablation only, never in the live path, never as evidence of human response. See PROJECT_HANDOFF.md §6 and AI_CONTINUATION_CONTEXT.md §0.

- Every trace row from any of these modes MUST have hr_source_type set to "manual", "replay", or "synthetic" respectively. Only hr_source_type == "ppg" rows are valid pilot data.
