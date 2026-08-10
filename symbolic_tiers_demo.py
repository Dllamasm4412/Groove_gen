"""Intensity-TIER drum engine (replaces raw density stuffing).

Key idea: the controller still outputs a monotonic scalar (good for PD sign
stability -- preserves pd_controller.py's design), but that scalar now selects
a musically-DESIGNED intensity TIER instead of a raw event count. Each tier is
a coherent arrangement that escalates the way a real drummer builds energy:

  Tier 1  backbeat only        (kick 1&3, snare 2&4, quarter hats)
  Tier 2  + steady 8th hats
  Tier 3  + offbeat/8th kick pushes, light ghost snares
  Tier 4  + 16th hats (brightness up), ride option
  Tier 5  + phrase-end fills, crash accents

Coherent at EVERY level -- no clutter. Groove (syncopation/microtiming) stays a
FIXED independently-clamped 'spice', per the architecture doc, NOT ramped.
"""
import os, numpy as np, pretty_midi as pm, soundfile as sf
import symbolic_bed_proto as S

OUT="/Users/daniel/Desktop/PhD/groove_gen_project/symbolic_out"; SR=44100
KICK=36; SNARE=38; CHH=42; OHH=46; RIDE=51; CRASH=49
CONGA_H=63; CONGA_L=64; CLAVE=75; COWBELL=56; TIMBALE=65

def _hum(t, ms=8):  # micro-timing humanization
    return t + np.random.uniform(-ms,ms)/1000.0
def _vel(v, spread=8):
    return int(np.clip(v+np.random.randint(-spread,spread),1,127))

def drum_bar_tier(d, t0, spb, tier, genre="pop", bar_idx=0, n_bars=8):
    """Write ONE bar of drums at the given intensity tier (1-5)."""
    bar=spb*4
    if genre=="salsa":
        # salsa escalates via conga/timbale activity + cowbell, clave always present
        clave=[0.0,0.75,1.5,2.0,3.0] if bar_idx%2==0 else [0.5,1.0,2.0,2.5,3.5]
        for h in clave: S.note(d,CLAVE,_hum(t0+h*spb),0.05,_vel(80))
        S.note(d,KICK,_hum(t0),0.1,_vel(88))
        if tier>=2:
            for b in range(4): S.note(d,CONGA_L,_hum(t0+b*spb),0.06,_vel(66))
        if tier>=3:
            for off in [0.5,1.5,2.5,3.5]: S.note(d,CONGA_H,_hum(t0+off*spb),0.06,_vel(70))
        if tier>=4:
            S.note(d,COWBELL,_hum(t0+2*spb),0.08,_vel(78))
            for off in [0.25,0.75,1.25,1.75,2.25,2.75,3.25,3.75]:
                S.note(d,CONGA_H,_hum(t0+off*spb),0.04,_vel(58))
        if tier>=5 and bar_idx%4==3:
            for off in np.linspace(2.0,3.9,6): S.note(d,TIMBALE,_hum(t0+off*spb),0.05,_vel(84))
    else:
        # pop/rnb/calm: backbone + escalating hats + kicks + fills
        S.note(d,KICK,_hum(t0),0.1,_vel(96))
        S.note(d,KICK,_hum(t0+2*spb),0.1,_vel(88))
        S.note(d,SNARE,_hum(t0+1*spb),0.1,_vel(92))
        S.note(d,SNARE,_hum(t0+3*spb),0.1,_vel(92))
        if tier==1:
            for b in range(4): S.note(d,CHH,_hum(t0+b*spb),0.04,_vel(58))
        if tier>=2:
            for k in range(8): S.note(d,CHH,_hum(t0+(k/8)*bar),0.03,_vel(52+10*(k%2==0)))
        if tier>=3:
            S.note(d,KICK,_hum(t0+2.5*spb),0.09,_vel(72))     # push
            S.note(d,SNARE,_hum(t0+3.75*spb),0.04,_vel(40))   # ghost
        if tier>=4:
            for k in range(16): S.note(d,CHH,_hum(t0+(k/16)*bar),0.02,_vel(44+12*(k%4==0)))
            S.note(d,OHH,_hum(t0+3.5*spb),0.07,_vel(58))
        if tier>=5 and bar_idx%4==3:
            for off in np.linspace(2.0,3.9,6): S.note(d,SNARE,_hum(t0+off*spb),0.05,_vel(70+int(off*4)))
            S.note(d,CRASH,_hum(t0+ (4 if bar_idx==n_bars-1 else 0)*spb),0.3,_vel(90))

def build_with_tiers(genre, fn, bpm, tier_sequence):
    """Bed (fn) + a drum track that steps through tier_sequence, one per bar."""
    m=fn(bpm=bpm, bars=len(tier_sequence))
    spb=60.0/bpm
    d=pm.Instrument(program=0, is_drum=True, name="tier drums")
    for b,tier in enumerate(tier_sequence):
        drum_bar_tier(d, b*spb*4, spb, tier, genre=genre, bar_idx=b, n_bars=len(tier_sequence))
    m.instruments.append(d)
    return m

if __name__=="__main__":
    # demo: coherent tier climb 1->5 (2 bars each would be 10 bars; use 8 bars 1..5..)
    seq=[1,2,3,4,5,5,4,3]   # rise then settle -- shows control BOTH directions, stays coherent
    specs=[("salsa",S.build_salsa,128),("pop",S.build_pop,104),
           ("rnb",S.build_rnb,88),("calm",S.build_calm,72)]
    for g,fn,bpm in specs:
        cs = seq if g!="calm" else [1,1,2,2,3,3,2,1]  # calm stays gentle
        m=build_with_tiers(g,fn,bpm,cs)
        raw=S.render_midi(m, os.path.join(OUT,f"{g}_TIERS.wav"))
        pol=S.polish(raw, os.path.join(OUT,f"{g}_TIERS_polished.wav"))
        mv=os.popen(f'ffmpeg -i "{pol}" -af volumedetect -f null - 2>&1|grep mean_volume').read().strip()
        print(f"{g}: tiers {cs} -> {os.path.basename(pol)} | {mv.split(': ')[-1] if mv else 'n/a'}")
    print("DONE")
