"""
Closed-loop run_session v2 for GrooveGen (M0.5 Step 5.5).

Upgrades over v1 (run_session.py):
    1. Quarter-bar crossfade default (fade_bars=0.25) instead of half-bar
    2. Melody bank rotation -- distinct seeds per (genre, tier) per repeat
    3. Physiological controller (LadderMPC) instead of naked LinearBandPolicy;
       controller CHOOSES BOTH genre AND tier from the schedule's tempo hint,
       driven by an HR_target the caller supplies.

The schedule now provides only a TEMPO plan (or a fixed tempo per genre);
genre/tier come from the controller. If the caller wants to force a
genre schedule, they can bypass the controller by passing a
`FixedGenreOverride` policy (not implemented in this file to keep it lean).

Public API
----------
    SessionConfigV2         Config dataclass
    TraceRowV2              Extended trace row (adds g_hat, unreachable, rung)
    run_session_v2(
        hr_source, renderer, player, mixer, ladder, controller, config,
        hr_target_bpm, hr_baseline_bpm,
        melody_bank=None, segments_max=None, trace_writer=None, ...
    )

Backward-compatibility: run_session.py v1 is unchanged; use v2 explicitly.
"""

from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional, Sequence

from crossfade import CrossfadeMixer, bar_duration_frames
from renderer_to_player import enqueue_segment
from ladder import Ladder, build_ladder
from control import LadderMPC, ControllerConfig
from melody_bank import MelodyBank


class TraceRowV2(NamedTuple):
    wall_time: float
    session_time: float
    segment_idx: int
    bar_idx_in_segment: int
    bar_idx_global: int
    genre: str
    tempo_bpm: float
    tier: int
    rung: int
    seed: int
    hr_bpm: Optional[float]
    hr_target_bpm: float
    hr_baseline_bpm: float
    hr_source: Optional[str]
    hr_is_fresh: bool
    # Controller diagnostics
    g_hat_bpm: float
    governed_r_bpm: float
    is_unreachable: bool
    saturation_state: str
    dead_zone_active: bool
    predicted_hr_H: float
    effective_error_bpm: float
    # Arousal poll (Step 6 extended trace)
    arousal_1_9: Optional[float]
    arousal_source: Optional[str]
    arousal_t_wall: Optional[float]
    # Saturation modes (appended): 'mpc' | 'rotate' | 'relax', and the rung
    # the MPC chose before any rotation/relaxation override
    control_mode: str = 'mpc'
    mpc_rung: Optional[int] = None
    # Target schedule phase name ('' when the target is fixed)
    phase: str = ''
    # Segment HR aggregation (appended): fresh readings in the window the
    # controller's HR came from, their SD (understated: the source's own
    # windows overlap), and the single decision-time read
    hr_n_fresh: int = 0
    hr_seg_sd_bpm: Optional[float] = None
    hr_instant_bpm: Optional[float] = None
    # Haptic pacing via the estimator (appended; empty without it).
    # haptic_goal_bpm is what GrooveGen sent this segment; haptic_goal_eff_bpm
    # is the pacer's clipped goal as last reported (may lag one message).
    haptic_state: str = ''
    pace_bpm: Optional[float] = None
    haptic_goal_bpm: Optional[float] = None
    haptic_goal_eff_bpm: Optional[float] = None
    rr_rpm: Optional[float] = None
    # HR provenance (appended): host time of the segment's HR decision (trace
    # wall_time marks when bars play, later) and the source timestamp of the
    # decision-time read. hr_poll_log rows with for_segment == segment_idx,
    # accepted, and t_wall >= hr_decision_t_wall - hr_window_s are exactly the
    # readings whose median is hr_bpm (when hr_n_fresh >= hr_min_readings).
    hr_decision_t_wall: Optional[float] = None
    hr_read_t_wall: Optional[float] = None
    # Ladder energy coordinate u of the played cell (appended; the ladder
    # source is in the session summary)
    cell_u: Optional[float] = None
    # Render timing (appended): fluidsynth render wall time of the segment,
    # its planned duration (bars at tempo) and the audio still queued when it
    # was enqueued (0 = the player had run dry: an audible gap)
    render_s: Optional[float] = None
    planned_s: Optional[float] = None
    queued_ahead_s: Optional[float] = None
    # Generator provenance (appended): 'v1_bank' (default) or the opt-in v2
    # session source (session_generator.py); the gen_* / motif_* columns are
    # None for v1_bank. gen_visit_idx is the cell's visit count this session.
    generator: Optional[str] = None
    gen_version: Optional[str] = None
    dev_version: Optional[str] = None
    gen_stim_seed: Optional[int] = None
    gen_visit_idx: Optional[int] = None
    gen_block_idx: Optional[int] = None
    gen_pos_in_block: Optional[int] = None
    gen_base_seed: Optional[int] = None
    gen_var_seed: Optional[int] = None
    motif_policy: Optional[str] = None
    motif_selection: Optional[str] = None
    motif_role: Optional[str] = None
    motif_ops: Optional[str] = None
    motif_id: Optional[str] = None
    motif_theme_id: Optional[str] = None
    motif_error: Optional[str] = None


HR_POLL_LOG_FIELDS = ('poll_wall', 'for_segment', 'kind', 't_wall', 'bpm',
                      'source_fresh', 'accepted')


@dataclass(frozen=True)
class SessionConfigV2:
    bars_per_segment: int = 8
    sample_rate: int = 44100
    beats_per_bar: int = 4
    hr_stale_seconds: float = 3.0
    fade_bars: float = 0.25              # QUARTER BAR per user request
    max_segments: int = 24
    # Gap control. Each render is cut to its bars plus one crossfade, so the
    # fluidsynth release tail (2.7-7 s below -50 dBFS) is crossfaded into the
    # next downbeat instead of played as silence. The loop then wakes
    # render_lead_s before the queued audio runs out, so the next segment
    # (HR read + controller + ~0.6-1.7 s render) is queued before it is needed.
    trim_render_tail: bool = True
    render_lead_s: float = 3.0
    # Segment HR. hr_poll_s > 0: read the source every hr_poll_s during the
    # pacing wait; the controller gets the median of fresh readings from the
    # last hr_window_s (if at least hr_min_readings), else the decision-time
    # read. 0 = one read per segment (old behaviour).
    hr_poll_s: float = 0.0
    hr_window_s: float = 10.0
    hr_min_readings: int = 3
    # No usable HR: 'baseline' substitutes the baseline and steps the
    # controller (old behaviour); 'hold' keeps the current rung and skips
    # the RLS update (LadderMPC.hold).
    stale_hr_policy: str = 'baseline'
    # Haptic pacing through the estimator: each segment send goal = segment
    # target (hr_source.set_goal) and a keepalive on every HR poll. Needs
    # hr_poll_s > 0 so keepalives arrive well inside the estimator watchdog.
    haptic_pacing: bool = False
    # Tempo policy: if the controller picks a genre, we use the genre's
    # tempo_default from GENRE_CFG (imported from composer), or the genre's
    # tier_tempo entry when it has one (cell-backed hiphop, rock).


def _hr_reading_is_fresh(reading, now: float, stale_s: float) -> bool:
    if reading is None:
        return False
    if not getattr(reading, 'is_fresh', True):
        return False
    age = now - float(reading.t_wall)
    return age <= stale_s


def _bar_duration_seconds(tempo_bpm: float, beats_per_bar: int = 4) -> float:
    return (60.0 / tempo_bpm) * beats_per_bar


def run_session_v2(
    hr_source,
    renderer,
    player,
    mixer: CrossfadeMixer,
    ladder: Ladder,
    controller: LadderMPC,
    config: SessionConfigV2,
    *,
    hr_target_bpm: float,
    hr_baseline_bpm: float,
    initial_rung: int = 0,
    target_schedule: Optional[Callable[[float], Optional[tuple[str, float]]]] = None,
    melody_bank: Optional[MelodyBank] = None,
    arousal_source=None,
    trace_writer: Optional[Callable[[TraceRowV2], None]] = None,
    on_segment: Optional[Callable[[int, TraceRowV2], None]] = None,
    hr_poll_log: Optional[Callable[[dict], None]] = None,
    segment_source=None,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.time,
    perf_counter_fn: Callable[[], float] = time.perf_counter,
) -> list[TraceRowV2]:
    """
    Run the closed-loop session with physiological controller.

    Parameters
    ----------
    hr_source : object with .read() returning HRReading-like NamedTuple
    renderer  : SymbolicSegmentRenderer
    player    : PlayerBase
    mixer     : CrossfadeMixer (configured with fade_bars=config.fade_bars)
    ladder    : Ladder (from build_ladder())
    controller: LadderMPC
    config    : SessionConfigV2
    hr_target_bpm  : researcher-set target HR
    hr_baseline_bpm: pre-session baseline HR (used by governor)
    initial_rung   : starting rung (default 0 = calm-1)
    target_schedule: optional f(session_s) -> (phase, target_bpm), evaluated
                     at the time the segment will start playing; returning
                     None ends the session. Overrides hr_target_bpm.
    melody_bank    : optional MelodyBank; if None, one is created with N=4
    hr_poll_log    : optional f(row) called on every HR read with a dict of
                     HR_POLL_LOG_FIELDS; kind is 'decision' or 'wait', and
                     for_segment the segment whose decision the read feeds
    segment_source : optional opt-in v2 generator (session_generator.
                     SessionSegmentSource): next_segment(genre, tier) ->
                     (MIDI, info), rendered with renderer.render_pm. It gets
                     only the chosen cell. None (default) = the v1 bank via
                     melody_bank + renderer.render_segment, unchanged.

    Returns
    -------
    list[TraceRowV2]
    """
    from composer import GENRE_CFG  # local to keep top-level import cheap

    if config.stale_hr_policy not in ('baseline', 'hold'):
        raise ValueError(f"unknown stale_hr_policy: {config.stale_hr_policy!r}")
    if config.haptic_pacing and config.hr_poll_s <= 0:
        raise ValueError("haptic_pacing requires hr_poll_s > 0 (keepalives)")
    haptic_status_fn = getattr(hr_source, 'haptic_status', None)

    # Fresh readings keyed by t_wall (dedupes a source that repeats its
    # last reading between updates)
    hr_window: dict[float, float] = {}

    def _poll_hr(for_segment, kind):
        """Read once; returns (reading, fresh) and records fresh readings."""
        try:
            r = hr_source.read()
        except Exception:
            r = None
        poll_wall = time_fn()
        ok = _hr_reading_is_fresh(r, poll_wall, config.hr_stale_seconds)
        if ok:
            hr_window[float(r.t_wall)] = float(r.bpm)
        if hr_poll_log is not None:
            try:
                hr_poll_log({
                    'poll_wall': poll_wall, 'for_segment': for_segment, 'kind': kind,
                    't_wall': None if r is None else float(r.t_wall),
                    'bpm': None if r is None else float(r.bpm),
                    'source_fresh': None if r is None else bool(getattr(r, 'is_fresh', True)),
                    'accepted': ok,
                })
            except Exception:
                pass
        return r, ok

    if melody_bank is None:
        melody_bank = MelodyBank(variants_per_cell=4, base_seed=0)

    trace: list[TraceRowV2] = []
    current_rung = initial_rung
    bar_idx_global = 0
    session_start = perf_counter_fn()
    # perf_counter time at which all queued audio will have played
    play_end = session_start

    for seg_idx in range(config.max_segments):
        # 1. HR for this decision: decision-time read, plus (hr_poll_s > 0)
        #    the median of fresh readings polled during the last wait
        now_wall = time_fn()
        reading, instant_fresh = _poll_hr(seg_idx, 'decision')
        instant_bpm = float(reading.bpm) if instant_fresh else None
        n_fresh = 0
        seg_sd = None
        if config.hr_poll_s > 0:
            recent = [b for t, b in hr_window.items()
                      if t >= now_wall - config.hr_window_s]
            hr_window.clear()
            n_fresh = len(recent)
            if len(recent) >= 2:
                seg_sd = statistics.stdev(recent)
            if n_fresh >= config.hr_min_readings:
                fresh, hr_used = True, float(statistics.median(recent))
            else:
                fresh, hr_used = instant_fresh, instant_bpm
        else:
            hr_window.clear()
            n_fresh = 1 if instant_fresh else 0
            fresh, hr_used = instant_fresh, instant_bpm

        if fresh:
            hr_bpm = hr_used
            hr_source_name = getattr(reading, 'source_type', 'unknown')
        else:
            # Fall back to baseline if no HR yet -- lets the controller run cold
            hr_bpm = hr_baseline_bpm
            hr_source_name = None

        # 1b. Target for this segment (phase schedule, if any)
        phase = ''
        seg_target_bpm = hr_target_bpm
        if target_schedule is not None:
            planned_start_s = max(perf_counter_fn(), play_end) - session_start
            scheduled = target_schedule(planned_start_s)
            if scheduled is None:
                break
            phase, seg_target_bpm = scheduled[0], float(scheduled[1])

        # 2. Poll arousal (optional). Poll BEFORE the controller decides so
        #    the current segment's arousal informs the current decision.
        arousal_val: Optional[float] = None
        arousal_src_name: Optional[str] = None
        arousal_t: Optional[float] = None
        if arousal_source is not None:
            try:
                a_reading = arousal_source.poll()
                arousal_val = float(a_reading.value)
                arousal_src_name = getattr(a_reading, 'source_type', 'unknown')
                arousal_t = float(a_reading.t_wall)
            except Exception:
                arousal_val = None

        # 3. Controller decides next rung (or holds it on stale HR)
        if not fresh and config.stale_hr_policy == 'hold':
            decision = controller.hold(
                current_rung=current_rung,
                hr_target=seg_target_bpm,
                hr_base=hr_baseline_bpm,
            )
        else:
            decision = controller.step(
                hr_bpm=hr_bpm,
                hr_target=seg_target_bpm,
                hr_base=hr_baseline_bpm,
                current_rung=current_rung,
                arousal_1_9=arousal_val,
            )

        # 3b. Haptic pacing goal for this segment (the estimator's pacer clips
        #     it to its own safety bounds) and the pacer's last reported state
        haptic_goal = None
        if config.haptic_pacing:
            haptic_goal = seg_target_bpm
            try:
                hr_source.set_goal(haptic_goal)
            except Exception:
                pass
        hstat = {}
        if callable(haptic_status_fn):
            try:
                hstat = haptic_status_fn() or {}
            except Exception:
                hstat = {}
        current_rung = decision.next_rung
        cell = ladder.by_rung[current_rung]
        genre, tier = cell.genre, cell.tier
        # Cell-backed genres (hiphop, rock) pick their internal tier from
        # tempo, so they carry a per-tier tempo; others use tempo_default.
        genre_cfg = GENRE_CFG[genre]
        tempo_bpm = float(genre_cfg.get('tier_tempo', {}).get(tier, genre_cfg['tempo_default']))

        render_t0 = perf_counter_fn()
        if segment_source is None:
            # 3. Pick a seed from the melody bank (rotates on each visit)
            seed = melody_bank.seed_for(genre, tier)

            # 4. Render segment
            audio = renderer.render_segment(
                genre=genre,
                tempo_bpm=tempo_bpm,
                tier=tier,
                n_bars=config.bars_per_segment,
                segment_idx=seed,   # use seed as segment_idx for determinism
            )
            gen_fields = {'generator': 'v1_bank'}
        else:
            # 3-4. Opt-in v2: the cell's next visit from the session source
            #      (it sees only genre and tier), rendered as composed
            from session_generator import trace_fields

            pm, info = segment_source.next_segment(genre, tier)
            if abs(float(info['tempo_bpm']) - tempo_bpm) > 1e-9:
                raise RuntimeError(f"v2 tempo {info['tempo_bpm']} != runner tempo {tempo_bpm} for {genre}{tier}")
            seed = int(info['base_seed'])
            audio = renderer.render_pm(pm)
            gen_fields = {'generator': 'v2_session', **trace_fields(info)}
        render_s = perf_counter_fn() - render_t0

        if config.trim_render_tail:
            fade_frames = int(round(
                bar_duration_frames(tempo_bpm, config.beats_per_bar, config.sample_rate)
                * config.fade_bars))
            keep = config.bars_per_segment * bar_duration_frames(
                tempo_bpm, config.beats_per_bar, config.sample_rate) + fade_frames
            audio = audio[:keep]

        # 5. Crossfade + play. Queued audio plays back-to-back, so this emit
        #    starts when the previously queued audio ends (or now, if drained).
        emit = mixer.push(audio, tempo_bpm=tempo_bpm)
        now_perf = perf_counter_fn()
        queued_ahead_s = max(play_end - now_perf, 0.0)
        play_start = max(now_perf, play_end)
        if emit.shape[0] > 0:
            enqueue_segment(player, emit)
            play_end = play_start + emit.shape[0] / config.sample_rate

        # 6. Emit trace rows (one per bar), timed at when the bars play
        bar_s = _bar_duration_seconds(tempo_bpm, config.beats_per_bar)
        emit_wall = time_fn() + (play_start - now_perf)
        session_t = play_start - session_start
        for bar_i in range(config.bars_per_segment):
            row = TraceRowV2(
                wall_time=emit_wall + bar_i * bar_s,
                session_time=session_t + bar_i * bar_s,
                segment_idx=seg_idx,
                bar_idx_in_segment=bar_i,
                bar_idx_global=bar_idx_global,
                genre=genre,
                tempo_bpm=tempo_bpm,
                tier=tier,
                rung=current_rung,
                seed=seed,
                hr_bpm=hr_bpm if fresh else None,
                hr_target_bpm=seg_target_bpm,
                hr_baseline_bpm=hr_baseline_bpm,
                hr_source=hr_source_name,
                hr_is_fresh=fresh,
                g_hat_bpm=decision.g_hat_bpm,
                governed_r_bpm=decision.governed_r,
                is_unreachable=decision.is_unreachable,
                saturation_state=decision.saturation_state,
                dead_zone_active=decision.dead_zone_active,
                predicted_hr_H=decision.predicted_hr_H,
                effective_error_bpm=decision.effective_error_bpm,
                arousal_1_9=arousal_val,
                arousal_source=arousal_src_name,
                arousal_t_wall=arousal_t,
                control_mode=decision.control_mode,
                mpc_rung=decision.mpc_rung,
                phase=phase,
                hr_n_fresh=n_fresh,
                hr_seg_sd_bpm=seg_sd,
                hr_instant_bpm=instant_bpm,
                haptic_state=str(hstat.get('pacer_state') or hstat.get('haptic_mode') or ''),
                pace_bpm=hstat.get('pace_bpm'),
                haptic_goal_bpm=haptic_goal,
                haptic_goal_eff_bpm=hstat.get('goal_bpm'),
                rr_rpm=hstat.get('rr_rpm'),
                hr_decision_t_wall=now_wall,
                hr_read_t_wall=None if reading is None else float(reading.t_wall),
                cell_u=ladder.by_rung[current_rung].u,
                render_s=render_s,
                planned_s=config.bars_per_segment * bar_s,
                queued_ahead_s=queued_ahead_s if seg_idx else None,
                **gen_fields,
            )
            trace.append(row)
            if trace_writer is not None:
                trace_writer(row)
            bar_idx_global += 1

        if on_segment is not None:
            on_segment(seg_idx, trace[-1])

        # 7. Feedback hook: if the HR source is a closed-loop simulator,
        #    notify it of the applied energy so it can advance its plant.
        #    Real hardware sources ignore this (no .step method).
        step_fn = getattr(hr_source, 'step', None)
        if callable(step_fn):
            step_fn(cell.u)

        # 8. Pace playback: wake render_lead_s before the queue runs dry
        #    (last segment: no next render, so leave the lead for the tail).
        #    With hr_poll_s > 0 the wait is split into polls (bounded count,
        #    so a clock that sleep_fn does not advance cannot spin forever).
        lead_s = config.render_lead_s if seg_idx < config.max_segments - 1 else 0.0
        deadline = play_end - lead_s
        wait_s = deadline - perf_counter_fn()
        if config.hr_poll_s > 0:
            for _ in range(int(math.ceil(max(wait_s, 0.0) / config.hr_poll_s)) + 2):
                remaining = deadline - perf_counter_fn()
                if remaining <= 0:
                    break
                sleep_fn(min(config.hr_poll_s, remaining))
                _poll_hr(seg_idx + 1, 'wait')
                if config.haptic_pacing:
                    try:
                        hr_source.keepalive()
                    except Exception:
                        pass
        elif wait_s > 0:
            sleep_fn(wait_s)

    tail = mixer.flush()
    if tail.shape[0] > 0:
        enqueue_segment(player, tail)
        play_end = max(perf_counter_fn(), play_end) + tail.shape[0] / config.sample_rate
    wait_s = play_end - perf_counter_fn()
    if wait_s > 0:
        sleep_fn(wait_s)

    return trace
