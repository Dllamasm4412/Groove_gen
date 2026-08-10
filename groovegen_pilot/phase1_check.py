"""phase1_check.py — end-to-end Phase 1 integration test.

Proves: scene.py (map_profile) -> SessionConfig.from_scene -> run_session with the
REAL FluidSynthRenderer (consolidated renderer.py) produces a valid trace + audio.
"""
import sys, time
sys.path.insert(0, "/Users/daniel/Desktop/PhD/groove_gen_project")
sys.path.insert(0, "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot")

import numpy as np, soundfile as sf, pandas as pd
from scene import scene_from_features
from run_session import SessionConfig, run_session, FluidSynthRenderer

# 1) anchor-song feature row -> scene (initial conditions)
feat = dict(tempo_final=104, spectral_centroid_mean=2100, hpss_harmonic_ratio=0.55,
            hpss_percussive_ratio=0.45, onset_density=6, lhl_syncopation_mean=0.6)
scene = scene_from_features(feat)
print(f"[scene] genre={scene.genre} bpm={scene.bpm} start_tier={scene.start_tier} "
      f"transpose={scene.transpose:+d}")

# 2) build config from the scene; short run for a fast real-audio check
cfg = SessionConfig.from_scene(scene, n_bars=12, setpoint_kind="downreg",
                               seed=7, session_name="phase1_real",
                               code_version="v0.1-phase1")

# 3) run with the REAL renderer
t0 = time.time()
trace_path, wav_path = run_session(cfg, renderer=FluidSynthRenderer(sr=44100))
wall = time.time() - t0
print(f"[run ] wall={wall:.1f}s  trace={trace_path}  wav={wav_path}")

# 4) validate trace
df = pd.read_csv(trace_path)
assert len(df) == cfg.n_bars, f"expected {cfg.n_bars} rows, got {len(df)}"
assert df["tier_applied"].between(1, 5).all(), "tier out of [1,5]"
assert df["density_cmd"].between(3, 20).all(), "density out of [3,20]"
assert df["wall_t"].is_monotonic_increasing, "wall_t not monotonic"
mae = (df["arousal_setpoint"] - df["arousal_measured"]).abs().mean()
settled = (df["arousal_setpoint"] - df["arousal_measured"]).abs().iloc[cfg.n_bars//2:].mean()
misses = int(df["deadline_miss"].sum())
print(f"[trace] rows={len(df)} MAE={mae:.3f} settledMAE={settled:.3f} "
      f"deadline_misses={misses} tier_range=[{df.tier_applied.min()},{df.tier_applied.max()}]")
print(f"[trace] render_ms p50={df.render_ms.median():.1f} p95={df.render_ms.quantile(.95):.1f} "
      f"max={df.render_ms.max():.1f}  bar_dur_ms={60000/df.tempo_cmd.iloc[0]*4:.0f}")

# 5) validate audio is real (not silence)
y, srr = sf.read(wav_path)
peak = float(np.abs(y).max()); rms = float(np.sqrt(np.mean(y**2)))
dur = len(y)/srr
print(f"[audio] {dur:.1f}s @ {srr}Hz  peak={peak:.3f} rms={rms:.4f}  "
      f"{'OK (audible)' if rms > 1e-3 else 'SILENT!!'}")
print("PHASE1 OK" if (peak > 0.05 and misses == 0) else "PHASE1 REVIEW NEEDED")
