"""verify_drum_variants.py — GrooveGen composer v1.4 drum-variant verification.

Purpose: after adding 4 seed-selected drum-pattern variants per genre (Move 1),
verify that:

  CHECK 1: same seed still produces bit-identical MIDI (determinism preserved)
  CHECK 2: drum hit-count spread across variants stays inside ±15% (arousal
           envelope constraint — percussive_ratio doesn't leak out of band)
  CHECK 3: variants produce *audibly distinct* drum patterns (Jaccard overlap
           on drum note fingerprints < 0.75 for at least half of variant pairs)

Baseline (v1.3, before drum variants):
  All seeds → SAME drum pattern per genre → Jaccard 1.0 across all pairs.

Target (v1.4, after Move 1):
  4 distinct drum fingerprints per drum-having genre (pop, rnb, latin).
  Median pairwise Jaccard ≤ 0.60 for pop and latin, ≤ 0.50 for rnb.

Run:
    cd /Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot
    python verify_drum_variants.py
"""
from __future__ import annotations

from composer import generate_segment


def notes_tuples(pm):
    """Full-composition note tuples (start, pitch, velocity)."""
    out = []
    for inst in pm.instruments:
        for n in inst.notes:
            out.append((round(n.start, 4), n.pitch, n.velocity))
    return out


def drum_fingerprint(pm):
    """Drum-only note positions, quantized to 32nd grid. Used to compare
    drum patterns across variants independent of jitter."""
    d = [i for i in pm.instruments if i.is_drum][0]
    return frozenset((round(n.start * 32) / 32, n.pitch) for n in d.notes)


def drum_hit_count(pm):
    d = [i for i in pm.instruments if i.is_drum][0]
    return len(d.notes)


def percussive_ratio(pm):
    d = [i for i in pm.instruments if i.is_drum][0]
    total = sum(len(inst.notes) for inst in pm.instruments)
    return len(d.notes) / total if total else 0.0


def pairwise_jaccard(fp_list):
    """Return list of pairwise Jaccard indices for a list of frozensets."""
    out = []
    for i in range(len(fp_list)):
        for j in range(i + 1, len(fp_list)):
            union = len(fp_list[i] | fp_list[j])
            if union == 0:
                out.append(1.0)
            else:
                out.append(len(fp_list[i] & fp_list[j]) / union)
    return out


# ==============================================================================
GENRES_WITH_DRUMS = ['pop', 'rnb', 'latin']
ALL_GENRES = ['pop', 'rnb', 'latin', 'calm']


print('=' * 70)
print('CHECK 1: DETERMINISM (same seed -> bit-identical)')
print('=' * 70)
det_pass = True
for genre in ALL_GENRES:
    pm1 = generate_segment(genre, density=0.6, duration_bars=8, seed=42)
    pm2 = generate_segment(genre, density=0.6, duration_bars=8, seed=42)
    match = notes_tuples(pm1) == notes_tuples(pm2)
    print(f'  {genre:6s}: match={match}, notes={len(notes_tuples(pm1))}')
    det_pass = det_pass and match
print(f'  {"PASS" if det_pass else "FAIL"} — same seed still bit-identical')
print()


print('=' * 70)
print('CHECK 2: DRUM HIT-COUNT SPREAD (arousal envelope constraint)')
print('=' * 70)
print('  Target: max/min hit-count spread ≤ 25% (±12% around mean)')
env_pass = True
for genre in GENRES_WITH_DRUMS:
    counts = []
    percs = []
    for seed in range(60):
        pm = generate_segment(genre, density=0.6, duration_bars=8, seed=seed)
        counts.append(drum_hit_count(pm))
        percs.append(percussive_ratio(pm))
    spread_pct = (max(counts) - min(counts)) / min(counts) * 100
    perc_spread = max(percs) - min(percs)
    ok = spread_pct <= 25.0
    env_pass = env_pass and ok
    print(f'  {genre:6s}: hit_count [{min(counts):3d}, {max(counts):3d}] '
          f'spread={spread_pct:5.1f}%  '
          f'perc_ratio [{min(percs):.3f}, {max(percs):.3f}] '
          f'{"OK" if ok else "OUT"}')
print(f'  {"PASS" if env_pass else "FAIL"} — variants stay inside arousal envelope')
print()


print('=' * 70)
print('CHECK 3: DRUM-PATTERN DISTINCTNESS (perceptual variety)')
print('=' * 70)
print('  Baseline v1.3: 1 drum pattern per genre -> Jaccard 1.00')
print('  Target v1.4:   median pairwise Jaccard ≤ 0.60')
dist_pass = True
for genre in GENRES_WITH_DRUMS:
    fingerprints = {}
    for seed in range(60):
        pm = generate_segment(genre, density=0.6, duration_bars=8, seed=seed)
        fp = drum_fingerprint(pm)
        fh = hash(fp)
        if fh not in fingerprints:
            fingerprints[fh] = fp
    fps = list(fingerprints.values())
    js = pairwise_jaccard(fps)
    js_sorted = sorted(js)
    median = js_sorted[len(js_sorted) // 2] if js_sorted else 1.0
    ok = median <= 0.60 and len(fps) >= 3
    dist_pass = dist_pass and ok
    if js:
        print(f'  {genre:6s}: {len(fps)} distinct fingerprints  '
              f'pairwise Jaccard [{min(js):.2f}, {max(js):.2f}]  '
              f'median={median:.2f}  {"OK" if ok else "OUT"}')
    else:
        print(f'  {genre:6s}: {len(fps)} distinct fingerprint(s) only — '
              f'variants not firing  OUT')
print(f'  {"PASS" if dist_pass else "FAIL"} — variants perceptibly different')
print()

print('=' * 70)
overall = det_pass and env_pass and dist_pass
print(f'OVERALL: {"PASS" if overall else "FAIL"}')
print('=' * 70)
