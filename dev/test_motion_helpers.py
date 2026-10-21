"""Exercise the actual transient helper with a virtual clock; no robot needed."""
import contextlib
import io
import json
from pathlib import Path
import types
import unittest

HELPERS = Path(__file__).resolve().parents[1] / "cli/vexaim/src/motion.py"
STOP_HELPER = HELPERS.with_name("stop.py")


class Robot:
    def __init__(self):
        self.clock = 0
        self.active_until = 0
        self.rotation = 0
        self.start_rotation = 0
        self.started = 0
        self.target = 0
        self.stalled = False
        self.calibrating = False
        self.interrupt = False
        self.stops = 0
        self.stop_settle_ms = 0
        self.stopped_after = 0
        self.starts = 0
        self.timer = types.SimpleNamespace(time=lambda unit: self.clock)
        self.inertial = types.SimpleNamespace(
            get_rotation=self.get_rotation,
            get_heading=lambda: self.get_rotation() % 360,
            is_calibrating=lambda: self.calibrating,
        )

    def get_rotation(self):
        if self.active_until > self.started:
            elapsed = min(1, (self.clock - self.started) / (self.active_until - self.started))
            return self.start_rotation + (0 if self.stalled else elapsed * self.target)
        return self.rotation

    def turn_for(self, direction, value, speed, unit, blocking):
        self.starts += 1
        self.started = self.clock
        self.start_rotation = self.rotation
        self.target = value * direction
        self.active_until = self.clock + value / speed * 1000

    def move_for(self, value, angle, speed, unit, blocking):
        self.turn_for(1, value, speed, unit, blocking)
        self.target = 0

    def is_stopped(self):
        return not self.is_turn_active() and self.clock >= self.stopped_after

    def is_turn_active(self):
        return self.clock < self.active_until or (self.stalled and self.starts > self.stops)

    is_move_active = is_turn_active
    get_x_position = lambda self: 0
    get_y_position = lambda self: 0
    get_battery_level = lambda self: 95

    def stop_all_movement(self):
        self.rotation = self.get_rotation()
        self.active_until = self.started = self.clock
        self.stops += 1
        self.stopped_after = self.clock + self.stop_settle_ms

    def wait(self, amount, unit):
        self.clock += amount
        if self.interrupt:
            self.interrupt = False
            raise KeyboardInterrupt


class MotionHelpers(unittest.TestCase):
    def setUp(self):
        self.robot = Robot()
        def timer():
            start=self.robot.clock
            return types.SimpleNamespace(time=lambda unit:self.robot.clock-start)
        self.namespace = dict(robot=self.robot, Timer=timer, wait=self.robot.wait, MSEC=0, LEFT=-1, RIGHT=1, DPS=0, MMPS=0)
        exec(compile(STOP_HELPER.read_text() + '\n' + HELPERS.read_text(), str(HELPERS), "exec"), self.namespace)
        self.motion = self.namespace["_va_motion"]

    def test_full_turn_is_one_action_and_reports_only_sensor_verification(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.motion("turn", -360, 0, 60)
        lines = output.getvalue().splitlines()
        self.assertIn('"event": "started"', lines[0])
        result = json.loads(lines[-1])
        self.assertEqual(result["rotation_delta_deg"], -360)
        self.assertFalse(result["physical_accuracy_verified"])
        self.assertTrue(result["stopped"])
        self.assertEqual(self.robot.starts, 1)
        self.assertLessEqual(self.robot.clock, 6300)

    def test_stalled_action_is_stopped_by_robot_deadline(self):
        self.robot.stalled = True
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "deadline"):
            self.motion("turn", 360, 0, 30)
        self.assertEqual(self.robot.stops, 1)
        self.assertLessEqual(self.robot.clock, 20200)

    def test_interrupt_always_stops(self):
        self.robot.interrupt = True
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
            self.motion("turn", 90, 0, 60)
        self.assertEqual(self.robot.stops, 1)

    def test_gyro_initializing_and_invalid_arguments_do_not_start(self):
        self.robot.calibrating = True
        with self.assertRaisesRegex(RuntimeError, "initializing"):
            self.motion("turn", 90, 0, 60)
        self.robot.calibrating = False
        for value in (0, 361, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.motion("turn", value, 0, 60)
        self.assertEqual(self.robot.starts, 0)

    def test_delayed_stopped_state_is_polled_without_repeating_stop_or_motion(self):
        self.robot.stop_settle_ms = 350
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.motion("turn", -15, 0, 30)
        result = json.loads(output.getvalue().splitlines()[-1])
        self.assertTrue(result['stopped'])
        self.assertEqual((self.robot.starts, self.robot.stops), (1, 1))
        self.assertGreaterEqual(self.robot.clock, 850)
        self.assertLessEqual(self.robot.clock, 900)

    def test_unconfirmed_stop_has_a_finite_deadline_and_no_retry(self):
        self.robot.stop_settle_ms = float('inf')
        self.assertFalse(self.namespace['_va_stop']())
        self.assertEqual(self.robot.clock, 1000)
        self.assertEqual((self.robot.starts, self.robot.stops), (0, 1))

    def test_movement_with_unconfirmed_stop_still_fails(self):
        self.robot.stop_settle_ms = float('inf')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, 'sensor check failed'):
            self.motion('turn', -15, 0, 30)
        self.assertEqual((self.robot.starts, self.robot.stops), (1, 1))
        self.assertLessEqual(self.robot.clock, 1500)


if __name__ == "__main__":
    unittest.main()
