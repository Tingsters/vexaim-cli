"""Instructor-only, stationary BLE feasibility probe; not a student dependency.

Run with: uv run --no-project --with bleak==3.0.2 --with keyring==25.7.0 python
    dev/ble-feasibility.py --name AIM6518 --pair --report dist/ble-feasibility.json
Pairing codes are entered with a masked local prompt and saved only in the OS vault.
This does not upload programs, change firmware, drive motors, or operate the kicker.
"""

import argparse
import asyncio
import binascii
import getpass
import hashlib
import json
import re
import struct
import subprocess
import sys
import tempfile
import time
import warnings
from pathlib import Path

import keyring
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

BASE = "08590f7e-db05-467e-8757-72f6faeb"
PAIRING = BASE + "13e5"
USER_TX = BASE + "1316"
USER_RX = BASE + "1326"
SYSTEM_TX = BASE + "1306"
SYSTEM_RX = BASE + "13f5"
VAULT_SERVICE = "vexaim.bluetooth"
UNPAIRED = bytes.fromhex("deadface")


def decode_pin(code):
    if not re.fullmatch(r"[0-9]{4}", code):
        raise ValueError(
            "Enter exactly four digits; the code is not printed or logged."
        )
    # Upstream's bluetooth example encodes numeric digits, not ASCII characters.
    return bytes(int(digit) for digit in code)


def native_credential_store():
    # Select the intended OS vault explicitly; never select a plaintext fallback plugin.
    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring

        return WinVaultKeyring()
    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring

        return Keyring()
    if sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring

        return Keyring()
    raise RuntimeError("No supported native credential store on this platform.")


def usb_present():
    if sys.platform != "win32":
        return None
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "@(Get-PnpDevice -PresentOnly | Where-Object { $_.InstanceId -match "
                "'VID_2888&PID_0700' }).Count"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return int(result.stdout.strip()) > 0


class UserStream:
    def __init__(self, client):
        self.client = client
        self.queue = asyncio.Queue(maxsize=1024)
        self.buffer = bytearray()
        self.overflow = False
        self.received_bytes = 0

    def notification(self, _characteristic, value):
        self.received_bytes += len(value)
        try:
            self.queue.put_nowait(bytes(value))
        except asyncio.QueueFull:
            self.overflow = True

    async def write(self, value):
        # A conservative 20-byte payload works even before MTU negotiation.
        for offset in range(0, len(value), 20):
            await asyncio.wait_for(
                self.client.write_gatt_char(
                    USER_RX, value[offset : offset + 20], response=False
                ),
                5,
            )
            await asyncio.sleep(0.01)

    async def until(self, predicate, timeout):
        deadline = time.monotonic() + timeout
        while True:
            if self.overflow or len(self.buffer) > 65536:
                raise RuntimeError(
                    "Notification buffer overflow; output is incomplete."
                )
            if predicate(self.buffer):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                self.buffer.extend(await asyncio.wait_for(self.queue.get(), remaining))
            except TimeoutError:
                return False

    async def sync(self):
        for _ in range(3):
            await self.write(b"\x03\x03")
            await self.until(lambda _value: False, 0.3)
            self.buffer.clear()
            await self.write(b"\x01")
            if await self.until(lambda value: value.endswith(b"to exit\r\n>"), 2):
                self.buffer.clear()
                return True
        return False

    async def execute(self, code, timeout=15):
        self.buffer.clear()
        await self.write(code.encode("utf-8") + b"\x04")
        if not await self.until(
            lambda value: (
                value.startswith(b"OK")
                and value.count(b"\x04") >= 2
                and value.endswith(b">")
            ),
            timeout,
        ):
            raise TimeoutError(
                "Authenticated BLE user channel did not complete a raw-REPL response."
            )
        stdout, stderr, _tail = bytes(self.buffer[2:]).split(b"\x04", 2)
        if stderr.strip():
            raise RuntimeError(
                "Stationary Python capability query returned a traceback."
            )
        return json.loads(stdout.decode("utf-8").strip())

    def collect_pending(self):
        """Drain this channel only; CDC notifications have their own subscriber."""
        while not self.queue.empty():
            self.buffer.extend(self.queue.get_nowait())
        if self.overflow or len(self.buffer) > 65536:
            raise RuntimeError("Notification buffer overflow; output is incomplete.")

    async def start_preview(self):
        self.buffer.clear()
        # Do not await the raw-REPL completion: the camera display must remain active
        # while the separate system channel snapshots and downloads the framebuffer.
        source = (
            "try:\n"
            " robot.screen.show_aivision()\n"
            " wait(300,MSEC)\n"
            " print('preview-ready')\n"
            " wait(60,SECONDS)\n"
            "finally:\n"
            " robot.screen.hide_aivision()\n"
        )
        await self.write(source.encode() + b"\x04")
        if not await self.until(
            lambda value: b"preview-ready" in value or value.count(b"\x04") >= 2,
            5,
        ):
            raise TimeoutError("Preview program did not signal readiness.")
        if not self.buffer.startswith(b"OK") or b"preview-ready" not in self.buffer:
            raise RuntimeError("Preview program failed before signalling readiness.")
        if b"\x04" in self.buffer:
            raise RuntimeError("Preview program ended before capture began.")


STATE = "print(json.dumps({'battery_pct':robot.get_battery_level(),'stopped':robot.is_stopped()}))\n"


CAPABILITIES = """from vex import *
from vex_globals import *
import json,sys
try:
    robot
except NameError:
    robot=Robot()
result={'battery_pct':robot.get_battery_level(),'stopped':robot.is_stopped(),
        'vision_members':dir(robot.vision),'builtin_modules':list(getattr(sys,'builtin_module_names',[])),
        'get_camera_image_available':hasattr(robot.vision,'get_camera_image')}
text=json.dumps(result)
for i in range(0,len(text),120):
    sys.stdout.write(text[i:i+120])
    wait(60,MSEC)
print()
"""

CAMERA_CAPABILITIES = """import vex,json,sys
try:
    robot
except NameError:
    from vex import *
    from vex_globals import *
    robot=Robot()
result={'platform':sys.platform,'vex_image_names':[n for n in dir(vex) if any(w in n.lower() for w in ['camera','image','jpeg','frame','vision'])]}
# Do not guess debug_get arguments: its semantics are undocumented.
result['vision_method_docs']={n:getattr(getattr(robot.vision,n),'__doc__',None) for n in ['debug_get','take_snapshot','get_data']}
text=json.dumps(result)
for i in range(0,len(text),120):
    sys.stdout.write(text[i:i+120])
    wait(60,MSEC)
print()
"""

NATIVE_IMAGE_CAPABILITIES = """import json
result={}
for name in ['socket','network','camera','framebuf','aim']:
    try:
        module=__import__(name)
        result[name]={'available':True,'image_members':[n for n in dir(module) if any(w in n.lower() for w in ['image','camera','jpeg','frame','capture','socket','timeout'])]}
    except ImportError:
        result[name]={'available':False}
import aim
result['aim_members']=dir(aim)
result['aim_file']=getattr(aim,'__file__',None)
result['aim_repl_members']=dir(aim._repl) if hasattr(aim,'_repl') else []
result['aim_ram_members']=dir(aim._ram) if hasattr(aim,'_ram') else []
layer=getattr(robot.screen,'layer',None)
result['screen_layer']={'type':str(type(layer)),'callable':callable(layer),'doc':getattr(layer,'__doc__',None)}
if isinstance(layer,int):
    result['screen_layer']['value']=layer
result['robot_display_members']=[n for n in dir(robot) if any(w in n.lower() for w in ['program','screen','mode','start','init'])]
text=json.dumps(result)
for i in range(0,len(text),120):
    sys.stdout.write(text[i:i+120])
    wait(60,MSEC)
print()
"""


async def system_channel_control(client, stream, report):
    """Isolate notification subscription from screen/file operations."""
    report["experiment"] = "system-channel-retained-control"
    received = asyncio.Event()
    result = report["system_channel_control"] = {}

    def notification(_characteristic, value):
        if value:
            received.set()

    result["before_subscribe"] = await stream.execute(STATE)
    await client.start_notify(SYSTEM_TX, notification)
    result["system_notifications_retained"] = True
    result["after_subscribe"] = await stream.execute(STATE)
    await client.write_gatt_char(SYSTEM_RX, bytes.fromhex("c936b847a4"), response=False)
    await asyncio.wait_for(received.wait(), 3)
    result["system_version_notification_received"] = True
    result["after_system_query"] = await stream.execute(STATE)
    result["before_disconnect"] = await stream.execute(STATE)


async def live_preview_capture(client, stream, args, report):
    """One named, bounded experiment; diagnostic completion never passes the camera gate."""
    preview_only = getattr(args, "preview_only", False)
    report["experiment"] = (
        "preview-only-control" if preview_only else "live-preview-default-framebuffer"
    )
    report["protocol_provenance"] = (
        "native screen.show_aivision; no system/file operations"
        if preview_only
        else "vex-cdc ScreenCapturePacket + Read/Cbuf/Sys/screen"
    )
    report["screen_capture_protocol"] = {}
    report["before_capture"] = await stream.execute(STATE)
    started = time.monotonic()
    try:
        await stream.start_preview()
        report["preview_ready"] = True
        print("Preview program ready; it has a 60-second upper bound.", flush=True)
        if preview_only:
            # No system notifications or file operations in this control experiment.
            await asyncio.sleep(20)
        else:
            async with asyncio.timeout(40):
                await check_screen_capture(
                    client,
                    inspect_buffer=True,
                    output_file=args.framebuffer_output,
                    result=report["screen_capture_protocol"],
                    pipeline=getattr(args, "read_pipeline", 1),
                    keep_system_notifications=True,
                )
            if not report["screen_capture_protocol"].get("buffer_read_complete"):
                raise RuntimeError("Default LCD framebuffer capture did not complete.")
        stream.collect_pending()
        report["preview_program_active_before_cleanup"] = b"\x04" not in stream.buffer
        if preview_only:
            report["preview_control_seconds"] = round(time.monotonic() - started, 3)
        else:
            report["preview_program_active_after_transfer"] = report[
                "preview_program_active_before_cleanup"
            ]
            report["capture_seconds"] = round(time.monotonic() - started, 3)
            report["capture_within_30_seconds"] = report["capture_seconds"] <= 30
        output = args.framebuffer_output
        if output and report["screen_capture_protocol"].get("buffer_read_complete"):
            report["frame_sha256"] = hashlib.sha256(output.read_bytes()).hexdigest()
    finally:
        report["gatt_connected_after_capture"] = client.is_connected
        try:
            if not client.is_connected:
                raise RuntimeError(
                    "BLE disconnected; check whether the robot screen remains on."
                )
            async with asyncio.timeout(15):
                # Interrupt only AFTER capture. sync also consumes the completed job's
                # stderr/prompt, so they cannot contaminate the next JSON response.
                if not await stream.sync():
                    raise RuntimeError(
                        "Could not resynchronize REPL after live preview capture."
                    )
                await stream.execute("robot.screen.hide_aivision()\nprint('{}')\n")
                report["preview_hidden"] = True
                report["after_capture"] = await stream.execute(STATE)
                report["console_recovered"] = True
        except (
            BleakError,
            OSError,
            RuntimeError,
            ValueError,
            asyncio.CancelledError,
        ) as error:
            report["console_recovered"] = False
            report["preview_cleanup_error"] = (
                str(error) if isinstance(error, RuntimeError) else type(error).__name__
            )


async def lcd_only_capture(client, args, report, keep_system_notifications=False):
    """Capture native camera or LCD pixels; this helper never enters REPL."""
    navigation = getattr(args, "lcd_nav", None)
    automatic = getattr(args, "select_ai_vision", False)
    native = getattr(args, "native_camera", False)
    layer = 8 if native else getattr(args, "capture_layer", None)
    if (automatic or layer is not None) and report.get("device_info") != {
        "model": "AIM",
        "hardware": "REV1",
        "firmware": "1.0.0.b0",
    }:
        raise RuntimeError(
            "Automatic menus and camera-layer diagnostics are calibrated only for AIM REV1 / BLE firmware 1.0.0.b0."
        )
    report["experiment"] = (
        "native-camera-jpeg"
        if native
        else (
            "automatic-ai-vision-selection"
            if automatic
            else "aim-lcd-navigation" if navigation else "current-lcd-system-only"
        )
    )
    report["python_console_touched"] = False
    report["display_mode_changed"] = (
        "navigation requested; inspect resulting image"
        if navigation or automatic
        else False
    )
    report["screen_capture_protocol"] = {}
    report["lcd_status"] = {}
    capture_clock = {}
    started = time.monotonic()
    async with asyncio.timeout(350 if automatic else 60):
        await check_screen_capture(
            client,
            inspect_buffer=True,
            output_file=args.framebuffer_output,
            result=report["screen_capture_protocol"],
            pipeline=getattr(args, "read_pipeline", 1),
            layer=layer,
            native_camera=native,
            keep_system_notifications=keep_system_notifications,
            capture_clock=capture_clock,
            navigation=navigation,
            status_result=report["lcd_status"],
            selection_result=(
                report.setdefault("ai_vision_selection", {}) if automatic else None
            ),
        )
    if not report["screen_capture_protocol"].get("buffer_read_complete"):
        raise RuntimeError("Current LCD framebuffer capture did not complete.")
    report["capture_seconds"] = round(time.monotonic() - started, 3)
    jpeg_output = getattr(args, "jpeg_output", None)
    if jpeg_output and native:
        report["jpeg_path"] = str(jpeg_output)
        report["jpeg_encoding_seconds"] = 0
        snapshot_elapsed = time.monotonic() - capture_clock["started"]
        report["snapshot_seconds"] = round(snapshot_elapsed, 3)
        report["snapshot_within_30_seconds"] = snapshot_elapsed <= 30
        report["jpeg_dimensions"] = report["screen_capture_protocol"]["jpeg_dimensions"]
        report["image_source"] = "native camera JPEG (CDC capture layer 8)"
    elif jpeg_output:
        encoding_started = time.monotonic()
        await encode_lcd_jpeg(args.framebuffer_output, jpeg_output)
        report["jpeg_encoding_seconds"] = round(time.monotonic() - encoding_started, 3)
        report["jpeg_path"] = str(jpeg_output)
        snapshot_elapsed = time.monotonic() - capture_clock["started"]
        report["snapshot_seconds"] = round(snapshot_elapsed, 3)
        report["snapshot_within_30_seconds"] = snapshot_elapsed <= 30
    report["frame_sha256"] = hashlib.sha256(
        args.framebuffer_output.read_bytes()
    ).hexdigest()
    report["gatt_connected_after_capture"] = client.is_connected
    report["camera_gate"] = (
        "unreviewed: native JPEG requires visual and changing-scene verification"
        if native
        else "unproven: current LCD pixels require visual inspection"
    )
    if automatic:
        report["display_mode_changed"] = any(
            "action" in event for event in report["ai_vision_selection"]["events"]
        )


async def encode_lcd_jpeg(raw_path, jpeg_path):
    """Decode the known native LCD format locally using the existing Windows helper."""
    if sys.platform != "win32":
        raise RuntimeError(
            "Integrated JPEG conversion currently requires Windows; retain raw output on other platforms."
        )
    if raw_path.stat().st_size != 240 * 240 * 2:
        raise RuntimeError(
            "Cannot encode an unknown framebuffer layout as 240x240 RGB565."
        )
    helper = Path(__file__).with_name("convert-rgb565.ps1")
    if not helper.is_file():
        raise RuntimeError("The local RGB565 conversion helper is missing.")
    jpeg_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="vexaim-jpeg-", dir=jpeg_path.parent
    ) as directory:
        staged = Path(directory) / "frame.jpg"
        # Local path arguments only: no shell, command string or image service.
        process = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(helper),
            "-InputPath",
            str(raw_path.resolve()),
            "-OutputPath",
            str(staged.resolve()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(process.communicate(), 10)
        except BaseException:
            if process.returncode is None:
                process.kill()
            await process.wait()
            raise
        if process.returncode != 0:
            raise RuntimeError(
                "Local RGB565-to-JPEG conversion failed; raw framebuffer retained."
            )
        if not staged.is_file() or staged.stat().st_size < 4:
            raise RuntimeError("JPEG conversion did not create a complete file.")
        with staged.open("rb") as encoded:
            if encoded.read(2) != b"\xff\xd8":
                raise RuntimeError("JPEG converter output has an invalid header.")
            encoded.seek(-2, 2)
            if encoded.read(2) != b"\xff\xd9":
                raise RuntimeError("JPEG converter output is incomplete.")
        staged.replace(jpeg_path)


def record_connection_interval(client, report, key):
    """Request acceptance is not negotiation; record the actual WinRT interval."""
    if sys.platform == "win32" and client.is_connected:
        try:
            report[key] = (
                client._backend._requester.get_connection_parameters().connection_interval
                * 1.25
            )
        except (AttributeError, OSError, RuntimeError) as error:
            report[key + "_error"] = type(error).__name__


AIM_NAVIGATION = {"center": 0x51, "back": 0x52, "left": 0x53, "right": 0x54}


def jpeg_dimensions(data):
    """Validate JPEG framing and read its SOF dimensions without changing pixels."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise RuntimeError("Native JPEG payload is incomplete; no image was saved.")
    cursor = 2
    while cursor + 4 <= len(data):
        if data[cursor] != 0xFF:
            break
        while cursor < len(data) and data[cursor] == 0xFF:
            cursor += 1
        if cursor >= len(data):
            break
        marker = data[cursor]
        cursor += 1
        if marker in (0xD9, 0xDA):
            break
        if cursor + 2 > len(data):
            break
        length = int.from_bytes(data[cursor : cursor + 2], "big")
        if length < 2 or cursor + length > len(data):
            break
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if length < 8:
                break
            height, width = struct.unpack_from(">HH", data, cursor + 3)
            if not (0 < width <= 4096 and 0 < height <= 4096):
                break
            return [width, height]
        cursor += length
    raise RuntimeError("Native JPEG has no valid frame dimensions; no image was saved.")


async def native_camera_recovery_control(client, args, report):
    """Read stationary Python state around native capture, retaining both subscriptions."""
    if report.get("device_info") != {
        "model": "AIM",
        "hardware": "REV1",
        "firmware": "1.0.0.b0",
    }:
        raise RuntimeError(
            "Native camera recovery is calibrated only for AIM REV1 / BLE firmware 1.0.0.b0."
        )
    stream = UserStream(client)
    report["python_console_touched"] = True
    report["console_recovered"] = False
    await client.start_notify(USER_TX, stream.notification)
    try:
        report["raw_repl_ready"] = await stream.sync()
        if not report["raw_repl_ready"]:
            raise RuntimeError("Native-camera control could not initialize Python.")
        initialize = (
            "from vex import *\nfrom vex_globals import *\nimport json\nrobot=Robot()\n"
            + STATE
        )
        report["before_capture"] = await stream.execute(initialize)
        if not report["before_capture"].get("stopped"):
            raise RuntimeError(
                "Robot reports movement; stationary camera control stopped."
            )
        await lcd_only_capture(client, args, report, keep_system_notifications=True)
        report["after_capture"] = await stream.execute(STATE)
        report["console_recovered"] = True
    finally:
        report["python_console_touched"] = True
        if client.is_connected:
            try:
                if report.get("raw_repl_ready"):
                    await stream.write(b"\x02")
                await asyncio.wait_for(client.stop_notify(USER_TX), 3)
                if report.get("screen_capture_protocol", {}).get(
                    "system_notifications_retained"
                ):
                    await asyncio.wait_for(client.stop_notify(SYSTEM_TX), 3)
            except (BleakError, OSError, RuntimeError) as error:
                report["cleanup_error"] = type(error).__name__


async def aim_lcd_status(exchange):
    """Read CDC SYS_STATUS, matching official vexcom _v5_SystemStatus layout."""
    head = bytes.fromhex("c936b847562000")
    reply = await exchange(head + binascii.crc_hqx(head, 0).to_bytes(2, "big"), 0x56)
    if reply is None:
        raise TimeoutError("AIM screen-status query did not reply.")
    frame, offset = reply
    if (
        len(frame) != 15
        or offset != 4
        or frame[:4] != bytes.fromhex("aa55560b")
        or frame[offset : offset + 2] != b"\x20\x76"
        or binascii.crc_hqx(frame[:-2], 0) != int.from_bytes(frame[-2:], "big")
    ):
        raise RuntimeError(
            "AIM screen-status reply has an unknown layout or invalid CRC."
        )
    return {"screen_id": frame[9], "flags_hex": frame[6:9].hex()}


def cdc_command(opcode, payload=b""):
    head = bytes.fromhex("c936b84756") + bytes([opcode, len(payload)]) + payload
    return head + binascii.crc_hqx(head, 0).to_bytes(2, "big")


def checked_cdc_body(reply, opcode):
    if reply is None:
        raise TimeoutError("Menu framebuffer request did not reply.")
    frame, offset = reply
    if (
        len(frame) < offset + 3
        or frame[offset] != opcode
        or binascii.crc_hqx(frame[:-2], 0) != int.from_bytes(frame[-2:], "big")
    ):
        raise RuntimeError(
            "Menu framebuffer reply has an invalid opcode, length or CRC."
        )
    return frame[offset:-2]


# Only menu icon fingerprints, derived from verified LCD captures, are stored.
# No camera image, font installation, OCR service, or extra package is required.
MENU_ICONS = {
    "d1a9ab9bb74976b0b1b8cb6b528b90507d797378fee6e2fdd37ab533c3e860eb": "Dashboard",
    "42263e324130db02cf1b9f66697adffa81b7ca0fcc9ad645840bf5bc4559231a": "AI Vision",
}
MENU_BAND_Y, MENU_BAND_HEIGHT = 88, 16


def menu_icon_fingerprint(band):
    if len(band) != 240 * MENU_BAND_HEIGHT * 2:
        raise ValueError("Menu icon band has the wrong size.")
    icon = b"".join(
        band[(y * 240 + 80) * 2 : (y * 240 + 160) * 2] for y in range(MENU_BAND_HEIGHT)
    )
    return hashlib.sha256(icon).hexdigest()


async def read_menu_icon(exchange):
    """Read sequentially up to the icon rows; AIM Cbuf rejects random seeks."""
    body = checked_cdc_body(await exchange(cdc_command(0x28), 0x56), 0x28)
    if body != b"\x28\x76":
        raise RuntimeError("Menu screen capture was not acknowledged.")
    payload = bytes([2, 2, 15, 0]) + struct.pack("<III", 512 * 272 * 4, 0, 0)
    payload += b"ini\x73" + bytes(8) + b"screen" + bytes(18)
    body = checked_cdc_body(await exchange(cdc_command(0x11, payload), 0x56), 0x11)
    if len(body) < 8 or body[:2] != b"\x11\x76":
        raise RuntimeError("Read-only menu framebuffer initialization failed.")
    window, size = struct.unpack_from("<HI", body, 2)
    if size != 240 * 240 * 2 or window < 28:
        raise RuntimeError(
            "Automatic menu recognition requires the calibrated 240x240 RGB565 framebuffer."
        )
    # AIM returned a valid-CRC error (-41) when seeking directly to the icon.
    # Its Cbuf reader requires sequential addresses, even after the initial read.
    seed = checked_cdc_body(
        await exchange(cdc_command(0x14, struct.pack("<IH", 0, 128)), 0x56), 0x14
    )
    if len(seed) != 133 or struct.unpack_from("<I", seed, 1)[0] != 0:
        raise RuntimeError(
            "Menu framebuffer initial read failed; no navigation was retried."
        )
    start = MENU_BAND_Y * 240 * 2
    length = MENU_BAND_HEIGHT * 240 * 2
    band = bytearray()
    chunk_size = min(216, (window - 15) // 4 * 4)
    address = 128
    while address < start + length:
        requested = min(chunk_size, start + length - address)
        body = checked_cdc_body(
            await exchange(
                cdc_command(0x14, struct.pack("<IH", address, requested)), 0x56
            ),
            0x14,
        )
        if (
            len(body) != requested + 5
            or struct.unpack_from("<I", body, 1)[0] != address
        ):
            echoed = struct.unpack_from("<I", body, 1)[0] if len(body) >= 5 else None
            raise RuntimeError(
                f"Menu framebuffer read mismatch: requested address {address}, bytes {requested}; "
                f"reply address {echoed}, body length {len(body)}. No navigation was retried."
            )
        if address + requested > start:
            band.extend(body[5 + max(0, start - address) :])
        address += requested
    return menu_icon_fingerprint(band)


async def select_ai_vision(exchange, result):
    """Locate live menu icons; never replay remembered press counts."""
    started = time.monotonic()
    result.update(events=[], complete=False, reboot_requested=False)
    events = result["events"]

    def completed(already_active=False):
        result.update(
            complete=True, camera_pixels_verified=False, already_active=already_active
        )
        result["selection_seconds"] = round(time.monotonic() - started, 3)

    async def action(name):
        event = {"action": name}
        events.append(event)
        await aim_lcd_navigation(exchange, name, event)
        await asyncio.sleep(0.35)

    async def select_verified(label, signature, expected_page):
        # A fresh second capture must still show exactly the same target. Only
        # Dashboard and AI Vision can authorize center; all other labels cannot.
        if (
            (await aim_lcd_status(exchange))["screen_id"] != expected_page
            or await read_menu_icon(exchange) != signature
            or (await aim_lcd_status(exchange))["screen_id"] != expected_page
        ):
            raise RuntimeError(
                "Menu changed before selection; no center press was sent."
            )
        events.append({"confirmed_label": label})
        await action("center")

    async def find_and_select(target, expected_page):
        seen = set()
        for _tile in range(10):
            status = await aim_lcd_status(exchange)
            events.append({"status": status})
            if expected_page == 32 and status["screen_id"] == 34:
                return  # The retained Dashboard state already opened its camera.
            if status["screen_id"] != expected_page:
                raise RuntimeError(
                    "Unexpected menu page; stopping without selecting an unknown tile."
                )
            signature = await read_menu_icon(exchange)
            label = MENU_ICONS.get(signature)
            events.append({"label": label, "icon_fingerprint": signature})
            print("LCD menu:", label or "unrecognized; selection disabled", flush=True)
            if label == target:
                await select_verified(label, signature, expected_page)
                return
            if signature in seen:
                break
            seen.add(signature)
            await action("right")
        raise RuntimeError(
            f"Could not locate {target} within the menu search limit; no unknown tile was selected."
        )

    async with asyncio.timeout(300):
        # 32 is the Dashboard carousel, not the camera (34).
        # It must never authorize success by itself. Back returns to the home
        # page without activating whatever detail/test a student last opened.
        for _depth in range(5):
            status = await aim_lcd_status(exchange)
            events.append({"status": status})
            if status["screen_id"] == 34:
                completed(already_active=not any("action" in event for event in events))
                return
            if status["screen_id"] == 0:
                break
            if _depth == 4:
                raise RuntimeError(
                    "Could not return to the home menu with four Back actions."
                )
            await action("back")
        await find_and_select("Dashboard", 0)
        await find_and_select("AI Vision", 32)
        after = await aim_lcd_status(exchange)
        events.append({"status": after})
        if after["screen_id"] != 34:
            raise RuntimeError(
                "AI Vision selection did not reach camera screen 34; stopping."
            )
        completed()


async def aim_lcd_navigation(exchange, action, result):
    """Match official vexcom 1.0.2b2 --aim touch,[left|right|center|back]."""
    if action not in AIM_NAVIGATION:
        raise ValueError("Unknown AIM LCD navigation action.")
    head = bytes.fromhex("c936b847566501") + bytes([AIM_NAVIGATION[action]])
    packet = head + binascii.crc_hqx(head, 0).to_bytes(2, "big")
    result.update(
        action=action,
        protocol="AIM_TOUCH 0x65; official vexcom _aim_command_touch / _aim_TouchCommand",
    )
    reply = await exchange(packet, 0x56)
    if reply is None:
        raise TimeoutError("AIM navigation did not reply; the action is not retried.")
    frame, offset = reply
    crc_valid = binascii.crc_hqx(frame[:-2], 0) == int.from_bytes(frame[-2:], "big")
    result.update(reply_crc_valid=crc_valid, reply_payload_hex=frame[offset:-2].hex())
    if not crc_valid or frame[offset:-2] != b"\x65\x76":
        raise RuntimeError(
            "AIM navigation was not acknowledged; inspect the LCD before another action."
        )
    result["acknowledged"] = True


async def check_screen_capture(
    client,
    inspect_buffer=False,
    output_file=None,
    result=None,
    layer=None,
    pipeline=1,
    keep_system_notifications=False,
    navigation=None,
    status_result=None,
    selection_result=None,
    capture_clock=None,
    transfer_timeout=45,
    native_camera=False,
):
    """Test existing CDC capture acknowledgement; do not download a displayed PIN."""
    if native_camera and layer != 8:
        raise ValueError(
            "Native camera capture requires the source-defined JPEG layer 8."
        )
    queue = asyncio.Queue(maxsize=64)
    overflow = False
    result = {} if result is None else result
    pending = bytearray()

    def notification(_characteristic, value):
        nonlocal overflow
        try:
            queue.put_nowait(bytes(value))
        except asyncio.QueueFull:
            overflow = True

    async def receive(expected_command):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            if overflow or len(pending) > 8192:
                raise RuntimeError("System notification buffer overflow.")
            # A notification may contain several complete replies. Parse the
            # retained bytes before waiting for another event (not after it).
            while len(pending) >= 4:
                if pending[:2] != b"\xaa\x55":
                    del pending[0]
                    continue
                if pending[3] & 0x80:
                    if len(pending) < 5:
                        break
                    header, length = 5, ((pending[3] & 0x7F) << 8) | pending[4]
                else:
                    header, length = 4, pending[3]
                if len(pending) < header + length:
                    break
                frame = bytes(pending[: header + length])
                del pending[: header + length]
                if frame[2] == expected_command:
                    return frame, header
            try:
                pending.extend(
                    await asyncio.wait_for(
                        queue.get(), max(0, deadline - time.monotonic())
                    )
                )
            except TimeoutError:
                return None
        return None

    async def exchange(packet, expected_command):
        await asyncio.wait_for(
            client.write_gatt_char(SYSTEM_RX, packet, response=False), 5
        )
        return await receive(expected_command)

    await client.start_notify(SYSTEM_TX, notification)
    try:
        version = await exchange(bytes.fromhex("c936b847a4"), 0xA4)
        result["system_version_replied"] = version is not None
        if status_result is not None:
            status_result["before"] = await aim_lcd_status(exchange)
        if selection_result is not None:
            await select_ai_vision(exchange, selection_result)
            if status_result is not None:
                status_result["after"] = await aim_lcd_status(exchange)
        if navigation:
            result["aim_navigation"] = {}
            await aim_lcd_navigation(exchange, navigation, result["aim_navigation"])
            await asyncio.sleep(0.35)
            if status_result is not None:
                status_result["after"] = await aim_lcd_status(exchange)
        if layer is not None and status_result is not None:
            if layer not in (1, 8):
                raise RuntimeError(
                    "LCD-only diagnostics support only the layer-1 repeat and source-defined layer-8 JPEG capability check."
                )
            if (
                not native_camera
                and (await aim_lcd_status(exchange))["screen_id"] != 34
            ):
                raise RuntimeError(
                    "The alternate-layer control requires the verified AI Vision camera screen; no layer request was sent."
                )
        result["capture_layer"] = layer
        capture_started = time.monotonic()
        if capture_clock is not None:
            capture_clock["started"] = capture_started
        # Exactly ScreenCapturePacket { layer: None } from the vendored vex-cdc.
        header = bytes.fromhex("c936b8475628") + (
            b"\x00" if layer is None else bytes([1, layer])
        )
        packet = header + binascii.crc_hqx(header, 0).to_bytes(2, "big")
        capture = await exchange(packet, 0x56)
        result["screen_capture_replied"] = capture is not None
        if capture is not None:
            frame, offset = capture
            result["reply_crc_valid"] = binascii.crc_hqx(
                frame[:-2], 0
            ) == int.from_bytes(frame[-2:], "big")
            result["reply_opcode"] = hex(frame[offset])
            result["acknowledgement"] = hex(frame[offset + 1])
            if (
                inspect_buffer
                and result["reply_crc_valid"]
                and frame[offset : offset + 2] == b"\x28\x76"
            ):

                def command(opcode, payload):
                    head = (
                        bytes.fromhex("c936b84756")
                        + bytes([opcode, len(payload)])
                        + payload
                    )
                    return head + binascii.crc_hqx(head, 0).to_bytes(2, "big")

                # The existing download_file Read/Cbuf/Sys/screen request; no file writes.
                payload = bytes([2, 2, 15, 0]) + struct.pack(
                    "<III", 512 * 272 * 4, 0, 0
                )
                payload += b"ini\x73" + bytes(8) + b"screen" + bytes(18)
                initialized = await exchange(command(0x11, payload), 0x56)
                if initialized is not None:
                    init_frame, init_offset = initialized
                    valid = binascii.crc_hqx(init_frame[:-2], 0) == int.from_bytes(
                        init_frame[-2:], "big"
                    )
                    result["buffer_init_crc_valid"] = valid
                    result["buffer_init_ack"] = hex(init_frame[init_offset + 1])
                    if (
                        valid
                        and init_frame[init_offset : init_offset + 2] == b"\x11\x76"
                    ):
                        try:
                            window, size = struct.unpack_from(
                                "<HI", init_frame, init_offset + 2
                            )
                            result.update(buffer_window=window, buffer_size=size)
                            if size == 0:
                                raise RuntimeError(
                                    "Selected capture layer has no framebuffer."
                                )
                            if size > 1024 * 1024:
                                raise RuntimeError(
                                    "Capture buffer size outside the 1 MiB limit."
                                )
                            first = await exchange(
                                command(0x14, struct.pack("<IH", 0, 128)), 0x56
                            )
                            if first is not None:
                                read_frame, read_offset = first
                                result["buffer_read_crc_valid"] = binascii.crc_hqx(
                                    read_frame[:-2], 0
                                ) == int.from_bytes(read_frame[-2:], "big")
                                body = read_frame[read_offset + 1 : -2]
                                if len(body) == 1:
                                    result["buffer_read_nack"] = hex(body[0])
                                elif len(body) >= 4:
                                    result["buffer_read_address"] = struct.unpack_from(
                                        "<I", body
                                    )[0]
                                    data = body[4:]
                                    result.update(
                                        first_read_bytes=len(data),
                                        jpeg_header=data.startswith(b"\xff\xd8"),
                                        bmp_header=data.startswith(b"BM"),
                                    )
                                    if layer == 8 and (
                                        not result["buffer_read_crc_valid"]
                                        or result["buffer_read_address"] != 0
                                        or read_frame[read_offset] != 0x14
                                    ):
                                        raise RuntimeError(
                                            "JPEG capability header failed CRC/address validation."
                                        )
                                    if layer == 8 and not data.startswith(b"\xff\xd8"):
                                        raise RuntimeError(
                                            "Source-defined layer 8 did not return a JPEG header; stopping after the first block without guessing another format."
                                        )
                                    if output_file is not None:
                                        if (
                                            not result["buffer_read_crc_valid"]
                                            or result["buffer_read_address"] != 0
                                            or read_frame[read_offset] != 0x14
                                        ):
                                            raise RuntimeError(
                                                "First framebuffer block failed CRC/address validation."
                                            )
                                        received = bytearray(data[:size])
                                        started = time.monotonic()
                                        result["bytes_received"] = len(received)
                                        chunk_size = min(
                                            216, max(0, window - 14) // 4 * 4
                                        )
                                        if chunk_size == 0:
                                            raise RuntimeError(
                                                "Framebuffer receive window is too small."
                                            )
                                        while len(received) < size:
                                            result["transfer_deadline_seconds"] = (
                                                transfer_timeout
                                            )
                                            if (
                                                time.monotonic() - started
                                                > transfer_timeout
                                            ):
                                                raise TimeoutError(
                                                    f"Framebuffer transfer exceeded {transfer_timeout} seconds."
                                                )
                                            # Default to the hardware-tested sequential read.
                                            # An optional bounded pipeline is experimental.
                                            requests = []
                                            cursor = len(received)
                                            for _ in range(
                                                max(1, min(4, pipeline, window // 15))
                                            ):
                                                if cursor >= size:
                                                    break
                                                requested = min(
                                                    chunk_size,
                                                    (size - cursor + 3) // 4 * 4,
                                                )
                                                requests.append(
                                                    (
                                                        cursor,
                                                        requested,
                                                        time.monotonic(),
                                                    )
                                                )
                                                await asyncio.wait_for(
                                                    client.write_gatt_char(
                                                        SYSTEM_RX,
                                                        command(
                                                            0x14,
                                                            struct.pack(
                                                                "<IH", cursor, requested
                                                            ),
                                                        ),
                                                        response=False,
                                                    ),
                                                    5,
                                                )
                                                cursor += requested
                                                if pipeline > 1:
                                                    await asyncio.sleep(0.005)
                                            for (
                                                address,
                                                requested,
                                                request_started,
                                            ) in requests:
                                                read = await receive(0x56)
                                                if read is None:
                                                    raise TimeoutError(
                                                        "Framebuffer read did not reply."
                                                    )
                                                packet, start = read
                                                if binascii.crc_hqx(
                                                    packet[:-2], 0
                                                ) != int.from_bytes(packet[-2:], "big"):
                                                    raise RuntimeError(
                                                        "Framebuffer packet CRC failed."
                                                    )
                                                chunk = packet[start + 1 : -2]
                                                if (
                                                    packet[start] != 0x14
                                                    or len(chunk) < 5
                                                    or struct.unpack_from("<I", chunk)[
                                                        0
                                                    ]
                                                    != address
                                                ):
                                                    raise RuntimeError(
                                                        "Framebuffer read returned the wrong address or a NACK."
                                                    )
                                                if len(chunk) - 4 != requested:
                                                    raise RuntimeError(
                                                        "Framebuffer read returned an incomplete chunk."
                                                    )
                                                if pipeline == 1:
                                                    timing = result.setdefault(
                                                        "read_round_trip_ms",
                                                        {
                                                            "count": 0,
                                                            "sum": 0,
                                                            "min": None,
                                                            "max": 0,
                                                        },
                                                    )
                                                    elapsed_ms = (
                                                        time.monotonic()
                                                        - request_started
                                                    ) * 1000
                                                    timing["count"] += 1
                                                    timing["sum"] += elapsed_ms
                                                    timing["min"] = (
                                                        elapsed_ms
                                                        if timing["min"] is None
                                                        else min(
                                                            timing["min"], elapsed_ms
                                                        )
                                                    )
                                                    timing["max"] = max(
                                                        timing["max"], elapsed_ms
                                                    )
                                                received.extend(
                                                    chunk[
                                                        4 : 4
                                                        + min(
                                                            requested,
                                                            size - len(received),
                                                        )
                                                    ]
                                                )
                                                result.update(
                                                    bytes_received=len(received),
                                                    transfer_seconds=round(
                                                        time.monotonic() - started, 3
                                                    ),
                                                )
                                        if layer == 8:
                                            result["jpeg_dimensions"] = jpeg_dimensions(
                                                received
                                            )
                                        output_file.parent.mkdir(
                                            parents=True, exist_ok=True
                                        )
                                        with tempfile.TemporaryDirectory(
                                            prefix="vexaim-frame-",
                                            dir=output_file.parent,
                                        ) as directory:
                                            staged = Path(directory) / "frame"
                                            staged.write_bytes(received)
                                            staged.replace(output_file)
                                        result["capture_to_raw_seconds"] = round(
                                            time.monotonic() - capture_started, 3
                                        )
                                        timing = result.get("read_round_trip_ms")
                                        if timing:
                                            timing["mean"] = (
                                                timing.pop("sum") / timing["count"]
                                            )
                                            for key in ("min", "max", "mean"):
                                                timing[key] = round(timing[key], 3)
                                        result.update(
                                            framebuffer_path=str(output_file),
                                            bytes_received=len(received),
                                            transfer_seconds=round(
                                                time.monotonic() - started, 3
                                            ),
                                        )
                        finally:
                            # Match the library's read-only download_file: it does not
                            # send FILE_EXIT, whose actions belong to program uploads.
                            result["buffer_read_complete"] = result.get(
                                "buffer_size", 0
                            ) > 0 and result.get("bytes_received", 0) == result.get(
                                "buffer_size", -1
                            )
        if native_camera and status_result is not None:
            status_result["after_capture"] = await aim_lcd_status(exchange)
        return result
    finally:
        timing = result.get("read_round_trip_ms")
        if timing and "sum" in timing:
            timing["mean"] = timing.pop("sum") / timing["count"]
            for key in ("min", "max", "mean"):
                timing[key] = round(timing[key], 3)
        if keep_system_notifications:
            # On the tested Windows/Bleak/AIM combination, disabling TXData
            # notifications silenced TXUser too. Retain both until all Python
            # work, including preview cleanup, has finished. Re-registering
            # TXUser alone did not recover this condition in the hardware control.
            result["system_notifications_retained"] = True
        else:
            await asyncio.wait_for(client.stop_notify(SYSTEM_TX), 3)


async def probe(args, report):
    print("Stage: checking USB absence and scanning for the selected AIM.", flush=True)
    report["robot_usb_present"] = usb_present()
    if report["robot_usb_present"] is True:
        raise RuntimeError(
            "Unplug the robot USB cable before this wireless-only probe."
        )
    discoveries = await BleakScanner.discover(timeout=8, return_adv=True)
    matches = [
        (device, adv)
        for device, adv in discoveries.values()
        if (adv.local_name or device.name) == args.name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected exactly one robot named {args.name}; found {len(matches)}."
        )
    device, adv = matches[0]
    report.update(
        name=args.name, device_id=device.address, advertised_services=adv.service_uuids
    )
    async with BleakClient(device, timeout=15, pair=False) as client:
        print(
            "Stage: GATT connected; checking identity and authentication.", flush=True
        )
        report["gatt_connected"] = client.is_connected
        report["mtu"] = client.mtu_size
        # Windows 11 supports a temporary high-throughput preset for bulk transfers.
        # The device is disposed on exit, restoring the normal connection policy.
        connection_request = None
        if sys.platform == "win32" and getattr(args, "framebuffer_output", None):
            try:
                from winrt.windows.devices.bluetooth import (
                    BluetoothLEPreferredConnectionParameters,
                )

                radio_device = client._backend._requester
                before = radio_device.get_connection_parameters()
                report["initial_connection_interval_ms"] = (
                    before.connection_interval * 1.25
                )
                connection_request = (
                    radio_device.request_preferred_connection_parameters(
                        BluetoothLEPreferredConnectionParameters.throughput_optimized
                    )
                )
                report["throughput_request_status"] = str(connection_request.status)
            except (AttributeError, OSError, ImportError, RuntimeError) as error:
                report["throughput_request_error"] = type(error).__name__
        report["device_info"] = {}
        for field, short in [
            ("model", "2a24"),
            ("firmware", "2a26"),
            ("hardware", "2a27"),
        ]:
            raw = await client.read_gatt_char(
                f"0000{short}-0000-1000-8000-00805f9b34fb"
            )
            report["device_info"][field] = bytes(raw).decode("utf-8").rstrip("\0")
        if report["device_info"]["model"] != "AIM":
            raise RuntimeError("Selected peripheral does not identify as a VEX AIM.")
        requester = getattr(client._backend, "_requester", None)
        info = getattr(requester, "device_information", None)
        report["os_bonded"] = getattr(getattr(info, "pairing", None), "is_paired", None)
        report["characteristics"] = []
        for service in client.services:
            for characteristic in service.characteristics:
                labels = []
                for descriptor in characteristic.descriptors:
                    if descriptor.uuid.startswith("00002901"):
                        labels.append(
                            bytes(
                                await client.read_gatt_descriptor(descriptor.handle)
                            ).decode("utf-8", "replace")
                        )
                report["characteristics"].append(
                    {
                        "uuid": characteristic.uuid,
                        "properties": characteristic.properties,
                        "labels": labels,
                    }
                )

        auth = bytes(await client.read_gatt_char(PAIRING))
        if len(auth) != 4:
            raise RuntimeError(
                "Malformed VEX authentication response (expected four bytes)."
            )
        if auth != UNPAIRED and any(digit > 9 for digit in auth):
            raise RuntimeError(
                "Unrecognized VEX authentication response; no command was sent."
            )
        report["initial_vex_authenticated"] = auth != UNPAIRED
        # Do not log authentication values: a successful response contains the PIN.
        auth = None
        if not report["initial_vex_authenticated"]:
            keyring.set_keyring(native_credential_store())
            code = keyring.get_password(VAULT_SERVICE, device.address)
            if args.pair:
                if not sys.stdin.isatty():
                    raise RuntimeError(
                        "Pairing requires a local interactive terminal with masked input."
                    )
                await client.write_gatt_char(PAIRING, bytes([255] * 4), response=True)
                print(
                    f"Look at {args.name}'s screen. Enter the four-digit code here, not in chat.",
                    flush=True,
                )
                code = await asyncio.wait_for(
                    asyncio.to_thread(getpass.getpass, "Robot code (hidden): "), 120
                )
            if code is None:
                raise RuntimeError(
                    "VEX authentication required. Run this probe locally with --pair."
                )
            pin = decode_pin(code)
            await client.write_gatt_char(PAIRING, pin, response=True)
            await asyncio.sleep(0.2)
            accepted = bytes(await client.read_gatt_char(PAIRING)) == pin
            if not accepted:
                raise RuntimeError("Robot rejected the code; no credential was saved.")
            keyring.set_password(VAULT_SERVICE, device.address, code)
            code, pin = None, None
        report["vex_authenticated"] = True
        if getattr(args, "lcd_only", False):
            if getattr(args, "python_recovery_check", False):
                stage = "checking stationary Python state before and after native camera capture"
            elif getattr(args, "native_camera", False):
                stage = "capturing native camera JPEG without Python or LCD navigation"
            else:
                stage = "capturing LCD without Python; navigation requires an explicit option"
            print(f"Stage: authenticated; {stage}.", flush=True)
            record_connection_interval(
                client, report, "connection_interval_ms_before_operation"
            )
            try:
                if getattr(args, "python_recovery_check", False):
                    await native_camera_recovery_control(client, args, report)
                else:
                    await lcd_only_capture(client, args, report)
            finally:
                record_connection_interval(
                    client, report, "connection_interval_ms_after_operation"
                )
            return
        print("Stage: VEX authenticated; checking the Python console.", flush=True)
        stream = UserStream(client)
        await client.start_notify(USER_TX, stream.notification)
        try:
            report["raw_repl_ready"] = await stream.sync()
            report["user_notification_bytes"] = stream.received_bytes
            if not report["raw_repl_ready"]:
                raise RuntimeError(
                    "Authenticated GATT connection succeeded, but no raw-REPL prompt arrived over TXUser."
                )
            report["python_capabilities"] = await stream.execute(CAPABILITIES)
            report["control_round_trips"] = [
                await stream.execute(STATE) for _ in range(3)
            ]
            print(
                "Stage: three stationary Python control round trips passed.", flush=True
            )
            if getattr(args, "native_image_check", False):
                report["native_image_capabilities"] = await stream.execute(
                    NATIVE_IMAGE_CAPABILITIES
                )
            if getattr(args, "system_channel_check", False):
                await system_channel_control(client, stream, report)
            if getattr(args, "live_preview", False) or getattr(
                args, "preview_only", False
            ):
                await live_preview_capture(client, stream, args, report)
            elif (
                getattr(args, "camera_check", False)
                or getattr(args, "framebuffer_check", False)
                or getattr(args, "framebuffer_output", None)
            ):
                report["camera_capabilities"] = await stream.execute(
                    CAMERA_CAPABILITIES
                )
                inspect_buffer = getattr(args, "framebuffer_check", False) or bool(
                    getattr(args, "framebuffer_output", None)
                )
                if inspect_buffer:
                    await stream.execute(
                        "robot.screen.show_aivision()\nwait(300,MSEC)\nprint('{}')\n"
                    )
                try:
                    report["screen_capture_protocol"] = {}
                    await check_screen_capture(
                        client,
                        inspect_buffer=inspect_buffer,
                        output_file=getattr(args, "framebuffer_output", None),
                        result=report["screen_capture_protocol"],
                        layer=getattr(args, "capture_layer", None),
                        pipeline=getattr(args, "read_pipeline", 1),
                        keep_system_notifications=True,
                    )
                finally:
                    if inspect_buffer and client.is_connected:
                        try:
                            if not await stream.sync():
                                raise RuntimeError(
                                    "Could not resynchronize REPL after CDC transfer."
                                )
                            await stream.execute(
                                "robot.screen.hide_aivision()\nprint('{}')\n"
                            )
                            report["preview_hidden"] = True
                        except (BleakError, OSError, RuntimeError, ValueError) as error:
                            report["preview_cleanup_error"] = (
                                str(error)
                                if isinstance(error, RuntimeError)
                                else type(error).__name__
                            )
            report["camera_gate"] = (
                "unproven: capability discovery is not image capture"
            )
        finally:
            if client.is_connected:
                try:
                    if report.get("raw_repl_ready"):
                        await stream.write(b"\x02")
                    await asyncio.wait_for(client.stop_notify(USER_TX), 3)
                    if report.get("screen_capture_protocol", {}).get(
                        "system_notifications_retained"
                    ) or report.get("system_channel_control", {}).get(
                        "system_notifications_retained"
                    ):
                        await asyncio.wait_for(client.stop_notify(SYSTEM_TX), 3)
                except (BleakError, OSError, RuntimeError) as error:
                    report["cleanup_error"] = type(error).__name__


def main():
    # getpass must never fall back to echoed input when no real console is available.
    warnings.simplefilter("error", getpass.GetPassWarning)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--pair", action="store_true")
    parser.add_argument(
        "--native-camera",
        action="store_true",
        help="Instructor native camera snapshot: save the robot's JPEG over BLE without entering Python or navigating the LCD; requires --jpeg-output and an existing credential",
    )
    parser.add_argument(
        "--python-recovery-check",
        action="store_true",
        help="Instructor control: read stationary Python state before and after --native-camera with both notification streams retained",
    )
    parser.add_argument(
        "--select-ai-vision",
        action="store_true",
        help="Instructor-only: recognize calibrated Dashboard/AI Vision icons over BLE and select the camera without rebooting; requires --lcd-only",
    )
    parser.add_argument(
        "--lcd-nav",
        choices=tuple(AIM_NAVIGATION),
        help="Instructor-only: one AIM LCD navigation action before --lcd-only capture; confirm the current screen first, never select drive/kicker tests",
    )
    parser.add_argument(
        "--lcd-only",
        action="store_true",
        help="Capture the current LCD without entering Python or showing/hiding previews; requires --framebuffer-output and an existing credential",
    )
    parser.add_argument(
        "--system-channel-check",
        action="store_true",
        help="Spike control: test Python around a system-version query; retain both subscriptions until disconnect; no framebuffer operations",
    )
    parser.add_argument(
        "--native-image-check",
        action="store_true",
        help="Inspect native image/socket module availability; no network connection or unknown API call",
    )
    parser.add_argument(
        "--preview-only",
        action="store_true",
        help="Spike control: show a bounded preview for 20 seconds, then check recovery; no framebuffer operations",
    )
    parser.add_argument(
        "--live-preview",
        action="store_true",
        help="Spike: capture the default LCD buffer while a bounded 60-second preview program is still running; requires --framebuffer-output",
    )
    parser.add_argument(
        "--camera-check",
        action="store_true",
        help="Inspect image capabilities and the existing CDC screen-capture acknowledgement; no image is downloaded",
    )
    parser.add_argument(
        "--framebuffer-check",
        action="store_true",
        help="Request camera preview and inspect LCD-buffer metadata and the first 128 bytes; no image is saved",
    )
    parser.add_argument(
        "--framebuffer-output",
        type=Path,
        help="Save a complete framebuffer locally with CRC/address checks and a 45-second operational transfer deadline; camera content requires inspection",
    )
    parser.add_argument(
        "--jpeg-output",
        type=Path,
        help="Save unchanged native JPEG with --native-camera; alternatively decode the known 240x240 RGB565 LCD format on Windows with --lcd-only and --framebuffer-output",
    )
    parser.add_argument(
        "--capture-layer",
        type=int,
        choices=(0, 1, 2, 3, 8),
        help="Instructor capture control; LCD-only permits layer 1 or one source-defined layer-8 JPEG capability check, requiring camera mode",
    )
    parser.add_argument(
        "--read-pipeline",
        type=int,
        choices=range(1, 5),
        default=1,
        help="Outstanding read requests; 1 was hardware tested, larger values are experimental",
    )
    parser.add_argument(
        "--report", type=Path, default=Path("dist/ble-feasibility.json")
    )
    args = parser.parse_args()
    if args.python_recovery_check and not args.native_camera:
        parser.error("--python-recovery-check requires --native-camera")
    if args.native_camera:
        if (
            not args.jpeg_output
            or args.framebuffer_output
            or args.capture_layer is not None
            or args.select_ai_vision
            or args.lcd_nav
            or args.read_pipeline != 1
        ):
            parser.error(
                "--native-camera requires --jpeg-output, sequential reads, and no raw-output, layer or navigation options"
            )
        args.lcd_only = True
        # Native bytes are already JPEG; no second file or transcoder is needed.
        args.framebuffer_output = args.jpeg_output
    if args.capture_layer == 8 and not args.lcd_only:
        parser.error(
            "Layer 8 is restricted to the system-only JPEG capability check (--lcd-only)"
        )
    if args.jpeg_output and (not args.lcd_only or not args.framebuffer_output):
        parser.error("--jpeg-output requires --lcd-only and --framebuffer-output")
    if (
        args.jpeg_output
        and not args.native_camera
        and (sys.platform != "win32" or args.capture_layer is not None)
    ):
        parser.error(
            "--jpeg-output requires Windows and the known default LCD format (no --capture-layer)"
        )
    paths = [
        path.resolve()
        for path in (
            args.jpeg_output,
            None if args.native_camera else args.framebuffer_output,
            args.report,
        )
        if path is not None
    ]
    if len(set(paths)) != len(paths):
        parser.error("JPEG, raw framebuffer and JSON report paths must be different")
    if args.select_ai_vision and (not args.lcd_only or args.lcd_nav):
        parser.error(
            "--select-ai-vision requires --lcd-only and cannot be combined with --lcd-nav"
        )
    if args.select_ai_vision and args.read_pipeline != 1:
        parser.error("--select-ai-vision requires sequential reads (--read-pipeline 1)")
    if args.lcd_nav and not args.lcd_only:
        parser.error("--lcd-nav requires --lcd-only")
    if args.lcd_only and (
        not args.framebuffer_output
        or args.pair
        or args.live_preview
        or args.preview_only
        or args.system_channel_check
        or args.native_image_check
        or args.camera_check
        or args.framebuffer_check
        or args.capture_layer not in (None, 1, 8)
    ):
        parser.error(
            "--lcd-only requires --framebuffer-output and cannot be combined with pairing or Python/display experiments"
        )
    if args.preview_only and (
        args.live_preview
        or args.framebuffer_output
        or args.framebuffer_check
        or args.camera_check
        or args.capture_layer is not None
    ):
        parser.error(
            "--preview-only cannot be combined with framebuffer/capture experiments"
        )
    if args.system_channel_check and (
        args.live_preview
        or args.preview_only
        or args.camera_check
        or args.framebuffer_check
        or args.framebuffer_output
        or args.capture_layer is not None
    ):
        parser.error(
            "--system-channel-check must run separately from preview/capture experiments"
        )
    if args.live_preview and (
        not args.framebuffer_output or args.capture_layer is not None
    ):
        parser.error(
            "--live-preview requires --framebuffer-output and the default capture layer"
        )
    report = {
        "stationary_only": True,
        "camera_gate": "unproven",
        "ok": False,
        "host_platform": sys.platform,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    probe_started = time.monotonic()
    try:

        async def bounded_probe():
            async with asyncio.timeout(360 if args.select_ai_vision else 150):
                await probe(args, report)

        asyncio.run(bounded_probe())
        report["ok"] = report.get("console_recovered", True)
    except (
        Exception,
        KeyboardInterrupt,
    ) as error:  # noqa: BLE001 -- sanitize all SDK/vault errors at the CLI boundary
        report["error"] = (
            str(error)
            if isinstance(error, (RuntimeError, TimeoutError, ValueError))
            else type(error).__name__
        )
    report["probe_seconds"] = round(time.monotonic() - probe_started, 3)
    report["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
