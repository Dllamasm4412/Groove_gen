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

import time
from dataclasses import dataclass
from typing import Callable, NamedTuple, Optional, Sequence

from crossfade import CrossfadeMixer
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


@dataclass(frozen=True)
class SessionConfigV2:
    bars_per_segment: int = 8
    sample_rate: int = 44100
    beats_per_bar: int = 4
    hr_stale_seconds: float = 3.0
    fade_bars: float = 0.25              # QUARTER BAR per user request
    max_segments: int = 24
    # Tempo policy: if the controller picks a genre, we use the genre's
    # tempo_default from GENRE_CFG (imported from composer).
    # A future extension could allow tempo modulation within a genre.


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
    melody_bank: Optional[MelodyBank] = None,
    arousal_source=None,
    trace_writer: Optional[Callable[[TraceRowV2], None]] = None,
    on_segment: Optional[Callable[[int, TraceRowV2], None]] = None,
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
    melody_bank    : optional MelodyBank; if None, one is created with N=4

    Returns
    -------
    list[TraceRowV2]
    """
    from composer import GENRE_CFG  # local to keep top-level import cheap

    if melody_bank is None:
        melody_bank = MelodyBank(variants_per_cell=4, base_seed=0)

    trace: list[TraceRowV2] = []
    current_rung = initial_rung
    bar_idx_global = 0
    session_start = perf_counter_fn()

    for seg_idx in range(config.max_segments):
        # 1. Read HR once per segment
        now_wall = time_fn()
        reading = None
        try:
            reading = hr_source.read()
        except Exception:
            reading = None
        fresh = _hr_reading_is_fresh(reading, now_wall, config.hr_stale_seconds)

        if fresh and reading is not None:
            hr_bpm = float(reading.bpm)
            hr_source_name = getattr(reading, 'source_type', 'unknown')
        else:
            # Fall back to baseline if no HR yet -- lets the controller run cold
            hr_bpm = hr_baseline_bpm
            hr_source_name = None

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

        # 3. Controller decides next rung
        decision = controller.step(
            hr_bpm=hr_bpm,
            hr_target=hr_target_bpm,
            hr_base=hr_baseline_bpm,
            current_rung=current_rung,
            arousal_1_9=arousal_val,
        )
        current_rung = decision.next_rung
        cell = ladder.by_rung[current_rung]
        genre, tier = cell.genre, cell.tier
        tempo_bpm = float(GENRE_CFG[genre]['tempo_default'])

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

        # 5. Crossfade + play
        emit = mixer.push(audio, tempo_bpm=tempo_bpm)
        if emit.shape[0] > 0:
            enqueue_segment(player, emit)

        # 6. Emit trace rows (one per bar)
        bar_s = _bar_duration_seconds(tempo_bpm, config.beats_per_bar)
        emit_wall = time_fn()
        session_t = perf_counter_fn() - session_start
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
                hr_target_bpm=hr_target_bpm,
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

        # 8. Pace playback
        if emit.shape[0] > 0:
            sleep_fn(emit.shape[0] / config.sample_rate)

    tail = mixer.flush()
    if tail.shape[0] > 0:
        enqueue_segment(player, tail)
        sleep_fn(tail.shape[0] / config.sample_rate)

    return trace
