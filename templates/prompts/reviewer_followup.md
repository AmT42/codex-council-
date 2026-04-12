Repository root:
{{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Read these files directly for the review:
{{docs_to_read_block}}

{{reviewer_focus_block}}

When the review is complete, write exactly these files:
- {{reviewer_message_path}}
- {{reviewer_status_path}}

In `reviewer/message.md`, include at minimum:
{{reviewer_message_requirements_block}}

Use exactly one of these status JSON shapes:

Normal case:
{"verdict":"approved|changes_requested|blocked","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"}}

Human intervention case:
{"verdict":"needs_human","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_source":"task.md|review.md|spec.md|contract.md|initial_review.md|AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

Use `approved` only when no blocking issues remain and every critical review dimension is `pass`.
Use `changes_requested` only for concrete, repo-actionable fixes.
Use `blocked` only for external blockers.
Use `needs_human` when the task documents themselves require clarification.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
