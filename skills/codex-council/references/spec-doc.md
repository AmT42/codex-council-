# `spec.md`

## When to use it

Create `spec.md` only when `task.md` would leave real implementation ambiguity.

Common triggers:

- multi-surface features
- explicit in-scope and out-of-scope boundaries
- architecture or interface constraints
- non-obvious validation expectations
- work that would otherwise need too much detail stuffed into `task.md`

`github_pr_codex` note:

- a PR-driven run can still omit `spec.md` entirely when the PR plus current-head review findings are specific enough
- add `spec.md` only when the branch/worktree change remains too broad to execute safely from the PR context alone

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

For broad/spec-driven work, the spec should also make the relevant execution dimensions decision-complete, not merely mention them. Typical dimensions:

- source of truth / ownership
- read path
- write path / mutation flow
- runtime / performance expectations
- failure / fallback / degraded behavior
- state / integrity / concurrency invariants
- observability / validation hooks

If a dimension is relevant, decide it. If it truly does not apply, say so explicitly with a short reason.

## Quality bar

The spec should answer enough questions that the generator does not need to invent architecture or scope boundaries.

At minimum, it should make clear:

- what is being built or changed
- what is explicitly in and out of scope
- what constraints matter
- what validation the reviewer should expect
- what implementation-critical runtime or state policy should happen, when relevant

## Question policy

Ask blocking questions before launch.

Use `## Open Questions` only for uncertainty that does not prevent safe execution of the current plan.

## Good defaults

- Keep the spec concrete and implementation-relevant.
- Name important boundaries explicitly so the reviewer can enforce them.
- Pair `spec.md` with `contract.md`.
- Prefer explicit defaults or assumptions over leaving the generator to choose policy during implementation.

## Example uses

- a feature touching backend, UI, and migration surfaces
- work with strict backward-compatibility requirements
- an initiative with explicit non-goals and rollout constraints
