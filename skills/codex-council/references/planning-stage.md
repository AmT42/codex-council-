# Planning Stage

## Purpose

For broad, vague, novice-described, or agentic work, do not jump directly from the user prompt to locked execution docs.

Use a planning stage first.

That stage exists to:

- preserve the user's real intent before translation
- produce stronger `task.md`, `spec.md`, and `contract.md`
- reject weak or misleading document drafts before the generator sees them

## When to invoke it

Default to the planning stage when any of these are true:

- the request is broad or spans multiple surfaces
- the user wording is vague or novice-level
- the product is agentic, prompt-driven, tool/schema-heavy, or workflow-heavy
- the task includes approvals, sandboxing, evaluators, orchestration, retries, or complex state behavior
- the spec must be unusually rigorous

Concrete narrow bugfixes can still go straight to execution docs.

## Roles

- planner
  - authors the candidate execution docs
- intent critic
  - reviews those docs for intent fidelity and execution safety

## Route

1. Inspect the repo and gather likely affected surfaces.
2. Preserve the raw user intent explicitly.
3. Planner writes draft `task.md`, `spec.md`, and `contract.md` as needed.
4. Intent critic reviews them against user intent, repo facts, and the planning quality bar.
5. Planner revises the docs directly.
6. Only after approval should those docs be treated as locked execution inputs.

## Hard mode

`hard` mode belongs to this planning stage.

It means:

- require a decision-complete spec, not a directional sketch
- require explicit treatment of prompt/tool/schema/instruction surfaces when relevant
- reject omissions, hidden assumptions, vague contract language, and toy-like abstractions
- optimize for execution safety and intent fidelity rather than brevity

It does **not** merely mean “write more words”.
