# Council Brief

This task is handled by a two-agent council:
- the generator fixes the issues described in `initial_review.md`
- the reviewer checks for bad code, introduced errors, unintended behavior, regressions, tech debt, and unnecessary complexity

## Mission
- This file is the council brief.
- It defines how generator and reviewer should behave.
- It is not the place for extra feature requirements or vague aspirations.
- `initial_review.md` is the canonical first generator brief for this simple mode.
- Its points are starting review hypotheses, not unquestionable truth. They must be validated against the codebase.
- Optimize for reliable fixes, correctness, maintainability, and low regression risk.

## Source of truth
- `initial_review.md` is the canonical starting review brief.
- This brief plus the role-specific instruction file define how to execute the task.
- If these files conflict or are too ambiguous to continue safely, stop and emit `needs_human`.

## Shared expectations
- Respect the existing architecture, style, and constraints unless the initial review clearly requires change.
- Prefer minimal, coherent changes over broad rewrites.
- Do not silently change scope.
- Surface contradictions, missing decisions, or dangerous assumptions explicitly.
- Prefer clear fixes and verifiable outcomes over vague progress.
- Generator must think critically about each initial-review point before acting. Invalid points should be rejected with evidence, not implemented blindly.
- Generator must fix the valid issues without introducing bad code, regressions, tech debt, or unnecessary complexity.
- Reviewer should focus on correctness, safety, regressions, maintainability, and whether the implementation clearly made the code worse.
- Reviewer must adjudicate generator disagreements with evidence and must not keep restating the same blocker without stronger evidence.

## Human intervention rule
- If `initial_review.md`, this brief, or the role-specific instructions conflict or are too ambiguous to continue safely, stop and emit `needs_human`.
- Use `human_message` to tell the user exactly what must be clarified, corrected, or added before work should continue, and name the faulty source explicitly.
