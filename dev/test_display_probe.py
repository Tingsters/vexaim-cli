"""AIM display protocol fixtures; no radio, vault, photos or robot required."""

import binascii
import importlib.util
import struct
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

spec = importlib.util.spec_from_file_location(
    "display_probe", Path(__file__).with_name("display-probe.py")
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def reply(family, opcode, body=b"", ack=0x76):
    data = bytes([opcode, ack]) + body
    head = b"\xaa\x55" + bytes([family, len(data) + 2]) + data
    return head + binascii.crc_hqx(head, 0).to_bytes(2, "big")


class Protocol(unittest.TestCase):
    def test_official_function_payload_fixtures(self):
        # Independent fixtures from emulation of official VEXcom's functions.
        expected = {
            "start": "c936b847577f2020190000000000000000000000000000000000000000000000000000000000007d2c",
            "stop": "c936b847577f20201a000000000000000000000000000000000000000000000000000000000000ff76",
            "emoji": "c936b847577f2020160000000000000600000000000000000000000000000000000000000000006456",
            "hide": "c936b847577f2020170000000000000000000000000000000000000000000000000000000000005875",
        }
        for name, wire in expected.items():
            with self.subTest(name=name):
                self.assertEqual(probe.remote_packet(name), bytes.fromhex(wire))

    def test_fragmented_interleaved_families(self):
        remote = reply(0x57, 0x7F)
        system = reply(0x56, 0x20, b"1234567")
        for split in range(1, len(remote + system)):
            frames = probe.Frames()
            frames.feed((remote + system)[:split])
            frames.feed((remote + system)[split:])
            self.assertEqual(frames.take(0x56, 0x20), b"1234567")
            self.assertEqual(frames.take(0x57, 0x7F), b"")
            self.assertIsNone(frames.take(0x57, 0x7F))

    def test_bad_crc_length_header_and_nack(self):
        wire = bytearray(reply(0x57, 0x7F))
        wire[-1] ^= 1
        for bad in (wire, b"\xaa\x55\x57\x03", b"nope", b"\xaa\x55\x57\xff\xff"):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                probe.Frames().feed(bad)
        frames = probe.Frames()
        frames.feed(reply(0x57, 0x7F, ack=0xFF))
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            frames.take(0x57, 0x7F)

    def test_long_frame_split_at_varint(self):
        body = b"x" * 128
        data = bytes([0x7E, 0x76]) + body
        size = len(data) + 2
        head = b"\xaa\x55\x57" + bytes([0x80, size]) + data
        wire = head + binascii.crc_hqx(head, 0).to_bytes(2, "big")
        frames = probe.Frames()
        frames.feed(wire[:4])
        frames.feed(wire[4:])
        self.assertEqual(frames.take(0x57, 0x7E), body)

    def test_only_display_and_lifecycle_commands_are_available(self):
        for forbidden in ("drive", "kick", "calibrate", "program", "reset"):
            with self.assertRaises(KeyError):
                probe.remote_packet(forbidden)

    def test_official_circle_and_clear_payloads(self):
        # These were also checked against the official function in x86 emulation.
        for name, payload in {
            "clear": "2015000000000000ff0000000000000000000000000000000000000000000000",
            "circle": "202d0000000000007800780028000000ffffff00000000000000000000000000",
        }.items():
            with self.subTest(name=name):
                self.assertEqual(
                    probe.remote_packet(name)[7:-2], bytes.fromhex(payload)
                )

    def test_rgb565_png_decodes_to_known_primary_colors(self):
        raw = bytearray(240 * 240 * 2)
        struct.pack_into("<HHH", raw, 0, 0xF800, 0x07E0, 0x001F)
        image = probe.lcd_png(raw)
        pos = 8
        compressed = bytearray()
        while pos < len(image):
            size = struct.unpack_from(">I", image, pos)[0]
            kind, data = image[pos + 4 : pos + 8], image[pos + 8 : pos + 8 + size]
            self.assertEqual(
                zlib.crc32(kind + data),
                struct.unpack_from(">I", image, pos + 8 + size)[0],
            )
            if kind == b"IDAT":
                compressed.extend(data)
            pos += size + 12
        pixels = zlib.decompress(compressed)
        self.assertEqual(pixels[:10], b"\0\xff\0\0\0\xff\0\0\0\xff")


class Transport(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_observation_writes_once_without_claiming_ack(self):
        calls = []

        async def write(_, wire, response):
            calls.append(wire)

        report = {"remote_commands": []}
        system = probe.System(
            SimpleNamespace(write_gatt_char=write),
            SimpleNamespace(SYSTEM_RX="rx"),
            report,
            True,
        )
        await system.remote("start")
        self.assertEqual(calls, [probe.remote_packet("start")])
        self.assertFalse(report["remote_commands"][0]["acknowledged"])
        self.assertIn("observation required", report["remote_commands"][0]["delivery"])

    async def test_keepalive_is_a_bounded_read_query(self):
        calls = []

        async def write(_, wire, response):
            calls.append(wire)

        report = {}
        system = probe.System(
            SimpleNamespace(write_gatt_char=write),
            SimpleNamespace(SYSTEM_RX="rx"),
            report,
        )
        with (
            patch.object(
                probe, "time", SimpleNamespace(monotonic=iter([0, 0, 60]).__next__)
            ),
            patch.object(probe.asyncio, "sleep", new_callable=AsyncMock),
        ):
            await system.keepalive()
        self.assertEqual(calls, [probe.packet(0x57, 0x7E)])
        self.assertEqual(report["keepalive_reads_sent"], 1)

    async def test_timeout_does_not_replay_start(self):
        calls = []

        async def write(_, wire, response):
            calls.append(wire)

        system = probe.System(
            SimpleNamespace(write_gatt_char=write),
            SimpleNamespace(SYSTEM_RX="rx"),
            {"remote_commands": []},
        )
        with (
            patch.object(system.queue, "get", side_effect=TimeoutError),
            self.assertRaises(TimeoutError),
        ):
            await system.remote("start")
        self.assertEqual(len(calls), 1)

    async def test_connection_loss_does_not_replay_start(self):
        calls = []

        async def write(_, wire, response):
            calls.append(wire)
            raise OSError("Disconnected")

        system = probe.System(
            SimpleNamespace(write_gatt_char=write),
            SimpleNamespace(SYSTEM_RX="rx"),
            {"remote_commands": []},
        )
        with self.assertRaises(OSError):
            await system.remote("start")
        self.assertEqual(len(calls), 1)

    async def test_fragmented_ack_and_no_replay_on_rejection(self):
        calls = []
        report = {"remote_commands": []}
        system = None

        async def write(_, wire, response):
            calls.append(wire)
            data = reply(0x57, 0x7F, ack=0xFF)
            system.notify(None, data[:3])
            system.notify(None, data[3:])

        system = probe.System(
            SimpleNamespace(write_gatt_char=write),
            SimpleNamespace(SYSTEM_RX="rx"),
            report,
        )
        with self.assertRaisesRegex(RuntimeError, "rejected"):
            await system.remote("start")
        self.assertEqual(len(calls), 1)
        self.assertFalse(report["remote_commands"][0]["acknowledged"])

    async def test_framebuffer_rejects_wrong_address(self):
        system = None

        async def write(_, wire, response):
            head = b"\xaa\x55\x56\x0b\x14" + struct.pack("<I", 4) + b"abcd"
            system.notify(None, head + binascii.crc_hqx(head, 0).to_bytes(2, "big"))

        system = probe.System(
            SimpleNamespace(write_gatt_char=write), SimpleNamespace(SYSTEM_RX="rx"), {}
        )
        with self.assertRaisesRegex(RuntimeError, "address or length"):
            await system.read_buffer(
                probe.packet(0x56, 0x14, struct.pack("<IH", 0, 4)), 0, 4
            )


if __name__ == "__main__":
    unittest.main()
