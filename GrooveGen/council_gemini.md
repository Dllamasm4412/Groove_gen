# Q1: Writing-engine taxonomy
**You need exactly 4 distinct symbolic writing engines to cover ~75% of your dataset robustly.**
1. **Four-Chord Synth (Pop/EDM/R&B - ~40%):** Triad/pad stabs, arpeggios, 4-on-the-floor or syncopated 16th rhythms.
2. **Heavy Riff (Rock/Metal - 18%):** Power-chord blocks, fast chugging 8ths/16ths, bass mirroring the guitar exactly, acoustic backbeat.
3. **Trap/Boom-Bap (Hip-hop - 7%):** Sparse melodic loops, half-time feel, rapid hi-hat subdivisions (32nds/triplets), 808 glide bass.
4. **Strum & Pick (Country/Folk - 10%):** Alternating bass (root-fifth), Travis-picking arpeggiations, sustained chords. 

# Q2: Voicings
**A shared library handles your generic triads, but distinct genres live and die on idiom-specific voicings.**
*   **Shared Library:** Basic root-position triads, open spread triads (root-fifth-tenth), simple diatonic octaves.
*   **Rock/Metal Engine (Idiom-specific):** Strictly power chords (root-fifth or root-fifth-octave) and single-note pedal points. 
*   **Pop/EDM Engine (Idiom-specific):** Sus2, sus4, and add9 chords (e.g., C-D-E-G) to create ambiguity and space. 
*   **R&B/Soul Engine (Idiom-specific):** Drop-2 7ths and 9ths, quartal voicings (stacked fourths).
*   **Country/Folk Engine (Idiom-specific):** Standard "cowboy" chord voicings emphasizing open strings, utilizing a strict root/fifth alternating bass.

# Q3: Timbre/soundfont layer
**You need 5 distinct sound sets, as timbre defines genre almost as much as the notes.**
1.  **Synth-heavy:** Supersaw/pads, sub-bass, 909 kit (Pop/EDM).
2.  **Overdriven:** Distorted guitar, picked rock bass, aggressive acoustic kit (Rock/Metal).
3.  **Urban:** Electric piano (Rhodes)/bells, 808 bass, trap kit with sharp snare/hats (Hip-hop).
4.  **Acoustic:** Acoustic guitar, upright/clean bass, brush or light acoustic kit (Country/Folk).
5.  **Soul:** Warm keys, fingerstyle electric bass, dry 70s drum kit (R&B).

*Genuinely require specific timbre:* Rock (distortion is non-negotiable), Hip-hop (808s/trap hats are definitional), EDM (supersaws). *Tolerate generic:* Pop and Folk can survive on generic piano/bass/drums if necessary.

# Q4: Feasibility NOW (symbolic + FluidSynth + free SF2 on a Colab T4)
**Synthetic genres are perfectly feasible today; acoustic/expressive genres must be declared out of scope.**
*   **Well-served (Feasible):** Pop, EDM, Trap/Hip-hop. Soundfonts excel at playing one-shot drum samples (909s, 808s) and static synth waveforms.
*   **"OK":** R&B and basic Folk. You can get away with a decent Rhodes or Piano SF2, though it will lack dynamic groove.
*   **OUT OF SCOPE (Need neural/advanced DSP):** Rock/Metal and Jazz. SF2 distorted guitars are notoriously awful—they sound like 1990s MS-DOS games. You lack DSP amp simulation, palm-mute articulation, and sympathetic string resonance. Jazz is similarly ruined by quantized MIDI and static velocity mapping.

# Q5: Recommendation for the PAPER vs the PRODUCT
**For the system paper, restrict coverage to Pop/EDM and Trap/Hip-hop; save the 80/20 expansion for the product.**
*   **Paper (Method/Pilot):** Your contribution is the per-bar closed-loop drum control. Covering Pop and Hip-hop proves the PD controller works across two wildly different rhythm and intensity paradigms (4-on-the-floor vs half-time). This is highly defensible and avoids participant distraction from bad MIDI acoustic instruments.
*   **Product Build Order:** Pop -> Hip-hop/Trap -> Country/Folk -> R&B -> Rock/Metal. The 80/20 is nailing Pop and Trap. Rock/Metal is last because it requires building an entirely new DSP layer (amp sims/pedals) to not sound comical.

# Where I'd push back on the researcher
**Building the Rock/Metal pack right now is a dangerous distraction that will harm your study.**
Because your generator relies on MIDI + FluidSynth, adding Rock/Metal will introduce a severe *timbral uncanny valley*. Your cognitive-science study measures arousal based on intensity tracking, but if participants hear an aggressively cheap, GM-style MIDI distorted guitar, their arousal response will be driven by *cringe and distraction*, not your PD controller's intended dynamic arc. Leave Rock/Metal out of the paper until you have the budget/compute to run a proper neural audio generator or a high-quality DSP amp-simulator pipeline. Focus on the synthetic genres where symbolic representation inherently thrives.