"""
Prepare the Qualtrics build of Experiment 1 (remote). Researcher tool; the
music itself is the frozen 4-bar set in ../stimuli (unchanged).

Steps (from the repository root; see QUALTRICS_BUILD.md):
    1. .venv/bin/python experiments/music_rating/qualtrics/prepare_qualtrics.py files
       Checks the stimulus and headphone sets and copies all 36 sounds to
       qualtrics/deploy/upload/, named by their anonymous IDs.
    2. Put the sounds online and give their links, either
       - one public folder (e.g. GitHub Pages) serving deploy/upload/:
         ... prepare_qualtrics.py qsf --base-url https://HOST/PATH/
       - or any links pasted into deploy/audio_urls.csv (e.g. Qualtrics
         library links): ... prepare_qualtrics.py qsf
       `qsf` downloads every link and requires its sha256 to match the
       manifests (the host serves the frozen bytes and each ID points at the
       right file), then writes deploy/GrooveGen_music_rating.qsf: the whole
       survey, ready to import into Qualtrics.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
if str(EXP) not in sys.path:
    sys.path.insert(0, str(EXP))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import build_qsf as bq  # noqa: E402
import headphone_check as hc  # noqa: E402
import stimuli as st  # noqa: E402

BUILD_DIR = HERE / 'deploy'
URLS_CSV = 'audio_urls.csv'
REMOTE_VERSION = 'music-rating-remote-1.0'
URL_FIELDS = ('id', 'kind', 'file', 'url')
QSF_NAME = 'GrooveGen_music_rating.qsf'


def sounds(stim_dir: Path = st.STIM_DIR, hp_dir: Path = hc.OUT_DIR) -> list[dict]:
    """Every sound the survey plays: id, kind, source path, expected sha256."""
    manifest, _ = st.verify_stimuli(stim_dir)
    out = [{'id': s['stimulus_id'], 'kind': s['kind'], 'path': Path(stim_dir) / s['file'],
            'sha256': s['audio_sha256']} for s in manifest['stimuli']]
    hpm = hc.load_manifest(hp_dir)
    for t in hpm['trials']:
        p = Path(hp_dir) / t['file']
        if not p.exists() or hc.sha256(p) != t['audio_sha256']:
            raise SystemExit(f'headphone file {p} missing or altered; run headphone_check.py verify')
        out.append({'id': t['id'], 'kind': 'headphone', 'path': p, 'sha256': t['audio_sha256']})
    return out


def main_rows(manifest: dict) -> list[str]:
    """Loop & Merge rows for the main loop: stimulus IDs sorted by ID (unrelated to the ladder)."""
    return sorted(s['stimulus_id'] for s in st.by_kind(manifest, 'main'))


def practice_rows(manifest: dict) -> list[str]:
    return [s['stimulus_id'] for s in st.by_kind(manifest, 'practice')]


def build_id(manifest_sha: str, hp_manifest: dict) -> str:
    hp_sha = hashlib.sha256(json.dumps(hp_manifest, sort_keys=True).encode()).hexdigest()
    return f'{REMOTE_VERSION}+stim.{manifest_sha[:12]}+hp.{hp_sha[:8]}'




def cmd_files(out: Path, stim_dir: Path, hp_dir: Path) -> int:
    snd = sounds(stim_dir, hp_dir)
    manifest, _ = st.load_manifest(stim_dir)
    up = out / 'upload'
    up.mkdir(parents=True, exist_ok=True)
    for s in snd:
        shutil.copyfile(s['path'], up / f"{s['id']}.wav")
    urls = out / URLS_CSV
    if urls.exists() and any(r['url'] for r in read_urls(urls)):
        print(f'kept {urls} (already has URLs)')
    else:
        with urls.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=URL_FIELDS)
            w.writeheader()
            w.writerows({'id': s['id'], 'kind': s['kind'], 'file': f"{s['id']}.wav", 'url': ''} for s in snd)
    print(f'{len(snd)} sounds in {up}\nnext: put them online, then run: prepare_qualtrics.py qsf (see QUALTRICS_BUILD.md)')
    return 0


def read_urls(path: Path) -> list[dict]:
    with Path(path).open(newline='', encoding='utf-8') as f:
        return [{k: (v or '').strip() for k, v in r.items()} for r in csv.DictReader(f)]


def url_problems(rows: list[dict], snd: list[dict], fetch=None) -> list[str]:
    """Every problem with the URL sheet; with fetch, downloads and checks each file's sha256."""
    want = {s['id']: s['sha256'] for s in snd}
    got = {r['id']: r['url'] for r in rows}
    out = [f'{i}: missing from {URLS_CSV}' for i in want if i not in got]
    out += [f'{i}: not a survey sound' for i in got if i not in want]
    out += [f'{i}: no url' for i, u in got.items() if i in want and not u]
    out += [f'{i}: url must start with https://' for i, u in got.items() if u and not u.startswith('https://')]
    seen: dict[str, str] = {}
    for i, u in got.items():
        if u and u in seen:
            out.append(f'{i}: same url as {seen[u]}')
        seen.setdefault(u, i)
    if fetch is not None and not out:
        for i, u in got.items():
            try:
                h = hashlib.sha256(fetch(u)).hexdigest()
            except Exception as exc:  # noqa: BLE001 - report every failure
                out.append(f'{i}: download failed ({exc})')
                continue
            if h != want[i]:
                out.append(f'{i}: downloaded file differs from the frozen sound (wrong URL or re-encoded)')
    return out


def http_fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'groovegen-prepare/1'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def rows_from_base(snd: list[dict], base_url: str) -> list[dict]:
    """Links for a host that serves the upload folder as-is: base URL + '<id>.wav'."""
    base = base_url.strip()
    if not base.startswith('https://'):
        raise SystemExit('--base-url must start with https://')
    base = base if base.endswith('/') else base + '/'
    return [{'id': s['id'], 'kind': s['kind'], 'file': f"{s['id']}.wav", 'url': f"{base}{s['id']}.wav"}
            for s in snd]


def cmd_qsf(out: Path, stim_dir: Path, hp_dir: Path, download: bool, base_url: str | None = None,
            template: Path = bq.TEMPLATE, headphone_check: bool = False) -> int:
    snd = sounds(stim_dir, hp_dir)
    if base_url:
        rows = rows_from_base(snd, base_url)
        out.mkdir(parents=True, exist_ok=True)
        with (out / URLS_CSV).open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=URL_FIELDS)
            w.writeheader()
            w.writerows(rows)
    else:
        rows = read_urls(out / URLS_CSV)
    problems = url_problems(rows, snd, http_fetch if download else None)
    if problems:
        raise SystemExit('the sound links are not ready:\n  ' + '\n  '.join(problems))
    if not Path(template).exists():
        raise SystemExit(f'no Qualtrics template export at {template}')
    manifest, sha = st.load_manifest(stim_dir)
    hpm = hc.load_manifest(hp_dir)
    build = build_id(sha, hpm)
    survey = bq.build(
        json.loads(Path(template).read_text(encoding='utf-8')),
        urls={r['id']: r['url'] for r in rows}, main_ids=main_rows(manifest), practice_ids=practice_rows(manifest),
        volume_id=next(s['id'] for s in snd if s['kind'] == 'volume'),
        hp_ids=[t['id'] for t in hpm['trials']], hp_answers=[t['answer'] for t in hpm['trials']],
        hp_times=hpm['params']['interval_times_s'], build_id=build, headphone_check=headphone_check)
    qsf = out / QSF_NAME
    qsf.write_text(json.dumps(survey, indent=1) + '\n', encoding='utf-8')
    (out / 'build.json').write_text(json.dumps({
        'build': build, 'stimulus_manifest_sha256': sha, 'urls_checked_by_download': download,
        'n_sounds': len(snd), 'break_after_main': bq.BREAK_AFTER_MAIN, 'base_url': base_url,
        'template': str(Path(template).name), 'headphone_check': headphone_check, 'qsf_sha256': hashlib.sha256(qsf.read_bytes()).hexdigest()},
        indent=1) + '\n', encoding='utf-8')
    note = 'all 36 links downloaded and match the frozen files' if download else 'links NOT downloaded (--no-download)'
    print(f'{note}\nwrote {qsf} (build {build})\nnext: in Qualtrics, Create project > Survey > import this .qsf file')
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('command', choices=('files', 'qsf'))
    ap.add_argument('--out', type=Path, default=BUILD_DIR)
    ap.add_argument('--stim-dir', type=Path, default=st.STIM_DIR)
    ap.add_argument('--hp-dir', type=Path, default=hc.OUT_DIR)
    ap.add_argument('--template', type=Path, default=bq.TEMPLATE)
    ap.add_argument('--base-url', default=None,
                    help='qsf: public folder serving deploy/upload/ (links = base + <id>.wav)')
    ap.add_argument('--headphone-check', action='store_true',
                    help='qsf: include the Huggins-pitch headphone screen (off by default)')
    ap.add_argument('--no-download', action='store_true', help='qsf: skip the download check (testing only)')
    args = ap.parse_args(argv)
    if args.command == 'files':
        return cmd_files(args.out, args.stim_dir, args.hp_dir)
    return cmd_qsf(args.out, args.stim_dir, args.hp_dir, not args.no_download, args.base_url, args.template,
                   args.headphone_check)


if __name__ == '__main__':
    sys.exit(main())
