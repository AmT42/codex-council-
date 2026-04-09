from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_tui_supervisor.py"
SPEC = importlib.util.spec_from_file_location("codex_tui_supervisor", MODULE_PATH)
assert SPEC is not None
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CodexTuiSupervisorTests(unittest.TestCase):
    def test_validate_generator_status_accepts_valid_payload(self) -> None:
        status = MODULE.validate_generator_status(
            {
                "result": "implemented",
                "summary": "Changed the parser and added tests.",
                "changed_files": ["src/parser.py", "tests/test_parser.py"],
                "commit_sha": "abc123",
                "compare_base_sha": "def456",
                "branch": "main",
            }
        )
        self.assertEqual(status["result"], "implemented")
        self.assertEqual(len(status["changed_files"]), 2)

    def test_validate_generator_status_requires_commit_metadata_for_implemented(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_generator_status(
                {
                    "result": "implemented",
                    "summary": "Changed the parser and added tests.",
                    "changed_files": ["src/parser.py"],
                }
            )

    def test_validate_reviewer_status_accepts_approved(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "approved",
                "summary": "No blocking issues remain.",
                "blocking_issues": [],
                "reviewed_commit_sha": "abc123",
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

    def test_validate_reviewer_status_requires_reviewed_commit_for_approved(self) -> None:
        with self.assertRaises(ValueError):
            MODULE.validate_reviewer_status(
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
            self.assertTrue((repo_root / ".codex-council" / "config.toml").exists())
            self.assertTrue((repo_root / ".codex-council" / ".gitignore").exists())
            self.assertTrue((task_root / "task.md").exists())
            self.assertTrue((task_root / "contract.md").exists())
            self.assertTrue((task_root / "AGENTS.md").exists())
            self.assertTrue((task_root / "generator.instructions.md").exists())
            self.assertTrue((task_root / "reviewer.instructions.md").exists())

    def test_scaffold_task_root_marks_placeholder_when_no_task_seed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            result = MODULE.scaffold_task_root(task_root, initial_task_text=None)
            self.assertTrue(result["task_created"])
            self.assertTrue(result["task_needs_edit"])

    def test_missing_task_files_reports_expected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            task_root.mkdir(parents=True)
            missing = MODULE.missing_task_files(task_root)
            self.assertEqual(len(missing), 5)
            self.assertTrue(any(path.name == "task.md" for path in missing))
            self.assertTrue(any(path.name == "contract.md" for path in missing))

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

    def test_prepare_turn_snapshots_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = Path(tmp_dir) / "task" / "runs" / "run-1"
            materials = {
                "task_text": "Do the task.",
                "contract_text": "- [ ] Done",
                "agents_text": "Shared rules.",
                "generator_text": "Generator rules.",
                "reviewer_text": "Reviewer rules.",
            }
            turn_dir = MODULE.prepare_turn(run_dir, 1, materials)
            self.assertEqual((turn_dir / "inputs" / "task.md").read_text(encoding="utf-8").strip(), "Do the task.")
            self.assertEqual((turn_dir / "inputs" / "contract.md").read_text(encoding="utf-8").strip(), "- [ ] Done")
            self.assertEqual((turn_dir / "inputs" / "AGENTS.md").read_text(encoding="utf-8").strip(), "Shared rules.")

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
                {"enabled": False},
                inline_context=True,
            )
            self.assertIn("Shared rules.", prompt)
            self.assertIn("Generator additions.", prompt)
            self.assertIn("Implement feature.", prompt)
            self.assertIn("Contract item", prompt)
            self.assertNotIn("supervisor controls turn order", prompt.lower())
            self.assertIn("needs_human", prompt)
            self.assertNotIn("stop and wait for further instructions", prompt.lower())
            self.assertIn("Why those changes move the code toward satisfying `contract.md`", prompt)
            self.assertIn("Changed invariants / preserved invariants", prompt)
            self.assertIn("Downstream readers / consumers checked", prompt)
            self.assertIn("Failure modes and fallback behavior considered", prompt)
            self.assertIn("Verification performed", prompt)

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
            (previous_turn_dir / "reviewer.md").write_text("Review text", encoding="utf-8")
            (previous_turn_dir / "reviewer.status.json").write_text("{}", encoding="utf-8")
            prompt = MODULE.build_generator_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                2,
                "demo-task",
                {"enabled": False},
                inline_context=False,
            )
            self.assertIn(str(task_root / "task.md"), prompt)
            self.assertIn(str(task_root / "contract.md"), prompt)
            self.assertNotIn("Shared rules.", prompt)
            self.assertNotIn("Generator additions.", prompt)

    def test_build_reviewer_turn_prompt_mentions_changes_requested_and_needs_human(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            task_root = Path(tmp_dir) / ".codex-council" / "demo-task"
            turn_dir = Path(tmp_dir) / "turns" / "0001"
            task_root.mkdir(parents=True)
            (task_root / "task.md").write_text("Implement feature.", encoding="utf-8")
            (task_root / "contract.md").write_text("- [ ] Contract item", encoding="utf-8")
            (task_root / "AGENTS.md").write_text("Shared rules.", encoding="utf-8")
            (task_root / "reviewer.instructions.md").write_text("Reviewer additions.", encoding="utf-8")
            prompt = MODULE.build_reviewer_turn_prompt(
                Path("/repo"),
                task_root,
                turn_dir,
                1,
                {"enabled": True},
                inline_context=True,
            )
            self.assertIn("Reviewer additions.", prompt)
            self.assertIn("changes_requested", prompt)
            self.assertIn("needs_human", prompt)
            self.assertIn("Use git as the primary source of what changed.", prompt)
            self.assertIn("contract.md", prompt)
            self.assertIn("Contract checklist copied from `contract.md`", prompt)
            self.assertIn("Critical review dimensions", prompt)
            self.assertIn("[pass]", prompt)
            self.assertIn("[fail]", prompt)
            self.assertIn("[uncertain]", prompt)
            self.assertIn("inspect both the writers and the downstream readers/consumers", prompt)
            self.assertIn("independent falsification or negative-path check", prompt)

    def test_wait_for_role_artifacts_returns_valid_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            turn_dir = Path(tmp_dir)
            (turn_dir / "generator.md").write_text("Implemented.", encoding="utf-8")
            (turn_dir / "generator.status.json").write_text(
                json.dumps(
                    {
                        "result": "implemented",
                        "summary": "Added feature.",
                        "changed_files": ["scripts/feature.py"],
                        "commit_sha": "abc123",
                        "compare_base_sha": "def456",
                        "branch": "main",
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
            )
            self.assertEqual(artifact_path.name, "generator.md")
            self.assertEqual(status_path.name, "generator.status.json")
            self.assertEqual(status["result"], "implemented")

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


if __name__ == "__main__":
    unittest.main()
