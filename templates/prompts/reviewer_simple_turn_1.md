Repository root:
{{repo_root}}

Turn {{turn_name}}.

Read these files directly for the review:
- {{initial_review_path}}
- {{generator_message_path}}
- {{generator_status_path}}

The generator has completed a change. Review the current repository state and these files carefully:

Your job is to detect:
- bad code
- introduced errors
- unintended behavior
- regressions
- tech debt
- clear unnecessary complexity

Also look for fragile changes that are likely to cause future errors.
If the generator explicitly disagreed with a review point, adjudicate that disagreement using code evidence.
Do not restate the same blocker without stronger evidence. If you cannot add stronger evidence, use `needs_human` instead of looping.

When the review is complete, write exactly these files:
- {{reviewer_message_path}}
- {{reviewer_status_path}}

In `reviewer/message.md`, include at minimum:
- Verdict summary
- Adjudication of generator disagreements
- Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`, one line for each of:
{{critical_review_dimensions_block}}
- Blocking issues
- Independent verification performed
- Residual risks or follow-up notes

Use exactly one of these status JSON shapes:

Normal case:
{"verdict":"approved|changes_requested|blocked","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"}}

Human intervention case:
{"verdict":"needs_human","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_source":"initial_review.md|AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

Use `approved` only when no blocking issues remain and every critical review dimension is `pass`. Use `changes_requested` when more generator work is required. Use `blocked` only for external blockers. Use `needs_human` when `initial_review.md` or the available instructions themselves require human clarification.
Use `changes_requested` only for concrete, repo-actionable fixes. If the only remaining blocker is that `initial_review.md` or the available instructions are too broad, contradictory, or non-auditable, use `needs_human` instead.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
