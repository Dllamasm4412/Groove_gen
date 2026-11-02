"""
Import a Qualtrics CSV export of the v3 draft survey into participant x stimulus
tables, joined with the candidate package's private manifest and the intended-
danceability coding.

Reuses the export parsing of experiments/music_rating/qualtrics/import_qualtrics.py
(read-only): loop columns "<k>_dance_1", "<k>_calming_1", "<k>_rt_Page Submit";
play records __js_t_<stimulus id> (stimulus ID, position shown, plays, full
play). In the draft, loop row k is stimulus S<k> (--loop-prefix row, the
Qualtrics default); confirm once with a test response (--verify, see
survey_test_plan.md).

Usage (repository root):
    python experiments/qualtrics_v3_candidate/import_v3_export.py EXPORT.csv --package <package dir> [--out DIR]
writes (default study_data/qualtrics_v3_candidate/<export name>/, gitignored):
    ratings_long.csv     one row per participant x experimental excerpt (practice excluded)
    participants.csv     one row per response, quality flags, suggested_include (flags only)
    import_summary.txt   counts and every data-integrity problem
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
QDIR = REPO / 'experiments' / 'music_rating' / 'qualtrics'
for p in (QDIR, QDIR.parent, HERE):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import import_qualtrics as iq  # noqa: E402  (read-only reuse of the export parser)

OUT_ROOT = REPO / 'study_data' / 'qualtrics_v3_candidate'
ATTN_MIN = iq.ATTN_MIN
STRAIGHTLINE_SD = iq.STRAIGHTLINE_SD
FULL_PLAY_TOLERANCE_S = iq.FULL_PLAY_TOLERANCE_S
STIM_FIELDS = ('condition_id', 'genre', 'tier', 'ladder_rung', 'tempo_bpm', 'lufs_integrated', 'drum_onsets_per_s',
               'notes_per_s', 'bass_notes_per_bar', 'offbeat_index', 'centroid_hz', 'flux', 'pulse_clarity',
               'energy_u_delivered', 'duration_s', 'generator_version')


def load_package(pkg: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    m = json.loads((pkg / 'E_analysis' / 'stimulus_manifest.json').read_text())
    stim = {r['stimulus_id']: r for r in m['stimuli']}
    coding = {}
    cpath = pkg / 'E_analysis' / 'intended_danceability.csv'
    if cpath.exists():
        with cpath.open(newline='') as f:
            coding = {r['stimulus_id']: r for r in csv.DictReader(f)}
    return stim, coding


def import_rows(rows: list[dict], header: list[str], stim: dict, coding: dict, prefix_mode: str = 'row'):
    table = sorted(stim)                                  # row k = k-th stimulus ID = S<k>
    cols = iq.loop_columns(header)
    long_rows, people, problems = [], [], []
    for n, r in enumerate(rows, 1):
        rid = r.get('ResponseId') or f'row{n}'
        records = {k[len(iq.RECORD):]: iq._json(v) for k, v in r.items() if k.startswith(iq.RECORD) and iq._json(v)}
        main_rec = {s: x for s, x in records.items() if s in stim}
        to_sid = iq.prefix_to_sid(prefix_mode, table, main_rec)
        mine = []
        for k, c in sorted(cols.items()):
            d, cal = iq._num(r.get(c.get('dance'))), iq._num(r.get(c.get('calming')))
            if d is None and cal is None:
                continue
            sid = to_sid.get(k)
            if sid is None:
                problems.append(f'{rid} loop {k}: ratings without a known stimulus; skipped')
                continue
            rec = main_rec.get(sid)
            if rec is None:
                problems.append(f'{rid} loop {k}: ratings for {sid} but no play record')
                rec = {}
            if rec.get('sid') not in (None, sid):
                problems.append(f'{rid} loop {k}: play record names {rec.get("sid")}, not {sid}')
            s = stim[sid]
            dur = rec.get('dur_s')
            full = bool(rec.get('complete')) and (rec.get('played_s') is None or dur is None or
                                                  rec['played_s'] >= dur - FULL_PLAY_TOLERANCE_S)
            row = {'response_id': rid, 'participant': f'P{n:03d}', 'stimulus_id': sid, 'loop_prefix': k,
                   'position': rec.get('pos'), 'danceability': d, 'calming': cal,
                   'rt_page_submit_s': iq._num(r.get(c.get('rt'))), 'plays': rec.get('plays'),
                   'prior_plays': rec.get('prior_plays'), 'full_play': full, 'play_errors': ';'.join(rec.get('errors') or []),
                   **{f: s.get(f) for f in STIM_FIELDS},
                   'intended_danceability': (coding.get(sid) or {}).get('intended_danceability_coding'),
                   'intended_danceability_status': (coding.get(sid) or {}).get('coding_status')}
            row['flag_replayed'] = (rec.get('plays') or 0) > 1 or (rec.get('prior_plays') or 0) > 0
            row['flag_not_full_play'] = not full
            long_rows.append(row)
            mine.append(row)
        sids = [x['stimulus_id'] for x in mine]
        if len(sids) != len(set(sids)):
            problems.append(f'{rid}: a stimulus rated more than once')
        if mine and len(mine) != len(stim):
            problems.append(f'{rid}: {len(mine)} of {len(stim)} excerpts rated')
        positions = [x['position'] for x in mine if isinstance(x['position'], int)]
        if positions and sorted(positions) != list(range(1, len(positions) + 1)):
            problems.append(f'{rid}: positions are not 1..{len(positions)}')
        attn = iq._num(iq._first(r, ['attn_1', 'attn']))
        dvals = [x['danceability'] for x in mine if x['danceability'] is not None]
        cvals = [x['calming'] for x in mine if x['calming'] is not None]
        sd_d = statistics.pstdev(dvals) if len(dvals) > 1 else None
        sd_c = statistics.pstdev(cvals) if len(cvals) > 1 else None
        device = iq._json(r.get('__js_device')) or {}
        flags = {
            'flag_unfinished': r.get('Finished') not in iq.FINISHED_YES,
            'flag_attention': attn is None or attn < ATTN_MIN,
            'flag_straightline': sd_d is not None and sd_c is not None and sd_d < STRAIGHTLINE_SD and sd_c < STRAIGHTLINE_SD,
            'flag_mobile': bool(iq.MOBILE.search(device.get('ua', ''))),
            'flag_no_headphones': r.get('post_headphones') not in iq.HEADPHONES_YES,
            'flag_volume_changed_a_lot': r.get('post_volume') in ('3', 'Yes, a lot'),
            'flag_incomplete_plays': any(x['flag_not_full_play'] for x in mine),
        }
        people.append({'response_id': rid, 'participant': f'P{n:03d}', 'n_rated': len(mine), 'attention': attn,
                       'sd_danceability': None if sd_d is None else round(sd_d, 2),
                       'sd_calming': None if sd_c is None else round(sd_c, 2),
                       'stim_set': r.get('stim_set'), 'survey_version': r.get('survey_version'),
                       'post_problems': r.get('post_problems', ''), **flags,
                       'suggested_include': len(mine) == len(stim) and not any(
                           flags[k] for k in ('flag_unfinished', 'flag_attention', 'flag_straightline'))})
    return long_rows, people, problems


def verify(rows, header, stim, response_id: str) -> str:
    """For a test response where every dance slider was set to the clip number
    shown on screen: which loop-column numbering makes dance == position?"""
    r = next(x for x in rows if x.get('ResponseId') == response_id)
    out = []
    for mode in ('row', 'position'):
        long_rows, _, _ = import_rows([r], header, stim, {}, mode)
        ok = sum(x['danceability'] == x['position'] for x in long_rows)
        out.append(f'--loop-prefix {mode}: {ok}/{len(long_rows)} ratings equal the clip number shown')
    return '\n'.join(out)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('export', type=Path)
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--out', type=Path, default=None)
    ap.add_argument('--loop-prefix', choices=('row', 'position'), default='row')
    ap.add_argument('--verify', default=None, help='ResponseId of a test response (dance slider = clip number shown)')
    a = ap.parse_args(argv)
    header, rows = iq.read_export(a.export)
    stim, coding = load_package(a.package)
    if a.verify:
        print(verify(rows, header, stim, a.verify))
        return 0
    long_rows, people, problems = import_rows(rows, header, stim, coding, a.loop_prefix)
    out = a.out or OUT_ROOT / a.export.stem
    write_csv(out / 'ratings_long.csv', long_rows)
    write_csv(out / 'participants.csv', people)
    (out / 'import_summary.txt').write_text('\n'.join([
        f'export: {a.export}', f'package: {a.package}', f'loop columns numbered by: {a.loop_prefix}',
        f'responses: {len(people)}; suggested_include: {sum(p["suggested_include"] for p in people)}',
        f'participant x excerpt rows: {len(long_rows)}', f'problems: {len(problems)}', *problems]) + '\n')
    print(f'wrote {out}: {len(long_rows)} ratings, {len(people)} responses, {len(problems)} problems')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
