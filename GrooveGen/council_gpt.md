# Q1 — Writing-engine taxonomy

**Committed take: build six distinct writing engines; fewer collapses important idioms, while eight-plus is premature fragmentation.**

1. **Pulse-pop/electronic:** pop, dance-pop, EDM, much alternative; grid stabs/pads, ostinato arp, four-on-floor or backbeat.
2. **Guitar riff/backbeat:** rock, metal, punk, hard alternative; power-chord motion, palm-muted pedal tones, syncopated single-note riffs, fills at phrase boundaries.
3. **Acoustic songwriter:** country, folk, singer-songwriter, soft indie; strum/pick patterns, alternating bass, open-position voice leading.
4. **Beat-loop/808:** hiphop, trap, some contemporary R&B; sparse harmonic loops, kick–bass co-design, hats with subdivisions/rolls, swung or displaced percussion.
5. **Pocket harmony:** R&B, soul, funk, neo-soul, reggae; syncopated comping, bass-led groove, anticipations, richer voice leading.
6. **Clave/tumbao:** Latin pop, salsa-adjacent styles, reggaeton; clave-aware placement, montuno/tumbao logic, genre-specific percussion coordination.

Jazz/classical should not drive architecture for 1.4% of tags. Their phrase-level grammar and performance practice are not just presets.

# Q2 — Voicings

**Committed take: use one shared pitch/voice-leading library, but expose constrained vocabularies per engine rather than letting every engine choose every chord form.**

- **Pulse-pop/electronic:** triads, inversions, sus2/sus4, add9, octave doublings, spread/open triads.
- **Guitar riff/backbeat:** root–fifth power chords, octave riffs, single-note scalar/blues riffs, occasional sus/add9; parallel motion is intentional.
- **Acoustic songwriter:** open and spread triads, inversions/slash chords, sus2/sus4, add9, pedal/open-string approximations.
- **Beat-loop/808:** sparse triads, minor/major 7ths, shell voicings, single-note or octave bass; leave spectral space.
- **Pocket harmony:** 7ths/9ths, shells, drop-2, quartal fragments, chromatic approach voicings.
- **Clave/tumbao:** triads and 7ths in close/inverted forms, octave melody, montuno dyads/tenths.

Shared primitives: triads, inversions, shells, 7ths, sus/add9, octave/dyad, range and voice-leading constraints. Idiom-specific renderers: guitar power-chord/riff grammar, acoustic strum geometry, drop-2 pocket comping, montuno, and 808 bass behavior.

# Q3 — Timbre/soundfont layer

**Committed take: target nine curated sound sets, not a giant GM palette.** They are: acoustic drum kit; electronic/909 kit; trap kit plus long 808 bass; distorted guitar; clean electric guitar; acoustic guitar; piano/Rhodes/organ keys; synth set (pad, pluck, lead, supersaw, synth bass); and orchestral/strings.

Specific timbre is genuinely required for rock/metal (distorted guitar plus acoustic drums), country/folk (acoustic or clean guitar), trap (808 and trap hats), EDM (synths and electronic drums), and Latin (recognizable percussion). Pop and R&B tolerate substitutions within keys/synth/guitar families. A “sound set” must include velocity response, envelope, register, gain, and articulation policy—not merely an SF2 program number.

# Q4 — Feasibility now

**Committed take: symbolic plus FluidSynth is strong for pop, EDM, trap, and simple Latin; acceptable for R&B, country/folk, reggae, and mainstream rock; weak for metal, jazz, and classical.**

Trap 808s are feasible if samples are good and kick/808 tuning, glide approximation, envelopes, and clipping are controlled. EDM is highly feasible because quantized drums, synth layers, automation approximations, and ostinati suit MIDI. Rock can pass as a stylized instrumental backing track. Distorted-guitar SF2 is **not good enough for convincing metal**: palm muting, pick attack, legato, bends, string choice, amp nonlinearities, and humanized double-tracking interact. It is sufficient only to demonstrate genre-conditioned control, clearly labeled as a proxy.

Jazz requires interactive timing, articulation, and longer-form harmonic/melodic agency; classical requires instrumentation-specific phrasing and dynamics. Neural audio is not inherently required for either, but this engine cannot credibly cover them now. Vocal-dependent rap, singer-songwriter authenticity, and vocal pop should be explicitly out of scope; neural audio does not solve study controllability cleanly.

# Q5 — Paper versus product

**Committed take: the paper needs two contrasting, reliable engines—not broad genre coverage.** Ship pulse-pop/electronic plus guitar-riff/backbeat, validate that the same per-bar L1–L5 interface yields monotonic, measurable changes in onset density, loudness, spectral balance, and percussion activity, and describe other packs as future work. For an n=5–8 pilot, claim controlled instrumental exemplars, not “any genre” or population coverage.

Product build order: (1) harden pulse-pop/electronic, (2) guitar riff/backbeat, (3) beat-loop/808, (4) acoustic songwriter, (5) pocket harmony, (6) clave/tumbao. Those six address nearly all named high-frequency families; invest next in routing/classification and asset quality, not more engines.

**Where I'd push back:** building a full rock/metal pack now is the wrong priority if it delays closed-loop validation. Build a deliberately limited rock proxy because it is the strongest architectural contrast, but do not spend thesis time chasing convincing SF2 metal. That is an articulation/rendering project, not evidence for the controller method.
