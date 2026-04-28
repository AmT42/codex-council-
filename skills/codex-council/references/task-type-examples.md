# Task-Type Examples

## Direct answer only

User:

> How does this harness work?

Route:

- request class: direct answer only
- docs: none
- commands: none

## Concrete debug request

User:

> Debug why sync duplicates rows.

Route:

- request class: concrete execution request
- execution review source: Normal Internal Council
- docs: `task.md` + `contract.md`
- questions: none unless repo inspection reveals multiple plausible sync paths
- commands: `init` if needed, fill the docs directly, then `start`
- do not implement the bugfix directly outside the council

## Pasted findings-driven fix

User:

> Address these pasted review comments.

Route:

- request class: findings-driven fix
- execution review source: Normal Internal Council
- docs: `review.md` + `contract.md`
- optional: add `task.md` only if a short brief would clarify the requested outcome
- commands: `init` if needed, fill the docs directly, then `start`

## Existing PR bridge

User:

> Use Codex Council on PR #123 and keep working until Codex stops reporting major issues.

Route:

- PR preflight: yes
- execution review source: GitHub PR Codex Bridge
- docs: PR and current-head GitHub Codex review findings are the effective brief; add `branch_northstar_summary.md` only if branch intent needs durable local context
- commands: `init` if needed, then `start --review-mode github_pr_codex --github-pr <pr-url>`
- do not default to the Normal Internal Council unless the user explicitly asks for the internal generator/reviewer execution loop

## Existing PR but Normal Internal Council requested

User:

> Use the internal generator/reviewer loop for PR #123 instead of GitHub Codex review.

Route:

- PR preflight: overridden explicitly
- execution review source: Normal Internal Council
- docs: materialize the relevant PR findings into `review.md` + `contract.md`
- commands: `init` if needed, fill the docs directly, then `start` without `--review-mode github_pr_codex`

## Broad feature work

User:

> Implement feature X.

Route:

- request class: broad feature or spec work
- preparation lane: Planning Preparation with planner + intent critic before execution docs are locked
- execution review source: Normal Internal Council after planning approval
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only the minimum blocking questions needed to make the spec executable
- commands: `init` if needed, run the planning stage, then `start`
- do not add harness-side glue unless the user explicitly asked for a harness feature
- spec bar: decision-complete for the relevant runtime/state/fallback/integrity dimensions, not just a high-level design sketch
- hard-mode note: for agentic, prompt-sensitive, tool/schema-heavy, or operationally risky work, use planning-stage `hard` mode

## Broad feature with risky adjacent helper path

User:

> Add a memory system so the agent can remember something when I ask it directly.

Route:

- request class: broad feature or spec work
- preparation lane: Planning Preparation with planner + intent critic before execution docs are locked
- execution review source: Normal Internal Council after planning approval
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only if repo inspection cannot determine the main user-facing workflow
- commands: `init` if needed, run the planning stage, then `start`
- spec bar:
  - define the primary user-facing “remember/store this now” path
  - define any maintenance/background/curation paths
  - state forbidden substitutions so the generator does not implement only a helper path and call the feature done
- planning bar:
  - intent critic rejects toy-like prompt/tool/schema descriptions
  - if the planner cannot make the policy explicit, stop with `needs_human`
- review bar:
  - reviewer must check the obvious user interaction directly, not only internals or passing tests

## Resume

User:

> Resume the paused council run.

Route:

- request class: inspect or resume an existing run
- commands: `status`, then `continue` if the run is still the right one

## Reopen an approved run

User:

> The run was approved, but that approval was wrong after we reviewed the fallback logic.

Route:

- request class: inspect or resume an existing run
- commands: `status`, then `reopen`
- reason kind: `false_approved`
- process rule: preserve the historical approval and create a fresh linked run instead of forcing `continue`

## Internal Council With Outer Audit

User:

> Run the internal council, then have the outer audit agent check the approval before we trust it.

Route:

- request class: same as the underlying task
- execution review source: Normal Internal Council
- post-approval audit add-on: Internal Council With Outer Audit
- commands: `start --outer-review-fork-session-id <parent_session_id>`
- compatibility: never combine this add-on with `--review-mode github_pr_codex`

## Outer-audit false-approved re-entry

User:

> The outer audit found a blocker after the internal reviewer approved.

Route:

- request class: inspect or resume an existing run
- post-approval audit add-on: Internal Council With Outer Audit
- docs: update canonical `review.md` with the surviving blocker
- commands: `reopen --reason-kind false_approved`, then after triage/finalization use `continue`

## Example: stale run after supervisor death

User:

> The generator finished in tmux but the reviewer never started.

Route:

- request class: inspect or resume an existing run
- commands: `status`, inspect `derived_continuation`, then `continue`
- process rule: keep the `continue` supervisor alive this time
