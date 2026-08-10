"""genre_styles.py — Genre style-engine for GrooveGen DL beds.

WHY THIS EXISTS
---------------
The Anticipatory Music Transformer (AMT) was trained on the Lakh MIDI dataset
with NO genre labels and NO text conditioning. It cannot turn the word "salsa"
into a montuno. It only *embellishes / continues* MIDI that is already
stylistically suggestive. So the genre identity must live in the SEED we feed
it — not in the model.

The old seed builder held one sustained block chord per bar for every genre,
which is exactly why hip-hop, r&b and pop all sounded alike and the piano
sounded simplistic. This module instead encodes the *rhythmic figuration,
voicing vocabulary, bass pattern, and instrumentation* that actually define
each genre, then renders a rich multi-instrument seed. The AMT then varies
WITHIN the style instead of regressing to a generic mean.

Each style produces a 2-bar (configurable) seed at 16th-note resolution.

Public API
----------
GENRE_STYLES : dict[str, StyleSpec]
build_style_seed(genre, bars=2) -> pretty_midi.PrettyMIDI
seed_feature_summary(pm) -> dict   (for auditing that genres really differ)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable
import random
import pretty_midi

# ---- GM programs (kept consistent with groovegen.py) -----------------------
GM_GRAND_PIANO   = 0
GM_ELECTRIC_PIANO = 4     # Rhodes — r&b/neo-soul
GM_CLAVINET      = 7     # funky plucky danceable-pop comp (Billie Jean family)
GM_VIBRAPHONE    = 11    # dusty boom-bap / lo-fi hip-hop chord timbre (distinct from Rhodes)
GM_NYLON_GUITAR  = 24
GM_STEEL_GUITAR  = 25
GM_OVERDRIVE_GUITAR = 29  # classic rock rhythm guitar
GM_FINGERED_BASS = 33
GM_PICKED_BASS   = 34
GM_SYNTH_BASS    = 38     # hip-hop sub/synth bass
GM_STRINGS       = 48
GM_BRASS_SECTION = 61     # salsa horn stabs
GM_SAW_LEAD      = 81     # synth-pop arpeggio pluck (saw lead)
GM_SYNTH_PAD     = 89

# Percussion (channel-10 / is_drum) — General MIDI key numbers
KICK, SNARE, CHH, OHH = 36, 38, 42, 46
RIM, CLAVE, HICONGA, LOWCONGA, COWBELL = 37, 75, 62, 63, 56
RIDE, CRASH, TOM_LO = 51, 49, 45


# ---------------------------------------------------------------------------
@dataclass
class StyleSpec:
    name: str
    tempo: int
    # progression: list of (root_midi, [chord-tone intervals]) — one per bar (or per chord)
    progression: list
    # which voicing transform to apply to chord tones
    voicing: str          # "triad" | "rootless9" | "min7_open" | "power" | "salsa_close"
    # comping rhythm: list of 16th-step indices (0..15) where the chord articulates
    comp_steps: list
    # bass pattern: list of (step, scale_degree_offset_semitones, dur_steps)
    bass_pattern: list
    chord_program: int
    bass_program: int
    # optional extra layer (e.g. horn stabs, clave) -> builder fn(pm, bars, spb16)
    extras: list = field(default_factory=list)
    feel: str = "straight"   # "straight" | "laidback" | "swing"
    desc: str = ""
    # --- humanization / phrasing (richer, less robotic comping) ----------------
    # comp_style: how each comp_step articulates the chord.
    #   "block"   -> full chord on every comp step (old behaviour)
    #   "sustain_accent" -> full chord rings on strong beats; lighter partial
    #                       voices on the weak off-beats (natural piano/guitar)
    #   "arp"           -> fire ONE chord-tone at a time across the comp_steps
    #                       in an up/down pattern (synth-pop pluck / Blinding
    #                       Lights motor); short notes, tresillo accent
    #   "staccato_chug" -> short, hard, palm-muted power-chord stabs with space
    #                       between hits + heavy low pedal (AC/DC / Metallica)
    comp_style: str = "block"
    humanize: bool = False   # apply velocity dynamics + micro-timing + strum
    base_vel: int = 70       # nominal chord velocity before accenting
    strum_ms: float = 0.0    # stagger between chord tones (ms); guitar/piano roll


# ---- voicing transforms ----------------------------------------------------
def _voice(root: int, ivals: list, style: str) -> list:
    """Return actual MIDI pitches for one chord under a voicing style."""
    if style == "triad":
        return [root + i for i in ivals[:3]]
    if style == "add9":                       # pop: triad + added 9th (sparkle)
        # use the chord's own tones (handles min/maj/min7) + a 9th on top
        tones = [root + i for i in ivals[:3]]
        return tones + [root + 14]
    if style == "power":                      # rock: root + 5th (+ octave)
        return [root, root + 7, root + 12]
    if style == "min7_open":                  # hip-hop: spread min7, drop the 5th low
        return [root, root + 10, root + 12 + 3, root + 12 + 7]
    if style == "rootless9":                  # r&b/neo-soul: rootless 3-7-9(-13), mid register
        # drop the root (bass covers it), voice 3rd/7th/9th up high
        third = root + (3 if 3 in ivals else 4)
        seventh = root + (10 if 10 in ivals else 11)
        ninth = root + 14
        return [third + 12, seventh + 12, ninth + 12]
    if style == "salsa_close":                # tight close RH voicing, montuno register
        return [root + 12 + i for i in ivals[:3]] + [root + 24]
    return [root + i for i in ivals[:3]]


# ---- per-genre styles ------------------------------------------------------
# comp_steps are 16th positions in ONE bar (16 steps). The builder repeats them
# per bar but re-voices to that bar's chord.
GENRE_STYLES: dict[str, StyleSpec] = {

    # Hip-hop: laid-back dorian min7 loop, sub bass, sparse syncopated chord stabs
    "hip-hop/rap": StyleSpec(
        name="hip-hop/rap", tempo=90, voicing="min7_open", feel="laidback",
        progression=[(45, [0,3,7,10]), (50, [0,3,7,10])],  # Amin7 - Dmin7
        comp_steps=[0, 6, 10],                 # off-beat stabs (the "&" feel)
        bass_pattern=[(0, -12, 4), (6, -12, 2), (10, -5, 3)],  # sub on 1, push on the &
        chord_program=GM_VIBRAPHONE, bass_program=GM_SYNTH_BASS,
        desc="Laid-back dorian min7 vamp; sub bass; sparse syncopated dusty vibe/boom-bap stabs (vibraphone, distinct from r&b Rhodes)"),

    # R&B / neo-soul: lush rootless 9th chords, behind-the-beat, soft passing stabs
    "r&b/soul": StyleSpec(
        name="r&b/soul", tempo=96, voicing="rootless9", feel="laidback",
        progression=[(48, [0,4,7,11,14]), (53, [0,4,7,11])],  # Cmaj9 - Fmaj7
        comp_steps=[2, 5, 8, 11, 14],          # gentle continuous comp, behind the beat
        bass_pattern=[(0,-12,3),(4,-7,2),(8,-12,3),(12,-3,2)],
        chord_program=GM_ELECTRIC_PIANO, bass_program=GM_FINGERED_BASS,
        desc="Lush rootless maj9 Rhodes voicings; behind-the-beat neo-soul comp"),

    # Pop: modeled on the TOP-DANCEABILITY pop in Sophia's dataset -- Billie Jean
    # (dance 93), Break My Stride (92), 360, Loba, Shape of You. Their shared DNA
    # is a ~120 BPM funky, SYNCOPATED, bright-but-not-buzzy groove: a tight
    # plucky clavinet/e-piano comp with a strong off-beat, over a syncopated
    # finger-bass -- high danceability, moderate energy, positive valence.
    # (The old buzzy saw lead is gone -- clavinet is the classic danceable-pop
    # comp timbre, e.g. the Billie Jean / Superstition family.)
    "pop": StyleSpec(
        name="pop", tempo=120, voicing="add9", feel="straight",
        # Bright, danceable major-pop loop: F#m7 - A - E - B  (vi-I-V-II in A),
        # the kind of warm, uplifting 4-chord pop vamp -- voiced with an added
        # 9th for sparkle, then walked by the arp engine.
        progression=[(54,[0,3,7,10]),(57,[0,4,7]),(52,[0,4,7]),(59,[0,4,7])],
        # funky off-beat-leaning pulse: emphasise the syncopated 'e' and '&'
        # (the danceable Billie-Jean pocket), not a flat every-16th run.
        comp_steps=[0,2,3,6,7,8,10,11,14,15],
        bass_pattern=[(0,-12,2),(3,-12,1),(6,-12,2),(8,-12,2),(11,-7,1),(14,-12,2)],  # syncopated finger-bass
        chord_program=GM_CLAVINET, bass_program=GM_FINGERED_BASS,
        comp_style="arp", humanize=True, base_vel=72, strum_ms=0.0,
        desc="Funky danceable pop (Billie Jean / Break My Stride family): syncopated plucky clavinet comp over a finger-bass groove; ~120 BPM, high danceability"),

    # Salsa: montuno arpeggio locked to 2-3 clave, bass tumbao, clave+conga, horn stabs
    "latin/salsa": StyleSpec(
        name="latin/salsa", tempo=180, voicing="salsa_close", feel="straight",
        progression=[(50,[0,4,7]),(57,[0,4,7])],  # Dmaj - Amaj montuno cell (II-V flavor)
        # montuno: syncopated repeating RH arpeggio (anticipated, clave-locked)
        comp_steps=[0,3,6, 8,11,14],
        # tumbao: bass anticipates beat 3 and the "& of 4" — NOT on the downbeat
        bass_pattern=[(6,-12,2),(10,-5,2),(14,-12,2),(11+ -11, -12, 1)],
        chord_program=GM_GRAND_PIANO, bass_program=GM_FINGERED_BASS,
        extras=["clave_23", "conga_tumbao", "horn_stabs"],
        desc="Piano montuno + bass tumbao locked to 2-3 clave; congas + horn stabs"),

    # Classic rock: modeled on AC/DC "Back in Black" -- the groove lives in the
    # SPACE between chunky, palm-muted, STACCATO power-chord hits, not in a
    # ringing wall of sound. So instead of a uniform 8th-note machine gun we use
    # a riff with accented chord stabs and silence between them (A5 / D5 / E5
    # bluesy-major-borrowed shapes). The new "staccato_chug" comp_style makes
    # each hit short + hard + muted with heavy low pedal -- AC/DC swagger.
    "classic-rock": StyleSpec(
        name="classic-rock", tempo=94, voicing="power", feel="straight",
        # A5 - A5 - D5 - E5 : the "Back in Black" call-and-answer power-chord
        # cell (A major / mixolydian rock vocabulary).
        progression=[(45,[0,4,7]),(45,[0,4,7]),(50,[0,4,7]),(52,[0,4,7])],
        # riff with SPACE: hard accent on 1, answer on the "&", a push before 3,
        # then a held stab -- deliberate gaps (the silence IS the groove).
        comp_steps=[0,3,6,8,11,14],
        bass_pattern=[(0,-12,2),(3,-12,1),(6,-12,2),(8,-12,2),(11,-12,1),(14,-12,2)],
        chord_program=GM_OVERDRIVE_GUITAR, bass_program=GM_PICKED_BASS,
        comp_style="staccato_chug", humanize=True, base_vel=90, strum_ms=6.0,
        desc="AC/DC 'Back in Black' style: chunky palm-muted STACCATO power-chord stabs with space between hits; heavy low pedal + hard accents"),

    # Metallica "Enter Sandman" flavor: a heavier, faster, MINOR variant of the
    # same staccato-chug engine -- relentless palm-muted chug on an open-E pedal
    # with E5/G5/F#5 shapes. Menacing, driving, sinister. Showcase/demo genre.
    "metal": StyleSpec(
        name="metal", tempo=123, voicing="power", feel="straight",
        # E5 pedal with G5 / F#5 answers (E minor) -- the Sandman main riff cell.
        progression=[(40,[0,3,7]),(40,[0,3,7]),(43,[0,4,7]),(42,[0,4,7])],
        # chugging gallop: dense low-pedal 8ths/16ths but still articulated +
        # muted, with accent kicks on the answer chords.
        comp_steps=[0,2,4,6,7,8,10,12,14,15],
        bass_pattern=[(0,-12,1),(2,-12,1),(4,-12,1),(6,-12,1),(8,-12,1),
                      (10,-12,1),(12,-12,1),(14,-12,1)],
        chord_program=GM_OVERDRIVE_GUITAR, bass_program=GM_PICKED_BASS,
        comp_style="staccato_chug", humanize=True, base_vel=96, strum_ms=4.0,
        desc="Metallica 'Enter Sandman' style: relentless palm-muted minor chug on an open-E pedal (E5/G5/F#5); menacing + driving"),
}


# ---- extra-layer builders (salsa percussion / horns) -----------------------
def _add_clave_23(drum, bars, spb16):
    # 2-3 son clave hits (in 16th steps within a 2-bar cell): bar1 [4,10]; bar2 [0,6,10]
    pattern = {0: [4,10], 1: [0,6,10]}
    for b in range(bars):
        hits = pattern.get(b % 2, [4,10])
        for s in hits:
            t = (b*16 + s) * spb16
            drum.notes.append(pretty_midi.Note(velocity=92, pitch=CLAVE, start=t, end=t+spb16*0.5))

def _add_conga_tumbao(drum, bars, spb16):
    # simplified tumbao: open tone on 'and of 2' and beat 4
    for b in range(bars):
        for s, k, v in [(6, HICONGA, 88), (12, LOWCONGA, 80), (14, HICONGA, 84)]:
            t = (b*16 + s) * spb16
            drum.notes.append(pretty_midi.Note(velocity=v, pitch=k, start=t, end=t+spb16*0.5))

def _add_horn_stabs(pm, bars, spb16):
    horns = pretty_midi.Instrument(program=GM_BRASS_SECTION, name="horn_stabs")
    for b in range(bars):
        # short stab on the "& of 4" anticipating the next bar (very salsa)
        for s, pitches in [(14, [62, 66, 69])]:
            t = (b*16 + s) * spb16
            for p in pitches:
                horns.notes.append(pretty_midi.Note(velocity=90, pitch=p, start=t, end=t+spb16*1.2))
    pm.instruments.append(horns)

_EXTRA_FNS = {"clave_23": _add_clave_23, "conga_tumbao": _add_conga_tumbao}


# ---- humanization helpers --------------------------------------------------
def _beat_accent(step: int) -> float:
    """Metric accent weight for a 16th step (0..15). Strong beats louder."""
    if step % 16 == 0:      # bar downbeat (beat 1)
        return 1.00
    if step % 8 == 0:       # beat 3
        return 0.90
    if step % 4 == 0:       # beats 2 & 4
        return 0.82
    if step % 2 == 0:       # off-beat 8ths ('and')
        return 0.66
    return 0.55             # 16th subdivisions


def _is_strong(step: int) -> bool:
    """Strong beat = quarter-note grid (full sustained chord under sustain_accent)."""
    return step % 4 == 0


# tresillo = the 3+3+2 sixteenth accent grid (steps 0, 3, 6) that underpins
# Shape of You and most modern pop. Hits landing on it get an extra push.
_TRESILLO = {0, 3, 6, 8, 11, 14}


def _arp_sequence(pitches: list, n_steps: int) -> list:
    """Up-down arpeggio index sequence over the chord tones, plus an octave top.

    Returns a list of MIDI pitches (length n_steps) walking root->top->back,
    so a synth pluck outlines the chord instead of striking it as a block.
    """
    if not pitches:
        return []
    ladder = sorted(pitches) + [min(pitches) + 12]   # add octave for sparkle
    up_down = ladder + ladder[-2:0:-1]               # 0..top..1 (no repeat ends)
    if not up_down:
        up_down = ladder
    return [up_down[i % len(up_down)] for i in range(n_steps)]


# ---- main seed builder -----------------------------------------------------
def build_style_seed(genre: str, bars: int = 2, seed: int = 0) -> pretty_midi.PrettyMIDI:
    """Render a rich, genre-correct multi-instrument MIDI seed for `genre`.

    `seed` makes the (small) humanization jitter reproducible.
    """
    if genre not in GENRE_STYLES:
        raise KeyError(f"Unknown genre {genre!r}. Known: {sorted(GENRE_STYLES)}")
    spec = GENRE_STYLES[genre]
    rng = random.Random(seed)
    pm = pretty_midi.PrettyMIDI(initial_tempo=spec.tempo)
    spb = 60.0 / spec.tempo          # sec per beat
    spb16 = spb / 4.0                # sec per 16th step
    swing = 0.06 * spb16 if spec.feel == "swing" else 0.0
    lay = 0.02 * spb16 if spec.feel == "laidback" else 0.0   # tiny behind-the-beat shift

    chords = pretty_midi.Instrument(program=spec.chord_program, name="bed_chords")
    bass = pretty_midi.Instrument(program=spec.bass_program, name="bed_bass")

    prog = spec.progression
    for b in range(bars):
        root, ivals = prog[b % len(prog)]
        pitches = _voice(root, ivals, spec.voicing)
        # for the arp engine: pre-walk one chord-tone per comp step this bar
        arp_pitches = (_arp_sequence(pitches, len(spec.comp_steps))
                       if spec.comp_style == "arp" else None)
        # ---- comp ----------------------------------------------------------
        for si, s in enumerate(spec.comp_steps):
            t0 = (b*16 + s) * spb16 + lay + (swing if s % 2 else 0)

            # phrasing: which voices play, and how long they ring, this step
            strong = _is_strong(s)
            if spec.comp_style == "arp":
                # synth-pop pluck: ONE tone per step, short, walking the chord
                voices = [arp_pitches[si]]
                dur = spb16 * 0.9          # short, plucky (gap between notes)
            elif spec.comp_style == "staccato_chug":
                # palm-muted power-chord stab: full (low) chord, very short,
                # with hard accents -> the space between hits is the groove
                voices = pitches
                dur = spb16 * (0.75 if strong else 0.55)
            elif spec.comp_style == "sustain_accent":
                if strong:
                    # full chord, rings into the next strong beat (legato, natural)
                    voices = pitches
                    dur = spb16 * 4.0
                else:
                    # weak step: lighter, shorter, only the upper voices (a stab,
                    # not the whole chord re-struck) -> avoids the robotic feel
                    voices = pitches[1:] if len(pitches) > 1 else pitches
                    dur = spb16 * 1.4
            else:  # "block" (hip-hop / r&b / salsa keep their existing character)
                voices = pitches
                dur = spb16 * (3 if spec.feel == "laidback" else 2)

            # velocity: metric accent + (optional) small human variation
            if spec.humanize:
                vel = spec.base_vel * _beat_accent(s)
                # tresillo / staccato extra push on the syncopated accent grid
                if spec.comp_style in ("arp", "staccato_chug") and s in _TRESILLO:
                    vel *= 1.12
                vel += rng.uniform(-6, 6)
                # timing micro-jitter (a few ms) so hits aren't perfectly quantized
                t0 += rng.uniform(-0.008, 0.008)
            else:
                vel = 58 if spec.feel == "laidback" else 70

            # strum: stagger chord tones by a few ms (guitar/piano roll), low->high
            strum_s = (spec.strum_ms / 1000.0) if spec.humanize else 0.0
            ordered = sorted(voices)
            for vi, p in enumerate(ordered):
                ts = max(0.0, t0 + vi * strum_s)   # clamp >=0 (fluidsynth requirement)
                v = int(max(1, min(127, vel - vi * 2)))  # top voices slightly softer
                chords.notes.append(pretty_midi.Note(velocity=v, pitch=int(p),
                                                     start=ts, end=ts + dur))
        # ---- bass ----------------------------------------------------------
        for (s, off, durst) in spec.bass_pattern:
            if s < 0 or s > 15:
                continue
            t0 = (b*16 + s) * spb16 + lay
            bass.notes.append(pretty_midi.Note(velocity=82, pitch=int(root+off),
                                               start=t0, end=t0+durst*spb16))
    pm.instruments += [chords, bass]

    # extras (salsa percussion + horns)
    if spec.extras:
        drum = pretty_midi.Instrument(program=0, is_drum=True, name="latin_perc")
        for ex in spec.extras:
            if ex in _EXTRA_FNS:
                _EXTRA_FNS[ex](drum, bars, spb16)
            elif ex == "horn_stabs":
                _add_horn_stabs(pm, bars, spb16)
        if drum.notes:
            pm.instruments.append(drum)
    return pm


def seed_feature_summary(pm: pretty_midi.PrettyMIDI) -> dict:
    """Cheap fingerprint so we can verify genres actually differ."""
    pitched = [i for i in pm.instruments if not i.is_drum]
    notes = [n for i in pitched for n in i.notes]
    pitches = [n.pitch for n in notes]
    progs = sorted({i.program for i in pitched})
    has_perc = any(i.is_drum for i in pm.instruments)
    dur = max(pm.get_end_time(), 1e-6)
    return dict(
        n_instruments=len(pm.instruments),
        n_pitched_notes=len(notes),
        notes_per_sec=round(len(notes)/dur, 2),
        programs=progs,
        pitch_range=(min(pitches), max(pitches)) if pitches else (0, 0),
        has_percussion=has_perc,
        tempo=round(pm.estimate_tempo()) if len(notes) >= 2 else None,
    )
