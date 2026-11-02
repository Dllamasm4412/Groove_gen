"""
Reports and research files for the candidate corpus (called by build_candidate.py).

Everything here is computed from the rendered files, the MIDI and the original
study's read-only manifest. Measurements describe the stimuli; they are not
listener responses, and nothing here validates perceived danceability.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from statistics import fmean, median

import numpy as np

REPO = Path(__file__).resolve().parent.parent.parent
CORPUS_FEATURES = REPO / 'groovegen_project' / 'data' / 'track_features.csv'
FEATURE_COLS = ('tempo_bpm', 'duration_s', 'lufs_integrated', 'peak_dbfs', 'drum_onsets_per_s', 'drum_notes_per_bar',
                'hat_notes_per_bar', 'bass_notes_per_bar', 'bass_on_kick_share', 'offbeat_index', 'parts',
                'notes_per_s', 'centroid_hz', 'flux', 'pulse_clarity', 'low_ratio', 'tempo_estimated_bpm',
                'energy_u_delivered', 'energy_u_midi_reference', 'corpus_onset_density', 'corpus_plp_mean',
                'corpus_beat_consistency', 'corpus_hpss_percussive_ratio', 'corpus_low_band_energy_ratio',
                'corpus_spectral_centroid_mean', 'corpus_tempo_final')
CORPUS_CORRELATES = (   # Spearman rho with Spotify danceability over the corpus's 644 tracks (computed 2026-11-02)
    ('hpss_percussive_ratio', '+0.30'), ('plp_mean', '+0.28'), ('low_band_energy_ratio', '+0.26'),
    ('tempo_folded', '+0.21'), ('beat_consistency', '+0.13'), ('onset_density', '+0.11'),
    ('lhl_syncopation_mean', '-0.07 (n.s.)'), ('rms_mean (loudness)', '+0.05 (n.s.)'),
    ('spectral_centroid_mean', '+0.02 (n.s.)'), ('Spotify energy', '-0.09'))


def _csv(path: Path, rows: list[dict], cols=None) -> None:
    cols = cols or list(dict.fromkeys(k for r in rows for k in r if not k.startswith('_')))
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def _spearman(x, y) -> float | None:
    from scipy import stats

    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    if len(pairs) < 3:
        return None
    return round(float(stats.spearmanr(*zip(*pairs)).statistic), 3)


def _chroma(path: Path) -> np.ndarray:
    import librosa

    from build_candidate import read_wav, SR
    x = read_wav(path).mean(axis=1)
    c = librosa.feature.chroma_stft(y=x, sr=SR, hop_length=2048).mean(axis=1)
    return c / (np.linalg.norm(c) + 1e-9)


def similarity(out: Path, rows: list[dict]) -> list[dict]:
    import pretty_midi

    from build_candidate import lead_ngrams
    grams = {r['stimulus_id']: lead_ngrams(pretty_midi.PrettyMIDI(str(out / r['midi_file']))) for r in rows}
    chroma = {r['stimulus_id']: _chroma(out / r['wav_file']) for r in rows}
    pairs = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            x, y = a['stimulus_id'], b['stimulus_id']
            j = len(grams[x] & grams[y]) / max(len(grams[x] | grams[y]), 1)
            h = max(float(chroma[x] @ np.roll(chroma[y], k)) for k in range(12))
            pairs.append({'a': x, 'b': y, 'a_condition': a['condition_id'], 'b_condition': b['condition_id'],
                          'same_genre': a['genre'] == b['genre'], 'melody_ngram_overlap': round(j, 3),
                          'pitch_class_profile_similarity_key_invariant': round(h, 4),
                          'identical_midi': a['midi_sha256'] == b['midi_sha256']})
    return pairs


def corpus_percentiles(rows: list[dict]) -> dict:
    """Where each excerpt's corpus-named features fall in the corpus distribution.
    Approximate: the excerpts are measured with the re-implemented extractor
    (groovegen_project/groovegen/profile_from_songs.py), not the original one."""
    import pandas as pd

    if not CORPUS_FEATURES.exists():
        return {}
    tf = pd.read_csv(CORPUS_FEATURES)
    out = {}
    for col in ('onset_density', 'plp_mean', 'beat_consistency', 'hpss_percussive_ratio', 'low_band_energy_ratio'):
        ref = tf[col].dropna().values
        for r in rows:
            v = r.get(f'corpus_{col}')
            if isinstance(v, (int, float)):
                out.setdefault(r['stimulus_id'], {})[col] = round(float((ref < v).mean() * 100), 1)
    return out


def monotonicity(rows: list[dict]) -> list[dict]:
    """Within each genre, does each tier step raise the rhythm / layering measures?"""
    feats = ('drum_onsets_per_s', 'drum_notes_per_bar', 'bass_notes_per_bar', 'parts', 'lufs_integrated',
             'energy_u_delivered', 'corpus_hpss_percussive_ratio', 'corpus_plp_mean', 'offbeat_index')
    out = []
    for genre in sorted({r['genre'] for r in rows}):
        g = sorted((r for r in rows if r['genre'] == genre), key=lambda r: r['tier'])
        for a, b in zip(g, g[1:]):
            row = {'genre': genre, 'step': f"{a['tier']}->{b['tier']}"}
            for f in feats:
                va, vb = a.get(f), b.get(f)
                row[f] = None if not isinstance(va, (int, float)) or not isinstance(vb, (int, float)) else round(vb - va, 3)
            out.append(row)
    return out


def write_reports(out: Path, dirs: dict, rows: list[dict], log: list[dict], audit: list[dict],
                  practice: list[dict], verification: list[dict], env: dict, cond_src: dict, label: str) -> None:
    E = dirs['E']
    prelim = not env['soundfont_is_locked_musyng']
    sims = similarity(out, rows)
    pct = corpus_percentiles(rows)
    for r in rows:
        for k, v in pct.get(r['stimulus_id'], {}).items():
            r[f'corpus_percentile_{k}'] = v
    mono = monotonicity(rows)
    by_sid = sorted(rows, key=lambda r: r['stimulus_id'])
    by_rung = sorted(rows, key=lambda r: r['ladder_rung'])

    # ---- data files -------------------------------------------------------
    manifest = {'corpus_version': 'qualtrics-27-candidate-v3.0', 'status': 'CANDIDATE - not frozen, not approved',
                'preliminary_soundfont': prelim, 'environment': env, 'conditions_source': cond_src,
                'stimuli': [{k: v for k, v in r.items() if not k.startswith('_')} for r in by_sid],
                'practice_volume_candidates': practice}
    (E / 'stimulus_manifest.json').write_text(json.dumps(manifest, indent=1, default=str))
    _csv(E / 'stimulus_manifest.csv', by_sid)
    _csv(E / 'audio_features.csv', by_sid, ['stimulus_id', 'condition_id', 'genre', 'tier', 'ladder_rung',
                                             *FEATURE_COLS, 'loudness_target_lufs', 'match_gain_db', 'limiter_applied',
                                             *sorted({k for r in rows for k in r if k.startswith('corpus_percentile_')})])
    _csv(E / 'generation_log.csv', log)
    _csv(E / 'condition_audit.csv', audit)
    _csv(E / 'similarity_pairs.csv', sorted(sims, key=lambda p: -p['melody_ngram_overlap']))
    _csv(E / 'within_genre_tier_steps.csv', mono)
    _csv(E / 'practice_volume_candidates.csv', practice)
    (E / 'verification.json').write_text(json.dumps(verification, indent=1))
    # Qualtrics: neutral mapping (no condition info) and analysis variables (private)
    _csv(E / 'qualtrics_loop_merge_rows.csv',
         [{'loop_row': i + 1, 'stimulus_id': r['stimulus_id'], 'file': f"{r['stimulus_id']}.mp3", 'url': ''}
          for i, r in enumerate(by_sid)])
    _csv(E / 'analysis_variables.csv', [{
        'stimulus_id': r['stimulus_id'], 'condition_id': r['condition_id'], 'genre': r['genre'], 'tier': r['tier'],
        'coding_within_genre_tier': r['coding_within_genre_tier'], 'coding_energy_ladder_rung': r['ladder_rung'],
        'ladder_u': r['ladder_u'], 'intended_danceability_level': '', 'generator_version': r['generator_version'],
        'tempo_bpm': r['tempo_bpm'], 'lufs_integrated': r['lufs_integrated'], 'drum_onsets_per_s': r['drum_onsets_per_s'],
        'energy_u_delivered': r['energy_u_delivered'], 'duration_s': r['duration_s']} for r in by_sid])
    sheet_cols = ['stimulus_id', 'musical_quality_1to5', 'urge_to_move_1to5', 'calming_1to5', 'genre_appropriate_1to5',
                  'coherence_1to5', 'repetitive_or_incomplete_y_n', 'technical_or_musical_problems_with_timestamps',
                  'keep_for_study_y_n_maybe']
    _csv(E / 'researcher_listening_sheet.csv', [{'stimulus_id': r['stimulus_id']} for r in by_sid], sheet_cols)

    # ---- condition audit (markdown) -----------------------------------------
    A = ['# Condition audit: the 27 conditions of the original study', '',
         f"Source: `{cond_src['source']}` (sha256 {cond_src['sha256'][:16]}..., built {cond_src['built_at']}, "
         f"locked source commit {cond_src['source_commit'][:10]}). Read only.", '',
         'Each condition is one live ladder cell (genre x tier). The original frozen clip is the first 4 bars of '
         "the cell's first 8-bar segment (locked v2c, stim seed 1). The columns `orig8_*` are measured here on the "
         f"full 8-bar segment, regenerated from the locked code and rendered with **{env['soundfont']}**; "
         '`table_*` are the locked energy table (measured on Musyng Kite).', '',
         '| Rung | Condition | Genre | Tier | Ladder u | Tempo | Density (v2c) | Original clip | Generator (v2c) | '
         '8-bar segment reproduced | Drum onsets/s | Drum notes/bar | Off-beat index | Bass on kick | LUFS (8-bar, this sf) | '
         'Energy u (8-bar) | Table LUFS (Musyng) | Table drum/s |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for a in audit:
        A.append(f"| {a['ladder_rung']} | {a['condition_id']} | {a['genre']} | {a['tier']} | {a['ladder_u']:.3f} | "
                 f"{a['tempo_bpm']:g} | {a['density_v2c']} | {a['original_stimulus_id']} ({a['original_clip_bars']} bars, "
                 f"{a['original_clip_duration_s']:.1f} s) | {a['original_gen_version']} | "
                 f"{'yes' if a['original_segment_reproduced'] else 'NO'} | {a['orig8_drum_onsets_per_s']:.2f} | "
                 f"{a['orig8_drum_notes_per_bar']:.1f} | {a['orig8_offbeat_index']} | {a['orig8_bass_on_kick_share']} | "
                 f"{a['orig8_lufs_target']:.1f} | {a['orig8_energy_u_delivered']:.2f} | {a['table_lufs_musyng']:.1f} | "
                 f"{a['table_drum_rate']:.2f} |")
    us = [a['ladder_u'] for a in audit]
    ties = [(audit[i]['condition_id'], audit[i + 1]['condition_id'], round(us[i + 1] - us[i], 4))
            for i in range(len(audit) - 1) if us[i + 1] - us[i] < 0.03]
    A += ['', '## Findings', '',
          '- **No intended-danceability level exists for any condition.** The frozen manifest records only the ladder '
          'rung and `ladder_u`, a composite *energy* scale (see `README.md`, "Intended danceability").',
          f"- **Near-ties on the energy ladder** (adjacent u within 0.03, the ladder's own within-cell spread): "
          + ', '.join(f'{a} / {b} (+{d})' for a, b, d in ties) + '.',
          '- **Within-genre tiers change density, not tempo,** for calm, lo-fi, R&B, pop and Latin (constant tempo per '
          'genre); hip-hop and rock tiers also raise the tempo.',
          '- **Tier caps:** calm has tiers 1-2 only, lo-fi 1-3, R&B 1-4, Latin 1-3 (capped live in 2026-09 because the '
          'developer heard Latin as R&B-level energy); pop, hip-hop and rock 1-5.',
          '- **Generator versions differ by genre in the original set:** rock has no development policy (v2a.3), '
          'hip-hop uses v2b.1, the others v2c.<genre>.',
          '- **Clip length:** the original frozen clips are 4 bars (7.9-15.7 s); the submitted protocol describes '
          'eight-bar excerpts of about 15-30 s (see `protocol_differences.md`).', '']
    # adjacent tiers of a genre in the ORIGINAL set: same drum part? same rhythm statistics?
    import pretty_midi

    def drum_events(a):
        pm = pretty_midi.PrettyMIDI(str(out / a['orig8_reference_wav'].replace('.wav', '.mid').replace(
            'F_reference_original_v2c_8bar/', 'F_reference_original_v2c_8bar/midi/')))
        step = 60.0 / float(pm.get_tempo_changes()[1][0]) / 4
        return {(n.pitch, int(round(n.start / step))) for i in pm.instruments if i.is_drum for n in i.notes}
    A += ['## Adjacent tiers in the original set', '',
          'Drum-event overlap between a tier and the next one of the same genre in the original 8-bar segments '
          '(Jaccard over (drum sound, 16th step); 1 = the same drum part), and whether the rhythm statistics are '
          'identical.', '', '| Genre | Tiers | Drum overlap | Same drum onsets/s, drum notes/bar and off-beat index |',
          '|---|---|---|---|']
    dup = []
    for g in sorted({a['genre'] for a in audit}):
        ga = sorted((a for a in audit if a['genre'] == g), key=lambda a: a['tier'])
        for x, y in zip(ga, ga[1:]):
            ex, ey = drum_events(x), drum_events(y)
            j = len(ex & ey) / max(len(ex | ey), 1)
            same = all(x[f'orig8_{k}'] == y[f'orig8_{k}'] for k in ('drum_onsets_per_s', 'drum_notes_per_bar', 'offbeat_index'))
            A.append(f"| {g} | {x['tier']} -> {y['tier']} | {j:.2f} | {'yes' if same else 'no'} |")
            if j >= 0.9 or same:
                dup.append(f"{g} {x['tier']}->{y['tier']}")
    A += ['', '**Within-genre tiers whose rhythm hardly differs in the original set:** ' + (', '.join(dup) or 'none')
          + '. For these, the original tier difference lies mainly in loudness, accompaniment density and (hip-hop, '
          'rock) tempo, not in the drum pattern.', '',
          '**Calm** in the original set has a light pulse at both tiers (kick on beats 1 and 3, quarter-note hats, '
          'rim on beat 3) with pad and piano; the v3 candidate keeps that pulse, mixed under the piano.', '']
    (E / 'condition_audit.md').write_text('\n'.join(A))

    # ---- quality control report ----------------------------------------------
    ok = all(v['ok'] for v in verification)
    top_sim = sorted(sims, key=lambda p: -p['melody_ngram_overlap'])[:6]
    top_pc = sorted(sims, key=lambda p: -p['pitch_class_profile_similarity_key_invariant'])[:6]
    rung = [r['ladder_rung'] for r in by_rung]
    Q = ['# Quality-control report', '',
         f"Corpus `{label}`, {len(rows)} excerpts, generator commit {env['git_head'][:10]}"
         f"{' (uncommitted changes present)' if env['git_dirty'] else ''}, {env['fluidsynth']}, soundfont "
         f"{env['soundfont']} (sha256 {env['soundfont_sha256'][:16]}...).", '',
         ('**PRELIMINARY: not rendered with Musyng Kite.** Musyng Kite was not available in the environment that '
          'built this package. The MIDI is final for this candidate version; the audio must be re-rendered with '
          'Musyng Kite (README, "Render with Musyng Kite") before any researcher decision on sound.' if prelim else
          'Rendered with the locked Musyng Kite file.'), '',
         'Nobody has listened to these files. Everything below is automated measurement; it cannot establish musical '
         'quality, coherence or perceived danceability.', '',
         '## 1. File verification', '',
         f"All 27 WAV masters and MP3s pass every check: **{'yes' if ok else 'NO'}**.", '',
         '| Check | Passed |', '|---|---|']
    for key in [k for k in verification[0] if k not in ('stimulus_id', 'ok', 'duration_s', 'mp3_duration_s')]:
        Q.append(f"| {key} | {sum(bool(v[key]) for v in verification)}/27 |")
    durs = [v['duration_s'] for v in verification]
    Q += ['', f"Durations {min(durs):.2f}-{max(durs):.2f} s (8 bars + a quarter-bar release fade). "
          f"Peaks {min(r['peak_dbfs'] for r in rows):.1f} to {max(r['peak_dbfs'] for r in rows):.1f} dBFS. "
          f"Loudness {min(r['lufs_integrated'] for r in rows):.1f} to {max(r['lufs_integrated'] for r in rows):.1f} LUFS "
          f"(integrated). Limiter used on {sum(r['limiter_applied'] for r in rows)} excerpt(s).", '',
          '## 2. Loudness: matched to each original condition', '',
          'Each excerpt is scaled by one static gain so its integrated loudness equals the original condition\'s '
          '8-bar v2c segment rendered the same way on the same soundfont (loudness is part of the original '
          'configurations and is kept, not normalised).', '',
          '| ID | Condition | Target LUFS | Delivered LUFS | Gain dB | Limiter | Peak dBFS |', '|---|---|---|---|---|---|---|']
    for r in by_rung:
        Q.append(f"| {r['stimulus_id']} | {r['condition_id']} | {r['loudness_target_lufs']:.2f} | {r['lufs_integrated']:.2f} | "
                 f"{r['match_gain_db']:+.2f} | {'yes' if r['limiter_applied'] else 'no'} | {r['peak_dbfs']:.2f} |")
    big = [r for r in rows if abs(r['match_gain_db']) > 8]
    Q += ['', f"Large matching gains (> 8 dB): {', '.join(r['stimulus_id'] + ' ' + r['condition_id'] for r in big) or 'none'}. "
          'A large gain means the v3 arrangement is much quieter or louder than the original before matching; the '
          'level then comes from the original configuration, not from the arrangement.', '',
          '## 3. Measured features by condition (ladder order)', '',
          '| ID | Condition | Tempo | Est. tempo | Drum onsets/s | Drum notes/bar | Bass notes/bar | Bass on kick | '
          'Off-beat idx | Parts | Centroid Hz | Flux | Pulse clarity | Energy u (delivered) | u (MIDI ref.) |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in by_rung:
        Q.append(f"| {r['stimulus_id']} | {r['condition_id']} | {r['tempo_bpm']:g} | {r['tempo_estimated_bpm']:.0f} | "
                 f"{r['drum_onsets_per_s']:.2f} | {r['drum_notes_per_bar']:.1f} | {r['bass_notes_per_bar']:.1f} | "
                 f"{r['bass_on_kick_share']} | {r['offbeat_index']} | {r['parts']} | {r['centroid_hz']:.0f} | "
                 f"{r['flux']:.2f} | {r['pulse_clarity']:.2f} | {r['energy_u_delivered']:.2f} | "
                 f"{r['energy_u_midi_reference']:.2f} |")
    est_off = [r for r in rows if not (0.9 < r['tempo_estimated_bpm'] / r['tempo_bpm'] < 1.1
                                       or 0.45 < r['tempo_estimated_bpm'] / r['tempo_bpm'] < 0.55
                                       or 1.9 < r['tempo_estimated_bpm'] / r['tempo_bpm'] < 2.1)]
    Q += ['', 'Tempo is exact by construction (MIDI); the estimated tempo is librosa\'s beat tracker on the audio, '
          'which may report half or double time. Estimates not within 10% of the tempo, its half or its double: '
          + (', '.join(f"{r['stimulus_id']} ({r['condition_id']}, {r['tempo_estimated_bpm']:.0f})" for r in est_off)
             or 'none') + '.', '',
          '## 4. Are the intended within-genre differences present?', '',
          'Change from each tier to the next within a genre (positive = the higher tier has more). See '
          '`within_genre_tier_steps.csv`.', '',
          '| Genre | Step | Drum onsets/s | Drum notes/bar | Bass notes/bar | Parts | LUFS | Energy u | Percussive ratio | '
          'Pulse (PLP) | Off-beat idx |', '|---|---|---|---|---|---|---|---|---|---|---|']
    for m in mono:
        Q.append(f"| {m['genre']} | {m['step']} | {m['drum_onsets_per_s']} | {m['drum_notes_per_bar']} | "
                 f"{m['bass_notes_per_bar']} | {m['parts']} | {m['lufs_integrated']} | {m['energy_u_delivered']} | "
                 f"{m['corpus_hpss_percussive_ratio']} | {m['corpus_plp_mean']} | {m['offbeat_index']} |")
    flat = [m for m in mono if (m['drum_notes_per_bar'] or 0) <= 0 and (m['bass_notes_per_bar'] or 0) <= 0
            and (m['parts'] or 0) <= 0]
    neg_u = [m for m in mono if (m['energy_u_delivered'] or 0) < 0.03]
    Q += ['', '**Flags:**', '',
          '- Steps where drum notes, bass notes and the number of parts do not increase (rhythmic manipulation absent '
          'or weak): ' + (', '.join(f"{m['genre']} {m['step']}" for m in flat) or 'none') + '.',
          '- Steps where the delivered energy score rises by less than 0.03 (the ladder\'s tie band; strong overlap): '
          + (', '.join(f"{m['genre']} {m['step']} ({m['energy_u_delivered']:+})" for m in neg_u) or 'none') + '.',
          '- Calm keeps the original configuration\'s light pulse at both tiers; tier 2 adds a second kick, 8th-note '
          'hats and a flowing piano texture.', '',
          '## 5. Across the ladder', '',
          f"Spearman correlation with the ladder rung, over the 27 excerpts: delivered energy u "
          f"{_spearman(rung, [r['energy_u_delivered'] for r in by_rung])}, drum onsets/s "
          f"{_spearman(rung, [r['drum_onsets_per_s'] for r in by_rung])}, percussive ratio "
          f"{_spearman(rung, [r.get('corpus_hpss_percussive_ratio') for r in by_rung])}, pulse (PLP) "
          f"{_spearman(rung, [r.get('corpus_plp_mean') for r in by_rung])}, loudness "
          f"{_spearman(rung, [r['lufs_integrated'] for r in by_rung])}. For the original 8-bar segments: energy u "
          f"{_spearman([a['ladder_rung'] for a in audit], [a['orig8_energy_u_delivered'] for a in audit])}.", '',
          '## 6. Identical or near-identical excerpts', '',
          f"Identical MIDI pairs: {sum(p['identical_midi'] for p in sims)}. Highest melodic overlap "
          '(transposition-invariant 3-note interval and rhythm n-grams of the lead line; 1 = the same phrases):', '',
          '| A | B | Same genre | Melody overlap | Pitch-class profile similarity |', '|---|---|---|---|---|']
    Q += [f"| {p['a']} ({p['a_condition']}) | {p['b']} ({p['b_condition']}) | {p['same_genre']} | "
          f"{p['melody_ngram_overlap']} | {p['pitch_class_profile_similarity_key_invariant']} |" for p in top_sim]
    Q += ['', 'Highest key-invariant pitch-class-profile similarity (whole-file chroma; similar harmony / key '
          'colour, not similar music):', '', '| A | B | Same genre | Similarity |', '|---|---|---|---|']
    Q += [f"| {p['a']} ({p['a_condition']}) | {p['b']} ({p['b_condition']}) | {p['same_genre']} | "
          f"{p['pitch_class_profile_similarity_key_invariant']} |" for p in top_pc]
    outl = []
    for f in ('centroid_hz', 'flux', 'pulse_clarity', 'drum_onsets_per_s'):
        v = np.array([r[f] for r in rows], float)
        z = (v - v.mean()) / (v.std() + 1e-9)
        outl += [f"{rows[i]['stimulus_id']} {rows[i]['condition_id']} {f} {v[i]:.2f} (z {z[i]:+.1f})"
                 for i in np.where(np.abs(z) > 2.2)[0]]
    Q += ['', '## 7. Acoustic outliers (|z| > 2.2 across the 27)', '', '- ' + ('\n- '.join(outl) if outl else 'none'), '',
          '## 8. Rule checks and coherence proxies', '',
          '- Every selected excerpt passed the generator\'s structural rule checks (chord tones on strong melody '
          'notes, bass on chord tones, the drum backbone of its genre and tier, ranges, no vocal programs, the phrase '
          'and the melody ending on the tonic for the six new genres; the v3 hip-hop rules for hip-hop).',
          f"- Candidates screened: {len(log)}; rejected: {sum(not l['passed'] for l in log)} "
          '(reasons in `generation_log.csv`).',
          '- Coherence, groove, genre identity and musical quality are **not** measurable here and need listening '
          '(`researcher_listening_sheet.csv`). The six non-hip-hop v3 genres have not been heard by anyone yet.', '',
          '## 9. Corpus-referenced features (approximate)', '',
          'Percentile of each excerpt within the 644-track corpus on the features that correlate with Spotify '
          'danceability there. The excerpts are measured with the repository\'s re-implementation of the corpus '
          'extractor, not the original extractor, and are 15-30 s rather than 30 s previews: treat as indicative. '
          'See `audio_features.csv` (`corpus_percentile_*`).', '']
    (E / 'quality_control_report.md').write_text('\n'.join(Q))

    # ---- researcher listening sheet (markdown) ------------------------------------
    S = ['# Researcher listening sheet (stimulus development; not participant data)', '',
         'Listen in ID order (`listening/playlist_S01-S27.m3u` or `listening/all_27_in_ID_order_3s_gaps.mp3`). '
         'Rate 1-5 (1 poor, 5 excellent). The IDs do not reveal genre or condition; the key is '
         '`stimulus_manifest.csv`. The same columns are in `researcher_listening_sheet.csv`.', '',
         '| ID | Quality | Urge to move | Calming | Genre fits | Coherent | Repetitive / incomplete? | Problems (with times) | Keep? |',
         '|---|---|---|---|---|---|---|---|---|']
    S += [f"| {r['stimulus_id']} | | | | | | | | |" for r in by_sid]
    (E / 'researcher_listening_sheet.md').write_text('\n'.join(S) + '\n')

    from candidate_docs import write_docs
    write_docs(out, E, rows, audit, practice, env, label, prelim, mono, sims)
