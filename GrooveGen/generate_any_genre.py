"""SINGLE ENTRY POINT for the whole system: make_song(profile, genre, salt).

- profile: audio-feature dict from the user's suggested song (symbolic_from_profile output).
- genre:   any string the user provides. Known -> curated style pack. Unknown -> generic
           feature-driven core (works for afrobeat, bossa nova, drill, k-pop, anything).
- salt:    change it to get a different (non-repetitive) song for the same profile+genre.

Returns a spec compatible with render_variety.render_spec (which renders audio via the
symbolic FluidSynth path). Character (pad_pluck / plucky_keys) is passed through as the
program the Colab soundfont routing maps to a modern patch.
"""
import style_packs as SP
import genre_agnostic_core as core
from pop_variety_lib import CHAR_PROG

# which drum feel the tier engine should use. It only special-cases 'salsa';
# latin genres -> salsa clave drums, everything else -> default pop/backbeat.
def _drum_genre(genre):
    return "salsa" if SP._norm(genre)=="latin" else "pop"

def make_song(profile, genre, character="pad_pluck", salt=0):
    p=SP.build(profile, genre, salt)
    p["program"]=CHAR_PROG.get(character,88)
    p["character"]=character
    p["genre"]=genre
    p["drum_genre"]=_drum_genre(genre)
    p["prog_name"]=f"{genre}:{p.get('source','?')}"
    return p

def describe(p):
    return core.describe(p)+f" | char={p.get('character')}"

if __name__=="__main__":
    # KNOWN genres (packs) + UNKNOWN genres (generic fallback), all from feature profiles
    cases=[
        ("pop",        {"trackID":"2J051fjLklkoPbzOoTAACZ","tempo_final":118,"spectral_centroid_mean":3000,
                        "hpss_harmonic_ratio":0.55,"hpss_percussive_ratio":0.45,"onset_density":3.8,"lhl_syncopation_mean":0.4}),
        ("R&B",        {"trackID":"62PLVssh2kExRDg50VVXjE","tempo_final":92,"spectral_centroid_mean":1900,
                        "hpss_harmonic_ratio":0.7,"hpss_percussive_ratio":0.3,"onset_density":2.4,"lhl_syncopation_mean":0.35,"mode":"minor"}),
        ("afrobeat",   {"trackID":"afro1","tempo_final":108,"spectral_centroid_mean":2600,
                        "hpss_harmonic_ratio":0.4,"hpss_percussive_ratio":0.6,"onset_density":4.2,"lhl_syncopation_mean":0.5}),
        ("bossa nova", {"trackID":"bossa1","tempo_final":128,"spectral_centroid_mean":1800,
                        "hpss_harmonic_ratio":0.65,"hpss_percussive_ratio":0.35,"onset_density":2.1,"lhl_syncopation_mean":0.3,"mode":"minor"}),
    ]
    print("packs available:", SP.list_packs())
    for g,prof in cases:
        routed = "PACK" if SP.has_pack(g) else "generic-fallback"
        print(f"\n[{g}] -> {routed}")
        for salt in (0,1):
            print("  ", describe(make_song(prof, g, character="pad_pluck", salt=salt)))
