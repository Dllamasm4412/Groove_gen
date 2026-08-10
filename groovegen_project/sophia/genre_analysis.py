"""Genre analysis: which genres drive danceability in Sophia's dataset?

Genres are Spotify-style multi-label comma-separated strings. We tokenize them,
then for each genre token compute (a) prevalence, (b) mean track danceability,
and (c) a danceability-weighted prominence score. We also collapse fine-grained
Spotify micro-genres into broad families so the result is actionable for a
'pick your top genre' study UI.
"""
import pandas as pd, numpy as np
from pathlib import Path
from collections import Counter

DATA = Path(__file__).resolve().parent.parent / "data"
df = pd.read_csv(DATA / "survey_and_music_data_N122.csv")

# one row per unique track (genres/danceability are track-level, repeated across conditions)
tracks = df.drop_duplicates(subset="trackID")[
    ["trackID", "song_title", "artist_genres", "song_dance", "song_bpm",
     "song_energy", "song_valence"]
].dropna(subset=["artist_genres", "song_dance"]).copy()
print(f"Unique tracks with genre+danceability: {len(tracks)}")

def split_genres(s):
    return [g.strip().lower() for g in str(s).split(",") if g.strip()]

# ---- broad family mapping (collapse Spotify micro-genres) ----
FAMILIES = {
    "hip-hop/rap":   ["hip hop", "hiphop", "rap", "trap", "drill", "grime"],
    "pop":           ["pop", "art pop", "alt pop", "indie pop", "synthpop", "dance pop",
                      "electropop", "hyperpop", "k-pop", "power pop", "pop rock"],
    "electronic/edm":["edm", "electronic", "house", "techno", "dubstep", "drum and bass",
                      "dnb", "trance", "future bass", "deathstep", "riddim", "electro"],
    "rock":          ["rock", "alt rock", "indie rock", "classic rock", "hard rock",
                      "punk", "pop punk", "garage rock", "psychedelic"],
    "metal/hardcore":["metal", "metalcore", "heavy metal", "deathcore", "post-hardcore",
                      "screamo", "death metal", "djent", "nu metal", "hardcore"],
    "r&b/soul":      ["r&b", "rnb", "soul", "neo soul", "funk", "motown"],
    "country/folk":  ["country", "country rock", "folk", "folk pop", "americana",
                      "bluegrass", "singer-songwriter"],
    "latin":         ["latin", "reggaeton", "salsa", "bachata", "cumbia", "latin pop"],
    "jazz":          ["jazz", "swing", "bebop", "smooth jazz"],
}
def to_family(tok):
    for fam, keys in FAMILIES.items():
        if any(k == tok or k in tok for k in keys):
            return fam
    return None

# ---- raw token-level stats ----
rows = []
for _, r in tracks.iterrows():
    for tok in split_genres(r["artist_genres"]):
        rows.append((tok, r["song_dance"], r["song_bpm"]))
tok_df = pd.DataFrame(rows, columns=["genre", "dance", "bpm"])

tok_stats = (tok_df.groupby("genre")
             .agg(n=("dance", "size"), mean_dance=("dance", "mean"),
                  mean_bpm=("bpm", "mean"))
             .query("n >= 5").sort_values("mean_dance", ascending=False))
print("\n=== Top fine-grained genre tokens by mean danceability (n>=5) ===")
print(tok_stats.head(15).round(1).to_string())

# ---- family-level stats (the actionable view) ----
frows = []
for _, r in tracks.iterrows():
    fams = set(filter(None, (to_family(t) for t in split_genres(r["artist_genres"]))))
    for f in fams:
        frows.append((f, r["song_dance"], r["song_bpm"]))
fam_df = pd.DataFrame(frows, columns=["family", "dance", "bpm"])
fam_stats = (fam_df.groupby("family")
             .agg(n_tracks=("dance", "size"), mean_dance=("dance", "mean"),
                  mean_bpm=("bpm", "mean"))
             .sort_values("mean_dance", ascending=False))
# prominence = how much this family contributes to the high-dance pool
fam_stats["prevalence_%"] = (100 * fam_stats["n_tracks"] / len(tracks)).round(1)
print("\n=== Broad genre FAMILIES, ranked by mean danceability ===")
print(fam_stats.round(1).to_string())

# rank by a blended score: danceability is primary, but require reasonable prevalence
fam_stats["score"] = fam_stats["mean_dance"] * np.log1p(fam_stats["n_tracks"])
top3_dance = fam_stats.sort_values("mean_dance", ascending=False).head(3).index.tolist()
top3_score = fam_stats.sort_values("score", ascending=False).head(3).index.tolist()
print("\nTop-3 by mean danceability   :", top3_dance)
print("Top-3 by danceability x prevalence:", top3_score)

# save
out = Path(__file__).resolve().parent / "genre_analysis_results.json"
import json
json.dump({
    "n_unique_tracks": int(len(tracks)),
    "family_stats": fam_stats.reset_index().round(2).to_dict(orient="records"),
    "top_tokens": tok_stats.reset_index().round(2).head(20).to_dict(orient="records"),
    "top3_by_danceability": top3_dance,
    "top3_by_dance_x_prevalence": top3_score,
}, open(out, "w"), indent=2)
print(f"\nWrote {out}")
