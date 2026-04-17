# `contract.md`

## Default policy

`contract.md` is the default acceptance and approval artifact for most non-trivial runs.

Skip it only when the request is:

- ultra-trivial
- effectively one-step
- or direct-answer-only

## Purpose

`contract.md` gives the reviewer an auditable definition of done.

It should encode short checklist items that are:

- objective
- observable
- relevant to the requested change
- narrow enough that approval is not guesswork

## Writing rules

Use a short checklist.

Good contract items usually cover:

- the required behavior
- an important risk or regression guardrail
- required validation
- when relevant, the correct path for the user-visible behavior

Bad contract items:

- `production-ready`
- `enterprise-grade`
- `best-in-class`
- `good UX`

Those phrases are acceptable only after decomposition into something concrete.

## Quality bar

A strong contract usually contains:

- at least one behavior outcome
- at least one regression or integrity guardrail when relevant
- at least one verification item

For broad/spec-driven work, treat those as a minimum bar rather than a nice-to-have.

If the contract cannot tell the reviewer why approval is justified, it is too weak.

## Recommended shape

Aim for roughly 3 to 6 checklist items.

Useful categories:

- behavior or user-visible outcome
- state or integrity requirement
- verification requirement such as tests, repro, or manual validation

When the spec introduces runtime, fallback, state, persistence, or compatibility guarantees, ensure at least one checklist item makes those guarantees auditable.

If the task has both a primary user-facing path and a maintenance/background/helper path, ensure at least one checklist item makes it auditable that the primary behavior is satisfied by the correct path and not merely by an adjacent helper mechanism.

## Example seed

```markdown
# Definition of Done

- [ ] The retry path no longer creates duplicate rows after a partial-success failure.
- [ ] The intended row still syncs successfully after the retry.
- [ ] Relevant automated verification for the changed behavior is present and passing.
```
