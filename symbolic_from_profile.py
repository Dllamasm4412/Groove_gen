"""symbolic_from_profile.py -- last-mile adapter: extracted feature profile -> symbolic bed.

This is the SYMBOLIC counterpart to prompt_from_anchor.py. Where that module turned
an extracted feature dict into a MusicGen TEXT prompt (lossy, uncontrollable), this
turns the SAME feature dict into EXACT symbolic bed parameters and renders a bed.

Design principle (matches two-timescale architecture): the user's songs shape the
BED (tempo, key/register, brightness via instrument choice, harmonic richness, genre
template, STARTING intensity). The controller independently drives the drum-intensity
TIER for the closed loop -- NOT set here. So onset_density/percussive_ratio only pick
a STARTING tier; they are not the controlled variable.

Feature -> bed-parameter mapping (all feature names match track_features.csv exactly):
  tempo_final            -> bed BPM (exact)
  mfcc_* + tempo + ratios-> genre template (salsa/pop/rnb/calm) via nearest-centroid
  spectral_centroid_mean -> instrument brightness (patch choice + voicing register)
  hpss_harmonic_ratio    -> chord richness (triad -> 7th -> 9th voicings)
  hpss_percussive_ratio  -> STARTING intensity tier (1-5), controller takes over after
  lhl_syncopation_mean   -> fixed genre 'spice' (clamped, per architecture) -- reported only

CPU-only, offline. Renders via FluidSynth + FluidR3_GM (same as the prototype).
"""
from __future__ import annotations
import os, numpy as np
import symbolic_bed_proto as S   # reuse build_salsa/pop/rnb/calm + render/polish

# ---- genre template registry (from the prototype) ----
GENRE_BUILDERS = {"latin-salsa": S.build_salsa, "pop": S.build_pop,
                  "r&b-soul": S.build_rnb, "calm": S.build_calm}

# Rough genre centroids in (tempo, centroid_hz, harm_ratio) space for nearest-match.
# Tuned to the committed bed library tempos + typical brightness/harmonicity.
GENRE_CENTROIDS = {
    "calm":        (73.0,  1300.0, 0.85),
    "r&b-soul":    (86.0,  1500.0, 0.80),
    "pop":         (104.0, 2300.0, 0.60),
    "latin-salsa": (125.0, 1900.0, 0.70),
}

def choose_genre(tempo, centroid, harm):
    """Nearest-centroid genre pick in normalized feature space."""
    def z(v, lo, hi): return (v-lo)/(hi-lo+1e-9)
    tq = z(tempo, 60, 200); cq = z(centroid, 800, 3700); hq = harm  # harm already ~0-1
    best, bd = None, 1e9
    for g,(gt,gc,gh) in GENRE_CENTROIDS.items():
        d = (tq-z(gt,60,200))**2 + (cq-z(gc,800,3700))**2 + (hq-gh)**2
        if d < bd: bd, best = d, g
    return best

def starting_tier(perc_ratio, onset_density):
    """Map percussiveness/onset activity of the reference songs -> STARTING tier 1-5.
    This is only the loop's initial condition; the controller drives it afterward."""
    # perc_ratio ~0.1-0.5 in this corpus; onset_density ~3-6
    score = 0.6*np.clip((perc_ratio-0.1)/0.4, 0, 1) + 0.4*np.clip((onset_density-3)/3, 0, 1)
    return int(np.clip(round(1 + score*4), 1, 5))

def brightness_transpose(centroid):
    """Brighter reference -> shift bed voicing up a bit (register). Returns semitone shift."""
    # centroid 800->3700 mapped to -3..+5 semitones
    return int(np.clip(round((centroid-1800)/350), -3, 6))

def map_profile(feat: dict) -> dict:
    """Turn one track_features.csv row (dict) into symbolic bed parameters."""
    tempo   = float(feat.get("tempo_final") or feat.get("tempo_librosa") or 100)
    centroid= float(feat.get("spectral_centroid_mean") or 1800)
    harm    = float(feat.get("hpss_harmonic_ratio") or 0.6)
    perc    = float(feat.get("hpss_percussive_ratio") or 0.3)
    onset   = float(feat.get("onset_density") or 4.0)
    sync    = float(feat.get("lhl_syncopation_mean") or 0.3)
    genre   = choose_genre(tempo, centroid, harm)
    # clamp tempo into the genre's sane band so the template stays idiomatic
    band = {"calm":(66,82),"r&b-soul":(78,96),"pop":(92,116),"latin-salsa":(108,140)}[genre]
    bpm  = float(np.clip(tempo, *band))
    return dict(genre=genre, bpm=round(bpm,1),
                start_tier=starting_tier(perc, onset),
                transpose=brightness_transpose(centroid),
                chord_richness=("9th" if harm>0.8 else "7th" if harm>0.55 else "triad"),
                syncopation_spice=round(float(np.clip(sync/3.0, 0.20, 0.40)),2),
                _src=dict(tempo=round(tempo,1),centroid=round(centroid,0),harm=round(harm,2),
                          perc=round(perc,2),onset=round(onset,2),sync=round(sync,2)))

def render_from_profile(feat: dict, out_wav: str, bars: int = 8):
    """Full pipeline: feature row -> params -> symbolic bed -> polished wav."""
    p = map_profile(feat)
    builder = GENRE_BUILDERS[p["genre"]]
    midi = builder(bpm=p["bpm"], bars=bars)
    # apply brightness transpose to pitched (non-drum) instruments
    if p["transpose"]:
        for inst in midi.instruments:
            if not inst.is_drum:
                for n in inst.notes:
                    n.pitch = int(np.clip(n.pitch + p["transpose"], 0, 127))
    raw = S.render_midi(midi, out_wav)
    pol = S.polish(raw, out_wav.replace(".wav","_polished.wav"))
    return p, pol

if __name__ == "__main__":
    import pandas as pd
    OUT="/Users/daniel/Desktop/PhD/groove_gen_project/symbolic_out"; os.makedirs(OUT, exist_ok=True)
    df = pd.read_csv("/Users/daniel/Desktop/PhD/groove_gen_project/uploaded_attachments/81b3afaf3b2a442cbffb9e69e7f4d360/track_features.csv")
    # the three diverse rows sampled earlier
    ids = ["62PLVssh2kExRDg50VVXjE","2J051fjLklkoPbzOoTAACZ","2RdEC8Ff83WkX7kDVCHseE"]
    for tid in ids:
        row = df[df.trackID==tid].iloc[0].to_dict()
        p, pol = render_from_profile(row, os.path.join(OUT, f"profile_{tid[:8]}.wav"))
        print(f"\n{tid[:8]}: src={p['_src']}")
        print(f"   -> genre={p['genre']} bpm={p['bpm']} start_tier={p['start_tier']} "
              f"transpose={p['transpose']} richness={p['chord_richness']} spice={p['syncopation_spice']}")
        print(f"   -> {os.path.basename(pol)}")
    print("\nDONE")
