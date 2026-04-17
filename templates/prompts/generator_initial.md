Role: Generator
Phase: implementation
Repo root: {{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Read these files directly before coding:
{{docs_to_read_block}}

{{review_bridge_block}}

{{generator_objective_block}}

Implement only the approved turn contract. Do not widen scope mid-turn.
If you hit a blocker, diagnose by evidence rather than by symptom-shaped guesses. State the last confirmed progress point, the first unconfirmed next step, and the direct observation supporting your blocker wording. Use the narrowest proven claim.

If you changed repo-tracked files in this turn, create a git commit before writing the generator artifacts for this turn.

Write exactly these files:
- {{generator_message_path}}
- {{generator_status_path}}

In `generator/message.md`, include at minimum:
{{generator_message_requirements_block}}

Use the `generator/status.json` schema documented in `generator.instructions.md`.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
