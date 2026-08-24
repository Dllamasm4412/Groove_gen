"""run_session.py — the HEADLESS closed-loop entry point (Phase 0 skeleton).

    from run_session import run_session, SessionConfig
    trace_path, wav_path = run_session(SessionConfig(...))

This is the SINGLE runtime path. The operator UI (Phase 3) will only call this.
Nothing here imports gradio, notebooks, or the rejected dlbed/AMT frozen-bed path.

Signal flow, once per bar:
    HRSource.read() -> bpm
      -> HRArousalMapper.to_arousal(bpm) -> arousal_measured
      -> CascadeController.step(setpoint, measured) -> {density, tempo_bpm, genre, tier_that_acted}
      -> TierMapper.step(density) -> (tier_cmd, tier_applied)
      -> renderer(tier_applied, tempo, genre, bar_idx) -> bar audio  [timed]
      -> append trace row + FLUSH

Framing (LOCKED): controller tracks AROUSAL. HR->arousal is a stated per-subject
linear calibration via HRArousalMapper. See trace_schema.py.

The renderer is injected so this file runs ANYWHERE. Default = MockRenderer (no
FluidSynth). On Colab, pass renderer=FluidSynthRenderer(...) for real audio.
"""
from __future__ import annotations
import csv, os, time, subprocess, importlib.util
from dataclasses import dataclass, field
from typing import Callable, Optional
import numpy as np

# --- import the validated modules from the existing package ---------------
import sys
_PKG = "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_project/groovegen"
_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
for p in (_PKG, _ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)

import pd_controller as pdc                      # CascadeController, synth_physiology
from hr_source import HRArousalMapper, TextInputHRSource, HeartRateReading  # type: ignore

from trace_schema import COLUMNS
from tier_mapping import TierMapper


# --------------------------------------------------------------------------
# Renderers: a bar-at-a-time audio producer. Injected into run_session.
# --------------------------------------------------------------------------
class MockRenderer:
    """Simulates a bar render: sleeps a small, tier-dependent time and returns
    a numpy audio stub. Lets us exercise timing/trace logic with no soundfont."""
    def __init__(self, sr: int = 44100, base_ms: float = 6.0, per_tier_ms: float = 2.0):
        self.sr = sr; self.base_ms = base_ms; self.per_tier_ms = per_tier_ms
    def render_bar(self, tier, tempo_bpm, genre, bar_idx, n_bars):
        # simulate render cost growing slightly with tier (more events)
        time.sleep((self.base_ms + self.per_tier_ms * tier) / 1000.0)
        n = int(self.sr * 60.0 / tempo_bpm * 4)   # 4 beats/bar
        return np.zeros(n, dtype=np.float32)


class FluidSynthRenderer:
    """Real renderer. Delegates to SymbolicBarRenderer (renderer.py), the ONE
    consolidated per-bar renderer over the validated symbolic path. Requires
    FluidSynth + a soundfont (present on Colab/local; MockRenderer needs neither).
    Phase 1: this is now a REAL render, not a silence stub."""
    def __init__(self, sr: int = 44100, sf2: Optional[str] = None,
                 gain: float = 0.8, polish: bool = False):
        self.sr = sr
        from renderer import SymbolicBarRenderer, SF2_DEFAULT
        self._r = SymbolicBarRenderer(sf2=sf2 or SF2_DEFAULT, sr=sr,
                                      gain=gain, polish=polish)
    def render_bar(self, tier, tempo_bpm, genre, bar_idx, n_bars):
        a = self._r.render_bar(int(tier), float(tempo_bpm), str(genre),
                               int(bar_idx), int(n_bars))
        if a is None:  # render failure -> silence of correct length, flagged upstream
            n = int(self.sr * 60.0 / tempo_bpm * 4)
            return np.zeros((n, 2), dtype=np.float32)
        return a


# --------------------------------------------------------------------------
# Setpoint scripts: scripted target arousal per bar (NOT an efficacy claim).
# --------------------------------------------------------------------------
def setpoint_script(kind: str, n_bars: int) -> np.ndarray:
    t = np.linspace(0, 1, n_bars)
    if kind == "downreg":      # calm the listener: high -> low
        return np.clip(0.8 - 0.6 * t, 0.05, 0.95)
    if kind == "upreg":        # energize: low -> high
        return np.clip(0.2 + 0.6 * t, 0.05, 0.95)
    if kind == "hold":
        return np.full(n_bars, 0.5)
    if kind == "step":         # step down at midpoint
        s = np.full(n_bars, 0.75); s[n_bars // 2:] = 0.3; return s
    raise ValueError(f"unknown setpoint script {kind!r}")


@dataclass
class SessionConfig:
    n_bars: int = 32
    setpoint_kind: str = "downreg"
    seed: int = 7
    genre: str = "pop"                 # initial scene genre (from map_profile scene)
    start_tier: int = 3                # initial scene tier
    start_bpm: Optional[float] = None  # initial scene tempo (iso-principle); None=controller default
    resting_hr: float = 60.0
    max_hr: float = 120.0
    # controller gains (hand-tuned, reported — NOT auto-optimized)
    density_kp: float = 6.0
    density_kd: float = 1.5
    code_version: str = "v0.0-phase0"
    out_dir: str = "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot/sessions"
    session_name: str = "demo"
    # plant: how measured arousal responds (mock). Real sessions read a sensor.
    use_synthetic_plant: bool = True

    @classmethod
    def from_scene(cls, scene, **overrides):
        """Build a config whose INITIAL genre/tempo/tier come from a Scene
        (scene.py -> map_profile over an anchor-song feature row). The scene sets
        initial conditions only; the controller drives everything per bar after.
        Any field can be overridden by keyword (n_bars, setpoint_kind, seed, ...).
        """
        base = dict(genre=scene.genre, start_tier=int(scene.start_tier),
                    start_bpm=float(scene.bpm))
        base.update(overrides)
        return cls(**base)


def _git_version(default: str) -> str:
    try:
        r = subprocess.run(["git", "describe", "--tags", "--always"],
                           cwd=_ROOT, capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return default


def run_session(cfg: SessionConfig,
                renderer: Optional[object] = None,
                hr_stream: Optional[Callable[[int], float]] = None) -> tuple[str, str]:
    """Run one headless closed-loop session. Returns (trace_csv_path, wav_path).

    renderer   : object with .render_bar(tier, tempo_bpm, genre, bar_idx, n_bars).
                 Defaults to MockRenderer (no soundfont needed).
    hr_stream  : optional callable(bar_idx)->bpm for a REAL sensor. If None and
                 cfg.use_synthetic_plant, a simple plant simulates arousal.
    """
    rng = np.random.default_rng(cfg.seed)
    np.random.seed(cfg.seed)
    os.makedirs(cfg.out_dir, exist_ok=True)
    code_version = _git_version(cfg.code_version)

    renderer = renderer or MockRenderer()
    mapper = HRArousalMapper(resting_hr=cfg.resting_hr, max_hr=cfg.max_hr)
    ctrl = pdc.CascadeController(density_kp=cfg.density_kp, density_kd=cfg.density_kd)
    # initial scene: start genre + start tier (Phase 3 will source these from map_profile)
    gi = ctrl.genre_order.index(cfg.genre) if cfg.genre in ctrl.genre_order else 0
    start_density = int(np.clip(round(3 + (cfg.start_tier - 1) / 4 * (20 - 3)), 3, 20))
    ctrl.reset(initial_genre_idx=gi, initial_tempo=cfg.start_bpm,
               initial_density=start_density)
    tiers = TierMapper(initial_tier=cfg.start_tier)

    setpoints = setpoint_script(cfg.setpoint_kind, cfg.n_bars)

    trace_path = os.path.join(cfg.out_dir, f"{cfg.session_name}_trace.csv")
    wav_path = os.path.join(cfg.out_dir, f"{cfg.session_name}.wav")

    # synthetic plant state (only used if no real sensor)
    arousal = 0.5
    audio_chunks = []
    t0 = time.monotonic()

    with open(trace_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader(); fh.flush()

        for bar in range(cfg.n_bars):
            setpoint = float(setpoints[bar])

            # --- measurement: real sensor OR synthetic plant -> arousal ---
            if hr_stream is not None:
                bpm = float(hr_stream(bar))
                measured = mapper.to_arousal(bpm)
            elif cfg.use_synthetic_plant:
                # plant nudges arousal toward the applied tier's implied level,
                # with noise — a stand-in until the Polar H10 streams real HR.
                target_a = (tiers.tier - 1) / 4.0
                arousal += 0.35 * (target_a - arousal) + rng.normal(0, 0.03)
                arousal = float(np.clip(arousal, 0, 1))
                measured = arousal
                bpm = mapper.to_bpm(measured)
            else:
                bpm = float("nan"); measured = setpoint  # open loop

            # --- controller: one bar (arousal units) ---
            out = ctrl.step(setpoint=setpoint, measurement=measured)
            density_cmd = int(out["density"])
            tempo_cmd = float(out["tempo_bpm"])
            genre = str(out["genre"])
            tier_that_acted = str(out["tier_that_acted"])

            # --- density -> tier (hysteresis + rate limit) ---
            tier_cmd, tier_applied = tiers.step(density_cmd)

            # --- render this bar, timed ---
            r0 = time.monotonic()
            chunk = renderer.render_bar(tier_applied, tempo_cmd, genre, bar, cfg.n_bars)
            render_ms = (time.monotonic() - r0) * 1000.0
            bar_dur_ms = 60.0 / tempo_cmd * 4 * 1000.0
            deadline_miss = int(render_ms > bar_dur_ms)
            if chunk is not None:
                audio_chunks.append(np.asarray(chunk, dtype=np.float32))

            row = {
                "wall_t": round(time.monotonic() - t0, 4),
                "bar_idx": bar,
                "hr_bpm_raw": round(bpm, 2) if bpm == bpm else float("nan"),
                "arousal_setpoint": round(setpoint, 4),
                "arousal_measured": round(measured, 4),
                "error": round(setpoint - measured, 4),
                "density_cmd": density_cmd,
                "tier_cmd": tier_cmd,
                "tier_applied": tier_applied,
                "tempo_cmd": round(tempo_cmd, 2),
                "tempo_applied": round(tempo_cmd, 2),  # Phase 2: committed-buffer value
                "genre": genre,
                "tier_that_acted": tier_that_acted,
                "render_ms": round(render_ms, 3),
                "deadline_miss": deadline_miss,
                "seed": cfg.seed,
                "code_version": code_version,
            }
            w.writerow(row); fh.flush()  # CRASH-SAFE: flush every bar

    # write concatenated audio (mock = silence; real renderer = actual bed)
    try:
        import soundfile as sf
        if audio_chunks:
            sf.write(wav_path, np.concatenate(audio_chunks), 44100)
    except Exception:
        wav_path = ""  # audio optional in Phase 0

    return trace_path, wav_path


if __name__ == "__main__":
    tp, wp = run_session(SessionConfig(n_bars=32, setpoint_kind="downreg",
                                       session_name="phase0_smoke"))
    print("trace:", tp)
    print("wav  :", wp or "(none)")
