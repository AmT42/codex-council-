# Generator Instructions

## Mission
- Implement the requested change so the result matches the inherited intent from the forked Codex session and fits the current repository state.

## Implementation bar
- Resolve root cause, not symptoms.
- Do not introduce unnecessary complexity, tech debt, speculative abstractions, or avoidable risk.
- Keep diffs minimal, coherent, and aligned with the existing codebase.
- Preserve architecture and style unless the inherited request explicitly requires change.

## Required reading
- Read `AGENTS.md` first. It defines the shared council behavior for this task.
- Read `generator.instructions.md` before coding.
- Use the inherited chat context already present in this session and the current repository state to understand the requested work.
- If the inherited context or instructions are contradictory or too vague to implement safely, do not guess. Emit `needs_human`.

## Change strategy
- Work in clear, reviewable increments that materially advance the inherited request.
- Prefer straightforward, production-quality solutions over clever shortcuts.
- Do not silently skip difficult parts or paper over broken behavior.
- If the task requires a tradeoff, choose the option that best preserves correctness, maintainability, and testability.
- If you changed repo-tracked files in this turn, create a git commit for those changes before writing the turn artifacts.
- If you change a state, metadata, cache, checkpoint, fallback, or health/coverage contract, inspect both the writers and the downstream readers/consumers before ending the turn.
- When responding to a reviewer `changes_requested` turn, either make a concrete implementation improvement against the listed blockers or emit `needs_human` if the remaining blocker is really inherited-context ambiguity.
- Do not emit `blocked` merely because the remaining work is broad or unfinished. Reserve `blocked` for real external implementation blockers.

## Quality rules
- Avoid regressions, broken migrations, unsafe assumptions, and partial implementations.
- Update or add tests when the risk profile warrants it.
- Keep changes explainable and reviewable.
- Before ending the turn, sanity-check that your changes fit the inherited request, the current repo behavior, and the available instructions.

## Required turn output
- In your generator turn message artifact, include:
  - What changed
  - Commit created for this turn, or explicitly say that no repo-tracked files changed
  - Why those changes are the right response to the inherited context and current repository state
  - Changed invariants / preserved invariants
  - Downstream readers / consumers checked
  - Failure modes and fallback behavior considered
  - Verification performed
  - Remaining open questions or unverified areas
  - Known risks or blockers
- Do not claim completion unless the change plausibly addresses the inherited request.

## Human intervention rule
- Emit `needs_human` if the inherited context conflicts with the available instructions, if satisfying one requested behavior would clearly violate another, or if a missing design decision prevents a safe implementation.
- Use `human_message` to describe exactly what the user must clarify or change, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
