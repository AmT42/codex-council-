Repository root:
{{repo_root}}

{{turn_one_context_block}}

{{migration_warning_block}}

Turn {{turn_name}}.

Implement the requested change carefully. If the plan is critically flawed, contradictory, or unsafe to continue, emit `needs_human` instead of guessing.

When the implementation is complete, write exactly these files:
- {{generator_md_path}}
- {{generator_status_path}}

In `generator.md`, include at minimum:
- What changed
- Why those changes move the code toward satisfying `contract.md`
- Changed invariants / preserved invariants
- Downstream readers / consumers checked
- Failure modes and fallback behavior considered
- Verification performed
- Remaining contract items not yet satisfied
- Known risks or blockers

The status JSON must be exactly this shape:
{"result":"implemented|no_changes_needed|blocked|needs_human","summary":"short string","changed_files":["relative/path"],"human_message":"required when needs_human","human_source":"required when needs_human"}

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
