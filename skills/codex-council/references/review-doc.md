# `review.md`

## When to use it

Use `review.md` when the input is already shaped like findings or debugging evidence.

Typical triggers:

- code review comments
- QA findings
- logs with an identified problem
- bug-analysis notes
- a debugging handoff

`github_pr_codex` exception:

- when the findings already live on the PR and the operator is running the GitHub review loop directly, those findings may be materialized into turn-scoped GitHub review input artifacts instead of a canonical `review.md`

## Writing rules

Under `## Findings`:

- list concrete issues
- keep one finding per bullet when possible
- describe the observable problem or code-level mismatch

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

## Good defaults

- Phrase findings as issues to investigate or fix, not unquestionable truth.
- Avoid mixing broad product requirements into `review.md`.
- Pair `review.md` with `contract.md` for most non-trivial runs.
- Add `task.md` only if the generator would otherwise lack a useful short brief.

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
