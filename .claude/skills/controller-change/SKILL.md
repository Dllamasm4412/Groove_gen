---
name: controller-change
description: Safely assess and implement GrooveGen controller changes with protocol scope, safety, and deterministic evidence checks.
---

# /controller-change

Purpose
- Safely assess and implement controller/session-control changes with explicit protocol and safety impact reporting.

When To Use
- Changes to LadderMPC, ControllerConfig, governor/setpoint logic, arousal modes, ladder transitions, session-control behavior, rung dynamics, or control metrics.

Mandatory Analysis Gates
1. Scope classification
- State whether the change impacts:
  - engineering validation only,
  - current participant protocol, or
  - future-study-only design.

2. Default behavior protection
- Preserve default arousal_mode='hr_primary' unless explicitly asked to change it.

3. Safety implications
- Identify effects on limits, including baseline-plus-10-bpm ceiling behavior where applicable.
- Call out any risk of more aggressive rung movement or saturation behavior changes.

4. Metric integrity
- Separate and report both:
  - HR vs raw requested target error
  - HR vs governed reference error
- Do not report only mean_abs_error against governed reference without labeling.

5. Evidence before hardware
- Provide deterministic simulation or trace-based checks before suggesting live hardware runs.

6. A/B wording correctness
- Never describe session_ab.py as closed-loop vs open-loop unless fixed-schedule open-loop is actually implemented.

Implementation Rules
- Prefer minimal, isolated patches.
- Preserve append-only trace schema constraints.
- For control-loop changes, include plan-invariance verification where relevant.

Output Template
- Scope Classification
- Safety and Protocol Impact
- Proposed/Implemented Changes
- Verification Plan and Evidence
- Metric Reporting Split (raw vs governed)
- Residual Risks / Follow-ups

Example Invocation
/controller-change
Review the proposed ladder redesign only. Compare the current scalar ladder against a two-axis (genre, tier) representation. Identify all controller, trace, and protocol consequences. Do not implement it.
