# GrooveGen — Genre Coverage & Feasibility Analysis
### How many writing engines + sound sets to be "usable by most people," and what's feasible now
**Date:** 2026-08-04 · **For:** Daniel Llamas (CU Boulder) · **Method:** AI council (Claude Opus 5, GPT-5.6, Gemini 3.1 Pro) + web research subagent, grounded in Sophia's N=122 genre distribution

---

## 1. Ground truth: what "most people" actually listen to

Genre-tag frequency in Sophia's dataset (`genre_distribution_sophia.txt`), bucketed into families:

| Family | Share of tags | Notes |
|---|---|---|
| Pop | 28.6% | + most of the 20% "alternative/indie" unmatched folds here |
| Rock / Metal | 18.1% | your named test case |
| Country / Folk | 10.2% | |
| Hip-hop / Rap | 7.3% | |
| R&B / Soul | 6.5% | |
| Electronic / EDM | 5.0% | |
| Latin | 1.7% | |
| Jazz / Classical | 1.4% | |
| Reggae / Afro | 1.0% | |

**Takeaway:** the head of the distribution is short. **Six families cover ~76% of tags** (~90%+ once alternative/indie is folded into pop+rock). You do NOT need dozens of genres to serve most people — you need a handful of *idioms*.

---

## 2. The key insight: genres are many, but IDIOMS are few

All three council members converged (independently) on the same core idea: **an "engine" is an accompaniment idiom (texture + rhythm model + voicing style), and idioms collapse across genres.** Pop, disco, and much of r&b share one idiom; rock/metal/punk share another. So the question isn't "how many genres" but "how many writing engines."

### Council vote on engine count
| Model | Engines | List |
|---|---|---|
| **Gemini 3.1 Pro** | **4** | Four-chord synth (pop/EDM/r&b) · Heavy riff (rock/metal) · Trap/boom-bap (hiphop) · Strum & pick (country/folk) |
| **GPT-5.6** | **6** | Pulse-pop/electronic · Guitar-riff · Acoustic-songwriter · Beat-loop/808 · Pocket-harmony (r&b/funk/reggae) · Clave/tumbao (latin) |
| **Claude Opus 5** | **6** (5 if rushed) | RIFF/power · STRUM · STAB/comp (have) · LOOP/sustain (EDM) · SPARSE-TRAP · KEYS/comp-jazz |

**Synthesis — recommended target: 6 engines**, but sequenced so the first 3 do the heavy lifting:

1. **STAB/COMP** (pop/funk/r&b/latin/afrobeat) — *already built* ✅ — ~37% of tags
2. **RIFF/POWER** (rock/metal/punk) — *built today* ✅ (this session) — ~18%
3. **SPARSE-TRAP** (hiphop/trap/drill) — 808 + hats, sparse harmony — ~7%
4. **LOOP/SUSTAIN** (EDM/house/techno) — supersaw + sidechain — ~5%
5. **STRUM** (country/folk/singer-songwriter) — boom-chuck + open voicings — ~10%
6. **KEYS/JAZZ** (jazz/neo-soul/gospel) — rootless 7ths — ~3% — *cut this first if needed*

Gemini's "4" collapses EDM into pop (defensible: both are grid/pad idioms) and drops the clave and jazz engines. That's the lean product MVP. The 6-engine target is the fuller "most people" system.

---

## 3. Voicings: one shared library + three idiom-locked additions

Unanimous across the council: **do NOT let every engine pick every chord.** One shared voicing library, plus a few idiom-specific vocabularies.

**Shared library (used by ≥3 engines):**
- Close triads (all inversions), sus2/sus4, add9, spread/open triad (root–5–10), octave doublings
- A voice-leading utility that minimizes top-voice motion between chords

**Idiom-locked additions:**
- **RIFF:** power dyad (root+5, +octave), single-note scalar/pentatonic/Phrygian riffs. **HARD RULE (all 3 models): never put a 3rd on a distorted timbre** — third + distortion = intermodulation mud. This is the single most important voicing rule in the build. *(Already implemented in `rock_metal_engine.py`.)*
- **KEYS/JAZZ:** rootless drop-2 7ths/9ths, shell voicings (3rd+7th), quartal stacks. Needs its own 7th-chord progression pool → it's a harmonic layer, not just a voicing swap.
- **STRUM:** 5–6 note guitar-shaped voicings with doubled open root/fifth (not pianistic close triads).

So: **~1 shared library + 3 idiom voicing sets.** Not dozens.

---

## 4. Timbre / sound sets: 5–9 needed; 4 are timbre-critical

Council votes: Gemini **5**, GPT **9**, Opus **8**. Convergent middle: **~8 sound sets** for the full system, but only **4 are genuinely timbre-critical** — the rest tolerate generic substitutes.

| Sound set | Timbre-critical? | Free SF2 available now? |
|---|---|---|
| Distorted guitar (+palm-mute) | **CRITICAL** (rock/metal) | ⚠️ GM Prog 30/31 exists but weak — needs DSP (see §5) |
| 808 sub + trap kit | **CRITICAL** (hiphop) | ✅ HS-TR-808 (MIT); melodic 808 = build a sine patch |
| Supersaw/synth | **CRITICAL** (EDM) | ✅ Unison.SF2 (CC0, already in use) |
| Acoustic guitar | **CRITICAL** (country/folk) | ✅ FreePats SteelString (GPLv3+ exc.) |
| Acoustic rock kit | tolerant | ✅ MuldjordKit (CC BY 4.0) / GM Power Kit |
| Piano / Rhodes / EP | tolerant | ✅ GM Prog 5 (no dedicated CC Rhodes found — gap) |
| Hammond organ | tolerant | ✅ FreePats Rock/Drawbar Organ (CC0) |
| Strings / orchestral | tolerant | ✅ GM |

**Pop, r&b, latin, jazz are timbre-TOLERANT** — piano/EP/synth read as "correct" without a bespoke patch. All soundfont URLs are HTTP-verified and license-checked in `soundfont_research.md`. **License flag:** the widely-recommended Arachno soundfont is **non-commercial only** — avoid if GrooveGen might ever ship.

---

## 5. Feasibility NOW (symbolic + FluidSynth + free SF2 on Colab T4)

Strong council convergence here:

**✅ Well-served today:** pop, EDM, trap/hiphop, r&b, latin, country/folk (with the acoustic SF2), rock *rhythm/structure*.
- Best ROI in the whole list (Opus + Gemini): **trap** — an 808 is just a sine + pitch glide, and hats are one-shots. Cheap, convincing, and a genuinely *new structural archetype* (sparse, half-time).
- **EDM** is highly feasible — quantized grid + supersaw SF2 is genuinely good.

**⚠️ "OK but proxy" — METAL TIMBRE:** All three models independently said the same thing bluntly: **a raw SF2 distorted guitar is NOT good enough.** Sampled distortion has baked-in gain staging, so power-chord dyads sound like two stacked samples, not one saturated signal — no palm-mute articulation, no chug. Gemini: "sounds like 1990s MS-DOS games." Opus: "you get an 80s hard-rock keyboard patch, not Thunderstruck."
- **The fix is not a better SF2 — it's post-FluidSynth DSP:** render a clean/overdriven patch, then `tanh` soft-clip → cabinet impulse-response (IR) convolution → tight noise gate (numpy/scipy or the `pedalboard` library). Opus estimate: ~150 lines → ~80% credible. This is an *articulation/rendering* project, separable from the writing engine (which is done).

**🚫 Out of scope for this paper (all 3 agree):** jazz (needs swing microtiming + human comp feel), classical, and anything vocal-led. **Do NOT reach for neural audio (MusicGen/JASCO)** — it destroys per-bar latency and controllability, which *is* your contribution.

---

## 6. The unanimous pushback (and I agree with it)

**All three council members independently flagged that building rock/metal FIRST is the wrong priority** — and this directly answers your "evaluate if we can make it work now":

- **Gemini (strongest):** a cheap GM distorted guitar creates a *timbral uncanny valley* in a **cognitive-science study** — participants' arousal would be driven by "cringe and distraction," not your PD controller's intended arc. That contaminates the very measurement the study exists to make.
- **Opus:** rock is the highest-effort, highest-risk pack — the only one that forces you out of symbolic+SF2 into a DSP chain. If the guitar sounds fake, reviewers hear "synth-pop cover with fuzz" and doubt the whole genre-agnostic claim. Do it **third**, after the waveshaper+IR chain is built and validated in isolation.
- **GPT:** build a deliberately *limited* rock proxy for architectural contrast, but don't spend thesis time chasing convincing SF2 metal — "that's an articulation project, not evidence for the controller method."

**What we built today is exactly the right half:** the RIFF/POWER *writing engine* (power chords, palm-mute grid, gallop, unison bass, tier-driven intensity) — see `groovegen_rock_metal_engine.mp4`. The *idiom* is now correct and auditable. What we deliberately did NOT do is pretend the GM timbre is study-ready.

---

## 7. Recommendation

### For the PAPER (system/method contribution, n≈5–8 pilot)
Ship **3 engines / 4 packs: pop-funk (have) + rock-riff + trap + EDM** → ~60% of the distribution, spanning the three control-relevant structural axes: dense-harmonic (pop), riff-driven (rock), sparse-percussive (trap), loop-sustain (EDM). For a pilot, **coverage is not the claim — controllability across idioms is.** The money figure: **per-bar tier-tracking error per engine.**
- Treat **metal timbre as a documented known limitation**, not a shipped weak version. Report the RIFF engine's *structural* control; note the DSP-timbre work as future work.

### For the PRODUCT ("usable by most people")
Build order (80/20, council consensus): **trap → EDM → rock-riff + DSP chain → country-strum → keys/jazz.**
- Trap and EDM are the 80/20: cheapest to build, genuinely convincing, and each adds a *new structural archetype* that strengthens the generalization claim more than rock does.

### Can we "make it work now"?
- **Writing engine for rock/metal: YES — done today.** ✅
- **Study-grade rock/metal *timbre*: NOT YET** — needs a ~150-line DSP chain (waveshaper + cabinet IR + gate) on Colab, then A/B validation before it's fit for participants.
- **Broad most-people coverage: YES, incrementally** — 6 engines + ~8 sound sets, almost all with confirmed free SF2s today. The only true blockers are (a) rock/metal timbre DSP and (b) two minor soundfont gaps (melodic 808 sub, dedicated Rhodes), both easily built.

---

## 8. Immediate next actions (proposed)
1. **Trap engine** (SPARSE-TRAP): 808 sine+glide sub, hat rolls, half-time kit — highest ROI, new archetype. *(Recommended next build.)*
2. **EDM engine** (LOOP/SUSTAIN): supersaw cell + four-on-floor + sidechain pump (you already have `polish_pump`).
3. **Rock timbre DSP chain** (`guitar_amp_dsp.py`): tanh soft-clip → cabinet IR → noise gate; A/B vs raw SF2; only then promote rock to study-eligible.
4. Fold all engines behind the single `make_song(profile, genre, salt)` entry point and into nb16 for the modern Colab timbre.

*Sources: council responses (`council_opus.md`, `council_gpt.md`, `council_gemini.md`); soundfont/idiom research with verified URLs (`soundfont_research.md`); genre distribution (`genre_distribution_sophia.txt`).*
