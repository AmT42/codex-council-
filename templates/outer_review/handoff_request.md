The internal generator/reviewer loop is recorded as approved for task `{{task_name}}` on run `{{run_id}}` turn `{{approved_turn}}`, but configured outer verification is still required.

Re-verify the whole task against the intended behavior and the current branch state before treating this branch as actually clear.

If an important blocker remains under unchanged requirements:
- update canonical `review.md`
- reopen with `--reason-kind false_approved`

If canonical docs changed after that approval instead:
- use `--reason-kind requirements_changed_after_approval`
