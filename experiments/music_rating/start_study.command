#!/bin/bash
# Experiment 1 launcher. Double-click in Finder (opens Terminal), or run from any folder:
#     experiments/music_rating/start_study.command [PARTICIPANT_CODE]
# Starts the local study server for one participant and opens the page in Chrome.
# Keep the Terminal window open until the participant has finished.

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
PY="$REPO/.venv/bin/python3.12"
APP="$HERE/app.py"
DATA="$REPO/study_data/music_rating"

finish() { echo; read -r -p "Press Enter to close this window. " _; exit "${1:-0}"; }

if [ ! -x "$PY" ]; then
  echo "Python environment not found at $PY"
  finish 1
fi

CODE="$1"
while [ -z "$CODE" ]; do
  read -r -p "Participant code (e.g. P002): " CODE
done

ARGS=(--participant "$CODE")
if [ -f "$DATA/$CODE/session.json" ]; then
  STATUS="$("$PY" -c 'import json,sys; m=json.load(open(sys.argv[1])); print(m["status"], m["next_seq"], len(m["trials"]))' "$DATA/$CODE/session.json")"
  read -r ST DONE TOTAL <<< "$STATUS"
  echo "Participant $CODE already has a session: status $ST, $DONE of $TOTAL trials saved."
  if [ "$ST" != "in_progress" ]; then
    echo "It cannot be continued. Use a new participant code."
    finish 1
  fi
  read -r -p "Continue (resume) this session? [y/N] " YN
  case "$YN" in
    [yY]*) ARGS+=(--resume) ;;
    *) echo "Not started. Use a new participant code to start a new session."; finish 1 ;;
  esac
fi

cd "$REPO" || finish 1
"$PY" "$APP" "${ARGS[@]}"
finish $?
