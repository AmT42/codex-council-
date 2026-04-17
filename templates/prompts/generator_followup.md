Repository root:
{{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Read these files directly before coding:
{{docs_to_read_block}}

{{review_bridge_block}}

Before making changes, read the previous reviewer artifacts carefully:
- {{previous_reviewer_message_path}}
- {{previous_reviewer_status_path}}

{{previous_reviewer_focus_block}}

{{generator_objective_block}}

Preserve the primary user-facing path described in the task documents. Do not treat a maintenance, helper, curation, migration, or repair path as an acceptable replacement unless the docs explicitly say so.
If you hit a blocker, diagnose by evidence rather than by symptom-shaped guesses. State the last confirmed progress point, the first unconfirmed next step, and the direct observation supporting your blocker wording. Use the narrowest proven claim.

If you changed repo-tracked files in this turn, create a git commit before writing the generator artifacts for this turn.

When the implementation is complete, write exactly these files:
- {{generator_message_path}}
- {{generator_status_path}}

In `generator/message.md`, include at minimum:
{{generator_message_requirements_block}}

Use exactly one of these status JSON shapes:

Normal case:
{"result":"implemented|no_changes_needed|blocked","summary":"short string","changed_files":["relative/path"]}

Human intervention case:
{"result":"needs_human","summary":"short string","changed_files":["relative/path"],"human_source":"task.md|review.md|spec.md|contract.md|initial_review.md|AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
