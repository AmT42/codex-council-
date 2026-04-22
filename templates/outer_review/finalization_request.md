Inspect the generator triage summary for outer-review cycle `{{cycle_id}}`, then revise, confirm, narrow, or clear canonical `review.md` before any next normal execution cycle starts.

Point extraction rule:
{{point_extraction_rule}}

After you finish that finalization step, run `continue {{task_name}}` so the harness can record the outer-review finalization acknowledgment artifact.

If `review.md` stays unchanged, still run `continue {{task_name}}`; unchanged text alone is not the proof artifact.

If no points remain after finalization, the reopened run will close as `closed_no_remaining_outer_findings` instead of inventing a fresh internal approval.
