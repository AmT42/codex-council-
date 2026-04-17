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
FIXTURES_ROOT = MODULE_PATH.parents[1] / "tests" / "fixtures"
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
            "review": {
                "fresh_reviewer_session_per_turn": True,
                "allow_reviewer_test_edits": True,
                "allow_reviewer_production_edits": False,
                "require_primary_path_smoke": True,
                "require_branch_health_gate": True,
                "require_changed_file_coverage": True,
                "baseline_commands": ["git diff --check"],
                "path_rules": [],
            },
        }

    def write_generator_status(self, turn_dir: Path, *, changed_files: list[str] | None = None) -> None:
        (turn_dir / "generator").mkdir(parents=True, exist_ok=True)
        (turn_dir / "generator" / "message.md").write_text("generator", encoding="utf-8")
        MODULE.save_json(
            turn_dir / "generator" / "status.json",
            {
                "result": "implemented",
                "summary": "Made a change.",
                "changed_files": changed_files or ["src/example.py"],
            },
        )

    def build_reviewer_evidence(
        self,
        *,
        changed_files: list[str] | None = None,
        required_commands: list[str] | None = None,
        inspected_paths: list[str] | None = None,
        failing_commands: list[str] | None = None,
        smoke_checks: list[dict[str, str]] | None = None,
        approval_gates: dict[str, bool] | None = None,
        reviewer_authored_tests: list[str] | None = None,
    ) -> dict:
        changed = changed_files or ["src/example.py"]
        commands = required_commands or ["git diff --check"]
        failing = failing_commands or []
        command_results = [
            {"command": command, "result": "failed" if command in failing else "passed"}
            for command in commands
        ]
        return {
            "changed_files": changed,
            "inspected_paths": inspected_paths or list(changed),
            "primary_user_path": "CLI path -> service path",
            "fallback_paths_checked": ["fallback/path.py"],
            "required_commands": commands,
            "commands_run": command_results,
            "failing_commands": failing,
            "reviewer_authored_tests": reviewer_authored_tests or [],
            "smoke_checks": (
                [{"name": "primary path smoke", "result": "passed"}]
                if smoke_checks is None
                else smoke_checks
            ),
            "contradictions_found": [],
            "approval_gates": approval_gates
            or {
                "scope_gate": True,
                "verification_gate": True,
                "primary_path_gate": True,
                "fallback_gate": True,
                "regression_gate": True,
                "evidence_gate": True,
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

    def test_load_council_config_reads_review_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            council_root = repo_root / MODULE.COUNCIL_DIRNAME
            council_root.mkdir()
            (council_root / "config.toml").write_text(
                """
[review]
fresh_reviewer_session_per_turn = false
allow_reviewer_test_edits = true
allow_reviewer_production_edits = false
require_primary_path_smoke = true
require_branch_health_gate = true
require_changed_file_coverage = true
baseline_commands = ["git diff --check", "pytest -q tests/test_example.py"]

[[review.path_rule]]
name = "workspace"
globs = ["src/**", "tests/**"]
commands = ["pytest -q tests/test_workspace.py"]
""".strip(),
                encoding="utf-8",
            )
            config = MODULE.load_council_config(repo_root)
            self.assertFalse(config["review"]["fresh_reviewer_session_per_turn"])
            self.assertEqual(
                config["review"]["baseline_commands"],
                ["git diff --check", "pytest -q tests/test_example.py"],
            )
            self.assertEqual(config["review"]["path_rules"][0]["name"], "workspace")

    def test_review_required_commands_for_changed_files_includes_matching_rules(self) -> None:
        council_config = self.build_council_config()
        council_config["review"]["path_rules"] = [
            {
                "name": "workspace",
                "globs": ["src/**", "tests/test_workspace.py"],
                "commands": ["pytest -q tests/test_workspace.py"],
            },
            {
                "name": "memory",
                "globs": ["src/memory.py"],
                "commands": ["pytest -q tests/test_memory.py"],
            },
        ]
        commands = MODULE.review_required_commands_for_changed_files(
            council_config,
            ["src/example.py", "tests/test_workspace.py"],
        )
        self.assertEqual(
            commands,
            ["git diff --check", "pytest -q tests/test_workspace.py"],
        )

    def test_validate_reviewer_artifacts_rejects_missing_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            self.write_generator_status(turn_dir)
            with self.assertRaisesRegex(FileNotFoundError, "missing reviewer evidence file"):
                MODULE.validate_reviewer_artifacts_for_turn(
                    turn_dir,
                    self.build_council_config(),
                    {
                        "verdict": "approved",
                        "summary": "ok",
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

    def test_validate_reviewer_artifacts_rejects_missing_required_command_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            self.write_generator_status(turn_dir, changed_files=["src/example.py"])
            council_config = self.build_council_config()
            council_config["review"]["path_rules"] = [
                {"name": "src", "globs": ["src/**"], "commands": ["pytest -q tests/test_example.py"]}
            ]
            MODULE.save_json(
                turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME,
                self.build_reviewer_evidence(
                    changed_files=["src/example.py"],
                    required_commands=["git diff --check", "pytest -q tests/test_example.py"],
                    failing_commands=[],
                ),
            )
            # Drop the mapped command from commands_run to force rejection.
            evidence = MODULE.load_json(turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME)
            evidence["commands_run"] = [{"command": "git diff --check", "result": "passed"}]
            MODULE.save_json(turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME, evidence)
            with self.assertRaisesRegex(ValueError, "must include every required command"):
                MODULE.validate_reviewer_artifacts_for_turn(
                    turn_dir,
                    council_config,
                    {
                        "verdict": "changes_requested",
                        "summary": "not clean",
                        "blocking_issues": ["x"],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "fail",
                            "failure_mode_and_fallback": "fail",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                    },
                )

    def test_validate_reviewer_artifacts_rejects_approved_with_failed_required_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            self.write_generator_status(turn_dir)
            MODULE.save_json(
                turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME,
                self.build_reviewer_evidence(failing_commands=["git diff --check"]),
            )
            with self.assertRaisesRegex(ValueError, "requires all required commands to pass"):
                MODULE.validate_reviewer_artifacts_for_turn(
                    turn_dir,
                    self.build_council_config(),
                    {
                        "verdict": "approved",
                        "summary": "ok",
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

    def test_validate_reviewer_artifacts_rejects_missing_changed_file_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            self.write_generator_status(turn_dir, changed_files=["src/example.py", "tests/test_example.py"])
            MODULE.save_json(
                turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME,
                self.build_reviewer_evidence(
                    changed_files=["src/example.py", "tests/test_example.py"],
                    inspected_paths=["src/example.py"],
                ),
            )
            with self.assertRaisesRegex(ValueError, "must cover all changed_files"):
                MODULE.validate_reviewer_artifacts_for_turn(
                    turn_dir,
                    self.build_council_config(),
                    {
                        "verdict": "changes_requested",
                        "summary": "missing coverage",
                        "blocking_issues": ["coverage"],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "fail",
                            "failure_mode_and_fallback": "fail",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                    },
                )

    def test_validate_reviewer_artifacts_rejects_missing_primary_smoke(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            self.write_generator_status(turn_dir)
            MODULE.save_json(
                turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME,
                self.build_reviewer_evidence(smoke_checks=[]),
            )
            with self.assertRaisesRegex(ValueError, "must include at least one primary-path smoke check"):
                MODULE.validate_reviewer_artifacts_for_turn(
                    turn_dir,
                    self.build_council_config(),
                    {
                        "verdict": "changes_requested",
                        "summary": "missing smoke",
                        "blocking_issues": ["smoke"],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "fail",
                            "failure_mode_and_fallback": "fail",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                    },
                )

    def test_normalize_reopen_reason_kind_rejects_unknown_value(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE.normalize_reopen_reason_kind("wrong")

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

    def test_write_raw_final_output_artifact_uses_full_pane_history_for_summary_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            (turn_dir / "reviewer").mkdir(parents=True)
            pane = "\n".join(
                [
                    "noise",
                    "COUNCIL_TERMINAL_SUMMARY_BEGIN",
                    "review complete",
                    "COUNCIL_TERMINAL_SUMMARY_END",
                    "",
                    "› Run /review on my current changes",
                ]
            )
            with mock.patch.object(MODULE, "wait_for_tmux_prompt", return_value=None), mock.patch.object(
                MODULE, "tmux_capture_joined_pane", return_value=pane
            ):
                MODULE.write_raw_final_output_artifact(turn_dir, "reviewer", "reviewer-session")
            self.assertEqual(
                (turn_dir / "reviewer" / "raw_final_output.md").read_text(encoding="utf-8").strip(),
                "review complete",
            )
            self.assertEqual(
                MODULE.load_json(turn_dir / "reviewer" / "capture_status.json"),
                {"status": "captured", "source": "terminal_summary_markers"},
            )

    def test_pane_has_trust_prompt_detects_codex_trust_screen(self) -> None:
        pane = "\n".join(
            [
                "You are in /tmp/repo",
                "Do you trust the contents of this directory?",
                "Press enter to continue",
            ]
        )
        self.assertTrue(MODULE.pane_has_trust_prompt(pane))
        self.assertEqual(MODULE.classify_tmux_pane(pane), "trust_prompt")
        self.assertFalse(MODULE.pane_shows_prompt(pane))

    def test_classify_tmux_pane_treats_non_footer_text_after_prompt_as_busy(self) -> None:
        pane = "\n".join(
            [
                "› Ready for prompt",
                "working...",
            ]
        )
        self.assertEqual(MODULE.classify_tmux_pane(pane), "busy")
        self.assertFalse(MODULE.pane_shows_prompt(pane))

    def test_classify_tmux_pane_accepts_codex_footer_after_prompt_line(self) -> None:
        pane = "\n".join(
            [
                "╭─────────────────────────────────────────────╮",
                "│ >_ OpenAI Codex (v0.120.0)                  │",
                "╰─────────────────────────────────────────────╯",
                "",
                "› Use /skills to list available skills",
                "",
                "  gpt-5.4 xhigh · ~/projects/demo",
            ]
        )
        self.assertTrue(MODULE.pane_has_codex_footer(pane))
        self.assertTrue(MODULE.pane_looks_interactive(pane))
        self.assertEqual(MODULE.classify_tmux_pane(pane), "ready")
        self.assertTrue(MODULE.pane_shows_prompt(pane))

    def test_wait_for_tmux_prompt_advances_past_trust_screen(self) -> None:
        trust_pane = "\n".join(
            [
                "You are in /tmp/repo",
                "Do you trust the contents of this directory?",
                "Press enter to continue",
            ]
        )
        ready_pane = "› Ready for prompt"
        with mock.patch.object(MODULE, "tmux_session_exists", side_effect=[True, True]), mock.patch.object(
            MODULE,
            "tmux_capture_pane",
            side_effect=[trust_pane, ready_pane],
        ), mock.patch.object(MODULE.time, "sleep", return_value=None), mock.patch.object(
            MODULE,
            "run_subprocess",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as run_subprocess:
            MODULE.wait_for_tmux_prompt("demo-session", 5, phase="demo", role="generator")
        run_subprocess.assert_called_once_with(["tmux", "send-keys", "-t", "demo-session", "Enter"])

    def test_tmux_send_prompt_retries_once_when_first_dispatch_does_not_change_pane(self) -> None:
        ready_pane = "› Ready for prompt"
        busy_pane = "running..."
        with mock.patch.object(
            MODULE,
            "tmux_capture_pane",
            side_effect=[ready_pane, ready_pane, busy_pane],
        ), mock.patch.object(
            MODULE.time,
            "sleep",
            return_value=None,
        ), mock.patch.object(
            MODULE,
            "run_subprocess",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ) as run_subprocess, mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ):
            MODULE.tmux_send_prompt("demo-session", "hello", phase="demo", role="generator")

        send_key_calls = [
            call
            for call in run_subprocess.call_args_list
            if call.args[0][:2] == ["tmux", "send-keys"]
        ]
        self.assertEqual(len(send_key_calls), 2)

    def test_tmux_send_prompt_blocks_when_dispatch_never_changes_pane(self) -> None:
        ready_pane = "› Ready for prompt"
        with mock.patch.object(
            MODULE,
            "tmux_capture_pane",
            side_effect=[ready_pane, ready_pane, ready_pane],
        ), mock.patch.object(
            MODULE.time,
            "sleep",
            return_value=None,
        ), mock.patch.object(
            MODULE,
            "run_subprocess",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ), mock.patch.object(
            MODULE.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr=""),
        ):
            with self.assertRaises(MODULE.SupervisorRuntimeError):
                MODULE.tmux_send_prompt("demo-session", "hello", phase="demo", role="generator")

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

    def test_golden_brief_quality_examples_pass_lints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            brief_root = FIXTURES_ROOT / "brief_quality"
            (task_root / MODULE.TASK_FILENAME).write_text((brief_root / "good_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.REVIEW_FILENAME).write_text((brief_root / "good_review.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text((brief_root / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text((brief_root / "good_contract.md").read_text(encoding="utf-8"), encoding="utf-8")

            self.assertEqual(MODULE.lint_task_workspace_readiness(task_root)[0], [])
            self.assertEqual(MODULE.lint_review_workspace_readiness(task_root / MODULE.REVIEW_FILENAME)[0], [])
            self.assertEqual(MODULE.lint_spec_workspace_readiness(task_root)[0], [])
            self.assertEqual(MODULE.lint_contract_workspace_readiness(task_root)[0], [])

    def test_lint_task_rejects_generic_success_signal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nDebug why sync duplicates rows after retry.\n\n## Context\n\n- The issue appears in the background sync worker.\n\n## Success Signal\n\nWorks.\n",
                encoding="utf-8",
            )
            errors, _ = MODULE.lint_task_workspace_readiness(task_root)
            self.assertTrue(any("success signal is too generic" in item for item in errors))

    def test_lint_review_rejects_generic_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            review_path = Path(tmp_dir) / "review.md"
            review_path.write_text("# Review\n\n## Findings\n\n- Fix this\n\n## Context\n\n- logs pending\n", encoding="utf-8")
            errors, _ = MODULE.lint_review_workspace_readiness(review_path)
            self.assertTrue(any("too generic" in item for item in errors))

    def test_lint_spec_rejects_unfilled_core_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nBuild dashboard\n\n## User Outcome\n\nUsers can use it.\n\n## In Scope\n\n- dashboard\n\n## Out of Scope\n\n- none\n\n## Constraints\n\n- keep API\n\n## Existing Context\n\nThere is an existing billing page.\n\n## Desired Behavior\n\nWorks.\n\n### Source of Truth / Ownership\n\nExisting billing state.\n\n### Read Path\n\nUse existing queries.\n\n### Write Path / Mutation Flow\n\nNot applicable because the page is read-only.\n\n### Runtime / Performance Expectations\n\nFast enough.\n\n### Failure / Fallback / Degraded Behavior\n\nHandle errors appropriately.\n\n### State / Integrity / Concurrency Invariants\n\nKeep it consistent.\n\n### Observability / Validation Hooks\n\nTests.\n\n## Technical Boundaries\n\n- keep routes stable\n\n## Validation Expectations\n\nTests.\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            errors, _ = MODULE.lint_spec_workspace_readiness(task_root)
            self.assertTrue(any("decision-complete" in item for item in errors))

    def test_lint_spec_requires_decision_complete_subsections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n"
                "## Goal\n\nImplement a memory system.\n\n"
                "## User Outcome\n\nOperators can rely on durable memory and recall.\n\n"
                "## In Scope\n\n- Memory runtime\n\n"
                "## Out of Scope\n\n- UI redesign\n\n"
                "## Constraints\n\n- Preserve the current database backend.\n\n"
                "## Existing Context\n\nThe repo already persists canonical events.\n\n"
                "## Desired Behavior\n\nThe system should support memory and recall.\n\n"
                "### Source of Truth / Ownership\n\nconversation events are involved.\n\n"
                "### Read Path\n\nimplementation defined.\n\n"
                "### Write Path / Mutation Flow\n\nas appropriate.\n\n"
                "### Runtime / Performance Expectations\n\nhandle edge cases appropriately.\n\n"
                "### Failure / Fallback / Degraded Behavior\n\nreuse existing infrastructure as appropriate.\n\n"
                "### State / Integrity / Concurrency Invariants\n\nleft to implementation.\n\n"
                "### Observability / Validation Hooks\n\nuse best judgment.\n\n"
                "## Technical Boundaries\n\n- Existing interfaces stay stable.\n\n"
                "## Validation Expectations\n\nRelevant validation is required.\n\n"
                "## Open Questions\n\n- None.\n",
                encoding="utf-8",
            )
            errors, _ = MODULE.lint_spec_workspace_readiness(task_root)
            self.assertTrue(any("decision-complete" in item for item in errors))

    def test_lint_spec_accepts_explicit_not_applicable_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n"
                "## Goal\n\nImplement a read-only reporting dashboard.\n\n"
                "## User Outcome\n\nOperators can inspect dashboard state safely.\n\n"
                "## In Scope\n\n- Reporting page\n\n"
                "## Out of Scope\n\n- Data mutation\n\n"
                "## Constraints\n\n- Preserve auth boundaries.\n\n"
                "## Existing Context\n\nThe repo already has billing read models.\n\n"
                "## Desired Behavior\n\nThe page shows billing status and retry health.\n\n"
                "### Source of Truth / Ownership\n\nExisting billing tables remain authoritative and the dashboard does not create a new state store.\n\n"
                "### Read Path\n\nRead through the current billing service and repository path.\n\n"
                "### Write Path / Mutation Flow\n\nNot applicable because this dashboard is read-only and must not mutate billing state.\n\n"
                "### Runtime / Performance Expectations\n\nAvoid N+1 queries and keep the existing request path.\n\n"
                "### Failure / Fallback / Degraded Behavior\n\nIf retry-state data is unavailable, show the main dashboard and render a degraded retry panel.\n\n"
                "### State / Integrity / Concurrency Invariants\n\nThe page must not change invoice semantics or auth behavior.\n\n"
                "### Observability / Validation Hooks\n\nTests must cover both the main path and degraded retry-state rendering.\n\n"
                "## Technical Boundaries\n\n- Keep current routes stable.\n\n"
                "## Validation Expectations\n\nAutomated and manual checks should cover the changed behavior.\n\n"
                "## Open Questions\n\n- None.\n",
                encoding="utf-8",
            )
            errors, _ = MODULE.lint_spec_workspace_readiness(task_root)
            self.assertEqual(errors, [])

    def test_lint_contract_rejects_vague_items_and_warns_without_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] Production-ready experience\n- [ ] Better UX overall\n",
                encoding="utf-8",
            )
            errors, warnings = MODULE.lint_contract_workspace_readiness(task_root)
            self.assertTrue(any("too vague or aspirational" in item for item in errors))
            self.assertTrue(any("verification item" in item for item in warnings))

    def test_validate_start_rejects_spec_contract_without_integrity_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            brief_root = FIXTURES_ROOT / "brief_quality"
            (task_root / MODULE.TASK_FILENAME).write_text((brief_root / "good_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text((brief_root / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n"
                "- [ ] Finance operators can inspect billing health from one dashboard.\n"
                "- [ ] Relevant automated verification for the changed behavior is present and passing.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as exc:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("regression, integrity, fallback, or state guardrail", str(exc.exception))

    def test_validate_start_rejects_broad_task_without_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a billing dashboard for finance operators.\n\n## Context\n\n- The work spans summary metrics, retry state, and recent invoice failures.\n- Preserve the existing route and API boundaries.\n\n## Success Signal\n\nFinance operators can inspect billing health from one dashboard and the relevant verification passes.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] Finance operators can inspect billing health from one dashboard.\n- [ ] Relevant automated verification for the changed behavior is present and passing.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as exc:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("requires spec.md", str(exc.exception))

    def test_validate_start_rejects_spec_without_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            brief_root = FIXTURES_ROOT / "brief_quality"
            (task_root / MODULE.TASK_FILENAME).write_text((brief_root / "good_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text((brief_root / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as exc:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("spec.md should be paired with contract.md", str(exc.exception))

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
            self.assertIn("diagnose by evidence rather than by symptom-shaped guesses", prompt)
            self.assertIn("last confirmed progress point", prompt)
            self.assertIn("Use the narrowest proven claim", prompt)
            self.assertNotIn("Shared council brief from", prompt)

    def test_build_generator_followup_prompt_includes_evidence_first_blocker_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0002"
            prev_turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix the parser bug.")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback logic\n", encoding="utf-8")
            (prev_turn_dir / "reviewer").mkdir(parents=True)
            (prev_turn_dir / "reviewer" / "message.md").write_text("review", encoding="utf-8")
            (prev_turn_dir / "reviewer" / "status.json").write_text(
                json.dumps(
                    {
                        "verdict": "changes_requested",
                        "summary": "Need more evidence.",
                        "blocking_issues": ["example"],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "pass",
                            "failure_mode_and_fallback": "uncertain",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "uncertain",
                            "maintainability": "pass",
                        },
                    }
                ),
                encoding="utf-8",
            )
            MODULE.save_json(
                prev_turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME,
                self.build_reviewer_evidence(reviewer_authored_tests=["tests/test_review_added.py"]),
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                "demo-task",
                state={"review_bridge": {"mode": "internal"}},
                inspection=inspection,
                inline_context=False,
            )
            self.assertIn("diagnose by evidence rather than by symptom-shaped guesses", prompt)
            self.assertIn("last confirmed progress point", prompt)
            self.assertIn("first unconfirmed next step", prompt)
            self.assertIn("Use the narrowest proven claim", prompt)
            self.assertIn(str(prev_turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME), prompt)

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

    def test_build_generator_prompt_mentions_pr_only_northstar_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            (task_root / MODULE.BRANCH_NORTHSTAR_SUMMARY_FILENAME).write_text(
                "# Northstar\n\nMerge-ready branch context.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                state={
                    "task_root": str(task_root),
                    "review_bridge": {
                        "mode": "github_pr_codex",
                        "github": {
                            "base_branch": "main",
                            "branch": "feature/demo",
                            "pr_url": "https://github.com/acme/repo/pull/123",
                        },
                    },
                },
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("You are working to get this PR merge-ready on the current branch/worktree.", prompt)
            self.assertIn(str(task_root / MODULE.BRANCH_NORTHSTAR_SUMMARY_FILENAME), prompt)

    def test_build_reviewer_initial_prompt_includes_contract_checklist_only_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text("# Review\n\n## Findings\n\n- Fix fallback\n", encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One check\n", encoding="utf-8")
            self.write_generator_status(turn_dir, changed_files=["src/example.py"])
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Contract checklist copied from `contract.md`", prompt)
            self.assertIn("Disagreement Adjudication", prompt)
            self.assertIn("Do not repeat the same blocker without stronger evidence", prompt)
            self.assertIn("directly supported by evidence or only inferred from symptoms", prompt)
            self.assertIn("narrowest justified blocker wording", prompt)
            self.assertIn("Code paths inspected", prompt)
            self.assertIn("Verification reviewed", prompt)
            self.assertIn("Branch Health Verdict", prompt)
            self.assertIn(str(turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME), prompt)

    def test_build_reviewer_followup_prompt_includes_blocker_diagnosis_check_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0002"
            prev_turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One check\n", encoding="utf-8")
            (prev_turn_dir / "generator").mkdir(parents=True)
            (prev_turn_dir / "generator" / "message.md").write_text("generator", encoding="utf-8")
            (prev_turn_dir / "generator" / "status.json").write_text(
                json.dumps(
                    {
                        "result": "implemented",
                        "summary": "Made a change.",
                        "changed_files": ["src/example.py"],
                    }
                ),
                encoding="utf-8",
            )
            self.write_generator_status(turn_dir, changed_files=["src/example.py"])
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=False,
            )
            self.assertIn("directly supported by evidence or only inferred from symptoms", prompt)
            self.assertIn("narrowest justified blocker wording", prompt)
            self.assertIn("Blocker Diagnosis Check", prompt)

    def test_build_reviewer_prompt_includes_required_commands_and_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            self.write_generator_status(turn_dir, changed_files=["src/example.py"])
            inspection = MODULE.inspect_task_workspace(task_root)
            council_config = self.build_council_config()
            council_config["review"]["path_rules"] = [
                {"name": "src", "globs": ["src/**"], "commands": ["pytest -q tests/test_example.py"]}
            ]
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                state={"review_bridge": {"mode": "internal"}, "council_config": council_config},
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Follow this protocol in order:", prompt)
            self.assertIn("pytest -q tests/test_example.py", prompt)
            self.assertIn(str(turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME), prompt)

    def test_reviewer_posture_is_forensic_when_spec_is_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.SPEC_FILENAME).write_text((FIXTURES_ROOT / "brief_quality" / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            posture = MODULE.reviewer_posture_for_task_root(task_root, inspection, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(posture, "forensic")

    def test_reviewer_posture_is_deep_for_findings_driven_work_without_spec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Retry fallback still leaves stale cache metadata behind.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            posture = MODULE.reviewer_posture_for_task_root(task_root, inspection, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(posture, "deep")

    def test_reviewer_initial_prompt_uses_forensic_posture_for_spec_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            (task_root / MODULE.SPEC_FILENAME).write_text((FIXTURES_ROOT / "brief_quality" / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] One behavior outcome\n- [ ] One regression guardrail\n- [ ] One verification item\n", encoding="utf-8")
            self.write_generator_status(turn_dir, changed_files=["src/example.py"])
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Reviewer posture: forensic.", prompt)
            self.assertIn("Treat passing tests as supporting evidence only", prompt)
            self.assertIn("You may edit repo-tracked files only to add or tighten tests or fixtures", prompt)

    def test_reviewer_initial_prompt_uses_standard_posture_for_narrow_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix parser bug")
            self.write_generator_status(turn_dir, changed_files=["src/parser.py"])
            inspection = MODULE.inspect_task_workspace(task_root)
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=True,
            )
            self.assertIn("Reviewer posture: standard.", prompt)
            self.assertNotIn("Reviewer posture: forensic.", prompt)

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
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=True,
                bootstrap_review_block=MODULE.format_fork_bootstrap_review_block(task_root),
            )
            self.assertIn("distill the current fork/session context", prompt)
            self.assertIn(str(task_root / MODULE.REVIEW_FILENAME), prompt)
            self.assertNotIn(str(role_message_path := turn_dir / "generator" / "message.md"), prompt)
            self.assertIn(str(turn_dir / "reviewer" / MODULE.REVIEWER_EVIDENCE_FILENAME), prompt)

    def test_enforce_fresh_reviewer_session_for_turn_resets_resume_state(self) -> None:
        run_state = {
            "council_config": self.build_council_config(),
            "roles": {
                "reviewer": {
                    "tmux_session": "reviewer-tmux",
                    "codex_session_id": "session-123",
                    "codex_thread_name": "thread-name",
                }
            },
        }
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(MODULE, "tmux_session_exists", return_value=True), mock.patch.object(
                MODULE, "tmux_kill_session", return_value=None
            ), mock.patch.object(MODULE, "save_run_state", return_value=None), mock.patch.object(
                MODULE, "append_run_event", return_value=None
            ) as append_event:
                MODULE.enforce_fresh_reviewer_session_for_turn(Path(tmp_dir), run_state, 3)
        self.assertIsNone(run_state["roles"]["reviewer"]["codex_session_id"])
        self.assertIsNone(run_state["roles"]["reviewer"]["codex_thread_name"])
        self.assertEqual(append_event.call_args.args[1], "reviewer_session_reset_for_fresh_turn")

    def test_build_prompts_include_reopen_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            inspection = MODULE.inspect_task_workspace(task_root)
            reopen_state = {
                "review_bridge": {"mode": "internal"},
                "reopen": {
                    "reason_kind": "false_approved",
                    "reason_message": "The reviewer missed a blocking fallback bug.",
                    "reopened_from": {"run_id": "run-1", "turn": "0001"},
                    "doc_comparison": {
                        "docs_changed_since_approval": True,
                        "changed_existing_docs": ["review.md"],
                        "added_docs": [],
                        "removed_docs": [],
                    },
                },
            }
            generator_prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                "demo-task",
                state=reopen_state,
                inspection=inspection,
                inline_context=True,
            )
            reviewer_prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                state={**reopen_state, "council_config": self.build_council_config()},
                inspection=inspection,
                inline_context=True,
            )
            for prompt in (generator_prompt, reviewer_prompt):
                self.assertIn("Reopen context:", prompt)
                self.assertIn("false_approved", prompt)
                self.assertIn("run `run-1` turn `0001`", prompt)
                self.assertIn("review.md", prompt)

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
            self.commit_repo_changes(repo_root, "scaffold workspace")
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

    def test_start_run_allows_github_pr_codex_without_local_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            self.commit_repo_changes(repo_root, "scaffold workspace")
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
                github_pr="https://github.com/acme/repo/pull/42",
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "read_codex_session_index", return_value=[]), mock.patch.object(
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
            ), mock.patch.object(
                MODULE,
                "create_tmux_sessions",
                return_value=None,
            ), mock.patch.object(
                MODULE,
                "wait_for_tmux_sessions_ready",
                return_value=None,
            ), mock.patch.object(
                MODULE,
                "supervisor_loop_from",
                return_value=None,
            ) as supervisor_loop, contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(supervisor_loop.call_args.kwargs["start_role"], "generator")
            state = MODULE.load_json(task_root / "runs" / "run-1" / "state.json")
            self.assertEqual(state["workspace_profile"], "undocumented")
            self.assertEqual(state["review_bridge"]["mode"], "github_pr_codex")

    def test_start_run_allows_github_pr_codex_generator_fork_bootstrap_without_local_docs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            self.commit_repo_changes(repo_root, "scaffold workspace")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                generator_session="gen",
                reviewer_session=None,
                fork_session_id="parent-id",
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="github_pr_codex",
                github_pr="42",
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(
                MODULE,
                "find_codex_session_entry",
                return_value={"id": "parent-id", "updated_at": "2026-04-10T12:00:00Z", "thread_name": "x"},
            ), mock.patch.object(
                MODULE,
                "read_codex_session_index",
                return_value=[],
            ), mock.patch.object(
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
            ), mock.patch.object(
                MODULE,
                "create_tmux_sessions",
                return_value=None,
            ), mock.patch.object(
                MODULE,
                "wait_for_tmux_sessions_ready",
                return_value=None,
            ), mock.patch.object(
                MODULE,
                "supervisor_loop_from",
                return_value=None,
            ) as supervisor_loop, contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(supervisor_loop.call_args.kwargs["start_role"], "generator")
            state = MODULE.load_json(task_root / "runs" / "run-1" / "state.json")
            self.assertEqual(state["bootstrap_phase"], "fork_to_generator_github_pr")
            self.assertEqual(state["roles"]["generator"]["fork_parent_session_id"], "parent-id")
            self.assertIsNone(state["roles"]["reviewer"]["fork_parent_session_id"])

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
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the parser bug that breaks the fallback path.\n\n## Context\n\n- The parser should preserve existing API behavior.\n- The broken path appears in fallback handling rather than normal parsing.\n\n## Success Signal\n\nThe fallback path behaves correctly again and the relevant verification passes.\n",
                encoding="utf-8",
            )
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

    def test_build_review_bridge_state_defaults_new_pr_base_branch_to_staging(self) -> None:
        args = argparse.Namespace(
            review_mode="github_pr_codex",
            github_pr=None,
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
            "find_existing_github_pr_for_branch",
            return_value=None,
        ):
            state = MODULE.build_review_bridge_state(
                Path("/repo"),
                Path("/repo/.codex-council/demo-task"),
                {"current_branch": "feature/pr"},
                args,
            )
        self.assertEqual(state["github"]["base_branch"], "staging")

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
            self.assertEqual(request_comment["body"], "@codex")
            self.assertEqual(state["review_bridge"]["github"]["last_request_comment_id"], 101)
            self.assertEqual(state["review_bridge"]["github"]["last_request_turn"], "0002")

    def test_current_github_pr_head_started_at_uses_latest_matching_timeline_event(self) -> None:
        started_at = MODULE.current_github_pr_head_started_at(
            [
                {
                    "event": "committed",
                    "created_at": "2026-04-12T00:05:00Z",
                    "commit_id": "oldhead",
                },
                {
                    "event": "committed",
                    "created_at": "2026-04-12T00:10:00Z",
                    "commit_id": "newhead",
                },
                {
                    "event": "head_ref_force_pushed",
                    "created_at": "2026-04-12T00:15:00Z",
                    "after": "newhead",
                },
            ],
            current_head_sha="newhead",
            pr_created_at="2026-04-12T00:00:00Z",
        )
        self.assertEqual(started_at, "2026-04-12T00:15:00Z")

    def test_inspect_github_pr_review_state_for_current_head_ignores_old_request_before_generator_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            turn_dir = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.save_json(
                turn_dir / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "repo_owner": "acme",
                        "repo": "repo",
                        "pr_number": 9,
                        "pr_url": "https://github.com/acme/repo/pull/9",
                        "pr_created_at": "2000-01-01T00:00:00Z",
                        "last_consumed_review_id": None,
                        "last_consumed_review_comment_id": None,
                    },
                },
            }
            with mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                return_value=[
                    {
                        "id": 101,
                        "created_at": "2000-01-02T00:00:00Z",
                        "body": "@codex",
                    }
                ],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_timeline_events",
                return_value=[],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_reviews",
                return_value=[],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_review_threads",
                return_value=[],
            ):
                review_state = MODULE.inspect_github_pr_review_state_for_current_head(
                    run_dir,
                    state,
                    1,
                    current_head_sha="newhead",
                )
            self.assertEqual(review_state["state"], "needs_request_comment")
            self.assertIsNone(review_state["request_comment"])

    def test_classify_github_pr_review_state_for_current_head_reuses_unanswered_literal_request(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
            ],
            current_head_started_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=None,
        )
        self.assertEqual(review_state["state"], "waiting_for_codex_reply")
        assert review_state["request_comment"] is not None
        self.assertEqual(review_state["request_comment"]["id"], 9)

    def test_classify_github_pr_review_state_for_current_head_returns_reply_ready(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
                {
                    "id": 10,
                    "created_at": "2026-04-12T00:10:00Z",
                    "body": "Codex Review: Ready to import.",
                },
            ],
            current_head_started_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=None,
        )
        self.assertEqual(review_state["state"], "codex_reply_ready_to_ingest")
        assert review_state["reply_comment"] is not None
        self.assertEqual(review_state["reply_comment"]["id"], 10)

    def test_classify_github_pr_review_state_for_current_head_returns_reply_ready_for_terminal_approval_comment(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
                {
                    "id": 10,
                    "created_at": "2026-04-12T00:10:00Z",
                    "body": "Codex Review: Didn't find any major issues. Keep it up!\n\nAll good.",
                },
            ],
            current_head_started_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=None,
        )
        self.assertEqual(review_state["state"], "codex_reply_ready_to_ingest")
        assert review_state["reply_comment"] is not None
        self.assertEqual(review_state["reply_comment"]["id"], 10)

    def test_classify_github_pr_review_state_for_current_head_keeps_consumed_current_head_reply_ready(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
                {
                    "id": 10,
                    "created_at": "2026-04-12T00:10:00Z",
                    "body": "Codex Review: Ready to import.",
                },
            ],
            current_head_started_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=10,
        )
        self.assertEqual(review_state["state"], "codex_reply_ready_to_ingest")
        assert review_state["request_comment"] is not None
        self.assertEqual(review_state["request_comment"]["id"], 9)
        assert review_state["reply_comment"] is not None
        self.assertEqual(review_state["reply_comment"]["id"], 10)

    def test_classify_github_pr_review_state_for_current_head_ignores_old_head_comments(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 8,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:05:00Z",
                    "body": "Codex Review: Old head reply.",
                },
                {
                    "id": 10,
                    "created_at": "2026-04-12T00:20:00Z",
                    "body": "@codex",
                },
            ],
            current_head_started_at="2026-04-12T00:20:00Z",
            last_consumed_comment_id=None,
        )
        self.assertEqual(review_state["state"], "waiting_for_codex_reply")
        assert review_state["request_comment"] is not None
        self.assertEqual(review_state["request_comment"]["id"], 10)

    def test_classify_github_pr_review_state_for_current_head_ignores_old_head_terminal_approval_comment(self) -> None:
        review_state = MODULE.classify_github_pr_review_state_for_current_head(
            [
                {
                    "id": 8,
                    "created_at": "2026-04-12T00:00:00Z",
                    "body": "@codex",
                },
                {
                    "id": 9,
                    "created_at": "2026-04-12T00:05:00Z",
                    "body": "Codex Review: Didn't find any major issues. Keep it up!\n\nAll good.",
                },
                {
                    "id": 10,
                    "created_at": "2026-04-12T00:20:00Z",
                    "body": "@codex",
                },
            ],
            current_head_started_at="2026-04-12T00:20:00Z",
            last_consumed_comment_id=None,
        )
        self.assertEqual(review_state["state"], "waiting_for_codex_reply")
        assert review_state["request_comment"] is not None
        self.assertEqual(review_state["request_comment"]["id"], 10)

    def test_select_latest_unconsumed_github_codex_review_comment_ignores_consumed_comments(self) -> None:
        comments = [
            {"id": 10, "created_at": "2026-04-12T00:00:00Z", "body": "@codex"},
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

    def test_select_latest_unconsumed_github_codex_approved_comment_ignores_non_approved_replies(self) -> None:
        comments = [
            {"id": 10, "created_at": "2026-04-12T00:00:00Z", "body": "@codex"},
            {"id": 11, "created_at": "2026-04-12T00:10:00Z", "body": "Codex Review: Needs one more fix."},
            {"id": 12, "created_at": "2026-04-12T00:20:00Z", "body": "Codex Review: Didn't find any major issues. Keep it up!\nAll good."},
        ]
        selected = MODULE.select_latest_unconsumed_github_codex_approved_comment(
            comments,
            request_comment_id=10,
            request_comment_created_at="2026-04-12T00:00:00Z",
            last_consumed_comment_id=None,
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
            self.assertEqual(sleeps, [600, 30])
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

    def test_wait_for_new_github_codex_review_comment_accepts_deadline_boundary_poll(self) -> None:
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
                "created_at": "2026-04-12T01:30:00Z",
                "body": "Codex Review: Final window reply.",
            }
            with mock.patch.object(MODULE.time, "time", side_effect=lambda: now[0]), mock.patch.object(
                MODULE.time,
                "sleep",
                side_effect=fake_sleep,
            ), mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                side_effect=[[], [], [], [], [comment]],
            ):
                result = MODULE.wait_for_new_github_codex_review_comment(
                    run_dir,
                    state,
                    1,
                    timeout_seconds=1800,
                )
            self.assertEqual(result["id"], 202)
            self.assertEqual(sleeps, [600, 30, 30, 30, 30])
            self.assertEqual(state["review_bridge"]["github"]["review_wait"]["poll_count"], 5)

    def test_wait_for_new_github_inline_review_snapshot_returns_approved_snapshot_from_issue_comment(self) -> None:
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
                        "last_consumed_review_id": None,
                        "last_consumed_review_comment_id": None,
                        "last_request_comment_created_at": request_created_at,
                        "last_request_comment_id": 101,
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
            }
            with mock.patch.object(MODULE.time, "time", side_effect=lambda: now[0]), mock.patch.object(
                MODULE.time,
                "sleep",
                side_effect=fake_sleep,
            ), mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                return_value=[
                    {
                        "id": 202,
                        "created_at": "2026-04-12T01:10:00Z",
                        "body": "Codex Review: Didn't find any major issues. Keep it up!\nAll good.",
                    }
                ],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_reviews",
                side_effect=AssertionError("GraphQL reviews should not be needed for terminal approval"),
            ), mock.patch.object(
                MODULE,
                "list_github_pr_review_threads",
                side_effect=AssertionError("GraphQL threads should not be needed for terminal approval"),
            ):
                snapshot = MODULE.wait_for_new_github_inline_review_snapshot(
                    run_dir,
                    state,
                    1,
                    current_head_sha="deadbeef",
                    current_head_started_at="2026-04-12T01:00:00Z",
                    timeout_seconds=1800,
                )
            self.assertEqual(snapshot["source"], "issue_comment_approval")
            self.assertEqual(snapshot["review"]["id"], 202)
            self.assertEqual(sleeps, [600])

    def test_seed_generator_github_review_input_materializes_existing_inline_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            turn_dir = run_dir / "turns" / "0001"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text=None)
            turn_dir.mkdir(parents=True)
            state = {
                "repo_root": str(Path(tmp_dir) / "repo"),
                "review_bridge": {
                    "mode": "github_pr_codex",
                    "github": {
                        "base_branch": "main",
                        "branch": "feature/demo",
                        "pr_number": 9,
                        "pr_url": "https://github.com/acme/repo/pull/9",
                        "repo": "repo",
                        "repo_owner": "acme",
                    },
                },
            }
            snapshot = {
                "active_threads": [
                    {
                        "body": "Handle the empty-file case by tombstoning existing rows.",
                        "comment_id": 55,
                        "created_at": "2026-04-12T01:10:00Z",
                        "line": 3284,
                        "path": "eve_app/src/tools/core/workspace_index.py",
                        "review_id": 202,
                        "thread_id": "thread-1",
                    }
                ],
                "blocking_issues": ["eve_app/src/tools/core/workspace_index.py:3284 - Handle the empty-file case by tombstoning existing rows."],
                "current_head_sha": "deadbeef",
                "current_head_started_at": "2026-04-12T01:00:00Z",
                "pr_number": 9,
                "pr_url": "https://github.com/acme/repo/pull/9",
                "review": {
                    "author_login": "chatgpt-codex-connector",
                    "body": "P1 Badge Tombstone stale docs when indexing empty files",
                    "commit_oid": "deadbeef",
                    "id": 202,
                    "state": "COMMENTED",
                    "submitted_at": "2026-04-12T01:10:00Z",
                },
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
                "inspect_github_pr_review_state_for_current_head",
                return_value={
                    "state": "codex_reply_ready_to_ingest",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "request_comment": {"id": 101, "created_at": "2026-04-12T01:00:00Z", "body": "@codex"},
                    "reply_comment": None,
                    "review_snapshot": snapshot,
                },
            ):
                MODULE.seed_generator_github_review_input(run_dir, state, task_root, 1, turn_dir)
            self.assertTrue((turn_dir / MODULE.GITHUB_REVIEW_INPUT_MARKDOWN_FILENAME).exists())
            self.assertTrue((turn_dir / MODULE.GITHUB_REVIEW_INPUT_JSON_FILENAME).exists())
            rendered = (turn_dir / MODULE.GITHUB_REVIEW_INPUT_MARKDOWN_FILENAME).read_text(encoding="utf-8")
            self.assertIn("workspace_index.py", rendered)
            manifest = MODULE.load_json(turn_dir / "context_manifest.json")
            self.assertIn("github_review_input_markdown", manifest["files"])
            self.assertIn("github_review_input_json", manifest["files"])

    def test_wait_for_new_github_codex_review_comment_polls_when_timeout_equals_initial_wait(self) -> None:
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
                "created_at": "2026-04-12T01:10:00Z",
                "body": "Codex Review: First poll works.",
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
                    timeout_seconds=MODULE.GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                )
            self.assertEqual(result["id"], 202)
            self.assertEqual(sleeps, [600])
            self.assertEqual(state["review_bridge"]["github"]["review_wait"]["poll_count"], 1)

    def test_wait_for_new_github_codex_review_comment_rejects_post_deadline_comment_on_late_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            request_created_at = "2026-04-12T01:00:00Z"
            resume_epoch = MODULE.parse_utc_timestamp("2026-04-12T01:31:00Z")
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
                            "last_polled_at": "2026-04-12T01:25:00Z",
                            "poll_count": 4,
                            "poll_interval_seconds": MODULE.GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                            "started_at": request_created_at,
                        },
                    },
                },
            }
            late_comment = {
                "id": 202,
                "created_at": "2026-04-12T01:30:30Z",
                "body": "Codex Review: Too late.",
            }
            with mock.patch.object(MODULE.time, "time", side_effect=lambda: now[0]), mock.patch.object(
                MODULE.time,
                "sleep",
                side_effect=fake_sleep,
            ), mock.patch.object(
                MODULE,
                "list_github_pr_issue_comments",
                return_value=[late_comment],
            ):
                with self.assertRaises(MODULE.SupervisorRuntimeError) as ctx:
                    MODULE.wait_for_new_github_codex_review_comment(
                        run_dir,
                        state,
                        1,
                        timeout_seconds=1800,
                        reuse_existing_request=True,
                    )
            self.assertEqual(ctx.exception.phase, "github_review_timeout")
            self.assertEqual(sleeps, [])
            self.assertEqual(state["review_bridge"]["github"]["review_wait"]["poll_count"], 5)

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
                "inspect_github_pr_review_state_for_current_head",
                return_value={
                    "state": "needs_request_comment",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "request_comment": None,
                    "reply_comment": None,
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
                return_value={
                    "id": 101,
                    "created_at": "2026-04-12T01:00:00Z",
                    "html_url": None,
                    "body": "@codex",
                },
            ), mock.patch.object(
                MODULE,
                "wait_for_new_github_inline_review_snapshot",
                return_value={
                    "active_threads": [],
                    "blocking_issues": [],
                    "current_head_sha": "deadbeef",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "pr_number": 9,
                    "pr_url": "https://github.com/acme/repo/pull/9",
                    "request_comment_created_at": "2026-04-12T01:00:00Z",
                    "review": {
                        "author_login": "chatgpt-codex-connector",
                        "body": "Codex Review: Didn't find any major issues. Keep it up!\nAll good.",
                        "commit_oid": "deadbeef",
                        "id": 202,
                        "state": "APPROVED",
                        "submitted_at": "2026-04-12T01:10:00Z",
                        "submitted_at_epoch": MODULE.parse_utc_timestamp("2026-04-12T01:10:00Z"),
                    },
                },
            ):
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "approved")
            saved_status = MODULE.load_json(turn_dir / "reviewer" / "status.json")
            self.assertEqual(saved_status["verdict"], "approved")
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("Didn't find any major issues", reviewer_message)
            self.assertIn("polled every 30 seconds", reviewer_message)

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
                "inspect_github_pr_review_state_for_current_head",
                return_value={
                    "state": "needs_request_comment",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "request_comment": None,
                    "reply_comment": None,
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
                return_value={
                    "id": 101,
                    "created_at": "2026-04-12T01:00:00Z",
                    "html_url": None,
                    "body": "@codex",
                },
            ), mock.patch.object(
                MODULE,
                "wait_for_new_github_inline_review_snapshot",
                side_effect=error,
            ):
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "blocked")
            self.assertIn("timed out waiting for Codex", reviewer_status["summary"])
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("GitHub review bridge failed", reviewer_message)

    def test_run_github_codex_review_phase_approves_from_existing_terminal_issue_comment_without_graphql(self) -> None:
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
                        "current_head_started_at": "2026-04-12T01:00:00Z",
                        "last_consumed_review_comment_body_sha256": None,
                        "last_consumed_review_comment_created_at": None,
                        "last_consumed_review_comment_id": None,
                        "last_consumed_review_turn": None,
                        "last_request_comment_created_at": None,
                        "last_request_comment_id": None,
                        "last_request_turn": None,
                        "last_observed_head_sha": "deadbeef",
                        "pr_created_at": "2026-04-12T00:00:00Z",
                        "pr_head_sha": "deadbeef",
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
                "inspect_github_pr_review_state_for_current_head",
                return_value={
                    "state": "codex_reply_ready_to_ingest",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "request_comment": {
                        "id": 101,
                        "created_at": "2026-04-12T01:00:00Z",
                        "body": "@codex",
                    },
                    "reply_comment": {
                        "id": 202,
                        "created_at": "2026-04-12T01:04:00Z",
                        "body": "Codex Review: Didn't find any major issues. Keep it up!\nAll good.",
                    },
                    "review_snapshot": None,
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
            ) as post_request, mock.patch.object(
                MODULE,
                "wait_for_new_github_inline_review_snapshot",
            ) as wait_for_snapshot:
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "approved")
            post_request.assert_not_called()
            wait_for_snapshot.assert_not_called()
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("Imported Codex review comment ID: `202`", reviewer_message)

    def test_run_github_codex_review_phase_imports_existing_current_head_reply_without_waiting(self) -> None:
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
                        "current_head_started_at": "2026-04-12T01:00:00Z",
                        "last_consumed_review_comment_body_sha256": None,
                        "last_consumed_review_comment_created_at": None,
                        "last_consumed_review_comment_id": None,
                        "last_consumed_review_turn": None,
                        "last_request_comment_created_at": None,
                        "last_request_comment_id": None,
                        "last_request_turn": None,
                        "last_observed_head_sha": "deadbeef",
                        "pr_created_at": "2026-04-12T00:00:00Z",
                        "pr_head_sha": "deadbeef",
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
                "inspect_github_pr_review_state_for_current_head",
                return_value={
                    "state": "codex_reply_ready_to_ingest",
                    "current_head_started_at": "2026-04-12T01:00:00Z",
                    "request_comment": {
                        "id": 101,
                        "created_at": "2026-04-12T01:00:00Z",
                        "body": "@codex",
                    },
                    "reply_comment": {
                        "id": 202,
                        "created_at": "2026-04-12T01:04:00Z",
                        "body": "Codex Review: Ready to import.",
                    },
                },
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
            ) as post_request, mock.patch.object(
                MODULE,
                "wait_for_new_github_codex_review_comment",
            ) as wait_for_comment:
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "changes_requested")
            post_request.assert_not_called()
            wait_for_comment.assert_not_called()
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("Imported Codex review comment ID: `202`", reviewer_message)
            self.assertNotIn("Waited 10 minutes", reviewer_message)

    def test_run_github_codex_review_phase_reuses_consumed_current_head_reply_without_duplicate_request(self) -> None:
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
                        "current_head_started_at": "2026-04-12T01:00:00Z",
                        "last_consumed_review_comment_body_sha256": None,
                        "last_consumed_review_comment_created_at": "2026-04-12T01:04:00Z",
                        "last_consumed_review_comment_id": 202,
                        "last_consumed_review_turn": "0001",
                        "last_request_comment_created_at": "2026-04-12T01:00:00Z",
                        "last_request_comment_id": 101,
                        "last_request_turn": "0001",
                        "last_observed_head_sha": "deadbeef",
                        "pr_created_at": "2026-04-12T00:00:00Z",
                        "pr_head_sha": "deadbeef",
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
                "list_github_pr_issue_comments",
                return_value=[
                    {
                        "id": 101,
                        "created_at": "2026-04-12T01:00:00Z",
                        "body": "@codex",
                    },
                    {
                        "id": 202,
                        "created_at": "2026-04-12T01:04:00Z",
                        "body": "Codex Review: Ready to import.",
                    },
                ],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_reviews",
                return_value=[],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_review_threads",
                return_value=[],
            ), mock.patch.object(
                MODULE,
                "list_github_pr_timeline_events",
                return_value=[
                    {
                        "event": "committed",
                        "created_at": "2026-04-12T01:00:00Z",
                        "commit_id": "deadbeef",
                    },
                ],
            ), mock.patch.object(
                MODULE,
                "post_github_pr_review_request_comment",
            ) as post_request, mock.patch.object(
                MODULE,
                "wait_for_new_github_codex_review_comment",
            ) as wait_for_comment:
                reviewer_status = MODULE.run_github_codex_review_phase(run_dir, state, task_root, 1, turn_dir)
            self.assertEqual(reviewer_status["verdict"], "changes_requested")
            post_request.assert_not_called()
            wait_for_comment.assert_not_called()
            reviewer_message = (turn_dir / "reviewer" / "message.md").read_text(encoding="utf-8")
            self.assertIn("Imported Codex review comment ID: `202`", reviewer_message)
            self.assertNotIn("Waited 10 minutes", reviewer_message)

    def test_determine_continue_target_reuses_same_turn_for_github_review_bridge_blocked_reviewer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            latest_turn = run_dir / "turns" / "0001"
            latest_turn.mkdir(parents=True)
            with mock.patch.object(
                MODULE,
                "resolve_continuation_plan",
                return_value={
                    "mode": "continue",
                    "turn_dir": latest_turn,
                    "turn_number": 1,
                    "role": "reviewer",
                    "create_new_turn": False,
                    "prior_status": "reviewer_blocked",
                },
            ):
                result = MODULE.determine_continue_target(
                    run_dir,
                    {"review_bridge": {"mode": "github_pr_codex"}},
                )
            self.assertEqual(result, (latest_turn, 1, "reviewer", False, "reviewer_blocked"))

    def test_determine_continue_target_ignores_stray_future_turn_when_reviewer_should_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            turn_two = MODULE.prepare_turn(run_dir, 2, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )

            result = MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(result, (turn_one, 1, "reviewer", False, "generator_complete_waiting_reviewer"))
            plan = MODULE.resolve_continuation_plan(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(plan["ignored_turns"], ["0002"])
            self.assertIn("reviewer has not started", plan["reason"])

    def test_determine_continue_target_reuses_annotated_empty_next_turn_after_changes_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            turn_two = MODULE.prepare_turn(run_dir, 2, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_one / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_one / "reviewer" / "status.json",
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
            MODULE.annotate_turn_continuation(
                turn_two,
                continuation_source="reviewer_changes_requested",
                selected_role="generator",
                selected_turn=2,
            )

            result = MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(result, (turn_two, 2, "generator", False, "reviewer_changes_requested"))

    def test_determine_continue_target_fails_for_unexplained_empty_next_turn_after_changes_requested(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.prepare_turn(run_dir, 2, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_one / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_one / "reviewer" / "status.json",
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

            with self.assertRaises(SystemExit) as ctx:
                MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertIn("does not clearly match", str(ctx.exception))

    def test_determine_continue_target_fails_when_later_turn_conflicts_with_earlier_unfinished_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            turn_two = MODULE.prepare_turn(run_dir, 2, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_two / "generator" / "prompt.md", "generator prompt")

            with self.assertRaises(SystemExit) as ctx:
                MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertIn("later turns already contain conflicting activity", str(ctx.exception))

    def test_show_status_includes_derived_continuation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.save_json(
                run_dir / "state.json",
                {"status": "blocked", "review_bridge": {"mode": "internal"}},
            )

            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
            )
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                result = MODULE.show_status(args)

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["derived_continuation"]["mode"], "continue")
            self.assertEqual(payload["derived_continuation"]["role"], "reviewer")
            self.assertEqual(payload["derived_continuation"]["continuation_state"], "generator_complete_waiting_reviewer")

    def test_save_run_state_rejects_waiting_reviewer_without_reviewer_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            run_dir.mkdir(parents=True)
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            state = {
                "status": "waiting_reviewer",
                "run_id": "run-1",
                "task_root": str(task_root),
                "current_turn": 1,
                "pending_turn": None,
                "pending_role": None,
                "transition_source_verdict": None,
                "roles": {
                    "generator": {"tmux_session": "gen"},
                    "reviewer": {"tmux_session": "rev"},
                },
            }
            with self.assertRaises(MODULE.SupervisorRuntimeError):
                MODULE.save_run_state(run_dir, state)

    def test_save_run_state_rejects_transitioning_turn_without_pending_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "run"
            current_turn_dir = run_dir / "turns" / "0001"
            current_turn_dir.mkdir(parents=True)
            MODULE.save_json(current_turn_dir / "turn.json", {"turn": "0001", "phase": "changes_requested"})
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            state = {
                "status": MODULE.TRANSITIONING_TURN_STATUS,
                "run_id": "run-1",
                "task_root": str(task_root),
                "current_turn": 1,
                "pending_turn": None,
                "pending_role": None,
                "transition_source_verdict": "reviewer_changes_requested",
                "roles": {
                    "generator": {"tmux_session": "gen"},
                    "reviewer": {"tmux_session": "rev"},
                },
            }
            with self.assertRaises(MODULE.SupervisorRuntimeError):
                MODULE.save_run_state(run_dir, state)

    def test_run_generator_phase_completes_transition_and_clears_pending_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the fallback path that leaves the parser in a partial state.\n\n## Context\n\n- The failure is in the parser fallback path, not the happy path.\n- Preserve the public API while fixing the partial-state behavior.\n\n## Success Signal\n\nThe fallback path no longer leaves partial state behind and the relevant verification passes.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            (run_dir / "turns").mkdir(parents=True)
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.save_turn_metadata(turn_one, 1, "changes_requested", role="reviewer")
            turn_two = MODULE.prepare_turn(run_dir, 2, task_root)
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_profile="task",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
            )
            state["status"] = MODULE.TRANSITIONING_TURN_STATUS
            state["current_turn"] = 1
            state["pending_turn"] = 2
            state["pending_role"] = "generator"
            state["transition_source_verdict"] = "reviewer_changes_requested"
            MODULE.save_run_state(run_dir, state)

            def fake_wait_for_role_artifacts(current_turn_dir, role, **kwargs):
                message_path, status_path = MODULE.role_artifact_paths(current_turn_dir, role)
                MODULE.write_text(message_path, "generator message")
                MODULE.save_json(
                    status_path,
                    {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
                )
                return message_path, status_path, MODULE.validate_generator_status(MODULE.load_json(status_path))

            with mock.patch.object(MODULE, "wait_for_tmux_prompt", return_value=None), mock.patch.object(
                MODULE, "tmux_send_prompt", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_role_artifacts", side_effect=fake_wait_for_role_artifacts
            ), mock.patch.object(MODULE, "write_raw_final_output_artifact", return_value=None):
                MODULE.run_generator_phase(run_dir, state, task_root, 2, turn_two, inline_context=False)

            saved = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(saved["current_turn"], 2)
            self.assertEqual(saved["status"], "waiting_generator")
            self.assertIsNone(saved["pending_turn"])
            self.assertIsNone(saved["pending_role"])
            events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("turn_transition_completed", events)

    def test_run_generator_phase_records_prompt_prepared_then_sent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix a small bug.\n\n## Context\n\n- Keep the change narrow.\n\n## Success Signal\n\nThe bug is fixed.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_profile="task",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
            )
            MODULE.save_run_state(run_dir, state)

            def fake_wait_for_role_artifacts(current_turn_dir, role, **kwargs):
                message_path, status_path = MODULE.role_artifact_paths(current_turn_dir, role)
                MODULE.write_text(message_path, "generator message")
                MODULE.save_json(
                    status_path,
                    {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
                )
                return message_path, status_path, MODULE.validate_generator_status(MODULE.load_json(status_path))

            with mock.patch.object(MODULE, "ensure_role_session_ready", return_value=None), mock.patch.object(
                MODULE, "wait_for_tmux_prompt", return_value=None
            ), mock.patch.object(
                MODULE, "tmux_send_prompt", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_role_artifacts", side_effect=fake_wait_for_role_artifacts
            ), mock.patch.object(MODULE, "write_raw_final_output_artifact", return_value=None):
                MODULE.run_generator_phase(run_dir, state, task_root, 1, turn_one, inline_context=True)

            events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertLess(events.index("generator_prompt_prepared"), events.index("generator_prompt_sent"))
            turn_metadata = MODULE.load_json(turn_one / "turn.json")
            self.assertEqual(turn_metadata["phase"], "generator_prompt_sent")

    def test_continue_run_recovers_from_broken_changes_requested_half_transition(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the fallback path that leaves the parser in a partial state.\n\n## Context\n\n- The failure is in the parser fallback path, not the happy path.\n- Preserve the public API while fixing the partial-state behavior.\n\n## Success Signal\n\nThe fallback path no longer leaves partial state behind and the relevant verification passes.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            (turn_one / "generator").mkdir(exist_ok=True)
            (turn_one / "reviewer").mkdir(exist_ok=True)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_one / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_one / "reviewer" / "status.json",
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
            MODULE.save_json(turn_one / "turn.json", {"turn": "0001", "phase": "changes_requested", "role": "reviewer"})
            broken_state = {
                "status": "waiting_reviewer",
                "current_turn": 2,
                "pending_turn": None,
                "pending_role": None,
                "transition_source_verdict": None,
                "task_root": str(task_root),
                "run_dir": str(run_dir),
                "review_bridge": {"mode": "internal"},
                "roles": {
                    "generator": {"tmux_session": "gen", "last_wait_phase": None},
                    "reviewer": {"tmux_session": "rev", "last_wait_phase": None},
                },
                "council_config": self.build_council_config(),
                "repo_root": str(repo_root),
            }
            MODULE.save_json(run_dir / "state.json", broken_state)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
            )
            captured = {}

            def fake_supervisor_loop_from(run_dir_arg, state_arg, task_root_arg, **kwargs):
                captured["kwargs"] = kwargs

            with mock.patch.object(MODULE, "supervisor_loop_from", side_effect=fake_supervisor_loop_from), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(captured["kwargs"]["start_turn"], 2)
            self.assertEqual(captured["kwargs"]["start_role"], "generator")
            self.assertFalse(captured["kwargs"]["reuse_existing_turn_for_first"])

    def test_continue_run_ensures_all_active_role_sessions_ready_before_supervisor_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix bug\n\n## Context\n\nctx\n\n## Success Signal\n\nworks\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            (turn_one / "generator").mkdir(exist_ok=True)
            MODULE.write_text(turn_one / "generator" / "prompt.md", "prompt")
            MODULE.save_json(
                run_dir / "state.json",
                {
                    "status": "waiting_generator",
                    "current_turn": 1,
                    "pending_turn": None,
                    "pending_role": None,
                    "transition_source_verdict": None,
                    "task_root": str(task_root),
                    "run_dir": str(run_dir),
                    "review_bridge": {"mode": "internal"},
                    "roles": {
                        "generator": {"tmux_session": "gen", "last_wait_phase": None},
                        "reviewer": {"tmux_session": "rev", "last_wait_phase": None},
                    },
                    "council_config": self.build_council_config(),
                    "repo_root": str(repo_root),
                },
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
            )
            resumed_roles: list[str] = []

            def fake_ensure_role_session_ready(run_dir_arg, state_arg, role):
                resumed_roles.append(role)

            with mock.patch.object(
                MODULE,
                "resolve_continuation_plan",
                return_value={
                    "mode": "continue",
                    "turn_dir": turn_one,
                    "turn_number": 1,
                    "role": "generator",
                    "create_new_turn": False,
                    "reuse_existing_turn_for_first": True,
                    "prior_status": "generator_pending",
                    "continuation_state": "generator_pending",
                    "reason": "turn 0001 still has incomplete or invalid generator artifacts.",
                    "reference_turn_dir": turn_one,
                    "source_turn_number": 1,
                    "ignored_turns": [],
                },
            ), mock.patch.object(
                MODULE,
                "ensure_role_session_ready",
                side_effect=fake_ensure_role_session_ready,
            ), mock.patch.object(
                MODULE,
                "supervisor_loop_from",
                return_value=None,
            ), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(resumed_roles, ["generator", "reviewer"])

    def test_reopen_run_creates_new_run_metadata_index_and_prompt_context_for_review_only_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Investigate why the fallback path still drops the new invariant on retry.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_one / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_one / "reviewer" / "status.json",
                {
                    "verdict": "approved",
                    "summary": "looked good at the time",
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
            MODULE.save_turn_metadata(turn_one, 1, "approved", role="reviewer")
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_profile="review",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen-old",
                reviewer_session="rev-old",
                review_bridge={"mode": "internal"},
            )
            state["status"] = "approved"
            state["current_turn"] = 1
            MODULE.save_run_state(run_dir, state)
            self.commit_repo_changes(repo_root, "record approved run")

            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Investigate why the fallback path still drops the new invariant on retry.\n- Reopen because the requirements now include a new fallback invariant that the old approval never checked.\n",
                encoding="utf-8",
            )
            self.commit_repo_changes(repo_root, "update review after approval")

            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                reason_kind="requirements_changed_after_approval",
                reason="The current review requirements changed after the original approval.",
            )
            with mock.patch.object(MODULE, "run_id_value", return_value="run-2"), mock.patch.object(
                MODULE, "read_codex_session_index", return_value=[]
            ), mock.patch.object(
                MODULE, "create_tmux_sessions", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_sessions_ready", return_value=None
            ), mock.patch.object(
                MODULE, "supervisor_loop_from", return_value=None
            ), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.reopen_run(args)

            self.assertEqual(result, 0)
            new_run_dir = task_root / "runs" / "run-2"
            new_state = MODULE.load_json(new_run_dir / "state.json")
            self.assertEqual(new_state["reopen"]["reason_kind"], "requirements_changed_after_approval")
            self.assertEqual(new_state["reopen"]["reopened_from"]["run_id"], "run-1")
            self.assertEqual(new_state["reopen"]["reopened_from"]["turn"], "0001")
            self.assertTrue(new_state["reopen"]["doc_comparison"]["docs_changed_since_approval"])
            self.assertIn("review.md", new_state["reopen"]["doc_comparison"]["changed_existing_docs"])
            self.assertNotIn("task", new_state["workspace_profile"])
            reopen_artifact = MODULE.load_json(new_run_dir / MODULE.REOPEN_METADATA_FILENAME)
            self.assertEqual(reopen_artifact["reopened_from"]["run_id"], "run-1")
            reopen_index_lines = MODULE.reopen_index_path_for(repo_root).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(reopen_index_lines), 1)
            reopen_index_entry = json.loads(reopen_index_lines[0])
            self.assertEqual(reopen_index_entry["new_run_id"], "run-2")
            self.assertEqual(reopen_index_entry["reason_kind"], "requirements_changed_after_approval")
            old_status = MODULE.load_json(turn_one / "reviewer" / "status.json")
            self.assertEqual(old_status["verdict"], "approved")

    def test_reopen_run_rejects_nonapproved_runs_and_points_to_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix bug.\n\n## Context\n\n- narrow scope\n\n## Success Signal\n\nA concrete regression is fixed.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_profile="task",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
            )
            state["status"] = "blocked"
            MODULE.save_run_state(run_dir, state)
            self.commit_repo_changes(repo_root, "record unfinished run")

            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                reason_kind="false_approved",
                reason="Approval was incorrect.",
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.reopen_run(args)
            self.assertIn("not approved", str(ctx.exception))
            self.assertIn("continue demo-task --run-id run-1", str(ctx.exception))

    def test_determine_continue_target_for_approved_run_mentions_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.write_text(turn_one / "generator" / "message.md", "generator message")
            MODULE.save_json(
                turn_one / "generator" / "status.json",
                {"result": "implemented", "summary": "done", "changed_files": ["src/app.py"]},
            )
            MODULE.write_text(turn_one / "reviewer" / "message.md", "reviewer message")
            MODULE.save_json(
                turn_one / "reviewer" / "status.json",
                {
                    "verdict": "approved",
                    "summary": "all clear",
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

            with self.assertRaises(SystemExit) as ctx:
                MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertIn("use `reopen`", str(ctx.exception))

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
                "# Task\n\n## Request\n\nFix the fallback path that leaves the parser in a partial state.\n\n## Context\n\n- The failure is in the parser fallback path, not the happy path.\n- Preserve the public API while fixing the partial-state behavior.\n\n## Success Signal\n\nThe fallback path no longer leaves partial state behind and the relevant verification passes.\n",
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

    def test_build_parser_exposes_write_start_role_shared_fork_github_and_reopen_args(self) -> None:
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
        reopen_args = parser.parse_args(
            [
                "reopen",
                "demo-task",
                "--reason-kind",
                "false_approved",
                "--reason",
                "Approval was wrong.",
            ]
        )
        self.assertEqual(write_args.command, "write")
        self.assertEqual(start_args.fork_session_id, "id")
        self.assertEqual(start_args.start_role, "reviewer")
        self.assertEqual(start_args.review_mode, "github_pr_codex")
        self.assertEqual(start_args.github_pr, "42")
        self.assertEqual(start_args.github_base, "main")
        self.assertEqual(reopen_args.command, "reopen")
        self.assertEqual(reopen_args.reason_kind, "false_approved")
        self.assertEqual(reopen_args.reason, "Approval was wrong.")

    def test_consumer_docs_reference_canonical_cli_and_document_model(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        architecture = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
        instructs = (repo_root / "INSTRUCTS.md").read_text(encoding="utf-8")
        skill = (repo_root / "skills" / "codex-council" / "SKILL.md").read_text(encoding="utf-8")
        run_lifecycle = (repo_root / "skills" / "codex-council" / "references" / "run-lifecycle.md").read_text(encoding="utf-8")
        failure_recovery = (repo_root / "skills" / "codex-council" / "references" / "failure-recovery.md").read_text(encoding="utf-8")
        routing = (repo_root / "skills" / "codex-council" / "references" / "routing.md").read_text(encoding="utf-8")

        for command in ("init", "write", "start", "continue", "reopen", "status"):
            self.assertIn(f"`{command}`", readme)
            self.assertIn(f"`{command}`", instructs)

        for doc_name in MODULE.INPUT_DOC_FILENAMES.values():
            self.assertIn(f"`{doc_name}`", readme)
            self.assertIn(f"`{doc_name}`", instructs)

        self.assertIn("`AGENTS.md`", readme)
        self.assertIn("`AGENTS.md`", instructs)
        self.assertIn("maintainer guidance", instructs)
        self.assertIn("outer coding agent", readme)
        self.assertIn("source of truth", architecture.lower())
        self.assertIn("artifact-driven", architecture)
        self.assertIn("harness operator", readme)
        self.assertIn("harness operator", instructs)
        self.assertIn("Do not implement the target-repo feature directly", instructs)
        self.assertIn("supervisor process", readme)
        self.assertIn("supervisor process", instructs)
        self.assertIn("tmux", architecture)
        self.assertIn("dedicated `tmux` session", readme)
        self.assertIn("dedicated `tmux` session", instructs)
        self.assertIn("foreground command is enough", instructs)
        self.assertIn("editing the canonical files directly", readme)
        self.assertIn("fill the canonical files directly", instructs)
        self.assertIn("Decision-Complete Specs", instructs)
        self.assertIn("false_approved", readme)
        self.assertIn("requirements_changed_after_approval", readme)
        self.assertIn("false_approved", instructs)
        self.assertIn("requirements_changed_after_approval", instructs)
        self.assertIn("`reopen`", skill)
        self.assertIn("false_approved", run_lifecycle)
        self.assertIn("requirements_changed_after_approval", run_lifecycle)
        self.assertIn("`reopen`", failure_recovery)
        self.assertIn("`reopen`", routing)

    def test_codex_council_skill_reference_pack_is_present_and_linked(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        skill_root = repo_root / "skills" / "codex-council"
        skill_path = skill_root / "SKILL.md"
        self.assertTrue(skill_path.exists())
        skill_text = skill_path.read_text(encoding="utf-8")

        expected_refs = (
            "references/routing.md",
            "references/novice-normalization.md",
            "references/operator-boundary.md",
            "references/supervisor-lifetime.md",
            "references/task-doc.md",
            "references/review-doc.md",
            "references/spec-doc.md",
            "references/contract-doc.md",
            "references/run-lifecycle.md",
            "references/failure-recovery.md",
            "references/user-sophistication-examples.md",
            "references/task-type-examples.md",
        )
        for relative_ref in expected_refs:
            self.assertTrue((skill_root / relative_ref).exists())
            self.assertIn(relative_ref, skill_text)
        self.assertIn("directly implement the target-repo feature yourself", skill_text)
        self.assertIn("abandon the supervisor process", skill_text)
        self.assertIn("process-lifetime rule", skill_text)
        self.assertIn("dedicated `tmux` session", skill_text)
        self.assertIn("prefer editing the canonical files directly", skill_text)
        self.assertIn("decision-complete", skill_text)

    def test_scaffold_templates_and_role_instructions_emphasize_brief_quality(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        task_template = (repo_root / "templates" / "scaffold" / "task.md").read_text(encoding="utf-8")
        review_template = (repo_root / "templates" / "scaffold" / "review.md").read_text(encoding="utf-8")
        spec_template = (repo_root / "templates" / "scaffold" / "spec.md").read_text(encoding="utf-8")
        contract_template = (repo_root / "templates" / "scaffold" / "contract.md").read_text(encoding="utf-8")
        generator_instructions = (repo_root / "templates" / "scaffold" / "generator.instructions.md").read_text(encoding="utf-8")
        reviewer_instructions = (repo_root / "templates" / "scaffold" / "reviewer.instructions.md").read_text(encoding="utf-8")

        self.assertIn("default starting point for most execution requests", task_template)
        self.assertIn("pair this file with `contract.md`", review_template)
        self.assertIn("pair this file with `contract.md`", task_template)
        self.assertIn("deeper structure than `task.md`", spec_template)
        self.assertIn("keep `contract.md` alongside this file", spec_template)
        self.assertIn("### Source of Truth / Ownership", spec_template)
        self.assertIn("Not applicable because", spec_template)
        self.assertIn("default acceptance and approval checklist", contract_template)
        self.assertIn("Skip it only for ultra-trivial tasks", contract_template)
        self.assertIn("regression / integrity / fallback / state guardrail", contract_template)
        self.assertIn("do not compensate by inventing missing requirements", generator_instructions)
        self.assertIn("vague or aspirational `contract.md` items", reviewer_instructions)
        self.assertIn("decision-complete", generator_instructions)
        self.assertIn("missing implementation-critical decisions", reviewer_instructions)
        self.assertIn("Passing tests or a satisfied-looking contract are not enough for approval", reviewer_instructions)
        self.assertIn("Code paths inspected", reviewer_instructions)


if __name__ == "__main__":
    unittest.main()
