"""Response requirements, incremental logging and crash/recovery (Session API)."""

from __future__ import annotations

import csv
import json

import pytest
from conftest import do_trial, run_to_trials

import session_store as ss


def rows(path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


GOOD = {'danceability': 10, 'calming': 90, 'touched_danceability': True, 'touched_calming': True}


# ---- response requirements ---------------------------------------------------------

def test_stage_order_enforced(new_session):
    sess = new_session()
    with pytest.raises(ss.Conflict):
        sess.advance('instructions')
    with pytest.raises(ss.Conflict):
        sess.play_start(0)
    sess.advance('welcome')
    sess.advance('instructions')
    with pytest.raises(ss.Conflict):
        sess.advance('volume')                     # volume sample not played yet
    sess.volume_played()
    sess.advance('volume')
    assert sess.meta['stage'] == 'trials'


def test_no_rating_before_clip_ends(new_session):
    sess = new_session()
    run_to_trials(sess)
    with pytest.raises(ss.Conflict):
        sess.submit(0, GOOD)                       # not played
    sess.play_start(0)
    with pytest.raises(ss.Conflict):
        sess.submit(0, GOOD)                       # still playing
    sess.play_end(0)
    sess.submit(0, GOOD)


@pytest.mark.parametrize('bad', [
    {'danceability': None}, {'danceability': 101}, {'danceability': -1}, {'danceability': 50.5},
    {'danceability': '50'}, {'danceability': True}, {'touched_danceability': False},
    {'touched_calming': None}, {'calming': None},
])
def test_both_ratings_required_and_valid(new_session, bad):
    sess = new_session()
    run_to_trials(sess)
    sess.play_start(0)
    sess.play_end(0)
    with pytest.raises(ss.SessionError):
        sess.submit(0, {**GOOD, **bad})
    assert rows(sess.dir / 'practice.csv') == []
    assert sess.meta['next_seq'] == 0


def test_no_replay_after_end_and_restart_logged(new_session):
    sess = new_session()
    run_to_trials(sess)
    sess.play_start(0)
    sess.play_start(0)                             # e.g. page reloaded mid-clip
    sess.play_end(0)
    with pytest.raises(ss.Conflict):
        sess.play_start(0)
    row = sess.submit(0, GOOD)
    assert row['n_plays'] == 2
    events = [json.loads(x)['event'] for x in (sess.dir / 'events.jsonl').read_text().splitlines()]
    assert events.count('audio_start') == 1 and events.count('audio_restart') == 1


def test_duplicate_and_out_of_order_rejected(new_session):
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    with pytest.raises(ss.Conflict):
        sess.submit(0, GOOD)                       # same trial again
    with pytest.raises(ss.Conflict):
        sess.play_start(5)                         # a future trial
    assert len(rows(sess.dir / 'practice.csv')) == 1


# ---- logging -------------------------------------------------------------------------

def test_full_session_rows_map_to_plan(new_session):
    sess = new_session()
    run_to_trials(sess)
    for i in range(29):
        do_trial(sess, d=i, c=100 - i)
    main = rows(sess.dir / 'ratings.csv')
    practice = rows(sess.dir / 'practice.csv')
    plan = sess.meta['trials']
    assert len(practice) == 2 and len(main) == 27
    assert [r['stimulus_id'] for r in practice] == [t['stimulus_id'] for t in plan[:2]]
    assert [r['stimulus_id'] for r in main] == [t['stimulus_id'] for t in plan[2:]]
    assert not {r['stimulus_id'] for r in practice} & {r['stimulus_id'] for r in main}
    assert [int(r['presentation_order']) for r in main] == list(range(1, 28))
    assert [int(r['danceability']) for r in main] == list(range(2, 29))
    assert [int(r['calming']) for r in main] == [100 - i for i in range(2, 29)]
    r = main[0]
    assert r['participant_code'] == 'P001' and r['session_id'] == sess.meta['session_id']
    assert int(r['randomization_seed']) == ss.participant_seed('P001')
    assert r['app_version'] == ss.EXPERIMENT_VERSION and r['manifest_sha256'] == sess.meta['manifest_sha256']
    for k in ('audio_start_utc', 'audio_end_utc', 'response_utc', 'response_latency_ms'):
        assert r[k]
    assert r['audio_start_utc'] <= r['audio_end_utc'] <= r['response_utc']
    meta = json.loads((sess.dir / 'session.json').read_text())
    assert meta['status'] == 'completed' and meta['session_end_utc'] and meta['stage'] == 'done'


def test_rows_hold_no_condition_metadata(new_session):
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    header = (sess.dir / 'practice.csv').read_text().splitlines()[0].split(',')
    assert not {'cell', 'genre', 'tier', 'bpm', 'rung'} & set(header)


def test_each_trial_saved_immediately(new_session):
    sess = new_session()
    run_to_trials(sess)
    for i in range(3):
        do_trial(sess)
        on_disk = len(rows(sess.dir / 'practice.csv')) + len(rows(sess.dir / 'ratings.csv'))
        assert on_disk == i + 1
        assert json.loads((sess.dir / 'session.json').read_text())['next_seq'] == i + 1


# ---- overwrite protection and recovery -------------------------------------------------

def test_existing_session_never_overwritten(new_session):
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    before = {p.name: p.read_bytes() for p in sess.dir.iterdir()}
    with pytest.raises(ss.SessionError, match='already exists'):
        new_session()
    assert {p.name: p.read_bytes() for p in sess.dir.iterdir()} == before


@pytest.mark.parametrize('code', ['', '../x', 'a/b', 'P 1', '.hidden', 'x' * 33])
def test_bad_codes_rejected(new_session, code):
    with pytest.raises(ss.SessionError):
        new_session(code)


def test_resume_continues_at_next_trial(new_session, loaded):
    stim_dir, manifest, sha = loaded
    sess = new_session()
    run_to_trials(sess)
    for _ in range(5):
        do_trial(sess)
    sess.play_start(5)                             # interrupted mid-clip, then the server dies
    again = ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)
    assert again.meta['next_seq'] == 5
    assert again.public_state()['trial'] == {'seq': 5, 'practice': False, 'number': 4, 'total': 27,
                                             'first_main': False, 'plays': 1, 'ended': False}
    again.play_start(5)                            # replays the interrupted clip; logged as a restart
    again.play_end(5)
    row = again.submit(5, GOOD)
    assert row['n_plays'] == 2
    for _ in range(23):
        do_trial(again)
    assert again.meta['status'] == 'completed'
    assert len(rows(again.dir / 'ratings.csv')) == 27


def test_crash_between_row_and_session_json(new_session, loaded):
    stim_dir, manifest, sha = loaded
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    stale = (sess.dir / 'session.json').read_text()
    do_trial(sess)
    (sess.dir / 'session.json').write_text(stale)  # the row was written, session.json was not
    again = ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)
    assert again.meta['next_seq'] == 2
    do_trial(again)
    assert [r['trial_index'] for r in rows(again.dir / 'practice.csv')] == ['1', '2']
    assert [r['trial_index'] for r in rows(again.dir / 'ratings.csv')] == ['3']
    assert 'progress_reconciled' in (again.dir / 'events.jsonl').read_text()


def test_resume_refuses_completed_changed_or_corrupt(new_session, loaded):
    stim_dir, manifest, sha = loaded
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    with pytest.raises(ss.SessionError, match='manifest'):
        ss.Session.resume(new_session.root, 'P001', manifest, 'f' * 64, stim_dir)
    with pytest.raises(ss.SessionError, match='no session'):
        ss.Session.resume(new_session.root, 'P999', manifest, sha, stim_dir)
    p = sess.dir / 'practice.csv'
    p.write_text(p.read_text().replace(sess.meta['trials'][0]['stimulus_id'], 'sdeadbe'))
    with pytest.raises(ss.SessionError, match='do not match'):
        ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)

    done = new_session('P002')
    run_to_trials(done)
    for _ in range(29):
        do_trial(done)
    with pytest.raises(ss.SessionError, match='already completed'):
        ss.Session.resume(new_session.root, 'P002', manifest, sha, stim_dir)


def test_withdraw_marks_status_only(new_session, loaded):
    stim_dir, manifest, sha = loaded
    sess = new_session()
    run_to_trials(sess)
    do_trial(sess)
    data_before = {n: (sess.dir / n).read_bytes() for n in ('practice.csv', 'ratings.csv')}
    meta = ss.Session.mark_withdrawn(new_session.root, 'P001', 'stopped after practice 1')
    assert meta['status'] == 'withdrawn' and meta['withdrawn_utc']
    assert json.loads((sess.dir / 'session.json').read_text())['status'] == 'withdrawn'
    assert {n: (sess.dir / n).read_bytes() for n in data_before} == data_before
    assert '"withdrawn"' in (sess.dir / 'events.jsonl').read_text()
    with pytest.raises(ss.SessionError, match='withdrawn'):
        ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)
    with pytest.raises(ss.SessionError, match='only an in-progress'):
        ss.Session.mark_withdrawn(new_session.root, 'P001')


def test_one_server_per_session(new_session, loaded):
    import os
    import subprocess
    import sys

    stim_dir, manifest, sha = loaded
    sess = new_session()
    lock = sess.dir / ss.Session.LOCK
    assert lock.read_text().split()[0] == str(os.getpid())
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        lock.write_text(f'{other.pid} x\n')                  # another live server holds it
        with pytest.raises(ss.SessionError, match='another running server'):
            ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)
        with pytest.raises(ss.SessionError, match='running server'):
            ss.Session.mark_withdrawn(new_session.root, 'P001')
    finally:
        other.kill()
        other.wait()
    again = ss.Session.resume(new_session.root, 'P001', manifest, sha, stim_dir)   # stale lock: taken over
    assert lock.read_text().split()[0] == str(os.getpid())
    assert 'stale_lock_removed' in (sess.dir / 'events.jsonl').read_text()
    again.stop()
    assert not lock.exists()


def test_midpoint_break(new_session):
    sess = new_session()
    run_to_trials(sess)
    with pytest.raises(ss.Conflict):
        sess.break_done()                                    # not at the break yet
    for _ in range(2 + ss.BREAK_AFTER_MAIN):
        assert not sess.public_state()['break']
        do_trial(sess)
    assert sess.public_state()['break']
    assert sess.public_state()['trial']['number'] == ss.BREAK_AFTER_MAIN + 1
    seq = sess.meta['next_seq']
    with pytest.raises(ss.Conflict, match='break'):
        sess.play_start(seq)
    sess.break_done()
    assert not sess.public_state()['break'] and sess.meta['break_done_utc']
    with pytest.raises(ss.Conflict):
        sess.break_done()
    do_trial(sess)
    assert '"break_end"' in (sess.dir / 'events.jsonl').read_text()
