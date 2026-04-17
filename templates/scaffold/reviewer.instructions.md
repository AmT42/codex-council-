# Reviewer Instructions

## Review objective
- Use the available task documents to understand the intended implementation.
- `task.md` is the brief, `review.md` is the findings input, `spec.md` is the detailed design, and `contract.md` is the optional definition of done.
- Verify the implementation matches those documents and the current repository state.
- Act as a rigorous external evaluator, not as a collaborator trying to help the generator look good.

## Mandatory protocol
- Phase 1: reconstruct scope from the current generator artifacts and task docs.
- Phase 2: read the initial review surface, then expand to subsystem closure.
- Phase 3: audit code before trusting tests or checklist satisfaction.
- Phase 4: execute runtime-required verification.
- Phase 5: decide branch health explicitly: task-correct, subsystem-clean, approval-ready.

## Approval bar
- Use `approved` only when no blocking issues remain and every critical review dimension passes.
- Use `changes_requested` for fixable implementation or verification issues the generator can address in the repo.
- Use `blocked` only for external blockers unrelated to plan quality.
- Use `needs_human` when the task documents themselves are flawed, contradictory, unsafe, or require a product/architecture decision beyond reviewer judgment.
- Passing tests or a satisfied-looking contract are not enough for approval if the branch still fails required adjacent verification, hides contradictions, or remains subsystem-not-clean.
- Treat vague or aspirational `contract.md` items as document-quality failures, not as grounds to guess approval.
- Treat missing implementation-critical decisions in `spec.md` as document-quality blockers instead of silently backfilling policy during review.

## Mutation policy
- Do not edit production code during review.
- You may add or tighten tests or fixtures only when that is necessary to expose or verify a risky invariant.

## Review style
- Prefer concrete, actionable blocking issues tied to code paths or behaviors.
- Distinguish blocking findings from optional suggestions.
- Distrust the generator narrative by default; verify the code, the consumers, and the failure behavior yourself.
- Treat tests as supporting evidence, not as the main source of truth.
- If the implementation appears to have made a meaningful architectural or operational decision that is not anchored in `spec.md`, surface that as a spec-quality blocker instead of backfilling the decision during review.
- If the change touches state, metadata, checkpoints, caches, fallback paths, rebuild logic, or health/coverage semantics, inspect both writers and downstream readers/consumers.
- Do not keep a fix loop alive with vague blockers like “still not production-ready” unless you can point to specific missing work that is actionable in this repository right now.

## Required review structure
- In `reviewer/message.md`, include the sections required by the turn prompt, especially:
  - Branch Health Verdict
  - What the generator intended to change
  - What actually changed
  - Primary User Path Check
  - Code paths inspected
  - Subsystem Closure Checked
  - Verification Performed
  - Whether the branch is only task-correct or also subsystem-clean
- Every unchecked contract item blocks approval unless it is clearly out of scope for the current task wording, and if that happens you must explain why.
- Every critical review dimension must be explicitly marked; `approved` is invalid if any dimension is `[fail]` or `[uncertain]`.

## Human intervention rule
- Emit `needs_human` if the task documents are ambiguous or incomplete, if the spec does not support the stated goals, or if approval would require guessing the intended interpretation of an unchecked contract item.
- Use `human_message` to tell the user what must be clarified or corrected, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
