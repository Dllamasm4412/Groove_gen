"""
GrooveGen — parametric symbolic groove generator (v2)
=====================================================
Step 1: pattern_builder (backbeat skeleton) + deterministic render to
loudness-normalized WAV.

Design principles (see groovegen_generator_spec.md):
  - Knobs are CAUSES: each control writes directly into the MIDI grid.
  - Timbre held constant: one fixed soundfont, one fixed kit, fixed mix.
  - Deterministic + seeded: same params + seed -> bit-identical pattern.
  - Loopable: 1-bar core repeated seamlessly to a target duration.

This module is intentionally dependency-light and Colab-friendly:
    pip install pretty_midi pyfluidsynth pyloudnorm soundfile numpy
    (plus a General-MIDI .sf2 soundfont; TimGM6mb.sf2 ships with pretty_midi)

Steps 2-5 (tempo/density/swing, syncopation, microtiming, grid export)
extend GrooveParams and PatternBuilder below without changing the render path.
"""
from __future__ import annotations

import os
import random
import warnings
from dataclasses import dataclass, field, asdict

import numpy as np
import pretty_midi
import pyloudnorm as pyln
import soundfile as sf

# ----------------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------------
FS = 44100  # render sample rate (Hz)
TARGET_LUFS = -14.0  # loudness target; constant across ALL stimuli (no loudness confound)

# Longuet-Higgins & Lee (1984) metric weights for a 16-step 4/4 bar.
# Higher = metrically stronger. Downbeat strongest; then beat 3; beats 2&4;
# 8th off-beats; 16th subdivisions. Used for the Witek-style syncopation index.
METRIC_WEIGHTS = {
    0: 5,  # beat 1 (downbeat)
    8: 4,  # beat 3
    4: 3, 12: 3,            # beats 2 & 4
    2: 2, 6: 2, 10: 2, 14: 2,  # 8th off-beats
    1: 1, 3: 1, 5: 1, 7: 1, 9: 1, 11: 1, 13: 1, 15: 1,  # 16ths
}

# Drum-instrument salience multipliers for the Witek (2014) syncopation index.
# Witek's index weights bass drum more than snare; hi-hat is excluded entirely.
# These multipliers are what scale the index onto the literature's 0-81 range.
_SYNC_SALIENCE_KICK = 2.0
_SYNC_SALIENCE_SNARE = 1.5

# General MIDI percussion (channel 10) note numbers
KICK = 36
SNARE = 38
CLOSED_HAT = 42
OPEN_HAT = 46
GHOST_SNARE = 37  # side stick / used for ghost notes
RIDE = 51
# Extra GM percussion used by the genre-aware groove templates (drum_style).
HANDCLAP = 39       # layered with/instead of snare on the backbeat (pop/r&b)
PEDAL_HAT = 44      # foot hat
LOW_TOM = 45
COWBELL = 56        # latin
HI_CONGA = 63
LOW_CONGA = 64
SIDE_STICK = 37     # = GHOST_SNARE pitch (rimclick)
LOW_BONGO = 60

# ----------------------------------------------------------------------------
# Fixed musical bed (bass + chords + melody).
#
# Rationale: drum-only stimuli don't sound like "a song." We add a CONSTANT
# harmonic/melodic bed so the 5 drum knobs are perceived as variations of the
# same tune. The bed is held FIXED so it can never confound the manipulation:
#   - Same notes, same 16-step positions, same velocities in EVERY stimulus
#     (i.e. symbolically byte-identical: identical MIDI events per bar).
#   - It does NOT read event_density, swing_amount, syncopation_level, or
#     microtiming_variance_ms. The drum knobs are the ONLY manipulated vars,
#     so causal attribution to the drums is preserved.
#   - It DOES share the global tempo clock (it must, to stay in time with the
#     drums) — but tempo is itself a controlled knob measured per stimulus, and
#     the bed's symbolic content is invariant. No knob alters the bed's pattern.
#
# Musical content (v3): empirically grounded in Sophia's high-danceability
# sensory-motor tracks (see sophia/BED_FEATURE_PROFILE.md). Profile -> 4/4,
# ~120 BPM, bass-forward (low_band_energy_ratio 0.70), prominent sustained
# harmony (hpss_harmonic_ratio 0.70), slight major/positive lean (valence ~60),
# pop/hip-hop/r&b idiom. Chosen realization: an A-DORIAN vamp Am7 - D/A.
# Bass stays on A (strong low anchor); the D chord supplies the bright Dorian
# 6th -> "positive but cool", not saccharine major. Loopable, harmonically
# simple so it never competes with the drum density/syncopation manipulation.
# Non-percussion GM programs on dedicated channels (never channel 10).
# ----------------------------------------------------------------------------
# GM program numbers (0-indexed). With the full FluidR3_GM soundfont these
# render as realistic sampled instruments (not the thin TimGM6mb timbres).
GM_GRAND_PIANO = 0      # "Acoustic Grand Piano" — warm, natural, modern melody
GM_FINGERED_BASS = 33   # "Fingered Bass" — round, woody electric bass
GM_ELECTRIC_BASS = 33   # alias
GM_ELECTRIC_PIANO = 4   # "Electric Piano 1" — Rhodes-like, r&b/pop idiom
GM_SYNTH_PAD = 89       # "Pad 2 (warm)" — sustained warm chordal harmony
GM_STRINGS = 48         # "String Ensemble 1" — lush sustained strings
GM_NYLON_GUITAR = 24    # "Nylon Acoustic Guitar" — soft plucked harmony
GM_VIBES = 11           # "Vibraphone" — bright mallet melody
GM_WARM_LEAD = 81       # "Lead 2 (sawtooth)" — sustained synth lead

# ----------------------------------------------------------------------------
# Bed profiles. Each profile is a complete, self-contained musical bed: a chord
# loop (one chord per bar), a bass program + groove pattern, a pad/harmony
# program, a melody program + motif, and a velocity balance. ALL profiles share
# the same Sophia-derived constraints (4/4, ~120 BPM, bass-forward, harmonically
# rich, slight major/positive lean) but differ in progression and feel so the
# user can pick the "song" they like best. A profile is byte-identical across
# every GrooveParams (knob-invariant) once selected.
#
# Velocities are tuned for FluidR3: bass is FELT but no longer dominates, the
# melody is clearly audible, the pad is a soft cushion. All stay under the kit
# (kick=110, snare=118) so the drums remain the perceptual figure.
# MIDI note numbers; "step" = 16th-note index within a bar (0..15).
# ----------------------------------------------------------------------------
@dataclass(frozen=True)
class BedProfile:
    name: str
    desc: str
    # one (bass_root, [chord tones], [(step, pitch), ...] melody motif) per bar
    chords: tuple
    bass_program: int = GM_FINGERED_BASS
    chord_program: int = GM_SYNTH_PAD
    melody_program: int = GM_ELECTRIC_PIANO
    bass_steps: tuple = (0, 2, 4, 6, 8, 10, 12, 14)   # steady 8th pulse
    bass_vel: int = 60
    chord_vel: int = 44
    melody_vel: int = 74
    # Optional song form. When provided, the bed plays as a STRUCTURED SONG
    # (sections concatenated once, then the whole song repeats) instead of a
    # plain loop. Each section names a melody treatment whose per-bar motifs
    # OVERRIDE prof.chords' melody, while bass + chords stay constant per bar.
    #   sections: tuple of (section_name, melody_scale) where melody_scale is a
    #             multiplier applied to melody velocity (intro can be 0.0 to
    #             suppress melody), and section_name selects the motif set in
    #             `section_motifs`.
    #   section_motifs: dict[name] -> tuple of per-bar motifs (same length and
    #             order as `chords`); each motif is [(step, pitch), ...].
    # If sections is None, behaviour is the classic single-loop bed.
    sections: tuple = None
    section_motifs: tuple = None   # tuple of (name, per_bar_motifs) pairs
    # Optional HUMANIZED COMP plan (demo/song path only). When provided, the
    # song renderer replaces the single sustained block chord per bar with a
    # genre-correct rhythmic comp that has metric velocity accents, slight
    # timing jitter, a strum stagger across chord tones, and a sustain-vs-stab
    # phrasing -- i.e. it sounds like a real player instead of a machine-gun.
    # If None, the classic single-block-chord-per-bar behaviour is unchanged
    # (so the knob-invariant STUDY bed is completely untouched).
    #   comp_plan = dict(steps=[..16th positions..],
    #       comp_style="sustain_accent"|"block", base_vel=int,
    #       strum_ms=float, humanize=bool, seed=int)
    comp_plan: dict = None


# --- Profile 1: A-Dorian vamp (the original v3) — cool, modern, hip-hop/r&b ---
# Am7 - D/A (i7 - IV/1 in Dorian). Bass holds A (strong low anchor). The D chord
# supplies the bright Dorian 6th -> "positive but cool", not saccharine.
BED_DORIAN = BedProfile(
    name="dorian_vamp",
    desc="A-Dorian vamp Am7-D/A — cool, modern, hip-hop/r&b feel",
    chords=(
        (45, [57, 60, 64, 67], [(0, 69), (6, 72), (10, 76), (12, 74)]),  # Am7
        (45, [57, 62, 66],     [(0, 74), (4, 71), (8, 69), (12, 66)]),    # D/A
    ),
    bass_program=GM_FINGERED_BASS,
    chord_program=GM_SYNTH_PAD,
    melody_program=GM_ELECTRIC_PIANO,
)

# --- Profile 2: C major pop loop — warm, uplifting, mainstream pop ---
# I - V - vi - IV (C - G - Am - F): the canonical "feel-good" pop progression,
# matching the slight-major / valence~60 lean of the high-danceability tracks.
# Bass walks the chord roots; nylon guitar + strings give an organic, lush bed.
BED_POP = BedProfile(
    name="pop_loop",
    desc="C major I-V-vi-IV pop loop — warm, uplifting, mainstream pop feel",
    chords=(
        (36, [48, 52, 55, 60], [(0, 67), (4, 64), (8, 72), (12, 71)]),   # C
        (43, [50, 55, 59, 62], [(0, 74), (6, 71), (10, 67), (12, 67)]),  # G
        (45, [48, 52, 57, 60], [(0, 72), (4, 69), (8, 64), (12, 64)]),   # Am
        (41, [48, 53, 57, 60], [(0, 69), (4, 65), (8, 72), (12, 65)]),   # F
    ),
    bass_program=GM_FINGERED_BASS,
    chord_program=GM_NYLON_GUITAR,
    melody_program=GM_VIBES,
    melody_vel=70,
)

# --- Profile 3: Em7-C-G-D minor-to-major lift — anthemic, cinematic groove ---
# Em7 - Cmaj7 - G - D (vi7 - IV - I - V in G major): starts pensive, resolves
# bright. Strings pad + Rhodes melody; syncopated bass on a dotted feel for a
# more forward, "driving" low end while still bass-forward.
BED_LIFT = BedProfile(
    name="anthemic_lift",
    desc="Em7-Cmaj7-G-D minor-to-major lift — anthemic, cinematic groove feel",
    chords=(
        (40, [52, 55, 59, 62], [(0, 71), (6, 74), (10, 79), (12, 76)]),  # Em7
        (36, [52, 55, 59, 64], [(0, 76), (4, 72), (8, 67), (12, 67)]),   # Cmaj7
        (43, [50, 55, 59, 62], [(0, 74), (4, 71), (8, 67), (12, 62)]),   # G
        (38, [50, 54, 57, 62], [(0, 69), (4, 66), (8, 74), (12, 62)]),   # D
    ),
    bass_program=GM_FINGERED_BASS,
    chord_program=GM_STRINGS,
    melody_program=GM_ELECTRIC_PIANO,
    bass_steps=(0, 3, 4, 6, 8, 11, 12, 14),  # slightly dotted/pushed feel
    bass_vel=62,
    chord_vel=40,
    melody_vel=72,
)

# --- HERO profile: the user's chosen "real song" bed ---------------------- #
# Dorian harmony (Am7 - D/A) the user liked, the ANTHEMIC profile's pushed/
# dotted bass groove (which the user singled out as "very good"), and a warm
# GRAND PIANO melody (chosen by ear over the electric-piano/guitar candidates).
# This is the recommended default for demos and the Stage-1 study bed.
# Per-section melody motifs over the 2-bar Am7 - D/A loop (one motif per bar).
# VERSE: moderately sparse (2-3 notes/bar), mid register, leaves space.
# CHORUS: denser (5-6 notes/bar), higher register, more stepwise movement -> lift.
_HERO_VERSE_MOTIFS = (
    [(0, 69), (8, 72)],                      # Am7 bar: A4 ... C5
    [(0, 71), (10, 69)],                     # D/A bar: B4 ... A4
)
_HERO_CHORUS_MOTIFS = (
    [(0, 76), (4, 74), (6, 72), (10, 77), (12, 76), (14, 79)],   # Am7 bar: E5-D5-C5-F5-E5-G5
    [(0, 78), (2, 76), (6, 74), (8, 71), (12, 73), (14, 74)],    # D/A bar: F#5-E5-D5-B4-C#5-D5
)

BED_HERO = BedProfile(
    name="hero",
    desc="Dorian Am7-D/A + anthemic pushed bass + warm grand-piano melody; Intro->Verse->Chorus song form",
    chords=(
        (45, [57, 60, 64, 67], [(0, 69), (6, 72), (10, 76), (12, 74)]),  # Am7
        (45, [57, 62, 66],     [(0, 74), (4, 71), (8, 69), (12, 66)]),    # D/A
    ),
    bass_program=GM_FINGERED_BASS,
    chord_program=GM_SYNTH_PAD,
    melody_program=GM_GRAND_PIANO,        # warm grand piano (user's pick)
    bass_steps=(0, 3, 4, 6, 8, 11, 12, 14),  # anthemic pushed/dotted feel
    bass_vel=62,
    chord_vel=44,
    melody_vel=74,
    # Song form: build-up arc. Each entry is one pass of the 2-bar chord loop.
    #   intro  : bed only (bass + chords), melody suppressed (scale 0.0)
    #   verse  : moderately sparse melody
    #   chorus : dense, higher melody (the "lift"), slightly louder
    sections=(
        ("intro",  0.0),
        ("verse",  1.0),
        ("chorus", 1.08),
        ("chorus", 1.08),
    ),
    section_motifs=(
        ("intro",  ((), ())),                 # no melody
        ("verse",  _HERO_VERSE_MOTIFS),
        ("chorus", _HERO_CHORUS_MOTIFS),
    ),
)

# --- HERO-STUDY profile: the FROZEN single-section study bed --------------- #
# For Stage-1 (and Stage-2) experiments the bed must be perceptually time-
# INVARIANT so the only thing that changes across stimuli is the manipulated
# knob (syncopation / density / swing). The full hero song's Intro->Verse->
# Chorus build-up introduces an uncontrolled temporal confound (loudness/
# register ramps over time), which would contaminate causal attribution of a
# groove rating to the knob. So the STUDY bed is a single frozen section:
# the VERSE only, looped as a plain constant bed (sections=None).
#
# Everything else is identical to BED_HERO: same harmony (Am7 - D/A), same
# anthemic pushed bass, same grand-piano timbre, same velocities. The ONLY
# difference is the melody is the constant 2-bar verse motif on every cycle
# (no intro suppression, no chorus lift). This routes through the plain
# build_bed_instruments() loop path -> identical symbolic content every cycle.
BED_HERO_STUDY = BedProfile(
    name="hero_study",
    desc="FROZEN single-section study bed: hero harmony/bass/timbre, constant verse melody loop (time- & knob-invariant)",
    chords=(
        # Same Am7 - D/A harmony + bass roots as BED_HERO, but the per-bar
        # melody is the frozen VERSE motif (moderately sparse, mid register).
        (45, [57, 60, 64, 67], list(_HERO_VERSE_MOTIFS[0])),  # Am7 + verse bar 1
        (45, [57, 62, 66],     list(_HERO_VERSE_MOTIFS[1])),  # D/A + verse bar 2
    ),
    bass_program=GM_FINGERED_BASS,
    chord_program=GM_SYNTH_PAD,
    melody_program=GM_GRAND_PIANO,
    bass_steps=(0, 3, 4, 6, 8, 11, 12, 14),  # anthemic pushed/dotted feel
    bass_vel=62,
    chord_vel=44,
    melody_vel=74,
    sections=None,  # FROZEN: plain constant loop, no song form
)

BED_PROFILES = {
    BED_HERO.name: BED_HERO,
    BED_HERO_STUDY.name: BED_HERO_STUDY,
    BED_DORIAN.name: BED_DORIAN,
    BED_POP.name: BED_POP,
    BED_LIFT.name: BED_LIFT,
}
# DEMO/product default = full structured hero song.
DEFAULT_BED_PROFILE = BED_HERO.name
# STUDY default = frozen single-section verse bed (used by the stimulus grid).
STUDY_BED_PROFILE = BED_HERO_STUDY.name

# Chords sustain on the downbeat of each bar (whole-bar pad).
_BED_CHORD_STEP = 0

# Default soundfont (overridable). Prefer the full FluidR3_GM (~148 MB):
# its sampled instruments are far more realistic than the tiny 6 MB
# TimGM6mb.sf2, which renders thin/"8-bit". Fall back to TimGM6mb only if
# FluidR3 is unavailable.
_DEFAULT_SF2_CANDIDATES = [
    # a soundfont dropped into the project's soundfonts/ folder wins
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "soundfonts", "FluidR3_GM.sf2"),
    "/usr/share/sounds/sf2/FluidR3_GM.sf2",
    "/usr/share/sounds/sf2/default-GM.sf2",
    "/usr/share/sounds/sf2/TimGM6mb.sf2",
    os.path.join(os.path.dirname(pretty_midi.__file__), "TimGM6mb.sf2"),
]


def default_sf2() -> str:
    for p in _DEFAULT_SF2_CANDIDATES:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "No default .sf2 soundfont found. Pass sf2_path explicitly."
    )


# ----------------------------------------------------------------------------
# Parameters (the "knobs"). Step 1 uses tempo + a fixed 8th-hat backbone.
# Later steps activate event_density, swing_amount, syncopation_level,
# microtiming_variance_ms.
# ----------------------------------------------------------------------------
@dataclass
class GrooveParams:
    # --- timing / structure ---
    tempo_bpm: float = 115.0          # knob 5
    bars: int = 1                     # core pattern length
    target_seconds: float = 30.0      # loop out to this duration
    seed: int = 0                     # seeds all stochastic elements

    # --- active knobs ---
    event_density: int = 8            # knob 1: target onsets/bar (step 2)
    swing_amount: float = 1.0         # knob 2: swing ratio 1.0(=50:50)..2.0(=2:1); 16th-level (step 2)
    swing_level: str = "16"           # "8" or "16": which subdivision is swung

    # --- knobs added in later steps (placeholders, inert for now) ---
    syncopation_level: float = 0.0    # knob 3: 0..1 (step 3)
    microtiming_variance_ms: float = 0.0  # knob 4: SD ms, seeded jitter (step 4)

    # --- fixed musical bed (NOT a knob; on/off + which song-bed only) ---
    with_bed: bool = True             # add constant bass+chords+melody under the kit
    bed_profile: str = DEFAULT_BED_PROFILE  # which BedProfile (song) to embed

    # --- genre-aware drum groove (NOT a knob; demo/song path only) ---
    # When None (default) the canonical research backbeat is used so the
    # stimulus-grid / study path is COMPLETELY unchanged. When set to a key in
    # DRUM_STYLES, build_core lays down that genre's idiomatic groove (distinct
    # kick/snare/clap/hat/perc placement + kit) instead of the generic backbeat.
    # The groove knob (density + syncopation) still modulates it on top.
    drum_style: str = None

    def as_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------
# Genre-aware drum groove templates (used only when GrooveParams.drum_style is
# set -- i.e. the UI / song-demo path, NOT the frozen study stimuli).
#
# Each template encodes the IDIOMATIC kick/snare/hat/extra-percussion placement
# that makes a genre instantly recognizable, plus a sensible default swing and a
# backbeat voice (snare vs clap vs rim) and hat voice. Steps are 16th positions
# in a bar (0..15). The density knob still adds/removes hat subdivisions and the
# syncopation knob still displaces the kick on top of these, so the groove knob
# remains fully active -- the template just sets the genre's rhythmic signature.
#
# Fields:
#   kick        : base kick steps (genre's signature kick pattern)
#   backbeat    : steps for the backbeat voice (usually 4 & 12)
#   back_voice  : which pitch plays the backbeat (SNARE / HANDCLAP / SIDE_STICK)
#   back_layer  : optional 2nd pitch layered on the backbeat (e.g. clap+snare)
#   hat_voice   : CLOSED_HAT or RIDE for the subdivision voice
#   hat_base    : hat steps ALWAYS present (genre's core hat feel); density adds more
#   swing       : default 16th-swing ratio (1.0 straight .. ~1.6); knob can override
#   ghost       : quiet ghost-snare steps for the genre's internal groove
#   perc        : list of (step, pitch, vel) extra percussion hits per bar
#   open_hat    : steps that get an OPEN hat accent (e.g. the 'and' lift)
# ----------------------------------------------------------------------------
DRUM_STYLES: dict[str, dict] = {
    # Hip-hop / boom-bap: punchy kick on 1 + the 'a' of 2 push, hard backbeat
    # snare on 2 & 4, swung lazy hats, sparse ghost notes. Laid-back swing.
    "hip-hop/rap": dict(
        kick=[0, 7, 10], backbeat=[4, 12], back_voice=SNARE, back_layer=None,
        hat_voice=CLOSED_HAT, hat_base=[0, 2, 4, 6, 8, 10, 12, 14],
        swing=1.5, ghost=[15], perc=[], open_hat=[14],
    ),
    # R&B / neo-soul: soft kick, RIM/side-stick + light snare backbeat, smooth
    # 16th hats, gentle swing, a ghost snare lead-in. Behind-the-beat feel.
    "r&b/soul": dict(
        kick=[0, 6, 8], backbeat=[4, 12], back_voice=SNARE, back_layer=SIDE_STICK,
        hat_voice=CLOSED_HAT, hat_base=[0, 2, 4, 6, 8, 10, 12, 14],
        swing=1.25, ghost=[7, 11], perc=[], open_hat=[],
    ),
    # Pop / dance (Billie Jean family): four-on-the-floor kick, snare+clap stack
    # on the backbeat, steady straight 16th hats, an open-hat lift on every 'and'.
    "pop": dict(
        kick=[0, 4, 8, 12], backbeat=[4, 12], back_voice=SNARE, back_layer=HANDCLAP,
        hat_voice=CLOSED_HAT, hat_base=[0, 2, 4, 6, 8, 10, 12, 14],
        swing=1.0, ghost=[], perc=[], open_hat=[2, 6, 10, 14],
    ),
    # Latin / salsa: clave-driven, busy cowbell/conga groove, kick on the tumbao
    # anticipations rather than four-on-floor, side-stick cross-rhythm.
    "latin/salsa": dict(
        # Lightened salsa: fewer, cleaner hits so the groove breathes instead of
        # sounding like a wall of percussion. hat_base thinned from constant 8ths
        # to quarter-note cascara, perc hits roughly halved (cowbell on the beat +
        # a sparse conga tumbao + the clave cross-stick). event_density can still
        # thicken the hats from here if you want the busier montuno feel.
        kick=[0, 8], backbeat=[], back_voice=SIDE_STICK, back_layer=None,
        hat_voice=CLOSED_HAT, hat_base=[0, 4, 8, 12],
        swing=1.0, ghost=[],
        perc=[(0, COWBELL, 86), (8, COWBELL, 86),
              (6, LOW_CONGA, 82), (14, LOW_CONGA, 82),
              (4, SIDE_STICK, 84), (10, SIDE_STICK, 78)],  # 2-3 clave cross-stick
        open_hat=[],
    ),
    # Classic rock: solid kick 1 & 'and of 3', big snare on 2 & 4, driving
    # straight 8th hats, the occasional open-hat crash-lift. No swing.
    "classic-rock": dict(
        kick=[0, 8, 11], backbeat=[4, 12], back_voice=SNARE, back_layer=None,
        hat_voice=CLOSED_HAT, hat_base=[0, 2, 4, 6, 8, 10, 12, 14],
        swing=1.0, ghost=[], perc=[], open_hat=[14],
    ),
    # Metal: double-kick gallop, hard snare backbeat, relentless straight hats.
    "metal": dict(
        kick=[0, 2, 4, 6, 8, 10, 12, 14], backbeat=[4, 12], back_voice=SNARE,
        back_layer=None, hat_voice=CLOSED_HAT, hat_base=[0, 2, 4, 6, 8, 10, 12, 14],
        swing=1.0, ghost=[], perc=[], open_hat=[],
    ),
}


# ----------------------------------------------------------------------------
# Pattern builder
# ----------------------------------------------------------------------------
class PatternBuilder:
    """Builds a PrettyMIDI drum pattern from GrooveParams.

    Step 1 implements the canonical backbeat skeleton that all later knobs
    perturb FROM (keeps the tactus / beat salience stable while knobs vary):
        Kick  : beats 1 & 3
        Snare : beats 2 & 4  (the backbeat)
        Hat   : straight 8th notes
    """

    def __init__(self, params: GrooveParams):
        self.p = params
        self.rng = np.random.default_rng(params.seed)
        self._realized_jitters: list[float] = []  # ms, for manipulation check

    def realized_microtiming_rms_ms(self) -> float:
        """RMS of realized timing jitter after a build (manipulation check)."""
        if not self._realized_jitters:
            return 0.0
        arr = np.asarray(self._realized_jitters)
        return float(np.sqrt(np.mean(arr ** 2)))

    @property
    def sec_per_beat(self) -> float:
        return 60.0 / self.p.tempo_bpm

    @property
    def bar_seconds(self) -> float:
        return 4 * self.sec_per_beat  # 4/4

    def _jitter(self, t: float) -> float:
        """Apply seeded Gaussian microtiming jitter (knob 4).

        microtiming_variance_ms is the SD of timing deviation in ms. Applied
        AFTER swing, so it is random noise AROUND the (possibly swung) grid,
        not a systematic shift. SD=0 -> mechanically perfect. Realized jitters
        are recorded for the manipulation check.
        """
        sd_ms = float(self.p.microtiming_variance_ms)
        if sd_ms <= 0.0:
            return t
        dev = float(self.rng.normal(0.0, sd_ms / 1000.0))
        self._realized_jitters.append(dev * 1000.0)  # store in ms
        return max(0.0, t + dev)

    def _add(self, drum, pitch, t, dur=0.09, vel=100):
        drum.notes.append(
            pretty_midi.Note(velocity=int(vel), pitch=pitch,
                             start=float(self._jitter(t)), end=float(t + dur))
        )

    # --- step-grid helpers (16 steps per bar = 16th-note resolution) ---
    STEPS_PER_BAR = 16

    def _step_time(self, bar_t: float, step: int) -> float:
        """Onset time of a 16th-note step, with swing applied.

        swing_amount r delays the 'off' subdivision so the beat-pair splits
        at fraction r/(1+r) instead of 1/2. Applied at the 8th or 16th level
        per swing_level. Straight when r == 1.0.
        """
        spb = self.sec_per_beat
        sixteenth = spb / 4.0
        t = bar_t + step * sixteenth
        r = float(self.p.swing_amount)
        if r <= 1.0:
            return t
        frac = r / (1.0 + r)  # 0.5 (straight) .. 0.667 (2:1)
        if self.p.swing_level == "16":
            # odd 16th steps (the 'e' and 'a') are the swung off-positions
            if step % 2 == 1:
                pair_start = bar_t + (step - 1) * sixteenth
                return pair_start + 2 * sixteenth * frac
            return t
        else:  # "8": swing the 'and' (8th off-beats) = steps 2,6,10,14
            if step % 4 == 2:
                pair_start = bar_t + (step - 2) * sixteenth
                return pair_start + 2 * (2 * sixteenth) * frac
            return t

    def _density_steps(self) -> tuple[list[int], list[int]]:
        """Allocate the onset budget to (hat_steps, ghost_steps).

        Kick(2) + snare(2) = 4 baseline onsets/bar. Remaining budget fills
        hats on metrically-ranked positions first (quarters -> 8ths -> 16ths,
        16 slots max); any budget beyond 16 hats spills into ghost snares on
        the empty off-positions, extending the ceiling toward ~24 onsets/bar.
        """
        budget = max(0, int(self.p.event_density) - 4)  # 4 = kick+snare baseline
        quarters = [0, 4, 8, 12]
        eighths = [2, 6, 10, 14]
        sixteenths = [1, 3, 5, 7, 9, 11, 13, 15]
        ranked = quarters + eighths + sixteenths
        hat_steps = sorted(ranked[:min(budget, 16)])
        # spill into ghost snares on off-16th positions not on the backbeat
        ghost_budget = max(0, budget - 16)
        ghost_pool = [1, 3, 5, 7, 9, 11, 13, 15]  # off-16ths
        ghost_steps = sorted(ghost_pool[:ghost_budget])
        return hat_steps, ghost_steps

    def build_core(self) -> pretty_midi.PrettyMIDI:
        """Build the 1-(or N-)bar core pattern (no loop-out yet).

        Backbeat skeleton (kick 1&3, snare 2&4) is preserved for beat
        salience; event_density controls hat subdivision; swing_amount
        shifts off-grid steps.

        When GrooveParams.drum_style is set (UI / song-demo path), delegate to
        the genre-aware builder instead -- the groove knob still modulates it.
        """
        if self.p.drum_style and self.p.drum_style in DRUM_STYLES:
            return self._build_core_genre(DRUM_STYLES[self.p.drum_style])
        pm = pretty_midi.PrettyMIDI(initial_tempo=self.p.tempo_bpm)
        drum = pretty_midi.Instrument(program=0, is_drum=True, name="kit")
        hat_steps, ghost_steps = self._density_steps()

        kick_steps = self._kick_steps()
        snare_steps = self._snare_steps()
        for bar in range(self.p.bars):
            bar_t = bar * self.bar_seconds
            # kick (placement set by syncopation_level)
            for s in kick_steps:
                self._add(drum, KICK, self._step_time(bar_t, s), vel=110)
            # snare (backbeat, displaced only at high syncopation)
            for s in snare_steps:
                self._add(drum, SNARE, self._step_time(bar_t, s), vel=118)
            # hats by density; accent on-beat hats louder than off-beat
            for s in hat_steps:
                vel = 82 if s % 4 == 0 else (74 if s % 2 == 0 else 64)
                self._add(drum, CLOSED_HAT, self._step_time(bar_t, s), vel=vel)
            # ghost snares (quiet) to extend density ceiling
            for s in ghost_steps:
                self._add(drum, GHOST_SNARE, self._step_time(bar_t, s), vel=45)

        pm.instruments.append(drum)
        return pm

    # ----- genre-aware core (UI / song-demo path only) -----
    def _build_core_genre(self, style: dict) -> pretty_midi.PrettyMIDI:
        """Build a genre-idiomatic drum groove from a DRUM_STYLES template.

        This is ONLY used when GrooveParams.drum_style is set (the UI / song
        path). The frozen study-stimulus path leaves drum_style=None and keeps
        the canonical backbeat in build_core.

        IMPORTANT: the genre template only sets the *starting pose* (signature
        kit + a sensible default tempo/swing). Groove itself is NOT driven by
        syncopation alone -- the literature (and our Sophia analysis) ranks the
        load-bearing knobs as Tier-1 = event_density, tempo, beat salience, and
        Tier-2 = syncopation, swing. ALL of these remain live on top of any
        genre, so the groove instrument is fully intact regardless of style:
          * event_density ADDS extra hat subdivisions beyond the template's
            hat_base (never removes the genre's signature hats).
          * syncopation_level DISPLACES the kick toward weak positions, exactly
            like the study path (_SYNC_KICK), so the knob's manipulation is
            identical regardless of genre.
          * swing: the template sets a default genre swing; an explicit
            swing_amount > 1.0 on the knob overrides it (knob wins).
        """
        # Swing: template default applies unless the knob explicitly asks for
        # MORE swing (Tier-2 knob; knob wins). We set self.p.swing_amount so
        # _step_time
        # (which reads it) swings consistently for every voice, then restore.
        knob_swing = float(self.p.swing_amount)
        eff_swing = knob_swing if knob_swing > 1.0 else float(style.get("swing", 1.0))
        saved_swing = self.p.swing_amount
        self.p.swing_amount = eff_swing
        try:
            pm = pretty_midi.PrettyMIDI(initial_tempo=self.p.tempo_bpm)
            drum = pretty_midi.Instrument(program=0, is_drum=True, name="kit")

            kick_steps = self._genre_kick_steps(style)
            back_steps = list(style.get("backbeat", []))
            back_voice = style.get("back_voice", SNARE)
            back_layer = style.get("back_layer", None)
            hat_voice = style.get("hat_voice", CLOSED_HAT)
            hat_steps = self._genre_hat_steps(style)
            ghost_steps = list(style.get("ghost", []))
            perc = list(style.get("perc", []))
            open_hat = list(style.get("open_hat", []))

            for bar in range(self.p.bars):
                bar_t = bar * self.bar_seconds
                # kick (displaced by syncopation knob)
                for s in kick_steps:
                    self._add(drum, KICK, self._step_time(bar_t, s), vel=110)
                # backbeat voice (+ optional stacked layer, e.g. snare+clap)
                for s in back_steps:
                    self._add(drum, back_voice, self._step_time(bar_t, s), vel=118)
                    if back_layer is not None:
                        self._add(drum, back_layer, self._step_time(bar_t, s), vel=100)
                # hats (template base + density-driven extras)
                for s in hat_steps:
                    vel = 82 if s % 4 == 0 else (74 if s % 2 == 0 else 64)
                    self._add(drum, hat_voice, self._step_time(bar_t, s), vel=vel)
                # open-hat accents (the genre's 'and' lift)
                for s in open_hat:
                    self._add(drum, OPEN_HAT, self._step_time(bar_t, s), vel=86)
                # ghost snares (quiet internal groove)
                for s in ghost_steps:
                    self._add(drum, GHOST_SNARE, self._step_time(bar_t, s), vel=45)
                # genre percussion (cowbell / congas / clave cross-stick)
                for (s, pitch, vel) in perc:
                    self._add(drum, pitch, self._step_time(bar_t, s), vel=vel)

            pm.instruments.append(drum)
            return pm
        finally:
            self.p.swing_amount = saved_swing

    def _genre_kick_steps(self, style: dict) -> list[int]:
        """Genre kick pattern, displaced toward weak positions by syncopation.

        At L0 the template's own kick pattern is used unchanged. As the
        syncopation knob rises, we fold in the study-path displacement
        (_SYNC_KICK) so the manipulation matches the research instrument, while
        still keeping the genre's signature kicks present. Metal's gallop and
        Latin's tumbao are left intact at L0/L1 so the genre stays recognizable.
        """
        base = list(style.get("kick", [0, 8]))
        sb = self._sync_bin()
        if sb == 0:
            return base
        # union of the genre kick and the study displacement targets, so the
        # knob pushes onto weak positions without erasing the genre identity
        disp = self._SYNC_KICK.get(sb, base)
        return sorted(set(base) | set(disp))

    def _genre_hat_steps(self, style: dict) -> list[int]:
        """Template hat_base, with the density knob ADDING finer subdivisions.

        The genre's signature hats (hat_base) are always present. event_density
        above the genre baseline fills in the remaining 16th-note slots (ranked
        off-beats first) so turning the knob up thickens the hats without
        changing the genre's core feel.
        """
        base = sorted(set(style.get("hat_base", [0, 4, 8, 12])))
        all_slots = list(range(self.STEPS_PER_BAR))
        extra_pool = [s for s in [1, 3, 5, 7, 9, 11, 13, 15] if s not in base]
        # density measured as desired hats/bar; add beyond what base provides
        want_extra = max(0, int(self.p.event_density) - len(base) - 4)
        extra = extra_pool[:min(want_extra, len(extra_pool))]
        return sorted(set(base) | set(extra))

    def onset_count_per_bar(self) -> int:
        """Manipulation check: actual onsets in the first bar."""
        core = self.build_core()
        notes = core.instruments[0].notes
        return sum(1 for n in notes if n.start < self.bar_seconds - 1e-6)

    # ----- syncopation (knob 3) -----
    # Placements calibrated so the salience-weighted, 2-bar Witek-style index
    # (see syncopation_index) lands in the literature-recommended bands from
    # groove_knob_literature.md:
    #   L0  S = 0   (band 0-4,   straight)
    #   L1  S = 16  (band 12-18, light)
    #   L2  S = 32  (band 26-34, sweet-spot apex ~30)
    #   L3  S = 49  (band 48-65, heavy)
    # syncopation_level (0..1) maps to 4 discrete levels at <=0, <=0.34, <=0.67, else.
    # (16-step bar; kick/snare steps. Snare backbeat 4&12 kept at L0-L2 for beat
    # salience; displaced at L3 for the heavy feel.)
    _SYNC_KICK = {0: [0, 8], 1: [0, 1, 5], 2: [1, 5, 13], 3: [1, 3, 7, 13]}
    _SYNC_SNARE = {0: [4, 12], 1: [4, 12], 2: [4, 12], 3: [5, 11]}

    def _sync_bin(self) -> int:
        lvl = float(self.p.syncopation_level)
        if lvl <= 0.0:
            return 0
        if lvl <= 0.34:
            return 1
        if lvl <= 0.67:
            return 2
        return 3

    def _kick_steps(self) -> list[int]:
        """Kick placement, displaced toward weak positions by syncopation_level.

        L0 -> kicks on strong beats (0, 8) = no syncopation. As the level rises,
        kicks move to weak steps whose following stronger step is left empty,
        raising the salience-weighted Witek index into the target bands.
        """
        return list(self._SYNC_KICK[self._sync_bin()])

    def _snare_steps(self) -> list[int]:
        """Snare backbeat (kept 4 & 12 for salience); displaced at heavy sync."""
        return list(self._SYNC_SNARE[self._sync_bin()])

    def syncopation_index(self) -> float:
        """Witek et al. (2014) syncopation index: Longuet-Higgins & Lee metric
        weights, ADDITIONALLY weighted by drum-instrument salience (bass drum >
        snare), summed over a 2-bar window. Hi-hat is excluded (per Witek 2014).

        The instrument-salience weighting is what lets the index reach the
        0-81 scale used in the literature (a pure L&L weight difference caps at
        ~5 per event). A note-onset is syncopated when, before the next onset,
        there is a REST on a metrically STRONGER position; the score is
        (strongest_rest_weight - onset_weight) * onset_salience. This is the
        manipulation check the manifest logs.
        """
        kick = self._kick_steps()
        snare = self._snare_steps()
        n = 16
        # Build a 2-bar (32-step) onset map -> salience (most salient voice wins).
        salience = {}
        for s in kick:
            for b in (0, 1):
                p = b * n + s
                salience[p] = max(salience.get(p, 0.0), _SYNC_SALIENCE_KICK)
        for s in snare:
            for b in (0, 1):
                p = b * n + s
                salience[p] = max(salience.get(p, 0.0), _SYNC_SALIENCE_SNARE)
        union = set(salience)
        if not union:
            return 0.0
        total = 2 * n
        score = 0.0
        for s in sorted(union):
            w_here = METRIC_WEIGHTS[s % n]
            best_rest_w = 0
            for d in range(1, total):
                pos = (s + d) % total
                if pos in union:
                    break
                best_rest_w = max(best_rest_w, METRIC_WEIGHTS[pos % n])
            diff = best_rest_w - w_here
            if diff > 0:
                score += diff * salience[s]
        return float(round(score, 1))

    # ----- fixed musical bed -----
    def _grid_step_time(self, bar_t: float, step: int) -> float:
        """Raw (un-swung, un-jittered) onset time of a 16th step.

        The bed deliberately bypasses _step_time and _jitter so that NO drum
        knob can perturb it. Its only tempo dependence is sec_per_beat, shared
        with the drums so they stay in time.
        """
        return bar_t + step * (self.sec_per_beat / 4.0)

    @staticmethod
    def _metric_accent(step: int) -> float:
        """Metric accent weight for a 16th step (0..15). Strong beats louder."""
        if step % 16 == 0:   # bar downbeat
            return 1.00
        if step % 8 == 0:    # beat 3
            return 0.90
        if step % 4 == 0:    # beats 2 & 4
            return 0.82
        if step % 2 == 0:    # off-beat 8ths
            return 0.66
        return 0.55          # 16th subdivisions

    def _emit_humanized_comp(self, chords, tones, bar_t, sixteenth, cp,
                             base_chord_vel, bar):
        """Emit a natural, genre-correct rhythmic comp for one bar.

        Replaces the single sustained block chord with a comp that has metric
        velocity accents, slight timing jitter, a strum stagger across chord
        tones, and (for ``sustain_accent``) a ring-on-strong / light-stab-on-weak
        phrasing. Driven by the per-genre ``comp_plan`` so pop/rock stop sounding
        like a quantized machine-gun.
        """
        if not tones:
            return
        steps = cp.get("steps") or [_BED_CHORD_STEP]
        comp_style = cp.get("comp_style", "block")
        humanize = cp.get("humanize", True)
        base_vel = cp.get("base_vel", base_chord_vel)
        strum_s = (cp.get("strum_ms", 0.0) / 1000.0) if humanize else 0.0
        # reproducible jitter, decorrelated per bar
        rng = random.Random(cp.get("seed", 0) * 131 + bar)
        tones_sorted = sorted(tones)
        # tresillo / staccato accent grid (matches genre_styles._TRESILLO)
        tresillo = {0, 3, 6, 8, 11, 14}
        # arp engine: pre-walk one chord-tone per comp step (synth-pop pluck)
        arp_seq = None
        if comp_style == "arp" and tones_sorted:
            ladder = tones_sorted + [tones_sorted[0] + 12]
            up_down = ladder + ladder[-2:0:-1]
            up_down = up_down or ladder
            arp_seq = [up_down[i % len(up_down)] for i in range(len(steps))]

        for si, s in enumerate(steps):
            strong = (s % 4 == 0)
            if comp_style == "arp":
                # synth-pop pluck: ONE tone per step, short, walking the chord
                voices = [arp_seq[si]] if arp_seq else tones_sorted
                dur = sixteenth * 0.9
            elif comp_style == "staccato_chug":
                # palm-muted power-chord stab: short, hard, space between hits
                voices = tones_sorted
                dur = sixteenth * (0.75 if strong else 0.55)
            elif comp_style == "sustain_accent":
                if strong:
                    voices = tones_sorted          # full chord rings
                    dur = sixteenth * 4.0
                else:
                    # light stab: upper voices only, short
                    voices = tones_sorted[1:] if len(tones_sorted) > 1 else tones_sorted
                    dur = sixteenth * 1.4
            else:  # block comp on each listed step
                voices = tones_sorted
                dur = sixteenth * 2.0

            t0 = self._grid_step_time(bar_t, s)
            if humanize:
                vel0 = base_vel * self._metric_accent(s)
                if comp_style in ("arp", "staccato_chug") and s in tresillo:
                    vel0 *= 1.12
                vel0 += rng.uniform(-6, 6)
                t0 += rng.uniform(-0.008, 0.008)
            else:
                vel0 = base_vel
            for vi, p in enumerate(voices):
                ts = max(0.0, t0 + vi * strum_s)   # clamp >=0 (fluidsynth requirement)
                v = int(max(1, min(127, vel0 - vi * 2)))  # upper voices softer
                chords.notes.append(pretty_midi.Note(
                    velocity=v, pitch=int(p), start=ts, end=ts + dur))

    def build_bed_instruments(self) -> list[pretty_midi.Instrument]:
        """Build the constant bass / chord / melody bed (1 4-bar cycle).

        Returns three melodic Instruments (is_drum=False, dedicated programs).
        Identical symbolic content for every GrooveParams regardless of knobs.
        """
        prof = BED_PROFILES[self.p.bed_profile]
        spb = self.sec_per_beat
        sixteenth = spb / 4.0
        bass = pretty_midi.Instrument(program=prof.bass_program, is_drum=False, name="bed_bass")
        chords = pretty_midi.Instrument(program=prof.chord_program, is_drum=False, name="bed_chords")
        melody = pretty_midi.Instrument(program=prof.melody_program, is_drum=False, name="bed_melody")

        n_bed_bars = len(prof.chords)
        for bar in range(n_bed_bars):
            bar_t = bar * self.bar_seconds
            root, tones, motif = prof.chords[bar]
            # Bass: steady root pulse on the chosen steps.
            for s in prof.bass_steps:
                t = self._grid_step_time(bar_t, s)
                bass.notes.append(pretty_midi.Note(
                    velocity=prof.bass_vel, pitch=root,
                    start=t, end=t + 1.9 * sixteenth))
            # Chords: one sustained pad per bar (whole bar).
            t0 = self._grid_step_time(bar_t, _BED_CHORD_STEP)
            for p in tones:
                chords.notes.append(pretty_midi.Note(
                    velocity=prof.chord_vel, pitch=p,
                    start=t0, end=t0 + self.bar_seconds - 0.02))
            # Melody motif within the bar.
            for (s, p) in motif:
                t = self._grid_step_time(bar_t, s)
                melody.notes.append(pretty_midi.Note(
                    velocity=prof.melody_vel, pitch=p,
                    start=t, end=t + 1.8 * sixteenth))
        return [bass, chords, melody]

    def build_bed_song(self) -> list[pretty_midi.Instrument]:
        """Build a STRUCTURED bed song from prof.sections (intro/verse/chorus...).

        Bass and chords are constant per bar (identical to the looped bed);
        only the MELODY changes per section, per the section's motif set and
        velocity scale. Returns three Instruments spanning the whole song
        (= len(sections) passes of the chord loop). Knob-invariant.
        """
        prof = BED_PROFILES[self.p.bed_profile]
        spb = self.sec_per_beat
        sixteenth = spb / 4.0
        motif_map = {name: motifs for (name, motifs) in prof.section_motifs}
        n_loop_bars = len(prof.chords)

        bass = pretty_midi.Instrument(program=prof.bass_program, is_drum=False, name="bed_bass")
        chords = pretty_midi.Instrument(program=prof.chord_program, is_drum=False, name="bed_chords")
        melody = pretty_midi.Instrument(program=prof.melody_program, is_drum=False, name="bed_melody")

        for sec_idx, (sec_name, mel_scale) in enumerate(prof.sections):
            sec_motifs = motif_map[sec_name]
            sec_t0 = sec_idx * n_loop_bars * self.bar_seconds
            for bar in range(n_loop_bars):
                bar_t = sec_t0 + bar * self.bar_seconds
                root, tones, _default_motif = prof.chords[bar]
                # Bass (constant)
                for s in prof.bass_steps:
                    t = self._grid_step_time(bar_t, s)
                    bass.notes.append(pretty_midi.Note(
                        velocity=prof.bass_vel, pitch=root,
                        start=t, end=t + 1.9 * sixteenth))
                # Chords (constant per bar). Two modes:
                #  - comp_plan present -> humanized, genre-correct rhythmic comp
                #  - else -> classic single sustained block chord (study/legacy)
                cp = prof.comp_plan
                if cp:
                    self._emit_humanized_comp(chords, tones, bar_t, sixteenth,
                                              cp, prof.chord_vel, bar)
                else:
                    t0 = self._grid_step_time(bar_t, _BED_CHORD_STEP)
                    for p in tones:
                        chords.notes.append(pretty_midi.Note(
                            velocity=prof.chord_vel, pitch=p,
                            start=t0, end=t0 + self.bar_seconds - 0.02))
                # Melody (section-specific)
                if mel_scale > 0.0:
                    vel = max(1, min(127, int(round(prof.melody_vel * mel_scale))))
                    for (s, pitch) in sec_motifs[bar]:
                        t = self._grid_step_time(bar_t, s)
                        melody.notes.append(pretty_midi.Note(
                            velocity=vel, pitch=pitch,
                            start=t, end=t + 1.8 * sixteenth))
        return [bass, chords, melody]

    @property
    def has_song_form(self) -> bool:
        return BED_PROFILES[self.p.bed_profile].sections is not None

    @property
    def bed_period_seconds(self) -> float:
        """Length of one full bed cycle.

        For a plain looped bed = number of chord-loop bars. For a structured
        song = the whole song (len(sections) passes of the chord loop).
        """
        prof = BED_PROFILES[self.p.bed_profile]
        loop_bars = len(prof.chords)
        if prof.sections is not None:
            return len(prof.sections) * loop_bars * self.bar_seconds
        return loop_bars * self.bar_seconds

    def build_looped(self) -> pretty_midi.PrettyMIDI:
        """Repeat the core seamlessly to >= target_seconds."""
        core = self.build_core()
        n_reps = max(1, int(np.ceil(self.p.target_seconds / self.bar_seconds
                                    / self.p.bars)))
        pm = pretty_midi.PrettyMIDI(initial_tempo=self.p.tempo_bpm)
        drum = pretty_midi.Instrument(program=0, is_drum=True, name="kit")
        core_drum = core.instruments[0]
        period = self.p.bars * self.bar_seconds
        total_seconds = n_reps * period
        for r in range(n_reps):
            off = r * period
            for n in core_drum.notes:
                drum.notes.append(
                    pretty_midi.Note(velocity=n.velocity, pitch=n.pitch,
                                     start=n.start + off, end=n.end + off)
                )
        pm.instruments.append(drum)

        # Tile the FIXED musical bed across the same duration. The bed cycle
        # (4 bars) is independent of the drum core length; we repeat it enough
        # times to cover the whole loop. Symbolic content per cycle is constant.
        if self.p.with_bed:
            bed_period = self.bed_period_seconds
            bed_reps = max(1, int(np.ceil(total_seconds / bed_period)))
            # Structured song (intro/verse/chorus) if the profile defines one,
            # otherwise the classic single-loop bed.
            bed_protos = (self.build_bed_song() if self.has_song_form
                          else self.build_bed_instruments())
            for proto in bed_protos:
                inst = pretty_midi.Instrument(
                    program=proto.program, is_drum=False, name=proto.name)
                for r in range(bed_reps):
                    off = r * bed_period
                    for n in proto.notes:
                        inst.notes.append(pretty_midi.Note(
                            velocity=n.velocity, pitch=n.pitch,
                            start=n.start + off, end=n.end + off))
                pm.instruments.append(inst)
        return pm


# ----------------------------------------------------------------------------
# Render path (deterministic; constant timbre + constant loudness)
# ----------------------------------------------------------------------------
def render_wav(pm: pretty_midi.PrettyMIDI, out_wav: str,
               sf2_path: str | None = None, fs: int = FS,
               target_lufs: float = TARGET_LUFS) -> dict:
    """Render a PrettyMIDI object to a loudness-normalized WAV.

    Returns a metadata dict (duration, measured/target LUFS, peak).
    """
    sf2 = sf2_path or default_sf2()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # silence sf2_path deprecation note
        audio = pm.fluidsynth(fs=fs, sf2_path=sf2)
    if audio.size == 0:
        raise RuntimeError("FluidSynth returned empty audio.")

    meter = pyln.Meter(fs)
    measured = meter.integrated_loudness(audio)
    norm = pyln.normalize.loudness(audio, measured, target_lufs)

    # Prevent clipping without changing relative loudness ordering:
    peak = float(np.max(np.abs(norm))) if norm.size else 0.0
    if peak > 1.0:
        norm = norm / peak * 0.999
        peak = float(np.max(np.abs(norm)))

    os.makedirs(os.path.dirname(os.path.abspath(out_wav)), exist_ok=True)
    sf.write(out_wav, norm.astype(np.float32), fs)
    return {
        "wav_path": out_wav,
        "duration_s": round(audio.size / fs, 3),
        "measured_lufs_pre_norm": round(float(measured), 2),
        "target_lufs": target_lufs,
        "peak_post_norm": round(peak, 4),
    }


def generate(params: GrooveParams, out_stem: str,
             sf2_path: str | None = None) -> dict:
    """End-to-end: params -> .mid + loudness-normalized .wav + metadata."""
    pb = PatternBuilder(params)
    pm = pb.build_looped()
    mid_path = out_stem + ".mid"
    os.makedirs(os.path.dirname(os.path.abspath(mid_path)), exist_ok=True)
    pm.write(mid_path)
    meta = render_wav(pm, out_stem + ".wav", sf2_path=sf2_path)
    meta["mid_path"] = mid_path
    meta.update(params.as_dict())
    return meta


if __name__ == "__main__":
    # Smoke test: render the step-1 backbeat at 115 BPM.
    _here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _stem = os.path.join(_here, "outputs", "audio", "step1_backbeat")
    m = generate(GrooveParams(tempo_bpm=115.0, target_seconds=8.0, seed=0),
                 out_stem=_stem)
    print("STEP 1 OK")
    for k in ("wav_path", "duration_s", "measured_lufs_pre_norm",
              "peak_post_norm", "tempo_bpm"):
        print(f"  {k}: {m[k]}")
