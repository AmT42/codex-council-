# Spec–Contract Linking Example

This file is the local worked example for the task workspace.

Use it as the canonical mental model for broad/spec-driven work inside a real council task.

Core rule:

- `spec.md` is the full execution truth
- each major spec section should contain acceptance criteria
- `contract.md` is the approval projection of that spec
- each major spec section should have its own top-level contract checkbox
- each acceptance criterion should be cited in `contract.md` as a matching `M#.A#` sub-check
- a top-level contract checkbox is only checkable if all linked acceptance sub-checks are satisfied

---

## Bad pattern

Too-shallow spec:

```md
## Desired Behavior

- memory_write should support add/replace/remove
- promotion should be LLM-driven
- prompt injection should work
```

Too-generic contract:

```md
- [ ] memory_write works
- [ ] promotion works
- [ ] memory is injected
```

Why this is bad:

- no named major sections
- no section-level acceptance criteria
- reviewer has to guess what “works” means
- contract is too generic to justify approval

---

## Good `spec.md` shape

For broad/spec-driven work, organize the spec into major sections such as `M1`, `M2`, `M3`.

Each major section should include:

- intended behavior and boundaries
- constraints for that slice
- `### Acceptance Criteria` labeled `A1`, `A2`, `A3`, and so on

Example:

```md
# Spec

## Goal

Replace the current deterministic shared-memory promotion model with a clearer two-tier memory lifecycle.

## User Outcome

The user can write durable memory intentionally, curated memory stays compact, and the top-level agent receives bounded memory context automatically.

## M1. Memory Write Semantics

`memory_write` keeps the same tool name for compatibility, but supports:

- `add`
- `replace`
- `remove`

The runtime must fail closed on ambiguity. The visible markdown body must stay human-readable and must not expose internal bookkeeping ids.

### Acceptance Criteria
- A1. `add` appends a plain markdown durable note into today’s daily memory file.
- A2. `replace` updates the uniquely resolved target and fails closed on ambiguous `match_text`.
- A3. `remove` deletes the uniquely resolved target and fails closed on ambiguous `match_text`.
- A4. The tool description clearly explains when to use `add`, `replace`, and `remove`.
- A5. Regression coverage exists for `add`, `replace`, `remove`, and ambiguity failure.

## M2. Daily And Curated Memory Lifecycle

Daily memory and curated memory remain separate:

- new notes land in `memory/YYYY-MM-DD.md`
- curated long-term memory lives in `MEMORY.md`
- promotion rewrites curated memory only

### Acceptance Criteria
- A1. New durable notes land in the daily file, not directly in `MEMORY.md`.
- A2. `MEMORY.md` is rewritten only through intended curation or edit paths.
- A3. Daily memory and curated memory remain plain human-readable markdown.
- A4. Hidden bookkeeping metadata does not appear in visible markdown bodies.
- A5. Curated memory rewrites are atomic.

## M3. Promotion Behavior

Promotion is LLM-driven, change-aware, and safe on failure.

It uses:

- current `MEMORY.md`
- changed eligible daily-memory notes

### Acceptance Criteria
- A1. Promotion uses current curated memory plus changed eligible daily notes.
- A2. Promotion respects the bounded cadence and change-detection rules.
- A3. Promotion failure leaves `MEMORY.md` unchanged.
- A4. Failed promotion does not falsely mark notes as promoted.
- A5. Promotion success records the intended bookkeeping state for later retries or digests.

## M4. Prompt Injection Scope And Limits

Automatic memory injection applies to the top-level EVE agent path only.

### Acceptance Criteria
- A1. The main top-level agent receives bounded memory injection from curated plus recent daily memory.
- A2. Delegated sub-agents do not receive shared memory by default.
- A3. Background maintenance paths do not receive shared memory by default.
- A4. Curated-memory and daily-memory caps are explicit and deterministic.
- A5. Daily-memory truncation is recency-preserving and regression-covered.

## M5. Durable Retrieval Compatibility

The new markdown memory files must remain retrieval-friendly for `fs_search` and `fs_get`.

### Acceptance Criteria
- A1. `fs_search` can recall both curated and daily memory after the redesign.
- A2. Searchable content remains semantic and human-readable.
- A3. Metadata noise is not reintroduced into searchable content.

## M6. Validation And Branch Quality

This task is not approvable only because the feature exists. It must also be validated and subsystem-clean.

### Acceptance Criteria
- A1. Targeted validation exists for write, replace/remove, promotion cadence, injection scope, and durable retrieval.
- A2. Required targeted validation is passing.
- A3. The touched subsystem is clean enough for approval: no known adjacent regression remains in the changed runtime or tool paths.
```

---

## Good `contract.md` shape

Now derive the contract from every major spec section.

```md
# Definition of Done

- [ ] M1. Memory Write Semantics
  - [ ] M1.A1 `add` appends a plain markdown durable note into today’s daily memory file.
  - [ ] M1.A2 `replace` updates the uniquely resolved target and fails closed on ambiguous `match_text`.
  - [ ] M1.A3 `remove` deletes the uniquely resolved target and fails closed on ambiguous `match_text`.
  - [ ] M1.A4 The tool description clearly explains when to use `add`, `replace`, and `remove`.
  - [ ] M1.A5 Regression coverage exists for `add`, `replace`, `remove`, and ambiguity failure.
- [ ] M2. Daily And Curated Memory Lifecycle
  - [ ] M2.A1 New durable notes land in the daily file, not directly in `MEMORY.md`.
  - [ ] M2.A2 `MEMORY.md` is rewritten only through intended curation or edit paths.
  - [ ] M2.A3 Daily memory and curated memory remain plain human-readable markdown.
  - [ ] M2.A4 Hidden bookkeeping metadata does not appear in visible markdown bodies.
  - [ ] M2.A5 Curated memory rewrites are atomic.
- [ ] M3. Promotion Behavior
  - [ ] M3.A1 Promotion uses current curated memory plus changed eligible daily notes.
  - [ ] M3.A2 Promotion respects the bounded cadence and change-detection rules.
  - [ ] M3.A3 Promotion failure leaves `MEMORY.md` unchanged.
  - [ ] M3.A4 Failed promotion does not falsely mark notes as promoted.
  - [ ] M3.A5 Promotion success records the intended bookkeeping state for later retries or digests.
- [ ] M4. Prompt Injection Scope And Limits
  - [ ] M4.A1 The main top-level agent receives bounded memory injection from curated plus recent daily memory.
  - [ ] M4.A2 Delegated sub-agents do not receive shared memory by default.
  - [ ] M4.A3 Background maintenance paths do not receive shared memory by default.
  - [ ] M4.A4 Curated-memory and daily-memory caps are explicit and deterministic.
  - [ ] M4.A5 Daily-memory truncation is recency-preserving and regression-covered.
- [ ] M5. Durable Retrieval Compatibility
  - [ ] M5.A1 `fs_search` can recall both curated and daily memory after the redesign.
  - [ ] M5.A2 Searchable content remains semantic and human-readable.
  - [ ] M5.A3 Metadata noise is not reintroduced into searchable content.
- [ ] M6. Validation And Branch Quality
  - [ ] M6.A1 Targeted validation exists for write, replace/remove, promotion cadence, injection scope, and durable retrieval.
  - [ ] M6.A2 Required targeted validation is passing.
  - [ ] M6.A3 The touched subsystem is clean enough for approval: no known adjacent regression remains in the changed runtime or tool paths.
```

Important:

- this is not a copy of the whole spec
- this is not a shallow “it works” checklist
- it is a short approval projection of the spec with explicit citations for every acceptance criterion

---

## Mapping rule

Reviewer rule:

- `M1` is checkable only if `M1.A1` through `M1.A5` all pass
- `M2` is checkable only if `M2.A1` through `M2.A5` all pass
- `M3` is checkable only if `M3.A1` through `M3.A5` all pass
- `M4` is checkable only if `M4.A1` through `M4.A5` all pass
- `M5` is checkable only if `M5.A1` through `M5.A3` all pass
- `M6` is checkable only if `M6.A1` through `M6.A3` all pass

This is the key rule:

> A contract item is only checkable if all linked acceptance criteria in `spec.md` are satisfied and all cited `M#.A#` sub-checks are checked.

---

## Regression example

Turn 1:

- `M5` retrieval compatibility is satisfied
- `M5.A1`, `M5.A2`, and `M5.A3` are all satisfied
- `regression_risk = pass`

Turn 2:

- a later change reintroduces metadata noise into the model-facing retrieval payload
- retrieval still “kind of works,” but no longer satisfies the spec cleanly

Correct reviewer behavior:

- `M5.A3` becomes `[ ]` again
- `M5` becomes `[ ]` again
- `regression_risk` becomes `fail`
- approval must be withheld

That is healthy review behavior. Contract items and review dimensions are recomputed from current branch state, not inherited as sticky green checkmarks.
