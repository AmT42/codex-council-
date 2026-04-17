# User Sophistication Examples

## Expert user

User:

> Fix the fallback path in the sync worker so retries no longer duplicate rows.

Behavior:

- no clarifying questions unless repo inspection reveals multiple plausible sync flows
- write `task.md`
- write `contract.md`
- launch quickly

## Intermediate user

User:

> The sync feature is buggy and sometimes duplicates rows after retries.

Behavior:

- inspect the repo for likely sync paths
- strengthen the request into concrete `task.md`
- make success auditable in `contract.md`
- only ask a blocking question if several plausible flows exist

## Novice user

User:

> My import thing is broken. It does weird stuff. Can you make it solid?

Behavior:

- do not pass the wording through unchanged
- infer likely import surfaces from the repo
- rewrite the problem concretely
- decide whether a short task brief is enough or whether the work needs `spec.md`
- add `contract.md`
- launch only when the brief is strong

## Broad/spec-driven user

User:

> Add a new memory and recall system for long-running agents.

Behavior:

- write `task.md`, `spec.md`, and `contract.md`
- do not stop at the feature headline
- decide the relevant source-of-truth, read/write flow, fallback, runtime, integrity, and validation policy in `spec.md`
- if one of those dimensions is still open and would materially change implementation, ask a blocking question or stop instead of launching

## User-intent preservation example

User:

> Make the system remember this fact when I ask it to.

Behavior:

- do not stop at “memory architecture”
- identify the primary user-facing intent:
  - a normal foreground “remember/store this now” path
- identify any nearby maintenance/curation/background paths:
  - periodic promotion
  - pre-compaction flush
  - repair jobs
- make the spec say which path must satisfy the request
- make the spec say which nearby paths are supporting only and must not silently substitute for the main interaction
