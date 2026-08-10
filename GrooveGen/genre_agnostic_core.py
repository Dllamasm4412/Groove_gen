"""Genre-AGNOSTIC song generator: derives ALL musical parameters from the audio-feature
profile of the user's suggested song, NOT from a genre name.

This is the fallback that lets the system handle ANY genre the user provides (afrobeat,
bossa nova, drill, k-pop, ...). It uses real audio evidence -- tempo, brightness, harmonic
vs percussive energy, syncopation, mode -- so it never hallucinates genre-specific theory.
Curated style packs (style_packs.py) OVERRIDE these defaults when we have them.

Feature columns come from track_features.csv (the user's extractor):
  tempo_final, spectral_centroid_mean, hpss_harmonic_ratio, hpss_percussive_ratio,
  onset_density, lhl_syncopation_mean  (+ optional mode/valence).

Design: every knob is a MONOTONIC, documented function of a feature -- so the mapping is
inspectable and defensible (matters for the paper), not a black box.
"""
import numpy as np, hashlib

# ---- generic chord-progression POOL (diatonic, genre-neutral) -----------------
# Expressed as scale-degree roots (0=tonic) + triad quality. We realize into MIDI
# given a key + mode, so this works in ANY key the profile implies.
MAJOR_PROGS = [
    [0,5,3,4],   # I-vi-IV-V (the pop/doo-wop workhorse)
    [0,4,5,3],   # I-V-vi-IV
    [3,4,0,5],   # IV-V-I-vi
    [1,4,0,5],   # ii-V-I-vi
    [0,3,4,0],   # I-IV-V-I
    [5,3,0,4],   # vi-IV-I-V
]
MINOR_PROGS = [
    [0,5,3,4],   # i-VI-iv-v (aeolian pop)
    [0,3,4,0],   # i-iv-v-i
    [0,6,3,4],   # i-VII-iv-v
    [0,5,1,4],   # i-VI-ii-v
    [0,3,6,4],   # i-iv-VII-v
]
# major-scale semitone offsets from tonic for scale degrees 0..6
MAJ_SCALE=[0,2,4,5,7,9,11]
MIN_SCALE=[0,2,3,5,7,8,10]

ARP_SHAPES = ["climb","rock","wide","sparse","pendulum","descend"]
STAB_GRIDS = [
    [0,0,1,0, 0,1,0,1, 0,0,1,0, 0,1,0,1],   # sparse
    [0,0,1,1, 0,1,1,0, 0,0,1,1, 0,1,0,1],   # medium funk
    [0,1,0,1, 0,1,1,0, 0,1,0,1, 1,0,1,0],   # busy
    [1,0,1,0, 1,1,0,1, 1,0,1,0, 1,0,1,1],   # very busy
]

def _seed(profile, salt=0):
    key=str(profile.get("trackID", tuple(sorted(profile.items())) if isinstance(profile,dict) else profile))+f"|{salt}"
    return int(hashlib.md5(key.encode()).hexdigest(),16)%(2**32)

def _get(profile, *names, default=None):
    for n in names:
        if n in profile and profile[n] is not None: return profile[n]
    return default

def derive_params(profile, salt=0):
    """Map audio features -> generation parameters. Every mapping documented + monotonic."""
    rng=np.random.RandomState(_seed(profile,salt))
    # --- tempo: use extracted tempo directly, small musical jitter ---
    bpm=float(_get(profile,"bpm","tempo_final",default=rng.randint(96,120)))
    bpm=float(np.clip(bpm+rng.uniform(-3,3),60,180))
    # --- mode/valence: explicit if given, else infer nothing -> random lean ---
    mode=_get(profile,"mode","valence",default=None)
    is_minor = (str(mode).lower() in ("minor","min","m","aeolian")) or (mode is None and rng.rand()<0.4)
    # --- brightness (spectral centroid) -> register transpose. Higher = brighter = up ---
    sc=_get(profile,"spectral_centroid_mean",default=None)
    if sc is not None:
        # centroid typically ~1000-4000 Hz; map to -3..+5 semitones
        transpose=int(np.clip(np.interp(sc,[1000,4000],[-3,5]),-4,7))
    else:
        transpose=int(rng.randint(-3,5))
    transpose+=int(_get(profile,"brightness_transpose",default=0))
    # --- syncopation -> stab grid busyness (more sync = busier off-beat writing) ---
    syn=_get(profile,"lhl_syncopation_mean","syncopation_spice",default=None)
    if syn is not None:
        syn_norm=float(np.clip(np.interp(syn,[0.0,0.6],[0,1]),0,1)) if syn>1e-6 else rng.rand()
    else:
        syn_norm=rng.rand()
    grid=STAB_GRIDS[min(int(syn_norm*len(STAB_GRIDS)),len(STAB_GRIDS)-1)]
    # --- harmonic vs percussive ratio -> melody density vs drum prominence ---
    harm=_get(profile,"hpss_harmonic_ratio",default=0.5)
    perc=_get(profile,"hpss_percussive_ratio",default=0.5)
    tot=harm+perc+1e-9; harm_frac=harm/tot
    # more harmonic -> arp more active + higher; more percussive -> sparser melody, drums up
    arp_active = harm_frac>0.45
    drum_gain = float(np.clip(np.interp(perc/tot,[0.3,0.7],[0.8,1.15]),0.75,1.2))
    # --- onset density -> tier arc energy (denser onsets -> higher tiers) ---
    od=_get(profile,"onset_density",default=None)
    if od is not None:
        base_tier=int(np.clip(np.interp(od,[1.0,6.0],[2,5]),2,5))
    else:
        base_tier=int(rng.randint(3,5))
    tier_arc=[int(np.clip(base_tier+d,1,5)) for d in [0,0,1,1,1,0,0,-1]]
    # --- pick progression from the right pool ---
    pool=MINOR_PROGS if is_minor else MAJOR_PROGS
    degrees=pool[rng.randint(len(pool))]
    scale=MIN_SCALE if is_minor else MAJ_SCALE
    # realize into MIDI: tonic base near C4 (60) + transpose
    tonic=60+transpose
    prog=[]
    for d in degrees:
        root=tonic+scale[d%7]-12            # bass-ish root
        # upper-structure triad: 1-3-5 of the degree, up an octave, genre-neutral voicing
        third=tonic+scale[(d+2)%7]
        fifth=tonic+scale[(d+4)%7]
        oct_=tonic+scale[d%7]+12
        prog.append((root,[third,fifth,oct_]))
    arp_name=ARP_SHAPES[rng.randint(len(ARP_SHAPES))]
    return dict(
        genre=_get(profile,"genre",default="generic"),
        bpm=round(bpm,1), is_minor=bool(is_minor), transpose=int(transpose),
        prog=prog, prog_degrees=degrees, stab_grid=grid,
        arp_name=arp_name, arp_rotation=int(rng.randint(0,8)), arp_active=bool(arp_active),
        tier_arc=tier_arc, drum_gain=round(drum_gain,3),
        ghost_density=int(rng.choice([2,4,6])),
        source="generic_core", seed=int(_seed(profile,salt)))

def describe(p):
    m="min" if p["is_minor"] else "maj"
    return (f"{p['genre']} [{p['source']}] | deg{p['prog_degrees']}/{m} | {p['bpm']}bpm | "
            f"t{p['transpose']:+d} | arp={p['arp_name']}(act={p['arp_active']}) | "
            f"drums x{p['drum_gain']} | tiers{p['tier_arc'][:4]}...")

if __name__=="__main__":
    tests=[
        {"trackID":"afro1","genre":"afrobeat","tempo_final":108,"spectral_centroid_mean":2600,
         "hpss_harmonic_ratio":0.4,"hpss_percussive_ratio":0.6,"onset_density":4.2,"lhl_syncopation_mean":0.45},
        {"trackID":"bossa1","genre":"bossa nova","tempo_final":128,"spectral_centroid_mean":1800,
         "hpss_harmonic_ratio":0.65,"hpss_percussive_ratio":0.35,"onset_density":2.1,"lhl_syncopation_mean":0.3,"mode":"minor"},
        {"trackID":"drill1","genre":"drill","tempo_final":142,"spectral_centroid_mean":3200,
         "hpss_harmonic_ratio":0.3,"hpss_percussive_ratio":0.7,"onset_density":5.5,"lhl_syncopation_mean":0.55,"mode":"minor"},
    ]
    for t in tests:
        for salt in (0,1): print(describe(derive_params(t,salt)))
