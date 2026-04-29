# Operator Boundary

## Core rule

When the user asks you to **use this harness/repo/skill/script** for a task, you are acting as a harness operator, not as the direct implementer of the target feature.

## What you must do

- inspect the target repo
- choose the route before creating documents
- for live PR requests, use the GitHub PR Codex Bridge and omit local canonical docs by default
- for local Council work, create or update `task.md`, `review.md`, `spec.md`, and `contract.md` as needed
- choose between direct answer, `prepare`, `start`, `continue`, and `reopen`
- launch or resume the council

Live PR requests are not doc-authoring requests. A PR URL, PR number, PR review permalink, "this PR", "the pull request", or "work on this PR" routes through the GitHub PR Codex Bridge first. Do not run planner/critic, do not create `task.md`, `review.md`, `spec.md`, or `contract.md`, and do not translate PR comments into a local brief unless the user explicitly asks for the Normal Internal Council or a local Council brief.

## What you must not do

- directly implement the target-repo feature yourself instead of using the council
- add glue code to `council-agent` because the target task would otherwise need setup
- build wrapper apps, Finder integrations, desktop helpers, or native extensions unless the user explicitly asked for a feature in `council-agent` itself

## Decision test

Ask:

1. Did the user ask to use the harness as the tool?
2. Is the requested feature meant for the target repo rather than this harness repo?

If yes to both, your next action should be:

- route the request first
- use the GitHub PR Codex Bridge for live PRs
- prepare the local Council run only when the selected route needs canonical docs

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
- select the correct source of truth
- for local Council work, synthesize the right docs and write `task.md`, `spec.md`, and `contract.md` as needed
- for live PR work, skip local docs by default and use the PR plus current-head GitHub Codex findings
- call `init` / `write` / `prepare` / `start` or `status` / `continue` / `reopen`
