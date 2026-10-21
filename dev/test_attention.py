"""Attention cues must never stand in for an operator's acknowledgment."""

import json
import unittest
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import attention


class AttentionTests(unittest.TestCase):
    def test_unheard_rehearsal_cannot_enable_unattended_alerts(self):
        with TemporaryDirectory() as folder, patch.object(attention, "play_chime"):
            helper = attention.Attention(folder)
            helper.rehearse()
            with self.assertRaisesRegex(RuntimeError, "Confirm"):
                helper.request("Turn robot on", "Robot unreachable", 1)

    def test_audio_failure_is_durable_and_cannot_be_confirmed(self):
        with TemporaryDirectory() as folder:
            helper = attention.Attention(folder)
            with (
                patch.object(
                    attention, "play_chime", side_effect=RuntimeError("No audio")
                ),
                self.assertRaisesRegex(RuntimeError, "No audio"),
            ):
                helper.rehearse()
            with self.assertRaises(RuntimeError):
                helper.confirm()
            self.assertEqual(
                json.loads(helper.rehearsal.read_text())["state"], "incomplete"
            )

    def exercise_request(self, reply_at=None, cancel=False, fail_audio=False):
        with TemporaryDirectory() as folder:
            helper = attention.Attention(folder)
            now = [0.0]
            alerts = []

            def chime():
                # The action must be written before the operator hears anything.
                pending = json.loads(helper.pending.read_text())
                self.assertEqual(pending["state"], "awaiting_user")
                self.assertEqual(pending["action"], "Turn AIM on")
                if fail_audio:
                    raise RuntimeError("Playback failed")
                alerts.append(now[0])

            def sleep(seconds):
                now[0] += seconds
                if reply_at is not None and now[0] >= reply_at:
                    request = json.loads(helper.pending.read_text())
                    path = helper.directory / (request["request_id"] + ".reply.json")
                    if not path.exists():
                        helper.reply(request["request_id"], cancel)

            with patch.object(attention, "play_chime"):
                helper.rehearse()
                helper.confirm()
            clock = SimpleNamespace(
                monotonic=lambda: now[0], time=lambda: 1000 + now[0], sleep=sleep
            )
            with (
                patch.object(attention, "time", clock),
                patch.object(attention, "play_chime", chime),
                patch("builtins.print"),
            ):
                result = helper.request("Turn AIM on", "Connection lost")
            durable = json.loads(helper.pending.read_text())
            self.assertEqual(result, durable)
            if result["state"] == "incomplete":
                with self.assertRaisesRegex(RuntimeError, "no longer"):
                    helper.reply(result["request_id"])
            return result, alerts, now[0]

    def test_timeout_is_incomplete_with_only_three_alerts(self):
        result, alerts, elapsed = self.exercise_request()
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(alerts, [0, 60, 120])
        self.assertEqual(elapsed, 600)

    def test_acknowledgment_stops_alerts_without_authorizing_actions(self):
        result, alerts, elapsed = self.exercise_request(reply_at=10)
        self.assertEqual(result["state"], "acknowledged")
        self.assertEqual(alerts, [0])
        self.assertEqual(elapsed, 10)
        self.assertNotIn("passed", result)

    def test_cancellation_never_becomes_acknowledgment(self):
        result, alerts, _ = self.exercise_request(reply_at=75, cancel=True)
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(alerts, [0, 60])

    def test_playback_failure_preserves_the_pending_action(self):
        result, alerts, elapsed = self.exercise_request(fail_audio=True)
        self.assertEqual(result["state"], "incomplete")
        self.assertEqual(result["action"], "Turn AIM on")
        self.assertEqual(alerts, [])
        self.assertEqual(elapsed, 0)

    def test_reply_after_deadline_is_rejected_even_if_request_process_stopped(self):
        with TemporaryDirectory() as folder:
            helper = attention.Attention(folder)
            attention.write_json(
                helper.pending,
                {"state": "awaiting_user", "request_id": "old", "expires_at": 1000},
            )
            with (
                patch.object(attention.time, "time", return_value=1001),
                self.assertRaisesRegex(RuntimeError, "no longer"),
            ):
                helper.reply("old")
            self.assertFalse((helper.directory / "old.reply.json").exists())


if __name__ == "__main__":
    unittest.main()
