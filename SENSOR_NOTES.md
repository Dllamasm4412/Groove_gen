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
- Beat doubling despite the 3 Hz band (2026-09-24 22:21, GrooveGen L1 run, 19.5 min): 82 of 1164 one-second HR windows read 124-158 bpm (1.8-2.5x the ~62 bpm running median) in 12 episodes of 1-13 s, all from minute 6 onward; alternating strong/weak peaks (prominence ratio 0.38 vs 0.81 normal), no sampling gaps, raw SD unchanged (no gross motion). The ±30% IBI screen is centred on the window's own median, so it cannot catch doubling once most peaks are doubled. The EMA and GrooveGen's segment median passed them through (8/42 segments at 76-134 bpm; RLS g_hat 2.9 -> 11.9). Fixed by a beat-doubling gate in estimate_stable_hr (HR_MAX_DOUBLE_PERIOD_GAIN: reject when the cardiac-band autocorrelation is higher at 2x the detected beat interval than at 1x by > 0.2); the window is marked invalid, not clamped. Replay (replay_stable_hr.py, test_stable_hr.py): 22:21 valid 0.935 -> 0.865, median 63.8 -> 63.5, max 158 -> 71; the one ~2x window in 18:53:57 also removed; the other 10 recordings unchanged; time-compressed to ~110-122 bpm, 1 window removed across 12 recordings. Limitation: two near-equal peaks per beat can be indistinguishable from true 2x HR (synthetic case passes the gate); no reference HR was recorded for this run. The developer reports the Apple Watch usually agrees with this sensor, except large values after slight movement and after a long while, consistent with this run.
- No absolute signal-quality floor (offline, 2026-09-25): the HR peak screen is relative (prominence 0.45 x band SD), so band-passed white noise of SD 1 count gave a valid HR of 92-143 bpm in 4 of 5 seeds; a flat signal is rejected. Finger-off or loosely seated noise could therefore publish plausible-looking HR. Not changed yet; `ppg_hr_<stamp>.csv` now logs `period_ac` (autocorrelation at the beat interval) and `pulse_sd` (cardiac-band SD, counts) per update so a quality floor can be set from real data. Offline separation: 1821 valid windows from the 12 recordings had period_ac p1 0.42 / p5 0.69 and pulse_sd p1 61 / median 471 counts; 396 of 600 white-noise windows (SD 1-20 counts) passed as valid, with period_ac <= 0.29 and pulse_sd <= 9. No real finger-off recording exists yet to confirm. Floor added the same day (HR_MIN_PERIOD_AC 0.3, HR_MIN_PULSE_SD 20 counts; reasons `aperiodic`, `weak_pulse`): noise windows passing as valid fell to 0.3% white / 0.7% pink / 2% brown; real windows lost 7/1823 at rest (all within 1.1x of the median) and 12/1146 time-compressed to ~100 bpm. Not yet run live.
- Haptic motors are powered from the XIAO (developer, 2026-09-24). In the 19:15 pacing run each HB adds a ~+200 count step to raw PPG at +10-40 ms (D9) and +150-180 ms (D7), flat while the motor is on (likely supply/ground coupling). Treat haptic-on PPG as contaminated until the motor supply is separated.
- Doubled beats at moderately raised HR (live L1b attempt, 2026-09-25 11:28, right after cycling, HR ~80, no haptics): the diastolic wave was counted as a beat in 76 of 101 updates (detected ~157 bpm; waveform period ~78 bpm). The doubling gate rejected them correctly, but so few valid updates remained that run_pilot_zero aborted the baseline (HR not fresh > 5 s). Fix (offline): a doubled window is re-detected with a minimum peak spacing of 0.75 x the doubled interval and accepted (`ok_undoubled`) only if it passes both gates; tried only when autocorr at the detected interval is < -0.1 (real doubled windows <= -0.24; one false recovery at 1.9x replay, HR halved, had +0.04). Replay: that run 16% -> 91% valid, median 81.6, p5-p95 74.6-85.7, longest invalid run 2 s; the L1 22:21 run 86.5% -> 93.5% (81 recovered, 1.02-1.22x median); the other 11 recordings unchanged at 1x/1.5x/1.9x. Limit: a diastolic wave at exactly half the period with the same shape as the systolic makes the waveform truly periodic at 2x; no check here can tell (synthetic only; not seen in real data). No Apple Watch reference was taken for this run; not yet run live.
- Haptic motors weak / dead (2026-09-28): after the 11:07 estimator run (71 HB sent and logged) one motor was silent and the other faint, then neither moved on LEFT/RIGHT commands. Cause: a loose wire (developer). Found with the motor-only sketch `new_biofeedback/xiao_haptic_motor_test` (D9, D7, both at 500 ms, LED mirrors the pins). `sent=1` in the haptic events CSV only means the command reached the serial port, not that a motor moved. Firmware re-flashed for the next run: `xiao_ppg_haptic_lub_dub_bridge`.
- Undoubling can halve a true HR (replay, 2026-09-28): in the 13:48 recording one `ok_undoubled` window read 46.7 bpm while stable HR was 72.5 (1 of 517 valid windows); `test_stable_hr.py` replay fails on it with both HEAD and current code. The stable HR and the runner's 10 s median absorb a single window; not fixed yet.
- Pacing did not resume after an aborted runner (2026-09-28 13:48 and 14:26 estimators): a runner that aborted in baseline sent "stop", which disabled pacing for the rest of that estimator process. Fixed: a stop now ends only that pacer and the next goal arms a fresh one; the runner baseline pauses instead of aborting and prints "ADJUST THE PPG SENSOR" while no valid HR arrives.

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
