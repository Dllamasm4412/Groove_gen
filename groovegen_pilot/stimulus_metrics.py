"""
Stimulus metrics for GrooveGen segments: repetition and controlled features.

Pure functions over one generated segment (pretty_midi.PrettyMIDI) or pairs of
segments. MIDI only: fast, deterministic, renderer-independent. Used by
stimulus_audit.py to baseline the v1 bank generator and, later, to check a
controlled-variation generator against the same numbers
(LIVE_GENERATION_PLAN.md sections 2-3).

Feature classes
---------------
LOCKED_FEATURES    must be identical for every segment of a (genre, tier) cell
                   (tempo, instrumentation, length).
BOUNDED_FEATURES   may move between segments of a cell but must stay inside
                   the cell's measured envelope (drum density, velocity,
                   onset rates, register).
BOUNDED_SET_FEATURES
                   set-valued; each segment's set must be a subset of the
                   cell's allowed set (union over the v1 bank variants).
                   Drum voices live here: v1 already picks a different drum
                   pattern (ride vs hat, clap vs snare) per bank seed, so
                   they are not constant within a cell (audit 2026-09-29).
FREE_FEATURES      where variation is allowed to live; not bounded, measured
                   only through the repetition metrics below.
REPETITION_METRICS R1-R7 of LIVE_GENERATION_PLAN.md section 2.

Conventions
-----------
- Bars are 4/4 at the segment's single played tempo; bar b covers
  [b * bar_s, (b + 1) * bar_s).
- An onset is (track key, pitch, grid position), grid = GRID_PER_BAR steps
  per bar. Velocity and duration are excluded, so accent-only changes do not
  count as variation.
- Drum layer = drum tracks; pitched layer = all non-drum tracks.
"""

from __future__ import annotations

import hashlib
import io
from typing import Iterable, Optional

import numpy as np
import pretty_midi

GRID_PER_BAR = 48          # 16ths and 8th-note triplets both land on the grid
BEATS_PER_BAR = 4
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
PC_NAMES = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')

# =============================================================================
# Feature classes
# =============================================================================

LOCKED_FEATURES: dict[str, str] = {
    'played_tempo_bpm': 'single tempo from the MIDI tempo map; must equal the planned cell tempo',
    'n_tempo_changes': 'number of tempo-map entries; must be 1',
    'n_bars': 'segment length in bars (last onset bar + 1)',
    'programs': 'sorted GM programs of the pitched tracks (instrumentation)',
}

BOUNDED_SET_FEATURES: dict[str, str] = {
    'drum_voices': 'sorted GM drum pitches used; must be a subset of the cell allowed set',
}

BOUNDED_FEATURES: dict[str, str] = {
    # From music_features_measured.midi_features (same 20 ms onset merge the
    # energy table uses)
    'drum_rate': 'distinct drum onsets per second',
    'drum_low_rate': 'kick onsets per second',
    'drum_backbeat_rate': 'snare/clap onsets per second',
    'drum_hats_rate': 'hat/cymbal onsets per second',
    'drum_hand_rate': 'other percussion onsets per second',
    'note_rate': 'distinct onsets per second, all tracks',
    # Added here
    'drum_onbeat_ratio': 'share of drum onsets on quarter-note beats (feel / accent placement)',
    'vel_mean': 'mean velocity, all notes',
    'vel_p90': '90th percentile velocity, all notes',
    'drum_vel_mean': 'mean velocity, drum notes',
    'pitched_vel_mean': 'mean velocity, pitched notes',
    'pitched_pitch_median': 'median MIDI pitch, pitched notes (register)',
    'pitched_pitch_p05': '5th percentile pitch, pitched notes',
    'pitched_pitch_p95': '95th percentile pitch, pitched notes',
}

FREE_FEATURES: dict[str, str] = {
    'drum_micro_variation': 'count-neutral per-bar drum changes that keep the genre skeleton',
    'phrase_end_fills': 'drum fills at bars 4 and 8 replacing, not adding, notes',
    'progression_choice': "choice among the genre's existing progressions",
    'bass_pattern_choice': "choice among the genre's existing bass patterns",
    'voicing_choice': 'voicing / octave / arpeggio direction within the register bound',
    'motif_transformation': 'displacement, ornament, cadence changes of the top line',
    'phrase_endings': 'hold vs restate at phrase ends',
}

REPETITION_METRICS: dict[str, str] = {
    'R1_distinct_drum_bars': 'unique drum-bar onset sets among the 8 bars',
    'R2_max_identical_drum_run': 'longest run of consecutive identical drum bars',
    'R3_exact_repeat_distance': 'segments since the last identical segment (content hash), per layer',
    'R4_near_repeat_similarity': 'shift-tolerant bar Jaccard vs the previous visit to the same cell',
    'R5_motif_distance': 'normalized edit distance of the top-line 2-bar motif vs the previous visit',
    'R6_phrase_marking': 'bar 4 / bar 8 drums differ from the bars 1 and 2 before them '
                         '(period-aware: a 2-bar clave is not a fill); phrase 1 != phrase 2',
    'R7_key_change': 'tonal collection differs from the previous segment of the same genre',
}

# =============================================================================
# Bar grid
# =============================================================================


def played_tempo(pm: pretty_midi.PrettyMIDI) -> float:
    return float(pm.get_tempo_changes()[1][0])


def bar_seconds(tempo_bpm: float) -> float:
    return 60.0 / tempo_bpm * BEATS_PER_BAR


def _track_key(idx: int, inst: pretty_midi.Instrument) -> tuple:
    # Index keeps two tracks with the same program apart (hiphop: two pianos)
    return ('drum', idx) if inst.is_drum else ('pitched', idx, int(inst.program))


def _grid(start: float, bar_s: float) -> tuple[int, int]:
    """(bar index, grid position) of an onset; snaps bar-end onsets forward."""
    pos_f = start / bar_s * GRID_PER_BAR
    step = int(round(pos_f))
    return step // GRID_PER_BAR, step % GRID_PER_BAR


def bar_onset_sets(pm: pretty_midi.PrettyMIDI, n_bars: int, layer: str = 'all',
                   tempo_bpm: Optional[float] = None) -> list[frozenset]:
    """One frozenset of (track key, pitch, grid pos) per bar. layer: all | drum | pitched."""
    if layer not in ('all', 'drum', 'pitched'):
        raise ValueError(f'unknown layer {layer!r}')
    bar_s = bar_seconds(tempo_bpm or played_tempo(pm))
    bars: list[set] = [set() for _ in range(n_bars)]
    for idx, inst in enumerate(pm.instruments):
        if layer == 'drum' and not inst.is_drum:
            continue
        if layer == 'pitched' and inst.is_drum:
            continue
        key = _track_key(idx, inst)
        for n in inst.notes:
            b, pos = _grid(n.start, bar_s)
            if 0 <= b < n_bars:
                bars[b].add((key, int(n.pitch), pos))
    return [frozenset(b) for b in bars]


def n_bars_played(pm: pretty_midi.PrettyMIDI) -> int:
    bar_s = bar_seconds(played_tempo(pm))
    starts = [n.start for inst in pm.instruments for n in inst.notes]
    return (max(_grid(s, bar_s)[0] for s in starts) + 1) if starts else 0


# =============================================================================
# Within-segment repetition (R1, R2, R6)
# =============================================================================


def distinct_bars(sets: list[frozenset]) -> int:
    return len(set(sets))


def max_identical_run(sets: list[frozenset]) -> int:
    best = run = 0
    prev = None
    for s in sets:
        run = run + 1 if s == prev else 1
        best = max(best, run)
        prev = s
    return best


def bar_period(sets: list[frozenset]) -> int:
    """Smallest p in (1, 2, 4) with sets[i] == sets[i - p] for every i >= p;
    len(sets) if none (e.g. a crash on bar 1 only, or a fill)."""
    for p in (1, 2, 4):
        if p < len(sets) and all(sets[i] == sets[i - p] for i in range(p, len(sets))):
            return p
    return len(sets)


def _phrase_end_marked(sets: list[frozenset], end: int) -> bool:
    """True if bar `end` differs from both of the two bars before it.

    Comparing against lag 1 and lag 2 keeps a 2-bar ostinato (latin clave
    3-2 / 2-3) from reading as a fill, and a bar-1 crash from reading as a
    marked bar 4. A fill repeated at bars 4 and 8 still counts at both.
    """
    if end >= len(sets) or end < 1:
        return False
    return all(sets[end] != sets[end - lag] for lag in (1, 2) if end - lag >= 0)


def phrase_metrics(drum_sets: list[frozenset], all_sets: list[frozenset]) -> dict:
    """R6 for an 8-bar segment of two 4-bar phrases (0-based bars 3 and 7 end them)."""
    return {
        'phrase_end_bar4_marked': _phrase_end_marked(drum_sets, 3),
        'phrase_end_bar8_marked': _phrase_end_marked(drum_sets, 7),
        'phrase_contrast': tuple(all_sets[0:4]) != tuple(all_sets[4:8]),
        'drum_period': bar_period(drum_sets),
    }


# =============================================================================
# Cross-segment similarity (R4, R5)
# =============================================================================


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def near_repeat_similarity(a_sets: list[frozenset], b_sets: list[frozenset]) -> float:
    """Mean over bars of b of the best Jaccard match among bars of a (R4).

    Shift-tolerant: a bar of b that reappears anywhere in a counts as a
    repeat. 1.0 = every bar of b occurs somewhere in a.
    """
    if not b_sets or not a_sets:
        return float('nan')
    return float(np.mean([max(_jaccard(x, y) for y in a_sets) for x in b_sets]))


def top_line_track(pm: pretty_midi.PrettyMIDI) -> Optional[int]:
    """Index of the pitched track with the highest median pitch (the motif carrier)."""
    best, best_med = None, -1.0
    for idx, inst in enumerate(pm.instruments):
        if inst.is_drum or not inst.notes:
            continue
        med = float(np.median([n.pitch for n in inst.notes]))
        if med > best_med:
            best, best_med = idx, med
    return best


def motif_signature(pm: pretty_midi.PrettyMIDI, bars: int = 2,
                    track: Optional[int] = None) -> tuple:
    """Transposition-invariant (grid pos, interval) skyline of the first `bars` bars.

    Skyline = highest note per onset position on the top-line track.
    """
    if track is None:
        track = top_line_track(pm)
    if track is None:
        return ()
    bar_s = bar_seconds(played_tempo(pm))
    top: dict[int, int] = {}
    for n in pm.instruments[track].notes:
        b, pos = _grid(n.start, bar_s)
        if 0 <= b < bars:
            step = b * GRID_PER_BAR + pos
            top[step] = max(top.get(step, -1), int(n.pitch))
    steps = sorted(top)
    sig, prev = [], None
    for s in steps:
        sig.append((s, 0 if prev is None else top[s] - prev))
        prev = top[s]
    return tuple(sig)


def edit_distance_norm(a: tuple, b: tuple) -> float:
    """Levenshtein distance / max length (0 = identical, 1 = nothing shared)."""
    if not a and not b:
        return 0.0
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1] / max(len(a), len(b))


# =============================================================================
# Tonal collection (R7)
# =============================================================================


def tonal_collection(pm: pretty_midi.PrettyMIDI) -> tuple[Optional[int], float]:
    """(pitch class of the best-fitting major scale, fit share) over pitched notes.

    Duration-weighted pitch-class histogram matched against the 12 major-scale
    collections; relative major and minor are the same collection. Ties take
    the lowest pitch class (deterministic). None if there are no pitched notes.
    """
    hist = np.zeros(12)
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            hist[n.pitch % 12] += max(n.end - n.start, 1e-3)
    total = hist.sum()
    if total <= 0:
        return None, 0.0
    scores = [sum(hist[(root + d) % 12] for d in MAJOR_SCALE) for root in range(12)]
    root = int(np.argmax(scores))
    return root, float(scores[root] / total)


# =============================================================================
# Locked and bounded features
# =============================================================================


def locked_signature(pm: pretty_midi.PrettyMIDI) -> dict:
    return {
        'played_tempo_bpm': round(played_tempo(pm), 3),
        'n_tempo_changes': int(len(pm.get_tempo_changes()[1])),
        'n_bars': n_bars_played(pm),
        'programs': sorted(int(i.program) for i in pm.instruments if not i.is_drum),
    }


def bounded_set_features(pm: pretty_midi.PrettyMIDI) -> dict:
    return {
        'drum_voices': sorted({int(n.pitch) for i in pm.instruments if i.is_drum for n in i.notes}),
    }


def set_within(values: Iterable, allowed: Iterable) -> bool:
    """BOUNDED_SET_FEATURES check: every value is in the cell's allowed set."""
    return set(values) <= set(allowed)


def bounded_features(pm: pretty_midi.PrettyMIDI, n_bars: int) -> dict:
    """BOUNDED_FEATURES for one segment over its nominal n_bars duration."""
    from music_features_measured import midi_features

    tempo = played_tempo(pm)
    dur_s = n_bars * bar_seconds(tempo)
    out = midi_features(pm, dur_s)

    bar_s = bar_seconds(tempo)
    drum_pos = {(_grid(n.start, bar_s)) for i in pm.instruments if i.is_drum for n in i.notes}
    onbeat = sum(1 for _, pos in drum_pos if pos % (GRID_PER_BAR // BEATS_PER_BAR) == 0)
    out['drum_onbeat_ratio'] = onbeat / len(drum_pos) if drum_pos else float('nan')

    vel = [n.velocity for i in pm.instruments for n in i.notes]
    dvel = [n.velocity for i in pm.instruments if i.is_drum for n in i.notes]
    pnotes = [n for i in pm.instruments if not i.is_drum for n in i.notes]
    out['vel_mean'] = float(np.mean(vel)) if vel else float('nan')
    out['vel_p90'] = float(np.percentile(vel, 90)) if vel else float('nan')
    out['drum_vel_mean'] = float(np.mean(dvel)) if dvel else float('nan')
    out['pitched_vel_mean'] = float(np.mean([n.velocity for n in pnotes])) if pnotes else float('nan')
    pitches = [n.pitch for n in pnotes]
    for key, q in (('pitched_pitch_median', 50), ('pitched_pitch_p05', 5), ('pitched_pitch_p95', 95)):
        out[key] = float(np.percentile(pitches, q)) if pitches else float('nan')
    return {k: out[k] for k in BOUNDED_FEATURES}


# =============================================================================
# Hashes
# =============================================================================


def midi_sha256(pm: pretty_midi.PrettyMIDI) -> str:
    """sha256 of the MIDI file bytes pretty_midi writes."""
    buf = io.BytesIO()
    pm.write(buf)
    return hashlib.sha256(buf.getvalue()).hexdigest()


def content_sha(sets: Iterable[frozenset]) -> str:
    """Order-sensitive hash of per-bar onset sets (ignores velocity, duration, metadata)."""
    h = hashlib.sha256()
    for s in sets:
        h.update(repr(sorted(s)).encode())
        h.update(b'|')
    return h.hexdigest()[:16]


# =============================================================================
# One-segment summary
# =============================================================================


def segment_metrics(pm: pretty_midi.PrettyMIDI, n_bars: int = 8) -> dict:
    """Everything the audit needs from one segment, plus the raw sets and motif
    (keys starting with '_') for cross-segment comparisons."""
    drum = bar_onset_sets(pm, n_bars, 'drum')
    pitched = bar_onset_sets(pm, n_bars, 'pitched')
    all_ = bar_onset_sets(pm, n_bars, 'all')
    key_pc, key_fit = tonal_collection(pm)
    top = top_line_track(pm)
    out = {
        'midi_sha256': midi_sha256(pm),
        'content_sha': content_sha(all_),
        'drum_sha': content_sha(drum),
        'pitched_sha': content_sha(pitched),
        'distinct_bars_all': distinct_bars(all_),
        'distinct_drum_bars': distinct_bars(drum),
        'distinct_pitched_bars': distinct_bars(pitched),
        'max_identical_drum_run': max_identical_run(drum),
        'max_identical_all_run': max_identical_run(all_),
        **phrase_metrics(drum, all_),
        'key_pc': key_pc,
        'key_name': None if key_pc is None else PC_NAMES[key_pc],
        'key_fit': key_fit,
        'motif_track': None if top is None else pm.instruments[top].name,
    }
    out.update(locked_signature(pm))
    out.update(bounded_set_features(pm))
    out.update(bounded_features(pm, n_bars))
    out['_drum_sets'] = drum
    out['_pitched_sets'] = pitched
    out['_all_sets'] = all_
    out['_motif'] = motif_signature(pm, track=top)
    return out
