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

    def test_validate_generator_status_accepts_valid_payload(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "implemented",
                "summary": "Changed the parser and added tests.",
                "changed_files": ["src/parser.py", "tests/test_parser.py"],
            }
        )
        self.assertEqual(status["result"], "implemented")
        self.assertEqual(len(status["changed_files"]), 2)

    def test_validate_generator_status_accepts_optional_git_metadata_when_present(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "implemented",
                "summary": "Changed the parser and added tests.",
                "changed_files": ["src/parser.py"],
                "commit_sha": "abc123",
                "compare_base_sha": "def456",
                "branch": "main",
            }
        )
        self.assertEqual(status["commit_sha"], "abc123")

    def test_validate_generator_status_rejects_council_runtime_changed_files(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_generator_status(
                {
                    "result": "implemented",
                    "summary": "Changed the parser and added tests.",
                    "changed_files": [".codex-council/task/runs/run-1/turns/0001/generator/message.md"],
                }
            )

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

    def test_validate_reviewer_status_accepts_optional_reviewed_commit_when_present(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "changes_requested",
                "summary": "One blocker remains.",
                "blocking_issues": ["Fix the fallback path."],
                "reviewed_commit_sha": "abc123",
                "critical_dimensions": {
                    "correctness_vs_intent": "fail",
                    "regression_risk": "uncertain",
                    "failure_mode_and_fallback": "fail",
                    "state_and_metadata_integrity": "pass",
                    "test_adequacy": "pass",
                    "maintainability": "pass",
                },
            }
        )
        self.assertEqual(status["reviewed_commit_sha"], "abc123")

    def test_validate_reviewer_status_normalizes_empty_human_fields_for_changes_requested(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "changes_requested",
                "summary": "One blocker remains.",
                "blocking_issues": ["Fix the fallback path."],
                "human_message": "",
                "human_source": "",
                "critical_dimensions": {
                    "correctness_vs_intent": "fail",
                    "regression_risk": "pass",
                    "failure_mode_and_fallback": "pass",
                    "state_and_metadata_integrity": "uncertain",
                    "test_adequacy": "fail",
                    "maintainability": "pass",
                },
            }
        )
        self.assertIsNone(status["human_message"])
        self.assertIsNone(status["human_source"])

    def test_validate_generator_status_requires_human_message_for_needs_human(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_generator_status(
                {
                    "result": "needs_human",
                    "summary": "Task plan is contradictory.",
                    "changed_files": [],
                    "human_source": "task.md",
                }
            )

        status = MODULE.validate_generator_status(
            {
                "result": "needs_human",
                "summary": "Task plan is contradictory.",
                "changed_files": [],
                "human_message": "Clarify whether API A or API B is the intended target.",
                "human_source": "task.md",
            }
        )
        self.assertEqual(status["result"], "needs_human")
        self.assertIn("Clarify", status["human_message"])
        self.assertEqual(status["human_source"], "task.md")

    def test_validate_generator_status_accepts_human_source_as_canonical_path(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "needs_human",
                "summary": "Task plan is contradictory.",
                "changed_files": [],
                "human_message": "Clarify whether API A or API B is the intended target.",
                "human_source": "/tmp/demo/.codex-council/task/task.md",
            }
        )
        self.assertEqual(status["human_source"], "task.md")

    def test_validate_reviewer_status_requires_human_message_for_needs_human(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_reviewer_status(
                {
                    "verdict": "needs_human",
                    "summary": "Plan conflicts with current architecture.",
                    "blocking_issues": [],
                    "critical_dimensions": {
                        "correctness_vs_intent": "uncertain",
                        "regression_risk": "uncertain",
                        "failure_mode_and_fallback": "uncertain",
                        "state_and_metadata_integrity": "uncertain",
                        "test_adequacy": "uncertain",
                        "maintainability": "uncertain",
                    },
                }
            )

        status = MODULE.validate_reviewer_status(
            {
                "verdict": "needs_human",
                "summary": "Plan conflicts with current architecture.",
                "blocking_issues": [],
                "human_message": "Decide whether the task should preserve the current API or introduce a breaking change.",
                "human_source": "contract.md",
                "critical_dimensions": {
                    "correctness_vs_intent": "uncertain",
                    "regression_risk": "uncertain",
                    "failure_mode_and_fallback": "uncertain",
                    "state_and_metadata_integrity": "uncertain",
                    "test_adequacy": "uncertain",
                    "maintainability": "uncertain",
                },
            }
        )
        self.assertEqual(status["verdict"], "needs_human")
        self.assertIn("Decide", status["human_message"])
        self.assertEqual(status["human_source"], "contract.md")

    def test_validate_reviewer_status_accepts_human_source_as_canonical_path(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "needs_human",
                "summary": "Plan conflicts with current architecture.",
                "blocking_issues": [],
                "human_message": "Replace the placeholder contract with concrete acceptance criteria.",
                "human_source": "/tmp/demo/.codex-council/task/contract.md",
                "critical_dimensions": {
                    "correctness_vs_intent": "uncertain",
                    "regression_risk": "uncertain",
                    "failure_mode_and_fallback": "uncertain",
                    "state_and_metadata_integrity": "uncertain",
                    "test_adequacy": "uncertain",
                    "maintainability": "uncertain",
                },
            }
        )
        self.assertEqual(status["human_source"], "contract.md")

    def test_validate_reviewer_status_rejects_approved_if_any_dimension_not_pass(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_reviewer_status(
                {
                    "verdict": "approved",
                    "summary": "No blocking issues remain.",
                    "blocking_issues": [],
                    "reviewed_commit_sha": "abc123",
                    "critical_dimensions": {
                        "correctness_vs_intent": "pass",
                        "regression_risk": "uncertain",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "pass",
                        "maintainability": "pass",
                    },
                }
            )

    def test_extract_last_tmux_slice_uses_last_two_prompts(self) -> None:
        pane = "\n".join(
            [
                "header",
                "› old prompt",
                "",
                "old output",
                "› current prompt",
                "",
                "last output line 1",
                "last output line 2",
                "",
            ]
        )
        result = MODULE.extract_last_tmux_slice(pane)
        self.assertEqual(result, "old output\n")

    def test_extract_terminal_summary_block_returns_last_complete_summary(self) -> None:
        pane = "\n".join(
            [
                "noise",
                "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                "old summary",
                "COUNCIL_TERMINAL_SUMMARY_END",
                "more noise",
                "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                "latest summary",
                "line 2",
                "COUNCIL_TERMINAL_SUMMARY_END",
            ]
        )
        self.assertEqual(
            MODULE.extract_terminal_summary_block(pane),
            "latest summary\nline 2",
        )

    def test_git_root_for_returns_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            repo_root.mkdir()
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            nested = repo_root / "nested" / "deeper"
            nested.mkdir(parents=True)
            self.assertEqual(MODULE.git_root_for(nested), repo_root.resolve())

    def test_resolve_target_root_rejects_non_git_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with self.assertRaises(SystemExit):
                MODULE.resolve_target_root(Path(tmp_dir), allow_non_git=False)

    def test_git_preflight_rejects_dirty_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            repo_root.mkdir()
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True, capture_output=True, text=True)
            (repo_root / "file.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            (repo_root / "file.txt").write_text("changed", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.git_preflight(repo_root)

    def test_git_preflight_allows_branch_without_upstream(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            repo_root.mkdir()
            subprocess.run(["git", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo_root, check=True, capture_output=True, text=True)
            (repo_root / "file.txt").write_text("x", encoding="utf-8")
            subprocess.run(["git", "add", "file.txt"], cwd=repo_root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=repo_root, check=True, capture_output=True, text=True)
            state = MODULE.git_preflight(repo_root)
            self.assertEqual(state["current_branch"], "master")
            self.assertIsNotNone(state["base_commit_sha"])

    def test_scaffold_task_root_creates_expected_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            result = MODULE.scaffold_task_root(
                task_root,
                initial_task_text="Implement a small feature.",
            )
            self.assertTrue(result["task_created"])
            self.assertFalse(result["task_needs_edit"])
            self.assertEqual(result["workspace_mode"], MODULE.WORKSPACE_MODE_SPEC_BACKED)
            self.assertTrue((repo_root / ".codex-council" / "config.toml").exists())
            self.assertTrue((repo_root / ".codex-council" / ".gitignore").exists())
            self.assertTrue((task_root / "task.md").exists())
            self.assertTrue((task_root / "contract.md").exists())
            self.assertTrue((task_root / "AGENTS.md").exists())
            self.assertTrue((task_root / "generator.instructions.md").exists())
            self.assertTrue((task_root / "reviewer.instructions.md").exists())
            self.assertTrue(
                (task_root / "task.md").read_text(encoding="utf-8").startswith("# Feature Spec")
            )
            self.assertTrue(
                (task_root / "contract.md").read_text(encoding="utf-8").startswith("# Definition of Done")
            )
            self.assertIn(
                "It is not the place for feature requirements",
                (task_root / "AGENTS.md").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (task_root / "AGENTS.md").read_text(encoding="utf-8"),
                MODULE.read_template("scaffold", "AGENTS.md"),
            )

    def test_scaffold_task_root_marks_placeholder_when_no_task_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            result = MODULE.scaffold_task_root(task_root, initial_task_text=None)
            self.assertTrue(result["task_created"])
            self.assertTrue(result["task_needs_edit"])

    def test_scaffold_task_root_can_skip_task_and_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            result = MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                skip_task_and_contract=True,
            )
            self.assertEqual(result["workspace_mode"], MODULE.WORKSPACE_MODE_INHERITED_CONTEXT)
            self.assertFalse((task_root / "task.md").exists())
            self.assertFalse((task_root / "contract.md").exists())
            self.assertTrue((task_root / "AGENTS.md").exists())
            self.assertTrue((task_root / "generator.instructions.md").exists())
            self.assertTrue((task_root / "reviewer.instructions.md").exists())
            self.assertIn(
                "inherited chat context",
                (task_root / "AGENTS.md").read_text(encoding="utf-8"),
            )

    def test_scaffold_task_root_can_create_simple_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            result = MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                simple_mode=True,
            )
            self.assertEqual(result["workspace_mode"], MODULE.WORKSPACE_MODE_SIMPLE)
            self.assertTrue((task_root / "initial_review.md").exists())
            self.assertFalse((task_root / "task.md").exists())
            self.assertFalse((task_root / "contract.md").exists())
            self.assertIn(
                "canonical first generator brief",
                (task_root / "initial_review.md").read_text(encoding="utf-8"),
            )

    def test_inspect_task_workspace_detects_modes_and_rejects_partial_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_task_root = Path(tmp_dir) / ".codex-council" / "spec-task"
            spec_task_root.mkdir(parents=True)
            (spec_task_root / "task.md").write_text("task", encoding="utf-8")
            (spec_task_root / "contract.md").write_text("contract", encoding="utf-8")
            self.assertEqual(
                MODULE.inspect_task_workspace(spec_task_root)["workspace_mode"],
                MODULE.WORKSPACE_MODE_SPEC_BACKED,
            )

            inherited_task_root = Path(tmp_dir) / ".codex-council" / "inherited-task"
            inherited_task_root.mkdir(parents=True)
            self.assertEqual(
                MODULE.inspect_task_workspace(inherited_task_root)["workspace_mode"],
                MODULE.WORKSPACE_MODE_INHERITED_CONTEXT,
            )

            simple_task_root = Path(tmp_dir) / ".codex-council" / "simple-task"
            simple_task_root.mkdir(parents=True)
            (simple_task_root / "initial_review.md").write_text("review", encoding="utf-8")
            self.assertEqual(
                MODULE.inspect_task_workspace(simple_task_root)["workspace_mode"],
                MODULE.WORKSPACE_MODE_SIMPLE,
            )

            partial_task_root = Path(tmp_dir) / ".codex-council" / "partial-task"
            partial_task_root.mkdir(parents=True)
            (partial_task_root / "task.md").write_text("task", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.inspect_task_workspace(partial_task_root)

            mixed_task_root = Path(tmp_dir) / ".codex-council" / "mixed-task"
            mixed_task_root.mkdir(parents=True)
            (mixed_task_root / "task.md").write_text("task", encoding="utf-8")
            (mixed_task_root / "contract.md").write_text("contract", encoding="utf-8")
            (mixed_task_root / "initial_review.md").write_text("review", encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.inspect_task_workspace(mixed_task_root)

    def test_init_task_can_skip_task_and_contract_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                task=None,
                task_file=None,
                skip_task_and_contract=True,
                simple=False,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.init_task(args)
            self.assertEqual(result, 0)
            rendered = output.getvalue()
            self.assertIn("task/contract: skipped for inherited-context mode", rendered)
            self.assertIn("both fork session ids", rendered)

    def test_init_task_can_create_simple_mode_from_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                task=None,
                task_file=None,
                skip_task_and_contract=False,
                simple=True,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.init_task(args)
            self.assertEqual(result, 0)
            rendered = output.getvalue()
            self.assertIn("initial_review:", rendered)
            self.assertIn("run `start` normally or with fork session ids", rendered)

    def test_build_codex_command_includes_configured_flags(self) -> None:
        repo_root = Path("/repo")
        command = MODULE.build_codex_command(
            repo_root,
            {
                "model": "gpt-5.4",
                "model_reasoning_effort": "xhigh",
                "dangerously_bypass_approvals_and_sandbox": True,
                "no_alt_screen": True,
            },
        )
        self.assertEqual(command[:3], ["codex", "-C", str(repo_root)])
        self.assertIn("--model", command)
        self.assertIn("gpt-5.4", command)
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', command)
        self.assertIn("--no-alt-screen", command)
        self.assertIn('model_reasoning_effort="xhigh"', command)

    def test_build_codex_fork_command_includes_session_id_and_configured_flags(self) -> None:
        repo_root = Path("/repo")
        command = MODULE.build_codex_fork_command(
            repo_root,
            {
                "model": "gpt-5.4",
                "model_reasoning_effort": "xhigh",
                "dangerously_bypass_approvals_and_sandbox": True,
                "no_alt_screen": True,
            },
            "parent-session-id",
        )
        self.assertEqual(command[:4], ["codex", "fork", "-C", str(repo_root)])
        self.assertEqual(command[-1], "parent-session-id")
        self.assertIn("--model", command)
        self.assertIn("gpt-5.4", command)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertIn("--no-alt-screen", command)

    def test_render_template_text_fails_on_unresolved_placeholder(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE.render_template_text(
                "Hello {{name}} {{missing}}",
                {"name": "world"},
                template_name="test-template",
            )

    def test_prepare_turn_creates_role_scoped_layout_and_context_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = repo_root / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Do the task.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Done", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer rules.", encoding="utf-8")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            turn_two = MODULE.prepare_turn(run_dir, 2, task_root)
            manifest_one = MODULE.load_json(turn_one / "context_manifest.json")
            manifest_two = MODULE.load_json(turn_two / "context_manifest.json")
            self.assertTrue((turn_one / "generator").is_dir())
            self.assertTrue((turn_one / "reviewer").is_dir())
            self.assertFalse((turn_one / "inputs").exists())
            self.assertEqual(
                manifest_one["files"]["task"]["sha256"],
                manifest_two["files"]["task"]["sha256"],
            )
            self.assertEqual(
                manifest_one["files"]["task"]["canonical_path"],
                str(task_root / "task.md"),
            )
            self.assertEqual(manifest_one["workspace_mode"], MODULE.WORKSPACE_MODE_SPEC_BACKED)

    def test_prepare_turn_records_inherited_context_manifest_without_spec_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = repo_root / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer rules.", encoding="utf-8")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            manifest = MODULE.load_json(turn_one / "context_manifest.json")
            self.assertEqual(manifest["workspace_mode"], MODULE.WORKSPACE_MODE_INHERITED_CONTEXT)
            self.assertNotIn("task", manifest["files"])
            self.assertNotIn("contract", manifest["files"])

    def test_prepare_turn_records_simple_manifest_with_initial_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = repo_root / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "initial_review.md").write_text("# Initial Review\n\n- Fix bug", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer rules.", encoding="utf-8")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            manifest = MODULE.load_json(turn_one / "context_manifest.json")
            self.assertEqual(manifest["workspace_mode"], MODULE.WORKSPACE_MODE_SIMPLE)
            self.assertIn("initial_review", manifest["files"])
            self.assertNotIn("task", manifest["files"])
            self.assertNotIn("contract", manifest["files"])

    def test_lint_task_workspace_readiness_rejects_placeholder_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text(MODULE.read_template("scaffold", "task.md"), encoding="utf-8")
            (task_root / "contract.md").write_text(
                MODULE.read_template("scaffold", "contract.md"),
                encoding="utf-8",
            )
            errors, warnings = MODULE.lint_task_workspace_readiness(task_root)
            self.assertTrue(errors)
            self.assertTrue(any("contract.md still contains scaffold placeholder text" in item for item in errors))

    def test_lint_task_workspace_readiness_accepts_concrete_contract_and_warns_on_embedded_success_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text(
                "\n".join(
                    [
                        "# Feature Spec",
                        "## Goal",
                        "Ship feature.",
                        "## User Outcome",
                        "Users can do the thing.",
                        "## In Scope",
                        "- API change",
                        "## Out of Scope",
                        "- Infra changes",
                        "## Constraints",
                        "- Keep SQLite",
                        "## Existing Context",
                        "There is already an Express backend.",
                        "## Desired Behavior",
                        "Requests succeed with structured responses.",
                        "## Technical Boundaries",
                        "Do not replace persistence.",
                        "## Validation Expectations",
                        "Add tests.",
                        "## Open Questions",
                        "- None",
                        "Success contract:",
                        "- secondary context only",
                    ]
                ),
                encoding="utf-8",
            )
            (task_root / "contract.md").write_text("# Definition of Done\n\n- [ ] Concrete acceptance criterion", encoding="utf-8")
            errors, warnings = MODULE.lint_task_workspace_readiness(task_root)
            self.assertEqual(errors, [])
            self.assertEqual(len(warnings), 1)

    def test_lint_task_workspace_readiness_rejects_missing_task_spec_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("# Feature Spec\n\n## Goal\nOnly one section", encoding="utf-8")
            (task_root / "contract.md").write_text("# Definition of Done\n\n- [ ] One check", encoding="utf-8")
            errors, _ = MODULE.lint_task_workspace_readiness(task_root)
            self.assertTrue(any("task.md is missing required heading" in item for item in errors))

    def test_lint_task_workspace_readiness_warns_on_vague_task_words(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text(
                "\n".join(
                    [
                        "# Feature Spec",
                        "## Goal",
                        "Build a production-ready viral feature.",
                        "## User Outcome",
                        "Users see better behavior.",
                        "## In Scope",
                        "- API change",
                        "## Out of Scope",
                        "- Infra changes",
                        "## Constraints",
                        "- Keep SQLite",
                        "## Existing Context",
                        "There is already an Express backend.",
                        "## Desired Behavior",
                        "Requests succeed with structured responses.",
                        "## Technical Boundaries",
                        "Do not replace persistence.",
                        "## Validation Expectations",
                        "Add tests.",
                        "## Open Questions",
                        "- None",
                    ]
                ),
                encoding="utf-8",
            )
            (task_root / "contract.md").write_text("# Definition of Done\n\n- [ ] One check", encoding="utf-8")
            errors, warnings = MODULE.lint_task_workspace_readiness(task_root)
            self.assertEqual(errors, [])
            self.assertTrue(any("production-ready" in item or "viral" in item for item in warnings))

    def test_lint_simple_workspace_readiness_rejects_placeholder_and_accepts_concrete_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "initial_review.md").write_text(
                MODULE.read_template("scaffold", "initial_review.md"),
                encoding="utf-8",
            )
            errors, warnings = MODULE.lint_simple_workspace_readiness(task_root)
            self.assertTrue(errors)
            self.assertEqual(warnings, [])

            (task_root / "initial_review.md").write_text(
                "# Initial Review\n\n## Findings To Address\n\n- Fix the nil dereference in the parser.\n",
                encoding="utf-8",
            )
            errors, warnings = MODULE.lint_simple_workspace_readiness(task_root)
            self.assertEqual(errors, [])
            self.assertEqual(warnings, [])

    def test_build_generator_turn_prompt_includes_task_files_and_not_supervisor_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator additions.", encoding="utf-8")
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=True,
            )
            self.assertIn("Shared rules.", prompt)
            self.assertIn("Generator additions.", prompt)
            self.assertIn("Implement feature.", prompt)
            self.assertIn("Contract item", prompt)
            self.assertIn("Read the current feature spec in `task.md`", prompt)
            self.assertNotIn("supervisor controls turn order", prompt.lower())
            self.assertIn("needs_human", prompt)
            self.assertNotIn("stop and wait for further instructions", prompt.lower())
            self.assertIn("create a git commit before writing the generator artifacts", prompt)
            self.assertIn("Why those changes move the code toward satisfying `contract.md`", prompt)
            self.assertIn("Commit created for this turn, or explicitly say that no repo-tracked files changed", prompt)
            self.assertIn("COUNCIL_TERMINAL_SUMMARY_BEGIN", prompt)
            self.assertIn("COUNCIL_TERMINAL_SUMMARY_END", prompt)
            self.assertIn("Changed invariants / preserved invariants", prompt)
            self.assertIn("Downstream readers / consumers checked", prompt)
            self.assertIn("Failure modes and fallback behavior considered", prompt)
            self.assertIn("Verification performed", prompt)
            self.assertIn("Canonical council files for this task", prompt)
            self.assertIn(str(turn_dir / "generator" / "message.md"), prompt)
            self.assertIn(str(turn_dir / "generator" / "status.json"), prompt)
            self.assertIn('{"result":"implemented|no_changes_needed|blocked"', prompt)
            self.assertIn("Current feature spec", prompt)
            self.assertIn("Current definition of done", prompt)

    def test_build_generator_turn_prompt_later_turn_references_paths_not_inlined_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0002"
            previous_turn_dir = turn_dir.parent / "0001"
            task_root.mkdir(parents=True)
            previous_turn_dir.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator additions.", encoding="utf-8")
            (previous_turn_dir / "reviewer").mkdir(parents=True)
            (previous_turn_dir / "reviewer" / "message.md").write_text("Review text", encoding="utf-8")
            (previous_turn_dir / "reviewer" / "status.json").write_text("{}", encoding="utf-8")
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=False,
            )
            self.assertIn(str(task_root / "task.md"), prompt)
            self.assertIn(str(task_root / "contract.md"), prompt)
            self.assertIn(str(previous_turn_dir / "reviewer" / "message.md"), prompt)
            self.assertNotIn("Shared rules.", prompt)
            self.assertNotIn("Generator additions.", prompt)
            self.assertNotIn("The previous reviewer verdict was `changes_requested`.", prompt)
            self.assertIn("create a git commit before writing the generator artifacts", prompt)
            self.assertIn("Read the current feature spec in `task.md`", prompt)

    def test_build_generator_turn_prompt_highlights_actionable_follow_up_after_changes_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0002"
            previous_turn_dir = turn_dir.parent / "0001"
            task_root.mkdir(parents=True)
            (previous_turn_dir / "reviewer").mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator additions.", encoding="utf-8")
            MODULE.write_text(previous_turn_dir / "reviewer" / "message.md", "Review text")
            MODULE.save_json(
                previous_turn_dir / "reviewer" / "status.json",
                {
                    "verdict": "changes_requested",
                    "summary": "Needs another pass.",
                    "blocking_issues": ["Add automated tests for the fallback path."],
                    "critical_dimensions": {
                        "correctness_vs_intent": "fail",
                        "regression_risk": "pass",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "fail",
                        "maintainability": "pass",
                    },
                },
            )
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=False,
            )
            self.assertIn("The previous reviewer verdict was `changes_requested`.", prompt)
            self.assertIn("Do not use `blocked` merely because the overall contract is still large or not yet complete.", prompt)
            self.assertIn("Add automated tests for the fallback path.", prompt)
            self.assertIn("create a git commit before writing the generator artifacts", prompt)
            self.assertIn("COUNCIL_TERMINAL_SUMMARY_BEGIN", prompt)

    def test_build_generator_turn_prompt_can_include_continue_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0002"
            previous_turn_dir = turn_dir.parent / "0001"
            task_root.mkdir(parents=True)
            (previous_turn_dir / "reviewer").mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator additions.", encoding="utf-8")
            MODULE.write_text(previous_turn_dir / "reviewer" / "message.md", "Review text")
            MODULE.save_json(
                previous_turn_dir / "reviewer" / "status.json",
                {
                    "verdict": "needs_human",
                    "summary": "Clarify the contract.",
                    "blocking_issues": ["Contract is too broad."],
                    "critical_dimensions": {
                        "correctness_vs_intent": "uncertain",
                        "regression_risk": "uncertain",
                        "failure_mode_and_fallback": "uncertain",
                        "state_and_metadata_integrity": "uncertain",
                        "test_adequacy": "uncertain",
                        "maintainability": "uncertain",
                    },
                    "human_message": "Clarify the contract.",
                    "human_source": "contract.md",
                },
            )
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=False,
                continue_context_block="This run is continuing after `paused_needs_human`.",
            )
            self.assertIn("This run is continuing after `paused_needs_human`.", prompt)

    def test_build_reviewer_turn_prompt_mentions_changes_requested_and_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text(
                MODULE.read_template("scaffold", "reviewer.instructions.md"),
                encoding="utf-8",
            )
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=True,
            )
            self.assertIn("Treat yourself as an external evaluator", prompt)
            self.assertIn("changes_requested", prompt)
            self.assertIn("needs_human", prompt)
            self.assertIn("contract.md", prompt)
            self.assertIn("Read the current feature spec in `task.md`", prompt)
            self.assertIn("Contract checklist copied from `contract.md`", prompt)
            self.assertIn("If the only remaining blocker is that `contract.md` is too broad", prompt)
            self.assertIn("Critical review dimensions", prompt)
            self.assertIn("COUNCIL_TERMINAL_SUMMARY_BEGIN", prompt)
            self.assertIn("[pass]", prompt)
            self.assertIn("[fail]", prompt)
            self.assertIn("[uncertain]", prompt)
            self.assertIn("correctness vs intent", prompt)
            self.assertIn("failure mode and fallback", prompt)
            self.assertIn("inspect both writers and downstream readers/consumers", prompt)
            self.assertIn("independent falsification attempt", prompt)
            self.assertNotIn("reviewed_commit_sha", prompt)
            self.assertIn(str(turn_dir / "reviewer" / "message.md"), prompt)
            self.assertIn(str(turn_dir / "reviewer" / "status.json"), prompt)
            self.assertIn('{"verdict":"approved|changes_requested|blocked"', prompt)
            self.assertIn("Current definition of done", prompt)

    def test_build_spec_backed_prompt_can_include_fork_context_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator additions.", encoding="utf-8")
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                inline_context=True,
                fork_context_block=MODULE.format_fork_context_block(
                    {"bootstrap_mode": "fork"}
                ),
            )
            self.assertIn("Fork context:", prompt)
            self.assertIn("prior Codex chat context", prompt)
            self.assertIn("task.md", prompt)
            self.assertIn("contract.md", prompt)

    def test_build_inherited_context_prompts_avoid_task_and_contract_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "AGENTS.md").write_text("Inherited council brief.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator inherited instructions.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer inherited instructions.", encoding="utf-8")
            generator_prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_INHERITED_CONTEXT,
                inline_context=True,
                fork_context_block=MODULE.format_fork_context_block(
                    {"bootstrap_mode": "fork"}
                ),
            )
            reviewer_prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                workspace_mode=MODULE.WORKSPACE_MODE_INHERITED_CONTEXT,
                inline_context=True,
                fork_context_block=MODULE.format_fork_context_block(
                    {"bootstrap_mode": "fork"}
                ),
            )
            self.assertIn("Inherited council brief.", generator_prompt)
            self.assertIn("Generator inherited instructions.", generator_prompt)
            self.assertNotIn("task.md", generator_prompt)
            self.assertNotIn("contract.md", generator_prompt)
            self.assertIn("Fork context:", generator_prompt)
            self.assertIn("Use the inherited chat context already present in this Codex session", reviewer_prompt)
            self.assertNotIn("task.md", reviewer_prompt)
            self.assertNotIn("contract.md", reviewer_prompt)
            self.assertIn("Critical review dimensions", reviewer_prompt)

    def test_build_simple_mode_prompts_use_initial_review_and_focus_on_code_risk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "initial_review.md").write_text(
                "# Initial Review\n\n- Fix the regression in parser fallback.",
                encoding="utf-8",
            )
            (task_root / "AGENTS.md").write_text("Simple council brief.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Simple generator instructions.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Simple reviewer instructions.", encoding="utf-8")
            generator_prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                workspace_mode=MODULE.WORKSPACE_MODE_SIMPLE,
                inline_context=True,
            )
            reviewer_prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                workspace_mode=MODULE.WORKSPACE_MODE_SIMPLE,
                inline_context=True,
            )
            self.assertIn("initial_review.md", generator_prompt)
            self.assertIn("classify each review point as `agree`, `disagree`, or `uncertain`", generator_prompt)
            self.assertIn("Do not introduce bad code, new errors, unintended behavior, regressions, tech debt, or clear unnecessary complexity", generator_prompt)
            self.assertNotIn("task.md", generator_prompt)
            self.assertNotIn("contract.md", generator_prompt)
            self.assertNotIn("Shared council brief from", generator_prompt)
            self.assertIn("Read these files directly for the review:", reviewer_prompt)
            self.assertIn("introduced errors", reviewer_prompt)
            self.assertIn("clear unnecessary complexity", reviewer_prompt)
            self.assertIn("Do not restate the same blocker without stronger evidence", reviewer_prompt)
            self.assertNotIn("task.md", reviewer_prompt)
            self.assertNotIn("contract.md", reviewer_prompt)

    def test_load_critical_review_dimensions_from_template_file(self) -> None:
        dimensions = MODULE.load_critical_review_dimensions()
        self.assertTrue(any(item["key"] == "correctness_vs_intent" for item in dimensions))
        self.assertTrue(any(item["label"] == "maintainability" for item in dimensions))

    def test_build_continue_context_inherited_mode_avoids_task_and_contract_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            previous_turn_dir = run_dir / "turns" / "0001"
            (previous_turn_dir / "generator").mkdir(parents=True)
            MODULE.write_text(previous_turn_dir / "generator" / "message.md", "generator message")
            MODULE.save_json(
                previous_turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            context = MODULE.build_continue_context(
                state={"status": "paused_needs_human"},
                previous_turn_dir=previous_turn_dir,
                role="generator",
                workspace_mode=MODULE.WORKSPACE_MODE_INHERITED_CONTEXT,
            )
            self.assertNotIn("task.md", context)
            self.assertNotIn("contract.md", context)
            self.assertIn("available canonical council files", context)

    def test_build_continue_context_simple_mode_mentions_initial_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            previous_turn_dir = run_dir / "turns" / "0001"
            (previous_turn_dir / "generator").mkdir(parents=True)
            MODULE.write_text(previous_turn_dir / "generator" / "message.md", "generator message")
            MODULE.save_json(
                previous_turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            context = MODULE.build_continue_context(
                state={"status": "paused_needs_human"},
                previous_turn_dir=previous_turn_dir,
                role="generator",
                workspace_mode=MODULE.WORKSPACE_MODE_SIMPLE,
            )
            self.assertIn("current initial review", context)

    def test_wait_for_role_artifacts_returns_valid_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir)
            (turn_dir / "generator").mkdir(parents=True)
            (turn_dir / "generator" / "message.md").write_text("Implemented.", encoding="utf-8")
            (turn_dir / "generator" / "status.json").write_text(
                json.dumps(
                    {
                        "result": "implemented",
                        "summary": "Added feature.",
                        "changed_files": ["scripts/feature.py"],
                    }
                ),
                encoding="utf-8",
            )
            artifact_path, status_path, status = MODULE.wait_for_role_artifacts(
                turn_dir,
                "generator",
                validator=MODULE.validate_generator_status,
                timeout_seconds=1,
                phase="generator_artifacts",
                tmux_name="generator-session",
                turn_number=1,
                repo_root=Path("/repo"),
                council_config={
                    "codex": {
                        "model": "gpt-5.4",
                        "model_reasoning_effort": "xhigh",
                        "dangerously_bypass_approvals_and_sandbox": True,
                        "no_alt_screen": True,
                    }
                },
            )
            self.assertEqual(artifact_path.name, "message.md")
            self.assertEqual(status_path.name, "status.json")
            self.assertEqual(status["result"], "implemented")

    def test_wait_for_role_artifacts_repairs_invalid_status_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            (turn_dir / "reviewer").mkdir(parents=True)
            message_path = turn_dir / "reviewer" / "message.md"
            status_path = turn_dir / "reviewer" / "status.json"
            message_path.write_text("Initial review", encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "verdict": "changes_requested",
                        "summary": "Needs one more fix.",
                        "blocking_issues": ["Fix the fallback path."],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "pass",
                            "failure_mode_and_fallback": "pass",
                            "state_and_metadata_integrity": "uncertain",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                        "human_message": "   should not be here   ",
                    }
                ),
                encoding="utf-8",
            )

            def fake_wait_for_tmux_prompt(*args, **kwargs):
                return None

            def fake_tmux_send_prompt(*args, **kwargs):
                status_path.write_text(
                    json.dumps(
                        {
                            "verdict": "changes_requested",
                            "summary": "Needs one more fix.",
                            "blocking_issues": ["Fix the fallback path."],
                            "critical_dimensions": {
                                "correctness_vs_intent": "fail",
                                "regression_risk": "pass",
                                "failure_mode_and_fallback": "pass",
                                "state_and_metadata_integrity": "uncertain",
                                "test_adequacy": "fail",
                                "maintainability": "pass",
                            },
                        }
                    ),
                    encoding="utf-8",
                )

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", fake_wait_for_tmux_prompt), mock.patch.object(
                MODULE, "tmux_send_prompt", fake_tmux_send_prompt
            ):
                artifact_path, status_path_value, status = MODULE.wait_for_role_artifacts(
                    turn_dir,
                    "reviewer",
                    validator=MODULE.validate_reviewer_status,
                    timeout_seconds=1,
                    phase="reviewer_artifacts",
                    tmux_name="reviewer-session",
                    turn_number=1,
                    repo_root=Path("/repo"),
                    council_config={
                        "codex": {
                            "model": "gpt-5.4",
                            "model_reasoning_effort": "xhigh",
                            "dangerously_bypass_approvals_and_sandbox": True,
                            "no_alt_screen": True,
                        }
                    },
                )

            self.assertEqual(artifact_path, message_path)
            self.assertEqual(status_path_value, status_path)
            self.assertEqual(status["verdict"], "changes_requested")
            self.assertTrue((turn_dir / "reviewer" / "validation_error.json").exists())

    def test_write_raw_final_output_artifact_writes_capture_note_when_summary_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            (turn_dir / "reviewer").mkdir(parents=True)
            expected = "Final reviewer summary.\n- point"
            MODULE.write_text(turn_dir / "reviewer" / "message.md", expected)

            def fake_wait(*args, **kwargs):
                return None

            def fake_capture(*args, **kwargs):
                return "Repository root:\n/repo\n• Ran cat file.txt\n"

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", fake_wait), mock.patch.object(
                MODULE, "capture_last_tmux_slice", fake_capture
            ):
                MODULE.write_raw_final_output_artifact(turn_dir, "reviewer", "reviewer-session")

            self.assertIn(
                "terminal summary unavailable",
                (turn_dir / "reviewer" / "raw_final_output.md").read_text(encoding="utf-8").lower(),
            )
            self.assertEqual(
                MODULE.load_json(turn_dir / "reviewer" / "capture_status.json")["status"],
                "unavailable",
            )

    def test_write_raw_final_output_artifact_uses_terminal_summary_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            (turn_dir / "reviewer").mkdir(parents=True)
            MODULE.write_text(turn_dir / "reviewer" / "message.md", "Final reviewer summary.\n- point")

            def fake_wait(*args, **kwargs):
                return None

            def fake_capture(*args, **kwargs):
                return "\n".join(
                    [
                        "noise",
                        "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                        "Short terminal summary",
                        "COUNCIL_TERMINAL_SUMMARY_END",
                    ]
                )

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", fake_wait), mock.patch.object(
                MODULE, "capture_last_tmux_slice", fake_capture
            ):
                MODULE.write_raw_final_output_artifact(turn_dir, "reviewer", "reviewer-session")

            self.assertEqual(
                (turn_dir / "reviewer" / "raw_final_output.md").read_text(encoding="utf-8").strip(),
                "Short terminal summary",
            )
            self.assertEqual(
                MODULE.load_json(turn_dir / "reviewer" / "capture_status.json")["status"],
                "captured",
            )

    def test_wait_for_role_artifacts_stops_after_failed_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            (turn_dir / "reviewer").mkdir(parents=True)
            message_path = turn_dir / "reviewer" / "message.md"
            status_path = turn_dir / "reviewer" / "status.json"
            message_path.write_text("Initial review", encoding="utf-8")
            status_path.write_text(
                json.dumps(
                    {
                        "verdict": "changes_requested",
                        "summary": "Needs one more fix.",
                        "blocking_issues": ["Fix the fallback path."],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "pass",
                            "failure_mode_and_fallback": "pass",
                            "state_and_metadata_integrity": "uncertain",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                        "human_message": "bad extra field",
                    }
                ),
                encoding="utf-8",
            )

            def fake_wait_for_tmux_prompt(*args, **kwargs):
                return None

            def fake_tmux_send_prompt(*args, **kwargs):
                status_path.write_text(
                    json.dumps(
                        {
                            "verdict": "changes_requested",
                            "summary": "Still invalid.",
                            "blocking_issues": ["Fix the fallback path."],
                            "critical_dimensions": {
                                "correctness_vs_intent": "fail",
                                "regression_risk": "pass",
                                "failure_mode_and_fallback": "pass",
                                "state_and_metadata_integrity": "uncertain",
                                "test_adequacy": "fail",
                                "maintainability": "pass",
                            },
                            "human_source": "task.md",
                        }
                    ),
                    encoding="utf-8",
                )

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", fake_wait_for_tmux_prompt), mock.patch.object(
                MODULE, "tmux_send_prompt", fake_tmux_send_prompt
            ):
                with self.assertRaises(MODULE.SupervisorRuntimeError) as cm:
                    MODULE.wait_for_role_artifacts(
                        turn_dir,
                        "reviewer",
                        validator=MODULE.validate_reviewer_status,
                        timeout_seconds=1,
                        phase="reviewer_artifacts",
                        tmux_name="reviewer-session",
                        turn_number=1,
                        repo_root=Path("/repo"),
                        council_config={
                            "codex": {
                                "model": "gpt-5.4",
                                "model_reasoning_effort": "xhigh",
                                "dangerously_bypass_approvals_and_sandbox": True,
                                "no_alt_screen": True,
                            }
                        },
                    )
            self.assertEqual(cm.exception.phase, "blocked_invalid_artifacts")

    def test_latest_run_dir_picks_lexically_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / "task"
            (task_root / "runs" / "20260408-120000-aaaaaa").mkdir(parents=True)
            (task_root / "runs" / "20260408-130000-bbbbbb").mkdir(parents=True)
            self.assertEqual(
                MODULE.latest_run_dir(task_root).name,
                "20260408-130000-bbbbbb",
            )

    def test_create_run_state_tracks_repo_local_paths(self) -> None:
        repo_root = Path("/repo")
        task_root = repo_root / ".codex-council" / "demo-task"
        state = MODULE.create_run_state(
            repo_root=repo_root,
            task_root=task_root,
            task_name="demo-task",
            run_id="20260408-abc123",
            workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
            council_config={
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
            },
            git_state=None,
            generator_session="gen",
            reviewer_session="rev",
        )
        self.assertEqual(state["repo_root"], str(repo_root))
        self.assertEqual(state["task_root"], str(task_root))
        self.assertEqual(state["task_name"], "demo-task")
        self.assertEqual(state["roles"]["generator"]["tmux_session"], "gen")
        self.assertEqual(state["workspace_mode"], MODULE.WORKSPACE_MODE_SPEC_BACKED)
        self.assertEqual(state["roles"]["generator"]["bootstrap_mode"], "fresh")

    def test_build_role_session_command_prefers_fork_then_resume(self) -> None:
        council_config = {
            "codex": {
                "model": "gpt-5.4",
                "model_reasoning_effort": "xhigh",
                "dangerously_bypass_approvals_and_sandbox": True,
                "no_alt_screen": True,
            }
        }
        repo_root = Path("/repo")
        fork_command = MODULE.build_role_session_command(
            repo_root,
            council_config,
            {
                "bootstrap_mode": "fork",
                "fork_parent_session_id": "parent-id",
                "codex_session_id": None,
            },
        )
        resumed_command = MODULE.build_role_session_command(
            repo_root,
            council_config,
            {
                "bootstrap_mode": "fork",
                "fork_parent_session_id": "parent-id",
                "codex_session_id": "child-id",
            },
        )
        self.assertEqual(fork_command[0:2], ["codex", "fork"])
        self.assertEqual(fork_command[-1], "parent-id")
        self.assertEqual(resumed_command[0:2], ["codex", "resume"])
        self.assertEqual(resumed_command[-1], "child-id")

    def test_assign_recent_codex_session_ids_filters_to_run_creation_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            run_dir.mkdir(parents=True)
            state = MODULE.create_run_state(
                repo_root=Path("/repo"),
                task_root=Path("/repo/.codex-council/demo-task"),
                task_name="demo-task",
                run_id="run-1",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                council_config={
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
                },
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
            )
            state["created_at"] = "2026-04-10T12:00:00Z"
            state["session_index_snapshot_ids"] = []
            with mock.patch.object(
                MODULE,
                "read_codex_session_index",
                return_value=[
                    {"id": "old", "updated_at": "2026-04-10T11:59:00Z", "thread_name": "old"},
                    {"id": "new-gen", "updated_at": "2026-04-10T12:00:01Z", "thread_name": "gen"},
                    {"id": "new-rev", "updated_at": "2026-04-10T12:00:02Z", "thread_name": "rev"},
                ],
            ):
                MODULE.assign_recent_codex_session_ids(run_dir, state)
            self.assertEqual(state["roles"]["generator"]["codex_session_id"], "new-gen")
            self.assertEqual(state["roles"]["reviewer"]["codex_session_id"], "new-rev")

    def test_start_run_requires_both_fork_session_ids_in_inherited_context_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                skip_task_and_contract=True,
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                generator_fork_session_id="parent-gen",
                reviewer_fork_session_id=None,
            )
            with self.assertRaises(SystemExit) as cm:
                MODULE.start_run(args)
            self.assertIn("--generator-fork-session-id", str(cm.exception))

    def test_start_run_inherited_context_allows_dirty_repo_with_valid_fork_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            (repo_root / "file.txt").write_text("dirty change", encoding="utf-8")
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                skip_task_and_contract=True,
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session="rev",
                generator_fork_session_id="parent-gen",
                reviewer_fork_session_id="parent-rev",
            )
            with mock.patch.object(
                MODULE,
                "find_codex_session_entry",
                side_effect=lambda session_id: {"id": session_id, "updated_at": "2026-04-10T12:00:00Z", "thread_name": session_id},
            ), mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
                MODULE, "create_tmux_sessions", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_sessions_ready", return_value=None
            ), mock.patch.object(MODULE, "supervisor_loop", return_value=None), contextlib.redirect_stdout(
                io.StringIO()
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            state = MODULE.load_json(task_root / "runs" / "run-1" / "state.json")
            self.assertEqual(state["workspace_mode"], MODULE.WORKSPACE_MODE_INHERITED_CONTEXT)
            self.assertEqual(state["roles"]["generator"]["bootstrap_mode"], "fork")
            self.assertEqual(state["roles"]["generator"]["fork_parent_session_id"], "parent-gen")

    def test_start_run_spec_backed_still_rejects_dirty_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text="Implement a concrete feature.",
            )
            (task_root / "contract.md").write_text(
                "# Definition of Done\n\n- [ ] Concrete acceptance criterion",
                encoding="utf-8",
            )
            (repo_root / "file.txt").write_text("dirty change", encoding="utf-8")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
            )
            with self.assertRaises(SystemExit):
                MODULE.start_run(args)

    def test_start_run_simple_mode_rejects_placeholder_initial_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                simple_mode=True,
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
            )
            with self.assertRaises(SystemExit):
                MODULE.start_run(args)

    def test_start_run_simple_mode_can_start_fresh_without_fork_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                simple_mode=True,
            )
            (task_root / "initial_review.md").write_text(
                "# Initial Review\n\n- Fix the parser regression.\n",
                encoding="utf-8",
            )
            self.commit_repo_changes(repo_root, "add simple task")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session="rev",
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
            )
            with mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
                MODULE, "create_tmux_sessions", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_sessions_ready", return_value=None
            ), mock.patch.object(MODULE, "supervisor_loop", return_value=None), contextlib.redirect_stdout(
                io.StringIO()
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            state = MODULE.load_json(task_root / "runs" / "run-1" / "state.json")
            self.assertEqual(state["workspace_mode"], MODULE.WORKSPACE_MODE_SIMPLE)
            self.assertEqual(state["roles"]["generator"]["bootstrap_mode"], "fresh")

    def test_start_run_simple_mode_still_rejects_dirty_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            MODULE.scaffold_council_root(repo_root)
            task_root = MODULE.task_root_for(repo_root, "demo-task")
            MODULE.scaffold_task_root(
                task_root,
                initial_task_text=None,
                simple_mode=True,
            )
            (task_root / "initial_review.md").write_text(
                "# Initial Review\n\n- Fix the parser regression.\n",
                encoding="utf-8",
            )
            self.commit_repo_changes(repo_root, "add simple task")
            (repo_root / "file.txt").write_text("dirty change", encoding="utf-8")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session=None,
                reviewer_session=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
            )
            with self.assertRaises(SystemExit):
                MODULE.start_run(args)

    def test_determine_continue_target_routes_from_generator_pending_same_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            turn_dir = run_dir / "turns" / "0005" / "generator"
            turn_dir.mkdir(parents=True)
            MODULE.save_json(
                run_dir / "turns" / "0005" / "turn.json",
                {
                    "turn": "0005",
                    "phase": "generator_prompt_sent",
                    "role": "generator",
                },
            )
            state = {"status": "waiting_generator", "current_turn": 5}
            latest_turn, turn_number, role, create_new_turn, prior_status = MODULE.determine_continue_target(run_dir, state)
            self.assertEqual(latest_turn.name, "0005")
            self.assertEqual(turn_number, 5)
            self.assertEqual(role, "generator")
            self.assertFalse(create_new_turn)
            self.assertEqual(prior_status, "generator_pending")

    def test_determine_continue_target_routes_from_reviewer_changes_requested_to_next_generator_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            turn_dir = run_dir / "turns" / "0005"
            (turn_dir / "generator").mkdir(parents=True)
            (turn_dir / "reviewer").mkdir(parents=True)
            MODULE.write_text(turn_dir / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_dir / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_dir / "reviewer" / "status.json",
                {
                    "verdict": "changes_requested",
                    "summary": "fix it",
                    "blocking_issues": ["one fix"],
                    "critical_dimensions": {
                        "correctness_vs_intent": "fail",
                        "regression_risk": "pass",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "fail",
                        "maintainability": "pass",
                    },
                },
            )
            MODULE.save_json(turn_dir / "turn.json", {"turn": "0005", "phase": "changes_requested", "role": "reviewer"})
            state = {"status": "paused_needs_human", "current_turn": 5}
            latest_turn, turn_number, role, create_new_turn, prior_status = MODULE.determine_continue_target(run_dir, state)
            self.assertEqual(latest_turn.name, "0005")
            self.assertEqual(turn_number, 6)
            self.assertEqual(role, "generator")
            self.assertTrue(create_new_turn)
            self.assertEqual(prior_status, "reviewer_changes_requested")

    def test_determine_continue_target_routes_reviewer_needs_human_to_same_role_next_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            turn_dir = run_dir / "turns" / "0005"
            (turn_dir / "generator").mkdir(parents=True)
            (turn_dir / "reviewer").mkdir(parents=True)
            MODULE.write_text(turn_dir / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_dir / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_dir / "reviewer" / "status.json",
                {
                    "verdict": "needs_human",
                    "summary": "clarify contract",
                    "blocking_issues": ["broad contract"],
                    "critical_dimensions": {
                        "correctness_vs_intent": "pass",
                        "regression_risk": "pass",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "pass",
                        "maintainability": "pass",
                    },
                    "human_message": "clarify",
                    "human_source": "contract.md",
                },
            )
            MODULE.save_json(turn_dir / "turn.json", {"turn": "0005", "phase": "paused_needs_human", "role": "reviewer"})
            state = {"status": "paused_needs_human", "current_turn": 5}
            latest_turn, turn_number, role, create_new_turn, prior_status = MODULE.determine_continue_target(run_dir, state)
            self.assertEqual(latest_turn.name, "0005")
            self.assertEqual(turn_number, 6)
            self.assertEqual(role, "reviewer")
            self.assertTrue(create_new_turn)
            self.assertEqual(prior_status, "reviewer_needs_human")

    def test_determine_continue_target_rejects_reviewer_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "runs" / "run-1"
            turn_dir = run_dir / "turns" / "0005"
            (turn_dir / "generator").mkdir(parents=True)
            (turn_dir / "reviewer").mkdir(parents=True)
            MODULE.write_text(turn_dir / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_dir / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_dir / "reviewer" / "status.json",
                {
                    "verdict": "approved",
                    "summary": "approved",
                    "blocking_issues": [],
                    "critical_dimensions": {
                        "correctness_vs_intent": "pass",
                        "regression_risk": "pass",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "pass",
                        "maintainability": "pass",
                    },
                },
            )
            MODULE.save_json(turn_dir / "turn.json", {"turn": "0005", "phase": "approved", "role": "reviewer"})
            with self.assertRaises(SystemExit):
                MODULE.determine_continue_target(run_dir, {"status": "approved", "current_turn": 5})

    def test_supervisor_loop_advances_after_changes_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            task_root = repo_root / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "generator.instructions.md").write_text("Generator rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer rules.", encoding="utf-8")
            run_dir = task_root / "runs" / "run-1"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_mode=MODULE.WORKSPACE_MODE_SPEC_BACKED,
                council_config={
                    "codex": {
                        "model": "gpt-5.4",
                        "model_reasoning_effort": "xhigh",
                        "dangerously_bypass_approvals_and_sandbox": True,
                        "no_alt_screen": True,
                    },
                    "council": {
                        "max_turns": 2,
                        "launch_timeout_seconds": 60,
                        "turn_timeout_seconds": 1800,
                        "require_git": True,
                    },
                },
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
            )
            MODULE.save_run_state(run_dir, state)

            def fake_wait_for_tmux_prompt(*args, **kwargs):
                return None

            def fake_tmux_send_prompt(*args, **kwargs):
                return None

            def fake_write_raw_output(*args, **kwargs):
                return None

            def fake_wait_for_role_artifacts(current_turn_dir, role, **kwargs):
                message_path, status_path = MODULE.role_artifact_paths(current_turn_dir, role)
                if current_turn_dir.name == "0001" and role == "generator":
                    status = {
                        "result": "implemented",
                        "summary": "Implemented first pass.",
                        "changed_files": ["src/app.py"],
                    }
                elif current_turn_dir.name == "0001" and role == "reviewer":
                    status = {
                        "verdict": "changes_requested",
                        "summary": "Needs one more fix.",
                        "blocking_issues": ["Fix the fallback path."],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "pass",
                            "failure_mode_and_fallback": "pass",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                    }
                elif current_turn_dir.name == "0002" and role == "generator":
                    status = {
                        "result": "no_changes_needed",
                        "summary": "No extra changes needed.",
                        "changed_files": [],
                    }
                else:
                    status = {
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
                MODULE.write_text(message_path, f"{role} message for {current_turn_dir.name}")
                MODULE.save_json(status_path, status)
                return message_path, status_path, status

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", fake_wait_for_tmux_prompt), mock.patch.object(
                MODULE, "tmux_send_prompt", fake_tmux_send_prompt
            ), mock.patch.object(
                MODULE, "write_raw_final_output_artifact", fake_write_raw_output
            ), mock.patch.object(
                MODULE, "wait_for_role_artifacts", fake_wait_for_role_artifacts
            ):
                MODULE.supervisor_loop(run_dir, state, task_root)

            self.assertEqual(state["status"], "approved")
            self.assertTrue((run_dir / "turns" / "0002" / "generator" / "prompt.md").exists())
            self.assertEqual(
                MODULE.load_json(run_dir / "turns" / "0001" / "turn.json")["phase"],
                "changes_requested",
            )

    def test_ensure_task_workspace_exists_raises_for_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            with self.assertRaises(SystemExit):
                MODULE.ensure_task_workspace_exists(task_root)

    def test_pause_for_human_updates_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            state = {
                "status": "waiting_generator",
                "stop_reason": None,
                "workspace_mode": MODULE.WORKSPACE_MODE_SPEC_BACKED,
            }
            MODULE.save_json(run_dir / "state.json", state)
            turn_dir = run_dir / "turns" / "0001"
            turn_dir.mkdir(parents=True)
            with contextlib.redirect_stdout(io.StringIO()):
                MODULE.pause_for_human(
                    run_dir,
                    state,
                    role="reviewer",
                    turn_dir=turn_dir,
                    summary="Task plan needs clarification.",
                    human_message="Clarify whether the endpoint change is allowed.",
                    human_source="task.md",
                )
            self.assertEqual(state["status"], "paused_needs_human")
            self.assertEqual(state["stop_reason"], "Task plan needs clarification.")

    def test_pause_for_human_inherited_mode_avoids_task_and_contract_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            state = {
                "status": "waiting_generator",
                "stop_reason": None,
                "workspace_mode": MODULE.WORKSPACE_MODE_INHERITED_CONTEXT,
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
                    human_message="Clarify the inherited intent.",
                    human_source="repo_state",
                )
            rendered = output.getvalue()
            self.assertNotIn("task.md", rendered)
            self.assertNotIn("contract.md", rendered)
            self.assertIn("feature spec and definition-of-done", rendered)

    def test_pause_for_human_simple_mode_mentions_initial_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir)
            state = {
                "status": "waiting_generator",
                "stop_reason": None,
                "workspace_mode": MODULE.WORKSPACE_MODE_SIMPLE,
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
                    human_message="Clarify the initial review.",
                    human_source="initial_review.md",
                )
            rendered = output.getvalue()
            self.assertIn("initial_review.md", rendered)
            self.assertNotIn("task.md / contract.md", rendered)


if __name__ == "__main__":
    unittest.main()
