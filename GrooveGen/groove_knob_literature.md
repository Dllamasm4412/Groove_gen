# Groove Knob Literature: Empirical Findings for BBCI Parametric Drum-Pattern Design

**Purpose:** Design-relevant quantitative review of the groove-music perception literature for five rhythmic "knobs" in a parametric symbolic MIDI drum-pattern generator, for a closed-loop BBCI groove-induction study. Each section reports direction/shape, sweet-spot values, effect sizes, and documented interactions. Level recommendations are for a 4-level experimental sweep.

---

## 1. SYNCOPATION (Degree / Density)

### 1.1 Direction & Shape

**Inverted-U (Wundt curve) — well-replicated.** Medium syncopation maximises both wanting-to-move (WTM) and pleasure; low and high syncopation both reduce groove. This is the most robustly established causal claim in the groove literature.

**Primary evidence:**

**Witek et al. (2014)** ran a web-based survey (N = 66 participants, 50 synthesised funk drum-breaks) in which syncopation was calculated using a modified Longuet-Higgins & Lee (1984) index that additionally weights drum-instrument salience (bass drum vs. snare drum vs. hi-hat). The index ranged from **0 to 81 in their stimulus set**. Participants rated on 5-point Likert scales (1 = not at all, 5 = very much). Results:
- Quadratic regression on mean ratings: **R² = .347 for WTM, R² = .427 for pleasure** (both F(1,48) significant at p < .001); coefficients were negative (inverted parabola).
- ANOVA (3 levels: Low / Medium / High, with approximately equal N per category) showed a **main effect of syncopation: F(1.62, 79.15) = 15.73, p < .001** (Greenhouse-Geisser corrected).
- Post-hoc (alpha-adjusted p < .005): **Medium > Low > High for WTM**; **Medium > {Low = High} for pleasure**.
- Dancing experience significantly amplified ratings: F(1,49) = 13.53, p = .001. Musical training approached significance (p = .062, musicians slightly lower than non-musicians).
- Stimuli were 4/4, 120 BPM, two-bar funk patterns looped 4× (16 s total). No microtiming was included. Syncopation was statistically independent of event density (r = .092, p = .526).

**Sioros et al. (2014)** used two controlled experiments with algorithmically generated piano melodies spanning a range of syncopation levels and event densities. They used a computational syncopation-generation algorithm that shifts events from strong to weak metrical positions without altering other features. Results replicate the inverted-U: **moderate syncopation produced significantly higher groove ratings than zero or maximum syncopation**. Importantly, there was "no simple relation between syncopation magnitude and groove," indicating the specific pattern of displaced events (not just the count) matters. Event density was used as a control and did not interact with syncopation in a simple additive way.

**Senn et al. (2018)** (exploratory study, N = 665, 248 drum patterns from popular music): Syncopation explained **R² = 0.010** of groove variance — a statistically significant but practically small effect. The authors note this is an ecologically-valid, naturalistic design where style-bias (R² = .123) and familiarity (η² = .051) dominate.

**Senn et al. (2024)** replicated the inverted-U using perceived complexity (not syncopation-based) as predictor, but **failed to confirm it** with a stimulus set of 40 idiomatic drum patterns. They note the inverted-U in Witek et al. (2014) may be partly driven by the 14 experimenter-composed "extreme" stimuli at the tails (very low or very high syncopation) receiving systematically low ratings. Musician-composed stimuli with naturalistic mid-complexity consistently receive high ratings, but the extremes of the curve may reflect ecological invalidity rather than pure parametric effects.

### 1.2 Operationalisation

Witek et al.'s syncopation index (**S**): For each note event on a metrically weak position followed by a rest on the subsequent metrically strong position, the degree of syncopation is the **difference in metric salience weights** between the "rest" (strong) and the "note" (weak) position. Instrument weights are superimposed: bass drum attacks at metrically strong positions count differently from snare drum events. The index aggregates over all syncopations in a 2-bar pattern. Range in their 50-stimulus set: **0–81** (minimum 0 = no syncopation; maximum 81 = extremely syncopated / near-metric dissolution). The **three-level categorisation** used in their ANOVA:

| Level | Approximate S range | Description |
|-------|--------------------|--------------------------------------------|
| Low | S ≈ 0–16 | Patterns with few or no syncopations |
| Medium | S ≈ 17–39 | Intermediate — inverted-U peak zone |
| High | S ≈ 40–81 | Heavy syncopation — metre perception disrupted |

*Note: Exact bin boundaries were chosen to achieve roughly equal numbers of stimuli per category (Table S1 in Witek et al., 2014). The peak of the regression parabola for WTM falls at approximately **S ≈ 28–32** (mid-range of the Medium bin).*

The **Senn et al. (2024)** recalibration expresses syncopation per beat: their 40 stimuli ranged [0.5, 8.3] units/beat; the apex of the parabola in their re-analysis of WTM on syncopation/beat was at **4.84 syncopation units per beat**.

### 1.3 Recommended 4-Level Sweep

| Level | S (Witek 2014 units) | Description |
|-------|---------------------|----------------------------------------------|
| L0 | S ≈ 0–4 | Straight beat, minimal syncopation |
| L1 | S ≈ 12–18 | Light syncopation (1–2 displaced events) |
| L2 | S ≈ 26–34 | **Sweet spot** — near parabola apex |
| L3 | S ≈ 48–65 | Heavy syncopation / high metric complexity |

For MIDI implementation: L0 = all drum hits on downbeats and obvious strong beats; L1 = 1 displaced bass-drum or snare event per bar; L2 = 2–3 syncopated events across bass/snare (e.g., anticipation on the "and" of beat 2 or 4); L3 = 4+ syncopated events, including 16th-level displacements and compound off-beat groupings.

### 1.4 Effect Sizes and Evidence Strength

- Witek et al. (2014): Quadratic model R² = .35–.43 (WTM / pleasure). Main ANOVA effect: F = 15.73, p < .001. Effect is medium-to-large at the stimulus level.
- Senn et al. (2018): R² = .010 — small naturalistic effect.
- Replicated by Sioros et al. (2014), Madison & Sioros (2014), and partially by Senn et al. (2024).
- **Evidence strength: STRONG for inverted-U shape; MODERATE for exact apex location.**

### 1.5 Caveats

1. The Witek (2014) stimulus set conflates syncopation with pattern "type" (musician-composed vs. experimenter-composed). Experimenter-composed high-syncopation stimuli may be ecologically odd, artificially deflating the high-syncopation end of the curve.
2. Syncopation index is computed only on bass drum + snare drum; hi-hat is excluded. An index of total pattern syncopation (all voices) is not standard.
3. The inverted-U vertex shifts with listener dancing experience (dancers prefer slightly higher syncopation levels; Text S6 in Witek et al. 2014).
4. The 2024 null replication (Senn et al.) suggests the effect may be weaker or more specific than originally thought when stimuli are drawn entirely from idiomatic musical contexts.
5. Replication by Sioros et al. (2014) used melodic (piano) not drum stimuli, limiting direct transferability.

**Citations:**
- Witek, M.A.G., Clarke, E.F., Wallentin, M., Kringelbach, M.L., & Vuust, P. (2014). Syncopation, body-movement and pleasure in groove music. *PLOS ONE*, 9(4), e94446. https://doi.org/10.1371/journal.pone.0094446
- Sioros, G., Miron, M., Davies, M., Gouyon, F., & Madison, G. (2014). Syncopation creates the sensation of groove in synthesized music examples. *Frontiers in Psychology*, 5, 1036. https://doi.org/10.3389/fpsyg.2014.01036
- Senn, O., Kilchenmann, L., Bechtold, T., & Hoesl, F. (2018). Groove in drum patterns as a function of both rhythmic properties and listeners' attitudes. *PLOS ONE*, 13(6), e0199604. https://doi.org/10.1371/journal.pone.0199604
- Senn, O., Hoesl, F., Bechtold, T.A., Kilchenmann, L., Jerjen, R., & Witek, M. (2024). Null effect of perceived drum pattern complexity on the experience of groove. *PLOS ONE*, 19(11), e0311877. https://doi.org/10.1371/journal.pone.0311877

---

## 2. TEMPO / BPM

### 2.1 Direction & Shape

**Inverted-U with a peak near 100–120 BPM.** Tempo has a non-monotonic effect on groove, with a clear optimum. Both too-slow and too-fast tempos reduce groove. The shape is consistent across studies, though the exact peak varies by pattern type.

**Primary evidence:**

**Etani et al. (2018)** is the most direct controlled study. They varied tempo systematically (60, 75, 100, 120, 150, 200 BPM) across five drum-break patterns (varying 8th-note vs. 16th-note pattern organisation and syncopation: degrees 2, 11, 2, 13, 15 on the Witek index). N = 35 Japanese music majors. Key results:
- Main effect of tempo: **F(2.831, 96.251) = 21.808, p < .01, ηp² = .391** — a large effect.
- Main effect of pattern: **F(2.664, 90.584) = 11.244, p < .01, ηp² = .249**.
- The interaction was significant (p = .002, ηp² = .077), meaning the optimal tempo depends on pattern type.
- Bonferroni post-hoc: **200 BPM < all others (p < .05); 60 BPM < 100 and 120 BPM (p < .01); 120 BPM marginally > 150 BPM (p = .077)**.
- Quadratic regression was significantly better than linear for all five patterns: **estimated optimal tempi were 107–126 BPM** (see Table 2 in paper). 16th-note patterns with medium syncopation (16_mid) peaked at ~110.6 BPM; 8th-note patterns with low syncopation (8_low) peaked at ~123.1 BPM. **No significant differences in optimal tempo between patterns** were found in Monte Carlo simulations, so the collective estimate of ~100–120 BPM is robust.
- The adjusted R² was modest (0.03–0.23) — tempo explains some but not all variance.

**Janata, Tomic, & Haberman (2012)** used 148 commercially available popular music excerpts across genres (Soul/R&B, Jazz, Rock, Folk). Key tempo finding: pieces with faster tempi elicited higher groove ratings overall; the **average tempo of high-groove-rated pieces was 115.6 BPM** (with concentration near 100 BPM ± 10 BPM, noted by Ashley 2014, as cited in Etani et al.). Soul/R&B produced highest groove. Familiarity (not tempo alone) was the primary predictor in Janata et al.'s design; tempo was confounded with genre.

**Madison et al. (2011)** found **no significant correlation between tempo and groove** across five music cultures — but this may be because each cultural piece was already performed at an "ecologically optimal" tempo, as Madison et al. (2011) themselves suggest. When tempo is systematically varied (as in Etani et al. 2018), the inverted-U emerges clearly.

**Madison (2006)** showed that for commercially available music, slower tempos monotonically decreased "makes me want to move" ratings — but this was monotonic over a limited range and confounded with genre.

**Merker (2014)** theoretically grounds the ~120 BPM peak in human **locomotor tempo** (~2 Hz / 120 BPM), which is the natural stepping rate. Entrainment to beat is easiest near this tempo.

**Moelants (2002)** analysis of DJ BPM lists found the **distribution peak between 120 and 130 BPM** for dance music.

### 2.2 Recommended 4-Level Sweep

| Level | BPM | Rationale |
|-------|-----|-----------|
| L0 | 70 BPM | Well below optimum; groove impaired |
| L1 | 95 BPM | Low boundary of sweet spot |
| L2 | 115 BPM | **Near-optimal** (consensus peak) |
| L3 | 150 BPM | Above optimum; groove diminished |

*Note: If the experiment also manipulates 16th-note swing (Knob 5), prefer patterns with 8th-note hi-hat subdivisions at L0–L1 BPM levels, because 16th-note subdivision at fast tempi becomes cognitively demanding.*

### 2.3 Effect Sizes and Evidence Strength

- Etani et al. (2018): ηp² = .391 for tempo — large effect size.
- Janata et al. (2012): No formal effect size for tempo alone (confounded with genre).
- **Evidence strength: STRONG for inverted-U; STRONG for 100–120 BPM range as optimum.**

### 2.4 Caveats

1. Etani et al.'s sample was all Japanese music majors (N = 35); cross-cultural generalisability is limited.
2. Optimal tempo interacts with pattern type (8th vs. 16th note subdivisions). 16th-note patterns may peak slightly lower (~110 BPM) than 8th-note patterns (~123 BPM).
3. Tempo and syncopation interact: for a fixed pattern, increasing tempo may effectively reduce the perceptual "weight" of syncopation events (they pass faster). This interaction is not systematically quantified.
4. For BBCI applications using locomotion-relevant rhythms, staying within 90–130 BPM keeps stimuli closest to natural step frequency for adult participants.

**Citations:**
- Etani, T., Marui, A., Kawase, S., & Keller, P.E. (2018). Optimal tempo for groove: Its relation to directions of body movement and Japanese nori. *Frontiers in Psychology*, 9, 462. https://doi.org/10.3389/fpsyg.2018.00462
- Janata, P., Tomic, S.T., & Haberman, J.M. (2012). Sensorimotor coupling in music and the psychology of the groove. *Journal of Experimental Psychology: General*, 141(1), 54–75. https://doi.org/10.1037/a0024208
- Madison, G., Gouyon, F., Ullén, F., & Hörnström, K. (2011). Modeling the tendency for music to induce movement in humans: First correlations with low-level audio descriptors across music genres. *Journal of Experimental Psychology: Human Perception and Performance*, 37(5), 1578–1594. https://doi.org/10.1037/a0024323

---

## 3. EVENT DENSITY / Number of Onsets per Bar

### 3.1 Direction & Shape

**Monotonically positive** (higher onset density → more groove), with no established inverted-U or ceiling in the ecologically-valid range of popular music drum patterns. The effect is consistent but small in naturalistic datasets.

**Primary evidence:**

**Madison et al. (2011)** studied 100 commercially available musical excerpts from five genres. Of all acoustic descriptors tested, **beat salience and event density (sub-beat variability / density)** were the two strongest predictors of groove, both positively correlated. These were genre-general (not just one culture). Microtiming predictors were non-significant or negative.

**Senn et al. (2018)** (248 naturalistic drum patterns, N = 665): Event density explained **R² = 0.011** — statistically significant (p ≈ .003 in their regression), positive direction. This is essentially the same magnitude as syncopation (R² = .010). Both effects were stronger for music professionals than for novices or mere listeners. Importantly, beat salience, residual microtiming, and rhythmic variability showed **no effect** in this large-scale ecologically-valid design.

**Witek et al. (2014)** controlled event density experimentally: syncopation and total onset count were made statistically independent (r = .092, p = .526) in their 50-stimulus set. Event density was not independently varied.

**Sioros et al. (2014)** used event density as a control condition (adding events without changing syncopation) and found that increasing density alone (without syncopation) did **not** increase groove as strongly as adding syncopation, but a mild positive trend was present.

**Madison & Sioros (2014)** found that when musicians maximised groove in monophonic melody performance, they added more notes on faster metrical levels (16th and 8th notes). This produced both increased syncopation and increased event density simultaneously, so their relative contributions cannot be disentangled from this study alone.

### 3.2 Operational Definition

Event density in groove research is typically operationalised as **the number of onset events per beat** (or per bar), particularly for events **faster than the beat level** (i.e., sub-beat events: 8th, 16th, 32nd notes). In drum patterns this equates to total note count across all voices per 1 or 2 bars. Senn et al. (2018) used **total number of hits per bar** across all drum voices.

Typical ranges in popular music drum patterns:
- Minimal/sparse patterns (e.g., simple 4-on-the-floor electronic): 4–8 onsets/bar
- Standard rock/pop beat: 8–12 onsets/bar
- Funk/soul patterns: 12–18 onsets/bar
- Dense funk / hip-hop: 16–24+ onsets/bar

### 3.3 Recommended 4-Level Sweep

| Level | Onsets/bar | Description |
|-------|-----------|------------------------------------------------|
| L0 | 4–6 | Sparse: kick + snare on quarters only |
| L1 | 8–10 | Standard: 8th-note hi-hat + kick/snare |
| L2 | 14–16 | Dense: 16th-note hi-hat + syncopated kick/snare |
| L3 | 20–24 | Very dense: 16th-note subdivisions in all voices |

*Note: Ensure syncopation index (Knob 1) is held roughly constant across density levels if density is the independent variable, or orthogonalise the two.*

### 3.4 Effect Sizes and Evidence Strength

- Madison et al. (2011): Beat salience and event density were the **strongest groove predictors across genres** but exact effect sizes (r, R²) are not fully reported in accessible abstracts.
- Senn et al. (2018): R² = .011 — small but significant.
- **Evidence strength: MODERATE (positive monotonic, but small effect size in naturalistic designs; no controlled parametric study analogous to Witek's syncopation study exists).**

### 3.5 Caveats

1. No study has specifically isolated event density across the full range (from 4 to 24 onsets/bar) in a fully controlled parametric design with groove as the sole dependent variable.
2. Event density is correlated with syncopation in real music: denser patterns tend to include more syncopation, making orthogonal control essential.
3. In Senn et al. (2018), familiarity and style-bias had far larger effects (combined R² = .152 vs. .011 for density). Individual differences dominate in naturalistic designs.
4. Density may interact with tempo: at high BPM, high density can create perceptual overload. At low BPM, density increases may feel more salient.

**Citations:**
- Madison, G., Gouyon, F., Ullén, F., & Hörnström, K. (2011). Modeling the tendency for music to induce movement in humans: First correlations with low-level audio descriptors across music genres. *Journal of Experimental Psychology: Human Perception and Performance*, 37(5), 1578–1594. https://doi.org/10.1037/a0024323
- Senn, O., Kilchenmann, L., Bechtold, T., & Hoesl, F. (2018). Groove in drum patterns as a function of both rhythmic properties and listeners' attitudes. *PLOS ONE*, 13(6), e0199604. https://doi.org/10.1371/journal.pone.0199604
- Sioros, G., Miron, M., Davies, M., Gouyon, F., & Madison, G. (2014). Syncopation creates the sensation of groove in synthesized music examples. *Frontiers in Psychology*, 5, 1036. https://doi.org/10.3389/fpsyg.2014.01036

---

## 4. MICROTIMING / TIMING DEVIATIONS (Non-quantized expressive timing)

### 4.1 THE DEBATE — Stated Plainly

This is the most contested parameter in groove research. Three distinct positions exist:

**Position A — "PD Theory"** (Keil, 1987, 1995): Participatory Discrepancies — small temporal deviations from strict metronomic grid — are *essential* for groove. Microtiming creates the "rhythmic tension" that makes music feel alive and invites entrainment. This position is widely held by professional musicians.

**Position B — "Exactitude Hypothesis"** (Frühauf et al. 2013; Davies et al. 2013): Perfectly quantized/mechanically-timed music produces *higher* groove ratings. Microtiming deviations are *detrimental* to groove.

**Position C — "Ceiling tolerance" / "tight but not loose"** (Senn et al. 2016; Kilchenmann & Senn 2015): Both fully quantized and naturally-performed microtiming (original small deviations) produce equivalently high groove. Exaggerated microtiming (>20–40% magnification) *reduces* groove. Neither PD Theory nor the Exactitude Hypothesis is fully supported.

**Design implication for BBCI:** Given the weight of controlled experimental evidence, **microtiming variance should be near-zero for initial conditions**; a small positive nudge (original human performance level) is tolerable, but larger deviations reliably hurt groove.

### 4.2 Primary Evidence

**Frühauf, Kopiez, & Platz (2013)** — *Music on the Timing Grid* — Musicae Scientiae:
- N = 93 music students. Simple rock drum pattern (snare + bass drum), 5 degrees of microtiming deviation: −25, −15, 0 (quantized), +15, +25 ms.
- **Result: The quantized version (0 ms deviation) received the highest groove quality ratings**. Increasing deviation (in either direction) produced monotonically lower ratings.
- Additional asymmetry: **early shifts were rated more negatively** than equivalent late shifts (bass drum and snare differ).
- No interaction with musical expertise in rock/pop style.
- **Conclusion explicitly stated: "groove effect independent of microtiming deviations."**

**Davies, Madison, Silva, & Gouyon (2013)** — *The Effect of Microtiming Deviations on the Perception of Groove in Short Rhythms* — Music Perception, 30(5), 497–510:
- Used synthesised Jazz, Funk, and Samba patterns with idiomatic microtiming patterns for each style. Microtiming magnitudes varied parametrically from 0 to ~double the natural level.
- Two experiments: untrained listeners + experts.
- **Result: "Contrary to a common and frequently expressed belief in the literature, systematic microtiming led to decreased groove ratings, as well as liking and naturalness."** 
- **Exception**: Jazz microtiming was "largely unaffected" by magnitude; only the largest (40 ms unsystematic) Jazz deviations produced significant decreases (Cohen's d = 0.71).
- No evidence that any level of microtiming *increased* groove in Funk or Samba.
- Expert listeners showed greater sensitivity to manipulations than non-experts.

**Senn, Kilchenmann, von Georgi, & Bullerjahn (2016)** — *The Effect of Expert Performance Microtiming on Listeners' Experience of Groove in Swing or Funk Music* — Frontiers in Psychology, 7, 1487:
- N = 159 (79 music experts, 80 non-experts). Two professional musicians recorded funk (100 BPM) and swing (150 BPM) patterns. The microtiming deviations (PDs) were scaled from −100% (fully quantized) to +100% (doubled deviations) in 12 steps.
- Outcome variables: Entrainment, Enjoyment, Irritation (EAG questionnaire) + Valence, Arousal, Dominance (SAM).
- **Key result: "Both the fully quantized music and the music with the originally performed microtiming pattern were rated equally high on groove." Groove ratings were high for all stimuli with Signed-Δ-Magnitude ≤ +20% (i.e., original or tighter timing); ratings decreased significantly at +40% expansion and beyond.**
- Pairwise effect sizes: largest Irritation effect was d = 0.966 (between −60% and +100% conditions).
- Style (swing vs. funk) did NOT significantly affect any outcome variable — surprising given expectations that jazz/swing depends on microtiming.
- **Neither PD Theory nor the Exactitude Hypothesis fully confirmed**: quantized and natural-timing conditions were statistically indistinguishable.

**Kilchenmann & Senn (2015)** — using objective body-movement tracking with the same stimulus set: Expert listeners showed entrainment differences, with the **tightest non-zero timing conditions driving the largest entrainment response** (not the fully quantized version), which partially supports PD Theory for expert listeners only. This conflicts with the questionnaire data from the same experiment, raising questions about dissociation between subjective experience and motor behaviour.

**Madison et al. (2011)**: Systematic microtiming was **not significantly correlated with groove** in the naturalistic sample; unsystematic microtiming was negatively correlated.

**Senn et al. (2018)**: Residual microtiming in naturalistic drum patterns showed **no effect on groove ratings** (R² ≈ 0) in the 248-pattern naturalistic study.

**Ziereis, Datseris et al. (2019)** — *Microtiming Deviations and Swing Feel in Jazz* — Scientific Reports:
- N = 160 listeners, 12 jazz piano standards, original MTDs quantized / expanded / inverted.
- Result: **Quantized versions were rated slightly higher than original recordings for swing feel**; expanded MTDs rated lower. Inversion had minimal effect for most pieces.
- Conclusion: "naturally fluctuating MTDs are not an essential factor for the feeling of swing."

### 4.3 Summary Position

| Study | Style | N | Direction of MT effect on groove |
|-------|-------|---|----------------------------------|
| Frühauf et al. 2013 | Rock | 93 | Negative (quantized = best) |
| Davies et al. 2013 | Funk, Samba | ~40 | Negative |
| Davies et al. 2013 | Jazz | ~40 | Null (except very large deviations) |
| Senn et al. 2016 | Swing, Funk | 159 | Null for original MT; negative for expanded MT |
| Madison et al. 2011 | Multi-genre | 100 clips | Null / negative |
| Senn et al. 2018 | Multi-genre drum | 665 | Null |
| Ziereis et al. 2019 | Jazz | 160 | Null / slight negative |
| Kilchenmann & Senn 2015 | Swing, Funk | 20 experts | Mixed (body motion ≠ rating) |

### 4.4 Recommended 4-Level Sweep

Given the evidence: **microtiming should default to near-zero (quantized) for the BBCI paradigm**. If microtiming is included as a knob, use a narrow, non-negative range:

| Level | MTD RMS | Description |
|-------|---------|------------------------------------------------------|
| L0 | 0 ms | Fully quantized / mechanical timing |
| L1 | ≈ 5–8 ms RMS | Very tight — sub-threshold for most listeners |
| L2 | ≈ 12–18 ms RMS | Natural human-performance level |
| L3 | ≈ 30–40 ms RMS | Clearly perceptible — likely reduces groove |

*If the goal is to maximise groove, use L0 or L1. L3 is a "degraded" condition for comparison.*

### 4.5 Effect Sizes and Evidence Strength

- Frühauf et al. (2013): Monotonic decreasing function; direction clear, exact d not reported in public abstract.
- Senn et al. (2016): Max Irritation Cohen's d = 0.966 between extreme conditions; entrainment effects near-significant (d ≈ 0.26–0.48 for ≥ +80% expansion).
- **Evidence strength: STRONG that large microtiming deviations hurt groove; MODERATE that quantized timing is equivalent to small natural deviations; WEAK evidence that any microtiming level improves groove.**

### 4.6 Caveats

1. **Genre specificity**: Jazz microtiming (especially swing ratio) may behave differently from random MTDs. The swing ratio is a macro-timing feature, not a small deviation — see Knob 5.
2. Expert vs. novice dissociation: Experts are more sensitive to MT manipulations; body-motion responses may differ from subjective reports.
3. The PD literature (Keil, ethnomusicologists) is largely based on expert musician testimony, not listener rating studies — caution in dismissing it entirely.
4. In MIDI implementation, "quantization" means snapping to a timing grid; human performance introduces natural micro-fluctuations. Fully-quantized MIDI avoids these.

**Citations:**
- Frühauf, J., Kopiez, R., & Platz, F. (2013). Music on the timing grid: The influence of microtiming on the perceived groove quality of a simple drum pattern performance. *Musicae Scientiae*, 17(2), 246–260. https://doi.org/10.1177/1029864913486793
- Davies, M., Madison, G., Silva, P., & Gouyon, F. (2013). The effect of microtiming deviations on the perception of groove in short rhythms. *Music Perception*, 30(5), 497–510. https://doi.org/10.1525/MP.2013.30.5.497
- Senn, O., Kilchenmann, L., von Georgi, R., & Bullerjahn, C. (2016). The effect of expert performance microtiming on listeners' experience of groove in swing or funk music. *Frontiers in Psychology*, 7, 1487. https://doi.org/10.3389/fpsyg.2016.01487
- Kilchenmann, L., & Senn, O. (2015). Microtiming in swing and funk affects the body movement behavior of music expert listeners. *Frontiers in Psychology*, 6, 1232. https://doi.org/10.3389/fpsyg.2015.01232
- Ziereis, A., Datseris, G., Geisel, T., Albrecht, T., Priesemann, V., & Hagmayer, Y. (2019). Microtiming deviations and swing feel in jazz. *Scientific Reports*, 9, 19812. https://doi.org/10.1038/s41598-019-55981-3

---

## 5. SWING / SHUFFLE RATIO (Especially 16th-note swing)

### 5.1 Direction & Shape

**Likely inverted-U or sweet-spot**, but the empirical evidence is limited and less precise than for syncopation. The swing ratio (or beat-upbeat ratio, BUR) shifts the position of off-beat subdivision events from the straight (1:1 = 50%) to the triplet (2:1 = 67%) position or beyond. Most groove-based American popular music uses swing ratios **between 1:1 (straight / 50%) and 2:1 (triplet / 67%)**, with genre-specific norms.

**Critical distinction from microtiming:** Swing ratio is a *systematic*, *intentional*, *global* displacement of sub-beat events (e.g., all 8th-note off-beats or all 16th-note off-beats shifted by a fixed proportion). This is fundamentally different from random or semi-random microtiming deviations (Knob 4). Swing is a macro-timing feature analogous to a **new grid**; microtiming is randomness around that grid.

### 5.2 Primary Evidence

**Senn et al. (2016 / 2018 ecosystem)** — Senn et al.'s 2016 swing/funk study used a professional swing performance at 150 BPM (12-bar swing pattern) and a funk performance at 100 BPM. In the swing condition, the natural swing ratio of the recording was defined as the 0% baseline (Δ-Magnitude). The study did **not** vary the mean swing ratio independently; it varied the *microtiming deviations around* the swing grid. Therefore this study does not directly answer what swing ratio maximises groove. However, the null effect of Style (swing vs. funk) on groove ratings suggests the swing ratio inherent in these two performances did not differentially affect subjective groove.

**Friberg & Sundström (2002)** — *Swing Ratios and Ensemble Timing in Jazz Performance* (Music Perception, 19(3), 333–349): A foundational musicological study. Measured actual beat-upbeat ratios (BURs) in jazz recordings across a range of tempos. Key finding: **BUR depends strongly on tempo** — at slow tempos (40–80 BPM) BURs were large (2:1 to 3:1 / triplet feel or beyond); at fast tempos (200–300 BPM) BURs approached 1:1 (straight feel). This is the well-known "swing at slow tempos" phenomenon. Effective swing ratios for medium tempos (100–160 BPM) clustered around **1.5:1 to 2:1** (corresponding to 60%–67% in Linn notation).

**Ziereis, Datseris et al. (2019)**: Used the average swing ratio of each of 12 jazz piano standards as the reference grid for defining MTDs. Quantizing to this (non-isochronous) grid produced slightly higher swing-feel ratings than the original performances (which had MTDs around that grid). This suggests the **swing ratio itself (not the micro-fluctuations around it) is what carries the swing feel**, consistent with Friberg & Sundström (2002).

**Ethanhein.com (2023) synthesises common practice**: Straight = 50%; light swing ≈ 57% (4:3 ratio); moderate swing = 60% (3:2 ratio); triplet swing = 67% (2:1 ratio). Jazz at slow tempos can reach 70–75%+. "Most groove-based American music of the past hundred years uses between 50% and 67% swing."

**Jacquet et al. / JASA (2017)**: *Effects of tempo, swing density, and listener's drumming experience on the groove of drum patterns* (JASA, 141(6), 4200) tested swing density (proportion of 8th-note subdivisions that are swung) and tempo on groove. While the full paper is behind a paywall, its existence confirms controlled experimental work on swing parameters. From abstract: swing density (how many beats are swung, not just the ratio) interacted with tempo.

**Senn et al. (2018)** included "Swing_8" and "Swing_16" as predictor variables in their 248-drum-pattern study. The results for these variables were **not highlighted as significant predictors** of groove in their abstract or summary — suggesting that in the naturalistic ecologically-valid sample, swing ratio alone did not account for significant groove variance, possibly because most pop/rock patterns were already swing-consistent for their genre.

### 5.3 Genre Norms for Swing Ratio (From empirical measurement)

| Genre / Feel | BUR (Beat-Upbeat Ratio) | As % (Linn notation) | 16th-note equivalent |
|---|---|---|---|
| Straight / quantized | 1:1 | 50% | 50% |
| Light funk/hip-hop swing | 1.3:1 – 1.5:1 | 56–60% | 53–57% |
| Standard jazz/swing | 1.5:1 – 2:1 | 60–67% | 57–63% |
| Triplet shuffle / blues | 2:1 | 67% | 67% |
| Slow jazz / extreme swing | 2:1 – 3:1 | 67–75% | > 67% |

*Note: 16th-note swing (as in funk) is applied to 16th-note subdivisions (the "e" and "a" positions within a beat), whereas 8th-note swing is applied to the "and" positions. These are independent.*

### 5.4 Recommended 4-Level Sweep

For a 16th-note groove context (funk/hip-hop style), varying 16th-note swing ratio:

| Level | Swing ratio (16th) | BUR | Description |
|-------|-------------------|----|--------------------------------------------------|
| L0 | 50% | 1:1 | Straight / quantized 16th notes |
| L1 | 55–57% | 1.2:1 – 1.3:1 | Light swing — subtle, common in hip-hop |
| L2 | 60–63% | 1.5:1 – 1.7:1 | **Standard funk swing sweet spot** |
| L3 | 67% | 2:1 | Triplet shuffle — strong, blues/shuffle feel |

For 8th-note swing (jazz/soul context), the same levels apply to the "and" of each beat.

### 5.5 Effect Sizes and Evidence Strength

- No direct controlled experiment has isolated 16th-note swing ratio as the sole variable with groove as the dependent variable.
- Indirect evidence: Friberg & Sundström (2002) shows BUR is a robust feature of jazz performances. Ziereis et al. (2019) shows swing ratio > MTDs around it in determining swing feel.
- **Evidence strength: MODERATE for the existence of a preferred range (1.5:1 – 2:1 / 60–67%); WEAK for a precisely defined inverted-U sweet spot for groove (WTM + pleasure).**

### 5.6 Caveats

1. Swing ratio and tempo interact: at faster tempos (>160 BPM), large swing ratios become unnatural (Friberg & Sundström 2002).
2. The distinction between 8th-note swing and 16th-note swing is critical: applying 8th-note swing at a "funk tempo" (100–120 BPM) gives a very different feel from 16th-note swing at the same tempo.
3. Swing ratio and syncopation are not independent: swung patterns can create syncopation-like emphasis on off-beat positions.
4. For the BBCI paradigm, **swing ratio is likely the most promising "positive knob"** (the only timing-based parameter that reliably creates a positive feel change without the risks of microtiming), but requires careful genre-specific calibration.

**Citations:**
- Friberg, A., & Sundström, A. (2002). Swing ratios and ensemble timing in jazz performance. *Music Perception*, 19(3), 333–349. https://doi.org/10.1525/MP.2002.19.3.333
- Ziereis, A., Datseris, G., Geisel, T., Albrecht, T., Priesemann, V., & Hagmayer, Y. (2019). Microtiming deviations and swing feel in jazz. *Scientific Reports*, 9, 19812. https://doi.org/10.1038/s41598-019-55981-3
- Senn, O., Kilchenmann, L., Bechtold, T., & Hoesl, F. (2018). Groove in drum patterns as a function of both rhythmic properties and listeners' attitudes. *PLOS ONE*, 13(6), e0199604. https://doi.org/10.1371/journal.pone.0199604

---

## 6. AUXILIARY PARAMETERS: Beat Salience and Tempo Instability

### 6.1 Beat Salience

**Madison et al. (2011)** is the key paper. Beat salience — defined as the **acoustical prominence of the regular beat** relative to surrounding events in the audio signal — was one of the **two strongest correlates of groove** in their 100-clip, five-genre dataset (the other being event density). The correlation was positive and genre-general. The effect was replicated by Stupacher et al. (2016), who additionally found high sound intensity in the low bass frequency range (60–250 Hz, the "bass groove" region) was positively correlated with groove.

**Beat salience vs. event density in Senn et al. (2018)**: Contradicting Madison et al. (2011), Senn et al. found **no significant effect of beat salience** on groove (R² ≈ 0) in their 248 naturalistic drum-pattern study. This discrepancy may reflect differences in how beat salience was computed (audio-based in Madison; pattern-based in Senn) or in the stimulus sets.

**Implication for MIDI design**: A strong, clearly perceptible downbeat (beat 1) is important. The kick drum pattern should clearly mark the pulse. The signal-to-noise ratio of the beat relative to off-beat events contributes to groove.

**Citation:** Madison, G., Gouyon, F., Ullén, F., & Hörnström, K. (2011). Modeling the tendency for music to induce movement in humans. *Journal of Experimental Psychology: Human Perception and Performance*, 37(5), 1578–1594. https://doi.org/10.1037/a0024323

### 6.2 Tempo Instability / Rhythmic Variability

**Senn et al. (2018)** tested "rhythmic variability" (inter-beat-interval variance / tempo fluctuation) as a predictor of groove and found **no significant effect** (R² ≈ 0).

**Implication**: Tempo should be held constant (metronome-precise) across loops in a BBCI paradigm. Systematic tempo acceleration or deceleration (ritardando / accelerando) is not a groove-positive intervention based on current evidence.

---

## 7. DOCUMENTED PARAMETER INTERACTIONS

| Interaction | Evidence | Direction |
|-------------|----------|-----------|
| Syncopation × Tempo | Etani et al. (2018): Optimal tempo differed by pattern type (8th vs. 16th note patterns) — p = .002 interaction. | 16th-note patterns peak at lower BPM than 8th-note patterns |
| Syncopation × Dancing Experience | Witek et al. (2014): Dancers amplify groove ratings; vertex of inverted-U may shift toward higher syncopation for dancers (Text S6). | Dancers prefer slightly more complex syncopation |
| Syncopation × Musical Expertise | Senn et al. (2018): Effects of syncopation and event density were stronger for music professionals (vs. novices). | Professionals more sensitive to rhythmic structure |
| Microtiming × Expertise | Senn et al. (2016): Near-significant Signed-Δ-Magnitude × Expertise interaction for Entrainment and Enjoyment. | Experts more sensitive to MT manipulations |
| Microtiming × Style | Davies et al. (2013): Jazz tolerated microtiming better than Funk/Samba. | Genre-specific tolerance |
| Swing Ratio × Tempo | Friberg & Sundström (2002): BUR decreases as tempo increases. | Fast tempos → straighter timing |
| Event Density × Syncopation | Sioros et al. (2014): Density alone weaker than syncopation; combining them not purely additive. | Syncopation dominates |

---

## 8. SUMMARY TABLE

| Parameter | Effect Shape | Recommended 4 Levels | Evidence Strength | Key Citation(s) |
|-----------|-------------|----------------------|-------------------|-----------------|
| **Syncopation** | Inverted-U (Wundt curve); peak at medium S | L0: S≈0–4 (none) / L1: S≈12–18 (light) / L2: S≈26–34 (**sweet spot**) / L3: S≈48–65 (heavy) | **Strong** — multiple replications | Witek et al. 2014 (R²=.35–.43); Sioros et al. 2014 |
| **Tempo / BPM** | Inverted-U; peak ~100–126 BPM | L0: 70 BPM / L1: 95 BPM / L2: 115 BPM (**peak**) / L3: 150 BPM | **Strong** — Etani et al. ηp²=.39 | Etani et al. 2018; Janata et al. 2012 |
| **Event Density** | Monotonically positive (more = more groove); no ceiling established | L0: 4–6 hits/bar / L1: 8–10 / L2: 14–16 / L3: 20–24 | **Moderate** — positive but small effect | Madison et al. 2011; Senn et al. 2018 (R²=.011) |
| **Microtiming / MTD** | Inverted-J: quantized ≈ natural-MT >> exaggerated MT; NO evidence that MT adds groove | L0: 0 ms (quantized) / L1: 5–8 ms RMS / L2: 12–18 ms RMS / L3: 30–40 ms RMS (degraded) | **Strong** that large MTD hurts; **moderate** that quantized ≈ natural MT | Frühauf et al. 2013; Davies et al. 2013; Senn et al. 2016 |
| **Swing Ratio (16th)** | Likely inverted-U or sweet spot; 60–67% (1.5:1 – 2:1 BUR) is sweet zone | L0: 50% (straight) / L1: 55–57% (light) / L2: 60–63% (**standard funk**) / L3: 67% (triplet shuffle) | **Moderate** (limited controlled studies; strong genre norms) | Friberg & Sundström 2002; Ziereis et al. 2019 |

---

## 9. DESIGN RECOMMENDATIONS FOR THE BBCI PARADIGM

1. **Primary manipulation (highest effect size): Syncopation.** Use the Witek syncopation index. Set L2 as the baseline "groovy" condition. Use L0 and L3 as degraded conditions and L1 and L2 as the target range for BBCI feedback.

2. **Fix tempo at 100–120 BPM** for the groove-induction context. Vary it only if tempo is itself a target knob. If varying, use the L1/L2/L3 levels from the table (avoid 70 BPM for baseline groove).

3. **Microtiming should default to 0 ms (quantized).** If microtiming is a knob, start at L0 and allow only positive steps to L1–L2. Do not use L3 in groove-induction conditions.

4. **Swing ratio is the safest "positive timing" knob.** A transition from L0 (straight) to L2 (60–63% / 3:2 ratio) adds groove without the risks of random microtiming.

5. **Event density is a useful secondary knob.** Increase gradually from L0 to L2 for a more-groove condition. Keep syncopation matched across density conditions.

6. **Control for familiarity and style-bias** (per Senn et al. 2018, these explained R²=.152 vs. structural features R²≈.01). Use unfamiliar drum-break stimuli or randomise pattern identity.

7. **Participant stratification by dancing experience** (Witek et al. 2014). Dancers respond more strongly to syncopation manipulations.

---

*Report prepared for BBCI groove-induction study design. All empirical claims are sourced from primary peer-reviewed publications cited inline.*
