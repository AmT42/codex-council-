Role: Evaluator
Phase: implementation review
Repo root: {{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Read in this order:
{{docs_to_read_block}}

{{reviewer_focus_block}}

{{reviewer_protocol_block}}

Do not inherit prior checklist state or prior critical-dimension state. Reassess both from current branch state.
If a previously satisfied contract item or a previously passing dimension regressed, call it out explicitly.

Write exactly these files:
- {{reviewer_message_path}}
- {{reviewer_status_path}}

In `reviewer/message.md`, include at minimum:
{{reviewer_message_requirements_block}}

Use the evaluator status schema documented in `reviewer.instructions.md`.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
