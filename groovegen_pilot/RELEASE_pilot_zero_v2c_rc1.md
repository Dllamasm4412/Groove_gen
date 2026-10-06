# GrooveGen pilot zero, release candidate `pilot-zero-v2c-rc1` (2026-10-06)

Engineering release candidate for the first live developer run with stateful
v2c generation and the perceptual ladder. This is not the locked pilot release.

## Identity

| Item | Value |
|---|---|
| Release-candidate code commit | `7eaff01aabe433bc7def40b6d910d2ecefa8ea78` (the tag `pilot-zero-v2c-rc1` is on the docs commit that adds this file; its code is identical) |
| Branch | `v2-controlled-live-generation` |
| Python | 3.12.13 (`.venv/bin/python3.12`) |
| FluidSynth | 2.6.0 |
| Soundfont | `soundfonts/Musyng_Kite.sf2`, sha256 `ed8c5a34c28b0fbbc805d6bbae74a169582c1881b57219972052e822c7be35f0` (`groovegen_pilot/Musyng_Kite.sf2` is the same file) |
| Generator for the live run | `--generator v2c`: SessionComposer, gen `v2a.3`; development hiphop `v2b.1`, calm `v2c.calm.0`, lofi `v2c.lofi.0`, rnb `v2c.rnb.0`, pop `v2c.pop.0`, latin `v2c.latin.1`; rock has no policy. The runner default stays `bank` (byte-identical to before v2). |
| Stimulus seed | 1 (`--stim-seed`, the runner default) |
| Energy table | `energy_table_v1.json`, sha256 `643b868ff81f4fa92519f284c3abbb79ae5f6677e17a1a2063dc33d7f0270e72` (measured without the Rock presentation gain and at the reference level) |
| Ladder | `--ladder ear`, `energy_order_by_ear.json` sha256 `80672b0287e98bb9f8cd416e6c402c5b0a0ae8edfc767ad8ad19e44585062ffc` |

## Final ladder (27 live cells, frozen)

calm1, calm2, lofi1, hiphop1, lofi2, lofi3, hiphop2, latin1, rnb1, rock1, rnb2,
rnb3, latin2, rnb4, latin3, rock2, pop1, pop2, pop3, hiphop3, pop4, pop5,
hiphop4, rock3, hiphop5, rock4, rock5.

This is the minimum-change re-order of the measured ladder under the four blind
listening relations that replicated (lofi1 < hiphop1, rnb1 < rock1, hiphop3 <
pop4, hiphop4 < rock3). The u values are the measured ones. Tier caps: calm 2,
lofi 3, rnb 4, latin 3 (live override), hiphop / pop / rock 5. Initial cell
`lofi:3`.

## Controller configuration (run_pilot_zero defaults, `--ladder ear`)

LadderMPC: horizon 3, max_step_per_segment 1, dead_zone 1.5 bpm, w_error 1.0,
w_churn 0.01, arousal_mode `hr_primary`, RLS forget 0.97 (g prior 2.5, max 12
bpm), plant tau 60 s, dt 20 s, delay 1 segment, max_du_per_segment none.
Saturation rotation on: after 3 stuck segments, band 2 x noise_u = 0.0267 u,
rotation_no_repeat 2. A requested MPC move is never reversed by rotation
(2026-10-06). Target relaxation off. The target is baseline + 10 bpm (120 s
baseline), session 10 min. HR: estimator over UDP, 1 Hz polling, 10 s median,
stale HR -> `stale_hold`. Crossfade 0.25 bar, `tail_out`; render lead 3.0 s.

## Audio presentation

- Global master attenuation: active, `segment_renderer.MASTER_GAIN_DB = -2.5`
  dB on every rendered segment. It fixed the fluidsynth 16-bit clipping on
  hiphop:4-5. Energy measurement and certification use the reference level.
- Rock: guitar program 26 (rock_cell), drums x1.20 velocity, per-tier render
  gain {1: +4, 2: +3, 3: +3, 4: +1.5, 5: 0} dB via the render directive (float
  render, gain, then a -1 dBFS look-ahead limiter with a 20 ms window); the
  master attenuation follows the limiter.

## Verification at the RC commit

- Full `tests/`: 655 passed, on the working copy and again on a clean
  `git archive` export of `7eaff01` (with the soundfont linked in).
- Regression gates: hr_trajectory, test_faults_fixed, pd_controller,
  tier_mapping, scene all exit 0. Estimator link
  (`test_estimator_hr_source.py`): all passed.
- `new_biofeedback/test_haptic_pacer.py` and `test_stable_hr.py`: 24 passed and
  2 failed. Both failures are recording replays (`ppg_live_raw_20260928_122929`
  pacer slew; `ppg_live_raw_20260928_134855` one window at 46.7 bpm against a
  72.5 median). They fail identically on the previous committed code, so they
  are not introduced here. Haptics are off for this run.
- Deterministic v2c sessions with `--ladder ear` (`simulate_session_v2.py`; two
  runs give a byte-identical trace and WAV):
  - Scripted HR (does not respond to the music): 64 segments, plan invariance
    max nunique 1, 0 direction violations in 29 requested moves.
  - Synthetic plant HR (`--hr plant`, engineering only): 57 segments covering
    up and down movement, holds (7), high saturation (4 at rock5), low
    saturation (5 at calm1), 33 genre changes, all 27 cells, 23 revisits, 7
    rotations; 0 direction violations in 45 requested moves; max rung jump 1
    (MPC) and 3 (rotation); visit counters continuous; 0 development
    fallbacks; peak -2.06 dBFS, 0 full-scale samples; real compose + render
    max 2.50 s against the 3.0 s lead.
- Certification `--audio`: Latin (v2c.latin.1) has the same cell verdicts as
  before, with a pulse-clarity residual on latin:1-2. hiphop:4-5 and rock:4-5
  with the master active reproduce the energy table (max diff 0).

Synthetic HR results are not evidence of any effect on a listener.

## Known imperfections (future work, not blocking)

calm:1 / calm:2 are barely distinguishable (measured and by ear). The lofi and
rnb:1-3 tiers are measured nearly flat. Near-tie boundaries that were never
listened to: hiphop1/lofi2, rnb3/latin2, rnb4/latin3, hiphop5/rock4. The Rock
envelope certification issue and the latin:1-2 pulse-clarity residual remain.
A rotation pick can jump 4 rungs (rnb2 <-> latin3, inside the band). The music
is frozen; only blocking reliability or safety fixes are allowed.

## First live developer run (real PPG, 10 min, no haptics)

Find the XIAO port first: `ls /dev/cu.usbmodem*`.

Terminal 1 (estimator; owns the serial port, publishes HR, no haptics):

```
cd ~/Desktop/PhD/groove_gen_project/new_biofeedback
../.venv/bin/python3.12 ppg_live_estimator_adaptive_haptics_stable_hr.py --port /dev/cu.usbmodemXXXX --no-haptics --publish-udp 127.0.0.1:5005
```

Terminal 2 (GrooveGen; start once terminal 1 shows valid HR):

```
cd ~/Desktop/PhD/groove_gen_project/groovegen_pilot
../.venv/bin/python3.12 run_pilot_zero.py --sf2 ../soundfonts/Musyng_Kite.sf2 --hr-source estimator --generator v2c --ladder ear --stim-seed 1 --session-minutes 10 --subject-id daniel_rc1_live1
```

Do not pass `--haptic-pacing`. The session folder is printed at start
(`output_dir=...`): `renders/pilot_zero/daniel_rc1_live1_<timestamp>/`.

Afterwards:

```
cd ~/Desktop/PhD/groove_gen_project/groovegen_pilot
S=$(ls -d renders/pilot_zero/daniel_rc1_live1_* | tail -1)
../.venv/bin/python3.12 summarize_session.py "$S" --render --sf2 ../soundfonts/Musyng_Kite.sf2
```

Check in `session_summary.json`:
- `condition` is `music` (no haptic pulses sent);
- `config.ladder_source` is `ear` and `config.master_gain_db` is -2.5;
- `timing.queued_ahead_s` (min > 0, `segments_queued_ahead_le_0` = 0);
- `cells` / `control` (direction violations 0, rotation runs, max rung jump);
- `visit_state.visit_counter_breaks` is empty;
- `development.fallback_segments`;
- `audio_rebuilt` (composition mismatches 0, peak, full-scale samples);
- `hr` (fresh vs stale segments, stale_hold, `hr_polls` valid fraction).
