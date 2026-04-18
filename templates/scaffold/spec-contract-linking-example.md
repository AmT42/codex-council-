# Spec–Contract Linking Example

This file is the local worked example for the task workspace.

Use it as the canonical mental model for broad/spec-driven work inside a real council task.

Core rule:

- `spec.md` is the full execution truth
- each major spec section should contain acceptance criteria
- `contract.md` is the approval projection of that spec
- one contract checkbox should map to one major spec section or one approval-critical group
- a contract checkbox is only checkable if all linked acceptance criteria are satisfied

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
- `### Acceptance Criteria`

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
- `add` appends a plain markdown durable note into today’s daily memory file.
- `replace` updates the uniquely resolved target and fails closed on ambiguous `match_text`.
- `remove` deletes the uniquely resolved target and fails closed on ambiguous `match_text`.
- The tool description clearly explains when to use `add`, `replace`, and `remove`.
- Regression coverage exists for `add`, `replace`, `remove`, and ambiguity failure.

## M2. Daily And Curated Memory Lifecycle

Daily memory and curated memory remain separate:

- new notes land in `memory/YYYY-MM-DD.md`
- curated long-term memory lives in `MEMORY.md`
- promotion rewrites curated memory only

### Acceptance Criteria
- New durable notes land in the daily file, not directly in `MEMORY.md`.
- `MEMORY.md` is rewritten only through intended curation or edit paths.
- Daily memory and curated memory remain plain human-readable markdown.
- Hidden bookkeeping metadata does not appear in visible markdown bodies.
- Curated memory rewrites are atomic.

## M3. Promotion Behavior

Promotion is LLM-driven, change-aware, and safe on failure.

It uses:

- current `MEMORY.md`
- changed eligible daily-memory notes

### Acceptance Criteria
- Promotion uses current curated memory plus changed eligible daily notes.
- Promotion respects the bounded cadence and change-detection rules.
- Promotion failure leaves `MEMORY.md` unchanged.
- Failed promotion does not falsely mark notes as promoted.
- Promotion success records the intended bookkeeping state for later retries or digests.

## M4. Prompt Injection Scope And Limits

Automatic memory injection applies to the top-level EVE agent path only.

### Acceptance Criteria
- The main top-level agent receives bounded memory injection from curated plus recent daily memory.
- Delegated sub-agents do not receive shared memory by default.
- Background maintenance paths do not receive shared memory by default.
- Curated-memory and daily-memory caps are explicit and deterministic.
- Daily-memory truncation is recency-preserving and regression-covered.

## M5. Durable Retrieval Compatibility

The new markdown memory files must remain retrieval-friendly for `fs_search` and `fs_get`.

### Acceptance Criteria
- `fs_search` can recall both curated and daily memory after the redesign.
- Searchable content remains semantic and human-readable.
- Metadata noise is not reintroduced into searchable content.

## M6. Validation And Branch Quality

This task is not approvable only because the feature exists. It must also be validated and subsystem-clean.

### Acceptance Criteria
- Targeted validation exists for write, replace/remove, promotion cadence, injection scope, and durable retrieval.
- Required targeted validation is passing.
- The touched subsystem is clean enough for approval: no known adjacent regression remains in the changed runtime or tool paths.
```

---

## Good `contract.md` shape

Now derive the contract from the approval-critical parts of the spec.

```md
# Definition of Done

- [ ] M1. Memory write semantics match Spec M1, including safe ambiguity handling and regression coverage for `add`, `replace`, and `remove`.
- [ ] M2. Daily and curated memory lifecycle matches Spec M2: daily notes land in daily memory, curated memory is maintained separately, markdown remains human-readable, and visible bookkeeping fields are not reintroduced.
- [ ] M3. Promotion behavior matches Spec M3: it is LLM-driven, change-aware, bounded by cadence, and safe on failure.
- [ ] M4. Prompt injection behavior matches Spec M4: bounded memory injection applies to the top-level agent only, with the specified scope and truncation rules.
- [ ] M5. Durable retrieval remains correct under the redesign: `fs_search` can recall the redesigned memory files cleanly without metadata noise.
- [ ] M6. Validation and branch quality gate: the targeted validation defined by Spec M6 is present and passing, and the touched subsystem is clean enough for approval.
```

Important:

- this is not a copy of the whole spec
- this is not a shallow “it works” checklist
- it is a short approval projection of the spec

---

## Mapping rule

Reviewer rule:

- `M1` is checkable only if all `M1` acceptance criteria pass
- `M2` is checkable only if all `M2` acceptance criteria pass
- `M3` is checkable only if all `M3` acceptance criteria pass
- `M4` is checkable only if all `M4` acceptance criteria pass
- `M5` is checkable only if all `M5` acceptance criteria pass
- `M6` is checkable only if all `M6` acceptance criteria pass

This is the key rule:

> A contract item is only checkable if all linked acceptance criteria in `spec.md` are satisfied.

---

## Regression example

Turn 1:

- `M5` retrieval compatibility is satisfied
- `regression_risk = pass`

Turn 2:

- a later change reintroduces metadata noise into the model-facing retrieval payload
- retrieval still “kind of works,” but no longer satisfies the spec cleanly

Correct reviewer behavior:

- `M5` becomes `[ ]` again
- `regression_risk` becomes `fail`
- approval must be withheld

That is healthy review behavior. Contract items and review dimensions are recomputed from current branch state, not inherited as sticky green checkmarks.
