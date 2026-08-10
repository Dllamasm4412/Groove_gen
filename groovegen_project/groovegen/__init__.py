"""GrooveGen package — re-exports the core API from groovegen.groovegen.

This lets callers do either:
    from groovegen import GrooveParams, PatternBuilder, generate, ...
or:
    from groovegen.groovegen import GrooveParams
"""
from .groovegen import (  # noqa: F401
    GrooveParams,
    PatternBuilder,
    BedProfile,
    BED_PROFILES,
    BED_HERO,
    BED_HERO_STUDY,
    BED_DORIAN,
    BED_POP,
    BED_LIFT,
    DEFAULT_BED_PROFILE,
    STUDY_BED_PROFILE,
    generate,
    render_wav,
    default_sf2,
    FS,
    TARGET_LUFS,
)
from . import dlbed
from . import genre_styles  # noqa: F401  (DL-bed adapter: midi_bed_to_profile, register_dl_bed, render_genre_demo)
