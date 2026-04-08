from __future__ import annotations

import importlib.util
import json
from pathlib import Path
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


def write_session_file(
    session_root: Path,
    *,
    filename: str,
    session_id: str,
    cwd: str,
    originator: str,
    user_message: str,
) -> Path:
    path = session_root / filename
    records = [
        {
            "timestamp": "2026-04-08T11:50:02.052Z",
            "type": "session_meta",
            "payload": {
                "cwd": cwd,
                "id": session_id,
                "originator": originator,
            },
        },
        {
            "timestamp": "2026-04-08T11:50:02.053Z",
            "type": "event_msg",
            "payload": {
                "type": "user_message",
                "message": user_message,
            },
        },
        {
            "timestamp": "2026-04-08T11:50:10.807Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "last_agent_message": "Ready.",
            },
        },
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


class CodexTuiSupervisorTests(unittest.TestCase):
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

    def test_validate_reviewer_status_accepts_approved(self) -> None:
        status = MODULE.validate_reviewer_status(
            {
                "verdict": "approved",
                "summary": "No blocking issues remain.",
                "blocking_issues": [],
            }
        )
        self.assertEqual(status["verdict"], "approved")

    def test_build_turn_task_mentions_iteration_after_first_turn(self) -> None:
        text = MODULE.build_turn_task("Implement feature X.", 2)
        self.assertIn("Implement feature X.", text)
        self.assertIn("iteration 2", text)

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

    def test_find_matching_new_tui_session_file_uses_prompt_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_root = Path(tmp_dir)
            workspace_root = Path("/repo")
            marker = MODULE.build_turn_marker("20260408-abc123", "generator", 1)

            ignored = write_session_file(
                session_root,
                filename="old.jsonl",
                session_id="old-session",
                cwd=str(workspace_root),
                originator="codex-tui",
                user_message="old prompt",
            )
            matching = write_session_file(
                session_root,
                filename="new.jsonl",
                session_id="new-session",
                cwd=str(workspace_root),
                originator="codex-tui",
                user_message=marker,
            )

            match, candidates = MODULE.find_matching_new_tui_session_file(
                session_root=session_root,
                known_files={ignored},
                workspace_root=workspace_root,
                prompt_marker=marker,
            )

            self.assertIsNotNone(match)
            assert match is not None
            self.assertEqual(match.thread_id, "new-session")
            self.assertEqual(match.session_file, matching)
            self.assertEqual(candidates, [])

    def test_find_matching_new_tui_session_file_rejects_wrong_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            session_root = Path(tmp_dir)
            workspace_root = Path("/repo")
            marker = MODULE.build_turn_marker("20260408-abc123", "reviewer", 1)

            wrong_cwd = write_session_file(
                session_root,
                filename="wrong.jsonl",
                session_id="wrong-session",
                cwd="/other-repo",
                originator="codex-tui",
                user_message=marker,
            )

            match, candidates = MODULE.find_matching_new_tui_session_file(
                session_root=session_root,
                known_files=set(),
                workspace_root=workspace_root,
                prompt_marker=marker,
            )

            self.assertIsNone(match)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]["session_file"], str(wrong_cwd))

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
                    }
                ),
                encoding="utf-8",
            )

            artifact_path, status_path, status = MODULE.wait_for_role_artifacts(
                turn_dir,
                "generator",
                validator=MODULE.validate_generator_status,
                timeout_seconds=1.0,
                phase="generator_artifacts",
            )
            self.assertEqual(artifact_path.name, "generator.md")
            self.assertEqual(status_path.name, "generator.status.json")
            self.assertEqual(status["result"], "implemented")

    def test_create_run_state_tracks_role_session_fields(self) -> None:
        state = MODULE.create_run_state(
            run_id="20260408-abc123",
            run_dir=Path("/repo/harness/runs/20260408-abc123"),
            workspace_root=Path("/repo"),
            max_turns=6,
            turn_timeout_seconds=1800.0,
            launch_timeout_seconds=60.0,
            generator_session="gen",
            reviewer_session="rev",
        )
        self.assertEqual(state["status"], "booting")
        self.assertIn("diagnostics_dir", state)
        self.assertIsNone(state["roles"]["generator"]["codex_thread_id"])
        self.assertIsNone(state["roles"]["reviewer"]["session_file"])


if __name__ == "__main__":
    unittest.main()
