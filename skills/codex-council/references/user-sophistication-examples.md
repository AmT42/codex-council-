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
