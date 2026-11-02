#!/usr/bin/env bash
# Re-render the 27 v3 candidate excerpts with the locked Musyng Kite soundfont and
# rebuild the final candidate package (audio, MIDI, analysis, draft surveys).
#
# Run on the developer Mac from the repository root, on the branch that holds
# this script:
#   bash experiments/qualtrics_v3_candidate/make_final_musyng.sh \
#       groovegen_qualtrics_27_final_candidate_v3.1-rc1_FluidR3_GM_PRELIMINARY \
#       /path/to/GrooveGen_music_rating.qsf
#
# The first argument is the FluidR3 rc1 package (it fixes the selection: the
# same 27 MIDI files and seeds, no re-screening, no new compositions). The
# second is the existing survey file, which is read and never modified.
#
# It stops, without rendering, if the soundfont is not the locked Musyng Kite
# file. It never substitutes another soundfont.
set -euo pipefail

RC1=${1:?usage: make_final_musyng.sh <FluidR3 rc1 package dir> <original QSF>}
QSF=${2:?usage: make_final_musyng.sh <FluidR3 rc1 package dir> <original QSF>}
SF2=${SF2:-soundfonts/Musyng_Kite.sf2}
PY=${PY:-.venv/bin/python}
LOCKED_SHA=ed8c5a34c28b0fbbc805d6bbae74a169582c1881b57219972052e822c7be35f0

[ -f experiments/qualtrics_v3_candidate/build_candidate.py ] || { echo "run from the repository root"; exit 1; }
[ -d "$RC1/E_analysis" ] || { echo "not a candidate package: $RC1"; exit 1; }
[ -f "$QSF" ] || { echo "survey file not found: $QSF"; exit 1; }
[ -f "$SF2" ] || { echo "soundfont not found: $SF2 (set SF2=/path/to/Musyng_Kite.sf2)"; exit 1; }
for tool in fluidsynth ffmpeg; do
  command -v "$tool" >/dev/null || { echo "$tool not found (brew install $tool)"; exit 1; }
done

SHA=$("$PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$SF2")
if [ "$SHA" != "$LOCKED_SHA" ]; then
  echo "soundfont checksum mismatch: $SHA"
  echo "expected the locked Musyng Kite file: $LOCKED_SHA"
  echo "nothing rendered"
  exit 1
fi
echo "soundfont OK: $SF2 ($SHA)"
echo "commit: $(git rev-parse HEAD)  ($(git status --porcelain | wc -l | tr -d ' ') uncommitted paths)"

# 1. Render the same 27 MIDI selections with Musyng Kite. Each excerpt is matched
#    to the loudness of its original v2c 8-bar segment rendered with the same
#    soundfont, so the loudness calibration is re-measured here, not copied.
"$PY" experiments/qualtrics_v3_candidate/build_candidate.py build \
  --sf2 "$SF2" --selection "$RC1/E_analysis/stimulus_manifest.json"
CAND=groovegen_qualtrics_27_candidate_v3.1_$(basename "$SF2" .sf2)

# 2. Final package: analysis, coding, measurements, draft surveys (new audio
#    checksums), listening package; the v3.0 -> v3.1 before/after clips are
#    carried over from the rc1 package and labelled FluidR3.
"$PY" experiments/qualtrics_v3_candidate/finalize_candidate.py build \
  --from "$CAND" --original-qsf "$QSF" --before-after-from "$RC1" --zip

OUT=groovegen_qualtrics_27_final_candidate_v3.1-rc1_$(basename "$SF2" .sf2)
"$PY" - "$OUT" <<'EOF'
import json, sys
from pathlib import Path
out = Path(sys.argv[1])
m = json.loads((out / 'E_analysis' / 'stimulus_manifest.json').read_text())
env = m['environment']
assert env['soundfont_is_locked_musyng'], 'package is not marked as rendered with the locked Musyng Kite'
mp3 = sorted((out / 'A_qualtrics_mp3').glob('S*.mp3'))
assert len(mp3) == 27, f'{len(mp3)} MP3 files'
print(f"{out}: 27 MP3, soundfont {env['soundfont']} {env['soundfont_sha256'][:12]}")
print('read', out / 'E_analysis' / 'readiness_checklist.md', 'and', out / 'H_qualtrics_draft' / 'survey_validation_report.md')
EOF
echo "listen to every excerpt before upload: Musyng Kite changes timbre and balance."
