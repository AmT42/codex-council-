# Routing

## Primary rule

Classify the request into exactly one primary operating mode before you write files or run commands.

The correct route matters because it determines:

- whether you should answer directly
- whether you should inspect an existing run
- which canonical docs to write
- whether to ask questions
- whether to use `start`, `continue`, or `reopen`

## Mode 1: Direct answer only

Use when the user is asking about:

- how the harness works
- what a document means
- why a run paused
- what the current command surface is

Action:

- answer directly
- do not scaffold `.codex-council`
- do not run `start`, `continue`, or `reopen`

## Mode 2: Inspect or resume an existing run

Use when the user is asking for:

- current run state
- continuation after a pause or stop
- next action after editing task documents

Action:

- inspect current workspace and run state first
- prefer `status`
- prefer `continue` when the existing run is still the right one
- prefer `reopen` when the selected run is already approved but must be superseded explicitly
- avoid overwriting docs unless the repo state clearly requires it

## Mode 3: Concrete execution request

Use when the user gives a specific change that can be acted on safely.

Examples:

- debug a bug
- fix a failing path
- implement a targeted change

Default docs:

- `task.md`
- `contract.md`

Question policy:

- ask nothing unless a missing detail would materially change the implementation target

## Mode 4: Findings-driven fix

Use when the user provides:

- review comments
- findings lists
- logs
- repro notes
- debugging evidence

Default docs:

- `review.md`
- `contract.md`

Optional:

- add `task.md` only when a short brief materially clarifies what the generator should do

## Mode 5: Broad feature or spec work

Use when the request spans multiple surfaces or would be unsafe to execute from a short task brief alone.

Default docs:

- `task.md`
- `spec.md`
- `contract.md`

Question policy:

- ask only the minimum blocking questions needed to make `spec.md` and `contract.md` executable

## Route summary format

Before launch, summarize the route to the user in one short block:

- chosen mode
- docs being written
- whether questions were skipped or asked
- whether you are about to `start`, `continue`, or `reopen`

## Default hierarchy

When several modes seem plausible:

1. Direct answer only if no harness action is needed
2. Inspect or resume if a suitable run already exists
3. Findings-driven fix if the input is already review-shaped
4. Concrete execution request for specific implementation/debug work
5. Broad feature or spec work only when the work genuinely needs structured expansion
