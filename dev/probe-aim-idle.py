"""Stationary developer investigation of AIM's native status requests.

Close CLI owners first. Bluetooth only; uses existing vault authentication.
No programs, firmware, wheels or kicker commands are sent. Optional --home-back
tests a source-derived Back input only after confirming home screen zero.
"""

import argparse
import asyncio
import contextlib
import importlib.util
import json
import sys
import time
from pathlib import Path


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def home_back(system, display, screen_id):
    """Never select a tile or inject input on a program/unknown menu screen."""
    if screen_id != 0:
        return False
    # Official VEXcom _aim_command_touch("back") -> _aim_TouchCommand(0x54).
    await system.exchange(display.packet(0x56, 0x65, b"\x54"))
    return True


async def run(args, report, save):
    root = Path(__file__).resolve().parent
    display = load("idle_display", root / "display-probe.py")
    helper = load("idle_ble", root / "ble-feasibility.py")
    if helper.usb_present() is True:
        raise RuntimeError("Unplug USB for this Bluetooth-only investigation")
    found = [
        d
        for d, a in (
            await helper.BleakScanner.discover(timeout=8, return_adv=True)
        ).values()
        if (a.local_name or d.name) == args.name
    ]
    if len(found) != 1:
        raise RuntimeError("Expected exactly one named AIM")
    async with helper.BleakClient(found[0], timeout=15, pair=False) as client:
        connection_request = None
        if sys.platform == "win32":
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
        if identity != display.IDENTITY:
            raise RuntimeError("Protocol gate requires AIM REV1 / BLE 1.0.0.b0")
        report["identity"] = identity
        auth = bytes(await client.read_gatt_char(helper.PAIRING))
        if auth == helper.UNPAIRED:
            helper.keyring.set_keyring(helper.native_credential_store())
            code = helper.keyring.get_password(helper.VAULT_SERVICE, found[0].address)
            if code is None:
                raise RuntimeError("Pair through the CLI first")
            pin = helper.decode_pin(code)
            await client.write_gatt_char(helper.PAIRING, pin, response=True)
            if bytes(await client.read_gatt_char(helper.PAIRING)) != pin:
                raise RuntimeError("Stored authentication rejected")
            code = pin = None
        elif len(auth) != 4 or any(digit > 9 for digit in auth):
            raise RuntimeError("Unknown authentication state")
        auth = None
        system = display.System(client, helper, report)
        stream = helper.UserStream(client)
        await client.start_notify(helper.SYSTEM_TX, system.notify)
        await client.start_notify(helper.USER_TX, stream.notification)
        try:
            if not await stream.sync():
                raise RuntimeError("Could not prepare console")
            state_source = display.PREPARE + display.STATE
            report["before"] = await stream.execute(state_source)
            if not report["before"]["stopped"] or report["before"]["imu_calibrating"]:
                raise RuntimeError("Stationary robot required")
            report["uptime_before"] = await stream.execute(
                "print(json.dumps({'ms':robot.timer.system()}))\n"
            )
            start = time.monotonic()
            failures = 0
            next_back = start
            while time.monotonic() - start < args.duration:
                # Official VEXcom: _v5_SystemStatus (0x20 flags) and
                # _v5_BrainStatus (0x22 versions/system status). Both are reads.
                try:
                    # Match ordinary CLI traffic, including its GATT auth read.
                    # Never save or print authentication bytes in the report.
                    current_auth = bytes(await client.read_gatt_char(helper.PAIRING))
                    if len(current_auth) != 4 or any(
                        digit > 9 for digit in current_auth
                    ):
                        raise RuntimeError(
                            "Bluetooth authentication is no longer valid"
                        )
                    current_auth = None
                    flags = await system.status() if args.probe != "status" else None
                    status = (
                        await system.exchange(display.packet(0x56, 0x22))
                        if args.probe != "flags"
                        else b""
                    )
                except (TimeoutError, OSError, RuntimeError) as error:
                    failures += 1
                    report.setdefault("poll_errors", []).append(
                        {
                            "elapsed_s": round(time.monotonic() - start, 3),
                            "connected": client.is_connected,
                            "error": str(error),
                        }
                    )
                    save()
                    if failures >= 3 or not client.is_connected:
                        raise
                    await asyncio.sleep(2)
                    continue  # Only fresh read-only queries may retry.
                failures = 0
                if args.home_back and time.monotonic() >= next_back:
                    # Once sent, a Back input is never automatically replayed,
                    # even if the transport loses its acknowledgment.
                    sent = await home_back(system, display, flags["screen_id"])
                    report.setdefault("home_back", []).append(
                        {
                            "elapsed_s": round(time.monotonic() - start, 3),
                            "sent": sent,
                        }
                    )
                    next_back = time.monotonic() + 60
                report["polls"].append(
                    {
                        "elapsed_s": round(time.monotonic() - start, 3),
                        "screen_id": flags["screen_id"] if flags else None,
                        "status_bytes": len(status),
                    }
                )
                save()
                if len(report["polls"]) % 15 == 1:
                    print(json.dumps(report["polls"][-1]), flush=True)
                await asyncio.sleep(2)
            report["after"] = await stream.execute(state_source)
            report["uptime_after"] = await stream.execute(
                "print(json.dumps({'ms':robot.timer.system()}))\n"
            )
            if not report["after"]["stopped"]:
                raise RuntimeError("Robot no longer stationary")
            if report["uptime_after"]["ms"] <= report["uptime_before"]["ms"]:
                raise RuntimeError("Robot uptime did not advance")
            report["passed"] = True
        finally:
            if client.is_connected:
                with contextlib.suppress(Exception):
                    await stream.write(b"\x02")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--probe", choices=["flags", "status", "both"], default="flags")
    parser.add_argument("--home-back", action="store_true")
    parser.add_argument("--duration", type=int, default=420, choices=range(60, 901))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.home_back and args.probe == "status":
        parser.error("--home-back requires live screen flags")
    report = {
        "passed": False,
        "polls": [],
        "stationary": True,
        "duration_s": args.duration,
        "probe": args.probe,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    try:
        asyncio.run(run(args, report, save))
    except Exception as error:  # noqa: BLE001 - preserve failed hardware evidence
        report["error"] = str(error)
    finally:
        save()
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "error": report.get("error"),
                    "report": str(args.output.resolve()),
                }
            ),
            flush=True,
        )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
