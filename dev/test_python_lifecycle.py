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
        for known, moving in [(False, False), (True, True)]:
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
