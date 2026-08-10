# Methods — Control framing (LOCKED 2026-08-04)

## What the controller tracks

GrooveGen's closed loop operates in a normalized **arousal** space, arousal ∈ [0, 1].
The scripted reference (setpoint) and the measured signal are both expressed as
arousal. We therefore describe the system's claim as **per-bar arousal-tracking
control of a symbolic music bed**, not direct heart-rate regulation.

## Heart rate → arousal mapping (stated, per-subject)

Heart rate is converted to arousal by a per-participant linear calibration
(`HRArousalMapper`):

    arousal = clip( (bpm − resting_hr) / (max_hr − resting_hr), 0, 1 )

`resting_hr` and `max_hr` are set once per participant during a short calibration
at session start. We report both the raw heart rate (`hr_bpm_raw`) and the derived
arousal (`arousal_measured`) in every trace row, so the mapping is fully auditable
and the control result can be re-expressed in BPM if desired. This is a deliberate,
disclosed modeling choice: the control loop is validated in arousal units; the
HR→arousal map is a fixed calibration, not a learned or claimed physiological model.

## Actuator (density ↔ tier reconciliation)

The validated cascade controller's fast loop emits an integer **event-density**
command in [3, 20]. The renderer and the paper's intensity narrative use five
**intensity tiers** (L1–L5). We map density → tier at render time only, keeping the
controller's internal state continuous to avoid quantization-induced limit cycles.
The mapping is monotonic and protected by (a) Schmitt-trigger **hysteresis** on tier
boundaries and (b) a **≤1-tier-per-bar rate limit**. We log both the raw command
(`density_cmd`, `tier_cmd`) and the applied tier (`tier_applied`), allowing the
quantization-induced component of tracking error to be reported separately.

## The cascade

Following the iso-principle, control authority is layered by timescale: the
fast density loop acts every bar; a **tempo** loop engages only when density
saturates against a rail for a sustained window; a **genre-energy** step engages
last. Each bar the trace records which tier acted (`tier_that_acted`), the
continuous and applied commands, the render latency (`render_ms`), and whether the
render exceeded the bar's real-time budget (`deadline_miss`). This latency/jitter
characterization is the empirical justification for a symbolic (not neural-audio)
bed: per-bar control requires bounded, sub-bar render latency.

## Measurement (honesty requirement)

The setpoint is legitimately scripted. The **measurement must come from a real
human** for the pilot; a synthetic plant is used only for development and timing
validation (`use_synthetic_plant=True`). Pilot sessions stream real heart rate
(Polar H10 over BLE) behind the same `HRSource` interface.
