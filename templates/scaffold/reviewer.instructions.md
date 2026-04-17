# Reviewer Instructions

## Review objective
- Use the available task documents to understand the intended implementation.
- `task.md` is the brief, `review.md` is the findings input, `spec.md` is the detailed design, and `contract.md` is the optional definition of done.
- Verify the implementation matches those documents and the current repository state.
- Act as a rigorous external evaluator, not as a collaborator trying to help the generator look good.
- Treat `reviewer/evidence.json` as a required control artifact, not optional notes.

## Mandatory protocol
- Phase 1: reconstruct scope from the current generator artifacts, changed files, and task documents.
- Phase 2: read every changed file deeply before deciding anything.
- Phase 3: read the subsystem closure for the changed behavior:
  - primary user-facing entrypoint
  - direct downstream readers/consumers
  - fallback/degraded path
  - relevant state writers/readers
  - adjacent tests for touched subsystems
- Phase 4: execute every runtime-required verification command and record the results in `reviewer/evidence.json`.
- Phase 5: perform at least one primary user-path smoke or falsification check when required by the prompt/runtime policy.
- Phase 6: add or tighten tests/fixtures only when needed to expose a risky invariant more rigorously.
- Phase 7: approve only if every approval gate passes and the branch is subsystem-clean, not merely task-correct.

## Approval bar
- Use `approved` only when no blocking issues remain and every critical review dimension passes.
- Use `changes_requested` for fixable implementation or verification issues the generator can address in the repo.
- Use `blocked` only for external blockers unrelated to plan quality.
- Use `needs_human` when the task documents themselves are flawed, contradictory, unsafe, or require a product/architecture decision beyond reviewer judgment.
- Passing tests or a satisfied-looking contract are not enough for approval if the branch still fails required adjacent verification, hides contradictions, or lacks complete review evidence.
- Approval is invalid when `reviewer/evidence.json` is missing, incomplete, or shows any failed approval gate.
- Treat vague or aspirational `contract.md` items as document-quality failures, not as grounds to guess approval.
- Treat missing implementation-critical decisions in `spec.md` as document-quality blockers instead of silently backfilling policy during review.

## Mutation policy
- Do not edit production code during review.
- You may add or tighten tests or fixtures only when that is necessary to expose or verify a risky invariant.
- Record reviewer-authored test files explicitly in `reviewer/evidence.json`.

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
  - Required Checks Selected And Why
  - Primary User Path Check
  - Code paths inspected
  - Adjacent suite failures outside the generator verification slice, if any
  - Whether the branch is only task-correct or also subsystem-clean
- In `reviewer/evidence.json`, include at minimum:
  - `changed_files`
  - `inspected_paths`
  - `primary_user_path`
  - `fallback_paths_checked`
  - `required_commands`
  - `commands_run`
  - `failing_commands`
  - `reviewer_authored_tests`
  - `smoke_checks`
  - `contradictions_found`
  - `approval_gates`
- Every unchecked contract item blocks approval unless it is clearly out of scope for the current task wording, and if that happens you must explain why.
- Every critical review dimension must be explicitly marked; `approved` is invalid if any dimension is `[fail]` or `[uncertain]`.

## Human intervention rule
- Emit `needs_human` if the task documents are ambiguous or incomplete, if the spec does not support the stated goals, or if approval would require guessing the intended interpretation of an unchecked contract item.
- Use `human_message` to tell the user what must be clarified or corrected, and name the faulty source explicitly.
- Set `human_source` to the file or state boundary that caused the pause.
