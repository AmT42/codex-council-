Role: Planner
Phase: planning
Repo root: {{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

Turn {{turn_name}}.

Read in this order:
{{docs_to_read_block}}

{{planner_objective_block}}

Write or tighten these canonical docs directly:
- {{task_path}}
- {{spec_path}}
- {{contract_path}}

Write exactly these planner artifacts:
- {{planner_message_path}}
- {{planner_status_path}}

In `planner/message.md`, include at minimum:
{{planner_message_requirements_block}}

Use the planner status schema documented in `planner.instructions.md`.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what changed in the planning docs
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn.
