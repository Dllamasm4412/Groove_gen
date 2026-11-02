"""
Final candidate package for the Qualtrics danceability / calming study
(IRB 26-0684): the v3.1 candidate corpus, verified and unchanged, with the
documents the study needs before stimuli can be frozen, and a draft survey.

Nothing is regenerated: the audio and MIDI are copied from a built candidate
package after checking every file against its manifest hashes. Added:
  E_analysis/  intended-danceability coding and its evaluation, tier comparison,
               analysis plan (primary and calming), review status and revision
               history, protocol differences, readiness checklist, stimulus key
  H_qualtrics_draft/  two draft .qsf files made from the existing survey
               (survey_v3.py), their automated validation, the survey audit,
               the manual test plan, the audio upload list
  listening/   all 27 in one file, playlist, before/after of the revised
               excerpts, final review sheet

Usage (repository root):
    python experiments/qualtrics_v3_candidate/finalize_candidate.py build --from <candidate package> \\
        --original-qsf GrooveGen_music_rating.qsf [--base-url URL] [--zip]
    python experiments/qualtrics_v3_candidate/finalize_candidate.py check-urls --package <final package>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import danceability_coding as dcode  # noqa: E402
import survey_v3 as sv  # noqa: E402

PACKAGE_VERSION = 'v3.1-rc1'
COPY_DIRS = ('A_qualtrics_mp3', 'B_wav_masters', 'C_midi_sources', 'D_internal_previews_10s',
             'F_reference_original_v2c_8bar', 'G_candidate_practice_volume', 'listening')
REVISED = ('S03', 'S04', 'S05', 'S14', 'S21', 'S24')
V3_PRACTICE = {'practice': [('P01', 'PRACTICE_1.mp3'), ('P02', 'PRACTICE_2.mp3')], 'volume': ('V01', 'VOLUME.mp3')}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def verify_source(src: Path) -> tuple[dict, list[str]]:
    m = json.loads((src / 'E_analysis' / 'stimulus_manifest.json').read_text())
    problems = []
    for r in m['stimuli']:
        for key, hkey in (('wav_file', 'wav_sha256'), ('mp3_file', 'mp3_sha256')):
            p = src / r[key]
            if not p.exists():
                problems.append(f"{r['stimulus_id']}: missing {r[key]}")
            elif sha256(p) != r[hkey]:
                problems.append(f"{r['stimulus_id']}: {r[key]} does not match its manifest hash")
        if not (src / r['midi_file']).exists():
            problems.append(f"{r['stimulus_id']}: missing {r['midi_file']}")
    ids = sorted(r['stimulus_id'] for r in m['stimuli'])
    if ids != [f'S{k:02d}' for k in range(1, 28)]:
        problems.append('stimulus IDs are not exactly S01-S27')
    return m, problems


# =============================================================================
# Survey drafts
# =============================================================================


def write_survey_drafts(original: Path, pkg: Path, out: Path, base_url: str) -> dict:
    import import_v3_export as iv

    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((pkg / 'E_analysis' / 'stimulus_manifest.json').read_text())
    orig, _ = sv.load(original)
    reproduced = sv.reproduces(original)
    results = {'original_sha256': sha256(original), 'original_reproduced_by_builder': reproduced, 'drafts': {}}
    for mode, name in (('original', 'GrooveGen_music_rating_v3_DRAFT.qsf'),
                       ('v3', 'GrooveGen_music_rating_v3_DRAFT_v3practice.qsf')):
        draft, params = sv.build_draft(original, manifest, base_url, mode, V3_PRACTICE)
        (out / name).write_text(sv.dumps(draft), encoding='utf-8')
        checks = sv.validate(draft, params, manifest, orig)
        # simulated export round trip: does the import name the right stimulus for every rating?
        stim = {r['stimulus_id']: r for r in manifest['stimuli']}
        trip = {}
        for prefix in ('row', 'position'):
            text = sv.simulated_export(params, prefix=prefix)
            tmp = out / f'_sim_{prefix}.csv'
            tmp.write_text(text)
            header, rows = iv.iq.read_export(tmp)
            tmp.unlink()
            long_rows, people, problems = iv.import_rows(rows, header, stim, {}, prefix)
            ok = all(int(x['stimulus_id'][1:]) == x['danceability'] and 100 - x['position'] == x['calming']
                     for x in long_rows)
            trip[prefix] = {'participants': len(people), 'ratings': len(long_rows), 'all_mapped_correctly': ok,
                            'problems': problems, 'practice_rows_in_analysis': sum(
                                x['stimulus_id'] in params['practice'] for x in long_rows)}
        results['drafts'][name] = {'practice_mode': mode, 'build': params['build'], 'checks': checks,
                                   'diff': sv.diff_summary(orig, draft), 'round_trip': trip,
                                   'sha256': sha256(out / name),
                                   'upload': [{'id': i, 'url': params['urls'][i]} for i in
                                              params['main'] + params['practice'] + [params['volume']]]}
    upload = []
    for r in sorted(manifest['stimuli'], key=lambda r: r['stimulus_id']):
        upload.append({'id': r['stimulus_id'], 'file_in_package': r['mp3_file'], 'url': base_url + Path(r['mp3_file']).name,
                       'sha256': r['mp3_sha256'], 'needed_by': 'both drafts'})
    for i, f in V3_PRACTICE['practice'] + [V3_PRACTICE['volume']]:
        p = pkg / 'G_candidate_practice_volume' / f
        upload.append({'id': i, 'file_in_package': f'G_candidate_practice_volume/{f}', 'url': base_url + f,
                       'sha256': sha256(p) if p.exists() else '', 'needed_by': 'v3practice draft only'})
    _csv(out / 'audio_upload_list.csv', upload)
    results['assembled_at'] = assembly_commit()
    (out / 'survey_build.json').write_text(json.dumps(results, indent=1, default=str))
    _survey_docs(out, results, base_url)
    return results


def _survey_docs(out: Path, results: dict, base_url: str) -> None:
    d1 = results['drafts']['GrooveGen_music_rating_v3_DRAFT.qsf']
    V = ['# Survey validation report (automated)', '',
         'Checks run by `survey_v3.py` on the draft .qsf files. They test the survey file and the import mapping; '
         '**they are not a Qualtrics test**: nothing was imported into Qualtrics, no browser played a clip, and the '
         'audio links were not reachable from the build environment. Those steps are in `survey_test_plan.md`.', '',
         f"Existing survey: sha256 {results['original_sha256'][:16]}... (equal to the build recorded in "
         "`experiments/music_rating/qualtrics/deploy/build.json`).", '',
         f"**The existing survey is reproduced byte for byte by the repository's builder from its own parameters: "
         f"{'yes' if results['original_reproduced_by_builder'] else 'NO'}.** The drafts are made by the same builder "
         'with the v3 stimulus parameters, plus the edits in `survey_changes.md`, so everything else in the survey is '
         'unchanged by construction.', '']
    for name, d in results['drafts'].items():
        n_ok = sum(c['passed'] for c in d['checks'])
        V += [f'## {name} (practice and volume clips: {d["practice_mode"]})', '',
              f"{n_ok} of {len(d['checks'])} checks pass. Build ID `{d['build']}`. sha256 {d['sha256'][:16]}...", '',
              '| Check | Result | Detail |', '|---|---|---|']
        V += [f"| {c['check']} | {'pass' if c['passed'] else '**FAIL**'} | {c['detail']} |" for c in d['checks']]
        V += ['', '**Simulated export round trip.** Twelve simulated respondents with random clip orders; each set '
              'the dance slider to the stimulus number and calming to 100 minus the position. The importer must name '
              'the right stimulus and position for every rating:', '']
        for prefix, t in d['round_trip'].items():
            V.append(f"- loop columns numbered by {prefix}: {t['ratings']} ratings from {t['participants']} "
                     f"respondents, all mapped correctly: **{'yes' if t['all_mapped_correctly'] else 'NO'}**, "
                     f"practice rows in the analysis table: {t['practice_rows_in_analysis']}, problems: "
                     f"{len(t['problems'])}")
        V += ['', 'Which numbering Qualtrics uses must be confirmed with one real test response '
              '(`survey_test_plan.md`, step 6).', '']
    (out / 'survey_validation_report.md').write_text('\n'.join(V))

    C = ['# Changes from the existing survey', '',
         'The drafts are separate files; the existing survey (`GrooveGen_music_rating.qsf`) and the live Qualtrics '
         'project are not changed. Two drafts differ only in the practice and volume clips:', '',
         '- `GrooveGen_music_rating_v3_DRAFT.qsf`: keeps the **existing** practice clips (lofi:2 and pop:4, 4-bar '
         'v2c) and volume clip (pop:3) and their existing links. No change to those materials.',
         '- `GrooveGen_music_rating_v3_DRAFT_v3practice.qsf`: uses the v3 candidate practice and volume clips '
         '(same cells, other seeds, 8 bars, loudness of the original cells). Replaces participant-facing material: '
         'needs your approval.', '', '## Edits (both drafts)', '',
         '| ID | Change | Why | Kind |', '|---|---|---|---|']
    C += [f'| {i} | {what} | {why} | {kind} |' for i, what, why, kind in sv.EDITS]
    C += ['', '## Element-by-element differences (draft with existing practice clips)', '']
    C += [f'- {x}' for x in d1['diff']]
    C += ['', 'Everything not listed is identical to the existing survey: the two rating questions, their sliders '
          '(0-100, end labels, forced response), the practice loop, the randomised main loop, the player (plays once, '
          'Next hidden until the clip has played completely, then the sliders), the break after clip 14, the '
          'attention slider, the four closing questions, options and branding.', '']
    (out / 'survey_changes.md').write_text('\n'.join(C))

    A = ['# Audit of the existing survey against the protocol', '',
         '| # | Item | Existing survey | Draft | Status |', '|---|---|---|---|---|',
         '| 1 | Consent text | placeholder "[CONSENT INFORMATION: replace this paragraph with the approved consent '
         'text.]" | placeholder kept (the approved consent document was not provided; no consent language invented) | '
         '**blocker: insert the approved text** |',
         '| 2 | Age 18+ confirmation | missing (only "Do you agree to take part?") | age question on the first page; '
         '"under 18" ends the survey | wording needs approval (use the consent document\'s if it has one) |',
         '| 3 | Clip duration in the instructions | "about 8 to 16 seconds" | "about 15 to 30 seconds" | done |',
         '| 4 | 1 volume sample, 2 practice clips | present (v2c, 4 bars, 8.6-13.1 s) | kept, or v3 clips in the '
         'second draft | **your choice** |',
         '| 5 | Audio links and mapping | 36 WAV links on GitHub Pages (27 old main IDs, 2 practice, 1 volume, 6 '
         'unused headphone-check sounds) | S01-S27 MP3 links under a new folder (old files untouched); no old main '
         'ID remains | upload the MP3s and run `check-urls` |',
         '| 6 | Randomised order | main loop randomised (all 27 rows) | unchanged | done |',
         '| 7 | Playback before advancing | Next hidden until the clip has played completely, then the sliders | '
         'unchanged | test in browsers |',
         '| 8 | Rating linked to stimulus | loop row k -> stimulus; play record per stimulus (ID, position, plays, '
         'complete) | row k = S<k>; same records | confirm with one test response |',
         '| 9 | Anonymous responses, embedded data | no anonymise setting in the file; "pid" field (filled from a '
         'link parameter if one is used) | "pid" removed; stim_set and survey_version added | **set "Anonymize '
         'responses" in Qualtrics** |',
         '| 10 | Incomplete responses | Save and continue on; partial responses kept for a week ("PartialData": '
         '"+1 week") | unchanged in the file | **set incomplete responses to be deleted** (protocol) and check |',
         '| 11 | Timing and missing responses | page timer per trial; both sliders forced; untouched sliders '
         'highlighted | unchanged | done |',
         '| 12 | Items not described in the protocol | attention slider, 4 closing questions (headphones, volume, '
         'quiet place, technical problems), break after clip 14, "laptop or desktop" instruction | unchanged | '
         'confirm they were in the survey text submitted to the IRB |',
         '| 13 | Device information | browser user-agent and screen size recorded for the playback check | unchanged '
         '| note for the IRB summary if needed |', '']
    (out / 'survey_audit.md').write_text('\n'.join(A))

    T = ['# Survey test plan (manual, in the institutional Qualtrics account)', '',
         'Do these with the draft imported as a **new** project (Create project > Survey > Import a QSF file). '
         'Nothing here was done by the build; tick each item yourself.', '',
         '## Before importing', '',
         f'1. Upload the 27 MP3s (`A_qualtrics_mp3/`) to `{base_url}` (or another host; then rebuild the drafts with '
         '`--base-url`). For the v3-practice draft also upload `PRACTICE_1.mp3`, `PRACTICE_2.mp3`, `VOLUME.mp3`.',
         '2. Run `finalize_candidate.py check-urls --package <this package>`: every link must download and match its '
         'sha256 (`audio_upload_list.csv`).',
         '3. Replace the consent placeholder with the approved consent text; confirm or replace the age-question '
         'wording.', '',
         '## In Qualtrics, before any participant', '',
         '4. Survey options: Anonymize responses ON; incomplete responses deleted (not recorded); Back button off; '
         'Save and continue as approved.',
         '5. Survey flow: embedded data block first; consent block; "I do not agree" and "under 18" each end the '
         'survey (test both).',
         '6. **Identity check:** take the survey in preview; on each clip set the dance slider to the number shown '
         'above the Play button ("Clip 5 of 27" -> 5). Export (Data & Analysis > Export > CSV, numeric values) and '
         'run `import_v3_export.py EXPORT.csv --package <this package> --verify <ResponseId>`: one numbering must '
         'give 27/27. Use that `--loop-prefix` for the real data.',
         '7. In that export: 27 main rating rows, each S01-S27 exactly once; 2 practice rows not in '
         '`ratings_long.csv`; positions 1-27; `stim_set` filled.',
         '8. Take the survey twice more: the clip order differs; the break appears after clip 14 only.', '',
         '## Playback (desktop and mobile)', '',
         '9. Chrome, Safari, Firefox and Edge on a computer; Safari on iPhone and Chrome on Android: the volume '
         'sample plays and can be replayed; each clip plays once; Next appears only after the clip ends; both sliders '
         'appear after every clip with the end labels "Not at all" / "Extremely" and "Not at all calming" / '
         '"Extremely calming"; a slider cannot be skipped.',
         '10. Interrupt a clip (pause from the keyboard media key, remove headphones on iOS): the play record shows '
         'the pause; the clip restarts from the beginning.',
         '11. Reload the page during a clip: the record shows prior_plays; check how you want to treat it.',
         '12. Loudest excerpt check: set the volume on the sample, then play the loudest excerpt '
         '(see `../E_analysis/qualtrics_readiness.md`); it must not be uncomfortable.', '',
         '## Data', '',
         '13. Leave one response incomplete: it must be deleted (not exported) under the incomplete-response setting.',
         '14. Confirm no IP address or location in the export (anonymized).',
         '15. Run `analyze_v3.py` on the test export to check the pipeline end to end (results meaningless).', '']
    (out / 'survey_test_plan.md').write_text('\n'.join(T))


def check_urls(pkg: Path) -> int:
    rows = list(csv.DictReader((pkg / 'H_qualtrics_draft' / 'audio_upload_list.csv').open()))
    bad = 0
    for r in rows:
        try:
            with urllib.request.urlopen(r['url'], timeout=30) as resp:
                ok = hashlib.sha256(resp.read()).hexdigest() == r['sha256']
        except Exception as exc:     # report and continue
            ok = False
            print(f"{r['id']}: {r['url']}: {exc}")
        bad += not ok
        print(f"{r['id']}: {'ok' if ok else 'MISMATCH OR MISSING'} ({r['needed_by']})")
    print(f'{len(rows) - bad} of {len(rows)} links ok')
    return 1 if bad else 0


# =============================================================================
# Documents
# =============================================================================


def within_genre_rank_r(rows: list[dict], key: str) -> float:
    from scipy import stats
    import numpy as np

    xs, ys = [], []
    for g in {r['genre'] for r in rows}:
        rs = [r for r in rows if r['genre'] == g]
        if len(rs) < 2:
            continue
        t = stats.rankdata([r['tier'] for r in rs])
        v = stats.rankdata([float(r[key]) for r in rs])
        xs += list(t - t.mean())
        ys += list(v - v.mean())
    return round(float(np.corrcoef(xs, ys)[0, 1]), 2)


def assembly_commit() -> dict:
    """The commit that assembled this package (coding, docs, survey drafts); the audio's own build commit is in
    the manifest's environment."""
    import subprocess
    git = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True).stdout.strip()  # noqa: E731
    return {'git_head': git('rev-parse', 'HEAD'), 'git_branch': git('branch', '--show-current'),
            'git_dirty': bool(git('status', '--porcelain', '--untracked-files=no'))}


def write_docs(out: Path, src_manifest: dict, coding: list[dict], steps: list[dict], audit: list[dict],
               survey: dict, label: str, prelim: bool) -> None:
    E = out / 'E_analysis'
    rows = src_manifest['stimuli']
    env = src_manifest['environment']
    code = {c['stimulus_id']: c for c in coding}
    # review status and revision history
    review = []
    for r in sorted(rows, key=lambda r: r['stimulus_id']):
        sid = r['stimulus_id']
        if sid in REVISED:
            hist = ('v3.0 (2026-11-02): generated; researcher listening: '
                    + ('judged poor' if sid in ('S03', 'S04') else 'heard (rock, asked to follow classic hard rock)')
                    + '. v3.1 (2026-11-02): re-generated with v3.genres.1 (same seed), see generator report.')
            status = ('revised after feedback; researcher reported being very pleased with the new music '
                      '(2026-11-02 message); per-excerpt confirmation pending (final_review_sheet.csv)')
        else:
            hist = 'v3.0 (2026-11-02): generated; researcher listening: accepted ("most sound amazing"). v3.1: unchanged.'
            status = 'reviewed in v3.0 and unchanged since (identical MIDI); per-excerpt confirmation pending'
        review.append({'stimulus_id': sid, 'condition_id': r['condition_id'], 'generator_version': r['generator_version'],
                       'seed': r['seed'], 'revised_in_v3.1': sid in REVISED, 'review_status': status,
                       'revision_history': hist})
    _csv(E / 'review_status.csv', review)
    # updated manifest (all build fields kept; coding and review added)
    rv = {x['stimulus_id']: x for x in review}
    for r in rows:
        r.update({'package_version': PACKAGE_VERSION,
                  'status': 'final candidate (not frozen, not approved for participant use)',
                  'intended_danceability_coding': code[r['stimulus_id']]['intended_danceability_coding'],
                  'intended_danceability_status': code[r['stimulus_id']]['coding_status'],
                  'intended_danceability_rule': code[r['stimulus_id']]['coding_rule'],
                  'review_status': rv[r['stimulus_id']]['review_status'],
                  'revision_history': rv[r['stimulus_id']]['revision_history']})
    src_manifest['package_version'] = PACKAGE_VERSION
    src_manifest['package_assembled_at'] = assembly_commit()
    src_manifest['status'] = 'FINAL CANDIDATE - not frozen, not approved for participant use'
    (E / 'stimulus_manifest.json').write_text(json.dumps(src_manifest, indent=1, default=str))
    _csv(E / 'stimulus_manifest.csv', sorted(rows, key=lambda r: r['stimulus_id']))
    _csv(E / 'stimulus_key.csv', [{'stimulus_id': r['stimulus_id'], 'condition_id': r['condition_id'], 'genre': r['genre'],
                                   'tier': r['tier'], 'intended_danceability_coding': r['intended_danceability_coding'],
                                   'ladder_rung': r['ladder_rung'], 'generator_version': r['generator_version'],
                                   'seed': r['seed']} for r in sorted(rows, key=lambda r: r['stimulus_id'])])
    _csv(E / 'final_review_sheet.csv', [{'stimulus_id': r['stimulus_id'], 'approve_for_study_yes_no': '',
                                         'musical_quality_1to5': '', 'urge_to_move_1to5': '', 'calming_1to5': '',
                                         'genre_appropriate_1to5': '', 'coherent_1to5': '',
                                         'repetitive_or_incomplete': '', 'problems_with_timestamps': '', 'comments': ''}
                                        for r in sorted(rows, key=lambda r: r['stimulus_id'])])
    rr = {k: within_genre_rank_r(rows, k) for k in ('drum_notes_per_bar', 'notes_per_s', 'parts', 'bass_notes_per_bar',
                                                     'offbeat_index', 'lufs_integrated', 'tempo_bpm', 'corpus_hpss_percussive_ratio',
                                                     'pulse_clarity', 'centroid_hz', 'energy_u_delivered')}
    v3c = {}
    oc = {}
    for s in steps:
        v3c[s['v3_class']] = v3c.get(s['v3_class'], 0) + 1
        oc[s['original_v2c_class']] = oc.get(s['original_v2c_class'], 0) + 1
    by_genre = {}
    for r in rows:
        by_genre.setdefault(r['genre'], []).append(r['tier'])
    sf = (f"**PRELIMINARY audio ({env['soundfont']}).** Musyng Kite was not available where this package was built; "
          'render the same MIDI with it before freezing (`make_final_musyng.sh`).' if prelim else
          f"Rendered with the locked Musyng Kite file (sha256 {env['soundfont_sha256'][:16]}...).")

    # ---- intended danceability -------------------------------------------------------
    D = ['# Intended danceability: definition and evaluation', '', sf, '',
         '## Definition (proposed; adopt before enrolment)', '',
         '**Intended danceability = the condition\'s within-genre tier** (calm 1-2, lo-fi 1-3, Latin 1-3, R&B 1-4, '
         'pop / hip-hop / rock 1-5), analysed with genre in the model so that tiers are compared only within a '
         'genre. It is a parameter of the approved configuration, fixed before any data, not a score computed from '
         'the audio or from expected ratings. Per-excerpt values and reasons: `intended_danceability.csv`.', '',
         '## Why not the energy ladder rung', '',
         '- The rung orders the 27 cells by a composite **energy** score (loudness 0.40, drum onset rate 0.25, tempo '
         '0.20, centroid 0.10, flux 0.05) and by ear. In the 975-song corpus, Spotify danceability is associated with '
         'percussive share (+0.30), pulse (+0.28), bass share (+0.26) and tempo (+0.21), not with loudness (+0.05) or '
         'brightness (+0.02): half of the composite\'s weight is on features without that association.',
         '- Genre explains 61% of the rung\'s variance (calm only at rungs 0-1, rock 9-26): a rung effect could be a '
         'genre effect.', '',
         '## Is within-genre tier supported by the actual manipulations?', '',
         'Within genres, tier goes with (rank correlation over the 27 excerpts, genre removed):', '',
         '| Measure | r with tier |', '|---|---|']
    names = {'drum_notes_per_bar': 'drum notes per bar', 'notes_per_s': 'notes per second (all parts)',
             'parts': 'number of parts', 'bass_notes_per_bar': 'bass notes per bar', 'offbeat_index': 'off-beat index',
             'lufs_integrated': 'loudness (LUFS)', 'tempo_bpm': 'tempo (hip-hop and rock only)',
             'corpus_hpss_percussive_ratio': 'percussive share (approx.)', 'pulse_clarity': 'pulse clarity',
             'centroid_hz': 'spectral centroid', 'energy_u_delivered': 'composite energy u'}
    D += [f'| {names[k]} | {v:+.2f} |' for k, v in rr.items()]
    D += ['', f"Each tier step was classified from per-bar measures (a tempo change alone does not count as more "
          f"activity). v3 corpus: {v3c}. The original v2c conditions: {oc}.", '',
          '**Conclusion.** In the v3 corpus, every one of the 20 within-genre tier steps adds rhythmic activity or '
          'layers (more drum or bass notes per bar, an extra part, or busier accompaniment), so tier is a defensible '
          'operationalisation of *intended* danceability in the sense of the protocol ("configurations designed to '
          'produce higher levels of danceability"), with three qualifications:', '',
          '1. **Loudness rises with tier** in most genres (r = ' + f"{rr['lufs_integrated']:+.2f}" + '), because each '
          'excerpt keeps its original condition\'s loudness. Tier and loudness cannot be separated with these '
          'stimuli. Steps that are louder by 1 LU or more: ' +
          ', '.join(f"{s['genre']} {s['step']} ({s['v3_d_lufs_integrated']:+.1f} LU)" for s in steps
                    if s['v3_d_lufs_integrated'] >= 1.0) + '. Quieter: ' +
          (', '.join(f"{s['genre']} {s['step']} ({s['v3_d_lufs_integrated']:+.1f} LU)" for s in steps
                     if s['v3_d_lufs_integrated'] <= -1.0) or 'none') + '.',
          '2. **Tempo rises with tier in hip-hop and rock** (as in the approved configurations).',
          '3. **Pulse clarity does not rise with tier** (r = ' + f"{rr['pulse_clarity']:+.2f}" + '); the manipulation '
          'is density and layering, not a clearer beat. Two top steps add no drum notes: pop 4->5 re-patterns '
          'the drums to a four-on-the-floor kick with off-beat open hats (slightly fewer drum notes per bar), and '
          'hip-hop 4->5 adds a second instrument doubling the hook and a more active counter-line (its drum part '
          'gains a crash but has slightly fewer notes per bar).', '',
          'In the **original v2c** conditions, three steps showed little measurable change (pop 2->3, calm 1->2, R&B '
          '1->2) and the rock tiers kept the same drum part (their differences were tempo, loudness and guitar '
          'density): the v3 realisation makes the tier manipulation clearer than the original set did.', '',
          '## Genre-related confounds', '',
          f"- Unequal tier ranges: {', '.join(f'{g} {min(t)}-{max(t)}' for g, t in sorted(by_genre.items()))}. With "
          'genre in the model, the slope is estimated mainly from pop, hip-hop and rock (five tiers each).',
          '- Genre fixes tempo range (65-130 BPM), instruments, harmony style, drum style and loudness range '
          f"({min(r['lufs_integrated'] for r in rows):.1f} to {max(r['lufs_integrated'] for r in rows):.1f} LUFS); "
          'genre main effects absorb these, but genre-specific tier effects may differ (report within-genre slopes).',
          '- One composition per condition: within a genre, each tier is also a different composition (seeded per '
          'cell, as in the original set). Composition identity is not separable from tier; the sensitivity model '
          'with a stimulus random intercept treats compositions as a sample.', '',
          '## Smallest justified adjustment', '',
          'No change to the approved conditions or stimuli is needed. Before enrolment, document:', '',
          '1. The coding above as the intended-danceability predictor.',
          '2. The primary model: rating ~ tier + genre (fixed) + participant random intercept (the protocol\'s model '
          'with genre added).',
          '3. Sensitivity models: + stimulus random intercept; + loudness covariate; included responses only.',
          '4. That conclusions concern these configurations (density, layering, loudness and, in two genres, tempo '
          'together), not single features.', '',
          'Whether adding genre to the model needs an amendment or only documentation is an IRB / advisor decision.', '',
          '## Per condition', '',
          '| ID | Condition | Tier (coding) | Changes at this tier | Step from the tier below | LUFS | Drum notes/bar | '
          'Notes/s | Bass notes/bar | Off-beat | Centroid | Pulse | Energy u |',
          '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for c in sorted(coding, key=lambda c: (c['genre'], c['tier'])):
        D.append(f"| {c['stimulus_id']} | {c['condition_id']} | {c['tier']} | {c['musical_changes_at_this_tier']} | "
                 f"{c['step_from_lower_tier'] or '-'} | {c['lufs_integrated']:.1f} | {c['drum_notes_per_bar']:.1f} | "
                 f"{c['notes_per_s']:.2f} | {c['bass_notes_per_bar']:.1f} | {c['offbeat_index']:.2f} | "
                 f"{c['centroid_hz']:.0f} | {c['pulse_clarity']:.2f} | {c['energy_u_delivered']:.2f} |")
    (E / 'intended_danceability.md').write_text('\n'.join(D) + '\n')

    # ---- tier comparison ------------------------------------------------------------
    Tc = ['# Acoustic validation across tiers within each genre', '', sf, '',
          '| Genre | Tier | ID | Duration s | Tempo | LUFS | Peak dBFS | Drum onsets/s | Notes/s | Off-beat | '
          'Bass notes/bar | Centroid Hz | Flux | Pulse clarity | Energy u |', '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in sorted(rows, key=lambda r: (r['genre'], r['tier'])):
        Tc.append(f"| {r['genre']} | {r['tier']} | {r['stimulus_id']} | {r['duration_s']:.2f} | {r['tempo_bpm']:g} | "
                  f"{r['lufs_integrated']:.1f} | {r['peak_dbfs']:.1f} | {r['drum_onsets_per_s']:.2f} | "
                  f"{r['notes_per_s']:.2f} | {r['offbeat_index']:.2f} | {r['bass_notes_per_bar']:.1f} | "
                  f"{r['centroid_hz']:.0f} | {r['flux']:.2f} | {r['pulse_clarity']:.2f} | {r['energy_u_delivered']:.2f} |")
    lo = min(rows, key=lambda r: r['lufs_integrated'])
    hi = max(rows, key=lambda r: r['lufs_integrated'])
    Tc += ['', '## Findings', '',
           '- **Duplicates / near-identical conditions:** none (no identical MIDI; highest melodic-phrase overlap '
           '6%; see `similarity_pairs.csv`).',
           '- **Inconsistent tier relationships:** ' + '; '.join(
               f"{s['genre']} {s['step']}: " + ', '.join(x for x in (
                   f"quieter ({s['v3_d_lufs_integrated']:+.1f} LU)" if s['v3_d_lufs_integrated'] <= -0.2 else '',
                   'fewer drum notes per bar' if s['v3_d_drum_notes_per_bar'] < 0 else '',
                   'lower energy u' if s['v3_d_energy_u_delivered'] < 0 else '') if x)
               for s in steps if s['v3_d_lufs_integrated'] <= -0.2 or s['v3_d_drum_notes_per_bar'] < 0
               or s['v3_d_energy_u_delivered'] < 0) + '. Loudness follows the original conditions; these are not '
           'errors but are reported so the analysis does not assume every feature rises.',
           f"- **Large loudness differences:** {hi['lufs_integrated'] - lo['lufs_integrated']:.1f} LU between the "
           f"quietest ({lo['stimulus_id']} {lo['condition_id']}, {lo['lufs_integrated']:.1f}) and loudest "
           f"({hi['stimulus_id']} {hi['condition_id']}, {hi['lufs_integrated']:.1f}) excerpt; adjacent rock tiers "
           'differ by about 3 LU. Inherited from the original configurations.',
           '- **Missing rhythmic differentiation:** none in v3 (every step adds drum/bass/part density); in the '
           'original v2c set: pop 2->3, calm 1->2, R&B 1->2 and the rock drum part.',
           '- **Acoustic outliers:** calm excerpts (no real drum part) have the lowest flux and pulse clarity, as '
           'expected (`quality_control_report.md` section 7).',
           '- **Manipulation not clearly represented:** pulse clarity does not rise with tier; pop 4->5 and hip-hop '
           '4->5 change the drum pattern rather than its density.', '']
    (E / 'tier_comparison.md').write_text('\n'.join(Tc))

    # ---- analysis plan -----------------------------------------------------------
    P = ['# Analysis plan (draft for adoption before enrolment)', '',
         '## Data', '',
         '`import_v3_export.py` turns a Qualtrics CSV export into `ratings_long.csv`: one row per participant x '
         'experimental excerpt, with anonymous participant index (P001...), Qualtrics ResponseId, stimulus ID, '
         'presentation position, genre, tier, intended danceability (coding), the two ratings (0-100), page '
         'submit time, plays and full-play flags, the measured audio features. Practice trials are excluded by '
         'construction. `participants.csv`: quality flags (unfinished, attention slider < 90, straight-lining on '
         'both scales, mobile device, no headphones, volume changed a lot, incomplete plays) and '
         '`suggested_include` (complete, attention passed, not straight-lining). Flags are applied as written here, '
         'decided before data.', '',
         '## Primary (danceability)', '',
         '- Model: `danceability ~ intended_danceability + C(genre) + (1 | participant)`, REML (`analyze_v3.py`).',
         '- Report the tier slope (rating points per tier) with 95% CI; per-excerpt mean, median and SD; the '
         'within-genre slopes descriptively.',
         '- Sensitivity: stimulus random intercept (crossed with participant); + loudness (LUFS) covariate; '
         'suggested_include only. Report all, whatever their direction.',
         '- Interpretation: the slope describes these 27 configurations (density, layering, loudness and in two '
         'genres tempo change together, one composition per condition). No single-feature causal claims.', '',
         '## Secondary (calming, exploratory)', '',
         '- Per excerpt: mean, median, SD, 95% CI of calming; ranked list (which excerpts are most calming).',
         '- By genre and by genre x tier: means.',
         '- Association with danceability: within-participant Spearman (median, IQR, share positive) and across '
         'excerpt means. No direction assumed.',
         '- Excerpts rated high on both: rule fixed now: excerpt mean >= 60 on both scales; and in the top third of '
         'excerpt means on both.',
         '- Measured features (loudness, tempo, drum onset rate, notes per second, bass notes, off-beat index, '
         'centroid, flux, pulse clarity, energy u): Spearman with excerpt-mean calming, Holm-adjusted, '
         'descriptive; associations across 27 excerpts, not effects of features on relaxation.',
         '- Not inferred: that danceable music is less calming, that low-energy music is relaxing, or any link to '
         'physiological arousal (none is measured).', '',
         '## Pipeline test', '',
         'The import and analysis scripts were run on simulated exports (survey_validation_report.md and the '
         'tests). Simulated data test the code only; they say nothing about the study\'s results.', '']
    (E / 'analysis_plan.md').write_text('\n'.join(P))

    # ---- protocol differences, readiness ---------------------------------------------
    PD = ['# Differences from the submitted protocol (version 2026-10-27) and from the existing study build', '',
          '| Item | Protocol | Existing build (repository / existing survey) | This final candidate | Decision needed |',
          '|---|---|---|---|---|',
          '| Stimuli | 27 prerecorded excerpts from "a computer-based system" | locked v2c, 4-bar clips | GrooveGen v3 '
          '(v3.hiphop.0, v3.genres.1), 8-bar excerpts, same 27 conditions | IRB: replacing stimuli after '
          'representative examples were attached |',
          f"| Excerpt length | eight-bar phrases, about 15-30 s | 4 bars, 7.9-15.7 s | 8 bars, "
          f"{min(r['duration_s'] for r in rows):.1f}-{max(r['duration_s'] for r in rows):.1f} s | none (now matches) |",
          '| Intended danceability levels | documented per excerpt before enrolment | not documented; analysis used '
          'the energy rung | within-genre tier, proposed with justification | adopt before enrolment |',
          '| Primary analysis | repeated-measures regression, participant random intercept | Spearman with rung | '
          'same model + genre; sensitivity analyses | amendment or documentation (IRB / advisor) |',
          '| Calming | exploratory, no direction | analysis script expects calming to fall with rung | descriptive / '
          'exploratory only | none |',
          '| Age 18+ confirmation | on the first screen | missing | added (draft wording) | approve wording |',
          '| Consent text | approved remote consent | placeholder | placeholder (not provided) | insert approved text |',
          '| Instructions duration | 15-30 s | "8 to 16 seconds" | "15 to 30 seconds" | none |',
          '| Volume / practice | 1 + 2 | v2c 4-bar clips | existing clips kept (or v3 clips in the second draft) | choose |',
          '| Incomplete submissions | deleted | partial data kept 1 week | unchanged in file | set in Qualtrics |',
          '| Identifiers | none | "pid" field available | removed | none |',
          '| Extra survey items | not described | attention slider, 4 closing questions, break, laptop/desktop | '
          'unchanged | confirm they were in the submitted survey text |',
          f"| Soundfont | not specified | Musyng Kite | {env['soundfont']}{' (preliminary)' if prelim else ''} | "
          'render with Musyng Kite before freezing |' if prelim else
          f"| Soundfont | not specified | Musyng Kite | {env['soundfont']} | none |",
          '| Audio format / hosting | not specified | WAV on GitHub Pages | MP3 (WAV masters kept); new folder | '
          'upload and check links |', '']
    (E / 'protocol_differences.md').write_text('\n'.join(PD))

    R = ['# Readiness checklist', '',
         'Status: **final candidate, not frozen.** Do not use with participants until every item marked "you" is done.', '',
         '| # | Item | Status | Who |', '|---|---|---|---|',
         '| 1 | 27 excerpts, one per approved condition, metadata complete, files verified | done (27/27) | - |',
         f"| 2 | Render with Musyng Kite and re-verify | {'**open**: run `make_final_musyng.sh` on the Mac' if prelim else 'done'} | you (Mac) |",
         '| 3 | Final listening approval per excerpt (`final_review_sheet.csv`), incl. the six revised in v3.1 | **open** | you |',
         '| 4 | Adopt the intended-danceability coding and analysis plan before enrolment | **open** | you / advisor |',
         '| 5 | IRB: stimulus replacement (v2c -> v3) and analysis refinement | **open** | you / IRB |',
         '| 6 | Approved consent text in the survey; age-question wording | **open (blocker)** | you |',
         '| 7 | Practice / volume clips: existing or v3 | **open** | you |',
         '| 8 | Upload MP3s, `check-urls` passes | **open** | you |',
         '| 9 | Import the draft as a new Qualtrics project; options (anonymize, delete incomplete) | **open** | you |',
         '| 10 | Manual survey tests (`H_qualtrics_draft/survey_test_plan.md`), identity check 27/27 | **open** | you |',
         '| 11 | Freeze: archive the final package (hashes in the manifest), tag the commit | **open** | you |',
         '| 12 | Automated checks: survey structure, mapping round trip, audio files | done | - |', '']
    (E / 'readiness_checklist.md').write_text('\n'.join(R))
    _readme(out, src_manifest, survey, sf, prelim, label)


def _readme(out: Path, m: dict, survey: dict, sf: str, prelim: bool, label: str) -> None:
    env = m['environment']
    R = [f'# GrooveGen v3: final candidate stimuli and draft survey ({PACKAGE_VERSION}, {label})', '',
         '**Status: final candidate. Not frozen, not approved for participant use.** The original study\'s stimuli, '
         'the existing survey file and the live Qualtrics project are unchanged.', '', sf, '',
         '## Start here', '',
         '1. Listen: `listening/all_27_in_ID_order_3s_gaps.mp3` (or the playlist); the six excerpts revised in v3.1 '
         'have before / after files in `listening/changed_since_.../`. Record decisions in '
         '`E_analysis/final_review_sheet.csv`.',
         '2. Read `E_analysis/readiness_checklist.md`: everything still open, and who does it.',
         '3. Read `E_analysis/intended_danceability.md` (the predictor) and `E_analysis/analysis_plan.md`.',
         '4. Survey: `H_qualtrics_draft/` (two drafts, the audit, changes, validation report, test plan).', '',
         '## Folders', '', '| Folder | Contents |', '|---|---|',
         '| `A_qualtrics_mp3/` | exactly 27 participant files `S01.mp3`-`S27.mp3` (neutral names, no tags) |',
         '| `B_wav_masters/` | 16-bit 44.1 kHz WAV masters |', '| `C_midi_sources/` | the MIDI each excerpt was rendered from |',
         '| `D_internal_previews_10s/` | internal 10 s previews; **not** research stimuli |',
         '| `E_analysis/` | **researcher only**: manifest, stimulus key, coding, measurements, reports, plans, checklists |',
         '| `F_reference_original_v2c_8bar/` | the original conditions rendered the same way (reference) |',
         '| `G_candidate_practice_volume/` | v3 practice and volume candidates (the existing ones are not replaced) |',
         '| `H_qualtrics_draft/` | draft surveys and their documentation |',
         '| `listening/` | all 27 in one file, playlist, before / after, previews |', '',
         '## Render with Musyng Kite (Mac)', '',
         'From the repository root (branch `claude/dazzling-brown-qz2gtb`), with this package unzipped there:', '',
         '```bash', f'experiments/qualtrics_v3_candidate/make_final_musyng.sh {out.name} /path/to/GrooveGen_music_rating.qsf',
         '```', '',
         'It checks the soundfont\'s sha256, renders the same 27 MIDI files (stops if any differs), measures, '
         'verifies, rebuilds the survey drafts and writes the Musyng Kite final candidate package and its zip.', '',
         f"Audio and measurements built at commit {env.get('git_head', '')[:10]}"
         f"{' (uncommitted changes present)' if env.get('git_dirty') else ''}; package (coding, documents, survey "
         f"drafts) assembled at commit {assembly_commit()['git_head'][:10]}"
         f"{' (uncommitted changes present)' if assembly_commit()['git_dirty'] else ''}; survey drafts validated: " +
         ', '.join(f"{k}: {sum(c['passed'] for c in d['checks'])}/{len(d['checks'])}" for k, d in survey['drafts'].items()) + '.', '']
    (out / 'README.md').write_text('\n'.join(R))


# =============================================================================
# Build
# =============================================================================


def build(src: Path, original_qsf: Path, out: Path | None, base_url: str, make_zip: bool,
          before_after_from: Path | None = None) -> Path:
    m, problems = verify_source(src)
    if problems:
        raise SystemExit('source package does not match its manifest:\n  ' + '\n  '.join(problems))
    env = m['environment']
    prelim = not env.get('soundfont_is_locked_musyng')
    ver = m['corpus_version'].rsplit('-', 1)[1]                  # e.g. v3.1
    label = src.name.split(f'{ver}_', 1)[-1] if f'{ver}_' in src.name else Path(env['soundfont']).stem
    out = out or REPO / f'groovegen_qualtrics_27_final_candidate_{PACKAGE_VERSION}_{label}'
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for d in COPY_DIRS:
        if (src / d).exists():
            shutil.copytree(src / d, out / d)
    if before_after_from and not any((out / 'listening').glob('changed_since_*')):
        for d in (before_after_from / 'listening').glob('changed_since_*'):
            shutil.copytree(d, out / 'listening' / (d.name + '_FluidR3_preliminary'))
    shutil.copytree(src / 'E_analysis', out / 'E_analysis')
    audit = list(csv.DictReader((src / 'E_analysis' / 'condition_audit.csv').open()))
    coding, steps = dcode.write(out / 'E_analysis', m['stimuli'], audit)
    survey = write_survey_drafts(original_qsf, out, out / 'H_qualtrics_draft', base_url)
    write_docs(out, m, coding, steps, audit, survey, label, prelim)
    _, after = verify_source(out)
    if after:
        raise SystemExit('copied package does not match its manifest:\n  ' + '\n  '.join(after))
    failed = [c['check'] for d in survey['drafts'].values() for c in d['checks'] if not c['passed']
              and 'placeholder' not in c['check'] and 'NOT a placeholder' not in c['check']]
    print(f'wrote {out}; survey checks failing (besides the consent placeholder): {failed or "none"}')
    if make_zip:
        for name, keep in ((f'{out.name}.zip', None), (f'{out.name}_listening_and_survey.zip',
                                                       ('A_qualtrics_mp3', 'E_analysis', 'H_qualtrics_draft', 'listening'))):
            zp = out.parent / name
            with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
                for p in sorted(out.rglob('*')):
                    rel = p.relative_to(out)
                    if p.is_file() and (keep is None or len(rel.parts) == 1 or rel.parts[0] in keep):
                        z.write(p, Path(out.name) / rel)
            with zipfile.ZipFile(zp) as z:
                assert z.testzip() is None
            print('zip', zp, f'{zp.stat().st_size / 1e6:.1f} MB')
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    b = sub.add_parser('build')
    b.add_argument('--from', dest='src', required=True, type=Path)
    b.add_argument('--original-qsf', required=True, type=Path)
    b.add_argument('--out', type=Path, default=None)
    b.add_argument('--base-url', default=sv.DEFAULT_BASE_URL)
    b.add_argument('--before-after-from', type=Path, default=None)
    b.add_argument('--zip', action='store_true')
    c = sub.add_parser('check-urls')
    c.add_argument('--package', required=True, type=Path)
    a = ap.parse_args(argv)
    if a.cmd == 'build':
        build(a.src, a.original_qsf, a.out, a.base_url, a.zip, a.before_after_from)
        return 0
    return check_urls(a.package)


if __name__ == '__main__':
    raise SystemExit(main())
