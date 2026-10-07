# Experiment 1: music perception rating (operator notes)

Standalone listening-and-rating study built on the locked GrooveGen release
`pilot-zero-v2c-locked`. The app uses no PPG, HR, haptics or controller, and generates no
music during sessions. Participants rate 27 frozen clips (one per live ladder cell) on two
0-100 scales. Only the verbal end anchors are shown on screen.

The ratings describe each clip as the system plays it, loudness included. The clips keep the
locked system's levels and are not normalized. Do not report the ratings as measurements of
composition independent of loudness.

## Before a study day

```
.venv/bin/python3.12 experiments/music_rating/build_stimuli.py verify
.venv/bin/python3.12 -m pytest experiments/music_rating/tests -q
```

`verify` checks that the 30 WAVs match `stimuli/manifest.json`. It then re-renders every clip
from the locked code and requires byte-identical MIDI and audio (about 2 min). The app re-checks
the hashes every time it starts.

## Running a session

```
.venv/bin/python3.12 experiments/music_rating/app.py --participant P001
```

1. Open `http://127.0.0.1:8765/` and switch the browser to full screen.
2. Set the system output to the study headphones.
3. The participant sets the volume on the setup screen and is told not to change it afterwards.

Ctrl+C stops the server.

- **Interrupted session:** `--participant P001 --resume` continues at the first unrated trial.
  An interrupted clip replays from the start, and the restart is logged as `n_plays` = 2.
- **Withdrawal:** `--participant P001 --withdraw --note "..."` marks the session withdrawn. It
  deletes and changes no data. Whether the data are kept, excluded or deleted follows the final
  consent form; do that step by hand.
- **Overwrite protection:** an existing participant code is never overwritten. Use a new code,
  or use `--resume`.
- **One server per session:** a session folder holds `server.lock` while a server has it open.
  A second server, or `--withdraw`, on that folder is refused. A lock left by a crashed server is
  taken over and logged.
- **Busy port:** if the port is taken, for example by a server still running from an earlier
  session, the app exits before creating any session data. Stop the other server first.

Data are written to `study_data/music_rating/<code>/` (gitignored):

| File | Contents |
|---|---|
| `ratings.csv` | the 27 experimental trials |
| `practice.csv` | the 2 practice trials, not for analysis |
| `session.json` | metadata, randomization seed, trial plan and status |
| `events.jsonl` | every UI and server event, with timestamps |

Rows hold opaque `stimulus_id` values. Join them with `stimuli/manifest.json` at analysis time
to get cell, genre, tier and BPM.

## Archiving the frozen stimuli (outside Git)

The WAVs are gitignored (103 MB). `manifest.json` is committed and pins their sha256 hashes.

```
.venv/bin/python3.12 experiments/music_rating/build_stimuli.py archive --out /path/to/lab/storage
cd /path/to/lab/storage && shasum -a 256 -c music-rating-stimuli-*.tar.sha256
```

The archive is `music-rating-stimuli-<manifest sha12>.tar`. It contains:

- the 30 WAVs;
- `manifest.json`;
- `MANIFEST_SHA256`;
- `SOURCE_TAG` (the tag `pilot-zero-v2c-locked` and its commit);
- `SHA256SUMS`, checkable with `shasum -a 256 -c SHA256SUMS` after extraction.

The tar is deterministic: archiving the same set again gives the same bytes. Keep at least two
copies.

To restore, extract the tar and copy the WAVs into `stimuli/`. If the archive is lost, the
`build` command can regenerate the set from the locked tag: run it into an empty folder, then
run `verify`.
