Role: Planner
Phase: planning revision
Repo root: {{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

Turn {{turn_name}}.

Read in this order:
{{docs_to_read_block}}

{{planner_objective_block}}

Revise these canonical docs directly:
- {{task_path}}
- {{spec_path}}
- {{contract_path}}

Write exactly these planner artifacts:
- {{planner_message_path}}
- {{planner_status_path}}

In `planner/message.md`, include at minimum:
{{planner_message_requirements_block}}

{{planner_status_schema_block}}

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what changed in the planning docs
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn.
