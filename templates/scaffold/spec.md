# Spec

Use this file only when the task needs deeper structure than `task.md`.

Reach for `spec.md` when the work spans multiple surfaces, needs explicit in-scope and out-of-scope boundaries, or would otherwise be too ambiguous to execute safely from a short task brief.

For most non-trivial spec-driven tasks, keep `contract.md` alongside this file so approval stays auditable.

## Goal

Describe the main thing that should be built or changed.

## User Outcome

Describe what a user, operator, or stakeholder should be able to do or observe when the work is complete.

## In Scope

List the behavior, systems, or surfaces that are part of this request.

## Out of Scope

List things that should not be changed in this task, even if they seem related.

## Constraints

List important limits or requirements.

## Existing Context

Describe the current product or technical context the council should know.

## Desired Behavior

Describe the required behavior in concrete terms.

### Primary User Path / Intents

State the main user-facing intent or workflow this task must satisfy. If this does not apply, write `Not applicable because ...`.

### Maintenance / Background Paths

State any maintenance, background, curation, migration, or repair paths that support the main behavior. If this does not apply, write `Not applicable because ...`.

### Forbidden Substitutions

State any nearby paths that must not be treated as replacements for the primary user-facing path. If this does not apply, write `Not applicable because ...`.

### Source of Truth / Ownership

State which data, docs, services, or systems are authoritative for this work, who writes them, and what is derived or cached. If this dimension truly does not apply, write `Not applicable because ...`.

### Read Path

Describe how the relevant state or inputs are read at runtime or during execution. Name the important interfaces, lookups, or retrieval paths. If this dimension truly does not apply, write `Not applicable because ...`.

### Write Path / Mutation Flow

Describe how state changes are persisted or emitted, including important side effects, sequencing, and idempotency expectations. If this dimension truly does not apply, write `Not applicable because ...`.

### Runtime / Performance Expectations

Describe important hot-path, background, latency, batching, caching, or cost expectations that the implementation must respect. If this dimension truly does not apply, write `Not applicable because ...`.

### Failure / Fallback / Degraded Behavior

Describe what should happen on partial failure, unavailable dependencies, stale state, or degraded mode. Name any fallback behavior explicitly. If this dimension truly does not apply, write `Not applicable because ...`.

### State / Integrity / Concurrency Invariants

Describe the invariants that must stay true across retries, restarts, overlapping work, migrations, caches, metadata, or concurrent execution. If this dimension truly does not apply, write `Not applicable because ...`.

### Observability / Validation Hooks

Describe what must be testable, inspectable, or measurable so the reviewer can verify the implementation without guessing. If this dimension truly does not apply, write `Not applicable because ...`.

### Prompt / System Design Implications

If prompts, instruction layers, or system-design text materially shape runtime behavior, describe what they must and must not imply. If this dimension truly does not apply, write `Not applicable because ...`.

When relevant, make explicit:

- what the model should do
- what the model must not guess
- what the prompt/runtime combination must force or forbid
- what user-visible behavior would be wrong even if internal helpers appear to work

## Technical Boundaries

Describe known technical boundaries, touched areas, interfaces, or architectural preferences.

## Validation Expectations

Describe how the work should be validated.

## Open Questions

List anything that is still undecided or ambiguous.
