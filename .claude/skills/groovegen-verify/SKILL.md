---
name: groovegen-verify
description: Verify GrooveGen changes using the existing environment, targeted evidence, deterministic disposable artifacts, and explicit limitations.
---

# /groovegen-verify

Purpose
- Standard end-of-task verification workflow for GrooveGen implementation tasks.
- Produce concrete evidence of correctness with the smallest sufficient checks.

When To Use
- After any code change.
- Before proposing commit readiness.
- When asked to verify without editing code.

Core Rules
- Inspect changed files first and propose the smallest appropriate verification plan before running commands.
- Use the existing repository venv only: /Users/daniel/Desktop/PhD/groove_gen_project/.venv
- Do not create, mutate, or replace Python environments.
- Start with targeted syntax/import checks, then run relevant tests/smoke scripts.
- For audio-impacting changes, render deterministic short artifacts to a disposable directory, never canonical frozen outputs.
- Never claim audio quality. Only report that render/playback commands completed.
- Report exact commands, changed files, pass/fail status, and limitations.

Project Constraints To Preserve
- No vocals.
- No neural networks in the live control path.
- Preserve frozen library contracts and deterministic behavior.
- Trace schema is append-only.
- Preserve within-segment plan invariance checks for control-loop changes.

Required Workflow
1. Discovery and plan
- Run git status --short and identify changed files.
- Map changed files to minimal checks.
- Print a Verification Plan before executing.

2. Baseline checks
- Targeted compile checks for changed Python files:
  - /Users/daniel/Desktop/PhD/groove_gen_project/.venv/bin/python -m py_compile <file1> <file2> ...
- Fast import sanity if entrypoints changed:
  - /Users/daniel/Desktop/PhD/groove_gen_project/.venv/bin/python -c "import <module>; print('ok')"

3. Behavioral checks
- Run focused tests or smoke scripts that directly cover changed areas.
- Prefer narrow scope before broad sweeps.

4. Audio-impact checks (only if relevant)
- Render deterministic short artifacts to a disposable path such as:
  - groovegen_pilot/renders/smoke_verify/<timestamp>/
- Do not write into renders/frozen_v2/.
- Report output paths and command exit status.

5. Summarize evidence
- List each command and result (pass/fail).
- List unchanged/untested risk areas.
- State explicit limitations.

Output Format
- Verification Plan
- Commands Run
- Changed Files Covered
- Results (pass/fail)
- Audio Render Artifacts (if any)
- Limitations / Not Verified
- Ready/Not Ready for Commit (with reason)

Example Invocation
/groovegen-verify
Verify the hiphop/rock genre-registration patch. Do not edit code. Check compilation, seven GENRE_CFG keys, 35 ladder cells, and deterministic rendering for hiphop tier 3 at 92 BPM and rock tier 3 at 120 BPM.
