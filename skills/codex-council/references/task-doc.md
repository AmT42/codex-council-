# `task.md`

## When to use it

Use `task.md` for most new execution requests.

It is the default brief for:

- concrete bugfixes
- targeted implementation work
- narrow refactors
- follow-up changes that are not naturally findings-shaped

## Writing rules

Keep it short and executable.

Fill:

- `## Request`
  - the concrete change to make
- `## Context`
  - just enough repo-specific context to act safely
- `## Success Signal`
  - what should be true when the work is done

## Good defaults

- Mention specific failing behavior, not vague aspirations.
- Include discovered constraints when they change implementation choices.
- If verification matters, say what should pass or be observable.
- Pair `task.md` with `contract.md` for most non-trivial runs.

## Escalate to `spec.md` when

- the task now spans multiple subsystems
- in/out scope boundaries matter
- the expected behavior needs structured elaboration
- non-obvious validation expectations need to be captured

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
