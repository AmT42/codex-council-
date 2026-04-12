# Run Lifecycle

## Preferred command surface

Use the existing CLI:

- `init`
- `write`
- `start`
- `status`
- `continue`

Do not invent parallel wrapper commands in the outer-agent workflow.

## Create or reuse a workspace

If the task workspace does not exist:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task --dir /path/to/target-repo
```

If it already exists:

- inspect the existing docs and runs first
- avoid reinitializing unless the user clearly wants a new task

## Write only the needed docs

Examples:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write review my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write spec my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --dir /path/to/target-repo --body "..."
```

Write the smallest sufficient document set, not every doc by reflex.

## Start

Use `start` after the chosen docs are ready:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

Before `start`, ensure the docs are strong enough to survive runtime validation.

Default to the current auto role routing.

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

## Safety notes

- Expect `start` to reject a dirty target repo in the normal path.
- If the request is direct-answer-only, do not call any lifecycle command.
- If the existing run is healthy and suitable, prefer continuing it instead of overwriting the workspace.
- If the docs are too weak, improve the docs before launch instead of hoping the council compensates for them.
