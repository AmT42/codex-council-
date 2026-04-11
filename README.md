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
    contract.md
    AGENTS.md
    AGENTS.inherited_context.md
    AGENTS.simple.md
    generator.instructions.md
    generator.instructions.inherited_context.md
    generator.instructions.simple.md
    reviewer.instructions.md
    reviewer.instructions.inherited_context.md
    reviewer.instructions.simple.md
    initial_review.md
  prompts/
    generator_turn_1.md
    generator_turn_n.md
    generator_inherited_turn_1.md
    generator_inherited_turn_n.md
    generator_simple_turn_1.md
    generator_simple_turn_n.md
    reviewer_turn_1.md
    reviewer_turn_n.md
    reviewer_inherited_turn_1.md
    reviewer_inherited_turn_n.md
    reviewer_simple_turn_1.md
    reviewer_simple_turn_n.md
  data/
    critical_review_dimensions.json
```

Meaning:
- `templates/scaffold/*` are copied during `init`
- `templates/prompts/*` are rendered into per-turn role prompt artifacts such as `turns/0001/generator/prompt.md`
- `templates/data/critical_review_dimensions.json` is the source of truth for reviewer critical-dimension keys and labels

The supervisor now supports three workspace shapes:
- `spec_backed`
  - `task.md` + `contract.md` + `AGENTS.md` + role instructions
- `inherited_context`
  - `AGENTS.md` + role instructions only
  - intended for fork-based starts that inherit product context from an existing Codex chat session
- `simple`
  - `initial_review.md` + `AGENTS.md` + role instructions
  - intended for “take this review and fix it safely” workflows, with either fresh or forked session bootstrap
  - generator must validate each review point before acting; reviewer must adjudicate disagreements instead of blindly looping

## Spec Model

This repo uses three canonical task files with different jobs:

- `task.md`
  - The canonical **Feature Spec**
  - Describes the requested behavior, constraints, boundaries, and validation expectations
- `contract.md`
  - The canonical **Definition of Done**
  - Checklist only; each item must be objectively checkable
- `AGENTS.md`
  - The canonical **Council Brief**
  - Stable generator/reviewer behavior only, not feature requirements

This separation matters:
- the feature spec says what should be built
- the definition of done says when approval is justified
- the council brief says how the agents should behave

### Glossary

- `spec`
  - A clear written description of the feature, behavior, constraints, and expected validation
- `definition of done`
  - The auditable checklist that must be true before approval
- `council brief`
  - Stable operating rules for generator and reviewer
- `blocking issue`
  - A concrete problem that prevents approval
- `needs_human`
  - A stop state used when the feature spec or definition of done is too ambiguous, contradictory, or non-auditable to continue safely

### Writing Guide

You do not need advanced technical vocabulary to write a good task.

Good `task.md` writing:
- describe behavior concretely
- describe constraints and non-goals
- describe what should happen for users or operators
- describe what parts of the system are in scope

Bad `task.md` writing:
- slogans without behavior
- vague adjectives without concrete follow-up
- mixing implementation, business aspiration, and approval criteria into one sentence

Good `contract.md` writing:
- checklist items that can be verified by reading code, running tests, or observing behavior

Bad `contract.md` writing:
- `production-ready`
- `enterprise-grade`
- `viral`
- `best-in-class`

Those phrases are acceptable only after they are decomposed into measurable engineering conditions.

### Example Workspace

Simple user request:
- “Make a replay-verified score submission flow for the Snake game.”

Good `task.md`:

```md
# Feature Spec

## Goal
Add replay-verified score submission for the Snake game backend.

## User Outcome
Players can submit scores, but the server stores them only after replay verification.

## In Scope
- Backend score submission
- Session validation
- Frontend score-submit payload changes
- Tests for replay verification

## Out of Scope
- Mobile app packaging
- Marketing or growth features

## Constraints
- Keep SQLite
- Keep the current frontend/backend split

## Existing Context
- The repo already has an Express backend and browser-based Snake frontend.

## Desired Behavior
- `/api/scores` rejects invalid replay payloads.
- Verified runs are stored in the leaderboard.

## Technical Boundaries
- Do not replace the current persistence layer.

## Validation Expectations
- Add tests for valid and invalid replay submissions.

## Open Questions
- None
```

Good `contract.md`:

```md
# Definition of Done

- [ ] `/api/scores` rejects invalid replay payloads with structured 4xx JSON.
- [ ] Verified replay submissions are persisted to the leaderboard.
- [ ] Required tests for replay verification are present and passing.
```

Good `AGENTS.md`:
- generator must implement against the feature spec and definition of done
- reviewer must approve only when the definition of done is satisfied
- ambiguity must become `needs_human`

### Future Planner / Preparator

The future planner/preparator loop should take a weak user request like:
- “make viral snake 3d game ios”

and convert it into:
- a concrete `task.md` feature spec
- a measurable `contract.md` definition of done
- optional role-instruction additions only when needed

It should not:
- dump product requirements into `AGENTS.md`
- use `contract.md` for vague business aspirations
- leave `task.md` as a one-line wish

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
/path/to/target-repo/.codex-council/my-task/task.md
/path/to/target-repo/.codex-council/my-task/contract.md
/path/to/target-repo/.codex-council/my-task/AGENTS.md
/path/to/target-repo/.codex-council/my-task/generator.instructions.md
/path/to/target-repo/.codex-council/my-task/reviewer.instructions.md
```

If you already know the task brief, you can seed it during init:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task \
  --dir /path/to/target-repo \
  --task "Implement feature X"
```

If you want a fork-based inherited-context workspace with no repo-local `task.md` or `contract.md` yet:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task \
  --dir /path/to/target-repo \
  --skip-task-and-contract
```

If you want a simple review-fix workspace driven by a repo-local `initial_review.md`:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task \
  --dir /path/to/target-repo \
  --simple
```

Simple mode is the right abstraction here. It should stay a dedicated mode, not become a multi-flag combination like `--with-review --skip-task-and-contract`.

Then edit the scaffolded files as needed and start the council:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo
```

Fork-based start examples:

Spec-backed fork start:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --generator-fork-session-id <generator_parent_session_id> \
  --reviewer-fork-session-id <reviewer_parent_session_id>
```

Inherited-context fork start:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --generator-fork-session-id <generator_parent_session_id> \
  --reviewer-fork-session-id <reviewer_parent_session_id>
```

In inherited-context mode, both fork session ids are required. This mode is intended for forked starts, not fresh spec-less runs.

Simple-mode fresh start:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo
```

Simple-mode fork start:

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
- refuse to start on a dirty repo in spec-backed mode
- refuse to start on a dirty repo in simple mode
- allow a dirty repo in inherited-context fork mode
- launch two real `codex` TUIs in `tmux` inside that target repo
- build each turn prompt from the available canonical task files for that workspace mode
- inline the canonical task files on turn 1, then only reference their canonical paths on later turns so the agents can inspect the current files directly
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
- `task.md` is the canonical feature spec
- `contract.md` is the canonical definition of done
- `initial_review.md` is the canonical first generator brief in simple mode
- in simple mode, `initial_review.md` is a starting review brief, not unquestionable truth
- in simple mode, generator must classify review points as `agree` / `disagree` / `uncertain` before coding
- in simple mode, reviewer must adjudicate generator disagreements with evidence and must not restate the same blocker without stronger evidence
- `AGENTS.md` is the canonical council brief
- `start` refuses to launch if `task.md` is missing required spec sections
- `start` refuses to launch if `contract.md` is still scaffold text or has no checklist items
- `start` refuses to launch if `initial_review.md` is still scaffold text or has no concrete bullet items in simple mode
- inherited-context mode intentionally omits repo-local `task.md` and `contract.md`
- inherited-context mode requires both `--generator-fork-session-id` and `--reviewer-fork-session-id`
- inherited-context mode allows a dirty worktree so the council can continue from already-modified forked context
- spec-backed mode keeps the old clean-worktree requirement, even when fork session ids are supplied
- simple mode can start either fresh or from fork; it keeps the normal clean-worktree requirement
- approval means both:
  - the contract checklist is satisfied
  - all critical review dimensions pass
- generator must write `generator/message.md` and `generator/status.json`
- reviewer must write `reviewer/message.md` and `reviewer/status.json`
- `raw_final_output.md` is trace-only and now captures only an explicit terminal summary block, not the full pasted prompt or tool trace
- `.codex-council/<task_name>/AGENTS.md` is injected into prompts as a council brief; it does not automatically scope repo-root edits through Codex AGENTS semantics
- either role may emit `needs_human` when `task.md` or the task instructions are flawed enough that continuing would be unsafe or misleading
- a reviewer should use `needs_human`, not `changes_requested`, when the remaining blocker is that the contract itself is too broad or non-auditable
- a generator should use `needs_human`, not `blocked`, when the remaining blocker is task or contract ambiguity rather than an external implementation blocker

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

This is the intended path after you edit `task.md`, `contract.md`, `AGENTS.md`, or role instructions, or after you discuss changes directly in the live Codex session and want the council to proceed.

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
