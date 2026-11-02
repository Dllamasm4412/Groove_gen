"""
MIDI-level loudness prediction for v3 segments (per-soundfont measured tables).

A table (levels_<soundfont stem>.json, written by `audition_v3.py
--measure-levels --sf2 <sf2>`, pinned to the soundfont's sha256) holds, for
the palette programs, the integrated loudness of a reference phrase (16 notes,
2 per second, velocity 90) at several note lengths, the same for each drum
pitch, a calibration offset fitted on rendered segments, and the loudness of
the locked v2c hip-hop:3 segments on that soundfont (the level-3 target).

predict_lufs(pm) sums per-note energies, each the reference loudness for the
note's program and length, + 40 log10(velocity / 90) (the SoundFont default
velocity curve, measured within 0.1 dB) + the channel-volume gain, over the
segment's duration. It stands in for rendering when a composition is
calibrated; certification still measures the rendered audio.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import pretty_midi

HERE = Path(__file__).resolve().parent
DEFAULT_TABLE = 'FluidR3_GM'
REF_RATE = 2.0              # reference phrase: notes per second


@lru_cache(maxsize=None)
def load_table(name: str = DEFAULT_TABLE) -> dict | None:
    path = HERE / f'levels_{name}.json'
    if not path.exists():
        return None
    t = json.loads(path.read_text())
    t['programs'] = {int(k): {float(d): v for d, v in curve.items()} for k, curve in t['programs'].items()}
    t['drums'] = {int(k): v for k, v in t['drums'].items()}
    return t


def _curve(curve: dict[float, float], dur: float) -> float:
    """Reference loudness at note length `dur`, linear in log(duration) between
    measured points and extrapolated past the longest one (a held chord keeps
    adding energy while it sounds)."""
    ds = sorted(curve)
    if dur <= ds[0]:
        return curve[ds[0]]
    if dur >= ds[-1]:
        a, b = ds[-2], ds[-1]
        slope = max(0.0, (curve[b] - curve[a]) / (math.log(b) - math.log(a)))
        return curve[b] + slope * (math.log(dur) - math.log(b))
    for a, b in zip(ds, ds[1:]):
        if a <= dur <= b:
            w = (math.log(dur) - math.log(a)) / (math.log(b) - math.log(a))
            return curve[a] + w * (curve[b] - curve[a])
    return curve[ds[-1]]


def _cc7_db(inst: pretty_midi.Instrument) -> float:
    vols = [c.value for c in inst.control_changes if c.number == 7]
    return 40 * math.log10(max(1, vols[-1]) / 100) if vols else 0.0


def predict_lufs(pm: pretty_midi.PrettyMIDI, duration_s: float, table: dict, parts: str = 'all') -> float:
    """Predicted integrated loudness of the rendered segment (energy-table recipe level).

    parts: 'all', 'drums' or 'melodic'."""
    energy = 0.0
    for inst in pm.instruments:
        if (parts == 'drums' and not inst.is_drum) or (parts == 'melodic' and inst.is_drum):
            continue
        gain = _cc7_db(inst)
        for n in inst.notes:
            if inst.is_drum:
                ref = table['drums'].get(n.pitch, table['drum_default'])
            else:
                curve = table['programs'].get(inst.program)
                ref = _curve(curve, n.end - n.start) if curve else table['program_default']
            level = ref + 40 * math.log10(max(1, n.velocity) / 90) + gain
            energy += 10 ** (level / 10) / REF_RATE
    if energy <= 0:
        return -70.0
    return 10 * math.log10(energy / duration_s) + table['offset_db']
