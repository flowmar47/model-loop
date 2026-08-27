#!/usr/bin/env python3
"""Spawn agy / Cursor CLI / Claude Code / Codex as a read-only rival or a builder."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from parse import (
    RivalError,
    extract_verdict,
    load_json_object,
    parse_codex_thread_id,
    session_and_text,
)

DEFAULT_TIMEOUT_S = 600
ROLES = ("review", "build", "inspect")
BENCHES = ("agy", "cursor", "claude", "codex")

REQUIRED_HELP = {
    "agy": (
        "--print",
        "--output-format",
        "--conversation",
        "--mode",
        "--sandbox",
        "--print-timeout",
        "--dangerously-skip-permissions",
    ),
    "cursor": (
        "--print",
        "--output-format",
        "--resume",
        "--mode",
        "--sandbox",
        "--force",
        "--trust",
    ),
    "claude": (
        "--print",
        "--output-format",
        "--resume",
        "--permission-mode",
        "--dangerously-skip-permissions",
    ),
    "codex": ("exec", "--sandbox", "--json", "--output-last-message", "resume"),
}

BINARIES = {
    "agy": ("agy",),
    "cursor": ("agent", "cursor-agent"),
    "claude": ("claude",),
    "codex": ("codex",),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def candidate_binaries(bench: str) -> list[str]:
    found: list[str] = []
    for name in BINARIES[bench]:
        which = shutil.which(name)
        if which:
            found.append(which)
        local = Path.home() / ".local/bin" / name
        if local.exists() or local.is_symlink():
            found.append(str(local))
    unique: list[str] = []
    for path in found:
        if path not in unique:
            unique.append(path)
    return unique


def resolve_binary(bench: str) -> tuple[str | None, str | None]:
    notes: list[str] = []
    for path in candidate_binaries(bench):
        located = Path(path)
        if located.is_symlink() and not located.exists():
            notes.append(
                f"{path} is a dangling symlink — reinstall Cursor CLI with "
                "`curl https://cursor.com/install -fsS | bash` if you want the cursor rival"
            )
            continue
        resolved = located.resolve()
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return str(resolved), None
        if located.exists():
            notes.append(f"{path} exists but is not executable")
    detail = (
        "; ".join(notes) if notes else f"none of {list(BINARIES[bench])} on PATH"
    )
    return None, detail


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    timeout: int,
    stdin: int | Any = subprocess.DEVNULL,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(argv),
            cwd=cwd,
            input=input_bytes.decode("utf-8") if input_bytes is not None else None,
            stdin=None if input_bytes is not None else stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise RivalError(f"binary missing: {argv[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RivalError(
            f"{argv[0]} exceeded {timeout}s — treat as a failed round, do not retry blind"
        ) from exc


def help_text(binary: str, cwd: Path) -> str:
    result = run_command((binary, "--help"), cwd=cwd, timeout=20)
    extra = ""
    if Path(binary).name == "codex":
        extra_result = run_command((binary, "exec", "--help"), cwd=cwd, timeout=20)
        extra = extra_result.stdout + extra_result.stderr
    return result.stdout + result.stderr + extra


def missing_flags(bench: str, text: str) -> list[str]:
    return [flag for flag in REQUIRED_HELP[bench] if flag not in text]


def version_string(binary: str, cwd: Path) -> str:
    result = run_command((binary, "--version"), cwd=cwd, timeout=20)
    body = (result.stdout or result.stderr).strip()
    return body.splitlines()[0] if body else "unknown"


def detect_planner() -> str:
    if os.environ.get("CURSOR_AGENT") or os.environ.get("CURSOR_CLI"):
        return "cursor"
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("ANTIGRAVITY") or os.environ.get("AGY_HOME"):
        return "agy"
    if os.environ.get("PI_AGENT") or os.environ.get("PI_SESSION"):
        return "pi"
    if os.environ.get("CODEX_CI") or os.environ.get("CODEX_THREAD_ID"):
        return "codex"
    return "unknown"


def doctor_one(bench: str, cwd: Path) -> dict[str, Any]:
    binary, note = resolve_binary(bench)
    report: dict[str, Any] = {
        "auth": None,
        "bench": bench,
        "binary": binary,
        "missing_flags": [],
        "note": note,
        "ok": False,
        "version": None,
    }
    if binary is None:
        return report
    try:
        report["version"] = version_string(binary, cwd)
        flags = missing_flags(bench, help_text(binary, cwd))
        report["missing_flags"] = flags
        report["auth"] = probe_auth(bench, binary, cwd)
        report["ok"] = not flags
    except RivalError as exc:
        report["note"] = str(exc)
    return report


def probe_auth(bench: str, binary: str, cwd: Path) -> str:
    if bench == "claude":
        result = run_command((binary, "auth", "status", "--json"), cwd=cwd, timeout=20)
        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return "unparsed"
        return "logged_in" if payload.get("loggedIn") else "logged_out"
    if bench == "codex":
        result = run_command((binary, "login", "status"), cwd=cwd, timeout=20)
        text = (result.stdout or "") + (result.stderr or "")
        if "Logged in" in text:
            return "logged_in"
        return "unknown"
    if bench == "cursor":
        result = run_command((binary, "status"), cwd=cwd, timeout=20)
        text = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            return "ok" if text.strip() else "unknown"
        return "unknown"
    if bench == "agy":
        result = run_command((binary, "models"), cwd=cwd, timeout=20)
        if result.returncode == 0:
            return "ok"
        return "unknown"
    return "unknown"


def read_prompt(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RivalError(f"failed to read prompt {path}: {exc}") from exc
    if not text.strip():
        raise RivalError(f"prompt file is empty: {path}")
    return text


def load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RivalError(f"invalid state file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RivalError(f"state is not an object: {path}")
    for key in ("bench", "role", "session_id", "cwd", "binary"):
        if not payload.get(key):
            raise RivalError(f"state missing {key}: {path}")
    if payload["bench"] not in BENCHES or payload["role"] not in ROLES:
        raise RivalError(f"state has unknown bench/role: {path}")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RivalError(f"failed to write {path}: {exc}") from exc


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RivalError(f"refusing to overwrite output {path} — pass a new --out path per round")
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        raise RivalError(f"failed to write {path}: {exc}") from exc


def build_argv(
    *,
    bench: str,
    binary: str,
    role: str,
    prompt: str,
    session_id: str | None,
    last_message: Path | None,
) -> tuple[list[str], bytes | None, bool]:
    """Return (argv, stdin_bytes, close_stdin). close_stdin True → DEVNULL."""
    resume = session_id is not None
    write_role = role == "build"
    if bench == "agy":
        argv = [binary, "-p", "--output-format", "json", "--print-timeout", "10m"]
        if write_role:
            argv.append("--dangerously-skip-permissions")
        else:
            argv.extend(("--mode", "plan", "--sandbox"))
        if resume:
            argv.extend(("--conversation", session_id or ""))
        argv.append(prompt)
        return argv, None, True
    if bench == "cursor":
        argv = [binary, "-p", "--output-format", "json", "--trust"]
        if write_role:
            argv.append("--force")
        else:
            argv.extend(("--mode", "ask", "--sandbox", "enabled"))
        if resume:
            argv.extend(("--resume", session_id or ""))
        argv.append(prompt)
        return argv, None, True
    if bench == "claude":
        argv = [binary, "-p", "--output-format", "json", "--disable-slash-commands", "--no-chrome"]
        if write_role:
            argv.append("--dangerously-skip-permissions")
        else:
            argv.extend(("--permission-mode", "plan"))
        if resume:
            argv.extend(("--resume", session_id or ""))
        argv.append(prompt)
        return argv, None, True
    if bench == "codex":
        if last_message is None:
            raise RivalError("codex requires a last-message path")
        if write_role:
            argv = [
                binary,
                "exec",
                "--dangerously-bypass-approvals-and-sandbox",
                "--json",
                "-o",
                str(last_message),
            ]
            if resume:
                argv.extend(("resume", session_id or "", "-"))
            else:
                argv.append("-")
            return argv, prompt.encode("utf-8"), False
        if resume:
            argv = [
                binary,
                "exec",
                "resume",
                session_id or "",
                "-c",
                'sandbox_mode="read-only"',
                "--json",
                "-o",
                str(last_message),
                prompt,
            ]
        else:
            argv = [
                binary,
                "exec",
                "-s",
                "read-only",
                "--json",
                "-o",
                str(last_message),
                prompt,
            ]
        return argv, None, True
    raise RivalError(f"unknown bench {bench}")


def run_round(args: argparse.Namespace, *, resume: bool) -> int:
    prompt_path = Path(args.prompt_file)
    out_path = Path(args.out)
    state_path = Path(args.state)
    prompt = read_prompt(prompt_path)
    timeout = int(args.timeout)

    if resume:
        state = load_state(state_path)
        bench = str(state["bench"])
        role = str(state["role"])
        session_id = str(state["session_id"])
        cwd = Path(str(state["cwd"]))
        binary = str(state["binary"])
        rounds = int(state.get("rounds", 0)) + 1
        started_at = str(state.get("started_at") or utc_now())
    else:
        bench = args.bench
        role = args.role
        if bench not in BENCHES:
            raise RivalError(f"unknown bench {bench}")
        if role not in ROLES:
            raise RivalError(f"unknown role {role}")
        if state_path.exists():
            raise RivalError(f"refusing to overwrite state {state_path} — use resume")
        binary, note = resolve_binary(bench)
        if binary is None:
            raise RivalError(f"{bench} CLI not found: {note}")
        cwd = Path(args.cwd).resolve()
        session_id = None
        rounds = 1
        started_at = utc_now()

    if not cwd.is_dir():
        raise RivalError(f"cwd is not a directory: {cwd}")

    last_message = out_path.with_suffix(out_path.suffix + ".codex-last") if bench == "codex" else None
    if last_message is not None:
        last_message.parent.mkdir(parents=True, exist_ok=True)
        if last_message.exists():
            last_message.unlink()
    argv, stdin_bytes, close_stdin = build_argv(
        bench=bench,
        binary=binary,
        role=role,
        prompt=prompt,
        session_id=session_id,
        last_message=last_message,
    )
    result = run_command(
        argv,
        cwd=cwd,
        timeout=timeout,
        stdin=subprocess.DEVNULL if close_stdin else subprocess.PIPE,
        input_bytes=stdin_bytes,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:800]
        raise RivalError(
            f"{bench} {role} exited {result.returncode}: {detail or 'no output'} "
            "— stop and surface this; do not retry blind"
        )

    if bench == "codex":
        new_session = session_id or parse_codex_thread_id(result.stdout + "\n" + result.stderr)
        if last_message is None or not last_message.is_file():
            raise RivalError("codex did not write -o last-message file")
        text = last_message.read_text(encoding="utf-8")
    else:
        payload = load_json_object(result.stdout)
        new_session, text = session_and_text(bench, payload)

    write_text(out_path, text)
    write_json(
        state_path,
        {
            "bench": bench,
            "binary": binary,
            "cwd": str(cwd),
            "role": role,
            "rounds": rounds,
            "session_id": new_session,
            "started_at": started_at,
            "updated_at": utc_now(),
            "version": version_string(binary, cwd),
        },
    )
    print(
        json.dumps(
            {
                "bench": bench,
                "ok": True,
                "out": str(out_path),
                "role": role,
                "rounds": rounds,
                "session_id": new_session,
                "verdict": extract_verdict(text),
            },
            sort_keys=True,
        )
    )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cwd = Path(args.cwd).resolve()
    wanted = [args.bench] if args.bench else list(BENCHES)
    reports = [doctor_one(bench, cwd) for bench in wanted]
    print(
        json.dumps(
            {
                "ok": all(item["ok"] for item in reports) if args.bench else True,
                "planner": detect_planner(),
                "benches": reports,
            },
            indent=2,
        )
    )
    if args.bench:
        return 0 if reports[0]["ok"] else 1
    return 0


def cmd_whoami(_: argparse.Namespace) -> int:
    print(json.dumps({"planner": detect_planner()}, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Spawn a rival coding CLI for model-loop.")
    parser.add_argument("--cwd", default=".", help="working directory for the spawned CLI")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S)
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="check binaries, flags, and auth")
    doctor.add_argument("--bench", choices=BENCHES)
    doctor.set_defaults(func=cmd_doctor)

    who = sub.add_parser("whoami", help="guess the invoking planner harness from env")
    who.set_defaults(func=cmd_whoami)

    start = sub.add_parser("start", help="fresh rival session")
    start.add_argument("--bench", required=True, choices=BENCHES)
    start.add_argument("--role", required=True, choices=ROLES)
    start.add_argument("--prompt-file", required=True)
    start.add_argument("--out", required=True)
    start.add_argument("--state", required=True)
    start.set_defaults(func=lambda a: run_round(a, resume=False))

    resume = sub.add_parser("resume", help="resume the exact stored session")
    resume.add_argument("--prompt-file", required=True)
    resume.add_argument("--out", required=True)
    resume.add_argument("--state", required=True)
    resume.set_defaults(func=lambda a: run_round(a, resume=True))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except RivalError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
