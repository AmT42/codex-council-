# Codex Council

This repo contains local supervisors for a sequential generator/reviewer Codex council.

## Template-Driven Layout

The council scaffold and turn-prompt text is stored in repo templates, not embedded directly in Python:

```text
templates/
  scaffold/
    council_root.gitignore
    config.toml
    task.md
    review.md
    spec.md
    contract.md
    AGENTS.md
    generator.instructions.md
    reviewer.instructions.md
  prompts/
    generator_initial.md
    generator_followup.md
    reviewer_initial.md
    reviewer_followup.md
    reviewer_fork_bootstrap.md
  data/
    critical_review_dimensions.json
```

Meaning:
- `templates/scaffold/*` are copied during `init`
- `templates/prompts/*` are rendered into per-turn role prompt artifacts such as `turns/0001/generator/prompt.md`
- `templates/data/critical_review_dimensions.json` is the source of truth for reviewer critical-dimension keys and labels

## Document Model

This repo now uses a single progressive model based on local task documents:

- `task.md`
  - default brief for bugs, tickets, and short requests
- `review.md`
  - findings input for debugging, review-fix loops, or external comments
- `spec.md`
  - detailed design doc when `task.md` is not enough
- `contract.md`
  - optional definition of done / stop condition
- `AGENTS.md`
  - stable council behavior only

This separation matters:
- `task.md` tells the council what to do in short form
- `review.md` tells the council what findings to address
- `spec.md` expands the task into a structured design when needed
- `contract.md` defines when approval is justified
- `AGENTS.md` defines how the agents should behave

### Glossary

- `task`
  - A short request, bug, or ticket description
- `review`
  - A set of findings or blockers to evaluate and fix
- `spec`
  - A detailed design layered on top of `task.md`
- `definition of done`
  - The auditable checklist that must be true before approval
- `council brief`
  - Stable operating rules for generator and reviewer
- `blocking issue`
  - A concrete problem that prevents approval
- `needs_human`
  - A stop state used when the task documents are too ambiguous, contradictory, or non-auditable to continue safely

### Writing Guide

You do not need advanced technical vocabulary to use this system well.

Use:
- `task.md` for most work by default
- `review.md` when you start from findings, debugging notes, or review comments
- `spec.md` only when the task needs deeper structure than `task.md`
- `contract.md` only when you need an objective approval bar

Good `task.md` writing:
- describe the bug or request concretely
- include just enough context to act safely
- say what success looks like

Good `review.md` writing:
- list concrete findings or blockers
- include logs, repro steps, or code references when useful
- avoid mixing unrelated issues into one bullet

Good `contract.md` writing:
- checklist items that can be verified by reading code, running tests, or observing behavior

Bad `contract.md` writing:
- `production-ready`
- `enterprise-grade`
- `viral`
- `best-in-class`

Those phrases are acceptable only after they are decomposed into measurable engineering conditions.

## Real TUI Mode

The TUI supervisor now works against a target repository and stores its task workspace inside that repository.

Primary usage:

```bash
cd /path/to/target-repo
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task
```

Or, from anywhere:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task \
  --dir /path/to/target-repo
```

`init` scaffolds:

```text
/path/to/target-repo/.codex-council/config.toml
/path/to/target-repo/.codex-council/.gitignore
/path/to/target-repo/.codex-council/my-task/AGENTS.md
/path/to/target-repo/.codex-council/my-task/generator.instructions.md
/path/to/target-repo/.codex-council/my-task/reviewer.instructions.md
```

If you already know the brief, you can seed `task.md` during init:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task \
  --dir /path/to/target-repo \
  --task "Implement feature X"
```

Then add whichever input documents you need:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task \
  --dir /path/to/target-repo \
  --body "Fix the bug in ..."
```

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write review my-task \
  --dir /path/to/target-repo \
  --body "The fallback path keeps returning partial state."
```

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write spec my-task \
  --dir /path/to/target-repo \
  --body "Implement a memory subsystem inspired by repo A and repo B."
```

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task \
  --dir /path/to/target-repo \
  --body "Full answer is always captured before the send button becomes active."
```

`start` chooses the first role automatically:
- `review.md` present => starts with `generator`
- `task.md` present => starts with `generator`
- fork with no local docs => starts with a reviewer bootstrap that materializes `review.md`, then continues with `generator`

You can override that rarely with `--start-role`.

Simple fork start for both roles from the same parent session:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --fork-session-id <parent_session_id>
```

Advanced per-role fork override:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --generator-fork-session-id <generator_parent_session_id> \
  --reviewer-fork-session-id <reviewer_parent_session_id>
```

Every execution creates a fresh run under:

```text
.codex-council/<task_name>/runs/<run_id>/
```

Each turn is role-scoped, for example:

```text
.codex-council/<task_name>/runs/<run_id>/turns/0002/turn.json
.codex-council/<task_name>/runs/<run_id>/turns/0002/context_manifest.json
.codex-council/<task_name>/runs/<run_id>/turns/0002/generator/prompt.md
.codex-council/<task_name>/runs/<run_id>/turns/0002/generator/message.md
.codex-council/<task_name>/runs/<run_id>/turns/0002/generator/status.json
.codex-council/<task_name>/runs/<run_id>/turns/0002/reviewer/prompt.md
.codex-council/<task_name>/runs/<run_id>/turns/0002/reviewer/message.md
.codex-council/<task_name>/runs/<run_id>/turns/0002/reviewer/status.json
```

The supervisor will:

- resolve the target directory to its git root by default
- refuse to start on a detached HEAD
- refuse to start on a dirty repo except during the fork bootstrap path
- launch two real `codex` TUIs in `tmux` inside that target repo
- build short path-based prompts from the available task documents
- bootstrap a local `review.md` when a fork start has no local `task.md`, `review.md`, or `spec.md`
- store per-turn canonical file hashes and metadata in `context_manifest.json`
- advance turns only when the required role artifact pair exists and validates
- automatically request one artifact rewrite if a role writes invalid status JSON
- pause when generator or reviewer emits `needs_human`
- stop when reviewer writes `{"verdict":"approved",...}`, `{"verdict":"blocked",...}`, or max turns is reached

Attach from two terminals with the commands printed by `start`, for example:

```bash
tmux attach -t codex-generator-my-task-<run_id>
tmux attach -t codex-reviewer-my-task-<run_id>
```

Important:

- watch the sessions, but do not type into them unless you intentionally want to override the council
- the authoritative control signal is only the artifact pair for the role
- `task.md` is the default brief
- `review.md` is the canonical findings input
- `spec.md` is the detailed design doc layered on top of `task.md`
- `contract.md` is the optional definition of done
- when `review.md` is present, generator must classify review points as `agree` / `disagree` / `uncertain` before coding
- reviewer must adjudicate generator disagreements with evidence and must not restate the same blocker without stronger evidence
- `AGENTS.md` is the canonical council brief
- `start` validates whichever of `task.md`, `review.md`, `spec.md`, and `contract.md` are present
- `spec.md` requires `task.md`
- `contract.md` requires at least `task.md` or `review.md`
- approval means all critical review dimensions pass, and also the contract checklist passes when `contract.md` exists
- generator must write `generator/message.md` and `generator/status.json`
- reviewer must write `reviewer/message.md` and `reviewer/status.json`
- `raw_final_output.md` is trace-only and now captures only an explicit terminal summary block, not the full pasted prompt or tool trace
- either role may emit `needs_human` when the task documents are flawed enough that continuing would be unsafe or misleading
- a reviewer should use `needs_human`, not `changes_requested`, when the remaining blocker is that the task documents themselves are too broad or non-auditable
- a generator should use `needs_human`, not `blocked`, when the remaining blocker is document ambiguity rather than an external implementation blocker

Reviewer stop conditions are structured, not guessed from prose:

```json
{"verdict":"approved","summary":"No blocking issues remain.","blocking_issues":[],"critical_dimensions":{"correctness_vs_intent":"pass","regression_risk":"pass","failure_mode_and_fallback":"pass","state_and_metadata_integrity":"pass","test_adequacy":"pass","maintainability":"pass"}}
```

Reviewer fix-loop example:

```json
{"verdict":"changes_requested","summary":"One blocker remains.","blocking_issues":["Fix the fallback path."],"critical_dimensions":{"correctness_vs_intent":"fail","regression_risk":"pass","failure_mode_and_fallback":"pass","state_and_metadata_integrity":"uncertain","test_adequacy":"fail","maintainability":"pass"}}
```

Human-intervention pause example:

```json
{"verdict":"needs_human","summary":"The plan is contradictory.","blocking_issues":[],"critical_dimensions":{"correctness_vs_intent":"uncertain","regression_risk":"uncertain","failure_mode_and_fallback":"uncertain","state_and_metadata_integrity":"uncertain","test_adequacy":"uncertain","maintainability":"uncertain"},"human_message":"Clarify whether the API change should be breaking or backward compatible.","human_source":"contract.md"}
```

Generator implemented example:

```json
{"result":"implemented","summary":"Implemented the requested change.","changed_files":["src/example.py"]}
```

Inspect the latest run state:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task \
  --dir /path/to/target-repo
```

Or a specific run:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task \
  --dir /path/to/target-repo \
  --run-id 20260408-123456-abcdef
```

Continue a stopped or paused run in place:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task \
  --dir /path/to/target-repo
```

`continue` reuses the existing run directory instead of creating a new run. It is artifact-driven:
- missing or invalid generator artifacts: continue generator on the same turn
- valid generator artifacts but missing or invalid reviewer artifacts: continue reviewer on the same turn
- reviewer `changes_requested`: continue generator on turn `N+1`
- generator or reviewer `needs_human`: continue the same role on turn `N+1`
- reviewer `approved`: cannot continue

When the original tmux session still exists, `continue` keeps using that same live role session so direct human chat in the terminal is preserved. If the tmux session is gone, the harness prefers resuming the same Codex conversation when it has a tracked session id; otherwise it starts a fresh role session with a continuation prompt.

This is the intended path after you edit `task.md`, `review.md`, `spec.md`, `contract.md`, `AGENTS.md`, or role instructions, or after you discuss changes directly in the live Codex session and want the council to proceed.

Generated runtime state and traces live under the task run tree and are ignored by `.codex-council/.gitignore`.

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
