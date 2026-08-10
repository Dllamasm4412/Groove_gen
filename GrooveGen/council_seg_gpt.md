# GrooveGen segment-control redesign — control/signal-processing review

## Executive position

Use a **multirate supervisory architecture**, closest to Option A but not exactly as stated:

1. A fast **measurement/planner process** runs during a segment. It reads and quality-checks HR, computes a robust HR estimate, updates the time-based reference, and may run the existing per-bar controller as a *shadow candidate generator*.
2. A **segment supervisor** makes one decision for the next segment, applies deadband, persistence, actuator priority, and rate limits, then commits a complete immutable plan.
3. The renderer generates that plan into a second buffer while the current buffer plays.
4. Playback applies zero-order hold: genre, tempo, and tier remain fixed for the whole segment, except for a logged crossfade interval.

This meets the comfort requirement and preserves useful validated code, but it is important not to overstate preservation. Once its outputs are withheld until a segment boundary, the old per-bar loop is no longer a live inner feedback loop. It is a **shadow planner inside a segment-rate closed loop**. Its old stability/convergence demonstration does not automatically validate the new multirate system.

## 1. Architecture choice

### Recommendation: supervised A, not pure A/B/C

**Option C is out.** A tempo glide violates the explicit “song fixed per segment” requirement and introduces another poorly isolated treatment dimension.

**Pure Option B is tempting but discards too much working machinery.** It gives the cleanest runtime story, but would throw away the density controller, tier mapping, and existing trace path before there is evidence that they are unusable.

**Plain Option A is also not control-theoretically honest.** Calling `CascadeController.step()` repeatedly while its candidate commands are not applied makes its saturation counters fictitious: the controller internally believes density/tempo changed the plant, while the listener is still hearing the frozen segment. Likewise, calling it only once per 30–60 s boundary changes its sample time by roughly an order of magnitude while `dt` and gains remain per-call quantities. Neither use preserves the validated closed-loop behavior.

I recommend a **segment supervisor around a shadow version of the existing planner**:

- During segment \(j\), retain the actual applied plan \(u_j=(g_j,T_j,L_j)\) unchanged.
- Continue reading HR at sensor cadence and compute one robust estimate per musical bar or fixed analysis window.
- The existing density PD and `TierMapper` may produce candidate fine-actuator values. Do not expose them to audio.
- At a pre-generation commit point, the supervisor decides \(u_{j+1}\) from the signed HR-trajectory error and candidate history, then enforces:
  - at most one intensity tier per segment;
  - at most about 4 musical BPM per 45 s segment initially;
  - at most one genre rung per transition;
  - one actuator class at a time, with genre last.
- Freeze \(u_{j+1}\), render it asynchronously, and apply it only at the next transition.

This preserves the ear-validated renderer and density-to-tier machinery while making the paper's live control law accurately segment-rate. The old `CascadeController` should not remain the authority for genre direction: `_density_saturated()` and `_tempo_saturated()` choose direction from whether `setpoint < 0.5`, not from the sign of `setpoint - measurement`. That is wrong for a moving trajectory. A setpoint of 0.6 with measurement 0.8 requires calming, but the present code tests the “exciting” rail. The segment supervisor must use the signed error.

There are two other concrete inconsistencies to fix:

- The requested ladder is `["calm", "r&b", "pop", "latin"]`, but `GENRE_ENERGY_ORDER` currently omits `"calm"`. The renderer supports calm, while `GENRE_EQUILIBRIUM_BAND` does not.
- `scene.py` explicitly calls genre morphing a “locked-out confound,” which contradicts the new requirement. The method and documentation must choose one position. For this redesign, genre becomes a logged, rate-limited actuator rather than a session-only scene variable.

For a clean METHOD paper, describe the architecture as **multirate sampled-data control with segment-wise zero-order-hold actuation, physiological reference shaping, supervisory hysteresis, and double-buffered rendering**. Do not call the shadow per-bar planner a validated inner closed loop.

## 2. HR-trajectory setpoint law

### Use a time-based slew-rate-limited ramp

Let \(\hat h_0\) be the robust baseline HR estimate, \(h_g\) the requested terminal HR, and \(\rho=6\) BPM/min \(=0.1\) BPM/s. Define the reference recursively using actual monotonic elapsed time:

\[
r_k=r_{k-1}+\operatorname{clip}\!\left(h_g-r_{k-1},-\rho\Delta t_k,+\rho\Delta t_k\right),
\qquad r_0=\hat h_0 .
\]

Equivalently, for a fixed goal this is a straight ramp from the baseline that stops at the goal. It must **not** be re-anchored to measured HR every segment; doing that can conceal failure and make the target drift with the plant.

Compute the control error in HR units first:

\[
e_k=r_k-\hat h_k.
\]

Then convert the shaped HR reference to the locked arousal framing:

\[
a_{r,k}=\operatorname{clip}\left(
\frac{r_k-h_{\mathrm{rest}}}{h_{\max}-h_{\mathrm{rest}}},0,1\right).
\]

The ±3 BPM tolerance should remain in HR units because it is interpretable and invariant to the calibration span. The controller can still log and use the equivalent arousal reference/error after mapping.

This is preferable to an exponential approach. An exponential has a goal-dependent initial slope unless its time constant is recomputed, and its long tail makes “arrival” arbitrary. A rate limiter states exactly what the researcher asked for and is auditable under variable segment lengths. I would not use adaptive or model-predictive control in this pilot: no subject-specific music-to-HR dynamics have been identified, the categorical genre actuator has unknown and delayed effects, and one session is insufficient to fit and validate a predictive model without leakage.

Strong pushback: **6 BPM/min is a reference slew rate, not a promised physiological rate.** Music cannot command HR slope directly. From 120 to 75 BPM, the reference takes 7.5 minutes to reach the goal, or about 7 minutes to enter the ±3 BPM terminal band. A shorter protocol cannot honestly demonstrate completion. The paper should say “tracks a reference shaped at 6 BPM/min,” never “reduces HR at 6 BPM/min.”

## 3. Deadband, genre steps, and segment cadence

Use a Schmitt deadband plus signed persistence, not a single ±3 threshold:

- Enter an “action required” state when \(|e_k|>3\) BPM.
- Return to “hold” when \(|e_k|<2\) BPM.
- In the 2–3 BPM region, retain the previous state but do not escalate a coarse actuator.
- Reset persistence on invalid HR, sign reversal, or re-entry into the inner band.

At each segment decision, estimate HR robustly from a recent valid window, initially the median of the last 15–20 s, and reject a decision if signal quality or sample coverage is inadequate. Do not use one instantaneous Polar reading.

Initial action policy:

1. After **one valid segment** outside 3 BPM, move the fine actuator by at most one tier in the needed direction.
2. If error remains same-sign outside 3 BPM and the fine actuator is at its permitted limit, change tempo by at most 4 BPM for the next 45 s segment.
3. Step genre by one rung only after **two consecutive valid segment decisions** with same-sign out-of-band error and finer actuators demonstrably insufficient.
4. After a genre step, impose a one-segment cooldown and reset the genre persistence counter.
5. Require stronger evidence for reversal: opposite-sign error beyond about 4.5 BPM for two consecutive decisions.

For \(e_k<0\), measured HR is above trajectory, so command lower tier/tempo/genre rung. For \(e_k>0\), command upward. The actuator direction must never be inferred from whether the normalized setpoint is above or below 0.5.

Two consecutive 45 s segments already mean roughly 90 s of evidence. Requiring three would make genre response too sluggish for a typical pilot. Conversely, allowing one noisy segment to switch genre invites a two-segment limit cycle. The combination of a 3/2 BPM Schmitt band, same-sign persistence, one-rung rate limit, and post-change cooldown is the minimum credible anti-chatter design.

These actuator limits constrain **music command motion**, not physiological motion. At 45 s cadence, 4 musical BPM/segment is about 5.3 musical BPM/min, one tier/segment is 1.33 tiers/min, and one genre rung/segment is 1.33 rungs/min before persistence/cooldown. Those values should be tuned by listening and timing tests, not by claiming physiological optimality.

For the first protocol, use a fixed nominal **45 s segment**, phrase-quantized as described below. Mixing arbitrary 30–60 s durations changes control delay, persistence time, and exposure dose, weakening both tuning and interpretation.

## 4. Pre-generation and crossfade

### Scheduling

Use two buffers: `active` and `next`.

1. Pre-render segment 0 before playback.
2. Start segment \(j\).
3. During its first 15–20 s, collect valid HR and update the reference.
4. At a logged commit time, decide and freeze plan \(u_{j+1}\).
5. Render \(u_{j+1}\) on a worker thread/process into the `next` buffer.
6. Validate sample rate, channel count, duration, peak, and nonempty output.
7. At the scheduled phrase boundary, crossfade `active` to `next` and swap buffers.
8. If `next` is not ready, do not block or insert silence. Repeat/extend the current progression or use a pre-rendered safe fallback, and log the underrun.

The current `run_session()` is an offline render loop, not a real-time playback engine: it generates chunks serially, never sleeps to a playback clock, and writes one WAV at the end. Its `deadline_miss` is therefore only a render-budget comparison. Real double-buffering requires an audio callback/stream plus asynchronous generation, even if the headless test uses a simulated clock.

### Segment and transition construction

Generate a phrase-length segment, preferably a multiple of four bars. For a nominal 45 s target:

\[
N_{\mathrm{bars}}=4\,\operatorname{round}\left(
\frac{45\,T}{240\cdot4}\right),
\]

then choose the nearest positive multiple of four whose duration remains within 30–60 s. The exact implementation can simply search nearby multiples of four. This preserves phrase boundaries while allowing tempo to determine exact wall duration.

Use a **one-bar equal-power crossfade aligned on downbeats**. With small tempo steps, a one-bar overlap is enough to hide cuts without blending two control conditions for too long. A long generic 5–10 s fade would contaminate the effective actuator state and blur segment attribution.

Do not claim full beat matching merely because downbeats align. If tempos differ, phases drift through the overlap. Either:

- cap adjacent tempo difference tightly and align downbeats for a one-bar fade; or
- synthesize a dedicated transition bar that moves from old to new tempo.

For the pilot, choose the first. Avoid runtime time-stretching because it adds artifacts and another unvalidated component. On a genre-rung change, hold tier and tempo constant if possible so the transition does not simultaneously change three levers.

### Renderer changes

Minimum reuse path: add `render_segment(plan, n_bars)` that calls the validated `render_bar()` repeatedly with **identical** tier/tempo/genre and concatenates the results. Better audio path: build one multi-bar MIDI object per segment and render once, preserving note/reverb tails and avoiding bar-boundary discontinuities. Keep the per-bar method for regression tests.

Add an equal-power crossfade utility using
\(y[n]=\cos(\pi n/2N)x[n]+\sin(\pi n/2N)z[n]\).
The current `polish=False` choice avoids per-bar reverb bleed; segment rendering can apply polish once to the whole segment.

## 5. Minimum `run_session()` and trace changes

### `run_session()` control-flow changes

Do not rewrite the controller or renderer first. Make the smallest structural change:

1. Add config fields:
   - `n_segments`;
   - `nominal_segment_s=45`;
   - `hr_goal_bpm`;
   - `reference_rate_bpm_per_min=6`;
   - `deadband_enter_bpm=3`, `deadband_exit_bpm=2`;
   - `genre_order=("calm","r&b","pop","latin")`;
   - `crossfade_bars=1`;
   - decision-window and generation-margin durations.
2. Replace `setpoint_script(kind, n_bars)` with a monotonic-time `HRReference` implementing the slew equation. The current normalized ramp is indexed by bar count, so its physical slope changes with tempo and segment duration.
3. Nest the current loop: `for segment` then `for bar_in_segment`.
4. At segment start, copy the committed plan into immutable `applied_*` variables. Every render call in that segment uses those values.
5. During the bars, read/log HR and optionally call the existing controller to obtain **planner candidates only**.
6. At the commit point, summarize HR, call a new small `SegmentSupervisor.decide(...)`, rate-limit the proposal, and submit `render_segment(next_plan)` asynchronously.
7. Crossfade buffers at the boundary; flush trace after every bar as today.

Do not reuse the current synthetic plant as evidence for the redesign. It responds only to `tiers.tier` and ignores tempo, genre, physiological delay, and pre-generation latency. It is suitable for plumbing tests only and must be labeled as such.

Also expose commanded versus applied tempo correctly. The current row writes `tempo_cmd` and `tempo_applied` to the same value, while the cascade's next commitment is hidden. That prevents auditing lookahead delay.

### Minimum additions to the existing per-bar CSV

Keep the current columns for compatibility and add:

- `segment_idx`
- `bar_in_segment`
- `segment_n_bars`
- `segment_elapsed_s`
- `hr_bpm_filtered`
- `hr_valid`
- `hr_ref_bpm`
- `hr_error_bpm`
- `deadband_state` (`hold|calm|excite`)
- `outside_count_same_sign`
- `planner_density_candidate`
- `planner_tier_candidate`
- `planner_tempo_candidate`
- `planner_genre_candidate`
- `density_applied`
- `genre_applied` (retain `genre` as an alias during migration)
- `plan_committed` (1 only on the commit row)
- `next_tier_committed`
- `next_tempo_committed`
- `next_genre_committed`
- `decision_reason`
- `commit_wall_t`
- `measurement_age_s`
- `generation_ms`
- `next_buffer_ready`
- `generation_deadline_miss`
- `crossfade_active`

The existing `tier_applied` and `tempo_applied` become the immutable segment plan actually heard. `density_cmd`, `tier_cmd`, `tempo_cmd`, `genre`, and `tier_that_acted` must not silently retain their old meaning; either define them explicitly as planner candidates or deprecate them. A repeated segment value in each bar row is acceptable and is the minimum change that preserves crash-safe per-bar logging.

For analysis, derive a one-row-per-segment table from this CSV rather than creating a second authoritative trace. Include commit-time HR median, sample coverage, applied plan, next committed plan, and underrun status.

## 6. Biggest risk/landmine

The biggest scientific risk is **mistaking a delayed, noisy, confounded physiological association for a controlled plant**. HR responds to movement, respiration, speech, posture, novelty, and sensor artifacts; music effects may have delays comparable to or longer than a 30–60 s segment. The generate-ahead decision adds additional measurement age. A genre switch followed by an HR change is not evidence that the genre caused it.

Mitigations:

- Make this a systems/feasibility paper, not an efficacy or causal-regulation paper.
- Log raw HR, filtered HR, validity/coverage, reference, decision time, measurement age, and all applied transitions.
- Use robust filtering and freeze control on poor signal; never interpret missing data as zero error.
- Use fixed 45 s segments in the pilot and keep actuator changes isolated where possible.
- Measure the effective closed-loop delay from HR window center to next-segment audio onset.
- Include hard safety rails and a manual stop.
- Treat genre order as user-supplied/personalizable. The existing code itself warns that the Pop/Latin ordering is weakly supported; “calm” is not a universal acoustic category either.
- Run Monte Carlo software tests with realistic HR noise, dropouts, 30–120 s plant delays, and variable generation times. Look specifically for two-segment oscillations, repeated rung reversals, stale decisions, and buffer underruns.

A closely related engineering landmine is the false idea that prior validation transfers unchanged. The current PD gains, saturation counters, and one-slot tempo commitment are calibrated in calls/bars, not seconds/segments. Keep them as regression-tested components, but retune and revalidate the supervisory system end to end.

## 7. Paper claim and figures

Yes, the claim should change materially.

Old implied claim: a per-bar cascade continuously adapts musical density/tempo/genre to track arousal.

Recommended claim: **GrooveGen is a multirate closed-loop music system that shapes an auditable HR-derived arousal reference, makes rate-limited segment-level decisions, holds each generated musical segment fixed for coherence, and hides generation latency using lookahead buffering and phrase-aligned crossfades.**

The contribution is the architecture and implementation. Do not claim that it lowers HR, follows 6 BPM/min, or that the genre ladder is physiologically optimal.

Recommended figures:

1. **Architecture/timing diagram:** sensor and planner cadence, HR window, commit point, asynchronous generation, active/next buffers, crossfade, and segment-rate zero-order hold.
2. **Reference-tracking trace:** raw and filtered HR, slew-limited HR reference, ±3 BPM band, segment boundaries, and invalid-signal intervals.
3. **Actuator staircase:** applied tier, tempo, and genre rung by segment, with candidate versus committed values and decision reasons.
4. **Latency/buffer figure:** generation-time distribution, commit-to-play delay, measurement age, deadline margin, and underrun count.
5. **State-machine figure:** 3/2 BPM Schmitt deadband, persistence counters, one-rung limit, cooldown, and fallback behavior.

The old per-bar renderer latency result can remain as component evidence, but it is no longer the decisive real-time metric. The paper now needs whole-segment generation latency, buffer readiness, transition continuity, and end-to-end decision age. Tracking plots should be explicitly descriptive system traces, not efficacy outcomes.

## BOTTOM LINE

Build a 45 s, phrase-quantized, segment-rate supervisor with a monotonic-time 6 BPM/min slew-limited HR reference, a 3 BPM enter/2 BPM exit Schmitt band, robust 15–20 s HR windows, one-segment fine-actuator rate limits, two-segment persistence before a one-rung genre change, and asynchronous double-buffered one-bar equal-power crossfades. Keep the validated per-bar controller and tier mapper only as shadow candidate/planning components and regression assets; do not claim their old closed-loop validation transfers when outputs are frozen. Fix signed-error direction, add the calm rung, expose committed versus applied commands, and rewrite the paper around multirate zero-order-hold control and rendering feasibility—not HR efficacy.
