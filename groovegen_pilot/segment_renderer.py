"""
SymbolicSegmentRenderer — adapts GrooveGen composer to the cascade-controller
renderer contract.

The cascade controller (from groovegen_project) emits per-segment commands as
`(genre, tempo_bpm, tier)` where `tier ∈ {1..5}`. The composer takes
`(genre, tempo_bpm, density)` where `density ∈ [0, 1]`. This adapter:

  1. Normalizes genre naming ('r&b' → 'rnb').
  2. Applies RUNG_TIER_CAP so calm/rnb can't exceed their energy caps
     (preserves ladder monotonicity: calm@5_eff <= rnb@2_eff).
  3. Maps tier → density via a fixed lookup.
  4. Derives the per-segment seed deterministically from (session_seed, segment_idx)
     so the whole session is bit-identical given the same session_seed.
  5. Renders MIDI → stereo float32 numpy audio at 44100 Hz via fluidsynth.

Public API
----------
    SymbolicSegmentRenderer(sf2_path, sr=44100, gain=0.8, session_seed=42)
        .render_segment(genre, tempo_bpm, tier, n_bars,
                        segment_idx=0) -> np.ndarray[shape=(n_samples, 2), float32]

Contract invariants preserved (from AI_CONTINUATION_CONTEXT.md §3):
    - Ladder monotonicity: RUNG_TIER_CAP clamps tier BEFORE lookup.
    - Bit-identical headless runs: deterministic seed derivation from session_seed.
    - Crossfade safety left to caller (renderer is not the clock).
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pretty_midi
from composer import GENRE_CFG, generate_segment, render_directive

# =============================================================================
# Constants
# =============================================================================

# Genre-specific tier caps. Preserves ladder monotonicity: even at tier=5,
# calm can't out-energize rnb because calm gets clamped to tier 2 first.
# Values from AI_CONTINUATION_CONTEXT.md §2 (RUNG_TIER_CAP).
RUNG_TIER_CAP: dict[str, int] = {
    "calm": 2,
    "lofi": 3,
    "rnb": 4,
    "pop": 5,
    "latin": 5,
    "hiphop": 5,
    "rock": 5,
}

# Tier → density lookup. Linear-ish spread across the composer's tested range.
# Density spread of ~68-78% across d=0.3/0.6/0.9 was measured on bank_v1;
# extending to the extremes for finer control.
TIER_TO_DENSITY: dict[int, float] = {
    1: 0.15,  # very sparse (skeleton only)
    2: 0.35,  # sparse
    3: 0.55,  # medium (bank_v1 default)
    4: 0.75,  # busy
    5: 0.90,  # dense (max ornaments)
}


# =============================================================================
# Genre normalization
# =============================================================================

_GENRE_ALIASES: dict[str, str] = {
    "r&b": "rnb",
    "R&B": "rnb",
    "rnb": "rnb",
    "RNB": "rnb",
    "calm": "calm",
    "CALM": "calm",
    "lofi": "lofi",
    "LOFI": "lofi",
    "lo-fi": "lofi",
    "lo_fi": "lofi",
    "pop": "pop",
    "POP": "pop",
    "latin": "latin",
    "LATIN": "latin",
    "salsa": "latin",  # legacy renderer used 'salsa' internally for latin
    "hiphop": "hiphop",
    "HIPHOP": "hiphop",
    "hip-hop": "hiphop",
    "hip_hop": "hiphop",
    "rock": "rock",
    "ROCK": "rock",
}


def _norm_genre(g: str) -> str:
    """Normalize genre to composer's canonical name. Raises on unknown."""
    key = g.strip()
    if key in _GENRE_ALIASES:
        return _GENRE_ALIASES[key]
    key_lower = key.lower()
    if key_lower in _GENRE_ALIASES:
        return _GENRE_ALIASES[key_lower]
    raise ValueError(f"unknown genre {g!r}; known: {sorted(set(_GENRE_ALIASES.values()))}")


# =============================================================================
# Renderer
# =============================================================================


class SymbolicSegmentRenderer:
    """
    One MIDI + one fluidsynth call per segment.

    Parameters
    ----------
    sf2_path : str | Path
        Path to Musyng_Kite.sf2 (or any GM soundfont). Verified at construction.
    sr : int
        Output sample rate. Default 44100 (matches bank_v1).
    gain : float in [0, 1]
        Fixed gain applied at fluidsynth output. Do NOT normalize per-segment
        (would cause loudness jump at every crossfade — fault 0c).
    session_seed : int
        Seed for deriving per-segment RNG seeds. Same session_seed + same
        segment_idx sequence => bit-identical audio.
    """

    def __init__(
        self, sf2_path: str | Path, sr: int = 44100, gain: float = 0.8, session_seed: int = 42,
        master_gain_db: float | None = None,
    ):
        self.sf2_path = Path(sf2_path)
        if not self.sf2_path.exists():
            raise FileNotFoundError(f"soundfont not found: {self.sf2_path}")
        self.sr = sr
        self.gain = gain
        self.master_gain_db = MASTER_GAIN_DB if master_gain_db is None else float(master_gain_db)
        self.session_seed = session_seed
        # Check fluidsynth is on PATH
        r = subprocess.run(["fluidsynth", "--version"], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(
                "fluidsynth binary not found on PATH. "
                "Install with `brew install fluid-synth` on macOS."
            )

    def _derive_seed(self, segment_idx: int) -> int:
        """Deterministic per-segment seed from session_seed."""
        # Simple hash; deterministic and well-distributed enough for RNG seeding.
        return (self.session_seed * 1_000_003 + segment_idx * 2_654_435_761) & 0xFFFFFFFF

    def render_segment(
        self,
        genre: str,
        tempo_bpm: int,
        tier: int,
        n_bars: int,
        *,
        segment_idx: int = 0,
    ) -> np.ndarray:
        """
        Generate + render one segment.

        Returns
        -------
        np.ndarray[shape=(n_samples, 2), dtype=float32]
            Stereo audio at self.sr. Range roughly [-1, 1] but not clipped or
            normalized — the caller (or crossfade) manages amplitude.
        """
        genre_norm = _norm_genre(genre)

        # Clamp tier via genre cap BEFORE density lookup (ladder monotonicity)
        tier_int = int(tier)
        tier_clamped = min(tier_int, RUNG_TIER_CAP.get(genre_norm, 5))
        tier_clamped = max(1, tier_clamped)
        density = TIER_TO_DENSITY[tier_clamped]

        seed = self._derive_seed(segment_idx)

        # Generate MIDI (composer clamps tempo to its own genre range)
        pm = generate_segment(
            genre_norm,
            tempo_bpm=tempo_bpm,
            density=density,
            duration_bars=n_bars,
            seed=seed,
        )

        # Render via fluidsynth: MIDI -> WAV -> numpy stereo float32
        return self._render_pm_to_audio(pm)

    def render_pm(self, pm: pretty_midi.PrettyMIDI) -> np.ndarray:
        """Render already-composed MIDI (the opt-in v2 session source) with the
        same fluidsynth settings as render_segment."""
        return self._render_pm_to_audio(pm)

    def _render_pm_to_audio(self, pm: pretty_midi.PrettyMIDI, master: bool = True) -> np.ndarray:
        """MIDI -> stereo float32 audio buffer via fluidsynth.

        A segment carrying a render directive (composer.render_directive; Rock
        only) renders as 32-bit float, so nothing clips inside fluidsynth,
        then takes its fixed gain and the fixed peak limiter. Everything else
        renders 16-bit. The master attenuation (master_gain_db, one value for
        every segment) scales the output: inside fluidsynth for the 16-bit
        path (its gain is linear to float precision, and the 16-bit stage is
        where hiphop:4-5 clipped), after the limiter for directive segments,
        so relative levels are unchanged. master=False renders the reference
        level (energy measurement and certification; MASTER_GAIN_DB)."""
        m = self.master_gain_db if master else 0.0
        gain_db = render_directive(pm)
        if gain_db is None:
            return self._fluidsynth(pm, gain=self.gain * 10 ** (m / 20))
        audio = self._fluidsynth(pm, ["-O", "float"]) * np.float32(10 ** (gain_db / 20))
        audio = limit_peaks(audio, self.sr)
        return audio if m == 0.0 else (audio * np.float32(10 ** (m / 20))).astype(np.float32)

    def _fluidsynth(self, pm: pretty_midi.PrettyMIDI, extra: list[str] | None = None,
                    gain: float | None = None) -> np.ndarray:
        with tempfile.TemporaryDirectory() as td:
            midi_path = Path(td) / "seg.mid"
            wav_path = Path(td) / "seg.wav"
            pm.write(str(midi_path))

            cmd = [
                "fluidsynth",
                "-ni",
                "-F",
                str(wav_path),
                *(extra or []),
                "-r",
                str(self.sr),
                "-g",
                str(self.gain if gain is None else gain),  # fixed gain, no normalization
                str(self.sf2_path),
                str(midi_path),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size < 1000:
                raise RuntimeError(
                    f"fluidsynth render failed:\nstdout: {r.stdout}\nstderr: {r.stderr}"
                )

            # Read WAV as float32 stereo. fluidsynth default is 16-bit PCM stereo.
            audio = _read_wav_float32(wav_path)
            return audio


# =============================================================================
# WAV I/O — minimal, no soundfile dependency (scipy is used only by limit_peaks)
# =============================================================================


def _read_wav_float32(path: Path) -> np.ndarray:
    """
    Minimal WAV reader for fluidsynth output (16-bit PCM stereo).
    Returns (n_samples, 2) float32 in [-1, 1].
    """
    import wave

    if _is_float_wav(path):   # fluidsynth -O float (Rock render path)
        return _read_float_wav(path)

    with wave.open(str(path), "rb") as wf:
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    if sampwidth == 2:
        pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        pcm = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"unexpected sample width: {sampwidth} bytes")

    if n_channels == 1:
        pcm = np.stack([pcm, pcm], axis=1)
    else:
        pcm = pcm.reshape(-1, n_channels)[:, :2]  # take first two channels
    return pcm.astype(np.float32)


def _wav_chunks(path: Path) -> dict[bytes, bytes]:
    data = Path(path).read_bytes()
    chunks, i = {}, 12
    while i + 8 <= len(data):
        cid, size = data[i:i + 4], int.from_bytes(data[i + 4:i + 8], "little")
        chunks.setdefault(cid, data[i + 8:i + 8 + size])
        i += 8 + size + (size & 1)
    return chunks


def _is_float_wav(path: Path) -> bool:
    """IEEE float format tag (3), or WAVE_FORMAT_EXTENSIBLE with float SubFormat."""
    fmt = _wav_chunks(path).get(b"fmt ", b"")
    tag = int.from_bytes(fmt[0:2], "little") if len(fmt) >= 2 else 0
    return tag == 3 or (tag == 0xFFFE and len(fmt) >= 26 and fmt[24:26] == b"\x03\x00")


def _read_float_wav(path: Path) -> np.ndarray:
    """32-bit IEEE float WAV -> (n_samples, 2) float32."""
    chunks = _wav_chunks(path)
    fmt = chunks[b"fmt "]
    n_channels = int.from_bytes(fmt[2:4], "little")
    bits = int.from_bytes(fmt[14:16], "little")
    if bits != 32:
        raise ValueError(f"unexpected float width: {bits} bits")
    pcm = np.frombuffer(chunks[b"data"], dtype="<f4").reshape(-1, n_channels)
    if n_channels == 1:
        pcm = np.concatenate([pcm, pcm], axis=1)
    return pcm[:, :2].astype(np.float32)


# Fixed master attenuation (dB) on every rendered segment (live and auditions;
# not energy measurement or certification, which render the reference level).
# Clipping audit 2026-10-06 (renders/clip_audit/): hiphop:5 hard-clipped in
# fluidsynth's 16-bit output in every render (6-14 full-scale samples per
# segment, flat runs up to 3 samples) and hiphop:4 in some; float renders
# peaked up to +1.49 dBFS (bank hiphop:5; v2c +0.45). Rock never clipped (its
# limiter holds -1 dBFS). -2.5 dB puts every non-directive segment at or below
# -1 dBFS, the Rock limiter ceiling; crossfade joins add up to ~0.6 dB.
MASTER_GAIN_DB = -2.5

# Fixed peak limiter for directive (Rock) segments. Stateless per segment and
# deterministic; there is no per-segment normalization (quiet segments pass
# through untouched).
LIMIT_CEILING_DBFS = -1.0
LIMIT_WINDOW_S = 0.02


def limit_peaks(audio: np.ndarray, sr: int, ceiling_dbfs: float = LIMIT_CEILING_DBFS,
                window_s: float = LIMIT_WINDOW_S) -> np.ndarray:
    """Look-ahead peak limiter. The gain each sample needs to stay under the
    ceiling is min-filtered over 2W and box-smoothed over W: the smoothed gain
    never exceeds the need (so peaks stay under the ceiling) and each dip
    lasts about 3W, without a hard clip."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    ceil = 10 ** (ceiling_dbfs / 20)
    w = max(1, round(window_s * sr))
    need = np.minimum(1.0, ceil / np.maximum(np.max(np.abs(audio), axis=1), 1e-12))
    if need.min() >= 1.0:
        return audio.astype(np.float32)
    g = uniform_filter1d(minimum_filter1d(need, 2 * w + 1, mode="nearest"), w, mode="nearest")
    g = np.minimum(g, need)   # guards float rounding; already <= need by construction
    out = (audio.astype(np.float64) * g[:, None]).astype(np.float32)
    return np.clip(out, -np.float32(ceil), np.float32(ceil))   # float32 cast rounding (<= 1 ulp)


def _write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    """Write stereo float32 audio as 16-bit PCM WAV (for smoke test listening)."""
    import wave

    pcm = np.clip(audio, -1.0, 1.0)
    pcm_i16 = (pcm * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(pcm_i16.tobytes())


# =============================================================================
# CLI smoke test
# =============================================================================

if __name__ == "__main__":
    import argparse
    import sys

    p = argparse.ArgumentParser()
    p.add_argument("--sf2", required=True, help="Path to Musyng_Kite.sf2")
    p.add_argument(
        "--out-dir", default="./renderer_smoke_out", help="Output directory for smoke-test WAVs"
    )
    args = p.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(exist_ok=True, parents=True)

    r = SymbolicSegmentRenderer(sf2_path=args.sf2, session_seed=42)
    print("SymbolicSegmentRenderer ready")
    print(f"  sf2:          {r.sf2_path}")
    print(f"  sample rate:  {r.sr} Hz")
    print(f"  session seed: {r.session_seed}\n")

    # One segment per genre at tier 3, 8 bars
    for genre in ["calm", "pop", "rnb", "latin", "r&b"]:  # test alias too
        norm = _norm_genre(genre)
        cfg = GENRE_CFG[norm]
        tempo = cfg["tempo_default"]
        audio = r.render_segment(
            genre, tempo_bpm=tempo, tier=3, n_bars=8, segment_idx=hash(genre) & 0xFFFF
        )
        print(
            f"{genre:6} (norm={norm:5}): "
            f"{audio.shape}  {audio.dtype}  "
            f"peak={np.max(np.abs(audio)):.3f}  "
            f"rms={np.sqrt(np.mean(audio**2)):.3f}"
        )

        # Write for listening
        out_path = out_dir / f"{norm}_tier3.wav"
        _write_wav(out_path, audio, r.sr)
        print(f"   wrote {out_path}")

    # Bit-identical determinism check: same seg_idx twice -> exact same bytes
    a1 = r.render_segment("pop", tempo_bpm=118, tier=3, n_bars=8, segment_idx=999)
    a2 = r.render_segment("pop", tempo_bpm=118, tier=3, n_bars=8, segment_idx=999)
    same = np.array_equal(a1, a2)
    print(f"\ndeterminism check (same segment_idx): {'PASS' if same else 'FAIL'}")

    # Tier cap check: calm@5 should render same as calm@2 (both -> tier 2)
    a_calm5 = r.render_segment("calm", tempo_bpm=65, tier=5, n_bars=8, segment_idx=1)
    a_calm2 = r.render_segment("calm", tempo_bpm=65, tier=2, n_bars=8, segment_idx=1)
    tier_cap_ok = np.array_equal(a_calm5, a_calm2)
    print(f"ladder cap check (calm@5 == calm@2): {'PASS' if tier_cap_ok else 'FAIL'}")

    sys.exit(0 if same and tier_cap_ok else 1)
