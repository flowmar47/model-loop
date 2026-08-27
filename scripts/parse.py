"""Parse rival CLI JSON/JSONL into a session id, text, and optional verdict."""

from __future__ import annotations

import json
from typing import Any, Sequence

VERDICTS = {"VERDICT: APPROVED", "VERDICT: REVISE"}


class RivalError(Exception):
    """User-facing failure with a concrete next step."""


def load_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise RivalError("CLI returned empty JSON")
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list):
            return select_result_object(payload)
    except json.JSONDecodeError:
        payload = None
    objects: list[Any] = []
    for line in stripped.splitlines():
        try:
            objects.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if objects:
        return select_result_object(objects)
    raise RivalError("CLI output did not contain a JSON object")


def select_result_object(items: Sequence[Any]) -> dict[str, Any]:
    for item in reversed(items):
        if isinstance(item, dict) and (
            item.get("type") == "result" or "result" in item or "response" in item
        ):
            return item
    for item in reversed(items):
        if isinstance(item, dict):
            return item
    raise RivalError("JSON list contained no object")


def parse_codex_thread_id(jsonl: str) -> str:
    for line in jsonl.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(payload, dict)
            and payload.get("type") == "thread.started"
            and isinstance(payload.get("thread_id"), str)
            and payload["thread_id"]
        ):
            return payload["thread_id"]
    raise RivalError(
        "codex exec produced no thread.started event — auth/model failure; "
        "run `codex login status` and retry"
    )


def extract_verdict(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    while lines and lines[-1] in {"```", "```text", "```markdown"}:
        lines.pop()
    if not lines:
        return None
    last = lines[-1]
    return last if last in VERDICTS else None


def session_and_text(
    bench: str, payload: dict[str, Any], *, fallback_text: str = ""
) -> tuple[str, str]:
    if bench == "agy":
        session = payload.get("conversation_id")
        text = payload.get("response") or fallback_text
        status = str(payload.get("status") or "")
        if status and status.upper() not in {"SUCCESS", "OK"}:
            error = payload.get("error") or status
            raise RivalError(f"agy run failed: {error}")
    elif bench in {"cursor", "claude"}:
        session = payload.get("session_id")
        text = payload.get("result") or payload.get("response") or fallback_text
        if payload.get("is_error") is True:
            raise RivalError(f"{bench} reported is_error: {text or payload}")
    else:
        raise RivalError(f"JSON session parse is not used for bench {bench}")
    if not isinstance(session, str) or not session.strip():
        raise RivalError(
            f"{bench} JSON had no session id — cannot resume later; "
            "re-run with --output-format json"
        )
    if not isinstance(text, str):
        text = fallback_text
    return session.strip(), text
