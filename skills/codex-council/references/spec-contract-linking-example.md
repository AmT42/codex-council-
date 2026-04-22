# Spec–Contract Linking Example

This example shows the intended relationship between:

- `spec.md`
- section-level acceptance criteria
- `contract.md`
- reviewer approval

Use this as the canonical mental model for broad/spec-driven work.

---

## Core rule

For broad/spec-driven work:

- `spec.md` is the full execution truth
- each major spec section should contain acceptance criteria
- `contract.md` is the approval projection of that spec
- each major spec section should have its own top-level contract checkbox
- each acceptance criterion should be cited in `contract.md` as a matching `M#.A#` sub-check
- a top-level contract checkbox is only checkable if **all linked acceptance sub-checks** are satisfied

This means:

- `spec.md` answers: what does “done right” mean?
- `contract.md` answers: what must be true right now to approve the branch?

---

## Bad pattern

### Too-shallow spec

```md
## Desired Behavior

- memory_write should support add/replace/remove
- promotion should be LLM-driven
- prompt injection should work
```

Why this is bad:

- no named major sections
- no section-level acceptance criteria
- reviewer has to guess what “work” means

### Too-generic contract

```md
- [ ] memory_write works
- [ ] promotion works
- [ ] memory is injected
```

Why this is bad:

- too broad to justify approval
- no traceability to the spec
- reviewer can mark items done while important sub-behaviors are still weak or missing

---

## Good `spec.md` shape

Below is the recommended pattern.

Each major section:

- has an id like `M1`, `M2`, `M3`
- explains the intended behavior and boundaries
- includes labeled acceptance criteria for that section

### Example

```md
# Spec

## Goal

Replace the current deterministic shared-memory promotion model with a clearer two-tier memory lifecycle.

## User Outcome

The user can write durable memory intentionally, curated memory stays compact, and the top-level agent receives bounded memory context automatically.

## M1. Memory Write Semantics

`memory_write` keeps the same tool name for compatibility, but supports three actions:

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

It must not re-run when nothing relevant changed.

### Acceptance Criteria
- A1. Promotion uses current curated memory plus changed eligible daily notes.
- A2. Promotion respects the bounded cadence and change-detection rules.
- A3. Promotion failure leaves `MEMORY.md` unchanged.
- A4. Failed promotion does not falsely mark notes as promoted.
- A5. Promotion success records the intended bookkeeping state for later retries/digests.

## M4. Prompt Injection Scope And Limits

Automatic memory injection applies to the top-level EVE agent path only.

It injects:

- bounded curated memory
- bounded recent daily memory

It must not inject the same memory by default into delegated sub-agents or background maintenance flows.

### Acceptance Criteria
- A1. The main top-level agent receives bounded memory injection from curated + recent daily memory.
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
- A3. The touched subsystem is clean enough for approval: no known adjacent regression remains in the changed runtime/tool paths.
```

---

## Good `contract.md` shape

Now derive the contract from **every major spec section**.

This contract is intentionally much shorter than the spec, but it still cites every acceptance criterion explicitly.

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
  - [ ] M3.A5 Promotion success records the intended bookkeeping state for later retries/digests.
- [ ] M4. Prompt Injection Scope And Limits
  - [ ] M4.A1 The main top-level agent receives bounded memory injection from curated + recent daily memory.
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
  - [ ] M6.A3 The touched subsystem is clean enough for approval: no known adjacent regression remains in the changed runtime/tool paths.
```

Important:

- this is **not** a copy of the whole spec
- this is **not** a shallow “it works” checklist
- it is a short approval projection of the spec with explicit citations for every acceptance criterion

---

## Mapping rule

The reviewer should reason like this:

| Contract Item | Linked Spec Section(s) | Check only if |
|---|---|---|
| `M1` | `M1. Memory Write Semantics` | `M1.A1` through `M1.A5` all pass |
| `M2` | `M2. Daily And Curated Memory Lifecycle` | `M2.A1` through `M2.A5` all pass |
| `M3` | `M3. Promotion Behavior` | `M3.A1` through `M3.A5` all pass |
| `M4` | `M4. Prompt Injection Scope And Limits` | `M4.A1` through `M4.A5` all pass |
| `M5` | `M5. Durable Retrieval Compatibility` | `M5.A1` through `M5.A3` all pass |
| `M6` | `M6. Validation And Branch Quality` | `M6.A1` through `M6.A3` all pass |

This is the key rule:

> A contract item is only checkable if all linked acceptance criteria in `spec.md` are satisfied and all cited `M#.A#` sub-checks are checked.

---

## Reviewer example

### Example: feature looks present, but approval is still wrong

Suppose:

- `memory_write(add|replace|remove)` is implemented
- daily/curated lifecycle is implemented
- prompt injection exists

But:

- sub-agents still get injected memory by default
- there is no regression test for the scope exclusion

Then:

- `M1` may be `[x]`
- `M2` may be `[x]`
- `M3` may be `[x]`
- `M4.A2` must stay `[ ]`
- `M4` must stay `[ ]`
- reviewer must not approve

Why:

- the spec says more than “memory injection exists”
- it says the **correct scope** of memory injection matters

---

## Regression example

This is the most important behavior to preserve.

### Turn 1

Reviewer finds:

- `M5` retrieval compatibility is satisfied
- `M5.A1`, `M5.A2`, and `M5.A3` are all satisfied
- `regression_risk = pass`

### Turn 2

Later code changes reintroduce metadata noise into searchable content.

Now reviewer must do this:

- turn `M5.A3` from `[x]` back to `[ ]`
- turn `M5` from `[x]` back to `[ ]`
- turn `regression_risk` from `pass` to `fail`
- explain the regression explicitly

Example reviewer wording:

```md
## Regressions From Prior Turn

- `M5.A3` was previously satisfied, but the current branch reintroduces metadata noise into searchable content, so this sub-check is now unchecked.
- `M5` was previously satisfied, but the current branch reintroduces metadata noise into searchable content, so this item is now unchecked.

## Dimension Regressions

- `regression_risk` regressed from `pass` to `fail` because the touched retrieval path now has a known adjacent regression.
```

This is correct reviewer behavior.

Checklist state is **not monotonic**.
Critical dimensions are **not monotonic**.

They are recomputed from current branch state every turn.

When a previously satisfied contract point regresses, the reviewer should uncheck it again. Old checkmarks do not survive regressions.

---

## Practical authoring guidance

When writing broad/spec-driven docs:

1. Write `spec.md` first.
2. Break major behavior into named sections.
3. Put labeled acceptance criteria under each major section.
4. Write `contract.md` second.
5. Add one top-level contract checkbox per major section.
6. Add one cited `M#.A#` sub-check per acceptance criterion.
7. Make sure each contract checkbox is traceable to the spec.
7. Keep the contract short.
8. Let the reviewer check boxes by verifying the linked spec acceptance criteria.

---

## Anti-patterns

Avoid these:

### Bad

- giant spec with no acceptance criteria
- contract with vague “works”, “production-ready”, “robust”
- contract that ignores important runtime/fallback/prompt/tool guarantees in the spec
- contract with no cited `M#.A#` acceptance sub-checks
- reviewer treating a previously checked box as permanently checked

### Good

- rich spec with section-level acceptance criteria
- short contract derived from the spec with cited `M#.A#` sub-checks
- reviewer using current branch state each turn
- reviewer allowed to regress both checklist items and critical dimensions

---

## Final rule

For broad/spec-driven work:

- `spec.md` is the truth
- `contract.md` is the auditable approval projection
- reviewer checks contract by verifying linked spec acceptance criteria and the cited `M#.A#` sub-checks
- approval also requires critical dimensions to pass and branch health to be acceptable
