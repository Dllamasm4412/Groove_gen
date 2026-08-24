"""Symbolic bed prototype for GrooveGen.

Generates genre-authentic MELODIC beds (harmony + bass + comp/melody) as MIDI,
with NO drums in the bed (drums are the controller's separate job). Renders via
FluidSynth + FluidR3_GM soundfont, then applies light polish (stereo, gentle
saturation, convolution-ish reverb) to lift it above raw GM timbre.

Genres: salsa (hand-authored montuno/clave/tumbao), pop, r&b/soul, calm.
Each bed is 8 bars. Melody/harmony carry genre identity; drums are absent.

This is a PROTOTYPE to judge soundfont timbre by ear -- not the final generator.
"""
import os, subprocess, tempfile
import numpy as np
import pretty_midi as pm
import soundfile as sf
from scipy.signal import fftconvolve

SF2 = "/usr/share/sounds/sf2/FluidR3_GM.sf2"
OUT = "/Users/daniel/Desktop/PhD/groove_gen_project/symbolic_out"
os.makedirs(OUT, exist_ok=True)
SR = 44100

# ----- GM program numbers (0-indexed) -----
AC_PIANO=0; EPIANO_RHODES=4; EPIANO_FM=5; CLAV=7
NYLON_GT=24; FINGER_BASS=33; PICK_BASS=34; SYNTH_BASS=38
STRINGS=48; WARM_PAD=89; SYN_PAD=90
TRUMPET=56; MUTED_TRUMPET=59; BRASS=61; SAX=65
MARIMBA=12; VIBRAPHONE=11

def note(inst, pitch, start, dur, vel=90):
    inst.notes.append(pm.Note(velocity=vel, pitch=pitch, start=start, end=start+dur))

def chord(inst, pitches, start, dur, vel=80):
    for p in pitches: note(inst, p, start, dur, vel)

# ============================ SALSA (hand-authored) ============================
def build_salsa(bpm=128, bars=8):
    """Salsa dura: piano montuno (2-3 son clave feel), tumbao bass, horn stabs.
    Harmony: a i-iv-V-i-ish minor montuno vamp (Am - Dm - E7 - Am), classic salsa."""
    spb = 60.0/bpm; bar = spb*4
    m = pm.PrettyMIDI(initial_tempo=bpm)
    piano = pm.Instrument(program=AC_PIANO, name="montuno")
    bass  = pm.Instrument(program=FINGER_BASS, name="tumbao")
    horns = pm.Instrument(program=BRASS, name="horn stabs")
    # chord progression per 2 bars: Am, Dm, E7, Am (each 2 bars)
    prog = [([57,60,64],45), ([57,62,65],50), ([56,59,64,68],52), ([57,60,64],45)]  # (voicing, bass root)
    # 2-3 son clave onset pattern (in 16ths over 2 bars): classic montuno rhythm
    # montuno = arpeggiated chord in a syncopated clave-locked figure
    montuno_offsets = [0.0, 0.75, 1.0, 1.5, 2.0, 2.75, 3.0, 3.5]  # beats within a bar (son-clave phrased)
    for b in range(bars):
        t0 = b*bar
        voicing, root = prog[(b//2) % len(prog)]
        # --- montuno: arpeggiate voicing in the clave figure, both bars ---
        arp = voicing + [voicing[0]+12]
        for k,off in enumerate(montuno_offsets):
            p = arp[k % len(arp)]
            note(piano, p, t0+off*spb, spb*0.45, vel=78+ (10 if off in (0.0,2.0) else 0))
        # --- tumbao bass: anticipated bass (the "&" of 2 and beat 4), genre-defining ---
        note(bass, root-12, t0+1.5*spb, spb*0.5, vel=92)   # anticipation into beat 2-and
        note(bass, root-12+7, t0+2.5*spb, spb*0.4, vel=80) # 5th
        note(bass, root-12, t0+3.5*spb, spb*0.5, vel=90)   # push to next bar
        # --- horn stabs: sparse, on clave accents, every 2 bars ---
        if b % 2 == 1:
            chord(horns, [v+12 for v in voicing], t0+3.0*spb, spb*0.5, vel=88)
    for i in (piano,bass,horns): m.instruments.append(i)
    return m

# ============================ POP ============================
def build_pop(bpm=104, bars=8):
    # PALETTE_PATCH_V2 applied
    """Bright pop: syncopated clav/synth comp, punchy finger bass. I-V-vi-IV in C."""
    spb=60.0/bpm; bar=spb*4
    m=pm.PrettyMIDI(initial_tempo=bpm)
    comp=pm.Instrument(program=EPIANO_RHODES, name="rhodes comp")
    bass=pm.Instrument(program=FINGER_BASS, name="bass")
    pad =pm.Instrument(program=STRINGS, name="strings pad")
    prog=[([60,64,67],48),([55,59,62],43),([57,60,64],45),([53,57,60],41)]  # C G Am F
    comp_off=[0.5,1.0,1.5,2.5,3.0,3.5]  # syncopated 8th pushes
    for b in range(bars):
        t0=b*bar; voi,root=prog[b%4]
        chord(pad, voi, t0, bar, vel=48)  # strings need a touch more level than SYN_PAD
        for off in comp_off:
            chord(comp,[v+12 for v in voi], t0+off*spb, spb*0.35, vel=70)
        for beat in range(4):
            note(bass, root-12, t0+beat*spb, spb*0.5, vel=88)
        note(bass, root-12+7, t0+3.5*spb, spb*0.4, vel=80)
    for i in (pad,comp,bass): m.instruments.append(i)
    return m

# ============================ R&B / SOUL ============================
def build_rnb(bpm=88, bars=8):
    """Laid-back neo-soul: Rhodes 7th/9th chords, deep pocket bass. ii-V vibe in F."""
    spb=60.0/bpm; bar=spb*4
    m=pm.PrettyMIDI(initial_tempo=bpm)
    rhodes=pm.Instrument(program=EPIANO_RHODES, name="rhodes")
    bass  =pm.Instrument(program=FINGER_BASS, name="bass")
    prog=[([62,65,69,72],50),([55,59,62,65],43),([53,57,60,64],41),([53,57,60,64],41)] # Gm9 Cmaj Fmaj7-ish
    for b in range(bars):
        t0=b*bar; voi,root=prog[b%4]
        # lush sustained rhodes, slightly swung stabs
        chord(rhodes, voi, t0+0.0, spb*1.5, vel=58)
        chord(rhodes, [v for v in voi], t0+2.5*spb, spb*1.2, vel=52)
        # deep pocket bass: root on 1, ghost/5th syncopations
        note(bass, root-12, t0+0.0, spb*0.9, vel=84)
        note(bass, root-12+7, t0+1.75*spb, spb*0.4, vel=62)  # ghost 5th (swung)
        note(bass, root-12, t0+2.5*spb, spb*0.8, vel=78)
    for i in (rhodes,bass): m.instruments.append(i)
    return m

# ============================ CALM ============================
def build_calm(bpm=72, bars=8):
    """Sparse ambient: warm pad + soft e-piano, slow bass. Open, unhurried. Cadd9 vibe."""
    spb=60.0/bpm; bar=spb*4
    m=pm.PrettyMIDI(initial_tempo=bpm)
    pad =pm.Instrument(program=WARM_PAD, name="warm pad")
    ep  =pm.Instrument(program=EPIANO_FM, name="soft ep")
    bass=pm.Instrument(program=FINGER_BASS, name="slow bass")
    prog=[([60,64,67,74],48),([57,60,64,71],45),([53,57,60,67],41),([55,59,62,69],43)]
    for b in range(bars):
        t0=b*bar; voi,root=prog[b%4]
        chord(pad, voi, t0, bar, vel=40)                    # sustained pad whole bar
        note(ep, voi[-1], t0+1.0*spb, spb*1.2, vel=44)      # single sparse melodic note
        note(ep, voi[1],  t0+3.0*spb, spb*1.0, vel=40)
        note(bass, root-12, t0, spb*3.5, vel=60)            # long slow bass
    for i in (pad,ep,bass): m.instruments.append(i)
    return m

# ---------- rendering ----------
def render_midi(midi, out_wav, sf2=SF2, sr=SR, gain=0.8):
    with tempfile.NamedTemporaryFile(suffix=".mid", delete=False) as f:
        midi.write(f.name); mid_path=f.name
    raw = out_wav.replace(".wav","_raw.wav")
    cmd=["fluidsynth","-ni","-F",raw,"-r",str(sr),"-g",str(gain),sf2,mid_path]
    r=subprocess.run(cmd, capture_output=True, text=True)
    os.unlink(mid_path)
    if not os.path.exists(raw):
        print("fluidsynth failed:", r.stderr[-400:]); return None
    return raw

def polish(raw_wav, out_wav, sr=SR, normalize=True, gain=1.0):
    """Light mastering: gentle tanh saturation + short algorithmic reverb + stereo width.

    normalize : bool
        If True (default, back-compat), peak-normalize the mix to 0.95. This
        is CORRECT for one-shot renders but WRONG when polishing many segments
        that will be crossfaded together: per-call peak-normalization makes
        every segment hit the same 0.95 peak regardless of its actual musical
        loudness, so a quiet calm segment and a loud latin segment come out at
        the same level -> an audible LOUDNESS STEP at every crossfade seam.
        For the segment pipeline pass normalize=False and instead apply ONE
        fixed session `gain` calibrated from the loudest reachable
        tier/genre, so relative loudness across the ladder is preserved.
    gain : float
        Fixed scalar applied when normalize=False (session-level makeup gain).
    """
    y,_=sf.read(raw_wav)
    if y.ndim==1: y=np.stack([y,y],axis=1)
    # gentle saturation (analog-ish warmth)
    y = np.tanh(y*1.4)/1.4
    # simple reverb: exponentially-decaying noise impulse response, ~0.9s
    ir_len=int(0.9*sr); t=np.arange(ir_len)/sr
    ir=(np.random.randn(ir_len)*np.exp(-t*4.5)).astype(np.float32); ir/=np.abs(ir).sum()
    wetL=fftconvolve(y[:,0], ir)[:len(y)]; wetR=fftconvolve(y[:,1], ir)[:len(y)]
    wet=np.stack([wetL,wetR],axis=1)
    mix = 0.82*y + 0.18*wet
    # slight stereo widening (Haas-ish few-ms delay on R)
    d=int(0.008*sr); mix[:,1]=np.concatenate([np.zeros(d),mix[:-d,1]])
    if normalize:
        mix=mix/(np.max(np.abs(mix))+1e-9)*0.95
    else:
        mix=mix*gain
        # safety clip only if the fixed gain overshoots -- does NOT re-normalize
        peak=np.max(np.abs(mix))
        if peak>0.99:
            mix=mix/(peak+1e-9)*0.99
    sf.write(out_wav, mix.astype(np.float32), sr)
    return out_wav

BEDS={"salsa_128":(build_salsa,128),"pop_104":(build_pop,104),
      "rnb_88":(build_rnb,88),"calm_72":(build_calm,72)}

def perc_harm(path):
    import librosa
    y,sr=librosa.load(path,sr=None,mono=True)
    yh=librosa.effects.harmonic(y,margin=3.0); yp=y[:len(yh)]-yh
    return float(np.sqrt(np.mean(yp**2))/(np.sqrt(np.mean(yh**2))+1e-9))

if __name__=="__main__":
    for name,(fn,bpm) in BEDS.items():
        midi=fn(bpm=bpm)
        raw=render_midi(midi, os.path.join(OUT,f"{name}.wav"))
        if not raw: continue
        pol=polish(raw, os.path.join(OUT,f"{name}_polished.wav"))
        ph_raw=perc_harm(raw); ph_pol=perc_harm(pol)
        # also save the MIDI for inspection
        midi.write(os.path.join(OUT,f"{name}.mid"))
        print(f"{name}: rendered. perc/harm raw={ph_raw:.2f} polished={ph_pol:.2f}  "
              f"(bed should be LOW = melodic, no drums)")
    print("DONE ->", OUT)
