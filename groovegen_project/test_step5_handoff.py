import sys, os, numpy as np, soundfile as sf
sys.path.insert(0, 'groovegen_project')
from groovegen.generate_and_gate import generate_and_gate, summarize, QualityGate

SR=44100
def click(bpm,sec,jit,seed):
    rng=np.random.default_rng(seed); spb=60/bpm; y=np.zeros(int(sec*SR)); t=0
    while t<sec:
        idx=int(max(0,t+rng.normal(0,jit/1000))*SR)
        if idx<len(y)-200: y[idx:idx+200]+=np.exp(-np.arange(200)/30)
        t+=spb
    return y

# Simulate arc_from_profile output (4 personalized segments)
segments=[
 {'genre':'latin','tempo_bpm':125,'prompt':'a bright latin groove at about 125 BPM, driving steady drums'},
 {'genre':'pop','tempo_bpm':110,'prompt':'a pop groove at about 110 BPM, steady drums'},
 {'genre':'r&b','tempo_bpm':97,'prompt':'a warm r&b groove at about 97 BPM'},
 {'genre':'calm','tempo_bpm':82,'prompt':'a warm r&b/soul groove at about 82 BPM, sparse'},
]
# seg1 (pop) deliberately wobbly -> should fallback; others clean
def gen(prompt,out,sec,bpm):
    seed=hash(out)%1000
    jit = 45.0 if 'seg1_' in out else 3.0
    sf.write(out, click(bpm,sec,jit,seed), SR); return out,SR

# fallback clean pop bed
BED_CACHE_DIR='groovegen_project/outputs/audio/nb15/beds'
os.makedirs(BED_CACHE_DIR, exist_ok=True)
for f in os.listdir(BED_CACHE_DIR):
    if f.startswith('seg'): os.remove(os.path.join(BED_CACHE_DIR,f))
fb='groovegen_project/outputs/audio/nb15/clean_pop.wav'
sf.write(fb, click(110,12,1.5,7), SR)

res=generate_and_gate(segments, gen, BED_CACHE_DIR,
    seconds_per_segment=[12,12,12,12],
    gate=QualityGate(12,40), max_tries=3,
    fallback_beds={'pop':fb}, cache=True)
print(summarize(res))
print("\n=== files written to BED_CACHE_DIR (what nb15 will pick up) ===")
for f in sorted(os.listdir(BED_CACHE_DIR)):
    if f.endswith('.wav'): print("  ", f)

# Now verify nb15's cache-lookup logic finds each seg
print("\n=== nb15 cache lookup simulation ===")
import glob
for i,seg in enumerate(segments):
    exact=os.path.join(BED_CACHE_DIR, f"seg{i}_{seg['genre']}_{seg['tempo_bpm']}bpm.wav")
    if os.path.exists(exact): found=os.path.basename(exact)
    else:
        hits=sorted(glob.glob(os.path.join(BED_CACHE_DIR,f"seg{i}_*.wav")))
        found=os.path.basename(hits[0]) if hits else "NONE (would generate inline)"
    print(f"  seg{i} {seg['genre']:5s} -> {found}")
