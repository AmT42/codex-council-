#!/usr/bin/env python3

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import textwrap
import time
import tomllib
import uuid
from typing import Literal


COUNCIL_DIRNAME = ".codex-council"
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "templates"
ROLE_NAMES = ("generator", "reviewer")
REVIEW_MODES = {"internal", "github_pr_codex"}
REOPEN_REASON_KINDS = {"false_approved", "requirements_changed_after_approval"}
BASE_REQUIRED_FILENAMES = (
    "AGENTS.md",
    "generator.instructions.md",
    "reviewer.instructions.md",
)
TASK_FILENAME = "task.md"
REVIEW_FILENAME = "review.md"
LEGACY_REVIEW_FILENAME = "initial_review.md"
SPEC_FILENAME = "spec.md"
CONTRACT_FILENAME = "contract.md"
INPUT_DOC_ORDER = ("task", "review", "spec", "contract")
INPUT_DOC_FILENAMES = {
    "task": TASK_FILENAME,
    "review": REVIEW_FILENAME,
    "spec": SPEC_FILENAME,
    "contract": CONTRACT_FILENAME,
}
CANONICAL_FILE_LABELS = {
    "agents": "AGENTS.md",
    "generator": "generator.instructions.md",
    "reviewer": "reviewer.instructions.md",
    **INPUT_DOC_FILENAMES,
}
CANONICAL_FILE_ORDER = ("task", "review", "spec", "contract", "agents", "generator", "reviewer")
GENERATOR_RESULTS = {"implemented", "no_changes_needed", "blocked", "needs_human"}
REVIEWER_VERDICTS = {"approved", "changes_requested", "blocked", "needs_human"}
HUMAN_SOURCES = {
    TASK_FILENAME,
    REVIEW_FILENAME,
    LEGACY_REVIEW_FILENAME,
    SPEC_FILENAME,
    CONTRACT_FILENAME,
    "AGENTS.md",
    "generator.instructions.md",
    "reviewer.instructions.md",
    "repo_state",
}
REVIEW_DIMENSION_STATUSES = {"pass", "fail", "uncertain"}
TMUX_PANE_POLL_SECONDS = 0.5
TMUX_PASTE_SETTLE_SECONDS = 0.1
TMUX_CAPTURE_HISTORY_LINES = 1000
ROLE_ARTIFACT_POLL_SECONDS = 1.0
TASK_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
GITHUB_PR_URL_RE = re.compile(r"^https?://[^/]+/([^/]+)/([^/]+)/pull/([0-9]+)(?:/.*)?$")
CHECKLIST_ITEM_RE = re.compile(r"^\s*(?:[-*]\s*)?\[\s*[xX]?\s*\]\s+\S")
REVIEW_ITEM_RE = re.compile(r"^\s*[-*]\s+\S")
CONTRACT_PLACEHOLDER_MARKERS = (
    "Write the definition of done for this task here as a checklist.",
    "Bad examples:",
)
REVIEW_PLACEHOLDER_MARKERS = (
    "Describe the concrete issue, finding, or blocker to fix.",
    "Optional extra context",
)
TASK_PLACEHOLDER_MARKERS = (
    "Describe the bug, ticket, or requested change in a few concrete sentences.",
    "Add just the context needed to act safely:",
    "Describe what should be true when this task is done.",
)
SPEC_PLACEHOLDER_MARKERS = (
    "Describe the main thing that should be built or changed.",
    "Describe what a user, operator, or stakeholder should be able to do or observe when the work is complete.",
    "List the behavior, systems, or surfaces that are part of this request.",
    "List things that should not be changed in this task, even if they seem related.",
    "List important limits or requirements.",
    "Describe the current product or technical context the council should know.",
    "Describe the required behavior in concrete terms.",
    "Describe known technical boundaries, touched areas, interfaces, or architectural preferences.",
    "Describe how the work should be validated.",
    "List anything that is still undecided or ambiguous.",
)
TASK_REQUIRED_HEADINGS = (
    "# Task",
    "## Request",
    "## Context",
    "## Success Signal",
)
SPEC_REQUIRED_HEADINGS = (
    "# Spec",
    "## Goal",
    "## User Outcome",
    "## In Scope",
    "## Out of Scope",
    "## Constraints",
    "## Existing Context",
    "## Desired Behavior",
    "## Technical Boundaries",
    "## Validation Expectations",
    "## Open Questions",
)
TASK_VAGUE_WORDS = ("production-ready", "production ready", "scalable", "viral", "enterprise", "best-in-class")
GENERIC_SUCCESS_SIGNAL_PHRASES = (
    "works",
    "it works",
    "done",
    "fixed",
    "is fixed",
    "should work",
    "works correctly",
)
GENERIC_REVIEW_FINDING_PHRASES = (
    "fix this",
    "fix bug",
    "bug",
    "issue",
    "problem",
    "still broken",
    "make it robust",
)
CONTRACT_VAGUE_PHRASES = TASK_VAGUE_WORDS + (
    "good ux",
    "solid",
    "robust",
    "better",
    "clean up",
)
VERIFICATION_HINT_WORDS = (
    "test",
    "tests",
    "verify",
    "verified",
    "verification",
    "validate",
    "validation",
    "repro",
    "passing",
    "manual",
    "screenshot",
    "typecheck",
    "lint",
)
BROAD_TASK_HINT_WORDS = (
    "build",
    "feature",
    "dashboard",
    "workflow",
    "system",
    "platform",
    "redesign",
    "overhaul",
    "onboarding",
    "pipeline",
)
ARTIFACT_REPAIR_ATTEMPTS = 1
SESSION_RECOVERY_ATTEMPTS = 1
RAW_OUTPUT_CAPTURE_TIMEOUT_SECONDS = 30.0
TERMINAL_SUMMARY_BEGIN = "COUNCIL_TERMINAL_SUMMARY_BEGIN"
TERMINAL_SUMMARY_END = "COUNCIL_TERMINAL_SUMMARY_END"
TRANSITIONING_TURN_STATUS = "transitioning_turn"
REOPEN_INDEX_FILENAME = "reopen-events.jsonl"
REOPEN_METADATA_FILENAME = "reopen.json"
TURN_METADATA_AUDIT_KEYS = (
    "continuation_reason",
    "continuation_source",
    "continued_at",
    "selected_role",
    "selected_turn",
)
GITHUB_CODEX_REVIEW_PREFIX = "Codex Review:"
GITHUB_CODEX_APPROVED_PREFIX = "Codex Review: Didn't find any major issues. Keep it up!"
GITHUB_CODEX_INITIAL_WAIT_SECONDS = 600
GITHUB_CODEX_POLL_INTERVAL_SECONDS = 300
CODEX_TRUST_PROMPT_TEXT = "Do you trust the contents of this directory?"
CODEX_TRUST_CONTINUE_TEXT = "Press enter to continue"
CODEX_FOOTER_RE = re.compile(r"^\s*\S.*\s+·\s+(?:~|/).+$")
TMUX_BOOT_GRACE_SECONDS = 2.0
TMUX_PROMPT_DISPATCH_ATTEMPTS = 2
TMUX_PROMPT_DISPATCH_CONFIRM_SECONDS = 0.2


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


class ContinuationResolutionError(RuntimeError):
    def __init__(self, message: str, *, details: dict | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ts_from_epoch(epoch_seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch_seconds))


def parse_utc_timestamp(value: str | None) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip()
    try:
        return datetime.fromisoformat(normalized.replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
    except ValueError:
        return None


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


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_if_missing(path: Path, text: str) -> bool:
    if path.exists():
        return False
    write_text(path, text)
    return True


def append_jsonl(path: Path, data: dict) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, sort_keys=True))
        fh.write("\n")


def template_path(*parts: str) -> Path:
    return TEMPLATE_ROOT.joinpath(*parts)


def read_template(*parts: str) -> str:
    path = template_path(*parts)
    if not path.exists():
        raise SystemExit(f"missing template file: {path}")
    return path.read_text(encoding="utf-8")


def load_critical_review_dimensions() -> list[dict]:
    path = template_path("data", "critical_review_dimensions.json")
    if not path.exists():
        raise SystemExit(f"missing template file: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    dimensions = data.get("dimensions")
    if not isinstance(dimensions, list):
        raise SystemExit(f"invalid critical review dimensions file: {path}")
    normalized: list[dict] = []
    for item in dimensions:
        if not isinstance(item, dict):
            raise SystemExit(f"invalid critical review dimensions file: {path}")
        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not isinstance(label, str):
            raise SystemExit(f"invalid critical review dimensions file: {path}")
        normalized.append({"key": key, "label": label})
    return normalized


def render_template_text(template_text: str, values: dict[str, str], *, template_name: str) -> str:
    def replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise SystemExit(f"unresolved placeholder `{key}` in template {template_name}")
        return values[key]

    rendered = re.sub(r"\{\{([A-Za-z0-9_]+)\}\}", replacer, template_text)
    unresolved = re.findall(r"\{\{([A-Za-z0-9_]+)\}\}", rendered)
    if unresolved:
        raise SystemExit(f"unresolved placeholders in template {template_name}: {', '.join(sorted(set(unresolved)))}")
    return rendered


def default_scaffold_text(filename: str) -> str:
    return read_template("scaffold", filename)


def build_task_doc_from_seed(initial_task_text: str) -> str:
    stripped = initial_task_text.strip()
    if stripped.startswith("# Task"):
        return stripped
    return textwrap.dedent(
        f"""\
        # Task

        ## Request

        {stripped}

        ## Context

        Add any concrete context, constraints, or references needed to act safely.

        ## Success Signal

        Describe what should be true when this task is done. Keep it short unless this needs a full `spec.md`.
        """
    ).rstrip()


def build_review_doc_from_seed(initial_review_text: str) -> str:
    stripped = initial_review_text.strip()
    if stripped.startswith("# Review"):
        return stripped
    return textwrap.dedent(
        f"""\
        # Review

        ## Findings

        - {stripped}

        ## Context

        Add any logs, repro steps, links, or code references that support the findings.
        """
    ).rstrip()


def build_spec_doc_from_seed(initial_task_text: str) -> str:
    stripped = initial_task_text.strip()
    if stripped.startswith("# Spec"):
        return stripped
    return textwrap.dedent(
        f"""\
        # Spec

        ## Goal

        {stripped}

        ## User Outcome

        Describe what a user, operator, or stakeholder should be able to do or observe when the work is complete.

        ## In Scope

        - Fill this in

        ## Out of Scope

        - Fill this in

        ## Constraints

        - Fill this in

        ## Existing Context

        Fill this in.

        ## Desired Behavior

        Fill this in.

        ## Technical Boundaries

        Fill this in.

        ## Validation Expectations

        Fill this in.

        ## Open Questions

        - None yet
        """
    ).rstrip()


def build_contract_doc_from_seed(initial_contract_text: str) -> str:
    stripped = initial_contract_text.strip()
    if stripped.startswith("# Definition of Done"):
        return stripped
    bullets = [
        line.strip()
        for line in stripped.splitlines()
        if line.strip()
    ]
    if not bullets:
        return read_template("scaffold", CONTRACT_FILENAME).rstrip()
    checklist = "\n".join(
        line if CHECKLIST_ITEM_RE.match(line) else f"- [ ] {line.lstrip('-* ').strip()}"
        for line in bullets
    )
    return textwrap.dedent(
        f"""\
        # Definition of Done

        {checklist}
        """
    ).rstrip()


def read_codex_session_index() -> list[dict]:
    path = codex_session_index_path()
    if not path.exists():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        session_id = item.get("id")
        updated_at = item.get("updated_at")
        thread_name = item.get("thread_name")
        if isinstance(session_id, str) and isinstance(updated_at, str):
            entries.append(
                {
                    "id": session_id,
                    "updated_at": updated_at,
                    "thread_name": thread_name if isinstance(thread_name, str) else None,
                }
            )
    return entries


def find_codex_session_entry(session_id: str) -> dict | None:
    for entry in read_codex_session_index():
        if entry["id"] == session_id:
            return entry
    return None


def run_subprocess(
    args: list[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        capture_output=True,
        input=input_text,
    )


def git_root_for(path: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip()).resolve()


def git_stdout(repo_root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SupervisorRuntimeError(
            "git_command",
            f"git {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            details={
                "command": ["git", "-C", str(repo_root), *args],
                "stderr": proc.stderr,
                "stdout": proc.stdout,
            },
        )
    return proc.stdout.strip()


def git_current_branch(repo_root: Path) -> str:
    return git_stdout(repo_root, "symbolic-ref", "--quiet", "--short", "HEAD")


def git_head_sha(repo_root: Path) -> str:
    return git_stdout(repo_root, "rev-parse", "HEAD")


def gh_run(
    repo_root: Path,
    args: list[str],
    *,
    phase: str,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    proc = run_subprocess(
        ["gh", *args],
        check=False,
        cwd=repo_root,
        input_text=input_text,
    )
    if proc.returncode != 0:
        raise SupervisorRuntimeError(
            phase,
            f"gh {' '.join(args)} failed: {proc.stderr.strip() or proc.stdout.strip()}",
            role="reviewer",
            details={
                "command": ["gh", *args],
                "stderr": proc.stderr,
                "stdout": proc.stdout,
            },
        )
    return proc


def gh_json(
    repo_root: Path,
    args: list[str],
    *,
    phase: str,
    input_text: str | None = None,
):
    proc = gh_run(repo_root, args, phase=phase, input_text=input_text)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SupervisorRuntimeError(
            phase,
            f"gh {' '.join(args)} returned invalid JSON",
            role="reviewer",
            details={
                "command": ["gh", *args],
                "stdout": proc.stdout,
            },
        ) from exc


def git_preflight(repo_root: Path) -> dict:
    status_porcelain = git_stdout(repo_root, "status", "--porcelain")
    if status_porcelain:
        raise SystemExit(
            f"{repo_root} has uncommitted changes. Clean or stash the worktree before starting the council."
        )

    proc = subprocess.run(
        ["git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"{repo_root} is in detached HEAD state. Switch to a branch before starting the council.")
    current_branch = proc.stdout.strip()

    head_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        raise SystemExit(f"{repo_root} has no commits yet. Create an initial commit before starting the council.")
    base_commit_sha = head_proc.stdout.strip()

    return {
        "enabled": True,
        "current_branch": current_branch,
        "base_commit_sha": base_commit_sha,
        "last_generator_commit_sha": None,
    }


def git_preflight_allowing_dirty(repo_root: Path) -> dict:
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short", "HEAD"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit(f"{repo_root} is in detached HEAD state. Switch to a branch before starting the council.")
    current_branch = proc.stdout.strip()

    head_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        raise SystemExit(f"{repo_root} has no commits yet. Create an initial commit before starting the council.")
    base_commit_sha = head_proc.stdout.strip()

    return {
        "enabled": True,
        "current_branch": current_branch,
        "base_commit_sha": base_commit_sha,
        "last_generator_commit_sha": None,
    }


def coerce_str(value, default: str, field_name: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise SystemExit(f"invalid config value for {field_name}: expected string")
    return value


def coerce_bool(value, default: bool, field_name: str) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SystemExit(f"invalid config value for {field_name}: expected boolean")
    return value


def coerce_int(value, default: int, field_name: str) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise SystemExit(f"invalid config value for {field_name}: expected integer")
    return value


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


def validate_task_name(task_name: str) -> str:
    if not TASK_NAME_RE.fullmatch(task_name):
        raise SystemExit(
            "task_name must match [A-Za-z0-9._-]+ so it can safely map to a directory name"
        )
    return task_name


def council_root_for(repo_root: Path) -> Path:
    return repo_root / COUNCIL_DIRNAME


def task_root_for(repo_root: Path, task_name: str) -> Path:
    return council_root_for(repo_root) / task_name


def config_path_for(repo_root: Path) -> Path:
    return council_root_for(repo_root) / "config.toml"


def council_gitignore_path_for(repo_root: Path) -> Path:
    return council_root_for(repo_root) / ".gitignore"


def latest_run_dir(task_root: Path) -> Path:
    runs_root = task_root / "runs"
    if not runs_root.exists():
        raise SystemExit(f"missing runs directory: {runs_root}")
    candidates = sorted(path for path in runs_root.iterdir() if path.is_dir())
    if not candidates:
        raise SystemExit(f"no runs found for task: {task_root.name}")
    return candidates[-1]


def resolve_run_dir(task_root: Path, run_id: str | None) -> Path:
    if run_id in (None, "latest"):
        return latest_run_dir(task_root)
    run_dir = task_root / "runs" / run_id
    if not run_dir.exists():
        raise SystemExit(f"missing run directory: {run_dir}")
    return run_dir


def list_turn_dirs(run_dir: Path) -> list[Path]:
    turns_root = run_dir / "turns"
    if not turns_root.exists():
        raise SystemExit(f"missing turns directory: {turns_root}")
    candidates = []
    for path in turns_root.iterdir():
        if not path.is_dir():
            continue
        try:
            turn_number = int(path.name)
        except ValueError:
            continue
        candidates.append((turn_number, path))
    if not candidates:
        raise SystemExit(f"no turns found for run: {run_dir}")
    return [path for _, path in sorted(candidates)]


def latest_turn_dir(run_dir: Path) -> Path:
    return list_turn_dirs(run_dir)[-1]


def events_path_for(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def reopen_index_path_for(repo_root: Path) -> Path:
    return council_root_for(repo_root) / REOPEN_INDEX_FILENAME


def codex_session_index_path() -> Path:
    return Path.home() / ".codex" / "session_index.jsonl"


def turn_dir_for(run_dir: Path, turn_number: int) -> Path:
    return run_dir / "turns" / turn_name(turn_number)


def turn_metadata_path(turn_dir: Path) -> Path:
    return turn_dir / "turn.json"


def context_manifest_path(turn_dir: Path) -> Path:
    return turn_dir / "context_manifest.json"


def reopen_metadata_path(run_dir: Path) -> Path:
    return run_dir / REOPEN_METADATA_FILENAME


def role_dir_for(turn_dir: Path, role: str) -> Path:
    return turn_dir / role


def role_prompt_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "prompt.md"


def role_message_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "message.md"


def role_status_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "status.json"


def role_raw_output_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "raw_final_output.md"


def role_capture_status_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "capture_status.json"


def role_validation_error_json_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "validation_error.json"


def role_validation_error_md_path(turn_dir: Path, role: str) -> Path:
    return role_dir_for(turn_dir, role) / "validation_error.md"


def inspect_task_workspace(task_root: Path) -> dict:
    base_required_files = [task_root / name for name in BASE_REQUIRED_FILENAMES]
    task_path = task_root / TASK_FILENAME
    review_path = task_root / REVIEW_FILENAME
    legacy_review_path = task_root / LEGACY_REVIEW_FILENAME
    spec_path = task_root / SPEC_FILENAME
    contract_path = task_root / CONTRACT_FILENAME

    if review_path.exists() and legacy_review_path.exists():
        raise SystemExit(
            f"invalid task workspace for {task_root.name}.\n"
            f"{REVIEW_FILENAME} and {LEGACY_REVIEW_FILENAME} cannot both exist."
        )

    doc_paths: dict[str, Path | None] = {
        "task": task_path if task_path.exists() else None,
        "review": review_path if review_path.exists() else (legacy_review_path if legacy_review_path.exists() else None),
        "spec": spec_path if spec_path.exists() else None,
        "contract": contract_path if contract_path.exists() else None,
    }
    if doc_paths["spec"] and not doc_paths["task"]:
        raise SystemExit(
            f"invalid task workspace for {task_root.name}.\n"
            f"{SPEC_FILENAME} requires {TASK_FILENAME}."
        )
    if doc_paths["contract"] and not (doc_paths["task"] or doc_paths["review"]):
        raise SystemExit(
            f"invalid task workspace for {task_root.name}.\n"
            f"{CONTRACT_FILENAME} requires at least {TASK_FILENAME} or {REVIEW_FILENAME}."
        )

    present_docs = tuple(name for name in INPUT_DOC_ORDER if doc_paths[name] is not None)
    return {
        "doc_paths": doc_paths,
        "legacy_review_source": bool(doc_paths["review"] and doc_paths["review"].name == LEGACY_REVIEW_FILENAME),
        "present_docs": present_docs,
        "profile": "+".join(present_docs) if present_docs else "undocumented",
        "required_files": base_required_files,
        "missing_files": [path for path in base_required_files if not path.exists()],
    }


def required_task_files(task_root: Path) -> list[Path]:
    return inspect_task_workspace(task_root)["required_files"]


def missing_task_files(task_root: Path) -> list[Path]:
    return inspect_task_workspace(task_root)["missing_files"]


def scaffold_council_root(repo_root: Path) -> None:
    council_root = council_root_for(repo_root)
    ensure_dir(council_root)
    write_if_missing(
        council_gitignore_path_for(repo_root),
        read_template("scaffold", "council_root.gitignore"),
    )
    write_if_missing(
        config_path_for(repo_root),
        read_template("scaffold", "config.toml"),
    )


def scaffold_task_root(
    task_root: Path,
    *,
    initial_task_text: str | None,
) -> dict:
    ensure_dir(task_root)
    task_created = False
    if initial_task_text:
        task_created = write_if_missing(
            task_root / TASK_FILENAME,
            build_task_doc_from_seed(initial_task_text),
        )
    agents_created = write_if_missing(
        task_root / "AGENTS.md",
        read_template("scaffold", "AGENTS.md"),
    )
    generator_created = write_if_missing(
        task_root / "generator.instructions.md",
        read_template("scaffold", "generator.instructions.md"),
    )
    reviewer_created = write_if_missing(
        task_root / "reviewer.instructions.md",
        read_template("scaffold", "reviewer.instructions.md"),
    )
    return {
        "task_created": task_created,
        "task_needs_edit": task_created and not initial_task_text,
        "review_created": False,
        "spec_created": False,
        "contract_created": False,
        "agents_created": agents_created,
        "generator_created": generator_created,
        "reviewer_created": reviewer_created,
        "profile": inspect_task_workspace(task_root)["profile"],
    }


def ensure_task_workspace_exists(task_root: Path) -> dict:
    inspection = inspect_task_workspace(task_root)
    missing = inspection["missing_files"]
    if missing:
        missing_lines = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(
            f"task workspace is not initialized for {task_root.name}.\n"
            f"Run `init {task_root.name}` first.\n"
            f"Missing files:\n{missing_lines}"
        )
    return inspection


def contract_checklist_items(contract_text: str) -> list[str]:
    return [
        line.strip()
        for line in contract_text.splitlines()
        if CHECKLIST_ITEM_RE.match(line)
    ]


def review_items(review_text: str) -> list[str]:
    return [
        line.strip()
        for line in review_text.splitlines()
        if REVIEW_ITEM_RE.match(line)
    ]


def normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def meaningful_word_count(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9_/-]+", value))


def contains_any_phrase(value: str, phrases: tuple[str, ...]) -> bool:
    normalized = normalize_text(value)
    return any(normalize_text(phrase) in normalized for phrase in phrases)


def extract_markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    capture = False
    collected: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == heading:
            capture = True
            collected = []
            continue
        if capture and stripped.startswith("## "):
            break
        if capture:
            collected.append(line)
    return "\n".join(collected).strip()


def strip_checklist_prefix(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]\s*)?\[\s*[xX]?\s*\]\s*", "", line).strip()


def strip_bullet_prefix(line: str) -> str:
    return re.sub(r"^\s*[-*]\s*", "", line).strip()


def section_contains_placeholder(section_text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in section_text for marker in markers)


def task_brief_requires_spec(task_text: str) -> bool:
    request_text = extract_markdown_section(task_text, "## Request")
    context_text = extract_markdown_section(task_text, "## Context")
    success_text = extract_markdown_section(task_text, "## Success Signal")
    normalized_request = normalize_text(request_text)
    broad = any(normalize_text(word) in normalized_request for word in BROAD_TASK_HINT_WORDS)
    if not broad:
        return False
    return (
        meaningful_word_count(request_text) < 16
        or meaningful_word_count(context_text) < 8
        or meaningful_word_count(success_text) < 8
    )


def lint_task_workspace_readiness(task_root: Path) -> tuple[list[str], list[str]]:
    task_text = (task_root / TASK_FILENAME).read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    if task_text.strip() == read_template("scaffold", TASK_FILENAME).strip():
        errors.append(f"{TASK_FILENAME} still contains scaffold placeholder text")
    for heading in TASK_REQUIRED_HEADINGS:
        if heading not in task_text:
            errors.append(f"{TASK_FILENAME} is missing required heading: {heading}")
    request_text = extract_markdown_section(task_text, "## Request")
    context_text = extract_markdown_section(task_text, "## Context")
    success_text = extract_markdown_section(task_text, "## Success Signal")
    if not request_text or section_contains_placeholder(request_text, TASK_PLACEHOLDER_MARKERS):
        errors.append(f"{TASK_FILENAME} needs a concrete `## Request` section")
    elif meaningful_word_count(request_text) < 4:
        errors.append(f"{TASK_FILENAME} request is too short to be a useful engineering brief")
    if not context_text or section_contains_placeholder(context_text, TASK_PLACEHOLDER_MARKERS):
        errors.append(f"{TASK_FILENAME} needs concrete repo or problem context in `## Context`")
    elif meaningful_word_count(context_text) < 2:
        errors.append(f"{TASK_FILENAME} context is too thin to act safely")
    if not success_text or section_contains_placeholder(success_text, TASK_PLACEHOLDER_MARKERS):
        errors.append(f"{TASK_FILENAME} needs an observable `## Success Signal`")
    if success_text and contains_any_phrase(success_text, GENERIC_SUCCESS_SIGNAL_PHRASES) and meaningful_word_count(success_text) < 10:
        errors.append(
            f"{TASK_FILENAME} success signal is too generic; describe observable completion instead of phrases like `works` or `done`"
        )
    elif success_text and meaningful_word_count(success_text) < 4:
        errors.append(f"{TASK_FILENAME} success signal is too short to be auditable")
    lowered_task = task_text.lower()
    for vague_word in TASK_VAGUE_WORDS:
        if vague_word in lowered_task:
            warnings.append(
                f"{TASK_FILENAME} uses vague wording `{vague_word}`; decompose it into concrete task behavior or promote the task into {SPEC_FILENAME}"
            )
    return errors, warnings


def lint_review_workspace_readiness(review_path: Path) -> tuple[list[str], list[str]]:
    review_text = review_path.read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    if review_text.strip() == read_template("scaffold", REVIEW_FILENAME).strip():
        errors.append(f"{review_path.name} still contains scaffold placeholder text")
    if "# Review" not in review_text and "# Initial Review" not in review_text:
        errors.append(f"{review_path.name} must begin with `# Review`")
    if any(marker in review_text for marker in REVIEW_PLACEHOLDER_MARKERS):
        errors.append(f"{review_path.name} still contains scaffold placeholder text")
    items = review_items(review_text)
    stripped_items = [strip_bullet_prefix(item) for item in items]
    if not items:
        errors.append(f"{review_path.name} must contain at least one bullet item")
    elif all(meaningful_word_count(item) < 4 for item in stripped_items):
        errors.append(f"{review_path.name} findings are too short to guide generator triage")
    for item in stripped_items:
        if contains_any_phrase(item, GENERIC_REVIEW_FINDING_PHRASES) and meaningful_word_count(item) < 8:
            errors.append(f"{review_path.name} contains a finding that is too generic to be actionable: `{item}`")
        elif meaningful_word_count(item) < 3:
            errors.append(f"{review_path.name} contains a finding that is too short to be actionable: `{item}`")
    return errors, warnings


def lint_spec_workspace_readiness(task_root: Path) -> tuple[list[str], list[str]]:
    spec_text = (task_root / SPEC_FILENAME).read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    if spec_text.strip() == read_template("scaffold", SPEC_FILENAME).strip():
        errors.append(f"{SPEC_FILENAME} still contains scaffold placeholder text")
    for heading in SPEC_REQUIRED_HEADINGS:
        if heading not in spec_text:
            errors.append(f"{SPEC_FILENAME} is missing required heading: {heading}")
    if any(marker in spec_text for marker in SPEC_PLACEHOLDER_MARKERS):
        errors.append(f"{SPEC_FILENAME} still contains scaffold placeholder text")
    for heading, minimum_words in (
        ("## Goal", 4),
        ("## User Outcome", 4),
        ("## Desired Behavior", 6),
        ("## Validation Expectations", 4),
    ):
        section_text = extract_markdown_section(spec_text, heading)
        if not section_text or meaningful_word_count(section_text) < minimum_words:
            errors.append(f"{SPEC_FILENAME} needs a more complete `{heading}` section")
    for heading in ("## In Scope", "## Out of Scope", "## Constraints", "## Technical Boundaries"):
        section_text = extract_markdown_section(spec_text, heading)
        if meaningful_word_count(section_text) < 2:
            warnings.append(f"{SPEC_FILENAME} should make `{heading}` more explicit for safe execution")
    lowered_spec = spec_text.lower()
    for vague_word in TASK_VAGUE_WORDS:
        if vague_word in lowered_spec:
            warnings.append(
                f"{SPEC_FILENAME} uses vague wording `{vague_word}`; decompose it into concrete behavior or constraints"
            )
    return errors, warnings


def lint_contract_workspace_readiness(task_root: Path) -> tuple[list[str], list[str]]:
    contract_text = (task_root / CONTRACT_FILENAME).read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    if any(marker in contract_text for marker in CONTRACT_PLACEHOLDER_MARKERS):
        errors.append(f"{CONTRACT_FILENAME} still contains scaffold placeholder text")
    if "# Definition of Done" not in contract_text:
        errors.append(f"{CONTRACT_FILENAME} must begin with `# Definition of Done`")
    checklist_items = contract_checklist_items(contract_text)
    normalized_items = [strip_checklist_prefix(item) for item in checklist_items]
    if not checklist_items:
        errors.append(f"{CONTRACT_FILENAME} must contain at least one checklist item")
    elif len(checklist_items) < 2:
        warnings.append(f"{CONTRACT_FILENAME} usually needs more than one checklist item to be auditable")
    for item in normalized_items:
        if meaningful_word_count(item) < 4:
            errors.append(f"{CONTRACT_FILENAME} item is too short to be auditable: `{item}`")
        if contains_any_phrase(item, CONTRACT_VAGUE_PHRASES):
            errors.append(f"{CONTRACT_FILENAME} item is too vague or aspirational: `{item}`")
    if normalized_items and not any(contains_any_phrase(item, VERIFICATION_HINT_WORDS) for item in normalized_items):
        warnings.append(f"{CONTRACT_FILENAME} should usually include at least one explicit verification item")
    if normalized_items and not any(not contains_any_phrase(item, VERIFICATION_HINT_WORDS) for item in normalized_items):
        warnings.append(
            f"{CONTRACT_FILENAME} should usually include at least one behavior or integrity item in addition to verification"
        )
    return errors, warnings


def load_council_config(repo_root: Path) -> dict:
    config_path = config_path_for(repo_root)
    if not config_path.exists():
        write_text(config_path, default_scaffold_text("config.toml"))
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"invalid TOML in {config_path}: {exc}") from exc

    codex_cfg = data.get("codex", {})
    council_cfg = data.get("council", {})

    return {
        "codex": {
            "dangerously_bypass_approvals_and_sandbox": coerce_bool(
                codex_cfg.get("dangerously_bypass_approvals_and_sandbox"),
                True,
                "codex.dangerously_bypass_approvals_and_sandbox",
            ),
            "model": coerce_str(codex_cfg.get("model"), "gpt-5.4", "codex.model"),
            "model_reasoning_effort": coerce_str(
                codex_cfg.get("model_reasoning_effort"),
                "xhigh",
                "codex.model_reasoning_effort",
            ),
            "no_alt_screen": coerce_bool(
                codex_cfg.get("no_alt_screen"),
                True,
                "codex.no_alt_screen",
            ),
        },
        "council": {
            "launch_timeout_seconds": coerce_int(
                council_cfg.get("launch_timeout_seconds"),
                60,
                "council.launch_timeout_seconds",
            ),
            "max_turns": coerce_int(
                council_cfg.get("max_turns"),
                6,
                "council.max_turns",
            ),
            "require_git": coerce_bool(
                council_cfg.get("require_git"),
                True,
                "council.require_git",
            ),
            "turn_timeout_seconds": coerce_int(
                council_cfg.get("turn_timeout_seconds"),
                1800,
                "council.turn_timeout_seconds",
            ),
        },
    }


def resolve_target_root(target: Path, *, allow_non_git: bool) -> tuple[Path, bool]:
    target = target.resolve()
    git_root = git_root_for(target)
    if git_root is not None:
        return git_root, True

    if allow_non_git:
        return target, False

    config_path = target / COUNCIL_DIRNAME / "config.toml"
    if config_path.exists():
        try:
            data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            raise SystemExit(f"invalid TOML in {config_path}") from None
        council_cfg = data.get("council", {})
        require_git = coerce_bool(
            council_cfg.get("require_git"),
            True,
            "council.require_git",
        )
        if not require_git:
            return target, False

    raise SystemExit(
        f"{target} is not inside a git worktree. Use --allow-non-git to target a plain directory."
    )


def build_codex_command(repo_root: Path, codex_cfg: dict) -> list[str]:
    cmd = ["codex", "-C", str(repo_root)]
    if codex_cfg["model"]:
        cmd.extend(["--model", codex_cfg["model"]])
    if codex_cfg["model_reasoning_effort"]:
        cmd.extend(["-c", f'model_reasoning_effort="{codex_cfg["model_reasoning_effort"]}"'])
    if codex_cfg["dangerously_bypass_approvals_and_sandbox"]:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    if codex_cfg["no_alt_screen"]:
        cmd.append("--no-alt-screen")
    return cmd


def build_codex_fork_command(
    repo_root: Path,
    codex_cfg: dict,
    session_id: str,
) -> list[str]:
    cmd = ["codex", "fork", "-C", str(repo_root)]
    if codex_cfg["model"]:
        cmd.extend(["--model", codex_cfg["model"]])
    if codex_cfg["model_reasoning_effort"]:
        cmd.extend(["-c", f'model_reasoning_effort="{codex_cfg["model_reasoning_effort"]}"'])
    if codex_cfg["dangerously_bypass_approvals_and_sandbox"]:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    if codex_cfg["no_alt_screen"]:
        cmd.append("--no-alt-screen")
    cmd.append(session_id)
    return cmd


def build_codex_resume_command(
    repo_root: Path,
    codex_cfg: dict,
    session_id: str,
) -> list[str]:
    cmd = ["codex", "resume", "-C", str(repo_root)]
    if codex_cfg["model"]:
        cmd.extend(["--model", codex_cfg["model"]])
    if codex_cfg["model_reasoning_effort"]:
        cmd.extend(["-c", f'model_reasoning_effort="{codex_cfg["model_reasoning_effort"]}"'])
    if codex_cfg["dangerously_bypass_approvals_and_sandbox"]:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    if codex_cfg["no_alt_screen"]:
        cmd.append("--no-alt-screen")
    cmd.append(session_id)
    return cmd


def build_role_session_command(repo_root: Path, council_config: dict, role_state: dict | None) -> list[str]:
    role_state = role_state or {}
    codex_session_id = role_state.get("codex_session_id")
    fork_parent_session_id = role_state.get("fork_parent_session_id")
    bootstrap_mode = role_state.get("bootstrap_mode", "fresh")
    if isinstance(codex_session_id, str) and codex_session_id:
        return build_codex_resume_command(repo_root, council_config["codex"], codex_session_id)
    if bootstrap_mode == "fork" and isinstance(fork_parent_session_id, str) and fork_parent_session_id:
        return build_codex_fork_command(repo_root, council_config["codex"], fork_parent_session_id)
    return build_codex_command(repo_root, council_config["codex"])


def tmux_session_exists(name: str) -> bool:
    proc = subprocess.run(
        ["tmux", "has-session", "-t", name],
        text=True,
        capture_output=True,
    )
    return proc.returncode == 0


def tmux_new_session(name: str, workspace_root: Path, command: list[str], *, role: str) -> None:
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
                shlex.join(command),
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


def tmux_kill_session(name: str) -> None:
    subprocess.run(
        ["tmux", "kill-session", "-t", name],
        text=True,
        capture_output=True,
    )


def tmux_capture_pane(name: str) -> str:
    proc = subprocess.run(
        ["tmux", "capture-pane", "-p", "-t", name],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return f"[capture failed for {name}]\n{proc.stderr.strip()}\n"
    return proc.stdout


def tmux_capture_joined_pane(
    name: str, history_lines: int = TMUX_CAPTURE_HISTORY_LINES
) -> str:
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


def extract_terminal_summary_block(pane_text: str) -> str | None:
    lines = pane_text.splitlines()
    begin_indexes = [
        idx for idx, line in enumerate(lines) if line.strip() == TERMINAL_SUMMARY_BEGIN
    ]
    for begin_idx in reversed(begin_indexes):
        for end_idx in range(begin_idx + 1, len(lines)):
            if lines[end_idx].strip() == TERMINAL_SUMMARY_END:
                snippet = [line.rstrip() for line in lines[begin_idx + 1 : end_idx]]
                while snippet and not snippet[0].strip():
                    snippet.pop(0)
                while snippet and not snippet[-1].strip():
                    snippet.pop()
                return "\n".join(snippet).rstrip() if snippet else None
    return None


def last_non_empty_pane_line(pane_text: str) -> str:
    for line in reversed(pane_text.splitlines()):
        if line.strip():
            return line.rstrip()
    return ""


def pane_prompt_lines(pane_text: str) -> list[str]:
    return [
        line.rstrip()
        for line in pane_text.splitlines()
        if line.strip() and line.lstrip().startswith("›")
    ]


def pane_has_codex_footer(pane_text: str) -> bool:
    return bool(CODEX_FOOTER_RE.match(last_non_empty_pane_line(pane_text)))


def pane_looks_interactive(pane_text: str) -> bool:
    if pane_has_trust_prompt(pane_text):
        return False
    prompt_lines = pane_prompt_lines(pane_text)
    if not prompt_lines:
        return False
    return pane_has_codex_footer(pane_text) or "OpenAI Codex" in pane_text


def classify_tmux_pane(pane_text: str) -> str:
    if pane_has_trust_prompt(pane_text):
        return "trust_prompt"
    last_line = last_non_empty_pane_line(pane_text)
    if not last_line:
        return "not_ready"
    if CODEX_TRUST_CONTINUE_TEXT in pane_text:
        return "unknown_interstitial"
    prompt_lines = pane_prompt_lines(pane_text)
    if last_line.lstrip().startswith("›"):
        return "ready"
    if prompt_lines and pane_has_codex_footer(pane_text):
        return "ready"
    if prompt_lines:
        return "busy"
    return "not_ready"


def pane_shows_prompt(pane_text: str) -> bool:
    return classify_tmux_pane(pane_text) == "ready"


def pane_has_trust_prompt(pane_text: str) -> bool:
    return (
        CODEX_TRUST_PROMPT_TEXT in pane_text
        and CODEX_TRUST_CONTINUE_TEXT in pane_text
    )


def pane_has_context_overflow(pane_text: str) -> bool:
    lowered = pane_text.lower()
    return (
        "ran out of room in the model's context window" in lowered
        or "start a new thread or clear earlier history before retrying" in lowered
    )


def pane_fingerprint(pane_text: str) -> str:
    return hashlib.sha256(pane_text.encode("utf-8")).hexdigest()


def restart_role_session(
    tmux_name: str,
    *,
    repo_root: Path,
    council_config: dict,
    role_state: dict | None = None,
    role: str,
) -> None:
    tmux_kill_session(tmux_name)
    command = build_role_session_command(repo_root, council_config, role_state)
    tmux_new_session(
        tmux_name,
        repo_root,
        command,
        role=role,
    )


def wait_for_tmux_prompt(
    tmux_name: str, timeout_seconds: float, *, phase: str, role: str
) -> None:
    deadline = time.time() + timeout_seconds
    last_pane = ""
    if phase.endswith("_tmux_boot"):
        time.sleep(min(TMUX_BOOT_GRACE_SECONDS, timeout_seconds))
    while time.time() < deadline:
        if not tmux_session_exists(tmux_name):
            raise SupervisorRuntimeError(
                phase,
                f"tmux session disappeared: {tmux_name}",
                role=role,
            )
        last_pane = tmux_capture_pane(tmux_name)
        pane_state = classify_tmux_pane(last_pane)
        if pane_state == "trust_prompt":
            try:
                run_subprocess(["tmux", "send-keys", "-t", tmux_name, "Enter"])
            except subprocess.CalledProcessError as exc:
                raise SupervisorRuntimeError(
                    phase,
                    f"failed to dismiss trust prompt in tmux session {tmux_name}: {exc.stderr.strip() or exc}",
                    role=role,
                    details={
                        "command": exc.cmd,
                        "stderr": exc.stderr,
                        "stdout": exc.stdout,
                        "tmux_session": tmux_name,
                    },
                ) from exc
            time.sleep(TMUX_PASTE_SETTLE_SECONDS)
            continue
        if pane_state == "ready":
            return
        time.sleep(TMUX_PANE_POLL_SECONDS)
    if phase.endswith(("_tmux_boot", "_prompt_ready")) and pane_looks_interactive(last_pane):
        return
    raise SupervisorRuntimeError(
        phase,
        f"timed out waiting for Codex prompt in tmux session {tmux_name}",
        role=role,
        details={"pane_excerpt": last_pane[-4000:]},
    )


def tmux_send_prompt(tmux_name: str, prompt: str, *, phase: str, role: str) -> None:
    buffer_name = f"codex-council-{uuid.uuid4().hex}"
    try:
        before_pane = tmux_capture_pane(tmux_name)
        if classify_tmux_pane(before_pane) != "ready":
            raise SupervisorRuntimeError(
                phase,
                f"tmux session {tmux_name} was not ready to receive a prompt",
                role=role,
                details={"pane_excerpt": before_pane[-4000:], "tmux_session": tmux_name},
            )
        before_fingerprint = pane_fingerprint(before_pane)
        for _ in range(TMUX_PROMPT_DISPATCH_ATTEMPTS):
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
            time.sleep(TMUX_PROMPT_DISPATCH_CONFIRM_SECONDS)
            after_pane = tmux_capture_pane(tmux_name)
            after_state = classify_tmux_pane(after_pane)
            if pane_fingerprint(after_pane) != before_fingerprint or after_state != "ready":
                return
        raise SupervisorRuntimeError(
            phase,
            f"prompt send to tmux session {tmux_name} did not change pane state",
            role=role,
            details={
                "attempts": TMUX_PROMPT_DISPATCH_ATTEMPTS,
                "pane_excerpt": before_pane[-4000:],
                "tmux_session": tmux_name,
            },
        )
    finally:
        subprocess.run(
            ["tmux", "delete-buffer", "-b", buffer_name],
            text=True,
            capture_output=True,
        )


def turn_name(turn_number: int) -> str:
    return f"{turn_number:04d}"


def run_id_value() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def build_tmux_session_name(task_name: str, role: str, run_id: str) -> str:
    return f"codex-{role}-{task_name}-{run_id}"


def load_task_materials(task_root: Path) -> dict:
    inspection = inspect_task_workspace(task_root)
    materials = {
        "profile": inspection["profile"],
        "doc_paths": inspection["doc_paths"],
        "agents_path": task_root / "AGENTS.md",
        "agents_text": (task_root / "AGENTS.md").read_text(encoding="utf-8").strip(),
        "generator_path": task_root / "generator.instructions.md",
        "generator_text": (task_root / "generator.instructions.md").read_text(encoding="utf-8").strip(),
        "reviewer_path": task_root / "reviewer.instructions.md",
        "reviewer_text": (task_root / "reviewer.instructions.md").read_text(encoding="utf-8").strip(),
    }
    for doc_name, doc_path in inspection["doc_paths"].items():
        materials[f"{doc_name}_path"] = doc_path or (task_root / INPUT_DOC_FILENAMES.get(doc_name, f"{doc_name}.md"))
        materials[f"{doc_name}_text"] = doc_path.read_text(encoding="utf-8").strip() if doc_path else ""
    return materials


def canonical_task_paths(task_root: Path, inspection: dict | None = None) -> dict:
    inspection = inspection or inspect_task_workspace(task_root)
    paths: dict[str, Path] = {
        "agents": task_root / "AGENTS.md",
        "generator": task_root / "generator.instructions.md",
        "reviewer": task_root / "reviewer.instructions.md",
    }
    for doc_name, doc_path in inspection["doc_paths"].items():
        if doc_path is not None:
            paths[doc_name] = doc_path
    return paths


def format_fork_context_block(role_state: dict) -> str:
    if role_state.get("bootstrap_mode") != "fork":
        return ""
    return textwrap.dedent(
        """\
        Fork context:
        - This role session was forked from prior Codex chat context.
        - Treat the current repository state and the available canonical council files for this task as the primary instructions for this run.
        """
    ).rstrip()


def canonical_file_label(key: str) -> str:
    return CANONICAL_FILE_LABELS.get(key, f"{key}.md")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_context_manifest(task_root: Path) -> dict:
    inspection = inspect_task_workspace(task_root)
    manifest: dict[str, dict] = {
        "generated_at": now_ts(),
        "files": {},
        "profile": inspection["profile"],
    }
    for key, canonical_path in canonical_task_paths(
        task_root,
        inspection,
    ).items():
        text = canonical_path.read_text(encoding="utf-8")
        digest = hash_text(text)
        stat = canonical_path.stat()
        manifest["files"][key] = {
            "canonical_path": str(canonical_path),
            "sha256": digest,
            "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return manifest


def snapshot_context_manifest(run_dir: Path, task_root: Path) -> dict:
    return build_context_manifest(task_root)


def compare_context_manifests(previous_manifest: dict, current_manifest: dict) -> dict:
    previous_files = previous_manifest.get("files")
    current_files = current_manifest.get("files")
    if not isinstance(previous_files, dict):
        raise SystemExit("approved run context manifest is missing a valid `files` map")
    if not isinstance(current_files, dict):
        raise SystemExit("current context manifest is missing a valid `files` map")

    previous_keys = {key for key in CANONICAL_FILE_ORDER if key in previous_files}
    current_keys = {key for key in CANONICAL_FILE_ORDER if key in current_files}
    shared_keys = [key for key in CANONICAL_FILE_ORDER if key in previous_keys and key in current_keys]
    changed_shared_keys = [
        key
        for key in shared_keys
        if previous_files[key].get("sha256") != current_files[key].get("sha256")
    ]
    added_keys = [key for key in CANONICAL_FILE_ORDER if key in current_keys and key not in previous_keys]
    removed_keys = [key for key in CANONICAL_FILE_ORDER if key in previous_keys and key not in current_keys]
    return {
        "approved_profile": previous_manifest.get("profile"),
        "current_profile": current_manifest.get("profile"),
        "compared_existing_docs": [canonical_file_label(key) for key in shared_keys],
        "changed_existing_docs": [canonical_file_label(key) for key in changed_shared_keys],
        "added_docs": [canonical_file_label(key) for key in added_keys],
        "removed_docs": [canonical_file_label(key) for key in removed_keys],
        "docs_changed_since_approval": bool(changed_shared_keys or added_keys or removed_keys),
    }


def load_context_manifest(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing context manifest: {path}")
    manifest = load_json(path)
    if not isinstance(manifest, dict):
        raise SystemExit(f"invalid context manifest: {path}")
    return manifest


def build_reopen_doc_comparison(approved_turn_dir: Path, task_root: Path) -> dict:
    previous_manifest = load_context_manifest(context_manifest_path(approved_turn_dir))
    current_manifest = build_context_manifest(task_root)
    return compare_context_manifests(previous_manifest, current_manifest)


def write_reopen_metadata_artifact(run_dir: Path, reopen_metadata: dict) -> None:
    save_json(reopen_metadata_path(run_dir), reopen_metadata)


def append_reopen_index(repo_root: Path, reopen_metadata: dict) -> None:
    append_jsonl(reopen_index_path_for(repo_root), reopen_metadata)


def append_run_event(
    run_dir: Path,
    event: str,
    *,
    turn_number: int | None = None,
    role: str | None = None,
    details: dict | None = None,
) -> None:
    payload = {
        "timestamp": now_ts(),
        "event": event,
    }
    if turn_number is not None:
        payload["turn"] = turn_name(turn_number)
    if role is not None:
        payload["role"] = role
    if details:
        payload["details"] = details
    append_jsonl(events_path_for(run_dir), payload)


def save_turn_metadata(
    turn_dir: Path,
    turn_number: int,
    phase: str,
    *,
    role: str | None = None,
    details: dict | None = None,
) -> None:
    payload = {}
    path = turn_metadata_path(turn_dir)
    if path.exists():
        existing = load_json(path)
        for key in TURN_METADATA_AUDIT_KEYS:
            if key in existing:
                payload[key] = existing[key]
    payload.update(
        {
            "turn": turn_name(turn_number),
            "phase": phase,
            "updated_at": now_ts(),
        }
    )
    if role:
        payload["role"] = role
    if details:
        payload["details"] = details
    save_json(path, payload)


def load_turn_metadata(turn_dir: Path) -> dict:
    path = turn_metadata_path(turn_dir)
    if not path.exists():
        raise SystemExit(f"missing turn metadata: {path}")
    return load_json(path)


def annotate_turn_continuation(
    turn_dir: Path,
    *,
    continuation_source: str,
    selected_role: str,
    selected_turn: int,
    reason: str | None = None,
) -> None:
    metadata = load_turn_metadata(turn_dir) if turn_metadata_path(turn_dir).exists() else {}
    metadata["continuation_source"] = continuation_source
    if reason:
        metadata["continuation_reason"] = reason
    metadata["selected_role"] = selected_role
    metadata["selected_turn"] = turn_name(selected_turn)
    metadata["continued_at"] = now_ts()
    save_json(turn_metadata_path(turn_dir), metadata)


def prepare_turn(run_dir: Path, turn_number: int, task_root: Path) -> Path:
    current = turn_dir_for(run_dir, turn_number)
    ensure_dir(current)
    ensure_dir(role_dir_for(current, "generator"))
    ensure_dir(role_dir_for(current, "reviewer"))
    save_json(context_manifest_path(current), snapshot_context_manifest(run_dir, task_root))
    if not turn_metadata_path(current).exists():
        save_turn_metadata(current, turn_number, "initialized")
    return current


def role_artifact_paths(current_turn_dir: Path, role: str) -> tuple[Path, Path]:
    return (
        role_message_path(current_turn_dir, role),
        role_status_path(current_turn_dir, role),
    )


def load_status_file(path: Path, validator) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"missing status file: {path}")
    data = load_json(path)
    return validator(data)


def wait_for_role_artifacts(
    current_turn_dir: Path,
    role: str,
    *,
    validator,
    timeout_seconds: float,
    phase: str,
    tmux_name: str,
    turn_number: int,
    repo_root: Path,
    council_config: dict,
) -> tuple[Path, Path, dict]:
    artifact_path, status_path = role_artifact_paths(current_turn_dir, role)
    run_dir = current_turn_dir.parents[1]
    deadline = time.time() + timeout_seconds
    last_error = ""
    repair_attempts = 0
    session_recovery_attempts = 0
    last_invalid_fingerprint: tuple[int, int] | None = None
    while time.time() < deadline:
        if artifact_path.exists() and status_path.exists():
            fingerprint = (
                artifact_path.stat().st_mtime_ns,
                status_path.stat().st_mtime_ns,
            )
            try:
                status = load_status_file(status_path, validator)
                save_turn_metadata(
                    current_turn_dir,
                    turn_number,
                    f"{role}_artifacts_valid",
                    role=role,
                    details={
                        "message_path": str(artifact_path),
                        "status_path": str(status_path),
                    },
                )
                append_run_event(
                    run_dir,
                    f"{role}_artifacts_valid",
                    turn_number=turn_number,
                    role=role,
                    details={"status_path": str(status_path)},
                )
                return artifact_path, status_path, status
            except Exception as exc:
                last_error = str(exc)
                save_turn_metadata(
                    current_turn_dir,
                    turn_number,
                    f"{role}_artifacts_invalid",
                    role=role,
                    details={"error": last_error},
                )
                append_run_event(
                    run_dir,
                    f"{role}_artifacts_invalid",
                    turn_number=turn_number,
                    role=role,
                    details={"error": last_error},
                )
                if repair_attempts < ARTIFACT_REPAIR_ATTEMPTS and fingerprint != last_invalid_fingerprint:
                    repair_attempts += 1
                    last_invalid_fingerprint = fingerprint
                    write_validation_error_artifacts(
                        current_turn_dir,
                        role,
                        error_message=last_error,
                        attempt=repair_attempts,
                        message_path=artifact_path,
                        status_path=status_path,
                    )
                    repair_prompt = build_artifact_repair_prompt(
                        current_turn_dir,
                        role,
                        turn_number=turn_number,
                        error_message=last_error,
                    )
                    wait_for_tmux_prompt(
                        tmux_name,
                        timeout_seconds,
                        phase=f"{phase}_repair_prompt_ready",
                        role=role,
                    )
                    tmux_send_prompt(
                        tmux_name,
                        repair_prompt,
                        phase=f"{phase}_repair_prompt",
                        role=role,
                    )
                    append_run_event(
                        run_dir,
                        f"{role}_repair_requested",
                        turn_number=turn_number,
                        role=role,
                        details={"attempt": repair_attempts, "error": last_error},
                    )
                    time.sleep(TMUX_PASTE_SETTLE_SECONDS)
                    continue
                elif repair_attempts >= ARTIFACT_REPAIR_ATTEMPTS and fingerprint != last_invalid_fingerprint:
                    raise SupervisorRuntimeError(
                        "blocked_invalid_artifacts",
                        f"{role} artifacts remained invalid after {repair_attempts} repair attempt(s): {last_error}",
                        role=role,
                        details={
                            "artifact_path": str(artifact_path),
                            "status_path": str(status_path),
                            "last_error": last_error,
                        },
                    )
        pane_text = tmux_capture_pane(tmux_name)
        pane_state = classify_tmux_pane(pane_text)
        if (
            session_recovery_attempts < SESSION_RECOVERY_ATTEMPTS
            and pane_has_context_overflow(pane_text)
            and pane_state in {"ready", "busy"}
        ):
            session_recovery_attempts += 1
            repair_prompt = role_prompt_path(current_turn_dir, role).read_text(encoding="utf-8")
            append_run_event(
                run_dir,
                f"{role}_session_restarted_after_context_overflow",
                turn_number=turn_number,
                role=role,
                details={"attempt": session_recovery_attempts},
            )
            restart_role_session(
                tmux_name,
                repo_root=repo_root,
                council_config=council_config,
                role_state=(
                    load_json(run_dir / "state.json")["roles"].get(role, {})
                    if (run_dir / "state.json").exists()
                    else None
                ),
                role=role,
            )
            wait_for_tmux_prompt(
                tmux_name,
                timeout_seconds,
                phase=f"{phase}_session_restart_ready",
                role=role,
            )
            tmux_send_prompt(
                tmux_name,
                repair_prompt,
                phase=f"{phase}_session_restart_prompt",
                role=role,
            )
            time.sleep(TMUX_PASTE_SETTLE_SECONDS)
            continue
        time.sleep(ROLE_ARTIFACT_POLL_SECONDS)
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


def normalize_human_source(value, *, role: str):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{role} human_source must be one of: {', '.join(sorted(HUMAN_SOURCES))}"
        )
    normalized = value.strip()
    if normalized == "repo_state":
        return normalized
    source_name = Path(normalized).name
    if source_name in HUMAN_SOURCES:
        return source_name
    if normalized not in HUMAN_SOURCES:
        raise ValueError(
            f"{role} human_source must be one of: {', '.join(sorted(HUMAN_SOURCES))}"
        )
    return normalized


def normalize_optional_text(value, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string when present")
    normalized = value.strip()
    return normalized or None


def normalize_required_text(value, *, field_name: str) -> str:
    normalized = normalize_optional_text(value, field_name=field_name)
    if normalized is None:
        raise SystemExit(f"{field_name} must be a non-empty string")
    return normalized


def normalize_reopen_reason_kind(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(
            f"--reason-kind must be one of: {', '.join(sorted(REOPEN_REASON_KINDS))}"
        )
    normalized = value.strip()
    if normalized not in REOPEN_REASON_KINDS:
        raise SystemExit(
            f"--reason-kind must be one of: {', '.join(sorted(REOPEN_REASON_KINDS))}"
        )
    return normalized


def normalize_changed_files(value) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("generator changed_files must be a list of strings")
    normalized: list[str] = []
    for item in value:
        path_text = item.strip()
        if not path_text:
            raise ValueError("generator changed_files entries must be non-empty strings")
        if COUNCIL_DIRNAME in Path(path_text).parts:
            raise ValueError("generator changed_files must not include .codex-council runtime paths")
        normalized.append(path_text)
    return normalized


def critical_review_dimension_keys() -> tuple[str, ...]:
    return tuple(item["key"] for item in load_critical_review_dimensions())


def validate_generator_status(data: dict) -> dict:
    result = data.get("result")
    if not isinstance(result, str) or result not in GENERATOR_RESULTS:
        raise ValueError(f"invalid generator result: {result}")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("generator summary must be a non-empty string")
    changed_files = normalize_changed_files(data.get("changed_files", []))
    human_message = normalize_optional_text(
        data.get("human_message"),
        field_name="generator human_message",
    )
    human_source = normalize_optional_text(
        data.get("human_source"),
        field_name="generator human_source",
    )
    if result == "needs_human":
        if not human_message:
            raise ValueError("generator human_message must be a non-empty string when result is needs_human")
        human_source = normalize_human_source(human_source, role="generator")
    elif human_message is not None or human_source is not None:
        raise ValueError("generator human_message and human_source may only be set when result is needs_human")
    commit_sha = normalize_optional_text(data.get("commit_sha"), field_name="generator commit_sha")
    compare_base_sha = normalize_optional_text(
        data.get("compare_base_sha"),
        field_name="generator compare_base_sha",
    )
    branch = normalize_optional_text(data.get("branch"), field_name="generator branch")
    for field_name, value in {
        "commit_sha": commit_sha,
        "compare_base_sha": compare_base_sha,
        "branch": branch,
    }.items():
        if value is not None and not value:
            raise ValueError(f"generator {field_name} must be a non-empty string when present")
    return {
        "result": result,
        "summary": summary.strip(),
        "changed_files": changed_files,
        "commit_sha": commit_sha,
        "compare_base_sha": compare_base_sha,
        "branch": branch,
        "human_message": human_message,
        "human_source": human_source,
    }


def validate_reviewer_status(data: dict) -> dict:
    verdict = data.get("verdict")
    if not isinstance(verdict, str) or verdict not in REVIEWER_VERDICTS:
        raise ValueError(f"invalid reviewer verdict: {verdict}")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("reviewer summary must be a non-empty string")
    blocking_issues = data.get("blocking_issues", [])
    if not isinstance(blocking_issues, list) or not all(
        isinstance(item, str) for item in blocking_issues
    ):
        raise ValueError("reviewer blocking_issues must be a list of strings")
    human_message = normalize_optional_text(
        data.get("human_message"),
        field_name="reviewer human_message",
    )
    human_source = normalize_optional_text(
        data.get("human_source"),
        field_name="reviewer human_source",
    )
    if verdict == "needs_human":
        if not human_message:
            raise ValueError("reviewer human_message must be a non-empty string when verdict is needs_human")
        human_source = normalize_human_source(human_source, role="reviewer")
    elif human_message is not None or human_source is not None:
        raise ValueError("reviewer human_message and human_source may only be set when verdict is needs_human")
    reviewed_commit_sha = normalize_optional_text(
        data.get("reviewed_commit_sha"),
        field_name="reviewer reviewed_commit_sha",
    )
    critical_dimensions = data.get("critical_dimensions")
    if not isinstance(critical_dimensions, dict):
        raise ValueError("reviewer critical_dimensions must be a dict")
    normalized_dimensions: dict[str, str] = {}
    for key in critical_review_dimension_keys():
        value = critical_dimensions.get(key)
        if not isinstance(value, str) or value not in REVIEW_DIMENSION_STATUSES:
            raise ValueError(
                f"reviewer critical_dimensions.{key} must be one of: {', '.join(sorted(REVIEW_DIMENSION_STATUSES))}"
            )
        normalized_dimensions[key] = value
    if verdict == "approved":
        failing = [key for key, value in normalized_dimensions.items() if value != "pass"]
        if failing:
            raise ValueError(
                "reviewer approved verdict requires all critical review dimensions to be `pass`"
            )
    return {
        "verdict": verdict,
        "summary": summary.strip(),
        "blocking_issues": [item.strip() for item in blocking_issues],
        "reviewed_commit_sha": reviewed_commit_sha,
        "human_message": human_message,
        "human_source": human_source,
        "critical_dimensions": normalized_dimensions,
    }


def format_review_dimensions_block() -> str:
    return "\n".join(
        f"- [pass|fail|uncertain] {item['label']}"
        for item in load_critical_review_dimensions()
    )


def format_doc_paths_block(task_root: Path, inspection: dict, role: str) -> str:
    paths = canonical_task_paths(task_root, inspection)
    lines = []
    for doc_name in INPUT_DOC_ORDER:
        doc_path = inspection["doc_paths"].get(doc_name)
        if doc_path is not None:
            lines.append(f"- {doc_path}")
    lines.append(f"- {paths['agents']}")
    lines.append(f"- {paths[role]}")
    return "\n".join(lines).rstrip()


def format_reviewer_input_files_block(task_root: Path, inspection: dict, turn_dir: Path) -> str:
    lines = [format_doc_paths_block(task_root, inspection, "reviewer")]
    lines.extend(
        [
            f"- {role_message_path(turn_dir, 'generator')}",
            f"- {role_status_path(turn_dir, 'generator')}",
        ]
    )
    return "\n".join(lines).rstrip()


def format_bootstrap_reviewer_input_files_block(task_root: Path, inspection: dict) -> str:
    return format_doc_paths_block(task_root, inspection, "reviewer")


def format_generator_objective_block(inspection: dict) -> str:
    has_task = inspection["doc_paths"]["task"] is not None
    has_review = inspection["doc_paths"]["review"] is not None
    has_spec = inspection["doc_paths"]["spec"] is not None
    has_contract = inspection["doc_paths"]["contract"] is not None
    lines: list[str] = []
    if has_review:
        lines.extend(
            [
                "Treat the review document as a set of review findings, not unquestionable truth.",
                "Before changing code, classify each review point as `agree`, `disagree`, or `uncertain`.",
                "- Fix the points you agree are valid.",
                "- If you disagree with a point, do not implement it blindly. Explain the disagreement with concrete code evidence in `generator/message.md`.",
                "- If you are uncertain, investigate before changing code and surface the uncertainty explicitly if it remains.",
            ]
        )
    if has_task and has_spec:
        lines.append("Implement the requested work using `task.md` as the brief and `spec.md` as the detailed design reference.")
    elif has_task:
        lines.append("Implement the requested work described in `task.md`.")
    elif has_review:
        lines.append("Use the review findings as the starting brief for the fix.")
    if has_contract:
        lines.append("Use `contract.md` as an objective stop condition and do not claim completion if its relevant items are not satisfied.")
    lines.extend(
        [
            "Resolve root cause, not symptoms.",
            "Do not introduce bad code, new errors, unintended behavior, regressions, tech debt, or unnecessary complexity.",
            "Anticipate plausible future error cases and harden the change where reasonable.",
            "If the available documents are contradictory or too ambiguous to continue safely, emit `needs_human` instead of guessing.",
        ]
    )
    return "\n".join(lines).rstrip()


def format_review_bridge_block(state: dict) -> str:
    if review_bridge_mode(state) != "github_pr_codex":
        return ""
    github_state = state["review_bridge"]["github"]
    lines = [
        "GitHub PR review mode is enabled.",
        f"- Work on branch `{github_state['branch']}` and ensure the latest branch head is pushed before ending the turn.",
    ]
    if github_state.get("pr_url"):
        lines.append(f"- Reuse the existing PR: {github_state['pr_url']}")
    else:
        lines.append(
            f"- No PR has been resolved yet; after your push, the harness will reuse or create the PR for branch `{github_state['branch']}`."
        )
    lines.extend(
        [
            f"- The harness will post the `@codex` review request comment and poll GitHub for the response; do not perform that PR bookkeeping manually.",
            f"- The expected base branch for PR creation is `{github_state['base_branch']}`.",
        ]
    )
    return "\n".join(lines).rstrip()


def format_reopen_context_block(state: dict) -> str:
    reopen = state.get("reopen")
    if not isinstance(reopen, dict):
        return ""
    reopened_from = reopen.get("reopened_from", {})
    doc_comparison = reopen.get("doc_comparison", {})
    lines = [
        "Reopen context:",
        "- This run explicitly supersedes a prior approved run; do not treat that historical approval as the current source of truth.",
        f"- Reopened from run `{reopened_from.get('run_id', 'unknown')}` turn `{reopened_from.get('turn', 'unknown')}`.",
        f"- Reopen reason kind: `{reopen.get('reason_kind', 'unknown')}`.",
        f"- Reopen reason: {reopen.get('reason_message', '')}",
    ]
    if reopen.get("reason_kind") == "false_approved":
        lines.append("- Interpret the earlier approval as incorrect under the intended requirements that were in force at the time.")
    elif reopen.get("reason_kind") == "requirements_changed_after_approval":
        lines.append("- Interpret the earlier approval as historical only; the active canonical docs changed after approval and now supersede it.")
    docs_changed = doc_comparison.get("docs_changed_since_approval")
    if docs_changed is True:
        lines.append("- Canonical docs changed since that approval.")
        changed_existing = doc_comparison.get("changed_existing_docs") or []
        added_docs = doc_comparison.get("added_docs") or []
        removed_docs = doc_comparison.get("removed_docs") or []
        if changed_existing:
            lines.append("- Existing docs changed: " + ", ".join(f"`{name}`" for name in changed_existing))
        if added_docs:
            lines.append("- Docs added since approval: " + ", ".join(f"`{name}`" for name in added_docs))
        if removed_docs:
            lines.append("- Docs removed since approval: " + ", ".join(f"`{name}`" for name in removed_docs))
    elif docs_changed is False:
        lines.append("- Canonical docs compared against the approved run are unchanged.")
    return "\n".join(lines).rstrip()


def format_generator_message_requirements_block(inspection: dict) -> str:
    has_review = inspection["doc_paths"]["review"] is not None
    has_contract = inspection["doc_paths"]["contract"] is not None
    lines = []
    if has_review:
        lines.extend(
            [
                "- Findings triage:",
                "  - Agreed points",
                "  - Disagreed points",
                "  - Uncertain points",
            ]
        )
    lines.extend(
        [
            "- What changed",
            "- Commit created for this turn, or explicitly say that no repo-tracked files changed",
        ]
    )
    if has_review:
        lines.extend(
            [
                "- Which review findings or reviewer blockers were addressed",
                "- Evidence for rejected points",
            ]
        )
    else:
        lines.append("- Which task or spec requirements were addressed")
    if has_contract:
        lines.append("- Why those changes move the code toward satisfying `contract.md`")
        lines.append("- Remaining contract items not yet satisfied")
    lines.extend(
        [
            "- Why the changes avoid bad code, errors, unintended behavior, regressions, tech debt, and unnecessary complexity",
            "- Anticipated future error cases and how they were handled",
            "- Changed invariants / preserved invariants",
            "- Downstream readers / consumers checked",
            "- Verification performed",
            "- Known risks or blockers",
        ]
    )
    return "\n".join(lines).rstrip()


def format_reviewer_focus_block(inspection: dict) -> str:
    has_task = inspection["doc_paths"]["task"] is not None
    has_review = inspection["doc_paths"]["review"] is not None
    has_spec = inspection["doc_paths"]["spec"] is not None
    has_contract = inspection["doc_paths"]["contract"] is not None
    lines = ["Review the current repository state and the generator artifacts carefully."]
    if has_review:
        lines.extend(
            [
                "Use the review document as the starting findings set.",
                "Verify whether the cited issues were fixed, whether the generator rejected any points correctly, and whether new bugs or regressions were introduced while fixing them.",
                "If the generator disputes a blocker with concrete code evidence, adjudicate that disagreement explicitly.",
                "Do not repeat the same blocker without stronger evidence. If you cannot add stronger evidence, use `needs_human` instead of looping.",
            ]
        )
    if has_task and has_spec:
        lines.append("Verify the implementation matches both the brief in `task.md` and the detailed requirements in `spec.md`.")
    elif has_task:
        lines.append("Verify the implementation matches the brief in `task.md`.")
    if has_contract:
        lines.append("Treat `contract.md` as an objective approval bar. Approval is invalid if the relevant checklist items are not satisfied.")
    lines.extend(
        [
            "Focus on correctness, unintended behavior, regressions, state integrity, maintainability, test adequacy, tech debt, and unnecessary complexity.",
            "Look for fragile changes that are likely to cause future errors.",
        ]
    )
    return "\n".join(lines).rstrip()


def format_reviewer_message_requirements_block(inspection: dict) -> str:
    has_review = inspection["doc_paths"]["review"] is not None
    has_contract = inspection["doc_paths"]["contract"] is not None
    lines = ["- Verdict summary"]
    if has_review:
        lines.append("- Disagreement Adjudication")
    if has_contract:
        lines.append("- Contract checklist copied from `contract.md`, using `[x]` and `[ ]`")
    lines.extend(
        [
            "- Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`, one line for each of:",
            format_review_dimensions_block(),
            "- Blocking issues",
            "- Independent verification performed",
            "- Residual risks or follow-up notes",
        ]
    )
    return "\n".join(lines).rstrip()


def format_fork_bootstrap_review_block(task_root: Path) -> str:
    review_path = task_root / REVIEW_FILENAME
    return textwrap.dedent(
        f"""\
        This run started from forked chat context without a usable local {TASK_FILENAME}, {REVIEW_FILENAME}, or {SPEC_FILENAME}.
        Your first job is to distill the current fork/session context plus repository state into a local `{REVIEW_FILENAME}` at:
        - {review_path}

        In that file, capture concrete findings, blockers, or risks the generator should address next.
        Unless you must use `needs_human` or `blocked`, emit `changes_requested` so the next turn goes to the generator with the newly materialized review.
        """
    ).rstrip()


def build_continue_context(
    *,
    state: dict,
    previous_turn_dir: Path | None,
    role: str,
    inspection: dict,
) -> str:
    if previous_turn_dir is None:
        return ""
    previous_message = role_message_path(previous_turn_dir, role)
    previous_status = role_status_path(previous_turn_dir, role)
    if not previous_message.exists() or not previous_status.exists():
        alt_role = "generator" if role == "reviewer" else "reviewer"
        alt_message = role_message_path(previous_turn_dir, alt_role)
        alt_status = role_status_path(previous_turn_dir, alt_role)
        if alt_message.exists() and alt_status.exists():
            previous_message = alt_message
            previous_status = alt_status
    lines = [
        f"This run is continuing after `{state['status']}`.",
        "The human may have edited canonical task files and may also have discussed updates directly in this same session.",
    ]
    doc_names = []
    for doc_name in INPUT_DOC_ORDER:
        if inspection["doc_paths"][doc_name] is not None:
            doc_names.append(INPUT_DOC_FILENAMES[doc_name])
    if doc_names:
        lines.append(
            "Before proceeding, reread the current task documents "
            + ", ".join(f"`{name}`" for name in doc_names)
            + ", the council files, and any direct human guidance already present in this chat session."
        )
    else:
        lines.append(
            "Before proceeding, inspect the current repository state, the council files, and any direct human guidance already present in this chat session."
        )
    if previous_message.exists() and previous_status.exists():
        lines.extend(
            [
                "Reference the most recent completed turn artifacts if needed:",
                f"- {previous_message}",
                f"- {previous_status}",
            ]
        )
    return "\n".join(lines).rstrip()


def build_generator_turn_prompt(
    repo_root: Path,
    task_root: Path,
    turn_dir: Path,
    turn_number: int,
    task_name: str,
    *,
    state: dict,
    inspection: dict,
    inline_context: bool,
    continue_context_block: str = "",
    fork_context_block: str = "",
) -> str:
    previous_turn_dir = turn_dir.parent / turn_name(turn_number - 1)
    previous_reviewer_status_path = role_status_path(previous_turn_dir, "reviewer")
    previous_reviewer_status = None
    previous_reviewer_focus = ""
    if previous_reviewer_status_path.exists():
        try:
            previous_reviewer_status = validate_reviewer_status(
                load_json(previous_reviewer_status_path)
            )
        except Exception:
            previous_reviewer_status = None
    if previous_reviewer_status and previous_reviewer_status["verdict"] == "changes_requested":
        joined_issues = "\n".join(
            f"- {item}" for item in previous_reviewer_status["blocking_issues"]
        ) or "- Address the reviewer blocking issues from the previous turn."
        previous_reviewer_focus = textwrap.dedent(
            f"""\
            The previous reviewer verdict was `changes_requested`.
            Before coding, classify each reviewer blocking issue as `agree`, `disagree`, or `uncertain`.
            - Fix the issues you agree are valid.
            - If you disagree with a blocker, do not implement it blindly. Explain the disagreement with concrete code evidence in `generator/message.md`.
            - If you are uncertain, investigate before changing code, and surface the uncertainty explicitly if it remains.
            - Emit `needs_human` if the remaining blocker comes from ambiguous, contradictory, or unsafe task documents.

            Use `blocked` only for a real external implementation blocker unrelated to clarifying the task itself.

            Reviewer blocking issues to address:
            {joined_issues}
            """
        ).rstrip()
    values = {
        "repo_root": str(repo_root),
        "task_name": task_name,
        "turn_name": turn_name(turn_number),
        "continue_context_block": continue_context_block,
        "reopen_context_block": format_reopen_context_block(state),
        "fork_context_block": fork_context_block,
        "docs_to_read_block": format_doc_paths_block(task_root, inspection, "generator"),
        "review_bridge_block": format_review_bridge_block(state),
        "generator_objective_block": format_generator_objective_block(inspection),
        "generator_message_requirements_block": format_generator_message_requirements_block(inspection),
        "previous_reviewer_message_path": str(role_message_path(previous_turn_dir, "reviewer")),
        "previous_reviewer_status_path": str(previous_reviewer_status_path),
        "previous_reviewer_focus_block": previous_reviewer_focus,
        "generator_message_path": str(role_message_path(turn_dir, "generator")),
        "generator_status_path": str(role_status_path(turn_dir, "generator")),
    }
    template_name = "generator_initial.md" if inline_context else "generator_followup.md"
    return render_template_text(
        read_template("prompts", template_name),
        values,
        template_name=f"prompts/{template_name}",
    ).rstrip()


def build_reviewer_turn_prompt(
    repo_root: Path,
    task_root: Path,
    turn_dir: Path,
    turn_number: int,
    *,
    state: dict,
    inspection: dict,
    inline_context: bool,
    continue_context_block: str = "",
    fork_context_block: str = "",
    bootstrap_review_block: str = "",
) -> str:
    docs_to_read_block = (
        format_bootstrap_reviewer_input_files_block(task_root, inspection)
        if bootstrap_review_block
        else format_reviewer_input_files_block(task_root, inspection, turn_dir)
    )
    values = {
        "repo_root": str(repo_root),
        "task_name": task_root.name,
        "turn_name": turn_name(turn_number),
        "continue_context_block": continue_context_block,
        "reopen_context_block": format_reopen_context_block(state),
        "fork_context_block": fork_context_block,
        "docs_to_read_block": docs_to_read_block,
        "reviewer_focus_block": format_reviewer_focus_block(inspection),
        "reviewer_message_requirements_block": format_reviewer_message_requirements_block(inspection),
        "bootstrap_review_block": bootstrap_review_block,
        "generator_message_path": str(role_message_path(turn_dir, "generator")),
        "generator_status_path": str(role_status_path(turn_dir, "generator")),
        "reviewer_message_path": str(role_message_path(turn_dir, "reviewer")),
        "reviewer_status_path": str(role_status_path(turn_dir, "reviewer")),
    }
    if bootstrap_review_block:
        template_name = "reviewer_fork_bootstrap.md"
    else:
        template_name = "reviewer_initial.md" if inline_context else "reviewer_followup.md"
    return render_template_text(
        read_template("prompts", template_name),
        values,
        template_name=f"prompts/{template_name}",
    ).rstrip()


def write_prompt_artifact(turn_dir: Path, role: str, prompt: str) -> None:
    write_text(role_prompt_path(turn_dir, role), prompt)


def write_final_message_artifact(turn_dir: Path, role: str, message: str) -> None:
    write_text(role_message_path(turn_dir, role), message)


def write_raw_final_output_artifact(turn_dir: Path, role: str, tmux_name: str) -> None:
    # Trace/debug only. This file must never be used as a control signal.
    captured_text = ""
    try:
        wait_for_tmux_prompt(
            tmux_name,
            RAW_OUTPUT_CAPTURE_TIMEOUT_SECONDS,
            phase=f"{role}_raw_output_capture",
            role=role,
        )
        # Search the full recent pane history for summary markers. Looking only
        # at the last slice can miss a valid summary when Codex prints another
        # prompt line after the summary block.
        captured_text = tmux_capture_joined_pane(tmux_name)
    except SupervisorRuntimeError:
        captured_text = ""
    summary_text = extract_terminal_summary_block(captured_text)
    if summary_text:
        write_text(role_raw_output_path(turn_dir, role), summary_text)
        save_json(
            role_capture_status_path(turn_dir, role),
            {"status": "captured", "source": "terminal_summary_markers"},
        )
        return
    write_text(
        role_raw_output_path(turn_dir, role),
        "[terminal summary unavailable]\nSee capture_status.json for capture state.",
    )
    save_json(
        role_capture_status_path(turn_dir, role),
        {"status": "unavailable", "reason": "missing_terminal_summary_markers"},
    )


def write_validation_error_artifacts(
    turn_dir: Path,
    role: str,
    *,
    error_message: str,
    attempt: int,
    message_path: Path,
    status_path: Path,
) -> None:
    payload = {
        "attempt": attempt,
        "message": error_message,
        "message_path": str(message_path),
        "role": role,
        "status_path": str(status_path),
        "timestamp": now_ts(),
    }
    save_json(role_validation_error_json_path(turn_dir, role), payload)
    write_text(
        role_validation_error_md_path(turn_dir, role),
        textwrap.dedent(
            f"""\
            # Validation Error

            Attempt: {attempt}
            Role: {role}

            {error_message}

            Rewrite only:
            - {message_path}
            - {status_path}
            """
        ).rstrip(),
    )


def build_artifact_repair_prompt(
    turn_dir: Path,
    role: str,
    *,
    turn_number: int,
    error_message: str,
) -> str:
    return render_template_text(
        read_template("prompts", "artifact_repair.md"),
        {
            "role": role,
            "turn_name": turn_name(turn_number),
            "message_path": str(role_message_path(turn_dir, role)),
            "status_path": str(role_status_path(turn_dir, role)),
            "validation_error": error_message,
        },
        template_name="prompts/artifact_repair.md",
    ).rstrip()


def begin_turn_transition(
    run_dir: Path,
    state: dict,
    task_root: Path,
    *,
    from_turn: int,
    to_turn: int,
    from_role: str,
    to_role: str,
    source_verdict: str,
    reason: str | None = None,
) -> Path:
    next_turn_dir = prepare_turn(run_dir, to_turn, task_root)
    annotate_turn_continuation(
        next_turn_dir,
        continuation_source=source_verdict,
        selected_role=to_role,
        selected_turn=to_turn,
        reason=reason or f"{from_role} produced `{source_verdict}`; continue with {to_role} on turn {turn_name(to_turn)}.",
    )
    state["status"] = TRANSITIONING_TURN_STATUS
    state["current_turn"] = from_turn
    state["pending_turn"] = to_turn
    state["pending_role"] = to_role
    state["transition_source_verdict"] = source_verdict
    state["stop_reason"] = None
    save_run_state(run_dir, state)
    append_run_event(
        run_dir,
        "turn_transition_started",
        turn_number=from_turn,
        role=from_role,
        details={
            "from_role": from_role,
            "from_turn": turn_name(from_turn),
            "source_verdict": source_verdict,
            "to_role": to_role,
            "to_turn": turn_name(to_turn),
        },
    )
    return next_turn_dir


def pause_for_human(
    run_dir: Path,
    state: dict,
    *,
    role: str,
    turn_dir: Path,
    summary: str,
    human_message: str | None,
    human_source: str | None,
) -> None:
    turn_number = int(turn_dir.name)
    inspection = inspect_task_workspace(Path(state["task_root"]))
    state["status"] = "paused_needs_human"
    state["stop_reason"] = summary
    save_run_state(run_dir, state)
    save_turn_metadata(
        turn_dir,
        turn_number,
        "paused_needs_human",
        role=role,
        details={"summary": summary},
    )
    append_run_event(
        run_dir,
        "paused_needs_human",
        turn_number=turn_number,
        role=role,
        details={"summary": summary, "human_source": human_source},
    )
    print(f"{role} paused the council and requested human intervention.", flush=True)
    print(f"read: {role_message_path(turn_dir, role)}", flush=True)
    print(f"read: {role_status_path(turn_dir, role)}", flush=True)
    if human_source:
        print(f"human_source: {human_source}", flush=True)
    if human_message:
        print(f"human_message: {human_message}", flush=True)
    doc_names = [INPUT_DOC_FILENAMES[name] for name in INPUT_DOC_ORDER if inspection["doc_paths"][name] is not None]
    if doc_names:
        next_step = (
            "update "
            + " / ".join(doc_names + ["AGENTS.md", "role instructions"])
            + " as needed, then use `continue` to resume this run."
        )
    else:
        next_step = (
            f"add {TASK_FILENAME}, {REVIEW_FILENAME}, or {SPEC_FILENAME}, or update the council files as needed, then use `continue` to resume this run."
        )
    print(next_step, flush=True)


def create_run_state(
    *,
    repo_root: Path,
    task_root: Path,
    task_name: str,
    run_id: str,
    workspace_profile: str,
    council_config: dict,
    git_state: dict | None,
    generator_session: str,
    reviewer_session: str | None,
    review_bridge: dict,
    generator_bootstrap_mode: str = "fresh",
    reviewer_bootstrap_mode: str = "fresh",
    generator_fork_parent_session_id: str | None = None,
    reviewer_fork_parent_session_id: str | None = None,
    bootstrap_phase: str | None = None,
    reopen_context: dict | None = None,
) -> dict:
    run_dir = task_root / "runs" / run_id
    state = {
        "created_at": now_ts(),
        "council_config": council_config,
        "council_root": str(council_root_for(repo_root)),
        "current_turn": 1,
        "diagnostics_dir": str(run_dir / "diagnostics"),
        "git": git_state,
        "repo_root": str(repo_root),
        "review_bridge": review_bridge,
        "roles": {
            "generator": {
                "bootstrap_mode": generator_bootstrap_mode,
                "codex_session_id": None,
                "codex_thread_name": None,
                "fork_parent_session_id": generator_fork_parent_session_id,
                "last_wait_phase": None,
                "tmux_session": generator_session,
            },
            "reviewer": {
                "bootstrap_mode": reviewer_bootstrap_mode,
                "codex_session_id": None,
                "codex_thread_name": None,
                "fork_parent_session_id": reviewer_fork_parent_session_id,
                "last_wait_phase": None,
                "tmux_session": reviewer_session,
            },
        },
        "run_dir": str(run_dir),
        "run_id": run_id,
        "status": "booting",
        "stop_reason": None,
        "task_name": task_name,
        "task_root": str(task_root),
        "session_index_snapshot_ids": [],
        "workspace_profile": workspace_profile,
        "bootstrap_phase": bootstrap_phase,
        "pending_turn": None,
        "pending_role": None,
        "transition_source_verdict": None,
    }
    if reopen_context is not None:
        state["reopen"] = reopen_context
    return state


def validate_run_state(run_dir: Path, state: dict) -> None:
    required_keys = {"status", "run_id", "task_root", "roles"}
    if not required_keys.issubset(state.keys()):
        return
    status = state.get("status")
    if not isinstance(status, str) or not status:
        raise SupervisorRuntimeError(
            "invalid_run_state",
            "run state is missing a valid status",
            details={"state": state},
        )

    pending_turn = state.get("pending_turn")
    pending_role = state.get("pending_role")
    if status != TRANSITIONING_TURN_STATUS and (pending_turn is not None or pending_role is not None):
        raise SupervisorRuntimeError(
            "invalid_run_state",
            "pending turn metadata may only be present while transitioning turns",
            details={
                "status": status,
                "pending_turn": pending_turn,
                "pending_role": pending_role,
            },
        )

    if status in {"booting", "approved", "blocked", "paused_needs_human", "max_turns_reached"}:
        return

    current_turn = state.get("current_turn")
    if not isinstance(current_turn, int) or current_turn < 1:
        raise SupervisorRuntimeError(
            "invalid_run_state",
            "run state current_turn must be a positive integer",
            details={"status": status, "current_turn": current_turn},
        )

    current_turn_dir = turn_dir_for(run_dir, current_turn)
    if status == TRANSITIONING_TURN_STATUS:
        if not isinstance(pending_turn, int) or pending_turn <= current_turn:
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "transitioning turn state requires a pending_turn greater than current_turn",
                details={
                    "current_turn": current_turn,
                    "pending_turn": pending_turn,
                    "pending_role": pending_role,
                },
            )
        if pending_role not in ROLE_NAMES:
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "transitioning turn state requires a pending_role of generator or reviewer",
                details={"pending_role": pending_role},
            )
        if not turn_metadata_path(current_turn_dir).exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "transitioning turn state requires the current turn to be initialized",
                details={
                    "current_turn": current_turn,
                    "current_turn_dir": str(current_turn_dir),
                },
            )
        pending_turn_dir = turn_dir_for(run_dir, pending_turn)
        if not turn_metadata_path(pending_turn_dir).exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "transitioning turn state requires the pending turn to be initialized",
                details={
                    "pending_turn": pending_turn,
                    "pending_turn_dir": str(pending_turn_dir),
                },
            )
        return

    if status == "waiting_generator":
        if not turn_metadata_path(current_turn_dir).exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "waiting_generator requires the current turn to be initialized",
                details={"current_turn_dir": str(current_turn_dir)},
            )
        if not role_prompt_path(current_turn_dir, "generator").exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "waiting_generator requires a generator prompt artifact for the current turn",
                details={"prompt_path": str(role_prompt_path(current_turn_dir, "generator"))},
            )
        return

    if status == "waiting_reviewer":
        if not turn_metadata_path(current_turn_dir).exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "waiting_reviewer requires the current turn to be initialized",
                details={"current_turn_dir": str(current_turn_dir)},
            )
        if not role_prompt_path(current_turn_dir, "reviewer").exists():
            raise SupervisorRuntimeError(
                "invalid_run_state",
                "waiting_reviewer requires a reviewer prompt artifact for the current turn",
                details={"prompt_path": str(role_prompt_path(current_turn_dir, "reviewer"))},
            )
        return


def save_run_state(run_dir: Path, state: dict) -> None:
    validate_run_state(run_dir, state)
    save_json(run_dir / "state.json", state)


def resolve_fork_parent_session_ids(args: argparse.Namespace) -> tuple[str | None, str | None]:
    shared = normalize_optional_text(getattr(args, "fork_session_id", None), field_name="fork session id")
    generator = normalize_optional_text(
        getattr(args, "generator_fork_session_id", None),
        field_name="generator fork session id",
    )
    reviewer = normalize_optional_text(
        getattr(args, "reviewer_fork_session_id", None),
        field_name="reviewer fork session id",
    )
    if shared:
        generator = generator or shared
        reviewer = reviewer or shared
    return generator, reviewer


def has_any_fork_parent(generator_fork_id: str | None, reviewer_fork_id: str | None) -> bool:
    return bool(generator_fork_id or reviewer_fork_id)


def validate_task_workspace_for_start(task_root: Path, inspection: dict) -> None:
    errors: list[str] = []
    warnings: list[str] = []
    task_text = ""
    if inspection["doc_paths"]["task"] is not None:
        task_text = (task_root / TASK_FILENAME).read_text(encoding="utf-8")
        task_errors, task_warnings = lint_task_workspace_readiness(task_root)
        errors.extend(task_errors)
        warnings.extend(task_warnings)
    if inspection["doc_paths"]["review"] is not None:
        review_errors, review_warnings = lint_review_workspace_readiness(inspection["doc_paths"]["review"])
        errors.extend(review_errors)
        warnings.extend(review_warnings)
    if inspection["doc_paths"]["spec"] is not None:
        spec_errors, spec_warnings = lint_spec_workspace_readiness(task_root)
        errors.extend(spec_errors)
        warnings.extend(spec_warnings)
    if inspection["doc_paths"]["contract"] is not None:
        contract_errors, contract_warnings = lint_contract_workspace_readiness(task_root)
        errors.extend(contract_errors)
        warnings.extend(contract_warnings)
    if inspection["doc_paths"]["spec"] is not None and inspection["doc_paths"]["contract"] is None:
        errors.append(f"{SPEC_FILENAME} should be paired with {CONTRACT_FILENAME} so approval stays auditable")
    elif inspection["doc_paths"]["contract"] is None and inspection["present_docs"]:
        warnings.append(
            f"starting without {CONTRACT_FILENAME} removes the explicit approval bar; add it unless this task is truly trivial"
        )
    if task_text and inspection["doc_paths"]["spec"] is None and task_brief_requires_spec(task_text):
        errors.append(
            f"{TASK_FILENAME} looks broad enough and requires {SPEC_FILENAME}; add a spec or narrow the task brief before start"
        )
    if errors:
        formatted = "\n".join(f"- {item}" for item in errors)
        raise SystemExit(
            f"{task_root} is not ready for start.\n"
            f"Fix these issues first:\n{formatted}"
        )
    for warning in warnings:
        print(f"warning: {warning}")


def determine_start_role(
    *,
    inspection: dict,
    fork_enabled: bool,
    requested_role: str,
) -> tuple[str, str | None]:
    if requested_role not in {"auto", "generator", "reviewer"}:
        raise SystemExit("--start-role must be one of: auto, generator, reviewer")
    has_task = inspection["doc_paths"]["task"] is not None
    has_review = inspection["doc_paths"]["review"] is not None
    has_spec = inspection["doc_paths"]["spec"] is not None
    has_docs = bool(inspection["present_docs"])

    if requested_role == "generator":
        if has_task or has_review or has_spec:
            return "generator", None
        raise SystemExit(f"cannot start with generator without a local {TASK_FILENAME}, {REVIEW_FILENAME}, or {SPEC_FILENAME}")

    if requested_role == "reviewer":
        if has_docs:
            return "reviewer", None
        if fork_enabled:
            return "reviewer", "fork_to_review"
        raise SystemExit(f"cannot start with reviewer without a local document or fork session id")

    if has_review:
        return "generator", None
    if has_task:
        return "generator", None
    if fork_enabled:
        return "reviewer", "fork_to_review"
    raise SystemExit(
        f"no local input documents found for {inspection['profile']}.\n"
        f"Create {TASK_FILENAME}, {REVIEW_FILENAME}, or {SPEC_FILENAME}, or start from a fork session."
    )


def build_review_write_path(task_root: Path) -> Path:
    return task_root / REVIEW_FILENAME


def normalize_review_mode(args: argparse.Namespace) -> str:
    mode = getattr(args, "review_mode", "internal")
    github_options_present = any(
        getattr(args, field, None)
        for field in ("github_pr", "github_branch", "github_base")
    )
    if mode == "internal" and github_options_present:
        mode = "github_pr_codex"
    if mode not in REVIEW_MODES:
        raise SystemExit(
            f"--review-mode must be one of: {', '.join(sorted(REVIEW_MODES))}"
        )
    return mode


def review_bridge_mode(state: dict) -> str:
    review_bridge = state.get("review_bridge", {})
    mode = review_bridge.get("mode", "internal")
    return mode if mode in REVIEW_MODES else "internal"


def role_uses_tmux(state: dict, role: str) -> bool:
    return not (role == "reviewer" and review_bridge_mode(state) == "github_pr_codex")


def active_tmux_roles(state: dict) -> tuple[str, ...]:
    return tuple(role for role in ROLE_NAMES if role_uses_tmux(state, role))


def parse_github_pr_ref(value: str) -> dict:
    normalized = value.strip()
    if not normalized:
        raise SystemExit("--github-pr must be a pull request number or URL")
    if normalized.isdigit():
        return {
            "ref": normalized,
            "number": int(normalized),
            "repo_name_with_owner": None,
        }
    match = GITHUB_PR_URL_RE.match(normalized)
    if match:
        owner, repo, number = match.groups()
        return {
            "ref": normalized,
            "number": int(number),
            "repo_name_with_owner": f"{owner}/{repo}",
        }
    raise SystemExit("--github-pr must be a pull request number or GitHub pull request URL")


def load_github_repo_metadata(repo_root: Path) -> dict:
    data = gh_json(
        repo_root,
        ["repo", "view", "--json", "defaultBranchRef,nameWithOwner,url"],
        phase="github_repo_view",
    )
    name_with_owner = data.get("nameWithOwner")
    repo_url = data.get("url")
    default_branch_ref = data.get("defaultBranchRef")
    default_branch = (
        default_branch_ref.get("name")
        if isinstance(default_branch_ref, dict)
        else None
    )
    if (
        not isinstance(name_with_owner, str)
        or not name_with_owner.strip()
        or not isinstance(repo_url, str)
        or not repo_url.strip()
        or not isinstance(default_branch, str)
        or not default_branch.strip()
    ):
        raise SupervisorRuntimeError(
            "github_repo_view",
            "gh repo view returned incomplete repository metadata",
            role="reviewer",
            details={"response": data},
        )
    owner, repo = name_with_owner.split("/", 1)
    return {
        "default_branch": default_branch.strip(),
        "name_with_owner": name_with_owner.strip(),
        "owner": owner,
        "repo": repo,
        "url": repo_url.strip(),
    }


def _normalize_github_pr_payload(data: dict) -> dict:
    number = data.get("number")
    url = data.get("url")
    head_ref_name = data.get("headRefName")
    base_ref_name = data.get("baseRefName")
    head_ref_oid = data.get("headRefOid")
    title = data.get("title")
    if (
        not isinstance(number, int)
        or not isinstance(url, str)
        or not url.strip()
        or not isinstance(head_ref_name, str)
        or not head_ref_name.strip()
        or not isinstance(base_ref_name, str)
        or not base_ref_name.strip()
        or not isinstance(head_ref_oid, str)
        or not head_ref_oid.strip()
    ):
        raise SupervisorRuntimeError(
            "github_pr_payload",
            "GitHub pull request metadata was incomplete",
            role="reviewer",
            details={"response": data},
        )
    return {
        "number": number,
        "url": url.strip(),
        "head_ref_name": head_ref_name.strip(),
        "base_ref_name": base_ref_name.strip(),
        "head_ref_oid": head_ref_oid.strip(),
        "title": title.strip() if isinstance(title, str) and title.strip() else None,
    }


def resolve_github_pr_reference(repo_root: Path, pr_ref: str) -> dict:
    data = gh_json(
        repo_root,
        [
            "pr",
            "view",
            pr_ref,
            "--json",
            "baseRefName,headRefName,headRefOid,number,title,url",
        ],
        phase="github_pr_resolve",
    )
    return _normalize_github_pr_payload(data)


def find_existing_github_pr_for_branch(repo_root: Path, branch: str) -> dict | None:
    data = gh_json(
        repo_root,
        [
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "open",
            "--limit",
            "10",
            "--json",
            "baseRefName,headRefName,headRefOid,number,title,updatedAt,url",
        ],
        phase="github_pr_lookup",
    )
    if not isinstance(data, list):
        raise SupervisorRuntimeError(
            "github_pr_lookup",
            "gh pr list returned invalid data",
            role="reviewer",
            details={"response": data},
        )
    candidates = [
        _normalize_github_pr_payload(item)
        | {
            "updated_at": item.get("updatedAt")
            if isinstance(item.get("updatedAt"), str)
            else "",
        }
        for item in data
        if isinstance(item, dict)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["updated_at"], item["number"]), reverse=True)
    return candidates[0]


def extract_task_request_summary(task_root: Path) -> str:
    task_path = task_root / TASK_FILENAME
    if task_path.exists():
        in_request = False
        for line in task_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "## Request":
                in_request = True
                continue
            if in_request and stripped.startswith("## "):
                break
            if in_request and stripped:
                return stripped.lstrip("-* ").strip()
    return task_root.name.replace("-", " ")


def build_github_pr_create_title(task_root: Path) -> str:
    summary = extract_task_request_summary(task_root)
    return summary[:120] if summary else task_root.name


def build_github_pr_create_body(task_root: Path, run_id: str) -> str:
    return textwrap.dedent(
        f"""\
        Automated PR opened by codex-council for task `{task_root.name}`.

        - Council workspace: `{task_root}`
        - Run: `{run_id}`
        """
    ).rstrip()


def create_github_pr(
    repo_root: Path,
    *,
    branch: str,
    base_branch: str,
    title: str,
    body: str,
) -> dict:
    if branch == base_branch:
        raise SupervisorRuntimeError(
            "github_pr_create",
            f"cannot create a pull request when branch `{branch}` and base `{base_branch}` are the same",
            role="reviewer",
            details={"branch": branch, "base_branch": base_branch},
        )
    proc = gh_run(
        repo_root,
        [
            "pr",
            "create",
            "--head",
            branch,
            "--base",
            base_branch,
            "--title",
            title,
            "--body",
            body,
        ],
        phase="github_pr_create",
    )
    created_url = next(
        (line.strip() for line in reversed(proc.stdout.splitlines()) if line.strip()),
        "",
    )
    if not created_url:
        raise SupervisorRuntimeError(
            "github_pr_create",
            "gh pr create did not return a pull request URL",
            role="reviewer",
            details={"stdout": proc.stdout},
        )
    return resolve_github_pr_reference(repo_root, created_url)


def resolve_pushed_branch_head_sha(repo_root: Path, branch: str) -> str:
    local_head_sha = git_head_sha(repo_root)
    upstream_proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"],
        text=True,
        capture_output=True,
    )
    if upstream_proc.returncode == 0 and upstream_proc.stdout.strip():
        upstream_ref = upstream_proc.stdout.strip()
        upstream_sha = git_stdout(repo_root, "rev-parse", upstream_ref)
        if upstream_sha == local_head_sha:
            return upstream_sha
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"branch `{branch}` is not pushed at the current HEAD `{local_head_sha}`",
            role="reviewer",
            details={
                "branch": branch,
                "local_head_sha": local_head_sha,
                "upstream_ref": upstream_ref,
                "upstream_sha": upstream_sha,
            },
        )

    remotes = [line.strip() for line in git_stdout(repo_root, "remote").splitlines() if line.strip()]
    remote_name = "origin" if "origin" in remotes else (remotes[0] if len(remotes) == 1 else None)
    if not remote_name:
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"branch `{branch}` has no configured upstream or resolvable git remote",
            role="reviewer",
            details={"branch": branch, "remotes": remotes},
        )
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "ls-remote", "--heads", remote_name, branch],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"failed to inspect remote branch `{branch}` on `{remote_name}`: {proc.stderr.strip() or proc.stdout.strip()}",
            role="reviewer",
            details={
                "branch": branch,
                "remote": remote_name,
                "stderr": proc.stderr,
                "stdout": proc.stdout,
            },
        )
    remote_line = next((line for line in proc.stdout.splitlines() if line.strip()), "")
    if not remote_line:
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"branch `{branch}` is not pushed to remote `{remote_name}`",
            role="reviewer",
            details={"branch": branch, "remote": remote_name},
        )
    remote_sha = remote_line.split()[0]
    if remote_sha != local_head_sha:
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"branch `{branch}` is pushed to `{remote_name}`, but the remote HEAD does not match local HEAD `{local_head_sha}`",
            role="reviewer",
            details={
                "branch": branch,
                "local_head_sha": local_head_sha,
                "remote": remote_name,
                "remote_sha": remote_sha,
            },
        )
    return remote_sha


def build_review_bridge_state(
    repo_root: Path,
    task_root: Path,
    git_state: dict | None,
    args: argparse.Namespace,
) -> dict:
    mode = normalize_review_mode(args)
    if mode == "internal":
        return {"mode": "internal"}
    if git_state is None:
        raise SystemExit("github_pr_codex review mode requires a git worktree")
    if getattr(args, "start_role", "auto") == "reviewer":
        raise SystemExit("github_pr_codex review mode cannot start with reviewer")
    repo_meta = load_github_repo_metadata(repo_root)
    github_pr_value = normalize_optional_text(
        getattr(args, "github_pr", None),
        field_name="github pr",
    )
    github_branch_value = normalize_optional_text(
        getattr(args, "github_branch", None),
        field_name="github branch",
    )
    github_base_value = normalize_optional_text(
        getattr(args, "github_base", None),
        field_name="github base",
    )

    pr_number = None
    pr_url = None
    pr_head_sha = None
    branch_source = "auto"
    branch = github_branch_value or git_state["current_branch"]
    base_branch = github_base_value or repo_meta["default_branch"]

    if github_pr_value:
        parsed_pr = parse_github_pr_ref(github_pr_value)
        if (
            parsed_pr["repo_name_with_owner"]
            and parsed_pr["repo_name_with_owner"] != repo_meta["name_with_owner"]
        ):
            raise SystemExit(
                f"provided PR repo `{parsed_pr['repo_name_with_owner']}` does not match target repo `{repo_meta['name_with_owner']}`"
            )
        pr_info = resolve_github_pr_reference(repo_root, parsed_pr["ref"])
        if github_branch_value and github_branch_value != pr_info["head_ref_name"]:
            raise SystemExit(
                f"--github-branch `{github_branch_value}` does not match PR head branch `{pr_info['head_ref_name']}`"
            )
        branch = pr_info["head_ref_name"]
        base_branch = pr_info["base_ref_name"]
        branch_source = "pr"
        pr_number = pr_info["number"]
        pr_url = pr_info["url"]
        pr_head_sha = pr_info["head_ref_oid"]
    else:
        branch_source = "explicit" if github_branch_value else "auto"
        existing_pr = find_existing_github_pr_for_branch(repo_root, branch)
        if existing_pr is not None:
            pr_number = existing_pr["number"]
            pr_url = existing_pr["url"]
            base_branch = existing_pr["base_ref_name"]
            pr_head_sha = existing_pr["head_ref_oid"]

    return {
        "mode": "github_pr_codex",
        "github": {
            "base_branch": base_branch,
            "branch": branch,
            "branch_source": branch_source,
            "last_consumed_review_comment_body_sha256": None,
            "last_consumed_review_comment_created_at": None,
            "last_consumed_review_comment_id": None,
            "last_consumed_review_turn": None,
            "last_observed_head_sha": pr_head_sha,
            "last_request_comment_created_at": None,
            "last_request_comment_id": None,
            "last_request_turn": None,
            "pr_head_sha": pr_head_sha,
            "pr_number": pr_number,
            "pr_url": pr_url,
            "repo_name_with_owner": repo_meta["name_with_owner"],
            "repo_owner": repo_meta["owner"],
            "repo": repo_meta["repo"],
            "repo_url": repo_meta["url"],
            "review_wait": {
                "deadline_at": None,
                "initial_wait_seconds": GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                "last_polled_at": None,
                "poll_count": 0,
                "poll_interval_seconds": GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                "started_at": None,
            },
        },
    }


def record_current_git_state(run_dir: Path, state: dict) -> tuple[str | None, str | None]:
    if not state.get("git"):
        return None, None
    repo_root = Path(state["repo_root"])
    current_branch = git_current_branch(repo_root)
    head_sha = git_head_sha(repo_root)
    state["git"]["current_branch"] = current_branch
    state["git"]["last_generator_commit_sha"] = head_sha
    save_run_state(run_dir, state)
    return current_branch, head_sha


def sync_github_review_branch_state(run_dir: Path, state: dict) -> tuple[str, str]:
    repo_root = Path(state["repo_root"])
    current_branch = git_current_branch(repo_root)
    head_sha = git_head_sha(repo_root)
    github_state = state["review_bridge"]["github"]
    expected_branch = github_state["branch"]
    if current_branch != expected_branch:
        if github_state.get("pr_number") is None and github_state.get("branch_source") == "auto":
            github_state["branch"] = current_branch
        else:
            raise SupervisorRuntimeError(
                "github_branch_mismatch",
                f"current git branch `{current_branch}` does not match the GitHub review branch `{expected_branch}`",
                role="reviewer",
                details={
                    "current_branch": current_branch,
                    "expected_branch": expected_branch,
                },
            )
    github_state["last_observed_head_sha"] = head_sha
    if state.get("git"):
        state["git"]["current_branch"] = current_branch
        state["git"]["last_generator_commit_sha"] = head_sha
    save_run_state(run_dir, state)
    return current_branch, head_sha


def ensure_github_pr_ready(
    run_dir: Path,
    state: dict,
    task_root: Path,
    turn_number: int,
) -> dict:
    current_branch, current_head_sha = sync_github_review_branch_state(run_dir, state)
    repo_root = Path(state["repo_root"])
    github_state = state["review_bridge"]["github"]
    created = False
    if github_state.get("pr_number"):
        pr_info = resolve_github_pr_reference(repo_root, str(github_state["pr_number"]))
    else:
        pr_info = find_existing_github_pr_for_branch(repo_root, current_branch)
        if pr_info is None:
            resolve_pushed_branch_head_sha(repo_root, current_branch)
            pr_info = create_github_pr(
                repo_root,
                branch=current_branch,
                base_branch=github_state["base_branch"],
                title=build_github_pr_create_title(task_root),
                body=build_github_pr_create_body(task_root, state["run_id"]),
            )
            created = True
    if pr_info["head_ref_name"] != current_branch:
        raise SupervisorRuntimeError(
            "github_branch_mismatch",
            f"GitHub PR #{pr_info['number']} targets branch `{pr_info['head_ref_name']}`, but the local branch is `{current_branch}`",
            role="reviewer",
            details={
                "current_branch": current_branch,
                "pr_head_ref_name": pr_info["head_ref_name"],
                "pr_number": pr_info["number"],
            },
        )
    if pr_info["head_ref_oid"] != current_head_sha:
        raise SupervisorRuntimeError(
            "github_branch_not_pushed",
            f"GitHub PR #{pr_info['number']} is still at `{pr_info['head_ref_oid']}` instead of local HEAD `{current_head_sha}`; push branch `{current_branch}` before review can continue",
            role="reviewer",
            details={
                "current_branch": current_branch,
                "current_head_sha": current_head_sha,
                "pr_head_ref_oid": pr_info["head_ref_oid"],
                "pr_number": pr_info["number"],
            },
        )
    github_state["base_branch"] = pr_info["base_ref_name"]
    github_state["branch"] = pr_info["head_ref_name"]
    github_state["pr_head_sha"] = pr_info["head_ref_oid"]
    github_state["pr_number"] = pr_info["number"]
    github_state["pr_url"] = pr_info["url"]
    save_run_state(run_dir, state)
    append_run_event(
        run_dir,
        "github_pr_created" if created else "github_pr_reused",
        turn_number=turn_number,
        role="reviewer",
        details={
            "branch": github_state["branch"],
            "pr_number": github_state["pr_number"],
            "pr_url": github_state["pr_url"],
        },
    )
    return pr_info


def build_github_codex_request_comment(state: dict, turn_number: int, commit_sha: str) -> str:
    github_state = state["review_bridge"]["github"]
    return textwrap.dedent(
        f"""\
        @codex review

        Please review the latest PR state for blocking correctness issues, regressions, failure modes, and missing tests.

        - Task: {state['task_name']}
        - Run: {state['run_id']}
        - Turn: {turn_name(turn_number)}
        - Branch: {github_state['branch']}
        - Commit: {commit_sha}

        Reply with a new PR comment that starts with `{GITHUB_CODEX_REVIEW_PREFIX}`.
        """
    ).rstrip()


def post_github_pr_review_request_comment(
    run_dir: Path,
    state: dict,
    turn_number: int,
    commit_sha: str,
) -> dict:
    repo_root = Path(state["repo_root"])
    github_state = state["review_bridge"]["github"]
    pr_number = github_state.get("pr_number")
    if not isinstance(pr_number, int):
        raise SupervisorRuntimeError(
            "github_review_request_post",
            "cannot post a GitHub review request without a PR number",
            role="reviewer",
        )
    request_body = build_github_codex_request_comment(state, turn_number, commit_sha)
    response = gh_json(
        repo_root,
        [
            "api",
            f"repos/{github_state['repo_owner']}/{github_state['repo']}/issues/{pr_number}/comments",
            "-f",
            f"body={request_body}",
        ],
        phase="github_review_request_post",
    )
    comment_id = response.get("id")
    created_at = response.get("created_at")
    html_url = response.get("html_url")
    if (
        not isinstance(comment_id, int)
        or not isinstance(created_at, str)
        or not created_at.strip()
    ):
        raise SupervisorRuntimeError(
            "github_review_request_post",
            "GitHub did not return the posted request comment metadata",
            role="reviewer",
            details={"response": response},
        )
    github_state["last_request_comment_id"] = comment_id
    github_state["last_request_comment_created_at"] = created_at.strip()
    github_state["last_request_turn"] = turn_name(turn_number)
    github_state["review_wait"] = {
        "deadline_at": None,
        "initial_wait_seconds": GITHUB_CODEX_INITIAL_WAIT_SECONDS,
        "last_polled_at": None,
        "poll_count": 0,
        "poll_interval_seconds": GITHUB_CODEX_POLL_INTERVAL_SECONDS,
        "started_at": None,
    }
    save_run_state(run_dir, state)
    append_run_event(
        run_dir,
        "github_review_request_posted",
        turn_number=turn_number,
        role="reviewer",
        details={
            "comment_id": comment_id,
            "comment_url": html_url if isinstance(html_url, str) else None,
            "pr_number": pr_number,
        },
    )
    return {
        "body": request_body,
        "created_at": created_at.strip(),
        "html_url": html_url.strip() if isinstance(html_url, str) and html_url.strip() else None,
        "id": comment_id,
    }


def list_github_pr_issue_comments(
    repo_root: Path,
    *,
    owner: str,
    repo: str,
    pr_number: int,
) -> list[dict]:
    response = gh_json(
        repo_root,
        [
            "api",
            "--paginate",
            "--slurp",
            f"repos/{owner}/{repo}/issues/{pr_number}/comments?per_page=100",
        ],
        phase="github_review_poll",
    )
    pages = response if isinstance(response, list) else [response]
    comments: list[dict] = []
    for page in pages:
        if isinstance(page, list):
            comments.extend(item for item in page if isinstance(item, dict))
        elif isinstance(page, dict):
            comments.append(page)
    return comments


def extract_github_review_blocking_issues(comment_body: str) -> list[str]:
    bullets: list[str] = []
    for line in comment_body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(GITHUB_CODEX_REVIEW_PREFIX):
            continue
        if REVIEW_ITEM_RE.match(stripped):
            bullets.append(stripped)
            continue
        numbered = re.match(r"^\d+\.\s+\S", stripped)
        if numbered:
            bullets.append(stripped)
    if bullets:
        return bullets
    paragraphs = [line.strip() for line in comment_body.splitlines() if line.strip()]
    if len(paragraphs) > 1:
        return [paragraphs[1][:300]]
    if paragraphs:
        return [paragraphs[0][:300]]
    return ["GitHub Codex requested changes."]


def select_latest_unconsumed_github_codex_review_comment(
    comments: list[dict],
    *,
    request_comment_id: int | None,
    request_comment_created_at: str | None,
    last_consumed_comment_id: int | None,
    latest_allowed_created_at: str | None = None,
) -> dict | None:
    candidates: list[dict] = []
    latest_allowed_created_at_epoch = parse_utc_timestamp(latest_allowed_created_at)
    for comment in comments:
        comment_id = comment.get("id")
        body = comment.get("body")
        created_at = comment.get("created_at")
        created_at_epoch = parse_utc_timestamp(created_at if isinstance(created_at, str) else None)
        if (
            not isinstance(comment_id, int)
            or not isinstance(body, str)
            or not isinstance(created_at, str)
            or created_at_epoch is None
        ):
            continue
        if request_comment_id is not None and comment_id <= request_comment_id:
            continue
        if last_consumed_comment_id is not None and comment_id == last_consumed_comment_id:
            continue
        if request_comment_created_at and created_at < request_comment_created_at:
            continue
        if (
            latest_allowed_created_at_epoch is not None
            and created_at_epoch > latest_allowed_created_at_epoch
        ):
            continue
        if not body.lstrip().startswith(GITHUB_CODEX_REVIEW_PREFIX):
            continue
        candidates.append(comment)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item.get("created_at", ""), item.get("id", 0)))
    return candidates[-1]


def wait_for_new_github_codex_review_comment(
    run_dir: Path,
    state: dict,
    turn_number: int,
    *,
    timeout_seconds: float,
    reuse_existing_request: bool = False,
) -> dict:
    if timeout_seconds < GITHUB_CODEX_INITIAL_WAIT_SECONDS:
        raise SupervisorRuntimeError(
            "github_review_timeout_config",
            f"github_pr_codex review mode requires turn_timeout_seconds >= {GITHUB_CODEX_INITIAL_WAIT_SECONDS}",
            role="reviewer",
            details={"turn_timeout_seconds": timeout_seconds},
        )
    repo_root = Path(state["repo_root"])
    github_state = state["review_bridge"]["github"]
    pr_number = github_state.get("pr_number")
    request_comment_id = github_state.get("last_request_comment_id")
    request_comment_created_at = github_state.get("last_request_comment_created_at")
    if not isinstance(pr_number, int) or not isinstance(request_comment_id, int):
        raise SupervisorRuntimeError(
            "github_review_poll",
            "cannot poll GitHub review comments before posting a request comment",
            role="reviewer",
            details={
                "pr_number": pr_number,
                "request_comment_id": request_comment_id,
            },
        )
    wait_state = github_state["review_wait"]
    request_created_at_epoch = parse_utc_timestamp(request_comment_created_at)
    if not reuse_existing_request:
        started_at_epoch = request_created_at_epoch or time.time()
        wait_state["started_at"] = ts_from_epoch(started_at_epoch)
        wait_state["deadline_at"] = ts_from_epoch(started_at_epoch + timeout_seconds)
        wait_state["last_polled_at"] = None
        wait_state["poll_count"] = 0
        save_run_state(run_dir, state)
        append_run_event(
            run_dir,
            "github_review_wait_started",
            turn_number=turn_number,
            role="reviewer",
            details={
                "initial_wait_seconds": GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                "poll_interval_seconds": GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                "pr_number": pr_number,
            },
        )
    else:
        started_at_epoch = (
            parse_utc_timestamp(wait_state.get("started_at"))
            or request_created_at_epoch
            or time.time()
        )
        deadline_epoch = parse_utc_timestamp(wait_state.get("deadline_at"))
        if deadline_epoch is None:
            deadline_epoch = started_at_epoch + timeout_seconds
            wait_state["deadline_at"] = ts_from_epoch(deadline_epoch)
        wait_state["started_at"] = ts_from_epoch(started_at_epoch)
        save_run_state(run_dir, state)
        append_run_event(
            run_dir,
            "github_review_wait_resumed",
            turn_number=turn_number,
            role="reviewer",
            details={
                "poll_count": int(wait_state.get("poll_count", 0)),
                "pr_number": pr_number,
            },
        )

    deadline = parse_utc_timestamp(wait_state.get("deadline_at")) or (started_at_epoch + timeout_seconds)
    while True:
        last_polled_at_epoch = parse_utc_timestamp(wait_state.get("last_polled_at"))
        if last_polled_at_epoch is not None:
            next_poll_epoch = last_polled_at_epoch + GITHUB_CODEX_POLL_INTERVAL_SECONDS
        else:
            initial_wait_anchor = request_created_at_epoch or started_at_epoch
            next_poll_epoch = initial_wait_anchor + GITHUB_CODEX_INITIAL_WAIT_SECONDS

        if next_poll_epoch > deadline:
            raise SupervisorRuntimeError(
                "github_review_timeout",
                f"no new Codex review comment appeared on PR #{pr_number} within {int(timeout_seconds)} seconds",
                role="reviewer",
                details={
                    "last_request_comment_created_at": request_comment_created_at,
                    "last_request_comment_id": request_comment_id,
                    "poll_count": int(wait_state.get("poll_count", 0)),
                    "pr_number": pr_number,
                },
            )

        now_epoch = time.time()
        if now_epoch < next_poll_epoch:
            time.sleep(next_poll_epoch - now_epoch)
            continue

        polled_at = time.time()
        wait_state["last_polled_at"] = ts_from_epoch(polled_at)
        wait_state["poll_count"] = int(wait_state.get("poll_count", 0)) + 1
        save_run_state(run_dir, state)
        comments = list_github_pr_issue_comments(
            repo_root,
            owner=github_state["repo_owner"],
            repo=github_state["repo"],
            pr_number=pr_number,
        )
        comment = select_latest_unconsumed_github_codex_review_comment(
            comments,
            request_comment_id=request_comment_id,
            request_comment_created_at=request_comment_created_at,
            last_consumed_comment_id=github_state.get("last_consumed_review_comment_id"),
            latest_allowed_created_at=wait_state.get("deadline_at"),
        )
        if comment is not None:
            github_state["last_consumed_review_comment_body_sha256"] = hash_text(
                comment["body"]
            )
            github_state["last_consumed_review_comment_created_at"] = comment["created_at"]
            github_state["last_consumed_review_comment_id"] = comment["id"]
            github_state["last_consumed_review_turn"] = turn_name(turn_number)
            save_run_state(run_dir, state)
            append_run_event(
                run_dir,
                "github_review_comment_received",
                turn_number=turn_number,
                role="reviewer",
                details={
                    "comment_id": comment["id"],
                    "pr_number": pr_number,
                },
            )
            return comment


def github_reviewer_status_from_comment(comment_body: str, reviewed_commit_sha: str) -> dict:
    if comment_body.startswith(GITHUB_CODEX_APPROVED_PREFIX):
        dimensions = {
            key: "pass" for key in critical_review_dimension_keys()
        }
        return {
            "verdict": "approved",
            "summary": "GitHub Codex reported no major blocking issues.",
            "blocking_issues": [],
            "critical_dimensions": dimensions,
            "reviewed_commit_sha": reviewed_commit_sha,
        }
    dimensions = {
        key: (
            "fail"
            if key == "correctness_vs_intent"
            else "uncertain"
        )
        for key in critical_review_dimension_keys()
    }
    return {
        "verdict": "changes_requested",
        "summary": "GitHub Codex requested follow-up changes.",
        "blocking_issues": extract_github_review_blocking_issues(comment_body),
        "critical_dimensions": dimensions,
        "reviewed_commit_sha": reviewed_commit_sha,
    }


def build_github_reviewer_message(
    state: dict,
    turn_number: int,
    *,
    comment: dict | None = None,
    request_comment: dict | None = None,
    status: dict,
    error: SupervisorRuntimeError | None = None,
) -> str:
    github_state = state["review_bridge"]["github"]
    pr_label = github_state["pr_url"] or f"#{github_state.get('pr_number')}"
    lines = [
        "# Review",
        "",
        "## Verdict Summary",
        "",
        f"- Verdict: `{status['verdict']}`",
        f"- Summary: {status['summary']}",
        f"- PR: {pr_label}",
        f"- Branch: `{github_state['branch']}`",
        f"- Turn: `{turn_name(turn_number)}`",
    ]
    if request_comment is not None:
        lines.append(f"- Review request comment ID: `{request_comment['id']}`")
    if comment is not None:
        lines.append(f"- Imported Codex review comment ID: `{comment['id']}`")
    if status["blocking_issues"]:
        lines.extend(["", "## Blocking Issues", ""])
        lines.extend(f"- {item}" for item in status["blocking_issues"])
    lines.extend(["", "## Imported Review Comment", ""])
    if comment is not None:
        lines.append(comment["body"].rstrip())
    elif error is not None:
        lines.append(f"GitHub review bridge failed during `{error.phase}`.")
        lines.append("")
        lines.append(str(error))
    else:
        lines.append("No review comment was imported.")
    lines.extend(["", "## Independent Verification Performed", ""])
    lines.append("- Resolved or created the PR through `gh` in the target repository.")
    if request_comment is not None:
        if request_comment.get("body") is None:
            lines.append(
                f"- Reused the previously posted `@codex` review request comment on PR #{github_state['pr_number']}."
            )
        else:
            lines.append(
                f"- Posted an `@codex` review request comment on PR #{github_state['pr_number']}."
            )
        lines.append(
            f"- Waited {GITHUB_CODEX_INITIAL_WAIT_SECONDS // 60} minutes, then polled every {GITHUB_CODEX_POLL_INTERVAL_SECONDS // 60} minutes for a new Codex review comment."
        )
    if error is not None:
        lines.append("- Surfaced the GitHub review bridge failure explicitly as a blocked reviewer artifact.")
    else:
        lines.append("- Stored the latest unconsumed Codex review comment in the reviewer turn artifacts for the next generator turn.")
    lines.extend(["", "## Residual Risks or Follow-up Notes", ""])
    if status["verdict"] == "changes_requested":
        lines.append("- The next generator turn should triage the imported GitHub Codex findings just like internal reviewer feedback.")
    elif status["verdict"] == "approved":
        lines.append("- The external GitHub Codex reviewer reported no major blocking issues on the current PR head.")
    else:
        lines.append("- Review could not be completed because the external GitHub bridge did not reach a usable Codex comment.")
    return "\n".join(lines).rstrip()


def build_github_review_bridge_prompt(
    state: dict,
    turn_number: int,
    *,
    continue_context_block: str = "",
    reuse_existing_request: bool,
) -> str:
    github_state = state["review_bridge"]["github"]
    pr_label = github_state["pr_url"] or f"#{github_state.get('pr_number')}"
    request_mode = "resume the existing review wait" if reuse_existing_request else "post a new `@codex` review request comment"
    lines = [
        "GitHub Codex PR review bridge",
        "",
        f"Turn: {turn_name(turn_number)}",
        f"PR: {pr_label}",
        f"Branch: {github_state['branch']}",
        f"Base branch: {github_state['base_branch']}",
        f"Action: {request_mode}",
    ]
    if continue_context_block:
        lines.extend(["", continue_context_block])
    reopen_context_block = format_reopen_context_block(state)
    if reopen_context_block:
        lines.extend(["", reopen_context_block])
    return "\n".join(lines).rstrip()

def assign_recent_codex_session_ids(run_dir: Path, state: dict) -> None:
    known_ids = set(state.get("session_index_snapshot_ids", []))
    created_at = state.get("created_at")
    assigned_ids = {
        role_state.get("codex_session_id")
        for role_state in state["roles"].values()
        if role_state.get("codex_session_id")
    }
    entries = sorted(read_codex_session_index(), key=lambda item: item["updated_at"])
    available = [
        entry
        for entry in entries
        if entry["id"] not in known_ids
        and entry["id"] not in assigned_ids
        and (not isinstance(created_at, str) or entry["updated_at"] >= created_at)
    ]
    changed = False
    for role in active_tmux_roles(state):
        role_state = state["roles"][role]
        if role_state.get("codex_session_id") or not available:
            continue
        entry = available.pop(0)
        role_state["codex_session_id"] = entry["id"]
        role_state["codex_thread_name"] = entry.get("thread_name")
        append_run_event(
            run_dir,
            f"{role}_session_identified",
            role=role,
            details={"codex_session_id": entry["id"]},
        )
        changed = True
    if changed:
        save_run_state(run_dir, state)


def write_failure_diagnostics(run_dir: Path, state: dict, error: SupervisorRuntimeError) -> Path:
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
    for role in ROLE_NAMES:
        tmux_name = state["roles"][role]["tmux_session"]
        if role_uses_tmux(state, role) and isinstance(tmux_name, str) and tmux_name:
            write_text(failure_dir / f"{role}.pane.txt", tmux_capture_joined_pane(tmux_name))
        else:
            write_text(failure_dir / f"{role}.pane.txt", "[tmux session not used]\n")
    return failure_dir


def create_tmux_sessions(run_dir: Path, state: dict) -> None:
    repo_root = Path(state["repo_root"])
    for role in active_tmux_roles(state):
        role_state = state["roles"][role]
        phase = f"{role}_session_start"
        role_state["last_wait_phase"] = phase
        save_run_state(run_dir, state)
        command = build_role_session_command(repo_root, state["council_config"], role_state)
        tmux_new_session(role_state["tmux_session"], repo_root, command, role=role)
        append_run_event(run_dir, f"{role}_session_started", role=role)
    save_run_state(run_dir, state)


def ensure_role_session_ready(run_dir: Path, state: dict, role: str) -> None:
    repo_root = Path(state["repo_root"])
    tmux_name = state["roles"][role]["tmux_session"]
    if not tmux_session_exists(tmux_name):
        role_state = state["roles"][role]
        codex_session_id = role_state.get("codex_session_id")
        session_entry = (
            find_codex_session_entry(codex_session_id)
            if isinstance(codex_session_id, str)
            else None
        )
        if session_entry and isinstance(state.get("created_at"), str) and session_entry["updated_at"] < state["created_at"]:
            codex_session_id = None
            role_state["codex_session_id"] = None
            role_state["codex_thread_name"] = None
            save_run_state(run_dir, state)
        restart_role_session(
            tmux_name,
            repo_root=repo_root,
            council_config=state["council_config"],
            role_state=role_state,
            role=role,
        )
        event_name = (
            f"{role}_session_resumed"
            if codex_session_id
            else f"{role}_session_restarted"
        )
        append_run_event(run_dir, event_name, role=role)
    wait_for_tmux_prompt(
        tmux_name,
        float(state["council_config"]["council"]["launch_timeout_seconds"]),
        phase=f"{role}_session_ready",
        role=role,
    )
    assign_recent_codex_session_ids(run_dir, state)


def wait_for_tmux_sessions_ready(run_dir: Path, state: dict) -> None:
    launch_timeout_seconds = float(state["council_config"]["council"]["launch_timeout_seconds"])
    for role in active_tmux_roles(state):
        state["roles"][role]["last_wait_phase"] = f"{role}_tmux_boot"
        save_run_state(run_dir, state)
        wait_for_tmux_prompt(
            state["roles"][role]["tmux_session"],
            launch_timeout_seconds,
            phase=f"{role}_tmux_boot",
            role=role,
        )
        append_run_event(run_dir, f"{role}_session_ready", role=role)
    assign_recent_codex_session_ids(run_dir, state)


def run_generator_phase(
    run_dir: Path,
    state: dict,
    task_root: Path,
    turn_number: int,
    current_turn_dir: Path,
    *,
    inline_context: bool,
    continue_context_block: str = "",
) -> dict:
    repo_root = Path(state["repo_root"])
    inspection = inspect_task_workspace(task_root)
    state["workspace_profile"] = inspection["profile"]
    was_transitioning = state.get("status") == TRANSITIONING_TURN_STATUS
    transition_from_turn = state.get("current_turn")
    transition_source_verdict = state.get("transition_source_verdict")
    turn_timeout_seconds = float(state["council_config"]["council"]["turn_timeout_seconds"])
    generator_prompt = build_generator_turn_prompt(
        repo_root,
        task_root,
        current_turn_dir,
        turn_number,
        state["task_name"],
        state=state,
        inspection=inspection,
        inline_context=inline_context,
        continue_context_block=continue_context_block,
        fork_context_block=format_fork_context_block(state["roles"]["generator"]),
    )
    write_prompt_artifact(current_turn_dir, "generator", generator_prompt)
    state["current_turn"] = turn_number
    state["pending_turn"] = None
    state["pending_role"] = None
    state["transition_source_verdict"] = None
    state["status"] = "waiting_generator"
    state["roles"]["generator"]["last_wait_phase"] = "generator_prompt_ready"
    save_run_state(run_dir, state)
    if was_transitioning and isinstance(transition_from_turn, int):
        append_run_event(
            run_dir,
            "turn_transition_completed",
            turn_number=turn_number,
            role="generator",
            details={
                "from_role": "reviewer",
                "from_turn": turn_name(transition_from_turn),
                "source_verdict": transition_source_verdict,
                "to_role": "generator",
                "to_turn": turn_name(turn_number),
            },
        )
    save_turn_metadata(current_turn_dir, turn_number, "generator_prompt_prepared", role="generator")
    append_run_event(
        run_dir,
        "generator_prompt_prepared",
        turn_number=turn_number,
        role="generator",
    )
    ensure_role_session_ready(run_dir, state, "generator")
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
    save_turn_metadata(current_turn_dir, turn_number, "generator_prompt_sent", role="generator")
    append_run_event(
        run_dir,
        "generator_prompt_sent",
        turn_number=turn_number,
        role="generator",
    )
    generator_artifact_path, _, generator_status = wait_for_role_artifacts(
        current_turn_dir,
        "generator",
        validator=validate_generator_status,
        timeout_seconds=turn_timeout_seconds,
        phase="generator_artifacts",
        tmux_name=state["roles"]["generator"]["tmux_session"],
        turn_number=turn_number,
        repo_root=repo_root,
        council_config=state["council_config"],
    )
    write_final_message_artifact(
        current_turn_dir,
        "generator",
        generator_artifact_path.read_text(encoding="utf-8"),
    )
    write_raw_final_output_artifact(
        current_turn_dir,
        "generator",
        state["roles"]["generator"]["tmux_session"],
    )
    return generator_status


def run_reviewer_phase(
    run_dir: Path,
    state: dict,
    task_root: Path,
    turn_number: int,
    current_turn_dir: Path,
    *,
    inline_context: bool,
    continue_context_block: str = "",
    bootstrap_review_phase: bool = False,
) -> dict:
    repo_root = Path(state["repo_root"])
    inspection = inspect_task_workspace(task_root)
    state["workspace_profile"] = inspection["profile"]
    turn_timeout_seconds = float(state["council_config"]["council"]["turn_timeout_seconds"])
    reviewer_prompt = build_reviewer_turn_prompt(
        repo_root,
        task_root,
        current_turn_dir,
        turn_number,
        state=state,
        inspection=inspection,
        inline_context=inline_context,
        continue_context_block=continue_context_block,
        fork_context_block=format_fork_context_block(state["roles"]["reviewer"]),
        bootstrap_review_block=(
            format_fork_bootstrap_review_block(task_root)
            if bootstrap_review_phase
            else ""
        ),
    )
    write_prompt_artifact(current_turn_dir, "reviewer", reviewer_prompt)
    state["current_turn"] = turn_number
    state["pending_turn"] = None
    state["pending_role"] = None
    state["transition_source_verdict"] = None
    state["status"] = "waiting_reviewer"
    state["roles"]["reviewer"]["last_wait_phase"] = "reviewer_prompt_ready"
    save_run_state(run_dir, state)
    save_turn_metadata(current_turn_dir, turn_number, "reviewer_prompt_prepared", role="reviewer")
    append_run_event(
        run_dir,
        "reviewer_prompt_prepared",
        turn_number=turn_number,
        role="reviewer",
    )
    ensure_role_session_ready(run_dir, state, "reviewer")
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
    save_turn_metadata(current_turn_dir, turn_number, "reviewer_prompt_sent", role="reviewer")
    append_run_event(
        run_dir,
        "reviewer_prompt_sent",
        turn_number=turn_number,
        role="reviewer",
    )
    reviewer_artifact_path, _, reviewer_status = wait_for_role_artifacts(
        current_turn_dir,
        "reviewer",
        validator=validate_reviewer_status,
        timeout_seconds=turn_timeout_seconds,
        phase="reviewer_artifacts",
        tmux_name=state["roles"]["reviewer"]["tmux_session"],
        turn_number=turn_number,
        repo_root=repo_root,
        council_config=state["council_config"],
    )
    write_final_message_artifact(
        current_turn_dir,
        "reviewer",
        reviewer_artifact_path.read_text(encoding="utf-8"),
    )
    write_raw_final_output_artifact(
        current_turn_dir,
        "reviewer",
        state["roles"]["reviewer"]["tmux_session"],
    )
    return reviewer_status


def blocked_github_reviewer_status(summary: str, reviewed_commit_sha: str | None) -> dict:
    dimensions = {
        key: ("fail" if key == "failure_mode_and_fallback" else "uncertain")
        for key in critical_review_dimension_keys()
    }
    return validate_reviewer_status(
        {
            "verdict": "blocked",
            "summary": summary,
            "blocking_issues": [summary],
            "critical_dimensions": dimensions,
            "reviewed_commit_sha": reviewed_commit_sha,
        }
    )


def run_github_codex_review_phase(
    run_dir: Path,
    state: dict,
    task_root: Path,
    turn_number: int,
    current_turn_dir: Path,
    *,
    continue_context_block: str = "",
) -> dict:
    github_state = state["review_bridge"]["github"]
    reuse_existing_request = (
        github_state.get("last_request_turn") == turn_name(turn_number)
        and isinstance(github_state.get("last_request_comment_id"), int)
    )
    reviewer_prompt = build_github_review_bridge_prompt(
        state,
        turn_number,
        continue_context_block=continue_context_block,
        reuse_existing_request=reuse_existing_request,
    )
    write_prompt_artifact(current_turn_dir, "reviewer", reviewer_prompt)
    state["current_turn"] = turn_number
    state["pending_turn"] = None
    state["pending_role"] = None
    state["transition_source_verdict"] = None
    state["status"] = "waiting_reviewer"
    state["roles"]["reviewer"]["last_wait_phase"] = "github_review_bridge"
    save_run_state(run_dir, state)
    save_turn_metadata(
        current_turn_dir,
        turn_number,
        "reviewer_bridge_started",
        role="reviewer",
        details={"mode": "github_pr_codex", "reused_request": reuse_existing_request},
    )
    append_run_event(
        run_dir,
        "reviewer_bridge_started",
        turn_number=turn_number,
        role="reviewer",
        details={"mode": "github_pr_codex", "reused_request": reuse_existing_request},
    )

    request_comment = None
    reviewed_commit_sha = github_state.get("last_observed_head_sha")
    try:
        pr_info = ensure_github_pr_ready(run_dir, state, task_root, turn_number)
        reviewed_commit_sha = pr_info["head_ref_oid"]
        if reuse_existing_request:
            request_comment = {
                "body": None,
                "created_at": github_state["last_request_comment_created_at"],
                "html_url": None,
                "id": github_state["last_request_comment_id"],
            }
        else:
            request_comment = post_github_pr_review_request_comment(
                run_dir,
                state,
                turn_number,
                reviewed_commit_sha,
            )
        comment = wait_for_new_github_codex_review_comment(
            run_dir,
            state,
            turn_number,
            timeout_seconds=float(state["council_config"]["council"]["turn_timeout_seconds"]),
            reuse_existing_request=reuse_existing_request,
        )
        reviewer_status = validate_reviewer_status(
            github_reviewer_status_from_comment(comment["body"], reviewed_commit_sha)
        )
        reviewer_message = build_github_reviewer_message(
            state,
            turn_number,
            comment=comment,
            request_comment=request_comment,
            status=reviewer_status,
        )
        write_final_message_artifact(current_turn_dir, "reviewer", reviewer_message)
        save_json(role_status_path(current_turn_dir, "reviewer"), reviewer_status)
        write_text(role_raw_output_path(current_turn_dir, "reviewer"), comment["body"])
        save_json(
            role_capture_status_path(current_turn_dir, "reviewer"),
            {"status": "captured", "source": "github_pr_comment"},
        )
        save_turn_metadata(
            current_turn_dir,
            turn_number,
            "reviewer_artifacts_valid",
            role="reviewer",
            details={"status_path": str(role_status_path(current_turn_dir, "reviewer"))},
        )
        append_run_event(
            run_dir,
            "reviewer_artifacts_valid",
            turn_number=turn_number,
            role="reviewer",
            details={"source": "github_pr_codex"},
        )
        return reviewer_status
    except SupervisorRuntimeError as error:
        reviewer_status = blocked_github_reviewer_status(str(error), reviewed_commit_sha)
        reviewer_message = build_github_reviewer_message(
            state,
            turn_number,
            request_comment=request_comment,
            status=reviewer_status,
            error=error,
        )
        write_final_message_artifact(current_turn_dir, "reviewer", reviewer_message)
        save_json(role_status_path(current_turn_dir, "reviewer"), reviewer_status)
        write_text(
            role_raw_output_path(current_turn_dir, "reviewer"),
            f"[github review bridge blocked]\n{error.phase}: {error}\n",
        )
        save_json(
            role_capture_status_path(current_turn_dir, "reviewer"),
            {"status": "captured", "source": "github_pr_bridge_error"},
        )
        append_run_event(
            run_dir,
            "github_review_blocked",
            turn_number=turn_number,
            role="reviewer",
            details={"phase": error.phase, "summary": str(error)},
        )
        return reviewer_status


def run_review_phase(
    run_dir: Path,
    state: dict,
    task_root: Path,
    turn_number: int,
    current_turn_dir: Path,
    *,
    inline_context: bool,
    continue_context_block: str = "",
    bootstrap_review_phase: bool = False,
) -> dict:
    if review_bridge_mode(state) == "github_pr_codex":
        return run_github_codex_review_phase(
            run_dir,
            state,
            task_root,
            turn_number,
            current_turn_dir,
            continue_context_block=continue_context_block,
        )
    return run_reviewer_phase(
        run_dir,
        state,
        task_root,
        turn_number,
        current_turn_dir,
        inline_context=inline_context,
        continue_context_block=continue_context_block,
        bootstrap_review_phase=bootstrap_review_phase,
    )


def supervisor_loop_from(
    run_dir: Path,
    state: dict,
    task_root: Path,
    *,
    start_turn: int,
    start_role: str,
    reuse_existing_turn_for_first: bool = False,
    first_continue_context_block: str = "",
) -> None:
    next_role = start_role
    max_turn_budget = int(state["council_config"]["council"]["max_turns"])
    last_turn = start_turn + max_turn_budget - 1

    for turn_number in range(start_turn, last_turn + 1):
        state["workspace_profile"] = inspect_task_workspace(task_root)["profile"]
        if turn_number == start_turn and reuse_existing_turn_for_first:
            current_turn_dir = turn_dir_for(run_dir, turn_number)
            ensure_dir(role_dir_for(current_turn_dir, "generator"))
            ensure_dir(role_dir_for(current_turn_dir, "reviewer"))
        else:
            current_turn_dir = prepare_turn(run_dir, turn_number, task_root)

        continue_context_block = first_continue_context_block if turn_number == start_turn else ""

        if next_role == "generator":
            generator_status = run_generator_phase(
                run_dir,
                state,
                task_root,
                turn_number,
                current_turn_dir,
                inline_context=turn_number == 1,
                continue_context_block=continue_context_block,
            )
            if generator_status["result"] == "needs_human":
                pause_for_human(
                    run_dir,
                    state,
                    role="generator",
                    turn_dir=current_turn_dir,
                    summary=generator_status["summary"],
                    human_message=generator_status["human_message"],
                    human_source=generator_status["human_source"],
                )
                return
            if generator_status["result"] == "blocked":
                state["status"] = "blocked"
                state["stop_reason"] = generator_status["summary"]
                save_run_state(run_dir, state)
                save_turn_metadata(
                    current_turn_dir,
                    turn_number,
                    "blocked",
                    role="generator",
                    details={"summary": generator_status["summary"]},
                )
                append_run_event(
                    run_dir,
                    "blocked",
                    turn_number=turn_number,
                    role="generator",
                    details={"summary": generator_status["summary"]},
                )
                return
            record_current_git_state(run_dir, state)
            reviewer_status = run_review_phase(
                run_dir,
                state,
                task_root,
                turn_number,
                current_turn_dir,
                inline_context=turn_number == 1,
                bootstrap_review_phase=state.get("bootstrap_phase") == "fork_to_review",
            )
        else:
            reviewer_status = run_review_phase(
                run_dir,
                state,
                task_root,
                turn_number,
                current_turn_dir,
                inline_context=turn_number == 1,
                continue_context_block=continue_context_block,
                bootstrap_review_phase=state.get("bootstrap_phase") == "fork_to_review",
            )

        if reviewer_status["verdict"] == "approved":
            state["status"] = "approved"
            state["stop_reason"] = reviewer_status["summary"]
            save_run_state(run_dir, state)
            save_turn_metadata(
                current_turn_dir,
                turn_number,
                "approved",
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            append_run_event(
                run_dir,
                "approved",
                turn_number=turn_number,
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            return
        if reviewer_status["verdict"] == "needs_human":
            pause_for_human(
                run_dir,
                state,
                role="reviewer",
                turn_dir=current_turn_dir,
                summary=reviewer_status["summary"],
                human_message=reviewer_status["human_message"],
                human_source=reviewer_status["human_source"],
            )
            return
        if reviewer_status["verdict"] == "blocked":
            state["status"] = "blocked"
            state["stop_reason"] = reviewer_status["summary"]
            save_run_state(run_dir, state)
            save_turn_metadata(
                current_turn_dir,
                turn_number,
                "blocked",
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            append_run_event(
                run_dir,
                "blocked",
                turn_number=turn_number,
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            return
        if reviewer_status["verdict"] == "changes_requested":
            if state.get("bootstrap_phase") == "fork_to_review":
                state["bootstrap_phase"] = None
            next_turn_number = turn_number + 1
            if next_turn_number > last_turn:
                break
            begin_turn_transition(
                run_dir,
                state,
                task_root,
                from_turn=turn_number,
                to_turn=next_turn_number,
                from_role="reviewer",
                to_role="generator",
                source_verdict="reviewer_changes_requested",
            )
            save_turn_metadata(
                current_turn_dir,
                turn_number,
                "changes_requested",
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            append_run_event(
                run_dir,
                "changes_requested",
                turn_number=turn_number,
                role="reviewer",
                details={"summary": reviewer_status["summary"]},
            )
            next_role = "generator"
            continue

    state["status"] = "max_turns_reached"
    state["stop_reason"] = f"reached max turns ({max_turn_budget})"
    save_run_state(run_dir, state)
    append_run_event(run_dir, "max_turns_reached", turn_number=state["current_turn"])


def supervisor_loop(run_dir: Path, state: dict, task_root: Path) -> None:
    supervisor_loop_from(
        run_dir,
        state,
        task_root,
        start_turn=1,
        start_role="generator",
    )


def render_doc_content(doc_kind: str, body: str) -> str:
    if doc_kind == "task":
        return build_task_doc_from_seed(body)
    if doc_kind == "review":
        return build_review_doc_from_seed(body)
    if doc_kind == "spec":
        return build_spec_doc_from_seed(body)
    if doc_kind == "contract":
        return build_contract_doc_from_seed(body)
    raise SystemExit(f"unsupported doc kind: {doc_kind}")


def document_path_for(task_root: Path, doc_kind: str) -> Path:
    return task_root / INPUT_DOC_FILENAMES[doc_kind]


def write_document_command(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    scaffold_council_root(repo_root)
    task_root = task_root_for(repo_root, task_name)
    scaffold_task_root(task_root, initial_task_text=None)

    body = read_text_arg(args.body, args.body_file, default="")
    target_path = document_path_for(task_root, args.doc_kind)
    if not body.strip():
        template_name = INPUT_DOC_FILENAMES[args.doc_kind]
        write_text(target_path, read_template("scaffold", template_name))
    else:
        write_text(target_path, render_doc_content(args.doc_kind, body))
    print(f"wrote: {target_path}")
    return 0


def print_run_launch_summary(run_dir: Path, state: dict, task_root: Path) -> None:
    review_mode = review_bridge_mode(state)
    print(f"repo_root: {state['repo_root']}")
    print(f"task_root: {task_root}")
    print(f"run_id: {state['run_id']}")
    print(f"run_dir: {run_dir}")
    print(f"generator tmux: {state['roles']['generator']['tmux_session']}")
    print(f"attach generator: tmux attach -t {state['roles']['generator']['tmux_session']}")
    reviewer_session = state["roles"]["reviewer"]["tmux_session"]
    if isinstance(reviewer_session, str):
        print(f"reviewer tmux: {reviewer_session}")
        print(f"attach reviewer: tmux attach -t {reviewer_session}")
    elif review_mode == "github_pr_codex":
        github_state = state["review_bridge"]["github"]
        print("reviewer bridge: github_pr_codex")
        print(f"review branch: {github_state['branch']}")
        if github_state.get("pr_url"):
            print(f"review pr: {github_state['pr_url']}")
    reopen = state.get("reopen")
    if isinstance(reopen, dict):
        reopened_from = reopen.get("reopened_from", {})
        print(f"reopened from run: {reopened_from.get('run_id')}")
        print(f"reopened from turn: {reopened_from.get('turn')}")
        print(f"reopen reason kind: {reopen.get('reason_kind')}")


def run_supervisor_for_initialized_run(
    run_dir: Path,
    state: dict,
    task_root: Path,
    *,
    start_turn: int,
    start_role: str,
) -> int:
    try:
        create_tmux_sessions(run_dir, state)
        print_run_launch_summary(run_dir, state, task_root)
        wait_for_tmux_sessions_ready(run_dir, state)
        if review_bridge_mode(state) == "github_pr_codex":
            print("generator Codex TUI session is ready")
        else:
            print("both Codex TUI sessions are ready")
        supervisor_loop_from(
            run_dir,
            state,
            task_root,
            start_turn=start_turn,
            start_role=start_role,
        )
    except SupervisorRuntimeError as error:
        state = load_json(run_dir / "state.json")
        state["status"] = (
            "blocked_invalid_artifacts"
            if error.phase == "blocked_invalid_artifacts"
            else "blocked"
        )
        state["stop_reason"] = f"{error.phase}: {error}"
        failure_dir = write_failure_diagnostics(run_dir, state, error)
        save_run_state(run_dir, state)
        append_run_event(
            run_dir,
            state["status"],
            role=error.role,
            turn_number=state.get("current_turn"),
            details={"phase": error.phase, "message": str(error)},
        )
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
        append_run_event(
            run_dir,
            "blocked",
            turn_number=state.get("current_turn"),
            details={"phase": error.phase, "message": str(error)},
        )
        print(f"supervisor error during {error.phase}: {error}", flush=True)
        print(f"diagnostics: {failure_dir}", flush=True)
        return 1

    final_state = load_json(run_dir / "state.json")
    print(f"final status: {final_state['status']}")
    if final_state.get("stop_reason"):
        print(f"stop reason: {final_state['stop_reason']}")
    return 0


def start_run(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, is_git = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    review_mode = normalize_review_mode(args)

    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(
            f"missing task workspace: {task_root}\n"
            f"Run `init {task_name}` first."
        )
    inspection = ensure_task_workspace_exists(task_root)
    council_config = load_council_config(repo_root)
    generator_fork_session_id, reviewer_fork_session_id = resolve_fork_parent_session_ids(args)
    for session_id in (generator_fork_session_id, reviewer_fork_session_id):
        if session_id and not find_codex_session_entry(session_id):
            raise SystemExit(f"unknown fork parent session id: {session_id}")
    fork_enabled = has_any_fork_parent(generator_fork_session_id, reviewer_fork_session_id)
    if review_mode == "github_pr_codex" and fork_enabled:
        raise SystemExit("github_pr_codex review mode does not support forked role sessions")
    if review_mode == "github_pr_codex" and not is_git:
        raise SystemExit("github_pr_codex review mode requires a git worktree")
    if not is_git and fork_enabled:
        raise SystemExit("fork start requires a git worktree and cannot be used with --allow-non-git")
    validate_task_workspace_for_start(task_root, inspection)
    start_role, bootstrap_phase = determine_start_role(
        inspection=inspection,
        fork_enabled=fork_enabled,
        requested_role=args.start_role,
    )
    if bootstrap_phase == "fork_to_review" and not reviewer_fork_session_id:
        raise SystemExit(
            "fork bootstrap requires reviewer fork context; pass --fork-session-id or --reviewer-fork-session-id"
        )
    if is_git:
        git_state = (
            git_preflight(repo_root)
            if bootstrap_phase != "fork_to_review"
            else git_preflight_allowing_dirty(repo_root)
        )
    else:
        git_state = None

    run_id = args.run_id or run_id_value()
    run_dir = task_root / "runs" / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    ensure_dir(run_dir / "turns")

    generator_session = args.generator_session or build_tmux_session_name(task_name, "generator", run_id)
    reviewer_session = (
        args.reviewer_session or build_tmux_session_name(task_name, "reviewer", run_id)
        if review_mode == "internal"
        else None
    )
    session_index_snapshot_ids = [entry["id"] for entry in read_codex_session_index()]

    state = create_run_state(
        repo_root=repo_root,
        task_root=task_root,
        task_name=task_name,
        run_id=run_id,
        workspace_profile=inspection["profile"],
        council_config=council_config,
        git_state=git_state,
        generator_session=generator_session,
        reviewer_session=reviewer_session,
        review_bridge={"mode": review_mode},
        generator_bootstrap_mode="fork" if generator_fork_session_id else "fresh",
        reviewer_bootstrap_mode="fork" if reviewer_fork_session_id else "fresh",
        generator_fork_parent_session_id=generator_fork_session_id,
        reviewer_fork_parent_session_id=reviewer_fork_session_id,
        bootstrap_phase=bootstrap_phase,
    )
    state["session_index_snapshot_ids"] = session_index_snapshot_ids
    save_run_state(run_dir, state)
    append_run_event(run_dir, "run_created", details={"task_name": task_name})
    try:
        state["review_bridge"] = build_review_bridge_state(repo_root, task_root, git_state, args)
        save_run_state(run_dir, state)
    except SupervisorRuntimeError as error:
        state = load_json(run_dir / "state.json")
        state["status"] = "blocked"
        state["stop_reason"] = f"{error.phase}: {error}"
        failure_dir = write_failure_diagnostics(run_dir, state, error)
        save_run_state(run_dir, state)
        append_run_event(
            run_dir,
            "blocked",
            role=error.role,
            turn_number=state.get("current_turn"),
            details={"phase": error.phase, "message": str(error)},
        )
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
        append_run_event(
            run_dir,
            "blocked",
            turn_number=state.get("current_turn"),
            details={"phase": error.phase, "message": str(error)},
        )
        print(f"supervisor error during {error.phase}: {error}", flush=True)
        print(f"diagnostics: {failure_dir}", flush=True)
        return 1
    return run_supervisor_for_initialized_run(
        run_dir,
        state,
        task_root,
        start_turn=1,
        start_role=start_role,
    )


def reopen_run(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, is_git = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(
            f"missing task workspace: {task_root}\n"
            f"Run `init {task_name}` first."
        )
    inspection = ensure_task_workspace_exists(task_root)
    reason_kind = normalize_reopen_reason_kind(args.reason_kind)
    reason_message = normalize_required_text(args.reason, field_name="reopen reason")
    previous_run_dir = resolve_run_dir(task_root, args.run_id)
    state_path = previous_run_dir / "state.json"
    if not state_path.exists():
        raise SystemExit(f"missing run state: {state_path}")
    previous_state = load_json(state_path)
    try:
        continuation_plan_data = resolve_continuation_plan(previous_run_dir, previous_state)
    except ContinuationResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if continuation_plan_data["mode"] != "terminal":
        raise SystemExit(
            build_reopen_nonterminal_message(task_name, previous_run_dir.name, continuation_plan_data)
        )

    approved_turn_dir = continuation_plan_data["turn_dir"]
    approved_reviewer_status = load_status_file(
        role_status_path(approved_turn_dir, "reviewer"),
        validate_reviewer_status,
    )
    validate_task_workspace_for_start(task_root, inspection)
    doc_comparison = build_reopen_doc_comparison(approved_turn_dir, task_root)
    reopen_metadata = build_reopen_metadata(
        task_name=task_name,
        previous_run_dir=previous_run_dir,
        approved_turn_dir=approved_turn_dir,
        approved_reviewer_status=approved_reviewer_status,
        reason_kind=reason_kind,
        reason_message=reason_message,
        doc_comparison=doc_comparison,
    )
    council_config = load_council_config(repo_root)
    start_role, bootstrap_phase = determine_start_role(
        inspection=inspection,
        fork_enabled=False,
        requested_role="auto",
    )
    if bootstrap_phase is not None:
        raise SystemExit("reopen does not support fork bootstrap; add local task documents first")
    if is_git:
        git_state = git_preflight(repo_root)
    else:
        git_state = None

    run_id = run_id_value()
    run_dir = task_root / "runs" / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    ensure_dir(run_dir / "turns")
    review_bridge = clone_review_bridge_state_for_new_run(previous_state)
    generator_session = build_tmux_session_name(task_name, "generator", run_id)
    reviewer_session = (
        build_tmux_session_name(task_name, "reviewer", run_id)
        if review_bridge_mode({"review_bridge": review_bridge}) == "internal"
        else None
    )
    session_index_snapshot_ids = [entry["id"] for entry in read_codex_session_index()]
    state = create_run_state(
        repo_root=repo_root,
        task_root=task_root,
        task_name=task_name,
        run_id=run_id,
        workspace_profile=inspection["profile"],
        council_config=council_config,
        git_state=git_state,
        generator_session=generator_session,
        reviewer_session=reviewer_session,
        review_bridge=review_bridge,
        bootstrap_phase=None,
        reopen_context=reopen_metadata,
    )
    state["session_index_snapshot_ids"] = session_index_snapshot_ids
    save_run_state(run_dir, state)
    write_reopen_metadata_artifact(run_dir, reopen_metadata)
    append_reopen_index(
        repo_root,
        {
            **reopen_metadata,
            "new_run_id": run_id,
            "new_run_dir": str(run_dir),
        },
    )
    append_run_event(
        run_dir,
        "run_created",
        details={"task_name": task_name, "reopened_from_run_id": previous_run_dir.name},
    )
    append_run_event(
        run_dir,
        "run_reopened",
        details={
            "reason_kind": reason_kind,
            "reopened_from_run_id": previous_run_dir.name,
            "reopened_from_turn": approved_turn_dir.name,
            "docs_changed_since_approval": doc_comparison["docs_changed_since_approval"],
        },
    )
    return run_supervisor_for_initialized_run(
        run_dir,
        state,
        task_root,
        start_turn=1,
        start_role=start_role,
    )


def init_task(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)

    scaffold_council_root(repo_root)
    task_root = task_root_for(repo_root, task_name)
    initial_task_text = read_text_arg(args.task, args.task_file, default="").strip()
    result = scaffold_task_root(task_root, initial_task_text=initial_task_text or None)

    print(f"repo_root: {repo_root}")
    print(f"council_root: {council_root_for(repo_root)}")
    print(f"task_root: {task_root}")
    print(f"config: {config_path_for(repo_root)}")
    print(f"task: {task_root / TASK_FILENAME}")
    print(f"review: {task_root / REVIEW_FILENAME}")
    print(f"spec: {task_root / SPEC_FILENAME}")
    print(f"contract: {task_root / CONTRACT_FILENAME}")
    print(f"agents: {task_root / 'AGENTS.md'}")
    print(f"generator: {task_root / 'generator.instructions.md'}")
    print(f"reviewer: {task_root / 'reviewer.instructions.md'}")
    if result["task_needs_edit"]:
        print(f"next: review {TASK_FILENAME}, then run `start` or use `write` to add other documents")
    else:
        print(f"next: use `write task|review|spec|contract {task_name}` or edit the files directly, then run `start`")
    return 0


def show_status(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(f"missing task workspace: {task_root}")
    run_dir = resolve_run_dir(task_root, args.run_id)

    state_path = run_dir / "state.json"
    if not state_path.exists():
        raise SystemExit(f"missing run state: {state_path}")
    state = load_json(state_path)
    continuation = inspect_continuation_plan(run_dir, state)
    payload = dict(state)
    derived_payload = {
        "mode": continuation["mode"],
        "reason": continuation["reason"],
    }
    if continuation["mode"] in {"continue", "terminal"}:
        derived_payload["continuation_state"] = continuation["continuation_state"]
        derived_payload["turn"] = turn_name(continuation["turn_number"])
        derived_payload["turn_dir"] = str(continuation["turn_dir"])
        derived_payload["ignored_turns"] = continuation["ignored_turns"]
    if continuation["mode"] == "continue":
        derived_payload["role"] = continuation["role"]
        derived_payload["create_new_turn"] = continuation["create_new_turn"]
        derived_payload["reuse_existing_turn_for_first"] = continuation["reuse_existing_turn_for_first"]
        derived_payload["prior_status"] = continuation["prior_status"]
        if continuation["source_turn_number"] is not None:
            derived_payload["source_turn"] = turn_name(continuation["source_turn_number"])
        if continuation["reference_turn_dir"] is not None:
            derived_payload["reference_turn_dir"] = str(continuation["reference_turn_dir"])
    elif continuation["mode"] == "error":
        derived_payload["details"] = continuation["details"]
    payload["derived_continuation"] = derived_payload
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


ArtifactContinuationState = Literal[
    "generator_pending",
    "generator_invalid",
    "generator_needs_human",
    "generator_blocked",
    "generator_complete_waiting_reviewer",
    "reviewer_pending",
    "reviewer_invalid",
    "reviewer_changes_requested",
    "reviewer_needs_human",
    "reviewer_blocked",
    "reviewer_approved",
]


def fallback_continue_role(state: dict) -> str:
    pending_role = state.get("pending_role")
    if pending_role in ROLE_NAMES:
        return pending_role
    return "reviewer" if state.get("status") == "waiting_reviewer" else "generator"


def inspect_role_artifacts(turn_dir: Path, role: str, validator) -> dict:
    message_path, status_path = role_artifact_paths(turn_dir, role)
    if not message_path.exists() or not status_path.exists():
        return {
            "role": role,
            "message_exists": message_path.exists(),
            "status_exists": status_path.exists(),
            "state": "pending",
            "message_path": message_path,
            "status_path": status_path,
        }
    try:
        validated = load_status_file(status_path, validator)
    except Exception as exc:
        return {
            "role": role,
            "message_exists": True,
            "status_exists": True,
            "state": "invalid",
            "error": str(exc),
            "message_path": message_path,
            "status_path": status_path,
        }
    return {
        "role": role,
        "message_exists": True,
        "status_exists": True,
        "state": "valid",
        "validated_status": validated,
        "message_path": message_path,
        "status_path": status_path,
    }


def inspect_role_runtime(turn_dir: Path, role: str, validator) -> dict:
    inspected = inspect_role_artifacts(turn_dir, role, validator)
    inspected["prompt_exists"] = role_prompt_path(turn_dir, role).exists()
    inspected["activity_exists"] = bool(
        inspected["prompt_exists"] or inspected["message_exists"] or inspected["status_exists"]
    )
    return inspected


def classify_turn_continuation_state(turn: dict) -> str:
    generator = turn["generator"]
    reviewer = turn["reviewer"]

    if not generator["activity_exists"] and not reviewer["activity_exists"]:
        return "not_started"

    if reviewer["activity_exists"] and generator["state"] != "valid":
        return "ambiguous"

    if generator["state"] == "invalid":
        return "generator_invalid"
    if generator["state"] == "pending":
        return "generator_pending"

    generator_result = generator["validated_status"]["result"]
    if generator_result == "needs_human":
        return "ambiguous" if reviewer["activity_exists"] else "generator_needs_human"
    if generator_result == "blocked":
        return "ambiguous" if reviewer["activity_exists"] else "generator_blocked"

    if reviewer["state"] == "invalid":
        return "reviewer_invalid"
    if reviewer["state"] == "pending":
        return "reviewer_pending" if reviewer["activity_exists"] else "generator_complete_waiting_reviewer"

    reviewer_verdict = reviewer["validated_status"]["verdict"]
    if reviewer_verdict == "approved":
        return "reviewer_approved"
    if reviewer_verdict == "changes_requested":
        return "reviewer_changes_requested"
    if reviewer_verdict == "needs_human":
        return "reviewer_needs_human"
    return "reviewer_blocked"


def inspect_turn_for_continuation(turn_dir: Path) -> dict:
    metadata = load_turn_metadata(turn_dir) if turn_metadata_path(turn_dir).exists() else {}
    generator = inspect_role_runtime(turn_dir, "generator", validate_generator_status)
    reviewer = inspect_role_runtime(turn_dir, "reviewer", validate_reviewer_status)
    inspection = {
        "turn_dir": turn_dir,
        "turn_number": int(turn_dir.name),
        "metadata": metadata,
        "generator": generator,
        "reviewer": reviewer,
    }
    inspection["continuation_state"] = classify_turn_continuation_state(inspection)
    inspection["has_runtime_activity"] = bool(
        generator["activity_exists"] or reviewer["activity_exists"]
    )
    inspection["is_empty_initialized"] = bool(metadata) and not inspection["has_runtime_activity"]
    return inspection


def continuation_plan(
    *,
    turn_dir: Path,
    turn_number: int,
    role: str,
    create_new_turn: bool,
    reuse_existing_turn_for_first: bool,
    prior_status: str,
    continuation_state: str,
    reason: str,
    reference_turn_dir: Path | None,
    source_turn_number: int | None,
    ignored_turns: list[str],
) -> dict:
    return {
        "mode": "continue",
        "turn_dir": turn_dir,
        "turn_number": turn_number,
        "role": role,
        "create_new_turn": create_new_turn,
        "reuse_existing_turn_for_first": reuse_existing_turn_for_first,
        "prior_status": prior_status,
        "continuation_state": continuation_state,
        "reason": reason,
        "reference_turn_dir": reference_turn_dir,
        "source_turn_number": source_turn_number,
        "ignored_turns": ignored_turns,
    }


def terminal_continuation_plan(
    *,
    turn_dir: Path,
    turn_number: int,
    continuation_state: str,
    reason: str,
    ignored_turns: list[str],
) -> dict:
    return {
        "mode": "terminal",
        "turn_dir": turn_dir,
        "turn_number": turn_number,
        "continuation_state": continuation_state,
        "reason": reason,
        "ignored_turns": ignored_turns,
    }


def approved_run_continue_message() -> str:
    return "cannot continue an approved run; use `reopen` to supersede the approval explicitly"


def next_turn_expectation(turn: dict, continuation_state: str, review_mode: str) -> dict | None:
    turn_number = turn["turn_number"]
    if continuation_state == "reviewer_changes_requested":
        role = "generator"
    elif continuation_state in {"generator_needs_human", "generator_blocked"}:
        role = "generator"
    elif continuation_state in {"reviewer_needs_human", "reviewer_blocked"}:
        if continuation_state == "reviewer_blocked" and review_mode == "github_pr_codex":
            return None
        role = "reviewer"
    else:
        return None
    return {
        "target_turn_number": turn_number + 1,
        "source_turn_number": turn_number,
        "source_status": continuation_state,
        "role": role,
        "reason": (
            f"turn {turn_name(turn_number)} ended with `{continuation_state}`, "
            f"so {role} should continue on turn {turn_name(turn_number + 1)}."
        ),
    }


def turn_matches_expected_transition(turn: dict, expected_transition: dict) -> bool:
    metadata = turn["metadata"]
    selected_turn = metadata.get("selected_turn")
    return (
        metadata.get("continuation_source") == expected_transition["source_status"]
        and metadata.get("selected_role") == expected_transition["role"]
        and (
            selected_turn is None
            or selected_turn == turn_name(expected_transition["target_turn_number"])
        )
    )


def collect_ignored_future_turns(turns: list[dict], index: int) -> tuple[list[str], list[dict]]:
    ignored = []
    conflicts = []
    for later_turn in turns[index + 1 :]:
        if later_turn["continuation_state"] == "not_started":
            ignored.append(turn_name(later_turn["turn_number"]))
            continue
        conflicts.append(
            {
                "turn": turn_name(later_turn["turn_number"]),
                "state": later_turn["continuation_state"],
            }
        )
    return ignored, conflicts


def resolve_turn_continuation(
    run_dir: Path,
    turns: list[dict],
    state: dict,
    *,
    index: int,
    expected_transition: dict | None = None,
) -> dict:
    turn = turns[index]
    continuation_state = turn["continuation_state"]
    turn_label = turn_name(turn["turn_number"])

    if expected_transition is not None and turn["turn_number"] != expected_transition["target_turn_number"]:
        raise ContinuationResolutionError(
            f"expected turn {turn_name(expected_transition['target_turn_number'])} after `{expected_transition['source_status']}`, "
            f"but found {turn_label} instead",
            details={
                "expected_turn": turn_name(expected_transition["target_turn_number"]),
                "found_turn": turn_label,
            },
        )

    if continuation_state == "ambiguous":
        raise ContinuationResolutionError(
            f"turn {turn_label} mixes reviewer activity with incomplete generator state",
            details={"turn": turn_label},
        )

    if continuation_state == "not_started":
        if expected_transition is not None:
            if not turn_matches_expected_transition(turn, expected_transition):
                raise ContinuationResolutionError(
                    f"turn {turn_label} exists but does not clearly match the expected transition from `{expected_transition['source_status']}`",
                    details={
                        "turn": turn_label,
                        "metadata": turn["metadata"],
                        "expected_source_status": expected_transition["source_status"],
                        "expected_role": expected_transition["role"],
                    },
                )
            ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
            if conflicts:
                raise ContinuationResolutionError(
                    f"turn {turn_label} is the expected next turn, but later turns already contain conflicting activity",
                    details={"turn": turn_label, "conflicts": conflicts},
                )
            return continuation_plan(
                turn_dir=turn["turn_dir"],
                turn_number=turn["turn_number"],
                role=expected_transition["role"],
                create_new_turn=False,
                reuse_existing_turn_for_first=bool(turn["metadata"]),
                prior_status=expected_transition["source_status"],
                continuation_state=continuation_state,
                reason=expected_transition["reason"] + " The target turn exists but has not started yet.",
                reference_turn_dir=turn["turn_dir"],
                source_turn_number=expected_transition["source_turn_number"],
                ignored_turns=ignored_turns,
            )
        if index == 0:
            ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
            if conflicts:
                raise ContinuationResolutionError(
                    f"turn {turn_label} has no role activity, but later turns already contain conflicting activity",
                    details={"turn": turn_label, "conflicts": conflicts},
                )
            selected_role = turn["metadata"].get("selected_role")
            role = selected_role if selected_role in ROLE_NAMES else fallback_continue_role(state)
            return continuation_plan(
                turn_dir=turn["turn_dir"],
                turn_number=turn["turn_number"],
                role=role,
                create_new_turn=False,
                reuse_existing_turn_for_first=bool(turn["metadata"]),
                prior_status="no_artifacts_present",
                continuation_state=continuation_state,
                reason=f"turn {turn_label} exists but no prompt or role artifacts were written yet.",
                reference_turn_dir=None,
                source_turn_number=None,
                ignored_turns=ignored_turns,
            )
        raise ContinuationResolutionError(
            f"turn {turn_label} has no role activity and no validated earlier turn explains it",
            details={"turn": turn_label, "metadata": turn["metadata"]},
        )

    if continuation_state in {"generator_pending", "generator_invalid"}:
        ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
        if conflicts:
            raise ContinuationResolutionError(
                f"turn {turn_label} still needs generator work, but later turns already contain conflicting activity",
                details={"turn": turn_label, "conflicts": conflicts},
            )
        return continuation_plan(
            turn_dir=turn["turn_dir"],
            turn_number=turn["turn_number"],
            role="generator",
            create_new_turn=False,
            reuse_existing_turn_for_first=True,
            prior_status=continuation_state,
            continuation_state=continuation_state,
            reason=f"turn {turn_label} still has incomplete or invalid generator artifacts.",
            reference_turn_dir=turn["turn_dir"],
            source_turn_number=turn["turn_number"],
            ignored_turns=ignored_turns,
        )

    if continuation_state in {
        "generator_complete_waiting_reviewer",
        "reviewer_pending",
        "reviewer_invalid",
    }:
        ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
        if conflicts:
            raise ContinuationResolutionError(
                f"turn {turn_label} still needs reviewer work, but later turns already contain conflicting activity",
                details={"turn": turn_label, "conflicts": conflicts},
            )
        reason = (
            f"generator finished on turn {turn_label}, but reviewer has not started yet."
            if continuation_state == "generator_complete_waiting_reviewer"
            else f"turn {turn_label} still has incomplete or invalid reviewer artifacts."
        )
        return continuation_plan(
            turn_dir=turn["turn_dir"],
            turn_number=turn["turn_number"],
            role="reviewer",
            create_new_turn=False,
            reuse_existing_turn_for_first=True,
            prior_status=continuation_state,
            continuation_state=continuation_state,
            reason=reason,
            reference_turn_dir=turn["turn_dir"],
            source_turn_number=turn["turn_number"],
            ignored_turns=ignored_turns,
        )

    if continuation_state == "reviewer_approved":
        ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
        if conflicts:
            raise ContinuationResolutionError(
                f"turn {turn_label} is already approved, but later turns contain conflicting activity",
                details={"turn": turn_label, "conflicts": conflicts},
            )
        return terminal_continuation_plan(
            turn_dir=turn["turn_dir"],
            turn_number=turn["turn_number"],
            continuation_state=continuation_state,
            reason=f"turn {turn_label} is approved; this run should not continue. Use `reopen` to supersede the approval explicitly.",
            ignored_turns=ignored_turns,
        )

    if continuation_state == "reviewer_blocked" and review_bridge_mode(state) == "github_pr_codex":
        ignored_turns, conflicts = collect_ignored_future_turns(turns, index)
        if conflicts:
            raise ContinuationResolutionError(
                f"turn {turn_label} still needs the GitHub reviewer bridge, but later turns contain conflicting activity",
                details={"turn": turn_label, "conflicts": conflicts},
            )
        return continuation_plan(
            turn_dir=turn["turn_dir"],
            turn_number=turn["turn_number"],
            role="reviewer",
            create_new_turn=False,
            reuse_existing_turn_for_first=True,
            prior_status=continuation_state,
            continuation_state=continuation_state,
            reason=f"turn {turn_label} is blocked in the GitHub reviewer bridge; resume reviewer on the same turn.",
            reference_turn_dir=turn["turn_dir"],
            source_turn_number=turn["turn_number"],
            ignored_turns=ignored_turns,
        )

    next_transition = next_turn_expectation(
        turn,
        continuation_state,
        review_bridge_mode(state),
    )
    if next_transition is None:
        raise ContinuationResolutionError(
            f"unsupported continuation state on turn {turn_label}: {continuation_state}",
            details={"turn": turn_label, "state": continuation_state},
        )
    if index + 1 >= len(turns):
        return continuation_plan(
            turn_dir=turn_dir_for(run_dir, next_transition["target_turn_number"]),
            turn_number=next_transition["target_turn_number"],
            role=next_transition["role"],
            create_new_turn=True,
            reuse_existing_turn_for_first=False,
            prior_status=continuation_state,
            continuation_state=continuation_state,
            reason=next_transition["reason"],
            reference_turn_dir=turn["turn_dir"],
            source_turn_number=turn["turn_number"],
            ignored_turns=[],
        )
    return resolve_turn_continuation(
        run_dir,
        turns,
        state,
        index=index + 1,
        expected_transition=next_transition,
    )


def resolve_continuation_plan(run_dir: Path, state: dict) -> dict:
    turns_root = run_dir / "turns"
    if not turns_root.exists() or not any(path.is_dir() for path in turns_root.iterdir()):
        turn_number = int(state.get("current_turn", 1))
        role = fallback_continue_role(state)
        return continuation_plan(
            turn_dir=turn_dir_for(run_dir, turn_number),
            turn_number=turn_number,
            role=role,
            create_new_turn=False,
            reuse_existing_turn_for_first=False,
            prior_status="no_turns_present",
            continuation_state="not_started",
            reason=f"run has no turn directories yet; resume from turn {turn_name(turn_number)}.",
            reference_turn_dir=None,
            source_turn_number=None,
            ignored_turns=[],
        )
    turns = [inspect_turn_for_continuation(turn_dir) for turn_dir in list_turn_dirs(run_dir)]
    return resolve_turn_continuation(run_dir, turns, state, index=0)


def inspect_continuation_plan(run_dir: Path, state: dict) -> dict:
    try:
        return resolve_continuation_plan(run_dir, state)
    except ContinuationResolutionError as exc:
        return {"mode": "error", "reason": str(exc), "details": exc.details}


def classify_continuation_state(run_dir: Path) -> tuple[Path, ArtifactContinuationState, dict]:
    plan = resolve_continuation_plan(run_dir, {"review_bridge": {"mode": "internal"}})
    if plan["mode"] == "terminal":
        return plan["turn_dir"], "reviewer_approved", {"reason": plan["reason"]}
    return plan["turn_dir"], plan["prior_status"], {"reason": plan["reason"]}


def determine_continue_target(run_dir: Path, state: dict) -> tuple[Path, int, str, bool, str]:
    try:
        plan = resolve_continuation_plan(run_dir, state)
    except ContinuationResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if plan["mode"] == "terminal":
        raise SystemExit(approved_run_continue_message())
    return (
        plan["turn_dir"],
        plan["turn_number"],
        plan["role"],
        plan["create_new_turn"],
        plan["prior_status"],
    )


def build_reopen_metadata(
    *,
    task_name: str,
    previous_run_dir: Path,
    approved_turn_dir: Path,
    approved_reviewer_status: dict,
    reason_kind: str,
    reason_message: str,
    doc_comparison: dict,
) -> dict:
    approved_turn_metadata = load_turn_metadata(approved_turn_dir)
    return {
        "event": "run_reopened",
        "reopened_at": now_ts(),
        "task_name": task_name,
        "reason_kind": reason_kind,
        "reason_message": reason_message,
        "reopened_from": {
            "run_id": previous_run_dir.name,
            "run_dir": str(previous_run_dir),
            "turn": approved_turn_dir.name,
            "turn_dir": str(approved_turn_dir),
            "approved_summary": approved_reviewer_status["summary"],
            "approved_recorded_at": approved_turn_metadata.get("updated_at"),
        },
        "doc_comparison": doc_comparison,
    }


def build_reopen_nonterminal_message(task_name: str, run_id: str, plan: dict) -> str:
    if plan["mode"] == "continue":
        return (
            f"cannot reopen run `{run_id}` because it is not approved; "
            f"it is currently `{plan['continuation_state']}` on turn `{turn_name(plan['turn_number'])}`. "
            f"Use `continue {task_name} --run-id {run_id}` instead."
        )
    return f"cannot reopen run `{run_id}` because it is not in an approved terminal state."


def clone_review_bridge_state_for_new_run(previous_state: dict) -> dict:
    mode = review_bridge_mode(previous_state)
    if mode != "github_pr_codex":
        return {"mode": "internal"}
    previous = previous_state["review_bridge"]["github"]
    return {
        "mode": "github_pr_codex",
        "github": {
            "base_branch": previous["base_branch"],
            "branch": previous["branch"],
            "branch_source": previous.get("branch_source", "auto"),
            "last_consumed_review_comment_body_sha256": None,
            "last_consumed_review_comment_created_at": None,
            "last_consumed_review_comment_id": None,
            "last_consumed_review_turn": None,
            "last_observed_head_sha": previous.get("last_observed_head_sha"),
            "last_request_comment_created_at": None,
            "last_request_comment_id": None,
            "last_request_turn": None,
            "pr_head_sha": previous.get("pr_head_sha"),
            "pr_number": previous.get("pr_number"),
            "pr_url": previous.get("pr_url"),
            "repo_name_with_owner": previous["repo_name_with_owner"],
            "repo_owner": previous["repo_owner"],
            "repo": previous["repo"],
            "repo_url": previous["repo_url"],
            "review_wait": {
                "deadline_at": None,
                "initial_wait_seconds": GITHUB_CODEX_INITIAL_WAIT_SECONDS,
                "last_polled_at": None,
                "poll_count": 0,
                "poll_interval_seconds": GITHUB_CODEX_POLL_INTERVAL_SECONDS,
                "started_at": None,
            },
        },
    }


def continue_run(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(f"missing task workspace: {task_root}")
    run_dir = resolve_run_dir(task_root, args.run_id)

    state = load_json(run_dir / "state.json")
    inspection = inspect_task_workspace(task_root)
    state["workspace_profile"] = inspection["profile"]
    try:
        continuation_plan_data = resolve_continuation_plan(run_dir, state)
    except ContinuationResolutionError as exc:
        raise SystemExit(str(exc)) from exc
    if continuation_plan_data["mode"] == "terminal":
        raise SystemExit(approved_run_continue_message())

    turn_number = continuation_plan_data["turn_number"]
    role = continuation_plan_data["role"]
    create_new_turn = continuation_plan_data["create_new_turn"]
    prior_status = continuation_plan_data["prior_status"]
    continue_context = build_continue_context(
        state=state,
        previous_turn_dir=continuation_plan_data["reference_turn_dir"],
        role=role,
        inspection=inspection,
    )
    if state.get("bootstrap_phase") == "fork_to_review" and prior_status == "reviewer_changes_requested":
        state["bootstrap_phase"] = None

    if create_new_turn:
        state["status"] = TRANSITIONING_TURN_STATUS
        state["current_turn"] = continuation_plan_data["source_turn_number"]
        state["pending_turn"] = turn_number
        state["pending_role"] = role
        state["transition_source_verdict"] = prior_status
    else:
        state["current_turn"] = turn_number
        state["pending_turn"] = None
        state["pending_role"] = None
        state["transition_source_verdict"] = None
        prompt_exists = (
            continuation_plan_data["reuse_existing_turn_for_first"]
            and role_prompt_path(continuation_plan_data["turn_dir"], role).exists()
        )
        if prompt_exists:
            state["status"] = "waiting_generator" if role == "generator" else "waiting_reviewer"
        else:
            state["status"] = "booting"
    state["stop_reason"] = None
    target_turn_dir = (
        begin_turn_transition(
            run_dir,
            state,
            task_root,
            from_turn=continuation_plan_data["source_turn_number"],
            to_turn=turn_number,
            from_role=(
                "reviewer"
                if prior_status.startswith("reviewer_")
                else "generator"
            ),
            to_role=role,
            source_verdict=prior_status,
            reason=continuation_plan_data["reason"],
        )
        if create_new_turn
        else continuation_plan_data["turn_dir"]
    )
    if not create_new_turn:
        save_run_state(run_dir, state)
        if continuation_plan_data["reuse_existing_turn_for_first"]:
            annotate_turn_continuation(
                target_turn_dir,
                continuation_source=prior_status,
                selected_role=role,
                selected_turn=turn_number,
                reason=continuation_plan_data["reason"],
            )
    append_run_event(
        run_dir,
        "run_continued",
        turn_number=turn_number,
        role=role,
        details={
            "prior_status": prior_status,
            "reason": continuation_plan_data["reason"],
            "ignored_turns": continuation_plan_data["ignored_turns"],
        },
    )
    supervisor_loop_from(
        run_dir,
        state,
        task_root,
        start_turn=turn_number,
        start_role=role,
        reuse_existing_turn_for_first=continuation_plan_data["reuse_existing_turn_for_first"],
        first_continue_context_block=continue_context,
    )

    final_state = load_json(run_dir / "state.json")
    print(f"run_dir: {run_dir}")
    print(f"continued role: {role}")
    print(f"continuation reason: {continuation_plan_data['reason']}")
    if continuation_plan_data["ignored_turns"]:
        print(f"ignored turns: {', '.join(continuation_plan_data['ignored_turns'])}")
    print(f"current_turn: {final_state['current_turn']}")
    print(f"final status: {final_state['status']}")
    if final_state.get("stop_reason"):
        print(f"stop reason: {final_state['stop_reason']}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run two real Codex TUIs against a target repo using a repo-local .codex-council workspace."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize .codex-council and a task workspace")
    init.add_argument("task_name")
    init.add_argument("--dir", help="target repository or working directory")
    init.add_argument("--allow-non-git", action="store_true")
    init.add_argument("--task")
    init.add_argument("--task-file")
    init.set_defaults(func=init_task)

    write = sub.add_parser("write", help="write or replace one canonical task document")
    write.add_argument("doc_kind", choices=["task", "review", "spec", "contract"])
    write.add_argument("task_name")
    write.add_argument("--dir", help="target repository or working directory")
    write.add_argument("--allow-non-git", action="store_true")
    write.add_argument("--body")
    write.add_argument("--body-file")
    write.set_defaults(func=write_document_command)

    start = sub.add_parser("start", help="start a council run for a task name")
    start.add_argument("task_name")
    start.add_argument("--dir", help="target repository or working directory")
    start.add_argument("--allow-non-git", action="store_true")
    start.add_argument("--run-id")
    start.add_argument("--generator-session")
    start.add_argument("--reviewer-session")
    start.add_argument("--fork-session-id")
    start.add_argument("--generator-fork-session-id")
    start.add_argument("--reviewer-fork-session-id")
    start.add_argument("--review-mode", choices=["internal", "github_pr_codex"], default="internal")
    start.add_argument("--github-pr")
    start.add_argument("--github-branch")
    start.add_argument("--github-base")
    start.add_argument("--start-role", choices=["auto", "generator", "reviewer"], default="auto")
    start.set_defaults(func=start_run)

    cont = sub.add_parser("continue", help="continue a stopped or paused council run")
    cont.add_argument("task_name")
    cont.add_argument("--dir", help="target repository or working directory")
    cont.add_argument("--allow-non-git", action="store_true")
    cont.add_argument("--run-id", default="latest")
    cont.set_defaults(func=continue_run)

    reopen = sub.add_parser("reopen", help="reopen an approved run into a fresh auditable run")
    reopen.add_argument("task_name")
    reopen.add_argument("--dir", help="target repository or working directory")
    reopen.add_argument("--allow-non-git", action="store_true")
    reopen.add_argument("--run-id", default="latest")
    reopen.add_argument("--reason-kind", choices=sorted(REOPEN_REASON_KINDS), required=True)
    reopen.add_argument("--reason", required=True)
    reopen.set_defaults(func=reopen_run)

    status = sub.add_parser("status", help="show the latest or chosen run state for a task")
    status.add_argument("task_name")
    status.add_argument("--dir", help="target repository or working directory")
    status.add_argument("--allow-non-git", action="store_true")
    status.add_argument("--run-id", default="latest")
    status.set_defaults(func=show_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
