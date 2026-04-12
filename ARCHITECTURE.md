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
      -> Canonical docs in target repo
        -> codex_tui_supervisor.py
          -> generator / reviewer role sessions
            -> turn artifacts
              -> status / continue / approval
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
- decide whether to answer directly, start a run, or continue a run
- synthesize the right canonical documents
- ask only the minimum blocking questions

### Skill router

The `codex-council` skill is the front door for the outer agent.

It does not replace the runtime. It encodes:

- routing
- novice-input normalization
- doc selection
- lifecycle rules
- recovery rules

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

### Runtime supervisor

`scripts/codex_tui_supervisor.py` is the low-level control plane.

It is responsible for:

- workspace scaffolding
- document validation before `start`
- role-session launch and reuse
- prompt artifact generation
- artifact validation
- turn transitions
- pause/resume behavior

### Role sessions

The runtime launches two role sessions:

- generator
- reviewer

These are separate cognitive roles, not just two consecutive prompts. The system depends on preserving that separation.

### Turn artifacts

Each turn writes role-scoped artifacts.

Core files:

- `turn.json`
- `context_manifest.json`
- `<role>/prompt.md`
- `<role>/message.md`
- `<role>/status.json`
- `<role>/raw_final_output.md`

These artifacts are the real control plane.

## Source of Truth

The system has multiple kinds of state, but they do not all have equal authority.

### Highest authority

- canonical docs in the target repo
- validated turn artifacts

### Lower authority

- `state.json`
  - operational cache, useful but not authoritative when artifacts disagree
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
- produce strong `task.md`, `review.md`, `spec.md`, and `contract.md`

### 2. Brief quality enforcement

Before `start`, the runtime validates:

- presence of the required headings
- absence of scaffold placeholders
- enough useful content to execute safely
- auditable `contract.md` checklist quality
- broad work that likely requires `spec.md`

This is the layer that prevents weak documents from reaching the council.

### 3. Role separation

Generator and reviewer have different jobs and different approval semantics.

The generator does not decide approval.
The reviewer does not silently invent requirements.

### 4. Artifact-driven continuation

`continue` must inspect what the roles actually wrote:

- pending artifacts
- invalid artifacts
- `changes_requested`
- `needs_human`
- `approved`

This avoids resuming the wrong role or wrong turn.

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

### `contract.md`

Auditable approval bar for most non-trivial work.

### Task-local `AGENTS.md`

Stable council behavior only.

It must not become a dumping ground for task-specific product requirements.

## Stable vs Customizable

### Stable

- canonical file names
- role separation
- artifact-driven transitions
- CLI shape
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

The correct stop state for documentation ambiguity is `needs_human`, not continued guessing.

## Why The Product Needs Heavy Docs

This repo is not just runtime code. It is a **behavioral system** whose quality depends on:

- how the outer agent thinks
- how docs are synthesized
- how the council interprets them
- how humans resume and customize it

That is why public docs, skill references, templates, runtime validators, and tests must all stay synchronized.
