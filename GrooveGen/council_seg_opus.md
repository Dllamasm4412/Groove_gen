# Council Response — Segment-Based Control Redesign (Opus)

**Reviewer role:** control systems + music generation. **Stance:** the redesign is correct in
direction and *underspecified in the two places that will actually break it* (measurement noise
floor, and where the ramp's "clock" lives). I disagree with parts of the framing below, and I
disagree with Option A as literally written. Everything here is grounded in the code I read:
`pd_controller.py`, `run_session.py`, `trace_schema.py`, `tier_mapping.py`, `renderer.py`,
`scene.py`, plus `symbolic_tiers_demo.drum_bar_tier`, `symbolic_bed_proto.render_midi/polish`,
and `hr_source.HRArousalMapper`.

---

## 0. Three things I found in the code that the brief does not mention, and that change the answers

These are not stylistic. Each one silently breaks the proposed design.

**(0a) The `calm` rung does not exist in the controller.**
`GENRE_ENERGY_ORDER = ["r&b", "pop", "latin"]` and `GENRE_EQUILIBRIUM_BAND` has exactly those
three keys. But `renderer.py` `_PROG`/`_INST` *do* have `"calm"`, and `_norm_genre()` maps
`calm|ambient|chill` → `"calm"`. So the ladder you want (`calm→r&b→pop→latin`) is a 4-rung ladder
whose bottom rung the controller cannot address. Worse, `run_session.py` does:

```python
gi = ctrl.genre_order.index(cfg.genre) if cfg.genre in ctrl.genre_order else 0
```

A `calm` scene from `scene.py` **silently starts the session at `r&b`** with no warning and no
trace record. If your first participant's anchor song is a ballad, you will run the entire session
one rung off from what your Methods section says, and nothing in the CSV will reveal it. Fix
before anything else (see §5).

**(0b) `_density_saturated` / `_tempo_saturated` pick their direction from `setpoint < 0.5`, not
from the sign of the error.** With a *trajectory* setpoint this is a latent bug: a session
descending from HR 120 to 75 with `resting_hr=60, max_hr=120` has `arousal_setpoint` sweeping
1.00 → 0.25, **crossing 0.5 mid-session**. At that crossing the saturation-direction test flips
even though the error sign never changed, so the escalation logic starts asking "is density pinned
at *max*?" during a calming session. It won't be, so the counters reset and the ladder goes deaf
exactly halfway through every down-regulation run. Under the old per-bar `setpoint_script`
(`downreg` = 0.8→0.2) you had the same crossing and just never noticed because the per-bar loop
had 250 chances to recover. At segment cadence you get ~30 chances total.

**(0c) `polish()` normalizes every render to 0.95 peak.** If you polish per segment you get a
**loudness step at every crossfade**. That is the single most audible possible artifact and it is
purely an artifact of the mastering call, not of the music.

---

## Q1. Which option: A, B, C, or other?

**Answer: B for the control law, A for the code path. Not A as written, and definitely not C.**

### Why I reject Option A as written

Option A says "run the per-bar controller internally to *design* the next segment's parameters."
To iterate a per-bar loop forward without a real participant in it, you must iterate it against a
plant model. The only plant model you have is `dual_lever_plant_step`, whose own docstring says,
in capitals: *"THIS IS A FABRICATED TOY PLANT, NOT A VALIDATED PHYSIOLOGICAL MODEL."*

So Option A, implemented honestly, is a **model-predictive controller with an admittedly
fabricated model**. That is strictly worse than a simple gain: it is more machinery, harder to
explain, and it hands a reviewer a devastating one-line objection ("your live actuator decisions
are computed from a plant you state is fabricated"). Do not put the toy plant in the live path.
Keep it where it belongs — in the offline ablation/simulation figures, clearly labelled.

There is also no benefit. Rolling a per-bar PD forward 13 bars against a monotone plant from a
frozen measurement converges to approximately "one proportional step in the direction of the
error," which is what a single `step()` call already gives you. You'd be paying complexity for
arithmetic you already have.

### Why B (pure segment controller) is right, and why it costs you almost nothing

One control update per segment boundary. That is the honest description of the system, it matches
the comfort requirement exactly (nothing changes inside a segment, by construction rather than by
convention), and it makes the genre-energy ladder a *first-class* coarse actuator instead of a
tier that fires once per 250 bars.

The crucial point the brief misses: **`CascadeController` is already timescale-agnostic.** Read
the arithmetic — nothing in `PDDensityController.step`, `TempoController.step`, or
`CascadeController.step` assumes a bar. The word "bar" appears only in docstrings and in the
*names* of the hysteresis counters (`n_bars_saturated_for_tempo`, `n_bars_saturated_for_genre`).
The `dt` parameter is already documented as "seconds per control update." So Option B does **not**
require discarding the validated controller. It requires calling it once per segment with
different constants:

```python
ctrl = pdc.CascadeController(
    density_kp=6.0, density_kd=1.5,          # keep hand-tuned values (reportable)
    max_step_bpm=4.0,                        # was 8.0 — see Q4, crossfade beat-drift
    band=3.0 / (cfg.max_hr - cfg.resting_hr),# ±3 BPM deadband, DERIVED not hardcoded
    n_bars_saturated_for_tempo=1,            # read as "segments"
    n_bars_saturated_for_genre=2,            # read as "segments"
    genre_order=["calm", "r&b", "pop", "latin"],
)
```

That is the whole controller change. **Zero new controller classes. Zero edits to
`pd_controller.py`** except the two-line direction fix in (0b) and the `calm` additions in (0a).
The cascade's anti-fight discipline — density first, tempo only when density saturates, genre only
when tempo *also* saturates — is *more* defensible at segment cadence, not less, because it is now
what bounds how often the listener hears a genre change.

So: **the paper says "segment-cadence cascade" (B); the diff says "same controller, new
constants, new outer loop" (A's code-preservation goal).** You get B's clean story with A's
sunk-cost preservation. That is the synthesis.

### Why C stays out (and one piece of it I'd smuggle back in)

You rejected within-segment tempo glide and you were right: `render_midi` builds one MIDI at one
`initial_tempo`, and this project has already been burned by mid-stream tempo change — the
transition diagnosis in your own session log traced "drums speed up / sound weird" to exactly
crossfading across a tempo difference. Don't reintroduce it.

The one piece of C worth keeping is **not** control — it's *arrangement*. `drum_bar_tier` already
fires a fill at `bar_idx % 4 == 3` and a crash at `bar_idx == n_bars - 1`. That's phrase structure,
not control, and it's free (see Q4). Keep the control law flat inside a segment; let the
*arrangement* have shape.

### Pushback you did not ask for, on the premise: 60 s segments are wrong for a method paper

At 30 s segments and a 15-minute session you get **~30 control updates**. At 60 s you get **~15**.
Fifteen decisions is not a control system a reviewer can look at — it's a playlist with a
justification. Your actuator staircase figure will have 15 steps of which maybe 3 are genre steps.

Take the **30 s** end of your own range, not the middle, not 60. Three independent reasons:

1. **Control resolution.** 30 vs 15 updates doubles the resolution of every actuator figure.
2. **Musical sufficiency is already satisfied at 30 s.** At 100 BPM, 30 s ≈ 12.5 bars — three full
   cycles of the 4-bar `_PROG` progression plus a fill. That is a verse. It is not a fragment.
3. **The arithmetic below (Q3) shows 30 s is the *only* length where the deadband and the ramp
   rate are commensurate.** At 60 s the reference outruns the deadband by 2× every single
   segment, which guarantees the ladder arms every time. 30 s is not a compromise; it is the
   designed value.

---

## Q2. The HR-trajectory setpoint law

**Recommendation: a rate-limited, progress-gated linear ramp with a first-order terminal approach
and a hard lead clamp.** In control-engineering terms this is a **reference governor**, and that
is the phrase to use in Methods. Reject naked exponential; reject adaptive outright.

### The law

Let \(r\) = 6 BPM/min = 0.1 BPM/s, \(T\) = segment seconds (30), \(D\) = 3 BPM deadband,
\(L\) = 8 BPM max lead, \(\tau\) = 60 s terminal time constant, \(H_g\) = goal HR.

**Initialization (iso-principle — this matters and is cheap):**
\[ H_{\mathrm{ref}}(0) = \bar H_{\mathrm{meas}}(\text{baseline window}) \]
i.e. anchor the reference to the participant's *own measured* HR over a 60 s pre-session baseline,
not to a nominal value. Same principle `TempoController.reset()`'s docstring already states for
seeding tempo from resting HR. Log the baseline.

**Per segment boundary \(n\):**

1. Signed distance to goal: \(\Delta_n = H_g - H_{\mathrm{ref}}(n-1)\), \(s_n = \operatorname{sign}\Delta_n\).
2. **Terminal taper** (the only thing I borrow from exponential): the effective rate is
   \[ r^{\mathrm{eff}}_n = \min\!\left(r,\ \frac{|\Delta_n|}{\tau}\right) \]
   so the ramp is linear at 6 BPM/min while far away, and softens into a first-order approach
   inside the last ~6 BPM. This removes the sharp corner at arrival and the terminal ladder
   chatter that a hard corner causes. Two lines of code.
3. **Progress gate** \(g_n \in \{0, 1\}\) — the anti-windup, and the most important line in the law:
   \[ g_n = \begin{cases} 0 & \text{if } s_n\,\big(H_{\mathrm{ref}}(n-1) - \bar H_{\mathrm{meas}}(n)\big) > L \quad \text{(participant is lagging past the lead clamp)} \\ 1 & \text{otherwise} \end{cases} \]
4. Advance: \(H_{\mathrm{ref}}(n) = H_{\mathrm{ref}}(n-1) + s_n \cdot \min\!\big(|\Delta_n|,\ r^{\mathrm{eff}}_n T g_n\big)\)
5. Clamp lead unconditionally: \(H_{\mathrm{ref}}(n) \leftarrow \bar H_{\mathrm{meas}}(n) + \operatorname{clip}\big(H_{\mathrm{ref}}(n) - \bar H_{\mathrm{meas}}(n),\ -L,\ +L\big)\)
6. Convert once, at the boundary: `setpoint_arousal = mapper.to_arousal(H_ref(n))`, hand to
   `ctrl.step()`. The existing arousal framing is **untouched** — HR trajectory generation sits
   *upstream* of `HRArousalMapper`, which is exactly where a reviewer expects a per-subject
   calibration to sit.

### Why linear over exponential

- **Reportability.** The claim becomes "the reference advanced at a pre-registered bounded rate
  of 6 BPM/min." One number, checkable by eye against the slope of a line in Figure 1. An
  exponential's rate is a function of time and you end up reporting τ *and* the initial slope
  anyway.
- **An exponential's steepest slope is at \(t=0\)** — precisely when the participant is most
  aroused and least able to follow. \(H_g + (H_0-H_g)e^{-t/\tau}\) with \(H_0=120, H_g=75,
  \tau=180\,\mathrm{s}\) starts at 15 BPM/min. To honour "bounded rate ~6 BPM/min" you must
  rate-limit it — at which point you have implemented a linear ramp with a soft tail, which is
  exactly what I recommend above. So the recommendation *is* the sensible exponential, arrived at
  from the defensible direction.
- **The physiology literature specifies rates, not time constants.** Paced-breathing and
  iso-principle down-regulation protocols are described as bounded rates of change. Linear is the
  native vocabulary.

### Why adaptive is a trap at n = 5–8

Adaptive means online identification of a per-subject plant gain. You have ~30 control updates
per subject, an unmeasurable and non-stationary disturbance (the participant's own thoughts), and
no held-out data. You cannot identify that plant, and the moment you claim to, a reviewer asks for
the identification validation study you didn't run. Worse: an adaptive gain makes each
participant's trace a different system, which destroys the one thing a method paper needs —
**that every session ran the same, fully specified, pre-registered controller.**

If you want per-subject adaptation, put it where it is already legitimate and already in the code:
`HRArousalMapper(resting_hr, max_hr)` calibrated once, offline, before the session. That is
adaptation you can document in one paragraph.

### The premise I *do* push back on

"HR now = 120, goal = 75" is not a realistic seated-baseline down-regulation. A seated adult at
rest is 60–80; 120 seated means acute stress or you just induced it. If you are *not* running a
stressor task, your participants will start at ~75 and your goal will be ~65, giving you **10 BPM
of total range against a 3 BPM deadband and ±0.7 BPM of residual noise** — a 3:1 dynamic range for
the entire study. That is thin. Two options, pick one and write it down before collecting:
(a) include a brief validated arousal induction (e.g. a mental-arithmetic or Stroop block) so
there is genuinely something to down-regulate from; or (b) run **up-regulation** as the primary
direction, where the range is real (75 → 100 is 25 BPM) and the ladder has three rungs of
headroom above the start. I lean (b) for a method paper — it is a bigger, cleaner actuator
excursion, it exercises the ladder in the direction where all four rungs are reachable, and it
requires no stressor and hence a much lighter IRB conversation. Down-regulation is the more
*interesting* application, but up-regulation is the better *demonstration*, and this paper is a
demonstration.

---

## Q3. Deadband × ladder step × segment cadence

Do the arithmetic first; the design falls out of it.

### The arousal↔BPM conversion is already fixed by your own code

`HRArousalMapper`: `arousal = (bpm - resting)/(max - resting)`. With the `SessionConfig` defaults
(`resting_hr=60, max_hr=120`) the span is 60 BPM, so:

| quantity | BPM | arousal |
|---|---|---|
| 1 BPM | 1 | 0.01667 |
| **deadband ±3 BPM** | 3 | **0.0500** |
| ramp 6 BPM/min | 6 | 0.1000/min |
| ramp over a 30 s segment | 3.0 | 0.0500 |
| ramp over a 60 s segment | 6.0 | 0.1000 |

Two consequences, and they are the design:

**(i) `CascadeController`'s default `band=0.05` *already is* the ±3 BPM deadband** under the
default calibration. That is a genuine gift — the validated controller's tolerance band and the
researcher's newly-specified deadband are the same number. But **do not hardcode 0.05**, because
per-subject calibration changes the span: `band = deadband_bpm / (max_hr - resting_hr)`. Log both
`band` and `hr_deadband_bpm` so the mapping is auditable.

**(ii) At 30 s, the reference advances exactly one deadband width per segment.** This is the
clean design point: the deadband is "one segment of ramp." A participant who follows the ramp
stays in band; a participant who makes *no* progress for one segment is exactly at the band edge;
two segments of no progress puts them clearly outside. That is a self-consistent, explainable
arming rule.

At 60 s the reference advances **two** deadband widths per segment, so a participant who lags even
slightly is guaranteed out of band after a single segment, every segment. The ladder arms
continuously. This is the arithmetic proof that 60 s is the wrong choice, and it is the argument
to use with yourself.

### The ladder-stepping rule (concrete, all four conditions required)

Step the ladder at most one rung, and only when **all** hold:

1. **Persistence:** \(|e_n| > D\) for **N = 2** consecutive segment boundaries (≈60 s of
   sustained, not momentary, tracking failure). Yes to the brief's proposed "N consecutive
   segments" — N = 2 specifically.
2. **Re-arm hysteresis (Schmitt, not a bare threshold):** the counter increments only while
   \(|e_n| > D + h\) with \(h = 1\) BPM, and resets only when \(|e_n| < D - h\). Without this the
   counter chatters when the error sits near D. You already use exactly this pattern in
   `TierMapper` (`hysteresis=0.25` tier-fraction); reuse the idea, don't reinvent it.
3. **Cascade precedence (keep it — this is what makes the validated architecture still true):**
   tempo *and* tier must be saturated in the needed direction. This is `CascadeController`'s
   existing `_consec_tempo_saturated >= n_bars_saturated_for_genre` gate, with the counter now
   ticking in segments. Do not bypass it; it is the difference between "coarse actuator in a
   cascade" and "genre roulette."
4. **Minimum dwell:** ≥ **M = 2** segments since the last genre change. With 30 s segments this
   caps genre changes at one per 60 s and, combined with (1), at roughly **one per 90–120 s** in
   practice → **~3–5 genre changes in a 15-minute session.** That is a musically defensible
   number: it is a set, not a shuffle.

**Asymmetry — do this, it is cheap and it is the right call:** N = 2 for the calming direction,
**N = 3** for the exciting direction. Rationale: over-arousing a participant is the direction with
ethical and data-quality consequences, so require more evidence before escalating upward. It also
means a transient artifact (a movement spike on the H10) cannot ratchet you up the ladder. State
the asymmetry explicitly in Methods; a reviewer will read it as care, not as a fudge.

**Ladder authority bookkeeping — the thing that will quietly ruin a session.** The ladder is a
4-rung actuator with ±1 step per ≥2 segments. Its *total authority in a session is bounded*, and
if `scene.py` starts you at a rail you have **zero** coarse-actuator headroom in the needed
direction and your headline contribution is invisible in that participant's trace. `scene.py`
will happily hand you `calm` for a 74-BPM ballad anchor (its own `__main__` demonstrates exactly
that row). Therefore: **clamp the initial rung to the ladder interior** — rung ∈ {1, 2} for
down-regulation, rung ∈ {0, 1} for up-regulation — and log `ladder_rung_initial` *and*
`scene_genre_requested` so any clamping is visible in the CSV rather than silent.

While you are there: `scene.py`'s module docstring currently asserts *"genre-morph mid-session is
a locked-out confound."* Under this redesign that sentence is **false and load-bearing in the
wrong direction**. Rewrite it now, or a future you will read it and trust it.

---

## Q4. Pre-generation and crossfade

### The latency situation is far better than you think — and it collapses the whole problem

Measured: p50 ≈ 221 ms, p95 ≈ 330 ms per bar. A 30 s segment at 100 BPM is ~13 bars.

| | per-bar path (13 separate FluidSynth calls) | budget | margin |
|---|---|---|---|
| p50 | 13 × 221 ms ≈ **2.9 s** | 30 s | **10.4×** |
| p95 | 13 × 330 ms ≈ **4.3 s** | 30 s | **7.0×** |

And you should not use 13 calls. **Render the whole segment as ONE `PrettyMIDI` and ONE
`render_midi()` invocation.** `render_midi` spawns a `fluidsynth` subprocess per call, and process
startup + soundfont load dominates that 221 ms far more than note count does — one call for 13
bars will land well under 2 s. Margin ~15×+.

**With 15× margin, there is no pre-generation race and no need for clever concurrency.** The whole
"generate ahead" problem reduces to: one background render, one 1-deep queue.

### The concrete mechanics

You need something you do not currently have at all: **an audio output clock.** `run_session()`
today appends bar buffers to `audio_chunks` and writes a WAV at the end — it never plays anything.
For a live participant session that is a hole, and the segment design is precisely what makes it
easy to fill.

```python
# player.py — NEW file, ~50 lines. Injected exactly like `renderer` already is.
class SoundDevicePlayer:
    """Pull-model playback. Segment audio is pushed; a callback drains it."""
    def __init__(self, sr=44100, blocksize=2048):
        import sounddevice as sd, queue
        self.q = queue.Queue(maxsize=3)
        self.underruns = 0
        self._tail = None
        def cb(outdata, frames, t, status):
            if status:                      # xrun flag from PortAudio
                self.underruns += 1
            ...  # drain self._tail / self.q into outdata, zero-fill on empty
        self.stream = sd.OutputStream(samplerate=sr, channels=2,
                                      blocksize=blocksize, callback=cb)
    def push(self, audio): self.q.put(audio)      # blocks if 3 segments queued
    def start(self): self.stream.start()

class NullPlayer:                 # DEFAULT — keeps headless/CI path bit-identical
    underruns = 0
    def push(self, audio): pass
    def start(self): pass
```

Main-thread structure, no locks, no shared mutable state:

```
render segment 0                     # blocking, ~2 s
player.push(segment 0); player.start()
for n in 1 .. N:
    control update at boundary n     # ctrl.step() ONCE, from smoothed HR
    render segment n (with 1-bar overlap head)   # ~2 s, inside a 30 s window
    crossfade tail(segment n-1) with head(segment n)
    player.push(segment n)           # blocks ~28 s -> this IS the clock
```

`player.push()` blocking on a bounded queue *is* your timing discipline. Do not add a timer.

### Crossfade: do it symbolically, and exploit the cascade's quiescence

**You do not need beat detection.** Both segments are symbolically rendered at known tempos, so
you know every downbeat sample-exactly. Concretely:

- Render segment \(n\) as `bars_per_segment + 1` bars. The extra head bar is the fade-in
  material, so the fade region is real audio on both sides — never audio-into-silence.
- Align the incoming segment's **downbeat** to the outgoing segment's next downbeat. Equal-power
  cos/sin ramp (your own earlier work measured boundary discontinuity 0.003–0.038 vs the beds'
  own transients up to 0.31 — equal-power bar-aligned fades are click-free here; that is settled).
- **Fade length: 2 beats (~1.2 s at 100 BPM).** Not one bar. Reason: beat drift. When tempos
  differ by \(\delta\) BPM, the two grids diverge; at the *midpoint* of a 2-beat fade (where both
  sources are at ~50 % gain and drift is most audible) the divergence with `max_step_bpm=4` at
  ~100 BPM is ≈ **25 ms** — a soft flam, at the edge of audibility. A full-bar fade doubles that
  to ~50 ms, which will be heard on kicks. Hence also `max_step_bpm: 8.0 → 4.0`.
- **Do not time-stretch.** The `crossfade_pieces()`/time-stretch path already exists in this
  project's history and it is overkill for a ≤4 BPM delta.
- **The cascade gives you free beat-matching, and this is the nicest structural point in the
  whole design:** under the anti-fight discipline, tempo is *quiescent* unless density/tier has
  saturated. So the **majority of segment transitions will have `tempo_delta == 0` — perfect,
  sample-exact beat match.** Only escalation transitions carry a ≤4 BPM delta. Log
  `xfade_tempo_delta_bpm` per transition and report its distribution; "78 % of transitions were
  exactly beat-matched" is a real, cheap, quantitative claim about musical quality.
- **Genre transitions** are drift-free (tempo unchanged) but timbrally abrupt. Mask them:
  `drum_bar_tier` **already** fires a fill at `bar_idx % 4 == 3` and a `CRASH` at
  `bar_idx == n_bars - 1`. Pass `bar_idx = bar_in_segment` and `n_bars = bars_per_segment` instead
  of the current global `bar` / `cfg.n_bars`, and you get a fill-and-crash on the last bar of every
  segment **for free** — an idiomatic transition cue that masks the seam. Two argument changes.

### Two renderer changes, and one audio-quality win you should take

```python
# renderer.py
# 1. Factor _bar_midi's body into _write_bar(insts, t0, tier, tempo, genre, bar_idx, n_bars)
#    (pure move, no logic change), then:
def render_segment(self, tier, tempo_bpm, genre, n_bars, xfade_head_bars=1):
    m = pm.PrettyMIDI(initial_tempo=tempo_bpm)
    insts = self._make_instruments(genre)
    spb = 60.0 / tempo_bpm
    for b in range(n_bars + xfade_head_bars):
        self._write_bar(insts, b * spb * 4, tier, tempo_bpm, genre,
                        bar_idx=b, n_bars=n_bars)     # phrase-aware fills/crash
    for i in insts: m.instruments.append(i)
    return self._render(m)      # ONE fluidsynth call
```

**Turn `polish` ON at segment level.** It is currently `polish=False` with the comment "reverb tail
bleeds across bars" — that constraint **disappears** when the unit of rendering is a whole
segment. So this redesign is also a genuine *audio-quality upgrade*: reverb tails resolve, no
per-bar seams. Say that in the paper; it is a real benefit of the architecture, not a side effect.

**But:** `polish()` ends with `mix = mix/(max|mix|+1e-9)*0.95` — per-call peak normalization. Call
it per segment and **every crossfade gets a loudness step.** Fix: add a `normalize=False` flag (or
apply a single fixed gain calibrated once at session start from the loudest reachable
tier/genre combination) and log `segment_peak` / `segment_rms_db` per segment so any residual
level drift is visible in the CSV rather than only in a participant's ears.

**Terminology pushback:** a 30 s segment is 3 loops of a fixed 4-bar `_PROG` progression with a
fill. Do **not** call that a "song" in the paper — a music reviewer will flag it in one line. Call
it a **segment** or a **cue**. It costs you nothing and it removes an attack surface. The
alternative (real arrangement: intro/verse/turnaround) is a music-generation project you do not
have time for and which is orthogonal to the control contribution.

---

## Q5. Minimum change to `run_session()` and the trace schema

**Governing principle: the trace row cadence stays PER BAR. Control cadence becomes per segment.**

This is the single most important decision in the whole redesign and I want to be emphatic about
it. Logging one row per *segment* would give you ~30 rows per session, destroy `render_ms` /
`deadline_miss` (your validated latency figure), and silently invalidate every analysis script
that reads `COLUMNS`. Keeping per-bar rows costs nothing (13 near-identical rows per segment; a
CSV row is bytes) and buys you three things:

1. Your tracking figure stays **dense** — HR is sampled every bar, so the measured-HR trace is
   smooth even though the actuator staircase is sparse.
2. `is_segment_boundary` makes every staircase figure a one-line filter.
3. **`groupby('segment_idx')[plan_cols].nunique().max() == 1` is a machine-checkable proof that
   nothing changed inside a segment.** That is the comfort claim, verified from the artifact
   rather than asserted in prose. Free, and reviewer-proof.

### `run_session()` — the minimum diff

**Do not delete anything.** Keep `setpoint_script()` (unused, for the ablation and back-compat).
Keep `MockRenderer`, `TierMapper`, `HRArousalMapper`, the DictWriter + per-row flush.

1. **New file `hr_trajectory.py` (~45 lines).** `HRTrajectory` implementing Q2 exactly. New file,
   so zero risk to validated code, and independently unit-testable.
2. **`SessionConfig` additions** (all defaulted; existing call sites keep working):
   `segment_seconds=30.0`, `n_segments=30`, `bars_per_segment=None` (derived:
   `round(segment_seconds / (4*60/tempo))`, recomputed per segment since tempo changes),
   `hr_goal_bpm=75.0`, `hr_ramp_bpm_per_min=6.0`, `hr_deadband_bpm=3.0`, `hr_deadband_hyst_bpm=1.0`,
   `hr_max_lead_bpm=8.0`, `terminal_tau_s=60.0`, `hr_smooth_window_s=30.0`,
   `n_seg_out_of_band_calm=2`, `n_seg_out_of_band_excite=3`, `min_genre_dwell_segments=2`,
   `xfade_beats=2`, `ladder=("calm","r&b","pop","latin")`, `polish_segments=True`.
   Keep `n_bars` as a derived/reported field, not the loop bound.
3. **Nest the loop.** The existing body splits cleanly:

```python
for seg in range(cfg.n_segments):
    hr_s   = hr_window.mean()                     # 30 s trailing, artifact-gated (Q6)
    hr_ref = traj.step(hr_s)                      # NEW
    e_bpm  = hr_ref - hr_s
    out    = ctrl.step(setpoint=mapper.to_arousal(hr_ref),   # SAME validated call
                       measurement=mapper.to_arousal(hr_s))  # ONCE per segment
    tier_cmd, tier_applied = tiers.step(out["density"])      # SAME, once per segment
    plan = freeze(genre=out["genre"], tempo=out["tempo_bpm"], tier=tier_applied)

    t0r = time.monotonic()
    audio = renderer.render_segment(**plan, n_bars=bars_per_segment)
    pregen_ms = (time.monotonic() - t0r) * 1000

    audio = crossfade(prev_tail, audio, beats=cfg.xfade_beats, tempo=plan.tempo)
    player.push(audio)                            # blocks ≈ segment_seconds -> the clock

    for b in range(bars_per_segment):             # TRACE ONLY. No control. No mutation.
        w.writerow(row(seg, b, plan, hr_ref, e_bpm, ...)); fh.flush()
```

4. **Injected `player`, defaulting to `NullPlayer`** — same pattern already used for `renderer`,
   so the headless/CI path stays bit-identical and Phase 0's passed stress test remains valid.
5. **The (0a)/(0b) fixes in `pd_controller.py`:** add `"calm"` to `GENRE_ENERGY_ORDER` at index 0;
   add `GENRE_EQUILIBRIUM_BAND["calm"] = (0.03, 0.50)` — **must sit below r&b's 0.68 ceiling** or
   the band logic that makes the genre tier causally necessary in simulation stops working;
   change `_density_saturated`/`_tempo_saturated` to branch on `error >= 0` instead of
   `setpoint >= 0.5`. Then **re-run the existing `__main__` self-test** — its calming scenario has
   `setpoint=0.15` with high measurement, so error is negative and the direction is unchanged; the
   monotonic-genre-walk-down assertion should still pass. That is your regression gate, and it
   already exists.
6. **`RUNG_TIER_CAP = {"calm": 2, "r&b": 4, "pop": 5, "latin": 5}`** in the renderer, ~3 lines.
   Without it the `calm` rung is not actually a lower rung: `_drum_genre("calm")` returns `"pop"`,
   so a tier-5 `calm` segment renders **pop drums at full intensity** — 16th hats, ghost snares,
   crash — which is louder and busier than a tier-2 r&b segment on the rung above it. Your energy
   ladder would be non-monotonic at the bottom, which is fatal to the whole premise. This cap is
   the 3-line fix; the alternative (a bespoke `calm` branch in `drum_bar_tier`) touches validated
   drum code for no additional benefit.

### Trace schema: append-only. Never remove, never redefine.

Keep all 17 existing columns with their exact current meanings. In particular **do not redefine
`error`** — it stays arousal-domain (`arousal_setpoint - arousal_measured`); the BPM-domain error
is a new, separately named column. Append at the end of `COLUMNS`:

**Segment structure (4)**
- `segment_idx` int — 0-based segment counter
- `bar_in_segment` int — 0-based bar within segment
- `is_segment_boundary` int 0/1 — 1 on the bar carrying the control update
- `segment_seconds` float — logged per row, so a mid-study config change is auditable

**HR trajectory (7)**
- `hr_bpm_smoothed` float — the 30 s artifact-gated mean actually fed to the controller
  (`hr_bpm_raw` stays the raw sample — log both, always)
- `hr_ref_bpm` float — the reference this segment (the NEW primary setpoint)
- `hr_goal_bpm` float — session terminal target
- `hr_ref_rate_bpm_per_min` float — the **effective** rate applied (post gate + taper). This is
  the honest column: it is how the trace reveals when the ramp froze.
- `hr_traj_error_bpm` float — `hr_ref_bpm - hr_bpm_smoothed`
- `ramp_frozen` int 0/1 — progress gate engaged
- `hr_deadband_bpm` float — the configured deadband (pairs with `band` for the auditable mapping)

**Deadband / ladder (5)**
- `in_deadband` int 0/1
- `consec_out_of_band` int — the arming counter
- `ladder_rung` int — 0=calm … 3=latin
- `ladder_step` int ∈ {−1, 0, +1} — what the ladder did at this boundary
- `segments_since_genre_change` int — dwell counter

**Frozen plan (3) — the within-segment-invariance audit**
- `segment_plan_genre` str, `segment_plan_tempo_bpm` float, `segment_plan_tier` int

**Pre-generation / transition / playback (6)**
- `pregen_ms` float — wall time to render the NEXT segment (NaN off-boundary) → new latency figure
- `pregen_margin_ratio` float — `segment_seconds / (pregen_ms/1000)`
- `xfade_beats` int, `xfade_tempo_delta_bpm` float — transition audit
- `segment_peak` float — catches the `polish()` normalization trap
- `underrun` int 0/1 — audio buffer underrun; with playback added, the **only** thing that can now
  ruin a session in a way you couldn't detect afterwards

**Provenance (2)**
- `ladder_rung_initial` int, `scene_genre_requested` str — makes the (0a) silent fallback and any
  interior clamping visible

25 new columns → 42 total. That is fine: CSV is cheap and each column answers one specific
reviewer question. **If you want the irreducible minimum, it is these eight:**
`segment_idx`, `is_segment_boundary`, `hr_ref_bpm`, `hr_traj_error_bpm`, `in_deadband`,
`ladder_rung`, `pregen_ms`, `underrun`. Everything else you will wish you had logged, but those
eight are the ones without which the paper cannot be written.

---

## Q6. The biggest landmine

**The ±3 BPM deadband sits below the physiological noise floor of unsmoothed HR. As specified,
the ladder will walk to a rail within ~3 minutes of every session and pin there. Every
participant's trace will look identical and the coarse actuator will look broken.**

This is arithmetic, not speculation. Beat-to-beat HR from a Polar H10's RR intervals swings on
the order of **±5–10 BPM** in a perfectly calm seated adult from respiratory sinus arrhythmia
alone — inhale up, exhale down, every breath. A ±3 BPM deadband on instantaneous HR is therefore
**inside** the noise. Consequence chain, all of which is forced:

`|e| > D` on essentially every boundary → `consec_out_of_band` arms every 2 segments → combined
with the ≥2-segment dwell, the ladder steps roughly **every 60–90 s** → a 4-rung ladder reaches a
rail in **~3 minutes** → it saturates and stays there for the remaining 12 minutes. You then also
get the *musical* failure the redesign was supposed to prevent: a genre change every 90 s driven
by respiration, not by state.

### The fix (all four parts; none is optional)

1. **Make the measurement window equal the control period.** Feed the controller a **30 s trailing
   mean of HR computed from artifact-gated RR intervals**, sampled at the segment boundary. This is
   the textbook-correct choice — for a controller with period \(T\), the measurement window should
   be \(\approx T\) — and here it is *free* because you already have to wait 30 s anyway.
2. **Verify the resulting margin.** ~35 beats in 30 s at ~70 BPM; beat-to-beat SD ~4 BPM ⇒
   SEM ≈ \(4/\sqrt{35}\) ≈ **0.7 BPM**. A 3 BPM deadband is then **~4σ** — comfortably above
   noise, and the whole failure chain above evaporates. State this calculation in Methods; it
   turns the deadband from an arbitrary number into a derived one.
3. **Artifact gating before averaging** (standard HRV practice, ~8 lines): reject RR outside
   [300, 2000] ms and any beat >20 % from the running median. A single ectopic beat or a chest-strap
   movement artifact can otherwise shift a 35-beat mean by several BPM — i.e. by more than your
   entire deadband. Log the rejection count per segment.
4. **Pre-register the window and the gate before you collect data.** If `hr_smooth_window_s`
   appears in your config *after* the first participant, it reads as post-hoc tuning of the exact
   parameter that determines whether your actuator fires. Write it into Methods now, freeze it,
   and log both `hr_bpm_raw` and `hr_bpm_smoothed` so anyone can recompute your smoothing from the
   artifact.

**Runner-up landmine, for completeness:** the ladder-authority problem in Q3 — a `scene.py`-chosen
starting rung at a rail leaves the coarse actuator with zero headroom, silently, because of the
(0a) fallback bug. Fix: clamp the initial rung to the ladder interior and log
`ladder_rung_initial` + `scene_genre_requested`.

---

## Q7. Impact on the paper's claim and figures

**Yes, it changes both — and it makes the paper better, which is the framing to use.**

### The claim

From: *"per-bar closed-loop physiological music control."*
To: **"Segment-cadence closed-loop control of a physiological setpoint *trajectory*, with a
genre-energy ladder as the coarse actuator, and pre-generated crossfaded segments as the
actuation mechanism."**

Frame this as **fixing a latent validity problem, not as a scope change.** The per-bar
architecture contained an unvalidated implicit claim — that per-bar musical morphing is a
*desirable* actuation strategy — which you have now falsified by ear. Saying so in the paper is a
strength, not an admission: it is exactly the kind of system-design finding a method paper at a
TEI/CHI-adjacent venue is *for*. A "we built it, listened to it, and the architecture was wrong at
the fast timescale" paragraph is more publishable than a clean-looking system nobody listened to.

Two free framing wins fall out:

- **The two-timescale story gets cleaner and more honest.** Previously control *and* rendering both
  ran at bar rate, so the "two timescales" were somewhat notional. Now: **rendering is fast
  (per-bar, pre-generated, batched into segments); control is slow (per-segment).** That is a real
  separation of concerns and a better architecture diagram.
- **You acquire a music-therapy literature for free.** A bounded-rate reference trajectory that
  starts matched to the listener's current state and walks toward a target *is* the
  **iso-principle**. The `TempoController.reset()` docstring already invokes it. That connects the
  paper to an established clinical-practice literature rather than to control theory alone, which
  broadens reviewers who can champion it. "Reference governor" + "iso-principle" is a genuinely
  novel pairing and is arguably the paper's best sentence.

### Figures

| | before | after |
|---|---|---|
| **F1 Tracking** | **CHANGED (improved)** | y-axis becomes **HR in BPM**, not arousal: measured HR, the `hr_ref` ramp, `hr_goal`, and the ±3 BPM deadband as a shaded ribbon. Far more legible to a non-control reader, and directly interpretable. Keep an arousal-domain inset so the `HRArousalMapper` calibration stays auditable. |
| **F2 Actuator staircase** | **CHANGED (sparser — this is the cost)** | Step plot vs `segment_idx`, three stacked lanes: ladder rung, tempo, tier. ~30 steps instead of ~250 bars. Honest cost of the redesign; mitigated by taking 30 s not 60 s segments. |
| **F3 Latency** | **REPLACED (stronger)** | Per-bar deadline-miss histogram loses meaning — with a frozen segment you are no longer under a per-bar deadline. Replace with **pre-generation margin**: `pregen_ms` against the 30 s budget (~10–15×). Keep the per-bar `render_ms` distribution as a sub-panel; you already measured it and it is free. |
| **F4 Transition audit** | **NEW — and you need it** | RMS envelope around each crossfade with `xfade_tempo_delta_bpm` annotated, plus the distribution of tempo deltas ("N % of transitions exactly beat-matched"). This is how you evidence *comfort* without making an efficacy claim — the objection "is it actually pleasant?" gets a quantitative answer instead of a promise. |
| **F5 Ablation** | **AT RISK — must be replaced** | See below. |

**F5 deserves its own paragraph because it is the figure this redesign breaks.** Your existing
ablation is cascade-vs-naive-parallel, and its punch came from the parallel controller *visibly
oscillating* at bar rate. At segment cadence with a 2-segment dwell and a deadband, the naive
parallel controller **won't visibly oscillate** — the dwell and deadband suppress it on their own.
Your ablation would show two nearly identical traces and prove nothing.

Replacement, and it is a better ablation anyway: **ablate the comfort mechanisms.** In simulation,
run (i) deadband on/off and (ii) dwell on/off, and report **genre changes per 15 minutes** and
**mean absolute tracking error**. Expect roughly *3–5 genre changes with both mechanisms vs 15+
without*, at comparable tracking error. That figure demonstrates that the comfort machinery is
doing real work at negligible control cost — which is precisely the contribution of the redesign.
Demote the old cascade-vs-parallel contrast to a simulation-only supplementary figure (it still
justifies the cascade *structure*, just not at this cadence).

**One statistical note.** ~30 control updates × 5–8 participants ≈ 150–240 control decisions total.
Report it as **system characterization with per-session traces shown individually.** Do not run a
group inferential test on n = 6 — the publishability framing is already LOCKED as SYSTEM/METHOD,
not efficacy, and a p-value on six people is the fastest way to invite the efficacy critique you
have deliberately avoided.

---

## BOTTOM LINE

Adopt **Option B semantically and Option A operationally**: make the live control law a genuine
one-update-per-segment controller — that is the honest, comfortable, defensible story — but
implement it by calling the *existing, validated* `CascadeController.step()` exactly once per
segment with new constants (`band = 3.0/(max_hr − resting_hr)`, `max_step_bpm = 4.0`, saturation
counters 1 and 2 read as segments, `genre_order = ["calm","r&b","pop","latin"]`), so you write
**zero new controller code** and never put the admittedly-fabricated `dual_lever_plant_step` in the
live path the way a literal reading of Option A would require. Track a **rate-limited,
progress-gated linear reference with a first-order terminal taper and an 8 BPM lead clamp** — a
reference governor, upstream of the untouched `HRArousalMapper` — and step the ladder at most one
rung only when the error exceeds ±3 BPM (with 1 BPM Schmitt re-arm) for 2 consecutive segments
(3 when exciting), tempo and tier are already saturated, and ≥2 segments have elapsed since the
last genre change; that yields ~3–5 genre changes per 15 minutes, which is a set rather than a
shuffle. Take **30 s segments, not 60**: at 30 s the reference advances exactly one deadband per
segment, which is self-consistent, whereas at 60 s it advances two and the ladder arms every
single segment — and 30 s doubles your control resolution to ~30 updates, which matters because
~15 decisions is a playlist, not a control system. Keep the trace **one row per bar** while moving
control to per segment, appending ~25 columns (irreducibly: `segment_idx`, `is_segment_boundary`,
`hr_ref_bpm`, `hr_traj_error_bpm`, `in_deadband`, `ladder_rung`, `pregen_ms`, `underrun`) so the
dense tracking figure and the validated latency data survive and so
`groupby('segment_idx').nunique() == 1` becomes a machine-checkable proof of within-segment
invariance. Render each segment as **one** MIDI and one FluidSynth call (≈2 s against a 30 s
budget, ~15× margin — so a single background render and a 1-deep queue is all the concurrency you
need), turn `polish` **on** now that reverb tails no longer bleed across bar seams but disable its
peak normalization or every crossfade gets a loudness step, and crossfade **2 beats** equal-power
at aligned downbeats, exploiting the fact that the cascade's quiescence makes most transitions
exactly beat-matched. Before any of this, fix the three code faults I found — `"calm"` missing from
`GENRE_ENERGY_ORDER`/`GENRE_EQUILIBRIUM_BAND` (currently a silent fallback to `r&b` in
`run_session`), the `setpoint < 0.5` direction test that flips mid-session under a trajectory
setpoint, and the absent per-rung tier cap that lets a tier-5 `calm` segment render full pop drums
and thereby make your energy ladder non-monotonic at the bottom. And treat the real landmine as
the priority it is: **a ±3 BPM deadband on unsmoothed HR is below the respiratory noise floor and
will pin the ladder at a rail within three minutes of every session** — feed the controller a 30 s
artifact-gated trailing mean (SEM ≈ 0.7 BPM, so 3 BPM becomes a ~4σ band), pre-register that
window before you collect, and log raw and smoothed HR side by side. Do all this and the paper
gets *stronger*, not merely different: you are fixing a latent validity problem — per-bar morphing
was an unvalidated assumption you have now falsified by ear — the fast/slow split becomes honest
(rendering fast, control slow), and you inherit the iso-principle literature for free; the price
is a sparser actuator figure and a replaced ablation (deadband/dwell on-off, counting genre changes
per session, which is a better ablation than cascade-vs-parallel was anyway).
