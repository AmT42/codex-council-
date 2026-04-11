Repository root:
{{repo_root}}

{{continue_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Read these files directly before materializing the local review:
{{docs_to_read_block}}

{{bootstrap_review_block}}

When the bootstrap review is complete, write exactly these files:
- {{reviewer_message_path}}
- {{reviewer_status_path}}

In `reviewer/message.md`, include at minimum:
- Bootstrap summary
- Why the distilled review is the right local source of truth for the next generator turn
- Files, repos, logs, or code paths inspected
- Open uncertainties or reasons for `needs_human`

Use exactly one of these status JSON shapes:

Normal case:
{"verdict":"changes_requested|blocked","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"}}

Human intervention case:
{"verdict":"needs_human","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_source":"task.md|review.md|spec.md|contract.md|initial_review.md|AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
