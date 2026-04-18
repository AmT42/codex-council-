# Failure Recovery

## Use this reference when

- a run paused for `needs_human`
- the user edited docs after a pause
- you are unsure whether `continue` is the right move
- the docs are too weak to justify `start`
- the supervisor died while a role session was still running
- an approved run was wrong or the canonical docs changed after approval

## Weak-doc failure

If the docs are not strong enough for safe execution:

- do not launch
- route broad, vague, or agentic work back through the planning stage before locking execution docs
- prefer `prepare` rather than trying to squeeze broad work into weak execution docs
- improve the docs first
- ask the smallest blocking question only if repo inspection cannot resolve the ambiguity

## Boundary failure

If you notice yourself drifting into “I should just build the feature directly”:

- stop
- reread `operator-boundary.md`
- return to preparing or resuming the council run

## Resume failure

If a task workspace and run already exist:

1. inspect `status` or `status --planning`
2. inspect the current canonical docs
3. decide whether the user is still talking about the same task
4. prefer `prepare` for planning runs if the planning task still matches
5. prefer `continue` for execution runs if the execution task still matches

## Supervisor-death failure

If the supervisor died mid-run:

- do not assume the generator/reviewer or planner/intent-critic stopped too
- inspect `status` or `status --planning`, especially `derived_continuation`
- if the artifacts show a clear next role, recover with `continue` for execution runs or `prepare` for planning runs
- when restarting orchestration, keep the new supervisor process alive
- if you are not going to wait in the foreground, relaunch that supervisor command inside a dedicated `tmux` session rather than another transient outer-agent shell

## Superseded-approval failure

If `status` shows that the selected run is already approved, but that approval is no longer the right source of truth:

- do not use `continue`
- use `reopen` to create a fresh linked run
- use `false_approved` when the prior approval was wrong under the old intended requirements
- use `requirements_changed_after_approval` when the canonical docs changed afterward and now supersede the old approval

## Human intervention failure

If the runtime or reviewer previously emitted `needs_human`:

- inspect the cited source file
- update the canonical docs or gather the missing clarification
- resume the same planning run with `prepare` or the same execution run with `continue` rather than starting a new one unless the user truly wants a fresh task

## Blocker-diagnosis failure

If a prior run reported a blocker with a confident root-cause label, do not assume that label is true.

Instead:

1. inspect the blocker artifact
2. identify the last confirmed progress point
3. identify what direct observation actually supports
4. continue or rewrite docs using the narrowest proven claim

Prefer:

- “blocked during DB-backed fixture setup”

over:

- “Postgres is broken”

unless the latter is directly proven.

## Broad-input failure

If the user keeps describing a broad aspiration instead of an executable change:

- stop trying to squeeze it into `task.md`
- promote to `spec.md`
- keep `contract.md` explicit and auditable

## Recovery summary

When recovering, explain briefly:

- what went wrong
- what doc or state you inspected
- whether you are about to fix the docs, answer directly, `prepare`, `continue`, or `reopen`
