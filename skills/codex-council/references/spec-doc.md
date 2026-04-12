# `spec.md`

## When to use it

Create `spec.md` only when `task.md` would leave real implementation ambiguity.

Common triggers:

- multi-surface features
- explicit in-scope and out-of-scope boundaries
- architecture or interface constraints
- non-obvious validation expectations
- work that would otherwise need too much detail stuffed into `task.md`

## Writing rules

`spec.md` should make complex work executable without becoming a dumping ground.

Fill the existing sections with concrete decisions:

- `## Goal`
- `## User Outcome`
- `## In Scope`
- `## Out of Scope`
- `## Constraints`
- `## Existing Context`
- `## Desired Behavior`
- `## Technical Boundaries`
- `## Validation Expectations`
- `## Open Questions`

## Question policy

Ask blocking questions before launch.

Use `## Open Questions` only for uncertainty that does not prevent safe execution of the current plan.

## Good defaults

- Keep the spec concrete and implementation-relevant.
- Name important boundaries explicitly so the reviewer can enforce them.
- Pair `spec.md` with `contract.md`.

## Example uses

- a feature touching backend, UI, and migration surfaces
- work with strict backward-compatibility requirements
- an initiative with explicit non-goals and rollout constraints
