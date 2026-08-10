# GrooveGen — 12-Song Personalization Pipeline (Design Spec)

**Purpose:** Turn a user's own musical taste into the raw material of the closed-loop system. The user supplies 12 songs; the system analyzes them, builds a per-user profile mapped to three arousal anchors, generates personalized MusicGen beds from that profile, quality-gates them for tempo stability, and feeds them into the existing GENRE→TEMPO→DENSITY controller.

**Where this sits (honest scope — Position C):** Personalization happens *offline at profile time*. Live adaptation (tempo/density/genre from the biosignal) happens *at run time*. We generate FROM the user's taste profile offline; we ADAPT that generated material live from state. This is NOT real-time generation conditioned on instantaneous physiology (that is Position B, deferred to fall).

---

## 1. Input: the 12-song request

| Bucket | Count | Axis it anchors | Role in the arc |
|--------|------:|-----------------|-----------------|
| Danceable | 6 | High arousal / high groove | Start state + up-regulation target |
| Enjoyed (not necessarily danceable) | 2 | High valence / mid arousal | Pulls the mid-range toward what the user actually likes |
| Relaxing | 3–4 (see note) | Low arousal | Down-regulation target (calm end) |

**Design note on counts:** the user proposed 6/2/2. I recommend **6/2/3–4**. Two songs is too thin for a stable feature centroid. Either (a) bump relaxing to 3–4, or (b) keep 2 but treat the relaxing/enjoyed anchors explicitly as *soft priors* (lower weight, lower confidence) versus the 6-song danceable *anchor*. Do not claim precision from n=2. State this limitation in the paper.

**Input format:** user provides either (a) audio files (30–60 s excerpts are enough — the existing extractor uses 30 s), or (b) track IDs / links we fetch. Excerpts avoid full-song licensing issues and match the extractor's 30 s window.

---

## 2. Feature extraction (REUSE existing tooling — zero new research)

The existing extractor (`track_features.csv`, `feature_extractor_version 0.1.0`) already produces **52 features per track**, including everything this pipeline needs:

- **Rhythm/tempo:** `tempo_final`, `beat_this_tempo`, `beat_consistency`, `downbeat_consistency`, `beat_ibi_mean`, `meter_estimate`
- **Groove/density:** `onset_density`, `event_density_on_vs_off`, `lhl_syncopation_mean/std`, `plp_mean/std` (pulse clarity)
- **Timbre/energy:** `rms_mean/std`, `spectral_centroid`, `spectral_rolloff`, `spectral_flatness`, `zero_crossing_rate`, `mfcc_1..13`
- **Source balance:** `hpss_harmonic_ratio`, `hpss_percussive_ratio`, `sub_band_energy_ratio`, `low_band_energy_ratio`

**Action:** run the existing extractor on all 12 user songs → one feature row each. No new feature code required.

---

## 3. Profile construction (per-bucket centroids → arousal anchors)

For each bucket, compute a **robust centroid** (median, not mean — robust to one odd track) over a chosen feature subset:

- **Arousal-relevant subset** (for anchoring the arc): `tempo_final`, `onset_density`, `rms_mean`, `spectral_centroid_mean`, `hpss_percussive_ratio`, `event_density_on_vs_off`, `plp_mean`.
- **Style/timbre subset** (for prompt flavor): `mfcc_1..13` centroid, `spectral_flatness_mean`, `hpss_harmonic_ratio`, `low_band_energy_ratio`.

Output: three anchor points in a reduced feature space:

```
anchor_danceable  = median(features[6 danceable songs])   # high arousal
anchor_enjoyed    = median(features[2 enjoyed songs])      # high valence, mid arousal
anchor_relaxing   = median(features[3-4 relaxing songs])   # low arousal
```

**Confidence weight** per anchor = f(bucket_n, within-bucket feature variance). Danceable (n=6, low variance) → high confidence; relaxing/enjoyed → soft prior. Store the weights; the paper reports them honestly.

**Sanity checks (quality gate on the INPUT):**
- If a "danceable" song has low `onset_density`/`tempo`, or a "relaxing" song is high-tempo/high-percussive, flag the mislabel to the user (don't silently average it in).
- Require the danceable centroid tempo > relaxing centroid tempo (the arc must actually descend). If not, ask the user to re-check their picks.

---

## 4. Arc definition (personalized, replaces the generic Latin→Pop→R&B→calm)

The descending arc becomes a **walk through the user's own taste space**, from their danceable anchor toward their relaxing anchor, with the enjoyed anchor shaping the middle:

```
segment 1 (start / highest tempo)  <- anchor_danceable        (tempo ≈ danceable centroid)
segment 2 (mid-high)               <- blend(danceable, enjoyed)
segment 3 (mid-low)                <- blend(enjoyed, relaxing)
segment 4 (calm / lowest tempo)    <- anchor_relaxing
```

The controller's committed tempo at each segment picks which anchor(s) to blend (tempo-band derivation, exactly as today — but the *bands are now set from the user's own centroids*, not hard-coded 112/98/84). This is the key upgrade: **genre/tempo bands are personalized, not generic.**

---

## 5. Prompt construction (features → MusicGen text prompt)

Map the (possibly blended) anchor for each segment to a MusicGen prompt via a **feature→language template**. Example mapping rules:

| Feature | Prompt phrase driver |
|---------|----------------------|
| `tempo_final` | "at about {N} BPM" |
| `hpss_percussive_ratio` high | "driving/steady drums"; low → "sparse percussion" |
| `onset_density` / `event_density` | "busy" vs "minimal" rhythmic activity |
| `spectral_centroid` high | "bright"; low → "warm/dark" |
| `hpss_harmonic_ratio` high | "rich chords/melody"; low → "rhythm-forward" |
| `mfcc` cluster → nearest genre exemplar | genre word from the 6 StyleSpecs (hip-hop, r&b, pop, latin, classic-rock, metal) |

The nearest-genre step reuses `GENRE_ENERGY_ORDER` / the existing genre model to pick the closest *known* style word, so prompts stay in MusicGen's competent vocabulary. Result: a per-segment prompt like *"a warm r&b/soul groove at about 82 BPM, sparse steady drums, mellow"* — but now grounded in THIS user's relaxing songs.

---

## 6. Generate → QUALITY-GATE → cache (the step that protects audio quality)

**This is where the pop-wander problem gets solved for good.** For each segment prompt:

1. Generate the bed with MusicGen (offline, one call per segment).
2. **Measure tempo stability** (reuse today's diagnostic: beat jitter, onset-vs-ideal-grid error). Threshold example: reject if beat jitter > ~12 ms or grid error > ~40 ms (latin-quality bar).
3. If it fails: regenerate (different seed) up to K tries, OR apply beat-sync quantize, OR fall back to a clean uploaded bed for that band.
4. **Cache the accepted beds to WAV.** Every future run reuses them → zero MusicGen cost after the first accept.

This makes personalization and audio-quality *complementary*: personalization sets the prompt; the quality gate guarantees the bed is tempo-stable before it ever enters the live loop.

---

## 7. Live run (UNCHANGED — reuse the existing controller)

The accepted, cached beds feed the existing pipeline exactly as today: `CascadeController.step()` tracks the setpoint → committed tempo/genre per segment → `render_aligned_drums` per-bar density → `splice_beds_downbeat_hard_cut` transitions → MP4. No controller changes. The only difference: the beds are now personalized and pre-validated.

---

## 8. What to build, in order (all CPU/local except step 6's generation)

1. `profile_from_songs.py` — run extractor on 12 songs, build 3 weighted centroids, run input sanity checks. (local, free)
2. `arc_from_profile.py` — set personalized tempo bands + segment anchor blends from centroids. (local, free)
3. `prompt_from_anchor.py` — feature→prompt templater + nearest-known-genre snap. (local, free)
4. `generate_and_gate.py` — MusicGen generate + tempo-stability gate + cache. (Colab GPU, one-time per user)
5. Wire cached beds into nb15's segment loop (replace the current bed source). (local, free)

Steps 1–3 and 5 are free and local. Only step 4 touches Colab, and its caching means it runs once per user, not per render.

---

## 9. Honest limitations to state in the paper

- Personalization is at PROFILE time, not real-time conditioning on physiology (Position C, not B).
- Relaxing/enjoyed anchors are low-n soft priors unless buckets are enlarged.
- Prompts are snapped to MusicGen's 6 known styles — the system personalizes *within* that vocabulary, it doesn't invent new genres.
- Generated beds still require the quality gate; a fraction may fall back to uploaded beds.
- No efficacy claim — the arc is driven by a scripted setpoint (as in nb12/13/15).
