"""Exercise the robot-side lease with a simulated SDK clock and scheduler.

These tests establish cleanup/ownership behavior, not real Thread scheduling.
"""

import unittest
from pathlib import Path
from types import SimpleNamespace

SOURCE = (Path(__file__).parents[1] / "cli/vexaim/src/power.py").read_text()


class LeaseTests(unittest.TestCase):
    def setup_sdk(self, initial=False, start_worker=True, fail_worker=False):
        self.clock = 100000
        self.flag = initial
        self.sets = []
        self.workers = []

        def control(*values):
            if values:
                self.flag = values[0]
                self.sets.append(values[0])
            return self.flag

        def thread(worker):
            if fail_worker:
                raise RuntimeError("injected Thread failure")
            instance = worker.__self__
            self.workers.append(instance)
            if start_worker:
                instance.tick()
            return instance

        self.scope = {
            "robot": SimpleNamespace(
                _sleep_disable=control,
                timer=SimpleNamespace(system=lambda: self.clock & 0xFFFFFFFF),
            ),
            "Thread": thread,
            "MSEC": "MSEC",
            "wait": lambda delay, units: setattr(self, "clock", self.clock + delay),
        }
        exec(SOURCE, self.scope)  # noqa: S102 - actual embedded helper in an isolated fake SDK
        self.acquire = self.scope["_va_power_acquire"]

    def test_loading_definitions_does_not_set_power_or_start_a_worker(self):
        self.setup_sdk()
        self.assertEqual(self.sets, [])
        self.assertEqual(self.workers, [])

    def test_acquire_requires_a_started_watchdog_and_boolean_readback(self):
        self.setup_sdk()
        value = self.acquire("owner", 1800000)
        self.assertTrue(value["active"])
        self.assertTrue(value["sleep_disabled"])
        self.assertFalse(value["restore_to"])
        self.assertGreater(value["watchdog_ticks"], 0)

    def test_invalid_lifetimes_do_not_change_the_sdk(self):
        self.setup_sdk()
        for ttl in (0, -1, 1800001):
            with self.assertRaises(ValueError):
                self.acquire("owner", ttl)
        self.assertEqual(self.sets, [])

    def test_expiry_restores_without_a_host_renewal(self):
        self.setup_sdk()
        self.acquire("owner", 1800000)
        lease = self.scope["_va_power_lease"]
        self.clock += 1800000
        lease.tick()
        self.assertFalse(self.flag)
        self.assertFalse(lease.active)
        self.assertTrue(lease.expired)
        self.assertEqual(self.sets, [True, False])

    def test_wraparound_does_not_make_the_lease_infinite(self):
        self.setup_sdk()
        self.clock = 0xFFFFFF00
        self.acquire("owner", 1000)
        lease = self.scope["_va_power_lease"]
        self.clock += 1000
        lease.tick()
        self.assertFalse(self.flag)
        self.assertFalse(lease.active)

    def test_prior_true_is_restored_rather_than_overridden(self):
        self.setup_sdk(initial=True)
        self.acquire("owner", 1000)
        self.scope["_va_power_lease"].release("owner")
        self.assertTrue(self.flag)

    def test_another_owner_cannot_renew_or_release_an_active_lease(self):
        self.setup_sdk()
        self.acquire("owner", 1000)
        lease = self.scope["_va_power_lease"]
        for action in (
            lambda: self.acquire("different", 1000),
            lambda: lease.renew("different", 1000),
            lambda: lease.release("different"),
        ):
            with self.assertRaises(RuntimeError):
                action()
        self.assertTrue(self.flag)
        self.assertTrue(lease.active)

    def test_real_client_renewal_reuses_the_worker_and_extends_expiry(self):
        self.setup_sdk()
        self.acquire("owner", 1000)
        self.clock += 500
        self.acquire("owner", 1000)
        lease = self.scope["_va_power_lease"]
        self.clock += 500
        lease.tick()
        self.assertTrue(lease.active)
        self.assertEqual(len(self.workers), 1)
        self.clock += 500
        lease.tick()
        self.assertFalse(lease.active)

    def test_missing_worker_rolls_back_the_flag(self):
        self.setup_sdk(start_worker=False)
        with self.assertRaisesRegex(RuntimeError, "watchdog did not start"):
            self.acquire("owner", 1800000)
        self.assertFalse(self.flag)

    def test_worker_creation_error_rolls_back_the_flag(self):
        self.setup_sdk(fail_worker=True)
        with self.assertRaisesRegex(RuntimeError, "Thread failure"):
            self.acquire("owner", 1800000)
        self.assertFalse(self.flag)

    def test_old_worker_cannot_release_the_replacement_lease(self):
        self.setup_sdk()
        self.acquire("old", 1000)
        old = self.scope["_va_power_lease"]
        self.clock += 1000
        old.tick()
        self.acquire("new", 1000)
        old.tick()
        old.release("old")
        self.assertTrue(self.flag)
        self.assertTrue(self.scope["_va_power_lease"].active)

    def test_a_stalled_worker_is_detected_and_can_be_replaced(self):
        self.setup_sdk()
        self.acquire("owner", 1800000)
        old = self.scope["_va_power_lease"]
        self.clock += 4000
        with self.assertRaisesRegex(RuntimeError, "stopped advancing"):
            old.renew("owner", 1800000)
        self.acquire("owner", 1800000)
        self.assertFalse(old.active)
        self.assertIsNot(old, self.scope["_va_power_lease"])
        self.assertTrue(self.flag)

    def test_context_handoff_replaces_the_worker_without_a_sleep_gap(self):
        self.setup_sdk()
        self.acquire("owner", 1800000)
        old = self.scope["_va_power_lease"]
        self.acquire("owner", 1800000, None, True)
        replacement = self.scope["_va_power_lease"]
        self.assertIsNot(old, replacement)
        self.assertFalse(old.active)
        self.assertFalse(replacement.previous)
        self.assertEqual(self.sets, [True, True])
        old.release("owner")
        self.assertTrue(self.flag)
        replacement.release("owner")
        self.assertFalse(self.flag)

    def test_unexpected_worker_exit_restores_the_original_flag(self):
        self.setup_sdk()
        self.acquire("owner", 1800000)
        self.scope["wait"] = lambda *_: (_ for _ in ()).throw(
            RuntimeError("worker exit")
        )
        with self.assertRaisesRegex(RuntimeError, "worker exit"):
            self.scope["_va_power_lease"].watch()
        self.assertFalse(self.flag)

    def test_non_boolean_sdk_state_is_not_written(self):
        self.setup_sdk(initial=1)
        with self.assertRaisesRegex(RuntimeError, "not Boolean"):
            self.acquire("owner", 1000)
        self.assertEqual(self.sets, [])


if __name__ == "__main__":
    unittest.main()
