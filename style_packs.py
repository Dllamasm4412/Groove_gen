"""Curated STYLE PACKS that override the genre-agnostic core when we have hand-authored
knowledge for a genre. Unknown genres fall through to genre_agnostic_core.derive_params.

A pack is just a function(profile, salt) -> params-dict-overrides. It may call the generic
core first and then patch specific fields, so packs stay small and only encode what's
genuinely genre-specific (e.g. latin clave grid, r&b 7th-chord voicings).

Registry is normalized/fuzzy: 'R&B', 'rnb', 'r and b' all resolve to the rnb pack.
"""
import numpy as np, re
import genre_agnostic_core as core

def _norm(g):
    g=(g or "").lower().strip()
    g=re.sub(r"[^a-z0-9]+"," ",g).strip()
    aliases={
        "r b":"rnb","r and b":"rnb","rhythm and blues":"rnb","rnb":"rnb","soul":"rnb","neo soul":"rnb",
        "pop":"pop","dance pop":"pop","synth pop":"pop","pop rock":"pop",
        "latin":"latin","salsa":"latin","reggaeton":"latin","latin pop":"latin",
        "calm":"calm","ambient":"calm","chill":"calm","lofi":"calm","lo fi":"calm",
        "rock":"rock","metal":"rock","hard rock":"rock","heavy metal":"rock",
        "punk":"rock","thrash":"rock","alt metal":"rock","nu metal":"rock",
    }
    return aliases.get(g, g)

# Genres whose accompaniment idiom is a SEPARATE writing engine (not a param-patch of the
# STAB/COMP core). These route to a dedicated engine module, not to PACKS. See
# genre_coverage_feasibility_memo.md: RIFF/POWER is engine #2.
ENGINE_ROUTES={"rock":"rock_metal_engine.make_rock_song"}

def engine_for(genre):
    """Return the dedicated-engine dotted path for a genre, or None if it uses the
    STAB/COMP core+packs path. NOTE: rock/metal timbre is a GM proxy until the
    waveshaper+cabinet-IR DSP chain lands (see memo section 5)."""
    return ENGINE_ROUTES.get(_norm(genre))

# ---- curated packs: call core, then patch genre-specific bits -----------------
def _pop(profile, salt):
    p=core.derive_params(profile,salt)
    p["arp_active"]=True                                 # pop wants the plucky arp over the top
    p["stab_grid"]=core.STAB_GRIDS[max(1,core.STAB_GRIDS.index(p["stab_grid"]))]  # >= medium funk
    p["source"]="pack:pop"
    return p

def _rnb(profile, salt):
    p=core.derive_params(profile,salt)
    # r&b: lush 7th chords -> add a 7th to each triad; laid-back so ease tiers down a notch
    newprog=[]
    for root,tri in p["prog"]:
        seventh=tri[0]+10                                # b7 above the 3rd-ish
        newprog.append((root,tri+[seventh]))
    p["prog"]=newprog
    p["tier_arc"]=[max(1,t-1) for t in p["tier_arc"]]
    p["arp_active"]=True; p["source"]="pack:rnb"
    return p

def _latin(profile, salt):
    p=core.derive_params(profile,salt)
    # latin: son clave 2-3 stab grid + drums forward
    clave=[1,0,0,1, 0,0,1,0, 0,1,0,0, 1,0,1,0]
    p["stab_grid"]=clave
    p["drum_gain"]=min(1.2,p["drum_gain"]*1.1)
    p["arp_active"]=True; p["source"]="pack:latin"
    return p

def _calm(profile, salt):
    p=core.derive_params(profile,salt)
    # calm: sparse, slow-ish, low tiers, gentle arp, drums quiet
    p["stab_grid"]=core.STAB_GRIDS[0]
    p["tier_arc"]=[max(1,min(3,t-2)) for t in p["tier_arc"]]
    p["drum_gain"]=min(p["drum_gain"],0.85); p["bpm"]=float(np.clip(p["bpm"],70,100))
    p["arp_active"]=True; p["arp_name"]="sparse"; p["source"]="pack:calm"
    return p

PACKS={"pop":_pop,"rnb":_rnb,"latin":_latin,"calm":_calm}

def has_pack(genre): return _norm(genre) in PACKS
def list_packs(): return sorted(PACKS.keys())
def build(profile, genre, salt=0):
    """Route: known genre -> curated pack; unknown -> generic core fallback."""
    key=_norm(genre)
    prof=dict(profile); prof.setdefault("genre",genre)
    if key in PACKS: return PACKS[key](prof,salt)
    p=core.derive_params(prof,salt)                      # generic fallback for ANY genre
    return p
