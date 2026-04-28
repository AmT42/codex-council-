# Examples

## Example: direct answer only

User:

> How does this harness work?

Route:

- request class: direct answer only
- docs: none
- commands: none

## Example: concrete debug request

User:

> Debug why sync duplicates rows.

Route:

- request class: concrete execution request
- execution review source: Normal Internal Council
- docs: `task.md` + `contract.md`
- questions: none unless repo inspection reveals multiple plausible sync paths
- commands: `init` if needed, fill the docs directly, then `start`

## Example: pasted findings-driven fix

User:

> Address these pasted review comments.

Route:

- request class: findings-driven fix
- execution review source: Normal Internal Council
- docs: `review.md` + `contract.md`
- optional: add `task.md` only if a short brief would clarify the requested outcome
- commands: `init` if needed, fill the docs directly, then `start`

## Example: live PR bridge

User:

> Use Codex Council on PR #123 and keep working until Codex stops reporting major issues.

Route:

- PR preflight: yes
- execution review source: GitHub PR Codex Bridge
- docs: none by default; optional `branch_northstar_summary.md` only if branch intent is unclear
- commands: `init` if needed, then `start --review-mode github_pr_codex --github-pr <pr-url>`
- note: do not copy PR findings into `review.md` unless the user explicitly asks for the internal generator/reviewer execution loop

## Example: broad feature work

User:

> Implement feature X.

Route:

- request class: broad feature or spec work
- preparation lane: Planning Preparation with planner + intent critic before execution docs are locked
- execution review source: Normal Internal Council after planning approval
- docs: `task.md` + `spec.md` + `contract.md`
- questions: only the minimum blocking questions needed to make the spec executable
- commands: `init` if needed, run the planning stage, lock the docs, then `start`
- note: use planning-stage `hard` mode when the work is agentic, prompt-sensitive, or otherwise unusually rigorous

## Example: resume

User:

> Resume the paused council run.

Route:

- request class: inspect or resume an existing run
- commands: `status`, then `continue` if the run is still the right one

## Example: stale run after supervisor death

User:

> The generator finished in tmux but the reviewer never started.

Route:

- request class: inspect or resume an existing run
- commands: `status`, inspect `derived_continuation`, then `continue`
- process rule: keep the `continue` supervisor alive this time

## Example: explain without scaffolding

User:

> What is `contract.md` for?

Route:

- request class: direct answer only
- docs: none
- commands: none
