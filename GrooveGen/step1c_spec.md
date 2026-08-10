# STEP 1C SPEC — Downbeat phase alignment (lock drums to the bed's real beat 1)

## Context (measured)
Step 1b locked drum tempo to each bed's real tempo (salsa 87.75, r&b 131.63) — tempo rush is gone. BUT drums are laid down assuming the bed's sample 0 = beat 1. Measured offset: salsa ~0.10s (0.6 of a 16th, fine), r&b ~0.85s (~half a bar, AUDIBLE/BAD). Need to detect where beat 1 actually is in the bed and shift the drum grid to match.

USER NOTE: we do NOT need strict continuity right now — focus on DISCRETE, well-aligned pieces. crossfade_pieces can stay as-is (optional), don't invest more there.

## Deliverable — extend /home/user/workspace/groovegen_project/groovegen/continuous.py (do NOT touch frozen groovegen.py)

### 1. Downbeat detection
Add `detect_bed_downbeat(bed_wav, tempo_bpm, sr=None) -> float`:
- Compute onset strength envelope (librosa.onset.onset_strength).
- Get beat frames via librosa.beat.beat_track(bpm=tempo_bpm) OR onset-envelope autocorrelation against a one-bar template.
- Estimate the phase offset (seconds) of beat 1 within the first bar: the time of the strongest low-frequency onset (kick-like) near the start, folded into [0, bar_seconds). A robust approach: cross-correlate the onset envelope with a comb template spaced at the beat period; the lag that maximizes correlation gives the grid phase. Return offset in seconds in [0, beat_period).
- Prefer aligning to the nearest STRONG onset to t=0 (a bed usually starts on or just after its downbeat). If the bed starts with lead-in silence, offset = time of first strong onset.
- Return the offset (seconds) to shift the DRUM grid so drum beat 1 coincides with the bed's beat 1.

### 2. Apply the offset in render_piece
- render_piece should call detect_bed_downbeat, then start the drum pattern at t = downbeat_offset (i.e. shift all drum note times by +offset, and correspondingly handle the bed so total lengths still line up — simplest: shift drums later by offset and trim/pad so drums and bed end together; or shift the bed earlier). Keep it simple and correct: the goal is drum kick on beat 1 lands on the bed's kick on beat 1.
- Re-verify by the SAME cross-correlation measurement the Step 1b report used (onset-envelope xcorr between rendered drums and original bed over the first bar). Target: |offset| < ~0.05s (well under a 16th) for BOTH beds.

### SANDBOX TEST (must pass, audio-verify)
Beds: salsa=/home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav, rnb=/home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
1. Print detect_bed_downbeat offset for both beds.
2. Re-render piece_salsa.wav and piece_rnb.wav to /home/user/workspace/step1c_outputs/ with the alignment fix (same params as 1b: salsa latin/salsa density 7, rnb r&b/soul density 6, 16s, subtle).
3. Measure and print the RESIDUAL drum-vs-bed onset offset for each after the fix (should be < ~0.05s, definitely << the ~0.85s r&b had before).
4. ffmpeg volumedetect mean_volume for each (not -inf).
5. Report whether the r&b alignment is now correct (the key acceptance test).

### Critical / honest
- If a bed's downbeat is genuinely ambiguous (percussive, no clear kick), say so and report the best estimate + residual.
- Measure before/after; show the r&b offset dropped from ~0.85s to <0.05s (or report why not).
- Filter noise: grep -Ev -i "tensorflow|oneDNN|deprecat|warn|numpy|cpu_feature|madmom|resample|hasattr|_a in|librosa"

## Report back
- detect_bed_downbeat offsets for both beds.
- residual drum-vs-bed offset AFTER fix for both (before was salsa 0.10s / rnb 0.85s).
- volumedetect for both pieces.
- Confirmation the r&b drums now land on the bed's beat 1, or an honest account of any residual.

## Output
Code → /home/user/workspace/groovegen_project/groovegen/continuous.py
Outputs → /home/user/workspace/step1c_outputs/
