#!/usr/bin/env python3

from __future__ import annotations

import argparse
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


COUNCIL_DIRNAME = ".codex-council"
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
CRITICAL_REVIEW_DIMENSIONS = (
    "correctness_vs_intent",
    "regression_risk",
    "failure_mode_and_fallback",
    "state_and_metadata_integrity",
    "test_adequacy",
    "maintainability",
)
TMUX_PANE_POLL_SECONDS = 0.5
TMUX_PASTE_SETTLE_SECONDS = 0.1
TMUX_CAPTURE_HISTORY_LINES = 1000
ROLE_ARTIFACT_POLL_SECONDS = 1.0
TASK_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

DEFAULT_COUNCIL_GITIGNORE = textwrap.dedent(
    """\
    # Generated council runtime data
    */runs/
    """
)

DEFAULT_CONFIG_TOML = textwrap.dedent(
    """\
    [codex]
    model = "gpt-5.4"
    model_reasoning_effort = "xhigh"
    dangerously_bypass_approvals_and_sandbox = true
    no_alt_screen = true

    [council]
    max_turns = 6
    launch_timeout_seconds = 60
    turn_timeout_seconds = 1800
    require_git = true
    """
)

DEFAULT_TASK_PLACEHOLDER = textwrap.dedent(
    """\
    Describe the requested work here as the canonical plan and brief for the council.

    Include:
    - goal / intended outcome
    - acceptance criteria
    - constraints
    - non-goals
    - relevant files, systems, endpoints, or UI flows
    - plan details, sequencing, or important implementation notes from the user
    """
)

DEFAULT_CONTRACT_PLACEHOLDER = textwrap.dedent(
    """\
    # Success Contract

    Write the definition of done for this task here as a checklist.

    Guidelines:
    - Keep this file short and audit-oriented.
    - Each bullet should describe something that must be true before approval.
    - The reviewer will copy this checklist into `reviewer.md` and mark items with `[x]` / `[ ]`.
    - Keep detailed architecture and implementation reasoning in `task.md`, not here.

    Example:
    - [ ] The main user-facing behavior works as intended.
    - [ ] Existing core behavior has not regressed.
    - [ ] Required tests were added or updated.
    """
)

DEFAULT_COUNCIL_BRIEF = textwrap.dedent(
    """\
    # Council Brief

    This task is handled by a two-agent council:
    - the generator implements or fixes the requested work
    - the reviewer checks fidelity to intent, correctness, risk, and test adequacy

    ## Mission
    - Deliver the user-requested outcome while adhering as closely as possible to the intent described in `task.md`.
    - Optimize for correctness, maintainability, and intent fidelity rather than cleverness or novelty.

    ## Source of truth
    - `task.md` is the canonical implementation plan and context for the requested work.
    - `contract.md` is the canonical definition of done and approval checklist for the task.
    - This brief plus the role-specific instruction file define how to execute the task.
    - If you need to know whether the plan or instructions changed between turns, inspect the canonical files directly and use git as needed.

    ## Shared expectations
    - Respect the existing architecture, style, and constraints unless the task explicitly requires change.
    - Prefer minimal, coherent changes over broad rewrites.
    - Do not silently change scope.
    - Surface contradictions, missing decisions, or dangerous assumptions explicitly.
    - Prefer clear contracts and verifiable outcomes over vague progress.
    - Generator implements against both `task.md` and `contract.md`.
    - Reviewer approves only when both the checklist in `contract.md` is satisfied and all critical review dimensions pass.

    ## Human intervention rule
    - If `task.md`, `contract.md`, this brief, or the role-specific instructions conflict or are too ambiguous to continue safely, stop and emit `needs_human`.
    - Use `human_message` to tell the user exactly what must be clarified, corrected, or added before work should continue, and name the faulty source explicitly.
    """
)

DEFAULT_GENERATOR_INSTRUCTIONS = textwrap.dedent(
    """\
    # Generator Instructions

    ## Mission
    - Implement the requested change so the result matches the intent in `task.md` and moves the codebase toward satisfying `contract.md`.

    ## Implementation bar
    - Resolve root cause, not symptoms.
    - Do not introduce unnecessary complexity, tech debt, speculative abstractions, or avoidable risk.
    - Keep diffs minimal, coherent, and aligned with the existing codebase.
    - Preserve architecture and style unless the task explicitly requires otherwise.

    ## Required reading
    - Read `task.md` first to understand the architecture, plan, and intended implementation.
    - Read `contract.md` before coding. It is the non-negotiable definition of done.
    - If these files disagree, do not guess. Emit `needs_human`.

    ## Change strategy
    - Work in clear, reviewable increments that materially advance the plan in `task.md`.
    - Prefer straightforward, production-quality solutions over clever shortcuts.
    - Do not silently skip difficult parts or paper over broken behavior.
    - If the task requires a tradeoff, choose the option that best preserves correctness, maintainability, and contract satisfaction.
    - Do not redefine success criteria yourself. `contract.md` owns the success criteria.
    - If you change a state, metadata, cache, checkpoint, fallback, or health/coverage contract, inspect both the writers and the downstream readers/consumers before ending the turn.

    ## Quality rules
    - Avoid regressions, broken migrations, unsafe assumptions, and partial implementations.
    - Update or add tests when the risk profile warrants it.
    - Keep changes explainable and reviewable.
    - Before ending the turn, sanity-check that your changes plausibly satisfy the relevant items in `contract.md` and do not obviously violate the task constraints.

    ## Required turn output
    - In `generator.md`, include:
      - What changed
      - Why those changes move the code toward satisfying `contract.md`
      - Changed invariants / preserved invariants
      - Downstream readers / consumers checked
      - Failure modes and fallback behavior considered
      - Verification performed
      - Remaining contract items not yet satisfied
      - Known risks or blockers
    - Do not claim completion unless the change plausibly satisfies the contract items it is supposed to address.

    ## Human intervention rule
    - Emit `needs_human` if `task.md` and `contract.md` conflict, if satisfying one contract item would clearly violate another, or if a missing design decision prevents a safe implementation.
    - Use `human_message` to describe exactly what the user must clarify or change, and name the faulty source explicitly.
    - Set `human_source` to the file or state boundary that caused the pause.
    """
)

DEFAULT_REVIEWER_INSTRUCTIONS = textwrap.dedent(
    """\
    # Reviewer Instructions

    ## Review objective
    - Use `task.md` to understand the plan, architecture, and intended implementation.
    - Use `contract.md` as the actual definition of done.
    - Verify the implementation matches the plan in `task.md` and satisfies the checklist in `contract.md`.
    - Act as a rigorous production code reviewer, not a stylistic nitpicker.
    - Be skeptical by default; do not give credit for work that only looks plausible.
    - Treat yourself as an external evaluator, not a collaborator trying to help the generator look good.

    ## Approval bar
    - Use `approved` only when no blocking issues remain.
    - Use `changes_requested` for fixable implementation issues that should go back to the generator.
    - Use `blocked` only for external blockers unrelated to plan quality.
    - Use `needs_human` when the plan itself is flawed, contradictory, unsafe, or requires a product/architecture decision beyond reviewer judgment.
    - Approval means both:
      - every relevant checklist item in `contract.md` is satisfied
      - every critical review dimension passes
    - If any critical review dimension fails or is still uncertain, the turn is not approvable.

    ## What to inspect
    - fidelity to `task.md`
    - satisfaction of each checklist item in `contract.md`
    - correctness of behavior versus intent
    - regressions relative to existing behavior
    - security, data loss, migration, and operational risk
    - API, UX, and contract mismatches
    - missing tests or weak verification for risky areas
    - concurrency, performance, and edge-case failures where relevant
    - code quality and maintainability of the implemented approach

    ## Review style
    - Prefer concrete, actionable blocking issues tied to code paths or behaviors.
    - Distinguish blocking findings from optional suggestions.
    - Avoid vague “improve this” feedback.
    - Use git and the latest commit range aggressively to understand exactly what changed before judging it.
    - Distrust the generator narrative by default; verify the code, the consumers, and the failure behavior yourself.
    - If the change touches state, metadata, checkpoints, caches, fallback paths, rebuild logic, or health/coverage semantics, inspect both writers and downstream readers/consumers.
    - Perform at least one independent falsification attempt on the riskiest changed invariant when the change touches silent degradation, partial failure, metadata drift, or fallback correctness.

    ## Required review structure
    - In `reviewer.md`, include:
      - Verdict summary
      - Contract checklist copied from `contract.md`, using `[x]` for satisfied and `[ ]` for not yet satisfied
      - Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`
      - Blocking issues
      - Independent verification performed
      - Residual risks or follow-up notes
    - The checklist should be the clearest answer to whether the loop is done.
    - Every unchecked contract item blocks approval unless it is clearly out of scope for the current task wording, and if that happens you must explain why.
    - Every critical review dimension must be explicitly marked; `approved` is invalid if any dimension is `[fail]` or `[uncertain]`.

    ## Human intervention rule
    - Emit `needs_human` if `contract.md` is ambiguous or incomplete, if `task.md` does not actually support the contract, or if approval would require guessing the intended interpretation of an unchecked contract item.
    - Use `human_message` to tell the user what must be clarified or corrected, and name the faulty source explicitly.
    - Set `human_source` to the file or state boundary that caused the pause.
    """
)


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


def required_task_files(task_root: Path) -> list[Path]:
    return [
        task_root / "task.md",
        task_root / "contract.md",
        task_root / "AGENTS.md",
        task_root / "generator.instructions.md",
        task_root / "reviewer.instructions.md",
    ]


def missing_task_files(task_root: Path) -> list[Path]:
    return [path for path in required_task_files(task_root) if not path.exists()]


def scaffold_council_root(repo_root: Path) -> None:
    council_root = council_root_for(repo_root)
    ensure_dir(council_root)
    write_if_missing(council_gitignore_path_for(repo_root), DEFAULT_COUNCIL_GITIGNORE)
    write_if_missing(config_path_for(repo_root), DEFAULT_CONFIG_TOML)


def scaffold_task_root(
    task_root: Path,
    *,
    initial_task_text: str | None,
) -> dict:
    ensure_dir(task_root)
    task_created = write_if_missing(
        task_root / "task.md",
        initial_task_text.strip() if initial_task_text else DEFAULT_TASK_PLACEHOLDER,
    )
    contract_created = write_if_missing(task_root / "contract.md", DEFAULT_CONTRACT_PLACEHOLDER)
    agents_created = write_if_missing(task_root / "AGENTS.md", DEFAULT_COUNCIL_BRIEF)
    generator_created = write_if_missing(
        task_root / "generator.instructions.md", DEFAULT_GENERATOR_INSTRUCTIONS
    )
    reviewer_created = write_if_missing(
        task_root / "reviewer.instructions.md", DEFAULT_REVIEWER_INSTRUCTIONS
    )
    return {
        "task_created": task_created,
        "task_needs_edit": task_created and not initial_task_text,
        "contract_created": contract_created,
        "agents_created": agents_created,
        "generator_created": generator_created,
        "reviewer_created": reviewer_created,
    }


def ensure_task_workspace_exists(task_root: Path) -> None:
    missing = missing_task_files(task_root)
    if missing:
        missing_lines = "\n".join(f"- {path}" for path in missing)
        raise SystemExit(
            f"task workspace is not initialized for {task_root.name}.\n"
            f"Run `init {task_root.name}` first.\n"
            f"Missing files:\n{missing_lines}"
        )


def load_council_config(repo_root: Path) -> dict:
    config_path = config_path_for(repo_root)
    if not config_path.exists():
        write_text(config_path, DEFAULT_CONFIG_TOML)
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
    return {
        "task_path": task_root / "task.md",
        "task_text": (task_root / "task.md").read_text(encoding="utf-8").strip(),
        "contract_path": task_root / "contract.md",
        "contract_text": (task_root / "contract.md").read_text(encoding="utf-8").strip(),
        "agents_path": task_root / "AGENTS.md",
        "agents_text": (task_root / "AGENTS.md").read_text(encoding="utf-8").strip(),
        "generator_path": task_root / "generator.instructions.md",
        "generator_text": (task_root / "generator.instructions.md").read_text(encoding="utf-8").strip(),
        "reviewer_path": task_root / "reviewer.instructions.md",
        "reviewer_text": (task_root / "reviewer.instructions.md").read_text(encoding="utf-8").strip(),
    }


def canonical_task_paths(task_root: Path) -> dict:
    return {
        "task": task_root / "task.md",
        "contract": task_root / "contract.md",
        "agents": task_root / "AGENTS.md",
        "generator": task_root / "generator.instructions.md",
        "reviewer": task_root / "reviewer.instructions.md",
    }


def prepare_turn(run_dir: Path, turn_number: int, materials: dict) -> Path:
    current = run_dir / "turns" / turn_name(turn_number)
    inputs_dir = current / "inputs"
    ensure_dir(inputs_dir)
    write_text(inputs_dir / "task.md", materials["task_text"])
    write_text(inputs_dir / "contract.md", materials["contract_text"])
    write_text(inputs_dir / "AGENTS.md", materials["agents_text"])
    write_text(inputs_dir / "generator.instructions.md", materials["generator_text"])
    write_text(inputs_dir / "reviewer.instructions.md", materials["reviewer_text"])
    return current


def role_artifact_paths(current_turn_dir: Path, role: str) -> tuple[Path, Path]:
    return (
        current_turn_dir / f"{role}.md",
        current_turn_dir / f"{role}.status.json",
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
    if not isinstance(value, str) or value not in HUMAN_SOURCES:
        raise ValueError(
            f"{role} human_source must be one of: {', '.join(sorted(HUMAN_SOURCES))}"
        )
    return value


def validate_generator_status(data: dict) -> dict:
    result = data.get("result")
    if not isinstance(result, str) or result not in GENERATOR_RESULTS:
        raise ValueError(f"invalid generator result: {result}")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("generator summary must be a non-empty string")
    changed_files = data.get("changed_files", [])
    if not isinstance(changed_files, list) or not all(isinstance(item, str) for item in changed_files):
        raise ValueError("generator changed_files must be a list of strings")
    human_message = data.get("human_message")
    human_source = data.get("human_source")
    if result == "needs_human":
        if not isinstance(human_message, str) or not human_message.strip():
            raise ValueError("generator human_message must be a non-empty string when result is needs_human")
        human_source = normalize_human_source(human_source, role="generator")
    elif human_message is not None and not isinstance(human_message, str):
        raise ValueError("generator human_message must be a string when present")
    elif human_source is not None:
        human_source = normalize_human_source(human_source, role="generator")
    commit_sha = data.get("commit_sha")
    compare_base_sha = data.get("compare_base_sha")
    branch = data.get("branch")
    if result == "implemented":
        for field_name, value in {
            "commit_sha": commit_sha,
            "compare_base_sha": compare_base_sha,
            "branch": branch,
        }.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"generator {field_name} must be a non-empty string when result is implemented")
    else:
        for field_name, value in {
            "commit_sha": commit_sha,
            "compare_base_sha": compare_base_sha,
            "branch": branch,
        }.items():
            if value is not None and not isinstance(value, str):
                raise ValueError(f"generator {field_name} must be a string when present")
    return {
        "result": result,
        "summary": summary.strip(),
        "changed_files": [item.strip() for item in changed_files],
        "commit_sha": commit_sha.strip() if isinstance(commit_sha, str) else None,
        "compare_base_sha": compare_base_sha.strip() if isinstance(compare_base_sha, str) else None,
        "branch": branch.strip() if isinstance(branch, str) else None,
        "human_message": human_message.strip() if isinstance(human_message, str) else None,
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
    human_message = data.get("human_message")
    human_source = data.get("human_source")
    if verdict == "needs_human":
        if not isinstance(human_message, str) or not human_message.strip():
            raise ValueError("reviewer human_message must be a non-empty string when verdict is needs_human")
        human_source = normalize_human_source(human_source, role="reviewer")
    elif human_message is not None and not isinstance(human_message, str):
        raise ValueError("reviewer human_message must be a string when present")
    elif human_source is not None:
        human_source = normalize_human_source(human_source, role="reviewer")
    reviewed_commit_sha = data.get("reviewed_commit_sha")
    if verdict in {"approved", "changes_requested"}:
        if not isinstance(reviewed_commit_sha, str) or not reviewed_commit_sha.strip():
            raise ValueError("reviewer reviewed_commit_sha must be a non-empty string when verdict is approved or changes_requested")
    elif reviewed_commit_sha is not None and not isinstance(reviewed_commit_sha, str):
        raise ValueError("reviewer reviewed_commit_sha must be a string when present")
    critical_dimensions = data.get("critical_dimensions")
    if not isinstance(critical_dimensions, dict):
        raise ValueError("reviewer critical_dimensions must be a dict")
    normalized_dimensions: dict[str, str] = {}
    for key in CRITICAL_REVIEW_DIMENSIONS:
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
        "reviewed_commit_sha": reviewed_commit_sha.strip() if isinstance(reviewed_commit_sha, str) else None,
        "human_message": human_message.strip() if isinstance(human_message, str) else None,
        "human_source": human_source,
        "critical_dimensions": normalized_dimensions,
    }


def format_turn_one_context(task_root: Path, role: str) -> str:
    paths = canonical_task_paths(task_root)
    role_path = paths[role]
    sections = [
        "Canonical council files for this task:",
        f"- {paths['task']}",
        f"- {paths['contract']}",
        f"- {paths['agents']}",
        f"- {role_path}",
        "",
        f"Shared council brief from {paths['agents']}:",
        paths["agents"].read_text(encoding="utf-8").strip(),
        "",
        f"Role instructions from {role_path}:",
        role_path.read_text(encoding="utf-8").strip(),
        "",
        f"Current plan from {paths['task']}:",
        paths["task"].read_text(encoding="utf-8").strip(),
        "",
        f"Definition of done from {paths['contract']}:",
        paths["contract"].read_text(encoding="utf-8").strip(),
    ]
    return "\n".join(sections).rstrip()


def format_contract_migration_warning(task_root: Path) -> str:
    task_text = (task_root / "task.md").read_text(encoding="utf-8")
    if "Success contract:" not in task_text:
        return ""
    return textwrap.dedent(
        """\
        Migration note:
        - `contract.md` is the canonical definition of done.
        - Any embedded “Success contract” prose inside `task.md` is secondary context only and must not override `contract.md`.
        """
    ).rstrip()


def format_later_turn_context(task_root: Path, role: str) -> str:
    paths = canonical_task_paths(task_root)
    role_path = paths[role]
    return textwrap.dedent(
        f"""\
        If you need current guidance or want to see whether the task changed since your last turn, inspect these canonical files directly:
        - {paths["task"]}
        - {paths["contract"]}
        - {paths["agents"]}
        - {role_path}
        
        Use git if you need to understand what changed between turns.
        """
    ).rstrip()


def build_generator_turn_prompt(
    repo_root: Path,
    task_root: Path,
    turn_dir: Path,
    turn_number: int,
    task_name: str,
    git_state: dict | None,
    *,
    inline_context: bool,
) -> str:
    sections: list[str] = [f"Repository root:\n{repo_root}"]
    if inline_context:
        sections.append(format_turn_one_context(task_root, "generator"))
    else:
        sections.append(format_later_turn_context(task_root, "generator"))
    migration_warning = format_contract_migration_warning(task_root)
    if migration_warning:
        sections.append(migration_warning)
    sections.append(f"Turn {turn_name(turn_number)}.")
    if turn_number > 1:
        previous_turn_dir = turn_dir.parent / turn_name(turn_number - 1)
        sections.append(
            "Before making changes, read the previous reviewer artifacts carefully:\n"
            f"- {previous_turn_dir / 'reviewer.md'}\n"
            f"- {previous_turn_dir / 'reviewer.status.json'}"
        )
    if git_state and git_state.get("enabled"):
        sections.append(
            textwrap.dedent(
                f"""\
                This run is operating on git branch `{git_state["current_branch"]}`.
                If you implement code changes in this turn:
                - commit them on the current branch with message `council({task_name}): turn {turn_name(turn_number)}`
                - report `commit_sha`, `compare_base_sha`, and `branch` in `generator.status.json`

                For turn {turn_name(turn_number)}, `compare_base_sha` must be:
                `{git_state["last_generator_commit_sha"] or git_state["base_commit_sha"]}`
                """
            ).rstrip()
        )
    sections.append(
        "Implement the requested change carefully. If the plan is critically flawed, contradictory, or unsafe to continue, emit `needs_human` instead of guessing.\n\n"
        "When the implementation is complete, write exactly these files:\n"
        f"- {turn_dir / 'generator.md'}\n"
        f"- {turn_dir / 'generator.status.json'}\n\n"
        "In `generator.md`, include at minimum:\n"
        "- What changed\n"
        "- Why those changes move the code toward satisfying `contract.md`\n"
        "- Changed invariants / preserved invariants\n"
        "- Downstream readers / consumers checked\n"
        "- Failure modes and fallback behavior considered\n"
        "- Verification performed\n"
        "- Remaining contract items not yet satisfied\n"
        "- Known risks or blockers\n\n"
        "The status JSON must be exactly this shape:\n"
        '{"result":"implemented|no_changes_needed|blocked|needs_human","summary":"short string","changed_files":["relative/path"],"commit_sha":"required when implemented","compare_base_sha":"required when implemented","branch":"required when implemented","human_message":"required when needs_human","human_source":"required when needs_human"}'
    )
    sections.append("After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.")
    return "\n\n".join(sections).rstrip()


def build_reviewer_turn_prompt(
    repo_root: Path,
    task_root: Path,
    turn_dir: Path,
    turn_number: int,
    git_state: dict | None,
    *,
    inline_context: bool,
) -> str:
    sections: list[str] = [f"Repository root:\n{repo_root}"]
    if inline_context:
        sections.append(format_turn_one_context(task_root, "reviewer"))
    else:
        sections.append(format_later_turn_context(task_root, "reviewer"))
    migration_warning = format_contract_migration_warning(task_root)
    if migration_warning:
        sections.append(migration_warning)
    sections.extend(
        [
            f"Turn {turn_name(turn_number)}.",
            "The generator has completed a change. Review the current repository state and these files carefully:\n"
            f"- {turn_dir / 'generator.md'}\n"
            f"- {turn_dir / 'generator.status.json'}",
        ]
    )
    if git_state and git_state.get("enabled"):
        sections.append(
            textwrap.dedent(
                """\
                Use git as the primary source of what changed.
                Read `generator.status.json` to get `branch`, `compare_base_sha`, and `commit_sha`, then inspect:
                - `git show <commit_sha>`
                - `git diff <compare_base_sha>..<commit_sha>`
                - any other git commands you need to understand the latest generator change set
                Treat git history as the primary record of the latest change set, and use repository state plus artifacts as supporting context.
                If generator reported `no_changes_needed`, inspect the current HEAD and write that HEAD commit as `reviewed_commit_sha`.
                If the change touches state, metadata, checkpoints, caches, rebuild logic, health checks, or fallback behavior, inspect both the writers and the downstream readers/consumers.
                Perform at least one independent falsification or negative-path check on the riskiest changed invariant.
                """
            ).rstrip()
        )
    sections.extend(
        [
            "When the review is complete, write exactly these files:\n"
            f"- {turn_dir / 'reviewer.md'}\n"
            f"- {turn_dir / 'reviewer.status.json'}\n\n"
            "In `reviewer.md`, include at minimum:\n"
            "- Verdict summary\n"
            "- Contract checklist copied from `contract.md`, using `[x]` and `[ ]`\n"
            "- Critical review dimensions, using `[pass]`, `[fail]`, or `[uncertain]`\n"
            "- Blocking issues\n"
            "- Independent verification performed\n"
            "- Residual risks or follow-up notes\n\n"
            "The status JSON must be exactly this shape:\n"
            '{"verdict":"approved|changes_requested|blocked|needs_human","summary":"short string","blocking_issues":["issue"],"reviewed_commit_sha":"required for approved or changes_requested","critical_dimensions":{"correctness_vs_intent":"pass|fail|uncertain","regression_risk":"pass|fail|uncertain","failure_mode_and_fallback":"pass|fail|uncertain","state_and_metadata_integrity":"pass|fail|uncertain","test_adequacy":"pass|fail|uncertain","maintainability":"pass|fail|uncertain"},"human_message":"required when needs_human","human_source":"required when needs_human"}',
            "Use `approved` only when no blocking issues remain and every critical review dimension is `pass`. Use `changes_requested` when more generator work is required. Use `blocked` only for external blockers. Use `needs_human` when the plan or instructions themselves require user clarification.",
            "After producing the required artifacts for this turn, end your turn. Do not continue with extra speculative work beyond the requested deliverables for this turn.",
        ]
    )
    return "\n\n".join(sections).rstrip()


def write_prompt_artifact(turn_dir: Path, role: str, prompt: str) -> None:
    write_text(turn_dir / f"supervisor_to_{role}.md", prompt)


def write_final_message_artifact(turn_dir: Path, role: str, message: str) -> None:
    write_text(turn_dir / f"{role}.final_message.md", message)


def write_raw_final_output_artifact(turn_dir: Path, role: str, tmux_name: str) -> None:
    # Trace/debug only. This file must never be used as a control signal.
    write_text(turn_dir / role / "raw_final_output.md", capture_last_tmux_slice(tmux_name))


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
    state["status"] = "paused_needs_human"
    state["stop_reason"] = summary
    save_run_state(run_dir, state)
    print(f"{role} paused the council and requested human intervention.", flush=True)
    print(f"read: {turn_dir / f'{role}.md'}", flush=True)
    print(f"read: {turn_dir / f'{role}.status.json'}", flush=True)
    if human_source:
        print(f"human_source: {human_source}", flush=True)
    if human_message:
        print(f"human_message: {human_message}", flush=True)
    print(
        "update task.md / AGENTS.md / role instructions as needed, then start a fresh run.",
        flush=True,
    )


def create_run_state(
    *,
    repo_root: Path,
    task_root: Path,
    task_name: str,
    run_id: str,
    council_config: dict,
    git_state: dict | None,
    generator_session: str,
    reviewer_session: str,
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
                "last_wait_phase": None,
                "tmux_session": generator_session,
            },
            "reviewer": {
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
    }


def save_run_state(run_dir: Path, state: dict) -> None:
    save_json(run_dir / "state.json", state)


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
    codex_command = build_codex_command(repo_root, state["council_config"]["codex"])
    for role in ("generator", "reviewer"):
        role_state = state["roles"][role]
        phase = f"{role}_session_start"
        role_state["last_wait_phase"] = phase
        save_run_state(run_dir, state)
        tmux_new_session(role_state["tmux_session"], repo_root, codex_command, role=role)
    save_run_state(run_dir, state)


def verify_generator_git_metadata(
    repo_root: Path, git_state: dict, generator_status: dict, task_name: str, turn_number: int
) -> str:
    commit_sha = generator_status["commit_sha"]
    compare_base_sha = generator_status["compare_base_sha"]
    branch = generator_status["branch"]
    expected_branch = git_state["current_branch"]
    expected_base = git_state["last_generator_commit_sha"] or git_state["base_commit_sha"]

    if branch != expected_branch:
        raise SupervisorRuntimeError(
            "generator_git_metadata",
            f"generator reported branch {branch} but expected {expected_branch}",
            role="generator",
        )
    if compare_base_sha != expected_base:
        raise SupervisorRuntimeError(
            "generator_git_metadata",
            f"generator reported compare_base_sha {compare_base_sha} but expected {expected_base}",
            role="generator",
        )
    head_sha = git_stdout(repo_root, "rev-parse", "HEAD")
    if head_sha != commit_sha:
        raise SupervisorRuntimeError(
            "generator_git_metadata",
            f"generator reported commit_sha {commit_sha} but repo HEAD is {head_sha}",
            role="generator",
        )
    expected_message = f"council({task_name}): turn {turn_name(turn_number)}"
    actual_message = git_stdout(repo_root, "log", "-1", "--pretty=%s")
    if actual_message != expected_message:
        raise SupervisorRuntimeError(
            "generator_git_metadata",
            f"latest commit message is `{actual_message}` but expected `{expected_message}`",
            role="generator",
        )
    return commit_sha


def verify_reviewer_commit_reference(
    expected_reviewed_commit_sha: str | None, reviewer_status: dict
) -> None:
    reviewed_commit_sha = reviewer_status["reviewed_commit_sha"]
    if reviewed_commit_sha != expected_reviewed_commit_sha:
        raise SupervisorRuntimeError(
            "reviewer_git_metadata",
            f"reviewer reported reviewed_commit_sha {reviewed_commit_sha} but expected {expected_reviewed_commit_sha}",
            role="reviewer",
        )


def wait_for_tmux_sessions_ready(run_dir: Path, state: dict) -> None:
    launch_timeout_seconds = float(state["council_config"]["council"]["launch_timeout_seconds"])
    for role in ("generator", "reviewer"):
        state["roles"][role]["last_wait_phase"] = f"{role}_tmux_boot"
        save_run_state(run_dir, state)
        wait_for_tmux_prompt(
            state["roles"][role]["tmux_session"],
            launch_timeout_seconds,
            phase=f"{role}_tmux_boot",
            role=role,
        )


def supervisor_loop(run_dir: Path, state: dict, task_root: Path) -> None:
    repo_root = Path(state["repo_root"])
    turn_timeout_seconds = float(state["council_config"]["council"]["turn_timeout_seconds"])
    git_state = state.get("git")

    for turn_number in range(1, int(state["council_config"]["council"]["max_turns"]) + 1):
        state["current_turn"] = turn_number
        materials = load_task_materials(task_root)
        current_turn_dir = prepare_turn(run_dir, turn_number, materials)
        save_run_state(run_dir, state)

        generator_prompt = build_generator_turn_prompt(
            repo_root,
            task_root,
            current_turn_dir,
            turn_number,
            state["task_name"],
            git_state,
            inline_context=turn_number == 1,
        )
        write_prompt_artifact(current_turn_dir, "generator", generator_prompt)
        state["status"] = "waiting_generator"
        state["roles"]["generator"]["last_wait_phase"] = "generator_prompt_ready"
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
            current_turn_dir,
            "generator",
            generator_artifact_path.read_text(encoding="utf-8"),
        )
        write_raw_final_output_artifact(
            current_turn_dir,
            "generator",
            state["roles"]["generator"]["tmux_session"],
        )
        if git_state and git_state.get("enabled") and generator_status["result"] == "implemented":
            git_state["last_generator_commit_sha"] = verify_generator_git_metadata(
                repo_root,
                git_state,
                generator_status,
                state["task_name"],
                turn_number,
            )
            save_run_state(run_dir, state)
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
            return

        reviewer_prompt = build_reviewer_turn_prompt(
            repo_root,
            task_root,
            current_turn_dir,
            turn_number,
            git_state,
            inline_context=turn_number == 1,
        )
        write_prompt_artifact(current_turn_dir, "reviewer", reviewer_prompt)
        state["status"] = "waiting_reviewer"
        state["roles"]["reviewer"]["last_wait_phase"] = "reviewer_prompt_ready"
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
            current_turn_dir,
            "reviewer",
            reviewer_artifact_path.read_text(encoding="utf-8"),
        )
        write_raw_final_output_artifact(
            current_turn_dir,
            "reviewer",
            state["roles"]["reviewer"]["tmux_session"],
        )

        if git_state and git_state.get("enabled") and reviewer_status["verdict"] in {"approved", "changes_requested"}:
            verify_reviewer_commit_reference(
                git_state["last_generator_commit_sha"] or git_state["base_commit_sha"],
                reviewer_status,
            )

        if reviewer_status["verdict"] == "approved":
            state["status"] = "approved"
            state["stop_reason"] = reviewer_status["summary"]
            save_run_state(run_dir, state)
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
            return

    state["status"] = "max_turns_reached"
    state["stop_reason"] = f"reached max turns ({state['council_config']['council']['max_turns']})"
    save_run_state(run_dir, state)


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
    ensure_task_workspace_exists(task_root)
    council_config = load_council_config(repo_root)
    materials = load_task_materials(task_root)
    if not materials["task_text"] or materials["task_text"] == DEFAULT_TASK_PLACEHOLDER.strip():
        raise SystemExit(
            f"{task_root / 'task.md'} is still a placeholder. Fill it in before running start."
        )
    git_state = git_preflight(repo_root) if is_git else None

    run_id = args.run_id or run_id_value()
    run_dir = task_root / "runs" / run_id
    if run_dir.exists():
        raise SystemExit(f"run directory already exists: {run_dir}")
    ensure_dir(run_dir / "turns")

    generator_session = args.generator_session or build_tmux_session_name(task_name, "generator", run_id)
    reviewer_session = args.reviewer_session or build_tmux_session_name(task_name, "reviewer", run_id)

    state = create_run_state(
        repo_root=repo_root,
        task_root=task_root,
        task_name=task_name,
        run_id=run_id,
        council_config=council_config,
        git_state=git_state,
        generator_session=generator_session,
        reviewer_session=reviewer_session,
    )
    save_run_state(run_dir, state)

    try:
        create_tmux_sessions(run_dir, state)
        print(f"repo_root: {repo_root}")
        print(f"task_root: {task_root}")
        print(f"run_id: {run_id}")
        print(f"run_dir: {run_dir}")
        if git_state and git_state.get("enabled"):
            print(f"git branch: {git_state['current_branch']}")
            print(f"git base_commit: {git_state['base_commit_sha']}")
        print(f"generator tmux: {generator_session}")
        print(f"reviewer tmux: {reviewer_session}")
        print(f"attach generator: tmux attach -t {generator_session}")
        print(f"attach reviewer: tmux attach -t {reviewer_session}")

        wait_for_tmux_sessions_ready(run_dir, state)
        print("both Codex TUI sessions are ready")
        supervisor_loop(run_dir, state, task_root)
    except SupervisorRuntimeError as error:
        state = load_json(run_dir / "state.json")
        state["status"] = "blocked"
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
    print(f"task: {task_root / 'task.md'}")
    print(f"contract: {task_root / 'contract.md'}")
    print(f"agents: {task_root / 'AGENTS.md'}")
    print(f"generator: {task_root / 'generator.instructions.md'}")
    print(f"reviewer: {task_root / 'reviewer.instructions.md'}")
    if result["task_needs_edit"]:
        print("next: edit task.md and any instruction files, then run `start`")
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

    start = sub.add_parser("start", help="start a council run for a task name")
    start.add_argument("task_name")
    start.add_argument("--dir", help="target repository or working directory")
    start.add_argument("--allow-non-git", action="store_true")
    start.add_argument("--run-id")
    start.add_argument("--generator-session")
    start.add_argument("--reviewer-session")
    start.set_defaults(func=start_run)

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
