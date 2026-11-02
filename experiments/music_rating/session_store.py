"""
Experiment 1 session state, randomization and data files (no HTTP, no audio).

Files in <data_root>/<participant_code>/:
    session.json   metadata, trial plan and progress (atomic rewrite on every change)
    ratings.csv    one row per completed experimental trial (appended, fsynced)
    practice.csv   the practice trials, same columns (not analysis data)
    events.jsonl   every UI event with server time (append-only, fsynced)

The CSV rows are the source of truth for progress: on resume the next trial is
the first one without a row, so a crash between the CSV append and the
session.json rewrite neither loses nor duplicates a trial. A session folder
is never overwritten: create() refuses an existing participant code and
resume() refuses a completed session or a different stimulus manifest.

Rows hold opaque stimulus IDs only; join with the hidden stimulus manifest
(stimuli/manifest.json) for cell, genre, tier and BPM at analysis time.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import stimuli as st

EXPERIMENT_VERSION = 'music-rating-1.1'
SEED_SALT = 'groovegen-music-rating-v1'
CODE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_-]{0,31}$')
STAGES = ('welcome', 'instructions', 'volume', 'trials', 'done')
MAX_ABS_RANK_CORR = 0.5          # reject orders too close to ladder order (or its reverse)
MAX_SHUFFLES = 100_000
BREAK_AFTER_MAIN = 14            # optional rest screen after this many experimental trials (0 = none)

RATING_FIELDS = (
    'participant_code', 'session_id', 'trial_index', 'presentation_order', 'stimulus_id',
    'danceability', 'calming', 'response_latency_ms', 'response_latency_server_ms',
    'audio_start_utc', 'audio_end_utc', 'response_utc', 'audio_played_s', 'clip_duration_s',
    'n_plays', 'randomization_seed', 'app_version', 'manifest_sha256')


class SessionError(Exception):
    status = 400


class Conflict(SessionError):
    """Out-of-order, duplicate or premature request (HTTP 409)."""
    status = 409


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


# =============================================================================
# Randomization
# =============================================================================

def participant_seed(code: str) -> int:
    """Deterministic per-participant seed (recorded in session.json)."""
    return int(hashlib.sha256(f'{SEED_SALT}|{code}'.encode()).hexdigest()[:8], 16)


def rank_corr(order: list[str], ladder: list[str]) -> float:
    """Spearman correlation between presentation position and ladder rung."""
    n = len(order)
    pos = {sid: i for i, sid in enumerate(order)}
    d2 = sum((pos[sid] - r) ** 2 for r, sid in enumerate(ladder))
    return 1 - 6 * d2 / (n * (n * n - 1))


def randomize(main: list[dict], seed: int) -> tuple[list[str], int]:
    """(stimulus IDs in presentation order, shuffles tried). Every main stimulus
    exactly once; no two same-genre clips in a row; |rank correlation with the
    ladder| <= MAX_ABS_RANK_CORR. Same seed -> same order."""
    ladder = [s['stimulus_id'] for s in sorted(main, key=lambda s: s['rung'])]
    genre = {s['stimulus_id']: s['genre'] for s in main}
    rng = random.Random(seed)
    for attempt in range(1, MAX_SHUFFLES + 1):
        order = ladder[:]
        rng.shuffle(order)
        if any(genre[a] == genre[b] for a, b in zip(order, order[1:])):
            continue
        if abs(rank_corr(order, ladder)) > MAX_ABS_RANK_CORR:
            continue
        return order, attempt
    raise RuntimeError(f'no valid order after {MAX_SHUFFLES} shuffles (seed {seed})')


# =============================================================================
# File helpers
# =============================================================================

def _write_json_atomic(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, indent=1)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _append_line(path: Path, text: str) -> None:
    with path.open('a', encoding='utf-8', newline='') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())


def _csv_line(row: dict) -> str:
    import io
    buf = io.StringIO()
    csv.DictWriter(buf, fieldnames=RATING_FIELDS, lineterminator='\n').writerow(row)
    return buf.getvalue()


def _read_rows(path: Path) -> list[dict]:
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


# =============================================================================
# Session
# =============================================================================

def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Session:
    LOCK = 'server.lock'

    def __init__(self, folder: Path, meta: dict, manifest: dict, stim_dir: Path):
        self.dir = folder
        self.meta = meta
        self.stim = {s['stimulus_id']: s for s in manifest['stimuli']}
        self.stim_dir = Path(stim_dir)
        self._start_mono: Optional[float] = None
        self._end_mono: Optional[float] = None

    # ---- construction --------------------------------------------------------

    @staticmethod
    def check_code(code: str) -> str:
        if not CODE_RE.match(code or ''):
            raise SessionError(f'participant code {code!r}: use 1-32 letters, digits, - or _')
        return code

    @classmethod
    def create(cls, data_root: Path, code: str, manifest: dict, manifest_sha: str, stim_dir: Path,
               app_info: Optional[dict] = None) -> 'Session':
        cls.check_code(code)
        folder = Path(data_root) / code
        Path(data_root).mkdir(parents=True, exist_ok=True)
        try:
            folder.mkdir()
        except FileExistsError:
            raise SessionError(f'{folder} already exists; resume it with --resume or choose a new code') from None
        seed = participant_seed(code)
        order, attempts = randomize(st.by_kind(manifest, 'main'), seed)
        practice = [s['stimulus_id'] for s in st.by_kind(manifest, 'practice')]
        trials = [{'seq': i, 'kind': 'practice', 'presentation_order': i + 1, 'stimulus_id': sid}
                  for i, sid in enumerate(practice)]
        trials += [{'seq': len(practice) + i, 'kind': 'main', 'presentation_order': i + 1, 'stimulus_id': sid}
                   for i, sid in enumerate(order)]
        now = utc_now()
        meta = {
            'participant_code': code, 'session_id': f"{code}_{now[:19].replace('-', '').replace(':', '')}",
            'experiment_version': EXPERIMENT_VERSION, 'source_tag': manifest['source_tag'],
            'source_commit': manifest['provenance']['source_commit'], 'manifest_sha256': manifest_sha,
            'randomization_seed': seed, 'randomization_shuffles': attempts,
            'randomization_rules': {'no_adjacent_same_genre': True, 'max_abs_rank_corr': MAX_ABS_RANK_CORR},
            'session_start_utc': now, 'session_end_utc': None, 'status': 'in_progress',
            'stage': 'welcome', 'trials': trials, 'next_seq': 0, 'current': None,
            'volume_plays': 0, 'resumed_utc': [], 'app': app_info or {},
            'break_after_main': BREAK_AFTER_MAIN, 'break_done_utc': None,
        }
        for name in ('ratings.csv', 'practice.csv'):
            with (folder / name).open('x', encoding='utf-8', newline='') as f:
                csv.DictWriter(f, fieldnames=RATING_FIELDS, lineterminator='\n').writeheader()
        (folder / 'events.jsonl').open('x').close()
        sess = cls(folder, meta, manifest, stim_dir)
        sess._acquire()
        sess._save()
        sess._event('session_created', randomization_seed=seed)
        return sess

    @classmethod
    def resume(cls, data_root: Path, code: str, manifest: dict, manifest_sha: str, stim_dir: Path) -> 'Session':
        cls.check_code(code)
        folder = Path(data_root) / code
        if not (folder / 'session.json').exists():
            raise SessionError(f'no session to resume at {folder}')
        meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        if meta['status'] == 'completed':
            raise SessionError(f'{code} is already completed; nothing to resume (data left untouched)')
        if meta['status'] == 'withdrawn':
            raise SessionError(f'{code} was marked withdrawn; refusing to resume (data left untouched)')
        if meta['manifest_sha256'] != manifest_sha:
            raise SessionError(f'{code} was run with stimulus manifest {meta["manifest_sha256"][:12]}, '
                               f'current is {manifest_sha[:12]}; refusing to resume')
        order, _ = randomize(st.by_kind(manifest, 'main'), meta['randomization_seed'])
        if [t['stimulus_id'] for t in meta['trials'] if t['kind'] == 'main'] != order:
            raise SessionError(f'{code}: stored trial order does not match its seed; refusing to resume')
        sess = cls(folder, meta, manifest, stim_dir)
        sess._acquire()
        sess._reconcile()
        meta['resumed_utc'].append(utc_now())
        sess._save()
        sess._event('session_resumed', next_seq=meta['next_seq'], stage=meta['stage'])
        return sess

    @classmethod
    def mark_withdrawn(cls, data_root: Path, code: str, note: str = '') -> dict:
        """Record that the participant withdrew. Changes only status fields in
        session.json and appends an event; never deletes or edits ratings.
        What happens to the data afterwards follows the consent form."""
        cls.check_code(code)
        folder = Path(data_root) / code
        if not (folder / 'session.json').exists():
            raise SessionError(f'no session at {folder}')
        meta = json.loads((folder / 'session.json').read_text(encoding='utf-8'))
        if meta['status'] != 'in_progress':
            raise SessionError(f'{code} is {meta["status"]}; only an in-progress session can be marked withdrawn')
        lock = folder / cls.LOCK
        pid = int(lock.read_text().split()[0]) if lock.exists() else -1
        if pid > 0 and pid != os.getpid() and _pid_alive(pid):
            raise SessionError(f'{code} is open in a running server (pid {pid}); stop it first')
        now = utc_now()
        meta.update(status='withdrawn', withdrawn_utc=now, withdrawn_note=note, session_end_utc=now)
        _append_line(folder / 'events.jsonl', json.dumps({'server_utc': now, 'event': 'withdrawn', 'note': note,
                                                          'next_seq': meta['next_seq']}) + '\n')
        _write_json_atomic(folder / 'session.json', meta)
        return meta

    def _acquire(self) -> None:
        """One server per session folder: refuse while another live process
        holds server.lock; take over a stale lock (crashed server) and log it."""
        path = self.dir / self.LOCK
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                try:
                    pid = int(path.read_text().split()[0])
                except (OSError, ValueError, IndexError):
                    pid = -1
                if pid > 0 and pid != os.getpid() and _pid_alive(pid):
                    raise SessionError(f'{self.dir} is open in another running server (pid {pid}); stop it first')
                path.unlink(missing_ok=True)
                self._event('stale_lock_removed', pid=pid)
                continue
            with os.fdopen(fd, 'w') as f:
                f.write(f'{os.getpid()} {utc_now()}\n')
            return
        raise SessionError(f'could not lock {self.dir}')

    def _reconcile(self) -> None:
        """Progress from the CSV rows; refuse if they do not follow the plan."""
        trials = self.meta['trials']
        practice, main = _read_rows(self.dir / 'practice.csv'), _read_rows(self.dir / 'ratings.csv')
        if main and len(practice) < sum(t['kind'] == 'practice' for t in trials):
            raise SessionError(f'{self.dir}: experimental rows exist before practice finished')
        done = practice + main
        if len(done) > len(trials):
            raise SessionError(f'{self.dir}: more saved rows than trials; refusing to resume')
        for row, t in zip(done, trials):
            if row['stimulus_id'] != t['stimulus_id'] or int(row['trial_index']) != t['seq'] + 1:
                raise SessionError(f'{self.dir}: saved rows do not match the trial plan; refusing to resume')
        if len(done) != self.meta['next_seq']:
            self._event('progress_reconciled', from_seq=self.meta['next_seq'], to_seq=len(done))
            self.meta['next_seq'] = len(done)
            self.meta['current'] = None
        if done and self.meta['stage'] != 'trials':
            self.meta['stage'] = 'trials'
        if len(done) == len(trials):
            self._finish()

    # ---- persistence ---------------------------------------------------------

    def _save(self) -> None:
        _write_json_atomic(self.dir / 'session.json', self.meta)

    def _event(self, event: str, **fields: Any) -> None:
        rec = {'server_utc': utc_now(), 'event': event, **fields}
        _append_line(self.dir / 'events.jsonl', json.dumps(rec) + '\n')

    def _finish(self) -> None:
        self.meta.update(stage='done', status='completed', session_end_utc=utc_now(), current=None)

    # ---- participant-facing state (no stimulus metadata) ---------------------

    def public_state(self) -> dict:
        m = self.meta
        out: dict[str, Any] = {'stage': m['stage'], 'volume_played': m['volume_plays'] > 0}
        if m['stage'] == 'trials':
            t = m['trials'][m['next_seq']]
            same_kind = [x for x in m['trials'] if x['kind'] == t['kind']]
            cur = m['current'] or {}
            out['trial'] = {
                'seq': t['seq'], 'practice': t['kind'] == 'practice', 'number': t['presentation_order'],
                'total': len(same_kind), 'first_main': t['kind'] == 'main' and t['presentation_order'] == 1,
                'plays': cur.get('plays', 0), 'ended': bool(cur.get('ended')),
            }
            out['break'] = self._break_pending()
        return out

    def _break_pending(self) -> bool:
        """True on the trial after the break point until the participant continues
        (sessions created before the break existed have no break)."""
        m = self.meta
        n = m.get('break_after_main') or 0
        if not n or m.get('break_done_utc') or m['stage'] != 'trials':
            return False
        t = m['trials'][m['next_seq']]
        return t['kind'] == 'main' and t['presentation_order'] == n + 1

    def break_done(self, client: Optional[dict] = None) -> None:
        if not self._break_pending():
            raise Conflict('no break now')
        self.meta['break_done_utc'] = utc_now()
        self._event('break_end', next_seq=self.meta['next_seq'], client=client)
        self._save()

    # ---- stage flow ----------------------------------------------------------

    def advance(self, from_stage: str, client: Optional[dict] = None) -> None:
        stage = self.meta['stage']
        if from_stage != stage or stage not in ('welcome', 'instructions', 'volume'):
            raise Conflict(f'cannot leave stage {from_stage!r} (current {stage!r})')
        if stage == 'volume' and self.meta['volume_plays'] < 1:
            raise Conflict('play the volume sample first')
        self.meta['stage'] = STAGES[STAGES.index(stage) + 1]
        self._event('stage', stage=self.meta['stage'], client=client)
        self._save()

    def volume_played(self, client: Optional[dict] = None) -> None:
        if self.meta['stage'] != 'volume':
            raise Conflict('not in volume check')
        self.meta['volume_plays'] += 1
        self._event('volume_play', n=self.meta['volume_plays'], client=client)
        self._save()

    def clip_path(self, which: str) -> Path:
        """Only the clip of the current screen is served."""
        if which == 'volume':
            if self.meta['stage'] != 'volume':
                raise Conflict('no volume clip now')
            sid = next(s['stimulus_id'] for s in self.stim.values() if s['kind'] == 'volume')
        else:
            self._current_trial(which)
            sid = self.meta['trials'][self.meta['next_seq']]['stimulus_id']
        return self.stim_dir / self.stim[sid]['file']

    # ---- trials --------------------------------------------------------------

    def _current_trial(self, seq: Any) -> dict:
        if self.meta['stage'] != 'trials':
            raise Conflict('not in the trials stage')
        try:
            seq = int(seq)
        except (TypeError, ValueError):
            raise SessionError('bad trial number') from None
        if seq != self.meta['next_seq']:
            raise Conflict(f'trial {seq} is not the current trial')
        return self.meta['trials'][seq]

    def play_start(self, seq: Any, client: Optional[dict] = None) -> None:
        t = self._current_trial(seq)
        if self._break_pending():
            raise Conflict('continue from the break first')
        cur = self.meta['current'] or {'seq': t['seq'], 'plays': 0, 'ended': False}
        if cur['ended']:
            raise Conflict('this clip has already been played')
        cur['plays'] += 1
        cur['start_utc'] = utc_now()
        self.meta['current'] = cur
        self._start_mono, self._end_mono = time.monotonic(), None
        self._event('audio_start' if cur['plays'] == 1 else 'audio_restart', seq=t['seq'], plays=cur['plays'],
                    client=client)
        self._save()

    def play_end(self, seq: Any, client: Optional[dict] = None) -> None:
        t = self._current_trial(seq)
        cur = self.meta['current']
        if not cur or cur['plays'] < 1:
            raise Conflict('the clip has not started')
        if cur['ended']:
            raise Conflict('the clip has already ended')
        now = time.monotonic()
        elapsed = None if self._start_mono is None else round(now - self._start_mono, 3)
        played = (client or {}).get('played_s')
        cur.update(ended=True, end_utc=utc_now(), server_elapsed_s=elapsed,
                   played_s=played if isinstance(played, (int, float)) else None)
        self._end_mono = now
        dur = self.stim[t['stimulus_id']]['duration_s']
        early = elapsed is not None and elapsed < dur - 1.0
        self._event('audio_end', seq=t['seq'], server_elapsed_s=elapsed, early=early, client=client)
        self._save()

    def client_event(self, kind: str, seq: Any = None, detail: Any = None) -> None:
        if kind not in ('audio_paused', 'audio_resumed', 'audio_error', 'fullscreen', 'page_loaded'):
            raise SessionError(f'unknown client event {kind!r}')
        self._event(kind, seq=seq, detail=str(detail)[:500] if detail is not None else None)

    def submit(self, seq: Any, payload: dict) -> dict:
        """Validate and save one trial's ratings; returns the saved row."""
        t = self._current_trial(seq)
        cur = self.meta['current']
        if not cur or not cur.get('ended'):
            raise Conflict('ratings are only accepted after the whole clip has played')
        scores = {}
        for key in ('danceability', 'calming'):
            v = payload.get(key)
            if type(v) is not int or not 0 <= v <= 100:
                raise SessionError(f'{key} must be an integer 0-100')
            if payload.get(f'touched_{key}') is not True:
                raise SessionError(f'{key} slider was not moved')
            scores[key] = v
        lat = payload.get('latency_ms')
        lat_server = None if self._end_mono is None else round((time.monotonic() - self._end_mono) * 1e3)
        m = self.meta
        row = {
            'participant_code': m['participant_code'], 'session_id': m['session_id'],
            'trial_index': t['seq'] + 1, 'presentation_order': t['presentation_order'],
            'stimulus_id': t['stimulus_id'], **scores,
            'response_latency_ms': round(lat) if isinstance(lat, (int, float)) and lat >= 0 else '',
            'response_latency_server_ms': '' if lat_server is None else lat_server,
            'audio_start_utc': cur.get('start_utc'), 'audio_end_utc': cur.get('end_utc'), 'response_utc': utc_now(),
            'audio_played_s': '' if cur.get('played_s') is None else round(cur['played_s'], 3),
            'clip_duration_s': self.stim[t['stimulus_id']]['duration_s'], 'n_plays': cur['plays'],
            'randomization_seed': m['randomization_seed'], 'app_version': m['experiment_version'],
            'manifest_sha256': m['manifest_sha256'],
        }
        name = 'practice.csv' if t['kind'] == 'practice' else 'ratings.csv'
        _append_line(self.dir / name, _csv_line(row))          # 1. the row (source of truth)
        self._event('response', seq=t['seq'], kind=t['kind'], **scores)
        m['next_seq'] += 1                                      # 2. progress
        m['current'] = None
        self._start_mono = self._end_mono = None
        if m['next_seq'] == len(m['trials']):
            self._finish()
            self._event('session_completed')
        self._save()
        return row

    def stop(self, reason: str | None = None) -> None:
        self._event('server_stopped', reason=reason, stage=self.meta['stage'], next_seq=self.meta['next_seq'])
        (self.dir / self.LOCK).unlink(missing_ok=True)
