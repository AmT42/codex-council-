from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_tui_supervisor.py"
SPEC = importlib.util.spec_from_file_location("codex_tui_supervisor", MODULE_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CodexTuiSupervisorTests(unittest.TestCase):
    def init_git_repo(self, repo_root: Path) -> None:
        repo_root.mkdir()
        subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True, capture_output=True, text=True)
        (repo_root / "file.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "file.txt"], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True, text=True)

    def commit_repo_changes(self, repo_root: Path, message: str = "update") -> None:
        subprocess.run(["git", "add", "."], cwd=repo_root, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo_root, check=True, capture_output=True, text=True)

    def scaffold_base_workspace(self, repo_root: Path, task_name: str = "demo-task") -> Path:
        MODULE.scaffold_council_root(repo_root)
        task_root = MODULE.task_root_for(repo_root, task_name)
        MODULE.scaffold_task_root(task_root, initial_task_text=None)
        return task_root

    def build_council_config(self) -> dict:
        return {
            "codex": {
                "model": "gpt-5.4",
                "model_reasoning_effort": "xhigh",
                "dangerously_bypass_approvals_and_sandbox": True,
                "no_alt_screen": True,
            },
            "council": {
                "max_turns": 6,
                "launch_timeout_seconds": 60,
                "turn_timeout_seconds": 1800,
                "require_git": True,
            },
        }

    def test_validate_generator_status_accepts_valid_payload(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "implemented",
                "summary": "Changed parser and tests.",
                "changed_files": ["src/parser.py", "tests/test_parser.py"],
            }
        )
        self.assertEqual(status["result"], "implemented")
        self.assertEqual(len(status["changed_files"]), 2)

    def test_validate_reviewer_status_accepts_approved(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "approved",
                "summary": "No blocking issues remain.",
                "blocking_issues": [],
                "critical_dimensions": {
                    "correctness_vs_intent": "pass",
                    "regression_risk": "pass",
                    "failure_mode_and_fallback": "pass",
                    "state_and_metadata_integrity": "pass",
                    "test_adequacy": "pass",
                    "maintainability": "pass",
                },
            }
        )
        self.assertEqual(status["verdict"], "approved")

    def test_extract_terminal_summary_block_returns_last_complete_summary(self) -> None:
        pane = "\n".join(
            [
                "noise",
                "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                "old",
                "COUNCIL_TERMINAL_SUMMARY_END",
                "noise",
                "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                "latest",
                "COUNCIL_TERMINAL_SUMMARY_END",
            ]
        )
        self.assertEqual(MODULE.extract_terminal_summary_block(pane), "latest")

    def test_scaffold_task_root_creates_base_files_only_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            result = MODULE.scaffold_task_root(task_root, initial_task_text=None)
            self.assertTrue((task_root / "AGENTS.md").exists())
            self.assertTrue((task_root / "generator.instructions.md").exists())
            self.assertTrue((task_root / "reviewer.instructions.md").exists())
            self.assertFalse((task_root / MODULE.TASK_FILENAME).exists())
            self.assertEqual(result["profile"], "undocumented")

    def test_scaffold_task_root_can_seed_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix the broken auth flow.")
            self.assertTrue((task_root / MODULE.TASK_FILENAME).exists())
            self.assertIn("# Task", (task_root / MODULE.TASK_FILENAME).read_text(encoding="utf-8"))

    def test_inspect_task_workspace_accepts_valid_document_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)

            inspection = MODULE.inspect_task_workspace(task_root)
            self.assertEqual(inspection["profile"], "undocumented")

            (task_root / MODULE.TASK_FILENAME).write_text("# Task\n\n## Request\n\nFix bug\n\n## Context\n\nctx\n\n## Success Signal\n\nWorks\n", encoding="utf-8")
            self.assertEqual(MODULE.inspect_task_workspace(task_root)["profile"], "task")

            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix bug\n", encoding="utf-8")
            self.assertEqual(MODULE.inspect_task_workspace(task_root)["profile"], "task+review")

            (task_root / MODULE.SPEC_FILENAME).write_text(MODULE.read_template("scaffold", MODULE.SPEC_FILENAME), encoding="utf-8")
            self.assertEqual(MODULE.inspect_task_workspace(task_root)["profile"], "task+review+spec")

            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One check\n", encoding="utf-8")
            self.assertEqual(MODULE.inspect_task_workspace(task_root)["profile"], "task+review+spec+contract")

    def test_inspect_task_workspace_supports_legacy_initial_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            (task_root / MODULE.LEGACY_REVIEW_FILENAME).write_text("# Initial Review\n\n- Fix fallback\n", encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            self.assertEqual(inspection["profile"], "review")
            self.assertTrue(inspection["legacy_review_source"])

    def test_inspect_task_workspace_rejects_invalid_document_combinations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)

            (task_root / MODULE.SPEC_FILENAME).write_text("# Spec\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.inspect_task_workspace(task_root)
            (task_root / MODULE.SPEC_FILENAME).unlink()

            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One check\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.inspect_task_workspace(task_root)
            (task_root / MODULE.CONTRACT_FILENAME).unlink()

            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n- x\n", encoding="utf-8")
            (task_root / MODULE.LEGACY_REVIEW_FILENAME).write_text("# Initial Review\n\n- y\n", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.inspect_task_workspace(task_root)

    def test_lint_task_review_spec_and_contract_reject_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.TASK_FILENAME).write_text(MODULE.read_template("scaffold", MODULE.TASK_FILENAME), encoding="utf-8")
            self.assertTrue(MODULE.lint_task_workspace_readiness(task_root)[0])

            review_path = task_root / MODULE.REVIEW_FILENAME
            review_path.write_text(MODULE.read_template("scaffold", MODULE.REVIEW_FILENAME), encoding="utf-8")
            self.assertTrue(MODULE.lint_review_workspace_readiness(review_path)[0])

            (task_root / MODULE.SPEC_FILENAME).write_text(MODULE.read_template("scaffold", MODULE.SPEC_FILENAME), encoding="utf-8")
            self.assertTrue(MODULE.lint_spec_workspace_readiness(task_root)[0])

            (task_root / MODULE.CONTRACT_FILENAME).write_text(MODULE.read_template("scaffold", MODULE.CONTRACT_FILENAME), encoding="utf-8")
            self.assertTrue(MODULE.lint_contract_workspace_readiness(task_root)[0])

    def test_write_document_command_writes_requested_doc(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                doc_kind="review",
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                body="Fix the failing migration path.",
                body_file=None,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.write_document_command(args)
            self.assertEqual(result, 0)
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            self.assertTrue((task_root / MODULE.REVIEW_FILENAME).exists())
            self.assertIn("# Review", (task_root / MODULE.REVIEW_FILENAME).read_text(encoding="utf-8"))

    def test_format_doc_paths_block_uses_paths_not_inlined_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n- Fix fallback\n", encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            block = MODULE.format_doc_paths_block(task_root, inspection, "generator")
            self.assertIn(str(task_root / MODULE.TASK_FILENAME), block)
            self.assertIn(str(task_root / MODULE.REVIEW_FILENAME), block)
            self.assertNotIn("Fix fallback", block)

    def test_build_generator_initial_prompt_is_path_based_and_review_aware(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix the parser bug.")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback logic\n", encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text("# Spec\n\n## Goal\n\nFix parser\n\n## User Outcome\n\nWorks\n\n## In Scope\n\n- parser\n\n## Out of Scope\n\n- ui\n\n## Constraints\n\n- keep api\n\n## Existing Context\n\nctx\n\n## Desired Behavior\n\nok\n\n## Technical Boundaries\n\nnone\n\n## Validation Expectations\n\ntests\n\n## Open Questions\n\n- none\n", encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                state={"review_bridge": {"mode": "internal"}},
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Read these files directly before coding:", prompt)
            self.assertIn(str(task_root / MODULE.TASK_FILENAME), prompt)
            self.assertIn(str(task_root / MODULE.REVIEW_FILENAME), prompt)
            self.assertIn(str(task_root / MODULE.SPEC_FILENAME), prompt)
            self.assertIn("classify each review point as `agree`, `disagree`, or `uncertain`", prompt)
            self.assertNotIn("Shared council brief from", prompt)

    def test_build_generator_prompt_mentions_github_review_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix the parser bug.")
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                state={
                    "review_bridge": {
                        "mode": "github_pr_codex",
                        "github": {
                            "base_branch": "main",
                            "branch": "feature/demo",
                            "pr_url": "https://github.com/acme/repo/pull/123",
                        },
                    }
                },
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("GitHub PR review mode is enabled.", prompt)
            self.assertIn("feature/demo", prompt)
            self.assertIn("https://github.com/acme/repo/pull/123", prompt)

    def test_build_reviewer_initial_prompt_includes_contract_checklist_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback\n", encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One check\n", encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Contract checklist copied from `contract.md`", prompt)
            self.assertIn("Disagreement Adjudication", prompt)
            self.assertIn("Do not repeat the same blocker without stronger evidence", prompt)

    def test_build_reviewer_bootstrap_prompt_materializes_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                inspection=inspection,
                inline_context=True,
                bootstrap_review_block=MODULE.format_fork_bootstrap_review_block(task_root),
            )
            self.assertIn("distill the current fork/session context", prompt)
            self.assertIn(str(task_root / MODULE.REVIEW_FILENAME), prompt)
            self.assertNotIn(str(role_message_path := turn_dir / "generator" / "message.md"), prompt)

    def test_build_continue_context_mentions_present_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback\n", encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            previous_turn_dir = Path(tmp_dir) / "runs" / "run-1" / "turns" / "0001"
            (previous_turn_dir / "generator").mkdir(parents=True)
            MODULE.write_text(previous_turn_dir / "generator" / "message.md", "done")
            MODULE.save_json(previous_turn_dir / "generator" / "status.json", {"result": "implemented", "summary": "done", "changed_files": []})
            context = MODULE.build_continue_context(
                state={"status": "paused_needs_human"},
                previous_turn_dir=previous_turn_dir,
                role="generator",
                inspection=inspection,
            )
            self.assertIn("`task.md`", context)
            self.assertIn("`review.md`", context)

    def test_snapshot_context_manifest_uses_present_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback\n", encoding="utf-8")
            manifest = MODULE.snapshot_context_manifest(task_root / "runs" / "run-1", task_root)
            self.assertEqual(manifest["profile"], "task+review")
            self.assertIn("task", manifest["files"])
            self.assertIn("review", manifest["files"])
            self.assertNotIn("spec", manifest["files"])

    def test_determine_start_role_prefers_review_then_task_then_fork_bootstrap(self) -> None:
        undocumented = {"doc_paths": {"task": None, "review": None, "spec": None, "contract": None}, "present_docs": (), "profile": "undocumented"}
        task_only = {"doc_paths": {"task": Path("/tmp/task.md"), "review": None, "spec": None, "contract": None}, "present_docs": ("task",), "profile": "task"}
        review_only = {"doc_paths": {"task": None, "review": Path("/tmp/review.md"), "spec": None, "contract": None}, "present_docs": ("review",), "profile": "review"}

        self.assertEqual(MODULE.determine_start_role(inspection=review_only, fork_enabled=False, requested_role="auto"), ("generator", None))
        self.assertEqual(MODULE.determine_start_role(inspection=task_only, fork_enabled=False, requested_role="auto"), ("generator", None))
        self.assertEqual(MODULE.determine_start_role(inspection=undocumented, fork_enabled=True, requested_role="auto"), ("reviewer", "fork_to_review"))
        with self.assertRaises(SystemExit):
            MODULE.determine_start_role(inspection=undocumented, fork_enabled=False, requested_role="auto")

    def test_start_run_bootstraps_review_from_fork_when_no_local_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session="rev",
                fork_session_id="parent-id",
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "find_codex_session_entry", return_value={"id": "parent-id", "updated_at": "2026-04-10T12:00:00Z", "thread_name": "x"}), mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
                MODULE, "create_tmux_sessions", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_sessions_ready", return_value=None
            ), mock.patch.object(MODULE, "supervisor_loop_from", return_value=None) as supervisor_loop, contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(supervisor_loop.call_args.kwargs["start_role"], "reviewer")
            state = MODULE.load_json(task_root / "runs" / "run-1" / "state.json")
            self.assertEqual(state["bootstrap_phase"], "fork_to_review")
            self.assertEqual(state["roles"]["generator"]["fork_parent_session_id"], "parent-id")
            self.assertEqual(state["roles"]["reviewer"]["fork_parent_session_id"], "parent-id")

    def test_start_run_rejects_bootstrap_without_reviewer_fork_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            self.scaffold_base_workspace(repo_root)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id="parent-id",
                reviewer_fork_session_id=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "find_codex_session_entry", return_value={"id": "parent-id", "updated_at": "2026-04-10T12:00:00Z", "thread_name": "x"}):
                with self.assertRaises(SystemExit):
                    MODULE.start_run(args)

    def test_start_run_prefers_generator_for_task_or_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text("# Task\n\n## Request\n\nFix bug\n\n## Context\n\nctx\n\n## Success Signal\n\nworks\n", encoding="utf-8")
            self.commit_repo_changes(repo_root, "add task")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session="rev",
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
                MODULE, "create_tmux_sessions", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_sessions_ready", return_value=None
            ), mock.patch.object(MODULE, "supervisor_loop_from", return_value=None) as supervisor_loop, contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(supervisor_loop.call_args.kwargs["start_role"], "generator")

    def test_start_run_rejects_invalid_or_placeholder_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(MODULE.read_template("scaffold", MODULE.REVIEW_FILENAME), encoding="utf-8")
            self.commit_repo_changes(repo_root, "add placeholder review")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                start_role="auto",
            )
            with self.assertRaises(SystemExit):
                MODULE.start_run(args)

    def test_build_review_bridge_state_reuses_existing_pr_from_arg(self) -> None:
        args = argparse.Namespace(
            review_mode="github_pr_codex",
            github_pr="https://github.com/acme/repo/pull/42",
            github_branch=None,
            github_base=None,
            start_role="auto",
        )
        with mock.patch.object(
            MODULE,
            "load_github_repo_metadata",
            return_value={
                "default_branch": "main",
                "name_with_owner": "acme/repo",
                "owner": "acme",
                "repo": "repo",
                "url": "https://github.com/acme/repo",
            },
        ), mock.patch.object(
            MODULE,
            "resolve_github_pr_reference",
            return_value={
                "number": 42,
                "url": "https://github.com/acme/repo/pull/42",
                "head_ref_name": "feature/pr",
                "base_ref_name": "main",
                "head_ref_oid": "abc123",
                "title": "Fix issue",
            },
        ):
            state = MODULE.build_review_bridge_state(
                Path("/repo"),
                Path("/repo/.codex-council/demo-task"),
                {"current_branch": "local-branch"},
                args,
            )
        self.assertEqual(state["mode"], "github_pr_codex")
        self.assertEqual(state["github"]["pr_number"], 42)
        self.assertEqual(state["github"]["branch"], "feature/pr")
        self.assertEqual(state["github"]["base_branch"], "main")

    def test_ensure_github_pr_ready_creates_pr_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            state = {
                "run_id": "run-1",
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "base_branch": "main",
                        "branch": "feature/demo",
                        "branch_source": "auto",
                        "last_observed_head_sha": None,
                        "pr_number": None,
                        "pr_url": None,
                        "review_wait": {
                            "deadline_at": None,
                            "initial_wait_seconds": MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                            "last_polled_at": None,
                            "poll_count": 0,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": None,
                        },
                    },
                },
            }
            with mock.patch.object(
                MODULE,
                "sync_github_review_branch_state",
                return_value=("feature/demo", "deadbeef"),
            ), mock.patch.object(
                MODULE,
                "find_existing_github_pr_for_branch",
                return_value=None,
            ), mock.patch.object(
                MODULE,
                "resolve_pushed_branch_head_sha",
                return_value="deadbeef",
            ) as pushed, mock.patch.object(
                MODULE,
                "create_github_pr",
                return_value={
                    "number": 7,
                    "url": "https://github.com/acme/repo/pull/7",
                    "head_ref_name": "feature/demo",
                    "base_ref_name": "main",
                    "head_ref_oid": "deadbeef",
                    "title": "Fix bug",
                },
            ) as create_pr:
                pr_info = MODULE.ensure_github_pr_ready(run_dir, state, task_root, 1)
            pushed.assert_called_once()
            create_pr.assert_called_once()
            self.assertEqual(pr_info["number"], 7)
            self.assertEqual(state["review_bridge"]["github"]["pr_number"], 7)
            self.assertEqual(state["review_bridge"]["github"]["pr_url"], "https://github.com/acme/repo/pull/7")

    def test_post_github_pr_review_request_comment_records_comment_id_and_timestamp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "run_id": "run-1",
                "task_name": "demo-task",
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "branch": "feature/demo",
                        "pr_number": 9,
                        "repo_owner": "acme",
                        "repo": "repo",
                    },
                },
            }
            with mock.patch.object(
                MODULE,
                "gh_json",
                return_value={
                    "id": 101,
                    "created_at": "2026-04-12T01:00:00Z",
                    "html_url": "https://github.com/acme/repo/pull/9#issuecomment-101",
                },
            ):
                request_comment = MODULE.post_github_pr_review_request_comment(run_dir, state, 2, "deadbeef")
            self.assertEqual(request_comment["id"], 101)
            self.assertTrue(request_comment["body"].startswith("@codex review"))
            self.assertEqual(state["review_bridge"]["github"]["last_request_comment_id"], 101)
            self.assertEqual(state["review_bridge"]["github"]["last_request_turn"], "0002")

    def test_select_latest_unconsumed_github_codex_review_comment_ignores_consumed_comments(self) -> None:
        comments = [
            {"id": 10, "created_at": "2026-04-12T00:00:00Z", "body": "@codex review"},
            {"id": 11, "created_at": "2026-04-12T00:10:00Z", "body": "Codex Review: First review"},
            {"id": 12, "created_at": "2026-04-12T00:20:00Z", "body": "Codex Review: Latest review"},
        ]
        selected = MODULE.select_latest_unconsumed_github_codex_review_comment(
            comments,
            request_comment_id=10,
            request_comment_created_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=11,
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected["id"], 12)

    def test_wait_for_new_github_codex_review_comment_uses_initial_wait_then_poll_interval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            request_created_at = "2026-04-12T01:00:00Z"
            now = [MODULE.parse_utc_timestamp(request_created_at)]
            sleeps: list[float] = []

            def fake_sleep(seconds: float) -> None:
                sleeps.append(seconds)
                now[0] += seconds

            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "last_consumed_review_comment_id": None,
                        "last_request_comment_created_at": request_created_at,
                        "last_request_comment_id": 101,
                        "pr_number": 9,
                        "repo": "repo",
                        "repo_owner": "acme",
                        "review_wait": {
                            "deadline_at": None,
                            "initial_wait_seconds": MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                            "last_polled_at": None,
                            "poll_count": 0,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": None,
                        },
                    },
                },
            }
            comment = {
                "id": 202,
                "created_at": "2026-04-12T01:15:00Z",
                "body": "Codex Review: Needs one more fix.",
            }
            with mock.patch.object(MODULE.time, "time", side_effect=lambda: now[0]), mock.patch.object(
                MODULE.time,
                "sleep",
                side_effect=fake_sleep,
            ), mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                side_effect=[[], [comment]],
            ):
                result = MODULE.wait_for_new_github_codex_review_comment(
                    run_dir,
                    state,
                    1,
                    timeout_seconds=1800,
                )
            self.assertEqual(result["id"], 202)
            self.assertEqual(sleeps, [600, 300])
            self.assertEqual(state["review_bridge"]["github"]["review_wait"]["poll_count"], 2)

    def test_wait_for_new_github_codex_review_comment_reuses_existing_request_without_restarting_initial_wait(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            request_created_at = "2026-04-12T01:00:00Z"
            resume_epoch = MODULE.parse_utc_timestamp("2026-04-12T01:11:00Z")
            assert resume_epoch is not None
            now = [resume_epoch]
            sleeps: list[float] = []

            def fake_sleep(seconds: float) -> None:
                sleeps.append(seconds)
                now[0] += seconds

            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "last_consumed_review_comment_id": None,
                        "last_request_comment_created_at": request_created_at,
                        "last_request_comment_id": 101,
                        "pr_number": 9,
                        "repo": "repo",
                        "repo_owner": "acme",
                        "review_wait": {
                            "deadline_at": "2026-04-12T01:30:00Z",
                            "initial_wait_seconds": MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                            "last_polled_at": None,
                            "poll_count": 0,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": request_created_at,
                        },
                    },
                },
            }
            comment = {
                "id": 202,
                "created_at": "2026-04-12T01:11:00Z",
                "body": "Codex Review: Ready to import.",
            }
            with mock.patch.object(MODULE.time, "time", side_effect=lambda: now[0]), mock.patch.object(
                MODULE.time,
                "sleep",
                side_effect=fake_sleep,
            ), mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                return_value=[comment],
            ):
                result = MODULE.wait_for_new_github_codex_review_comment(
                    run_dir,
                    state,
                    1,
                    timeout_seconds=1800,
                    reuse_existing_request=True,
                )
            self.assertEqual(result["id"], 202)
            self.assertEqual(sleeps, [])
            self.assertEqual(state["review_bridge"]["github"]["review_wait"]["poll_count"], 1)

    def test_run_github_codex_review_phase_stops_on_terminal_no_blocker_comment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            turn_dir = run_dir / "turns" / "0001"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            state = {
                "council_config": {"council": {"turn_timeout_seconds": 1800}},
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "base_branch": "main",
                        "branch": "feature/demo",
                        "last_request_comment_created_at": None,
                        "last_request_comment_id": None,
                        "last_request_turn": None,
                        "last_observed_head_sha": "deadbeef",
                        "pr_number": 9,
                        "pr_url": "https://github.com/acme/repo/pull/9",
                        "repo": "repo",
                        "repo_owner": "acme",
                        "review_wait": {
                            "deadline_at": None,
                            "initial_wait_seconds": MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                            "last_polled_at": None,
                            "poll_count": 0,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": None,
                        },
                    },
                },
                "roles": {"reviewer": {"last_wait_phase": None}},
                "status": "booting",
            }
            with mock.patch.object(
                MODULE,
                "ensure_github_pr_ready",
                return_value={
                    "number": 9,
                    "url": "https://github.com/acme/repo/pull/9",
                    "head_ref_name": "feature/demo",
                    "base_ref_name": "main",
                    "head_ref_oid": "deadbeef",
                    "title": "Fix bug",
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
                return_value={
                    "id": 101,
                    "created_at": "2026-04-12T01:00:00Z",
                    "html_url": None,
                    "body": "@codex review",
                },
            ), mock.patch.object(
                MODULE,
                "wait_for_new_github_codex_review_comment",
                return_value={
                    "id": 202,
                    "created_at": "2026-04-12T01:10:00Z",
                    "body": "Codex Review: Didn't find any major issues. Keep it up!\nAll good.",
                },
            ):
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "approved")
            saved_status = MODULE.load_json(turn_dir / "reviewer" / "status.json")
            self.assertEqual(saved_status["verdict"], "approved")
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("Didn't find any major issues", reviewer_message)

    def test_run_github_codex_review_phase_surfaces_timeout_as_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            turn_dir = run_dir / "turns" / "0001"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            state = {
                "council_config": {"council": {"turn_timeout_seconds": 1800}},
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "base_branch": "main",
                        "branch": "feature/demo",
                        "last_request_comment_created_at": None,
                        "last_request_comment_id": None,
                        "last_request_turn": None,
                        "last_observed_head_sha": "deadbeef",
                        "pr_number": 9,
                        "pr_url": "https://github.com/acme/repo/pull/9",
                        "repo": "repo",
                        "repo_owner": "acme",
                        "review_wait": {
                            "deadline_at": None,
                            "initial_wait_seconds": MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                            "last_polled_at": None,
                            "poll_count": 0,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": None,
                        },
                    },
                },
                "roles": {"reviewer": {"last_wait_phase": None}},
                "status": "booting",
            }
            error = MODULE.SupervisorRuntimeError("github_review_timeout", "timed out waiting for Codex", role="reviewer")
            with mock.patch.object(
                MODULE,
                "ensure_github_pr_ready",
                return_value={
                    "number": 9,
                    "url": "https://github.com/acme/repo/pull/9",
                    "head_ref_name": "feature/demo",
                    "base_ref_name": "main",
                    "head_ref_oid": "deadbeef",
                    "title": "Fix bug",
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
                return_value={
                    "id": 101,
                    "created_at": "2026-04-12T01:00:00Z",
                    "html_url": None,
                    "body": "@codex review",
                },
            ), mock.patch.object(
                MODULE,
                "wait_for_new_github_codex_review_comment",
                side_effect=error,
            ):
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "blocked")
            self.assertIn("timed out waiting for Codex", reviewer_status["summary"])
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("GitHub review bridge failed", reviewer_message)

    def test_determine_continue_target_reuses_same_turn_for_github_review_bridge_blocked_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            latest_turn = run_dir / "turns" / "0001"
            latest_turn.mkdir(parents=True)
            with mock.patch.object(
                MODULE,
                "classify_continuation_state",
                return_value=(latest_turn, "reviewer_blocked", {}),
            ):
                result = MODULE.determine_continue_target(
                    run_dir,
                    {"review_bridge": {"mode": "github_pr_codex"}},
                )
            self.assertEqual(result, (latest_turn, 1, "reviewer", False, "reviewer_blocked"))

    def test_create_tmux_sessions_skips_reviewer_for_github_review_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {"mode": "github_pr_codex"},
                "roles": {
                    "generator": {"last_wait_phase": None, "tmux_session": "gen"},
                    "reviewer": {"last_wait_phase": None, "tmux_session": "rev"},
                },
                "council_config": self.build_council_config(),
            }
            with mock.patch.object(MODULE, "tmux_new_session") as tmux_new_session:
                MODULE.create_tmux_sessions(run_dir, state)
            tmux_new_session.assert_called_once()
            self.assertEqual(tmux_new_session.call_args.args[0], "gen")

    def test_start_run_converts_github_startup_failure_into_blocked_state_with_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix bug\n\n## Context\n\nctx\n\n## Success Signal\n\nworks\n",
                encoding="utf-8",
            )
            self.commit_repo_changes(repo_root, "add task")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="github_pr_codex",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
                MODULE,
                "load_github_repo_metadata",
                side_effect=MODULE.SupervisorRuntimeError(
                    "github_repo_view",
                    "gh repo view failed",
                    role="reviewer",
                ),
            ), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.start_run(args)
            self.assertEqual(result, 1)
            run_dir = task_root / "runs" / "run-1"
            state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(state["status"], "blocked")
            self.assertIn("github_repo_view", state["stop_reason"])
            diagnostics_root = run_dir / "diagnostics"
            self.assertTrue(diagnostics_root.exists())
            self.assertTrue(any(diagnostics_root.iterdir()))

    def test_pause_for_human_mentions_present_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback\n", encoding="utf-8")
            run_dir = task_root / "runs" / "run-1"
            state = {
                "status": "waiting_generator",
                "stop_reason": None,
                "task_root": str(task_root),
            }
            MODULE.save_json(run_dir / "state.json", state)
            turn_dir = run_dir / "turns" / "0001"
            turn_dir.mkdir(parents=True)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                MODULE.pause_for_human(
                    run_dir,
                    state,
                    role="generator",
                    turn_dir=turn_dir,
                    summary="Need clarification.",
                    human_message="Clarify the finding.",
                    human_source="review.md",
                )
            rendered = output.getvalue()
            self.assertIn("task.md / review.md / AGENTS.md", rendered)

    def test_init_task_outputs_document_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                task=None,
                task_file=None,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.init_task(args)
            self.assertEqual(result, 0)
            rendered = output.getvalue()
            self.assertIn("task:", rendered)
            self.assertIn("review:", rendered)
            self.assertIn("spec:", rendered)
            self.assertIn("contract:", rendered)

    def test_build_parser_exposes_write_start_role_shared_fork_and_github_review_args(self) -> None:
        parser = MODULE.build_parser()
        write_args = parser.parse_args(["write", "task", "demo-task", "--body", "Fix it"])
        start_args = parser.parse_args(
            [
                "start",
                "demo-task",
                "--fork-session-id",
                "id",
                "--start-role",
                "reviewer",
                "--review-mode",
                "github_pr_codex",
                "--github-pr",
                "42",
                "--github-base",
                "main",
            ]
        )
        self.assertEqual(write_args.command, "write")
        self.assertEqual(start_args.fork_session_id, "id")
        self.assertEqual(start_args.start_role, "reviewer")
        self.assertEqual(start_args.review_mode, "github_pr_codex")
        self.assertEqual(start_args.github_pr, "42")
        self.assertEqual(start_args.github_base, "main")


if __name__ == "__main__":
    unittest.main()
