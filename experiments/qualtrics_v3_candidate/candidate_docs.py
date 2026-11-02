"""
Narrative documents for the candidate corpus (called from qc_report.write_reports).
"""

from __future__ import annotations

from pathlib import Path
from statistics import fmean


def _eta2(rows, key='ladder_rung') -> float:
    vals = [r[key] for r in rows]
    mu = fmean(vals)
    by: dict = {}
    for r in rows:
        by.setdefault(r['genre'], []).append(r[key])
    ss_t = sum((v - mu) ** 2 for v in vals)
    ss_b = sum(len(v) * (fmean(v) - mu) ** 2 for v in by.values())
    return ss_b / ss_t if ss_t else 0.0


def write_docs(out: Path, E: Path, rows, audit, practice, env, label, prelim, mono, sims, changes=None) -> None:
    changed = [c for c in (changes or []) if not c['midi_unchanged']]
    heard = ('The researcher listened to version v3.0 (2026-11-02): most excerpts were judged to sound good; S03 '
             '(rock, tier 1) and S04 (pop, tier 1) were judged poor, and rock was asked to sound like classic stadium '
             'and melodic hard rock. ' + (f"{len(rows) - len(changed)} excerpts are unchanged since v3.0 (identical "
             f"MIDI); the {len(changed)} revised ones ({', '.join(c['stimulus_id'] for c in changed)}) have not been "
             'heard yet.' if changes else '')) if changes else \
        'Nobody has listened to these files yet. They were generated, rendered and checked by software only.'
    by_rung = sorted(rows, key=lambda r: r['ladder_rung'])
    genres = sorted({r['genre'] for r in rows}, key=lambda g: fmean(r['ladder_rung'] for r in rows if r['genre'] == g))
    eta = _eta2(rows)
    tiers = {g: sorted(r['tier'] for r in rows if r['genre'] == g) for g in genres}
    rungs = {g: sorted(r['ladder_rung'] for r in rows if r['genre'] == g) for g in genres}
    hh = [r for r in rows if r['genre'] == 'hiphop']
    vol = next((p for p in practice if p['kind'] == 'volume'), None)
    loudest = max(rows, key=lambda r: r['lufs_integrated'])
    quietest = min(rows, key=lambda r: r['lufs_integrated'])
    sf_note = (f"**PRELIMINARY audio ({env['soundfont']}, not Musyng Kite).** The MIDI, seeds and selection are final "
               'for this candidate version; render the audio with Musyng Kite before judging sound (see "Render with '
               'Musyng Kite").' if prelim else f"Rendered with the locked Musyng Kite file ({env['soundfont']}).")

    # ---------------------------------------------------------------- package README
    R = [f'# GrooveGen v3 candidate stimuli for the danceability study ({label})', '',
         '**Status: CANDIDATE. Not frozen, not approved for participants.** A separately versioned set for the '
         'researcher\'s listening and decisions. The original study\'s stimuli, manifest and Qualtrics files are '
         'unchanged and were only read.', '', sf_note, '',
         heard, '',
         *(['Before / after MP3s of the revised excerpts: `listening/' + next(iter(
             p.name for p in (out / 'listening').iterdir() if p.name.startswith('changed_since_'))) + '/`.', '']
           if changed else []),
         '## Folders', '',
         '| Folder | Contents |', '|---|---|',
         '| `A_qualtrics_mp3/` | Exactly 27 experimental excerpts, `S01.mp3`-`S27.mp3` (192 kbps, 44.1 kHz stereo, no tags). Names reveal nothing about genre, condition or generator. |',
         '| `B_wav_masters/` | The same 27 as 16-bit 44.1 kHz WAV masters (no metadata chunks). |',
         '| `C_midi_sources/` | The generated MIDI each recording was rendered from. |',
         '| `D_internal_previews_10s/` | **Internal previews only, not approved replacements**: the first whole bars nearest 10 s of each excerpt (WAV; MP3s in `listening/previews_mp3/`). |',
         '| `E_analysis/` | Private answer key (`stimulus_manifest.*`), features, generation log, QC report, condition audit, design notes, Qualtrics files, listening sheet. |',
         '| `F_reference_original_v2c_8bar/` | Reference: each original condition\'s full 8-bar locked-v2c segment rendered the same way (named by the same S IDs). |',
         '| `G_candidate_practice_volume/` | Candidate practice (2) and volume (1) clips in v3. The original ones are **not** replaced; see `E_analysis/qualtrics_readiness.md`. |',
         '| `listening/` | `playlist_S01-S27.m3u` and one continuous MP3 of all 27 in ID order with 3 s gaps. |', '',
         '## Listen first', '',
         '1. Play `listening/all_27_in_ID_order_3s_gaps.mp3` (or the playlist) without opening `E_analysis/`.',
         '2. Fill in `E_analysis/researcher_listening_sheet.csv` (quality, urge to move, calming, genre fit, '
         'coherence, repetitive or incomplete, problems with timestamps, keep?).',
         '3. Then read `E_analysis/README.md` and the answer key.', '',
         '## Render with Musyng Kite (on the Mac)', '',
         'From the repository root, on the v3 branch (`claude/dazzling-brown-qz2gtb`), with the locked soundfont at '
         '`soundfonts/Musyng_Kite.sf2`:', '',
         '```bash',
         f'.venv/bin/python3.12 experiments/qualtrics_v3_candidate/build_candidate.py build --sf2 soundfonts/Musyng_Kite.sf2 --selection {out.name}/E_analysis/stimulus_manifest.json --zip',
         '```', '',
         'This regenerates the same 27 MIDI files from the same seeds (it stops if any hash differs), re-renders the '
         'original 8-bar references on Musyng Kite to get each condition\'s loudness target, matches, measures and '
         'writes `groovegen_qualtrics_27_candidate_v3_Musyng_Kite/`. Selection is not re-run. Any Musyng-specific '
         'problem (for example a peak needing the limiter) is reported, not silently fixed.', '',
         f"Built from commit {env['git_head'][:10]} ({env['git_branch']}), {env['fluidsynth']}.", '']
    (out / 'README.md').write_text('\n'.join(R))

    # ---------------------------------------------------------------- analysis README / design
    D = ['# Candidate corpus: design, generation and selection', '',
         sf_note, '',
         '## 1. What the protocol requires (IRB 26-0684, version 2026-10-27)', '',
         '- 27 prerecorded excerpts, each heard once in randomised order; one volume-setting sample and two practice '
         'excerpts before them; eight-bar phrases of about 15-30 s; two 0-100 ratings per excerpt.',
         '- "The 27 excerpts were generated using configurations assigned different intended danceability levels. '
         'These intended levels will be documented for each excerpt before participants are enrolled."',
         '- Primary analysis: whether higher intended danceability predicts higher danceability ratings, repeated-'
         'measures regression with a participant random intercept. Calming: exploratory, no directional hypothesis.',
         '- "The configurations vary in more than one musical property": no single-feature causal claim.', '',
         '## 2. The 27 conditions (unchanged)', '',
         'The conditions are the original study\'s 27 main stimuli: one per live ladder cell (genre x tier). '
         'Full table: `condition_audit.md` / `.csv`.', '',
         '| Genre | Tiers | Ladder rungs |', '|---|---|---|']
    D += [f"| {g} | {', '.join(map(str, tiers[g]))} | {', '.join(map(str, rungs[g]))} |" for g in genres]
    D += ['', '## 3. Intended danceability: not defined anywhere yet', '',
          'No intended-danceability level exists in the protocol, the frozen stimulus manifest, the Qualtrics build or '
          'the analysis code. The only ordering is the **ladder rung** (0-26), which `analyze_ratings.py` correlates '
          'with the ratings. The rung is the developer\'s by-ear order of a **composite energy** score:', '',
          '- energy E = z-weighted rendered loudness 0.40, drum onset rate 0.25, tempo 0.20, spectral centroid '
          '0.10, spectral flux 0.05 (`music_features_measured.py`), re-ordered by four blind listening relations.',
          '- In the corpus (644 tracks with audio features), Spotify danceability correlates with percussive share '
          '(rho +0.30), pulse strength (PLP, +0.28), bass share (+0.26), octave-folded tempo (+0.21), beat '
          'regularity (+0.13) and onset density (+0.11), but **not** with loudness (RMS, +0.05 n.s.), brightness '
          '(centroid, +0.02 n.s.) or syncopation (LHL, -0.07 n.s.); Spotify energy correlates slightly negatively '
          '(-0.09). Half of the energy composite\'s weight (loudness 0.40 + centroid 0.10) is on features with no '
          'corpus association with danceability.',
          '- `analyze_ratings.py` also sets `EXPECTED = {danceability: +1, calming: -1}`; the protocol states no '
          'directional calming hypothesis.', '',
          f'**Genre confound.** Genre explains {eta:.0%} of the variance in ladder rung (eta squared {eta:.2f}): calm '
          'occupies only rungs 0-1, lo-fi 2-5, rock 9-26. If the rung were the intended level, a positive '
          'association could arise from genre differences alone.', '',
          '**Recommendation (for the researcher to decide and document before enrolment):**', '',
          '1. **Primary predictor: within-genre tier** (`coding_within_genre_tier`, 1-5), analysed within genre '
          '(genre as a fixed effect, or tier centred within genre), with the participant random intercept. The tier '
          'is the configuration parameter the generator actually sets; in this corpus every tier step adds '
          'rhythmic activity or layering (more drum or bass notes, or an extra percussion or accompaniment layer) '
          'while genre, style and instrumentation stay; and the within-genre comparison removes the genre confound. '
          'Section 4 of `quality_control_report.md` shows, per step, whether the intended differences are present in '
          'the audio and MIDI.',
          '2. **Secondary: the ladder rung**, reported for continuity with the existing analysis, described as '
          '"designed energy", not danceability.',
          '3. Do not use a measured audio index (including the corpus-referenced features in `audio_features.csv`) '
          'as the intended level: it would be a property of the produced audio, chosen after generation.',
          '4. Remove the directional calming expectation from the analysis code, or label it exploratory.', '',
          'This changes the analysis model the protocol names (adds genre). Whether that needs an amendment or only '
          'documentation before enrolment is an IRB / advisor decision.', '',
          '## 4. Genre and the intended level: structure', '',
          '- Unbalanced by design: calm 2 tiers, lo-fi 3, Latin 3, R&B 4, pop / hip-hop / rock 5. No genre spans '
          'the whole energy range; low rungs are almost all calm, lo-fi and low hip-hop tiers.',
          '- Kept as approved (no conditions added or removed). An improved design, if a new protocol version is '
          'considered: the same tiers (for example 1, 3, 5) in every genre, or genre x tier fully crossed for a '
          'smaller set of genres, so tier and genre are orthogonal; consider equal loudness across conditions '
          '(loudness is 40% of the energy composite but not associated with danceability in the corpus).', '',
          '## 5. Controlled and incidental differences', '',
          '**Controlled (from the configuration):** genre; tier; tempo (the configuration\'s, identical to the original '
          'condition: constant per genre for calm, lo-fi, R&B, pop and Latin; rising with tier for hip-hop and rock); '
          'loudness (matched to the original condition\'s 8-bar segment); the tier\'s layer set and rhythmic '
          'activity (drum pattern density and percussion layers, bass figure, accompaniment pattern, melody anchor at '
          'tier 1, extra pad or arpeggio at the top tiers); excerpt length (8 bars).', '',
          '**Incidental (from the seed, documented per excerpt in `stimulus_manifest.csv`):** key; mode; chord '
          'progression; melodic motif; instrument palette within the genre; groove variant (which kick pattern '
          'variant, which clave direction); swing amount (lo-fi, R&B); for hip-hop the sub-style, chord loops, '
          'motif, palette and kick patterns. Each condition has its own composition (as in the original set, whose '
          'seeds also differ per cell). Composition is therefore not held constant across tiers within a genre: an '
          'alternative with one composition per genre at all its tiers isolates the tier manipulation better but '
          'repeats the same piece up to five times; the generator supports it (same seed for every tier).', '',
          '## 6. Generators: v2c and v3', '',
          '| Genre | Original condition (v2c) | This candidate |', '|---|---|---|']
    for g in genres:
        orig = sorted({a['original_gen_version'] for a in audit if a['genre'] == g})
        new = sorted({r['generator_version'] for r in rows if r['genre'] == g})
        D.append(f"| {g} | {', '.join(orig)} | {', '.join(new)} |")
    D += ['', '- **Hip-hop:** the v3 hip-hop generator the developer listened to and approved (its statement '
          'section at level = tier, tier tempo).',
          '- **The six other genres:** new, opt-in `composer/v3/genres.py` (v3.genres.0), written for this corpus. '
          'Each genre has its own harmony grammar, drum / percussion patterns per tier, bass-drum relationship, '
          'comping, melodic cells and palettes, building on the instruments the developer chose by ear for the '
          'locked cells (calm: piano with the original calm configuration\'s light pulse; lo-fi: Rhodes, upright bass, soft swung drums; R&B: Rhodes, synth '
          'sub-bass, straight half-time 16ths; pop: acoustic-guitar or piano lead; Latin: son clave, tumbao bass, '
          'montuno piano, percussion growing from shaker to congas, bongos and cowbell; rock (revised in v3.1): '
          'riff-based hard rock on driven guitars at every tier, in the stadium / melodic hard-rock style the '
          'researcher named, generated from that style\'s techniques without reproducing any song). '
          'Shared from v3: the motif and chord-fitting machinery, '
          'voice leading, swing grid, part-overlap handling and rule checks. The researcher has heard v3.0 of these '
          'six; the rock revision (v3.1) has not been heard yet.',
          '- Generator version is uniform (v3) across genres in this candidate, so it is not confounded with genre or '
          'tier; but the hip-hop generator is more mature (listened to and iterated) than the other six.', '',
          '## 7. Generation and selection procedure', '',
          '1. For each condition in ladder order, candidates k = 0, 1, 2, 3 with seed = first 4 bytes of '
          'sha256("qualtrics-27-v3-candidate-1|<genre>|<tier>|<k>").',
          '2. Each candidate is checked: generator rule checks pass; after loudness matching the peak is at or below '
          '-1 dBFS (the locked limiter allowed if it costs at most 1 LU); no silence longer than 0.5 s inside the '
          '8 bars; its lead-line phrases overlap less than 50% with any excerpt already selected.',
          '3. The **first** passing candidate is selected. No listening, no rating and no danceability or calmness '
          'measure is used. Every candidate, its checks and rejection reasons are in `generation_log.csv`.',
          '4. Neutral IDs S01-S27 come from a fixed hash of each condition (`qualtrics-27-v3-ids-1`), not from the '
          'ladder or genre order.', '',
          '## 8. Rendering', '',
          '- SymbolicSegmentRenderer.render_pm (FluidSynth, gain 0.8, master -2.5 dB), the same path as the original '
          'stimuli; 8 bars plus a quarter-bar release with the live equal-power fade; a 3 ms fade-in.',
          '- One static gain per excerpt matches the original condition\'s 8-bar loudness on the same soundfont; the '
          'locked look-ahead limiter (-1 dBFS) only where a matched excerpt would exceed -1 dBFS (recorded).',
          f"- Loudness range {quietest['lufs_integrated']:.1f} LUFS ({quietest['condition_id']}) to "
          f"{loudest['lufs_integrated']:.1f} LUFS ({loudest['condition_id']}), as in the original configurations. "
          'No normalisation.',
          '- Previews: the first whole bars nearest 10 s, same gain, quarter-bar fade. Internal only.', '',
          '## 9. Measurements', '',
          '`audio_features.csv`: tempo (MIDI, exact) and the beat tracker\'s estimate; duration; integrated loudness; '
          'peak; drum onsets per second (MIDI, 20 ms merge; the energy table\'s definition); drum, hat and bass notes '
          'per bar; bass onsets on a kick; an off-beat index (mean metrical depth of kick, snare and bass onsets; '
          'not the corpus\'s LHL syncopation); number of parts; spectral centroid, flux and pulse clarity; the '
          'composite energy score with the delivered loudness (`energy_u_delivered`) and at the reference level '
          '(`energy_u_midi_reference`, as the energy table measures); and corpus-named features (percussive ratio, '
          'PLP, bass band ratio, onset density, beat consistency) from the repository\'s re-implementation of the '
          'corpus extractor, with approximate percentiles in the corpus. None of these measures perceived '
          'danceability; the participants\' ratings do.', '',
          '## 10. Revisions', '',
          '- **v3.0** (2026-11-02): first candidate. The researcher listened: most excerpts good; S03 (rock:1) and '
          'S04 (pop:1) poor; rock should follow classic stadium / melodic hard rock.',
          '- **v3.1** (2026-11-02): generator v3.genres.1. Rock rewritten as riff-based hard rock on driven guitars '
          'at every tier (power-chord stabs with space, 8th-note drives, palm-muted chugs, pedal-point 16th riffs; a '
          'second guitar from tier 3; a lead guitar answering the riff at tier 4 and carrying a melodic hook at tier '
          '5; tier 1 plays an intro form of the riff). Pop tier 1 re-arranged: the full melody instead of held notes '
          'only, a soft snare instead of a side-stick, half-note strums instead of whole notes. Seeds, conditions, '
          'selection rule, loudness matching and rendering unchanged; every other excerpt is byte-identical to v3.0 '
          '(`changes_vs_previous_version.csv`). The rock riffs and hooks are generated from the style\'s techniques; '
          'no existing song is reproduced.', '',
          '## 11. Readiness', '',
          '**Not ready to freeze.** Before this set (or a revision) can be frozen:', '',
          '1. Render with Musyng Kite (one command above) and listen again, at least to the excerpts revised in '
          'v3.1 (`changes_vs_previous_version.csv`).',
          '2. Decide and document the intended-danceability coding before enrolment (section 3).',
          '3. Decide whether replacing the stimuli (v2c -> v3; 4 -> 8 bars, as the protocol already says) needs an '
          'IRB modification or notification, given that representative examples were attached to the submission.',
          '4. Decide on practice and volume clips (`qualtrics_readiness.md`).',
          '5. If data collection has started with the original 4-bar set, keep that set unchanged and treat this as '
          'a new stimulus version for a separate data collection.',
          '6. Test the full Qualtrics flow with the new files (playback on desktop and mobile browsers, loop & merge '
          'identity in the export).', '']
    (E / 'README.md').write_text('\n'.join(D))

    # ---------------------------------------------------------------- protocol differences
    P = ['# Differences from the submitted protocol (version 2026-10-27)', '',
         '| Item | Protocol | Original study build (repository) | This candidate |', '|---|---|---|---|',
         '| Excerpt length | eight-bar phrases, about 15-30 s | **4 bars, 7.9-15.7 s** (researcher decision 2026-10-09; rc1 was 8 bars) | 8 bars, '
         f"{min(r['duration_s'] for r in rows):.1f}-{max(r['duration_s'] for r in rows):.1f} s (calm at 65 BPM is "
         'about 0.5 s over 30 s with its release) |',
         '| Intended danceability levels | documented per excerpt before enrolment | not documented; ladder rung (energy) used in analysis | not documented; candidate codings provided, decision required |',
         '| Calming hypothesis | none (exploratory) | analysis code expects calming to fall with rung | no expectation encoded |',
         '| Generator | "a computer-based system" informed by the corpus analysis | locked v2c (pilot-zero-v2c-locked) | v3 (hip-hop v3.hiphop.0, other genres v3.genres.0) |',
         '| Representative examples attached for IRB review | prerecorded examples | presumably from the original set | differ from those examples |',
         f"| Soundfont | not specified | Musyng Kite | {env['soundfont']}{' (preliminary)' if prelim else ''} |",
         '| Audio format in Qualtrics | not specified | WAV hosted on GitHub Pages | MP3 provided (WAV masters also) |',
         '| Volume and practice clips | 1 + 2 | original v2c clips (4 bars) | originals kept; v3 candidates provided separately |',
         '| 10 s clips | not in protocol | the 4-bar set is about 8-16 s | internal previews only, not for participants |', '',
         'The 27 conditions, the two rating questions and scales, the randomised once-each presentation and the '
         'volume / practice structure are unchanged.', '']
    (E / 'protocol_differences.md').write_text('\n'.join(P))

    # ---------------------------------------------------------------- Qualtrics readiness
    Qr = ['# Qualtrics readiness', '',
          'Nothing here changes the live survey. The original build (`experiments/music_rating/qualtrics/`) uses a '
          'Loop & Merge block with 27 rows and "Randomize loop order", one audio URL and the stimulus ID per row.', '',
          '## Files', '',
          '- `A_qualtrics_mp3/S01.mp3`-`S27.mp3`: upload to the Qualtrics library (or the hosting the build uses).',
          '- `E_analysis/qualtrics_loop_merge_rows.csv`: one row per excerpt (stimulus ID, file, an empty `url` '
          'column to fill after upload), in the same shape as `deploy/audio_urls.csv`.',
          '- `E_analysis/analysis_variables.csv`: private; join on `stimulus_id` after export.',
          '- `E_analysis/stimulus_manifest.csv` / `.json`: the private answer key.', '',
          '## Randomisation and identity', '',
          '- Present the 27 as Loop & Merge rows with randomised loop order (each exactly once), and carry the '
          'stimulus ID as a loop field (embedded data) so every exported rating row names its S ID. Do not rely on '
          'loop position.',
          '- Practice and volume trials outside the loop, fixed order, as in the original survey.', '',
          '## Practice and volume clips', '',
          '- The original volume clip is pop:3 (stim seed 2) and the practice clips lofi:2 and pop:4. They are 4-bar '
          'v2c clips. If the main excerpts become 8-bar v3, practice clips of the same length and generator '
          'represent the task better; candidates are in `G_candidate_practice_volume/` (same cells, other seeds, '
          'loudness matched to the original practice / volume cells). Using them is the researcher\'s decision.',
          (f"- **Volume level:** the volume clip sits at {vol['lufs']:.1f} LUFS; the loudest main excerpt is "
           f"{loudest['lufs_integrated']:.1f} LUFS ({loudest['stimulus_id']}), {loudest['lufs_integrated'] - vol['lufs']:.1f} LU "
           'louder. The protocol\'s risk section relies on the volume sample to avoid unexpectedly loud music; '
           'consider a volume clip at or near the loudest excerpt\'s level.' if vol else ''), '',
          '## Check by hand before launch', '',
          '- Playback of every MP3 in Chrome, Safari and Firefox, desktop and mobile; no autoplay restrictions '
          'blocking the first clip; the clip plays completely before the sliders appear (as in the original survey).',
          '- The exported data carry the S ID for all 27 rows, with no duplicates and no missing IDs.',
          '- MP3 encoder delay: each MP3 starts with about 25 ms of encoder padding; durations match the WAVs within '
          '0.12 s (verified).',
          f"- Calm excerpts are the quietest ({quietest['lufs_integrated']:.1f} LUFS); check they are audible at the "
          'volume participants set.', '']
    (E / 'qualtrics_readiness.md').write_text('\n'.join(Qr))
    del mono, sims, hh, by_rung
