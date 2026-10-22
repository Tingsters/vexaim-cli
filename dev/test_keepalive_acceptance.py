"""Test autonomous endurance evidence and its stationary-only command scope."""

import ast
import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "keepalive_accept", Path(__file__).with_name("accept-keepalive.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class AcceptanceTests(unittest.TestCase):
    def test_power_evidence_requires_real_flag_and_watchdog_progress(self):
        valid = {
            "active": True,
            "sleep_disabled": True,
            "expired": False,
            "watchdog_age_ms": 0,
            "watchdog_ticks": 4300,
            "same_lease": True,
        }
        probe.validate_power_evidence(valid, 100, 420)
        for change in (
            {"active": False},
            {"sleep_disabled": False},
            {"expired": True},
            {"watchdog_age_ms": 4000},
            {"same_lease": False},
            {"watchdog_ticks": 100},
            {"watchdog_ticks": None},
        ):
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                probe.validate_power_evidence({**valid, **change}, 100, 420)

    def test_missing_power_proof_cannot_be_accepted(self):
        with self.assertRaises(RuntimeError):
            probe.validate_power_evidence({})

    def run_probe(self, root, **options):
        tool = root / "vexaim"
        tool.touch()
        now = [0.0]
        calls = []
        moving = options.pop("moving", False)
        camera_ready = options.pop("camera_ready", True)
        reboot = options.pop("reboot", False)
        failed_health = options.pop("failed_health", False)
        frozen_health = options.pop("frozen_health", False)
        lost_nonce = options.pop("lost_nonce", False)
        context_reset = options.pop("context_reset", False)
        stalled_power = options.pop("stalled_power", False)
        cancel_at = options.pop("cancel_at", None)
        host_stall = options.pop("host_stall", False)
        timer_reads = [0]
        nonce = [None]
        args = SimpleNamespace(
            tool=tool,
            session="test-session",
            duration=60,
            interval=15,
            display=False,
            quiet_seconds=0,
            camera_interval=0,
            after_stop_quiet=0,
            stop_file=None,
            output_dir=root / "reports",
        )
        for name, value in options.items():
            setattr(args, name, value)

        def run(command, **_kwargs):
            words = command[4:]
            calls.append((now[0], words))
            if words == ["info"]:
                value = {
                    "robot_state": {
                        "stopped": not moving,
                        "imu_calibrating": False,
                        "battery_pct": 90,
                        "heading": 0,
                        "x_mm": 0,
                        "y_mm": 0,
                    }
                }
            elif words == ["timer", "system"]:
                timer_reads[0] += 1
                uptime = (
                    0 if reboot and timer_reads[0] > 1 else 100000 + int(now[0] * 1000)
                )
                value = {"value": {"value": uptime}}
            elif words[:2] == ["exec", "--no-preamble"]:
                source = words[2]
                if "'same_lease':" in source:
                    value = {
                        "stdout": json.dumps(
                            {
                                "same_lease": True,
                                "active": True,
                                "expired": False,
                                "sleep_disabled": True,
                                "watchdog_age_ms": 0,
                                "watchdog_ticks": 1
                                if stalled_power
                                else int(now[0] * 10) + 1,
                            }
                        )
                    }
                    return subprocess.CompletedProcess(
                        command, 0, json.dumps({"ok": True, **value}), ""
                    )
                if source.startswith("_va_endurance_nonce = "):
                    nonce[0] = ast.literal_eval(
                        source.split(" = ", 1)[1].split(";", 1)[0]
                    )
                value = {
                    "stdout": "changed"
                    if lost_nonce and timer_reads[0] > 1
                    else nonce[0]
                }
            elif words[:2] == ["camera", "observe"]:
                value = {"control_ready": camera_ready}
            elif words == ["screen", "show-emoji", "HAPPY"]:
                if context_reset:
                    nonce[0] = None
                value = {}
            elif words[:2] == ["screen", "screenshot"]:
                now[0] += 5
                value = {"control_ready": True, "path": words[2]}
            elif words == ["session", "status"]:
                value = {
                    "keepalive": {
                        "active": not failed_health,
                        "healthy": True,
                        "confirmed_polls": 1 if frozen_health else int(now[0] / 2) + 1,
                        "power": {"supported": True, "active": True},
                    }
                }
            elif words == ["stop"]:
                if context_reset:
                    nonce[0] = None
                value = {"stopped": True}
            else:
                raise AssertionError("Unexpected robot action: " + repr(words))
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"ok": True, **value}), ""
            )

        def sleep(seconds):
            now[0] += seconds + (120 if host_stall else 0)
            if cancel_at is not None and now[0] >= cancel_at:
                args.stop_file.touch()

        clock = SimpleNamespace(
            monotonic=lambda: now[0], time=lambda: 1700000000 + now[0], sleep=sleep
        )
        with (
            patch.object(probe, "time", clock),
            patch.object(probe.subprocess, "run", side_effect=run),
            patch("builtins.print"),
        ):
            result = probe.main(args)
        report = json.loads(next(args.output_dir.glob("endurance-*.json")).read_text())
        return result, report, calls

    def test_silent_interval_exceeds_sleep_threshold_without_client_polls(self):
        with TemporaryDirectory() as folder:
            code, report, calls = self.run_probe(
                Path(folder), duration=420, quiet_seconds=370
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["passed"])
            self.assertGreaterEqual(report["elapsed_s"], 420)
            self.assertFalse(
                any(
                    0 < when < 370 and words != ["session", "status"]
                    for when, words in calls
                )
            )
            self.assertTrue(
                all(
                    words in (["info"], ["timer", "system"], ["session", "status"])
                    or words[:2] == ["exec", "--no-preamble"]
                    for _, words in calls
                )
            )

    def test_moving_robot_stops_acceptance_without_motion_commands(self):
        with TemporaryDirectory() as folder:
            code, report, calls = self.run_probe(Path(folder), moving=True)
            self.assertEqual(code, 1)
            self.assertFalse(report["passed"])
            self.assertEqual(calls[-1][1], ["info"])
            self.assertFalse(
                any(words[0] in ("move", "turn", "kicker") for _, words in calls)
            )

    def test_camera_with_failed_recovery_cannot_pass(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder), camera_interval=30, camera_ready=False
            )
            self.assertEqual(code, 1)
            self.assertFalse(report["passed"])
            self.assertIn("Postcapture", report["error"])

    def test_rebooted_uptime_cannot_pass(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(Path(folder), reboot=True)
            self.assertEqual(code, 1)
            self.assertIn("system time", report["error"])

    def test_early_handoff_is_distinct_from_a_passing_endurance_run(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            stop = root / "handoff"
            stop.touch()
            code, report, _ = self.run_probe(root, stop_file=stop)
            self.assertEqual(code, 2)
            self.assertTrue(report["handoff_requested"])
            self.assertFalse(report["passed"])
            self.assertEqual(report["state"], "incomplete")
            self.assertEqual(report["checks"], [])

    def test_invalid_duration_is_rejected_before_robot_io(self):
        with TemporaryDirectory() as folder:
            code, report, calls = self.run_probe(Path(folder), quiet_seconds=370)
            self.assertEqual(code, 1)
            self.assertFalse(report["passed"])
            self.assertEqual(calls, [])

    def test_broken_background_worker_is_detected_without_radio_traffic(self):
        with TemporaryDirectory() as folder:
            code, report, calls = self.run_probe(
                Path(folder), quiet_seconds=60, failed_health=True
            )
            self.assertEqual(code, 1)
            self.assertFalse(report["passed"])
            self.assertLess(report["elapsed_s"], 10)
            self.assertEqual(calls[-1][1], ["session", "status"])

    def test_stagnant_heartbeat_count_cannot_pass(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder), quiet_seconds=60, frozen_health=True
            )
            self.assertEqual(code, 1)
            self.assertIn("did not advance", report["error"])

    def test_camera_and_quiet_period_after_stop_are_stationary(self):
        with TemporaryDirectory() as folder:
            code, report, calls = self.run_probe(
                Path(folder), duration=100, quiet_seconds=20, after_stop_quiet=40
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["passed"])
            words = [command for _, command in calls]
            self.assertIn(["stop"], words)
            self.assertIn(["screen", "show-emoji", "HAPPY"], words)
            self.assertEqual(
                sum(command[:2] == ["camera", "observe"] for command in words), 2
            )

    def test_lcd_transfer_requires_its_existing_watchdog_to_advance(self):
        for stalled in (False, True):
            with self.subTest(stalled=stalled), TemporaryDirectory() as folder:
                code, report, _ = self.run_probe(
                    Path(folder),
                    duration=60,
                    after_stop_quiet=1,
                    require_power_lease=True,
                    capture_lcd=True,
                    stalled_power=stalled,
                )
                self.assertEqual(code, 1 if stalled else 0)
                if stalled:
                    self.assertIn("watchdog did not advance", report["error"])

    def test_explicit_native_context_changes_preserve_uptime_validation(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder),
                duration=100,
                quiet_seconds=20,
                after_stop_quiet=40,
                require_power_lease=True,
                context_reset=True,
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["passed"])
            self.assertEqual(len(report["context_transitions"]), 1)
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder),
                duration=100,
                quiet_seconds=20,
                after_stop_quiet=40,
                require_power_lease=True,
                context_reset=True,
                reboot=True,
            )
            self.assertEqual(code, 1)
            self.assertIn("system time", report["error"])

    def test_interpreter_state_loss_fails_even_with_continuous_system_time(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(Path(folder), lost_nonce=True)
            self.assertEqual(code, 1)
            self.assertEqual(report["failure_class"], "interpreter_state_lost")
            self.assertFalse(report["passed"])

    def test_explicit_baseline_can_measure_firmware_without_active_monitor(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder),
                quiet_seconds=60,
                failed_health=True,
                allow_inactive_monitor=True,
            )
            self.assertEqual(code, 0)
            self.assertTrue(report["passed"])

    def test_handoff_during_quiet_never_runs_camera_or_passes(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            stop = root / "handoff"
            code, report, calls = self.run_probe(
                root, stop_file=stop, cancel_at=5, quiet_seconds=20, after_stop_quiet=20
            )
            self.assertEqual(code, 2)
            self.assertFalse(report["passed"])
            self.assertFalse(
                any(words[0] in ("camera", "screen") for _, words in calls)
            )

    def test_host_sleep_or_stalled_monitoring_cannot_pass_quiet_interval(self):
        with TemporaryDirectory() as folder:
            code, report, _ = self.run_probe(
                Path(folder), quiet_seconds=60, host_stall=True
            )
            self.assertEqual(code, 2)
            self.assertEqual(report["state"], "incomplete")
            self.assertFalse(report["passed"])
            self.assertIn("Host monitoring paused", report["error"])


if __name__ == "__main__":
    unittest.main()
