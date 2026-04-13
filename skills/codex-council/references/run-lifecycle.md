# Run Lifecycle

## Preferred command surface

Use the existing CLI:

- `init`
- `write`
- `start`
- `status`
- `continue`
- `reopen`

Do not invent parallel wrapper commands in the outer-agent workflow.

For canonical document authoring, a capable outer agent should usually edit the files directly rather than treating `write --body` as the primary API.

## Create or reuse a workspace

If the task workspace does not exist:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task --dir /path/to/target-repo
```

If it already exists:

- inspect the existing docs and runs first
- avoid reinitializing unless the user clearly wants a new task

## Fill only the needed docs

Preferred for outer agents:

- edit `task.md`, `review.md`, `spec.md`, and `contract.md` directly
- use your normal file-editing tools
- keep the smallest sufficient document set

## Optional CLI fallback

Examples:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write review my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write spec my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --dir /path/to/target-repo --body "..."
```

Treat these `write --body` examples as a fallback for manual use or simple automation.

## Start

Use `start` after the chosen docs are ready:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

Before `start`, ensure the docs are strong enough to survive runtime validation.

Default to the current auto role routing.

`github_pr_codex` special case:

- when the user already has a PR and wants GitHub Codex to review the live branch, `start` may proceed without local `task.md`, `review.md`, or `spec.md`
- in that mode, the PR plus current-head GitHub review findings act as the effective brief
- `branch_northstar_summary.md` is optional supporting context when the branch/worktree intent needs to be stated explicitly

Example:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --review-mode github_pr_codex \
  --github-pr https://github.com/acme/repo/pull/123
```

Process rule:

- either wait for `start`
- or run it in a truly persistent environment
- if you are an outer Codex agent and do not want to stay attached, prefer a dedicated `tmux` session for the supervisor command itself
- never fire-and-forget from an outer-agent session that may exit

Preferred persistent command example:

```bash
tmux new-session -d -s council-supervisor 'python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo'
```

## Status

Inspect before resuming or rewriting:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo
```

Use `status` whenever you are unsure whether to resume, rewrite docs, or create a new run.

## Continue

Prefer `continue` over a new run when:

- the latest run already matches the intended task
- the run paused for `needs_human`
- the reviewer returned `changes_requested`
- the human edited task docs and wants the same run to proceed
- the run is blocked in the `github_pr_codex` reviewer bridge and should resume the same reviewer turn

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task --dir /path/to/target-repo
```

Process rule:

- `continue` is also a live supervisor process
- it needs the same lifetime guarantees as `start`
- if you will not wait in the foreground, prefer running the `continue` command inside a dedicated `tmux` session

Approved runs are terminal for `continue`.

`github_pr_codex` special case:

- a blocked reviewer bridge should usually resume on the same turn
- if the latest pushed head has no matching `@codex` request, a correct resume path should post a fresh literal `@codex` rather than reusing an older request from a previous head

## Reopen

Use `reopen` only when the selected run is already approved and that approval must be superseded explicitly.

- `false_approved`
  - the earlier approval was wrong under the intended requirements at the time
- `requirements_changed_after_approval`
  - the canonical docs changed after approval and now supersede it

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py reopen my-task --dir /path/to/target-repo --run-id latest --reason-kind false_approved --reason "The earlier approval missed a blocking fallback bug."
```

`reopen` starts a fresh linked run from the current canonical docs, preserves the old approved run unchanged, and appends an audit entry under `.codex-council/reopen-events.jsonl`.

## Safety notes

- Expect `start` to reject a dirty target repo in the normal path.
- If the request is direct-answer-only, do not call any lifecycle command.
- If the existing run is healthy and suitable, prefer continuing it instead of overwriting the workspace.
- If the existing run is already approved but wrong or outdated, prefer `reopen` over mutating that run or forcing `continue`.
- If the docs are too weak, improve the docs before launch instead of hoping the council compensates for them.
- If the supervisor dies, the role sessions may survive but the council will not keep advancing until `continue` is run.
