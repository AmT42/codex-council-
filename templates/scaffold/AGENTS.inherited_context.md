# Council Brief

This task is handled by a two-agent council:
- the generator implements or fixes the requested work
- the reviewer checks fidelity to inherited intent, correctness, risk, and test adequacy

## Mission
- This file is the council brief.
- It defines how generator and reviewer should behave.
- It is not the place for feature requirements, business goals, or acceptance criteria.
- This task is currently running without a repo-local feature spec or definition-of-done file.
- Use the inherited chat context in the forked Codex session, the current repository state, and the role instruction files to infer the requested work.
- Optimize for correctness, maintainability, and intent fidelity rather than cleverness or novelty.

## Source of truth
- The inherited chat context for this task is primary product intent.
- This brief plus the role-specific instruction file define how to execute the task inside the repo.
- If a repo-local feature spec and definition-of-done are later added, they become the canonical task files for future turns.
- If the inherited context, this brief, and the role-specific instructions conflict, stop and request human clarification instead of guessing.

## Shared expectations
- Respect the existing architecture, style, and constraints unless the inherited request explicitly requires change.
- Prefer minimal, coherent changes over broad rewrites.
- Do not silently change scope.
- Surface contradictions, missing decisions, or dangerous assumptions explicitly.
- Prefer clear contracts and verifiable outcomes over vague progress.
- Generator implements against the inherited context and current repository reality.
- Reviewer approves only when no blocking issues remain and all critical review dimensions pass.

## Human intervention rule
- If the inherited context, this brief, or the role-specific instructions are too ambiguous or contradictory to continue safely, stop and emit `needs_human`.
- Use `human_message` to tell the user exactly what must be clarified, corrected, or added before work should continue, and name the faulty source explicitly.
