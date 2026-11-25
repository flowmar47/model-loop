#!/usr/bin/env python3
"""Parser tests for model-loop rival.py — no live CLI calls."""

from __future__ import annotations

import io
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_verdict_markdown_variants(self) -> None:
        variants = (
            "ok\n### VERDICT: APPROVED",
            "needs work\n## **VERDICT: REVISE**",
            "ok\n**VERDICT: APPROVED**.",
            "fix\n**VERDICT: REVISE.**",
            "ok\n*VERDICT: APPROVED*",
            "fix\n_VERDICT: REVISE_",
            "ok\n`VERDICT: APPROVED`",
            "fix\nVERDICT: REVISE.",
        )
        for text in variants:
            with self.subTest(text=text):
                expected = "VERDICT: APPROVED" if "APPROVED" in text else "VERDICT: REVISE"
                self.assertEqual(rival.extract_verdict(text), expected)

    def test_verdict_rejects_buried_or_annotated(self) -> None:
        for text in (
            "The verdict is VERDICT: APPROVED",
            "VERDICT: APPROVED — with caveats",
            "VERDICT: APPROVED\nSee notes above.",
        ):
            with self.subTest(text=text):
                self.assertIsNone(rival.extract_verdict(text))

    def test_empty_response_raises_and_includes_agy_denied_actions(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.session_and_text("claude", {"session_id": "s1", "result": "   "})
        with self.assertRaises(rival.RivalError) as ctx:
            rival.session_and_text(
                "agy",
                {
                    "conversation_id": "conv-1",
                    "status": "SUCCESS",
                    "response": "",
                    "denied_actions": ["write_file", "run_command"],
                },
            )
        self.assertIn("denied_actions", str(ctx.exception))
        self.assertIn("write_file", str(ctx.exception))

    def test_extract_reported_model(self) -> None:
        self.assertEqual(
            rival.extract_reported_model("cursor", {"model": "cur-model"}),
            "cur-model",
        )
        self.assertEqual(
            rival.extract_reported_model(
                "claude",
                {"modelUsage": {"claude-primary": {"inputTokens": 10}}},
            ),
            "claude-primary",
        )
        self.assertEqual(
            rival.extract_reported_model(
                "agy",
                {"stats": {"models": {"agy-primary": {"calls": 1}}}},
            ),
            "agy-primary",
        )
        self.assertEqual(
            rival.parse_codex_reported_model('{"type":"thread.started","model":"codex-m"}\n'),
            "codex-m",
        )

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

    def test_codex_build_resume_puts_flags_after_subcommand(self) -> None:
        argv, stdin, close = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="build",
            prompt="fix it",
            session_id="thr_1",
            last_message=Path("/tmp/last.txt"),
        )
        self.assertEqual(argv[1:4], ["exec", "resume", "thr_1"])
        self.assertGreater(
            argv.index("--dangerously-bypass-approvals-and-sandbox"),
            argv.index("resume"),
        )
        self.assertEqual(argv[-1], "-")
        self.assertFalse(close)
        self.assertEqual(stdin, b"fix it")

    def test_agy_print_timeout_follows_timeout(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="review",
            prompt="look",
            session_id=None,
            last_message=None,
            timeout_s=1200,
        )
        self.assertEqual(argv[argv.index("--print-timeout") + 1], "20m")

    def test_agy_print_timeout_odd_seconds(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="review",
            prompt="look",
            session_id=None,
            last_message=None,
            timeout_s=90,
        )
        self.assertEqual(argv[argv.index("--print-timeout") + 1], "90s")

    def test_agy_review_is_plan_sandbox_not_skip_permissions(self) -> None:
        cwd = Path("/tmp/work")
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="inspect",
            prompt="look",
            session_id=None,
            last_message=None,
            model="example-model",
            effort="high",
            cwd=cwd,
        )
        self.assertIn("--mode", argv)
        self.assertIn("plan", argv)
        self.assertIn("--sandbox", argv)
        self.assertIn("--disable-slash-commands", argv)
        self.assertEqual(argv[argv.index("--add-dir") + 1], str(cwd))
        self.assertNotIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[-2:], ["--print", "look"])
        self.assertLess(argv.index("--model"), argv.index("--print"))
        self.assertLess(argv.index("--effort"), argv.index("--print"))

    def test_agy_build_uses_accept_edits_and_print_last(self) -> None:
        cwd = Path("/tmp/build-dir")
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="build",
            prompt="implement",
            session_id="conv-1",
            last_message=None,
            cwd=cwd,
        )
        self.assertEqual(argv[argv.index("--mode") + 1], "accept-edits")
        self.assertIn("--dangerously-skip-permissions", argv)
        self.assertEqual(argv[argv.index("--conversation") + 1], "conv-1")
        self.assertEqual(argv[argv.index("--add-dir") + 1], str(cwd))
        self.assertEqual(argv[-2:], ["--print", "implement"])

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

    def test_claude_pins_model_and_effort_before_prompt(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="claude",
            binary="/bin/claude",
            role="review",
            prompt="look at PLAN.md",
            session_id=None,
            last_message=None,
            model="example-model",
            effort="example-effort",
        )
        self.assertEqual(argv[-1], "look at PLAN.md")
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "example-model")
        self.assertIn("--effort", argv)
        self.assertEqual(argv[argv.index("--effort") + 1], "example-effort")

    def test_cursor_rejects_effort(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.build_argv(
                bench="cursor",
                binary="/bin/agent",
                role="review",
                prompt="look",
                session_id=None,
                last_message=None,
                effort="example-effort",
            )

    def test_codex_rejects_effort(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.build_argv(
                bench="codex",
                binary="/bin/codex",
                role="review",
                prompt="look",
                session_id=None,
                last_message=Path("/tmp/last.txt"),
                effort="high",
            )

    def test_agy_passes_unknown_effort_until_live_help_is_applied(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="agy",
            binary="/bin/agy",
            role="review",
            prompt="look",
            session_id=None,
            last_message=None,
            effort="example-effort",
        )
        self.assertEqual(argv[argv.index("--effort") + 1], "example-effort")

    def test_agy_rejects_effort_absent_from_live_help(self) -> None:
        with self.assertRaises(rival.RivalError) as ctx:
            rival.build_argv(
                bench="agy",
                binary="/bin/agy",
                role="review",
                prompt="look",
                session_id=None,
                last_message=None,
                effort="example-effort",
                allowed_efforts=frozenset({"low", "medium", "high"}),
            )
        self.assertIn("from this CLI's --help", str(ctx.exception))
        self.assertNotIn("update the enum in rival.py", str(ctx.exception))

    def test_claude_required_help_includes_effort(self) -> None:
        self.assertIn("--effort", rival.REQUIRED_HELP["claude"])
        self.assertIn("--model", rival.REQUIRED_HELP["claude"])

    def test_parse_effort_values_from_live_help_not_a_snapshot(self) -> None:
        agy = rival.parse_effort_values("  --effort `low|medium|high`\n")
        self.assertEqual(agy, frozenset({"low", "medium", "high"}))
        claude = rival.parse_effort_values(
            "--effort  Effort level (low, medium, high, xhigh, max, example-effort)\n"
        )
        self.assertIn("example-effort", claude or frozenset())
        self.assertIn("max", claude or frozenset())
        self.assertIsNone(rival.parse_effort_values("--effort VALUE\n"))
        self.assertIsNone(rival.parse_effort_values("no effort flag here\n"))

    def test_run_round_accepts_effort_added_to_live_help(self) -> None:
        captured: list[list[str]] = []
        claude_json = json.dumps(
            {
                "type": "result",
                "session_id": "sess-help",
                "result": "ok\nVERDICT: APPROVED",
            }
        )

        def fake_run(argv, **_kwargs):
            captured.append(list(argv))
            if "--help" in argv:
                stdout = "--effort low, medium, high, xhigh, max, example-effort\n"
            elif "--version" in argv:
                stdout = "2.1.243\n"
            else:
                stdout = claude_json
            return subprocess.CompletedProcess(list(argv), 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            with (
                mock.patch.object(
                    rival, "resolve_binary", return_value=("/fake/claude", None)
                ),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO),
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--effort",
                        "example-effort",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out.txt"),
                        "--state",
                        str(root / "state.json"),
                    ]
                )
        self.assertEqual(rc, 0)
        spawn = next(argv for argv in captured if "-p" in argv)
        self.assertEqual(spawn[spawn.index("--effort") + 1], "example-effort")

    def test_codex_pins_model_as_dash_m(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="review",
            prompt="look",
            session_id=None,
            last_message=Path("/tmp/last.txt"),
            model="example-model",
        )
        self.assertEqual(argv[-1], "look")
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "example-model")
        self.assertNotIn("--model", argv)

    def test_cursor_accepts_model(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="cursor",
            binary="/bin/agent",
            role="review",
            prompt="look",
            session_id=None,
            last_message=None,
            model="example-model",
        )
        self.assertEqual(argv[-1], "look")
        self.assertEqual(argv[argv.index("--model") + 1], "example-model")

    def test_empty_effort_is_rejected(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.coerce_pin("--effort", "")

    def test_pin_whitespace_is_stripped(self) -> None:
        self.assertEqual(rival.coerce_pin("--model", "  example-model  "), "example-model")

    def test_empty_model_flag_fails_before_spawn(self) -> None:
        spawned: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            spawned.append(list(argv))
            return subprocess.CompletedProcess(list(argv), 0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            with (
                mock.patch.object(
                    rival, "resolve_binary", return_value=("/fake/claude", None)
                ),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO),
                mock.patch.object(sys, "stderr", new_callable=io.StringIO),
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--model",
                        "",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out.txt"),
                        "--state",
                        str(root / "state.json"),
                    ]
                )
        self.assertEqual(rc, 1)
        self.assertEqual(spawned, [])


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


class DoctorTests(unittest.TestCase):
    def test_doctor_requires_known_good_auth_for_every_bench(self) -> None:
        for bench in rival.BENCHES:
            with self.subTest(bench=bench):
                with (
                    mock.patch.object(
                        rival, "resolve_binary", return_value=(f"/fake/{bench}", None)
                    ),
                    mock.patch.object(rival, "version_string", return_value="1.0"),
                    mock.patch.object(
                        rival,
                        "help_text",
                        return_value=" ".join(rival.REQUIRED_HELP[bench]),
                    ),
                    mock.patch.object(
                        rival, "probe_auth", return_value=rival.AUTH_OK[bench]
                    ),
                ):
                    report = rival.doctor_one(bench, Path.cwd())
                self.assertTrue(report["ok"])

    def test_doctor_rejects_unauthenticated_bench_with_all_flags(self) -> None:
        with (
            mock.patch.object(
                rival, "resolve_binary", return_value=("/fake/claude", None)
            ),
            mock.patch.object(rival, "version_string", return_value="1.0"),
            mock.patch.object(
                rival,
                "help_text",
                return_value=" ".join(rival.REQUIRED_HELP["claude"]),
            ),
            mock.patch.object(rival, "probe_auth", return_value="logged_out"),
        ):
            report = rival.doctor_one("claude", Path.cwd())
        self.assertFalse(report["ok"])
        self.assertEqual(report["auth"], "logged_out")

    def test_claude_auth_probe_requires_success_exit(self) -> None:
        result = subprocess.CompletedProcess(
            ["claude"], 1, stdout='{"loggedIn": true}', stderr="failed"
        )
        with mock.patch.object(rival, "run_command", return_value=result):
            self.assertEqual(
                rival.probe_auth("claude", "/fake/claude", Path.cwd()), "unknown"
            )

    def test_dangling_cursor_repair_uses_neutral_official_installer_note(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "agent"
            link.symlink_to(Path(tmp) / "missing")
            with mock.patch.object(
                rival, "candidate_binaries", return_value=[str(link)]
            ):
                binary, note = rival.resolve_binary("cursor")
        self.assertIsNone(binary)
        self.assertIn("official installer", note or "")
        self.assertIn("user authorization", note or "")
        self.assertNotIn("curl", note or "")

    def test_dangling_non_cursor_symlink_names_bench_without_cursor_note(self) -> None:
        for bench in ("agy", "claude", "codex"):
            with self.subTest(bench=bench), tempfile.TemporaryDirectory() as tmp:
                link = Path(tmp) / bench
                link.symlink_to(Path(tmp) / "missing")
                with mock.patch.object(
                    rival, "candidate_binaries", return_value=[str(link)]
                ):
                    binary, note = rival.resolve_binary(bench)
                self.assertIsNone(binary)
                self.assertIn(bench, note or "")
                self.assertNotIn("Cursor", note or "")
                self.assertNotIn("official installer", note or "")

    def test_help_text_runs_exec_help_for_codex_js_and_bench_codex(self) -> None:
        calls: list[list[str]] = []

        def fake_run(argv, **_kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(list(argv), 0, stdout="--help-ok", stderr="")

        with mock.patch.object(rival, "run_command", side_effect=fake_run):
            rival.help_text("/usr/local/lib/node_modules/@openai/codex/bin/codex.js", Path.cwd())
            rival.help_text("/custom/wrapper", Path.cwd(), bench="codex")
        self.assertEqual(calls[0], ["/usr/local/lib/node_modules/@openai/codex/bin/codex.js", "--help"])
        self.assertEqual(calls[1], ["/usr/local/lib/node_modules/@openai/codex/bin/codex.js", "exec", "--help"])
        self.assertEqual(calls[2], ["/custom/wrapper", "--help"])
        self.assertEqual(calls[3], ["/custom/wrapper", "exec", "--help"])

    def test_full_sweep_not_ok_when_every_bench_fails(self) -> None:
        broken = {
            "auth": None,
            "bench": "x",
            "binary": None,
            "missing_flags": [],
            "note": "missing",
            "ok": False,
            "version": None,
        }
        with (
            mock.patch.object(rival, "doctor_one", return_value=dict(broken)),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as buf,
        ):
            rc = rival.main(["doctor"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])

    def test_full_sweep_ok_when_one_bench_works(self) -> None:
        reports = iter([False, True, False, False])

        def fake_doctor(bench, _cwd):
            return {"bench": bench, "ok": next(reports)}

        with (
            mock.patch.object(rival, "doctor_one", side_effect=fake_doctor),
            mock.patch.object(sys, "stdout", new_callable=io.StringIO) as buf,
        ):
            rc = rival.main(["doctor"])
        self.assertEqual(rc, 0)
        self.assertTrue(json.loads(buf.getvalue())["ok"])


class StateTests(unittest.TestCase):
    def valid_state(self, root: Path) -> dict[str, object]:
        return {
            "bench": "claude",
            "binary": "/recorded/claude",
            "cwd": str(root.resolve()),
            "effort": None,
            "model": None,
            "role": "review",
            "rounds": 1,
            "session_id": "sess-1",
            "started_at": "2026-08-31T12:00:00+00:00",
        }

    def test_refuse_overwrite_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.txt"
            path.write_text("old", encoding="utf-8")
            with self.assertRaises(rival.RivalError):
                rival.write_text(path, "new")

    def test_resume_replays_stored_pins(self) -> None:
        captured: list[list[str]] = []
        claude_json = json.dumps(
            {
                "type": "result",
                "session_id": "sess-1",
                "result": "ok\nVERDICT: APPROVED",
            }
        )

        def fake_run(argv, **_kwargs):
            captured.append(list(argv))
            stdout = "2.1.243\n" if "--version" in argv else claude_json
            return subprocess.CompletedProcess(list(argv), 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            state = root / "state.json"
            out1 = root / "round-1.txt"
            out2 = root / "round-2.txt"
            with (
                mock.patch.object(
                    rival, "resolve_binary", return_value=("/fake/claude", None)
                ),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO) as buf,
            ):
                start_rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--model",
                        "example-model",
                        "--effort",
                        "example-effort",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out1),
                        "--state",
                        str(state),
                    ]
                )
                saved_state = json.loads(state.read_text(encoding="utf-8"))
                saved_state["binary"] = "/mutable/untrusted/claude"
                state.write_text(json.dumps(saved_state), encoding="utf-8")
                resume_rc = rival.main(
                    [
                        "resume",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out2),
                        "--state",
                        str(state),
                    ]
                )
        self.assertEqual(start_rc, 0)
        self.assertEqual(resume_rc, 0)
        start_spawn = next(argv for argv in captured if "-p" in argv)
        resume_spawn = next(argv for argv in reversed(captured) if "-p" in argv)
        self.assertNotEqual(start_spawn, resume_spawn)
        self.assertEqual(start_spawn[start_spawn.index("--model") + 1], "example-model")
        self.assertEqual(start_spawn[start_spawn.index("--effort") + 1], "example-effort")
        self.assertEqual(resume_spawn[resume_spawn.index("--model") + 1], "example-model")
        self.assertEqual(resume_spawn[resume_spawn.index("--effort") + 1], "example-effort")
        self.assertEqual(resume_spawn[0], "/fake/claude")
        self.assertNotIn("/mutable/untrusted/claude", resume_spawn)
        printed = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(printed["model"], "example-model")
        self.assertEqual(printed["effort"], "example-effort")

    def test_malformed_state_fields_raise_rival_error(self) -> None:
        malformed = {
            "bench": [],
            "role": "unknown",
            "session_id": "",
            "cwd": "relative/path",
            "binary": 7,
            "rounds": True,
            "started_at": "2026-08-31T12:00:00",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for field, value in malformed.items():
                with self.subTest(field=field):
                    state = self.valid_state(root)
                    state[field] = value
                    path = root / f"{field}.json"
                    path.write_text(json.dumps(state), encoding="utf-8")
                    with self.assertRaises(rival.RivalError):
                        rival.load_state(path)

    def test_malformed_resume_is_one_line_and_never_spawns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            state = self.valid_state(root)
            state["rounds"] = "one"
            state_path = root / "state.json"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            with (
                mock.patch.object(rival, "run_command") as spawned,
                mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr,
            ):
                rc = rival.main(
                    [
                        "resume",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out.txt"),
                        "--state",
                        str(state_path),
                    ]
                )
            self.assertEqual(rc, 1)
            spawned.assert_not_called()
            self.assertEqual(len(stderr.getvalue().splitlines()), 1)
            self.assertNotIn("Traceback", stderr.getvalue())

    def test_nul_state_session_and_model_are_one_line_without_spawn(self) -> None:
        malformed = (
            ("session_id", "sess-1\0--dangerous"),
            ("model", "model\0--dangerous"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            for field, value in malformed:
                with self.subTest(field=field):
                    state = self.valid_state(root)
                    state[field] = value
                    state_path = root / f"{field}.state.json"
                    state_path.write_text(json.dumps(state), encoding="utf-8")
                    with (
                        mock.patch.object(rival, "run_command") as spawned,
                        mock.patch.object(
                            sys, "stderr", new_callable=io.StringIO
                        ) as stderr,
                    ):
                        override = ["--model", "safe-model"] if field == "model" else []
                        rc = rival.main(
                            [
                                "resume",
                                "--prompt-file",
                                str(prompt),
                                "--out",
                                str(root / f"{field}.out.txt"),
                                "--state",
                                str(state_path),
                                *override,
                            ]
                        )
                    self.assertEqual(rc, 1)
                    spawned.assert_not_called()
                    self.assertEqual(len(stderr.getvalue().splitlines()), 1)
                    self.assertNotIn("Traceback", stderr.getvalue())

    def test_existing_output_and_state_fail_before_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            for occupied_arg in ("out", "state"):
                with self.subTest(occupied_arg=occupied_arg):
                    out = root / f"{occupied_arg}-out.txt"
                    state = root / f"{occupied_arg}-state.json"
                    occupied = out if occupied_arg == "out" else state
                    occupied.write_text("preserve", encoding="utf-8")
                    with (
                        mock.patch.object(rival, "run_command") as spawned,
                        mock.patch.object(sys, "stderr", new_callable=io.StringIO),
                    ):
                        rc = rival.main(
                            [
                                "--cwd",
                                str(root),
                                "start",
                                "--bench",
                                "claude",
                                "--role",
                                "review",
                                "--prompt-file",
                                str(prompt),
                                "--out",
                                str(out),
                                "--state",
                                str(state),
                            ]
                        )
                    self.assertEqual(rc, 1)
                    spawned.assert_not_called()
                    self.assertEqual(occupied.read_text(encoding="utf-8"), "preserve")

    def test_existing_codex_last_message_is_preserved_without_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            out = root / "round.txt"
            last_message = out.with_suffix(out.suffix + ".codex-last")
            last_message.write_text("preserve", encoding="utf-8")
            with (
                mock.patch.object(
                    rival, "resolve_binary", return_value=("/fake/codex", None)
                ),
                mock.patch.object(rival, "run_command") as spawned,
                mock.patch.object(sys, "stderr", new_callable=io.StringIO),
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "codex",
                        "--role",
                        "review",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out),
                        "--state",
                        str(root / "state.json"),
                    ]
                )
            self.assertEqual(rc, 1)
            spawned.assert_not_called()
            self.assertEqual(last_message.read_text(encoding="utf-8"), "preserve")

    def test_codex_state_last_message_collision_preserves_state_without_spawn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            out = root / "round.txt"
            state_path = out.with_suffix(out.suffix + ".codex-last")
            state = self.valid_state(root)
            state["bench"] = "codex"
            state_path.write_text(json.dumps(state), encoding="utf-8")
            original = state_path.read_bytes()
            with (
                mock.patch.object(
                    rival, "resolve_binary", return_value=("/fake/codex", None)
                ),
                mock.patch.object(rival, "run_command") as spawned,
                mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr,
            ):
                rc = rival.main(
                    [
                        "resume",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out),
                        "--state",
                        str(state_path),
                    ]
                )
            self.assertEqual(rc, 1)
            spawned.assert_not_called()
            self.assertEqual(state_path.read_bytes(), original)
            self.assertFalse(out.exists())
            self.assertIn("pairwise distinct", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())


class TimeoutTests(unittest.TestCase):
    def test_timeout_accepts_inclusive_bounds(self) -> None:
        parser = rival.build_parser()
        for value in (30, 3600):
            with self.subTest(value=value):
                args = parser.parse_args(["--timeout", str(value), "doctor"])
                self.assertEqual(args.timeout, value)

    def test_timeout_rejects_values_outside_bounds(self) -> None:
        for value in (29, 3601):
            with (
                self.subTest(value=value),
                mock.patch.object(sys, "stderr", new_callable=io.StringIO),
                self.assertRaises(SystemExit),
            ):
                rival.build_parser().parse_args(["--timeout", str(value), "doctor"])


class RunnerTests(unittest.TestCase):
    def test_self_bench_guard_blocks_and_allow_same_bench_overrides(self) -> None:
        claude_json = json.dumps(
            {
                "type": "result",
                "session_id": "sess-self",
                "result": "ok\nVERDICT: APPROVED",
            }
        )

        def fake_run(argv, **_kwargs):
            stdout = "2.1.243\n" if "--version" in argv else claude_json
            return subprocess.CompletedProcess(list(argv), 0, stdout=stdout, stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            with (
                mock.patch.object(rival, "detect_planner", return_value="claude"),
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/claude", None)),
                mock.patch.object(rival, "run_command", side_effect=fake_run) as mocked_run,
                mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr,
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out1.txt"),
                        "--state",
                        str(root / "state1.json"),
                    ]
                )
            self.assertEqual(rc, 1)
            mocked_run.assert_not_called()
            self.assertIn("distinct harnesses", stderr.getvalue())

            with (
                mock.patch.object(rival, "detect_planner", return_value="claude"),
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/claude", None)),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO),
            ):
                rc_override = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--allow-same-bench",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out2.txt"),
                        "--state",
                        str(root / "state2.json"),
                    ]
                )
            self.assertEqual(rc_override, 0)

    def test_dry_run_start_and_resume_do_not_spawn_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            out_start = root / "start.txt"
            state_start = root / "start.json"
            with (
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/codex", None)),
                mock.patch.object(rival, "run_command") as mocked_run,
                mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "codex",
                        "--role",
                        "build",
                        "--model",
                        "example-model",
                        "--unset-base-url",
                        "--dry-run",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out_start),
                        "--state",
                        str(state_start),
                    ]
                )
            self.assertEqual(rc, 0)
            mocked_run.assert_not_called()
            self.assertFalse(out_start.exists())
            self.assertFalse(state_start.exists())
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["bench"], "codex")
            self.assertEqual(payload["role"], "build")
            self.assertEqual(payload["cwd"], str(root.resolve()))
            self.assertEqual(payload["model"], "example-model")
            self.assertIsNone(payload["effort"])
            self.assertEqual(payload["stdin_mode"], "pipe")
            self.assertTrue(payload["unset_base_url"])
            self.assertIn("-m", payload["argv"])

            state_resume = root / "existing.json"
            state_resume.write_text(
                json.dumps(
                    {
                        "bench": "agy",
                        "binary": "/fake/agy",
                        "cwd": str(root.resolve()),
                        "effort": None,
                        "model": "example-model",
                        "role": "review",
                        "rounds": 1,
                        "session_id": "conv-1",
                        "started_at": "2026-08-31T12:00:00+00:00",
                    }
                ),
                encoding="utf-8",
            )
            out_resume = root / "resume.txt"
            with (
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/agy", None)),
                mock.patch.object(rival, "run_command") as mocked_run,
                mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
            ):
                rc_resume = rival.main(
                    [
                        "resume",
                        "--dry-run",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out_resume),
                        "--state",
                        str(state_resume),
                    ]
                )
            self.assertEqual(rc_resume, 0)
            mocked_run.assert_not_called()
            self.assertFalse(out_resume.exists())
            resume_payload = json.loads(stdout.getvalue())
            self.assertEqual(resume_payload["bench"], "agy")
            self.assertEqual(resume_payload["stdin_mode"], "devnull")
            self.assertFalse(resume_payload["unset_base_url"])
            self.assertEqual(resume_payload["argv"][-2:], ["--print", "look"])

    def test_status_prints_validated_state_and_rejects_malformed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.json"
            state_data = {
                "bench": "claude",
                "binary": "/fake/claude",
                "cwd": str(root.resolve()),
                "effort": None,
                "model": None,
                "role": "review",
                "rounds": 2,
                "session_id": "sess-2",
                "started_at": "2026-08-31T12:00:00+00:00",
            }
            state_path.write_text(json.dumps(state_data), encoding="utf-8")
            with mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout:
                rc = rival.main(["status", "--state", str(state_path)])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(stdout.getvalue()), state_data)

            bad_path = root / "bad.json"
            bad_path.write_text('{"bench":"claude"}', encoding="utf-8")
            with mock.patch.object(sys, "stderr", new_callable=io.StringIO) as stderr:
                rc_bad = rival.main(["status", "--state", str(bad_path)])
            self.assertEqual(rc_bad, 1)
            self.assertEqual(len(stderr.getvalue().splitlines()), 1)

    def test_env_hygiene_strips_claudecode_and_optional_base_urls(self) -> None:
        captured_envs: list[dict[str, str] | None] = []
        claude_json = json.dumps(
            {
                "type": "result",
                "session_id": "sess-env",
                "modelUsage": {"example-reported-model": {"inputTokens": 5}},
                "result": "ok\nVERDICT: APPROVED",
            }
        )

        def fake_run(argv, **kwargs):
            if "-p" in argv:
                captured_envs.append(kwargs.get("env"))
                return subprocess.CompletedProcess(list(argv), 0, stdout=claude_json, stderr="")
            return subprocess.CompletedProcess(list(argv), 0, stdout="2.1.243\n", stderr="")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "CLAUDECODE": "1",
                        "CLAUDE_CODE": "1",
                        "ANTHROPIC_BASE_URL": "http://127.0.0.1:8787",
                        "OPENAI_BASE_URL": "http://127.0.0.1:8788",
                        "KEEP_ME": "yes",
                    },
                    clear=False,
                ),
                mock.patch.object(rival, "detect_planner", return_value="unknown"),
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/claude", None)),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO) as stdout,
            ):
                rc1 = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out1.txt"),
                        "--state",
                        str(root / "state1.json"),
                    ]
                )
                rc2 = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "claude",
                        "--role",
                        "review",
                        "--unset-base-url",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(root / "out2.txt"),
                        "--state",
                        str(root / "state2.json"),
                    ]
                )
            self.assertEqual(rc1, 0)
            self.assertEqual(rc2, 0)
            env1, env2 = captured_envs
            assert env1 is not None and env2 is not None
            self.assertNotIn("CLAUDECODE", env1)
            self.assertNotIn("CLAUDE_CODE", env1)
            self.assertEqual(env1.get("ANTHROPIC_BASE_URL"), "http://127.0.0.1:8787")
            self.assertEqual(env1.get("KEEP_ME"), "yes")
            self.assertNotIn("CLAUDECODE", env2)
            self.assertNotIn("CLAUDE_CODE", env2)
            self.assertNotIn("ANTHROPIC_BASE_URL", env2)
            self.assertNotIn("OPENAI_BASE_URL", env2)
            self.assertEqual(env2.get("KEEP_ME"), "yes")

            lines = stdout.getvalue().splitlines()
            round_out = json.loads(lines[-1])
            self.assertIsInstance(round_out["elapsed_seconds"], float)
            self.assertEqual(round_out["reported_model"], "example-reported-model")
            saved_state = json.loads((root / "state2.json").read_text(encoding="utf-8"))
            self.assertIsInstance(saved_state["elapsed_seconds"], float)
            self.assertEqual(saved_state["reported_model"], "example-reported-model")

    def test_codex_cleans_up_temp_last_message_after_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("look", encoding="utf-8")
            out = root / "round.txt"
            state = root / "state.json"
            last_message = out.with_suffix(out.suffix + ".codex-last")

            def fake_run(argv, **_kwargs):
                if "--version" in argv:
                    return subprocess.CompletedProcess(list(argv), 0, stdout="codex-cli 0.171.0\n", stderr="")
                last_message.write_text("looks fine\nVERDICT: APPROVED\n", encoding="utf-8")
                return subprocess.CompletedProcess(
                    list(argv),
                    0,
                    stdout='{"type":"thread.started","thread_id":"thr_cleanup"}\n',
                    stderr="",
                )

            with (
                mock.patch.object(rival, "resolve_binary", return_value=("/fake/codex", None)),
                mock.patch.object(rival, "run_command", side_effect=fake_run),
                mock.patch.object(sys, "stdout", new_callable=io.StringIO),
            ):
                rc = rival.main(
                    [
                        "--cwd",
                        str(root),
                        "start",
                        "--bench",
                        "codex",
                        "--role",
                        "review",
                        "--prompt-file",
                        str(prompt),
                        "--out",
                        str(out),
                        "--state",
                        str(state),
                    ]
                )
            self.assertEqual(rc, 0)
            self.assertFalse(last_message.exists())
            self.assertIn("VERDICT: APPROVED", out.read_text(encoding="utf-8"))

    def test_run_command_timeout_kills_process_group(self) -> None:
        fake_proc = mock.Mock()
        fake_proc.pid = 424242
        fake_proc.communicate.side_effect = [
            subprocess.TimeoutExpired(cmd=["sleep"], timeout=30),
            ("", ""),
        ]
        with (
            mock.patch.object(subprocess, "Popen", return_value=fake_proc) as popen_mock,
            mock.patch.object(os, "killpg") as killpg_mock,
        ):
            with self.assertRaises(rival.RivalError) as ctx:
                rival.run_command(["sleep", "99"], cwd=Path.cwd(), timeout=30)
        self.assertTrue(popen_mock.call_args.kwargs["start_new_session"])
        killpg_mock.assert_called_once_with(424242, signal.SIGKILL)
        self.assertIn("exceeded 30s", str(ctx.exception))


class SkillDocsTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parent.parent
    PINNED_SKU = re.compile(
        r"\b(?:gpt-[0-9]|o[1-9]|claude[- ]?(?:opus|sonnet|haiku)[- ]?[0-9]"
        r"|gemini[- ]?[0-9]|grok[- ]?[0-9]|fable)\b",
        re.IGNORECASE,
    )

    def test_skill_does_not_pin_skus_or_frozen_efforts(self) -> None:
        for name in ("SKILL.md", "README.md", "adapters.md"):
            text = (self.ROOT / name).read_text(encoding="utf-8")
            with self.subTest(name=name):
                self.assertIsNone(self.PINNED_SKU.search(text))
                self.assertNotIn("update the enum in rival.py", text)
                self.assertNotIn("-codex model variant", text)

    def test_adapter_does_not_freeze_effort_names(self) -> None:
        source = (self.ROOT / "scripts" / "rival.py").read_text(encoding="utf-8")
        self.assertNotIn("EFFORT_SNAPSHOT", source)
        self.assertNotIn("EFFORT_VALUES", source)
        self.assertNotIn("claude: low|medium|high|xhigh|max", source)
        self.assertNotIn("update the enum in rival.py", source)


if __name__ == "__main__":
    unittest.main()
