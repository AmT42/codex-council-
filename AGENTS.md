# Codex Council Repo Guide

This repository is the implementation of the `codex-council` harness itself.

If you are working in this repo, you are usually changing the harness, not the target project being reviewed or implemented.

## What This Repo Is

- This repo runs a two-role Codex council:
  - `generator`
  - `reviewer`
- The main runtime is `scripts/codex_tui_supervisor.py`.
- The human-facing scaffold and prompt text lives in `templates/`.
- The test suite is `tests/test_codex_tui_supervisor.py`.

## Canonical Model

The council workspace inside a target repo is:

- `.codex-council/<task_name>/task.md`
  - canonical **Feature Spec**
- `.codex-council/<task_name>/contract.md`
  - canonical **Definition of Done**
- `.codex-council/<task_name>/AGENTS.md`
  - canonical **Council Brief**
- `.codex-council/<task_name>/generator.instructions.md`
  - generator-specific additions
- `.codex-council/<task_name>/reviewer.instructions.md`
  - reviewer-specific additions

Do not blur these roles.

- `task.md` is where feature requirements belong.
- `contract.md` is checklist-only and must stay auditable.
- `AGENTS.md` is for stable council behavior, not product requirements.

## Runtime Model

- `init` scaffolds the repo-local council workspace.
- `start` launches a new run.
- `continue` resumes an existing run in place.
- `status` shows run state.

Each run writes role-scoped turn artifacts under:

- `turns/<turn>/generator/`
- `turns/<turn>/reviewer/`

Important runtime files:

- `turns/<turn>/turn.json`
- `turns/<turn>/context_manifest.json`
- `turns/<turn>/<role>/prompt.md`
- `turns/<turn>/<role>/message.md`
- `turns/<turn>/<role>/status.json`
- `turns/<turn>/<role>/raw_final_output.md`

## Source Of Truth Rules

- Artifact files are the control plane.
- `state.json` is informational and cached; it must not outrank actual turn artifacts.
- `continue` must route from the latest validated artifacts, not from stale run status alone.
- Prompt examples, template text, runtime validators, and artifact filenames must stay synchronized.

## Prompt And Trace Rules

- Human-facing prompt/scaffold text belongs in `templates/`, not as long inline Python constants.
- `message.md` is the authoritative structured role deliverable.
- `raw_final_output.md` is trace-only.
- `raw_final_output.md` must not duplicate `message.md` and must not contain pasted prompt text or mixed tool trace when avoidable.

## What To Avoid

- Do not modify external target repos while working on this harness unless the user explicitly asks for that.
- Do not treat test repos like `/Users/amt42/projects/test-git` as part of this repo.
- Do not put feature requirements into scaffold `AGENTS.md`.
- Do not accept vague `contract.md` language as sufficient definition of done.
- Do not keep `changes_requested` alive for non-auditable business aspirations; that should become `needs_human`.
- Do not let invalid artifacts silently time out if they can be surfaced or repaired.
- Do not change runtime behavior without updating templates and tests in the same batch.

## Current Design Expectations

- `task.md` is titled `# Feature Spec`.
- `contract.md` is titled `# Definition of Done`.
- `start` lint-checks both spec structure and DoD quality before launching.
- `continue` is artifact-driven and session-aware.
- If a live tmux role session exists, prefer reusing it.
- If the tmux session is gone, prefer resuming the same Codex conversation when a tracked session id is available.

## Working Style In This Repo

- Keep changes surgical and behavior-driven.
- Prefer improving the harness model over patching one-off symptoms.
- When changing continuation, artifact, or prompt behavior, think through all role/turn states, not only the user’s immediate example.
- If you add a new runtime rule, add or update tests for it.
