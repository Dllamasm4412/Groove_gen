# Council answer — Opus

## Q1. Writing-engine taxonomy: **six engines** (five if you must ship faster)

Six distinct writing engines cover ~90% of Sophia's distribution. Genre count is large; *idiom* count is small, because accompaniment texture collapses across genres.

1. **RIFF/POWER** — monophonic-or-dyad rhythmic riff, root+5, palm-mute 8ths/16ths, unison bass. Rock, metal, punk, grunge, hard alternative (~28% with unmatched).
2. **STRUM** — sustained chord bed, strum pattern (DDU-UDU), open/spread voicings, root-fifth bass. Country, folk, singer-songwriter, indie-acoustic, pop-rock; reggae skank as a variant (~12–15%).
3. **STAB/COMP** (what you have) — short triad/7th stabs on a syncopated grid + arp. Funk-pop, disco, r&b, latin, afrobeat (~37% with pop).
4. **LOOP/SUSTAIN** — 1–2 bar repeated pad/pluck cell, sidechained sustain, 16th arps, minimal harmonic motion. EDM, house, techno, synthwave, cinematic (~5–8%).
5. **SPARSE-TRAP** — long pad or detuned pluck every 1–2 bars, no chordal rhythm; rhythm lives in hats + 808 glide. Hiphop/trap/drill (~7%).
6. **KEYS/COMP-JAZZ** — rootless drop-2/3 7ths, shell voicings, off-beat comp, walking bass. Jazz, neo-soul, gospel, lounge (~3%, but it's the credibility engine).

If you cut one, cut #6. Four engines is too few — you'd merge RIFF with STRUM, which is exactly your current failure mode.

## Q2. Voicings: one shared library, three idiom-locked additions

**Shared (≥3 engines):** close triads with all inversions, sus2/sus4, add9, spread triad (root–5–10), plus a voice-leading utility minimizing top-voice motion. Serves STAB, STRUM, LOOP, SPARSE-TRAP.

**Idiom-locked:**
- RIFF: dyad root+5 (and +octave), single-note scalar riffs from the mode, and a pentatonic/blues cell. **Never put full triads on a distorted timbre** — third + distortion = intermodulation mud. Most important rule in the build.
- KEYS-JAZZ: rootless drop-2 7ths/9ths, shell (3rd+7th), quartal stacks. Needs a 7th-chord progression pool, so it's a harmonic layer, not just a voicing swap.
- STRUM: 5–6 note guitar-shaped voicings with doubled open root/fifth, not pianistic close triads.

Register discipline beats voicing exotica: keep accompaniment 200 Hz–2 kHz, let bass own below 120 Hz.

## Q3. Timbre: **eight sound sets**

Distorted guitar (+palm-mute variant), clean/crunch electric, steel-string acoustic, piano, Rhodes/EP, organ, supersaw pad+lead, and percussion (acoustic-rock kit + 808/trap bank as two banks of one set).

**Timbre-critical:** metal/rock (distortion), trap (808 sub with glide, crisp hats), country/folk (acoustic guitar), EDM (saw/supersaw). **Timbre-tolerant:** pop, r&b, latin, cinematic — piano/EP/synth all read as correct. Jazz needs only a decent piano.

## Q4. Feasibility today on FluidSynth + free SF2

**Good now:** trap/hiphop (808 = sine + pitch glide; best ROI in the list), EDM (supersaw SF2 is genuinely convincing), country/folk (free acoustic SF2s are decent), pop/r&b/latin (working), rock rhythm guitar at moderate gain.

**Only "OK":** metal. Honest answer: **SF2 distorted guitar is not good enough.** Sampled distortion has baked-in gain staging, so power-chord dyads sound like two stacked samples rather than one saturated signal; there's no mute articulation, no pick variance, no chug. You get an 80s hard-rock keyboard patch, not Thunderstruck. The fix isn't a better SF2 — it's post-FluidSynth DSP: render a clean/overdriven patch, then tanh soft-clip + cabinet IR + tight noise gate in numpy/scipy (or pedalboard). ~150 lines, gets you to 80% credible. Without it, skip metal.

**Out of scope:** jazz (needs swing microtiming, brushes, human comp feel), anything vocal-led, lo-fi/texture genres. Don't reach for MusicGen/JASCO — it destroys per-bar latency and controllability, which *is* your contribution.

## Q5. Paper vs product

**Paper: three engines, four packs — pop/funk (have), rock-riff, trap, EDM.** ~60% of the distribution, and it spans the control-relevant axes: dense-harmonic, riff-driven, sparse-percussive. For n=5–8, coverage isn't the claim; controllability across idioms is. Report tier-tracking error per engine — that's the figure that sells it.

**Product order (80/20):** trap → EDM → rock-riff+DSP → country-strum → jazz-keys.

## Where I'd push back

Building rock/metal **first** is wrong. It's the highest-effort, highest-risk pack — the only one that forces you out of symbolic+SF2 into a DSP chain — and if the guitar sounds fake, reviewers hear "synth-pop cover with fuzz" and doubt the whole genre-agnostic claim. Trap and EDM hand you two new *structural* archetypes (sparse, loop-sustain) for a fraction of the effort, proving the core generalizes in the writing model, not just timbre. Do rock third, after the waveshaper+IR chain exists and is validated in isolation. And be blunt in the paper: declare metal timbre a known limitation rather than shipping a weak version of the genre you most conspicuously named.
