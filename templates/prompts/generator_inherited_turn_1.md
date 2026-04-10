Repository root:
{{repo_root}}

{{turn_one_context_block}}

{{continue_context_block}}

{{fork_context_block}}

Turn {{turn_name}}.

Use the inherited chat context already present in this Codex session, the available canonical council files, and the current repository state to infer the requested work.
Implement the requested change carefully. If the inherited context or available instructions are critically flawed, contradictory, or unsafe to continue, emit `needs_human` instead of guessing.

If you changed repo-tracked files in this turn, create a git commit before writing the generator artifacts for this turn.

When the implementation is complete, write exactly these files:
- {{generator_message_path}}
- {{generator_status_path}}

In `generator/message.md`, include at minimum:
- What changed
- Commit created for this turn, or explicitly say that no repo-tracked files changed
- Why those changes are the right response to the inherited context and current repository state
- Changed invariants / preserved invariants
- Downstream readers / consumers checked
- Failure modes and fallback behavior considered
- Verification performed
- Remaining open questions or unverified areas
- Known risks or blockers

Use exactly one of these status JSON shapes:

Normal case:
{"result":"implemented|no_changes_needed|blocked","summary":"short string","changed_files":["relative/path"]}

Human intervention case:
{"result":"needs_human","summary":"short string","changed_files":["relative/path"],"human_source":"AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
