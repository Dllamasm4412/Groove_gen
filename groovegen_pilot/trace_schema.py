"""trace_schema.py — SINGLE SOURCE OF TRUTH for the per-bar session trace.

Every closed-loop session writes exactly these columns, one row per bar, flushed
to disk every bar (crash-safe). Figures and analysis read ONLY this file.

Framing decision (LOCKED 2026-08-04, Daniel): the controller tracks AROUSAL (0..1).
Heart rate is converted to arousal via hr_source.HRArousalMapper as a STATED,
per-subject-calibrated linear mapping (resting_hr->0, max_hr->1). We report both
the raw bpm and the derived arousal so the mapping is fully auditable; the control
claim is arousal-tracking, NOT direct HR regulation.

Actuator reconciliation (finding #1): the validated CascadeController's fast loop
emits an integer event-density in [3,20]. We expose that raw command AND a derived
intensity TIER in [1,5] (a monotonic reporting bucket with hysteresis + rate limit,
see tier_mapping.py). We log BOTH density_cmd and tier_applied so quantization-
induced tracking error can be reported as a separate, honest term.
"""
from __future__ import annotations

# Ordered list of columns. run_session writes rows as dicts keyed by these names.
COLUMNS = [
    # --- timing ---
    "wall_t",            # float, seconds since session start (time.monotonic based)
    "bar_idx",           # int, 0-based bar counter
    # --- physiology / reference ---
    "hr_bpm_raw",        # float, raw HR reading this bar (NaN if none)
    "arousal_setpoint",  # float 0..1, scripted target arousal for this bar
    "arousal_measured",  # float 0..1, measured arousal (HRArousalMapper.to_arousal(hr))
    "error",             # float, setpoint - measured
    # --- controller outputs (continuous + quantized) ---
    "density_cmd",       # int [3,20], raw fast-loop density command from controller
    "tier_cmd",          # int [1,5], tier implied by density_cmd BEFORE hysteresis
    "tier_applied",      # int [1,5], tier actually rendered AFTER hysteresis/rate-limit
    "tempo_cmd",         # float bpm, controller tempo command
    "tempo_applied",     # float bpm, tempo actually rendered (committed-buffer value)
    "genre",             # str, active genre this bar
    "tier_that_acted",   # 'density'|'tempo'|'genre'|'none' (which cascade tier moved)
    # --- render / performance ---
    "render_ms",         # float, wall-clock ms to render this bar's audio
    "deadline_miss",     # int 0/1, 1 if render_ms exceeded the bar's real duration
    # --- reproducibility ---
    "seed",              # int, RNG seed for the session
    "code_version",      # str, git-describe or tag (e.g. 'v0.1-pilot')
]

# Types used for validation / documentation.
DTYPES = {
    "wall_t": float, "bar_idx": int, "hr_bpm_raw": float,
    "arousal_setpoint": float, "arousal_measured": float, "error": float,
    "density_cmd": int, "tier_cmd": int, "tier_applied": int,
    "tempo_cmd": float, "tempo_applied": float, "genre": str,
    "tier_that_acted": str, "render_ms": float, "deadline_miss": int,
    "seed": int, "code_version": str,
}

assert set(DTYPES) == set(COLUMNS), "DTYPES and COLUMNS must match"
