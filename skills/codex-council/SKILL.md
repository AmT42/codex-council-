---
name: codex-council
description: Operate the Codex Council harness from an outer Codex agent. Use when a user wants help turning vague or precise software requests into strong task.md, review.md, spec.md, and contract.md documents, then starting, inspecting, continuing, or reopening a generator/reviewer council run in a target repository.
---

# Codex Council

This skill is the front door for using `council-agent` as a long-running harness.

Use it when the user wants you to operate this repo against some target repository. Do not use it when you are modifying `council-agent` itself; for maintainer work, follow repo-root `AGENTS.md`.

## Non-Negotiable Boundary

If the user asked you to **use this harness** for a task, you are the harness operator.

Your job is to:

- inspect the target repo
- write or update the canonical council docs
- choose between direct answer, `start`, `continue`, and `reopen`
- launch or resume the council

Your job is **not** to:

- directly implement the target-repo feature yourself instead of using the council
- add helper code, wrappers, integrations, or glue inside `council-agent` just because the target task would be easier that way
- treat a missing convenience layer as permission to bypass the harness

Only modify `council-agent` itself when the user explicitly asks for a feature or change in this harness repository.

## Purpose

Your job is not only to launch commands. Your job is to transform user intent into a strong council brief.

That includes:

- classifying the request
- discovering missing repo facts
- normalizing novice input into strong documents
- invoking a planning stage before execution docs are locked when the work needs it
- choosing the smallest sufficient document set
- deciding between direct answer, `start`, `continue`, and `reopen`

## Read order

Read these first:

- [`../../INSTRUCTS.md`](../../INSTRUCTS.md)
- [`../../ARCHITECTURE.md`](../../ARCHITECTURE.md)
- [`references/routing.md`](./references/routing.md)
- [`references/novice-normalization.md`](./references/novice-normalization.md)
- [`references/planning-stage.md`](./references/planning-stage.md)

Then load only the references needed for the chosen route:

- [`references/planner-authoring.md`](./references/planner-authoring.md)
- [`references/intent-critic.md`](./references/intent-critic.md)
- [`references/hard-mode.md`](./references/hard-mode.md)
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
- Prefer `status` + `continue` over restarting a healthy paused run, but use `reopen` when an approved run must be superseded explicitly.
- Do not pass vague user wording directly into the council docs.
- Do not do the target-repo implementation work yourself when the harness is the requested tool.
- For broad/spec-driven/vague/agentic work, run a planning stage before locking execution docs.
- In that planning stage, use the planner to author docs and the intent critic to reject weak or non-faithful drafts before execution begins.
- For broad/spec-driven work, do not stop at architecture shape. Write a **decision-complete** `spec.md` that covers the relevant runtime, state, fallback, performance, and validation consequences so the generator does not need to invent policy.
- When the task is agentic, workflow-driven, or prompt-sensitive, make the brief explicit about:
  - the primary user-facing path or intent
  - any maintenance/background/curation paths
  - forbidden substitutions between those paths
  - prompt/system-design consequences that must not be improvised in code
- When the current run or prior findings include a blocker, timeout, or stall report, normalize that report into the strongest evidence-backed form rather than passing through a guessed root cause. Prefer the narrowest proven claim.
- Do not launch `start`, `continue`, or `reopen` and then abandon the supervisor process.
- This is a process-lifetime rule, not a special built-in Codex background feature.
- A plain foreground command is fine only when you will stay attached and wait for the supervisor.
- If you need the supervisor to outlive the current outer-agent shell, prefer launching the supervisor command inside a dedicated `tmux` session.
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
- use the planning stage to write stronger docs than the user could have written directly
- escalate to `spec.md` when needed
- when using `spec.md`, cover not just what is being built, but the relevant source-of-truth, read/write flow, failure/fallback, runtime cost, integrity/concurrency, and observability decisions unless they are explicitly not applicable
- explicitly preserve the primary user-facing intent so the generator does not solve the wrong adjacent workflow
- use `hard` mode in the planning stage when the spec must be unusually rigorous; `hard` means decision-complete rigor, not mere length

Use [`references/novice-normalization.md`](./references/novice-normalization.md) before handling vague or under-specified requests.

## Command surface

Do not invent a new interface. Use the existing CLI:

- `init`
- `write`
- `start`
- `status`
- `continue`
- `reopen`

For document authoring, prefer editing the canonical files directly with your normal file tools when you already have them. Treat `write --body` as a convenience fallback, not the primary path for a capable outer agent.

Use [`references/run-lifecycle.md`](./references/run-lifecycle.md) for command recipes and continuation policy, including when an approved run should be reopened instead of continued.

When using `start`, `continue`, or `reopen`, also read [`references/supervisor-lifetime.md`](./references/supervisor-lifetime.md).

## Document rules

- `task.md` is the default brief for most execution requests.
- `review.md` is for findings-shaped input such as comments, logs, repro notes, or debugging handoff.
- `spec.md` is only for work that needs deeper structure than a short task brief.
- `contract.md` is the default acceptance and approval checklist for most non-trivial runs.
- Task-local `AGENTS.md` stays behavioral and stable; do not put task-specific requirements there.
- `github_pr_codex` special case: when the user already has a PR and wants GitHub Codex to review the live branch, local `task.md` / `review.md` / `spec.md` may be omitted if the PR and current-head review findings already form a usable brief.
- `branch_northstar_summary.md` is optional supporting context for branch/worktree intent in that PR-driven mode.

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
- an approved run may need `reopen` because it was false-approved or the canonical docs changed after approval
- a human paused the run and edited task docs

Use [`references/operator-boundary.md`](./references/operator-boundary.md) if you feel tempted to “just do the feature directly” instead of operating the harness.

## Worked examples

Before handling unfamiliar requests, read:

- [`references/user-sophistication-examples.md`](./references/user-sophistication-examples.md)
- [`references/task-type-examples.md`](./references/task-type-examples.md)
