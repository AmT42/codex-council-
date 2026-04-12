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

Process rule:

- either wait for `start`
- or run it in a truly persistent environment
- never fire-and-forget from an outer-agent session that may exit

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

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task --dir /path/to/target-repo
```

Process rule:

- `continue` is also a live supervisor process
- it needs the same lifetime guarantees as `start`

Approved runs are terminal for `continue`.

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
