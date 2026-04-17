# `task.md`

## When to use it

Use `task.md` for most new execution requests.

It is the default brief for:

- concrete bugfixes
- targeted implementation work
- narrow refactors
- follow-up changes that are not naturally findings-shaped

`github_pr_codex` exception:

- when the operator already has an existing PR and wants the live PR review loop to drive the work, `task.md` can be omitted if the PR plus current-head review findings already provide a concrete brief

Planning-stage note:

- for broad, vague, or agentic work, prefer authoring `task.md` through the planning stage rather than drafting it ad hoc
- once the planning-stage critic approves the task brief, treat it as the locked execution summary rather than reopening intent casually during coding

## Writing rules

Keep it short and executable.

Fill:

- `## Request`
  - the concrete change to make
- `## Context`
  - just enough repo-specific context to act safely
- `## Success Signal`
  - what should be true when the work is done

When the task involves workflows, automation, memory, prompts, or maintenance behavior, also make clear in `task.md` which path is the **primary user-facing path** and which nearby paths are only supporting mechanisms.

## Quality bar

A good `task.md` should let the generator start confidently without inventing missing product intent.

It should:

- name the actual behavior, not just a vibe
- identify relevant surfaces or constraints when known
- say what success means in observable terms

## Good defaults

- Mention specific failing behavior, not vague aspirations.
- Include discovered constraints when they change implementation choices.
- If verification matters, say what should pass or be observable.
- Pair `task.md` with `contract.md` for most non-trivial runs.
- If the request is about a user capability, name the path that must satisfy that capability instead of assuming any adjacent helper path is good enough.
- If prompts, system instructions, tool descriptions, or schemas are part of the real product surface, name that explicitly in the brief.

## Escalate to `spec.md` when

- the task spans multiple subsystems
- in/out scope boundaries matter
- the expected behavior needs structured elaboration
- non-obvious validation expectations need to be captured
- the request contains broad feature language instead of a narrow implementation target

## Example seed

```markdown
# Task

## Request

Debug why the sync job duplicates rows when a retry happens after partial success.

## Context

- The issue appears in the background sync path, not the manual import flow.
- Preserve the current public API and stored data model unless the fix requires a schema change.
- Reproduce the bug before claiming it is fixed.

## Success Signal

The retry path no longer creates duplicate rows, the intended row still syncs successfully, and the relevant verification passes.
```
