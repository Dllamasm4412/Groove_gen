"""
Intended-danceability coding for the candidate corpus: a documented, a-priori
coding of the 27 approved conditions, with the musical changes each tier makes
and what the produced audio actually shows.

The coding is the condition's WITHIN-GENRE TIER (a configuration parameter set
before any participant data). It is not computed from the produced audio, from
any danceability model or from expected ratings. Its status is "proposed": the
researcher adopts (or replaces) it before enrolment.
"""

from __future__ import annotations

import csv
from pathlib import Path

# Per-bar measures, so a tempo change alone does not count as more rhythmic activity (tempo is reported apart)
GROOVE_KEYS = ('drum_notes_per_bar', 'drum_onsets_per_bar', 'bass_notes_per_bar', 'parts', 'notes_per_bar')
STEP_MIN = {'drum_notes_per_bar': 1.0, 'drum_onsets_per_bar': 0.5, 'bass_notes_per_bar': 0.5, 'parts': 1,
            'notes_per_bar': 2.0}
LOUD_STEP = 1.0          # LU: smaller loudness differences are treated as about equal

# What each tier adds, per genre (from the generator's realisation code; v3.genres.1 / v3.hiphop.0)
TIER_CHANGES = {
    'calm': {1: 'piano: rolled chords on beats 1 and 3, left-hand root; melody held notes; light pulse '
                '(kick on 1, rim on 3, quarter-note hats, mixed far under the piano)',
             2: 'flowing 8th-note broken chords, left-hand root and fifth; full melody; pulse gains a second kick '
                'and 8th-note hats'},
    'lofi': {1: 'soft swung boom-bap (kick, side-stick backbeat, 8th hats); held rootless Rhodes chords; upright '
                'bass on 1 and the "and" of 3; melody held notes',
             2: 'snare backbeat, kick variant, ghost note; Rhodes hits on 1 and the "and" of 3; bass adds the fifth; '
                'full melody',
             3: 'shaker 16ths and open hats; broken-chord arpeggio layer; walking bass with approach notes'},
    'rnb': {1: 'half-time beat: kick, side-stick on 3, 8th hats; held rootless chords; sub-bass on kick hits; '
               'melody held notes',
            2: 'snare on 3, syncopated kick variant; chord hits on 1 and the "and" of 3; bass locked to the kick; '
               'full melody',
            3: '16th hats with accents, clap layer, ghost snares; syncopated chord stabs; bass approach notes; '
               'melodic grace notes',
            4: 'shaker, open hats, triplet hat rolls; extra kick pickups; pad'},
    'pop': {1: 'kick on 1 and 3, soft snare on 2 and 4, quarter-note hats; half-note strums; bass on 1 and 3; '
               'full melody',
            2: 'kick variant every other bar, 8th hats; bass on every beat',
            3: 'full kick variant, clap layered on the snare, open hats at phrase ends, snare fill; syncopated '
               'comping; bass locked to the kick with octave pickups',
            4: '16th hats, tambourine, crash, tom fill; 8th-note comping pulse; bass 8ths with octave pops and '
               'approach notes; pad',
            5: 'four-on-the-floor kick, open hats on the off-beats, 16th tambourine, crashes; octave-pumping bass'},
    'latin': {1: 'maracas 8ths and soft son clave; block chords on the clave; bass root plus anticipation; melody '
                 'held notes',
              2: 'conga tumbao and guiro; piano montuno; tumbao bass (fifth on the "and" of 2, next root on 4); '
                 'full melody',
              3: 'bongo martillo and soft bombo kick; montuno in octaves; bass adds a passing root; melodic grace notes'},
    'hiphop': {1: 'kick and snare skeleton, quarter-note hats; bass on chord changes; held chords; hook main notes '
                  'only (level 1)',
               2: 'composition kick pattern, 8th hats; full bass figure; comping pattern; full hook',
               3: '16th hats with accents, open hats, ghost snares, fills; bass pickups',
               4: 'clap, percussion layer, counter-line',
               5: 'active counter-line, hook doubled on a second instrument, crash'},
    'rock': {1: 'driven-guitar riff in its intro form over a plain backbeat (kick 1 and 3, snare 2 and 4, quarter '
                'hats); bass on the riff\'s chord hits',
             2: 'full riff, 8th hats, crash at the top',
             3: 'second guitar under the riff, kick variant, open hats, crashes on bars 1 and 5, snare fill; '
                'driving bass 8ths',
             4: 'ride cymbal 8ths, kick pickups, ghost snare, tom fills; lead guitar answering the riff in bars 3-4 '
                'and 7-8; bass octave pops',
             5: 'ride and bell, kick 8th pushes, crashes every other bar, full tom fill; open power chords on the '
                'second guitar; melodic lead hook throughout'},
}
TEMPO_NOTE = {'hiphop': 'tempo rises with tier (85-96 BPM)', 'rock': 'tempo rises with tier (110-130 BPM)'}

REASON = ('Within-genre tier is the configuration parameter that sets the arrangement\'s rhythmic activity and '
          'layering (drum and percussion density, bass activity, accompaniment rhythm, extra layers) while genre, '
          'instruments and harmony style stay; in the corpus analysis, percussive share, pulse, bass share and '
          'onset density were the features associated with Spotify danceability. Coded before any participant '
          'data; not computed from the produced audio.')


def _per_bar(r: dict) -> dict:
    bar_s = 240.0 / float(r['tempo_bpm'])
    return {**r, 'drum_onsets_per_bar': float(r['drum_onsets_per_s']) * bar_s,
            'notes_per_bar': float(r['notes_per_s']) * bar_s}


def step_class(prev: dict, cur: dict) -> tuple[str, dict]:
    prev, cur = _per_bar(prev), _per_bar(cur)
    d = {k: round(cur[k] - prev[k], 3) for k in GROOVE_KEYS + ('lufs_integrated', 'offbeat_index', 'tempo_bpm',
                                                                 'energy_u_delivered')}
    groove = [k for k in GROOVE_KEYS if d[k] >= STEP_MIN[k]]
    loud = d['lufs_integrated']
    if not groove and d['tempo_bpm'] > 0:
        cls = 'tempo and loudness mainly' if loud >= LOUD_STEP else 'tempo mainly'
    elif groove:
        cls = ('groove-related change and louder' if loud >= LOUD_STEP else
               'groove-related change, quieter' if loud <= -LOUD_STEP else 'groove-related change, loudness about equal')
    else:
        cls = 'mainly loudness' if loud >= LOUD_STEP else 'little measurable change'
    notes = []
    if groove and d['drum_notes_per_bar'] < 0:
        notes.append('drum part re-patterned rather than denser')
    if d['tempo_bpm'] > 0:
        notes.append(f"tempo +{d['tempo_bpm']:g} BPM")
    return cls, {**d, 'groove_measures_up': ','.join(groove), 'notes': '; '.join(notes)}


def build_coding(rows: list[dict], audit: list[dict]) -> tuple[list[dict], list[dict]]:
    """(per-stimulus coding table, per-step table incl. the original v2c segments)."""
    by_genre: dict[str, list] = {}
    for r in rows:
        by_genre.setdefault(r['genre'], []).append(r)
    orig = {a['condition_id']: a for a in audit}
    table, steps = [], []
    for g, rs in by_genre.items():
        rs = sorted(rs, key=lambda r: r['tier'])
        for i, r in enumerate(rs):
            row = {'stimulus_id': r['stimulus_id'], 'condition_id': r['condition_id'], 'genre': g, 'tier': r['tier'],
                   'tiers_in_genre': len(rs), 'intended_danceability_coding': r['tier'],
                   'coding_rule': 'within-genre tier of the approved configuration (analysed with genre in the model)',
                   'coding_status': 'proposed - researcher to adopt before enrolment',
                   'reason': REASON, 'musical_changes_at_this_tier': TIER_CHANGES[g][r['tier']] + (
                       f"; {TEMPO_NOTE[g]}" if g in TEMPO_NOTE else ''),
                   **{k: r[k] for k in ('tempo_bpm', 'duration_s', 'lufs_integrated', 'peak_dbfs', 'drum_onsets_per_s',
                                        'drum_notes_per_bar', 'notes_per_s', 'offbeat_index', 'bass_notes_per_bar',
                                        'centroid_hz', 'flux', 'pulse_clarity', 'energy_u_delivered')},
                   'step_from_lower_tier': '', 'ladder_rung_energy_order': r['ladder_rung']}
            if i:
                cls, d = step_class(rs[i - 1], r)
                row['step_from_lower_tier'] = cls + (f" ({d['notes']})" if d['notes'] else '')
                ocls, od = step_class({**orig[rs[i - 1]['condition_id']], **_o(orig[rs[i - 1]['condition_id']])},
                                      {**orig[r['condition_id']], **_o(orig[r['condition_id']])})
                steps.append({'genre': g, 'step': f"{rs[i - 1]['tier']}->{r['tier']}",
                              'v3_class': cls, **{f'v3_d_{k}': v for k, v in d.items()},
                              'original_v2c_class': ocls, **{f'orig_d_{k}': v for k, v in od.items()}})
            table.append(row)
    table.sort(key=lambda r: r['stimulus_id'])
    return table, steps


def _o(a: dict) -> dict:
    """Original-segment measures under the corpus names (condition_audit.csv columns)."""
    f = lambda k: float(a[k]) if a.get(k) not in (None, '') else 0.0  # noqa: E731
    return {'drum_notes_per_bar': f('orig8_drum_notes_per_bar'), 'drum_onsets_per_s': f('orig8_drum_onsets_per_s'),
            'bass_notes_per_bar': f('orig8_bass_notes_per_bar'), 'parts': f('orig8_parts'),
            'notes_per_s': f('orig8_notes_per_s'), 'lufs_integrated': f('orig8_lufs_target'),
            'offbeat_index': f('orig8_offbeat_index'), 'tempo_bpm': f('tempo_bpm'),
            'energy_u_delivered': f('orig8_energy_u_delivered')}


def write(E: Path, rows: list[dict], audit: list[dict]) -> tuple[list[dict], list[dict]]:
    table, steps = build_coding(rows, audit)
    for path, data in ((E / 'intended_danceability.csv', table), (E / 'tier_steps_v3_vs_original.csv', steps)):
        with path.open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in data for k in r)))
            w.writeheader()
            w.writerows(data)
    return table, steps
