"""
Closed-loop run_session for GrooveGen pilot (M0.5 Step 5).

This is the nested control loop that wires together:
    HR source (Step 2) -> tier policy -> composer/renderer (Step 1) ->
    crossfade mixer (Step 4) -> player (Step 3)

Loop structure (locked design):
    OUTER: control per segment
        Read HR once per segment. Decide tier. Render segment. Push
        through crossfade mixer. Enqueue to player.
    INNER: trace per bar
        For each bar within the just-rendered segment, emit a trace
        row with wall_time, session_time, segment_idx, bar_idx_in_segment,
        genre, tempo_bpm, tier, hr_bpm, hr_source, hr_is_fresh.

The genre schedule is provided by the caller (a simple list). This module
does NOT decide genre — that's a downstream concern (probably a scheduler
tied to session phase or user selection). Tier IS controlled by HR here.

Public API
----------
    SessionConfig
        Immutable session parameters: schedule, bars_per_segment,
        session_seed, sample_rate, hr_stale_seconds.

    TraceRow (NamedTuple)
        One row per bar of playback.

    run_session(
        hr_source, renderer, player, mixer, tier_policy, config,
        segments_max=None, trace_writer=None,
    ) -> list[TraceRow]

        Runs the outer loop until either the schedule is exhausted or
        segments_max is reached. Trace rows are appended to the return
        list AND (if trace_writer is provided) fed to trace_writer.write().

Design decisions locked in this file
-----------------------------------
    - Tier policy = LinearBandPolicy (option A) — swappable via TierPolicy
    - HR is sampled ONCE per segment, at the start
    - If HR reading is missing or stale (>hr_stale_seconds old), fall back
      to the last-known tier (or tier 3 if no prior)
    - Segment index is monotonic starting at 0
    - Bar-level HR values in trace rows are the SAME reading used for tier
      decision (we do not re-sample per bar — that's what the "control per
      segment" decision means)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Protocol, Sequence, Callable, NamedTuple

import numpy as np

from composer import GENRE_CFG
from crossfade import CrossfadeMixer
from renderer_to_player import enqueue_segment
from hr_to_tier import TierPolicy, LinearBandPolicy


class HRSourceProtocol(Protocol):
    """Any HR source with .read() returning an HRReading-like NamedTuple."""
    def read(self): ...


class TraceRow(NamedTuple):
    wall_time: float          # unix timestamp when this bar's audio was enqueued
    session_time: float       # seconds since session start
    segment_idx: int
    bar_idx_in_segment: int   # 0-indexed within the segment
    bar_idx_global: int       # 0-indexed across the whole session
    genre: str
    tempo_bpm: float
    tier: int
    hr_bpm: Optional[float]   # None if no HR was available at segment start
    hr_source: Optional[str]  # 'replay' | 'synth_sine' | 'manual' | ...
    hr_is_fresh: bool         # False if we used the last-known tier fallback


@dataclass(frozen=True)
class SessionConfig:
    schedule: Sequence[tuple[str, float]]  # [(genre, tempo_bpm), ...]
    bars_per_segment: int = 8
    session_seed: int = 42
    sample_rate: int = 44100
    beats_per_bar: int = 4
    hr_stale_seconds: float = 3.0  # readings older than this trigger fallback
    fallback_tier: int = 3  # used before any HR reading arrives


def _hr_reading_is_fresh(reading, now: float, stale_s: float) -> bool:
    """A reading is fresh if it exists and its t_wall is within stale_s of now."""
    if reading is None:
        return False
    # HRReading has attribute is_fresh AND t_wall; enforce both age and self-report
    if not getattr(reading, 'is_fresh', True):
        return False
    age = now - float(reading.t_wall)
    return age <= stale_s


def _bar_duration_seconds(tempo_bpm: float, beats_per_bar: int = 4) -> float:
    return (60.0 / tempo_bpm) * beats_per_bar


def run_session(
    hr_source: HRSourceProtocol,
    renderer,
    player,
    mixer: CrossfadeMixer,
    tier_policy: TierPolicy,
    config: SessionConfig,
    *,
    segments_max: Optional[int] = None,
    trace_writer: Optional[Callable[[TraceRow], None]] = None,
    on_segment: Optional[Callable[[int, str, int, Optional[float]], None]] = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.time,
    perf_counter_fn: Callable[[], float] = time.perf_counter,
) -> list[TraceRow]:
    """
    Run the closed-loop session. See module docstring for full semantics.

    Parameters
    ----------
    hr_source : object with .read() returning HRReading-like NamedTuple
    renderer  : SymbolicSegmentRenderer (or any object with .render_segment)
    player    : PlayerBase (NullPlayer or SoundDevicePlayer)
    mixer     : CrossfadeMixer
    tier_policy : TierPolicy (LinearBandPolicy or any .decide(hr_bpm)->int)
    config    : SessionConfig
    segments_max : max number of segments to play (None = play the whole schedule)
    trace_writer : optional callback receiving each TraceRow as it's produced
    on_segment : optional callback(segment_idx, genre, tier, hr_bpm) called after
                 each segment is rendered but before playback (useful for prints)
    sleep_fn, time_fn, perf_counter_fn : injectable clocks for testing

    Returns
    -------
    list[TraceRow]
    """
    trace: list[TraceRow] = []
    last_known_tier: Optional[int] = None
    session_start = perf_counter_fn()
    bar_idx_global = 0

    n_segments = len(config.schedule)
    if segments_max is not None:
        n_segments = min(n_segments, segments_max)

    for seg_idx in range(n_segments):
        genre, tempo_bpm = config.schedule[seg_idx]

        # 1. Read HR ONCE per segment
        now_wall = time_fn()
        reading = None
        try:
            reading = hr_source.read()
        except Exception:
            reading = None
        fresh = _hr_reading_is_fresh(reading, now_wall, config.hr_stale_seconds)

        # 2. Decide tier
        if fresh and reading is not None:
            hr_bpm = float(reading.bpm)
            hr_source_name = getattr(reading, 'source_type', 'unknown')
            tier = tier_policy.decide(hr_bpm)
            last_known_tier = tier
        else:
            hr_bpm = None
            hr_source_name = None
            if last_known_tier is not None:
                tier = last_known_tier
            else:
                tier = config.fallback_tier

        # 3. Render the segment
        audio = renderer.render_segment(
            genre=genre,
            tempo_bpm=tempo_bpm,
            tier=tier,
            n_bars=config.bars_per_segment,
            segment_idx=seg_idx,
        )

        # 4. Notify (for interactive prints)
        if on_segment is not None:
            on_segment(seg_idx, genre, tier, hr_bpm)

        # 5. Push through crossfade mixer -> player
        emit = mixer.push(audio, tempo_bpm=tempo_bpm)
        if emit.shape[0] > 0:
            enqueue_segment(player, emit)

        # 6. Emit one trace row per bar of THIS segment
        bar_s = _bar_duration_seconds(tempo_bpm, config.beats_per_bar)
        emit_wall = time_fn()
        for bar_i in range(config.bars_per_segment):
            row = TraceRow(
                wall_time=emit_wall + bar_i * bar_s,
                session_time=(perf_counter_fn() - session_start) + bar_i * bar_s,
                segment_idx=seg_idx,
                bar_idx_in_segment=bar_i,
                bar_idx_global=bar_idx_global,
                genre=genre,
                tempo_bpm=tempo_bpm,
                tier=tier,
                hr_bpm=hr_bpm,
                hr_source=hr_source_name,
                hr_is_fresh=fresh,
            )
            trace.append(row)
            if trace_writer is not None:
                trace_writer(row)
            bar_idx_global += 1

        # 7. Sleep for the emitted audio's duration so playback stays in sync
        #    with the tempo (skipped for NullPlayer; sleep_fn can be a no-op).
        if emit.shape[0] > 0:
            sleep_fn(emit.shape[0] / config.sample_rate)

    # Flush the mixer's held tail so the last segment finishes cleanly
    tail = mixer.flush()
    if tail.shape[0] > 0:
        enqueue_segment(player, tail)
        sleep_fn(tail.shape[0] / config.sample_rate)

    return trace
