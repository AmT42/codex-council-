# Review

This file is the canonical findings/review input for the council.

GitHub PR bridge note: if the work is an existing live PR and the user asked Codex Council to work on that PR, do not copy PR findings into this file by default. Prefer `start --review-mode github_pr_codex --github-pr <pr-url>` and let the PR plus current-head GitHub Codex findings drive the run.

This file is canonical findings input for the Normal Internal Council. It is not a role output like `turns/.../reviewer/message.md`, not the GitHub PR review source in `github_pr_codex`, and not a place for broad product requirements.

Use it when the work starts from:
- a bug analysis
- review findings
- external comments
- a debugging handoff

For most non-trivial findings-driven work, pair this file with `contract.md` so approval stays auditable.

## Findings

- Describe the concrete issue, finding, or blocker to fix.
- If relevant, say whether the issue is about the wrong user-facing path, the wrong maintenance/helper path, or a dangerous substitution between them.
- Prefer findings that would be visible to a serious software engineer trying one obvious smoke interaction, not only findings visible from internal architecture review.

## Context

- Optional extra context, logs, repro steps, stack traces, or links.
