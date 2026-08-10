"""renderer.py — the ONE renderer interface for the closed loop (Phase 1).

Wraps the validated symbolic path (symbolic_bed_proto + symbolic_tiers_demo)
behind a single per-bar call:

    r = SymbolicBarRenderer(genre="pop")
    audio = r.render_bar(tier=3, tempo_bpm=104, genre="pop", bar_idx=0, n_bars=32)

WHY a per-bar renderer (vs the existing build_* multi-bar builders):
  The closed loop changes TIER and TEMPO every bar, so the bed cannot be built
  once up front. This renderer produces ONE bar of (harmonic bed + tier-scaled
  drums) at the current control state, renders it with FluidSynth, and returns
  a numpy stereo buffer. It reuses the validated note/chord/drum_bar_tier code
  so the musical content is identical to what was already vetted — we only
  change WHEN it is generated (per bar, under control) not HOW.

Design notes:
  * Bed intensity also scales with tier (voices added at higher tiers) so the
    harmonic layer, not just drums, reflects the controller's intensity command.
    This keeps the tier a genuine INTENSITY actuator, per the reassessment memo's
    requirement that control knobs be manipulable, not merely descriptive.
  * MockRenderer stays in run_session.py for dependency-free timing tests;
    this file is the REAL path used on Colab/local where FluidSynth exists.
  * render_bar returns (audio, meta) where meta carries render timing already
    measured by the caller; here we just return the buffer.
"""
from __future__ import annotations
import os, sys, tempfile, subprocess
import numpy as np

_ROOT = "/Users/daniel/Desktop/PhD/groove_gen_project"
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pretty_midi as pm
import symbolic_bed_proto as S
import symbolic_tiers_demo as T

SF2_DEFAULT = S.SF2      # /usr/share/sounds/sf2/FluidR3_GM.sf2 locally; override on Colab
SR = S.SR                # 44100

# --- per-genre harmonic bed vocab (scale-degree progressions in C) ------------
# root pitch + chord voicing for a I-based diatonic loop, one chord per bar.
_PROG = {
    # (voicing pitches, bass root) per bar, cycled
    "pop":  [([60,64,67],48),([55,59,62],43),([57,60,64],45),([53,57,60],41)],  # C G Am F
    "r&b":  [([60,64,67,70],48),([57,60,64,67],45),([53,57,60,64],41),([55,59,62,65],43)],  # 7ths
    "latin":[([60,64,67],48),([53,57,60],41),([55,59,62],43),([55,59,62],43)],  # C F G G (son)
    "calm": [([60,64,67],48),([57,60,64],45),([53,57,60],41),([55,59,62],43)],  # I vi IV V, soft
}
_PROG["r&b-soul"] = _PROG["r&b"]
_PROG["latin-salsa"] = _PROG["latin"]

# instrument programs by genre (GM); Colab supersaw path can override pop later
_INST = {
    "pop":  dict(comp=S.CLAV, bass=S.FINGER_BASS, pad=S.SYN_PAD),
    "r&b":  dict(comp=4,      bass=S.FINGER_BASS, pad=S.SYN_PAD),   # EP comp
    "latin":dict(comp=S.CLAV, bass=S.FINGER_BASS, pad=S.SYN_PAD),
    "calm": dict(comp=88,     bass=S.FINGER_BASS, pad=S.SYN_PAD),   # new-age pad comp
}
_INST["r&b-soul"] = _INST["r&b"]; _INST["latin-salsa"] = _INST["latin"]

# drum-genre routing: only salsa has a bespoke feel in drum_bar_tier; else pop.
def _drum_genre(genre: str) -> str:
    return "salsa" if genre in ("latin", "latin-salsa") else "pop"

# --- per-rung tier ceiling -------------------------------------------------
# The drum engine treats pop/rnb/calm identically (see symbolic_tiers_demo
# drum_bar_tier: only "salsa" is special-cased). So WITHOUT a cap, a tier-5
# "calm" segment renders FULL pop drums -- 16th hats, ghost snares, crash --
# which is louder/busier than a tier-2 r&b segment on the rung ABOVE it. That
# makes the genre-energy ladder non-monotonic at the bottom, which is fatal to
# the whole premise (calm must be the LEAST energetic rung). Cap the effective
# tier per rung so calm cannot out-energize r&b. The controller still commands
# tiers 1-5; this only bounds how much intensity each genre is ALLOWED to
# express, preserving a monotone energy ordering across genres.
RUNG_TIER_CAP = {"calm": 2, "r&b": 4, "pop": 5, "latin": 5}

def _norm_genre(genre: str) -> str:
    g = (genre or "pop").lower()
    if g in _PROG:
        return g
    if "r&b" in g or "rnb" in g or "soul" in g:
        return "r&b"
    if "latin" in g or "salsa" in g:
        return "latin"
    if "calm" in g or "ambient" in g or "chill" in g:
        return "calm"
    return "pop"


class SymbolicBarRenderer:
    """Renders ONE bar of bed+drums at a given intensity tier/tempo/genre."""

    def __init__(self, sf2: str = SF2_DEFAULT, sr: int = SR, gain: float = 0.8,
                 polish: bool = False):
        self.sf2 = sf2
        self.sr = sr
        self.gain = gain
        self.polish = polish   # off by default per-bar (reverb tail bleeds across bars)

    def _bar_midi(self, tier: int, tempo_bpm: float, genre: str,
                  bar_idx: int, n_bars: int) -> pm.PrettyMIDI:
        g = _norm_genre(genre)
        # Clamp the commanded tier to this genre's energy ceiling so the
        # ladder stays monotone (calm can never out-energize r&b). See
        # RUNG_TIER_CAP above.
        tier = min(int(tier), RUNG_TIER_CAP.get(g, 5))
        spb = 60.0 / tempo_bpm
        bar = spb * 4
        m = pm.PrettyMIDI(initial_tempo=tempo_bpm)
        inst = _INST[g]
        comp = pm.Instrument(program=inst["comp"], name="comp")
        bass = pm.Instrument(program=inst["bass"], name="bass")
        pad  = pm.Instrument(program=inst["pad"],  name="pad")
        drums = pm.Instrument(program=0, is_drum=True, name="drums")

        prog = _PROG[g]
        voi, root = prog[bar_idx % len(prog)]

        # --- harmonic bed intensity scales with tier -------------------------
        # tier 1: pad only (sustained). tier 2+: add comp stabs. tier 4+: denser
        # comp + walking bass push. Bed reflects the intensity command, not just drums.
        if tier >= 1:
            S.chord(pad, voi, 0.0, bar, vel=36 + 3 * tier)
        if tier >= 2:
            stabs = {2: [1.0, 3.0], 3: [0.5, 1.0, 2.5, 3.0],
                     4: [0.5, 1.0, 1.5, 2.5, 3.0, 3.5],
                     5: [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]}[min(tier, 5)]
            for off in stabs:
                S.chord(comp, [v + 12 for v in voi], off * spb, spb * 0.35,
                        vel=60 + 3 * tier)
        # bass: quarter notes always; add push at higher tiers
        for beat in range(4):
            S.note(bass, root - 12, beat * spb, spb * 0.5, vel=78 + 2 * tier)
        if tier >= 4:
            S.note(bass, root - 12 + 7, 3.5 * spb, spb * 0.4, vel=80)

        # --- drums via the VALIDATED tier engine -----------------------------
        T.drum_bar_tier(drums, 0.0, spb, int(tier), genre=_drum_genre(g),
                        bar_idx=bar_idx, n_bars=n_bars)

        for i in (pad, comp, bass, drums):
            m.instruments.append(i)
        return m

    def render_bar(self, tier: int, tempo_bpm: float, genre: str,
                   bar_idx: int, n_bars: int) -> np.ndarray:
        """Return a stereo float32 buffer for one bar. None on render failure."""
        m = self._bar_midi(tier, tempo_bpm, genre, bar_idx, n_bars)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            out = f.name
        raw = S.render_midi(m, out, sf2=self.sf2, sr=self.sr, gain=self.gain)
        if raw is None or not os.path.exists(raw):
            return None
        import soundfile as sf
        y, _ = sf.read(raw)
        try:
            os.unlink(raw); os.unlink(out)
        except OSError:
            pass
        if y.ndim == 1:
            y = np.stack([y, y], axis=1)
        return y.astype(np.float32)


if __name__ == "__main__":
    import soundfile as sf
    r = SymbolicBarRenderer()
    chunks = []
    # render an 8-bar rising-tier demo across a genre to prove the interface
    for bar, tier in enumerate([1, 2, 3, 4, 5, 4, 3, 2]):
        a = r.render_bar(tier=tier, tempo_bpm=104, genre="pop", bar_idx=bar, n_bars=8)
        assert a is not None, f"render failed at bar {bar}"
        chunks.append(a)
        print(f"bar {bar} tier {tier}: {a.shape[0]} samples, peak {np.abs(a).max():.3f}")
    out = "/Users/daniel/Desktop/PhD/groove_gen_project/groovegen_pilot/renderer_selfcheck.wav"
    sf.write(out, np.concatenate(chunks), r.sr)
    print("wrote", out)
