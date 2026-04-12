# Task-Type Examples

## Direct answer only

User:

> How does this harness work?

Route:

- mode: direct answer only
- docs: none
- commands: none

## Concrete debug request

User:

> Debug why sync duplicates rows.

Route:

- mode: concrete execution request
- docs: `task.md` + `contract.md`
- questions: none unless repo inspection reveals multiple plausible sync paths
- commands: `init` if needed, then `write`, then `start`

## Findings-driven fix

User:

> Address these PR review comments.

Route:

- mode: findings-driven fix
- docs: `review.md` + `contract.md`
- optional: add `task.md` only if a short brief would clarify the requested outcome
- commands: `init` if needed, then `write`, then `start`

## Broad feature work

User:

> Implement feature X.

Route:

- mode: broad feature or spec work
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only the minimum blocking questions needed to make the spec executable
- commands: `init` if needed, then `write`, then `start`

## Resume

User:

> Resume the paused council run.

Route:

- mode: inspect or resume an existing run
- commands: `status`, then `continue` if the run is still the right one
