---
name: research-protocol-check
description: Classify GrooveGen work by engineering, current-pilot, and amendment-required research scope.
---

# /research-protocol-check

Purpose
- Ensure proposed changes are aligned with current GrooveGen research scope, protocol stage, and IRB boundaries.

When To Use
- Any feature/design request that could change participant experience, data collection scope, personalization depth, or study claims.

Required Distinctions
- Engineering validation on developer rig
- Current feasibility-pilot behavior
- Changes requiring IRB amendment or follow-up protocol

Scope Expansion Flags (must be explicitly called out)
- Streaming-service listening history or external music links
- Per-user rule mutation
- Respiration sensing or additional hardware
- New silent-baseline conditions
- Participant self-report collection or retention changes
- Claims of real open-loop comparison before implementation exists

Project-Specific Guardrails
- Keep feasibility pilot personalization at the approved level unless explicitly authorized to expand.
- Avoid efficacy claims; use engineering/system framing.
- Confirm whether data retention/export behavior changes with any new logging.

Required Workflow
1. Summarize requested change in one paragraph.
2. Classify scope (engineering / pilot / requires amendment).
3. List protocol and data-governance impacts.
4. Provide allowed-now path and deferred path.
5. If blocked by protocol scope, provide a safe alternative implementation plan.

Output Template
- Request Summary
- Scope Classification
- IRB/Protocol Impact
- Data Collection/Retention Impact
- Allowed Actions Now
- Deferred Actions (future-study)

Example Invocation
/research-protocol-check
Assess whether adding streaming-history-based personalization to the current gate is in scope for the feasibility pilot. Provide an allowed-now alternative if not in scope.
