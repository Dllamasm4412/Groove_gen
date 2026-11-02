# GrooveGen pilot zero, release candidate `pilot-zero-v2c-rc2` (2026-10-07)

Engineering release candidate after the three live developer tests of RC1.
It is not the locked pilot release. Configuration, ladder, music, controller
gains, haptics and certification are those of RC1
(`RELEASE_pilot_zero_v2c_rc1.md`), except for the two fixes below.

## Identity

| Item | Value |
|---|---|
| Release-candidate code commit | `ca6ccaf040d56fdb37a6588300ab1f0ec0b3e6e9` (the tag `pilot-zero-v2c-rc2` is on the docs commit that adds this file; its code is identical) |
| Previous RC | `pilot-zero-v2c-rc1` (code `7eaff01`), unchanged |
| Python / FluidSynth | 3.12.13 / 2.6.0 |
| Soundfont | `soundfonts/Musyng_Kite.sf2`, sha256 `ed8c5a34c28b0fbbc805d6bbae74a169582c1881b57219972052e822c7be35f0` |
| Generator for live runs | `--generator v2c`, gen `v2a.3`; hiphop `v2b.1`, calm `v2c.calm.0`, lofi `v2c.lofi.0`, rnb `v2c.rnb.0`, pop `v2c.pop.0`, latin `v2c.latin.1` (runner default stays `bank`) |
| Stimulus seed | 1 |
| Ladder | `--ladder ear`, `energy_order_by_ear.json` sha256 `80672b02...` (unchanged); energy table `643b868f...` (unchanged) |
| Master headroom | active, -2.5 dB |
| Rock presentation | unchanged (drums x1.20; gain {+4, +3, +3, +1.5, 0} dB; -1 dBFS limiter) |

## Changes since RC1

1. `f1408ad` fix(tools): count only accepted HR polls (summary tool only).
2. `3d7319a` fix(v2): add local variety at ladder saturation. When the
   controller is stuck at the top rung pushing up, rotation chooses from the
   top rung and its two nearest cells below (`top_rotation_cells=2`: rock5,
   rock4, hiphop5) instead of replaying rock5. Test A held rock5 for 6
   segments. Normal moves, mid-ladder and bottom rotation, the ladder and the
   controller gains are unchanged.
3. `ca6ccaf` fix(session): honor requested fixed-session duration. Without
   `--phases`, the session now ends by music time. Music lasts between the
   requested length minus the first render (about 1-2 s) and the requested
   length plus one segment (at most 29.5 s on the live ladder; the last
   segment always plays to its end). Before, `--session-minutes 10` gave
   8.6-9.0 min. `--phases` is unchanged.

## Live engineering validation (RC1 code)

Tests A (music), B (music + haptic pacing) and C (music, phased up/down)
passed. The results are in `RELEASE_pilot_zero_v2c_rc1.md`. They are
engineering results only and say nothing about whether music or haptics
change HR.

## Verification at the RC2 commit

- Full `tests/`: 663 passed. The new tests cover the top stall (5 seeds, 45
  segments) and fixed-duration sessions at 65, 118 and 130 bpm and with mixed
  cells. The ladder, its step sizes, generator identity fixtures and the
  default `bank` path are pinned by existing tests, which all pass.
- Regression gates (hr_trajectory, test_faults_fixed, pd_controller,
  tier_mapping, scene) and the estimator link: all exit 0.
- Deterministic v2c simulations with `--ladder ear` and the synthetic plant
  (engineering only); each was run twice and gave byte-identical traces and
  audio:
  - `--session-minutes 10`: 35 segments, 10.14 min of music (was 30 segments,
    about 8.6 min).
  - Top hold (`--phases 'up:40:10'`): after reaching rock5 it plays rock5,
    hiphop5, rock4 repeatedly (at most 3 rock5 in a row, at arrival); rotation
    jumps at most 2 rungs.
  - Test C's schedule (`up:10:5,down:-6:6`): the trace is identical to the
    pre-fix dry run, so behaviour below the top is unchanged.
  - All three: 0 direction violations, normal moves 1 rung, plan invariance
    holds, no visit-counter breaks, peak at most -2.06 dBFS with no
    full-scale samples.
- Timing, with nothing else running (`--sweep 3`, 81 renders): compose +
  render mean 0.85 s, p95 1.17 s, max 1.44 s against the 3.0 s lead.
  The concurrent simulations above showed up to 6 s only because six runs
  and the test suite shared the CPU.

## Known imperfections (future work, not blocking)

All RC1 items, plus:
- Test C's up phase: when the learned gain collapses mid-ladder, rotation
  fills most of the stall (9 of 16 segments) until the MPC asks to move again.
  This is designed behaviour; changing it would mean tuning the controller.
- The two recording-replay tests in `new_biofeedback` (pacer slew across a
  17 s pause; one raw 46.7 bpm window) still fail, as before RC1. Both were
  reviewed and classified as test gaps or known estimator imperfections.

## Live commands (unchanged from RC1)

Music only: estimator with `--no-haptics --publish-udp 127.0.0.1:5005`;
runner `--sf2 ../soundfonts/Musyng_Kite.sf2 --hr-source estimator --generator
v2c --ladder ear --stim-seed 1 --session-minutes 10` (now about 10 min of
music). With haptic pacing, add `--goal-udp 5006 --pace-max-seconds 720
--pace-invalid-window-s 60` to the estimator and `--haptic-pacing` to the
runner. Those two estimator settings need the developer's approval for each
run (DEVIATIONS.md). Afterwards: `summarize_session.py <session> --render`.
