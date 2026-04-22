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
            "planning": {
                "max_turns": 4,
            },
            "review": {
                "fresh_reviewer_session_per_turn": True,
                "reviewer_reset_mode": "clear",
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

    def write_planner_status(self, turn_dir: Path, *, result: str = "drafted") -> None:
        (turn_dir / "planner").mkdir(parents=True, exist_ok=True)
        (turn_dir / "planner" / "message.md").write_text("planner", encoding="utf-8")
        payload = {
            "result": result,
            "summary": "Planning docs updated.",
            "docs_updated": [MODULE.TASK_FILENAME, MODULE.SPEC_FILENAME, MODULE.CONTRACT_FILENAME],
        }
        if result == "needs_human":
            payload["human_source"] = MODULE.TASK_FILENAME
            payload["human_message"] = "Need clarification."
        MODULE.save_json(turn_dir / "planner" / "status.json", payload)

    def write_intent_critic_status(self, turn_dir: Path, *, verdict: str = "approved") -> None:
        (turn_dir / "intent_critic").mkdir(parents=True, exist_ok=True)
        (turn_dir / "intent_critic" / "message.md").write_text("critic", encoding="utf-8")
        dimensions = {key: "pass" for key in MODULE.planning_review_dimension_keys()}
        if verdict != "approved":
            dimensions["spec_completeness"] = "fail"
        payload = {
            "verdict": verdict,
            "summary": "Planning docs reviewed.",
            "blocking_issues": [] if verdict == "approved" else ["Spec still missing a major section."],
            "critical_dimensions": dimensions,
        }
        if verdict == "needs_human":
            payload["human_source"] = MODULE.TASK_FILENAME
            payload["human_message"] = "Need product clarification."
        MODULE.save_json(turn_dir / "intent_critic" / "status.json", payload)

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

    def test_validate_generator_status_rejects_unknown_result(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            MODULE.validate_generator_status(
                {
                    "result": "changed",
                    "summary": "Changed parser and tests.",
                    "changed_files": ["src/parser.py"],
                }
            )
        self.assertIn("invalid generator result: changed", str(ctx.exception))

    def test_validate_generator_status_accepts_outer_review_triage(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "no_changes_needed",
                "summary": "Recorded triage only.",
                "changed_files": [],
                "outer_review_triage": {
                    "cycle_id": "run-2.C1",
                    "points": [
                        {
                            "point_id": "run-2.C1.P1",
                            "classification": "agree",
                            "evidence_summary": "The current branch still misses the required handoff artifact.",
                        }
                    ],
                },
            }
        )
        self.assertEqual(status["outer_review_triage"]["cycle_id"], "run-2.C1")

    def test_validate_generator_status_for_turn_requires_complete_outer_review_triage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            turn_dir.mkdir(parents=True)
            MODULE.save_json(
                turn_dir / MODULE.OUTER_REVIEW_INPUT_JSON_FILENAME,
                {
                    "cycle_id": "run-2.C1",
                    "points": [
                        {"point_id": "run-2.C1.P1"},
                        {"point_id": "run-2.C1.P2"},
                    ],
                },
            )
            with self.assertRaises(ValueError) as ctx:
                MODULE.validate_generator_status_for_turn(
                    turn_dir,
                    {
                        "result": "no_changes_needed",
                        "summary": "Only triaged one point.",
                        "changed_files": [],
                        "outer_review_triage": {
                            "cycle_id": "run-2.C1",
                            "points": [
                                {
                                    "point_id": "run-2.C1.P1",
                                    "classification": "agree",
                                    "evidence_summary": "First point only.",
                                }
                            ],
                        },
                    },
                )
            self.assertIn("must contain every active outer-review point", str(ctx.exception))

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

    def test_validate_planner_status_accepts_valid_payload(self) -> None:
        status = MODULE.validate_planner_status(
            {
                "result": "drafted",
                "summary": "Tightened the planning docs.",
                "docs_updated": [MODULE.TASK_FILENAME, MODULE.SPEC_FILENAME, MODULE.CONTRACT_FILENAME],
            }
        )
        self.assertEqual(status["result"], "drafted")
        self.assertEqual(len(status["docs_updated"]), 3)

    def test_validate_intent_critic_status_accepts_approved(self) -> None:
        status = MODULE.validate_intent_critic_status(
            {
                "verdict": "approved",
                "summary": "Docs are ready for execution.",
                "blocking_issues": [],
                "critical_dimensions": {key: "pass" for key in MODULE.planning_review_dimension_keys()},
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
reviewer_reset_mode = "restart"
allow_reviewer_test_edits = true
allow_reviewer_production_edits = false
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
            self.assertEqual(config["review"]["reviewer_reset_mode"], "restart")
            self.assertEqual(
                config["review"]["baseline_commands"],
                ["git diff --check", "pytest -q tests/test_example.py"],
            )
            self.assertEqual(config["review"]["path_rules"][0]["name"], "workspace")

    def test_load_council_config_rejects_unknown_reviewer_reset_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            council_root = repo_root / MODULE.COUNCIL_DIRNAME
            council_root.mkdir()
            (council_root / "config.toml").write_text(
                """
[review]
reviewer_reset_mode = "wrong"
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                MODULE.load_council_config(repo_root)

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
            self.assertTrue((task_root / "planner.instructions.md").exists())
            self.assertTrue((task_root / "intent_critic.instructions.md").exists())
            self.assertTrue((task_root / "spec-contract-linking-example.md").exists())
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

    def test_golden_brief_quality_examples_pass_start_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            brief_root = FIXTURES_ROOT / "brief_quality"
            (task_root / MODULE.TASK_FILENAME).write_text((brief_root / "good_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text((brief_root / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text((brief_root / "good_contract.md").read_text(encoding="utf-8"), encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            MODULE.validate_task_workspace_for_start(task_root, inspection)

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
                "## Desired Behavior\n\n"
                "## M1. Reporting Dashboard Surface\n\n"
                "The page shows billing status and retry health.\n\n"
                "### Acceptance Criteria\n"
                "- A1. Operators can inspect billing status from the reporting page.\n"
                "- A2. Retry health is visible on the main reporting surface.\n"
                "- A3. The dashboard remains read-only.\n\n"
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
            self.assertIn(".codex-council/demo-task/task.md", prompt)
            self.assertIn(".codex-council/demo-task/review.md", prompt)
            self.assertIn(".codex-council/demo-task/spec.md", prompt)
            self.assertIn("classify each review point as `agree`, `disagree`, or `uncertain`", prompt)
            self.assertIn("Do not describe a tests/docs/fixtures-only or helper-seam-only turn as a production fix", prompt)
            self.assertIn("Change surface classification: production/runtime code, tests/docs/fixtures/council artifacts only, or both", prompt)
            self.assertIn("What remains unproven or only indirectly proven after this turn", prompt)
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
            self.assertIn("disconfirming check against the real path", prompt)
            self.assertIn("priority items to address first, not as the whole approval surface", prompt)
            self.assertIn("Priority findings to address first (not the whole approval surface):", prompt)
            self.assertIn("next review will reopen the full task from current branch state", prompt)
            self.assertIn("Use the narrowest proven claim", prompt)

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
            self.assertIn("`generator/status.json` must use exactly this schema:", prompt)
            self.assertIn("`implemented`", prompt)
            self.assertIn("`no_changes_needed`", prompt)
            self.assertIn("`blocked`", prompt)
            self.assertIn("`needs_human`", prompt)

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

    def test_build_planner_prompt_includes_planner_status_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "run-1"
            turn_dir = run_dir / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            prompt = MODULE.build_planner_turn_prompt(
                Path("/repo"),
                task_root,
                run_dir,
                turn_dir,
                1,
                state={},
                inline_context=True,
            )
            self.assertIn("`planner/status.json` must use exactly this schema:", prompt)
            self.assertIn("`drafted`", prompt)
            self.assertIn("`blocked`", prompt)
            self.assertIn("`needs_human`", prompt)

    def test_build_intent_critic_prompt_includes_status_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "run-1"
            turn_dir = run_dir / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            prompt = MODULE.build_intent_critic_turn_prompt(
                Path("/repo"),
                task_root,
                run_dir,
                turn_dir,
                1,
                state={},
                inline_context=True,
            )
            self.assertIn("`intent_critic/status.json` must use exactly this schema:", prompt)
            self.assertIn("`approved`", prompt)
            self.assertIn("`changes_requested`", prompt)
            self.assertIn("`blocked`", prompt)
            self.assertIn("`needs_human`", prompt)

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
            self.assertIn("Treat the generator's latest message as context information only", prompt)
            self.assertIn("Approval is whole-task and whole-branch", prompt)
            self.assertIn("Reconstruct the full approval surface", prompt)
            self.assertIn("Review scope note:", prompt)
            self.assertIn("Primary review scope: the full current branch state against `task.md`, `spec.md`, and `contract.md`.", prompt)
            self.assertIn("Latest generator context only (not review scope)", prompt)
            self.assertIn("Latest generator context only (not review scope):", prompt)
            self.assertIn("context information only", prompt)
            self.assertIn("revisit the full approval surface, including already-checked contract items", prompt)
            self.assertIn("Minimum context checks only (not approval proof):", prompt)
            self.assertIn("complete full-task audit", prompt)
            self.assertIn("Generator Framing Risks Checked", prompt)
            self.assertIn("Disconfirming Checks Run", prompt)
            self.assertIn("Evidence Basis for Approval-Critical Claims", prompt)
            self.assertIn("What remains unproven after this turn", prompt)
            self.assertIn("Previously checked contract items and cited acceptance sub-checks re-audited", prompt)
            self.assertIn("Contract items or cited acceptance sub-checks unchecked again this turn, if any", prompt)
            self.assertIn("Areas audited beyond the latest generator delta", prompt)
            self.assertIn("What the latest generator turn claimed", prompt)
            self.assertIn("Why the review was not limited to that claim", prompt)
            self.assertIn("Regressions that forced reversal of prior confidence", prompt)
            self.assertIn("Key Code Paths Inspected", prompt)
            self.assertIn("Verification Performed", prompt)
            self.assertIn("Branch Health Verdict", prompt)
            self.assertIn("`reviewer/status.json` must use exactly this schema:", prompt)
            self.assertIn("`approved`", prompt)
            self.assertIn("`changes_requested`", prompt)
            self.assertIn("`blocked`", prompt)
            self.assertIn("`needs_human`", prompt)

    def test_build_artifact_repair_prompt_includes_role_schema_block(self) -> None:
        prompt = MODULE.build_artifact_repair_prompt_for_paths(
            role="generator",
            turn_number=3,
            error_message="invalid generator result: changed",
            output_paths=[Path("/tmp/message.md"), Path("/tmp/status.json")],
        )
        self.assertIn("invalid generator result: changed", prompt)
        self.assertIn("`generator/status.json` must use exactly this schema:", prompt)
        self.assertIn("`implemented`", prompt)

    def test_record_prompt_dispatch_artifact_writes_dispatch_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.record_prompt_dispatch_artifact(
                turn_dir,
                "generator",
                prompt="fix the issue",
                dispatch_reason="generator_turn",
            )
            dispatch_path = MODULE.role_dispatch_path(turn_dir, "generator")
            self.assertTrue(dispatch_path.exists())
            payload = MODULE.load_json(dispatch_path)
            self.assertEqual(payload["dispatch_count"], 1)
            self.assertEqual(payload["last_dispatch_reason"], "generator_turn")
            self.assertEqual(payload["dispatches"][0]["dispatch_reason"], "generator_turn")

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
            self.assertIn("Do not inherit prior checklist state", prompt)
            self.assertIn("previously satisfied contract item", prompt)
            self.assertIn("Re-audit every approval-critical contract section and every cited acceptance sub-check from current branch state", prompt)
            self.assertIn("already-checked contract items that may need to be unchecked again on regression", prompt)
            self.assertIn("Ask explicitly what could have regressed outside the latest fix", prompt)
            self.assertIn("only rechecked the latest fix, the latest open blocker, or the currently unchecked contract items", prompt)
            self.assertIn("Evidence Basis for Approval-Critical Claims", prompt)

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
            self.assertIn("targeted disconfirming real-path check", prompt)
            self.assertIn("latest generator turn only as background context", prompt)
            self.assertIn("pytest -q tests/test_example.py", prompt)

    def test_build_evaluator_brief_labels_latest_surface_as_starting_point_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            inspection = MODULE.inspect_task_workspace(task_root)
            brief = MODULE.build_evaluator_brief(
                repo_root,
                task_root,
                inspection,
                turn_dir,
                state={"review_bridge": {"mode": "internal"}, "council_config": self.build_council_config()},
                phase="implementation-review",
                initial_review_surface=["src/example.py"],
                required_commands=["pytest -q tests/test_example.py"],
            )
            self.assertIn("Primary review scope: the full current branch state against `task.md`, `spec.md`, and `contract.md`.", brief)
            self.assertIn("revisit all approval-critical areas, including already-checked contract items", brief)
            self.assertIn("Latest generator artifacts are background context only", brief)
            self.assertIn("## Latest Generator Context Only", brief)
            self.assertIn("Use this only as background after reconstructing the full approval surface", brief)
            self.assertIn("## Latest-Context Background Checks Only", brief)
            self.assertIn("never replace a full-task, full-branch re-audit", brief)

    def test_build_reviewer_prompt_warns_when_change_surface_is_tests_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            self.write_generator_status(turn_dir, changed_files=["tests/test_example.py", "README.md"])
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
            self.assertIn("This turn appears to touch only tests/docs/fixtures or council artifacts.", prompt)
            self.assertIn("independently verify the unchanged production/runtime path", prompt)

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
            self.assertIn("You may add or tighten tests/fixtures only when needed", prompt)

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

    def test_enforce_fresh_reviewer_session_for_turn_uses_clear_mode_when_ready(self) -> None:
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
                MODULE, "clear_role_session", return_value=None
            ) as clear_session, mock.patch.object(MODULE, "save_run_state", return_value=None), mock.patch.object(
                MODULE, "append_run_event", return_value=None
            ) as append_event:
                MODULE.enforce_fresh_reviewer_session_for_turn(Path(tmp_dir), run_state, 3)
        clear_session.assert_called_once()
        self.assertEqual(run_state["roles"]["reviewer"]["codex_session_id"], "session-123")
        self.assertEqual(run_state["roles"]["reviewer"]["last_session_reset_reason"], "fresh_reviewer_session_clear")
        self.assertEqual(append_event.call_args.args[1], "reviewer_session_cleared_for_fresh_turn")

    def test_enforce_fresh_reviewer_session_for_turn_honors_restart_mode(self) -> None:
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
        run_state["council_config"]["review"]["reviewer_reset_mode"] = "restart"
        with tempfile.TemporaryDirectory() as tmp_dir:
            with mock.patch.object(MODULE, "tmux_session_exists", return_value=True), mock.patch.object(
                MODULE, "tmux_kill_session", return_value=None
            ) as kill_session, mock.patch.object(MODULE, "clear_role_session", return_value=None) as clear_session, mock.patch.object(
                MODULE, "save_run_state", return_value=None
            ), mock.patch.object(
                MODULE, "append_run_event", return_value=None
            ) as append_event:
                MODULE.enforce_fresh_reviewer_session_for_turn(Path(tmp_dir), run_state, 3)
        kill_session.assert_called_once()
        clear_session.assert_not_called()
        self.assertIsNone(run_state["roles"]["reviewer"]["codex_session_id"])
        self.assertEqual(run_state["roles"]["reviewer"]["last_session_reset_reason"], "fresh_reviewer_session_restart")
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
            MODULE.append_run_event(run_dir, "generator_prompt_sent", turn_number=1, role="generator")
            MODULE.append_run_event(run_dir, "reviewer_session_ready", turn_number=1, role="reviewer")

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
            self.assertEqual(payload["latest_role_milestones"]["generator"]["event"], "generator_prompt_sent")
            self.assertEqual(payload["latest_role_milestones"]["reviewer"]["event"], "reviewer_session_ready")

    def test_determine_continue_target_explains_reviewer_reset_handoff_gap(self) -> None:
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
            MODULE.write_text(turn_one / "reviewer" / "prompt.md", "reviewer prompt")
            MODULE.save_turn_metadata(turn_one, 1, "reviewer_session_reset_completed", role="reviewer")
            result = MODULE.determine_continue_target(run_dir, {"review_bridge": {"mode": "internal"}})
            self.assertEqual(result[:4], (turn_one, 1, "reviewer", False))
            self.assertEqual(result[4], "reviewer_pending")

    def test_run_reviewer_phase_records_handoff_milestones(self) -> None:
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
            self.write_generator_status(turn_one, changed_files=["src/example.py"])
            state = {
                "status": "booting",
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
            }
            with mock.patch.object(MODULE, "enforce_fresh_reviewer_session_for_turn", return_value=None), mock.patch.object(
                MODULE, "ensure_role_session_ready", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_tmux_prompt", return_value=None
            ), mock.patch.object(
                MODULE, "tmux_send_prompt", return_value=None
            ), mock.patch.object(
                MODULE, "write_raw_final_output_artifact", return_value=None
            ), mock.patch.object(
                MODULE, "wait_for_role_artifacts",
                return_value=(turn_one / "reviewer" / "message.md", turn_one / "reviewer" / "status.json", {
                    "verdict": "changes_requested",
                    "summary": "need more work",
                    "blocking_issues": ["x"],
                    "critical_dimensions": {
                        "correctness_vs_intent": "fail",
                        "regression_risk": "fail",
                        "failure_mode_and_fallback": "pass",
                        "state_and_metadata_integrity": "pass",
                        "test_adequacy": "fail",
                        "maintainability": "pass",
                    },
                    "human_message": None,
                    "human_source": None,
                    "reviewed_commit_sha": None,
                })
            ):
                MODULE.write_text(turn_one / "reviewer" / "message.md", "review")
                MODULE.save_json(
                    turn_one / "reviewer" / "status.json",
                    {
                        "verdict": "changes_requested",
                        "summary": "need more work",
                        "blocking_issues": ["x"],
                        "critical_dimensions": {
                            "correctness_vs_intent": "fail",
                            "regression_risk": "fail",
                            "failure_mode_and_fallback": "pass",
                            "state_and_metadata_integrity": "pass",
                            "test_adequacy": "fail",
                            "maintainability": "pass",
                        },
                    },
                )
                reviewer_status = MODULE.run_reviewer_phase(run_dir, state, task_root, 1, turn_one, inline_context=True)
            self.assertEqual(reviewer_status["verdict"], "changes_requested")
            self.assertEqual(state["roles"]["reviewer"]["last_wait_phase"], "reviewer_prompt_sent")
            metadata = MODULE.load_turn_metadata(turn_one)
            self.assertEqual(metadata["phase"], "reviewer_prompt_sent")

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

    def test_continue_run_writes_diagnostics_on_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
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
                    "run_id": "run-1",
                    "diagnostics_dir": str(run_dir / "diagnostics"),
                },
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
            )
            error = MODULE.SupervisorRuntimeError("generator_session_ready", "boom", role="generator")
            with mock.patch.object(MODULE, "ensure_active_role_sessions_ready", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)
            self.assertEqual(result, 1)
            diagnostics_root = run_dir / "diagnostics"
            self.assertTrue(diagnostics_root.exists())
            failure_dirs = [path for path in diagnostics_root.iterdir() if path.is_dir()]
            self.assertTrue(failure_dirs)
            self.assertTrue((failure_dirs[0] / "error.json").exists())
            persisted_state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(persisted_state["status"], "blocked")
            self.assertIn("generator_session_ready", persisted_state["stop_reason"])
            events_text = MODULE.events_path_for(run_dir).read_text(encoding="utf-8")
            self.assertIn("\"event\": \"blocked\"", events_text)

    def test_continue_run_rejects_missing_state_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            broken_run_dir = task_root / "runs" / "broken-run"
            (broken_run_dir / "turns").mkdir(parents=True)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="broken-run",
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.continue_run(args)
            self.assertIn("missing run state", str(ctx.exception))

    def test_continue_run_writes_blocked_invalid_artifacts_status_on_invalid_artifact_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
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
                    "run_id": "run-1",
                    "diagnostics_dir": str(run_dir / "diagnostics"),
                },
            )
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
            )
            error = MODULE.SupervisorRuntimeError("blocked_invalid_artifacts", "broken artifact", role="generator")
            with mock.patch.object(MODULE, "ensure_active_role_sessions_ready", side_effect=error), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)
            self.assertEqual(result, 1)
            persisted_state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(persisted_state["status"], "blocked_invalid_artifacts")
            events_text = MODULE.events_path_for(run_dir).read_text(encoding="utf-8")
            self.assertIn("\"event\": \"blocked_invalid_artifacts\"", events_text)

    def test_build_outer_review_state_for_start_rejects_github_mode(self) -> None:
        args = argparse.Namespace(outer_review_session_id="sess-123")
        with self.assertRaises(SystemExit) as ctx:
            MODULE.build_outer_review_state_for_start("github_pr_codex", args)
        self.assertIn("--outer-review-session-id", str(ctx.exception))

    def test_start_run_rejects_outer_review_session_id_for_github_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix a bug.\n\n## Context\n\n- narrow scope\n\n## Success Signal\n\nA concrete regression is fixed.\n",
                encoding="utf-8",
            )
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
                review_mode="github_pr_codex",
                github_pr="42",
                github_branch=None,
                github_base=None,
                outer_review_session_id="sess-123",
                start_role="auto",
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.start_run(args)
            self.assertIn("--outer-review-session-id", str(ctx.exception))

    def test_write_outer_review_input_artifacts_uses_findings_section_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Fix the missing handoff artifact.\n\n## Context\n\n- This context bullet must not become an active point.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-2"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-2",
                workspace_profile="review",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
                outer_review=MODULE.new_outer_review_state(codex_session_id=None),
                reopen_context={
                    "reason_kind": "false_approved",
                    "outer_review_path": True,
                    "reopened_from": {"run_id": "run-1", "turn": "0001"},
                },
            )

            payload = MODULE.write_outer_review_input_artifacts(
                run_dir,
                task_root,
                turn_one,
                state=state,
            )

            self.assertEqual(payload["point_extraction_mode"], "findings_section_bullets")
            self.assertEqual(len(payload["points"]), 1)
            self.assertEqual(payload["points"][0]["text"], "Fix the missing handoff artifact.")

    def test_outer_review_input_ledger_uses_exact_text_lineage_on_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            previous_run_dir = task_root / "runs" / "run-1"
            new_run_dir = task_root / "runs" / "run-2"
            previous_state = MODULE.create_run_state(
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
                outer_review=MODULE.new_outer_review_state(codex_session_id="sess-old"),
            )
            previous_state["outer_review"]["active_cycle_id"] = "run-1.C1"
            MODULE.save_run_state(previous_run_dir, previous_state)
            MODULE.save_outer_review_ledger(
                previous_run_dir,
                {
                    "version": 1,
                    "cycles": [
                        {
                            "cycle_id": "run-1.C1",
                            "active_points": [
                                {
                                    "point_id": "run-1.C1.P1",
                                    "ordinal": 1,
                                    "raw_line": "- Keep the handoff artifact deterministic.",
                                    "text": "Keep the handoff artifact deterministic.",
                                    "normalized_text": "keep the handoff artifact deterministic.",
                                    "cycle_id": "run-1.C1",
                                },
                                {
                                    "point_id": "run-1.C1.P2",
                                    "ordinal": 2,
                                    "raw_line": "- Require explicit finalization acknowledgment.",
                                    "text": "Require explicit finalization acknowledgment.",
                                    "normalized_text": "require explicit finalization acknowledgment.",
                                    "cycle_id": "run-1.C1",
                                },
                            ],
                            "handoff_turns": ["0003"],
                        }
                    ],
                    "point_history": {
                        "run-1.C1.P1": {
                            "point_id": "run-1.C1.P1",
                            "cycle_id": "run-1.C1",
                            "later_reviewer_disposition": "cleared",
                            "finalization_outcome": "carried_forward_unchanged",
                            "lineage_kind": "new_in_cycle",
                            "derived_from_point_ids": [],
                        },
                        "run-1.C1.P2": {
                            "point_id": "run-1.C1.P2",
                            "cycle_id": "run-1.C1",
                            "later_reviewer_disposition": "cleared",
                            "finalization_outcome": "carried_forward_unchanged",
                            "lineage_kind": "new_in_cycle",
                            "derived_from_point_ids": [],
                        },
                    },
                },
            )
            MODULE.clone_outer_review_ledger(previous_run_dir, new_run_dir)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Keep the handoff artifact deterministic.\n- Require an explicit acknowledgment artifact before resume.\n",
                encoding="utf-8",
            )
            turn_one = MODULE.prepare_turn(new_run_dir, 1, task_root)
            new_state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-2",
                workspace_profile="review",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
                outer_review=MODULE.new_outer_review_state(codex_session_id=None),
                reopen_context={
                    "reason_kind": "false_approved",
                    "outer_review_path": True,
                    "reopened_from": {
                        "run_id": "run-1",
                        "turn": "0003",
                        "run_dir": str(previous_run_dir),
                    },
                },
            )

            MODULE.write_outer_review_input_artifacts(
                new_run_dir,
                task_root,
                turn_one,
                state=new_state,
            )

            ledger = MODULE.load_outer_review_ledger(new_run_dir)
            point_history = ledger["point_history"]
            self.assertEqual(point_history["run-2.C1.P1"]["lineage_kind"], "carried_forward_unchanged")
            self.assertEqual(point_history["run-2.C1.P1"]["derived_from_point_ids"], ["run-1.C1.P1"])
            self.assertEqual(point_history["run-2.C1.P2"]["lineage_kind"], "new_in_cycle")
            self.assertEqual(point_history["run-2.C1.P2"]["derived_from_point_ids"], [])
            self.assertEqual(point_history["run-1.C1.P1"]["later_reviewer_disposition"], "upheld")
            self.assertEqual(point_history["run-1.C1.P2"]["later_reviewer_disposition"], "cleared")

    def test_write_outer_review_handoff_artifacts_updates_state_and_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-1",
                workspace_profile="task",
                council_config=self.build_council_config(),
                git_state={
                    "current_branch": MODULE.git_current_branch(repo_root),
                    "last_generator_commit_sha": MODULE.git_head_sha(repo_root),
                },
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
                outer_review=MODULE.new_outer_review_state(codex_session_id="sess-123"),
            )
            MODULE.save_run_state(run_dir, state)
            with mock.patch.object(
                MODULE,
                "dispatch_outer_review_prompt",
                return_value=("confirmed_prompt_dispatch", "outer-thread"),
            ):
                MODULE.write_outer_review_handoff_artifacts(run_dir, state, task_root, turn_one, 1)

            payload = MODULE.load_json(turn_one / MODULE.OUTER_REVIEW_HANDOFF_JSON_FILENAME)
            updated_state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(payload["dispatch_status"], "confirmed_prompt_dispatch")
            self.assertIn("false_approved", payload["request_text"])
            self.assertIn("requirements_changed_after_approval", payload["request_text"])
            self.assertEqual(updated_state["outer_review"]["latest_handoff_turn"], "0001")
            self.assertEqual(updated_state["outer_review"]["latest_handoff_dispatch_status"], "confirmed_prompt_dispatch")
            self.assertEqual(updated_state["outer_review"]["codex_thread_name"], "outer-thread")

    def test_continue_run_closes_when_outer_review_finalization_clears_all_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-2"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            MODULE.save_json(
                turn_one / MODULE.OUTER_REVIEW_INPUT_JSON_FILENAME,
                {
                    "cycle_id": "run-2.C1",
                    "source": {
                        "review_path": str(task_root / MODULE.REVIEW_FILENAME),
                        "reopened_from_run_id": "run-1",
                        "reopened_from_turn": "0001",
                        "reopen_reason_kind": "false_approved",
                    },
                    "point_extraction_mode": "findings_section_bullets",
                    "points": [
                        {
                            "point_id": "run-2.C1.P1",
                            "ordinal": 1,
                            "raw_line": "- Keep the handoff deterministic.",
                            "text": "Keep the handoff deterministic.",
                            "normalized_text": "keep the handoff deterministic.",
                            "cycle_id": "run-2.C1",
                        }
                    ],
                },
            )
            MODULE.save_json(
                turn_one / MODULE.OUTER_REVIEW_FINALIZATION_JSON_FILENAME,
                {
                    "cycle_id": "run-2.C1",
                    "review_snapshot_sha256_before_finalization": "before-sha",
                    "triage": {
                        "cycle_id": "run-2.C1",
                        "points": [
                            {
                                "point_id": "run-2.C1.P1",
                                "classification": "agree",
                                "evidence_summary": "The branch still lacks the handoff artifact.",
                            }
                        ],
                    },
                },
            )
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-2",
                workspace_profile="review",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
                outer_review=MODULE.new_outer_review_state(codex_session_id=None),
            )
            state["status"] = "paused_needs_human"
            state["current_turn"] = 1
            state["outer_review"]["active_cycle_id"] = "run-2.C1"
            state["outer_review"]["pending_outer_finalization"] = True
            MODULE.save_run_state(run_dir, state)

            args = argparse.Namespace(task_name="demo-task", dir=str(repo_root), allow_non_git=False, run_id="run-2")
            with contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)

            self.assertEqual(result, 0)
            final_state = MODULE.load_json(run_dir / "state.json")
            ack = MODULE.load_json(turn_one / MODULE.OUTER_REVIEW_FINALIZATION_ACK_JSON_FILENAME)
            self.assertEqual(final_state["status"], "closed_no_remaining_outer_findings")
            self.assertEqual(ack["confirmation_mode"], "cleared_all_points")

    def test_continue_run_acknowledges_unchanged_outer_review_and_resumes_generator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- Keep the handoff deterministic.\n",
                encoding="utf-8",
            )
            run_dir = task_root / "runs" / "run-2"
            turn_one = MODULE.prepare_turn(run_dir, 1, task_root)
            review_text = (task_root / MODULE.REVIEW_FILENAME).read_text(encoding="utf-8")
            MODULE.save_json(
                turn_one / MODULE.OUTER_REVIEW_INPUT_JSON_FILENAME,
                {
                    "cycle_id": "run-2.C1",
                    "source": {
                        "review_path": str(task_root / MODULE.REVIEW_FILENAME),
                        "reopened_from_run_id": "run-1",
                        "reopened_from_turn": "0001",
                        "reopen_reason_kind": "false_approved",
                    },
                    "point_extraction_mode": "findings_section_bullets",
                    "points": [
                        {
                            "point_id": "run-2.C1.P1",
                            "ordinal": 1,
                            "raw_line": "- Keep the handoff deterministic.",
                            "text": "Keep the handoff deterministic.",
                            "normalized_text": "keep the handoff deterministic.",
                            "cycle_id": "run-2.C1",
                        }
                    ],
                },
            )
            MODULE.save_json(
                turn_one / MODULE.OUTER_REVIEW_FINALIZATION_JSON_FILENAME,
                {
                    "cycle_id": "run-2.C1",
                    "review_snapshot_sha256_before_finalization": MODULE.hash_text(review_text),
                    "triage": {
                        "cycle_id": "run-2.C1",
                        "points": [
                            {
                                "point_id": "run-2.C1.P1",
                                "classification": "agree",
                                "evidence_summary": "The branch still lacks the handoff artifact.",
                            }
                        ],
                    },
                },
            )
            state = MODULE.create_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="run-2",
                workspace_profile="review",
                council_config=self.build_council_config(),
                git_state=None,
                generator_session="gen",
                reviewer_session="rev",
                review_bridge={"mode": "internal"},
                outer_review=MODULE.new_outer_review_state(codex_session_id=None),
            )
            state["status"] = "paused_needs_human"
            state["current_turn"] = 1
            state["outer_review"]["active_cycle_id"] = "run-2.C1"
            state["outer_review"]["pending_outer_finalization"] = True
            MODULE.save_run_state(run_dir, state)

            args = argparse.Namespace(task_name="demo-task", dir=str(repo_root), allow_non_git=False, run_id="run-2")
            with mock.patch.object(MODULE, "ensure_active_role_sessions_ready", return_value=None), mock.patch.object(
                MODULE,
                "supervisor_loop_from",
                return_value=None,
            ) as supervisor_loop, contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.continue_run(args)

            self.assertEqual(result, 0)
            ack = MODULE.load_json(turn_one / MODULE.OUTER_REVIEW_FINALIZATION_ACK_JSON_FILENAME)
            self.assertEqual(ack["confirmation_mode"], "review_unchanged_confirmed")
            supervisor_loop.assert_called_once()
            self.assertEqual(supervisor_loop.call_args.kwargs["start_turn"], 2)
            self.assertEqual(supervisor_loop.call_args.kwargs["start_role"], "generator")

    def test_determine_continue_target_rejects_closed_no_remaining_outer_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            MODULE.scaffold_task_root(task_root, initial_task_text="Fix bug")
            run_dir = task_root / "runs" / "run-1"
            MODULE.prepare_turn(run_dir, 1, task_root)
            state = {
                "status": "closed_no_remaining_outer_findings",
                "current_turn": 1,
                "review_bridge": {"mode": "internal"},
            }
            with self.assertRaises(SystemExit) as ctx:
                MODULE.determine_continue_target(run_dir, state)
            self.assertIn("closed_no_remaining_outer_findings", str(ctx.exception))

    def test_reopen_run_enters_outer_review_path_only_for_false_approved_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.REVIEW_FILENAME).write_text(
                "# Review\n\n## Findings\n\n- The approved branch still misses the outer handoff lifecycle.\n",
                encoding="utf-8",
            )
            previous_run_dir = task_root / "runs" / "run-1"
            turn_one = MODULE.prepare_turn(previous_run_dir, 1, task_root)
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
                    "summary": "approved before outer verification",
                    "blocking_issues": [],
                    "critical_dimensions": {key: "pass" for key in MODULE.critical_review_dimension_keys()},
                },
            )
            MODULE.save_turn_metadata(turn_one, 1, "approved", role="reviewer")
            previous_state = MODULE.create_run_state(
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
                outer_review=MODULE.new_outer_review_state(codex_session_id="sess-123"),
            )
            previous_state["status"] = "approved"
            previous_state["current_turn"] = 1
            previous_state["outer_review"]["latest_handoff_turn"] = "0001"
            previous_state["outer_review"]["latest_handoff_artifact_json"] = str(
                turn_one / MODULE.OUTER_REVIEW_HANDOFF_JSON_FILENAME
            )
            previous_state["outer_review"]["latest_handoff_artifact_md"] = str(
                turn_one / MODULE.OUTER_REVIEW_HANDOFF_MARKDOWN_FILENAME
            )
            MODULE.save_run_state(previous_run_dir, previous_state)
            MODULE.save_json(
                turn_one / MODULE.OUTER_REVIEW_HANDOFF_JSON_FILENAME,
                {
                    "task_name": "demo-task",
                    "run_id": "run-1",
                    "approved_turn": "0001",
                    "request_text": "reopen with false_approved if needed",
                },
            )
            MODULE.write_text(
                turn_one / MODULE.OUTER_REVIEW_HANDOFF_MARKDOWN_FILENAME,
                "# Outer Review Handoff\n",
            )
            self.commit_repo_changes(repo_root, "record outer review handoff")

            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="run-1",
                reason_kind="false_approved",
                reason="The approved run still misses the required outer-review gate.",
                outer_review_session_id=None,
                clear_outer_review_session_id=False,
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
            new_state = MODULE.load_json(task_root / "runs" / "run-2" / "state.json")
            self.assertTrue(new_state["reopen"]["outer_review_path"])
            self.assertTrue((task_root / "runs" / "run-2" / MODULE.OUTER_REVIEW_LEDGER_FILENAME).exists())

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
            self.assertIn("planner:", rendered)
            self.assertIn("intent_critic:", rendered)
            self.assertIn("spec_contract_example:", rendered)

    def test_build_parser_exposes_prepare_write_start_role_shared_fork_github_and_reopen_args(self) -> None:
        parser = MODULE.build_parser()
        prepare_args = parser.parse_args(
            [
                "prepare",
                "demo-task",
                "--intent",
                "Build a robust workflow.",
                "--hard",
                "--planner-session",
                "planner-tmux",
                "--critic-session",
                "critic-tmux",
            ]
        )
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
        status_args = parser.parse_args(["status", "demo-task", "--planning"])
        self.assertEqual(prepare_args.command, "prepare")
        self.assertEqual(prepare_args.intent, "Build a robust workflow.")
        self.assertTrue(prepare_args.hard)
        self.assertEqual(prepare_args.planner_session, "planner-tmux")
        self.assertEqual(prepare_args.critic_session, "critic-tmux")
        self.assertEqual(write_args.command, "write")
        self.assertEqual(start_args.fork_session_id, "id")
        self.assertEqual(start_args.start_role, "reviewer")
        self.assertEqual(start_args.review_mode, "github_pr_codex")
        self.assertEqual(start_args.github_pr, "42")
        self.assertEqual(start_args.github_base, "main")
        self.assertEqual(reopen_args.command, "reopen")
        self.assertEqual(reopen_args.reason_kind, "false_approved")
        self.assertEqual(reopen_args.reason, "Approval was wrong.")
        self.assertTrue(status_args.planning)

    def test_build_parser_exposes_outer_review_session_args(self) -> None:
        parser = MODULE.build_parser()
        start_args = parser.parse_args(
            [
                "start",
                "demo-task",
                "--outer-review-session-id",
                "sess-123",
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
                "--clear-outer-review-session-id",
            ]
        )
        self.assertEqual(start_args.outer_review_session_id, "sess-123")
        self.assertTrue(reopen_args.clear_outer_review_session_id)

    def test_prepare_run_scaffolds_planning_workspace_and_source_intent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent="Build a production-grade workflow.",
                intent_file=None,
                hard=True,
                run_id=None,
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with mock.patch.object(MODULE, "run_planning_supervisor_for_initialized_run", return_value=0):
                result = MODULE.prepare_run(args)
            self.assertEqual(result, 0)
            task_root = MODULE.task_root_for(Path(tmp_dir), "demo-task")
            planning_runs_root = task_root / MODULE.PLANNING_RUNS_DIRNAME
            self.assertTrue((task_root / "planner.instructions.md").exists())
            self.assertTrue((task_root / "intent_critic.instructions.md").exists())
            self.assertTrue(planning_runs_root.exists())
            run_dirs = sorted(path for path in planning_runs_root.iterdir() if path.is_dir())
            self.assertEqual(len(run_dirs), 1)
            source_intent = (run_dirs[0] / MODULE.PLANNING_SOURCE_INTENT_FILENAME).read_text(encoding="utf-8")
            self.assertIn("Build a production-grade workflow.", source_intent)
            self.assertIn("Hard mode: enabled", source_intent)

    def test_resolve_planning_continuation_plan_routes_changes_requested_to_next_planner_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="changes_requested")
            plan = MODULE.resolve_planning_continuation_plan(run_dir, state)
            self.assertEqual(plan["mode"], "continue")
            self.assertEqual(plan["role"], "planner")
            self.assertTrue(plan["create_new_turn"])
            self.assertEqual(plan["turn_number"], 2)

    def test_show_status_supports_planning_runs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text("# Task\n\n## Request\n\nPlan it\n\n## Context\n\nctx\n\n## Success Signal\n\nready\n", encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text("# Spec\n\n## Goal\n\ngoal\n\n## User Outcome\n\noutcome\n\n## In Scope\n\n- one\n\n## Out of Scope\n\n- two\n\n## Constraints\n\n- three\n\n## Existing Context\n\nctx\n\n## Desired Behavior\n\nbody\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate\n\n## Open Questions\n\n- none\n", encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] Example\n", encoding="utf-8")
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="task+spec+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=True,
            )
            state["status"] = "approved"
            state["stop_reason"] = "Docs approved."
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="approved")
            MODULE.refresh_planning_turn_context_manifest(run_dir, task_root, turn_one)
            MODULE.append_run_event(run_dir, "planner_prompt_sent", turn_number=1, role="planner")
            MODULE.append_run_event(run_dir, "intent_critic_prompt_sent", turn_number=1, role="intent_critic")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                run_id="plan-run",
                planning=True,
            )
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = MODULE.show_status(args)
            self.assertEqual(result, 0)
            payload = json.loads(output.getvalue())
            self.assertTrue(payload["docs_approved_for_execution"])
            self.assertIn("planner", payload["latest_role_milestones"])
            self.assertIn("intent_critic", payload["latest_role_milestones"])

    def test_validate_task_workspace_for_start_rejects_missing_section_acceptance_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. Workflow matches Spec M1 and validation passes.\n- [ ] Validation and branch quality gate.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("missing `### Acceptance Criteria`", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_unlabeled_acceptance_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Acceptance Criteria\n- The primary workflow works on the intended path.\n- Validation covers the changed behavior.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The workflow works.\n- [ ] Validation and branch quality gate.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must label acceptance criteria as `- A1. ...`", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_missing_contract_acceptance_subchecks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Acceptance Criteria\n- A1. The primary workflow works on the intended path.\n- A2. Validation covers the changed behavior.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. Workflow Surface\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must cite every acceptance criterion as indented sub-checks", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_contract_acceptance_text_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Acceptance Criteria\n- A1. The primary workflow works on the intended path.\n- A2. Validation covers the changed behavior.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. Workflow Surface\n  - [ ] M1.A1 The wrong path works instead.\n  - [ ] M1.A2 Validation covers the changed behavior.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must cite the linked acceptance criterion text", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_contract_section_title_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Acceptance Criteria\n- A1. The primary workflow works on the intended path.\n- A2. Validation covers the changed behavior.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. Totally Unrelated Title\n  - [ ] M1.A1 The primary workflow works on the intended path.\n  - [ ] M1.A2 Validation covers the changed behavior.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must use the same section title", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_contract_acceptance_operator_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. Workflow Surface\n\nDescribe the behavior.\n\n### Acceptance Criteria\n- A1. p99 latency stays <= 500 ms for the primary workflow.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. Workflow Surface\n  - [ ] M1.A1 p99 latency stays >= 500 ms for the primary workflow.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must cite the linked acceptance criterion text", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_top_level_acceptance_subcheck(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            brief_root = FIXTURES_ROOT / "brief_quality"
            (task_root / MODULE.TASK_FILENAME).write_text((brief_root / "good_task.md").read_text(encoding="utf-8"), encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text((brief_root / "good_spec.md").read_text(encoding="utf-8"), encoding="utf-8")
            contract_text = (brief_root / "good_contract.md").read_text(encoding="utf-8") + "\n- [ ] M1.A99 Totally unrelated top-level item.\n"
            (task_root / MODULE.CONTRACT_FILENAME).write_text(contract_text, encoding="utf-8")
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("must be indented under the top-level `M1` checklist item", str(ctx.exception))

    def test_validate_task_workspace_for_start_rejects_duplicate_major_spec_sections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. First Workflow Surface\n\nDescribe the first behavior.\n\n### Acceptance Criteria\n- A1. The first workflow path works.\n\n## M1. Duplicate Workflow Surface\n\nDescribe the duplicate behavior.\n\n### Acceptance Criteria\n- A1. The duplicate workflow path works.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M1. First Workflow Surface\n  - [ ] M1.A1 The first workflow path works.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("repeats major section ids", str(ctx.exception))

    def test_validate_task_workspace_for_start_does_not_confuse_m1_with_m10_linkage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nBuild a broad workflow feature safely.\n\n## Context\n\nThe feature spans multiple product and runtime surfaces.\n\n## Success Signal\n\nThe behavior is implemented and remains auditable.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.SPEC_FILENAME).write_text(
                "# Spec\n\n## Goal\n\nDesign a broad feature safely.\n\n## User Outcome\n\nUsers can complete the workflow safely.\n\n## In Scope\n\n- Workflow\n\n## Out of Scope\n\n- Unrelated systems\n\n## Constraints\n\n- Stay auditable\n\n## Existing Context\n\nContext.\n\n## Desired Behavior\n\n## M1. First Surface\n\nDescribe the first behavior.\n\n### Acceptance Criteria\n- A1. The first surface works.\n- A2. The first validation exists.\n\n## M10. Tenth Surface\n\nDescribe the tenth behavior.\n\n### Acceptance Criteria\n- A1. The tenth surface works.\n- A2. The tenth validation exists.\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate well\n\n## Open Questions\n\n- none\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] M10. The tenth surface works and validation passes.\n- [ ] Validation and branch quality gate.\n",
                encoding="utf-8",
            )
            inspection = MODULE.inspect_task_workspace(task_root)
            with self.assertRaises(SystemExit) as ctx:
                MODULE.validate_task_workspace_for_start(task_root, inspection)
            self.assertIn("missing linkage for: M1", str(ctx.exception))

    def test_latest_named_run_dir_uses_state_created_at_not_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            runs_root = Path(tmp_dir) / "planning-runs"
            older = runs_root / "z-old"
            newer = runs_root / "a-new"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            MODULE.save_json(older / "state.json", {"created_at": "2026-04-18T10:00:00Z"})
            MODULE.save_json(newer / "state.json", {"created_at": "2026-04-18T11:00:00Z"})
            latest = MODULE.latest_named_run_dir(runs_root, label="planning runs")
            self.assertEqual(latest.name, "a-new")

    def test_latest_run_dir_uses_state_created_at_not_directory_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            runs_root = task_root / "runs"
            older = runs_root / "z-old"
            newer = runs_root / "a-new"
            older.mkdir(parents=True)
            newer.mkdir(parents=True)
            MODULE.save_json(older / "state.json", {"created_at": "2026-04-18T10:00:00Z"})
            MODULE.save_json(newer / "state.json", {"created_at": "2026-04-18T11:00:00Z"})
            latest = MODULE.latest_run_dir(task_root)
            self.assertEqual(latest.name, "a-new")

    def test_prepare_run_rejects_reserved_latest_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent="Plan it",
                intent_file=None,
                hard=False,
                run_id="latest",
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.prepare_run(args)
            self.assertIn("reserved as a run selector", str(ctx.exception))

    def test_start_run_rejects_reserved_latest_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id="latest",
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.start_run(args)
            self.assertIn("reserved as a run selector", str(ctx.exception))

    def test_prepare_run_rejects_latest_planning_continuation_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_intent_critic_status(turn_one, verdict="changes_requested")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id=None,
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.prepare_run(args)
            self.assertIn("mixes intent critic activity with incomplete planner state", str(ctx.exception))

    def test_prepare_run_rejects_latest_planning_run_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            broken_run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "broken-run"
            (broken_run_dir / "turns").mkdir(parents=True)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id=None,
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.prepare_run(args)
            self.assertIn("missing state", str(ctx.exception))

    def test_prepare_run_rejects_explicit_planning_run_missing_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            broken_run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "broken-run"
            (broken_run_dir / "turns").mkdir(parents=True)
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id="broken-run",
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.prepare_run(args)
            self.assertIn("selected planning run is missing state", str(ctx.exception))

    def test_prepare_run_explicit_approved_planning_run_rejects_doc_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text("# Task\n\n## Request\n\nPlan it\n\n## Context\n\nctx\n\n## Success Signal\n\nready\n", encoding="utf-8")
            (task_root / MODULE.SPEC_FILENAME).write_text("# Spec\n\n## Goal\n\ngoal\n\n## User Outcome\n\noutcome\n\n## In Scope\n\n- one\n\n## Out of Scope\n\n- two\n\n## Constraints\n\n- three\n\n## Existing Context\n\nctx\n\n## Desired Behavior\n\nbody\n\n### Source of Truth / Ownership\n\nNot applicable because none.\n\n### Read Path\n\nNot applicable because none.\n\n### Write Path / Mutation Flow\n\nNot applicable because none.\n\n### Runtime / Performance Expectations\n\nNot applicable because none.\n\n### Failure / Fallback / Degraded Behavior\n\nNot applicable because none.\n\n### State / Integrity / Concurrency Invariants\n\nNot applicable because none.\n\n### Observability / Validation Hooks\n\nNot applicable because none.\n\n## Technical Boundaries\n\nbounds\n\n## Validation Expectations\n\nvalidate\n\n## Open Questions\n\n- none\n", encoding="utf-8")
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] Example\n", encoding="utf-8")
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="task+spec+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="approved")
            MODULE.refresh_planning_turn_context_manifest(run_dir, task_root, turn_one)
            (task_root / MODULE.CONTRACT_FILENAME).write_text("# Definition of Done\n\n- [ ] Example changed\n", encoding="utf-8")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id="plan-run",
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            with self.assertRaises(SystemExit) as ctx:
                MODULE.prepare_run(args)
            self.assertIn("canonical docs changed since that approval", str(ctx.exception))

    def test_prepare_run_resume_path_writes_diagnostics_on_runtime_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id=None,
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            error = MODULE.SupervisorRuntimeError("planner_session_ready", "boom", role="planner")
            with mock.patch.object(MODULE, "ensure_active_role_sessions_ready", side_effect=error):
                result = MODULE.prepare_run(args)
            self.assertEqual(result, 1)
            diagnostics_root = run_dir / "diagnostics"
            self.assertTrue(diagnostics_root.exists())
            failure_dirs = [path for path in diagnostics_root.iterdir() if path.is_dir()]
            self.assertTrue(failure_dirs)
            self.assertTrue((failure_dirs[0] / "error.json").exists())
            persisted_state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(persisted_state["status"], "blocked")
            events_text = MODULE.events_path_for(run_dir).read_text(encoding="utf-8")
            self.assertIn("\"event\": \"blocked\"", events_text)

    def test_prepare_run_resumes_same_turn_intent_critic_pending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            MODULE.write_prompt_artifact(turn_one, "intent_critic", "critic prompt")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=tmp_dir,
                allow_non_git=True,
                intent=None,
                intent_file=None,
                hard=False,
                run_id=None,
                planner_session=None,
                critic_session=None,
                new_run=False,
            )
            captured: dict[str, object] = {}

            def fake_planning_loop_from(run_dir_arg, state_arg, task_root_arg, **kwargs):
                captured["run_dir"] = run_dir_arg
                captured["state_status"] = state_arg["status"]
                captured["kwargs"] = kwargs

            with mock.patch.object(MODULE, "ensure_active_role_sessions_ready", return_value=None), mock.patch.object(
                MODULE,
                "planning_loop_from",
                side_effect=fake_planning_loop_from,
            ), contextlib.redirect_stdout(io.StringIO()):
                result = MODULE.prepare_run(args)
            self.assertEqual(result, 0)
            self.assertEqual(Path(captured["run_dir"]).resolve(), run_dir.resolve())
            self.assertEqual(captured["state_status"], "waiting_intent_critic")
            self.assertEqual(captured["kwargs"]["start_turn"], 1)
            self.assertEqual(captured["kwargs"]["start_role"], "intent_critic")
            self.assertTrue(captured["kwargs"]["reuse_existing_turn_for_first"])

    def test_planning_loop_resume_respects_absolute_max_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (run_dir / "turns").mkdir(parents=True)
            config = self.build_council_config()
            config["planning"]["max_turns"] = 4
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=config,
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(run_dir, state)
            MODULE.write_text(run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            MODULE.prepare_planning_turn(run_dir, 2, task_root)

            def planner_side_effect(_run_dir, mutated_state, _task_root, turn_number, turn_dir, **_kwargs):
                mutated_state["current_turn"] = turn_number
                mutated_state["pending_turn"] = None
                mutated_state["pending_role"] = None
                mutated_state["transition_source_verdict"] = None
                mutated_state["status"] = "waiting_planner"
                MODULE.write_prompt_artifact(turn_dir, "planner", "planner prompt")
                MODULE.save_run_state(run_dir, mutated_state)
                return {"result": "drafted", "summary": "drafted", "docs_updated": []}

            with mock.patch.object(MODULE, "run_planner_phase", side_effect=planner_side_effect), mock.patch.object(
                MODULE,
                "run_intent_critic_phase",
                return_value={
                    "verdict": "changes_requested",
                    "summary": "more work",
                    "blocking_issues": ["gap"],
                    "critical_dimensions": {key: "fail" for key in MODULE.planning_review_dimension_keys()},
                    "human_message": None,
                    "human_source": None,
                },
            ):
                MODULE.planning_loop_from(
                    run_dir,
                    state,
                    task_root,
                    start_turn=2,
                    start_role="planner",
                    reuse_existing_turn_for_first=True,
                )

            final_state = MODULE.load_json(run_dir / "state.json")
            self.assertEqual(final_state["status"], "max_turns_reached")
            self.assertFalse((run_dir / "turns" / "0005").exists())

    def test_start_run_ignores_in_progress_planning_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync.\n",
                encoding="utf-8",
            )
            planning_run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            (planning_run_dir / "turns").mkdir(parents=True)
            planning_state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="task+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            MODULE.save_run_state(planning_run_dir, planning_state)
            MODULE.write_text(planning_run_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(planning_run_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.commit_repo_changes(repo_root, message="prepare docs without approved planning run")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id=None,
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "build_review_bridge_state", return_value={"mode": "internal"}), mock.patch.object(
                MODULE,
                "run_supervisor_for_initialized_run",
                return_value=0,
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)

    def test_start_run_ignores_latest_blocked_planning_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync.\n- [ ] Required verification for the changed retry path is present and passing.\n",
                encoding="utf-8",
            )
            blocked_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "blocked-run"
            (blocked_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="blocked-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            state["created_at"] = "2026-04-18T12:00:00Z"
            MODULE.save_run_state(blocked_dir, state)
            MODULE.write_text(blocked_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(blocked_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="blocked")
            self.commit_repo_changes(repo_root, message="prepare docs with blocked planning run present")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id=None,
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "build_review_bridge_state", return_value={"mode": "internal"}), mock.patch.object(
                MODULE,
                "run_supervisor_for_initialized_run",
                return_value=0,
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)

    def test_start_run_ignores_latest_approved_planning_run_with_doc_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync.\n- [ ] Required verification for the changed retry path is present and passing.\n",
                encoding="utf-8",
            )
            approved_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "approved-run"
            (approved_dir / "turns").mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="approved-run",
                workspace_profile="task+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            state["created_at"] = "2026-04-18T12:00:00Z"
            MODULE.save_run_state(approved_dir, state)
            MODULE.write_text(approved_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(approved_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="approved")
            MODULE.refresh_planning_turn_context_manifest(approved_dir, task_root, turn_one)
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync after drift.\n- [ ] Required verification for the changed retry path is present and passing.\n",
                encoding="utf-8",
            )
            self.commit_repo_changes(repo_root, message="canonical docs drift after planning approval")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id=None,
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "build_review_bridge_state", return_value={"mode": "internal"}), mock.patch.object(
                MODULE,
                "run_supervisor_for_initialized_run",
                return_value=0,
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)

    def test_start_run_ignores_newest_planning_run_by_created_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync.\n",
                encoding="utf-8",
            )
            older_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "z-old"
            newer_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "a-new"
            (older_dir / "turns").mkdir(parents=True)
            (newer_dir / "turns").mkdir(parents=True)
            older_state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="z-old",
                workspace_profile="task+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session-old",
                critic_session="critic-session-old",
                hard_mode=False,
            )
            older_state["created_at"] = "2026-04-18T10:00:00Z"
            newer_state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="a-new",
                workspace_profile="task+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session-new",
                critic_session="critic-session-new",
                hard_mode=False,
            )
            newer_state["created_at"] = "2026-04-18T11:00:00Z"
            MODULE.save_run_state(older_dir, older_state)
            MODULE.save_run_state(newer_dir, newer_state)
            MODULE.write_text(older_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            MODULE.write_text(newer_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            older_turn = MODULE.prepare_planning_turn(older_dir, 1, task_root)
            self.write_planner_status(older_turn, result="drafted")
            self.write_intent_critic_status(older_turn, verdict="approved")
            MODULE.refresh_planning_turn_context_manifest(older_dir, task_root, older_turn)
            newer_turn = MODULE.prepare_planning_turn(newer_dir, 1, task_root)
            self.write_planner_status(newer_turn, result="drafted")
            self.commit_repo_changes(repo_root, message="execution docs are ready despite newer planning run")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id=None,
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "build_review_bridge_state", return_value={"mode": "internal"}), mock.patch.object(
                MODULE,
                "run_supervisor_for_initialized_run",
                return_value=0,
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)

    def test_start_run_allows_latest_approved_planning_run_without_doc_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir) / "repo"
            self.init_git_repo(repo_root)
            task_root = self.scaffold_base_workspace(repo_root)
            (task_root / MODULE.TASK_FILENAME).write_text(
                "# Task\n\n## Request\n\nFix the retry path so duplicate rows are not created during sync.\n\n## Context\n\nThe sync worker currently retries after a transient timeout and may write the same row twice.\n\n## Success Signal\n\nA retry no longer creates duplicate rows and the changed path is covered by verification.\n",
                encoding="utf-8",
            )
            (task_root / MODULE.CONTRACT_FILENAME).write_text(
                "# Definition of Done\n\n- [ ] The retry path no longer writes duplicate rows during sync.\n- [ ] Required verification for the changed retry path is present and passing.\n",
                encoding="utf-8",
            )
            approved_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "approved-run"
            (approved_dir / "turns").mkdir(parents=True)
            planning_state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="approved-run",
                workspace_profile="task+contract",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            planning_state["created_at"] = "2026-04-18T12:00:00Z"
            MODULE.save_run_state(approved_dir, planning_state)
            MODULE.write_text(approved_dir / MODULE.PLANNING_SOURCE_INTENT_FILENAME, "# Source Intent\n")
            turn_one = MODULE.prepare_planning_turn(approved_dir, 1, task_root)
            self.write_planner_status(turn_one, result="drafted")
            self.write_intent_critic_status(turn_one, verdict="approved")
            MODULE.refresh_planning_turn_context_manifest(approved_dir, task_root, turn_one)
            self.commit_repo_changes(repo_root, message="prepare planning docs")
            args = argparse.Namespace(
                task_name="demo-task",
                dir=str(repo_root),
                allow_non_git=False,
                run_id=None,
                generator_session=None,
                reviewer_session=None,
                fork_session_id=None,
                generator_fork_session_id=None,
                reviewer_fork_session_id=None,
                review_mode="internal",
                github_pr=None,
                github_branch=None,
                github_base=None,
                start_role="auto",
            )
            with mock.patch.object(MODULE, "build_review_bridge_state", return_value={"mode": "internal"}), mock.patch.object(
                MODULE,
                "run_supervisor_for_initialized_run",
                return_value=0,
            ):
                result = MODULE.start_run(args)
            self.assertEqual(result, 0)

    def test_write_failure_diagnostics_supports_planning_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            repo_root = Path(tmp_dir)
            task_root = self.scaffold_base_workspace(repo_root)
            run_dir = task_root / MODULE.PLANNING_RUNS_DIRNAME / "plan-run"
            run_dir.mkdir(parents=True)
            state = MODULE.create_planning_run_state(
                repo_root=repo_root,
                task_root=task_root,
                task_name="demo-task",
                run_id="plan-run",
                workspace_profile="undocumented",
                council_config=self.build_council_config(),
                planner_session="planner-session",
                critic_session="critic-session",
                hard_mode=False,
            )
            error = MODULE.SupervisorRuntimeError("intent_critic_turn", "boom", role="intent_critic")
            with mock.patch.object(MODULE, "tmux_capture_joined_pane", return_value="pane"):
                failure_dir = MODULE.write_failure_diagnostics(run_dir, state, error)
            self.assertTrue((failure_dir / "planner.pane.txt").exists())
            self.assertTrue((failure_dir / "intent_critic.pane.txt").exists())

    def test_consumer_docs_reference_canonical_cli_and_document_model(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        architecture = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
        instructs = (repo_root / "INSTRUCTS.md").read_text(encoding="utf-8")
        skill = (repo_root / "skills" / "codex-council" / "SKILL.md").read_text(encoding="utf-8")
        run_lifecycle = (repo_root / "skills" / "codex-council" / "references" / "run-lifecycle.md").read_text(encoding="utf-8")
        failure_recovery = (repo_root / "skills" / "codex-council" / "references" / "failure-recovery.md").read_text(encoding="utf-8")
        routing = (repo_root / "skills" / "codex-council" / "references" / "routing.md").read_text(encoding="utf-8")

        for command in ("init", "write", "prepare", "start", "continue", "reopen", "status"):
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
        self.assertIn("planner / intent critic planning loop", architecture)
        self.assertIn("## Planning Stage", readme)
        self.assertIn("## Planning Stage", instructs)
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
        self.assertIn("`prepare`", skill)
        self.assertIn("--planning", run_lifecycle)
        self.assertIn("`prepare`", routing)
        self.assertIn("`prepare`", failure_recovery)
        self.assertIn("Decision-Complete Specs", instructs)
        self.assertIn("hard` mode", readme)
        self.assertIn("hard` mode", instructs)
        self.assertIn("false_approved", readme)
        self.assertIn("requirements_changed_after_approval", readme)
        self.assertIn("false_approved", instructs)
        self.assertIn("requirements_changed_after_approval", instructs)
        self.assertIn("`reopen`", skill)
        self.assertIn("planning stage", skill)
        self.assertIn("false_approved", run_lifecycle)
        self.assertIn("requirements_changed_after_approval", run_lifecycle)
        self.assertIn("`reopen`", failure_recovery)
        self.assertIn("`reopen`", routing)

    def test_consumer_docs_describe_internal_outer_review_loop(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        readme = (repo_root / "README.md").read_text(encoding="utf-8")
        architecture = (repo_root / "ARCHITECTURE.md").read_text(encoding="utf-8")
        instructs = (repo_root / "INSTRUCTS.md").read_text(encoding="utf-8")
        skill = (repo_root / "skills" / "codex-council" / "SKILL.md").read_text(encoding="utf-8")
        run_lifecycle = (repo_root / "skills" / "codex-council" / "references" / "run-lifecycle.md").read_text(encoding="utf-8")
        failure_recovery = (repo_root / "skills" / "codex-council" / "references" / "failure-recovery.md").read_text(encoding="utf-8")
        routing = (repo_root / "skills" / "codex-council" / "references" / "routing.md").read_text(encoding="utf-8")

        for text in (readme, instructs, run_lifecycle):
            self.assertIn("--outer-review-session-id", text)
            self.assertIn("resumable Codex session id", text)
            self.assertIn("closed_no_remaining_outer_findings", text)
            self.assertIn("triage-only", text)

        self.assertIn("outer-review finalization", failure_recovery)
        self.assertIn("false_approved", routing)
        self.assertIn("outer review", skill.lower())
        self.assertIn("outer-review handoff", architecture.lower())

    def test_codex_council_skill_reference_pack_is_present_and_linked(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        skill_root = repo_root / "skills" / "codex-council"
        skill_path = skill_root / "SKILL.md"
        self.assertTrue(skill_path.exists())
        skill_text = skill_path.read_text(encoding="utf-8")

        expected_refs = (
            "references/routing.md",
            "references/novice-normalization.md",
            "references/planning-stage.md",
            "references/planner-authoring.md",
            "references/intent-critic.md",
            "references/hard-mode.md",
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
        self.assertIn("planning stage", skill_text)

    def test_scaffold_templates_and_role_instructions_emphasize_brief_quality(self) -> None:
        repo_root = MODULE_PATH.parents[1]
        task_template = (repo_root / "templates" / "scaffold" / "task.md").read_text(encoding="utf-8")
        review_template = (repo_root / "templates" / "scaffold" / "review.md").read_text(encoding="utf-8")
        spec_template = (repo_root / "templates" / "scaffold" / "spec.md").read_text(encoding="utf-8")
        contract_template = (repo_root / "templates" / "scaffold" / "contract.md").read_text(encoding="utf-8")
        planner_instructions = (repo_root / "templates" / "scaffold" / "planner.instructions.md").read_text(encoding="utf-8")
        intent_critic_instructions = (repo_root / "templates" / "scaffold" / "intent_critic.instructions.md").read_text(encoding="utf-8")
        generator_instructions = (repo_root / "templates" / "scaffold" / "generator.instructions.md").read_text(encoding="utf-8")
        reviewer_instructions = (repo_root / "templates" / "scaffold" / "reviewer.instructions.md").read_text(encoding="utf-8")
        linking_example = (repo_root / "skills" / "codex-council" / "references" / "spec-contract-linking-example.md").read_text(encoding="utf-8")

        self.assertIn("default starting point for most execution requests", task_template)
        self.assertIn("pair this file with `contract.md`", review_template)
        self.assertIn("pair this file with `contract.md`", task_template)
        self.assertIn("planning stage", task_template)
        self.assertIn("deeper structure than `task.md`", spec_template)
        self.assertIn("keep `contract.md` alongside this file", spec_template)
        self.assertIn("planning-stage `hard` mode", spec_template)
        self.assertIn("named major sections", spec_template)
        self.assertIn("acceptance criteria for that slice", spec_template)
        self.assertIn("spec-contract-linking-example.md", spec_template)
        self.assertIn("### Source of Truth / Ownership", spec_template)
        self.assertIn("Not applicable because", spec_template)
        self.assertIn("default acceptance and approval checklist", contract_template)
        self.assertIn("Skip it only for ultra-trivial tasks", contract_template)
        self.assertIn("regression / integrity / fallback / state guardrail", contract_template)
        self.assertIn("prompts, instructions, tools, schemas", contract_template)
        self.assertIn("approval projection of `spec.md`", contract_template)
        self.assertIn("prove it on the real path", contract_template)
        self.assertIn("traceable to a named spec section", contract_template)
        self.assertIn("spec-contract-linking-example.md", contract_template)
        self.assertIn("decision-complete spec", planner_instructions)
        self.assertIn("tool descriptions, tool schemas", planner_instructions)
        self.assertIn("execution-safe", planner_instructions)
        self.assertIn("derive `contract.md` from every major spec section in that spec", planner_instructions)
        self.assertIn("reviewer-usable falsification hook", planner_instructions)
        self.assertIn("local fix to one slice cannot be mistaken for whole-task approval", planner_instructions)
        self.assertIn("already-satisfied contract items can become unsatisfied again", planner_instructions)
        self.assertIn("spec-contract-linking-example.md", planner_instructions)
        self.assertIn("strict external evaluator", intent_critic_instructions)
        self.assertIn("hidden assumptions presented as facts", intent_critic_instructions)
        self.assertIn("toy-like prompt / tool / schema descriptions", intent_critic_instructions)
        self.assertIn("helper-only validation guidance", intent_critic_instructions)
        self.assertIn("execution scope that is narrower than the approval scope", intent_critic_instructions)
        self.assertIn("helper, background, repair, or maintenance paths", intent_critic_instructions)
        self.assertIn("checked items feel settled", intent_critic_instructions)
        self.assertIn("re-audit and re-uncheck behavior explicit", intent_critic_instructions)
        self.assertIn("Reject docs that would let an execution reviewer focus only on the latest local fix", intent_critic_instructions)
        self.assertIn("spec-to-contract traceability", intent_critic_instructions)
        self.assertIn("spec-contract-linking-example.md", intent_critic_instructions)
        self.assertIn("do not compensate by inventing missing requirements", generator_instructions)
        self.assertIn("prompt, system-instruction, tool-description, and schema contracts", generator_instructions)
        self.assertIn("tests, fixtures, docs, or a helper seam", generator_instructions)
        self.assertIn("What remains unproven or only indirectly proven after this turn", generator_instructions)
        self.assertIn("Do not frame a narrow turn as if it resolved the whole task", generator_instructions)
        self.assertIn("adjacent review surfaces still need reviewer re-audit", generator_instructions)
        self.assertIn("starting fix queue, not as the whole review boundary", generator_instructions)
        self.assertIn("latest blocker or the latest unchecked contract item is enough for approval", generator_instructions)
        self.assertIn("vague or aspirational `contract.md` items", reviewer_instructions)
        self.assertIn("actively try to falsify the generator's framing", reviewer_instructions)
        self.assertIn("tests-only, docs-only, fixture-only, or council-artifact-only changes", reviewer_instructions)
        self.assertIn("fresh, deep, complete audit of the current branch state", reviewer_instructions)
        self.assertIn("Approval is whole-task and whole-branch", reviewer_instructions)
        self.assertIn("local fix to one surface never implies whole-task approval", reviewer_instructions)
        self.assertIn("latest generator message, the generator summary, and the previous reviewer finding list as context only", reviewer_instructions)
        self.assertIn("Revisit every approval-critical contract item every turn", reviewer_instructions)
        self.assertIn("Previously checked items are not trusted by default", reviewer_instructions)
        self.assertIn("Approval is invalid if you have only rechecked the latest local fix", reviewer_instructions)
        self.assertIn("latest open blocker or only the currently unchecked contract items", reviewer_instructions)
        self.assertIn("What remains unproven after this turn", reviewer_instructions)
        self.assertIn("Evidence Basis for Approval-Critical Claims", reviewer_instructions)
        self.assertIn("decision-complete", generator_instructions)
        self.assertIn("missing implementation-critical decisions", reviewer_instructions)
        self.assertIn("Passing tests or a satisfied-looking contract are not enough for approval", reviewer_instructions)
        self.assertIn("weak planning-authored docs", reviewer_instructions)
        self.assertIn("approval projection of that truth", reviewer_instructions)
        self.assertIn("spec-contract-linking-example.md", reviewer_instructions)
        self.assertIn("Code paths inspected", reviewer_instructions)
        self.assertIn("disconfirming or adversarial check", spec_template)
        self.assertIn("exercise the real path", spec_template)
        self.assertIn("## Core rule", linking_example)
        self.assertIn("## Good `spec.md` shape", linking_example)
        self.assertIn("## Good `contract.md` shape", linking_example)
        self.assertIn("## Regression example", linking_example)

        scaffold_example = (repo_root / "templates" / "scaffold" / "spec-contract-linking-example.md").read_text(encoding="utf-8")
        self.assertIn("## Good `spec.md` shape", scaffold_example)
        self.assertIn("## Good `contract.md` shape", scaffold_example)


if __name__ == "__main__":
    unittest.main()
