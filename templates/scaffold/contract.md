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
- For broad/spec-driven work, create one top-level checkbox per major spec section.
- Ensure each top-level item is traceable to a named spec section.
- Use the same section title after `M#.` that appears in the linked `spec.md` heading.
- Under each top-level `M#` checkbox, add indented `M#.A#` sub-checks that cite every linked acceptance criterion from `spec.md`.
- The top-level `M#` checkbox is only checkable if every nested `M#.A#` sub-check is checked.
- Do not add nested checklist items that are not tied to a spec acceptance criterion.
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

For broad/spec-driven work, prefer a shape like:

```md
# Definition of Done

- [ ] M1. Section Name
  - [ ] M1.A1 First linked acceptance criterion.
  - [ ] M1.A2 Second linked acceptance criterion.
- [ ] M2. Another Section
  - [ ] M2.A1 First linked acceptance criterion.
  - [ ] M2.A2 Second linked acceptance criterion.
```
