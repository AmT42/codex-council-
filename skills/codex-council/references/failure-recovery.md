# Failure Recovery

## Use this reference when

- a run paused for `needs_human`
- the user edited docs after a pause
- you are unsure whether `continue` is the right move
- the docs are too weak to justify `start`
- the supervisor died while a role session was still running

## Weak-doc failure

If the docs are not strong enough for safe execution:

- do not launch
- improve the docs first
- ask the smallest blocking question only if repo inspection cannot resolve the ambiguity

## Boundary failure

If you notice yourself drifting into “I should just build the feature directly”:

- stop
- reread `operator-boundary.md`
- return to preparing or resuming the council run

## Resume failure

If a task workspace and run already exist:

1. inspect `status`
2. inspect the current canonical docs
3. decide whether the user is still talking about the same task
4. prefer `continue` if the task and run still match

## Supervisor-death failure

If the supervisor died mid-run:

- do not assume the generator or reviewer stopped too
- inspect `status` and especially `derived_continuation`
- if the artifacts show a clear next role, recover with `continue`
- when restarting orchestration, keep the new supervisor process alive

## Human intervention failure

If the runtime or reviewer previously emitted `needs_human`:

- inspect the cited source file
- update the canonical docs or gather the missing clarification
- continue the run in place rather than starting a new one unless the user truly wants a fresh task

## Broad-input failure

If the user keeps describing a broad aspiration instead of an executable change:

- stop trying to squeeze it into `task.md`
- promote to `spec.md`
- keep `contract.md` explicit and auditable

## Recovery summary

When recovering, explain briefly:

- what went wrong
- what doc or state you inspected
- whether you are about to fix the docs, answer directly, or `continue`
