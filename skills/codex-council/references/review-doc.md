# `review.md`

## When to use it

Use `review.md` when the input is already shaped like findings or debugging evidence.

Typical triggers:

- code review comments
- QA findings
- logs with an identified problem
- bug-analysis notes
- a debugging handoff

GitHub PR Codex Bridge exception:

- for GitHub PR Codex Bridge, omit `review.md` by default
- create or use `review.md` only when the user explicitly requests a local Council brief or the internal generator/reviewer loop
- when findings already live on the PR, the PR bridge materializes them into turn-scoped GitHub review input artifacts instead of canonical `review.md`
- `review.md` is canonical findings input for the Normal Internal Council; it is not `turns/.../reviewer/message.md`, it is not the GitHub PR review source in `github_pr_codex`, and it is not the place for broad product requirements

## Writing rules

Under `## Findings`:

- list concrete issues
- keep one finding per bullet when possible
- describe the observable problem or code-level mismatch
- if relevant, say whether the issue is:
  - wrong user-facing path
  - wrong maintenance/background path
  - wrong substitution between the two

Under `## Context`:

- add logs, repro steps, stack traces, links, or code references
- include only supporting detail that makes the findings easier to validate

## Quality bar

A good `review.md` should give the generator enough signal to triage findings as `agree`, `disagree`, or `uncertain`.

Weak findings:

- “fix this”
- “still broken”
- “make it robust”

Strong findings:

- describe the behavior mismatch
- mention likely surfaces
- point at the repro or evidence
- make it clear when the code implements a nearby helper/maintenance path but misses the primary user intent
- distinguish observed fact from inferred cause when the issue involves a blocker, stall, or timeout
- prefer the narrowest justified blocker wording rather than naming a guessed root cause

## Good defaults

- Phrase findings as issues to investigate or fix, not unquestionable truth.
- Avoid mixing broad product requirements into `review.md`.
- Pair `review.md` with `contract.md` for most non-trivial runs.
- Add `task.md` only if the generator would otherwise lack a useful short brief.
- Prefer product-sanity findings over purely architectural vibes when a simple user workflow should obviously work.

## Example seed

```markdown
# Review

## Findings

- Retry handling in the sync path appears to re-insert rows that were already persisted during the partial-success case.
- The current regression coverage does not exercise a retry after partial success.

## Context

- Repro: run the sync job, force a network error after the first persisted row, then retry the same batch.
- Suspect area: the background sync worker and any deduplication or checkpoint logic around batch retries.
```
