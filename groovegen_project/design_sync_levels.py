"""Design syncopated kick/snare placements that hit the literature index bands.

Witek et al. (2014) index = Longuet-Higgins & Lee metric-weight syncopation
ADDITIONALLY weighted by drum-instrument salience (bass drum > snare > hi-hat).
That salience multiplier is why their scale reaches 0-81; a pure L&L weight
difference (max ~5 per event) cannot. We therefore:
  (1) score over a 2-bar window (Witek used 2-bar patterns), and
  (2) multiply each syncopation by an instrument-salience weight.

Targets (groove_knob_literature.md):
  L0  S ~ 0-4    straight
  L1  S ~ 12-18  light
  L2  S ~ 26-34  sweet spot (apex ~30)
  L3  S ~ 48-65  heavy
"""
METRIC_WEIGHTS = {
    0: 5, 8: 4, 4: 3, 12: 3,
    2: 2, 6: 2, 10: 2, 14: 2,
    1: 1, 3: 1, 5: 1, 7: 1, 9: 1, 11: 1, 13: 1, 15: 1,
}
N = 16
# Instrument salience multipliers (Witek: bass drum most salient).
# Hi-hat EXCLUDED from the index per Witek et al. (2014).
SALIENCE = {"kick": 2.0, "snare": 1.5}


def index_2bar(voices):
    """voices: dict name->list[int steps]. Salience-weighted 2-bar index."""
    # map each tiled step -> the most salient voice onsetting there
    all_onsets = {}  # step_2bar -> salience
    union = set()
    for name, steps in voices.items():
        if name not in SALIENCE:   # skip hi-hat (excluded per Witek)
            continue
        sal = SALIENCE[name]
        for b in (0, 1):
            for s in steps:
                pos = b * N + s
                union.add(pos)
                all_onsets[pos] = max(all_onsets.get(pos, 0.0), sal)
    if not union:
        return 0.0
    total = 2 * N
    score = 0.0
    for s in sorted(union):
        w_here = METRIC_WEIGHTS[s % N]
        best_rest = 0
        for d in range(1, total):
            pos = (s + d) % total
            if pos in union:
                break
            best_rest = max(best_rest, METRIC_WEIGHTS[pos % N])
        diff = best_rest - w_here
        if diff > 0:
            score += diff * all_onsets[s]   # salience-weighted
    return round(score, 1)


candidates = {
    # L0 straight: kicks on strong beats, snare backbeat, hats on 8ths. ~0.
    "L0": dict(kick=[0, 8], snare=[4, 12], hat=[0, 2, 4, 6, 8, 10, 12, 14]),

    # L1 light: anticipate beat 3 (kick on 7), one pushed kick on 10.
    "L1": dict(kick=[0, 7], snare=[4, 12], hat=[0, 2, 4, 6, 8, 10, 12, 14]),

    # L2 sweet spot (~30): beat 1 kept, beat 3 anticipated, two pushed kicks.
    "L2": dict(kick=[0, 7, 10, 14], snare=[4, 12], hat=[0, 2, 4, 6, 8, 10, 12, 14]),

    # L3 heavy (~48-65): strong beats EMPTY, dense off-beat kicks, displaced snare.
    "L3": dict(kick=[3, 7, 11, 14], snare=[5, 13], hat=[2, 6, 10, 14]),
}

bands = {"L0": "0-4", "L1": "12-18", "L2": "26-34", "L3": "48-65"}
print(f"{'lvl':<4}{'idx':>7}   target")
for lvl, v in candidates.items():
    print(f"{lvl:<4}{index_2bar(v):>7}   {bands[lvl]:<8} kick={v['kick']} snare={v['snare']}")
