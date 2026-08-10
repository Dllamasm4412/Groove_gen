# nb15 RE-TUNE SPEC — tempo-band-driven genre, spread the arc

## CONTEXT
The redesigned nb15 works (5 segments, deadband works, all prior fixes intact) BUT the arc came out compressed:
`latin@125 → latin@111 → latin@96 → pop@91 → r&b@90` — three tempo steps happened INSIDE Latin, then genre flipped latin→pop→r&b in the final ~6 BPM. Two root causes:
1. `tempo_min=90` — controller hit its floor at 90, so R&B/calm couldn't spread out below it.
2. Genre is driven by the cascade's SATURATION ESCALATION, so all genre changes bunched up at the tempo floor.

## THE FIX THE USER CHOSE (authoritative)
DERIVE GENRE FROM THE COMMITTED TEMPO BAND, not from cascade genre escalation. User's exact words: "keep all higher tempos latin, then middle tempos pop, slower tempos r&b and lastly calm tempos for the calm genre." And: "Add a calm floor below R&B."

So each genre OWNS a distinct tempo band. One clean big jump per band crossing, genre + tempo descend TOGETHER.

## TEMPO→GENRE BAND MAPPING (implement in the notebook segment-build loop, cell ~9)
Define explicit bands (tune edges so the descending HR curve crosses all four):
- tempo >= 112            -> "latin"   (HIGH)
- 98 <= tempo < 112       -> "pop"     (MIDDLE)
- 84 <= tempo < 98        -> "r&b"     (SLOWER)
- tempo < 84              -> "calm"    (LOWEST)

Target arc: latin@~125 → pop@~108 → r&b@~90 → calm@~76, ~4 committed segments, each ~15s.

## CONTROLLER CHANGES (cell ~6)
- **tempo_min = 70** (was 90) so the curve can reach the calm band (~76) and the R&B band (~90) with room.
- Keep max_step_bpm=15, density_min=3, density_max=8.
- The scripted HR curve should descend from ~125 to ~74 (END_HR_BPM ~= 74) so it crosses all four bands, then hold a calm plateau (controller idle → tier 'none').
- KEEP CascadeController's tempo + density tiers as the actuators (do NOT reimplement). ONLY the GENRE selection is overridden: after each committed tempo is known, look up genre from the band table above instead of using cc's internal genre index. (You can still call cc.step(); just derive the segment's genre from committed tempo, not from cc.genre.)

## "CALM" IS NOT A REAL GENRE — HONEST IMPLEMENTATION (important)
genre_styles.py has NO "calm" StyleSpec (styles: latin/salsa, pop, r&b/soul, hip-hop, classic-rock, metal). Do NOT invent a fake "calm genre." Implement "calm" as: **r&b/soul style at the lowest tempo band with density floored at 3** — a sparse, slow neo-soul bed. Label it in the UI/prompt/panels as "calm (sparse low-tempo R&B/soul)" — NEVER as a distinct genre we don't have. Update the honesty/evidence-tier language accordingly.
- GENRE_TO_STYLE must map: {"latin":"latin", "pop":"pop", "r&b":"r&b", "calm":"r&b"} (calm reuses r&b style, sparser).
- GENRE_MOOD: give "calm" a slow/sparse mood prompt (e.g. "slow, sparse, gentle, minimal") distinct from r&b's.
- For the MusicGen prompt on calm segments, use a slow-tempo sparse phrasing.
- Density on calm segment: force toward floor (3–4).

## VIZ
- Tempo panel: should now show ~4 clean steps, each aligned with a genre-band boundary. Keep hard-cut markers.
- Add genre band SHADING or genre labels on the tempo panel so the latin/pop/r&b/calm bands are visible (optional but strongly preferred — it makes "tempo determines genre" legible).
- Keep all 4 panels (SIMULATED HR, respiration shown-not-driving, tempo, density + tier_that_acted strip).
- The tier_that_acted strip: note that since genre is now tempo-derived, 'genre' may not appear in tier_that_acted (that's fine — genre is a DISPLAY DERIVATION now). Update any assertion that requires 'genre' in tier counts. Still require 'tempo' and 'none' present.

## KEEP ALL PRIOR FIXES (do NOT regress)
transformers==4.44.2 pin; CUDA_LAUNCH_BLOCKING; hf_transfer + HF_HUB_DOWNLOAD_TIMEOUT=60; use_safetensors=True; token cap + loop-to-length (GEN_SECONDS=12, MAX_NEW_TOKENS_CAP=1400, gen_bed loops short bed to fill segment); splice_beds_downbeat_hard_cut (hard cut, no crossfade); CascadeController REUSED (tempo+density tiers) not reimplemented. Honesty guardrails: HR is scripted setpoint the controller TRACKS, never "lowers HR"/"regulates emotion"; respiration shown-not-driving; top disclaimer + PubMed 34886210 & 28266647 (plant sign only) + closing per-claim evidence-tier table + limitations + Latin N=19 caveat.

## BUILDER + VALIDATION
- Edit EXISTING builder /home/user/workspace/groovegen_project/build_notebook_15.py. Inner docstrings inside r"""...""" cell wrappers MUST use ''' not """.
- Re-emit /home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb.
- VALIDATE: nbformat.validate; ast.parse each code cell after stripping ^\s*[!%] lines.
- CONTROL DRY-RUN (extract setpoint curve + cc wiring + tempo→genre band mapping from the notebook's own cells, run standalone):
  * assert committed-segment count in [4,5]
  * assert the genre sequence is latin → pop → r&b → calm (all four present, in that order)
  * assert each genre's committed tempo is IN its band (latin>=112, pop 98-112, r&b 84-98, calm <84)
  * assert density within [3,8]; assert 'tempo' and 'none' in tier_that_acted
  * REPORT the exact per-segment (genre, committed_tempo, n_bars, density) table
- SPLICE dry-run on r&b + salsa beds (paths below): finite, non-silent.
- FFMPEG volumedetect dry-run: mean_volume != -inf.
- Write /home/user/workspace/nb15_retune_findings.md with the per-segment table + validation + confirmation prior fixes intact.

## BEDS
- r&b bed: /home/user/workspace/uploaded_attachments/c11d88d97a6f4aaf95cdfc94d6b36941/download.wav
- salsa/latin bed: /home/user/workspace/uploaded_attachments/63787d33f08b41dba1d938272f63641a/download-3.wav
- pop + calm beds: GENERATED via MusicGen at committed tempo (existing gen_bed path).

## FILES
- Builder: /home/user/workspace/groovegen_project/build_notebook_15.py
- Notebook out: /home/user/workspace/groovegen_project/notebooks/15_closed_loop_hr_audio.ipynb
- Controller: /home/user/workspace/groovegen_project/groovegen/pd_controller.py (CascadeController, TempoController.max_step_bpm, density_min/max)
- genre_styles: /home/user/workspace/groovegen_project/groovegen/genre_styles.py (no 'calm' style — reuse r&b)
- Findings out: /home/user/workspace/nb15_retune_findings.md
