# `contract.md`

## Default policy

`contract.md` is the default acceptance and approval artifact for most non-trivial runs.

Skip it only when the request is:

- ultra-trivial
- effectively one-step
- or direct-answer-only

## Purpose

`contract.md` gives the reviewer an auditable definition of done.

For broad/spec-driven work, treat `contract.md` as the approval projection of `spec.md`, not as an independent mini-spec.

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

For broad/spec-driven work:
- prefer one checkbox per major spec section or approval-critical group
- ensure each item is traceable to a named spec section
- only check an item when all acceptance criteria for the linked spec section are satisfied
- write each item precisely enough that a partially complete change cannot still satisfy it by interpretation
- do not allow a checkbox to stand in for a broad feature claim unless its linked spec section has explicit acceptance criteria that fully define completion for that point
- when a major spec section has multiple acceptance criteria, prefer explicit contract sub-checks rather than collapsing them into one broad paraphrase if that would weaken approval
- if a contract sub-check drops an approval-critical detail from the linked acceptance criterion, it is too weak

For a full worked example, see:

- [`spec-contract-linking-example.md`](./spec-contract-linking-example.md)

Bad contract items:

- `production-ready`
- `enterprise-grade`
- `best-in-class`
- `good UX`

Those phrases are acceptable only after decomposition into something concrete.

Planning-stage note:

- when broad or agentic work goes through the planning stage, the intent critic should reject any contract that still relies on vague aspirational language
- in planning-stage `hard` mode, a contract that cannot justify approval without interpretation is a hard fail

## Quality bar

A strong contract usually contains:

- at least one behavior outcome
- at least one regression or integrity guardrail when relevant
- at least one verification item

For broad/spec-driven work, treat those as a minimum bar rather than a nice-to-have.

If the contract cannot tell the reviewer why approval is justified, it is too weak.

If the contract can be marked complete while the linked spec is still only partially implemented, it is too weak.

## Recommended shape

Aim for roughly 3 to 6 checklist items.

Useful categories:

- behavior or user-visible outcome
- state or integrity requirement
- verification requirement such as tests, repro, or manual validation

When the spec introduces runtime, fallback, state, persistence, or compatibility guarantees, ensure at least one checklist item makes those guarantees auditable.

For spec-driven work, the reviewer may mark a contract item done only when all acceptance criteria for the linked spec section are satisfied for that item. Partial satisfaction is not enough.

Reviewer contract state is recomputed from current branch state every turn. If later generator work regresses a previously satisfied contract item or sub-check, the reviewer should uncheck it again and record the regression explicitly.

If the task has both a primary user-facing path and a maintenance/background/helper path, ensure at least one checklist item makes it auditable that the primary behavior is satisfied by the correct path and not merely by an adjacent helper mechanism.

When prompts, system instructions, tool descriptions, schemas, approvals, or evaluator behavior are part of the product surface, ensure at least one checklist item makes their required behavior auditable.

When subsystem cleanliness materially affects approval, include one explicit branch-quality / validation gate item rather than relying only on feature-presence checkboxes.

## Example seed

```markdown
# Definition of Done

- [ ] The retry path no longer creates duplicate rows after a partial-success failure.
- [ ] The intended row still syncs successfully after the retry.
- [ ] Relevant automated verification for the changed behavior is present and passing.
```
