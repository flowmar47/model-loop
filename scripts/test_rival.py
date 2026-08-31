#!/usr/bin/env python3
"""Parser tests for model-loop rival.py — no live CLI calls."""

from __future__ import annotations

import io
import json
import os
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

    def test_claude_pins_model_and_effort_before_prompt(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="claude",
            binary="/bin/claude",
            role="review",
            prompt="look at PLAN.md",
            session_id=None,
            last_message=None,
            model="fable",
            effort="xhigh",
        )
        self.assertEqual(argv[-1], "look at PLAN.md")
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "fable")
        self.assertIn("--effort", argv)
        self.assertEqual(argv[argv.index("--effort") + 1], "xhigh")

    def test_cursor_rejects_effort(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.build_argv(
                bench="cursor",
                binary="/bin/agent",
                role="review",
                prompt="look",
                session_id=None,
                last_message=None,
                effort="xhigh",
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

    def test_agy_rejects_xhigh_effort(self) -> None:
        with self.assertRaises(rival.RivalError) as ctx:
            rival.build_argv(
                bench="agy",
                binary="/bin/agy",
                role="review",
                prompt="look",
                session_id=None,
                last_message=None,
                effort="xhigh",
            )
        self.assertIn("update the enum in rival.py", str(ctx.exception))

    def test_claude_required_help_includes_effort(self) -> None:
        self.assertIn("--effort", rival.REQUIRED_HELP["claude"])
        self.assertIn("--model", rival.REQUIRED_HELP["claude"])

    def test_codex_pins_model_as_dash_m(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="codex",
            binary="/bin/codex",
            role="review",
            prompt="look",
            session_id=None,
            last_message=Path("/tmp/last.txt"),
            model="gpt-5",
        )
        self.assertEqual(argv[-1], "look")
        self.assertIn("-m", argv)
        self.assertEqual(argv[argv.index("-m") + 1], "gpt-5")
        self.assertNotIn("--model", argv)

    def test_cursor_accepts_model(self) -> None:
        argv, _, _ = rival.build_argv(
            bench="cursor",
            binary="/bin/agent",
            role="review",
            prompt="look",
            session_id=None,
            last_message=None,
            model="composer",
        )
        self.assertEqual(argv[-1], "look")
        self.assertEqual(argv[argv.index("--model") + 1], "composer")

    def test_empty_effort_is_rejected(self) -> None:
        with self.assertRaises(rival.RivalError):
            rival.coerce_pin("--effort", "")

    def test_pin_whitespace_is_stripped(self) -> None:
        self.assertEqual(rival.coerce_pin("--model", "  fable  "), "fable")

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
                        "fable",
                        "--effort",
                        "xhigh",
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
        self.assertEqual(start_spawn[start_spawn.index("--model") + 1], "fable")
        self.assertEqual(start_spawn[start_spawn.index("--effort") + 1], "xhigh")
        self.assertEqual(resume_spawn[resume_spawn.index("--model") + 1], "fable")
        self.assertEqual(resume_spawn[resume_spawn.index("--effort") + 1], "xhigh")
        self.assertEqual(resume_spawn[0], "/fake/claude")
        self.assertNotIn("/mutable/untrusted/claude", resume_spawn)
        printed = json.loads(buf.getvalue().splitlines()[-1])
        self.assertEqual(printed["model"], "fable")
        self.assertEqual(printed["effort"], "xhigh")

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


if __name__ == "__main__":
    unittest.main()
