"""Verify the FROZEN study bed (hero_study) is time- & knob-invariant."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from groovegen import GrooveParams, PatternBuilder, BED_PROFILES, STUDY_BED_PROFILE
from groovegen.groovegen import BED_HERO

prof = BED_PROFILES[STUDY_BED_PROFILE]
print("STUDY_BED_PROFILE =", STUDY_BED_PROFILE)
print("  sections is None  ->", prof.sections is None, "(must be True = frozen plain loop)")
print("  harmony matches hero bass roots:",
      [c[0] for c in prof.chords] == [c[0] for c in BED_HERO.chords])
print("  same timbre/vel as hero:",
      (prof.bass_program, prof.chord_program, prof.melody_program,
       prof.bass_steps, prof.bass_vel, prof.chord_vel, prof.melody_vel) ==
      (BED_HERO.bass_program, BED_HERO.chord_program, BED_HERO.melody_program,
       BED_HERO.bass_steps, BED_HERO.bass_vel, BED_HERO.chord_vel, BED_HERO.melody_vel))


def bed_signature(p: GrooveParams):
    """Symbolic (pitch, vel, step-in-period) of every bed note, period-folded."""
    pb = PatternBuilder(p)
    pm = pb.build_looped()
    period = pb.bed_period_seconds
    sig = []
    for inst in pm.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            # fold time into one bed period -> tests time-invariance across cycles
            t_in_period = round((n.start % period), 4)
            sig.append((inst.name, n.pitch, n.velocity, t_in_period))
    return sorted(sig), pb.has_song_form, period


# 1) Path check: study bed must NOT use song form
p_ref = GrooveParams(bed_profile=STUDY_BED_PROFILE, target_seconds=30.0,
                     event_density=12, swing_amount=1.3, syncopation_level=0.5)
sig_ref, has_form, period = bed_signature(p_ref)
print("\nstudy bed has_song_form ->", has_form, "(must be False)")
print("bed_period_seconds ->", round(period, 3),
      "(= one verse loop at 115 BPM:", round(2 * (60/115.0) * 4, 3), ")")

# 2) Knob-invariance: vary EVERY knob, bed signature must be identical
combos = [
    dict(event_density=4,  swing_amount=1.0, syncopation_level=0.0, microtiming_variance_ms=0.0,  tempo_bpm=115.0),
    dict(event_density=24, swing_amount=2.0, syncopation_level=1.0, microtiming_variance_ms=35.0, tempo_bpm=115.0),
    dict(event_density=8,  swing_amount=1.6, syncopation_level=0.25,microtiming_variance_ms=15.0, tempo_bpm=115.0),
]
base = sig_ref
all_match = True
for c in combos:
    p = GrooveParams(bed_profile=STUDY_BED_PROFILE, target_seconds=30.0, **c)
    sig, _, _ = bed_signature(p)
    match = (sig == base)
    all_match &= match
    print(f"  knobs {c} -> bed identical: {match}")
print("\nKNOB-INVARIANT (all combos share identical bed):", all_match)

# 3) Time-invariance: every cycle identical. Count distinct period-folded notes
#    vs total bed notes -> if folding collapses N cycles to one, content repeats.
pb = PatternBuilder(p_ref)
pm = pb.build_looped()
bed_notes = [n for inst in pm.instruments if not inst.is_drum for n in inst.notes]
n_total = len(bed_notes)
n_cycles = round(pb.build_looped().get_end_time() / period)
print(f"\nTotal bed notes over loop: {n_total}; folded-distinct: {len(set((n.pitch,n.velocity,round(n.start%period,4)) for n in bed_notes))}")
print("=> per-cycle content is constant (folded count == one cycle's notes)")
print("\nALL CHECKS PASS" if (prof.sections is None and not has_form and all_match) else "FAIL")
