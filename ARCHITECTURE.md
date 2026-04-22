# Architecture

This document describes the system model of Codex Council as a harness for outer-agent-operated, long-running software work.

## Goal

The system must allow an outer coding agent to:

1. interpret weak or strong user intent
2. synthesize strong canonical task documents
3. launch a generator/reviewer council safely
4. preserve source-of-truth artifacts across pauses and resumes
5. stop only on explicit approval, blocker, or human intervention

## Layered Model

The harness is intentionally layered.

```text
User
  -> Outer agent
    -> codex-council skill
      -> prepare (planner / intent critic planning loop when needed)
        -> Canonical docs in target repo
          -> codex_tui_supervisor.py
            -> generator / reviewer role sessions
              -> turn artifacts
                -> status / continue / reopen / approval
```

### User

The user may be:

- an expert with a precise request
- a novice with vague language
- a reviewer/operator resuming existing work

The system is not allowed to assume the user can write a good engineering brief.

### Outer agent

The outer agent is the primary operating surface of the product.

Its responsibilities:

- classify the request
- inspect the target repo and current `.codex-council` state
- decide whether to answer directly, start a run, continue a run, or reopen an approved run
- synthesize the right canonical documents
- ask only the minimum blocking questions

Its non-responsibilities:

- it should not directly implement the target-repo feature when the user asked to use the harness
- it should not extend `council-agent` itself just because the target task needs some glue
- it should not replace the generator/reviewer council with its own one-shot implementation pass

### Skill router

The `codex-council` skill is the front door for the outer agent.

It does not replace the runtime. It encodes:

- routing
- novice-input normalization
- planning-stage invocation
- doc selection
- lifecycle rules
- recovery rules
- operator-vs-implementer boundary

### Planning preparation

For broad, vague, or unusually rigorous work, the outer agent should not go directly from user prompt to locked execution docs.

Instead, it should use a planning preparation stage:

- `planner`
  - authors draft `task.md`, `spec.md`, and `contract.md`
- `intent critic`
  - verifies fidelity to user intent, repo plausibility, and document quality before execution

When the planning loop produces `spec.md`, it should converge on:

- `spec.md` organized into major `M#` sections
- labeled acceptance criteria under each section (`A1`, `A2`, `A3`, ...)
- no per-section `Non-Goals` / `Out of Scope` subsections; exclusions belong in the global scope sections or explicit acceptance criteria
- `contract.md` that mirrors those sections with top-level `M#` items and cited `M#.A#` sub-checks

In runtime terms, that stage is now `prepare`:

- it writes auditable planning artifacts under `planning-runs/`
- it preserves `source_intent.md` per planning run
- it loops planner and intent critic until `approved`, `blocked`, `needs_human`, or planning max turns

This stage is where `hard` mode belongs.

`hard` mode means:

- require a decision-complete spec for the relevant task class
- require explicit coverage of prompt/tool/schema behavior when the product is agentic
- reject omissions, toy-like abstractions, and hidden assumptions
- optimize for execution safety and intent fidelity rather than brevity

### Canonical docs

The canonical docs live in the target repo under `.codex-council/<task_name>/`.

They are the durable briefing layer between the outer agent and the runtime:

- `task.md`
- `review.md`
- `spec.md`
- `contract.md`
- `AGENTS.md`
- `generator.instructions.md`
- `reviewer.instructions.md`

Standard scaffolded planning-support files live under the task workspace in the current harness model:

- `planner.instructions.md`
  - task-local planner guidance used during `prepare`
- `intent_critic.instructions.md`
  - task-local planning-critic guidance used during `prepare`
- `spec-contract-linking-example.md`
  - task-local worked example for the spec→acceptance criteria→contract linkage model

Optional supporting context may also exist under the task workspace:

- `branch_northstar_summary.md`
  - non-canonical branch/worktree context used to preserve intent for branch-driven work such as `github_pr_codex`

Planning runs live separately from execution runs:

- `.codex-council/<task_name>/planning-runs/<run_id>/...`
- `.codex-council/<task_name>/runs/<run_id>/...`

### Runtime supervisor

`scripts/codex_tui_supervisor.py` is the low-level control plane.

It is responsible for:

- workspace scaffolding
- document validation before `start`
- explicit `reopen` lifecycle handling for approved runs
- role-session launch and reuse
- prompt artifact generation
- artifact validation
- turn transitions
- pause/resume behavior

It is a live orchestrator process, not just a launcher. If it dies mid-run, role sessions may keep going, but orchestration stops.

### Role sessions

The runtime launches two role sessions:

- generator
- reviewer

These are separate cognitive roles, not just two consecutive prompts. The system depends on preserving that separation.

The reviewer is not merely a checklist scorer. In stronger review postures, it should:

- audit changed code directly before trusting tests
- inspect downstream readers/consumers and failure paths
- treat passing tests as supporting evidence rather than primary truth
- surface fragile architecture, hidden regressions, or silent degradation even when the contract appears mostly satisfied

Reviewer contract state is not monotonic across turns.

If later generator work regresses a previously satisfied contract point or cited acceptance sub-check, the reviewer should uncheck it again and record that regression explicitly rather than preserving the old checkmark.

The reviewer may tighten tests or fixtures when that materially improves review evidence, but it should not directly patch production code.

### Turn artifacts

Each turn writes role-scoped artifacts.

Core files:

- `turn.json`
- `context_manifest.json`
- `reopen.json` when the run was created via `reopen`
- `<role>/prompt.md`
- `<role>/message.md`
- `<role>/status.json`
- `<role>/raw_final_output.md`

Some modes may add non-canonical, turn-scoped context artifacts such as GitHub review input snapshots when the reviewer source is external.

These artifacts are the real control plane.

## Source of Truth

The system has multiple kinds of state, but they do not all have equal authority.

### Highest authority

- canonical docs in the target repo
- validated turn artifacts

### Lower authority

- `state.json`
  - operational cache, useful but not authoritative when artifacts disagree
- `.codex-council/reopen-events.jsonl`
  - append-only reopen audit store for approved-run supersessions
- live session state
  - useful for continuation, not a substitute for validated artifacts

### Why this matters

The harness must route `continue` from the latest validated artifacts, not from stale memory of what probably happened.

## Robustness Loops

There are several nested robustness loops in the design.

### 1. User input -> strong brief

This is the most important product loop.

Weak request:

- vague language
- missing vocabulary
- incomplete intent

Outer-agent responsibilities:

- infer what can be learned from the repo
- ask only the minimum blocking questions
- for broad/vague/agentic work, run planner/intent-critic preparation before locking execution docs
- produce strong `task.md`, `review.md`, `spec.md`, and `contract.md`
- preserve the primary user-facing intent instead of translating it into a nearby but non-equivalent maintenance/helper path

### 1a. Planning-stage robustness

For work that needs a true spec, the outer agent should use a two-role authoring loop before execution:

- planner drafts the execution docs plus explicit assumptions/open questions
- intent critic reviews those docs against raw user intent, repo facts, and the planning quality bar
- planner revises the docs directly instead of arguing around omissions
- unresolved ambiguity escalates to `needs_human`

The critic should cite exact missing dimensions, not vague “add more detail” requests.

### 2. Brief quality enforcement

Before `start`, the runtime validates:

- presence of the required headings
- absence of scaffold placeholders
- enough useful content to execute safely
- auditable `contract.md` checklist quality
- broad work that likely requires `spec.md`
- decision-complete `spec.md` subsections for broad/spec-driven work

This is the layer that prevents weak documents from reaching the council.

### 3. Role separation

Generator and reviewer have different jobs and different approval semantics.

The generator does not decide approval.
The reviewer does not silently invent requirements.
The reviewer should not silently backfill missing implementation-critical policy from vague specs; that is a doc-quality failure, not reviewer discretion.

The same discipline should hold in the planning stage:

- planner authors the docs
- intent critic evaluates them
- the critic should not silently author missing policy on the planner’s behalf

### 3a. Evidence before diagnosis

The council should not turn a surface symptom into a confident root-cause claim without direct support.

Expected discipline:

- localize where execution stopped
- state the last confirmed progress point
- distinguish observed facts from inference
- use the narrowest proven blocker wording until stronger evidence exists

This is important because blocked turns often happen near shared dependencies or setup boundaries, and a vague summary can send the next turn down the wrong path even when the implementation itself is fine.

### 4. Artifact-driven continuation

`continue` must inspect what the roles actually wrote:

- pending artifacts
- invalid artifacts
- `changes_requested`
- `needs_human`
- `approved`

This avoids resuming the wrong role or wrong turn.

It also makes recovery possible when the supervisor died and `state.json` is stale but the role artifacts already show what should happen next.

Approved runs are terminal for `continue`.

If the approval was wrong or the canonical requirements changed afterward, the runtime must require an explicit `reopen` that:

- preserves the old approved run unchanged
- creates a fresh linked run from the current canonical docs
- records reopen metadata and doc-change context durably

### 5. Approval discipline

Approval is structured, not narrative.

Reviewer approval depends on:

- no blocking issues
- all critical review dimensions passing
- `contract.md` satisfaction when present

## Canonical Document Roles

### `task.md`

Short executable brief for most concrete work.

### `review.md`

Findings input for debugging, review comments, and externally supplied issues.

### `spec.md`

Detailed design layer when the task is too broad or ambiguous.

For broad/spec-driven work, this layer should be decision-complete rather than directional. Relevant execution dimensions such as source of truth, read/write flow, fallback, runtime expectations, integrity invariants, and validation hooks should be decided explicitly or marked not applicable.

For agentic applications, `spec.md` should also make clear:

- the primary user-facing path
- any maintenance/background paths that support it
- forbidden substitutions between those paths
- prompt/system-design implications when they materially shape runtime behavior

### `contract.md`

Auditable approval bar for most non-trivial work.

For spec-driven work, the contract should still stay short, but it should cover more than a feature outcome alone. It should usually include:

- at least one behavior outcome
- at least one regression / integrity / fallback / state guardrail
- at least one verification item

For broad/spec-driven work, the contract should also be a precise approval projection of the major `M*` sections in `spec.md`.

When a spec section has multiple acceptance criteria, the contract should make those criteria explicit enough that the reviewer cannot satisfy the contract point while any linked acceptance criterion still fails.

### Task-local `AGENTS.md`

Stable council behavior only.

It must not become a dumping ground for task-specific product requirements.

## Stable vs Customizable

### Stable

- canonical file names
- role separation
- artifact-driven transitions
- CLI shape, including explicit `reopen`
- review dimension model

### Customizable

- task-local content inside canonical docs
- role instruction additions
- skill/reference-pack wording
- team-specific workflow conventions

## Failure Modes

The harness is especially designed to surface these failures instead of silently pushing through them:

- task docs are contradictory
- task docs are too vague to execute safely
- contract is not auditable
- generator artifacts are missing or invalid
- reviewer repeats vague blockers without stronger evidence
- a paused run is resumed from the wrong state
- a false approval or outdated approval is silently reused instead of being superseded explicitly

The correct stop state for documentation ambiguity is `needs_human`, not continued guessing.

## Why The Product Needs Heavy Docs

This repo is not just runtime code. It is a **behavioral system** whose quality depends on:

- how the outer agent thinks
- how docs are synthesized
- how the council interprets them
- how humans resume and customize it

That is why public docs, skill references, templates, runtime validators, and tests must all stay synchronized.

## Boundary Rule

When the user says, in effect, “use this harness to do feature X”, the system boundary is:

- outer agent: classify, inspect, synthesize docs, launch or resume
- council runtime: actual implementation/review loop in the target repo

Breaking that boundary is a product failure, even if the direct implementation would have been technically possible.

## Process-Lifetime Rule

When an outer agent uses `prepare`, `start`, `continue`, or `reopen`, it must preserve the lifetime of the supervisor process whenever that command actually launches or resumes a supervisor.

Valid patterns:

- block and wait
- launch in a dedicated persistent terminal
- launch in `tmux`
- launch as a truly detached background job

Preferred operator default:

- if the outer agent can stay attached, run the supervisor command in the foreground and wait
- if the outer agent cannot guarantee that, launch the supervisor command in its own dedicated `tmux` session
- treat detached background jobs as a fallback, not the default operator path

Invalid pattern:

- start the supervisor from an outer-agent shell and then let that shell die

That failure mode can leave a run stale even if a role session later writes valid artifacts.
