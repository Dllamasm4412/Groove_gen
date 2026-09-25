## Sensor identity

- Sensor make and model: DFRobot analog PPG on a Seeed XIAO M0 (SAMD21), PPG signal on A10; USB serial number 3512D2DF5030524E572E3120FF150833 (confirmed 2026-09-24)
- Connection method: USB serial, 115200 baud. Enumerates as /dev/cu.usbmodem113101 in the current socket; the name follows the USB socket, not the board (older docs cite usbmodem2023101 and tty.usbmodem11201). Run `ls /dev/cu.usbmodem*` before each session.
- Firmware / SDK version if known: `new_biofeedback/xiao_ppg_haptic_lub_dub_bridge` (also accepts haptic commands on D9/D7). Both XIAO firmwares emit the identical stream, so the flashed firmware cannot be identified from the data.

## Data stream

- Output stream contents: raw PPG waveform at 100 Hz, 12-bit ADC (0–4095)
- Update rate: 100 Hz (confirmed from time_ms deltas, 2026-09-24)
- Fields consumed by HRSource: `time_ms,raw_ppg,clipped` (SerialPPGSource requires exactly 3 fields)
- Sample data snippet (first 5 lines of a raw capture): 62451,440,0 / 62461,437,0 / 62471,456,0

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

- Poor finger seating (2026-09-24, first Stage 0 attempt): raw range only ~418–484, SerialPPGSource HR swung 62→105 bpm within seconds, then 6 consecutive quality failures aborted the baseline ("HR stream not fresh"). Re-seated re-run: 100% fresh, SD 0.4 bpm.
- SerialPPGSource does not log raw samples, so a quality failure cannot be diagnosed after the fact.
- Dicrotic double peaks (2026-09-24 18:23, estimator run): strong unclipped signal (raw ~2000–3400) but the 0.5–5 Hz band passed the diastolic wave, giving alternating 0.33/0.67 s IBIs; HR valid 14/39, zero HB sent. Fixed by CARDIAC_BAND = (0.5, 3.0) in the estimator (replay: 39/39 valid, other recordings unchanged).
- Peak-top clipping after warm-up (2026-09-24 18:31): pulse amplitude grew over ~40 s until each beat touched 4095 for 10–30 ms; the all-or-nothing clip gate invalidated every 8 s window and HB stopped. Estimator HR/beat gates now tolerate rail runs <= 100 ms (MAX_CLIP_RUN_S; raised from 50 ms after the 18:51/18:53 runs showed 60–100 ms tops, HR valid 26/129 and 17/62); respiration gate stays strict. Lighter finger pressure also avoids it. The resting DC level is ~2190 counts, so strong pulses reach 4095.
- Clipping accuracy check (offline, 2026-09-24): clean 18:23 recording, peaks artificially clipped, time-compressed to ~95 and ~130 bpm. For windows that passed, median |window HR error| was 0.00 bpm; max 1.2 bpm at rest, 1.5 bpm at 95 bpm, 2.8 bpm at 130 bpm with the top 8–10% cut. Flat tops get shorter as HR rises (130 bpm with 10% cut: 50–70 ms), so the 100 ms limit does not block higher HR. When clipping is heavy (rest, top 10% cut), extract_pulses' own IBI screens reject most windows (18% valid) rather than returning bad HR.

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
