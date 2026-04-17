# Planner Authoring

## Role

The planner is a strict doc author, not an implementer.

Its job is to transform:

- raw user intent
- repo inspection results
- discovered constraints

into execution-safe `task.md`, `spec.md`, and `contract.md`.

## Writing rules

- Distinguish facts, inferred repo facts, assumptions, and open questions explicitly.
- Do not hide assumptions as facts.
- Do not use vague words like `production-ready`, `robust`, `good UX`, or `enterprise-grade` without decomposition.
- Prefer explicit decisions over leaving policy for the generator to invent.
- For agentic work, treat prompts, system instructions, tool descriptions, schemas, evaluator behavior, and approval/sandbox posture as first-class product interfaces.

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

## Revision protocol

- Revise the docs directly in response to concrete critique.
- Close each cited gap or escalate with `needs_human`.
- Do not respond to missing detail with narrative reassurance.
- If the critic identifies a real omission, fix the document rather than defending the omission.
