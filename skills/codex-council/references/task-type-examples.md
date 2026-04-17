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
- commands: `init` if needed, fill the docs directly, then `start`
- do not implement the bugfix directly outside the council

## Findings-driven fix

User:

> Address these PR review comments.

Route:

- mode: findings-driven fix
- docs: `review.md` + `contract.md`
- optional: add `task.md` only if a short brief would clarify the requested outcome
- commands: `init` if needed, fill the docs directly, then `start`

## Broad feature work

User:

> Implement feature X.

Route:

- mode: broad feature or spec work
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only the minimum blocking questions needed to make the spec executable
- commands: `init` if needed, fill the docs directly, then `start`
- do not add harness-side glue unless the user explicitly asked for a harness feature
- spec bar: decision-complete for the relevant runtime/state/fallback/integrity dimensions, not just a high-level design sketch

## Broad feature with risky adjacent helper path

User:

> Add a memory system so the agent can remember something when I ask it directly.

Route:

- mode: broad feature or spec work
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only if repo inspection cannot determine the main user-facing workflow
- commands: `init` if needed, fill the docs directly, then `start`
- spec bar:
  - define the primary user-facing “remember/store this now” path
  - define any maintenance/background/curation paths
  - state forbidden substitutions so the generator does not implement only a helper path and call the feature done
- review bar:
  - reviewer must check the obvious user interaction directly, not only internals or passing tests

## Resume

User:

> Resume the paused council run.

Route:

- mode: inspect or resume an existing run
- commands: `status`, then `continue` if the run is still the right one

## Reopen an approved run

User:

> The run was approved, but that approval was wrong after we reviewed the fallback logic.

Route:

- mode: inspect or resume an existing run
- commands: `status`, then `reopen`
- reason kind: `false_approved`
- process rule: preserve the historical approval and create a fresh linked run instead of forcing `continue`

## Example: stale run after supervisor death

User:

> The generator finished in tmux but the reviewer never started.

Route:

- mode: inspect or resume an existing run
- commands: `status`, inspect `derived_continuation`, then `continue`
- process rule: keep the `continue` supervisor alive this time
