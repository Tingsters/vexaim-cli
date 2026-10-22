"""Exercise finite stationary control code and reject misleading evidence."""

import contextlib
import importlib.util
import io
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "python_lifecycle", Path(__file__).with_name("probe-python-lifecycle.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LifecycleTests(unittest.TestCase):
    def test_thread_endurance_uses_a_short_session_request(self):
        command = probe.execution_command("tool", "session", "source", 1200, "thread")
        self.assertEqual(command[command.index("--timeout") + 1], "30")
        self.assertIn("--session", command)
        with self.assertRaisesRegex(ValueError, "120-second"):
            probe.execution_command("tool", "session", "source", 420, "main")

    def test_long_main_control_requires_explicit_standalone_selection(self):
        command = probe.execution_command(
            "tool", "session", "source", 420, "main", "AIM6518"
        )
        self.assertNotIn("--session", command)
        self.assertEqual(command[command.index("--timeout") + 1], "450")
        self.assertEqual(command[command.index("--name") + 1], "AIM6518")
        with self.assertRaisesRegex(ValueError, "only for the main"):
            probe.execution_command(
                "tool", "session", "source", 420, "thread", "AIM6518"
            )

    def test_close_wait_observes_ipc_release_without_another_robot_connection(self):
        replies = [
            subprocess.CompletedProcess(
                [], 0, json.dumps({"ok": True, "state": "closing"}), ""
            ),
            subprocess.CompletedProcess(
                [],
                1,
                json.dumps({"error": "Session: Session unavailable (closed)"}),
                "",
            ),
        ]
        with (
            patch.object(probe.subprocess, "run", side_effect=replies) as command,
            patch.object(probe.time, "sleep"),
        ):
            probe.wait_for_close("tool", "session")
        self.assertEqual(command.call_count, 2)
        self.assertTrue(
            all(
                call.args[0][-2:] == ["session", "status"]
                for call in command.call_args_list
            )
        )

    def test_ambiguous_close_error_does_not_authorize_a_second_connection(self):
        result = subprocess.CompletedProcess(
            [], 1, json.dumps({"error": "Session response timed out"}), ""
        )
        with (
            patch.object(probe.subprocess, "run", return_value=result),
            self.assertRaisesRegex(RuntimeError, "response timed out"),
        ):
            probe.wait_for_close("tool", "session")

    def test_existing_report_is_preserved(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            tool, report = root / "tool", root / "report.json"
            tool.touch()
            report.write_text('{"state":"failed"}')
            with self.assertRaises(FileExistsError):
                probe.run(SimpleNamespace(tool=tool, output=report))
            self.assertEqual(report.read_text(), '{"state":"failed"}')

    def test_python_tracebacks_survive_cli_failure(self):
        reply = subprocess.CompletedProcess(
            [], 1, json.dumps({"ok": False, "stderr": "NameError: wait"}), ""
        )
        with self.assertRaisesRegex(RuntimeError, "NameError: wait"):
            probe.cli_result(reply)

    def execute_source(self, mode):
        clock = [10000]
        pending = []

        def wait(duration, units):
            self.assertEqual((duration, units), (100, "MSEC"))
            clock[0] += duration

        # No motors, display, sensors or power methods exist in this environment.
        scope = {
            "robot": SimpleNamespace(timer=SimpleNamespace(system=lambda: clock[0])),
            "wait": wait,
            "MSEC": "MSEC",
            "Thread": lambda fn: pending.append(fn),
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exec(probe.source_for("_test_control", 60, mode), scope)  # noqa: S102 - generated source under test
        return scope, output.getvalue().strip(), pending

    def test_main_runs_for_a_finite_interval_without_actuator_access(self):
        _scope, output, pending = self.execute_source("main")
        value = json.loads(output)
        probe.validate_result(value, "_test_control", 60, 60.1)
        self.assertEqual(value["ticks"], 600)
        self.assertEqual(pending, [])

    def test_thread_returns_to_repl_and_has_its_own_finite_deadline(self):
        scope, output, pending = self.execute_source("thread")
        self.assertEqual(output, "_test_control")
        self.assertFalse(scope["_test_control"]["done"])
        pending[0]()
        probe.validate_result(scope["_test_control"], "_test_control", 60, 60.1)
        self.assertEqual(scope["_test_control"]["ticks"], 600)

    def test_invalid_or_unbounded_source_is_rejected_before_robot_io(self):
        for token, duration, mode in [
            ("x;robot.move()", 60, "main"),
            ("token", 0, "main"),
            ("token", 1201, "main"),
            ("token", 60, "power"),
        ]:
            with (
                self.subTest(token=token, duration=duration, mode=mode),
                self.assertRaises(ValueError),
            ):
                probe.source_for(token, duration, mode)

    def test_lost_nonce_incomplete_worker_and_short_intervals_cannot_pass(self):
        valid = {
            "nonce": "token",
            "ticks": 600,
            "done": True,
            "start_ms": 10000,
            "end_ms": 70000,
        }
        for changes, elapsed in [
            ({"nonce": "rebooted"}, 60),
            ({"done": False}, 60),
            ({"ticks": 0}, 60),
            ({"end_ms": 69999}, 60),
            ({}, 59.9),
        ]:
            with (
                self.subTest(changes=changes, elapsed=elapsed),
                self.assertRaises(RuntimeError),
            ):
                probe.validate_result({**valid, **changes}, "token", 60, elapsed)

    def test_unknown_profile_and_movement_refuse_execution(self):
        for known, moving, wrong_name in [
            (False, False, False),
            (True, True, False),
            (True, False, True),
        ]:
            with (
                self.subTest(known=known, moving=moving),
                TemporaryDirectory() as folder,
            ):
                root = Path(folder)
                tool = root / "tool"
                tool.touch()
                replies = [
                    {
                        "ok": True,
                        "name": "AIM6518",
                        "transport": "bluetooth",
                        "device_info": {
                            "model": "AIM",
                            "hardware": "REV1",
                            "firmware": "1.0.4.b0" if known else "1.0.5.b0",
                        },
                    },
                    {"ok": True, "robot_state": {"stopped": not moving}},
                ]
                calls = []

                def command(words, calls=calls, replies=replies, **_kwargs):
                    calls.append(words[4:])
                    return subprocess.CompletedProcess(
                        words, 0, json.dumps(replies.pop(0)), ""
                    )

                args = SimpleNamespace(
                    tool=tool,
                    output=root / "report.json",
                    duration=60,
                    mode="main",
                    session="test",
                    standalone_name="WRONG" if wrong_name else None,
                )
                with (
                    patch.object(probe.subprocess, "run", side_effect=command),
                    patch.object(probe.subprocess, "Popen") as launch,
                    patch("builtins.print"),
                ):
                    self.assertEqual(probe.run(args), 1)
                    launch.assert_not_called()
                self.assertFalse(json.loads(args.output.read_text())["passed"])
                self.assertEqual(
                    calls,
                    [["session", "status"], ["info"]]
                    if known
                    else [["session", "status"]],
                )


if __name__ == "__main__":
    unittest.main()
