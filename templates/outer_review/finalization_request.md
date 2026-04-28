Persistent outer-review audit agent: inspect the generator triage summary for outer-review cycle `{{cycle_id}}`, then revise, confirm, narrow, or clear canonical `review.md` before any next Normal Internal Council cycle starts.

Do not act as the generator, the internal reviewer, or the GitHub PR Codex Bridge, and do not make production code changes.

Point extraction rule:
{{point_extraction_rule}}

After you finish that finalization step, run:

```bash
{{continue_command}}
```

so the harness can record the outer-review finalization acknowledgment artifact.

If `review.md` stays unchanged, still run the continue command above; unchanged text alone is not the proof artifact.

If no points remain after finalization, the reopened run will close as `closed_no_remaining_outer_findings` instead of inventing a fresh internal approval.
