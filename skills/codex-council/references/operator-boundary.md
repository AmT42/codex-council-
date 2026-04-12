# Operator Boundary

## Core rule

When the user asks you to **use this harness/repo/skill/script** for a task, you are acting as a harness operator, not as the direct implementer of the target feature.

## What you must do

- inspect the target repo
- create or update `task.md`, `review.md`, `spec.md`, and `contract.md` as needed
- choose between direct answer, `start`, and `continue`
- launch or resume the council

## What you must not do

- directly implement the target-repo feature yourself instead of using the council
- add glue code to `council-agent` because the target task would otherwise need setup
- build wrapper apps, Finder integrations, desktop helpers, or native extensions unless the user explicitly asked for a feature in `council-agent` itself

## Decision test

Ask:

1. Did the user ask to use the harness as the tool?
2. Is the requested feature meant for the target repo rather than this harness repo?

If yes to both, your next action should be:

- prepare the council run

not:

- implement the target feature directly

## Example of wrong behavior

User intent:

> Use this repo to add feature reopen to the target project.

Wrong response:

- build new harness-side glue
- create wrapper scripts or native integrations
- implement the target feature outside the council

Correct response:

- inspect the target repo
- synthesize the right docs
- write `task.md`, `spec.md`, and `contract.md` as needed
- call `init` / `write` / `start` or `status` / `continue`
