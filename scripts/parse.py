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
    candidate = lines[-1].lstrip("#").strip()
    candidate = candidate.rstrip(".").strip()
    candidate = candidate.strip("*_`").strip()
    candidate = candidate.rstrip(".").strip()
    return candidate if candidate in VERDICTS else None


def extract_reported_model(bench: str, payload: dict[str, Any]) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("model", "model_id", "modelName", "model_name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if bench == "claude":
        model_usage = payload.get("modelUsage")
        if isinstance(model_usage, dict):
            models = [
                key.strip()
                for key in model_usage
                if isinstance(key, str) and key.strip()
            ]
            if models:
                return models[0] if len(models) == 1 else ", ".join(models)
    if bench == "agy":
        stats = payload.get("stats")
        if isinstance(stats, dict) and isinstance(stats.get("models"), dict):
            models = [
                key.strip()
                for key in stats["models"]
                if isinstance(key, str) and key.strip()
            ]
            if models:
                return models[0] if len(models) == 1 else ", ".join(models)
    return None


def parse_codex_reported_model(jsonl: str) -> str | None:
    for line in jsonl.splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            model = extract_reported_model("codex", payload)
            if model:
                return model
    return None


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
    if not text.strip():
        detail = ""
        if bench == "agy":
            denied = payload.get("denied_actions")
            if denied:
                detail = f" (denied_actions: {denied})"
        raise RivalError(f"{bench} returned an empty response{detail}")
    return session.strip(), text
