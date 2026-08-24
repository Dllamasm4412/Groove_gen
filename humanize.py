"""GrooveGen deterministic humanization pass.

Post-processes a pretty_midi.PrettyMIDI object in place with:

  1. **Velocity shaping** — replaces the uniform per-note velocity constants that
     make current bed renders sound "programmed":
       * Accent map: notes falling on beat 1 or 3 (strong beats) get +10; beats
         2 or 4 (backbeat) get +5; off-beat 8ths get -8; 16th subdivisions get
         -12 (ghost-note tier).
       * Per-track velocity band: each instrument gets its own [vmin, vmax]
         window applied on top of the accent map, so a pad stays quiet even on
         downbeats.
       * Alternation for repeating comp figures: consecutive comp notes at the
         same pitch alternate strong/weak by ±5.
  2. **Timing jitter** — seeded ±jitter_ms Gaussian nudge on note start times
     (default σ = 6 ms, hard-clipped at ±14 ms). Deterministic under a fixed
     seed so every trace row is reproducible; nudge sizes match production
     literature (Cue, Splice guides cite ±5–15 ms).
  3. **Micro-swing (optional)** — pushes off-beat 8ths by +swing_ms so straight
     8ths feel less mechanical without moving into full triplet swing.

Non-goals:
  * No pitch changes, no chord re-voicing, no note deletion/insertion.
  * Runtime-safe: pure numpy + stdlib random, no I/O, no ML.
  * Trace-friendly: returns a summary dict caller can append to the trace
    schema (op = "humanize_v1", seed, params_hash).

Design guardrails (per council synthesis):
  * Deterministic under seed: same MIDI + same seed => byte-identical output.
  * Additive: never *removes* micro-timing, only nudges. Grid-quantized input
     stays close to the grid; already-swung input is not over-swung.
  * Trace-append-only compatible: caller records op-descriptor, not per-note
     deltas.

Usage:
    from humanize import humanize, HumanizeParams
    from symbolic_bed_proto import build_pop
    midi = build_pop()
    summary = humanize(midi, seed=42, params=HumanizeParams.POP)
    # midi is now humanized in place; summary describes what was applied.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field

import numpy as np
import pretty_midi as pm


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HumanizeParams:
    """Humanization parameters. All defaults are conservative."""

    # Velocity accents (added to notes falling on the corresponding grid)
    accent_beat_1_3: int = 10   # strong beats
    accent_beat_2_4: int = 5    # backbeat
    accent_offbeat_8: int = -8  # "&" of any beat
    accent_offbeat_16: int = -12  # 16th subdivisions between 8ths

    # Alternation for repeated-pitch comp figures (successive same-pitch notes)
    alt_strong_delta: int = +4
    alt_weak_delta: int = -4

    # Timing jitter (seeded Gaussian, hard-clipped)
    jitter_sigma_ms: float = 6.0
    jitter_clip_ms: float = 14.0

    # Micro-swing (push off-beat 8ths later by this many ms; 0 disables)
    swing_ms: float = 0.0

    # Velocity band clamp per-track (applied AFTER accents). Keys are substrings
    # matched (case-insensitive) against Instrument.name; first match wins.
    # None means don't clamp.
    velocity_bands: dict[str, tuple[int, int]] | None = None

    # Presets --------------------------------------------------------------

    @staticmethod
    def POP() -> "HumanizeParams":
        """Pop preset: light swing, Rhodes/strings/bass velocity discipline."""
        return HumanizeParams(
            accent_beat_1_3=10,
            accent_beat_2_4=6,
            accent_offbeat_8=-6,
            accent_offbeat_16=-10,
            alt_strong_delta=+4,
            alt_weak_delta=-4,
            jitter_sigma_ms=6.0,
            jitter_clip_ms=14.0,
            swing_ms=4.0,
            velocity_bands={
                "rhodes": (48, 92),
                "comp": (48, 92),      # legacy: build_pop's comp instrument
                "strings": (30, 58),   # strings live in the pad slot; keep them soft
                "pad": (30, 58),
                "bass": (72, 100),
            },
        )

    @staticmethod
    def RNB() -> "HumanizeParams":
        """R&B: deeper swing, ghost bass respected, sustained Rhodes."""
        return HumanizeParams(
            accent_beat_1_3=8,
            accent_beat_2_4=6,
            accent_offbeat_8=-5,
            accent_offbeat_16=-10,
            alt_strong_delta=+3,
            alt_weak_delta=-3,
            jitter_sigma_ms=8.0,
            jitter_clip_ms=16.0,
            swing_ms=8.0,
            velocity_bands={
                "rhodes": (44, 82),
                "bass": (58, 92),
            },
        )

    @staticmethod
    def SALSA() -> "HumanizeParams":
        """Salsa: tight timing (small jitter), strong clave accents, no swing."""
        return HumanizeParams(
            accent_beat_1_3=8,
            accent_beat_2_4=4,
            accent_offbeat_8=-4,
            accent_offbeat_16=-8,
            alt_strong_delta=+3,
            alt_weak_delta=-3,
            jitter_sigma_ms=3.5,   # salsa is precise
            jitter_clip_ms=8.0,
            swing_ms=0.0,          # clave is straight
            velocity_bands={
                "montuno": (66, 100),
                "tumbao": (78, 104),
                "bass": (78, 104),
                "horn": (82, 108),
            },
        )

    @staticmethod
    def CALM() -> "HumanizeParams":
        """Calm: very light everything; barely humanized to stay ambient."""
        return HumanizeParams(
            accent_beat_1_3=4,
            accent_beat_2_4=2,
            accent_offbeat_8=-3,
            accent_offbeat_16=-5,
            alt_strong_delta=+2,
            alt_weak_delta=-2,
            jitter_sigma_ms=8.0,   # slower feel tolerates more drift
            jitter_clip_ms=20.0,
            swing_ms=0.0,
            velocity_bands={
                "pad": (34, 52),
                "ep": (36, 58),
                "bass": (52, 74),
            },
        )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------


def _params_hash(params: HumanizeParams) -> str:
    """Stable short hash of params for trace/version pinning."""
    payload = json.dumps(asdict(params), sort_keys=True, default=str).encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def _spb_of(midi: pm.PrettyMIDI) -> float:
    """Seconds per beat from the MIDI's initial tempo (fallback 120 BPM)."""
    try:
        _, tempi = midi.get_tempo_changes()
        bpm = float(tempi[0]) if len(tempi) else 120.0
    except Exception:
        bpm = 120.0
    if bpm <= 0:
        bpm = 120.0
    return 60.0 / bpm


def _accent_delta(start_beat: float, params: HumanizeParams, eps: float = 0.02) -> int:
    """Return velocity delta for a note whose start (in beats within its bar) is start_beat.

    Grid detection:
      - within eps of an integer beat and beat is 0 or 2 (bars are 4-beat): strong
      - within eps of an integer beat and beat is 1 or 3: backbeat
      - within eps of x.5 (any beat + 0.5): off-beat 8th
      - within eps of x.25 or x.75: off-beat 16th
      - otherwise: 0 (already off-grid, let it be)
    """
    bar_pos = start_beat % 4.0
    frac = bar_pos - int(bar_pos)
    beat_idx = int(bar_pos)

    def near(x: float, target: float) -> bool:
        return abs(x - target) < eps

    if near(frac, 0.0) or near(frac, 1.0):
        # on the beat
        if beat_idx in (0, 2):
            return params.accent_beat_1_3
        else:
            return params.accent_beat_2_4
    if near(frac, 0.5):
        return params.accent_offbeat_8
    if near(frac, 0.25) or near(frac, 0.75):
        return params.accent_offbeat_16
    return 0


def _velocity_band_for(instr_name: str, params: HumanizeParams) -> tuple[int, int] | None:
    if not params.velocity_bands:
        return None
    name_l = (instr_name or "").lower()
    for key, band in params.velocity_bands.items():
        if key.lower() in name_l:
            return band
    return None


def humanize(
    midi: pm.PrettyMIDI,
    seed: int = 0,
    params: HumanizeParams | None = None,
) -> dict:
    """Apply humanization to midi in place. Returns a trace-friendly summary."""
    if params is None:
        params = HumanizeParams()
    rng = random.Random(seed)  # deterministic
    np_rng = np.random.default_rng(seed)

    spb = _spb_of(midi)
    jitter_sigma_s = params.jitter_sigma_ms / 1000.0
    jitter_clip_s = params.jitter_clip_ms / 1000.0
    swing_s = params.swing_ms / 1000.0

    total_notes = 0
    total_shifted = 0
    per_track = []

    for instr in midi.instruments:
        if instr.is_drum:
            # Drums are the controller's job (per module docstring); leave alone.
            per_track.append({"name": instr.name, "notes": len(instr.notes), "touched": False})
            continue

        band = _velocity_band_for(instr.name, params)
        prev_pitch = None
        prev_strong = False
        touched = 0

        # Pre-sort notes by start so alternation walks the timeline.
        instr.notes.sort(key=lambda n: n.start)

        # Pre-draw jitter deltas for reproducibility given seed.
        jitters = np_rng.normal(0.0, jitter_sigma_s, size=len(instr.notes))
        jitters = np.clip(jitters, -jitter_clip_s, jitter_clip_s)

        for i, n in enumerate(instr.notes):
            start_beat = n.start / spb
            delta = _accent_delta(start_beat, params)

            # Alternation on repeated same-pitch comp figures
            if prev_pitch == n.pitch:
                if prev_strong:
                    delta += params.alt_weak_delta
                    prev_strong = False
                else:
                    delta += params.alt_strong_delta
                    prev_strong = True
            else:
                prev_strong = False
            prev_pitch = n.pitch

            new_vel = int(n.velocity) + delta
            if band is not None:
                new_vel = int(np.clip(new_vel, band[0], band[1]))
            new_vel = int(np.clip(new_vel, 1, 127))
            n.velocity = new_vel

            # Timing: jitter + optional swing on off-beat 8ths
            bar_pos = start_beat % 4.0
            frac = bar_pos - int(bar_pos)
            add = float(jitters[i])
            if swing_s > 0.0 and abs(frac - 0.5) < 0.02:
                add += swing_s
            new_start = max(0.0, n.start + add)
            duration = n.end - n.start
            n.start = new_start
            n.end = new_start + duration
            touched += 1

        per_track.append({"name": instr.name, "notes": len(instr.notes), "touched": touched})
        total_notes += len(instr.notes)
        total_shifted += touched

    return {
        "op": "humanize_v1",
        "seed": seed,
        "params_hash": _params_hash(params),
        "params": asdict(params),
        "spb": spb,
        "notes_total": total_notes,
        "notes_touched": total_shifted,
        "per_track": per_track,
    }


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Build a tiny synthetic MIDI (4 bars @ 120 BPM, quarter-note chord stabs)
    # to prove humanization runs deterministically and modifies notes.
    midi = pm.PrettyMIDI(initial_tempo=120)
    inst = pm.Instrument(program=4, name="rhodes comp")
    for bar in range(4):
        for beat in range(4):
            for p in (60, 64, 67):
                inst.notes.append(
                    pm.Note(velocity=80, pitch=p,
                            start=bar * 2.0 + beat * 0.5,
                            end=bar * 2.0 + beat * 0.5 + 0.4)
                )
    midi.instruments.append(inst)

    before_vels = [n.velocity for n in inst.notes]
    before_starts = [n.start for n in inst.notes]

    summary_a = humanize(midi, seed=42, params=HumanizeParams.POP())
    after_vels = [n.velocity for n in inst.notes]
    after_starts = [n.start for n in inst.notes]

    print("Summary:", json.dumps(summary_a, indent=2, default=str)[:600], "...")
    print(f"Notes:   {len(inst.notes)}")
    print(f"Vel range before: [{min(before_vels)}, {max(before_vels)}]  after: [{min(after_vels)}, {max(after_vels)}]")
    print(f"Vel changed:  {sum(1 for a, b in zip(before_vels, after_vels) if a != b)} / {len(after_vels)}")
    print(f"Start moved:  {sum(1 for a, b in zip(before_starts, after_starts) if abs(a - b) > 1e-9)} / {len(after_starts)}")

    # Determinism check: rebuild identical MIDI and re-humanize with same seed.
    midi2 = pm.PrettyMIDI(initial_tempo=120)
    inst2 = pm.Instrument(program=4, name="rhodes comp")
    for bar in range(4):
        for beat in range(4):
            for p in (60, 64, 67):
                inst2.notes.append(
                    pm.Note(velocity=80, pitch=p,
                            start=bar * 2.0 + beat * 0.5,
                            end=bar * 2.0 + beat * 0.5 + 0.4)
                )
    midi2.instruments.append(inst2)
    humanize(midi2, seed=42, params=HumanizeParams.POP())
    same_vel = all(a.velocity == b.velocity for a, b in zip(inst.notes, inst2.notes))
    same_time = all(abs(a.start - b.start) < 1e-12 for a, b in zip(inst.notes, inst2.notes))
    print(f"Deterministic under seed: velocities={same_vel}, timings={same_time}")
