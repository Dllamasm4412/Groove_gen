"""PD (Proportional-Derivative) controller for GrooveGen's closed-loop demo.

Roadmap 4.4 (software-only closed-loop demo, TEI 2027 paper). This module is
the control-layer counterpart to the per-bar fast-loop entry point built in
`hybrid_render.render_aligned_drum_bar` (Roadmap 4.1). It implements EXACTLY
the control law specified in `ARCHITECTURE_TWO_TIMESCALE.md` §5 ("Control
layer"), evaluated once per bar:

    e(k)  = setpoint - measurement(k)                      (§5.1)
    u(k)  = Kp * e(k) + Kd * (e(k) - e(k-1)) / dt           (§5.1)
    d(k+1) = clip(d(k) + u(k), d_min, d_max)                (§5.1, §5.3)

Two design choices are called out explicitly in the architecture doc and
preserved here:

- **PD, not PID** (§5.2): no integral term. Physiological features are
  already windowed/smoothed upstream (HRV, SCL), so an added integral term
  risks wind-up against a bar-quantized actuator. There is also no
  persistent steady-state disturbance to reject here.
- **Density is the ONLY controlled variable** (§5.4): event_density has a
  reported linear, monotonic relationship with perceived groove/arousal
  across the literature cited in §5.4, so a PD controller's sign is stable
  across its whole operating range. Syncopation is documented in the same
  section to have a non-monotonic (inverted-U / Wundt curve) relationship
  with perceived groove and is therefore explicitly NOT touched by this
  controller -- it stays a fixed, independently-clamped "spice" parameter
  ([0.20, 0.40] per §5.3) wherever this controller's output is consumed.

This module has NO dependency on the audio engine -- it is pure control-loop
arithmetic (numpy only) so it can be unit-tested and reused independently of
`hybrid_render`/`groovegen`.
"""
from __future__ import annotations

import numpy as np

__all__ = [
    "PDDensityController",
    "synth_physiology",
    "TempoController",
    "CascadeController",
    "GENRE_ENERGY_ORDER",
    "synth_hr",
    "dual_lever_plant_step",
    "GENRE_EQUILIBRIUM_BAND",
]


class PDDensityController:
    """Discrete-time PD controller whose output IS the next event_density.

    Call `step(setpoint, measurement)` once per bar. Internally this:
      1. computes the error e(k) = setpoint - measurement,
      2. computes a derivative term from the change in error across the two
         most recent calls (finite difference, divided by dt),
      3. computes u(k) = Kp*e(k) + Kd*de/dt,
      4. adds u(k) to the *current* density state d(k) to get a raw proposed
         density d(k) + u(k),
      5. clips the result to [density_min, density_max] and rounds to the
         nearest integer (event_density is an integer knob on the fast-loop
         renderer -- see `hybrid_render.render_aligned_drum_bar`),
      6. stores that integer as the new density state d(k+1) and returns it.

    This mirrors ARCHITECTURE_TWO_TIMESCALE.md §5.1's
    `d(k+1) = clip(d(k) + u(k), d_min, d_max)` update and the reflecting-
    boundary clamp behavior described in §5.3 (a `clip`, not a hard rail
    that would bias the walk/controller distribution at the edges -- callers
    that want true "reflection" rather than clamping can post-process the
    returned value, but clip-to-range is what §5.1/§5.3 specify and is what
    is implemented here).

    Parameters
    ----------
    kp : float
        Proportional gain (K_p in §5.1).
    kd : float
        Derivative gain (K_d in §5.1).
    density_min, density_max : int
        Hard bounds on the returned event_density (the fast-loop renderer's
        safe/tested range; see step_perbar_findings.md for empirical
        behavior across this band, including the r&b/soul hat-base plateau
        below ~density 12).
    dt : float or None
        Seconds per control update (one bar period, §6.3 of the
        architecture doc: bar_seconds = 4 * 60 / tempo_bpm). If None
        (default), dt=1.0 is used and `step()` operates in units of "per
        control update" rather than "per second" -- this is equivalent up to
        a constant rescaling of Kd and is the simplest way to run the
        controller in a notebook/demo where every call already corresponds
        to exactly one bar.

    Notes on state
    --------------
    The controller keeps two pieces of state across calls: the previous
    error e(k-1) (for the derivative term) and the current density d(k)
    (so each call's output is an *increment* from the last commanded
    density, not a re-derivation from scratch). Call `reset()` to clear
    both, e.g. at the start of a new demo run.
    """

    def __init__(self, kp: float, kd: float, density_min: int = 3,
                 density_max: int = 20, dt: float | None = None):
        if density_min > density_max:
            raise ValueError("density_min must be <= density_max")
        self.kp = float(kp)
        self.kd = float(kd)
        self.density_min = int(density_min)
        self.density_max = int(density_max)
        self.dt = 1.0 if dt is None else float(dt)
        if self.dt <= 0:
            raise ValueError("dt must be > 0")
        self.reset()

    def reset(self, initial_density: int | None = None) -> None:
        """Clear controller state. Call at the start of a fresh run.

        `initial_density` seeds d(k) (defaults to the midpoint of
        [density_min, density_max]) so the very first `step()` call has a
        sensible base to increment from.
        """
        self._prev_error: float | None = None
        if initial_density is None:
            initial_density = round((self.density_min + self.density_max) / 2.0)
        self._density = int(np.clip(initial_density, self.density_min, self.density_max))

    @property
    def density(self) -> int:
        """The most recently commanded density (d(k))."""
        return self._density

    def step(self, setpoint: float, measurement: float) -> int:
        """Run one control update and return the next integer event_density.

        Parameters
        ----------
        setpoint : float
            Target value a_target (e.g. target arousal, 0..1).
        measurement : float
            Current measured value a_measured(k) (e.g. current simulated/real
            arousal estimate, 0..1).

        Returns
        -------
        int
            The next event_density, clipped to [density_min, density_max].
        """
        error = float(setpoint) - float(measurement)

        if self._prev_error is None:
            # First call: no previous error yet, so the derivative term is
            # taken as zero (avoids a spurious large derivative kick from an
            # undefined e(k-1)).
            derivative = 0.0
        else:
            derivative = (error - self._prev_error) / self.dt

        u = self.kp * error + self.kd * derivative

        raw = self._density + u
        clipped = float(np.clip(raw, self.density_min, self.density_max))
        new_density = int(round(clipped))

        self._prev_error = error
        self._density = new_density
        return new_density


def synth_physiology(n_bars: int, kind: str = "arousal_ramp",
                      seed: int = 0) -> np.ndarray:
    """Return a SIMULATED, normalized (0..1) arousal signal, one sample/bar.

    *** THIS IS SYNTHETIC DATA, NOT REAL PHYSIOLOGY. ***
    It stands in for a PPG/GSR/respiration-derived arousal estimate so the
    closed-loop control demo can be exercised end-to-end in software before
    any real sensor pipeline or IRB-approved human-subjects data collection
    exists (see ARCHITECTURE_TWO_TIMESCALE.md §6.2 for what a REAL arousal
    estimate would actually require -- multi-second acquisition windows,
    HR/HRV + SCR/SCL fusion, etc.). Nothing here should be read as validating
    or measuring any real physiological response.

    Parameters
    ----------
    n_bars : int
        Number of samples to generate (one per bar).
    kind : {'arousal_ramp', 'calm_step', 'sine'}
        - 'arousal_ramp': linear ramp from ~0.15 up to ~0.9 over the first
          60% of bars, then holds near the peak (simulates rising arousal,
          e.g. a stressor onset).
        - 'calm_step': starts elevated (~0.85) and drops to a low plateau
          (~0.2) partway through (simulates a calming/relaxation transition).
        - 'sine': smooth oscillation between ~0.2 and ~0.8 (useful for
          exercising the controller against a moving target continuously).
    seed : int
        RNG seed for the small amount of additive noise (keeps the signal
        reproducible while still looking non-trivial).

    Returns
    -------
    np.ndarray
        Shape (n_bars,), float64, values clipped to [0, 1].
    """
    if n_bars <= 0:
        raise ValueError("n_bars must be > 0")
    rng = np.random.default_rng(seed)
    x = np.linspace(0.0, 1.0, n_bars)

    if kind == "arousal_ramp":
        ramp_frac = 0.6
        base = np.where(
            x <= ramp_frac,
            0.15 + (0.9 - 0.15) * (x / ramp_frac),
            0.9,
        )
    elif kind == "calm_step":
        step_at = 0.4
        base = np.where(x <= step_at, 0.85, 0.2)
        # smooth the step slightly so it isn't a discontinuity artifact
        if n_bars >= 5:
            kernel = np.ones(3) / 3.0
            base = np.convolve(base, kernel, mode="same")
    elif kind == "sine":
        base = 0.5 + 0.3 * np.sin(2 * np.pi * 1.5 * x)
    else:
        raise ValueError(f"unknown kind={kind!r}; expected "
                          "'arousal_ramp', 'calm_step', or 'sine'")

    noise = rng.normal(0.0, 0.015, size=n_bars)
    return np.clip(base + noise, 0.0, 1.0)


# =========================================================================
# THREE-TIER CASCADE (notebook 13, TEI 2027) -- GENRE / TEMPO / DENSITY
# =========================================================================
#
# The pieces above (`PDDensityController`, `synth_physiology`) are the FAST
# inner loop, frozen and ear-validated (notebook 12). Everything below adds
# the two SLOWER outer tiers on top, following the iso-principle: first
# match the current arousal state, then gradually walk it toward the
# target, coarsest lever last and finest lever fastest.
#
#   GENRE   (outermost, coarsest, switches rarely)
#     -> TEMPO   (slow loop, quantized to bed-generation events)
#         -> DENSITY (fast inner loop, ~1 update/bar, UNCHANGED above)
#
# This is a proper CASCADE, not three independent PID loops fighting over
# the same raw error (see `CascadeController` docstring for the anti-fight
# discipline this implies).

# ---- Tier 1: GENRE ordering -------------------------------------------
#
# Genres are ordered by ENERGY -- the validated arousal proxy identified in
# genre_axis_findings.md. Danceability was explicitly REJECTED as an
# arousal axis: across 704 real tracks it correlated r=-0.071 with energy
# (essentially uncorrelated) and gives a DIFFERENT genre ranking
# (R&B > Pop) than energy/tempo do (Pop > R&B) -- see
# genre_axis_findings.md §5-6. Energy is the theoretically-motivated
# arousal proxy (activation/intensity), so it is what this controller's
# genre tier walks along.
#
# *** LATIN LOW-N CAVEAT ***
# The Pop/Latin top-of-scale ordering rests on only N=19 Latin-tagged
# tracks (vs. Pop N=244, R&B N=78) -- see genre_axis_findings.md §2. This
# is directional, not precise (SEMs 2-5x larger than Pop/R&B). The ONLY
# strongly-supported claim from the data is "R&B is the calmest genre"
# (lowest energy, N=78, robust). Whether Pop or Latin sits above it at the
# high-arousal end is comparatively weak evidence and should be treated as
# a PERSONALIZABLE DEFAULT -- a lookup table a per-user calibration study
# could freely override -- not a universal law of genre arousal.
#
# The ordering is therefore a single, trivially-swappable named constant.
# To change the default ordering (e.g. once a larger Latin corpus lands,
# or per-user calibration prefers a different top genre), edit ONLY this
# list -- nothing else in `CascadeController` hardcodes genre identities.
GENRE_ENERGY_ORDER = ["calm", "r&b", "pop", "latin"]  # ascending energy/arousal
# ^ calm lowest-energy (new-age/ambient bottom rung, added 2026-08-04 for the
#   segment redesign's 4-rung ladder) -> r&b (robust, N=78) -> pop -> latin
#   highest-energy (weakly-supported top-tier distinction, N=19). See caveat
#   above. NOTE: a `calm` scene from scene.py previously fell through to index
#   0 == r&b silently (run_session gi-lookup); with calm now at index 0 the
#   ladder can actually address its own bottom rung.


class TempoController:
    """Discrete, quantized-step tempo controller (outer SLOW loop, tier 2).

    Mirrors `PDDensityController`'s sign convention and PD structure
    exactly, but its output is a musical TEMPO (BPM) instead of a density,
    and it is deliberately coarse/slow: real bed-generation is quantized to
    discrete segments (a new MusicGen bed must be rendered to actually
    change tempo -- you cannot "glide" a fixed neural bed's BPM), so this
    controller advances in STAIRSTEPS, not a smooth curve, and each step is
    capped to a small `max_step_bpm` change so that a stale/lookahead
    commitment (see `CascadeController`) is never far wrong and crossfades
    between beds stay musically smooth.

    Control law (identical structure to `PDDensityController.step`):
        e(k)  = setpoint - measurement
        u(k)  = Kp * e(k) + Kd * (e(k) - e(k-1)) / dt
        t(k+1) = clip(t(k) + clip(u(k), -max_step_bpm, +max_step_bpm),
                      tempo_min, tempo_max)

    Sign convention (mirrors `PDDensityController` exactly): error is
    `setpoint - measurement`. For a LOW/calm arousal setpoint with a HIGH
    measured arousal, error is negative, so `u(k)` is negative and tempo is
    driven DOWN -- lower tempo is this module's "calming" actuator
    direction, symmetric with the density controller's convention
    (§5.4-style monotonicity, mirrored here for tempo).

    Parameters
    ----------
    kp, kd : float
        Proportional / derivative gains.
    tempo_min, tempo_max : float
        Hard BPM bounds (default 60-140, a generically wide musical range).
    max_step_bpm : float
        Maximum |change| in commanded tempo per `step()` call -- models the
        "keep steps small so a stale commitment is never far wrong" realism
        constraint from the notebook 13 spec. Default 8 BPM/segment.
    dt : float or None
        Seconds per control update; `None` -> 1.0 (per-update units), same
        convention as `PDDensityController`.
    """

    def __init__(self, kp: float, kd: float = 0.0, tempo_min: float = 60.0,
                 tempo_max: float = 140.0, max_step_bpm: float = 8.0,
                 dt: float | None = None):
        if tempo_min > tempo_max:
            raise ValueError("tempo_min must be <= tempo_max")
        if max_step_bpm <= 0:
            raise ValueError("max_step_bpm must be > 0")
        self.kp = float(kp)
        self.kd = float(kd)
        self.tempo_min = float(tempo_min)
        self.tempo_max = float(tempo_max)
        self.max_step_bpm = float(max_step_bpm)
        self.dt = 1.0 if dt is None else float(dt)
        if self.dt <= 0:
            raise ValueError("dt must be > 0")
        self.reset()

    def reset(self, initial_tempo: float | None = None) -> None:
        """Clear controller state.

        `initial_tempo` seeds t(k). Per the iso-principle, the caller
        should normally seed this from a simulated RESTING HEART RATE
        (see `synth_hr`) so the very first bed's tempo starts matched to
        the listener's current state rather than jumping cold to the
        target. Defaults to the midpoint of [tempo_min, tempo_max] if not
        given.
        """
        self._prev_error: float | None = None
        if initial_tempo is None:
            initial_tempo = (self.tempo_min + self.tempo_max) / 2.0
        self._tempo = float(np.clip(initial_tempo, self.tempo_min, self.tempo_max))

    @property
    def tempo_bpm(self) -> float:
        """The most recently commanded tempo, t(k)."""
        return self._tempo

    @property
    def at_min(self) -> bool:
        """True if the controller is saturated at its floor (fully calm)."""
        return self._tempo <= self.tempo_min + 1e-9

    @property
    def at_max(self) -> bool:
        """True if the controller is saturated at its ceiling (fully excited)."""
        return self._tempo >= self.tempo_max - 1e-9

    def step(self, setpoint: float, measurement: float) -> float:
        """Run one control update and return the next tempo in BPM.

        Parameters
        ----------
        setpoint : float
            Target arousal (0..1), same units/scale as the density tier's
            setpoint -- the cascade hands this down from the outer state,
            it is NOT independently re-derived here (see `CascadeController`).
        measurement : float
            Current measured/simulated arousal (0..1).

        Returns
        -------
        float
            Next tempo_bpm, clipped to [tempo_min, tempo_max], with the
            per-call change capped to +/- max_step_bpm.
        """
        error = float(setpoint) - float(measurement)

        if self._prev_error is None:
            derivative = 0.0
        else:
            derivative = (error - self._prev_error) / self.dt

        u = self.kp * error + self.kd * derivative
        u_capped = float(np.clip(u, -self.max_step_bpm, self.max_step_bpm))

        raw = self._tempo + u_capped
        new_tempo = float(np.clip(raw, self.tempo_min, self.tempo_max))

        self._prev_error = error
        self._tempo = new_tempo
        return new_tempo


def synth_hr(n_bars: int, resting_bpm: float = 72.0,
             kind: str = "calm_step", seed: int = 0) -> np.ndarray:
    """Return a SIMULATED heart-rate-like arousal signal, one sample/bar.

    *** THIS IS SIMULATED, NOT REAL PHYSIOLOGY. *** Exactly like
    `synth_physiology`, this stands in for a PPG/ECG-derived HR estimate so
    the three-tier cascade can be seeded/exercised end-to-end before any
    real sensor pipeline or IRB-approved human-subjects data collection
    exists. `resting_bpm` only sets the notional starting point used to
    seed the tempo tier's initial tempo (iso-principle: start the music
    near the listener's own resting rate) -- it is a convenience wrapper
    around `synth_physiology`'s normalized 0..1 signal, not a new model.

    Parameters
    ----------
    n_bars : int
        Number of samples (one per bar).
    resting_bpm : float
        Simulated resting heart rate in BPM (typical adult range ~60-100).
        Used purely to document/seed an initial tempo choice in the demo;
        does not change the shape of the returned normalized signal.
    kind : {'calm_step', 'arousal_ramp', 'sine'}
        Forwarded to `synth_physiology` (same three shapes).
    seed : int
        RNG seed, forwarded to `synth_physiology`.

    Returns
    -------
    np.ndarray
        Shape (n_bars,), float64, normalized arousal in [0, 1].
    """
    if not (40.0 <= resting_bpm <= 140.0):
        raise ValueError("resting_bpm outside a plausible simulated HR range (40-140)")
    return synth_physiology(n_bars, kind=kind, seed=seed)


# Genre-dependent equilibrium bands for the toy plant below. Each genre
# occupies its own "energy territory" -- a [floor, ceil] sub-range of the
# full 0..1 arousal scale that its tempo/density levers can reach within.
# This is what gives genre switching an actual EFFECT on the plant (moving
# to a lower-energy genre lowers the ceiling the inner loops can reach, so
# a persistently-saturated tempo/density pair actually needs the genre
# switch to keep converging) -- not just a re-labeling with no consequence.
# Ordering mirrors GENRE_ENERGY_ORDER; values are illustrative/tuned for a
# visibly convergent demo, not measured from real listener data.
GENRE_EQUILIBRIUM_BAND = {
    "calm":  (0.03, 0.50),  # bottom rung; ceiling MUST stay below r&b's 0.68
                            # floor+range so the calm->r&b step is causally
                            # necessary in sim (same logic as r&b->pop->latin)
    "r&b":   (0.10, 0.68),
    "pop":   (0.18, 0.80),
    "latin": (0.28, 0.95),
}


def dual_lever_plant_step(arousal: float, genre: str, tempo_bpm: float, density: int,
                           *, tempo_min: float, tempo_max: float,
                           density_min: int, density_max: int,
                           relax: float = 0.10, w_tempo: float = 0.5, w_density: float = 0.5,
                           external_drive: float = 0.0, noise: float = 0.0) -> float:
    """One step of the toy PLANT used by the notebook 13 simulation.

    *** THIS IS A FABRICATED TOY PLANT, NOT A VALIDATED PHYSIOLOGICAL
    MODEL. *** It exists only so the cascade controller has something to
    close the loop against in software, exactly like notebook 12's single-
    lever toy plant (see `step_cl_findings.md`) but extended to THREE
    levers (genre, tempo, AND density) since the cascade now commands all
    three tiers.

    Design: arousal RELAXES toward an equilibrium implied by the current
    genre + tempo + density, rather than being nudged by a constant
    additive increment. This gives the plant a genuine, stable fixed point
    for any fixed lever setting (needed for the cascade to actually
    converge and STAY converged, rather than sailing through the setpoint
    to a rail) --

        tempo_norm    = (tempo_bpm - tempo_min) / (tempo_max - tempo_min)
        density_norm  = (density - density_min) / (density_max - density_min)
        lever_norm    = w_tempo * tempo_norm + w_density * density_norm
        floor, ceil   = GENRE_EQUILIBRIUM_BAND[genre]
        equilibrium   = floor + (ceil - floor) * lever_norm
        arousal(k+1)  = clip(arousal(k) + relax*(equilibrium - arousal(k))
                              + external_drive + noise, 0, 1)

    Each genre owns its own `[floor, ceil]` energy territory (see
    `GENRE_EQUILIBRIUM_BAND`) -- e.g. r&b's ceiling (0.68) is below pop's
    floor+range, so a fully-saturated (max tempo, max density) r&b bed
    still cannot reach as high an equilibrium arousal as a modestly-driven
    pop or latin bed. This is what makes the GENRE tier causally necessary
    in the simulation (not just cosmetic): once tempo+density saturate
    within a genre and the target is still out of reach, only advancing
    genre can move the achievable equilibrium band further.

    Parameters
    ----------
    arousal : float
        Current simulated arousal, 0..1.
    genre : str
        Currently active genre (key into `GENRE_EQUILIBRIUM_BAND`).
    tempo_bpm : float
        Currently ACTIVE tempo (BPM) -- i.e. after any commitment lag has
        been applied by the caller (see `CascadeController`).
    density : int
        Currently commanded event_density.
    tempo_min, tempo_max, density_min, density_max : numeric
        Each lever's operating range, used only to normalize it to [0, 1].
    relax : float
        Relaxation rate toward the lever-implied equilibrium per bar
        (0..1); higher = plant responds faster. Tuned (see
        step_nb13_findings.md) for visible, non-oscillatory convergence.
    w_tempo, w_density : float
        Relative weight of each lever in the equilibrium blend (sum need
        not be 1, but is by default for an interpretable 0..1 blend).
    external_drive : float
        An additional per-step forcing term (e.g. to simulate an outside
        stressor); default 0 (no extra forcing beyond the levers).
    noise : float
        Additive noise for this step (caller supplies pre-sampled noise so
        the whole trace stays reproducible under a single RNG).

    Returns
    -------
    float
        Next arousal, clipped to [0, 1].
    """
    if genre not in GENRE_EQUILIBRIUM_BAND:
        raise ValueError(f"unknown genre={genre!r}; expected one of {list(GENRE_EQUILIBRIUM_BAND)}")
    tempo_norm = (float(tempo_bpm) - tempo_min) / (tempo_max - tempo_min)
    density_norm = (float(density) - density_min) / (density_max - density_min)
    lever_norm = w_tempo * tempo_norm + w_density * density_norm
    floor, ceil = GENRE_EQUILIBRIUM_BAND[genre]
    equilibrium = floor + (ceil - floor) * lever_norm
    next_arousal = arousal + relax * (equilibrium - arousal) + external_drive + noise
    return float(np.clip(next_arousal, 0.0, 1.0))

class CascadeController:
    """Three-tier CASCADE: GENRE (coarse) -> TEMPO (medium) -> DENSITY (fast).

    This composes the existing, FROZEN `PDDensityController` (unchanged,
    ear-validated fast inner loop) with a new `TempoController` (medium
    outer loop) and a genre index walked along `GENRE_ENERGY_ORDER`
    (coarsest outer loop).

    *** ANTI-FIGHT DISCIPLINE (read this before changing the logic) ***
    The three tiers must NOT each independently chase the raw global
    error, or they fight each other: e.g. density drops to calm the sound
    while tempo *also* drops for the same reason, then density -- now
    "ahead" of a partially-calmed measurement -- swings back up, and the
    two loops oscillate against each other indefinitely (see the notebook
    13 contrast demo, which builds exactly this naive parallel controller
    and shows it oscillating, side-by-side with this cascade converging).

    The fix implemented here is a genuine CASCADE, not three peers:
      - The FAST inner loop (density) always runs every bar and is the
        primary disturbance-rejector.
      - The MEDIUM loop (tempo) is normally quiescent. It only acts once
        density has been SATURATED (pinned at density_min or density_max)
        for >= `n_bars_saturated_for_tempo` consecutive bars AND the error
        is still outside a tolerance band -- i.e. density alone has proven
        it cannot hold the operating point, so a coarser lever is needed.
      - The COARSEST loop (genre) is normally quiescent. It only advances
        once TEMPO has *also* saturated (pinned at tempo_min/tempo_max in
        the needed direction) for >= `n_bars_saturated_for_genre`
        consecutive bars with the error still large -- i.e. both finer
        levers have proven insufeicient and the whole "operating point"
        (which bed/genre is even playing) needs to move.
      - Each tier's setpoint is the SAME global arousal setpoint handed
        DOWN from the caller -- but only the tier whose turn it is (per
        the saturation gating above) actually changes its output on a
        given bar. Density's setpoint is not "recomputed" from a
        genre-adjusted target; the outer tiers change the OPERATING POINT
        (which genre / what tempo band the density loop sits inside), the
        inner loop still just rejects the residual error within that
        band. This one-tier-acts-at-a-time gating (with hysteresis via the
        consecutive-bar counters, so a single noisy bar can't flip a tier)
        is what prevents the fight.

    GENERATE-AHEAD / COMMITMENT LAG on tempo: real bed generation takes
    ~10s, so the next bed's tempo must be committed one segment AHEAD of
    when it plays (double-buffering to hide generation latency). This
    class models that with a one-slot buffer: the tempo value ACTIVE on
    bar k was computed from the arousal state at the START of segment k-1
    (i.e. it is deliberately one segment stale). `step()` applies the
    buffered (previously committed) tempo first, THEN computes a new
    commitment for next time.

    Parameters
    ----------
    tempo_kp, tempo_kd : float
        Gains passed to the internal `TempoController`.
    tempo_min, tempo_max, max_step_bpm : see `TempoController`.
    density_kp, density_kd : float
        Gains passed to the internal `PDDensityController`.
    density_min, density_max : see `PDDensityController`.
    band : float
        Tolerance band on |error| below which all outer tiers are
        considered "satisfied" (no saturation escalation needed).
    n_bars_saturated_for_tempo, n_bars_saturated_for_genre : int
        Consecutive-bar hysteresis thresholds gating the tempo/genre tiers
        (see anti-fight discipline above).
    genre_order : list[str] or None
        Defaults to `GENRE_ENERGY_ORDER`. Passed explicitly so a caller
        can trivially swap in a personalized ordering without touching
        this class.
    """

    def __init__(self, *, tempo_kp: float = 4.0, tempo_kd: float = 1.0,
                 tempo_min: float = 60.0, tempo_max: float = 140.0,
                 max_step_bpm: float = 8.0,
                 density_kp: float = 2.5, density_kd: float = 0.8,
                 density_min: int = 3, density_max: int = 20,
                 band: float = 0.05,
                 n_bars_saturated_for_tempo: int = 3,
                 n_bars_saturated_for_genre: int = 5,
                 genre_order: list[str] | None = None):
        self.genre_order = list(genre_order) if genre_order is not None else list(GENRE_ENERGY_ORDER)
        if len(self.genre_order) < 1:
            raise ValueError("genre_order must be non-empty")
        self.band = float(band)
        self.n_bars_saturated_for_tempo = int(n_bars_saturated_for_tempo)
        self.n_bars_saturated_for_genre = int(n_bars_saturated_for_genre)

        self.tempo_ctrl = TempoController(
            kp=tempo_kp, kd=tempo_kd, tempo_min=tempo_min, tempo_max=tempo_max,
            max_step_bpm=max_step_bpm,
        )
        self.density_ctrl = PDDensityController(
            kp=density_kp, kd=density_kd, density_min=density_min, density_max=density_max,
        )
        self.reset()

    def reset(self, initial_genre_idx: int = 0, initial_tempo: float | None = None,
              initial_density: int | None = None) -> None:
        """Reset all three tiers and the commitment-lag buffer."""
        self._genre_idx = int(np.clip(initial_genre_idx, 0, len(self.genre_order) - 1))
        self.tempo_ctrl.reset(initial_tempo)
        self.density_ctrl.reset(initial_density)
        # Generate-ahead double-buffer: the tempo ACTIVE right now is what
        # was committed on the previous call. Seed it with the initial
        # tempo so bar 0 plays the iso-principle-matched starting tempo
        # rather than an undefined value.
        self._committed_next_tempo = self.tempo_ctrl.tempo_bpm
        self._active_tempo = self.tempo_ctrl.tempo_bpm
        self._consec_density_saturated = 0
        self._consec_tempo_saturated = 0

    @property
    def genre(self) -> str:
        return self.genre_order[self._genre_idx]

    def _density_saturated(self, error: float) -> bool:
        """True if density is pinned at the rail needed to reduce |error|.

        Direction is taken from the SIGN OF THE ERROR (setpoint -
        measurement), NOT from an absolute setpoint threshold. Under a
        trajectory setpoint that sweeps across arousal 0.5 mid-session, a
        `setpoint < 0.5` test would flip the saturation direction even
        though the error sign never changed -- silently going deaf halfway
        through a run. `error > 0` means we need MORE arousal (exciting);
        `error < 0` means we need LESS (calming).
        """
        d = self.density_ctrl.density
        if error < 0:  # calming direction wants LOW density
            return d <= self.density_ctrl.density_min
        else:  # exciting direction wants HIGH density
            return d >= self.density_ctrl.density_max

    def _tempo_saturated(self, error: float) -> bool:
        """True if tempo is pinned at the rail needed to reduce |error|.

        Direction from the sign of the error, not `setpoint < 0.5` -- see
        `_density_saturated` for why (trajectory setpoints cross 0.5).
        """
        if error < 0:
            return self.tempo_ctrl.at_min
        else:
            return self.tempo_ctrl.at_max

    def step(self, setpoint: float, measurement: float) -> dict:
        """Run one bar of the cascade and return the tier outputs.

        Parameters
        ----------
        setpoint : float
            Global target arousal (0..1) -- the SAME value is handed down
            to every tier; only the tier whose turn it is (per the
            saturation-gated cascade logic) will actually move.
        measurement : float
            Current measured/simulated arousal (0..1).

        Returns
        -------
        dict
            {'genre': str, 'tempo_bpm': float, 'density': int,
             'tier_that_acted': 'density'|'tempo'|'genre'|'none'}
        """
        error = float(setpoint) - float(measurement)
        tier_that_acted = "density"  # density runs every bar (fast loop)

        # ---- Tier 3: DENSITY (fast, always runs) ----
        # The density loop's setpoint is the SAME global setpoint handed
        # down -- it is not re-derived from genre/tempo state, per the
        # anti-fight discipline: outer tiers change the operating point
        # (which bed plays), not the inner loop's target.
        density = self.density_ctrl.step(setpoint=setpoint, measurement=measurement)

        # ---- Apply the ALREADY-COMMITTED tempo for this segment ----
        # (generate-ahead / double-buffering: this is what was decided
        # from the arousal state one segment ago, not from `measurement`
        # this bar).
        active_tempo = self._committed_next_tempo
        self._active_tempo = active_tempo

        # ---- Saturation bookkeeping (hysteresis counters) ----
        if abs(error) > self.band and self._density_saturated(error):
            self._consec_density_saturated += 1
        else:
            self._consec_density_saturated = 0

        # ---- Tier 2: TEMPO (medium, only when density has proven stuck) ----
        tempo_acted = False
        if (abs(error) > self.band
                and self._consec_density_saturated >= self.n_bars_saturated_for_tempo):
            # Density alone can't hold the band -- let the coarser tempo
            # lever act. It is committed now for use NEXT segment (the
            # lookahead-commitment lag), acting on the state at the START
            # of the CURRENT segment (i.e. `measurement`), exactly as
            # documented in the class/tier-2 docstrings.
            self._committed_next_tempo = self.tempo_ctrl.step(setpoint=setpoint, measurement=measurement)
            tempo_acted = True
            tier_that_acted = "tempo"

        if abs(error) > self.band and self._tempo_saturated(error):
            self._consec_tempo_saturated += 1
        else:
            self._consec_tempo_saturated = 0

        # ---- Tier 1: GENRE (coarsest, only when tempo has ALSO saturated) ----
        if (abs(error) > self.band
                and self._consec_tempo_saturated >= self.n_bars_saturated_for_genre):
            if error < 0 and self._genre_idx > 0:
                self._genre_idx -= 1  # walk DOWN toward the calmer genre
                tier_that_acted = "genre"
                self._consec_tempo_saturated = 0  # genre switch resets escalation
            elif error > 0 and self._genre_idx < len(self.genre_order) - 1:
                self._genre_idx += 1  # walk UP toward the more energizing genre
                tier_that_acted = "genre"
                self._consec_tempo_saturated = 0

        if not tempo_acted and tier_that_acted == "density" and abs(error) <= self.band:
            tier_that_acted = "none"  # inside the band -- nothing needed to act

        return {
            "genre": self.genre,
            "tempo_bpm": active_tempo,
            "density": density,
            "tier_that_acted": tier_that_acted,
        }


if __name__ == "__main__":
    # ---- Tiny self-test: no audio engine, no external deps beyond numpy ----
    print("PDDensityController + synth_physiology self-test")
    print("=" * 60)

    n_bars = 12
    arousal = synth_physiology(n_bars, kind="arousal_ramp", seed=0)
    print(f"synth_physiology('arousal_ramp', n_bars={n_bars}):")
    print("  ", np.round(arousal, 3).tolist())
    assert arousal.shape == (n_bars,)
    assert np.all((arousal >= 0.0) & (arousal <= 1.0)), "arousal out of [0,1]"

    calm = synth_physiology(n_bars, kind="calm_step", seed=1)
    sine = synth_physiology(n_bars, kind="sine", seed=2)
    for name, sig in [("calm_step", calm), ("sine", sine)]:
        assert sig.shape == (n_bars,)
        assert np.all((sig >= 0.0) & (sig <= 1.0)), f"{name} out of [0,1]"
    print(f"synth_physiology('calm_step')[:5]  = {np.round(calm[:5], 3).tolist()}")
    print(f"synth_physiology('sine')[:5]       = {np.round(sine[:5], 3).tolist()}")

    # ---- Controller: toy closed loop ----
    # Toy plant: higher density nudges the NEXT arousal sample down a bit
    # (see notebook 12, Step 3, for the fully documented version of this
    # assumption). Here we just confirm the controller mechanics: integer
    # output, in-range, and it reacts sensibly to a large fixed error.
    ctrl = PDDensityController(kp=8.0, kd=2.0, density_min=3, density_max=20)
    print("\nPDDensityController(kp=8.0, kd=2.0, density_min=3, density_max=20)")
    print(f"  initial density (midpoint seed) = {ctrl.density}")

    setpoint = 0.3  # "calm" target arousal
    measurements = arousal  # pretend measured arousal follows the ramp
    densities = []
    for k, m in enumerate(measurements):
        d = ctrl.step(setpoint=setpoint, measurement=m)
        assert isinstance(d, int), "step() must return a python int"
        assert ctrl.density_min <= d <= ctrl.density_max, "density out of range"
        densities.append(d)

    print(f"  setpoint = {setpoint}")
    print(f"  measurements (first 6) = {np.round(measurements[:6], 3).tolist()}")
    print(f"  commanded densities    = {densities}")
    assert all(ctrl.density_min <= d <= ctrl.density_max for d in densities)
    assert all(isinstance(d, int) for d in densities)

    # Sign convention used throughout this module and notebook 12: error is
    # (setpoint - measurement). With a LOW ("calm") setpoint, measured
    # arousal rising above it produces an increasingly NEGATIVE error, so
    # u(k) drives density DOWN. This is deliberate -- in the notebook's toy
    # plant, LOWER density is treated as the "calming" actuator direction
    # (see notebook 12, Step 3, for the documented assumption). Here we just
    # confirm the controller's sign is monotonic and stable (§5.4): as
    # measured arousal rises further above the calm setpoint, commanded
    # density should not increase.
    high_err_density = np.mean(densities[-3:])   # arousal near its peak (~0.9), setpoint=0.3
    low_err_density = np.mean(densities[:3])      # arousal near its start (~0.15-0.4)
    print(f"  mean density during high-arousal bars = {high_err_density:.2f}")
    print(f"  mean density during low-arousal bars  = {low_err_density:.2f}")
    assert high_err_density <= low_err_density, (
        "expected LOWER commanded density when measured arousal is farther "
        "above the calm setpoint, given error=setpoint-measurement and this "
        "module's 'density is the calming actuator' sign convention (§5.4 "
        "monotonicity, sign as documented in notebook 12 Step 3)"
    )

    # reset() behavior
    ctrl.reset(initial_density=10)
    assert ctrl.density == 10
    d0 = ctrl.step(setpoint=0.5, measurement=0.5)
    assert d0 == 10, "zero error, zero derivative on first call -> density unchanged"

    print("\nALL ASSERTIONS PASSED (PDDensityController tier)")

    # =====================================================================
    # TempoController + CascadeController self-test (notebook 13, cascade)
    # =====================================================================
    print("\n" + "=" * 60)
    print("TempoController + CascadeController self-test")
    print("=" * 60)

    # ---- TempoController basics: range + step-cap ----
    tctrl = TempoController(kp=6.0, kd=1.5, tempo_min=60, tempo_max=140, max_step_bpm=8)
    resting_hr = 72.0
    tctrl.reset(initial_tempo=resting_hr)  # iso-principle: seed tempo ~ resting HR
    assert tctrl.tempo_bpm == resting_hr

    tempo_setpoint = 0.2  # calm target arousal
    tempo_trace = [tctrl.tempo_bpm]
    hr_like = synth_hr(20, resting_bpm=resting_hr, kind="calm_step", seed=3)
    # force a persistently HIGH measurement so the controller is driven hard
    # toward its floor, to test both range-clipping and the step cap.
    forced_measurements = np.clip(hr_like + 0.5, 0.0, 1.0)
    for m in forced_measurements:
        t = tctrl.step(setpoint=tempo_setpoint, measurement=float(m))
        assert tctrl.tempo_min - 1e-6 <= t <= tctrl.tempo_max + 1e-6, "tempo out of range"
        step_size = abs(t - tempo_trace[-1])
        assert step_size <= tctrl.max_step_bpm + 1e-6, (
            f"tempo step {step_size} exceeded max_step_bpm={tctrl.max_step_bpm}"
        )
        tempo_trace.append(t)
    print(f"TempoController tempo trace (calm target, forced-high measurement):")
    print("  ", [round(v, 1) for v in tempo_trace])
    assert tempo_trace[-1] < tempo_trace[0], "tempo should have walked DOWN toward the calm target"
    print("  all steps <= max_step_bpm=8, all tempos in [60,140]: PASS")

    # ---- CascadeController: genre index only advances when saturated ----
    cc = CascadeController(
        tempo_kp=6.0, tempo_kd=1.5, tempo_min=60, tempo_max=140, max_step_bpm=8,
        density_kp=2.5, density_kd=0.8, density_min=3, density_max=20,
        band=0.05, n_bars_saturated_for_tempo=3, n_bars_saturated_for_genre=5,
    )
    # start "hot": latin/fast/dense. latin is now the TOP rung of the 4-rung
    # ladder [calm, r&b, pop, latin], i.e. index len-1 (was index 2 in the old
    # 3-rung [r&b, pop, latin] ladder before `calm` was prepended 2026-08-04).
    cc.reset(initial_genre_idx=len(cc.genre_order) - 1, initial_tempo=130.0, initial_density=18)
    assert cc.genre == "latin", f"expected latin (top rung), got {cc.genre!r}"

    genre_trace, tempo_trace2, density_trace, arousal_trace, acted_trace = [], [], [], [], []
    arousal = 0.95  # start very aroused
    calm_setpoint = 0.15  # strong down-regulation target -- should force all 3 tiers eventually
    rng = np.random.default_rng(7)
    N = 60
    for k in range(N):
        out = cc.step(setpoint=calm_setpoint, measurement=arousal)
        genre_trace.append(out["genre"])
        tempo_trace2.append(out["tempo_bpm"])
        density_trace.append(out["density"])
        acted_trace.append(out["tier_that_acted"])
        arousal_trace.append(arousal)

        # bookkeeping asserts
        assert 60 - 1e-6 <= out["tempo_bpm"] <= 140 + 1e-6
        assert 3 <= out["density"] <= 20
        if k > 0:
            step_size = abs(tempo_trace2[-1] - tempo_trace2[-2])
            assert step_size <= 8 + 1e-6, f"tempo jumped {step_size} > max_step_bpm at bar {k}"

        arousal = dual_lever_plant_step(
            arousal, out["genre"], out["tempo_bpm"], out["density"],
            tempo_min=60, tempo_max=140, density_min=3, density_max=20,
            relax=0.10, noise=float(rng.normal(0, 0.004)),
        )

    print(f"\nCascade run (calm_setpoint={calm_setpoint}, start arousal=0.95, N={N} bars):")
    print("  genres visited (unique, in order):",
          [g for i, g in enumerate(genre_trace) if i == 0 or g != genre_trace[i - 1]])
    print("  tier_that_acted counts:",
          {t: acted_trace.count(t) for t in set(acted_trace)})
    print("  final tempo:", round(tempo_trace2[-1], 1),
          "| final density:", density_trace[-1],
          "| final arousal:", round(arousal_trace[-1], 4))

    # genre must only ever move MONOTONICALLY DOWN here (down-regulation
    # target), never up, and never on the very first few bars (needs
    # saturation of both inner tiers first -> hysteresis).
    genre_indices = [cc.genre_order.index(g) for g in genre_trace]
    assert all(b <= a for a, b in zip(genre_indices, genre_indices[1:])), (
        "genre index should only walk DOWN during down-regulation, never up"
    )
    first_genre_switch = next((i for i in range(1, N) if genre_trace[i] != genre_trace[i - 1]), None)
    assert first_genre_switch is None or first_genre_switch >= cc.n_bars_saturated_for_tempo, (
        "genre should not switch before the inner tiers have had a chance to saturate"
    )

    # cascade must actually converge close to the calm setpoint by the end
    final_err = abs(arousal_trace[-1] - calm_setpoint)
    print(f"  final |arousal - setpoint| = {final_err:.4f}")
    assert final_err < 0.08, f"cascade did not converge close enough (final_err={final_err:.4f})"

    print("\nALL ASSERTIONS PASSED")
