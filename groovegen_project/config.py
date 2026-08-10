"""Central path configuration for the GrooveGen project.

All scripts and notebooks import paths from here so the project is portable:
clone the folder anywhere (local, Colab, a server) and everything resolves
relative to the project root. No absolute /home/... paths anywhere.
"""
from pathlib import Path

# Project root = the folder that contains this file.
ROOT = Path(__file__).resolve().parent

DATA = ROOT / "data"
SOPHIA = ROOT / "sophia"
OUTPUTS = ROOT / "outputs"
AUDIO_OUT = OUTPUTS / "audio"
FIG_OUT = OUTPUTS / "figures"
SOUNDFONTS = ROOT / "soundfonts"

# Input data files
SURVEY_CSV = DATA / "survey_and_music_data_N122.csv"
TRACK_FEATURES_CSV = DATA / "track_features.csv"
DATA_DICTIONARY_CSV = DATA / "data_dictionary.csv"

# Analysis outputs
ANALYSIS_JSON = SOPHIA / "analysis_results.json"
TRAIT_MODERATOR_JSON = SOPHIA / "trait_moderator_results.json"
LAYER1_FIG = FIG_OUT / "layer1_validation.png"
LAYER2_FIG = FIG_OUT / "layer2_betas.png"

for d in (OUTPUTS, AUDIO_OUT, FIG_OUT, SOUNDFONTS):
    d.mkdir(parents=True, exist_ok=True)


def find_soundfont() -> str:
    """Return a path to a General-MIDI .sf2 soundfont.

    Preference order:
      1. A FluidR3_GM.sf2 placed in the project's soundfonts/ folder
      2. The system FluidR3_GM.sf2 (high quality, ~148 MB)
      3. The system default-GM.sf2
      4. The small TimGM6mb.sf2 (low quality fallback)
    """
    candidates = [
        SOUNDFONTS / "FluidR3_GM.sf2",
        Path("/usr/share/sounds/sf2/FluidR3_GM.sf2"),
        Path("/usr/share/sounds/sf2/default-GM.sf2"),
        Path("/usr/share/sounds/sf2/TimGM6mb.sf2"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    raise FileNotFoundError(
        "No .sf2 soundfont found. Download FluidR3_GM.sf2 into "
        f"{SOUNDFONTS} (see README), or install fluid-soundfont-gm."
    )
