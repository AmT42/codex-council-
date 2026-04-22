# Planner Authoring

## Role

The planner is a strict doc author, not an implementer.

Its job is to transform:

- raw user intent
- repo inspection results
- discovered constraints

into execution-safe `task.md`, `spec.md`, and `contract.md`.

## Runtime outputs

In the `prepare` loop, the planner writes:

- canonical docs directly:
  - `task.md`
  - `spec.md`
  - `contract.md`
- planner artifacts:
  - `planner/message.md`
  - `planner/status.json`

`planner/status.json` uses:

- `result`: `drafted` | `blocked` | `needs_human`
- `summary`
- `docs_updated`
- `human_source` / `human_message` only for `needs_human`

## Writing rules

- Distinguish facts, inferred repo facts, assumptions, and open questions explicitly.
- Do not hide assumptions as facts.
- Do not use vague words like `production-ready`, `robust`, `good UX`, or `enterprise-grade` without decomposition.
- Prefer explicit decisions over leaving policy for the generator to invent.
- For agentic work, treat prompts, system instructions, tool descriptions, schemas, evaluator behavior, and approval/sandbox posture as first-class product interfaces.
- For broad/spec-driven work, organize `spec.md` into named major sections and place acceptance criteria under each section.
- Derive `contract.md` from the approval-critical parts of `spec.md`; do not write a shallow generic contract and do not restate the whole spec.

## Completeness matrix

When relevant, the planner should cover:

- user intent
- scope boundaries
- architecture/components
- source of truth
- read path
- write path / mutation flow
- failure / fallback / degraded behavior
- state / integrity / concurrency invariants
- observability / validation
- prompt/tool/schema contracts
- approval / safety / sandbox posture

If a dimension truly does not apply, say so explicitly.

## Spec-to-contract linkage

- Write `spec.md` first as the full decision-complete truth.
- Then derive `contract.md` from the approval-critical parts of that spec.
- For each major spec section, ask:
  - if this section were wrong, could approval be wrong?
  - if yes, it needs a contract item or to be covered by a grouped contract item
- A contract item is only valid if all linked acceptance criteria for that spec section are satisfied.
- If a grouped contract item would let the reviewer approve while one linked acceptance criterion still fails, split that item into explicit sub-checks.
- Use [`spec-contract-linking-example.md`](./spec-contract-linking-example.md) as the canonical model.

## Revision protocol

- Revise the docs directly in response to concrete critique.
- Close each cited gap or escalate with `needs_human`.
- Do not respond to missing detail with narrative reassurance.
- If the critic identifies a real omission, fix the document rather than defending the omission.
