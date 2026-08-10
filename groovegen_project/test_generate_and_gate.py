import sys, os, numpy as np, soundfile as sf
sys.path.insert(0, 'groovegen_project')
from groovegen.generate_and_gate import (
    generate_and_gate, measure_tempo_stability, QualityGate, summarize, beatsync_quantize
)

SR = 44100
def click_track(bpm, seconds, jitter_ms=0.0, seed=0):
    """Synthesize a click train at bpm with optional timing jitter (ms)."""
    rng = np.random.default_rng(seed)
    spb = 60.0/bpm
    y = np.zeros(int(seconds*SR))
    t = 0.0
    while t < seconds:
        jit = rng.normal(0, jitter_ms/1000.0)
        idx = int(max(0,(t+jit))*SR)
        if idx < len(y)-200:
            click = np.exp(-np.arange(200)/30.0)  # short percussive blip
            y[idx:idx+200] += click
        t += spb
    return y

# Fake generator: seg0 clean, seg1 very wobbly (forces retry->quantize->maybe fallback)
CALLS = {}
def fake_generator(prompt, out_wav, seconds, target_bpm):
    n = CALLS.get(out_wav, 0); CALLS[out_wav] = n+1
    if 'seg0' in out_wav:
        y = click_track(target_bpm, seconds, jitter_ms=2.0, seed=n)   # clean
    else:
        y = click_track(target_bpm, seconds, jitter_ms=45.0, seed=n)  # wobbly always
    sf.write(out_wav, y, SR)
    return out_wav, SR

# fallback bed for the wobbly genre = a clean click track written to disk
os.makedirs('test_gate_out', exist_ok=True)
fb_path = 'test_gate_out/clean_pop_fallback.wav'
sf.write(fb_path, click_track(110, 12, jitter_ms=1.5, seed=99), SR)

segments = [
    {'genre':'latin','tempo_bpm':125,'prompt':'a latin groove at 125 bpm'},
    {'genre':'pop','tempo_bpm':110,'prompt':'a pop groove at 110 bpm'},
]
# clear any cache from prior runs
for f in os.listdir('test_gate_out'):
    if f.startswith('seg'): os.remove(os.path.join('test_gate_out',f))

print("=== RUN 1 (fresh generate) ===")
res = generate_and_gate(segments, fake_generator, 'test_gate_out',
                        seconds_per_segment=[12,12],
                        gate=QualityGate(max_beat_jitter_ms=12, max_grid_err_ms=40),
                        max_tries=3, fallback_beds={'pop':fb_path}, cache=True)
print(summarize(res))

print("\n=== RUN 2 (should hit CACHE, zero MusicGen calls) ===")
CALLS.clear()
res2 = generate_and_gate(segments, fake_generator, 'test_gate_out',
                         seconds_per_segment=[12,12],
                         gate=QualityGate(max_beat_jitter_ms=12, max_grid_err_ms=40),
                         max_tries=3, fallback_beds={'pop':fb_path}, cache=True)
print(summarize(res2))
print("generator calls in RUN 2:", sum(CALLS.values()), "(should be 0)")
