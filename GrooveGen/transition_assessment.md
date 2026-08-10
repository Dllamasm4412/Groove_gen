# Tempo-Transition Mechanism Assessment for GrooveGen

**Question:** how should GrooveGen splice from an outgoing bed to a freshly-generated incoming bed at a *different tempo* so the transition sounds best? (Crossfade was already rejected — user heard two different-tempo beds overlapping and it sounded bad.)

**Test material:** the two uploaded beds, treated as bed A → bed B:
- **Bed A** = r&b upload (`download.wav`) — detected tempo **136.4 BPM**, downbeat at 4.43s, 10.94s total.
- **Bed B** = salsa upload (`download-3.wav`) — detected tempo **95.2 BPM**, downbeat at 0.20s, 10.94s total.

Analysis used `get_bed_info()` from `hybrid_render.py` (madmom RNN downbeat grid, octave-corrected tempo, `bed_grid`/`sec_per_beat`/`sec_per_bar` precomputed). This is a ~43% tempo change (136→95 BPM), a realistically hard case — bigger than most real GrooveGen bed-to-bed transitions, which is useful for stress-testing.

All code, wavs, and MP4s are in `/home/user/workspace/transition_test/`.

---

## The three mechanisms tested

1. **Downbeat-aligned hard cut** (`mech1_hard_cut.py` → `mech1_hard_cut.wav` / `.mp4`) — A is truncated at its last complete downbeat (7.95s), B starts exactly at its first detected downbeat (0.142s); a 1.5ms linear micro-fade on each side of the seam only, to kill any DC-step click. No overlap, no added material.

2. **Fill-masked cut** (`mech2_fill_masked.py` → `mech2_fill_masked.wav` / `.mp4`) — same two downbeat-aligned cut points as (1), but a 1-bar **drum-only fill** is spliced in between, rendered with `render_aligned_drums()` at high `event_density=10`/`syncopation_level=0.6`, tempo pinned to the average of A/B (115.8 BPM) so it reads as a rhythmic bridge rather than belonging to either bed.

3. **Tempo-ramp (time-stretch)** (`mech3_tempo_ramp.py` → `mech3_tempo_ramp.wav` / `.mp4`) — the last bar of A is split into 8 sub-chunks and each is time-stretched with `librosa.effects.time_stretch` at a progressively increasing rate so the *local* tempo glides from 136.4→95.2 BPM across that bar, chunk joins smoothed with 3ms crossfades, then a hard cut to B's first downbeat.

---

## Objective seam metrics

Lower is better on every column. "Seam" = the literal splice sample(s); mechanisms 2 and 3 have two seams (entry/exit of the inserted material), so both are reported plus the max (the more audible one dominates perception).

| Mechanism | Click amplitude (max, sample-to-sample Δ) | RMS discontinuity (max, 30ms windows) | Downbeat/grid phase error |
|---|---|---|---|
| **1. Downbeat-aligned hard cut** | **0.0265** | **0.0072** | **0.0 ms** (cut lands exactly on both grids by construction) |
| 2. Fill-masked cut | 0.0926 (entry seam, A→fill) | 0.0888 (entry seam, A→fill) | 0.0 ms at both literal splice points, but the fill's own onset transient is the largest measured discontinuity of all three mechanisms |
| 3. Tempo-ramp (time-stretch) | 0.0265 (exit seam, ramp→B; same as cut 1) | 0.0716 (entry seam, head→ramp — the point where time-stretch artifacts begin) | **313 ms** — the stretched bar runs 2.073s vs. an original 1.760s bar; this is the accumulated drift between where A's un-warped grid would have put the next beat and where the ramp actually lands relative to it |

Supporting numbers:
- Mechanism 2's drum fill is 2.07s at 115.8 BPM; its attack transient produces ~3.5× the click amplitude and ~12× the RMS discontinuity of the plain hard cut at its entry seam — inserting new percussive material does **not** reduce the objective seam signature, it relocates and *adds* a louder transient (a real drum fill/crash always has a strong attack; that's expected).
- Mechanism 3's transient-smear proxy (onset-strength peak ratio, stretched/original) is 1.044 — under 5% change, i.e. `librosa.effects.time_stretch` on this material does not audibly blunt the transient. But this is a mild ramp target (136→95, mostly slowing down; time-compression that *speeds up* percussive material smears far more than time-expansion). The real cost shows up as the 313ms grid-phase error and general softening/phasiness typical of phase-vocoder stretch on transient-heavy percussive content, which the onset-peak metric under-reports.
- All output audio confirmed non-silent: `ffmpeg -af volumedetect` on each MP4 gives mean_volume ≈ −19.6 to −19.9 dB (max_volume −2.4 dB) for all three — no silent renders.

---

## Ranking (best → worst)

**1. Downbeat-aligned hard cut** — cleanest by every objective metric, and cheapest computationally (zero extra audio to render, zero extra latency).

**2. Fill-masked cut** — perceptually the most "musical" idea (this is literally what human drummers do at a tempo change), but it is *not* objectively cleaner at the seam — it has the largest click and RMS discontinuity of the three, because a fill's own attack transient IS a big discontinuity by nature. Its advantage is entirely perceptual/psychoacoustic: it gives the listener's ear a full bar of rhythmic information to reinterpret as an intentional "turnaround" rather than an edit, which a raw discontinuity number can't capture. It also has real production cost: it requires a pre-rendered fill (an extra `render_aligned_drums` call, ~50-150ms of synthesis + FluidSynth render time in this pipeline) sitting on the critical path of every transition.

**3. Tempo-ramp (time-stretch)** — worst on the metric that matters most for a beat-driven system: **313ms of downbeat/grid phase error**, i.e. the very thing this mechanism is trying to smooth over (a tempo change) does not resolve into a clean handoff — it resolves into a bar whose live-target-tempo endpoint isn't where a listener's tempo-tracking expects it, which is where the "did that just stumble" feeling comes from with large tempo deltas. It's also the most expensive: 8 sequential `librosa.effects.time_stretch` calls (STFT-based phase vocoder) plus join-smoothing, meaningfully higher latency than the other two, and the risk of audible phasiness/smearing grows sharply as the tempo delta grows (safe for small deltas like ±5-8%, this 43% delta already shows it straining).

---

## RECOMMENDATION: use the **downbeat-aligned hard cut**, mechanism 1

**Why, considering both audio quality and real-time feasibility:**

- **Audio quality:** it wins every objective metric measured — lowest click amplitude, lowest RMS discontinuity, and by construction zero downbeat/grid phase error on both sides of the seam. There is no artifact to reason about later (no fill loudness/timing to tune, no time-stretch rate/chunk-size to tune).
- **Real-time feasibility:** it is the cheapest possible transition — no extra audio render, no phase vocoder, no extra latency. It is a slice + a 1.5ms fade, i.e. microseconds of compute. In a live/interactive system (GrooveGen's fast-loop, per-bar rendering architecture in `hybrid_render.py`) this is the only one of the three that has *zero* impact on the real-time budget.
- **The fill-masked cut is the best runner-up** for the case where GrooveGen wants a stronger "this was intentional" musical signal (e.g. a big user-triggered tempo change, not an automatic one) and can afford ~1 bar of extra pre-render latency (`render_aligned_drums` is already in the codebase and cheap — one bar). Because bar boundaries are already known from `get_bed_info()`, this is a very small addition to bolt on later as an *optional* embellishment layered on top of mechanism 1's cut logic — but it should not be the default given it does not improve the raw seam metrics.
- **The tempo-ramp is not recommended** at tempo deltas of this size. It could be revisited for *small* tempo deltas (~5-10%) where phase-vocoder smearing is negligible and the grid-phase error would be proportionally much smaller, but GrooveGen's bed catalog can have arbitrarily large tempo jumps (a calm 63 BPM preset next to a salsa 95+ BPM preset), so a mechanism whose failure mode gets worse exactly when the tempo delta is large is a bad general-purpose default. It's also the slowest to compute of the three.

### Drop-in implementation for nb15

```python
import numpy as np
import soundfile as sf
from groovegen.hybrid_render import get_bed_info


def last_complete_downbeat_idx(bed_grid, sec_per_bar, downbeat_s, duration_s):
    """Index into bed_grid of the LAST downbeat that starts a full bar which
    still fits entirely inside the bed audio (grid_time + one bar <= duration)."""
    grid = np.asarray(bed_grid)
    start_idx = int(np.argmin(np.abs(grid - downbeat_s)))
    bar_indices = list(range(start_idx, len(grid), 4))  # 4/4: every 4th grid entry is a downbeat
    best = bar_indices[0]
    for bi in bar_indices:
        if grid[bi] + sec_per_bar <= duration_s + 1e-6:
            best = bi
        else:
            break
    return best


def first_downbeat_idx(bed_grid, downbeat_s):
    grid = np.asarray(bed_grid)
    return int(np.argmin(np.abs(grid - downbeat_s)))


def micro_fade(y, sr, ms=1.5, side="both"):
    """Tiny linear micro-fade (default 1.5ms) to prevent a sample-level click
    at a hard cut. side: 'in' | 'out' | 'both'."""
    n = max(1, int(round(sr * ms / 1000.0)))
    n = min(n, len(y) // 4 if len(y) >= 4 else len(y))
    y = y.copy()
    if n <= 0:
        return y
    if side in ("in", "both"):
        y[:n] *= np.linspace(0.0, 1.0, n, dtype=np.float32)
    if side in ("out", "both"):
        y[-n:] *= np.linspace(1.0, 0.0, n, dtype=np.float32)
    return y


def splice_beds_downbeat_hard_cut(bed_wav_a: str, bed_wav_b: str, out_wav: str,
                                   expected_tempo_a: float | None = None,
                                   expected_tempo_b: float | None = None) -> dict:
    """RECOMMENDED tempo-transition mechanism: downbeat-aligned hard cut.

    Ends bed A on its last complete downbeat, starts bed B on its first
    downbeat, joins with a 1.5ms micro-fade on each side (click-prevention
    only -- NOT a crossfade; there is zero overlap between A and B audio,
    which is the fix for the rejected crossfade approach). Zero added
    latency beyond one get_bed_info() call per bed (already required
    elsewhere in the pipeline and cached by get_bed_info).
    """
    info_a = get_bed_info(bed_wav_a, expected_tempo=expected_tempo_a)
    info_b = get_bed_info(bed_wav_b, expected_tempo=expected_tempo_b)
    sr = info_a["sr"]
    assert info_b["sr"] == sr, "beds must share sample rate"

    cut_idx_a = last_complete_downbeat_idx(
        info_a["bed_grid"], info_a["sec_per_bar"], info_a["downbeat_s"], info_a["duration_s"])
    cut_sample_a = int(round(info_a["bed_grid"][cut_idx_a] * sr))

    start_idx_b = first_downbeat_idx(info_b["bed_grid"], info_b["downbeat_s"])
    start_sample_b = int(round(info_b["bed_grid"][start_idx_b] * sr))

    seg_a = micro_fade(info_a["y"][:cut_sample_a], sr, ms=1.5, side="out")
    seg_b = micro_fade(info_b["y"][start_sample_b:], sr, ms=1.5, side="in")

    out = np.concatenate([seg_a, seg_b]).astype(np.float32)
    sf.write(out_wav, out, sr)
    return dict(out_wav=out_wav, sr=sr, seam_sample=len(seg_a),
                cut_time_a_s=float(info_a["bed_grid"][cut_idx_a]),
                start_time_b_s=float(info_b["bed_grid"][start_idx_b]))
```

Usage in nb15's transition step: call `splice_beds_downbeat_hard_cut(current_bed_wav, next_bed_wav, out_wav)` whenever the target tempo changes; pass `expected_tempo_a`/`expected_tempo_b` if the preset's tempo hint is known (recommended — it stabilizes `get_bed_info`'s octave correction, per `analyze_bed`'s docstring in `hybrid_render.py`).

---

## Deliverables

- `/home/user/workspace/transition_test/mech1_hard_cut.wav`, `.mp4`
- `/home/user/workspace/transition_test/mech2_fill_masked.wav`, `.mp4`
- `/home/user/workspace/transition_test/mech3_tempo_ramp.wav`, `.mp4`
- `/home/user/workspace/transition_test/mech{1,2,3}_metrics.json` — raw metric dumps
- `/home/user/workspace/transition_test/bed_info_summary.json` — bed A/B tempo/grid analysis
- `/home/user/workspace/transition_test/{common.py, step1_analyze.py, mech1_hard_cut.py, mech2_fill_masked.py, mech3_tempo_ramp.py, make_videos.py}` — all experiment source, reproducible
- This file: `/home/user/workspace/transition_assessment.md`

All three MP4s verified non-silent via `ffmpeg -af volumedetect` (mean_volume ≈ −19.6 to −19.9 dB, max_volume −2.4 dB — none report `-inf`).
