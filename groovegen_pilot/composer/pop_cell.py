"""
composer/pop_cell.py — thin adapter for the legacy _gen_pop generator.

Returns pretty_midi.PrettyMIDI directly (NOT music21 Score). music21's MIDI
round-trip re-quantizes ticks_per_beat and adds meta-events, changing the
audio. Callers must dispatch on return type — see freeze_library.py.

Approved by user 2026-09-10 after listening to renders/legacy_pop_samples/.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pretty_midi

# Load legacy composer.py explicitly — the composer/ package shadows normal import.
_COMPOSER_PATH = Path(__file__).resolve().parent.parent / "composer.py"
assert _COMPOSER_PATH.exists(), f"legacy composer.py not found at {_COMPOSER_PATH}"
_spec = importlib.util.spec_from_file_location("_composer_legacy", _COMPOSER_PATH)
_composer_legacy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_composer_legacy)
_gen_pop = _composer_legacy._gen_pop
_GENRE_CFG = _composer_legacy.GENRE_CFG

# Tier ladder approved by user via legacy render listening test (2026-09-10).
_TIER_TEMPO = {1: 100, 2: 108, 3: 115, 4: 122, 5: 130}
_TIER_DENSITY_FLOOR = {1: 0.40, 2: 0.60, 3: 0.70, 4: 0.85, 5: 1.00}


def generate_pop_segment(
    tempo_bpm: int,
    density: float,
    duration_bars: int = 8,
    seed: int = 6001,
) -> pretty_midi.PrettyMIDI:
    """Render an 8-bar pop segment. Returns pretty_midi.PrettyMIDI."""
    return _gen_pop(
        tempo_bpm=tempo_bpm,
        duration_bars=duration_bars,
        seed=seed,
        cfg=_GENRE_CFG["pop"],
        density=density,
    )


if __name__ == "__main__":
    pm = generate_pop_segment(
        tempo_bpm=_TIER_TEMPO[3],
        density=_TIER_DENSITY_FLOOR[3],
        duration_bars=8,
        seed=6001,
    )
    pm.write("/tmp/pop_cell_smoke.mid")
    n = sum(len(inst.notes) for inst in pm.instruments)
    assert pm is not None and n > 0, f"empty pop cell output (notes={n})"
    print(f"wrote /tmp/pop_cell_smoke.mid; notes={n} duration={pm.get_end_time():.2f}s")
