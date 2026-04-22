# Run Lifecycle

## Preferred command surface

Use the existing CLI:

- `init`
- `write`
- `prepare`
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

## Prepare

Use `prepare` for broad, vague, novice-described, or agentic work before execution:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py prepare my-task --dir /path/to/target-repo --intent "..."
```

Useful flags:

- `--intent`
- `--intent-file`
- `--hard`
- `--new-run`
- `--run-id`

Resume or inspect planning later:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo --planning
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py prepare my-task --dir /path/to/target-repo
```

Planning approval is the preferred way to lock execution inputs for broad work, but `start` still validates the current canonical docs directly and does not require an approved planning run.

If the latest planning run is already approved and canonical docs are unchanged, `prepare` may exit immediately and report that the docs are already prepared for execution. Use `--new-run` or new `--intent` when you want a fresh planning pass.

## Start

Use `start` after the chosen docs are ready:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

Optional internal outer-review layer:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --outer-review-session-id <codex_session_id>
```

Rules:

- the identifier is a resumable Codex session id
- this layer is internal-review-mode-only for the first implementation
- do not pass `--outer-review-session-id` when using `--review-mode github_pr_codex`

Before `start`, ensure the docs are strong enough to survive runtime validation.

If planning runs already exist for the task, treat them as advisory context. `start` should validate the current canonical docs directly instead of requiring the latest planning run to be approved or unchanged.

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

Inspect planning instead:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo --planning
```

Use `status` whenever you are unsure whether to resume, rewrite docs, or create a new run.

## Continue

Prefer `continue` over a new run when:

- the latest run already matches the intended task
- the run paused for `needs_human`
- the reviewer returned `changes_requested`
- the human edited task docs and wants the same run to proceed
- the run is blocked in the `github_pr_codex` reviewer bridge and should resume the same reviewer turn
- the run is paused for outer-review finalization and the outer agent already finalized canonical `review.md`

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task --dir /path/to/target-repo
```

Process rule:

- `continue` is also a live supervisor process
- it needs the same lifetime guarantees as `start`
- if you will not wait in the foreground, prefer running the `continue` command inside a dedicated `tmux` session

Approved runs are terminal for `continue`.

Internal outer-review special case:

- after the first triage-only generator turn on an outer-review `false_approved` reopen, the run pauses for outer finalization through canonical `review.md`
- run `continue` after that finalization step even if `review.md` stayed unchanged; the harness must still write `outer_review_finalization_ack.*`
- if no points remain, `continue` closes the run as `closed_no_remaining_outer_findings`
- if points remain, `continue` writes the acknowledgment artifact first and only then resumes a fresh normal generator/reviewer cycle

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

Exact internal outer-review loop:

- approved internal run with configured outer review writes `outer_review_handoff.*`
- outer agent re-verifies the whole task against intended behavior and current branch state
- if blockers remain under unchanged requirements, update canonical `review.md` and use `reopen --reason-kind false_approved`
- only that precise false-approved reopen of an internally approved run with a prior handoff enters the explicit outer-review path
- the first generator turn of that reopen is triage-only
- after triage, the outer agent finalizes the surviving review through canonical `review.md` and then uses `continue`
- `reopen --outer-review-session-id <codex_session_id>` overrides the inherited internal outer-review session id for the new run
- `reopen --clear-outer-review-session-id` disables inherited internal outer review for the new run

## Safety notes

- Expect `start` to reject a dirty target repo in the normal path.
- If the request is direct-answer-only, do not call any lifecycle command.
- If the existing run is healthy and suitable, prefer continuing it instead of overwriting the workspace.
- If the existing run is already approved but wrong or outdated, prefer `reopen` over mutating that run or forcing `continue`.
- If the docs are too weak, improve the docs before launch instead of hoping the council compensates for them.
- If the supervisor dies, the role sessions may survive but the council will not keep advancing until `continue` is run.
