# Codex Handoff

This repo contains a small coordinator for a sequential Codex generator/reviewer loop.

## Real TUI Mode

If you want two actual `codex` TUIs that you can watch in separate terminals, use the tmux-based supervisor:

```bash
python3 scripts/codex_tui_supervisor.py start \
  --task-file /absolute/path/to/task.md \
  --generator-prompt-file prompts/generator.txt \
  --reviewer-prompt-file prompts/reviewer.txt
```

The supervisor will:

- create a run folder under `harness/runs/<run_id>/`
- launch two real `codex --no-alt-screen` sessions in tmux and wait until both are ready for input
- send the first real task to generator as the generator's first prompt
- keep reviewer idle until there is generator output to review
- send turn prompts sequentially
- advance turns from filesystem artifacts, not from Codex internal session events
- stop when reviewer writes `{"verdict":"approved",...}`, `{"verdict":"blocked",...}`, or max turns is reached

Attach from two terminals with the commands printed by `start`, for example:

```bash
tmux attach -t codex-generator-<run_id>
tmux attach -t codex-reviewer-<run_id>
```

Important:

- watch the sessions, but do not type into them unless you intentionally want to override the supervisor
- both `tmux attach` targets should exist immediately after `start` prints them
- the structured turn artifacts are written under `harness/runs/<run_id>/turns/0001/`, `0002/`, and so on
- generator must write `generator.md` and `generator.status.json`
- reviewer must write `reviewer.md` and `reviewer.status.json`
- the supervisor tracks real TUI sessions from `~/.codex/sessions/...`, not from `~/.codex/session_index.jsonl`
- there is no separate "ready and wait" bootstrap turn anymore
- the actual go/no-go signal is the artifact pair for the role: once both files exist and the status JSON validates, the supervisor moves on
- for traceability, the supervisor also captures the last tmux slice into `turns/<turn>/<role>/raw_final_output.md`

Reviewer stop conditions are structured, not guessed from prose:

```json
{"verdict":"approved","summary":"No blocking issues remain.","blocking_issues":[]}
```

You can inspect the run state with:

```bash
python3 scripts/codex_tui_supervisor.py status <run_id>
```

If bootstrap or a turn times out, the supervisor keeps the tmux sessions alive and writes diagnostics under:

```text
harness/runs/<run_id>/diagnostics/
```

## Headless Mode

It does not try to make two interactive `codex` TUIs talk to each other. That path is brittle.
Instead, it keeps two persisted Codex threads and resumes them by explicit `thread_id`.

## Why this works

- `codex exec --json ...` emits a stable `thread_id`
- `codex exec resume --json <thread_id> ...` resumes that exact thread
- the coordinator uses a global lock, so only one Codex turn runs at a time even if both worker terminals are open

## Setup

The repo includes starter prompt files:

```text
[prompts/generator.txt]
[prompts/reviewer.txt]
```

Initialize the handoff state:

```bash
python3 scripts/codex_handoff.py init \
  --generator-prompt-file prompts/generator.txt \
  --reviewer-prompt-file prompts/reviewer.txt \
  --full-auto
```

Running `init` on an existing state directory resets the saved agent threads, queues, and logs for that state directory.
By default, the coordinator stops handing off when a reply looks terminal, for example `No changes...` or `No new findings...`. It also caps each agent at 12 turns per run. Override that only if you really want open-ended loops:

```bash
python3 scripts/codex_handoff.py init \
  --generator-prompt-file prompts/generator.txt \
  --reviewer-prompt-file prompts/reviewer.txt \
  --full-auto \
  --allow-terminal-handoff \
  --max-turns-per-agent 30
```

## Run

Terminal 1:

```bash
python3 scripts/codex_handoff.py run generator
```

Terminal 2:

```bash
python3 scripts/codex_handoff.py run reviewer
```

These worker commands do not launch the ncurses Codex TUI. They stream the Codex session commentary and tool activity live while keeping the run automatable.

Queue the first task for the generator:

```bash
python3 scripts/codex_handoff.py enqueue generator \
  --body "Implement the feature described in docs/spec.md"
```

From there:

- generator processes the task
- generator automatically queues a review message for reviewer
- reviewer processes that message
- reviewer automatically queues feedback back to generator

The loop continues until it reaches a terminal reply, hits the turn cap, or you stop the workers.

## Notes

- Use explicit `thread_id` resume, not `--last`. `--last` is not safe for automation.
- Logs are written under `.codex-handoff/logs/`.
- Status is available with:

```bash
python3 scripts/codex_handoff.py status
```

- If you want custom handoff text, pass `--to-reviewer-template-file` and `--to-generator-template-file` during `init`. Each template must contain `{message}`.
- If you already have a stuck queue from an older version, run `init` again to reset `.codex-handoff/`.

## Snake Smoke Test

`scripts/snake_game.py` uses `curses`, so the automated tests cover game logic and fake-screen rendering only.
When changing terminal rendering or input handling, run a quick real-TTY smoke test:

```bash
python3 scripts/snake_game.py --width 24 --height 16
```

Check startup, pause/resume, restart, quit, and terminal resize behavior in an actual terminal.

To try the 3D variant, run:

```bash
python3 scripts/snake_game_3d.py --width 14 --height 10 --depth 6
```

Use WASD or arrow keys for planar movement, `U`/`O` for depth movement, and `P`/`R`/`Q` for pause, restart, and quit.
