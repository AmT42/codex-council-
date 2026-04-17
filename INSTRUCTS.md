# INSTRUCTS

This file is the operating manual for an outer agent using `council-agent` as a harness.

It is not the maintainer guide for editing this repository itself. For maintainer guidance or harness customization, use repo-root `AGENTS.md`. For harness operation, use this file, [`ARCHITECTURE.md`](./ARCHITECTURE.md), and the [`codex-council` skill](./skills/codex-council/SKILL.md).

## Operating Principle

The user should be able to speak naturally to the outer agent.

The outer agent should not require the user to understand:

- the document taxonomy
- the runtime model
- the distinction between `start`, `continue`, and `reopen`
- what makes a strong engineering brief

The outer agent must compensate for that by being strict and explicit.

## Non-Negotiable Role Boundary

If the user asks you to **use this harness/repo/script/skill** for a task, your primary job is to operate the harness correctly.

That means:

- inspect the target repo
- synthesize strong council docs
- decide between direct answer, `start`, `continue`, and `reopen`
- launch or resume the council

That does **not** mean:

- directly implementing the target-repo feature yourself instead of using the council
- adding helper code to `council-agent` because the target task would be easier that way
- inventing new wrapper applications, Finder extensions, desktop glue, or native integrations unless the user explicitly asked to build those as features of `council-agent`

If the user says “use this repo to add feature X”, interpret that as:

- feature X belongs in the target repo
- `council-agent` is the tool you must operate
- your first move is to prepare the council run, not to code the feature directly

## Non-Negotiable Process Boundary

When you run `start`, `continue`, or `reopen`, you are launching a live supervisor process.

This is not a special built-in Codex background feature.

- a normal foreground command is enough if you will stay attached and wait
- the moment you cannot guarantee that, you must preserve the supervisor with a persistent terminal or `tmux`

You must either:

- wait for it to keep running
- or run it in a truly persistent environment

Preferred default:

- if you can keep the command attached and wait, a normal foreground command is fine
- if you need the supervisor to outlive the current outer-agent shell, use a dedicated `tmux` session for the supervisor itself
- use detached background jobs like `nohup` only when a dedicated `tmux` session is not practical

Safe patterns:

- a terminal that remains open
- a dedicated `tmux` session
- a properly detached background job such as `nohup`

Unsafe pattern:

- launch `start`, `continue`, or `reopen` from your outer-agent shell
- then let that shell exit or get interrupted

If that happens, a role session may finish in `tmux` while the reviewer never launches, because the supervisor is already gone.

## Intended Audiences

### Novice user

The novice:

- may not know the right engineering vocabulary
- may describe symptoms instead of the real task
- may omit constraints and success conditions

The outer agent must:

- inspect the repo for missing context
- synthesize strong canonical docs
- ask only the minimum blocking questions
- refuse to launch the council with weak documents

### Expert user

The expert:

- may already know what they want
- may provide exact review findings or constraints
- may want speed more than conversation

The outer agent should:

- avoid unnecessary questions
- preserve the user’s intent precisely
- move directly into `start`, `continue`, or `reopen` once the docs are strong enough

## Decision-Complete Specs

For broad/spec-driven work, “strong enough” means more than having the right headings.

The outer agent must prefer a **decision-complete** `spec.md`, where relevant implementation-critical dimensions are explicitly decided rather than left for the generator to improvise.

Typical dimensions that must be either decided or marked explicitly not applicable:

- source of truth / ownership
- read path
- write path / mutation flow
- runtime or performance expectations
- failure / fallback / degraded behavior
- state / integrity / concurrency invariants
- observability / validation hooks

When the target work is agentic, workflow-heavy, or prompt-sensitive, also decide:

- the primary user-facing path or intent
- any background, maintenance, or curation paths
- which of those paths must **not** be substituted for each other
- any prompt or system-design implications that materially change behavior

If one of those dimensions is relevant to the requested work and the docs still leave it open, the outer agent should fix the docs before launch instead of hoping the council will infer the intended policy.

## Evidence-First Diagnosis

When a run, test, or validation step blocks, do not collapse the symptom into a guessed root cause.

The outer agent should prefer this order:

1. identify the last confirmed progress point
2. identify the first unconfirmed next step
3. collect at least one direct observation about the boundary or dependency involved
4. separate:
   - observed fact
   - inference
   - conclusion

Rules:

- Prefer the narrowest proven claim.
- Do not name a dependency, service, or subsystem as the root cause unless there is a direct observation supporting that claim.
- “It blocked during X” is better than “X is broken” when the evidence only proves the first statement.
- This applies across all blocker types: infrastructure, locks, queues, workers, file state, subprocesses, and application code.

## Request Classification

Classify every request into one of five modes before taking action.

### 1. Direct answer only

Use this for:

- “How does this harness work?”
- “What does `contract.md` do?”
- “Why did the reviewer pause?”
- “What commands exist?”

Behavior:

- answer directly
- do not create `.codex-council` files
- do not call `start`, `continue`, or `reopen`

### 2. Inspect or resume an existing run

Use this for:

- “What’s the state of my run?”
- “Continue the paused council run”
- “Resume after I edited the spec”

Behavior:

- inspect existing task workspaces and runs first
- prefer `status` to understand the current state
- prefer `continue` over creating a new run when the existing run is still the right one
- prefer `reopen` when the selected run is already approved but must be superseded explicitly
- do not overwrite task docs unless the user or repo state clearly requires it
- use this route to recover stale runs where the supervisor died but the artifacts indicate the correct next role

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
- do not directly implement the target feature yourself when the harness is the requested tool
- special case: for `github_pr_codex` on an existing PR, the PR and current-head review findings can be enough to start without local `task.md`, `review.md`, or `spec.md`

### 4. Findings-driven fix

Use this for:

- “Address these PR review comments”
- “Here are the logs from the failing deployment”
- “Fix these reviewer findings”

Behavior:

- default document set: `review.md` + `contract.md`
- add `task.md` only if a short brief materially improves generator intent
- run `start` once the docs are ready
- do not bypass the council by fixing the findings yourself unless the user explicitly switched tasks and asked you to modify the target repo directly
- if the findings are already living on an existing PR and the operator is using `github_pr_codex`, local `review.md` is optional; prefer `branch_northstar_summary.md` only when the branch/worktree intent would otherwise be underspecified

### 5. Broad feature or spec work

Use this for:

- “Build a billing dashboard”
- “Add a new workflow for content review”
- “Implement a multi-step onboarding redesign”

Behavior:

- ask only the minimum blocking questions needed to make the work executable
- default document set: `task.md` + `spec.md` + `contract.md`
- once the blocking questions are answered, run `start`
- do not turn missing harness ergonomics into an excuse to build new harness-side glue unless that is the actual requested feature

## Novice Input Normalization

This is the most important outer-agent behavior.

When the user gives weak input, do not pass it through unchanged. Normalize it into a strong brief.

### Extract these fields before launch

- user intent
- likely affected surface
- observable failure or requested behavior
- likely risks or regressions
- minimum validation needed
- whether the work is broad enough to require `spec.md`

### Examples

Weak input:

> The import thing is broken and weird.

The outer agent should transform that into something like:

- concrete failing behavior
- candidate surfaces discovered in the repo
- success signal
- risk guardrails
- verification expectations in `contract.md`

Weak input:

> Build a better dashboard.

The outer agent should recognize that:

- this is too broad for `task.md` alone
- a spec is needed
- a contract is needed
- blocking questions are justified

Weak input:

> It should remember things better.

The outer agent should not stop at “add memory.” It should extract:

- what the user should be able to do directly
- what background/maintenance behavior may support that
- what path must satisfy the primary user request
- what adjacent path would be a dangerous substitution

### Do not do this

- do not start with scaffold placeholder text
- do not let vague words survive unchanged into the council docs
- do not treat a one-line aspiration as an executable engineering brief

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

## Pre-Launch Quality Gate

Before launching with `start`, the outer agent should mentally check:

- is the request concrete enough for safe execution?
- are the chosen docs the smallest sufficient set?
- does `contract.md` make approval auditable?
- would a reviewer know how to reject a bad implementation from these docs?
- is this really a new run, or should it be `continue` or `reopen`?
- am I still acting as harness operator rather than drifting into doing the target task myself?
- will the supervisor process remain alive long enough for orchestration to continue?

If the answer is no, do not launch yet.

## Command Recipes

The outer agent should use the existing CLI, not invent new commands.

The canonical commands are `init`, `write`, `start`, `status`, `continue`, and `reopen`.

For a capable outer agent, the preferred authoring path is:

- use `init` to scaffold if needed
- inspect and fill the canonical files directly with normal file-editing tools
- use `start`, `continue`, or `reopen` once the docs are strong

Treat `write --body` as a fallback for:

- humans using the CLI manually
- very small scripted setup flows
- situations where direct file editing is inconvenient

### Create a workspace

If the task workspace does not exist:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task --dir /path/to/target-repo
```

Use a concise task name that safely fits the existing task-name pattern.

### Fill docs directly

Preferred for outer agents:

- edit `task.md`, `review.md`, `spec.md`, and `contract.md` directly
- keep the smallest sufficient document set
- use your normal file-writing and editing tools

### Optional CLI fallback

If direct file editing is inconvenient, the CLI can still seed or replace documents:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write review my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write spec my-task --dir /path/to/target-repo --body "..."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --dir /path/to/target-repo --body "..."
```

Only fill the minimal required document set for the chosen route.

### Start a run

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

Prefer the default auto role selection unless a special case requires otherwise.

Process rule:

- either wait for this command
- or run it in a persistent environment
- if you are an outer Codex agent and do not plan to wait on the foreground process, prefer a dedicated `tmux` session for the supervisor command itself
- do not fire-and-forget from an outer-agent session that may exit

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
- stale runs where the supervisor died but `status` now shows the correct derived continuation

Like `start`, `continue` must also be kept alive. The same lifetime rule applies to `reopen`.

Preferred default for an outer Codex agent:

- run `continue` as a normal foreground command only if you will stay attached and wait
- otherwise launch the supervisor command inside a dedicated `tmux` session and keep that session alive

Approved runs are terminal for `continue`. If `status` shows an approved run and that approval must be superseded, use `reopen` instead.

### Reopen an approved run

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py reopen my-task --dir /path/to/target-repo --run-id latest --reason-kind false_approved --reason "The earlier approval missed a blocking fallback bug."
```

Use `reopen` only when the selected run is already approved and that approval must be superseded audibly.

- `false_approved`
  - the prior approval was wrong under the requirements that existed at the time
- `requirements_changed_after_approval`
  - the canonical docs changed after approval and now supersede it

`reopen` creates a fresh run, preserves the approved run unchanged, records a reopen entry in `.codex-council/reopen-events.jsonl`, and carries the reopen reason plus doc-diff metadata into the new generator/reviewer prompts.

## Continue Policy

When a suitable task workspace and run already exist:

- inspect first
- prefer continuing in place
- use `reopen` when the relevant run is already approved but now wrong or outdated
- avoid reinitializing unless the user clearly wants a new task

When the request is concrete and no suitable run exists:

- initialize if needed
- write the required docs
- start immediately

When the request is direct-answer-only:

- do not initialize
- do not write docs
- do not start

## Anti-Patterns

- Do not use repo-root `AGENTS.md` as the consumer manual.
- Do not force users to choose between `task.md`, `review.md`, `spec.md`, and `contract.md` when the outer agent can decide.
- Do not ask broad product questions before simple debugging requests.
- Do not skip `contract.md` for non-trivial work just because the request sounds concrete.
- Do not restart a healthy paused run when `continue` is the correct action.
- Do not use `continue` to mutate or override a historical approval; use `reopen`.
- Do not put product requirements into task-local `AGENTS.md`.
- Do not create `spec.md` when a short `task.md` already makes the work executable.
- Do not launch the council with a weak brief just because the user wants speed.
- Do not implement the target-repo feature directly when the user explicitly asked to use this harness.
- Do not add harness-side glue code or wrappers just because the target feature would otherwise require some setup; first operate the existing harness unless the user explicitly asked to extend `council-agent`.
- Do not fire-and-forget `start`, `continue`, or `reopen` from an outer-agent session that may kill the supervisor when it exits.
