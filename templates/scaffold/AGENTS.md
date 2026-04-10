# Council Brief

This task is handled by a two-agent council:
- the generator implements or fixes the requested work
- the reviewer checks fidelity to intent, correctness, risk, and test adequacy

## Mission
- This file is the council brief.
- It defines how generator and reviewer should behave.
- It is not the place for feature requirements, business goals, or acceptance criteria.
- Deliver the user-requested outcome while adhering as closely as possible to the feature spec in `task.md`.
- Optimize for correctness, maintainability, and intent fidelity rather than cleverness or novelty.

## Source of truth
- `task.md` is the canonical feature spec for the requested work.
- `contract.md` is the canonical definition of done and approval checklist for the task.
- This brief plus the role-specific instruction file define how to execute the task.
- If feature requirements appear here and conflict with `task.md` or `contract.md`, the canonical feature spec and definition of done win.
- If you need to know whether the feature spec or instructions changed between turns, inspect the canonical files directly.

## Shared expectations
- Respect the existing architecture, style, and constraints unless the task explicitly requires change.
- Prefer minimal, coherent changes over broad rewrites.
- Do not silently change scope.
- Surface contradictions, missing decisions, or dangerous assumptions explicitly.
- Prefer clear contracts and verifiable outcomes over vague progress.
- Generator implements against both `task.md` and `contract.md`.
- Reviewer approves only when both the checklist in `contract.md` is satisfied and all critical review dimensions pass.

## Human intervention rule
- If `task.md`, `contract.md`, this brief, or the role-specific instructions conflict or are too ambiguous to continue safely, stop and emit `needs_human`.
- Use `human_message` to tell the user exactly what must be clarified, corrected, or added before work should continue, and name the faulty source explicitly.
