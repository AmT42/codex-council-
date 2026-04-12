# Codex Council

Codex Council is a Codex-first harness for long-running software work.

It is designed to be operated by an outer coding agent that can inspect a target repository, choose the right task documents, and then launch or resume a generator/reviewer council inside that repository.

The current runtime lives in [`scripts/codex_tui_supervisor.py`](./scripts/codex_tui_supervisor.py). The recommended outer-agent entrypoint is the [`codex-council` skill](./skills/codex-council/SKILL.md). The agent operating manual lives in [`INSTRUCTS.md`](./INSTRUCTS.md).

This repo follows the same broad harness ideas discussed in Anthropic's [Harness design for long-running application development](https://www.anthropic.com/engineering/harness-design-long-running-apps) and OpenAI's [Harness engineering](https://openai.com/fr-FR/index/harness-engineering/): structured artifacts, explicit evaluator roles, context handoffs, and repo-embedded operating knowledge.

## What It Does

Codex Council runs a two-role loop inside a target repo:

- `generator`
  - implements or fixes the requested work
- `reviewer`
  - evaluates correctness, regressions, fidelity to intent, and test adequacy

The control plane is file-based. The council reads canonical task documents from the target repo and writes turn-scoped artifacts under `.codex-council/<task>/runs/<run_id>/`.

This is not a one-shot prompt wrapper. It is a harness for multi-turn, artifact-driven implementation and review.

## Recommended Entry Point

If an outer Codex agent has access to this repo, point it at:

- [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md)
- [`INSTRUCTS.md`](./INSTRUCTS.md)

That skill is the intended user-facing interface for v1. It teaches the outer agent:

- when to answer directly without running the harness
- when to scaffold `task.md`, `review.md`, `spec.md`, and `contract.md`
- when to ask blocking questions
- when to `start`
- when to prefer `status` + `continue`

If you want Codex to discover the skill as an installed skill, copy or symlink `skills/codex-council` into `$CODEX_HOME/skills/` or `~/.codex/skills/`.

## Document Model

The council workspace inside a target repo is:

```text
.codex-council/<task_name>/
  AGENTS.md
  generator.instructions.md
  reviewer.instructions.md
  task.md
  review.md
  spec.md
  contract.md
  runs/
```

Canonical documents:

- `task.md`
  - default brief for most execution requests
- `review.md`
  - findings input for debugging, review-driven work, and external comments
- `spec.md`
  - detailed design when `task.md` alone would be too ambiguous
- `contract.md`
  - default acceptance and approval checklist for most non-trivial runs
- `AGENTS.md`
  - stable council behavior only, not feature requirements

Recommended defaults for outer-agent routing:

- concrete bugfix or targeted implementation
  - `task.md` + `contract.md`
- findings-driven fix
  - `review.md` + `contract.md`
- broad feature or complex design
  - `task.md` + `spec.md` + `contract.md`
- meta question about the harness
  - answer directly, do not scaffold docs

## Quickstart

### Outer-agent workflow

1. The outer agent reads [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md).
2. It classifies the user request.
3. It creates or updates the minimal required task documents.
4. It starts or continues the harness with the existing CLI.

### Manual fallback

From a target repository:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py init my-task
```

Then write the docs you need:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write task my-task --body "Debug why sync duplicates rows."
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py write contract my-task --body "The duplication bug is reproduced and fixed."
```

Start the council:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py start my-task
```

Inspect or resume later:

```bash
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py status my-task
python3 /path/to/council-agent/scripts/codex_tui_supervisor.py continue my-task
```

## CLI Overview

The current public CLI stays unchanged:

- `init`
  - scaffold `.codex-council` and a task workspace
- `write`
  - replace one canonical task document
- `start`
  - launch a new council run
- `status`
  - inspect the latest or chosen run
- `continue`
  - resume the latest valid run in place

The outer-agent skill should orchestrate those commands rather than inventing a parallel interface.

## Runtime Notes

The TUI supervisor:

- resolves the target directory to its git root by default
- launches generator and reviewer `codex` sessions in `tmux`
- writes role-scoped prompts, messages, statuses, and terminal summaries per turn
- advances turns only when the expected artifact pairs exist and validate
- prefers artifact-driven `continue` over stale run metadata
- can bootstrap from forked session context when local task docs are missing

`continue` is the intended path after:

- editing `task.md`, `review.md`, `spec.md`, `contract.md`, or role instructions
- a `needs_human` pause
- a `changes_requested` reviewer verdict
- a stopped session whose validated artifacts still exist

## Which Doc Should I Use?

- Use `task.md` for most concrete execution requests.
- Use `review.md` when the user gives findings, logs, repro notes, or review comments.
- Add `spec.md` only when a plain task brief would still leave meaningful implementation ambiguity.
- Default to `contract.md` for non-trivial work so the reviewer has an auditable approval bar.
- Keep task-local `AGENTS.md` stable and behavioral.

Detailed routing, synthesis rules, examples, and anti-patterns live in [`INSTRUCTS.md`](./INSTRUCTS.md) and the skill reference pack under [`skills/codex-council/references/`](./skills/codex-council/references/).

## Repository Layout

```text
templates/
  scaffold/
    council_root.gitignore
    config.toml
    task.md
    review.md
    spec.md
    contract.md
    AGENTS.md
    generator.instructions.md
    reviewer.instructions.md
  prompts/
    generator_initial.md
    generator_followup.md
    reviewer_initial.md
    reviewer_followup.md
    reviewer_fork_bootstrap.md
    artifact_repair.md
  data/
    critical_review_dimensions.json
skills/
  codex-council/
    SKILL.md
    references/
scripts/
  codex_tui_supervisor.py
tests/
  test_codex_tui_supervisor.py
```

## Maintainer Note

Repo-root [`AGENTS.md`](./AGENTS.md) is maintainer guidance for agents modifying this harness.

Consumer-facing guidance for agents using the harness lives in:

- [`INSTRUCTS.md`](./INSTRUCTS.md)
- [`skills/codex-council/SKILL.md`](./skills/codex-council/SKILL.md)
