# INSTRUCTS

This file is the operating manual for an outer agent using `council-agent` as a harness.

It is not maintainer guidance for editing this repository itself. For maintainer work, use repo-root `AGENTS.md`. For harness operation, use this file and the [`codex-council` skill](./skills/codex-council/SKILL.md).

## What This Repo Can Do

An outer agent can use this repo to:

- answer direct questions about how the harness works
- scaffold canonical task documents inside a target repo
- start a new generator/reviewer run
- inspect current run state with `status`
- resume the correct role and turn with `continue`
- preserve explicit review feedback and approval criteria through structured artifacts

The outer agent should hide most of the internal document model from the end user. The user should usually describe the work in plain language; the outer agent chooses the right documents and commands.

## Routing Table

Classify every request into one of these modes before taking action.

### 1. Direct answer only

Use this for:

- “How does this harness work?”
- “What does `contract.md` do?”
- “Why did the reviewer pause?”
- “What commands exist?”

Behavior:

- answer directly
- do not create `.codex-council` files
- do not call `start` or `continue`

### 2. Inspect or resume an existing run

Use this for:

- “What’s the state of my run?”
- “Continue the paused council run”
- “Resume after I updated the contract”

Behavior:

- inspect existing task workspaces and runs first
- prefer `status` to understand the current state
- prefer `continue` over creating a new run when the task and run already exist
- do not overwrite task docs unless the user or repo state clearly requires it

### 3. Concrete execution request

Use this for:

- “Debug why sync duplicates rows”
- “Fix the failing fallback path”
- “Implement the parser change described in issue 42”

Behavior:

- do not ask clarifying questions when the request is specific enough to act safely
- default document set: `task.md` + `contract.md`
- `spec.md` is usually unnecessary here
- after writing the needed docs, run `start`

### 4. Findings-driven fix

Use this for:

- “Address these PR review comments”
- “Here are the logs from the failing deployment”
- “Fix these reviewer findings”

Behavior:

- default document set: `review.md` + `contract.md`
- add `task.md` only if a short brief materially improves generator intent
- run `start` once the docs are ready

### 5. Broad feature or spec work

Use this for:

- “Build a billing dashboard”
- “Add a new workflow for content review”
- “Implement a multi-step onboarding redesign”

Behavior:

- ask only the minimum blocking questions needed to make the work executable
- default document set: `task.md` + `spec.md` + `contract.md`
- once the blocking questions are answered, run `start`

## Question Policy

Default rule:

- prefer action over questions

Ask questions only when missing information would materially change:

- which docs should be created
- what success means
- what is in or out of scope
- whether the work is findings-driven or implementation-driven
- whether a run should be resumed instead of restarted

Do not ask questions that the outer agent can answer by inspecting:

- the target repo
- the existing `.codex-council` workspace
- current run artifacts
- current branch and worktree state

For broad feature work, ask the fewest questions needed to make `spec.md` and `contract.md` decision-complete.

## Document Selection and Synthesis

### `task.md`

Use `task.md` as the default brief for nearly all new execution requests.

Synthesize:

- `## Request`
  - the concrete bug, fix, or requested change
- `## Context`
  - relevant files, constraints, logs, or repo facts that make execution safer
- `## Success Signal`
  - what should be true when the task is done

Keep `task.md` short. If it starts turning into a design document, create `spec.md`.

### `review.md`

Use `review.md` when the input is already findings-shaped.

Structure it as:

- concrete findings under `## Findings`
- supporting logs, repro steps, or code references under `## Context`

Do not mix broad product requirements into `review.md`.

### `spec.md`

Create `spec.md` only when `task.md` would leave meaningful ambiguity.

Typical triggers:

- multiple surfaces or subsystems
- explicit scope boundaries
- architectural or interface constraints
- non-obvious validation expectations
- broad feature work that needs structured decomposition

Non-blocking uncertainty may remain in `## Open Questions`, but blocking uncertainty should be asked before launch.

### `contract.md`

`contract.md` is the default acceptance and approval artifact for most non-trivial runs.

Use it unless the request is:

- ultra-trivial
- effectively one-step
- or direct-answer-only

Checklist rules:

- short and auditable
- objective and observable
- derived from user intent, likely reviewer gates, and concrete verification signals
- no vague phrases like `production-ready` or `best-in-class`

Good contract items usually cover:

- the required behavior
- an important regression or integrity guardrail
- required verification such as tests, reproduction, or manual validation

### Task-local `AGENTS.md`

Treat the injected task-local `AGENTS.md` as stable council behavior.

Do not put task-specific requirements, scope, or acceptance criteria there.

## Command Recipes

The outer agent should use the existing CLI, not invent new commands.

### Create a workspace

If the task workspace does not exist:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task --dir /path/to/target-repo
```

Use a concise task name that safely fits the existing task-name pattern.

### Write docs

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write review my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write spec my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --dir /path/to/target-repo --body "..."
```

Only write the minimal required document set for the chosen route.

### Start a run

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

Prefer the default auto role selection unless a special case requires otherwise.

### Inspect a run

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo
```

Use this before deciding whether to continue or rewrite documents.

### Continue a run

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task --dir /path/to/target-repo
```

Use `continue` after:

- a `changes_requested` verdict
- a `needs_human` pause
- human edits to canonical task docs
- session loss where validated artifacts still exist

## Run-State Policy

When a suitable task workspace and run already exist:

- inspect first
- prefer continuing in place
- avoid reinitializing unless the user clearly wants a new task

When the request is concrete and no suitable run exists:

- initialize if needed
- write the required docs
- start immediately

When the request is direct-answer-only:

- do not initialize
- do not write docs
- do not start

## Worked Defaults

- “Debug why sync duplicates rows”
  - route: concrete execution request
  - docs: `task.md` + `contract.md`
  - questions: none unless the repo state makes the target ambiguous
  - action: `init` if needed, then `write`, then `start`

- “Address these PR review comments”
  - route: findings-driven fix
  - docs: `review.md` + `contract.md`
  - action: `init` if needed, then `write`, then `start`

- “Build feature X”
  - route: broad feature/spec work
  - docs: `task.md` + `spec.md` + `contract.md`
  - questions: only the minimum blocking questions
  - action: after questions, `write`, then `start`

- “What’s the state of my run?”
  - route: inspect/resume
  - action: `status`, then optionally `continue`

- “How does this repo work?”
  - route: direct answer only
  - action: explain, do not scaffold

## Anti-Patterns

- Do not use repo-root `AGENTS.md` as the consumer manual.
- Do not force users to choose between `task.md`, `review.md`, `spec.md`, and `contract.md` when the outer agent can decide.
- Do not ask broad product questions before simple debugging requests.
- Do not skip `contract.md` for non-trivial work just because the request sounds concrete.
- Do not restart a healthy paused run when `continue` is the correct action.
- Do not put product requirements into task-local `AGENTS.md`.
- Do not create `spec.md` when a short `task.md` already makes the work executable.
