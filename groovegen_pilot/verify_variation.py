"""
Verify composer v1.3 non-repetition upgrade.

Three checks:
1. Determinism preserved: same seed -> bit-identical MIDI
2. Seed-to-seed variation: position-for-position pitch match rate should be
   much lower than the 89% baseline observed on v1.2
3. Cell-visit variation (Option 2): melody_bank rotation over 4 variants
   produces 4 musically distinct outputs (different note counts / pitch sets)
"""
from __future__ import annotations

import sys
sys.path.insert(0, '/home/user/workspace')

from composer import generate_segment
from melody_bank import MelodyBank


def all_pitches(pm):
    """Flatten pitches in note-start-time order across all instruments."""
    events = []
    for inst in pm.instruments:
        for n in inst.notes:
            events.append((n.start, n.pitch, id(inst)))
    events.sort()
    return [p for _, p, _ in events]


def pitch_match_rate(pm_a, pm_b):
    """Position-for-position pitch match rate between two segments."""
    a = all_pitches(pm_a)
    b = all_pitches(pm_b)
    L = min(len(a), len(b))
    if L == 0:
        return 0.0
    matches = sum(1 for i in range(L) if a[i] == b[i])
    return matches / L


def note_counts(pm):
    return sum(len(inst.notes) for inst in pm.instruments)


def unique_pitch_seq(pm):
    """Return sorted unique (pitch, quantized_start) pairs \u2014 identifies
    whether two segments have structurally different note content."""
    seen = set()
    for inst in pm.instruments:
        for n in inst.notes:
            seen.add((n.pitch, round(n.start, 3)))
    return len(seen)


print('=' * 70)
print('CHECK 1: DETERMINISM (same seed -> bit-identical)')
print('=' * 70)
for genre in ['calm', 'pop', 'rnb', 'latin']:
    a = generate_segment(genre, density=0.6, duration_bars=8, seed=42)
    b = generate_segment(genre, density=0.6, duration_bars=8, seed=42)
    ap = all_pitches(a)
    bp = all_pitches(b)
    ok = ap == bp
    print(f'  {genre:6}: match={ok}, notes={note_counts(a)}')
    assert ok, f'{genre}: determinism broken'
print('  PASS \u2014 same seed still bit-identical')

print()
print('=' * 70)
print('CHECK 2: SEED-TO-SEED VARIATION (baseline was 89% match on pop)')
print('=' * 70)
for genre in ['calm', 'pop', 'rnb', 'latin']:
    seeds = [1, 42, 999, 7, 314]
    pms = [generate_segment(genre, density=0.6, duration_bars=8, seed=s) for s in seeds]
    rates = []
    for i in range(len(seeds)):
        for j in range(i + 1, len(seeds)):
            r = pitch_match_rate(pms[i], pms[j])
            rates.append(r)
    mean_rate = sum(rates) / len(rates)
    max_rate = max(rates)
    min_rate = min(rates)
    counts = [note_counts(p) for p in pms]
    unique_ct = [unique_pitch_seq(p) for p in pms]
    print(f'  {genre:6}: '
          f'match rate mean={mean_rate:.2f} min={min_rate:.2f} max={max_rate:.2f} '
          f'| note counts={counts}')

print()
print('=' * 70)
print('CHECK 3: MELODY_BANK ROTATION (Option 2)')
print('=' * 70)
bank = MelodyBank(variants_per_cell=4, base_seed=0)
for genre in ['calm', 'pop', 'rnb', 'latin']:
    tier = 3  # mid-ladder
    seeds = [bank.seed_for(genre, tier) for _ in range(4)]
    print(f'  {genre:6}: bank seeds for tier={tier}: {seeds}')
    pms = [generate_segment(genre, density=0.6, duration_bars=8, seed=s) for s in seeds]
    rates = []
    for i in range(4):
        for j in range(i + 1, 4):
            rates.append(pitch_match_rate(pms[i], pms[j]))
    mean_rate = sum(rates) / len(rates)
    counts = [note_counts(p) for p in pms]
    print(f'          rotation-4 pairwise mean match={mean_rate:.2f} '
          f'| note counts={counts}')

print()
print('All checks completed.')
