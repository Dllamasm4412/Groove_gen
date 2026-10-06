from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import statistics
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import composer as _composer

GENRE_CFG = getattr(_composer, "GENRE_CFG", {})
# Genres left off the live ladder (kept in GENRE_CFG and the offline ladder).
# latin returned 2026-09-25 with its closed hi-hat layer (composer v1.5).
LIVE_EXCLUDE_GENRES: tuple[str, ...] = ()
# Live-only tier caps on top of segment_renderer.RUNG_TIER_CAP (cells above the
# cap are dropped from the live ladder; kept cells keep their u). latin4/5
# measured just below pop1 but the developer hears latin as rnb-level energy
# (L2 run, 2026-09-28), so latin stops at tier 3 (within the rnb band).
LIVE_TIER_CAP_OVERRIDES: dict[str, int] = {"latin": 3}
# Measured per-cell energy features (music_features_measured.py).
ENERGY_TABLE = Path(__file__).resolve().parent / "energy_table_v1.json"
# The developer's by-ear energy ratings of the live cells (energy_by_ear.py);
# --ladder ear reorders the measured ladder by them.
EAR_ORDER = Path(__file__).resolve().parent / "energy_order_by_ear.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimum-viable closed-loop pilot driver for subject-zero sessions."
    )
    parser.add_argument("--port", default="/dev/cu.usbmodem2023101")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--genre", default="calm", choices=sorted(GENRE_CFG.keys()))
    parser.add_argument("--baseline-seconds", type=int, default=120)
    parser.add_argument("--session-minutes", type=float, default=10.0)
    parser.add_argument("--target-offset-bpm", type=float, default=10.0)
    parser.add_argument("--sf2", required=True, help="Path to SoundFont (.sf2).")
    parser.add_argument("--out-dir", default="renders/pilot_zero")
    parser.add_argument("--subject-id", default="daniel_zero")
    parser.add_argument(
        "--initial-cell",
        default="lofi:3",
        help="starting ladder cell as genre:tier (default lofi:3)",
    )
    parser.add_argument(
        "--initial-rung",
        type=int,
        default=None,
        help="starting rung index; overrides --initial-cell (rungs refer to the tier-capped ladder)",
    )
    parser.add_argument(
        "--ladder",
        choices=("measured", "ear", "prior"),
        default="measured",
        help="cell energy source: measured features (--energy-table), measured values "
        "in the developer's by-ear order (--ear-order), or the unmeasured prior",
    )
    parser.add_argument(
        "--energy-table",
        type=Path,
        default=ENERGY_TABLE,
        help="measured energy table for --ladder measured / ear",
    )
    parser.add_argument(
        "--ear-order",
        type=Path,
        default=EAR_ORDER,
        help="by-ear ratings for --ladder ear (energy_by_ear.py apply)",
    )
    parser.add_argument(
        "--max-step-per-segment",
        type=int,
        default=1,
        help="rungs the controller may move per segment; default 1",
    )
    parser.add_argument(
        "--saturation-rotation",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="rotate genres near a saturated cell (default on; --no-saturation-rotation to disable)",
    )
    parser.add_argument(
        "--rotation-band-u",
        type=float,
        default=None,
        help="rotation window in u; default 2x the measured within-cell energy SD "
        "(measured ladder) or 0.20 (prior ladder)",
    )
    parser.add_argument(
        "--target-relaxation",
        action="store_true",
        help="engineering mode: after long saturation, step back down and re-climb",
    )
    parser.add_argument(
        "--max-du-per-segment",
        type=float,
        default=None,
        help="cap on ladder energy change per segment (e.g. 0.13); default: rung limit only",
    )
    parser.add_argument(
        "--phases",
        default=None,
        help=(
            "target schedule as name:offset_bpm:minutes,... relative to baseline, "
            "e.g. up:10:5,down:-4:5,hold:0:5; overrides --target-offset-bpm and "
            "--session-minutes"
        ),
    )
    parser.add_argument(
        "--hr-source",
        choices=("serial", "estimator"),
        default="serial",
        help=(
            "serial: open --port directly; estimator: receive HR from "
            "new_biofeedback's estimator over UDP (it owns the port)"
        ),
    )
    parser.add_argument("--estimator-port", type=int, default=5005,
                        help="UDP port the estimator publishes to (--publish-udp)")
    parser.add_argument("--goal-port", type=int, default=5006,
                        help="UDP port the estimator reads goals on (--goal-udp)")
    parser.add_argument(
        "--haptic-pacing",
        action="store_true",
        help=(
            "send goal = segment target to the estimator's pacer each segment "
            "(requires --hr-source estimator and the estimator run with --goal-udp)"
        ),
    )
    parser.add_argument(
        "--generator",
        default="bank",
        choices=("bank", "v2a", "v2c"),
        help=(
            "segment MIDI source: bank = v1 melody bank (default, unchanged); "
            "v2a = SessionComposer arrangement; v2c = v2a + per-genre development "
            "(session_generator.py; LIVE_GENERATION_PLAN.md section 6.18)"
        ),
    )
    parser.add_argument("--stim-seed", type=int, default=1,
                        help="SessionComposer stimulus seed (--generator v2a / v2c only)")
    parser.add_argument("--no-play", action="store_true", help="Skip audio playback.")
    return parser.parse_args()


def parse_phases(spec: str) -> list[tuple[str, float, float]]:
    """'up:10:5,down:-4:5' -> [('up', 10.0, 5.0), ('down', -4.0, 5.0)]."""
    phases = []
    for item in spec.split(","):
        name, offset, minutes = item.strip().split(":")
        if float(minutes) <= 0:
            raise ValueError(f"ERROR: phase {name!r} must have minutes > 0")
        phases.append((name, float(offset), float(minutes)))
    if not phases:
        raise ValueError("ERROR: --phases is empty")
    return phases


def make_target_schedule(phases: list[tuple[str, float, float]], baseline_bpm: float):
    """f(session_s) -> (phase, target_bpm), or None after the last phase."""

    def schedule(session_s: float):
        end_s = 0.0
        for name, offset, minutes in phases:
            end_s += minutes * 60.0
            if session_s < end_s:
                return name, baseline_bpm + offset
        return None

    return schedule


def setup_logging(session_dir: Path) -> logging.Logger:
    session_dir.mkdir(parents=True, exist_ok=True)
    log_path = session_dir / "pilot.log"

    logger = logging.getLogger("pilot_zero")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(fmt)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger


def ensure_valid_args(args: argparse.Namespace) -> None:
    if args.baseline_seconds <= 0:
        raise ValueError("ERROR: --baseline-seconds must be > 0")
    if args.baseline_seconds <= 60:
        raise ValueError(
            "ERROR: --baseline-seconds must be > 60 so baseline median can drop first 60s"
        )
    if args.session_minutes <= 0:
        raise ValueError("ERROR: --session-minutes must be > 0")
    if args.initial_rung is not None and args.initial_rung < 0:
        raise ValueError("ERROR: --initial-rung must be >= 0")
    if args.haptic_pacing and args.hr_source != "estimator":
        raise ValueError("ERROR: --haptic-pacing requires --hr-source estimator")
    if args.phases is not None:
        parse_phases(args.phases)


def build_player(no_play: bool, sample_rate: int, logger: logging.Logger):
    # ---------- Player setup ----------
    from player import NullPlayer

    if no_play:
        player = NullPlayer(sample_rate=44100, channels=2)
        logger.info("audio playback disabled (--no-play), using NullPlayer")
    else:
        try:
            from player import SoundDevicePlayer

            player = SoundDevicePlayer(sample_rate=44100, channels=2)
            logger.info("using SoundDevicePlayer for live playback")
        except Exception as e:
            logger.warning(f"SoundDevicePlayer unavailable: {e}; falling back to NullPlayer")
            player = NullPlayer(sample_rate=44100, channels=2)
    return player


def audio_output_info(player) -> dict[str, Any]:
    """What audio output the session actually had (build_player can fall back
    to NullPlayer silently)."""
    if player is None:
        return {"audio_output": None, "audio_output_latency_s": None}
    name = type(player).__name__
    kind = {"SoundDevicePlayer": "sounddevice", "NullPlayer": "null"}.get(name, name)
    latency = getattr(getattr(player, "_output_stream", None), "latency", None)
    return {
        "audio_output": kind,
        "audio_output_latency_s": float(latency) if isinstance(latency, (int, float)) else None,
    }


def session_condition(audio_on: bool, prov: dict[str, Any] | None) -> str:
    """Condition label from what happened, not from the flags requested.

    Haptic counts only if the estimator reported HB commands actually sent
    (n_hb_sent > 0); 'haptic_echo' marks peak-echo pulses, 'haptic_cli' an
    estimator pacing goal not set by GrooveGen. Returns 'none' if neither.
    """
    parts = []
    if audio_on:
        parts.append("music")
    if prov and prov.get("n_hb_sent", 0) > 0:
        if "echo" in prov.get("haptic_modes", []):
            parts.append("haptic_echo")
        elif "cli" in prov.get("goal_sources", []):
            parts.append("haptic_cli")
        else:
            parts.append("haptic")
    return "+".join(parts) or "none"


def provenance_warnings(args: argparse.Namespace, audio: dict[str, Any],
                        prov: dict[str, Any] | None, stage: str) -> list[str]:
    warnings = []
    if stage == "session" and not args.no_play and audio.get("audio_output") != "sounddevice":
        warnings.append("audio requested but the session ran without audio output")
    if prov is None:
        return warnings
    n_hb = prov.get("n_hb_sent", 0)
    if "echo" in prov.get("haptic_modes", []):
        warnings.append(f"{stage}: estimator in echo mode (peak-echo haptics, PPG motor artifact)")
    if stage == "baseline" and n_hb > 0:
        warnings.append(f"baseline: {n_hb} haptic pulses sent during baseline")
    if stage == "session" and args.haptic_pacing and n_hb == 0:
        warnings.append("session: --haptic-pacing set but the estimator sent no HB pulses")
    if stage == "session" and not args.haptic_pacing and n_hb > 0:
        warnings.append(f"session: {n_hb} haptic pulses sent without --haptic-pacing")
    if len(prov.get("log_stamps", [])) > 1:
        warnings.append(f"{stage}: estimator restarted (log stamps {prov['log_stamps']}); "
                        "its MCU clock restarts, fit clock mappings per stamp")
    if prov.get("n_received", 1) == 0:
        warnings.append(f"{stage}: no estimator messages received")
    return warnings


class PPGSignalMonitor:
    """Tells the operator to adjust the PPG sensor while no valid HR arrives.

    update(ok) is called on every HR read. After after_s without a valid
    reading it logs ADJUST THE PPG SENSOR (repeated every repeat_s), and once
    a valid reading returns it logs that the signal is back. Logging only;
    the callers decide what to pause.
    """

    def __init__(self, logger: logging.Logger, context: str,
                 after_s: float = 5.0, repeat_s: float = 10.0, time_fn=None):
        self.logger = logger
        self.context = context
        self.after_s = after_s
        self.repeat_s = repeat_s
        self.time_fn = time_fn or time.time
        self.bad_since: Optional[float] = None
        self.last_alert: Optional[float] = None
        self.n_episodes = 0

    def update(self, ok: bool) -> None:
        now = self.time_fn()
        if ok:
            if self.last_alert is not None:
                self.logger.info("PPG signal back after %.0f s without valid HR; resuming",
                                 now - self.bad_since)
            self.bad_since = self.last_alert = None
            return
        if self.bad_since is None:
            self.bad_since = now
        if now - self.bad_since >= self.after_s and (
            self.last_alert is None or now - self.last_alert >= self.repeat_s
        ):
            if self.last_alert is None:
                self.n_episodes += 1
            self.logger.warning("ADJUST THE PPG SENSOR: no valid HR for %.0f s (%s)",
                                now - self.bad_since, self.context)
            self.last_alert = now


def collect_baseline(
    ppg_source,
    baseline_seconds: int,
    baseline_csv_path: Path,
    logger: logging.Logger,
) -> tuple[float, list[dict[str, Any]]]:
    logger.info("Starting baseline phase: warm-up 8s, then %ds at 1Hz.", baseline_seconds)
    time.sleep(8.0)

    samples: list[dict[str, Any]] = []
    stale_streak = 0
    monitor = PPGSignalMonitor(logger, "baseline paused until HR returns")

    # More than 5 consecutive stale reads pause the baseline (no samples are
    # recorded) instead of aborting; it resumes on the next fresh read.
    while len(samples) < baseline_seconds:
        reading = ppg_source.read()
        is_fresh = bool(getattr(reading, "is_fresh", False))
        bpm_val = float(getattr(reading, "bpm", float("nan")))
        t_wall = float(getattr(reading, "t_wall", time.time()))
        monitor.update(is_fresh)

        if is_fresh:
            stale_streak = 0
        else:
            stale_streak += 1

        if stale_streak > 5:
            time.sleep(1.0)
            continue

        row = {"t_wall": t_wall, "bpm": bpm_val, "is_fresh": is_fresh}
        samples.append(row)
        logger.info("baseline t=%ss  hr=%.1f bpm  (n_samples=%d)", len(samples), bpm_val, len(samples))
        time.sleep(1.0)

    baseline_csv_path.parent.mkdir(parents=True, exist_ok=True)
    with baseline_csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["t_wall", "bpm", "is_fresh"])
        writer.writeheader()
        writer.writerows(samples)

    usable = [row["bpm"] for idx, row in enumerate(samples) if idx >= 60 and row["is_fresh"]]
    if not usable:
        raise RuntimeError(
            "ERROR: No fresh baseline samples remained after dropping first 60 seconds"
        )

    baseline_median = float(statistics.median(usable))
    logger.info("Baseline complete: median over last 60s = %.2f bpm", baseline_median)
    return baseline_median, samples


def log_segment(logger: logging.Logger, seg_idx: int, row: Any) -> None:
    hr = "--" if row.hr_bpm is None else f"{row.hr_bpm:.1f}"
    msg = (
        f"seg {seg_idx:2d} {row.phase or '-':>5} {row.genre}{row.tier} "
        f"target={row.hr_target_bpm:.1f} hr={hr} (n={row.hr_n_fresh}) "
        f"mode={row.control_mode}"
    )
    if row.haptic_state:
        pace = "--" if row.pace_bpm is None else f"{row.pace_bpm:.1f}"
        goal = "--" if row.haptic_goal_eff_bpm is None else f"{row.haptic_goal_eff_bpm:.1f}"
        msg += f" | haptic={row.haptic_state} pace={pace} goal_eff={goal}"
    if row.rr_rpm is not None:
        msg += f" rr={row.rr_rpm:.1f}"
    if row.generator == "v2_session":
        msg += f" | visit={row.gen_visit_idx} sel={row.motif_selection or '-'}"
    logger.info(msg)


def save_trace_csv(trace: list[Any], path: Path, logger: logging.Logger) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import pandas as pd

        records = [row._asdict() if hasattr(row, "_asdict") else row for row in trace]
        df = pd.DataFrame.from_records(records)
        df.to_csv(path, index=False)
        logger.info("Saved trace CSV via pandas: %s", path)
        return
    except Exception as exc:
        logger.warning("Pandas trace save failed (%s). Falling back to stdlib CSV writer.", exc)

    records = []
    for row in trace:
        try:
            records.append(asdict(row))
        except Exception:
            if hasattr(row, "_asdict"):
                records.append(row._asdict())
            elif isinstance(row, dict):
                records.append(row)
            else:
                records.append(vars(row))

    if not records:
        path.write_text("", encoding="utf-8")
        logger.info("Trace empty; wrote empty CSV file: %s", path)
        return

    fieldnames = list(records[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)
    logger.info("Saved trace CSV via stdlib fallback: %s", path)


def compute_summary(
    trace: list[Any],
    args: argparse.Namespace,
    timestamp: str,
    baseline_median: float,
    target_bpm: float,
    n_cells: int | None = None,
    initial_rung: int | None = None,
    stale_hr_policy: str | None = None,
    hr_poll_s: float | None = None,
) -> dict[str, Any]:
    if trace:
        n_segments = len(
            {int(getattr(r, "segment_idx", -1)) for r in trace if hasattr(r, "segment_idx")}
        )
        # stale_hold rows carry no error (NaN): no HR was used for them
        abs_err = [
            abs(float(getattr(r, "effective_error_bpm", 0.0)))
            for r in trace
            if getattr(r, "control_mode", "mpc") != "stale_hold"
            and math.isfinite(float(getattr(r, "effective_error_bpm", 0.0)))
        ]
        mean_abs_error_bpm = float(sum(abs_err) / len(abs_err)) if abs_err else None
        seg_first = {}
        for r in trace:
            seg_first.setdefault(int(getattr(r, "segment_idx", -1)), r)
        segs = list(seg_first.values())
        fresh_segment_fraction = (
            sum(bool(getattr(r, "hr_is_fresh", False)) for r in segs) / len(segs)
        )
        n_stale_hold = sum(getattr(r, "control_mode", "") == "stale_hold" for r in segs)
        mean_hr_n_fresh = sum(int(getattr(r, "hr_n_fresh", 0)) for r in segs) / len(segs)
        hr_vals = [
            getattr(r, "hr_bpm", None) for r in trace if getattr(r, "hr_bpm", None) is not None
        ]
        final_hr_bpm = float(hr_vals[-1]) if hr_vals else None
        # HR vs the requested (raw) target, per phase; fresh HR rows only
        raw_err_by_phase: dict[str, list[float]] = {}
        for r in trace:
            if getattr(r, "hr_bpm", None) is not None:
                raw_err_by_phase.setdefault(getattr(r, "phase", ""), []).append(
                    abs(float(r.hr_target_bpm) - float(r.hr_bpm))
                )
        mean_abs_raw_error_by_phase = {
            k: float(sum(v) / len(v)) for k, v in raw_err_by_phase.items()
        }
    else:
        n_segments = 0
        mean_abs_error_bpm = None
        fresh_segment_fraction = None
        n_stale_hold = 0
        mean_hr_n_fresh = None
        final_hr_bpm = None
        mean_abs_raw_error_by_phase = {}

    return {
        "subject_id": args.subject_id,
        "timestamp": timestamp,
        "genre": args.genre,
        "saturation_rotation": args.saturation_rotation,
        "target_relaxation": args.target_relaxation,
        "baseline_median": baseline_median,
        "target_bpm": target_bpm,
        "session_minutes": args.session_minutes,
        "n_segments_completed": n_segments,
        "mean_abs_error_bpm": mean_abs_error_bpm,
        "final_hr_bpm": final_hr_bpm,
        # mean_abs_error_bpm above is the controller's effective error, i.e.
        # HR vs the GOVERNED reference; this is HR vs the requested target.
        "mean_abs_raw_error_bpm_by_phase": mean_abs_raw_error_by_phase,
        "phases": args.phases,
        "max_du_per_segment": args.max_du_per_segment,
        "n_cells": n_cells,
        "initial_rung": initial_rung,
        "hr_source": args.hr_source,
        "haptic_pacing": args.haptic_pacing,
        "stale_hr_policy": stale_hr_policy,
        "hr_poll_s": hr_poll_s,
        # per segment: HR fresh at the decision, stale-hold count, and the
        # mean number of fresh readings in the controller's HR window
        "fresh_segment_fraction": fresh_segment_fraction,
        "n_stale_hold_segments": n_stale_hold,
        "mean_hr_n_fresh": mean_hr_n_fresh,
    }


def main() -> int:
    args = parse_args()

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    session_dir = Path(args.out_dir) / f"{args.subject_id}_{timestamp}"
    logger = setup_logging(session_dir)

    trace: list[Any] = []
    partial_trace_rows: list[Any] = []
    ppg_source = None
    player = None
    hr_poll_file = None

    try:
        ensure_valid_args(args)

        logger.info("subject_id=%s genre=%s", args.subject_id, args.genre)
        logger.info("output_dir=%s", session_dir)

        # Build pipeline in locked import order.
        from control import ControllerConfig, LadderMPC
        from crossfade import CrossfadeMixer
        from ladder import build_ladder
        from run_session_v2 import SessionConfigV2, run_session_v2
        from segment_renderer import RUNG_TIER_CAP, SymbolicSegmentRenderer

        if args.hr_source == "estimator":
            from estimator_hr_source import EstimatorHRSource

            ppg_source = EstimatorHRSource(
                listen=("127.0.0.1", args.estimator_port),
                goal_addr=("127.0.0.1", args.goal_port),
                rx_log_path=session_dir / "estimator_rx.csv",
            ).start()
            logger.info(
                "hr_source=estimator (UDP %d); haptic_pacing=%s (goals to UDP %d)",
                args.estimator_port, args.haptic_pacing, args.goal_port,
            )
        else:
            from serial_ppg_source import SerialPPGSource

            ppg_source = SerialPPGSource(port=args.port, baud=args.baud).start()

        baseline_csv = session_dir / "baseline_hr.csv"
        baseline_median, _baseline_samples = collect_baseline(
            ppg_source=ppg_source,
            baseline_seconds=args.baseline_seconds,
            baseline_csv_path=baseline_csv,
            logger=logger,
        )

        take_prov = getattr(ppg_source, "take_provenance", None)
        baseline_prov = take_prov() if callable(take_prov) else None
        for w in provenance_warnings(args, {}, baseline_prov, "baseline"):
            logger.warning(w)

        target_bpm = baseline_median + float(args.target_offset_bpm)
        logger.info("baseline_median=%.2f bpm", baseline_median)
        target_schedule = None
        session_minutes = args.session_minutes
        if args.phases is not None:
            phases = parse_phases(args.phases)
            target_schedule = make_target_schedule(phases, baseline_median)
            session_minutes = sum(m for _, _, m in phases)
            target_bpm = baseline_median + phases[0][1]
            for name, offset, minutes in phases:
                logger.info(
                    "phase %s: target=%.2f bpm (%+.1f) for %.1f min",
                    name, baseline_median + offset, offset, minutes,
                )
        else:
            logger.info("target_bpm=%.2f bpm", target_bpm)

        # Only cells the renderer plays distinctly (calm<=2, lofi<=3, rnb<=4).
        # Measured ladder: cell energy from rendered loudness, drum onset
        # rate, played tempo, centroid and flux (energy_table_v1.json).
        energy_table_sha = ear_order_sha = None
        live_tier_caps = {**RUNG_TIER_CAP, **LIVE_TIER_CAP_OVERRIDES}
        if args.ladder in ("measured", "ear"):
            from ladder import load_ear_ratings, load_energy_table
            features, weights, tie_band, energy_table_sha = load_energy_table(args.energy_table)
            ear_ratings = None
            if args.ladder == "ear":
                ear_ratings, ear_order_sha = load_ear_ratings(args.ear_order)
            ladder = build_ladder(
                tier_caps=live_tier_caps, exclude_genres=LIVE_EXCLUDE_GENRES,
                features=features, weights=weights, tie_band=tie_band,
                ear_ratings=ear_ratings,
            )
            logger.info("ladder: measured (%s, sha256 %s)", args.energy_table, energy_table_sha[:16])
            if ear_ratings is not None:
                logger.info("ladder: by-ear order (%s, sha256 %s)", args.ear_order, ear_order_sha[:16])
        else:
            ladder = build_ladder(tier_caps=live_tier_caps, exclude_genres=LIVE_EXCLUDE_GENRES)
            logger.info("ladder: prior")
        if args.initial_rung is not None:
            initial_rung = args.initial_rung
        else:
            genre0, tier0 = args.initial_cell.split(":")
            initial_rung = ladder.index(genre0, int(tier0))
        if not 0 <= initial_rung < len(ladder.cells):
            raise ValueError(f"ERROR: initial rung {initial_rung} outside 0..{len(ladder.cells) - 1}")
        c0 = ladder.by_rung[initial_rung]
        logger.info(
            "ladder: %d cells; initial rung %d = %s%d (u=%.3f)",
            len(ladder.cells), initial_rung, c0.genre, c0.tier, c0.u,
        )
        max_gap = max(b.u - a.u for a, b in zip(ladder.cells, ladder.cells[1:]))
        if args.max_du_per_segment is not None and args.max_du_per_segment < max_gap:
            logger.warning(
                "max_du_per_segment=%.3f is below the largest adjacent-cell gap %.3f: "
                "some 1-rung moves are blocked",
                args.max_du_per_segment, max_gap,
            )
        if args.rotation_band_u is not None:
            rotation_band_u = args.rotation_band_u
        elif args.ladder in ("measured", "ear"):
            # cells within ~2 noise SDs of the stall cell (user OK 2026-09-25
            # to rotate slightly below the top)
            rotation_band_u = 2.0 * ladder.noise_u
        else:
            rotation_band_u = ControllerConfig().rotation_band_u
        controller = LadderMPC(
            ladder,
            ControllerConfig(
                max_step_per_segment=args.max_step_per_segment,
                saturation_rotation=args.saturation_rotation,
                rotation_band_u=rotation_band_u,
                target_relaxation=args.target_relaxation,
                max_du_per_segment=args.max_du_per_segment,
            ),
        )
        logger.info(f"controller max_step_per_segment={args.max_step_per_segment}")
        logger.info(
            "saturation_rotation=%s (band %.3f u) target_relaxation=%s",
            args.saturation_rotation,
            rotation_band_u,
            args.target_relaxation,
        )
        logger.info("max_du_per_segment=%s", args.max_du_per_segment)
        renderer = SymbolicSegmentRenderer(sf2_path=args.sf2, sr=44100, session_seed=42)
        player = build_player(args.no_play, sample_rate=44100, logger=logger)
        player.start()
        logger.info("player started")
        # tail_out: each segment's downbeat plays at full level; only the
        # previous segment's release tail fades out underneath it
        mixer = CrossfadeMixer(fade_bars=0.25, fade_mode="tail_out")
        # Opt-in v2 generator: one SessionComposer for the whole session; it
        # sees only the chosen cell (session_generator.py)
        segment_source = None
        if args.generator != "bank":
            from session_generator import GENERATORS, SessionSegmentSource

            segment_source = SessionSegmentSource(args.stim_seed, develop=GENERATORS[args.generator])
            logger.info("generator=%s stim_seed=%d", args.generator, args.stim_seed)
        cfg = SessionConfigV2(
            bars_per_segment=8,
            sample_rate=44100,
            fade_bars=0.25,
            hr_poll_s=1.0,
            stale_hr_policy="hold",
            haptic_pacing=args.haptic_pacing,
            # With a phase schedule the schedule ends the session; segments
            # run 15-22 s, so this is only a cap.
            max_segments=int(session_minutes * 60 / (12 if target_schedule else 20)),
        )
        if cfg.max_segments <= 0:
            raise RuntimeError("ERROR: computed max_segments <= 0; increase --session-minutes")

        # Every HR read the session makes (run_session_v2.HR_POLL_LOG_FIELDS)
        from run_session_v2 import HR_POLL_LOG_FIELDS
        hr_poll_file = (session_dir / "hr_polls.csv").open("w", newline="", encoding="utf-8")
        hr_poll_writer = csv.DictWriter(hr_poll_file, fieldnames=list(HR_POLL_LOG_FIELDS))
        hr_poll_writer.writeheader()

        # Stale HR never ends the session: the controller holds its cell
        # (stale_hr_policy='hold') and the operator is told to adjust the sensor.
        session_ppg_monitor = PPGSignalMonitor(logger, "music holds its current cell until HR returns")

        def log_hr_poll(row: dict[str, Any]) -> None:
            hr_poll_writer.writerow(row)
            hr_poll_file.flush()
            session_ppg_monitor.update(bool(row["accepted"]))

        # The first goal goes out with segment 0 and the estimator arms its
        # pacer on receipt, so from segment 1 on a missing pacer means the
        # estimator is not pacing (warn now, not only in the summary).
        pacer_warned = False

        def on_segment(seg_idx: int, row: Any) -> None:
            nonlocal pacer_warned
            log_segment(logger, seg_idx, row)
            status_fn = getattr(ppg_source, "haptic_status", None)
            if args.haptic_pacing and seg_idx >= 1 and not pacer_warned and callable(status_fn):
                if (status_fn() or {}).get("pacer_state") is None:
                    logger.warning(
                        "HAPTICS NOT RUNNING: --haptic-pacing is set but the estimator reports "
                        "no pacer. Stop both programs, restart the estimator, then the runner."
                    )
                    pacer_warned = True

        def write_summary(interrupted: bool) -> Path:
            summary = compute_summary(
                trace=partial_trace_rows,
                args=args,
                timestamp=timestamp,
                baseline_median=baseline_median,
                target_bpm=target_bpm,
                n_cells=len(ladder.cells),
                initial_rung=initial_rung,
                stale_hr_policy=cfg.stale_hr_policy,
                hr_poll_s=cfg.hr_poll_s,
            )
            summary["ladder_excluded_genres"] = list(LIVE_EXCLUDE_GENRES)
            summary["ladder_source"] = args.ladder
            summary["rotation_band_u"] = rotation_band_u
            summary["rotation_no_repeat"] = controller.cfg.rotation_no_repeat
            summary["energy_table"] = str(args.energy_table) if args.ladder != "prior" else None
            summary["energy_table_sha256"] = energy_table_sha
            summary["ear_order"] = str(args.ear_order) if args.ladder == "ear" else None
            summary["ear_order_sha256"] = ear_order_sha
            summary["ladder_cells"] = [f"{c.genre}{c.tier}:{c.u:.4f}" for c in ladder.cells]
            summary["crossfade_tail_scaled"] = mixer.n_tail_scaled
            summary["generator"] = segment_source.config() if segment_source else {"generator": "bank"}
            # Condition provenance: what actually ran, not only the flags
            session_prov = take_prov() if callable(take_prov) else None
            audio = audio_output_info(player)
            session_warnings = provenance_warnings(args, audio, session_prov, "session")
            for w in session_warnings:
                logger.warning(w)
            warnings = provenance_warnings(args, {}, baseline_prov, "baseline") + session_warnings
            summary.update(
                interrupted=interrupted,
                no_play=args.no_play,
                **audio,
                condition=session_condition(audio["audio_output"] == "sounddevice", session_prov),
                estimator_baseline=baseline_prov,
                estimator_session=session_prov,
                estimator_log_errors=getattr(ppg_source, "n_log_errors", None),
                provenance_warnings=warnings,
            )
            path = session_dir / "summary.json"
            path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
            return path

        try:
            trace = run_session_v2(
                hr_source=ppg_source,
                renderer=renderer,
                player=player,
                mixer=mixer,
                ladder=ladder,
                controller=controller,
                config=cfg,
                hr_target_bpm=target_bpm,
                hr_baseline_bpm=baseline_median,
                initial_rung=initial_rung,
                target_schedule=target_schedule,
                trace_writer=partial_trace_rows.append,
                on_segment=on_segment,
                hr_poll_log=log_hr_poll,
                segment_source=segment_source,
            )
            # Keep one canonical reference after successful completion.
            partial_trace_rows = trace
        except KeyboardInterrupt:
            trace_path = session_dir / "session_trace.csv"
            save_trace_csv(partial_trace_rows, trace_path, logger)
            logger.info("session interrupted — partial trace saved to %s", trace_path)
            try:
                summary_path = write_summary(interrupted=True)
                logger.info("partial summary saved to %s", summary_path)
            except Exception as e:
                logger.warning(f"partial summary failed: {e}")
            return 130

        trace_path = session_dir / "session_trace.csv"
        save_trace_csv(partial_trace_rows, trace_path, logger)

        summary_path = write_summary(interrupted=False)
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        logger.info("condition=%s", summary["condition"])

        logger.info("Session complete.")
        logger.info(
            "Summary: subject=%s segments=%s final_hr=%s mean_abs_error=%.3f",
            summary["subject_id"],
            summary["n_segments_completed"],
            summary["final_hr_bpm"],
            summary["mean_abs_error_bpm"]
            if summary["mean_abs_error_bpm"] is not None
            else float("nan"),
        )
        logger.info("Artifacts: trace=%s summary=%s", trace_path, summary_path)
        return 0

    except Exception as exc:
        logger.exception("ERROR: %s", exc)
        return 1

    finally:
        if args.haptic_pacing and ppg_source is not None:
            try:
                ppg_source.stop()
                logger.info("sent pacing stop to estimator")
            except Exception as e:
                logger.warning(f"pacing stop failed: {e}")
        if player is not None:
            try:
                player.stop(drain=True)
            except Exception as e:
                logger.warning(f"player.stop() failed: {e}")
            try:
                player.close()
            except AttributeError:
                pass  # PlayerBase doesn't require close()
            except Exception as e:
                logger.warning(f"player.close() failed: {e}")
        if ppg_source is not None:
            try:
                ppg_source.close()
            except Exception:
                pass
        if hr_poll_file is not None:
            hr_poll_file.close()


if __name__ == "__main__":
    sys.exit(main())
