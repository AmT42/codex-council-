# Definition of Done

This file is the default acceptance and approval checklist for most non-trivial council runs.

Skip it only for ultra-trivial tasks or direct-answer-only requests.

Write the definition of done for this task here as a checklist.

Rules:
- Keep this file short and audit-oriented.
- Every item must be objectively checkable.
- Each bullet should describe something that must be true before approval.
- Keep detailed product reasoning, architecture, and implementation notes in `task.md`, `review.md`, or `spec.md`, not here.
- The reviewer will copy this checklist into the reviewer turn message artifact and mark items with `[x]` / `[ ]`.
- For broad/spec-driven work, treat this file as the approval projection of `spec.md`, not as an independent mini-spec.
- Prefer one checkbox per major spec section or approval-critical group, not one checkbox per tiny implementation detail.
- Each contract item should be traceable to a named spec section, and it is only checkable if all acceptance criteria for that linked spec section are satisfied.
- When a contract item depends on runtime enforcement, fallback safety, validator correctness, or state integrity, phrase it so the reviewer can prove it on the real path rather than by helper equivalence alone.
- See the worked example in `spec-contract-linking-example.md` for the intended spec→acceptance criteria→contract mapping.
- For broad/spec-driven work, include at least:
  - one concrete behavior or outcome item
  - one regression / integrity / fallback / state guardrail
  - one explicit verification item
  - one branch-quality / approval-quality item when subsystem cleanliness materially affects approval
- When relevant, include one item that proves the main user-visible behavior is satisfied by the correct path rather than by an adjacent helper or maintenance path.
- When prompts, instructions, tools, schemas, approvals, or evaluator behavior are part of the product surface, include at least one item that makes those requirements auditable.

Bad examples:
- [ ] ready to go viral
- [ ] production-ready
- [ ] enterprise-grade

Good examples:
- [ ] Health endpoint returns a structured success payload.
- [ ] Required API errors return structured 4xx or 5xx JSON responses.
- [ ] Deployment instructions are present and accurate.
- [ ] Required tests for the changed behavior are present and passing.
- [ ] Analytics events for the onboarding funnel are implemented and documented.
