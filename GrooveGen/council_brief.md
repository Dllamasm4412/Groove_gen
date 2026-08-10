# AI Council Brief — GrooveGen genre-coverage architecture

You are one member of a 3-model council advising a PhD system-design decision. Give your
OWN independent, opinionated answer. Do not hedge into "it depends" — commit to numbers and
name trade-offs. A skeptical PhD researcher (Daniel Llamas, CU Boulder) values honest
technical pushback over agreement.

## System context (GrooveGen)
- A closed-loop music-generation system for a cognitive-science study. A PD controller sets a
  per-bar **intensity tier (L1-L5)** plus tempo; the generator renders audio to track a
  scripted arousal setpoint. Paper is a SYSTEM/METHOD contribution (per-bar closed-loop drum
  control), NOT an efficacy claim. NO VOCALS anywhere.
- Current generator is SYMBOLIC: writes MIDI (chord stabs + arpeggio + bass + tiered drums),
  renders via FluidSynth + SoundFonts (GM locally; Unison supersaw / 909 drums / GeneralUser
  on Colab T4). Runs one Colab session at a time, Python 3.12.
- Just generalized to "any genre": a genre-agnostic CORE derives params (progression pool,
  stab grid, arp shape, transpose, tier arc, drum gain) from a song's AUDIO FEATURES
  (tempo, spectral centroid=brightness, HPSS harmonic/percussive ratio, onset density, LHL
  syncopation, mode). Curated STYLE PACKS (pop/rnb/latin/calm) override the core when known.
- KNOWN GAP: the writing model = triad stabs + arpeggio (funk-pop idiom). Timbre = soft synth
  patches. So metal/rock inputs (Thunderstruck, Enter Sandman, Back in Black) come out with
  correct tempo/mode/energy but WRONG idiom (no distorted guitar, no power-chord riff) — sounds
  like a synth-pop cover. That's the problem to solve.

## Ground-truth genre distribution (Sophia's N=122 dataset, by artist_genre tag frequency)
pop 28.6% | rock/metal 18.1% | country/folk 10.2% | hiphop/rap 7.3% | r&b/soul 6.5% |
electronic/edm 5.0% | latin 1.7% | jazz/classical 1.4% | reggae/afro 1.0% | unmatched 20.3%
(unmatched is mostly "alternative"/"indie" -> folds into pop & rock).
GOAL: a system usable by MOST PEOPLE (broad coverage), not every niche.

## YOUR QUESTIONS (answer all, concisely, with commitment)
1. **Writing-engine taxonomy.** How many DISTINCT symbolic "writing engines" (idioms:
   accompaniment texture + rhythm model + voicing style) are needed to robustly cover MOST
   listeners, given the distribution above? List them explicitly and say which genre families
   each covers. Is it ~4, ~6, ~8, ~12? Commit to a number.
2. **Voicings.** For each engine, what chord-voicing vocabulary is essential (e.g. power chords
   (root+5), triads, drop-2 7ths, quartal, sus/add9, spread/open, single-note riff)? Which
   voicings are REUSED across engines (shared library) vs idiom-specific?
3. **Timbre/soundfont layer.** Symbolic writing is separable from timbre. How many distinct
   SoundFont/instrument "sound sets" are needed (e.g. distorted guitar, clean electric, acoustic
   guitar, Rhodes/EP, synth-lead/supersaw, piano, organ, 808/trap kit, acoustic kit, strings)?
   Which genres genuinely REQUIRE a specific timbre vs tolerate a generic one?
4. **Feasibility NOW (symbolic + FluidSynth + free SF2 on a Colab T4).** Which genre families
   are well-served by symbolic+SF2 TODAY? Which are only "OK"? Which genuinely NEED neural
   audio (e.g. MusicGen/JASCO) or vocals and should be declared OUT OF SCOPE for this paper?
   Be specific: metal distorted guitar via SF2 — good enough or not? hiphop/trap 808s — yes?
   EDM — yes? jazz — no?
5. **Recommendation for the PAPER vs the PRODUCT.** For the SYSTEM paper (method contribution,
   n~5-8 pilot), what genre coverage is DEFENSIBLE and sufficient? Separately, for a future
   "usable by most people" product, what's the build order? Where is the 80/20?

## Output format
Answer Q1-Q5 with headers. Lead each with your committed take in the first sentence. Include a
"where I'd push back on the researcher" note if you think building the rock/metal pack now is
the wrong priority. <=700 words.
