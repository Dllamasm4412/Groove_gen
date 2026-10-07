"""
Experiment 1 participant app: a local, offline listening-and-rating page.

Python standard library only (http.server); binds 127.0.0.1. No PPG, HR,
haptics, controller or music generation: it plays the frozen WAVs listed in
stimuli/manifest.json and refuses to start unless every file matches its hash.

The browser never receives stimulus IDs, file names, cells, genres, tiers,
BPM or ladder positions: it asks for /clip?n=<trial number>, and the server
serves only the current trial's clip.

Usage (from the repository root; the researcher enters the participant code):
    .venv/bin/python experiments/music_rating/app.py --participant P001
    .venv/bin/python experiments/music_rating/app.py --participant P001 --resume
    .venv/bin/python experiments/music_rating/app.py --participant P001 --withdraw [--note TEXT]
then open http://127.0.0.1:8765/ in a browser and switch it to full screen.
Data: study_data/music_rating/<code>/ (gitignored). Ctrl+C stops the server;
the session can be resumed at the first unrated trial. --withdraw marks an
in-progress session withdrawn (status only; no data is deleted or changed).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import session_store as ss  # noqa: E402
import stimuli as st  # noqa: E402

DATA_ROOT = REPO / 'study_data' / 'music_rating'
INDEX_HTML = HERE / 'static' / 'index.html'
MAX_BODY = 16_384


class Handler(BaseHTTPRequestHandler):
    server_version = 'local'
    sys_version = ''

    def log_message(self, fmt, *args):      # keep the terminal quiet; events.jsonl is the log
        pass

    # ---- responses ----

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), 'application/json')

    def _state(self) -> None:
        self._json(200, self.server.session.public_state())

    def _guard(self, fn) -> None:
        try:
            with self.server.lock:
                fn()
        except ss.SessionError as exc:
            self._json(exc.status, {'error': str(exc)})
        except Exception:                    # researcher terminal only; the participant sees a generic message
            traceback.print_exc()
            self._json(500, {'error': 'internal error'})

    # ---- routes ----

    def do_GET(self):
        url = urlparse(self.path)
        if url.path in ('/', '/index.html'):
            return self._send(200, INDEX_HTML.read_bytes(), 'text/html; charset=utf-8')
        if url.path == '/api/state':
            return self._guard(self._state)
        if url.path == '/clip':
            which = parse_qs(url.query).get('n', [''])[0]

            def clip():
                self._send(200, self.server.session.clip_path(which).read_bytes(), 'audio/wav')
            return self._guard(clip)
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            return self._json(413, {'error': 'request too large'})
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {'error': 'bad JSON'})
        sess = self.server.session
        client = body.get('client') if isinstance(body.get('client'), dict) else None
        routes = {
            '/api/advance': lambda: sess.advance(body.get('from'), client),
            '/api/volume_play': lambda: sess.volume_played(client),
            '/api/play_start': lambda: sess.play_start(body.get('seq'), client),
            '/api/play_end': lambda: sess.play_end(body.get('seq'), client),
            '/api/response': lambda: sess.submit(body.get('seq'), body),
            '/api/client_event': lambda: sess.client_event(body.get('kind'), body.get('seq'), body.get('detail')),
        }
        action = routes.get(urlparse(self.path).path)
        if action is None:
            return self._json(404, {'error': 'not found'})

        def run():
            action()
            self._state()
        self._guard(run)


def make_server(session: ss.Session | None, port: int = 8765, host: str = '127.0.0.1') -> ThreadingHTTPServer:
    """Bind first (main() attaches the session only after the port is ours, so
    a busy port never creates or touches a session folder)."""
    if host not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('the participant app is localhost-only')
    server = ThreadingHTTPServer((host, port), Handler)
    server.session = session
    server.lock = threading.Lock()
    return server


def app_info() -> dict:
    def git(*a):
        r = subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    return {'experiment_version': ss.EXPERIMENT_VERSION, 'git_head': git('rev-parse', 'HEAD'),
            'git_branch': git('branch', '--show-current'),
            'experiment_code_uncommitted': bool(git('status', '--porcelain', '--', str(HERE))),
            'python': sys.version.split()[0]}


def open_session(args) -> ss.Session:
    manifest, sha = st.verify_stimuli(args.stim_dir)
    if args.resume:
        return ss.Session.resume(args.data_root, args.participant, manifest, sha, args.stim_dir)
    return ss.Session.create(args.data_root, args.participant, manifest, sha, args.stim_dir, app_info())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--participant', required=True, help='participant code, e.g. P001')
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--resume', action='store_true', help='continue an interrupted session')
    mode.add_argument('--withdraw', action='store_true',
                      help='mark an in-progress session withdrawn (no data deleted) and exit')
    ap.add_argument('--note', default='', help='with --withdraw: free-text note stored in session.json')
    ap.add_argument('--data-root', type=Path, default=DATA_ROOT)
    ap.add_argument('--stim-dir', type=Path, default=st.STIM_DIR)
    ap.add_argument('--port', type=int, default=8765)
    args = ap.parse_args(argv)
    try:
        if args.withdraw:
            meta = ss.Session.mark_withdrawn(args.data_root, args.participant, args.note)
            print(f"{args.participant}: marked withdrawn after {meta['next_seq']}/{len(meta['trials'])} "
                  f"trials; data left in {Path(args.data_root) / args.participant}")
            return 0
        server = make_server(None, args.port)
    except (st.StimulusError, ss.SessionError) as exc:
        print(f'music_rating: {exc}', file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'music_rating: port {args.port} is not available ({exc.strerror}); is another study server '
              f'still running? Stop it first. No session data was created.', file=sys.stderr)
        return 2
    try:
        sess = open_session(args)
    except (st.StimulusError, ss.SessionError) as exc:
        server.server_close()
        print(f'music_rating: {exc}', file=sys.stderr)
        return 2
    server.session = sess
    m = sess.meta
    print(f"participant {m['participant_code']}  session {m['session_id']}  stage {m['stage']}  "
          f"next trial {m['next_seq'] + 1}/{len(m['trials'])}")
    print(f'data: {sess.dir}')
    print(f'open http://127.0.0.1:{server.server_address[1]}/ in the browser (full screen); Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with server.lock:
            sess.stop()
        server.server_close()
    print(f"stopped: status {m['status']}, {m['next_seq']}/{len(m['trials'])} trials saved")
    return 0


if __name__ == '__main__':
    sys.exit(main())
