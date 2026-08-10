"""genre_presets.py — One-call genre + calm conditioning for the hybrid pipeline.

WHY THIS EXISTS
---------------
The hybrid pipeline has two layers that must AGREE on style:
  * the NEURAL BED  (MusicGen)  -> carries harmony / instrumentation / feel
  * the SYMBOLIC DRUMS (GrooveGen knobs) -> carry the groove (the manipulation)

Up to now the user hand-wrote a MusicGen prompt AND separately picked a
drum_style + knobs, and had to keep them consistent by hand. This module makes
the genre the single source of truth: pick a genre (and optionally a calm
level) and it returns

    {
      "bed_prompt"  : str,    # paste into MusicGen
      "tempo_hint"  : int,    # the genre's idiomatic tempo (also goes in prompt)
      "drum_style"  : str,    # the matching DRUM_STYLES key
      "knobs"       : dict,    # event_density / syncopation_level / swing_amount /
                               # microtiming_variance_ms  -> forwarded to hybrid_render
      "seed_genre"  : str,    # genre_styles key for the optional MusicGen melody seed
    }

so the bed and the drums are guaranteed to describe the same song.

GENRES (match groovegen.DRUM_STYLES and genre_styles.GENRE_STYLES exactly):
    hip-hop/rap, r&b/soul, pop, latin/salsa, classic-rock, metal

CALM MODE  (two ways, the user asked for BOTH)
----------------------------------------------
  1. STANDALONE 'calm' genre  -> a literature-grounded tranquil preset
     (low tempo, major/modal, slow harmonic rhythm, soft legato timbre, sparse
      brush-kit drums, zero syncopation).
  2. CALM AS A MODIFIER (calm_level in 0.0..1.0) layerable on ANY genre ->
     interpolates the genre toward the tranquil target: lowers tempo, softens
     the bed prompt (adds 'mellow, soft dynamics, legato, warm'), and reduces
     the drum arousal knobs (density, syncopation, swing) toward calm values.

The calm feature targets are grounded in the relaxation / arousal-reduction
literature; see calm_music_literature.md and the CALM_TARGET table below for
citations. The knob is the SAME groove instrument the study uses, so calm is
fully measurable, not a black box.
"""
from __future__ import annotations
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
@dataclass
class GenrePreset:
    genre: str
    tempo: int                  # idiomatic tempo (bpm)
    bed_core: str               # instrumentation / harmony phrase for MusicGen
    bed_feel: str               # feel words for MusicGen
    drum_style: str             # DRUM_STYLES key
    seed_genre: str             # genre_styles.GENRE_STYLES key (melody seed)
    knobs: dict                 # default groove knobs for this genre
    suppress_bed_drums: bool = True   # HPSS-strip MusicGen's baked-in drums (see note)
    guidance_scale: float = 3.0       # CFG weight; higher => follows prompt more literally
    lock_tempo: bool = False          # pin drum grid to `tempo` (dense-texture genres where
                                      # beat tracking mis-reads tempo, e.g. salsa montuno)
    mix_kwargs: dict | None = None    # per-genre hybrid-mix balance overrides (bed_gain_db,
                                      # drum_gain_db, sidechain_depth_db, bed_hpf_hz). None =
                                      # use mix_stems defaults (bed -2 dB, drums -4.5 dB).
    note: str = ""


# Default (non-calm) presets. Tempos/styles mirror genre_styles.py so bed and
# drums describe the same song.
GENRE_PRESETS: dict[str, GenrePreset] = {
    "hip-hop/rap": GenrePreset(
        genre="hip-hop/rap", tempo=90,
        bed_core=("dusty boom-bap hip-hop instrumental built on signature hip-hop instruments: "
                  "a chopped soul sample, warm Rhodes/vibraphone chord stabs, a deep round sub bass, "
                  "and vinyl-crackle texture, dorian minor vamp, no drums"),
        bed_feel="laid-back, behind-the-beat, lo-fi, mellow",
        drum_style="hip-hop/rap", seed_genre="hip-hop/rap",
        knobs=dict(event_density=9, syncopation_level=0.35, swing_amount=1.08, microtiming_variance_ms=6.0),
        note="Boom-bap: sparse, swung, behind-the-beat."),
    "r&b/soul": GenrePreset(
        genre="r&b/soul", tempo=96,
        bed_core=("smooth neo-soul built on signature R&B instruments: lush Rhodes electric piano "
                  "with rootless major-9 voicings, a round fingered electric bass, warm analog synth pads, "
                  "and subtle clean guitar licks, no drums"),
        bed_feel="warm, laid-back, in-the-pocket, soulful",
        drum_style="r&b/soul", seed_genre="r&b/soul",
        # Tightened pocket: random microtiming jitter removed (it read as 'loose'
        # against the smooth sustained Rhodes harmony), density and syncopation
        # trimmed so the groove is deliberate, not busy. The slow tempo + lush
        # chords expose timing slop more than any other genre, so we keep the
        # drums clean and on-grid here.
        # DENSITY LOWERED 8->6 and swing eased: user's ear was right, the pocket
        # was too busy for laid-back neo-soul (measured 4.1 hits/sec).
        knobs=dict(event_density=6, syncopation_level=0.18, swing_amount=1.02, microtiming_variance_ms=0.0),
        # Neo-soul beds are sparse/legato -> beat tracking mis-reads the tempo
        # (a bed at 96 got tracked at 136). Pin it so the pocket sits right.
        lock_tempo=True,
        # User: 'drums overpower the MusicGen bed, give the bed a bit more volume.'
        # Push the bed up (+2 dB vs the -2 default) and pull drums down (-7 vs
        # -4.5) so the lush Rhodes sits forward and the groove supports it.
        mix_kwargs=dict(bed_gain_db=0.0, drum_gain_db=-7.0, sidechain_depth_db=3.5),
        note="Neo-soul: lush chords, tight deliberate pocket, bed-forward mix."),
    "pop": GenrePreset(
        genre="pop", tempo=118,
        bed_core=("modern radio pop built on contemporary pop-production instruments: a bright "
                  "plucked synth lead hook, glossy sidechained synth-pad chords that pump with the beat, "
                  "a deep punchy synth bass, shimmering bell/pluck arpeggios, and a tight muted electric "
                  "guitar stab, bright major key, no drums"),
        bed_feel="energetic, danceable, glossy, polished, modern, radio-ready, uplifting",
        drum_style="pop", seed_genre="pop",
        knobs=dict(event_density=12, syncopation_level=0.30, swing_amount=1.0, microtiming_variance_ms=2.0),
        note="Danceable pop: straight, tight, high groove."),
    "latin/salsa": GenrePreset(
        # tempo_hint is the QUARTER-NOTE pulse (~95 BPM). Salsa 'feels' fast but
        # MusicGen renders the beat around 90-110; the old 180 hint made the
        # octave-snap double the grid to ~218 BPM, so the drums landed at 2x the
        # bed's pulse and sounded badly off-beat. 95 tracks the real felt pulse.
        genre="latin/salsa", tempo=95,
        bed_core=("uplifting modern salsa romantica in the style of Marc Anthony 'Vivir Mi Vida', built on "
                  "signature salsa instruments: a bright joyful acoustic piano montuno, an upright/electric "
                  "bass tumbao locked to a 2-3 clave, a big anthemic brass section of trumpets and trombones "
                  "playing soaring mambo horn lines, and a tres guitar, bright major key, no drums"),
        bed_feel="energetic, syncopated, danceable, festive, joyful, anthemic, celebratory, uplifting",
        drum_style="latin/salsa", seed_genre="latin/salsa",
        knobs=dict(event_density=6, syncopation_level=0.35, swing_amount=1.0, microtiming_variance_ms=1.0),
        lock_tempo=True,   # montuno's dense 8th-notes make madmom read ~101; pin to 95 so
                           # the grid stops sliding off the clave (drums felt off-beat).
        note="Salsa: clave-locked, breathing groove (lightened), quarter-pulse ~95, tempo pinned."),
    "classic-rock": GenrePreset(
        genre="classic-rock", tempo=94,
        bed_core=("classic rock built on signature rock instruments: a chunky overdriven power-chord "
                  "rhythm electric guitar, a warm Hammond organ pad, and a driving picked electric bass, "
                  "no drums"),
        bed_feel="punchy, driving, raw, energetic",
        drum_style="classic-rock", seed_genre="classic-rock",
        knobs=dict(event_density=11, syncopation_level=0.20, swing_amount=1.0, microtiming_variance_ms=3.0),
        note="Classic rock: chunky, straight backbeat."),
    "metal": GenrePreset(
        genre="metal", tempo=123,
        bed_core=("heavy metal built on signature metal instruments: relentless high-gain palm-muted "
                  "distorted rhythm guitars chugging minor power chords on a low open-E pedal, a gritty "
                  "distorted bass doubling the riff, no drums"),
        bed_feel="aggressive, driving, dark, intense",
        drum_style="metal", seed_genre="metal",
        knobs=dict(event_density=13, syncopation_level=0.20, swing_amount=1.0, microtiming_variance_ms=1.0),
        note="Metal: relentless, tight, double-time feel."),
}


# ---------------------------------------------------------------------------
# CALM TARGET — literature-grounded tranquil / low-arousal feature set.
# Every value below is grounded in the relaxation / autonomic-arousal
# literature; full citations with URLs are in calm_music_literature.md.
# Summary of the evidence each field encodes:
#
#   tempo 60-70 BPM  -> sits in the resting-HR band that supports parasympathetic
#       (vagal) dominance and the lowest HR/GSR; faster-than-resting tempo raises
#       HR via sympatho-respiratory coupling.  (Bernardi et al. 2006 -- raga 55 /
#       slow classical 70 gave the largest HR fall; Khalfa et al. 2008 -- slow
#       tempo is the PRIMARY driver of lower skin conductance; Wu & Chang 2021.)
#   syncopation 0.0  -> zero/minimal syncopation, simple isochronous pulse, no
#       prominent backbeat -> high predictability lowers arousal.  (Schubert &
#       Keller 2011; Witek et al. 2014 -- syncopation drives wanting-to-move/
#       arousal.)
#   event_density LOW (+ space)  -> sparse onsets (~1-2 events/beat) and
#       deliberate near-silence are the STRONGEST acute parasympathetic driver --
#       pauses dropped HR/BP/ventilation below baseline.  (Bernardi et al. 2006.)
#   swing 1.0, microtiming 0 ms  -> steady, no agitation, fully predictable.
#   bed prompt -> major / modal (Dorian, Lydian) diatonic harmony, SLOW harmonic
#       rhythm (~1 chord / 2-4 bars), low harmonic complexity, soft stable
#       dynamics (no crescendos -> avoids vasoconstriction), dark/warm low-
#       spectral-centroid timbre with slow legato attack (piano, soft string
#       pads).  (Eerola et al. 2013; Batliner et al. 2022; Bernardi et al. 2009;
#       Milne et al. 2023.)
#
# NOTE on phrasing (not a knob, but documented for the bed design): ~8-12 s
# phrases (~0.1 Hz, 5-7 phrases/min) entrain the baroreflex resonance frequency
# and maximise HRV -- the biofeedback 'golden frequency' (Bernardi et al. 2009).
# The Marconi Union 'Weightless 65%' claim is marketing-derived, NOT peer-
# reviewed; a controlled study found only modest SCL effects and no advantage
# over silence for HR/respiration (Shepherd et al. 2022). We design from the
# mechanism literature, not that claim.
# ---------------------------------------------------------------------------
CALM_TARGET = dict(
    tempo=63,                       # 60-70 BPM resting-HR band (Bernardi 2006; Khalfa 2008)
    syncopation_level=0.0,          # zero syncopation, predictable pulse (Schubert & Keller 2011)
    swing_amount=1.0,               # straight, no agitation
    event_density=4,                # very sparse onsets + space; pauses = strongest vagal driver (Bernardi 2006)
    microtiming_variance_ms=0.0,    # steady, predictable
    bed_core=("gentle solo classical piano playing slow flowing broken-chord arpeggios in the "
              "romantic-impressionist style of Chopin, Debussy and Mozart, with warm sustained "
              "string pads underneath, diatonic major / Lydian harmony with a clear tonic, slow "
              "harmonic rhythm changing about once every two to four bars, smooth legato lines "
              "with sustain pedal, no drums"),
    bed_feel=("calm, tranquil, soft and stable dynamics with no crescendos, dark warm timbre, "
              "flowing legato arpeggios, soothing, peaceful, slow, spacious with gentle pauses"),
)

# Standalone calm preset (its own selectable 'genre').
CALM_PRESET = GenrePreset(
    genre="calm", tempo=CALM_TARGET["tempo"],
    bed_core=CALM_TARGET["bed_core"], bed_feel=CALM_TARGET["bed_feel"],
    drum_style="r&b/soul",          # softest kit; brushed/sparse via low density
    seed_genre="r&b/soul",
    knobs=dict(event_density=CALM_TARGET["event_density"],
               syncopation_level=CALM_TARGET["syncopation_level"],
               swing_amount=CALM_TARGET["swing_amount"],
               microtiming_variance_ms=CALM_TARGET["microtiming_variance_ms"]),
    # Calm beds are already tonal/drum-free (measured perc/harm ratio ~0.05), so
    # HPSS would only risk thinning the delicate piano/pads. Leave the bed intact.
    suppress_bed_drums=False,
    note="Standalone tranquil preset (literature-grounded low-arousal target).")

# Standalone CALM-CLASSICAL preset: same literature-grounded low-arousal targets
# (tempo ~60 BPM, zero syncopation, sparse, soft, no crescendos) but voiced as an
# explicitly classical SOLO PIANO piece -- a slow nocturne/adagio with a gentle
# singing melody over flowing left-hand arpeggios, rather than the ambient
# piano+pad of the generic 'calm' preset. Stays inside the same feature table:
# slow tempo, tonal/consonant harmony, legato, low dynamics, sparse onsets.
CALM_CLASSICAL_PRESET = GenrePreset(
    genre="calm-classical", tempo=60,
    # Prompt tuned for COHERENCE, not virtuosity: ask for ONE simple idea at a
    # time and long held notes so MusicGen doesn't stack a busy melody + running
    # arpeggios + pads into harmonic clutter. Minimal, spacious, single-voice.
    bed_core=("a minimal, slow, peaceful solo piano piece, sparse and simple in the gentle style of "
              "Erik Satie Gymnopedie, one hand playing a few soft single notes of a quiet melody while "
              "the other holds one calm sustained chord underneath, mostly one note at a time, lots of "
              "space and silence between phrases, one simple chord held for several seconds before it "
              "slowly changes, diatonic major key with a clear tonic, sustain pedal, no drums"),
    bed_feel=("very calm, minimal, sparse, coherent, uncluttered, soft even dynamics with no climaxes, "
              "warm intimate close-mic piano, long held notes, slow, still, spacious, soothing, peaceful"),
    drum_style="r&b/soul",          # softest kit; effectively near-silent at this density
    seed_genre="r&b/soul",
    knobs=dict(event_density=3, syncopation_level=0.0, swing_amount=1.0, microtiming_variance_ms=0.0),
    suppress_bed_drums=False,       # solo piano is already clean; keep it delicate
    note="Classical calm: minimal Satie-style solo piano (literature-grounded low-arousal target).")


# ---------------------------------------------------------------------------
# DRUM-FREE PROMPT BUILDER
# ---------------------------------------------------------------------------
# MusicGen has NO negative prompt (the transformers `generate()` API only takes
# positive text + guidance_scale). "no drums" is just tokens the model routinely
# ignores, because genre words like "salsa"/"rock"/"pop" imply a drum kit from
# the training data. The reliable prompt-side levers (confirmed by the MusicGen
# HF docs + practitioner reports) are:
#   1. NAME ONLY the tonal instruments you want and frame it as "instrumental
#      backing track, only these instruments" -- specifying the desired
#      instruments works far better than trying to exclude percussion.
#   2. DROP the bare genre keyword (it carries drums implicitly); keep the
#      instruments + harmony that define the style instead.
#   3. Append an explicit, repeated no-percussion clause as a weak nudge.
#   4. Raise guidance_scale (CFG) so the model follows the prompt more literally.
# This does NOT guarantee zero drums -- nothing in a text prompt can -- so it is
# LAYERED with the HPSS audio suppression (suppress_bed_drums) that cleans up
# whatever still leaks through. Use both for the cleanest bed.

def drumfree_prompt(bed_core: str, bed_feel: str, tempo: int) -> str:
    """Rewrite a bed prompt into an aggressive 'tonal instruments only' prompt.

    Strips genre/drum-carrying nouns from the core, then frames the remaining
    instrument list as an explicit percussion-free instrumental backing track.
    Pair with a higher guidance_scale (see get_preset(..., drumfree=True)).
    """
    core = bed_core
    # remove any existing "no drums" tail so we control the phrasing
    for tail in (", no drums", " no drums", ", no percussion", " no percussion"):
        core = core.replace(tail, "")
    frame = ("solo instrumental backing track with absolutely no drums, no "
             "percussion, no drum kit, no beat and no rhythmic percussion of any "
             "kind \u2014 only these tonal instruments: ")
    tail = (", sustained and melodic only, played rubato with no drum machine and "
            "no percussive hits, completely percussion-free")
    return f"{frame}{core}{tail}, {bed_feel}, tempo around {tempo} BPM"


# ---------------------------------------------------------------------------
def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def get_preset(genre: str, calm_level: float = 0.0,
               tempo_override: int | None = None,
               drumfree: bool = False) -> dict:
    """Return the bed prompt + drum knobs for a genre, optionally moved toward calm.

    Parameters
    ----------
    genre : one of GENRE_PRESETS keys, 'calm' for the standalone tranquil
            (ambient piano + pads) preset, or 'calm-classical' for the slow
            solo-piano nocturne calm preset.
    calm_level : 0.0..1.0. 0 = pure genre. 1 = fully tranquil. Intermediate
            values interpolate tempo and the arousal knobs toward CALM_TARGET
            and soften the bed prompt. Ignored when genre == 'calm' (already 1).
    tempo_override : if given, use this BPM as the final tempo_hint (and in the
            bed prompt) instead of the genre/calm-interpolated tempo. Lets the
            user dial in any tempo per genre. The drum knobs are unchanged.
    drumfree : if True, rewrite the bed prompt to an aggressive 'tonal
            instruments only, no percussion' phrasing (see drumfree_prompt) and
            RAISE guidance_scale so MusicGen follows it more literally. This is
            the PROMPT-side attempt to stop MusicGen baking in its own drums.
            It reduces but cannot guarantee zero drums (MusicGen has no true
            negative prompt), so it is meant to be LAYERED with the HPSS audio
            suppression (suppress_bed_drums). Ignored for calm presets (already
            drum-free by design).

    Returns
    -------
    dict with bed_prompt, tempo_hint, drum_style, knobs, seed_genre, calm_level,
    suppress_bed_drums, guidance_scale.
    """
    calm_level = float(max(0.0, min(1.0, calm_level)))

    if genre in ("calm", "calm-classical"):
        p = CALM_CLASSICAL_PRESET if genre == "calm-classical" else CALM_PRESET
        tempo = int(tempo_override) if tempo_override else p.tempo
        prompt = f"{p.bed_core}, {p.bed_feel}, tempo around {tempo} BPM"
        return dict(bed_prompt=prompt, tempo_hint=tempo, drum_style=p.drum_style,
                    knobs=dict(p.knobs), seed_genre=p.seed_genre, calm_level=1.0,
                    suppress_bed_drums=p.suppress_bed_drums,
                    guidance_scale=p.guidance_scale,
                    lock_tempo=(tempo if getattr(p, 'lock_tempo', False) else None),
                    mix_kwargs=(dict(p.mix_kwargs) if getattr(p, 'mix_kwargs', None) else None),
                    genre=genre, note=p.note)

    if genre not in GENRE_PRESETS:
        raise KeyError(f"unknown genre {genre!r}; choose from "
                       f"{list(GENRE_PRESETS) + ['calm', 'calm-classical']}")
    p = GENRE_PRESETS[genre]

    if calm_level <= 0.0:
        tempo = int(tempo_override) if tempo_override else p.tempo
        if drumfree:
            prompt = drumfree_prompt(p.bed_core, p.bed_feel, tempo)
            gscale = max(p.guidance_scale, 4.5)   # follow the prompt harder
        else:
            prompt = f"{p.bed_core}, {p.bed_feel}, tempo around {tempo} BPM"
            gscale = p.guidance_scale
        return dict(bed_prompt=prompt, tempo_hint=tempo, drum_style=p.drum_style,
                    knobs=dict(p.knobs), seed_genre=p.seed_genre, calm_level=0.0,
                    suppress_bed_drums=p.suppress_bed_drums,
                    guidance_scale=gscale,
                    lock_tempo=(tempo if p.lock_tempo else None),
                    mix_kwargs=(dict(p.mix_kwargs) if p.mix_kwargs else None),
                    genre=genre, note=p.note)

    # ---- interpolate genre -> calm target -------------------------------
    t = calm_level
    tempo = int(round(_lerp(p.tempo, CALM_TARGET["tempo"], t)))
    if tempo_override:
        tempo = int(tempo_override)
    knobs = dict(
        event_density=int(round(_lerp(p.knobs["event_density"],
                                       CALM_TARGET["event_density"], t))),
        syncopation_level=round(_lerp(p.knobs["syncopation_level"],
                                       CALM_TARGET["syncopation_level"], t), 3),
        swing_amount=round(_lerp(p.knobs["swing_amount"],
                                  CALM_TARGET["swing_amount"], t), 3),
        microtiming_variance_ms=round(_lerp(p.knobs["microtiming_variance_ms"],
                                             CALM_TARGET["microtiming_variance_ms"], t), 2),
    )
    # soften the bed prompt: keep genre instrumentation, add calm feel words and
    # ask for the calming features (soft dynamics, legato, slow harmonic rhythm)
    calm_words = "mellow, soft dynamics, legato, warm, relaxed, spacious"
    if t >= 0.6:
        calm_words += ", very calm, soothing, slow flowing arpeggios, slow harmonic changes"
    if drumfree:
        prompt = drumfree_prompt(p.bed_core, f"{p.bed_feel}, {calm_words}", tempo)
        gscale = max(p.guidance_scale, 4.5)
    else:
        prompt = f"{p.bed_core}, {p.bed_feel}, {calm_words}, tempo around {tempo} BPM"
        gscale = p.guidance_scale
    # As the bed moves toward calm it also becomes more tonal/less percussive, so
    # HPSS is only needed while it's still a rhythmic genre. Keep the genre's
    # setting for t<0.6, drop it once it's mostly calm.
    suppress = p.suppress_bed_drums and (t < 0.6)
    # Once the bed is interpolated toward calm its tempo is no longer the preset's
    # idiomatic value, so a hard tempo lock would fight the interpolated tempo.
    # Keep the lock only while still mostly the source genre (t < 0.4).
    locked = (tempo if (p.lock_tempo and t < 0.4) else None)
    # Keep the genre's bed-forward mix while it's mostly the source genre; once
    # it's mostly calm the interpolated bed is already gentle, so fall back to
    # the mix defaults.
    mixk = (dict(p.mix_kwargs) if (p.mix_kwargs and t < 0.5) else None)
    return dict(bed_prompt=prompt, tempo_hint=tempo, drum_style=p.drum_style,
                knobs=knobs, seed_genre=p.seed_genre, calm_level=t,
                suppress_bed_drums=suppress,
                guidance_scale=gscale,
                lock_tempo=locked,
                mix_kwargs=mixk,
                genre=genre, note=f"{p.note} (calm {t:.2f})")


def list_genres() -> list[str]:
    """All selectable genres, calm variants last."""
    return list(GENRE_PRESETS) + ["calm", "calm-classical"]
