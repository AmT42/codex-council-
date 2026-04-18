# Supervisor Lifetime

## Core rule

`prepare`, `start`, `continue`, and `reopen` are supervisor-facing lifecycle commands.

When one of them actually launches or resumes a supervisor, that process must remain alive while the council is advancing turns.

`prepare` has one fast path:

- if the latest planning run is already approved and canonical docs are unchanged, it may exit immediately without launching planner or intent-critic sessions

This is not a special Codex-only background API requirement.

- a normal foreground command is enough if the launcher will stay attached and wait
- `tmux` is needed only when the launcher cannot reliably stay attached

## Why this matters

The generator/reviewer and planner/intent-critic roles run inside separate `tmux` sessions, but the supervisor is what:

- watches for artifacts
- validates them
- decides the next role
- sends the next prompt

If the supervisor dies:

- already-running role sessions may keep going
- but orchestration stops

## Safe patterns

- wait for the `prepare`, `start`, `continue`, or `reopen` command
- run it inside a dedicated terminal that stays open
- run it inside a dedicated `tmux` session
- run it as a truly detached background job

## Preferred default

- if the outer agent can stay attached, a normal foreground command is sufficient
- if the outer agent might continue doing other work or might exit, the preferred default is to launch the supervisor command inside a dedicated `tmux` session
- detached background jobs such as `nohup` are acceptable, but they are a fallback behind a dedicated `tmux` session because `tmux` keeps the lifetime and logs easier to inspect

Example:

```bash
tmux new-session -d -s council-supervisor 'python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo'
```

## Unsafe pattern

- launch `python3 ... codex_tui_supervisor.py start ...` from an outer-agent shell
- let that outer-agent shell get interrupted or exit

That can leave the run stale:

- generator may finish
- reviewer may never launch
- `state.json` may still look stale

## Recovery

If you suspect this happened:

1. run `status` or `status --planning`
2. inspect `derived_continuation`
3. run `continue` for execution runs, or `prepare` for planning runs, if the next role is now derivable from the artifacts
4. use `reopen` only when the selected execution run is already approved but must be superseded
5. keep the new supervisor process alive this time
