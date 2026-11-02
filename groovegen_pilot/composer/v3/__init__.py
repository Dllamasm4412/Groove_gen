"""
GrooveGen v3 generator (opt-in prototype; MUSIC_GENERATION_V3_REVISED_IMPLEMENTATION_PLAN.md).

Hip-hop only. Every other genre, and every locked path (v1 bank, v2a, v2c),
is untouched: composer.py, the frozen cells and composer/arrangement.py are
not modified, and nothing here imports physiology or controller modules.

    theory.py   pitch, chord, scale, voicing and swing-grid helpers (pure)
    state.py    CompositionSpec / CompositionState / SegmentPlan (frozen data)
    hiphop.py   composition creation, segment planning, realisation, levels
    checks.py   musical rule checks and transposition-invariant identity
    source.py   HipHopV3Source and V3SegmentSource (next_segment(genre, tier))

Content is a pure function of (stim_seed, GEN_VERSION, the sequence of
levels requested so far), so a session replays exactly from its tier log.
"""

GEN_VERSION = 'v3.hiphop.0'
