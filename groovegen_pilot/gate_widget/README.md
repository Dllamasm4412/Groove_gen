# GrooveGen Pre-Session Gate Widget

Streamlit app for one-time participant personalization before a closed-loop session.

## Prerequisites

1. Use the repo virtualenv (`.venv`).
2. Generate frozen renders first:

```bash
python freeze_library.py --out renders/frozen
```

The widget expects these files:
- `renders/frozen/calm_t3.wav`
- `renders/frozen/lofi_t3.wav`
- `renders/frozen/latin_t3.wav`
- `renders/frozen/rock_t3.wav`
- `renders/frozen/hiphop_t3.wav`

## Install

```bash
cd groovegen_pilot
../.venv/bin/pip install -r gate_widget/requirements.txt
```

## Run

```bash
cd groovegen_pilot
../.venv/bin/streamlit run gate_widget/app.py
```

## Run Tests

```bash
cd groovegen_pilot
../.venv/bin/pytest tests/test_gate_scoring.py -v
```

## Output Profiles

Saved JSON profiles are written to:
- `groovegen_pilot/profiles/`

This directory is intentionally gitignored because it contains participant data.
