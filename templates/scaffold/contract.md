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
