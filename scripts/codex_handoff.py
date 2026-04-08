#!/usr/bin/env python3

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import uuid


DEFAULT_STATE_DIR = ".codex-handoff"
DEFAULT_MAX_TURNS_PER_AGENT = 12
TERMINAL_REPLY_PREFIXES = (
    "no changes",
    "no changes made",
    "no changes applied",
    "no new findings",
)
DEFAULT_TO_REVIEWER = textwrap.dedent(
    """\
    Review the generator output below.
    Focus on bugs, regressions, missing tests, and unclear reasoning.
    Return concrete feedback the generator can act on.

    Generator output:

    {message}
    """
)
DEFAULT_TO_GENERATOR = textwrap.dedent(
    """\
    Revise your previous work using the reviewer feedback below.
    Apply the fixes directly and summarize what changed.

    Reviewer feedback:

    {message}
    """
)


def now_ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data) -> None:
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as fh:
        json.dump(data, fh, indent=2, sort_keys=True)
        fh.write("\n")
        tmp_name = fh.name
    os.replace(tmp_name, path)


def read_text(value: str | None, file_path: str | None, default: str = "") -> str:
    if value and file_path:
        raise SystemExit("pass either a literal value or a file, not both")
    if file_path:
        path = Path(file_path)
        if not path.exists():
            raise SystemExit(
                f"missing file: {file_path}\n"
                f"create it first or pass the prompt inline with the matching option"
            )
        return path.read_text(encoding="utf-8")
    if value is not None:
        return value
    return default


def normalize_text(text: str) -> str:
    return " ".join(text.lower().split())


def is_terminal_reply(reply: str) -> bool:
    normalized = normalize_text(reply)
    if not normalized:
        return True
    if any(normalized.startswith(prefix) for prefix in TERMINAL_REPLY_PREFIXES):
        return True
    if "approved state" in normalized and (
        "no changes" in normalized or "no new findings" in normalized
    ):
        return True
    return False


def state_paths(root: Path) -> dict[str, Path]:
    return {
        "root": root,
        "config": root / "config.json",
        "lock": root / "global.lock",
        "queues": root / "queues",
        "processing": root / "processing",
        "processed": root / "processed",
        "agents": root / "agents",
        "logs": root / "logs",
    }


def agent_state_path(root: Path, agent: str) -> Path:
    return state_paths(root)["agents"] / f"{agent}.json"


def queue_dir(root: Path, agent: str) -> Path:
    return state_paths(root)["queues"] / agent


def processing_dir(root: Path, agent: str) -> Path:
    return state_paths(root)["processing"] / agent


def processed_dir(root: Path, agent: str) -> Path:
    return state_paths(root)["processed"] / agent


@contextlib.contextmanager
def global_lock(root: Path):
    lock_path = state_paths(root)["lock"]
    ensure_dir(lock_path.parent)
    with lock_path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def ensure_state_tree(root: Path) -> None:
    paths = state_paths(root)
    for key in ("root", "queues", "processing", "processed", "agents", "logs"):
        ensure_dir(paths[key])
    for agent in ("generator", "reviewer"):
        ensure_dir(queue_dir(root, agent))
        ensure_dir(processing_dir(root, agent))
        ensure_dir(processed_dir(root, agent))


def clear_state_tree(root: Path) -> None:
    paths = state_paths(root)
    for path in paths["agents"].glob("*.json"):
        path.unlink()
    for agent in ("generator", "reviewer"):
        for folder in (queue_dir(root, agent), processing_dir(root, agent), processed_dir(root, agent)):
            for path in folder.glob("*.json"):
                path.unlink()
    for log_dir in paths["logs"].glob("*"):
        if log_dir.is_dir():
            for path in log_dir.glob("*.log"):
                path.unlink()


def build_config(args: argparse.Namespace) -> dict:
    generator_prompt = read_text(
        args.generator_prompt,
        args.generator_prompt_file,
        default="You are the code generator. Produce the requested changes directly.",
    ).strip()
    reviewer_prompt = read_text(
        args.reviewer_prompt,
        args.reviewer_prompt_file,
        default=(
            "You are the code reviewer. Review changes with a strict code review mindset. "
            "Prioritize bugs, regressions, missing tests, and unclear assumptions."
        ),
    ).strip()
    to_reviewer = read_text(
        args.to_reviewer_template,
        args.to_reviewer_template_file,
        default=DEFAULT_TO_REVIEWER,
    ).rstrip()
    to_generator = read_text(
        args.to_generator_template,
        args.to_generator_template_file,
        default=DEFAULT_TO_GENERATOR,
    ).rstrip()
    for name, template in {
        "to-reviewer template": to_reviewer,
        "to-generator template": to_generator,
    }.items():
        if "{message}" not in template:
            raise SystemExit(f"{name} must contain {{message}}")
    return {
        "created_at": now_ts(),
        "workspace_root": str(Path.cwd().resolve()),
        "poll_interval_seconds": args.poll_interval,
        "loop_policy": {
            "max_turns_per_agent": args.max_turns_per_agent,
            "stop_on_repeated_reply": True,
            "stop_on_terminal_reply": not args.allow_terminal_handoff,
        },
        "codex": {
            "model": args.model,
            "sandbox": args.sandbox,
            "approval": args.approval,
            "full_auto": args.full_auto,
            "skip_git_repo_check": args.skip_git_repo_check,
            "extra_args": args.codex_arg or [],
        },
        "agents": {
            "generator": {
                "peer": "reviewer",
                "bootstrap_prompt": generator_prompt,
                "forward_template": to_reviewer,
            },
            "reviewer": {
                "peer": "generator",
                "bootstrap_prompt": reviewer_prompt,
                "forward_template": to_generator,
            },
        },
    }


def write_log(root: Path, agent: str, message_id: str, text: str) -> Path:
    path = state_paths(root)["logs"] / agent / f"{message_id}.log"
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    return path


def enqueue_message(root: Path, to_agent: str, body: str, sender: str) -> Path:
    ensure_dir(queue_dir(root, to_agent))
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    msg_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": msg_id,
        "created_at": now_ts(),
        "from": sender,
        "to": to_agent,
        "body": body,
    }
    target = queue_dir(root, to_agent) / f"{msg_id}.json"
    save_json(target, payload)
    return target


def claim_next_message(root: Path, agent: str) -> Path | None:
    inbox = queue_dir(root, agent)
    work = processing_dir(root, agent)
    ensure_dir(inbox)
    ensure_dir(work)
    for candidate in sorted(inbox.glob("*.json")):
        target = work / candidate.name
        try:
            os.replace(candidate, target)
            return target
        except FileNotFoundError:
            continue
    return None


def build_prompt(bootstrap_prompt: str, sender: str, body: str, is_first_turn: bool) -> str:
    body = body.rstrip()
    if is_first_turn:
        return textwrap.dedent(
            f"""\
            {bootstrap_prompt}

            First incoming message from {sender}:

            {body}
            """
        ).rstrip()
    return textwrap.dedent(
        f"""\
        Incoming message from {sender}:

        {body}
        """
    ).rstrip()


def locate_session_file(thread_id: str, timeout_seconds: float = 15.0) -> Path | None:
    root = Path.home() / ".codex" / "sessions"
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matches = list(root.rglob(f"*{thread_id}.jsonl"))
        if matches:
            return matches[0]
        time.sleep(0.2)
    return None


def stream_session_events(agent: str, thread_id: str, stop_event: threading.Event) -> None:
    session_file = locate_session_file(thread_id)
    if not session_file:
        return

    tool_started: set[str] = set()
    with session_file.open("r", encoding="utf-8") as fh:
        while not stop_event.is_set():
            line = fh.readline()
            if not line:
                time.sleep(0.2)
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type")
            payload = event.get("payload", {})
            if event_type == "event_msg" and payload.get("type") == "agent_message":
                message = payload.get("message", "").strip()
                phase = payload.get("phase")
                if message and phase == "commentary":
                    print(f"[{agent} commentary] {message}", flush=True)
            elif event_type == "response_item":
                item_type = payload.get("type")
                if item_type in {"function_call", "custom_tool_call"}:
                    call_id = payload.get("call_id")
                    if call_id and call_id not in tool_started:
                        tool_started.add(call_id)
                        name = payload.get("name", "tool")
                        print(f"[{agent} tool] {name}", flush=True)


def run_codex(
    workspace_root: Path, agent: str, prompt: str, thread_id: str | None, codex_cfg: dict
) -> tuple[str, str, dict]:
    if thread_id:
        cmd = ["codex", "exec", "resume", "--json"]
    else:
        cmd = ["codex", "exec", "--json"]
    if codex_cfg.get("model"):
        cmd.extend(["--model", codex_cfg["model"]])
    if codex_cfg.get("sandbox"):
        cmd.extend(["--sandbox", codex_cfg["sandbox"]])
    if codex_cfg.get("approval"):
        cmd.extend(["--ask-for-approval", codex_cfg["approval"]])
    if codex_cfg.get("full_auto"):
        cmd.append("--full-auto")
    if codex_cfg.get("skip_git_repo_check"):
        cmd.append("--skip-git-repo-check")
    cmd.extend(codex_cfg.get("extra_args", []))
    if thread_id:
        cmd.extend([thread_id, prompt])
    else:
        cmd.append(prompt)

    proc = subprocess.Popen(
        cmd,
        cwd=workspace_root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    assert proc.stderr is not None

    actual_thread_id = thread_id
    last_message = ""
    usage: dict = {}
    raw_events: list[str] = []
    session_monitor_stop = threading.Event()
    session_monitor: threading.Thread | None = None

    for raw_line in proc.stdout:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        raw_events.append(line)
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            print(f"[codex-json] {line}", flush=True)
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            actual_thread_id = event.get("thread_id", actual_thread_id)
            if actual_thread_id:
                print(f"[thread] {actual_thread_id}", flush=True)
                if session_monitor is None:
                    session_monitor = threading.Thread(
                        target=stream_session_events,
                        args=(agent, actual_thread_id, session_monitor_stop),
                        daemon=True,
                    )
                    session_monitor.start()
        elif event_type == "item.completed":
            item = event.get("item", {})
            if item.get("type") == "agent_message":
                last_message = item.get("text", "")
        elif event_type == "turn.completed":
            usage = event.get("usage", {})

    stderr_text = proc.stderr.read()
    return_code = proc.wait()
    session_monitor_stop.set()
    if session_monitor is not None:
        session_monitor.join(timeout=1.0)
    if return_code != 0:
        raise RuntimeError(
            f"codex exited with {return_code}\n\nSTDERR:\n{stderr_text}\n\nSTDOUT:\n"
            + "\n".join(raw_events)
        )
    if not actual_thread_id:
        raise RuntimeError("codex did not emit a thread id")
    return actual_thread_id, last_message.rstrip(), usage


def process_message(root: Path, agent: str, msg_path: Path, config: dict) -> None:
    message = load_json(msg_path, default=None)
    if message is None:
        raise RuntimeError(f"failed to load message {msg_path}")
    state_path = agent_state_path(root, agent)
    state = load_json(state_path, default={})
    agent_cfg = config["agents"][agent]
    prompt = build_prompt(
        bootstrap_prompt=agent_cfg["bootstrap_prompt"],
        sender=message["from"],
        body=message["body"],
        is_first_turn=not state.get("thread_id"),
    )

    print(f"[{agent}] processing {message['id']} from {message['from']}", flush=True)
    thread_id, reply, usage = run_codex(
        workspace_root=Path(config["workspace_root"]),
        agent=agent,
        prompt=prompt,
        thread_id=state.get("thread_id"),
        codex_cfg=config["codex"],
    )
    normalized_reply = normalize_text(reply)
    state.update(
        {
            "agent": agent,
            "thread_id": thread_id,
            "turns": int(state.get("turns", 0)) + 1,
            "updated_at": now_ts(),
            "last_message_id": message["id"],
            "last_reply": reply,
            "last_reply_normalized": normalized_reply,
        }
    )
    save_json(state_path, state)

    log_text = textwrap.dedent(
        f"""\
        agent: {agent}
        thread_id: {thread_id}
        message_id: {message["id"]}
        from: {message["from"]}
        created_at: {message["created_at"]}
        processed_at: {now_ts()}
        usage: {json.dumps(usage, sort_keys=True)}

        --- incoming ---
        {message["body"].rstrip()}

        --- reply ---
        {reply.rstrip()}
        """
    )
    log_path = write_log(root, agent, message["id"], log_text.rstrip() + "\n")
    print(f"[{agent}] wrote {log_path}", flush=True)
    if reply:
        preview = reply if len(reply) <= 700 else reply[:700] + "\n...[truncated]"
        print(f"[{agent}] reply\n{preview}", flush=True)

    peer = agent_cfg["peer"]
    previous_reply = normalize_text(load_json(agent_state_path(root, peer), default={}).get("last_reply", ""))
    loop_policy = config.get("loop_policy", {})
    max_turns = int(loop_policy.get("max_turns_per_agent", DEFAULT_MAX_TURNS_PER_AGENT))
    should_queue = bool(reply.strip())
    stop_reason = ""
    if should_queue and loop_policy.get("stop_on_terminal_reply", True) and is_terminal_reply(reply):
        should_queue = False
        stop_reason = "terminal no-op reply detected"
    elif should_queue and loop_policy.get("stop_on_repeated_reply", True) and normalized_reply == state.get("last_forwarded_reply_normalized"):
        should_queue = False
        stop_reason = "same reply repeated by the same agent"
    elif should_queue and loop_policy.get("stop_on_repeated_reply", True) and normalized_reply == previous_reply:
        should_queue = False
        stop_reason = "reply matches the peer's previous reply"
    elif should_queue and int(state.get("turns", 0)) >= max_turns:
        should_queue = False
        stop_reason = f"reached max turns for {agent} ({max_turns})"

    if should_queue:
        peer = agent_cfg["peer"]
        forwarded = agent_cfg["forward_template"].format(message=reply).rstrip()
        next_msg = enqueue_message(root, peer, forwarded, sender=agent)
        state["last_forwarded_reply_normalized"] = normalized_reply
        save_json(state_path, state)
        print(f"[{agent}] queued {peer}: {next_msg.name}", flush=True)
    else:
        reason = stop_reason or "reply was empty"
        print(f"[{agent}] stopping handoff: {reason}", flush=True)

    archive_path = processed_dir(root, agent) / msg_path.name
    ensure_dir(archive_path.parent)
    shutil.move(str(msg_path), str(archive_path))


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).resolve()
    ensure_state_tree(root)
    clear_state_tree(root)
    config = build_config(args)
    save_json(state_paths(root)["config"], config)
    print(f"initialized handoff state in {root}")
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).resolve()
    config = load_json(state_paths(root)["config"], default=None)
    if not config:
        raise SystemExit(f"missing config: {state_paths(root)['config']}")
    body = read_text(args.body, args.body_file).rstrip()
    if not body:
        raise SystemExit("message body is empty")
    target = enqueue_message(root, args.agent, body, args.sender)
    print(target)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).resolve()
    config = load_json(state_paths(root)["config"], default=None)
    if not config:
        raise SystemExit(f"missing config: {state_paths(root)['config']}")
    for agent in ("generator", "reviewer"):
        state = load_json(agent_state_path(root, agent), default={})
        queued = len(list(queue_dir(root, agent).glob("*.json")))
        processing = len(list(processing_dir(root, agent).glob("*.json")))
        print(
            json.dumps(
                {
                    "agent": agent,
                    "thread_id": state.get("thread_id"),
                    "turns": state.get("turns", 0),
                    "queued": queued,
                    "processing": processing,
                }
            )
        )
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = Path(args.state_dir).resolve()
    config = load_json(state_paths(root)["config"], default=None)
    if not config:
        raise SystemExit(f"missing config: {state_paths(root)['config']}")
    poll = float(config.get("poll_interval_seconds", 1.0))
    agent = args.agent

    while True:
        msg_path = claim_next_message(root, agent)
        if msg_path is None:
            if args.once:
                return 0
            time.sleep(poll)
            continue
        try:
            with global_lock(root):
                process_message(root, agent, msg_path, config)
        except KeyboardInterrupt:
            retry_path = queue_dir(root, agent) / msg_path.name
            if msg_path.exists():
                shutil.move(str(msg_path), str(retry_path))
            raise
        except Exception as exc:
            print(f"[{agent}] error: {exc}", file=sys.stderr, flush=True)
            retry_path = queue_dir(root, agent) / msg_path.name
            if msg_path.exists():
                shutil.move(str(msg_path), str(retry_path))
            if args.once:
                return 1
            time.sleep(poll)
        if args.once:
            return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run two Codex threads that hand off work sequentially."
    )
    parser.add_argument(
        "--state-dir",
        default=DEFAULT_STATE_DIR,
        help=f"state directory (default: {DEFAULT_STATE_DIR})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="create config and state directories")
    init_p.add_argument("--generator-prompt")
    init_p.add_argument("--generator-prompt-file")
    init_p.add_argument("--reviewer-prompt")
    init_p.add_argument("--reviewer-prompt-file")
    init_p.add_argument("--to-reviewer-template")
    init_p.add_argument("--to-reviewer-template-file")
    init_p.add_argument("--to-generator-template")
    init_p.add_argument("--to-generator-template-file")
    init_p.add_argument("--poll-interval", type=float, default=1.0)
    init_p.add_argument("--max-turns-per-agent", type=int, default=DEFAULT_MAX_TURNS_PER_AGENT)
    init_p.add_argument("--model")
    init_p.add_argument("--sandbox")
    init_p.add_argument("--approval")
    init_p.add_argument("--full-auto", action="store_true")
    init_p.add_argument("--skip-git-repo-check", action="store_true")
    init_p.add_argument(
        "--allow-terminal-handoff",
        action="store_true",
        help="continue handing off even when replies look terminal/no-op",
    )
    init_p.add_argument(
        "--codex-arg",
        action="append",
        help="extra arg forwarded to codex exec/exec resume; repeat as needed",
    )
    init_p.set_defaults(func=cmd_init)

    enqueue_p = sub.add_parser("enqueue", help="queue a message for one agent")
    enqueue_p.add_argument("agent", choices=["generator", "reviewer"])
    enqueue_p.add_argument("--body")
    enqueue_p.add_argument("--body-file")
    enqueue_p.add_argument("--sender", default="user")
    enqueue_p.set_defaults(func=cmd_enqueue)

    run_p = sub.add_parser("run", help="run one agent worker loop")
    run_p.add_argument("agent", choices=["generator", "reviewer"])
    run_p.add_argument("--once", action="store_true")
    run_p.set_defaults(func=cmd_run)

    status_p = sub.add_parser("status", help="show queue and thread status")
    status_p.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
