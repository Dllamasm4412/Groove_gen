"""The local HTTP app end to end, and metadata blinding: nothing the browser
receives names a genre, tier, BPM, rung, cell, stimulus ID or file."""

from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import app
import stimuli as st

FORBIDDEN_WORDS = [*st.GENRES, 'r&b', 'hip-hop', 'lo-fi', 'genre', 'tier', 'bpm', 'tempo', 'rung', 'ladder',
                   'cell', 'energy', 'arousal', 'stimulus', 'stimuli', 'manifest', 'seed', 'wav']


class Client:
    def __init__(self, port: int):
        self.base = f'http://127.0.0.1:{port}'
        self.seen: list[str] = []          # every text body the browser would receive

    def _do(self, req):
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def get(self, path):
        code, headers, body = self._do(urllib.request.Request(self.base + path))
        if not headers.get('Content-Type', '').startswith('audio/'):
            self.seen.append(body.decode())
        return code, headers, body

    def post(self, path, body=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body or {}).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
        code, _, raw = self._do(req)
        self.seen.append(raw.decode())
        return code, json.loads(raw)


@pytest.fixture
def served(new_session):
    sess = new_session()
    server = app.make_server(sess, port=0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield sess, Client(server.server_address[1])
    server.shutdown()
    server.server_close()


def rate(c: Client, seq: int):
    if json.loads(c.get('/api/state')[2]).get('break'):
        assert c.post('/api/play_start', {'seq': seq})[0] == 409           # no clip before the break ends
        assert c.post('/api/break_done')[0] == 200
    assert c.post('/api/play_start', {'seq': seq})[0] == 200
    assert c.post('/api/play_end', {'seq': seq, 'client': {'played_s': 0.05}})[0] == 200
    return c.post('/api/response', {'seq': seq, 'danceability': 55, 'calming': 45,
                                    'touched_danceability': True, 'touched_calming': True, 'latency_ms': 900})


def run_full(sess, c: Client) -> None:
    c.get('/')
    for stage in ('welcome', 'instructions'):
        assert c.post('/api/advance', {'from': stage})[0] == 200
    code, _, _ = c.get('/clip?n=volume')
    assert code == 200
    c.post('/api/volume_play')
    c.post('/api/advance', {'from': 'volume'})
    for seq in range(29):
        code, headers, body = c.get(f'/clip?n={seq}')
        assert code == 200 and headers['Content-Type'] == 'audio/wav'
        sid = sess.meta['trials'][seq]['stimulus_id']
        assert body == (sess.stim_dir / f'{sid}.wav').read_bytes()   # the planned hidden stimulus
        c.get('/api/state')
        code, state = rate(c, seq)
        assert code == 200
    assert state['stage'] == 'done'


def test_full_http_session(served):
    sess, c = served
    run_full(sess, c)
    assert sess.meta['status'] == 'completed'
    assert len((sess.dir / 'ratings.csv').read_text().splitlines()) == 28   # header + 27


def test_nothing_sent_to_the_browser_names_a_condition(served):
    sess, c = served
    run_full(sess, c)
    c.post('/api/play_start', {'seq': 99})                                   # error bodies count too
    c.get('/clip?n=volume')
    text = '\n'.join(c.seen).lower()
    for word in FORBIDDEN_WORDS:
        assert not re.search(rf'\b{re.escape(word)}\b', text), word
    for s in sess.stim.values():
        assert s['stimulus_id'].lower() not in text
        assert s['audio_sha256'] not in text


def test_page_is_offline_and_neutral():
    html = app.INDEX_HTML.read_text().lower()
    assert not re.search(r'https?://', html)                                 # no external resources
    visible = re.sub(r'<script.*?</script>|<style.*?</style>', '', html, flags=re.S)
    for word in FORBIDDEN_WORDS:
        assert not re.search(rf'\b{re.escape(word)}\b', visible), word


def test_page_ui_requirements():
    html = app.INDEX_HTML.read_text()
    for slider in ('danceability', 'calming'):
        tag = re.search(rf'<input[^>]*id="{slider}"[^>]*>', html, re.S).group(0)
        assert 'class="vas untouched"' in tag and 'min="0"' in tag and 'max="100"' in tag
    assert re.search(r'<button id="submit"[^>]*\bdisabled>', html)          # Continue starts disabled
    assert len(re.findall(r'<div class="ticks" aria-hidden="true">((?:<span></span>){6})</div>', html)) == 2
    assert 'id="break"' in html and 'id="break-next"' in html
    assert re.search(r'<div id="ratings" hidden>', html)                    # sliders hidden until the clip ends
    assert 'untouched::-webkit-slider-thumb { opacity: 0; }' in html        # no visible default answer
    assert 'controls' not in re.sub(r'<script.*?</script>', '', html, flags=re.S)  # no audio controls
    assert 'How much does this music make you want to move or dance?' in html
    assert 'How calming or relaxing does this music feel?' in html


def test_only_the_current_clip_is_served(served):
    sess, c = served
    assert c.get('/clip?n=0')[0] == 409                                      # not in trials yet
    for stage in ('welcome', 'instructions'):
        c.post('/api/advance', {'from': stage})
    c.post('/api/volume_play')
    c.post('/api/advance', {'from': 'volume'})
    assert c.get('/clip?n=volume')[0] == 409
    assert c.get('/clip?n=1')[0] == 409                                      # a future trial
    assert c.get('/clip?n=../manifest.json')[0] == 400
    for path in ('/manifest.json', '/stimuli/manifest.json', f'/{sess.meta["trials"][0]["stimulus_id"]}.wav',
                 '/static/index.html', '/session.json'):
        assert c.get(path)[0] == 404
    rate(c, 0)
    assert c.get('/clip?n=0')[0] == 409                                      # a finished trial


def test_http_rejects_premature_and_duplicate(served):
    sess, c = served
    for stage in ('welcome', 'instructions'):
        c.post('/api/advance', {'from': stage})
    c.post('/api/volume_play')
    c.post('/api/advance', {'from': 'volume'})
    code, _ = c.post('/api/response', {'seq': 0, 'danceability': 5, 'calming': 5,
                                       'touched_danceability': True, 'touched_calming': True})
    assert code == 409
    rate(c, 0)
    code, _ = c.post('/api/response', {'seq': 0, 'danceability': 5, 'calming': 5,
                                       'touched_danceability': True, 'touched_calming': True})
    assert code == 409
    assert len((sess.dir / 'practice.csv').read_text().splitlines()) == 2    # header + 1


def test_localhost_only(new_session):
    with pytest.raises(ValueError):
        app.make_server(new_session(), port=0, host='0.0.0.0')


def test_startup_refuses_altered_stimuli(tmp_path, stim_dir, capsys):
    m, _ = st.load_manifest(stim_dir)
    (stim_dir / m['stimuli'][0]['file']).write_bytes(b'RIFF')
    rc = app.main(['--participant', 'P001', '--data-root', str(tmp_path / 'd'), '--stim-dir', str(stim_dir),
                   '--port', '0'])
    assert rc == 2 and 'integrity' in capsys.readouterr().err
    assert not (tmp_path / 'd' / 'P001').exists()


def test_startup_refuses_overwrite(tmp_path, stim_dir, capsys, new_session):
    new_session('P001')
    rc = app.main(['--participant', 'P001', '--data-root', str(new_session.root), '--stim-dir', str(stim_dir),
                   '--port', '0'])
    assert rc == 2 and 'already exists' in capsys.readouterr().err


def test_real_wavs_have_no_metadata():
    if not (st.STIM_DIR / st.MANIFEST_NAME).exists():
        pytest.skip('frozen stimuli not built')
    for p in Path(st.STIM_DIR).glob('*.wav'):
        assert st.wav_chunk_ids(p) == [b'fmt ', b'data'], p.name


def test_busy_port_creates_no_session(tmp_path, stim_dir, capsys):
    import socket

    with socket.socket() as busy:
        busy.bind(('127.0.0.1', 0))
        busy.listen()
        port = busy.getsockname()[1]
        rc = app.main(['--participant', 'P001', '--data-root', str(tmp_path / 'd'), '--stim-dir', str(stim_dir),
                       '--port', str(port)])
    assert rc == 2 and 'not available' in capsys.readouterr().err
    assert not (tmp_path / 'd' / 'P001').exists()
