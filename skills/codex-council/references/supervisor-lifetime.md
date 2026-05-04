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

## Launch sanity check

After any `prepare`, `start`, `continue`, or `reopen` that launches or resumes live sessions, do one quick operator check before moving on:

1. wait about 5 to 10 seconds
2. run `python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status <task> --dir <target-repo> --sessions` for execution runs, or add `--planning --sessions` for planning runs
3. inspect the expected role session if the run still looks like it is booting or no first artifact appears

Use the printed attach command, or capture the pane directly:

```bash
tmux capture-pane -p -t <role-tmux-session> | tail -80
```

If the pane shows a local Codex interstitial, treat it as operator setup rather than a council failure:

- update or install prompt
- login or auth prompt
- trust-this-directory prompt
- first-run setup prompt
- model/version selection prompt

Report the prompt clearly. Get explicit user approval before accepting updates, running install commands, authenticating, or trusting a directory. Once the normal Codex prompt is available, let the existing supervisor continue if it is still alive. If the supervisor already failed during boot, use `status` and then resume with `continue` for execution runs or `prepare` for planning runs.

If no council prompt was ever delivered to the role and no role artifacts were written, it is safe to kill and recreate only that blocked role session. Then inspect `status` and resume the existing execution run with `continue`, or inspect `status --planning` and resume the existing planning run with `prepare`. Do not rerun `start` or `reopen` just because Codex itself needed an update.

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
3. run `python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status <task> --dir <target-repo> --sessions`, or add `--planning --sessions`, and inspect any role session that failed to start
4. report local Codex interstitials before changing council docs or creating a new run; get explicit user approval before accepting updates, running installs, authenticating, or trusting a directory
5. run `continue` for execution runs, or `prepare` for planning runs, if the next role is now derivable from the artifacts
6. use `reopen` only when the selected execution run is already approved but must be superseded
7. keep the new supervisor process alive this time
