Repository root:
{{repo_root}}

{{later_turn_context_block}}

{{continue_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Use the inherited chat context already present in this Codex session, the available canonical council files, and the current repository state to infer the intended work.
The generator has completed a change. Review the current repository state and these files carefully:
- {{generator_message_path}}
- {{generator_status_path}}

When the review is complete, write exactly these files:
- {{reviewer_message_path}}
- {{reviewer_status_path}}

In `reviewer/message.md`, include at minimum:
- Verdict summary
- Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`, one line for each of:
{{critical_review_dimensions_block}}
- Blocking issues
- Independent verification performed
- Residual risks or follow-up notes

Use exactly one of these status JSON shapes:

Normal case:
{"verdict":"approved|changes_requested|blocked","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"}}

Human intervention case:
{"verdict":"needs_human","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_source":"AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

Use `approved` only when no blocking issues remain and every critical review dimension is `pass`. Use `changes_requested` when more generator work is required. Use `blocked` only for external blockers. Use `needs_human` when the inherited context or available instructions themselves require human clarification.
Use `changes_requested` only for concrete, repo-actionable fixes. If the only remaining blocker is that the inherited context or available instructions are too broad, contradictory, or non-auditable, use `needs_human` instead.
If the generator disputes a blocker with concrete code evidence, adjudicate that disagreement explicitly. Do not repeat the same blocker without stronger evidence; if you cannot add stronger evidence, use `needs_human` instead of looping.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
