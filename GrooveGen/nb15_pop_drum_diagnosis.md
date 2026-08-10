# nb15 Pop-Section Drum Diagnosis (v3 output)

## User report
"sounds great except in the pop section... the drum beat sounds a bit off. But the rest of the songs sound very good."

## Objective measurements (extracted from download-2.mp4, per-segment)

| seg   | target BPM | detected BPM | beat jitter (ms) | onset regularity (CoV) | pulse clarity |
|-------|-----------:|-------------:|-----------------:|-----------------------:|--------------:|
| latin | 125        | 126.0        | **5.5**          | **0.086**              | 0.868         |
| pop   | 110        | 110.0        | **29.5**         | **0.464**              | 0.789         |
| r&b   | 97         | 95.7         | 17.7             | 0.316                  | 0.573         |
| calm  | 82         | 82.0         | 49.4*            | 0.221                  | 0.784         |

*calm high jitter is expected/benign — it's a sparse (density 3) slow neo-soul bed; few onsets → noisy beat tracker, but perceptually fine per user.

**Pop is the outlier that matters:** correct tempo (110) but 5× the beat jitter and 5× the onset irregularity of latin.

## Root cause (confirmed by two independent tests)
1. **Grid drift throughout the segment:** pop onset-vs-ideal-110-grid error averages **127 ms** (max 266 ms). At 110 BPM one beat = 545 ms, so drum hits land ~23% of a beat off the bed's actual pulse across the whole segment — not a single glitch.
2. **A loop seam** at ~25 s into the segment (one beat +34% long) where the 12 s MusicGen bed tiles to fill ~30 s.

**Why only pop:** pop is the ONLY MusicGen-GENERATED bed in this run. Latin and R&B use clean UPLOADED WAV beds with crisp, steady pulses. Generated beds have a wobbly internal pulse, so `render_aligned_drums` (which warps drums onto the bed's detected downbeat grid) and the bed itself disagree — the drums sound "off" against the music.

## Fix options (ranked)
- **A (best, cheap): use a clean uploaded pop bed** — eliminates the generated-bed wobble entirely, same as latin/r&b. Zero MusicGen cost for pop. Needs one clean ~110 BPM pop/4-on-floor loop.
- **B (cheap, no new asset): quantize the generated pop bed to a strict grid before drum alignment** — time-stretch the generated bed to lock its pulse to exactly 110 BPM (rubberband/librosa), THEN align drums. Removes drift + seam. Adds one stretch op, no extra MusicGen call.
- **C (cheap): re-detect the grid AFTER loop-to-length and snap drums to the bed's own detected downbeats bar-by-bar** — reduces but won't fully remove wobble (bed still wanders within bars).
- **D (expensive, not recommended): regenerate pop with more MusicGen tries + pick the steadiest** — burns credits, still a generated bed.

## Credit-saving note
The MusicGen call is the only expensive step. Options A/B/C add ZERO MusicGen cost. Only D costs credits. Recommend A or B.
