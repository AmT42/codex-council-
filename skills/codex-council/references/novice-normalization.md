# Novice Normalization

## Purpose

This reference exists because the hardest product problem is not session orchestration. It is turning weak user input into a strong brief.

If the user is vague, emotional, non-technical, or symptom-focused, do not treat their wording as already fit for `task.md`.

## Required extraction

Before launch, try to infer or discover:

- what behavior is failing or desired
- what surface is most likely affected
- what success would look like
- what must not regress
- what minimum verification is needed

## Signals that input is too weak

Examples:

- “it’s weird”
- “make it solid”
- “fix the import thing”
- “build a better dashboard”
- “make it production-ready”

These are not executable council briefs.

## Normalization pattern

1. Inspect the repo for the most likely surfaces.
2. Rewrite the request in concrete engineering terms.
3. Add just enough context to make the work safer.
4. Add a concrete success signal.
5. Create `contract.md` with auditable checks.
6. Decide whether the work is still too broad and needs `spec.md`.

If the user is reporting a blocker, hang, timeout, or “it got stuck” symptom:

7. rewrite the finding in evidence-first form
8. separate observed fact from inferred cause
9. preserve uncertainty when the root cause is not directly proven

If the work needs `spec.md`, do not stop at “what feature are we building?”. Normalize the request into explicit decisions about the relevant execution model too: source of truth, read/write paths, fallback behavior, runtime constraints, integrity invariants, and validation hooks when those dimensions matter.

## When to ask questions

Ask only if the missing answer would materially change:

- the target surface
- the intended behavior
- the in/out scope line
- whether this is a bugfix or a feature

Do not ask questions that repo inspection can answer.

## Good transformations

Weak:

> The import thing is broken.

Stronger:

- identify the likely import path from the repo
- describe the duplicate or failing behavior concretely
- name the likely risk surfaces
- state how success will be verified

Weak:

> Build a better workflow for approvals.

Stronger:

- write `task.md` as a short brief
- add `spec.md` for desired behavior, scope, and constraints
- add `contract.md` for auditable completion

## Failure condition

If you cannot synthesize a safe brief even after repo inspection, do not launch. Ask the smallest blocking question or stop at explanation mode.
