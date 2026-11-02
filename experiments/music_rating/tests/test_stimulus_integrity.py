"""Stimulus integrity: the manifest check catches missing, duplicate, altered,
stray or descriptive stimuli; the real frozen set (if built) is complete,
unclipped, carries the master headroom and comes from the locked tag."""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest
from conftest import LADDER, write_manifest

import stimuli as st


def problems(d: Path) -> list[str]:
    manifest, _ = st.load_manifest(d)
    return st.manifest_problems(manifest, d)


def edit(d: Path, fn) -> None:
    m, _ = st.load_manifest(d)
    fn(m)
    write_manifest(d, m)


def test_synthetic_set_is_intact(stim_dir):
    assert problems(stim_dir) == []


def test_missing_file(stim_dir):
    m, _ = st.load_manifest(stim_dir)
    (stim_dir / m['stimuli'][5]['file']).unlink()
    assert any('missing' in p for p in problems(stim_dir))
    with pytest.raises(st.StimulusError):
        st.verify_stimuli(stim_dir)


def test_altered_audio(stim_dir):
    m, _ = st.load_manifest(stim_dir)
    p = stim_dir / m['stimuli'][0]['file']
    b = bytearray(p.read_bytes())
    b[-1] ^= 1
    p.write_bytes(bytes(b))
    assert any('sha256 mismatch' in x for x in problems(stim_dir))


def test_missing_and_duplicate_cell(stim_dir):
    edit(stim_dir, lambda m: m['stimuli'][3].update(cell=m['stimuli'][4]['cell']))
    assert any('duplicate main cells' in p for p in problems(stim_dir))


def test_wrong_count(stim_dir):
    edit(stim_dir, lambda m: m['stimuli'].pop(0))
    out = problems(stim_dir)
    assert any('26 main stimuli' in p for p in out)
    assert any('unlisted WAV' in p for p in out)       # the dropped stimulus' file is now stray


def test_duplicate_id(stim_dir):
    edit(stim_dir, lambda m: m['stimuli'][1].update(stimulus_id=m['stimuli'][0]['stimulus_id']))
    assert any('duplicate stimulus_id' in p for p in problems(stim_dir))


def test_descriptive_file_name(stim_dir):
    def rename(m):
        s = m['stimuli'][0]
        (stim_dir / s['file']).rename(stim_dir / 'rock5.wav')
        s['stimulus_id'], s['file'] = 'rock5', 'rock5.wav'
    edit(stim_dir, rename)
    assert any('rock5' in p for p in problems(stim_dir))


def test_metadata_chunk_rejected(stim_dir):
    m, _ = st.load_manifest(stim_dir)
    s = m['stimuli'][0]
    p = stim_dir / s['file']
    data = p.read_bytes()
    info = b'LIST' + (12).to_bytes(4, 'little') + b'INFOINAM' + (0).to_bytes(4, 'little')
    new = data[:4] + (len(data) - 8 + len(info)).to_bytes(4, 'little') + data[8:] + info
    p.write_bytes(new)
    s['audio_sha256'] = st.file_sha256(p)
    write_manifest(stim_dir, m)
    assert any('metadata' in x for x in problems(stim_dir))


def test_finish_clip_matches_live_trim_and_fade():
    import build_stimuli as bs
    from crossfade import bar_duration_frames

    tempo = 118.0
    audio = np.ones((bar_duration_frames(tempo, 4, 44100) * 10, 2), dtype=np.float32)
    clip = bs.finish_clip(audio, tempo)
    bar = bar_duration_frames(tempo, 4, 44100)
    fade = round(bar * 0.25)
    n = bs.CLIP_BARS * bar
    assert bs.CLIP_BARS == 4 and clip.shape[0] == n + fade
    assert np.all(clip[:n] == 1.0)                       # the bars are untouched
    assert clip[n, 0] == pytest.approx(1.0) and abs(clip[-1, 0]) < 1e-6
    assert np.all(np.diff(clip[n:, 0]) <= 0)             # monotone fade-out


def test_first_bars_cuts_at_the_bar_line():
    import pretty_midi

    import build_stimuli as bs

    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)       # bar = 2 s
    pm.text_events.append(pretty_midi.Text('groovegen_render gain_db=+3.00', 0.0))
    inst = pretty_midi.Instrument(0)
    inst.notes = [pretty_midi.Note(90, 60, 0.0, 1.0), pretty_midi.Note(90, 62, 7.5, 9.0),   # held across bar 4
                  pretty_midi.Note(90, 64, 8.0, 8.5), pretty_midi.Note(90, 65, 12.0, 13.0)]  # bar 5 on: dropped
    inst.pitch_bends = [pretty_midi.PitchBend(100, 7.0), pretty_midi.PitchBend(0, 8.0)]
    pm.instruments.append(inst)
    cut = bs.first_bars(pm, 4, 120.0)
    assert [(n.pitch, n.start, n.end) for n in cut.instruments[0].notes] == [(60, 0.0, 1.0), (62, 7.5, 8.0)]
    assert [b.time for b in cut.instruments[0].pitch_bends] == [7.0]
    assert [e.text for e in cut.text_events] == ['groovegen_render gain_db=+3.00']   # Rock directive kept
    assert len(pm.instruments[0].notes) == 4                                        # original untouched
    with pytest.raises(ValueError):
        bs.first_bars(pm, 4, 100.0)


def test_stimulus_ids_depend_on_clip_length():
    import build_stimuli as bs

    assert bs.stimulus_id('main', 'pop:3', 1, 4) != bs.stimulus_id('main', 'pop:3', 1, 8)


def test_provenance_ignores_docs_only():
    import build_stimuli as bs

    changed = ['groovegen_pilot/V2_CONTEXT.md', 'CLAUDE.md', 'groovegen_pilot/composer/pop_cell.py',
               'experiments/music_rating/app.py']
    assert bs.locked_code_changes(changed) == ['groovegen_pilot/composer/pop_cell.py']


# ---- the real frozen set ---------------------------------------------------------

REAL = st.STIM_DIR
needs_real = pytest.mark.skipif(not (REAL / st.MANIFEST_NAME).exists(), reason='frozen stimuli not built')


@needs_real
def test_real_set_intact_and_complete():
    manifest, _ = st.verify_stimuli(REAL)
    main = sorted(st.by_kind(manifest, 'main'), key=lambda s: s['rung'])
    assert [s['cell'] for s in main] == LADDER            # all 27 live cells, exactly once, rung order
    assert manifest['ladder']['n_cells'] == 27
    for s in manifest['stimuli']:
        assert s['n_full_scale'] == 0
        assert s['peak_dbfs'] <= -1.0
        assert s['master_gain_db'] == -2.5
        assert abs(s['master_gain_db_measured'] + 2.5) <= 0.05
        assert s['stim_seed'] == (1 if s['kind'] == 'main' else 2)
        assert s['visit_idx'] == 0
        assert s['n_bars'] == 4 and s['segment_bars'] == 8 and s['prefix_identical_to_segment'] is True
        assert s['duration_s'] == pytest.approx(4.25 * 240 / s['bpm'], abs=0.01)   # 4 bars + quarter-bar tail


@needs_real
def test_real_set_provenance():
    import build_stimuli as bs

    manifest, _ = st.load_manifest(REAL)
    prov = manifest['provenance']
    tag = subprocess.run(['git', 'rev-parse', f'{st.SOURCE_TAG}^{{commit}}'], cwd=bs.REPO,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert prov['source_commit'] == tag
    assert prov['locked_code_unchanged'] is True
    assert prov['soundfont']['sha256'] == bs.LOCKED_SF2_SHA256
    gen = manifest['render']['generator']
    assert gen['generator'] == 'v2c' and gen['stim_seed'] == 1
    want = {'calm': 'v2c.calm.0', 'lofi': 'v2c.lofi.0', 'rnb': 'v2c.rnb.0', 'pop': 'v2c.pop.0',
            'latin': 'v2c.latin.1', 'hiphop': 'v2b.1', 'rock': None}
    for s in manifest['stimuli']:
        assert s['dev_version'] == want[s['genre']], s['cell']


@needs_real
def test_real_manifest_matches_ladder_and_energy_files():
    import build_stimuli as bs

    manifest, _ = st.load_manifest(REAL)
    cells, info = bs.live_cells()
    assert info == manifest['ladder']
    by_cell = {s['cell']: s for s in st.by_kind(manifest, 'main')}
    for c in cells:
        assert by_cell[f'{c.genre}:{c.tier}']['rung'] == c.rung


@needs_real
def test_practice_clips_are_not_study_material():
    manifest, _ = st.load_manifest(REAL)
    main = {s['midi_sha256'] for s in st.by_kind(manifest, 'main')}
    for s in st.by_kind(manifest, 'practice') + st.by_kind(manifest, 'volume'):
        assert s['midi_sha256'] not in main



def test_archive_is_complete_deterministic_and_checkable(stim_dir, tmp_path):
    import hashlib
    import tarfile

    import build_stimuli as bs

    for d in ('a', 'b'):
        assert bs.cmd_archive(stim_dir, tmp_path / d) == 0
    (ta,), (tb,) = (list((tmp_path / d).glob('*.tar')) for d in ('a', 'b'))
    assert ta.read_bytes() == tb.read_bytes()
    with pytest.raises(SystemExit, match='already exists'):
        bs.cmd_archive(stim_dir, tmp_path / 'a')
    _, sha = st.load_manifest(stim_dir)
    with tarfile.open(ta) as tf:
        files = {m.name.split('/', 1)[1]: tf.extractfile(m).read() for m in tf.getmembers()}
    assert sum(n.endswith('.wav') for n in files) == 30
    assert files['MANIFEST_SHA256'].decode().split()[0] == sha
    assert files['SOURCE_TAG'].decode().splitlines()[0] == st.SOURCE_TAG
    for line in files['SHA256SUMS'].decode().splitlines():
        h, n = line.split('  ')
        assert hashlib.sha256(files[n]).hexdigest() == h
