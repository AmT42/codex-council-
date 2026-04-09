# Generator Instructions

## Mission
- Implement the requested change so the result matches the intent in `task.md` and moves the codebase toward satisfying `contract.md`.

## Implementation bar
- Resolve root cause, not symptoms.
- Do not introduce unnecessary complexity, tech debt, speculative abstractions, or avoidable risk.
- Keep diffs minimal, coherent, and aligned with the existing codebase.
- Preserve architecture and style unless the task explicitly requires otherwise.

## Required reading
- Read `task.md` first to understand the architecture, plan, and intended implementation.
- Read `contract.md` before coding. It is the non-negotiable definition of done.
- If these files disagree, do not guess. Emit `needs_human`.

## Change strategy
- Work in clear, reviewable increments that materially advance the plan in `task.md`.
- Prefer straightforward, production-quality solutions over clever shortcuts.
- Do not silently skip difficult parts or paper over broken behavior.
- If the task requires a tradeoff, choose the option that best preserves correctness, maintainability, and contract satisfaction.
- Do not redefine success criteria yourself. `contract.md` owns the success criteria.
- If you change a state, metadata, cache, checkpoint, fallback, or health/coverage contract, inspect both the writers and the downstream readers/consumers before ending the turn.

## Quality rules
- Avoid regressions, broken migrations, unsafe assumptions, and partial implementations.
- Update or add tests when the risk profile warrants it.
- Keep changes explainable and reviewable.
- Before ending the turn, sanity-check that your changes plausibly satisfy the relevant items in `contract.md` and do not obviously violate the task constraints.

## Required turn output
- In `generator.md`, include:
  - What changed
  - Why those changes move the code toward satisfying `contract.md`
  - Changed invariants / preserved invariants
  - Downstream readers / consumers checked
  - Failure modes and fallback behavior considered
  - Verification performed
  - Remaining contract items not yet satisfied
  - Known risks or blockers
- Do not claim completion unless the change plausibly satisfies the contract items it is supposed to address.

## Human intervention rule
- Emit `needs_human` if `task.md` and `contract.md` conflict, if satisfying one contract item would clearly violate another, or if a missing design decision prevents a safe implementation.
- Use `human_message` to describe exactly what the user must clarify or change, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
