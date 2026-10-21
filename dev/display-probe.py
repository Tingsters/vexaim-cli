"""Stationary AIM display investigation, Bluetooth only; not a student dependency.

uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python
    dev/display-probe.py --name AIM6518 --case normalize --ready

Close any CLI session first. Pair beforehand through vexaim; never pass a PIN.
No saved projects, firmware, motion, kicker, calibration or menu navigation.
Reports and optional LCD images stay local under .vexaim/display-spike/.
"""

import argparse
import asyncio
import binascii
import contextlib
import importlib.util
import json
import struct
import sys
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path

# Derived from official VEXcom 1.0.2b2 (PE SHA256
# cc15efc812e19a08ca5f2f864305720c8fa513b390e9004f8b806b6f40e4d40e).
# _aimrc_command_program_start/stop, _aimrc_command_screen, _aimrc_RcCmd.
# Start/stop/show/hide payloads checked by emulating the official functions.
# This is the REMOTE command family 0x57, not normal CDC family 0x56.
REMOTE_OPS = {
    "start": 0x19,
    "stop": 0x1A,
    "clear": 0x15,
    "emoji": 0x16,
    "hide": 0x17,
    "circle": 0x2D,
}
CASES = (
    "normalize",
    "remote-draw",
    "init-after-repl",
    "init-before-repl",
    "init-native",
)
IDENTITY = {"model": "AIM", "hardware": "REV1", "firmware": "1.0.0.b0"}
PREPARE = """from vex import *
from vex_globals import *
import json
try:
    robot
except NameError:
    robot=Robot()
"""
STATE = """print(json.dumps({'battery_pct':robot.get_battery_level(),
'stopped':robot.is_stopped(),'heading':robot.inertial.get_heading(),
'rotation':robot.inertial.get_rotation(),'x_mm':robot.get_x_position(),
'y_mm':robot.get_y_position(),'imu_calibrating':robot.inertial.is_calibrating()}))
"""
NORMALIZE = """robot.screen.hide_emoji()
robot.screen.set_origin(0,0)
robot.screen.set_clip_region(0,0,240,240)
robot.screen.set_pen_width(3)
robot.screen.set_pen_color(WHITE)
robot.screen.set_fill_color(WHITE)
robot.screen.set_font(FontType.MONO20)
robot.screen.clear_screen(BLUE)
robot.screen.draw_circle(120,120,40)
robot.screen.set_fill_color(BLUE)
robot.screen.print_at('LCD TEST',x=65,y=65)
"""


def packet(family, opcode, payload=b""):
    if family not in (0x56, 0x57) or len(payload) > 127:
        raise ValueError("Unexpected AIM command family or payload size")
    head = bytes.fromhex("c936b847") + bytes([family, opcode, len(payload)]) + payload
    return head + binascii.crc_hqx(head, 0).to_bytes(2, "big")


def remote_packet(name):
    data = bytearray(32)
    data[0], data[1] = 32, REMOTE_OPS[name]
    params = {
        "emoji": b"\x06\x00",
        "clear": b"\xff\x00\x00\x00",
        "circle": struct.pack("<hhhH", 120, 120, 40, 0) + b"\xff\xff\xff\x00",
    }.get(name, b"")
    data[8 : 8 + len(params)] = params
    return packet(0x57, 0x7F, data)


class Frames:
    """Reassemble notifications without discarding another family's reply."""

    def __init__(self):
        self.pending = bytearray()
        self.frames = []

    def feed(self, data):
        self.pending.extend(data)
        if len(self.pending) > 8192 or len(self.frames) > 64:
            raise RuntimeError("System notification overflow")
        while len(self.pending) >= 4:
            if self.pending[:2] != b"\xaa\x55":
                raise RuntimeError("Unknown system reply header")
            header = 5 if self.pending[3] & 128 else 4
            if len(self.pending) < header:
                return
            size = (
                (((self.pending[3] & 127) << 8) | self.pending[4])
                if header == 5
                else self.pending[3]
            )
            if not 4 <= size <= 4096:
                raise RuntimeError("Invalid system reply length")
            if len(self.pending) < header + size:
                return
            frame = bytes(self.pending[: header + size])
            del self.pending[: header + size]
            if binascii.crc_hqx(frame[:-2], 0) != int.from_bytes(frame[-2:], "big"):
                raise RuntimeError("System reply CRC failed")
            self.frames.append((frame, header))

    def take(self, family, opcode):
        for i, (frame, header) in enumerate(self.frames):
            if frame[2] == family and frame[header] == opcode:
                del self.frames[i]
                if frame[header + 1] != 0x76:
                    raise RuntimeError(
                        f"AIM rejected {family:02x}/{opcode:02x}: {frame[header + 1]:02x}"
                    )
                return frame[header + 2 : -2]
        return None


class System:
    def __init__(self, client, helper, report, observe_unacknowledged=False):
        self.client, self.helper, self.report = client, helper, report
        self.queue = asyncio.Queue(maxsize=128)
        self.frames = Frames()
        self.overflow = False
        self.observe_unacknowledged = observe_unacknowledged

    def notify(self, _, data):
        try:
            self.queue.put_nowait(bytes(data))
        except asyncio.QueueFull:
            self.overflow = True

    async def exchange(self, data):
        # A single command is in flight; no automatic retries or replay.
        family, opcode = data[4:6]
        await asyncio.wait_for(
            self.client.write_gatt_char(self.helper.SYSTEM_RX, data, response=False), 5
        )
        deadline = time.monotonic() + 3
        while True:
            if self.overflow:
                raise RuntimeError("System notification queue overflow")
            found = self.frames.take(family, opcode)
            if found is not None:
                return found
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"No reply to {family:02x}/{opcode:02x}; command not replayed"
                )
            try:
                data = await asyncio.wait_for(self.queue.get(), remaining)
            except TimeoutError:
                raise TimeoutError(
                    f"No reply to {family:02x}/{opcode:02x}; command not replayed"
                ) from None
            self.frames.feed(data)

    async def remote(self, name):
        wire = remote_packet(name)
        event = {"command": name, "packet_hex": wire.hex(), "acknowledged": False}
        self.report["remote_commands"].append(event)
        if self.observe_unacknowledged:
            await asyncio.wait_for(
                self.client.write_gatt_char(
                    self.helper.SYSTEM_RX, wire, response=False
                ),
                5,
            )
            event["delivery"] = (
                "unacknowledged single write; independent observation required"
            )
            return
        try:
            body = await self.exchange(wire)
        except TimeoutError:
            event["delivery"] = "unacknowledged; not replayed"
            raise
        event.update(acknowledged=True, reply_body_hex=body.hex())

    async def keepalive(self):
        """Official _aimrc_command_delay polls _aimrc_RcStatusCmd every 100 ms.

        Fresh READ queries, not replayed start/draw commands. Bound to 60 seconds.
        """
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            await asyncio.wait_for(
                self.client.write_gatt_char(
                    self.helper.SYSTEM_RX, packet(0x57, 0x7E), response=False
                ),
                3,
            )
            self.report["keepalive_reads_sent"] = (
                self.report.get("keepalive_reads_sent", 0) + 1
            )
            await asyncio.sleep(0.1)

    async def status(self):
        body = await self.exchange(packet(0x56, 0x20))
        if len(body) != 7:
            raise RuntimeError("Unknown AIM SYS_STATUS layout")
        return {
            "flags_hex": body[:3].hex(),
            "screen_id": body[3],
            "body_hex": body.hex(),
        }

    async def capture(self, output):
        await self.exchange(packet(0x56, 0x28))
        init = bytes([2, 2, 15, 0]) + struct.pack("<III", 512 * 272 * 4, 0, 0)
        init += b"ini\x73" + bytes(8) + b"screen" + bytes(18)
        body = await self.exchange(packet(0x56, 0x11, init))
        if len(body) < 6:
            raise RuntimeError("Short framebuffer initialization reply")
        window, size = struct.unpack_from("<HI", body)
        if size != 240 * 240 * 2 or window < 28:
            raise RuntimeError("Unknown LCD framebuffer format")
        raw = bytearray()
        while len(raw) < size:
            count = min(
                128 if not raw else min(216, (window - 15) // 4 * 4), size - len(raw)
            )
            address = len(raw)
            # Read replies use an address instead of an ACK byte. Receive separately.
            wire = packet(0x56, 0x14, struct.pack("<IH", address, count))
            part = await self.read_buffer(wire, address, count)
            raw.extend(part)
        output.write_bytes(lcd_png(raw))
        # No FILE_EXIT: this is a read-only buffer, not a program download.
        return {
            "path": str(output.resolve()),
            "width": 240,
            "height": 240,
            "bytes": output.stat().st_size,
        }

    async def read_buffer(self, wire, address, count):
        await asyncio.wait_for(
            self.client.write_gatt_char(self.helper.SYSTEM_RX, wire, response=False), 5
        )
        deadline = time.monotonic() + 3
        while True:
            if self.overflow:
                raise RuntimeError("System notification queue overflow")
            for i, (frame, header) in enumerate(self.frames.frames):
                if frame[2] == 0x56 and frame[header] == 0x14:
                    del self.frames.frames[i]
                    body = frame[header + 1 : -2]
                    if (
                        len(body) != count + 4
                        or struct.unpack_from("<I", body)[0] != address
                    ):
                        raise RuntimeError(
                            "Framebuffer address or length mismatch; not replayed"
                        )
                    return body[4:]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Framebuffer read timed out; not replayed")
            self.frames.feed(await asyncio.wait_for(self.queue.get(), remaining))


def lcd_png(raw):
    if len(raw) != 240 * 240 * 2:
        raise ValueError("LCD must be 240x240 RGB565")
    rgb = bytearray()
    for y in range(240):
        rgb.append(0)
        for x in range(240):
            v = struct.unpack_from("<H", raw, (y * 240 + x) * 2)[0]
            r, g, b = (v >> 11) & 31, (v >> 5) & 63, v & 31
            rgb.extend(((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)))

    def chunk(kind, body):
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 240, 240, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rgb))
        + chunk(b"IEND", b"")
    )


async def run(args, report):
    spec = importlib.util.spec_from_file_location(
        "ble_probe", Path(__file__).with_name("ble-feasibility.py")
    )
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    if helper.usb_present() is True:
        raise RuntimeError("Disconnect USB for Bluetooth implementation tests")
    matches = [
        (d, a)
        for d, a in (
            await helper.BleakScanner.discover(timeout=8, return_adv=True)
        ).values()
        if (a.local_name or d.name) == args.name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one {args.name}; found {len(matches)}")
    device, _ = matches[0]
    async with helper.BleakClient(device, timeout=15, pair=False) as client:
        connection_request = None
        if sys.platform == "win32" and args.capture:
            try:
                from winrt.windows.devices.bluetooth import (
                    BluetoothLEPreferredConnectionParameters,
                )

                connection_request = (
                    client._backend._requester.request_preferred_connection_parameters(
                        BluetoothLEPreferredConnectionParameters.throughput_optimized
                    )
                )
                report["throughput_request_status"] = str(connection_request.status)
            except (AttributeError, OSError, ImportError, RuntimeError) as error:
                report["throughput_request_error"] = type(error).__name__
        identity = {}
        for field, short in [
            ("model", "2a24"),
            ("firmware", "2a26"),
            ("hardware", "2a27"),
        ]:
            identity[field] = (
                bytes(
                    await client.read_gatt_char(
                        f"0000{short}-0000-1000-8000-00805f9b34fb"
                    )
                )
                .decode()
                .rstrip("\0")
            )
        report["identity"] = identity
        if identity != IDENTITY:
            raise RuntimeError(
                "Display protocol is gated to the inspected AIM REV1 / BLE 1.0.0.b0"
            )
        auth = bytes(await client.read_gatt_char(helper.PAIRING))
        if auth == helper.UNPAIRED:
            helper.keyring.set_keyring(helper.native_credential_store())
            code = helper.keyring.get_password(helper.VAULT_SERVICE, device.address)
            if code is None:
                raise RuntimeError("Pair first through vexaim's masked local prompt")
            pin = helper.decode_pin(code)
            await client.write_gatt_char(helper.PAIRING, pin, response=True)
            if bytes(await client.read_gatt_char(helper.PAIRING)) != pin:
                raise RuntimeError("Stored authentication rejected")
            code = pin = None
        elif len(auth) != 4 or any(digit > 9 for digit in auth):
            raise RuntimeError("Unknown authentication state")
        auth = None  # Authentication values must never enter reports.
        stream = helper.UserStream(client)
        system = System(client, helper, report, args.observe_unacknowledged)
        activated = False
        keepalive = None
        await client.start_notify(helper.USER_TX, stream.notification)
        await client.start_notify(helper.SYSTEM_TX, system.notify)
        try:
            report["screen_before"] = await system.status()
            if not await stream.sync():
                raise RuntimeError("Could not prepare the Python console")
            await stream.execute(PREPARE + "print('{}')\n")
            report["before"] = await stream.execute(STATE)
            if not report["before"]["stopped"] or report["before"]["imu_calibrating"]:
                raise RuntimeError("Stationary state required")
            if args.case.startswith("init-"):
                if args.keepalive:
                    keepalive = asyncio.create_task(system.keepalive())
                activated = True  # Attempt cleanup even after a lost start ACK.
                await system.remote("start")
                report["screen_after_start"] = await system.status()
                if args.case == "init-before-repl":
                    if not await stream.sync():
                        raise RuntimeError("REPL unavailable after remote start")
                    await stream.execute(PREPARE + "print('{}')\n")
                else:
                    # Preserve the prepared raw-REPL state: do not send Ctrl-C.
                    stream.buffer.clear()
                report["after_start"] = await stream.execute(STATE)
                if (
                    not report["after_start"]["stopped"]
                    or report["after_start"]["imu_calibrating"]
                ):
                    raise RuntimeError(
                        "Remote initialization changed stationary/calibration state"
                    )
            native = args.case in ("remote-draw", "init-native")
            print(
                f"WATCH {args.case}: blue background/white circle, HAPPY, then drawing again",
                flush=True,
            )
            if native:
                await system.remote("hide")
                await system.remote("clear")
                await system.remote("circle")
            else:
                await stream.execute(NORMALIZE + "print('{}')\n")
            report["screen_drawing"] = await system.status()
            await asyncio.sleep(3)
            if native:
                await system.remote("emoji")
            else:
                await stream.execute(
                    "robot.screen.show_emoji(HAPPY,LOOK_FORWARD)\nprint('{}')\n"
                )
            report["screen_emoji"] = await system.status()
            await asyncio.sleep(3)
            if native:
                await system.remote("hide")
            else:
                await stream.execute("robot.screen.hide_emoji()\nprint('{}')\n")
            await asyncio.sleep(3)
            if args.capture:
                report["lcd"] = await asyncio.wait_for(
                    system.capture(args.capture), 45 if args.keepalive else 55
                )
            # This is an API/control result. Visibility requires image/human evidence.
            report["after"] = await stream.execute(STATE)
            if not report["after"]["stopped"]:
                raise RuntimeError("Stopped state no longer confirmed")
            report["completed"] = True
        finally:
            if keepalive is not None:
                keepalive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    try:
                        await keepalive
                    except Exception as error:  # noqa: BLE001 - record any cleanup failure
                        report.setdefault("cleanup_errors", []).append(
                            f"Keepalive: {type(error).__name__}: {error}"
                        )
            if client.is_connected:
                # A rejected command must not prevent the other cleanup attempts.
                cleanup = (
                    (["hide", "stop"] if activated else ["hide"])
                    if (activated or args.case == "remote-draw")
                    else []
                )
                for command in cleanup:
                    if any(
                        e["command"] == command and not e["acknowledged"]
                        for e in report["remote_commands"]
                    ):
                        continue  # Do not replay an uncertain display command.
                    try:
                        await system.remote(command)
                    except Exception as error:  # noqa: BLE001 - continue other cleanup attempts
                        report.setdefault("cleanup_errors", []).append(str(error))
                try:
                    if not await stream.sync():
                        raise RuntimeError("Python cleanup synchronization failed")
                    await stream.execute(
                        PREPARE + "robot.screen.hide_emoji()\nprint('{}')\n"
                    )
                    report["recovery"] = await stream.execute(STATE)
                    report["screen_after_cleanup"] = await system.status()
                    await stream.write(b"\x02")
                except Exception as error:  # noqa: BLE001 - preserve incomplete hardware evidence
                    report.setdefault("cleanup_errors", []).append(str(error))
                # Retain both notifications until all Python and system work ends.
                report["unmatched_system_frames"] = [
                    frame.hex() for frame, _ in system.frames.frames
                ]
                report["system_pending_bytes"] = len(system.frames.pending)
                await client.stop_notify(helper.USER_TX)
                await client.stop_notify(helper.SYSTEM_TX)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--case", choices=CASES, required=True)
    parser.add_argument(
        "--ready",
        action="store_true",
        help="Operator confirmed stationary robot; no motors or kicker",
    )
    parser.add_argument("--report", type=Path)
    parser.add_argument(
        "--keepalive",
        action="store_true",
        help="Source-derived 100 ms remote status reads, bounded to 60 seconds; init cases only",
    )
    parser.add_argument(
        "--observe-unacknowledged",
        action="store_true",
        help="Developer-only: observe a single unacknowledged remote write without replay; require independent image/human evidence",
    )
    parser.add_argument(
        "--capture",
        type=Path,
        help="Optional local PNG of the drawing; adds up to 55 seconds",
    )
    args = parser.parse_args()
    if not args.ready:
        parser.error("Obtain power-on/stationary readiness, then supply --ready")
    if args.keepalive and (
        not args.observe_unacknowledged or not args.case.startswith("init-")
    ):
        parser.error("--keepalive requires --observe-unacknowledged and an init case")
    report_path = args.report or Path(".vexaim/display-spike") / (
        args.case + "-" + str(time.time_ns()) + ".json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if args.capture:
        args.capture.parent.mkdir(parents=True, exist_ok=True)
        if args.capture.resolve() == report_path.resolve():
            parser.error("Capture and report paths must differ")
    report = {
        "case": args.case,
        "transport": "bluetooth",
        "timestamp": datetime.now(UTC).isoformat(),
        "completed": False,
        "visibility_verified": False,
        "remote_commands": [],
        "observe_unacknowledged": args.observe_unacknowledged,
    }
    try:
        asyncio.run(run(args, report))
    except Exception as error:  # noqa: BLE001 - always persist the diagnostic report
        report["error"] = f"{type(error).__name__}: {error}"
    finally:
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    ok = (
        report["completed"]
        and not report.get("error")
        and not report.get("cleanup_errors")
        and report.get("recovery", {}).get("stopped") is True
    )
    print(
        json.dumps(
            {
                "ok": ok,
                "report": str(report_path.resolve()),
                "visibility_verified": False,
                "error": report.get("error"),
            }
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
