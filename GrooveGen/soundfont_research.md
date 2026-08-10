# SoundFont & Genre-Idiom Research
For a symbolic music-generation pipeline: MIDI → FluidSynth → SoundFont (.sf2), Google Colab, Python 3.12

Compiled 2026-08-04. Every URL below was checked for HTTP resolution (status code + content-length) via direct header requests unless noted otherwise. Licenses are stated as found on the original/authoritative page — not as claimed by secondary mirrors.

**Legend:** ✅ CONFIRMED FREE (clear open license, safe for any use incl. commercial) · ⚠️ RESTRICTED (free but with use restrictions — e.g. non-commercial only, attribution required) · 🚫 UNCLEAR/UNLICENSED (no stated license found — do not rely on for a shipped product without further clearance)

---

## PART A — SoundFont (.sf2) Inventory

### 1. Distorted / Overdriven Electric Guitar — **PRIORITY**

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **FluidR3_GM.sf2** (GM Program 30 "Overdriven Guitar", 31 "Distortion Guitar") | [`raw.githubusercontent.com/urish/cinto/.../FluidR3 GM.sf2`](https://raw.githubusercontent.com/urish/cinto/master/media/FluidR3%20GM.sf2) | ✅ **MIT** | ~148 MB (148,358,590 bytes) | HTTP 200 |
| FluidR3_GM alt. mirror (bundled with GS) | [`archive.org/download/fluidr3-gm-gs/FluidR3_GM_GS.sf2`](https://archive.org/download/fluidr3-gm-gs/FluidR3_GM_GS.sf2) | ✅ MIT | ~151 MB (151,001,312 bytes) | HTTP 200 (redirects to `ia803204.us.archive.org`) |
| **GeneralUser GS** (also has Overdriven/Distortion Guitar) | [`raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/GeneralUser.sf2`](https://raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/GeneralUser.sf2) | ✅ **GeneralUser GS License v2.0** (permissive, free for any use, no attribution required) — see [license text](https://scancode-licensedb.aboutcode.org/generaluser-gs-2.0.html) and [homepage](https://www.schristiancollins.com/generaluser) | ~30 MB (31,281,186 bytes) | HTTP 200 |
| Archive.org "found online" distortion patches | [`Guitar Distortion (1,274KB).sf2`](https://archive.org/download/soundfont-collection-2/Collections2/Guitar%20Distortion%20%281%2C274KB%29.sf2), [`Guitar DiStOrTiOnGuItAr11.sf2`](https://archive.org/download/soundfont-collection-2/Collections2/Guitar%20DiStOrTiOnGuItAr11.sf2) | 🚫 **UNCLEAR** — [item page](https://archive.org/details/soundfont-collection-2) states no license, uploader "pangrat," unknown provenance | 1.3 MB / 0.77 MB | HTTP 200 individually, but a third file in the same set (`Fender Distorted`) returned HTTP 500 — collection is unreliable |

**Recommendation:** Use **FluidR3_GM.sf2** as the primary distortion/overdrive guitar source (MIT, well-tested, includes both Overdriven and Distortion Guitar GM programs) with **GeneralUser GS** as a lightweight (~30 MB) fallback. Patches are single-sample GM style, not multi-velocity riff-specific — fine for prototyping but won't have amp-sim realism.

### 2. Clean Electric Guitar
Same two GM banks cover this via **GM Program 28 "Clean Electric Guitar"**:
- FluidR3_GM.sf2 — ✅ MIT — [same URL as above](https://raw.githubusercontent.com/urish/cinto/master/media/FluidR3%20GM.sf2)
- GeneralUser.sf2 — ✅ GeneralUser GS License — [same URL as above](https://raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/GeneralUser.sf2)

A dedicated repo, [`gdm-2112/electric-guitar-soundfonts`](https://github.com/gdm-2112/electric-guitar-soundfonts) (FlameStudios samples, GPL per its [license file](https://github.com/gdm-2112/electric-guitar-soundfonts/blob/main/SF2/FlameStudios/license.txt)), was found but only ships `.7z`/`.sf3` archives, not a bare `.sf2` — **not usable as a direct download URL**, flagged out.

### 3. Acoustic Guitar (Steel-String, Country/Folk)

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **FreePats FSS-SteelStringGuitar** (full) | [`freepats.zenvoid.org/.../FSS-SteelStringGuitar-SF2-20200521.tar.xz`](https://freepats.zenvoid.org/Guitar/FSS-SteelStringGuitar/FSS-SteelStringGuitar-SF2-20200521.tar.xz) | ✅ **GNU GPL v3+ with FreePats sample-redistribution exception** — see [FreePats steel guitar page](https://freepats.zenvoid.org/Guitar/steel-acoustic-guitar.html) (permission from Gary Campion/FlameStudios) | ~13 MB (12,965,944 bytes) | HTTP 200 |
| FreePats FSS-SteelStringGuitar (small) | [`...-small-SF2-20200521.tar.xz`](https://freepats.zenvoid.org/Guitar/FSS-SteelStringGuitar/FSS-SteelStringGuitar-small-SF2-20200521.tar.xz) | ✅ same license | ~2.7 MB (2,749,164 bytes) | HTTP 200 |
| GM fallback: Program 26 "Steel-String Guitar" | FluidR3_GM.sf2 / GeneralUser.sf2 (same URLs as §1) | ✅ MIT / GeneralUser GS License | — | HTTP 200 |

**Note:** FreePats files are `.tar.xz` archives, not bare `.sf2` — need extraction after download (trivial with `tarfile` in Python). Quality is good: purpose-built from the Seagull Steel String Acoustic Guitar GIG sample set.

### 4. Rhodes / Electric Piano (R&B/Soul)

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| GM Programs 5/6 "Electric Piano 1/2" | FluidR3_GM.sf2 / GeneralUser.sf2 (§1 URLs) | ✅ MIT / GeneralUser GS License | — | HTTP 200 |
| Archive.org Rhodes collection (`JD_Crystal_Rhodes.sf2`, `fender_rhodes.sf2`, `jRhodes3.sf2`) | [`archive.org/download/soundfonts_202310/Rhodes/`](https://archive.org/download/soundfonts_202310/Rhodes/) | 🚫 **UNCLEAR** — no stated license, uploader-sourced collection | jRhodes3.sf2 ≈ 75.3 MB | Individual file fetch returned HTTP 500 on retry — unreliable, not recommended |

**Gap:** No dedicated CC0/CC-BY standalone Rhodes .sf2 was found with a clearly stated license. **Recommendation: default to GM Program 5 (Electric Piano 1) in FluidR3_GM.sf2 or GeneralUser.sf2** — both license-clean and already verified.

### 5. Trap / Hip-Hop Drum Kit + 808 Sub-Bass

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **HS-TR-808-Drums.sf2** (TR-808 drum kit, not melodic 808 bass) | [`raw.githubusercontent.com/vigliensoni/soundfonts/master/hs_tr808/HS-TR-808-Drums.sf2`](https://raw.githubusercontent.com/vigliensoni/soundfonts/master/hs_tr808/HS-TR-808-Drums.sf2) | ✅ **MIT** — see [repo LICENSE](https://raw.githubusercontent.com/vigliensoni/soundfonts/master/LICENSE) (Copyright 2019 Gabriel Vigliensoni) | ~400 KB (407,218 bytes) | HTTP 200 |
| **909_drum_sf.sf2** (electronic kit, genre-adjacent alternative) | [`raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/DRUMS/909_drum_sf.sf2`](https://raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/DRUMS/909_drum_sf.sf2) | ⚠️ **CC Attribution 3.0 Unported** (attribution required) per [bratpeki README](https://github.com/bratpeki/soundfonts) | ~1.5 MB (1,589,700 bytes) | HTTP 200 |
| Archive.org `General808.sf2` | `archive.org/download/soundfont-collection-2/Collections2/General808.sf2` | 🚫 UNCLEAR — same unlicensed "pangrat" collection as §1 | ~70 KB | Not independently re-verified this session; treat as unreliable |
| 808/909 sample **datasets** (loops, not SF2, but CC-BY 4.0 and genuinely open) | [WaivOps-EDM-TR8 (808)](https://github.com/patchbanks/WaivOps-EDM-TR8), [WaivOps-EDM-TR9 (909)](https://github.com/patchbanks/WaivOps-EDM-TR9) — mentioned on [Gearspace](https://gearspace.com/board/electronic-music-instruments-and-electronic-music-production/1433181-free-open-source-tr-909-tr-808-audio-datasets.html) | ✅ CC BY 4.0 | — | Not SF2 format — would require building a soundfont from these samples |

**Gap confirmed:** No dedicated **melodic/tunable 808 sub-bass** .sf2 with a clearly stated open license was found. **Recommendation:** either (a) build a minimal sub-bass SF2 from a sine/saw wave (a few minutes of work in Polyphone), or (b) use **GM Program 39 "Synth Bass 1"** from FluidR3_GM/GeneralUser as a stand-in until a purpose-built patch is created.

### 6. Acoustic Drum Kit (Rock)

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **MuldjordKit** (DrumGizmo/FreePats acoustic kit, SF2 build) | [`github.com/freepats/muldjordkit/releases/download/2020-10-18/MuldjordKit-SF2-20201018.7z`](https://github.com/freepats/muldjordkit/releases/download/2020-10-18/MuldjordKit-SF2-20201018.7z) | ✅ **CC BY 4.0** — per [FreePats acoustic drum kit page](https://freepats.zenvoid.org/Percussion/acoustic-drum-kit.html) and [CC BY 4.0 deed](http://creativecommons.org/licenses/by/4.0/) | ~53 MB (54,877,940 bytes) | HTTP 200 (redirects through `release-assets.githubusercontent.com`) |
| GM fallback: "Power Kit" (Program 17) — rock-voiced GM drum kit | FluidR3_GM.sf2 / GeneralUser.sf2 (§1 URLs) | ✅ MIT / GeneralUser GS License — Power Kit explicitly "designed for rock and heavy music styles" per [GeneralUser GS drum kit docs](https://deepwiki.com/mrbumpy409/GeneralUser-GS/3.2-drum-kits) | — | HTTP 200 |
| `crabacus/the-open-source-drumkit` | [github.com/crabacus/the-open-source-drumkit](https://github.com/crabacus/the-open-source-drumkit) | ✅ Public Domain per [FLOSS drum kit list](https://collab.0x20.eu/s/floss-drum-kits), no license file in repo itself | — | Repo contains only raw WAV samples per its [README](https://raw.githubusercontent.com/crabacus/the-open-source-drumkit/master/README.md) — **not an SF2**, not directly usable |
| `WeedsGM3.sf2` | [`raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/WeedsGM3.sf2`](https://raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/WeedsGM3.sf2) | ⚠️ **Freeware, not clearly CC0** — original author released with informal "some rights reserved" per [Doomworld thread](https://www.doomworld.com/forum/topic/51104-weeds-general-midi-soundfont-v30/) | ~54.9 MB (54,894,076 bytes per GitHub tree) | Not independently HTTP-verified this session |

**Recommendation:** Use **MuldjordKit** (CC BY 4.0, purpose-built acoustic kit, requires attribution) as the primary rock drum source, or fall back to the **Power Kit** inside GeneralUser GS / FluidR3_GM (no extraction needed, already GM Program 17-mapped).

### 7. Synth Lead / Supersaw (alternatives to Unison.SF2)

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **Unison.SF2** (already in use) | [`raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/Unison.SF2`](https://raw.githubusercontent.com/bratpeki/soundfonts/main/SF2/GM/Unison.SF2) | ✅ **Public Domain / CC0 1.0** — per [Polyphone soundfont page](https://www.polyphone.io/en/soundfonts/instrument-sets/60-unison) (author Peter Jevnisek) and bratpeki README | ~29 MB (29,258,148 bytes) | HTTP 200 |
| GM fallback: Programs 81/82 "Lead 1 (square)" / "Lead 2 (sawtooth)" | FluidR3_GM.sf2 / GeneralUser.sf2 (§1 URLs) | ✅ MIT / GeneralUser GS License | — | HTTP 200 |
| **Arachno Soundfont** (widely praised synth leads) | [`arachnosoft.com/main/soundfont.php`](https://www.arachnosoft.com/main/soundfont.php) (official); mirror at [`github.com/rwtnb/Drumsthesia`](https://github.com/rwtnb/Drumsthesia/blob/main/Arachno%20SoundFont%20-%20Version%201.0.sf2) is a **Git-LFS pointer, not the real file** (only 134 bytes) | ⚠️ **RESTRICTED — personal/non-commercial use only.** Author states explicitly: *"this bank is primarily distributed for private, non-commercial purposes only... If you want to use it for commercial purposes, please obtain a written consent"* — [official Arachno page](https://www.arachnosoft.com/main/soundfont.php?documentation) — also listed as "personal use, don't share with more restrictions" on [Polyphone](https://www.polyphone.io/o/en/files/27-instrument-sets/255-arachno-soundfont) | — | Do **not** use for any product with commercial distribution |
| Concon Soundfont | [Polyphone listing](https://www.polyphone.io/en/soundfonts/instrument-sets/866-concon-soundfont) | ⚠️ RESTRICTED — "give credit, don't share with more restrictions" (CC BY-NC-ND-like) | — | Not independently verified |

**Recommendation:** Stick with **Unison.SF2** (CC0, already adopted) as primary; use GM Programs 81/82 in FluidR3_GM/GeneralUser as secondary supersaw-adjacent textures. **Do not use Arachno** unless the project stays strictly non-commercial — flagged as restricted.

### 8. Organ (Hammond, Soul/Gospel)

| Option | Direct URL | License | Size | Verified |
|---|---|---|---|---|
| **FreePats Drawbar Organ Emulation** (clean Hammond) | [`freepats.zenvoid.org/Organ/DrawbarOrganEmulation/DrawbarOrganEmulation-SF2-20190712.tar.xz`](https://freepats.zenvoid.org/Organ/DrawbarOrganEmulation/DrawbarOrganEmulation-SF2-20190712.tar.xz) | ✅ **CC0 1.0 Universal (public domain)** — per [FreePats electric organ page](https://freepats.zenvoid.org/Organ/electric-organ.html) | ~6 MB (6,037,780 bytes) | HTTP 200 |
| **FreePats Rock Organ Emulation** (driven/distorted Hammond — great for rock/soul) | [`freepats.zenvoid.org/Organ/RockOrganEmulation/RockOrganEmulation-SF2-20190715.tar.xz`](https://freepats.zenvoid.org/Organ/RockOrganEmulation/RockOrganEmulation-SF2-20190715.tar.xz) | ✅ CC0 1.0 | ~12.5 MB (12,549,588 bytes) | HTTP 200 |
| FreePats Percussive Organ Emulation | `freepats.zenvoid.org/Organ/PercussiveOrganEmulation/PercussiveOrganEmulation-SF2-20190715.tar.xz` | ✅ CC0 1.0 (same page) | — | Path confirmed in page HTML, not individually re-verified |
| GM fallback: Programs 17-19 (Drawbar/Percussive/Rock Organ) | FluidR3_GM.sf2 / GeneralUser.sf2 (§1 URLs) | ✅ MIT / GeneralUser GS License | — | HTTP 200 |

**Quality note:** FreePats organ samples are generated from the open-source `setBfree` Hammond B3 tonewheel emulator — physically modeled, excellent drawbar character. This is the **best free, fully-open Hammond option** available. Files are `.tar.xz`, need extraction.

---

### Part A Summary Table

| # | Instrument | Best Pick | License | Status |
|---|---|---|---|---|
| 1 | Distorted/OD guitar | FluidR3_GM.sf2 (Prog 30/31) | MIT | ✅ |
| 2 | Clean electric guitar | FluidR3_GM.sf2 (Prog 28) | MIT | ✅ |
| 3 | Acoustic guitar | FreePats FSS-SteelStringGuitar | GPLv3+ exception | ✅ |
| 4 | Rhodes/EP | FluidR3_GM.sf2 (Prog 5) | MIT | ✅ (gap: no dedicated CC Rhodes found) |
| 5 | Trap kit + 808 | HS-TR-808-Drums.sf2 + GM Synth Bass 1 stand-in | MIT | ✅ (gap: no dedicated melodic 808 bass found) |
| 6 | Acoustic rock kit | MuldjordKit | CC BY 4.0 | ✅ |
| 7 | Synth lead/supersaw | Unison.SF2 | Public Domain/CC0 | ✅ |
| 8 | Hammond organ | FreePats Rock/Drawbar Organ Emulation | CC0 1.0 | ✅ |

Every recommended pick above is a confirmed, freely-licensed, HTTP-verified direct download. Items marked 🚫/⚠️ throughout the detail sections are flagged and should be avoided or used only under their stated restriction.

---

## PART B — Symbolic Writing Idioms by Genre Family

### Rock / Metal
- **Accompaniment texture:** Rhythm guitar is the harmonic backbone — usually one or two distorted/overdriven guitar tracks doubling the same riff (sometimes octave- or power-chord-doubled for thickness), with bass guitar tracking the riff's root motion in unison or an octave below ([Guitar World, "Metal For Life"](https://www.guitarworld.com/lessons/metal-life-how-build-power-chord-variations-maximum-sonic-effect-part-2)).
- **Essential chord voicing:** Power chords — root + perfect 5th (+ optional octave), no 3rd, so the voicing is harmonically ambiguous (fits major or minor context) ([Music Theory of Power Chords](https://www.youtube.com/watch?v=dbhF2wnnT7M); [StudyRaid, "Construction of 5th Chords"](https://app.studyraid.com/en/read/6153/135660/construction-of-5th-chords)). Frequently played against an open low-string pedal tone for a "heavy" drone effect ([Guitar World](https://www.guitarworld.com/lessons/metal-life-how-build-power-chord-variations-maximum-sonic-effect-part-2)).
- **Rhythm/groove model:** Riffs are built from palm-muted 8th/16th-note patterns ("chugging") interrupted by open power-chord accents — palm muting is applied by resting the picking-hand's fleshy edge on the bridge saddles to damp sustain ([TrueFire, "How to Palm Mute"](https://learn.truefire.com/how-to-palm-mute-on-guitar); [Fundamental Changes, "Metal Rhythm Guitar"](https://www.fundamental-changes.com/metal-rhythm-guitar/)). "Galloping" rhythms (short-short-long, e.g. 16th-16th-8th) layered with palm muting are a genre-defining pattern, especially in thrash/power metal ([YouTube, "Galloping Palm Muted Riffs"](https://www.youtube.com/watch?v=KX6JWHYgwIE)).
- **Bass behavior:** Bass typically locks to the guitar riff's rhythm and root notes rather than providing independent melodic movement, reinforcing the low end under palm-muted chugs.
- **Harmonic language:** Riffs commonly draw on minor pentatonic, Phrygian, and harmonic-minor scale tones layered over power chords to create the dark, "heavy" tonal color typical of metal ([YouTube, "Write Mind Blowing Rock & Metal Riffs"](https://www.youtube.com/watch?v=VjGsotF8KKo)).

### Hip-Hop / Trap
- **Accompaniment texture:** Sparse, loop-based texture — a melodic hook (piano/pluck/synth) plus hi-hats and 808s carry most of the arrangement; there's little continuous harmonic "comping" compared to live-band genres.
- **Essential chord voicing:** Minimal — often just single melodic lines or simple triads/7ths in the hook, since the 808 sub-bass itself functions as the primary harmonic/bass element rather than a chord instrument.
- **Rhythm/groove model:** Hi-hats are the signature rhythmic device — a steady 8th-note base pattern is decorated with fast "rolls" using triplet or 16th/32nd-note subdivisions, usually placed at phrase ends as fills rather than sustained throughout ([Songen, "How to make trap hi-hat rolls"](https://songen.app/blog/trap-hi-hat-rolls/)). Kick and snare/clap sit in a half-time-feeling pattern under the busy hats.
- **Bass behavior:** The "808" is a tuned, pitched sub-bass drum sound (not a bass synth) whose note is typically triggered in sync with the kick and held as a long, distorted low-end tone that outlines the chord's root/bass note ([Production Music Live, "Trap Beat Guide: Bass"](https://www.productionmusiclive.com/blogs/news/trap-beat-guide-bass-essential-tips-for-making-808-patterns); [YouTube, "808 Beat Production"](https://www.youtube.com/watch?v=kzRiE3OQKTE)). Producers pitch-tune the 808 to the song's key so it functions melodically, not just rhythmically ([Electronic Mix Masters](https://www.youtube.com/watch?v=xzMKy5HdE5g)).
- **Low-end design:** Sub-bass content sits below ~80 Hz and is felt more than heard — a key mix consideration when generating 808 patches or choosing GM stand-ins ([Beat Kitchen, "Bass Design and the Low End"](https://beatkitchen.io/guides/electronic-music/04-bass-design/)).

### Country / Folk
- **Accompaniment texture:** Acoustic guitar is the rhythmic/harmonic backbone, often joined by pedal steel guitar and fiddle for melodic color, plus upright/electric bass and a steady drum kit ([Violet Recording, "How to Make Country Music"](https://violetrecording.com/how-to-make-country-music/)).
- **Essential chord voicing:** Simple, guitar-friendly open-position major triads built on the I–IV–V (with occasional ii/vi) — e.g., in C major: C, F, G ([PickupMusic, "Country Guitar Chords"](https://www.pickupmusic.com/blog/country-guitar-chords); [Acoustic Guitar / Chordly, "Country chord progressions"](https://chordly.com/tools/chord-progressions/country)). Nashville-number notation (1, 4, 5) is standard for communicating these progressions across keys.
- **Rhythm/groove model:** The "boom-chuck" strum pattern — alternating a picked bass note ("boom," on the root or 5th of the chord) with a strummed chord ("chuck") on the off-beat, borrowed from bluegrass rhythm guitar ([Acoustic Guitar, "The Country Boom-Chuck Rhythm"](https://acousticguitar.com/the-country-boom-chuck-rhythm/); [Good Guitarist, "Country Guitar Strumming Patterns"](https://goodguitarist.com/country-guitar-strumming-patterns/)).
- **Bass behavior:** Bass often doubles the guitar's "boom" bass notes (root, and alternating to the 5th on chord changes), producing a walking, alternating-bass feel under the strum ("Boom Chuck This!", [YouTube](https://www.youtube.com/watch?v=gYVvuoSciMM)).
- **Tempo/feel:** Typical tempos run 80–140 BPM with a straight or light shuffle feel; pedal steel commonly adds sustained bends/slides over the chord changes for the genre's characteristic "twang" ([Premier Guitar, "Bending Steel"](https://www.premierguitar.com/lessons/country/pedal-steel-guitar-bends-lesson); [Violet Recording](https://violetrecording.com/how-to-make-country-music/)).

### EDM / Electronic
- **Accompaniment texture:** Built around a four-on-the-floor kick, layered synth pads/plucks, and a prominent supersaw or pluck lead in the "drop" section; arrangement is phrase-based in 8/16/32-bar blocks (intro → breakdown → buildup → drop) ([EDM Ghost Production, "Electronic Song Structure Explained"](https://edm-ghost-production.com/dj-knowledge-base/electronic-song-structure); [Redstar Media, "Structuring Your EDM Tracks"](https://redstar.media/guides/production/structuring-your-edm-tracks)).
- **Essential chord voicing:** Supersaw chords are built from stacked, detuned sawtooth voices (unison/multi-oscillator detuning) voiced mostly in root-and-fifth octave doublings for maximum harmonic "meat" with minimal dissonance, then widened with stereo detuning ([Reddit r/edmproduction, "Chord voicing in supersaws"](https://www.reddit.com/r/edmproduction/comments/7egayj/chord_voicing_in_supersaws/); [Reddit, "Super Saws"](https://www.reddit.com/r/edmproduction/comments/ht5wuw/super_saws/)).
- **Rhythm/groove model:** Strict 4/4 with a kick on every beat ("four-on-the-floor"); the drop is the highest-energy arrival point where the full beat, bassline, and lead hook lock in together ([MusicProductionWiki, "How To Make EDM"](https://musicproductionwiki.com/articles/how-to-make-edm); [EDM Ghost Production](https://edm-ghost-production.com/dj-knowledge-base/electronic-song-structure)).
- **Bass behavior:** Bassline is rhythmically locked to the kick and typically sidechain-compressed against it — the bass (or the whole mix) ducks in volume every time the kick hits, creating the genre's signature "pumping" feel ([Reddit r/edmproduction, "How do you side chain..."](https://www.reddit.com/r/edmproduction/comments/179pkp/how_do_you_side_chain_a_pumping_beat_to_a_four_on/); [The Pro Audio Files, "Mix Bass and Kick with Multiband Sidechain"](https://theproaudiofiles.com/video/how-to-mix-bass-and-kick-with-multiband-sidechain-compression/)).
- **Arrangement dynamics:** Buildups progressively add tension (risers, filtered hats/percussion) before releasing into the drop, then a breakdown strips the arrangement back down ([YouTube, "How To Structure An EDM Track"](https://www.youtube.com/watch?v=EBVH4YlI3X4)).

### R&B / Soul
- **Accompaniment texture:** Rhodes/electric piano and/or clean electric guitar comp extended chords over a syncopated rhythm section (drums + bass); vocal-forward with harmonically rich backing rather than riff-driven.
- **Essential chord voicing:** Extended jazz-derived harmony — maj7, min7, dominant 7, and 9th/11th/13th extensions are standard, often connected via a soul-flavored ii–V–I (e.g., Dm7–G7–Cmaj7) ([MusoKit, "R&B Chord Progressions"](https://musokit.com/rnb-chord-progressions)). Neo-soul voicings favor minor 9th chords and slash chords (e.g., Cmaj7/E) that shift the bass note under a static chord quality ([ChordGen, "R&B Chord Progressions"](https://www.chordgen.org/chords/rnb); [Hear and Play, "Neo Soul Chords"](https://hearandplay.com/main/neo-soul-chords-minor-chords/)).
- **Rhythm/groove model:** Chords are voiced wide and "lush," with rhythmic comping that emphasizes syncopated attacks (pushed/delayed chord stabs) rather than straight downbeats, characteristic of the neo-soul/R&B pocket.
- **Bass behavior:** Basslines are syncopated and melodically active rather than root-only — the Motown/James Jamerson model layers a root–5th–octave skeleton with chromatic approach and connecting tones between chord changes for a "singing" bass line ([Online Bass Courses, "RnB, Soul & Motown Style Basslines"](https://onlinebasscourses.com/bass-line-creation/rnb-soul-motown-style-basslines/); [YouTube, "The Motown Bass Line Formula"](https://www.youtube.com/watch?v=9acSf-haRy0)).
- **Groove reference:** A classic Motown pattern emphasizes quarter-note pulses locked with the kick/snare, with small rhythmic/melodic variation introduced near the end of each bar to keep the line from feeling static ([Bonedo, "Soul Bass Patterns"](https://www.bonedo.de/artikel/soul-bass-patterns-die-fast-immer-passen/); [Bonedo, "Motown Bass-Workshop"](https://www.bonedo.de/artikel/die-tricks-der-studiobassisten-13-motown-bass-workshop/)).

---

## Appendix: General MIDI Program Reference (for fallback patch selection)
Per [Wikipedia, "General MIDI"](https://en.wikipedia.org/wiki/General_MIDI) and [midiprog.com](https://midiprog.com/program-numbers/):

| Program # | Instrument |
|---|---|
| 5–6 | Electric Piano 1/2 (Rhodes/Wurlitzer/FM) |
| 17 | Drawbar Organ |
| 18 | Percussive Organ |
| 19 | Rock Organ |
| 20 | Church Organ |
| 25 | Nylon Guitar |
| 26 | Steel-String Guitar |
| 27 | Jazz Guitar |
| 28 | Clean Electric Guitar |
| 29 | Muted Electric Guitar |
| **30** | **Overdriven Guitar** |
| **31** | **Distortion Guitar** |
| 32 | Guitar Harmonics |
| 33–40 | Bass family (39/40 = Synth Bass 1/2 — usable 808 stand-in) |
| 81–88 | Synth Leads (81 square, 82 sawtooth — supersaw-adjacent) |

Drum kit program numbers for GM/GS banks: Program 1 (Standard), 9 (Room), **17 (Power — recommended for rock)**, 25 (Electric), 26 (Rap/TR-808), 33 (Jazz), 41 (Brush) — per [pgmusic.com General MIDI reference](https://www.pgmusic.com/tutorial_gm.htm) and [GeneralUser GS drum kit docs](https://deepwiki.com/mrbumpy409/GeneralUser-GS/3.2-drum-kits).

---

## Key Gaps & Recommendations for the Build
1. **No dedicated melodic 808 sub-bass SF2 with clear licensing was found.** Build a simple sine/saw sub-bass patch in Polyphone, or use GM Program 39 "Synth Bass 1" as an interim stand-in.
2. **No dedicated CC-licensed Rhodes SF2 was found.** Use GM Program 5 "Electric Piano 1" from FluidR3_GM/GeneralUser.
3. **Arachno Soundfont is restricted to non-commercial personal use** — do not bundle it if the project may ever be distributed commercially.
4. **FreePats and DrumGizmo/MuldjordKit assets are distributed as `.tar.xz`/`.7z` archives**, not bare `.sf2` — build an extraction step into the download pipeline.
5. Any archive.org item uploaded by an individual user with no stated rights (e.g., the "soundfont-collection-2" set) should be treated as **not safely redistributable** and avoided in a shipped product, even though the files themselves resolve fine over HTTP.
