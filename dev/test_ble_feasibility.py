"""Protocol regressions for the instructor probe; no robot or credential access."""

import asyncio
import binascii
import importlib.util
import io
import json
import sys
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

spec = importlib.util.spec_from_file_location(
    "ble_probe", Path(__file__).with_name("ble-feasibility.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def jpeg_fixture(width=640, height=480):
    # Protocol-only fixture with a valid SOF header; image decoding is checked
    # separately with System.Drawing and real sensor images.
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\x00"
    head = b"\xff\xd8" + sof
    return head + bytes(1278 - len(head)) + b"\xff\xd9"


class FakeClient:
    def __init__(self):
        self.stream = None
        self.calls = 0
        self.writes = []

    async def write_gatt_char(self, characteristic, data, response):
        self.writes.append((characteristic, bytes(data), response))
        if data.endswith(b"\x04"):
            self.calls += 1
            payload = json.dumps({"call": self.calls, "symbol": ">"}).encode()
            self.stream.notification(None, b"OK" + payload + b"\x04\x04")
            # The trailing prompt is delivered separately, as real BLE notifications can be.
            asyncio.get_running_loop().call_later(
                0.01, self.stream.notification, None, b">"
            )


class PinTests(unittest.TestCase):
    def test_numeric_pin_encoding_including_leading_zero(self):
        self.assertEqual(probe.decode_pin("0123"), bytes([0, 1, 2, 3]))

    def test_invalid_pin_error_does_not_echo_input(self):
        for value in ["123", "12345", "12a4", "１２３４"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as raised:
                    probe.decode_pin(value)
                self.assertNotIn(value, str(raised.exception))


class AimNavigationTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def reply(ack=0x76):
        head = bytes.fromhex("aa55560465") + bytes([ack])
        return head + binascii.crc_hqx(head, 0).to_bytes(2, "big"), 4

    async def test_named_navigation_matches_official_host_tool_wire_format(self):
        for action, code in [
            ("center", 0x51),
            ("back", 0x52),
            ("left", 0x53),
            ("right", 0x54),
        ]:
            with self.subTest(action=action):
                exchange = AsyncMock(return_value=self.reply())
                result = {}
                await probe.aim_lcd_navigation(exchange, action, result)
                head = bytes.fromhex("c936b847566501") + bytes([code])
                exchange.assert_awaited_once_with(
                    head + binascii.crc_hqx(head, 0).to_bytes(2, "big"), 0x56
                )
                self.assertTrue(result["acknowledged"])

    async def test_nack_is_not_retried_or_treated_as_success(self):
        exchange = AsyncMock(return_value=self.reply(0xFF))
        with self.assertRaisesRegex(RuntimeError, "not acknowledged"):
            await probe.aim_lcd_navigation(exchange, "center", {})
        self.assertEqual(exchange.await_count, 1)

    async def test_timeout_does_not_repeat_a_possible_selection(self):
        exchange = AsyncMock(return_value=None)
        with self.assertRaisesRegex(TimeoutError, "not retried"):
            await probe.aim_lcd_navigation(exchange, "center", {})
        self.assertEqual(exchange.await_count, 1)

    async def test_bad_crc_cannot_confirm_a_mode_change(self):
        frame, offset = self.reply()
        exchange = AsyncMock(return_value=(frame[:-1] + bytes([frame[-1] ^ 1]), offset))
        with self.assertRaises(RuntimeError):
            await probe.aim_lcd_navigation(exchange, "center", {})

    async def test_unknown_action_cannot_send_a_packet(self):
        exchange = AsyncMock()
        with self.assertRaises(ValueError):
            await probe.aim_lcd_navigation(exchange, "guess-a-screen-id", {})
        exchange.assert_not_called()


class AimStatusTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def reply(screen_id=32):
        head = bytes.fromhex("aa55560b2076000611") + bytes([screen_id, 8, 0, 16])
        return head + binascii.crc_hqx(head, 0).to_bytes(2, "big"), 4

    async def test_screen_id_matches_official_host_status_layout(self):
        exchange = AsyncMock(return_value=self.reply())
        self.assertEqual(
            await probe.aim_lcd_status(exchange),
            {"screen_id": 32, "flags_hex": "000611"},
        )

    async def test_unknown_status_layout_or_bad_crc_is_rejected(self):
        frame, offset = self.reply()
        for reply in [(frame[:-1], offset), (frame[:-1] + b"\x00", offset), (frame, 5)]:
            with self.subTest(reply=reply):
                with self.assertRaises(RuntimeError):
                    await probe.aim_lcd_status(AsyncMock(return_value=reply))

    async def test_status_timeout_is_bounded(self):
        with self.assertRaises(TimeoutError):
            await probe.aim_lcd_status(AsyncMock(return_value=None))


class AutomaticMenuTests(unittest.IsolatedAsyncioTestCase):
    dashboard, ai_vision = probe.MENU_ICONS

    async def test_uncalibrated_firmware_cannot_send_any_menu_or_capture_operation(
        self,
    ):
        capture = AsyncMock()
        with (
            patch.object(probe, "check_screen_capture", capture),
            self.assertRaisesRegex(RuntimeError, "calibrated only"),
        ):
            await probe.lcd_only_capture(
                object(),
                SimpleNamespace(select_ai_vision=True),
                {
                    "device_info": {
                        "model": "AIM",
                        "hardware": "REV1",
                        "firmware": "unknown",
                    }
                },
            )
        capture.assert_not_called()

    async def run_menu(self, state):
        actions = []

        async def status(_exchange):
            return {
                "screen_id": (
                    0
                    if state["page"] == "home"
                    else 34 if state["page"] == "camera" else 32
                )
            }

        async def label(_exchange):
            return state[state["page"]][state["index"]]

        async def navigate(_exchange, action, result):
            actions.append(action)
            if action == "right":
                state["index"] = (state["index"] + 1) % len(state[state["page"]])
            elif action == "back":
                state.update(page="home", index=0)
            elif action == "center":
                current = state[state["page"]][state["index"]]
                if current == self.dashboard:
                    state.update(page="dashboard", index=state["remembered"])
                elif current == self.ai_vision:
                    state.update(page="camera", index=0)
                else:
                    self.fail("Automation selected an unknown or actuator tile")
            result["acknowledged"] = True

        report = {}
        with (
            patch.object(probe, "aim_lcd_status", side_effect=status),
            patch.object(probe, "read_menu_icon", side_effect=label),
            patch.object(probe, "aim_lcd_navigation", side_effect=navigate),
            patch.object(probe.asyncio, "sleep", new=AsyncMock()),
        ):
            await probe.select_ai_vision(AsyncMock(), report)
        return actions, report

    async def test_remembered_dashboard_position_is_observed_instead_of_replaying_boot_sequence(
        self,
    ):
        actions, report = await self.run_menu(
            {
                "page": "home",
                "index": 1,
                "remembered": 2,
                "home": ["Drive", "Projects", self.dashboard, "Settings"],
                "dashboard": ["Drivetrain", self.ai_vision, "Kicker", "LEDs"],
            }
        )
        self.assertEqual(
            actions, ["right", "center", "right", "right", "right", "center"]
        )
        self.assertTrue(report["complete"])
        self.assertFalse(report["reboot_requested"])

    async def test_dashboard_screen_id_alone_never_confirms_camera(self):
        actions, report = await self.run_menu(
            {
                "page": "dashboard",
                "index": 0,
                "remembered": 0,
                "home": [self.dashboard],
                "dashboard": ["Drivetrain", self.ai_vision],
            }
        )
        self.assertEqual(actions, ["back", "center", "right", "center"])
        self.assertTrue(report["complete"])
        self.assertFalse(report["camera_pixels_verified"])

    async def test_verified_camera_screen_34_requires_no_menu_input(self):
        actions, report = await self.run_menu({"page": "camera", "index": 0})
        self.assertEqual(actions, [])
        self.assertTrue(report["already_active"])
        self.assertFalse(report["camera_pixels_verified"])

    async def test_existing_ai_vision_tile_is_observed_after_home_normalization(self):
        actions, _report = await self.run_menu(
            {
                "page": "dashboard",
                "index": 0,
                "remembered": 0,
                "home": [self.dashboard],
                "dashboard": [self.ai_vision],
            }
        )
        self.assertEqual(actions, ["back", "center", "center"])

    async def test_unknown_language_or_layout_never_enables_center(self):
        navigation = AsyncMock()
        with (
            patch.object(
                probe, "aim_lcd_status", new=AsyncMock(return_value={"screen_id": 0})
            ),
            patch.object(
                probe, "read_menu_icon", new=AsyncMock(return_value="unknown")
            ),
            patch.object(probe, "aim_lcd_navigation", navigation),
            patch.object(probe.asyncio, "sleep", new=AsyncMock()),
            self.assertRaisesRegex(RuntimeError, "search limit"),
        ):
            await probe.select_ai_vision(AsyncMock(), {})
        self.assertTrue(
            all(
                call.args[1] in {"right", "back"} for call in navigation.await_args_list
            )
        )
        self.assertLessEqual(navigation.await_count, 8)

    async def test_screen_change_during_confirmation_cannot_send_center(self):
        navigation = AsyncMock()
        with (
            patch.object(
                probe, "aim_lcd_status", new=AsyncMock(return_value={"screen_id": 0})
            ),
            patch.object(
                probe,
                "read_menu_icon",
                new=AsyncMock(side_effect=[self.dashboard, "changed"]),
            ),
            patch.object(probe, "aim_lcd_navigation", navigation),
            self.assertRaisesRegex(RuntimeError, "Menu changed"),
        ):
            await probe.select_ai_vision(AsyncMock(), {})
        navigation.assert_not_called()

    async def test_failed_navigation_stops_without_repeating_an_action(self):
        navigation = AsyncMock(side_effect=TimeoutError("uncertain action"))
        with (
            patch.object(
                probe, "aim_lcd_status", new=AsyncMock(return_value={"screen_id": 0})
            ),
            patch.object(
                probe, "read_menu_icon", new=AsyncMock(return_value="unknown")
            ),
            patch.object(probe, "aim_lcd_navigation", navigation),
            self.assertRaises(TimeoutError),
        ):
            await probe.select_ai_vision(AsyncMock(), {})
        self.assertEqual(navigation.await_count, 1)

    async def test_unexpected_detail_page_requires_back_and_has_a_fixed_limit(self):
        navigation = AsyncMock()
        with (
            patch.object(
                probe, "aim_lcd_status", new=AsyncMock(return_value={"screen_id": 99})
            ),
            patch.object(probe, "aim_lcd_navigation", navigation),
            patch.object(probe, "read_menu_icon", new=AsyncMock()) as label,
            patch.object(probe.asyncio, "sleep", new=AsyncMock()),
            self.assertRaisesRegex(RuntimeError, "four Back"),
        ):
            await probe.select_ai_vision(AsyncMock(), {})
        self.assertEqual(navigation.await_count, 4)
        self.assertTrue(
            all(call.args[1] == "back" for call in navigation.await_args_list)
        )
        label.assert_not_called()


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_commands_consume_delayed_prompts_without_stale_prefix(self):
        client = FakeClient()
        stream = probe.UserStream(client)
        client.stream = stream
        self.assertEqual((await stream.execute("print('one')"))["call"], 1)
        self.assertEqual((await stream.execute("print('two')"))["call"], 2)
        self.assertEqual(stream.buffer[-1:], b">")

    async def test_long_program_respects_minimum_mtu_and_preserves_source(self):
        client = FakeClient()
        stream = probe.UserStream(client)
        client.stream = stream
        source = "# " + "a" * 70
        await stream.execute(source)
        self.assertTrue(all(len(data) <= 20 for _, data, _ in client.writes))
        self.assertEqual(
            b"".join(data for _, data, _ in client.writes), source.encode() + b"\x04"
        )

    async def test_silent_stream_times_out(self):
        stream = probe.UserStream(None)
        self.assertFalse(await stream.until(lambda _value: False, 0.01))

    async def test_overflow_cannot_be_mistaken_for_complete_output(self):
        stream = probe.UserStream(None)
        stream.buffer.extend(b"complete")
        stream.overflow = True
        with self.assertRaisesRegex(RuntimeError, "incomplete"):
            await stream.until(lambda _value: True, 0.01)


class FakeSystemClient:
    def __init__(self, corrupt_first=False, wrong_address=False):
        self.data = bytes(range(256)) * 5
        self.corrupt_first = corrupt_first
        self.wrong_address = wrong_address
        self.callback = None
        self.opcodes = []
        self.screen_id = 32
        self.layers = []

    async def start_notify(self, characteristic, callback):
        self.callback = callback

    async def stop_notify(self, characteristic):
        self.callback = None

    async def write_gatt_char(self, characteristic, packet, response):
        if packet == bytes.fromhex("c936b847a4"):
            reply = bytes.fromhex("aa55a406010000000000")
        else:
            if binascii.crc_hqx(packet[:-2], 0) != int.from_bytes(packet[-2:], "big"):
                raise AssertionError("Request CRC mismatch")
            opcode = packet[5]
            self.opcodes.append(opcode)
            if opcode == 0x28:
                self.layers.append(packet[7] if packet[6] == 1 else None)
                body = b"\x28\x76"
            elif opcode == 0x20:
                body = bytes.fromhex("2076000611") + bytes([self.screen_id, 8, 0, 16])
            elif opcode == 0x11:
                if packet[7:11] != bytes([2, 2, 15, 0]):
                    raise AssertionError("Expected read-only Sys/Cbuf capture access")
                body = b"\x11\x76" + struct.pack("<HI", 232, len(self.data)) + bytes(4)
            elif opcode == 0x14:
                address, size = struct.unpack_from("<IH", packet, 7)
                echoed = address + 4 if self.wrong_address else address
                body = (
                    b"\x14"
                    + struct.pack("<I", echoed)
                    + self.data[address : address + size]
                )
            else:
                raise AssertionError("Unexpected program/upload operation")
            length = len(body) + 2
            encoded_length = (
                bytes([length])
                if length < 128
                else bytes([0x80 | (length >> 8), length & 255])
            )
            head = b"\xaa\x55\x56" + encoded_length + body
            reply = head + binascii.crc_hqx(head, 0).to_bytes(2, "big")
            if opcode == 0x14 and self.corrupt_first:
                reply = reply[:-1] + bytes([reply[-1] ^ 1])
        self.callback(None, reply[:3])
        self.callback(None, reply[3:])


class FramebufferTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_camera_uses_jpeg_without_python_navigation_or_transcoding_from_home(
        self,
    ):
        client = FakeSystemClient()
        client.is_connected = True
        client.screen_id = 0
        client.data = jpeg_fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "native.jpg"
            report = {
                "device_info": {
                    "model": "AIM",
                    "hardware": "REV1",
                    "firmware": "1.0.0.b0",
                }
            }
            with patch.object(probe, "encode_lcd_jpeg", new=AsyncMock()) as encoder:
                await probe.lcd_only_capture(
                    client,
                    SimpleNamespace(
                        native_camera=True,
                        jpeg_output=output,
                        framebuffer_output=output,
                    ),
                    report,
                )
                encoder.assert_not_called()
            self.assertEqual(output.read_bytes(), client.data)
            self.assertEqual(list(Path(directory).glob("vexaim-frame-*")), [])
        self.assertEqual(client.layers, [8])
        self.assertNotIn(0x65, client.opcodes)
        self.assertFalse(report["python_console_touched"])
        self.assertFalse(report["display_mode_changed"])
        self.assertEqual(report["jpeg_dimensions"], [640, 480])
        self.assertEqual(report["lcd_status"]["before"]["screen_id"], 0)
        self.assertEqual(report["lcd_status"]["after_capture"]["screen_id"], 0)

    async def test_source_defined_jpeg_layer_stops_after_non_jpeg_header(self):
        client = FakeSystemClient()
        client.screen_id = 34
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "native.jpg"
            with self.assertRaisesRegex(RuntimeError, "did not return a JPEG header"):
                await probe.check_screen_capture(
                    client,
                    layer=8,
                    status_result={},
                    inspect_buffer=True,
                    output_file=output,
                )
            self.assertFalse(output.exists())
        self.assertEqual(client.layers, [8])
        self.assertEqual(client.opcodes.count(0x14), 1)

    async def test_source_defined_jpeg_payload_is_saved_only_with_complete_markers(
        self,
    ):
        for complete in (True, False):
            with self.subTest(complete=complete):
                client = FakeSystemClient()
                client.screen_id = 34
                client.data = jpeg_fixture()
                if not complete:
                    client.data = client.data[:-2] + b"\x00\x00"
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "native.jpg"
                    if complete:
                        result = await probe.check_screen_capture(
                            client,
                            layer=8,
                            status_result={},
                            inspect_buffer=True,
                            output_file=output,
                        )
                        self.assertEqual(output.read_bytes(), client.data)
                        self.assertTrue(result["jpeg_header"])
                    else:
                        with self.assertRaisesRegex(
                            RuntimeError, "JPEG payload is incomplete"
                        ):
                            await probe.check_screen_capture(
                                client,
                                layer=8,
                                status_result={},
                                inspect_buffer=True,
                                output_file=output,
                            )
                        self.assertFalse(output.exists())

    async def test_operational_deadline_can_complete_a_frame_after_thirty_seconds(self):
        for limit in (30, 45):
            with self.subTest(limit=limit), tempfile.TemporaryDirectory() as directory:
                client = FakeSystemClient()
                client.data = bytes(240 * 240 * 2)
                clock = SimpleNamespace(now=0)
                write = client.write_gatt_char

                async def delayed_write(characteristic, packet, response):
                    if packet != bytes.fromhex("c936b847a4") and packet[5] == 0x14:
                        clock.now += 0.07
                    await write(characteristic, packet, response)

                client.write_gatt_char = delayed_write
                output = Path(directory) / "frame.rgb565"
                result = {}
                with patch.object(
                    probe, "time", SimpleNamespace(monotonic=lambda: clock.now)
                ):
                    if limit == 30:
                        with self.assertRaisesRegex(TimeoutError, "exceeded 30"):
                            await probe.check_screen_capture(
                                client,
                                inspect_buffer=True,
                                output_file=output,
                                transfer_timeout=limit,
                                result=result,
                            )
                        self.assertFalse(output.exists())
                        self.assertIn("mean", result["read_round_trip_ms"])
                    else:
                        await probe.check_screen_capture(
                            client,
                            inspect_buffer=True,
                            output_file=output,
                            transfer_timeout=limit,
                            result=result,
                        )
                        self.assertEqual(output.read_bytes(), client.data)
                        self.assertGreater(result["capture_to_raw_seconds"], 30)
                        self.assertLess(result["capture_to_raw_seconds"], 45)

    async def test_layer_one_control_requires_camera_mode_before_capture_request(self):
        client = FakeSystemClient()
        with self.assertRaisesRegex(RuntimeError, "requires the verified AI Vision"):
            await probe.check_screen_capture(client, layer=1, status_result={})
        self.assertNotIn(0x28, client.opcodes)

    async def test_layer_one_control_remains_system_only_and_rejects_empty_buffer(self):
        client = FakeSystemClient()
        client.screen_id = 34
        client.data = b""
        with self.assertRaisesRegex(RuntimeError, "no framebuffer"):
            await probe.check_screen_capture(
                client, layer=1, status_result={}, inspect_buffer=True
            )
        self.assertEqual(client.layers, [1])
        self.assertNotIn(0x14, client.opcodes)

    async def test_complete_read_records_capture_and_round_trip_timing(self):
        client = FakeSystemClient()
        clock = {}
        with tempfile.TemporaryDirectory() as directory:
            result = await probe.check_screen_capture(
                client,
                inspect_buffer=True,
                output_file=Path(directory) / "frame.rgb565",
                capture_clock=clock,
            )
        self.assertIn("started", clock)
        self.assertGreaterEqual(result["capture_to_raw_seconds"], 0)
        self.assertGreater(result["read_round_trip_ms"]["count"], 0)
        self.assertNotIn("sum", result["read_round_trip_ms"])

    async def test_menu_recognition_reads_sequentially_to_icon_band_through_read_only_screen_file(
        self,
    ):
        client = FakeSystemClient()
        client.data = bytes(range(256)) * 450
        pending = asyncio.Queue()
        fragments = bytearray()
        cursor = 0

        def notification(_char, data):
            fragments.extend(data)
            if len(fragments) >= 4:
                header = 5 if fragments[3] & 0x80 else 4
                if len(fragments) < header:
                    return
                length = (
                    ((fragments[3] & 127) << 8) | fragments[4]
                    if header == 5
                    else fragments[3]
                )
                if len(fragments) == header + length:
                    pending.put_nowait((bytes(fragments), header))
                    fragments.clear()

        await client.start_notify(probe.SYSTEM_TX, notification)

        async def exchange(packet, _expected):
            nonlocal cursor
            if packet[5] == 0x14:
                address, size = struct.unpack_from("<IH", packet, 7)
                self.assertEqual(address, cursor, "AIM Cbuf does not allow seeking")
                cursor += size
            await client.write_gatt_char(probe.SYSTEM_RX, packet, False)
            return pending.get_nowait()

        signature = await probe.read_menu_icon(exchange)
        start = probe.MENU_BAND_Y * 240 * 2
        length = probe.MENU_BAND_HEIGHT * 240 * 2
        self.assertEqual(
            signature, probe.menu_icon_fingerprint(client.data[start : start + length])
        )
        self.assertEqual(cursor, start + length)
        self.assertEqual(set(client.opcodes), {0x28, 0x11, 0x14})

    async def test_menu_band_requires_calibrated_framebuffer_dimensions(self):
        client = FakeSystemClient()
        pending = bytearray()
        await client.start_notify(
            probe.SYSTEM_TX, lambda _char, data: pending.extend(data)
        )

        async def exchange(packet, _expected):
            pending.clear()
            await client.write_gatt_char(probe.SYSTEM_RX, packet, False)
            return bytes(pending), 4

        with self.assertRaisesRegex(RuntimeError, "240x240"):
            await probe.read_menu_icon(exchange)
        self.assertNotIn(0x14, client.opcodes)

    async def test_current_lcd_capture_never_writes_to_python_or_changes_display(self):
        client = FakeSystemClient()
        client.is_connected = True
        write = client.write_gatt_char

        async def system_only_write(characteristic, packet, response):
            self.assertEqual(characteristic, probe.SYSTEM_RX)
            await write(characteristic, packet, response)

        client.write_gatt_char = system_only_write
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "current.rgb565"
            report = {}
            await probe.lcd_only_capture(
                client, SimpleNamespace(framebuffer_output=output), report
            )
            self.assertEqual(output.read_bytes(), client.data)
        self.assertFalse(report["python_console_touched"])
        self.assertFalse(report["display_mode_changed"])
        self.assertEqual(set(client.opcodes), {0x20, 0x28, 0x11, 0x14})

    async def test_coalesced_pipelined_replies_are_consumed_without_another_event(self):
        client = FakeSystemClient()
        write = client.write_gatt_char
        coalesced = bytearray()
        read_count = 0

        async def combined_write(characteristic, packet, response):
            nonlocal read_count
            callback = client.callback
            if packet != bytes.fromhex("c936b847a4") and packet[5] == 0x14:
                address = struct.unpack_from("<I", packet, 7)[0]
                if address > 0:
                    client.callback = lambda _char, data: coalesced.extend(data)
                    try:
                        await write(characteristic, packet, response)
                    finally:
                        client.callback = callback
                    read_count += 1
                    if read_count % 2 == 0:
                        callback(None, bytes(coalesced))
                        coalesced.clear()
                    return
            await write(characteristic, packet, response)

        client.write_gatt_char = combined_write
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.rgb565"
            await probe.check_screen_capture(
                client, inspect_buffer=True, output_file=output, pipeline=2
            )
            self.assertEqual(output.read_bytes(), client.data)

    async def test_system_subscription_is_retained_for_subsequent_python_cleanup(self):
        client = FakeSystemClient()
        result = await probe.check_screen_capture(
            client, keep_system_notifications=True
        )
        self.assertIsNotNone(client.callback)
        self.assertTrue(result["system_notifications_retained"])

    async def test_failed_transfer_also_retains_subscription_for_python_cleanup(self):
        client = FakeSystemClient(corrupt_first=True)
        with (
            tempfile.TemporaryDirectory() as directory,
            self.assertRaisesRegex(RuntimeError, "CRC/address"),
        ):
            await probe.check_screen_capture(
                client,
                inspect_buffer=True,
                output_file=Path(directory) / "capture.rgb565",
                keep_system_notifications=True,
            )
        self.assertIsNotNone(client.callback)

    async def test_empty_capture_layer_is_rejected_before_any_memory_read(self):
        client = FakeSystemClient()
        client.data = b""
        result = {}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.rgb565"
            with self.assertRaisesRegex(RuntimeError, "no framebuffer"):
                await probe.check_screen_capture(
                    client, inspect_buffer=True, output_file=output, result=result
                )
            self.assertNotIn(0x14, client.opcodes)
            self.assertFalse(result["buffer_read_complete"])
            self.assertFalse(output.exists())

    async def test_complete_crc_checked_read_is_saved_without_program_exit(self):
        client = FakeSystemClient()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.rgb565"
            result = await probe.check_screen_capture(
                client, inspect_buffer=True, output_file=output
            )
            self.assertEqual(output.read_bytes(), client.data)
            self.assertTrue(result["buffer_read_complete"])
            self.assertEqual(result["bytes_received"], len(client.data))
            self.assertNotIn(0x12, client.opcodes)

    async def test_corrupt_first_block_is_rejected_without_creating_image(self):
        client = FakeSystemClient(corrupt_first=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.rgb565"
            with self.assertRaisesRegex(RuntimeError, "CRC/address"):
                await probe.check_screen_capture(
                    client, inspect_buffer=True, output_file=output
                )
            self.assertFalse(output.exists())

    async def test_wrong_first_address_is_rejected_without_creating_image(self):
        client = FakeSystemClient(wrong_address=True)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "capture.rgb565"
            with self.assertRaisesRegex(RuntimeError, "CRC/address"):
                await probe.check_screen_capture(
                    client, inspect_buffer=True, output_file=output
                )
            self.assertFalse(output.exists())


class LivePreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_starts_without_waiting_for_program_completion(self):
        stream = probe.UserStream(None)

        async def write(source):
            self.assertIn(b"wait(60,SECONDS)", source)
            self.assertIn(b"finally:", source)
            self.assertTrue(source.endswith(b"\x04"))
            stream.notification(None, b"OKpreview-")
            stream.notification(None, b"ready\r\n")

        stream.write = write
        await stream.start_preview()
        self.assertNotIn(b"\x04", stream.buffer)

    async def test_completed_preview_is_rejected_before_capture(self):
        stream = probe.UserStream(None)
        stream.write = AsyncMock()
        stream.notification(None, b"OKpreview-ready\r\n\x04\x04>")
        with self.assertRaisesRegex(RuntimeError, "ended before capture"):
            await stream.start_preview()

    async def test_preview_readiness_timeout_is_bounded(self):
        stream = probe.UserStream(None)
        stream.write = AsyncMock()
        stream.until = AsyncMock(return_value=False)
        with self.assertRaisesRegex(TimeoutError, "signal readiness"):
            await stream.start_preview()

    async def run_capture(self, capture_error=None, cleanup_error=None):
        events = []
        stream = probe.UserStream(None)
        stream.sync = AsyncMock(return_value=True)
        stream.execute = AsyncMock(
            side_effect=[{"battery_pct": 80}, {}, {"battery_pct": 80}]
        )

        async def start():
            events.append("preview-running")
            stream.buffer.extend(b"OKpreview-ready\r\n")

        stream.start_preview = start

        async def capture(*args, **kwargs):
            self.assertEqual(events, ["preview-running"])
            self.assertEqual(stream.sync.await_count, 0)
            self.assertNotIn(b"\x04", stream.buffer)
            events.append("capture")
            if capture_error:
                raise capture_error
            kwargs["result"]["buffer_read_complete"] = True

        if cleanup_error:
            stream.sync.side_effect = cleanup_error
        report = {}
        with patch.object(probe, "check_screen_capture", capture):
            try:
                await probe.live_preview_capture(
                    SimpleNamespace(is_connected=True),
                    stream,
                    SimpleNamespace(framebuffer_output=None),
                    report,
                )
            finally:
                self.assertEqual(stream.sync.await_count, 1)
                self.last_report = report
        return report

    async def test_capture_occurs_before_interrupt_and_console_is_checked_afterward(
        self,
    ):
        report = await self.run_capture()
        self.assertTrue(report["preview_program_active_after_transfer"])
        self.assertTrue(report["console_recovered"])
        self.assertEqual(report["after_capture"]["battery_pct"], 80)

    async def test_transfer_error_survives_cleanup_failure(self):
        with self.assertRaisesRegex(RuntimeError, "primary transfer failure"):
            await self.run_capture(
                RuntimeError("primary transfer failure"),
                RuntimeError("cleanup failure"),
            )
        self.assertEqual(self.last_report["preview_cleanup_error"], "cleanup failure")
        self.assertFalse(self.last_report["console_recovered"])

    async def test_cancellation_still_cleans_up_and_is_propagated(self):
        with self.assertRaises(asyncio.CancelledError):
            await self.run_capture(asyncio.CancelledError())
        self.assertTrue(self.last_report["preview_hidden"])


class DuplexClient(FakeClient):
    """Model the hardware observation: stopping system notifications silences user RX."""

    def __init__(self):
        super().__init__()
        self.stream = self
        self.callbacks = {}
        self.user_delivery = True

    def notification(self, characteristic, value):
        if self.user_delivery:
            self.callbacks[probe.USER_TX](characteristic, value)

    async def start_notify(self, characteristic, callback):
        self.callbacks[characteristic] = callback

    async def stop_notify(self, characteristic):
        self.callbacks.pop(characteristic, None)
        if characteristic == probe.SYSTEM_TX:
            self.user_delivery = False

    async def write_gatt_char(self, characteristic, data, response):
        if characteristic == probe.SYSTEM_RX:
            self.callbacks[probe.SYSTEM_TX](None, b"version-reply")
        else:
            await super().write_gatt_char(characteristic, data, response)


class SystemControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_camera_recovery_keeps_both_subscriptions_until_python_finishes(
        self,
    ):
        client = DuplexClient()
        client.is_connected = True
        stream = SimpleNamespace(
            notification=Mock(), sync=AsyncMock(return_value=True), write=AsyncMock()
        )
        calls = 0

        async def state(_source):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.assertIn(probe.SYSTEM_TX, client.callbacks)
                self.assertIn(probe.USER_TX, client.callbacks)
                self.assertTrue(client.user_delivery)
            return {"battery_pct": 70, "stopped": True}

        stream.execute = AsyncMock(side_effect=state)

        async def capture(_client, _args, report, keep_system_notifications):
            self.assertTrue(keep_system_notifications)
            await client.start_notify(probe.SYSTEM_TX, Mock())
            report["screen_capture_protocol"] = {"system_notifications_retained": True}

        report = {
            "device_info": {"model": "AIM", "hardware": "REV1", "firmware": "1.0.0.b0"}
        }
        with (
            patch.object(probe, "UserStream", return_value=stream),
            patch.object(probe, "lcd_only_capture", side_effect=capture),
        ):
            await probe.native_camera_recovery_control(client, object(), report)
        self.assertEqual(calls, 2)
        self.assertTrue(report["console_recovered"])
        self.assertTrue(report["python_console_touched"])
        self.assertEqual(client.callbacks, {})

    async def test_python_queries_finish_before_system_notification_teardown(self):
        client = DuplexClient()
        stream = probe.UserStream(client)
        await client.start_notify(probe.USER_TX, stream.notification)
        report = {}
        await probe.system_channel_control(client, stream, report)
        self.assertEqual(client.calls, 4)
        self.assertIn(probe.SYSTEM_TX, client.callbacks)
        self.assertTrue(
            report["system_channel_control"]["system_notifications_retained"]
        )
        self.assertEqual(
            report["system_channel_control"]["before_disconnect"]["call"], 4
        )


@unittest.skipUnless(
    sys.platform == "win32", "Local encoder uses Windows System.Drawing"
)
class JpegOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_command_saves_a_valid_jpeg_and_measures_whole_snapshot(self):
        client = FakeSystemClient()
        client.is_connected = True
        client.screen_id = 34
        client.data = struct.pack("<H", 0xF800) * 240 * 240
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "raw frame.rgb565"
            jpeg = Path(directory) / "captured frame.jpg"
            report = {}
            await probe.lcd_only_capture(
                client,
                SimpleNamespace(framebuffer_output=raw, jpeg_output=jpeg),
                report,
            )
            encoded = jpeg.read_bytes()
            self.assertEqual(encoded[:2], b"\xff\xd8")
            self.assertEqual(encoded[-2:], b"\xff\xd9")
            marker = encoded.find(b"\xff\xc0")
            self.assertGreaterEqual(marker, 0)
            self.assertEqual(struct.unpack_from(">HH", encoded, marker + 5), (240, 240))
            self.assertEqual(raw.read_bytes(), client.data)
            self.assertEqual(list(Path(directory).glob("vexaim-jpeg-*")), [])
        self.assertGreaterEqual(
            report["snapshot_seconds"], report["jpeg_encoding_seconds"]
        )
        self.assertGreaterEqual(
            report["snapshot_seconds"],
            report["screen_capture_protocol"]["capture_to_raw_seconds"],
        )
        self.assertTrue(report["snapshot_within_30_seconds"])
        self.assertFalse(report["python_console_touched"])

    async def test_unknown_layout_cannot_start_an_encoder(self):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "unknown.raw"
            raw.write_bytes(b"wrong layout")
            launch = AsyncMock()
            with (
                patch.object(probe.asyncio, "create_subprocess_exec", launch),
                self.assertRaisesRegex(RuntimeError, "unknown framebuffer"),
            ):
                await probe.encode_lcd_jpeg(raw, Path(directory) / "frame.jpg")
            launch.assert_not_called()

    async def test_failed_encoder_preserves_previous_jpeg_and_cleans_staging_directory(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "frame.raw"
            raw.write_bytes(bytes(240 * 240 * 2))
            jpeg = Path(directory) / "frame.jpg"
            jpeg.write_bytes(b"previous image")
            process = SimpleNamespace(
                returncode=1, communicate=AsyncMock(return_value=(b"", b"failed"))
            )
            with (
                patch.object(
                    probe.asyncio,
                    "create_subprocess_exec",
                    new=AsyncMock(return_value=process),
                ),
                self.assertRaisesRegex(RuntimeError, "conversion failed"),
            ):
                await probe.encode_lcd_jpeg(raw, jpeg)
            self.assertEqual(jpeg.read_bytes(), b"previous image")
            self.assertEqual(list(Path(directory).glob("vexaim-jpeg-*")), [])

    async def test_timed_out_encoder_is_killed_before_staging_cleanup(self):
        async def silent_encoder():
            await asyncio.Future()

        real_wait_for = asyncio.wait_for

        async def short_wait(awaitable, _timeout):
            return await real_wait_for(awaitable, 0.001)

        with tempfile.TemporaryDirectory() as directory:
            raw = Path(directory) / "frame.raw"
            raw.write_bytes(bytes(240 * 240 * 2))
            jpeg = Path(directory) / "frame.jpg"
            process = SimpleNamespace(
                returncode=None,
                communicate=silent_encoder,
                kill=Mock(),
                wait=AsyncMock(),
            )
            with (
                patch.object(
                    probe.asyncio,
                    "create_subprocess_exec",
                    new=AsyncMock(return_value=process),
                ),
                patch.object(probe.asyncio, "wait_for", side_effect=short_wait),
                self.assertRaises(TimeoutError),
            ):
                await probe.encode_lcd_jpeg(raw, jpeg)
            process.kill.assert_called_once()
            process.wait.assert_awaited_once()
            self.assertFalse(jpeg.exists())
            self.assertEqual(list(Path(directory).glob("vexaim-jpeg-*")), [])


class SnapshotArgumentTests(unittest.TestCase):
    def test_unsafe_output_combinations_are_rejected_before_any_robot_access(self):
        cases = [
            ["--native-camera"],
            ["--python-recovery-check"],
            ["--native-camera", "--jpeg-output", "a.jpg", "--select-ai-vision"],
            ["--native-camera", "--jpeg-output", "a.jpg", "--capture-layer", "8"],
            ["--capture-layer", "8"],
            ["--jpeg-output", "frame.jpg"],
            ["--lcd-only", "--framebuffer-output", "same", "--jpeg-output", "same"],
            [
                "--lcd-only",
                "--framebuffer-output",
                "raw",
                "--jpeg-output",
                "frame.jpg",
                "--capture-layer",
                "1",
            ],
            ["--lcd-only", "--framebuffer-output", "raw", "--capture-layer", "2"],
        ]
        for arguments in cases:
            with (
                self.subTest(arguments=arguments),
                patch.object(
                    sys, "argv", ["ble-feasibility.py", "--name", "AIM6518"] + arguments
                ),
                patch.object(sys, "stderr", io.StringIO()),
                patch.object(probe, "probe", new=AsyncMock()) as robot,
                self.assertRaises(SystemExit) as raised,
            ):
                probe.main()
            self.assertEqual(raised.exception.code, 2)
            robot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
