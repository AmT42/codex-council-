#!/usr/bin/env python3

from __future__ import annotations

import argparse
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
WORKSPACE_MODE_SPEC_BACKED = "spec_backed"
WORKSPACE_MODE_INHERITED_CONTEXT = "inherited_context"
WORKSPACE_MODES = {
    WORKSPACE_MODE_SPEC_BACKED,
    WORKSPACE_MODE_INHERITED_CONTEXT,
}
ROLE_NAMES = ("generator", "reviewer")
SPEC_BACKED_REQUIRED_FILENAMES = (
    "task.md",
    "contract.md",
    "AGENTS.md",
    "generator.instructions.md",
    "reviewer.instructions.md",
)
INHERITED_CONTEXT_REQUIRED_FILENAMES = (
    "AGENTS.md",
    "generator.instructions.md",
    "reviewer.instructions.md",
)
GENERATOR_RESULTS = {"implemented", "no_changes_needed", "blocked", "needs_human"}
REVIEWER_VERDICTS = {"approved", "changes_requested", "blocked", "needs_human"}
HUMAN_SOURCES = {
    "task.md",
    "contract.md",
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
CHECKLIST_ITEM_RE = re.compile(r"^\s*(?:[-*]\s*)?\[\s*[xX]?\s*\]\s+\S")
CONTRACT_PLACEHOLDER_MARKERS = (
    "Write the definition of done for this task here as a checklist.",
    "Bad examples:",
)
TASK_REQUIRED_HEADINGS = (
    "# Feature Spec",
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
ARTIFACT_REPAIR_ATTEMPTS = 1
SESSION_RECOVERY_ATTEMPTS = 1
RAW_OUTPUT_CAPTURE_TIMEOUT_SECONDS = 30.0
TERMINAL_SUMMARY_BEGIN = "COUNCIL_TERMINAL_SUMMARY_BEGIN"
TERMINAL_SUMMARY_END = "COUNCIL_TERMINAL_SUMMARY_END"


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


def build_task_spec_from_seed(initial_task_text: str) -> str:
    stripped = initial_task_text.strip()
    if stripped.startswith("# Feature Spec"):
        return stripped
    return textwrap.dedent(
        f"""\
        # Feature Spec

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
    args: list[str], *, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        check=check,
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


def latest_turn_dir(run_dir: Path) -> Path:
    turns_root = run_dir / "turns"
    if not turns_root.exists():
        raise SystemExit(f"missing turns directory: {turns_root}")
    candidates = sorted(path for path in turns_root.iterdir() if path.is_dir())
    if not candidates:
        raise SystemExit(f"no turns found for run: {run_dir}")
    return candidates[-1]


def events_path_for(run_dir: Path) -> Path:
    return run_dir / "events.jsonl"


def codex_session_index_path() -> Path:
    return Path.home() / ".codex" / "session_index.jsonl"


def turn_dir_for(run_dir: Path, turn_number: int) -> Path:
    return run_dir / "turns" / turn_name(turn_number)


def turn_metadata_path(turn_dir: Path) -> Path:
    return turn_dir / "turn.json"


def context_manifest_path(turn_dir: Path) -> Path:
    return turn_dir / "context_manifest.json"


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
    task_path = task_root / "task.md"
    contract_path = task_root / "contract.md"
    task_exists = task_path.exists()
    contract_exists = contract_path.exists()
    if task_exists != contract_exists:
        raise SystemExit(
            f"invalid task workspace for {task_root.name}.\n"
            "task.md and contract.md must either both exist or both be absent."
        )
    workspace_mode = (
        WORKSPACE_MODE_SPEC_BACKED
        if task_exists
        else WORKSPACE_MODE_INHERITED_CONTEXT
    )
    filenames = (
        SPEC_BACKED_REQUIRED_FILENAMES
        if workspace_mode == WORKSPACE_MODE_SPEC_BACKED
        else INHERITED_CONTEXT_REQUIRED_FILENAMES
    )
    required_files = [task_root / name for name in filenames]
    return {
        "workspace_mode": workspace_mode,
        "required_files": required_files,
        "missing_files": [path for path in required_files if not path.exists()],
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
    skip_task_and_contract: bool = False,
) -> dict:
    ensure_dir(task_root)
    if skip_task_and_contract and initial_task_text:
        raise SystemExit("cannot seed task text when --skip-task-and-contract is set")
    task_created = False
    contract_created = False
    if not skip_task_and_contract:
        task_template = (
            build_task_spec_from_seed(initial_task_text)
            if initial_task_text
            else read_template("scaffold", "task.md")
        )
        task_created = write_if_missing(
            task_root / "task.md",
            task_template,
        )
        contract_created = write_if_missing(
            task_root / "contract.md",
            read_template("scaffold", "contract.md"),
        )
    agents_created = write_if_missing(
        task_root / "AGENTS.md",
        read_template(
            "scaffold",
            "AGENTS.inherited_context.md" if skip_task_and_contract else "AGENTS.md",
        ),
    )
    generator_created = write_if_missing(
        task_root / "generator.instructions.md",
        read_template(
            "scaffold",
            (
                "generator.instructions.inherited_context.md"
                if skip_task_and_contract
                else "generator.instructions.md"
            ),
        ),
    )
    reviewer_created = write_if_missing(
        task_root / "reviewer.instructions.md",
        read_template(
            "scaffold",
            (
                "reviewer.instructions.inherited_context.md"
                if skip_task_and_contract
                else "reviewer.instructions.md"
            ),
        ),
    )
    return {
        "task_created": task_created,
        "task_needs_edit": task_created and not initial_task_text and not skip_task_and_contract,
        "contract_created": contract_created,
        "agents_created": agents_created,
        "generator_created": generator_created,
        "reviewer_created": reviewer_created,
        "workspace_mode": (
            WORKSPACE_MODE_INHERITED_CONTEXT
            if skip_task_and_contract
            else WORKSPACE_MODE_SPEC_BACKED
        ),
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


def lint_task_workspace_readiness(task_root: Path) -> tuple[list[str], list[str]]:
    task_text = (task_root / "task.md").read_text(encoding="utf-8")
    contract_text = (task_root / "contract.md").read_text(encoding="utf-8")
    errors: list[str] = []
    warnings: list[str] = []
    for heading in TASK_REQUIRED_HEADINGS:
        if heading not in task_text:
            errors.append(f"task.md is missing required heading: {heading}")
    lowered_task = task_text.lower()
    for vague_word in TASK_VAGUE_WORDS:
        if vague_word in lowered_task:
            warnings.append(
                f"task.md uses vague wording `{vague_word}`; decompose it into concrete feature-spec behavior or constraints"
            )
    if any(marker in contract_text for marker in CONTRACT_PLACEHOLDER_MARKERS):
        errors.append("contract.md still contains scaffold placeholder text")
    if "# Definition of Done" not in contract_text:
        errors.append("contract.md must begin with `# Definition of Done`")
    if not contract_checklist_items(contract_text):
        errors.append("contract.md must contain at least one checklist item")
    if "Success contract:" in task_text:
        warnings.append(
            "task.md still contains embedded `Success contract:` prose; `contract.md` is canonical"
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


def pane_shows_prompt(pane_text: str) -> bool:
    lines = [line.rstrip() for line in pane_text.splitlines() if line.strip()]
    for line in lines[-20:]:
        if line.lstrip().startswith("›"):
            return True
    return False


def pane_has_context_overflow(pane_text: str) -> bool:
    lowered = pane_text.lower()
    return (
        "ran out of room in the model's context window" in lowered
        or "start a new thread or clear earlier history before retrying" in lowered
    )


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
    buffer_name = f"codex-council-{uuid.uuid4().hex}"
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


def turn_name(turn_number: int) -> str:
    return f"{turn_number:04d}"


def run_id_value() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]


def build_tmux_session_name(task_name: str, role: str, run_id: str) -> str:
    return f"codex-{role}-{task_name}-{run_id}"


def load_task_materials(task_root: Path) -> dict:
    inspection = inspect_task_workspace(task_root)
    materials = {
        "workspace_mode": inspection["workspace_mode"],
        "agents_path": task_root / "AGENTS.md",
        "agents_text": (task_root / "AGENTS.md").read_text(encoding="utf-8").strip(),
        "generator_path": task_root / "generator.instructions.md",
        "generator_text": (task_root / "generator.instructions.md").read_text(encoding="utf-8").strip(),
        "reviewer_path": task_root / "reviewer.instructions.md",
        "reviewer_text": (task_root / "reviewer.instructions.md").read_text(encoding="utf-8").strip(),
    }
    if inspection["workspace_mode"] == WORKSPACE_MODE_SPEC_BACKED:
        materials["task_path"] = task_root / "task.md"
        materials["task_text"] = (task_root / "task.md").read_text(encoding="utf-8").strip()
        materials["contract_path"] = task_root / "contract.md"
        materials["contract_text"] = (task_root / "contract.md").read_text(encoding="utf-8").strip()
    else:
        materials["task_path"] = task_root / "task.md"
        materials["task_text"] = ""
        materials["contract_path"] = task_root / "contract.md"
        materials["contract_text"] = ""
    return materials


def canonical_task_paths(task_root: Path, workspace_mode: str | None = None) -> dict:
    mode = workspace_mode or inspect_task_workspace(task_root)["workspace_mode"]
    paths = {
        "agents": task_root / "AGENTS.md",
        "generator": task_root / "generator.instructions.md",
        "reviewer": task_root / "reviewer.instructions.md",
    }
    if mode == WORKSPACE_MODE_SPEC_BACKED:
        paths["task"] = task_root / "task.md"
        paths["contract"] = task_root / "contract.md"
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

def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshot_context_manifest(run_dir: Path, task_root: Path) -> dict:
    inspection = inspect_task_workspace(task_root)
    manifest: dict[str, dict] = {
        "generated_at": now_ts(),
        "files": {},
        "workspace_mode": inspection["workspace_mode"],
    }
    for key, canonical_path in canonical_task_paths(
        task_root,
        inspection["workspace_mode"],
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
    payload = {
        "turn": turn_name(turn_number),
        "phase": phase,
        "updated_at": now_ts(),
    }
    if role:
        payload["role"] = role
    if details:
        payload["details"] = details
    save_json(turn_metadata_path(turn_dir), payload)


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
) -> None:
    metadata = load_turn_metadata(turn_dir) if turn_metadata_path(turn_dir).exists() else {}
    metadata["continuation_source"] = continuation_source
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
        if (
            session_recovery_attempts < SESSION_RECOVERY_ATTEMPTS
            and pane_shows_prompt(pane_text)
            and pane_has_context_overflow(pane_text)
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


def format_turn_one_context(task_root: Path, role: str, workspace_mode: str) -> str:
    paths = canonical_task_paths(task_root, workspace_mode)
    role_path = paths[role]
    sections = ["Canonical council files for this task:"]
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        sections.extend(
            [
                f"- {paths['task']}",
                f"- {paths['contract']}",
            ]
        )
    sections.extend(
        [
            f"- {paths['agents']}",
            f"- {role_path}",
            "",
            f"Shared council brief from {paths['agents']}:",
            paths["agents"].read_text(encoding="utf-8").strip(),
            "",
            f"Role instructions from {role_path}:",
            role_path.read_text(encoding="utf-8").strip(),
        ]
    )
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        sections.extend(
            [
                "",
                f"Current feature spec from {paths['task']}:",
                paths["task"].read_text(encoding="utf-8").strip(),
                "",
                f"Current definition of done from {paths['contract']}:",
                paths["contract"].read_text(encoding="utf-8").strip(),
            ]
        )
    else:
        sections.extend(
            [
                "",
                "This task is currently operating in inherited-context mode.",
                "Rely on the inherited chat context in this Codex session, the current repository state, and the available council files above.",
            ]
        )
    return "\n".join(sections).rstrip()


def format_contract_migration_warning(task_root: Path, workspace_mode: str) -> str:
    if workspace_mode != WORKSPACE_MODE_SPEC_BACKED:
        return ""
    task_text = (task_root / "task.md").read_text(encoding="utf-8")
    if "Success contract:" not in task_text:
        return ""
    return textwrap.dedent(
        """\
        Migration note:
        - `task.md` is the canonical feature spec.
        - `contract.md` is the canonical definition of done.
        - Any embedded “Success contract” prose inside `task.md` is secondary context only and must not override `contract.md`.
        """
    ).rstrip()


def format_later_turn_context(task_root: Path, role: str, workspace_mode: str) -> str:
    paths = canonical_task_paths(task_root, workspace_mode)
    role_path = paths[role]
    lines = [
        "If you need current guidance or want to see whether the canonical files changed since your last turn, inspect these files directly:",
    ]
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        lines.extend(
            [
                f"- {paths['task']}",
                f"- {paths['contract']}",
            ]
        )
    lines.extend(
        [
            f"- {paths['agents']}",
            f"- {role_path}",
        ]
    )
    return textwrap.dedent(
        "\n".join(lines)
    ).rstrip()


def build_continue_context(
    *,
    state: dict,
    previous_turn_dir: Path | None,
    role: str,
    workspace_mode: str,
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
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        lines.append(
            "Before proceeding, reread the canonical feature spec, definition of done, and council files, and account for any direct human guidance already present in this chat session."
        )
    else:
        lines.append(
            "Before proceeding, reread the available canonical council files, inspect the current repository state, and account for any direct human guidance already present in this chat session."
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
    workspace_mode: str,
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
        if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
            previous_reviewer_focus = textwrap.dedent(
                f"""\
                The previous reviewer verdict was `changes_requested`.
                This generator turn must do one of these:
                - make concrete code, test, config, or documentation changes that reduce the reviewer blocking issues
                - emit `needs_human` if the remaining blocker comes from an ambiguous, non-auditable, or contradictory task/contract

                Do not use `blocked` merely because the overall contract is still large or not yet complete.
                Use `blocked` only for a real external implementation blocker unrelated to clarifying the task itself.

                Reviewer blocking issues to address:
                {joined_issues}
                """
            ).rstrip()
        else:
            previous_reviewer_focus = textwrap.dedent(
                f"""\
                The previous reviewer verdict was `changes_requested`.
                This generator turn must do one of these:
                - make concrete code, test, config, or documentation changes that reduce the reviewer blocking issues
                - emit `needs_human` if the remaining blocker comes from ambiguous inherited context, contradictory instructions, or unclear repository state

                Do not use `blocked` merely because the remaining work is broad or incomplete.
                Use `blocked` only for a real external implementation blocker unrelated to clarifying the task itself.

                Reviewer blocking issues to address:
                {joined_issues}
                """
            ).rstrip()
    values = {
        "repo_root": str(repo_root),
        "task_name": task_name,
        "task_path": str(task_root / "task.md"),
        "contract_path": str(task_root / "contract.md"),
        "agents_path": str(task_root / "AGENTS.md"),
        "role_instructions_path": str(task_root / "generator.instructions.md"),
        "turn_name": turn_name(turn_number),
        "turn_one_context_block": format_turn_one_context(task_root, "generator", workspace_mode),
        "later_turn_context_block": format_later_turn_context(task_root, "generator", workspace_mode),
        "continue_context_block": continue_context_block,
        "fork_context_block": fork_context_block,
        "migration_warning_block": format_contract_migration_warning(task_root, workspace_mode),
        "previous_reviewer_message_path": str(role_message_path(previous_turn_dir, "reviewer")),
        "previous_reviewer_status_path": str(previous_reviewer_status_path),
        "previous_reviewer_focus_block": previous_reviewer_focus,
        "generator_message_path": str(role_message_path(turn_dir, "generator")),
        "generator_status_path": str(role_status_path(turn_dir, "generator")),
    }
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        template_name = "generator_turn_1.md" if inline_context else "generator_turn_n.md"
    else:
        template_name = (
            "generator_inherited_turn_1.md"
            if inline_context
            else "generator_inherited_turn_n.md"
        )
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
    workspace_mode: str,
    inline_context: bool,
    continue_context_block: str = "",
    fork_context_block: str = "",
) -> str:
    values = {
        "repo_root": str(repo_root),
        "task_name": task_root.name,
        "task_path": str(task_root / "task.md"),
        "contract_path": str(task_root / "contract.md"),
        "agents_path": str(task_root / "AGENTS.md"),
        "role_instructions_path": str(task_root / "reviewer.instructions.md"),
        "turn_name": turn_name(turn_number),
        "turn_one_context_block": format_turn_one_context(task_root, "reviewer", workspace_mode),
        "later_turn_context_block": format_later_turn_context(task_root, "reviewer", workspace_mode),
        "continue_context_block": continue_context_block,
        "fork_context_block": fork_context_block,
        "migration_warning_block": format_contract_migration_warning(task_root, workspace_mode),
        "generator_message_path": str(role_message_path(turn_dir, "generator")),
        "generator_status_path": str(role_status_path(turn_dir, "generator")),
        "reviewer_message_path": str(role_message_path(turn_dir, "reviewer")),
        "reviewer_status_path": str(role_status_path(turn_dir, "reviewer")),
        "critical_review_dimensions_block": format_review_dimensions_block(),
    }
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        template_name = "reviewer_turn_1.md" if inline_context else "reviewer_turn_n.md"
    else:
        template_name = (
            "reviewer_inherited_turn_1.md"
            if inline_context
            else "reviewer_inherited_turn_n.md"
        )
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
        captured_text = capture_last_tmux_slice(tmux_name)
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
    workspace_mode = state.get("workspace_mode", WORKSPACE_MODE_SPEC_BACKED)
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
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        next_step = "update task.md / contract.md / AGENTS.md / role instructions as needed, then use `continue` to resume this run."
    else:
        next_step = (
            "update the available council brief or role instructions as needed; you may also add a repo-local feature spec and definition-of-done to switch into spec-backed mode, then use `continue` to resume this run."
        )
    print(next_step, flush=True)


def create_run_state(
    *,
    repo_root: Path,
    task_root: Path,
    task_name: str,
    run_id: str,
    workspace_mode: str,
    council_config: dict,
    git_state: dict | None,
    generator_session: str,
    reviewer_session: str,
    generator_bootstrap_mode: str = "fresh",
    reviewer_bootstrap_mode: str = "fresh",
    generator_fork_parent_session_id: str | None = None,
    reviewer_fork_parent_session_id: str | None = None,
) -> dict:
    run_dir = task_root / "runs" / run_id
    return {
        "created_at": now_ts(),
        "council_config": council_config,
        "council_root": str(council_root_for(repo_root)),
        "current_turn": 1,
        "diagnostics_dir": str(run_dir / "diagnostics"),
        "git": git_state,
        "repo_root": str(repo_root),
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
        "workspace_mode": workspace_mode,
    }


def save_run_state(run_dir: Path, state: dict) -> None:
    save_json(run_dir / "state.json", state)


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
    for role in ("generator", "reviewer"):
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
    for role in ("generator", "reviewer"):
        tmux_name = state["roles"][role]["tmux_session"]
        write_text(failure_dir / f"{role}.pane.txt", tmux_capture_joined_pane(tmux_name))
    return failure_dir


def create_tmux_sessions(run_dir: Path, state: dict) -> None:
    repo_root = Path(state["repo_root"])
    for role in ROLE_NAMES:
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
    for role in ROLE_NAMES:
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
    workspace_mode = inspect_task_workspace(task_root)["workspace_mode"]
    state["workspace_mode"] = workspace_mode
    turn_timeout_seconds = float(state["council_config"]["council"]["turn_timeout_seconds"])
    generator_prompt = build_generator_turn_prompt(
        repo_root,
        task_root,
        current_turn_dir,
        turn_number,
        state["task_name"],
        workspace_mode=workspace_mode,
        inline_context=inline_context,
        continue_context_block=continue_context_block,
        fork_context_block=format_fork_context_block(state["roles"]["generator"]),
    )
    write_prompt_artifact(current_turn_dir, "generator", generator_prompt)
    state["status"] = "waiting_generator"
    state["roles"]["generator"]["last_wait_phase"] = "generator_prompt_ready"
    save_run_state(run_dir, state)
    save_turn_metadata(current_turn_dir, turn_number, "generator_prompt_sent", role="generator")
    append_run_event(
        run_dir,
        "generator_prompt_sent",
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
) -> dict:
    repo_root = Path(state["repo_root"])
    workspace_mode = inspect_task_workspace(task_root)["workspace_mode"]
    state["workspace_mode"] = workspace_mode
    turn_timeout_seconds = float(state["council_config"]["council"]["turn_timeout_seconds"])
    reviewer_prompt = build_reviewer_turn_prompt(
        repo_root,
        task_root,
        current_turn_dir,
        turn_number,
        workspace_mode=workspace_mode,
        inline_context=inline_context,
        continue_context_block=continue_context_block,
        fork_context_block=format_fork_context_block(state["roles"]["reviewer"]),
    )
    write_prompt_artifact(current_turn_dir, "reviewer", reviewer_prompt)
    state["status"] = "waiting_reviewer"
    state["roles"]["reviewer"]["last_wait_phase"] = "reviewer_prompt_ready"
    save_run_state(run_dir, state)
    save_turn_metadata(current_turn_dir, turn_number, "reviewer_prompt_sent", role="reviewer")
    append_run_event(
        run_dir,
        "reviewer_prompt_sent",
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
        state["workspace_mode"] = inspect_task_workspace(task_root)["workspace_mode"]
        state["current_turn"] = turn_number
        if turn_number == start_turn and reuse_existing_turn_for_first:
            current_turn_dir = turn_dir_for(run_dir, turn_number)
            ensure_dir(role_dir_for(current_turn_dir, "generator"))
            ensure_dir(role_dir_for(current_turn_dir, "reviewer"))
        else:
            current_turn_dir = prepare_turn(run_dir, turn_number, task_root)
        save_run_state(run_dir, state)

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
            reviewer_status = run_reviewer_phase(
                run_dir,
                state,
                task_root,
                turn_number,
                current_turn_dir,
                inline_context=turn_number == 1,
            )
        else:
            reviewer_status = run_reviewer_phase(
                run_dir,
                state,
                task_root,
                turn_number,
                current_turn_dir,
                inline_context=turn_number == 1,
                continue_context_block=continue_context_block,
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


def start_run(args: argparse.Namespace) -> int:
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
    workspace_mode = inspection["workspace_mode"]
    if workspace_mode == WORKSPACE_MODE_INHERITED_CONTEXT and not is_git:
        raise SystemExit("inherited-context mode requires a git worktree and cannot start with --allow-non-git")
    council_config = load_council_config(repo_root)
    if workspace_mode == WORKSPACE_MODE_SPEC_BACKED:
        materials = load_task_materials(task_root)
        if not materials["task_text"] or materials["task_text"] == default_scaffold_text("task.md").strip():
            raise SystemExit(
                f"{task_root / 'task.md'} is still a placeholder. Fill it in before running start."
            )
        readiness_errors, readiness_warnings = lint_task_workspace_readiness(task_root)
        if readiness_errors:
            formatted = "\n".join(f"- {item}" for item in readiness_errors)
            raise SystemExit(
                f"{task_root} is not ready for start.\n"
                f"Fix these issues first:\n{formatted}"
            )
        for warning in readiness_warnings:
            print(f"warning: {warning}")
    if workspace_mode == WORKSPACE_MODE_INHERITED_CONTEXT:
        if not args.generator_fork_session_id or not args.reviewer_fork_session_id:
            raise SystemExit(
                "inherited-context mode requires both --generator-fork-session-id and --reviewer-fork-session-id"
            )
    for session_id in (args.generator_fork_session_id, args.reviewer_fork_session_id):
        if session_id and not find_codex_session_entry(session_id):
            raise SystemExit(f"unknown fork parent session id: {session_id}")
    if is_git:
        git_state = (
            git_preflight(repo_root)
            if workspace_mode == WORKSPACE_MODE_SPEC_BACKED
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
    reviewer_session = args.reviewer_session or build_tmux_session_name(task_name, "reviewer", run_id)
    session_index_snapshot_ids = [entry["id"] for entry in read_codex_session_index()]

    state = create_run_state(
        repo_root=repo_root,
        task_root=task_root,
        task_name=task_name,
        run_id=run_id,
        workspace_mode=workspace_mode,
        council_config=council_config,
        git_state=git_state,
        generator_session=generator_session,
        reviewer_session=reviewer_session,
        generator_bootstrap_mode="fork" if args.generator_fork_session_id else "fresh",
        reviewer_bootstrap_mode="fork" if args.reviewer_fork_session_id else "fresh",
        generator_fork_parent_session_id=args.generator_fork_session_id,
        reviewer_fork_parent_session_id=args.reviewer_fork_session_id,
    )
    state["session_index_snapshot_ids"] = session_index_snapshot_ids
    save_run_state(run_dir, state)
    append_run_event(run_dir, "run_created", details={"task_name": task_name})

    try:
        create_tmux_sessions(run_dir, state)
        print(f"repo_root: {repo_root}")
        print(f"task_root: {task_root}")
        print(f"run_id: {run_id}")
        print(f"run_dir: {run_dir}")
        print(f"generator tmux: {generator_session}")
        print(f"reviewer tmux: {reviewer_session}")
        print(f"attach generator: tmux attach -t {generator_session}")
        print(f"attach reviewer: tmux attach -t {reviewer_session}")

        wait_for_tmux_sessions_ready(run_dir, state)
        print("both Codex TUI sessions are ready")
        supervisor_loop(run_dir, state, task_root)
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


def init_task(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)

    scaffold_council_root(repo_root)
    task_root = task_root_for(repo_root, task_name)
    initial_task_text = read_text_arg(args.task, args.task_file, default="").strip()
    if args.skip_task_and_contract:
        result = scaffold_task_root(
            task_root,
            initial_task_text=None,
            skip_task_and_contract=True,
        )
    else:
        result = scaffold_task_root(task_root, initial_task_text=initial_task_text or None)

    print(f"repo_root: {repo_root}")
    print(f"council_root: {council_root_for(repo_root)}")
    print(f"task_root: {task_root}")
    print(f"config: {config_path_for(repo_root)}")
    if result["workspace_mode"] == WORKSPACE_MODE_SPEC_BACKED:
        print(f"task: {task_root / 'task.md'}")
        print(f"contract: {task_root / 'contract.md'}")
    else:
        print("task/contract: skipped for inherited-context mode")
    print(f"agents: {task_root / 'AGENTS.md'}")
    print(f"generator: {task_root / 'generator.instructions.md'}")
    print(f"reviewer: {task_root / 'reviewer.instructions.md'}")
    if result["task_needs_edit"]:
        print("next: edit task.md and any instruction files, then run `start`")
    elif result["workspace_mode"] == WORKSPACE_MODE_INHERITED_CONTEXT:
        print("next: edit the inherited-context instruction files, then run `start` with both fork session ids")
    else:
        print("next: review/edit the scaffolded files if needed, then run `start`")
    return 0


def show_status(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(f"missing task workspace: {task_root}")

    run_id = args.run_id
    if run_id in (None, "latest"):
        run_dir = latest_run_dir(task_root)
    else:
        run_dir = task_root / "runs" / run_id
        if not run_dir.exists():
            raise SystemExit(f"missing run directory: {run_dir}")

    state_path = run_dir / "state.json"
    if not state_path.exists():
        raise SystemExit(f"missing run state: {state_path}")
    print(json.dumps(load_json(state_path), indent=2, sort_keys=True))
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


def classify_continuation_state(run_dir: Path) -> tuple[Path, ArtifactContinuationState, dict]:
    latest_turn = latest_turn_dir(run_dir)
    generator = inspect_role_artifacts(latest_turn, "generator", validate_generator_status)
    if generator["state"] == "pending":
        return latest_turn, "generator_pending", generator
    if generator["state"] == "invalid":
        return latest_turn, "generator_invalid", generator

    generator_result = generator["validated_status"]["result"]
    if generator_result == "needs_human":
        return latest_turn, "generator_needs_human", generator
    if generator_result == "blocked":
        return latest_turn, "generator_blocked", generator

    reviewer = inspect_role_artifacts(latest_turn, "reviewer", validate_reviewer_status)
    if reviewer["state"] == "pending":
        return latest_turn, "reviewer_pending", reviewer
    if reviewer["state"] == "invalid":
        return latest_turn, "reviewer_invalid", reviewer

    reviewer_verdict = reviewer["validated_status"]["verdict"]
    if reviewer_verdict == "approved":
        return latest_turn, "reviewer_approved", reviewer
    if reviewer_verdict == "changes_requested":
        return latest_turn, "reviewer_changes_requested", reviewer
    if reviewer_verdict == "needs_human":
        return latest_turn, "reviewer_needs_human", reviewer
    return latest_turn, "reviewer_blocked", reviewer


def determine_continue_target(run_dir: Path, state: dict) -> tuple[Path, int, str, bool, str]:
    turns_root = run_dir / "turns"
    if not turns_root.exists() or not any(turns_root.iterdir()):
        fallback_role = "generator" if state.get("status") != "waiting_reviewer" else "reviewer"
        return run_dir / "turns" / turn_name(state.get("current_turn", 1)), int(state.get("current_turn", 1)), fallback_role, True, "no_turns_present"

    latest_turn, continuation_state, details = classify_continuation_state(run_dir)

    if continuation_state == "generator_pending":
        return latest_turn, int(latest_turn.name), "generator", False, continuation_state
    if continuation_state == "generator_invalid":
        return latest_turn, int(latest_turn.name), "generator", False, continuation_state
    if continuation_state == "reviewer_pending":
        return latest_turn, int(latest_turn.name), "reviewer", False, continuation_state
    if continuation_state == "reviewer_invalid":
        return latest_turn, int(latest_turn.name), "reviewer", False, continuation_state
    if continuation_state == "reviewer_approved":
        raise SystemExit("cannot continue an approved run")
    if continuation_state == "reviewer_changes_requested":
        return latest_turn, int(latest_turn.name) + 1, "generator", True, continuation_state
    if continuation_state == "reviewer_needs_human":
        return latest_turn, int(latest_turn.name) + 1, "reviewer", True, continuation_state
    if continuation_state == "reviewer_blocked":
        return latest_turn, int(latest_turn.name) + 1, "reviewer", True, continuation_state
    if continuation_state == "generator_needs_human":
        return latest_turn, int(latest_turn.name) + 1, "generator", True, continuation_state
    if continuation_state == "generator_blocked":
        return latest_turn, int(latest_turn.name) + 1, "generator", True, continuation_state
    raise SystemExit(f"unsupported continuation state: {details}")


def continue_run(args: argparse.Namespace) -> int:
    task_name = validate_task_name(args.task_name)
    target_input = Path(args.dir or Path.cwd()).resolve()
    repo_root, _ = resolve_target_root(target_input, allow_non_git=args.allow_non_git)
    task_root = task_root_for(repo_root, task_name)
    if not task_root.exists():
        raise SystemExit(f"missing task workspace: {task_root}")

    run_id = args.run_id
    run_dir = latest_run_dir(task_root) if run_id in (None, "latest") else task_root / "runs" / run_id
    if not run_dir.exists():
        raise SystemExit(f"missing run directory: {run_dir}")

    state = load_json(run_dir / "state.json")
    workspace_mode = inspect_task_workspace(task_root)["workspace_mode"]
    state["workspace_mode"] = workspace_mode
    latest_turn, turn_number, role, create_new_turn, prior_status = determine_continue_target(run_dir, state)
    previous_turn_dir = latest_turn if create_new_turn else (turn_dir_for(run_dir, turn_number - 1) if turn_number > 1 else None)
    continue_context = build_continue_context(
        state=state,
        previous_turn_dir=previous_turn_dir,
        role=role,
        workspace_mode=workspace_mode,
    )

    state["current_turn"] = turn_number
    state["stop_reason"] = None
    save_run_state(run_dir, state)
    append_run_event(
        run_dir,
        "run_continued",
        turn_number=turn_number,
        role=role,
        details={"prior_status": prior_status},
    )
    target_turn_dir = prepare_turn(run_dir, turn_number, task_root) if create_new_turn else turn_dir_for(run_dir, turn_number)
    annotate_turn_continuation(
        target_turn_dir,
        continuation_source=prior_status,
        selected_role=role,
        selected_turn=turn_number,
    )
    supervisor_loop_from(
        run_dir,
        state,
        task_root,
        start_turn=turn_number,
        start_role=role,
        reuse_existing_turn_for_first=not create_new_turn,
        first_continue_context_block=continue_context,
    )

    final_state = load_json(run_dir / "state.json")
    print(f"run_dir: {run_dir}")
    print(f"continued role: {role}")
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
    init.add_argument("--skip-task-and-contract", action="store_true")
    init.set_defaults(func=init_task)

    start = sub.add_parser("start", help="start a council run for a task name")
    start.add_argument("task_name")
    start.add_argument("--dir", help="target repository or working directory")
    start.add_argument("--allow-non-git", action="store_true")
    start.add_argument("--run-id")
    start.add_argument("--generator-session")
    start.add_argument("--reviewer-session")
    start.add_argument("--generator-fork-session-id")
    start.add_argument("--reviewer-fork-session-id")
    start.set_defaults(func=start_run)

    cont = sub.add_parser("continue", help="continue a stopped or paused council run")
    cont.add_argument("task_name")
    cont.add_argument("--dir", help="target repository or working directory")
    cont.add_argument("--allow-non-git", action="store_true")
    cont.add_argument("--run-id", default="latest")
    cont.set_defaults(func=continue_run)

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
