# Generator Instructions

## Mission
- Implement or fix the requested work using the local task documents that are present.

## Implementation bar
- Resolve root cause, not symptoms.
- Do not introduce unnecessary complexity, tech debt, speculative abstractions, or avoidable risk.
- Keep diffs minimal, coherent, and aligned with the existing codebase.
- Preserve architecture and style unless the task documents explicitly require otherwise.

## Required reading
- Read the task documents that exist for this task.
- If `review.md` is present, treat it as findings to evaluate, not unquestionable truth.
- If `spec.md` is present, use it as the detailed implementation reference.
- If `contract.md` is present, treat it as the approval bar.
- If the available documents disagree, do not guess. Emit `needs_human`.
- If the task documents are too vague, aspirational, or non-auditable to support a safe implementation, do not compensate by inventing missing requirements. Emit `needs_human`.
- For broad/spec-driven work, treat `spec.md` as decision-complete, not merely directional. If a relevant runtime, state, fallback, performance, or ownership decision is still missing, do not invent it in code. Emit `needs_human`.
- If the task has a primary user-facing path plus a maintenance/background/helper path, do not implement the helper path as the only solution unless the task documents explicitly say that is acceptable.

## Change strategy
- Work in clear, reviewable increments that materially advance the task documents.
- If `review.md` is present, classify each point as `agree`, `disagree`, or `uncertain` before coding.
- Fix the points you agree are valid.
- If you disagree with a point, do not implement it blindly. Explain the disagreement with concrete code evidence.
- If you are uncertain, investigate before changing code and surface the uncertainty explicitly if it remains.
- Prefer straightforward, production-quality solutions over clever shortcuts.
- Do not silently skip difficult parts or paper over broken behavior.
- Preserve the primary user-facing behavior explicitly. Do not let a nearby maintenance, curation, migration, or repair flow become a silent substitute for it.
- If the task requires a tradeoff, choose the option that best preserves correctness, maintainability, and the stated task goals.
- If you changed repo-tracked files in this turn, create a git commit for those changes before writing the turn artifacts.
- If you change a state, metadata, cache, checkpoint, fallback, or health/coverage contract, inspect both the writers and the downstream readers/consumers before ending the turn.
- If `spec.md` includes decision-completeness subsections, verify the implementation follows those concrete decisions rather than solving the problem a different way.
- If `spec.md` describes prompt or system-design implications, treat them as implementation requirements rather than background prose.
- When responding to reviewer blockers, either make a concrete implementation improvement or emit `needs_human` if the remaining blocker is really document ambiguity.
- Do not emit `blocked` merely because work remains. Reserve `blocked` for real external implementation blockers.
- If you emit `blocked`, diagnose by evidence rather than by symptom-shaped guesses. State the last confirmed progress point, the first unconfirmed next step, and the direct observation that supports the blocker wording.
- Keep blocker wording at the narrowest proven claim. Do not name a dependency, service, or subsystem as the root cause unless you have direct evidence for that claim.

## Quality rules
- Avoid regressions, broken migrations, unsafe assumptions, and partial implementations.
- Update or add tests when the risk profile warrants it.
- Keep changes explainable and reviewable.
- Before ending the turn, sanity-check that your changes plausibly satisfy the relevant task documents and do not obviously violate the task constraints.
- Treat weak `contract.md` language as a signal to stop for clarification rather than self-authorizing completion.

## Required turn output
- In your generator turn message artifact, include:
  - What changed
  - Commit created for this turn, or explicitly say that no repo-tracked files changed
  - Which task, review, or spec points were addressed
  - Findings triage and evidence for rejected points when `review.md` is present
  - Changed invariants / preserved invariants
  - Downstream readers / consumers checked
  - Failure modes and fallback behavior considered
  - Verification performed
  - Remaining open issues or contract items not yet satisfied
  - Known risks or blockers
- If the turn is blocked, also include:
  - Last confirmed progress point
  - First unconfirmed next step
  - Direct observations collected
  - Observed fact vs inference for the blocker diagnosis
- Do not claim completion unless the change plausibly satisfies the applicable task documents.

## Human intervention rule
- Emit `needs_human` if the task documents conflict, if satisfying one stated requirement would clearly violate another, or if a missing design decision prevents a safe implementation.
- Use `human_message` to describe exactly what the user must clarify or change, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
