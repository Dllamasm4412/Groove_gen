---
name: trace-analysis
description: Analyze GrooveGen session traces reproducibly while separating engineering-validation and participant-study outputs.
---

# /trace-analysis

Purpose
- Standardize post-hoc analysis of GrooveGen traces and session logs with reproducible, protocol-aware outputs.

When To Use
- Any task analyzing session traces, timing, controller behavior, freshness, latency, underruns, or plotting from engineering/pilot runs.

Core Rules
- Validate data before interpreting it.
- Clearly label engineering-validation logs vs participant-study data.
- Avoid participant identifiers in filenames, plots, exports, and summaries.
- Write analysis artifacts to a dedicated git-ignored output directory unless explicitly asked to commit aggregate artifacts.

Required Validation Checks
- Schema validation (required columns and types)
- Timestamp monotonicity and ordering
- Segment count consistency
- Missing values and NaN audit
- HR freshness flags / stale streaks
- Segment boundaries and ordering integrity

Required Analysis Plan
- HR vs requested target
- HR vs governed reference
- Controller rung over time
- Genre/tier and tempo over time
- Segment timing and inter-segment gaps
- Player underruns and render latency

Implementation Guidance
- Prefer deterministic scripts over ad-hoc notebook-only logic.
- Keep plotting/report generation reproducible from a single command.
- Include exact input/output paths in report headers.

Output Template
- Data Scope
- Validation Results
- Analysis Outputs Generated
- Key Findings (engineering, not efficacy claims)
- Limitations / Missing Signals

Example Invocation
/trace-analysis
Design and implement only the post-hoc plotting script for a single engineering-validation trace. Produce HR vs raw target, HR vs governed reference, rung, tempo, and gap-duration plots. Do not touch controller code.
