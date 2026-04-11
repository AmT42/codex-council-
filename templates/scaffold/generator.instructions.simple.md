# Generator Instructions

## Mission
- Fix the issues described in `initial_review.md` and any later reviewer blocking issues.

## Reliability bar
- Resolve root cause, not symptoms.
- Do not introduce bad code, new errors, unintended behavior, regressions, tech debt, or clear unnecessary complexity.
- Keep diffs minimal, coherent, and aligned with the existing codebase.
- Anticipate plausible future errors and harden the change where reasonable.

## Required reading
- Read `initial_review.md` first. It is the canonical first generator brief in simple mode.
- Use `AGENTS.md` for the shared council rules.
- If `AGENTS.md` and this file disagree, do not guess. Emit `needs_human`.

## Change strategy
- Work in clear, reviewable increments that materially reduce the issues called out in `initial_review.md` or the latest reviewer artifact.
- Before coding, classify each review point or reviewer blocker as `agree`, `disagree`, or `uncertain`.
- Fix the points you agree are valid.
- If you disagree with a point, do not implement it blindly. Explain the disagreement with concrete code evidence.
- If you are uncertain, investigate before changing code and surface the uncertainty explicitly if it remains.
- Prefer straightforward, production-quality fixes over clever shortcuts.
- Do not silently skip difficult parts or paper over broken behavior.
- If you changed repo-tracked files in this turn, create a git commit for those changes before writing the turn artifacts.
- If you change a state, metadata, cache, checkpoint, fallback, or health/coverage contract, inspect both the writers and the downstream readers/consumers before ending the turn.
- When responding to a reviewer `changes_requested` turn, either make a concrete implementation improvement against the listed blockers or emit `needs_human` if the remaining blocker is really an ambiguous initial review or instruction file.
- Do not emit `blocked` merely because the remaining work is broad or unfinished. Reserve `blocked` for real external implementation blockers.

## Quality rules
- Avoid regressions, broken migrations, unsafe assumptions, and partial implementations.
- Update or add tests when the risk profile warrants it.
- Keep changes explainable and reviewable.
- Before ending the turn, sanity-check that your changes reduce the cited issues and do not obviously make the codebase worse.

## Required turn output
- In your generator turn message artifact, include:
  - Findings triage:
    - Agreed points
    - Disagreed points
    - Uncertain points
  - What changed
  - Which initial review findings or reviewer blockers were addressed
  - Commit created for this turn, or explicitly say that no repo-tracked files changed
  - Evidence for rejected points
  - Why the changes avoid bad code, errors, unintended behavior, regressions, tech debt, and unnecessary complexity
  - Anticipated future error cases and how they were handled
  - Changed invariants / preserved invariants
  - Downstream readers / consumers checked
  - Verification performed
  - Remaining open findings or risks

## Human intervention rule
- Emit `needs_human` if `initial_review.md` conflicts with the instructions, if fixing one stated issue would clearly violate another, or if a missing design decision prevents a safe implementation.
- Use `human_message` to describe exactly what the user must clarify or change, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
