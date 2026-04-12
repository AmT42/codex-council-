---
name: codex-council
description: Operate the Codex Council harness from an outer Codex agent. Use when a user wants help choosing between task.md, review.md, spec.md, and contract.md, starting or continuing a council run, inspecting run state, or understanding how to use this repo as a long-running generator/reviewer harness.
---

# Codex Council

This skill is the outer-agent interface for `council-agent`.

Use it when the user wants you to operate this repo as a harness against some target repository. Do not use it when you are modifying `council-agent` itself; for maintainer work, follow repo-root `AGENTS.md`.

## First read

Read these files first:

- [`INSTRUCTS.md`](../../INSTRUCTS.md)
- [`references/routing.md`](./references/routing.md)

Then load only the references needed for the chosen route:

- [`references/task-doc.md`](./references/task-doc.md)
- [`references/review-doc.md`](./references/review-doc.md)
- [`references/spec-doc.md`](./references/spec-doc.md)
- [`references/contract-doc.md`](./references/contract-doc.md)
- [`references/run-lifecycle.md`](./references/run-lifecycle.md)
- [`references/examples.md`](./references/examples.md)

## Core rules

- Classify the request before taking action.
- Prefer action over questions when the request is concrete.
- Ask only high-impact blocking questions.
- Prefer the smallest sufficient document set.
- Default to `contract.md` for non-trivial work.
- Prefer `status` + `continue` over restarting a healthy paused run.
- Summarize the chosen route to the user before launching the harness.

## Required routing

Choose one mode:

1. Direct answer only
2. Inspect or resume an existing run
3. Concrete execution request
4. Findings-driven fix
5. Broad feature or spec work

Use [`references/routing.md`](./references/routing.md) for the exact mapping from request shape to docs and commands.

## Command surface

Do not invent a new interface. Use the existing CLI:

- `init`
- `write`
- `start`
- `status`
- `continue`

Use [`references/run-lifecycle.md`](./references/run-lifecycle.md) for command recipes and continuation policy.

## Document rules

- `task.md` is the default brief for most execution requests.
- `review.md` is for findings-shaped input such as comments, logs, repro notes, or debugging handoff.
- `spec.md` is only for work that needs deeper structure than a short task brief.
- `contract.md` is the default acceptance and approval checklist for most non-trivial runs.
- Task-local `AGENTS.md` stays behavioral and stable; do not put task-specific requirements there.

Use the corresponding document references before writing:

- [`references/task-doc.md`](./references/task-doc.md)
- [`references/review-doc.md`](./references/review-doc.md)
- [`references/spec-doc.md`](./references/spec-doc.md)
- [`references/contract-doc.md`](./references/contract-doc.md)

## Worked examples

Before handling unfamiliar requests, read [`references/examples.md`](./references/examples.md).
