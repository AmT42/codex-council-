# Codex Council

Codex Council is a Codex-first harness for long-running software work.

It is built for a world where the user often talks to an **outer coding agent** first, not directly to the harness. That outer agent may be working with:

- an expert user who already knows what they want
- a novice user who describes the problem poorly
- a reviewer or operator who needs to resume an existing run safely

The goal of this repo is not just to run two Codex sessions. The goal is to give the outer agent enough structure, rules, and artifacts to reliably turn messy human input into a strong engineering brief, then execute that brief through a generator/reviewer council that can be resumed and audited.

The current runtime lives in [`scripts/codex_tui_supervisor.py`](./scripts/codex_tui_supervisor.py). The recommended outer-agent entrypoint is the [`codex-council` skill](./skills/codex-council/SKILL.md). The main agent operating manual is [`INSTRUCTS.md`](./INSTRUCTS.md). The system reference is [`ARCHITECTURE.md`](./ARCHITECTURE.md).

This repo follows the same broad harness ideas discussed in Anthropic's [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) and OpenAI's [Harness engineering](https://openai.com/fr-FR/index/harness-engineering/): structured artifacts, explicit evaluator roles, context handoffs, and repo-embedded operating knowledge.

## The Problem It Solves

AI coding assistants fail in predictable ways when they are treated as a single generic brain:

- vague input becomes vague code
- planning, implementation, and review blur together
- approval is guessed from prose instead of checked against explicit criteria
- users who lack good engineering vocabulary produce weak briefs
- long-running work loses context or resumes incorrectly

Codex Council is designed to counter those failure modes.

It does that by combining:

- canonical task documents inside the target repo
- a generator/reviewer runtime with structured artifacts
- an outer-agent skill that decides how to frame the work before launch
- an approval layer centered on `contract.md`
- artifact-driven `continue` rather than guessing from stale state
- explicit `reopen` when a historical approval must be superseded audibly

It also depends on one discipline that is easy to miss in agentic applications:

- the **primary user-facing intent** must survive translation into the brief
- maintenance, curation, background, or repair paths must not silently replace that primary user path unless the task explicitly says they should

For broad or risky work, the reviewer is expected to act as a deeper forensic code auditor rather than a shallow checklist gate:

- passing tests are supporting evidence, not primary truth
- contract satisfaction does not excuse fragile code or hidden operational risk
- the reviewer should inspect changed code, downstream readers/consumers, and failure behavior directly
- the reviewer may tighten tests or fixtures when needed to improve review evidence, but it should not patch production code directly

## Operator Boundary

When a user asks an outer agent to **use this repo or harness** for some task, the outer agent is acting as a **harness operator**, not as the direct implementer of the target feature.

That means:

- the outer agent should scaffold or update the canonical council docs
- then `prepare`, `start`, `continue`, or `reopen` the harness as appropriate
- and let the generator/reviewer council do the actual target-repo implementation work

It must **not**:

- implement the target-repo feature directly instead of using the harness
- silently bypass the council because the feature sounds easy
- extend `council-agent` itself with glue code, wrappers, native integrations, or app-specific helpers unless the user explicitly asked to modify the harness repository

If the user asks for a native integration or a new product feature for `council-agent` itself, that is maintainer work on this repo. Otherwise, the outer agent should treat `council-agent` as the tool it operates, not the place where the target feature gets built.

## Product Model

There are two different agent surfaces in this repo.

### 1. Consumer-facing outer-agent surface

This is for the agent that is *using* the harness on behalf of a user.

Use:

- [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md)
- [`INSTRUCTS.md`](./INSTRUCTS.md)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md)

This surface teaches the outer agent:

- when to answer directly
- when to inspect and resume
- when to run a planning stage before execution docs are locked
- when to scaffold `task.md`, `review.md`, `spec.md`, and `contract.md`
- when to ask clarifying questions
- when not to ask them
- how to turn weak user input into strong council input

### 2. Maintainer/customizer surface

This is for an agent modifying `council-agent` itself.

Use:

- repo-root [`AGENTS.md`](./AGENTS.md)

That file is for harness maintenance and customization, not for operating the harness against a target repo.

## Decision-Complete Specs

For broad/spec-driven work, the outer agent should not stop at a high-level architecture sketch.

A strong `spec.md` is **decision-complete**: it makes the relevant implementation-critical dimensions explicit instead of leaving the generator to improvise them during coding.

Typical dimensions that should be decided, when relevant:

- source of truth / ownership
- read path
- write path / mutation flow
- runtime / performance expectations
- failure / fallback / degraded behavior
- state / integrity / concurrency invariants
- observability / validation hooks

If a dimension truly does not apply, the spec should say so explicitly instead of leaving the section vague.

For agentic or prompt-driven products, decision-complete also means:

- state the primary user-facing path or intent
- state any maintenance/background paths that support it
- state forbidden substitutions between them when those substitutions would create a product bug
- state any prompt or system-design implications that the generator should not be left to improvise

## Planning Stage

For broad, vague, novice-described, or agentic work, the harness should not jump straight from raw user wording to execution docs.

The preferred route is a planning stage:

- outer agent inspects the repo and preserves the raw user intent
- planner authors the draft `task.md`, `spec.md`, and `contract.md`
- intent critic checks whether those docs are faithful to the real intent and strong enough for execution
- only after that review passes should the execution docs be treated as locked inputs for the generator/reviewer loop

This planning stage is a preparation layer, not a replacement for the runtime council.

`hard` mode belongs here:

- it means planning-stage rigor, not mere verbosity
- it requires a decision-complete spec for the relevant task class
- it is especially appropriate for workflow-heavy, prompt-sensitive, tool/schema-heavy, or operationally risky work

## What The Harness Does

Codex Council runs a two-role loop inside a target repo:

- `generator`
  - implements or fixes the requested work
- `reviewer`
  - evaluates correctness, regressions, fidelity to intent, risk, and test adequacy

The control plane is file-based. The council reads canonical task documents from the target repo and writes turn-scoped artifacts under `.codex-council/<task>/runs/<run_id>/`.

This is not a one-shot prompt wrapper. It is a harness for:

- briefing
- planning for broad or high-rigor work
- implementation
- review
- pause/resume
- approval

## Recommended Entry Point

If an outer Codex agent has access to this repo, point it at:

- [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md)
- [`INSTRUCTS.md`](./INSTRUCTS.md)
- [`ARCHITECTURE.md`](./ARCHITECTURE.md)

The `codex-council` skill is the intended user-facing interface for v1. It is a **single front door** backed by a large reference pack. The skill should decide how to route the request instead of forcing the user to understand the internal document model.

If you want Codex to discover the skill as an installed skill, copy or symlink `skills/codex-council` into `$CODEX_HOME/skills/` or `~/.codex/skills/`.

## Document Model

The council workspace inside a target repo is:

```text
.codex-council/<task_name>/
  AGENTS.md
  generator.instructions.md
  planner.instructions.md
  reviewer.instructions.md
  intent_critic.instructions.md
  spec-contract-linking-example.md
  task.md
  review.md
  spec.md
  contract.md
  planning-runs/
  runs/
```

Canonical documents:

- `task.md`
  - default brief for most execution requests
- `review.md`
  - findings input for debugging, review-driven work, and external comments
- `spec.md`
  - detailed design when `task.md` alone would be too ambiguous
- `contract.md`
  - default acceptance and approval checklist for most non-trivial runs
- `AGENTS.md`
  - stable council behavior only, not feature requirements

Standard scaffolded planning-support files:

- `planner.instructions.md`
  - task-local planner role guidance for authoring strong execution docs
- `intent_critic.instructions.md`
  - task-local planning critic guidance for rejecting weak or non-faithful docs
- `spec-contract-linking-example.md`
  - task-local worked example for the spec→acceptance criteria→contract model used by planner, reviewer, and intent critic

Planning runs write their own artifacts under `.codex-council/<task_name>/planning-runs/<run_id>/`.

Optional supporting context:

- `branch_northstar_summary.md`
  - non-canonical branch/worktree context for `github_pr_codex` or other branch-driven work when the operator wants to preserve the repo northstar without turning it into a task brief

Recommended defaults for outer-agent routing:

- concrete bugfix or targeted implementation
  - `task.md` + `contract.md`
- findings-driven fix
  - `review.md` + `contract.md`
- GitHub PR Codex loop on an existing PR
  - `github_pr_codex` may start without local `task.md`, `review.md`, or `spec.md`
  - use the PR plus current-head GitHub review findings as the effective brief
  - add `branch_northstar_summary.md` when the branch/worktree intent needs durable context
- broad feature or complex design
  - planning stage first via `prepare`, then `task.md` + `spec.md` + `contract.md`
- meta question about the harness
  - answer directly, do not scaffold docs

## Five Operating Modes

The outer agent should classify each request into one primary mode before taking action.

### 1. Direct answer only

Use when the user is asking about the harness itself.

- answer directly
- do not scaffold `.codex-council`
- do not call `prepare`, `start`, `continue`, or `reopen`

### 2. Inspect or resume an existing run

Use when the user wants to understand or resume a current council run.

- inspect first
- prefer `status`
- prefer `continue` over reinitializing
- use `reopen` instead of `continue` when the selected run is already approved but that approval was wrong or the canonical requirements changed afterward

### 3. Concrete execution request

Use when the user gives a specific debug or implementation request that is already actionable.

- do not ask clarifying questions if the request is concrete enough
- default to `task.md` + `contract.md`
- start immediately once the docs are ready

### 4. Findings-driven fix

Use when the user provides review comments, logs, repro notes, or debugging findings.

- default to `review.md` + `contract.md`
- add `task.md` only if it materially clarifies the implementation target
- special case: when using `github_pr_codex` against an existing PR, local `task.md` / `review.md` / `spec.md` may be omitted if the PR and current-head review findings already provide a usable brief

### 5. Broad feature or spec work

Use when the work spans multiple surfaces or would be unsafe to execute from a short task brief.

- ask only minimum blocking questions
- default to a planning stage before locking `task.md` + `spec.md` + `contract.md`
- use planner + intent critic to reach an execution-safe brief
- make `spec.md` decision-complete for the relevant runtime/state/fallback/integrity dimensions
- use `hard` mode when the work is especially agentic, workflow-heavy, prompt-sensitive, or operationally risky

## For Novices vs Experts

This harness must work for both.

### Expert user

An expert may say:

> Fix the fallback path in the sync worker so retries no longer duplicate rows.

The outer agent should:

- avoid unnecessary questions
- synthesize a strong `task.md`
- add `contract.md`
- launch quickly

### Intermediate user

An intermediate user may say:

> The sync feature is buggy and sometimes duplicates rows after retries.

The outer agent should:

- inspect the repo for likely sync surfaces
- turn the vague report into a more concrete `task.md`
- make the success criteria explicit in `contract.md`
- ask a question only if there are several plausible flows or missing product constraints

### Novice user

A novice may say:

> My import thing is broken. It does weird stuff. Can you make it solid?

The outer agent should **not** pass that directly into the council.

It should:

- infer likely surfaces from the repo
- convert the request into concrete problem statements
- add risks and likely validation expectations
- decide whether a short task brief is enough or whether the work needs `spec.md`
- create an auditable `contract.md`
- only then start the harness

The system is only robust if the outer agent can normalize weak input into strong documents.

## Quickstart

### Outer-agent workflow

1. The outer agent reads [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md).
2. It classifies the user request.
3. It discovers facts from the target repo.
4. It fills the minimal canonical document set needed for safe execution, usually by editing the files directly with its normal file tools.
5. It prepares broad work first when needed, then starts, continues, or reopens the harness with the existing CLI.

### Manual fallback

The `write --body` flow below is a manual or lightweight automation fallback.

For a capable outer agent, the recommended path is:

- run `init` if the workspace does not exist
- fill `task.md`, `review.md`, `spec.md`, and `contract.md` directly with normal file-editing tools
- then run `prepare`, `start`, `continue`, or `reopen` as appropriate

From a target repository:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task --dir /path/to/target-repo
```

Then write the docs you need:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --dir /path/to/target-repo --body "Debug why sync duplicates rows."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --dir /path/to/target-repo --body "The retry path no longer duplicates rows and relevant verification passes."
```

For broad or vague work, prepare the docs first:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py prepare my-task \
  --dir /path/to/target-repo \
  --intent "Build a production-grade billing workflow with an operator dashboard." \
  --hard
```

Inspect or resume planning:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo --planning
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py prepare my-task --dir /path/to/target-repo
```

If the latest planning run is already approved and the canonical docs are unchanged, `prepare` may simply report that the docs are already prepared for execution. Use `--new-run` or pass new `--intent` when you intentionally want a fresh planning pass.

Start the execution council:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task --dir /path/to/target-repo
```

GitHub PR Codex example:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task \
  --dir /path/to/target-repo \
  --review-mode github_pr_codex \
  --github-pr https://github.com/acme/repo/pull/123
```

Inspect or resume later:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task --dir /path/to/target-repo
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task --dir /path/to/target-repo
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py reopen my-task --dir /path/to/target-repo --run-id latest --reason-kind false_approved --reason "The approval missed a blocking fallback bug."
```

GitHub PR Codex recovery example:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task \
  --dir /path/to/target-repo \
  --run-id 20260413-155411-90d947
```

## CLI Overview

The public CLI stays intentionally small:

- `init`
  - scaffold `.codex-council` and a task workspace
- `write`
  - replace one canonical task document
- `prepare`
  - start or resume a planning run for `task.md` / `spec.md` / `contract.md`
- `start`
  - launch a new council run
- `status`
  - inspect the latest or chosen run
- `continue`
  - resume the latest valid run in place
- `reopen`
  - supersede an approved run with a fresh run linked back to the historical approval

The outer-agent skill should orchestrate those commands rather than inventing a parallel interface. For strong agents, that usually means using `init`, then editing the canonical files directly, then calling `prepare` for broad work or `start` for concrete execution, and later `continue` or `reopen` as appropriate. `write` remains available as a convenience command, not the primary authoring path for agents.

## Runtime Notes

The TUI supervisor:

- resolves the target directory to its git root by default
- launches generator and reviewer `codex` sessions in `tmux`
- writes role-scoped prompts, messages, statuses, and terminal summaries per turn
- advances turns only when the expected artifact pairs exist and validate
- prefers artifact-driven `continue` over stale run metadata
- keeps `continue` terminal for approved runs and requires explicit `reopen` to supersede them
- can bootstrap from forked session context when local task docs are missing
- validates task documents before `start`
- can start `github_pr_codex` generator-first without local `task.md`, `review.md`, or `spec.md`
- materializes current-head GitHub review findings into turn-scoped review input artifacts for the generator
- resumes blocked `github_pr_codex` reviewer turns on the same turn instead of forcing a new turn

`continue` is the intended path after:

- editing `task.md`, `review.md`, `spec.md`, `contract.md`, or role instructions
- a `needs_human` pause
- a `changes_requested` reviewer verdict
- a stopped session whose validated artifacts still exist

`reopen` is the intended path after an approved run when:

- the approval was wrong under the requirements that existed at the time
  - use `--reason-kind false_approved`
- the canonical docs changed after approval and now supersede it
  - use `--reason-kind requirements_changed_after_approval`

`reopen` creates a fresh run from the current canonical docs, records the superseded run and turn, stores doc-diff metadata, and appends an audit entry under `.codex-council/reopen-events.jsonl`.

## Supervisor Lifetime

`prepare`, `start`, `continue`, and `reopen` are supervisor-facing lifecycle commands.

When one of them actually launches or resumes a supervisor process, it is not a fire-and-forget hint.

`prepare` has one fast path:

- if the latest planning run is already approved and canonical docs are unchanged, it may exit immediately without launching planner or intent-critic sessions

Important when a supervisor is actually running:

- the generator/reviewer or planner/intent-critic `tmux` sessions may keep running even if the supervisor dies
- but the council will stop advancing turns without the supervisor
- this can leave a run stale until someone inspects `status` and resumes with `continue`, or inspects `status --planning` and resumes with `prepare`

So an outer agent must do one of these:

- wait for the command to keep running when it actually launched or resumed a supervisor
- or launch the supervisor in a truly persistent environment

Practical rule:

- a plain foreground command is fine if the outer agent will stay attached and wait for it
- if the outer agent wants the supervisor to outlive the current shell, the preferred default is a dedicated `tmux` session for the supervisor command itself
- detached background jobs like `nohup` are acceptable, but less operator-friendly than `tmux`

Safe persistent environments:

- a dedicated terminal that stays open
- a dedicated `tmux` session
- a properly detached background job such as `nohup` or similar

Unsafe pattern:

- launch `python3 ... codex_tui_supervisor.py start ...` from an outer-agent session
- then let that session exit or get interrupted

## Robustness Philosophy

This harness is robust only if all three layers are strong:

- **outer-agent framing**
  - weak user input becomes strong task docs
- **runtime control plane**
  - artifact-driven transitions and pause/resume
- **approval discipline**
  - `contract.md` and reviewer critical dimensions gate completion

If one layer is weak, the whole system regresses toward generic prompt chaining.

## Stable vs Customizable

Stable:

- canonical document names
- CLI shape
- artifact-driven council flow
- role separation between generator and reviewer

Customizable:

- task-local council documents in the target repo
- role instruction content
- how teams tailor the skill or reference pack to their workflow

## Repository Layout

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
    planner.instructions.md
    reviewer.instructions.md
    intent_critic.instructions.md
    spec-contract-linking-example.md
  prompts/
    generator_initial.md
    generator_followup.md
    planner_initial.md
    planner_followup.md
    reviewer_initial.md
    reviewer_followup.md
    intent_critic_initial.md
    intent_critic_followup.md
    reviewer_fork_bootstrap.md
    artifact_repair.md
  data/
    critical_review_dimensions.json
skills/
  codex-council/
    SKILL.md
    references/
scripts/
  codex_tui_supervisor.py
tests/
  test_codex_tui_supervisor.py
```

## Where To Read Next

- [`INSTRUCTS.md`](./INSTRUCTS.md)
  - outer-agent operating manual
- [`ARCHITECTURE.md`](./ARCHITECTURE.md)
  - system model and source-of-truth rules
- [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md)
  - front door for outer agents
- [`AGENTS.md`](./AGENTS.md)
  - maintainer/customizer guidance for this harness repo
