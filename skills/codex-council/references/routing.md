# Routing

## Rule 0: Live PR Preflight

Live PR preflight is exclusive and runs before every other rule.

If the user says "PR", "pull request", "this PR", "current PR", "work on this PR", gives a PR URL/number, gives a URL with `#pullrequestreview-<id>`, mentions `@codex`, or asks about GitHub/Codex PR review comments, route exclusively to the GitHub PR Codex Bridge.

For a live PR:

- use GitHub PR Codex Bridge only
- do not run Normal Internal Council
- do not run planner/critic
- do not create `task.md`, `review.md`, `spec.md`, or `contract.md`
- do not translate PR comments into a local brief
- do not start a local generator/reviewer loop
- if no current-head GitHub Codex review exists, request or wait for `@codex`; do not invent generator work
- if the URL contains `#pullrequestreview-<id>`, preserve that id as the target review and verify the consumed GitHub Codex review id matches before continuing

Only override this route when the user explicitly requests the Normal Internal Council, the internal generator/reviewer execution loop, planner/critic preparation, a local Council brief, or outer-review audit.

## Primary Rule

If live PR preflight did not match, choose a route by four independent axes before you write files or run commands.

The correct route determines:

- whether you answer directly
- whether you inspect an existing run first
- which canonical docs to write
- whether to use `prepare`, `start`, `continue`, or `reopen`
- whether review comes from the Normal Internal Council or the GitHub PR Codex Bridge

## Routing Axes

| Axis | Values |
| --- | --- |
| Request class | direct answer, inspect/resume, concrete execution, findings fix, broad/spec work |
| Preparation lane | none, Planning Preparation via `prepare` |
| Execution review source | Normal Internal Council, GitHub PR Codex Bridge |
| Post-approval audit add-on | none, Internal Council With Outer Audit |

Canonical runtime names:

- **Normal Internal Council**
  - local `generator` plus local `reviewer`
  - default `--review-mode internal`
- **GitHub PR Codex Bridge**
  - GitHub PR Codex is the review source
  - the PR and current-head GitHub Codex findings are the only brief by default
  - this is not the Normal Internal Council generator/reviewer loop
  - any local fixing step is a PR-findings worker step, not a new Council execution loop
  - selected on `start` with `--review-mode github_pr_codex`
- **Internal Council With Outer Audit**
  - Normal Internal Council plus `--outer-review-fork-session-id`
  - additive post-approval audit only; not a review mode and not compatible with `github_pr_codex`
- **Planning Preparation**
  - planner plus intent critic via `prepare`
  - preparation lane before execution, not an execution review source

## PR Preflight

Before applying the normal request classes, check whether the user named an existing GitHub PR by URL, PR number, or wording like:

- "this PR"
- "the pull request"
- "use Codex Council on PR #123"
- "work on PR #123"
- "continue this PR until Codex has no more major comments"

If yes, route exclusively to the GitHub PR Codex Bridge:

- start new PR runs with `--review-mode github_pr_codex`
- pass `--github-pr <url-or-number>` when known
- treat the PR plus current-head GitHub Codex findings as the effective brief
- if the current PR head has no Codex request or findings yet, the PR bridge should post `@codex` and wait before generator work begins
- do not create `task.md`, `review.md`, `spec.md`, or `contract.md` just to hold the PR URL or copy PR findings
- do not use the Normal Internal Council unless the user explicitly asks for the internal generator/reviewer execution loop
- add `branch_northstar_summary.md` only when branch intent needs durable local context

PR review permalink rule:

- if the user gives a URL with `#pullrequestreview-<id>`, preserve that id as the target review
- pass the base PR URL to `--github-pr` if the CLI requires it
- do not drop the fragment silently in the route summary, run artifacts, or operator notes
- before continuing implementation, verify the consumed GitHub Codex review id matches the target id

For existing PR-bridge runs, use `continue` without `--review-mode`; the review source is stored in the run state.

## Fast Route Table

| User request | Route | Command shape |
| --- | --- | --- |
| Existing PR / PR URL / PR review permalink / "this PR" | GitHub PR Codex Bridge | `start --review-mode github_pr_codex --github-pr ...` |
| Pasted review notes, no live PR | Normal Internal Council findings fix | `review.md` + `contract.md` + `start` |
| Concrete bug/feature, no PR | Normal Internal Council | `task.md` + `contract.md` + `start` |
| Broad/vague/agentic work | Planning Preparation first | `prepare`, then `start` |
| Internal run plus final audit | Internal Council With Outer Audit | `start --outer-review-fork-session-id ...` |

## Route 1: Direct Answer Only

Use when the user is asking about:

- how the harness works
- what a document means
- why a run paused
- what the current command surface is

Action:

- answer directly
- do not scaffold `.codex-council`
- do not run `prepare`, `start`, `continue`, or `reopen`

## Route 2: Inspect Or Resume An Existing Run

Use when the user is asking for:

- current run state
- continuation after a pause or stop
- next action after editing task documents

Action:

- inspect current workspace and run state first
- prefer `status`
- use `status --planning` for planning runs
- prefer `continue` when the existing execution run is still the right one
- prefer `prepare` when the existing planning run is still the right one
- prefer `reopen` when the selected run is already approved but must be superseded explicitly
- avoid overwriting docs unless the repo state clearly requires it
- if `status` shows a pause waiting for outer-review finalization, finalize canonical `review.md` and then use `continue`; do not create a new run for that step

Continuation selector:

| Current state | Next command |
| --- | --- |
| Planning run active or paused | `status --planning`, then `prepare` |
| Internal execution run active or paused | `status`, then `continue` |
| GitHub PR Codex Bridge run blocked/paused | `status`, then `continue` with no `--review-mode` |
| Approved run that is now wrong or obsolete | `reopen` |
| Outer-review finalization pause | finalize `review.md`, then `continue` |

## Route 3: Concrete Execution Request

Use when the user gives a specific change that can be acted on safely.

Examples:

- debug a bug
- fix a failing path
- implement a targeted change

Default docs:

- `task.md`
- `contract.md`

Question policy:

- ask nothing unless a missing detail would materially change the implementation target
- if the request is specifically about a live PR, PR preflight wins and routes to the GitHub PR Codex Bridge

## Route 4: Findings-Driven Fix

Use when the user provides:

- pasted review comments
- findings lists
- logs
- repro notes
- debugging evidence

Default docs:

- `review.md`
- `contract.md`

Optional:

- add `task.md` only when a short brief materially clarifies what the generator should do
- if the findings already live on an existing PR, PR preflight wins: use the GitHub PR Codex Bridge and omit local canonical docs by default
- add `branch_northstar_summary.md` when the branch/worktree intent needs durable context without promoting that context into `task.md`
- for Internal Council With Outer Audit, findings that invalidate an earlier approval should update canonical `review.md` and route through `reopen --reason-kind false_approved`, not through `continue`

## Route 5: Broad Feature Or Spec Work

Use when the request spans multiple surfaces or would be unsafe to execute from a short task brief alone.

Default docs:

- Planning Preparation first
- then `task.md`
- then `spec.md`
- then `contract.md`

Question policy:

- ask only the minimum blocking questions needed to make `spec.md` and `contract.md` executable

Planning-stage policy:

- broad/spec-driven work should default to planner + intent critic preparation before execution docs are treated as locked
- use `hard` mode when the work is agentic, prompt-sensitive, tool/schema-heavy, workflow-heavy, or otherwise unusually rigorous
- run `prepare` for that planning loop
- do not move to `start` until the planning-stage critic has approved the authored docs

## Route Summary Format

Before launch, summarize the route to the user in one short block:

- request class
- preparation lane
- execution review source
- post-approval audit add-on, if any
- docs being written
- whether questions were skipped or asked
- whether you are about to `prepare`, `start`, `continue`, or `reopen`

## Default Hierarchy

When several routes seem plausible:

1. Direct answer only if no harness action is needed
2. PR preflight if the request names or clearly refers to a live GitHub PR
3. Inspect or resume if a suitable run already exists
4. Findings-driven fix if the input is already review-shaped
5. Concrete execution request for specific implementation/debug work
6. Broad feature or spec work only when the work genuinely needs structured expansion, and then route it through Planning Preparation before execution
