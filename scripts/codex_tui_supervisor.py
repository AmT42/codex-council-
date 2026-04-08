#!/usr/bin/env python3

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import subprocess
import tempfile
import textwrap
import time
import uuid


RUNS_ROOT = Path("harness/runs")
SESSION_ROOT = Path.home() / ".codex" / "sessions"
GENERATOR_RESULTS = {"implemented", "no_changes_needed", "blocked"}
REVIEWER_VERDICTS = {"approved", "changes_requested", "blocked"}
TMUX_PANE_POLL_SECONDS = 0.5
TMUX_PASTE_SETTLE_SECONDS = 0.1
TMUX_CAPTURE_HISTORY_LINES = 1000
SESSION_POLL_SECONDS = 0.5


@dataclass
class SessionSummary:
    session_file: Path
    thread_id: str | None
    cwd: str | None
    originator: str | None
    first_user_message: str


class SupervisorRuntimeError(RuntimeError):
    def __init__(
        self,
        phase: str,
        message: str,
        *,
        role: str | None = None,
        details: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.role = role
        self.details = details or {}


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_json(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        tmp_name = fh.name
    Path(tmp_name).replace(path)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_text_arg(value: str | None, file_path: str | None, default: str = "") -> str:
    if value and file_path:
        raise SystemExit("pass either a literal value or a file, not both")
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise SystemExit(f"missing file: {file_path}")
        return path.read_text(encoding="utf-8")
    if value is not None:
        return value
    return default


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def run_subprocess(
    args: list[str], *, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
        text=True,
        capture_output=True,
        input=input_text,
    )


def tmux_session_exists(name: str) -> bool:
    proc = subprocess.run(
        ["tmux", "has-session", "-t", name],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0


def tmux_new_session(name: str, workspace_root: Path, *, role: str) -> None:
    if tmux_session_exists(name):
        raise SystemExit(f"tmux session already exists: {name}")
    try:
        run_subprocess(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                name,
                "-c",
                str(workspace_root),
                "codex --no-alt-screen",
            ]
        )
    except subprocess.CalledProcessError as exc:
        raise SupervisorRuntimeError(
            "tmux_session_start",
            f"failed to create tmux session {name}: {exc.stderr.strip() or exc}",
            role=role,
            details={
                "command": exc.cmd,
                "stderr": exc.stderr,
                "stdout": exc.stdout,
            },
        ) from exc


def tmux_capture_pane(name: str) -> str:
    proc = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", name],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return f"[capture failed for {name}]\n{proc.stderr.strip()}\n"
    return proc.stdout


def tmux_capture_joined_pane(name: str, history_lines: int = TMUX_CAPTURE_HISTORY_LINES) -> str:
    proc = subprocess.run(
        ["tmux", "capture-pane", "-pJ", "-S", f"-{history_lines}", "-t", name],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return f"[capture failed for {name}]\n{proc.stderr.strip()}\n"
    return proc.stdout


def extract_last_tmux_slice(pane_text: str) -> str:
    lines = pane_text.splitlines()
    prompt_lines = [idx for idx, line in enumerate(lines) if line.lstrip().startswith("› ")]
    if len(prompt_lines) >= 2:
        start = prompt_lines[-2] + 1
        end = prompt_lines[-1]
    elif len(prompt_lines) == 1:
        start = prompt_lines[-1] + 1
        end = len(lines)
    else:
        start = 0
        end = len(lines)

    snippet = lines[start:end]
    while snippet and not snippet[0].strip():
        snippet.pop(0)
    while snippet and not snippet[-1].strip():
        snippet.pop()
    return "\n".join(snippet).rstrip() + ("\n" if snippet else "")


def capture_last_tmux_slice(name: str) -> str:
    return extract_last_tmux_slice(tmux_capture_joined_pane(name))


def pane_shows_prompt(pane_text: str) -> bool:
    lines = [line.rstrip() for line in pane_text.splitlines() if line.strip()]
    for line in lines[-20:]:
        if line.lstrip().startswith("›"):
            return True
    return False


def wait_for_tmux_prompt(
    tmux_name: str, timeout_seconds: float, *, phase: str, role: str
) -> None:
    deadline = time.time() + timeout_seconds
    last_pane = ""
    while time.time() < deadline:
        if not tmux_session_exists(tmux_name):
            raise SupervisorRuntimeError(
                phase,
                f"tmux session disappeared: {tmux_name}",
                role=role,
            )
        last_pane = tmux_capture_pane(tmux_name)
        if pane_shows_prompt(last_pane):
            return
        time.sleep(TMUX_PANE_POLL_SECONDS)
    raise SupervisorRuntimeError(
        phase,
        f"timed out waiting for Codex prompt in tmux session {tmux_name}",
        role=role,
        details={"pane_excerpt": last_pane[-4000:]},
    )


def tmux_send_prompt(tmux_name: str, prompt: str, *, phase: str, role: str) -> None:
    buffer_name = f"codex-supervisor-{uuid.uuid4().hex}"
    try:
        try:
            run_subprocess(
                ["tmux", "load-buffer", "-b", buffer_name, "-"],
                input_text=prompt,
            )
            run_subprocess(
                ["tmux", "paste-buffer", "-d", "-b", buffer_name, "-t", tmux_name]
            )
            time.sleep(TMUX_PASTE_SETTLE_SECONDS)
            run_subprocess(["tmux", "send-keys", "-t", tmux_name, "Enter"])
        except subprocess.CalledProcessError as exc:
            raise SupervisorRuntimeError(
                phase,
                f"failed to send prompt to tmux session {tmux_name}: {exc.stderr.strip() or exc}",
                role=role,
                details={
                    "command": exc.cmd,
                    "stderr": exc.stderr,
                    "stdout": exc.stdout,
                    "tmux_session": tmux_name,
                },
            ) from exc
    finally:
        subprocess.run(
            ["tmux", "delete-buffer", "-b", buffer_name],
            text=True,
            capture_output=True,
        )


def list_session_files(session_root: Path = SESSION_ROOT) -> list[Path]:
    if not session_root.exists():
        return []
    return sorted(session_root.rglob("*.jsonl"))


def extract_user_message_from_response_item(payload: dict) -> str:
    if payload.get("type") != "message" or payload.get("role") != "user":
        return ""
    texts: list[str] = []
    for item in payload.get("content", []):
        if item.get("type") == "input_text":
            texts.append(item.get("text", ""))
    return "\n".join(texts).strip()


def read_session_summary(session_file: Path) -> SessionSummary:
    thread_id = None
    cwd = None
    originator = None
    first_user_message = ""
    for line in session_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        record_type = record.get("type")
        payload = record.get("payload", {})
        if record_type == "session_meta" and thread_id is None:
            thread_id = payload.get("id")
            cwd = payload.get("cwd")
            originator = payload.get("originator")
        elif record_type == "event_msg" and payload.get("type") == "user_message":
            first_user_message = payload.get("message", "").strip()
            break
        elif record_type == "response_item":
            candidate = extract_user_message_from_response_item(payload)
            if candidate:
                first_user_message = candidate
                break
    return SessionSummary(
        session_file=session_file,
        thread_id=thread_id,
        cwd=cwd,
        originator=originator,
        first_user_message=first_user_message,
    )


def build_turn_marker(run_id: str, role: str, turn_number: int) -> str:
    return f"SUPERVISOR_TURN_MARKER run_id={run_id} role={role} turn={turn_name(turn_number)}"


def summarize_session_candidate(summary: SessionSummary) -> dict:
    return {
        "session_file": str(summary.session_file),
        "thread_id": summary.thread_id,
        "cwd": summary.cwd,
        "originator": summary.originator,
        "first_user_message_excerpt": summary.first_user_message[:400],
    }


def session_matches_prompt_marker(
    summary: SessionSummary,
    *,
    workspace_root: Path,
    prompt_marker: str,
) -> bool:
    if not summary.thread_id:
        return False
    if summary.cwd != str(workspace_root):
        return False
    if summary.originator != "codex-tui":
        return False
    if prompt_marker not in summary.first_user_message:
        return False
    return True


def find_matching_new_tui_session_file(
    *,
    session_root: Path,
    known_files: set[Path],
    workspace_root: Path,
    prompt_marker: str,
) -> tuple[SessionSummary | None, list[dict]]:
    candidates: list[dict] = []
    for session_file in list_session_files(session_root):
        if session_file in known_files:
            continue
        summary = read_session_summary(session_file)
        if session_matches_prompt_marker(
            summary,
            workspace_root=workspace_root,
            prompt_marker=prompt_marker,
        ):
            return summary, candidates
        candidates.append(summarize_session_candidate(summary))
    return None, candidates


def wait_for_new_tui_session_file(
    *,
    session_root: Path,
    known_files: set[Path],
    workspace_root: Path,
    prompt_marker: str,
    timeout_seconds: float,
    phase: str,
    role: str,
) -> SessionSummary:
    deadline = time.time() + timeout_seconds
    seen_candidates: dict[str, dict] = {}
    while time.time() < deadline:
        match, candidates = find_matching_new_tui_session_file(
            session_root=session_root,
            known_files=known_files,
            workspace_root=workspace_root,
            prompt_marker=prompt_marker,
        )
        for candidate in candidates:
            seen_candidates[candidate["session_file"]] = candidate
        if match is not None:
            return match
        time.sleep(SESSION_POLL_SECONDS)
    raise SupervisorRuntimeError(
        phase,
        f"timed out waiting for a new Codex TUI session file for {role}",
        role=role,
        details={"session_candidates": list(seen_candidates.values())},
    )


def task_complete_events(session_file: Path) -> list[dict]:
    events: list[dict] = []
    for line in session_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("type") != "event_msg":
            continue
        payload = record.get("payload", {})
        if payload.get("type") == "task_complete":
            events.append(payload)
    return events


def wait_for_task_complete_count(
    session_file: Path,
    previous_count: int,
    timeout_seconds: float,
    *,
    phase: str,
    role: str,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        events = task_complete_events(session_file)
        if len(events) > previous_count:
            return events[-1]
        time.sleep(1.0)
    raise SupervisorRuntimeError(
        phase,
        f"timed out waiting for task completion in {session_file}",
        role=role,
        details={"session_file": str(session_file), "previous_count": previous_count},
    )


def require_string(value, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def require_string_list(value, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be a list of strings")
    return [item.strip() for item in value]


def validate_generator_status(data: dict) -> dict:
    result = require_string(data.get("result"), "result")
    if result not in GENERATOR_RESULTS:
        raise ValueError(f"invalid generator result: {result}")
    summary = require_string(data.get("summary"), "summary")
    changed_files = require_string_list(data.get("changed_files", []), "changed_files")
    return {
        "result": result,
        "summary": summary,
        "changed_files": changed_files,
    }


def validate_reviewer_status(data: dict) -> dict:
    verdict = require_string(data.get("verdict"), "verdict")
    if verdict not in REVIEWER_VERDICTS:
        raise ValueError(f"invalid reviewer verdict: {verdict}")
    summary = require_string(data.get("summary"), "summary")
    blocking_issues = require_string_list(
        data.get("blocking_issues", []), "blocking_issues"
    )
    return {
        "verdict": verdict,
        "summary": summary,
        "blocking_issues": blocking_issues,
    }


def turn_name(turn_number: int) -> str:
    return f"{turn_number:04d}"


def turn_dir(run_dir: Path, turn_number: int) -> Path:
    return run_dir / "turns" / turn_name(turn_number)


def build_turn_task(original_task: str, turn_number: int) -> str:
    if turn_number == 1:
        return original_task.rstrip()
    return textwrap.dedent(
        f"""\
        Original task:

        {original_task.rstrip()}

        This is iteration {turn_number}. Address the reviewer feedback from the previous turn before doing anything else.
        """
    ).rstrip()


def build_generator_protocol(run_dir: Path, base_prompt: str) -> str:
    return textwrap.dedent(
        f"""\
        You are the generator in a two-agent Codex workflow.

        Collaboration root:
        {run_dir}

        Protocol:
        - The supervisor controls turn order. Do not poll or loop on your own.
        - Only act when the supervisor sends you a turn message in this Codex session.
        - You are the only agent allowed to modify source files.
        - For each turn N, write:
          - {run_dir}/turns/NNNN/generator.md
          - {run_dir}/turns/NNNN/generator.status.json
        - The status file must be valid JSON with exactly this shape:
          {{"result":"implemented|no_changes_needed|blocked","summary":"short string","changed_files":["relative/path"]}}
        - After writing both files, stop and wait for the next supervisor message.

        Base role instructions:
        {base_prompt.strip()}
        """
    ).rstrip()


def build_reviewer_protocol(run_dir: Path, base_prompt: str) -> str:
    return textwrap.dedent(
        f"""\
        You are the reviewer in a two-agent Codex workflow.

        Collaboration root:
        {run_dir}

        Protocol:
        - The supervisor controls turn order. Do not poll or loop on your own.
        - Only act when the supervisor sends you a review message in this Codex session.
        - Do not modify source files. Only write review artifacts under the collaboration root.
        - For each turn N, write:
          - {run_dir}/turns/NNNN/reviewer.md
          - {run_dir}/turns/NNNN/reviewer.status.json
        - The status file must be valid JSON with exactly this shape:
          {{"verdict":"approved|changes_requested|blocked","summary":"short string","blocking_issues":["issue"]}}
        - Use verdict "approved" when there are no blocking issues left.
        - After writing both files, stop and wait for the next supervisor message.

        Base role instructions:
        {base_prompt.strip()}
        """
    ).rstrip()


def build_generator_turn_prompt(
    run_dir: Path,
    turn_number: int,
    run_id: str,
    base_prompt: str,
    *,
    include_protocol: bool,
) -> str:
    current_turn_dir = turn_dir(run_dir, turn_number)
    marker = build_turn_marker(run_id, "generator", turn_number)
    sections: list[str] = []
    if include_protocol:
        sections.append(build_generator_protocol(run_dir, base_prompt))
        sections.append("Your first task is below.")
        sections.append("")
    sections.append(
        textwrap.dedent(
            f"""\
            Generator turn {turn_name(turn_number)}.

            Supervisor turn marker:
            {marker}

            Read:
            - {current_turn_dir / "task.md"}
            """
        ).rstrip()
    )
    if turn_number > 1:
        previous_turn_dir = turn_dir(run_dir, turn_number - 1)
        sections.append(
            textwrap.dedent(
                f"""\
                - {previous_turn_dir / "reviewer.md"}
                - {previous_turn_dir / "reviewer.status.json"}
                """
            ).rstrip()
        )
    sections.append(
        textwrap.dedent(
            f"""\

            Apply the required repository changes now.

            Then write:
            - {current_turn_dir / "generator.md"}
            - {current_turn_dir / "generator.status.json"}

            The status file must use:
            {{"result":"implemented|no_changes_needed|blocked","summary":"short string","changed_files":["relative/path"]}}

            After both files are written, stop and wait.
            """
        ).rstrip()
    )
    return "\n".join(sections).rstrip()


def build_reviewer_turn_prompt(
    run_dir: Path,
    turn_number: int,
    run_id: str,
    base_prompt: str,
    *,
    include_protocol: bool,
) -> str:
    current_turn_dir = turn_dir(run_dir, turn_number)
    marker = build_turn_marker(run_id, "reviewer", turn_number)
    sections: list[str] = []
    if include_protocol:
        sections.append(build_reviewer_protocol(run_dir, base_prompt))
        sections.append("Your first review task is below.")
        sections.append("")
    sections.append(
        textwrap.dedent(
            f"""\
            Reviewer turn {turn_name(turn_number)}.

            Supervisor turn marker:
            {marker}

            Review the current repository state and these files:
            - {current_turn_dir / "task.md"}
            - {current_turn_dir / "generator.md"}
            - {current_turn_dir / "generator.status.json"}

            Then write:
            - {current_turn_dir / "reviewer.md"}
            - {current_turn_dir / "reviewer.status.json"}

            The status file must use:
            {{"verdict":"approved|changes_requested|blocked","summary":"short string","blocking_issues":["issue"]}}

            Use "approved" when no blocking issues remain.
            Use "changes_requested" when generator work is still required.
            Use "blocked" only for external blockers.

            After both files are written, stop and wait.
            """
        ).rstrip()
    )
    return "\n".join(sections).rstrip()


def write_prompt_artifact(run_dir: Path, turn_number: int, role: str, prompt: str) -> None:
    write_text(turn_dir(run_dir, turn_number) / f"supervisor_to_{role}.md", prompt)


def write_final_message_artifact(
    run_dir: Path, turn_number: int, role: str, message: str
) -> None:
    write_text(turn_dir(run_dir, turn_number) / f"{role}.final_message.md", message)


def write_raw_final_output_artifact(run_dir: Path, turn_number: int, role: str, tmux_name: str) -> None:
    write_text(
        turn_dir(run_dir, turn_number) / role / "raw_final_output.md",
        capture_last_tmux_slice(tmux_name),
    )


def prepare_turn(run_dir: Path, turn_number: int, original_task: str) -> Path:
    current = turn_dir(run_dir, turn_number)
    ensure_dir(current)
    write_text(current / "task.md", build_turn_task(original_task, turn_number))
    return current


def load_status_file(path: Path, validator) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing status file: {path}")
    data = load_json(path)
    return validator(data)


def role_artifact_paths(current_turn_dir: Path, role: str) -> tuple[Path, Path]:
    return (
        current_turn_dir / f"{role}.md",
        current_turn_dir / f"{role}.status.json",
    )


def wait_for_role_artifacts(
    current_turn_dir: Path,
    role: str,
    *,
    validator,
    timeout_seconds: float,
    phase: str,
) -> tuple[Path, Path, dict]:
    artifact_path, status_path = role_artifact_paths(current_turn_dir, role)
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        if artifact_path.exists() and status_path.exists():
            try:
                return artifact_path, status_path, load_status_file(status_path, validator)
            except Exception as exc:
                last_error = str(exc)
        time.sleep(1.0)
    details = {
        "artifact_path": str(artifact_path),
        "status_path": str(status_path),
    }
    if last_error:
        details["last_error"] = last_error
    raise SupervisorRuntimeError(
        phase,
        f"timed out waiting for {role} artifacts in {current_turn_dir}",
        role=role,
        details=details,
    )


def create_run_state(
    run_id: str,
    run_dir: Path,
    workspace_root: Path,
    max_turns: int,
    turn_timeout_seconds: float,
    launch_timeout_seconds: float,
    generator_session: str,
    reviewer_session: str,
) -> dict:
    return {
        "created_at": now_ts(),
        "current_turn": 1,
        "diagnostics_dir": str(run_dir / "diagnostics"),
        "launch_timeout_seconds": launch_timeout_seconds,
        "max_turns": max_turns,
        "roles": {
            "generator": {
                "codex_thread_id": None,
                "last_wait_phase": None,
                "session_file": None,
                "task_complete_count": 0,
                "tmux_session": generator_session,
            },
            "reviewer": {
                "codex_thread_id": None,
                "last_wait_phase": None,
                "session_file": None,
                "task_complete_count": 0,
                "tmux_session": reviewer_session,
            },
        },
        "run_dir": str(run_dir),
        "run_id": run_id,
        "status": "booting",
        "stop_reason": None,
        "turn_timeout_seconds": turn_timeout_seconds,
        "workspace_root": str(workspace_root),
    }


def save_run_state(run_dir: Path, state: dict) -> None:
    save_json(run_dir / "state.json", state)


def create_tmux_sessions(run_dir: Path, state: dict) -> None:
    workspace_root = Path(state["workspace_root"])
    for role in ("generator", "reviewer"):
        role_state = state["roles"][role]
        phase = f"{role}_session_start"
        role_state["last_wait_phase"] = phase
        save_run_state(run_dir, state)
        tmux_new_session(
            state["roles"][role]["tmux_session"],
            workspace_root,
            role=role,
        )
    save_run_state(run_dir, state)


def wait_for_tmux_sessions_ready(run_dir: Path, state: dict) -> None:
    launch_timeout_seconds = float(state["launch_timeout_seconds"])
    for role in ("generator", "reviewer"):
        phase = f"{role}_tmux_boot"
        state["roles"][role]["last_wait_phase"] = phase
        save_run_state(run_dir, state)
        wait_for_tmux_prompt(
            state["roles"][role]["tmux_session"],
            launch_timeout_seconds,
            phase=phase,
            role=role,
        )


def wait_for_role_completion(
    run_dir: Path,
    state: dict,
    role: str,
    timeout_seconds: float,
    *,
    phase: str,
    known_files_before_prompt: set[Path] | None = None,
) -> str:
    role_state = state["roles"][role]
    role_state["last_wait_phase"] = phase
    save_run_state(run_dir, state)
    previous_count = int(role_state["task_complete_count"])
    session_file_value = role_state.get("session_file")
    session_file: Path
    if session_file_value:
        session_file = Path(session_file_value)
    else:
        known_files = (
            known_files_before_prompt
            if known_files_before_prompt is not None
            else set(list_session_files(SESSION_ROOT))
        )
        prompt_marker = build_turn_marker(state["run_id"], role, state["current_turn"])
        summary = wait_for_new_tui_session_file(
            session_root=SESSION_ROOT,
            known_files=known_files,
            workspace_root=Path(state["workspace_root"]),
            prompt_marker=prompt_marker,
            timeout_seconds=timeout_seconds,
            phase=phase,
            role=role,
        )
        session_file = summary.session_file
        role_state["session_file"] = str(session_file)
        role_state["codex_thread_id"] = summary.thread_id
        save_run_state(run_dir, state)
    event = wait_for_task_complete_count(
        session_file,
        previous_count=previous_count,
        timeout_seconds=timeout_seconds,
        phase=phase,
        role=role,
    )
    role_state["task_complete_count"] = len(task_complete_events(session_file))
    save_run_state(run_dir, state)
    return event.get("last_agent_message", "")


def supervisor_loop(run_dir: Path, state: dict, original_task: str) -> None:
    turn_timeout_seconds = float(state["turn_timeout_seconds"])
    run_id = state["run_id"]

    for turn_number in range(1, int(state["max_turns"]) + 1):
        state["current_turn"] = turn_number
        current_turn_dir = prepare_turn(run_dir, turn_number, original_task)
        save_run_state(run_dir, state)

        generator_prompt = build_generator_turn_prompt(
            run_dir,
            turn_number,
            run_id,
            state["generator_base_prompt"],
            include_protocol=state["roles"]["generator"]["session_file"] is None,
        )
        write_prompt_artifact(run_dir, turn_number, "generator", generator_prompt)
        state["status"] = "waiting_generator"
        save_run_state(run_dir, state)
        wait_for_tmux_prompt(
            state["roles"]["generator"]["tmux_session"],
            turn_timeout_seconds,
            phase="generator_prompt_ready",
            role="generator",
        )
        tmux_send_prompt(
            state["roles"]["generator"]["tmux_session"],
            generator_prompt,
            phase="generator_turn",
            role="generator",
        )
        generator_artifact_path, _, generator_status = wait_for_role_artifacts(
            current_turn_dir,
            "generator",
            validator=validate_generator_status,
            timeout_seconds=turn_timeout_seconds,
            phase="generator_artifacts",
        )
        write_final_message_artifact(
            run_dir,
            turn_number,
            "generator",
            generator_artifact_path.read_text(encoding="utf-8"),
        )
        write_raw_final_output_artifact(
            run_dir,
            turn_number,
            "generator",
            state["roles"]["generator"]["tmux_session"],
        )
        if generator_status["result"] == "blocked":
            state["status"] = "blocked"
            state["stop_reason"] = generator_status["summary"]
            save_run_state(run_dir, state)
            return

        reviewer_prompt = build_reviewer_turn_prompt(
            run_dir,
            turn_number,
            run_id,
            state["reviewer_base_prompt"],
            include_protocol=state["roles"]["reviewer"]["session_file"] is None,
        )
        write_prompt_artifact(run_dir, turn_number, "reviewer", reviewer_prompt)
        state["status"] = "waiting_reviewer"
        save_run_state(run_dir, state)
        wait_for_tmux_prompt(
            state["roles"]["reviewer"]["tmux_session"],
            turn_timeout_seconds,
            phase="reviewer_prompt_ready",
            role="reviewer",
        )
        tmux_send_prompt(
            state["roles"]["reviewer"]["tmux_session"],
            reviewer_prompt,
            phase="reviewer_turn",
            role="reviewer",
        )
        reviewer_artifact_path, _, reviewer_status = wait_for_role_artifacts(
            current_turn_dir,
            "reviewer",
            validator=validate_reviewer_status,
            timeout_seconds=turn_timeout_seconds,
            phase="reviewer_artifacts",
        )
        write_final_message_artifact(
            run_dir,
            turn_number,
            "reviewer",
            reviewer_artifact_path.read_text(encoding="utf-8"),
        )
        write_raw_final_output_artifact(
            run_dir,
            turn_number,
            "reviewer",
            state["roles"]["reviewer"]["tmux_session"],
        )

        if reviewer_status["verdict"] == "approved":
            state["status"] = "approved"
            state["stop_reason"] = reviewer_status["summary"]
            save_run_state(run_dir, state)
            return
        if reviewer_status["verdict"] == "blocked":
            state["status"] = "blocked"
            state["stop_reason"] = reviewer_status["summary"]
            save_run_state(run_dir, state)
            return

    state["status"] = "max_turns_reached"
    state["stop_reason"] = f"reached max turns ({state['max_turns']})"
    save_run_state(run_dir, state)


def write_failure_diagnostics(
    run_dir: Path, state: dict, error: SupervisorRuntimeError
) -> Path:
    diagnostics_root = Path(state["diagnostics_dir"])
    ensure_dir(diagnostics_root)
    failure_dir = diagnostics_root / f"{time.strftime('%Y%m%d-%H%M%S')}-{error.phase}"
    ensure_dir(failure_dir)
    save_json(
        failure_dir / "error.json",
        {
            "details": error.details,
            "message": str(error),
            "phase": error.phase,
            "role": error.role,
            "timestamp": now_ts(),
        },
    )
    save_json(failure_dir / "state_snapshot.json", state)
    for role in ("generator", "reviewer"):
        tmux_name = state["roles"][role]["tmux_session"]
        write_text(failure_dir / f"{role}.pane.txt", tmux_capture_pane(tmux_name))
    return failure_dir


def cmd_start(args: argparse.Namespace) -> int:
    workspace_root = Path.cwd().resolve()
    run_id = args.run_id or time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    run_dir = workspace_root / RUNS_ROOT / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")

    original_task = read_text_arg(
        args.task,
        args.task_file,
        default="",
    ).strip()
    if not original_task:
        raise SystemExit("task is empty")

    generator_prompt = read_text_arg(
        args.generator_prompt,
        args.generator_prompt_file,
        default="You are the code generator. Make the requested repository changes directly.",
    )
    reviewer_prompt = read_text_arg(
        args.reviewer_prompt,
        args.reviewer_prompt_file,
        default="You are the code reviewer. Find blocking issues and state clearly whether the work is approved.",
    )

    ensure_dir(run_dir / "turns")
    write_text(run_dir / "original_task.md", original_task)
    state = create_run_state(
        run_id=run_id,
        run_dir=run_dir,
        workspace_root=workspace_root,
        max_turns=args.max_turns,
        turn_timeout_seconds=args.turn_timeout_seconds,
        launch_timeout_seconds=args.launch_timeout_seconds,
        generator_session=args.generator_session or f"codex-generator-{run_id}",
        reviewer_session=args.reviewer_session or f"codex-reviewer-{run_id}",
    )
    state["generator_base_prompt"] = generator_prompt
    state["reviewer_base_prompt"] = reviewer_prompt
    save_run_state(run_dir, state)

    try:
        create_tmux_sessions(run_dir, state)
        print(f"run_id: {run_id}")
        print(f"run_dir: {run_dir}")
        print(f"generator tmux: {state['roles']['generator']['tmux_session']}")
        print(f"reviewer tmux: {state['roles']['reviewer']['tmux_session']}")
        print(f"attach generator: tmux attach -t {state['roles']['generator']['tmux_session']}")
        print(f"attach reviewer: tmux attach -t {state['roles']['reviewer']['tmux_session']}")

        wait_for_tmux_sessions_ready(run_dir, state)
        print("both Codex TUI sessions are ready")
        supervisor_loop(run_dir, state, original_task)
    except SupervisorRuntimeError as error:
        state = load_json(run_dir / "state.json")
        state["status"] = "bootstrap_failed" if "bootstrap" in error.phase else "blocked"
        state["stop_reason"] = f"{error.phase}: {error}"
        failure_dir = write_failure_diagnostics(run_dir, state, error)
        save_run_state(run_dir, state)
        print(f"supervisor error during {error.phase}: {error}", flush=True)
        print(f"diagnostics: {failure_dir}", flush=True)
        return 1
    except Exception as exc:
        error = SupervisorRuntimeError("unexpected", str(exc))
        state = load_json(run_dir / "state.json")
        state["status"] = "blocked"
        state["stop_reason"] = f"{error.phase}: {error}"
        failure_dir = write_failure_diagnostics(run_dir, state, error)
        save_run_state(run_dir, state)
        print(f"supervisor error during {error.phase}: {error}", flush=True)
        print(f"diagnostics: {failure_dir}", flush=True)
        return 1

    final_state = load_json(run_dir / "state.json")
    print(f"final status: {final_state['status']}")
    if final_state.get("stop_reason"):
        print(f"stop reason: {final_state['stop_reason']}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    run_dir = Path.cwd().resolve() / RUNS_ROOT / args.run_id
    state_path = run_dir / "state.json"
    if not state_path.exists():
        raise SystemExit(f"missing run state: {state_path}")
    state = load_json(state_path)
    print(json.dumps(state, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run two real Codex TUIs in tmux and coordinate them with a filesystem turn protocol."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start a new coordinated TUI run")
    start.add_argument("--run-id")
    start.add_argument("--task")
    start.add_argument("--task-file")
    start.add_argument("--generator-prompt")
    start.add_argument("--generator-prompt-file")
    start.add_argument("--reviewer-prompt")
    start.add_argument("--reviewer-prompt-file")
    start.add_argument("--generator-session")
    start.add_argument("--reviewer-session")
    start.add_argument("--max-turns", type=int, default=6)
    start.add_argument("--launch-timeout-seconds", type=float, default=60.0)
    start.add_argument("--turn-timeout-seconds", type=float, default=1800.0)
    start.set_defaults(func=cmd_start)

    status = sub.add_parser("status", help="show the state of an existing run")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
