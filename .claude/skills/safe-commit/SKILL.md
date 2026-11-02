---
name: safe-commit
description: Review GrooveGen Git changes and prepare a safe commit plan without staging, committing, pushing, or rewriting history.
---

# /safe-commit

Purpose
- Prepare safe, reviewable commit proposals without accidental staging of generated/private artifacts.

When To Use
- Before every commit request.
- After large patches, rendering runs, data generation, or exploratory work.

Hard Rules
- Never run git add, git commit, or git push unless explicitly requested after showing the proposed file list.
- Require verification evidence before labeling a commit as ready.
- Explicitly protect profiles/ as intentionally ignored.

Required Workflow
1. Working tree inspection
- Run git status --short
- Inspect git diff (and optionally --stat) for scope sanity.

2. File classification
- Safe-to-commit source/config/docs
- Generated artifacts to keep untracked
- Suspicious/private files requiring manual confirmation

3. Explicitly flag high-risk items
- Raw physiology/trace data
- Audio renders and large binaries
- .env and secrets
- Scratch folders and temporary outputs
- Auto-generated reports unless requested

4. Verification gate
- Summarize verification status and missing checks.
- If verification is missing, mark commit as not ready.

5. Commit draft
- Propose a precise conventional commit message.
- Propose a minimal file list to stage (proposal only).

Output Template
- Working Tree Summary
- Safe To Commit
- Keep Untracked / Exclude
- Verification Status
- Proposed Commit Message
- Proposed Stage List (do not execute)

Example Invocation
/safe-commit
Review the working tree after the genre-integration patch. Tell me exactly which files are safe to commit, which should remain untracked, the verification evidence still needed, and a proposed conventional commit message. Do not stage anything.
