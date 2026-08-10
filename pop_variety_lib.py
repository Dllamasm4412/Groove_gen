"""Per-genre variety library + procedural generator.

Answers the user's ask: songs should NOT always be the same melody. Variety = curated
library (musical) + procedural variation (non-repetitive), seeded from the user's
suggested-song profile so each suggestion yields a DIFFERENT matching song.

Two layers of variety:
  1) LIBRARY  -- hand-authored progressions + arp/riff motifs + structure templates per genre.
  2) PROCEDURAL -- transpose, tempo jitter, tier arc, arp permutation/rotation, motif choice,
                   voicing register, ghost-note density. Driven by a seed derived from the
                   track profile so it's deterministic per song but varied across songs.

Timbre 'character' (user picked C pad-pluck / D plucky keys) is passed through as a program
choice; the actual modern sound comes from the Colab supersaw/EP soundfont routing.
"""
import numpy as np, hashlib

# ----- LIBRARY: progressions (root MIDI + upper-structure triad) per genre -----
# Each chord = (root, [triad upper-structure notes]). Roots feed bass; triads feed stabs.
POP_PROGS = {
    "Am_C_F_G":  [(45,[64,67,72]),(48,[64,67,72]),(41,[65,69,72]),(43,[62,67,71])],
    "C_G_Am_F":  [(48,[64,67,72]),(43,[62,67,71]),(45,[64,69,72]),(41,[65,69,72])],  # I-V-vi-IV
    "F_G_Em_Am": [(41,[65,69,72]),(43,[62,67,71]),(40,[64,67,71]),(45,[64,69,72])],  # IV-V-iii-vi
    "Dm_G_C_Am": [(50,[65,69,74]),(43,[62,67,71]),(48,[64,67,72]),(45,[64,69,72])],  # ii-V-I-vi
    "Am_F_C_G":  [(45,[64,69,72]),(41,[65,69,72]),(48,[64,67,72]),(43,[62,67,71])],  # vi-IV-I-V (pop punk)
    "Cm_Ab_Eb_Bb":[(48,[63,67,72]),(44,[63,68,72]),(51,[63,67,70]),(46,[65,70,74])],# minor pop (Weeknd-ish)
}
POP_ARPS = {  # relative-to-triad index patterns (0,1,2 = triad notes; +12 = octave up)
    "climb":   [0,1,2,"1+","2","1","0+","1"],
    "rock":    [0,2,1,2,0,2,1,2],
    "wide":    ["0","2","1+","2","0+","2","1+","2"],
    "sparse":  [0,None,2,None,1,None,"2",None],
    "pendulum":[0,1,2,1,0,1,2,1],
}
POP_STAB_GRIDS = [
    [0,0,1,1, 0,1,1,0, 0,0,1,1, 0,1,0,1],   # syncopated funk chop
    [0,1,0,1, 0,1,1,0, 0,1,0,1, 1,0,1,0],   # busier
    [0,0,1,0, 0,1,0,1, 0,0,1,0, 0,1,0,1],   # sparser, breathes
    [1,0,0,1, 0,1,1,0, 1,0,0,1, 0,1,1,0],   # on-1 accent + chops
]
POP_TIER_ARCS = [[3,3,4,4,5,5,4,4],[4,4,4,5,5,4,4,3],[3,4,4,5,4,5,4,4],[4,5,4,4,5,5,4,3]]

# Character -> GM program (sandbox). Colab maps these to soundfont patches.
CHAR_PROG = {"pad_pluck":88, "plucky_keys":4, "square":80, "crystal":98, "saw":81, "vibes":11}

def _seed_from_profile(profile, salt=0):
    """deterministic int seed from a track profile dict (or trackID)."""
    key = str(profile.get("trackID", profile)) + f"|{salt}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**32)

def _resolve_arp(pattern, triad):
    """turn an arp pattern spec into MIDI pitches for a given triad."""
    out=[]
    for x in pattern:
        if x is None: out.append(None); continue
        if isinstance(x,int): out.append(triad[x]); continue
        # string like '1+' (index 1, +octave) or '0+'
        idx=int(x[0]); up=12 if x.endswith("+") else 0
        out.append(triad[idx]+up)
    return out

def make_pop_song(profile=None, character="pad_pluck", seed_salt=0):
    """Return a song spec: DIFFERENT progression/melody/tempo per profile+salt.

    profile: optional dict from symbolic_from_profile.map_profile (uses tempo/brightness/
             syncopation to bias choices). If None, purely random by salt.
    """
    profile = profile or {}
    rng = np.random.RandomState(_seed_from_profile(profile, seed_salt))
    # tempo: from profile if present, else 100-118, + small jitter
    base_bpm = float(profile.get("bpm", rng.randint(100,118)))
    bpm = float(np.clip(base_bpm + rng.uniform(-3,3), 92, 124))
    # transpose: brightness biases upward; else random -2..+3 semitones
    bright = profile.get("brightness_transpose", 0)
    transpose = int(np.clip(bright + rng.randint(-2,4), -4, 6))
    # pick progression -- minor profiles bias to minor progs
    prog_keys=list(POP_PROGS.keys())
    if profile.get("valence","")=="minor": prog_keys=["Am_C_F_G","Am_F_C_G","Cm_Ab_Eb_Bb","Dm_G_C_Am"]
    prog_name = prog_keys[rng.randint(len(prog_keys))]
    prog = [(r, [n+transpose for n in tri]) for (r,tri) in POP_PROGS[prog_name]]
    prog = [(r+transpose, tri) for (r,tri) in prog]
    # syncopation spice biases grid busyness
    spice = profile.get("syncopation_spice", rng.rand())
    grid = POP_STAB_GRIDS[min(int(spice*len(POP_STAB_GRIDS)), len(POP_STAB_GRIDS)-1)]
    # arp motif + rotation (procedural non-repetition)
    arp_name = list(POP_ARPS.keys())[rng.randint(len(POP_ARPS))]
    arp_rot  = rng.randint(0,8)
    tier_arc = POP_TIER_ARCS[rng.randint(len(POP_TIER_ARCS))]
    ghost_density = rng.choice([2,4,6])  # how many ghost stabs per bar
    return dict(genre="pop", bpm=round(bpm,1), transpose=transpose, prog_name=prog_name,
                prog=prog, stab_grid=grid, arp_name=arp_name, arp_rotation=arp_rot,
                tier_arc=tier_arc, ghost_density=int(ghost_density),
                program=CHAR_PROG.get(character,88), character=character,
                seed=int(_seed_from_profile(profile,seed_salt)))

def describe(spec):
    return (f"pop | {spec['prog_name']} | {spec['bpm']}bpm | t{spec['transpose']:+d} | "
            f"arp={spec['arp_name']}(rot{spec['arp_rotation']}) | grid#{POP_STAB_GRIDS.index(spec['stab_grid'])} | "
            f"char={spec['character']}")

if __name__=="__main__":
    # show that different profiles/salts give different songs
    demo_profiles=[
        {"trackID":"2J051fjLklkoPbzOoTAACZ","bpm":120,"brightness_transpose":2,"syncopation_spice":0.6},
        {"trackID":"62PLVssh2kExRDg50VVXjE","bpm":104,"brightness_transpose":0,"syncopation_spice":0.3,"valence":"minor"},
        {"trackID":"2RdEC8Ff83WkX7kDVCHseE","bpm":112,"brightness_transpose":3,"syncopation_spice":0.8},
    ]
    for p in demo_profiles:
        for salt in (0,1):
            print(describe(make_pop_song(p, character="pad_pluck", seed_salt=salt)))
