Repository root:
{{repo_root}}

Turn {{turn_name}}.

Read these files directly before coding:
- {{initial_review_path}}
- {{agents_path}}
- {{role_instructions_path}}

Before making changes, read the previous reviewer artifacts carefully:
- {{previous_reviewer_message_path}}
- {{previous_reviewer_status_path}}

{{previous_reviewer_focus_block}}

Implement the requested fixes reliably. Do not introduce bad code, new errors, unintended behavior, regressions, tech debt, or clear unnecessary complexity while fixing the review findings.
Anticipate plausible future error cases and harden the change where reasonable.
If `initial_review.md` or the available instructions are critically flawed, contradictory, or unsafe to continue, emit `needs_human` instead of guessing.

If you changed repo-tracked files in this turn, create a git commit before writing the generator artifacts for this turn.

When the implementation is complete, write exactly these files:
- {{generator_message_path}}
- {{generator_status_path}}

In `generator/message.md`, include at minimum:
- Findings triage:
  - Agreed points
  - Disagreed points
  - Uncertain points
- What changed
- Which initial review findings or reviewer blockers were addressed
- Commit created for this turn, or explicitly say that no repo-tracked files changed
- Evidence for rejected points
- Why the changes avoid bad code, errors, unintended behavior, regressions, tech debt, and unnecessary complexity
- Anticipated future error cases and how they were handled
- Changed invariants / preserved invariants
- Downstream readers / consumers checked
- Verification performed
- Remaining open findings or risks

Use exactly one of these status JSON shapes:

Normal case:
{"result":"implemented|no_changes_needed|blocked","summary":"short string","changed_files":["relative/path"]}

Human intervention case:
{"result":"needs_human","summary":"short string","changed_files":["relative/path"],"human_source":"initial_review.md|AGENTS.md|generator.instructions.md|reviewer.instructions.md|repo_state","human_message":"short string"}

After writing the required files, print exactly:
- `COUNCIL_TERMINAL_SUMMARY_BEGIN`
- one short terminal-only summary of what happened in this turn
- `COUNCIL_TERMINAL_SUMMARY_END`

After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.
