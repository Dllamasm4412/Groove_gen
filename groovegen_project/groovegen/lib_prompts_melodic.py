"""
lib_prompts_melodic.py
=======================

GrooveGen — Option 1 fix for percussion-dominated MusicGen beds.

BACKGROUND
----------
The original bed prompts (see ``lib_prompts`` / the legacy prompt table) explicitly
asked MusicGen for drums ("congas and timbales", "tight steady drums", "softly swung
steady drums", "very sparse soft drums", etc.). Measured on generated audio, the
percussive/harmonic RMS ratio of those beds was 0.54-0.88 — i.e. the baked-in drum
kit was roughly half to nearly all of the signal energy. GrooveGen's downstream
pipeline overlays its OWN synthetic, controllable drum layer (density is controlled
bar-by-bar by a closed-loop controller). Two independent drum layers running at
different phases produce incoherent, off-beat audio. Post-hoc HPSS stripping of the
baked drums was tried and rejected: it hollows out the melody (melody correlation
dropped to only 0.60-0.80 against the intended harmonic content).

THE FIX (Option 1)
-------------------
Rewrite the prompts so MusicGen generates MELODIC, LOW-PERCUSSION beds from birth —
there is no kit to strip out afterward. GrooveGen's own drum controller becomes the
only drum layer in the final mix.

CRITICAL CONSTRAINT: genre identity must keep living in the melodic/harmonic
content, not in a drum kit. A salsa bed with the drums removed must still sound
harmonically/rhythmically like salsa: piano montuno voicings, a 2-3 son clave
*phrasing* audible in the piano/bass comping pattern (not a clave drum sound), and
tumbao-style bass contour. The prompts are therefore NOT genericized to "ambient
pad" — genre-defining melodic/harmonic/comping vocabulary is deliberately kept, and
only drum-kit vocabulary (congas, timbales, "tight steady drums", "softly swung
drums", "sparse soft drums", ride/hi-hat/snare/kick language, etc.) is removed.

Two variants are provided per (genre, bpm) so the user can A/B them on real
MusicGen output and keep whichever measures lower percussive/harmonic ratio while
still sounding like the genre:

  * Variant A ("strict"):     "strictly no drums, no percussion"
  * Variant B ("light-hand"): "no drum kit, only light hand percussion if any"
    (permits a little non-kit hand percussion — e.g. a soft shaker or clave
    click as a texture, not a groove — in case a fully drum-free render loses
    too much of the genre's rhythmic identity; still forbids an actual kit).

Every single prompt, in both variants and all genres, still ends with the literal
string "instrumental, no vocals" — this is a hard, non-negotiable project rule
(no vocals anywhere in GrooveGen output), independent of the drum question.

Reference-artist style cues from the original prompts are preserved where they
describe genre/harmonic feel rather than drum programming (Marc Anthony-style
salsa piano/horns; Dua Lipa / Bruno Mars-style pop comping; D'Angelo / Anderson
.Paak-style r&b Rhodes and pocket bass).

Usage
-----
    from lib_prompts_melodic import PROMPTS_MELODIC_A, PROMPTS_MELODIC_B

    prompt = PROMPTS_MELODIC_A["latin/salsa"][128]
"""

# ---------------------------------------------------------------------------
# Variant A: strictly no drums, no percussion at all.
# ---------------------------------------------------------------------------
PROMPTS_MELODIC_A = {
    "latin/salsa": {
        128: (
            "Salsa dura piano montuno with bright, syncopated voicings phrased "
            "in a 2-3 son clave feel, walking tumbao-contour electric bass "
            "outlining the harmony, occasional bright horn stabs punctuating "
            "the montuno, Marc Anthony-style salsa energy, strictly no drums, "
            "no percussion, instrumental, no vocals"
        ),
        120: (
            "Salsa piano montuno with syncopated, clave-phrased comping in a "
            "2-3 son clave feel, tumbao-contour bass moving under the "
            "harmony, bright horn stabs for accents, Marc Anthony-style salsa "
            "warmth, strictly no drums, no percussion, instrumental, no "
            "vocals"
        ),
        112: (
            "Mid-tempo salsa piano montuno, syncopated 2-3 son clave-phrased "
            "voicings, smooth tumbao-contour bassline tracing the chord "
            "movement, sparing bright horn stabs, Marc Anthony-style salsa "
            "feel, strictly no drums, no percussion, instrumental, no vocals"
        ),
        105: (
            "Relaxed salsa piano montuno with a gentle 2-3 son clave phrasing "
            "in the comping, tumbao-contour bass gliding under the harmony, "
            "soft bright horn stabs, Marc Anthony-style salsa romance, "
            "strictly no drums, no percussion, instrumental, no vocals"
        ),
    },
    "pop": {
        104: (
            "Bright, syncopated plucky clavinet and synth comp, punchy "
            "finger-bass driving the groove through the harmony, energetic "
            "Dua Lipa / Bruno Mars-style pop feel, strictly no drums, no "
            "percussion, instrumental, no vocals"
        ),
        100: (
            "Syncopated plucky clavinet/synth comping with a bright pop "
            "energy, punchy finger-bass locking to the chord changes, "
            "Dua Lipa / Bruno Mars-style pop feel, strictly no drums, no "
            "percussion, instrumental, no vocals"
        ),
        95: (
            "Mid-tempo syncopated clavinet and synth comp, punchy finger-bass "
            "with a confident pop bounce, Dua Lipa / Bruno Mars-style pop "
            "energy, strictly no drums, no percussion, instrumental, no "
            "vocals"
        ),
        90: (
            "Laid-back but syncopated clavinet/synth comping, punchy "
            "finger-bass with warm pop groove, Dua Lipa / Bruno Mars-style "
            "feel, strictly no drums, no percussion, instrumental, no vocals"
        ),
    },
    "r&b/soul": {
        88: (
            "Laid-back electric piano (Rhodes) and clavinet comp with deep "
            "pocket finger-bass, warm smooth D'Angelo / Anderson .Paak-style "
            "r&b feel, strictly no drums, no percussion, instrumental, no "
            "vocals"
        ),
        84: (
            "Warm, laid-back Rhodes and clavinet comping, deep finger-bass "
            "sitting in the pocket, smooth D'Angelo / Anderson .Paak-style "
            "r&b groove, strictly no drums, no percussion, instrumental, no "
            "vocals"
        ),
        80: (
            "Slow, laid-back electric piano and clavinet comp, deep finger-"
            "bass with a smooth soulful pocket, D'Angelo / Anderson .Paak-"
            "style r&b warmth, strictly no drums, no percussion, "
            "instrumental, no vocals"
        ),
    },
    "calm": {
        80: (
            "Minimal, warm electric piano and pad textures, slow deep bass "
            "moving gently under the harmony, meditative and spacious, "
            "strictly no drums, no percussion, instrumental, no vocals"
        ),
        76: (
            "Minimal warm electric piano/pad, slow deep bass with a calm, "
            "meditative feel, strictly no drums, no percussion, "
            "instrumental, no vocals"
        ),
        72: (
            "Sparse, warm electric piano and soft pad, slow deep bass, "
            "meditative and unhurried atmosphere, strictly no drums, no "
            "percussion, instrumental, no vocals"
        ),
        70: (
            "Very minimal warm electric piano/pad textures, slow deep bass "
            "tones, meditative and still, strictly no drums, no percussion, "
            "instrumental, no vocals"
        ),
    },
}

# ---------------------------------------------------------------------------
# Variant B: no drum kit, only light hand percussion permitted (if any).
# ---------------------------------------------------------------------------
PROMPTS_MELODIC_B = {
    "latin/salsa": {
        128: (
            "Salsa dura piano montuno with bright, syncopated voicings phrased "
            "in a 2-3 son clave feel, walking tumbao-contour electric bass "
            "outlining the harmony, occasional bright horn stabs punctuating "
            "the montuno, Marc Anthony-style salsa energy, no drum kit, only "
            "light hand percussion if any, instrumental, no vocals"
        ),
        120: (
            "Salsa piano montuno with syncopated, clave-phrased comping in a "
            "2-3 son clave feel, tumbao-contour bass moving under the "
            "harmony, bright horn stabs for accents, Marc Anthony-style salsa "
            "warmth, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
        112: (
            "Mid-tempo salsa piano montuno, syncopated 2-3 son clave-phrased "
            "voicings, smooth tumbao-contour bassline tracing the chord "
            "movement, sparing bright horn stabs, Marc Anthony-style salsa "
            "feel, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
        105: (
            "Relaxed salsa piano montuno with a gentle 2-3 son clave phrasing "
            "in the comping, tumbao-contour bass gliding under the harmony, "
            "soft bright horn stabs, Marc Anthony-style salsa romance, no "
            "drum kit, only light hand percussion if any, instrumental, no "
            "vocals"
        ),
    },
    "pop": {
        104: (
            "Bright, syncopated plucky clavinet and synth comp, punchy "
            "finger-bass driving the groove through the harmony, energetic "
            "Dua Lipa / Bruno Mars-style pop feel, no drum kit, only light "
            "hand percussion if any, instrumental, no vocals"
        ),
        100: (
            "Syncopated plucky clavinet/synth comping with a bright pop "
            "energy, punchy finger-bass locking to the chord changes, "
            "Dua Lipa / Bruno Mars-style pop feel, no drum kit, only light "
            "hand percussion if any, instrumental, no vocals"
        ),
        95: (
            "Mid-tempo syncopated clavinet and synth comp, punchy finger-bass "
            "with a confident pop bounce, Dua Lipa / Bruno Mars-style pop "
            "energy, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
        90: (
            "Laid-back but syncopated clavinet/synth comping, punchy "
            "finger-bass with warm pop groove, Dua Lipa / Bruno Mars-style "
            "feel, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
    },
    "r&b/soul": {
        88: (
            "Laid-back electric piano (Rhodes) and clavinet comp with deep "
            "pocket finger-bass, warm smooth D'Angelo / Anderson .Paak-style "
            "r&b feel, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
        84: (
            "Warm, laid-back Rhodes and clavinet comping, deep finger-bass "
            "sitting in the pocket, smooth D'Angelo / Anderson .Paak-style "
            "r&b groove, no drum kit, only light hand percussion if any, "
            "instrumental, no vocals"
        ),
        80: (
            "Slow, laid-back electric piano and clavinet comp, deep finger-"
            "bass with a smooth soulful pocket, D'Angelo / Anderson .Paak-"
            "style r&b warmth, no drum kit, only light hand percussion if "
            "any, instrumental, no vocals"
        ),
    },
    "calm": {
        80: (
            "Minimal, warm electric piano and pad textures, slow deep bass "
            "moving gently under the harmony, meditative and spacious, no "
            "drum kit, only light hand percussion if any, instrumental, no "
            "vocals"
        ),
        76: (
            "Minimal warm electric piano/pad, slow deep bass with a calm, "
            "meditative feel, no drum kit, only light hand percussion if "
            "any, instrumental, no vocals"
        ),
        72: (
            "Sparse, warm electric piano and soft pad, slow deep bass, "
            "meditative and unhurried atmosphere, no drum kit, only light "
            "hand percussion if any, instrumental, no vocals"
        ),
        70: (
            "Very minimal warm electric piano/pad textures, slow deep bass "
            "tones, meditative and still, no drum kit, only light hand "
            "percussion if any, instrumental, no vocals"
        ),
    },
}


# ---------------------------------------------------------------------------
# Sanity checks — run on import so a broken edit fails loudly and immediately.
# ---------------------------------------------------------------------------
def _validate():
    _SUFFIX = "instrumental, no vocals"
    _LATIN_TERMS = ("montuno", "clave", "tumbao")

    for variant_name, table in (
        ("PROMPTS_MELODIC_A", PROMPTS_MELODIC_A),
        ("PROMPTS_MELODIC_B", PROMPTS_MELODIC_B),
    ):
        assert set(table.keys()) == {"latin/salsa", "pop", "r&b/soul", "calm"}, (
            f"{variant_name}: unexpected genre keys {list(table.keys())}"
        )

        for genre, bpm_table in table.items():
            for bpm, prompt in bpm_table.items():
                assert isinstance(prompt, str) and prompt.strip(), (
                    f"{variant_name}[{genre}][{bpm}] is empty"
                )
                assert prompt.rstrip().endswith(_SUFFIX), (
                    f"{variant_name}[{genre}][{bpm}] does not end with "
                    f"'{_SUFFIX}': {prompt!r}"
                )
                # No baked drum-kit vocabulary allowed anywhere.
                lowered = prompt.lower()
                for banned in (
                    "congas",
                    "timbales",
                    "tight steady drums",
                    "softly swung",
                    "sparse soft drums",
                    "hi-hat",
                    "snare",
                    "kick drum",
                ):
                    assert banned not in lowered, (
                        f"{variant_name}[{genre}][{bpm}] still contains banned "
                        f"drum-kit term {banned!r}"
                    )

                if genre == "latin/salsa":
                    for term in _LATIN_TERMS:
                        assert term in lowered, (
                            f"{variant_name}[{genre}][{bpm}] is missing "
                            f"required genre vocabulary {term!r}: {prompt!r}"
                        )

    # Same (genre, bpm) key shape across both variants.
    assert PROMPTS_MELODIC_A.keys() == PROMPTS_MELODIC_B.keys()
    for genre in PROMPTS_MELODIC_A:
        assert PROMPTS_MELODIC_A[genre].keys() == PROMPTS_MELODIC_B[genre].keys(), (
            f"BPM keys differ between variants for genre {genre!r}"
        )


_validate()


if __name__ == "__main__":
    # Quick manual inspection: python lib_prompts_melodic.py
    for variant_name, table in (
        ("A (strict no-drums)", PROMPTS_MELODIC_A),
        ("B (light hand percussion allowed)", PROMPTS_MELODIC_B),
    ):
        print(f"\n=== Variant {variant_name} ===")
        for genre, bpm_table in table.items():
            for bpm, prompt in bpm_table.items():
                print(f"\n[{genre} @ {bpm} bpm]\n{prompt}")
