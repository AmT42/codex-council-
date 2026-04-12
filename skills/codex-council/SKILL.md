---
name: codex-council
description: Operate the Codex Council harness from an outer Codex agent. Use when a user wants help turning vague or precise software requests into strong task.md, review.md, spec.md, and contract.md documents, then starting, inspecting, or continuing a generator/reviewer council run in a target repository.
---

# Codex Council

This skill is the front door for using `council-agent` as a long-running harness.

Use it when the user wants you to operate this repo against some target repository. Do not use it when you are modifying `council-agent` itself; for maintainer work, follow repo-root `AGENTS.md`.

## Purpose

Your job is not only to launch commands. Your job is to transform user intent into a strong council brief.

That includes:

- classifying the request
- discovering missing repo facts
- normalizing novice input into strong documents
- choosing the smallest sufficient document set
- deciding between direct answer, `start`, and `continue`

## Read order

Read these first:

- [`../../INSTRUCTS.md`](../../INSTRUCTS.md)
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`references/routing.md`](./references/routing.md)
- [`references/novice-normalization.md`](./references/novice-normalization.md)

Then load only the references needed for the chosen route:

- [`references/task-doc.md`](./references/task-doc.md)
- [`references/review-doc.md`](./references/review-doc.md)
- [`references/spec-doc.md`](./references/spec-doc.md)
- [`references/contract-doc.md`](./references/contract-doc.md)
- [`references/run-lifecycle.md`](./references/run-lifecycle.md)
- [`references/failure-recovery.md`](./references/failure-recovery.md)
- [`references/user-sophistication-examples.md`](./references/user-sophistication-examples.md)
- [`references/task-type-examples.md`](./references/task-type-examples.md)

## Core rules

- Classify the request before taking action.
- Prefer action over questions when the request is concrete.
- Ask only high-impact blocking questions.
- Prefer the smallest sufficient document set.
- Default to `contract.md` for non-trivial work.
- Prefer `status` + `continue` over restarting a healthy paused run.
- Do not pass vague user wording directly into the council docs.
- Summarize the chosen route to the user before launching the harness.

## Required routing

Choose one mode:

1. Direct answer only
2. Inspect or resume an existing run
3. Concrete execution request
4. Findings-driven fix
5. Broad feature or spec work

Use [`references/routing.md`](./references/routing.md) for the exact mapping from request shape to docs and commands.

## Novice normalization

If the user gives weak or imprecise input, do not launch immediately.

Instead:

- inspect the repo
- infer likely affected surfaces
- extract the real engineering problem
- write stronger docs than the user could have written directly
- escalate to `spec.md` when needed

Use [`references/novice-normalization.md`](./references/novice-normalization.md) before handling vague or under-specified requests.

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

## Recovery and edge cases

Use [`references/failure-recovery.md`](./references/failure-recovery.md) when:

- the current run looks ambiguous
- the docs are too weak for launch
- `continue` is likely but not obviously correct
- a human paused the run and edited task docs

## Worked examples

Before handling unfamiliar requests, read:

- [`references/user-sophistication-examples.md`](./references/user-sophistication-examples.md)
- [`references/task-type-examples.md`](./references/task-type-examples.md)
