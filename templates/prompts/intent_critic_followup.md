Role: Intent Critic
Phase: planning review
Repo root: {{repo_root}}

{{continue_context_block}}

{{reopen_context_block}}

Turn {{turn_name}}.

Read in this order:
{{docs_to_read_block}}

{{intent_critic_focus_block}}

{{intent_critic_protocol_block}}

Mark every planning review dimension explicitly:
{{planning_dimensions_block}}

Write exactly these files:
- {{intent_critic_message_path}}
- {{intent_critic_status_path}}

In `intent_critic/message.md`, include at minimum:
{{intent_critic_message_requirements_block}}

Use the intent critic status schema documented in `intent_critic.instructions.md`.

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of the planning verdict
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn.
