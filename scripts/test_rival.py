#!/usr/bin/env python3
"""Parser tests for model-loop rival.py — no live CLI calls."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import rival  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_codex_thread_id_from_jsonl(self) -> None:
        blob = "\n".join(
            [
                '{"type":"item.completed"}',
                '{"type":"thread.started","thread_id":"thr_abc"}',
                '{"type":"item.delta"}',
            ]
        )
        self.assertEqual(rival.parse_codex_thread_id(blob), "thr_abc")

    def test_codex_thread_id_missing(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.parse_codex_thread_id('{"type":"item.completed"}\n')

    def test_agy_session_and_text(self) -> None:
        payload = {
            "conversation_id": "conv-1",
            "status": "SUCCESS",
            "response": "looks wrong\nVERDICT: REVISE\n",
        }
        session, text = rival.session_and_text("agy", payload)
        self.assertEqual(session, "conv-1")
        self.assertIn("VERDICT: REVISE", text)

    def test_agy_failed_status(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.session_and_text(
                "agy",
                {"conversation_id": "x", "status": "ERROR", "error": "auth"},
            )

    def test_claude_session_from_wrapped_list(self) -> None:
        blob = json.dumps(
            [
                {"type": "assistant", "message": {"content": []}},
                {
                    "type": "result",
                    "session_id": "sess-9",
                    "result": "ok\nVERDICT: APPROVED",
                },
            ]
        )
        payload = rival.load_json_object(blob)
        session, text = rival.session_and_text("claude", payload)
        self.assertEqual(session, "sess-9")
        self.assertEqual(rival.extract_verdict(text), "VERDICT: APPROVED")

    def test_cursor_is_error(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.session_and_text(
                "cursor",
                {"session_id": "s", "is_error": True, "result": "boom"},
            )

    def test_verdict_strips_trailing_fence(self) -> None:
        text = "problem\nVERDICT: REVISE\n```\n"
        self.assertEqual(rival.extract_verdict(text), "VERDICT: REVISE")

    def test_verdict_absent(self) -> None:
        self.assertIsNone(rival.extract_verdict("no token here"))

    def test_missing_session_id(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.session_and_text("claude", {"result": "hi"})


class ArgvTests(unittest.TestCase):
    def test_codex_review_uses_read_only_and_closes_stdin(self) -> None:
        argv, stdin, close = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="review",
            prompt="go",
            session_id=None,
            last_message=Path("/tmp/last.txt"),
        )
        self.assertIn("-s", argv)
        self.assertIn("read-only", argv)
        self.assertTrue(close)
        self.assertIsNone(stdin)

    def test_codex_resume_forces_sandbox_via_config(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="review",
            prompt="again",
            session_id="thr_1",
            last_message=Path("/tmp/last.txt"),
        )
        self.assertIn("resume", argv)
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertNotIn("-s", argv)

    def test_codex_build_uses_long_bypass_flag(self) -> None:
        argv, stdin, close = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="build",
            prompt="implement",
            session_id=None,
            last_message=Path("/tmp/last.txt"),
        )
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", argv)
        self.assertFalse(close)
        self.assertEqual(stdin, b"implement")

    def test_agy_review_is_plan_sandbox_not_skip_permissions(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="inspect",
            prompt="look",
            session_id=None,
            last_message=None,
        )
        self.assertIn("--mode", argv)
        self.assertIn("plan", argv)
        self.assertIn("--sandbox", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)

    def test_cursor_review_is_ask_not_force(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="cursor",
            binary="/bin/agent",
            role="review",
            prompt="look",
            session_id="chat-1",
            last_message=None,
        )
        self.assertIn("--mode", argv)
        self.assertIn("ask", argv)
        self.assertNotIn("--force", argv)
        self.assertIn("--resume", argv)

    def test_claude_build_skips_permissions(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="claude",
            binary="/bin/claude",
            role="build",
            prompt="write",
            session_id=None,
            last_message=None,
        )
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertNotIn("plan", argv)


class DetectTests(unittest.TestCase):
    def test_unknown_without_markers(self) -> None:
        keys = (
            "CURSOR_AGENT",
            "CURSOR_CLI",
            "CLAUDECODE",
            "CLAUDE_CODE",
            "ANTIGRAVITY",
            "AGY_HOME",
            "PI_AGENT",
            "PI_SESSION",
            "CODEX_CI",
            "CODEX_THREAD_ID",
        )
        saved = {key: os.environ.pop(key, None) for key in keys}
        try:
            self.assertEqual(rival.detect_planner(), "unknown")
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


class StateTests(unittest.TestCase):
    def test_refuse_overwrite_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            path.write_text("old", encoding="utf-8")
            with self.assertRaises(rival.RivalError):
                rival.write_text(path, "new")


if __name__ == "__main__":
    unittest.main()
