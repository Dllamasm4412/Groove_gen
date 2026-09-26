"""
Melody bank rotation for GrooveGen (M0.5 Step 5.5b).

Problem: if we render (genre='pop', tempo=118, tier=3) twice with the same
seed, we get bit-identical MIDI. When the closed loop dwells on one rung
for 4 minutes (12 segments), the listener hears the same 4-bar loop
twelve times in a row.

Solution: pre-declare N distinct seeds per (genre, tier) cell and rotate
through them each time that cell is commanded. The composer is
deterministic in the (genre, tempo, tier, seed) tuple, so each variant
is a musically distinct realization of the same style pocket.

Public API
----------
    MelodyBank(variants_per_cell=4, base_seed=0)
        Deterministic, stateful seed rotator.

        .seed_for(genre, tier) -> int
            Return the next seed for this cell. Advances that cell's index.

        .reset(genre=None, tier=None)
            Reset rotation counters. If both None, reset ALL cells.

        .peek(genre, tier) -> int
            Return the seed that WOULD be returned next, without advancing.

Design notes
------------
    - Each cell has an independent counter. rnb-3 rotation doesn't leak
      into pop-3 rotation.
    - Seeds are derived deterministically from (genre_hash, tier, variant):
          seed = base_seed + genre_hash*10000 + tier*1000 + variant
      This gives us stable seeds across sessions (same variant = same seed).
    - `variants_per_cell=4` was chosen to match how long the controller
      typically dwells: 4 variants x 20 s = 80 s, enough for a natural
      loop-back on any rung.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Stable per-genre hashes (used as multipliers so seeds are well-separated)
_GENRE_HASH = {
    'calm':  1,
    'lofi':  5,
    'rnb':   2,
    'pop':   3,
    'latin': 4,
    'hiphop': 6,
    'rock':  7,
}


@dataclass
class MelodyBank:
    variants_per_cell: int = 4
    base_seed: int = 0
    # Per-cell rotation index (mutates)
    _counters: dict[tuple[str, int], int] = field(default_factory=dict)

    def _key(self, genre: str, tier: int) -> tuple[str, int]:
        if genre not in _GENRE_HASH:
            raise ValueError(f'unknown genre: {genre!r}')
        if tier not in (1, 2, 3, 4, 5):
            raise ValueError(f'tier must be 1..5, got {tier}')
        return (genre, tier)

    def _seed_for_variant(self, genre: str, tier: int, variant: int) -> int:
        h = _GENRE_HASH[genre]
        return int(self.base_seed + h * 10_000 + tier * 1_000 + variant)

    def seed_for(self, genre: str, tier: int) -> int:
        """Return next seed for (genre, tier). Advances the rotation counter."""
        key = self._key(genre, tier)
        idx = self._counters.get(key, 0)
        self._counters[key] = (idx + 1) % self.variants_per_cell
        return self._seed_for_variant(genre, tier, idx)

    def peek(self, genre: str, tier: int) -> int:
        """Return next seed WITHOUT advancing the counter."""
        key = self._key(genre, tier)
        idx = self._counters.get(key, 0)
        return self._seed_for_variant(genre, tier, idx)

    def reset(self, genre: str | None = None, tier: int | None = None) -> None:
        """Reset all counters (genre=tier=None) or a specific subset."""
        if genre is None and tier is None:
            self._counters.clear()
            return
        keys = list(self._counters.keys())
        for g, t in keys:
            if (genre is None or g == genre) and (tier is None or t == tier):
                del self._counters[(g, t)]

    def variants(self, genre: str, tier: int) -> list[int]:
        """List all N seeds for a cell (useful for pre-render / audit)."""
        return [self._seed_for_variant(genre, tier, v)
                for v in range(self.variants_per_cell)]


if __name__ == '__main__':
    bank = MelodyBank(variants_per_cell=4, base_seed=42)

    # Rotate through pop-3 four times, should get 4 distinct seeds, then wrap
    seeds = [bank.seed_for('pop', 3) for _ in range(8)]
    print(f'pop-3 rotation over 8 calls: {seeds}')
    assert seeds[0] != seeds[1], seeds
    assert seeds[:4] == seeds[4:], f'should wrap: {seeds}'

    # Different cells should give different seeds
    pop3 = bank.peek('pop', 3)
    rnb3 = bank.peek('rnb', 3)
    pop4 = bank.peek('pop', 4)
    print(f'peeks -> pop3={pop3}, rnb3={rnb3}, pop4={pop4}')
    assert pop3 != rnb3 != pop4, 'cells should have distinct seeds'

    # Peek does not advance
    before = bank.peek('calm', 1)
    _ = bank.peek('calm', 1)
    after = bank.seed_for('calm', 1)
    assert before == after, 'peek advanced the counter'

    # Reset works
    bank.reset('pop', 3)
    reset_seed = bank.seed_for('pop', 3)
    assert reset_seed == seeds[0], f'reset should restart: {reset_seed} vs {seeds[0]}'

    # variants() lists all N
    all_pop3 = bank.variants('pop', 3)
    print(f'all pop-3 variants: {all_pop3}')
    assert len(all_pop3) == 4
    assert len(set(all_pop3)) == 4

    print('ALL CHECKS PASSED')
