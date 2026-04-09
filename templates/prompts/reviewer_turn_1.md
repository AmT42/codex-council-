Repository root:
{{repo_root}}

{{turn_one_context_block}}

{{migration_warning_block}}

Turn {{turn_name}}.

The generator has completed a change. Review the current repository state and these files carefully:
- {{generator_md_path}}
- {{generator_status_path}}

When the review is complete, write exactly these files:
- {{reviewer_md_path}}
- {{reviewer_status_path}}

In `reviewer.md`, include at minimum:
- Verdict summary
- Contract checklist copied from `contract.md`, using `[x]` and `[ ]`
- Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`, one line for each of:
{{critical_review_dimensions_block}}
- Blocking issues
- Independent verification performed
- Residual risks or follow-up notes

The status JSON must be exactly this shape:
{"verdict":"approved|changes_requested|blocked|needs_human","summary":"short string","blocking_issues":["issue"],"critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_message":"required when needs_human","human_source":"required when needs_human"}

Use `approved` only when no blocking issues remain and every critical review dimension is `pass`. Use `changes_requested` when more generator work is required. Use `blocked` only for external blockers. Use `needs_human` when the plan or instructions themselves require user clarification.

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
