# Experiment 1 on Qualtrics (remote): build and launch

The whole survey is generated as one `.qsf` file and imported into Qualtrics; nothing is built by
hand.

| Source | What it holds |
|---|---|
| `../stimuli/` | The frozen 4-bar clips: 27 study, 2 practice, 1 volume sample |
| `headphone/` | 6 Huggins-pitch trials for an optional headphone check (`qsf --headphone-check`; off by default) |
| `build_qsf.py` | All blocks, questions, participant wording, loops and flow |
| `gg_qualtrics.js` | The player, copied into each question's JavaScript |
| `template/GG_template.qsf` | An export from the researcher's own account, so the file matches its format and branding |

The account uses the Qualtrics **Simple** layout. The player is written for it.

## 1. Collect the sound files

```
.venv/bin/python3.12 experiments/music_rating/qualtrics/prepare_qualtrics.py files
```

This copies the 36 sounds to `deploy/upload/`, named by their anonymous IDs. It also writes
`deploy/audio_urls.csv`, a list of the files with an empty `url` column.

## 2. Give the survey the links to the sounds

Choose one:

- **A. One public folder (no per-file work).** Publish `deploy/upload/` as one web folder, for
  example a public GitHub repository with Pages turned on. Then run:
  ```
  .venv/bin/python3.12 experiments/music_rating/qualtrics/prepare_qualtrics.py qsf --base-url https://<user>.github.io/<repo>/
  ```
- **B. The Qualtrics library.** For each file in the library, copy its link into the `url` column
  of `deploy/audio_urls.csv`, on the row with the same file name. Then run:
  ```
  .venv/bin/python3.12 experiments/music_rating/qualtrics/prepare_qualtrics.py qsf
  ```

Either way, the command downloads every link and requires each file to be byte-identical to the
frozen one. This catches a wrong link, a mix-up between files, or a host that alters files. It
then writes `deploy/GrooveGen_music_rating.qsf`.

## 3. Import

In Qualtrics, go to **Create project → Survey**, choose to import a **QSF file**, and pick
`deploy/GrooveGen_music_rating.qsf`.

## 4. Finish and check inside Qualtrics

1. **Consent:** replace the placeholder paragraph in the first block with the approved consent
   text.
2. **Survey flow:** check that the flow shows, in order:
   - the embedded-data fields;
   - consent, then a branch that ends the survey on "I do not agree";
   - instructions, volume;
   - practice, practice end, main, final.

   If a branch is missing or empty, tell me.
3. **Main block:** Loop & Merge must be on with 27 rows and "Randomize loop order" on. The
   `break` question must have display logic "`__js_pos` is equal to 14".
4. **End of survey:** set your recruitment platform's completion link if you use one. Consider
   Survey options → **Anonymize responses**, if the protocol requires it.

## 5. Test before launch

1. **Preview the whole survey on a laptop:**
   - each clip plays once, then the sliders appear, and both must be moved;
   - pausing a clip (for example with the keyboard's play/pause key) makes it start over;
   - the break appears after clip 14 only.
2. **Verification run:** do one full preview in which you set the **dance** slider to the clip
   number shown above the Play button ("Clip 5 of 27" → 5). Export the responses (Data &
   Analysis → Export → CSV, numeric values) into `study_data/` and run:
   ```
   .venv/bin/python3.12 experiments/music_rating/qualtrics/import_qualtrics.py study_data/<export>.csv --verify <ResponseId>
   ```
   One numbering should read `27/27`. If it is `--loop-prefix position` rather than `row`, add
   `--loop-prefix position` to every later import.
3. **Normal import:** run the same command without `--verify`. Expect the preview response as
   complete, with no integrity problems. Preview responses are marked and never suggested for
   inclusion.
4. **Blinding:** in the preview, view the page source of a listening page. Only anonymous IDs
   (`s…`) and file links may appear.

## 6. After data collection

Export as in 5.2 and run the importer. It writes:

- `ratings_long.csv`: one row per participant and clip, with cell, genre, tier, BPM and rung
  joined from the hidden manifest, and 0–5 versions of both ratings.
- `participants.csv`: quality flags and `suggested_include`. The flags cover headphones (self-report),
  the attention item, completeness, full plays, straight-lining, mobile devices and the order
  checks. Nothing is dropped automatically.

The ratings describe the clips as rendered, loudness included. They are not measurements of
composition independent of loudness.

The participant-facing wording lives in `build_qsf.py` (`TEXT`, `Q_DANCE`, `Q_CALM`, `POST`) and
is summarized in `IRB_SUMMARY_REMOTE.md`.
