"""ROCK/METAL writing engine — a DIFFERENT idiom from the funk-pop triad-stab generator.

Metal/hard-rock accompaniment is NOT triad stabs + arp. It is:
  - POWER CHORDS: root + fifth (+ octave), no third -> works under distortion.
  - PALM-MUTED RIFFS: fast repeated 8th/16th chugs on the root, with accent hits.
  - GALLOP rhythm (Metallica/Maiden): 8th + two 16ths per beat.
  - Driving bass locked to the guitar root; double-kick / driving drums at high tiers.

This engine emits a SPEC-compatible dict but with idiom-specific note builders so the
renderer (render_variety) can play it. Timbre = distorted-guitar SF2 on Colab (falls back to
a bright GM patch locally so the RHYTHM/IDIOM is auditable now).

Tiers still map to intensity: L1 sparse open chords -> L5 full gallop + double kick feel.
"""
import numpy as np, hashlib

# riff rhythm templates per tier: 1 = attack on this 16th slot (16 slots/bar)
# metal is about the CHUG pattern, not chord changes.
RIFF_GRIDS = {
    1: [1,0,0,0, 1,0,0,0, 1,0,0,0, 1,0,0,0],          # whole/half open chords
    2: [1,0,1,0, 1,0,1,0, 1,0,1,0, 1,0,1,0],          # straight 8ths
    3: [1,0,1,1, 1,0,1,1, 1,0,1,1, 1,0,1,1],          # gallop (8th+2x16th)
    4: [1,1,1,1, 1,0,1,1, 1,1,1,1, 1,0,1,1],          # 16th chug w/ gallop
    5: [1,1,1,1, 1,1,1,1, 1,1,1,1, 1,1,1,0],          # full 16th chug wall
}
# accent slots (open/ring-out power chord instead of muted chug)
ACCENT_SLOTS = [0,8]

# minor/modal riff root movements (semitone offsets from tonic) — metal loves b2, b5, b6, b7
RIFF_MOVES = [
    [0,0,0,3],       # i - i - i - biii
    [0,0,5,3],       # i - i - v - biii
    [0,3,5,0],       # i - biii - v - i
    [0,0,-2,0],      # i - i - bVII(below) - i  (drop feel)
    [0,5,6,5],       # i - v - bVI - v
    [0,1,0,0],       # i - bII - i - i  (phrygian/thrash)
]

def _seed(profile, salt=0):
    key=str(profile.get("trackID",profile))+f"|rock|{salt}"
    return int(hashlib.md5(key.encode()).hexdigest(),16)%(2**32)

def make_rock_song(profile=None, character="dist_guitar", salt=0):
    """Return a rock/metal spec. Uses the profile's tempo/mode/energy if present."""
    profile=profile or {}
    rng=np.random.RandomState(_seed(profile,salt))
    bpm=float(profile.get("bpm", profile.get("tempo_final", rng.randint(90,150))))
    bpm=float(np.clip(bpm+rng.uniform(-2,2),70,180))
    # metal skews minor; honor explicit mode
    mode=str(profile.get("mode", profile.get("valence",""))).lower()
    is_minor = mode in ("minor","min","m","aeolian") or (mode=="" and rng.rand()<0.7)
    # brightness -> register (metal usually low; small transpose range, biased down)
    sc=profile.get("spectral_centroid_mean")
    transpose = int(np.clip(np.interp(sc,[1000,4000],[-5,2]),-7,2)) if sc else int(rng.randint(-5,1))
    # tonic low on the neck (drop-ish): root near E2 (40) region
    tonic = 40 + transpose
    moves = RIFF_MOVES[rng.randint(len(RIFF_MOVES))]
    # energy/onset -> base tier
    od=profile.get("onset_density")
    perc=profile.get("hpss_percussive_ratio",0.55); harm=profile.get("hpss_harmonic_ratio",0.45)
    base = int(np.clip(np.interp(od,[2,6],[2,5]),2,5)) if od else int(rng.randint(3,5))
    tier_arc=[int(np.clip(base+d,1,5)) for d in [0,0,1,1,1,0,1,-1]]
    drum_gain=float(np.clip(np.interp(perc/(perc+harm+1e-9),[0.4,0.65],[1.0,1.2]),0.95,1.25))
    return dict(genre=profile.get("genre","rock"), engine="rock_metal",
                bpm=round(bpm,1), is_minor=bool(is_minor), transpose=int(transpose),
                tonic=int(tonic), riff_moves=moves, tier_arc=tier_arc,
                drum_gain=round(drum_gain,3), drum_genre="rock",
                character=character, seed=int(_seed(profile,salt)))

def describe(s):
    return (f"{s['genre']} [rock_metal] | tonic{s['tonic']} moves{s['riff_moves']} | "
            f"{s['bpm']}bpm {'min' if s['is_minor'] else 'maj'} | t{s['transpose']:+d} | "
            f"drums x{s['drum_gain']} | tiers{s['tier_arc'][:4]}... | char={s['character']}")

if __name__=="__main__":
    tests=[
        {"trackID":"acdc_ts","genre":"hard rock","tempo_final":133,"spectral_centroid_mean":3400,
         "hpss_percussive_ratio":0.55,"hpss_harmonic_ratio":0.45,"onset_density":5.6,"mode":"major"},
        {"trackID":"met_es","genre":"metal","tempo_final":123,"spectral_centroid_mean":2900,
         "hpss_percussive_ratio":0.6,"hpss_harmonic_ratio":0.4,"onset_density":4.8,"mode":"minor"},
    ]
    for t in tests:
        for salt in (0,1): print(describe(make_rock_song(t,salt=salt)))
