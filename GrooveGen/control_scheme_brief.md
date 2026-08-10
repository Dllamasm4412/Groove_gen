# Research brief: control scheme for closed-loop musical arousal/groove (GrooveGen, TEI paper)

## Context
GrooveGen is a closed-loop music system. A controller varies a musical parameter per bar to TRACK a scripted heart-rate setpoint (this is a SYSTEM/METHOD contribution — per-bar closed-loop control — NOT an efficacy claim. We never claim we "regulate emotion" or "lower HR"; HR is a scripted setpoint the controller tracks). Beds are symbolic MIDI (melody+harmony+bass, drums are a SEPARATE controllable track). Genres: salsa, pop, r&b/soul, calm.

Current design controls a single scalar: DRUM EVENT DENSITY (int 3-20). Problem observed: raw density stuffing sounds incoherent/cluttered and conflates two constructs. We are deciding what the controller SHOULD manipulate.

## Candidate schemes to evaluate
1. **Structured intensity tiers** — controller picks an intensity LEVEL (e.g. 1-5); each tier is a musically-designed drum/arrangement pattern that escalates coherently (backbeat -> offbeat hats -> 16th hats -> fills). One control axis, coherent at every level.
2. **Multi-parameter arousal bundle** — controller co-varies tempo + loudness + timbral brightness (+ structured rhythmic activity).
3. **Separate groove vs arousal axes** — axis A = syncopation/microtiming (groove/danceability/wanting-to-move); axis B = intensity (arousal).
4. **Genre/style morph** — move from a lower-energy style to a higher-energy style as the arousal lever (user's idea).

## Questions to answer (with CITATIONS to primary literature)
1. What musical parameters most robustly drive **perceived/felt AROUSAL**? Rank by evidence strength. (Look for: tempo, loudness, timbral brightness/spectral centroid, rhythmic density, mode, pitch height.) Cite music-emotion work (e.g. Juslin & Vastfjall, Gabrielsson & Lindstrom, Eerola & Vuoskoski, Gomez & Danuser).
2. What specifically drives **GROOVE / the sensation of wanting to move** (pleasurable urge to move, PLUMM/URGE)? Is it the SAME as arousal or separable? (Look for: Janata, Witek et al. 2014 syncopation-groove inverted-U, Madison, Stupacher, Matthews microtiming work.) Is moderate syncopation better than high?
3. Is **rhythmic/drum density** by itself a validated arousal lever, or does the evidence favor structured subdivision + backbeat salience over raw event count?
4. Is **genre/style morphing** (low-energy genre -> high-energy genre) a DEFENSIBLE single arousal manipulation, or does it introduce confounds (familiarity, preference, timbre, tempo all changing at once) that would weaken a controlled TEI study? Give the honest methodological verdict.
5. For a CLOSED-LOOP CONTROL paper (not efficacy), which scheme gives the cleanest, most defensible, most reproducible control signal while remaining musically coherent? Recommend ONE primary scheme + how to report it.

## Output
Write findings to `/home/user/workspace/control_scheme_research.md`. Structure:
- Ranked arousal drivers (with citations + effect direction)
- Groove vs arousal: same or separable? (with citations)
- Verdict on raw density (keep/replace/augment)
- Verdict on genre-morph idea (defensible or confounded?)
- FINAL RECOMMENDATION: one primary control scheme for the TEI paper, with a concrete parameter definition the engineer can implement, and 2-3 sentences on how to describe it in the paper's methods.
Cite primary sources with URLs inline. Be honest and opinionated — name trade-offs, recommend against weak designs.
