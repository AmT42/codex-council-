# Supervisor Lifetime

## Core rule

`start` and `continue` launch a live supervisor process.

That process must remain alive while the council is advancing turns.

## Why this matters

The generator and reviewer run inside separate `tmux` sessions, but the supervisor is what:

- watches for artifacts
- validates them
- decides the next role
- sends the next prompt

If the supervisor dies:

- already-running role sessions may keep going
- but orchestration stops

## Safe patterns

- wait for the `start` or `continue` command
- run it inside a dedicated terminal that stays open
- run it inside a dedicated `tmux` session
- run it as a truly detached background job

## Unsafe pattern

- launch `python3 ... codex_tui_supervisor.py start ...` from an outer-agent shell
- let that outer-agent shell get interrupted or exit

That can leave the run stale:

- generator may finish
- reviewer may never launch
- `state.json` may still look stale

## Recovery

If you suspect this happened:

1. run `status`
2. inspect `derived_continuation`
3. run `continue` if the next role is now derivable from the artifacts
4. keep the new supervisor process alive this time
