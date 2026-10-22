"""Stationary CLI endurance check; no additional Python packages or movement.

Use --display for the rc.5 display lifecycle control, or omit it to test session
keepalive without LCD activation. A stop file allows a clean autonomous handoff.
Reports and photographs stay local under .vexaim/keepalive.
"""

import argparse
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path

from attention import Attention, write_json


class Incomplete(RuntimeError):
    """The requested interval was not completed; this is never a pass."""


def validate_power_evidence(value, previous_ticks=None, seconds=0):
    if (
        value.get("active") is not True
        or value.get("sleep_disabled") is not True
        or value.get("expired") is not False
        or not isinstance(value.get("watchdog_ticks"), int)
        or value["watchdog_ticks"] <= 0
        or not isinstance(value.get("watchdog_age_ms"), (int, float))
        or not 0 <= value["watchdog_age_ms"] <= 3000
    ):
        raise RuntimeError("Robot power lease/watchdog is not live and confirmed")
    if previous_ticks is not None and (
        value.get("same_lease") is not True
        or value["watchdog_ticks"] - previous_ticks < max(1, int(seconds / 2))
    ):
        raise RuntimeError(
            "Quiet interval replaced its lease or watchdog did not advance"
        )


def main(args):
    tool = str(args.tool.resolve(strict=True))
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "passed": False,
        "stationary": True,
        "checks": [],
        "requested_seconds": args.duration,
        "quiet_seconds": args.quiet_seconds,
        "display_control": args.display,
        "started_at_unix_ms": int(time.time() * 1000),
        "state": "running",
        "label": getattr(args, "label", "stationary-endurance"),
        "phases": [],
    }
    path = output / ("endurance-" + str(uuid.uuid4()) + ".json")
    nonce = str(uuid.uuid4())

    def save():
        write_json(path, report)

    def check_cancel():
        if args.stop_file and args.stop_file.exists():
            report["handoff_requested"] = True
            raise Incomplete("Operator requested handoff; interval not completed")

    def phase(name):
        check_cancel()
        report["phase"] = name
        report["phases"].append({"name": name, "elapsed_s": time.monotonic() - start})
        save()

    def call(words):
        requested_at = time.monotonic()
        result = subprocess.run(
            [tool, "--json", "--session", args.session, *words],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=85,
            check=False,
        )
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        value = rows[-1] if rows else {"ok": False, "error": result.stderr}
        report["checks"].append(
            {
                "command": words,
                "result": value,
                "requested_elapsed_s": requested_at - start,
                "completed_elapsed_s": time.monotonic() - start,
            }
        )
        save()
        if result.returncode or value.get("ok") is not True:
            raise RuntimeError(value.get("error", "CLI command failed"))
        return value

    def sample():
        state = call(["info"])["robot_state"]
        if not state["stopped"] or state["imu_calibrating"]:
            raise RuntimeError("Robot is not stationary; endurance check stopped")
        system_time = call(["timer", "system"])["value"]["value"]
        result = call(["exec", "--no-preamble", "print(_va_endurance_nonce)"])
        if result.get("stdout", "").strip() != nonce:
            raise RuntimeError(
                "Persistent REPL nonce changed; interpreter state was lost"
            )
        report.setdefault("samples", []).append(
            {
                "elapsed_s": time.monotonic() - start,
                "system_time_ms": system_time,
                **state,
            }
        )
        if (
            len(report["samples"]) > 1
            and system_time < report["samples"][-2]["system_time_ms"]
        ):
            raise RuntimeError(
                "Robot system time went backwards; reset semantics need inspection"
            )
        report["elapsed_s"] = time.monotonic() - start
        save()
        print(
            json.dumps(
                {
                    "elapsed_s": round(time.monotonic() - start),
                    "battery_pct": state["battery_pct"],
                    "stopped": state["stopped"],
                    "system_time_ms": system_time,
                }
            ),
            flush=True,
        )

    def quiet(seconds):
        deadline = time.monotonic() + seconds
        first_count = None
        last_count = None
        last_observed = time.monotonic()
        while time.monotonic() < deadline:
            check_cancel()
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            observed = time.monotonic()
            if observed - last_observed > 15:
                raise Incomplete(
                    "Host monitoring paused; uninterrupted quiet interval not established"
                )
            last_observed = observed
            # Cached IPC only: no radio activity or owner lease renewal.
            health = call(["session", "status"]).get("keepalive", {})
            count = health.get("confirmed_polls")
            if count is not None:
                if first_count is None:
                    first_count = count
                last_count = count
            inactive_allowed = getattr(args, "allow_inactive_monitor", False)
            if (health.get("active") is False and not inactive_allowed) or health.get(
                "consecutive_failures", 0
            ) >= 3:
                raise RuntimeError(
                    "Background keepalive stopped; inspect cached health"
                )
            if (
                health.get("active") is True
                and health.get("last_confirmed_ms_ago", 0) is not None
                and health.get("last_confirmed_ms_ago", 0) > 12000
            ):
                raise RuntimeError("Background keepalive acknowledgments are stale")
        if (
            seconds >= 10
            and health.get("active") is True
            and first_count is not None
            and last_count <= first_count
        ):
            raise RuntimeError(
                "Background keepalive acknowledgment count did not advance"
            )

    def power_checkpoint(reset=False):
        source = "_va_endurance_power_ref = _va_power_lease\n" if reset else ""
        source += "print(_va_json.dumps({'same_lease':_va_power_lease is _va_endurance_power_ref,'active':_va_power_lease.active,'expired':_va_power_lease.expired,'sleep_disabled':_va_power_lease.control(),'watchdog_ticks':_va_power_lease.ticks,'watchdog_age_ms':_va_power_lease.age(_va_power_lease.last_tick_ms)}))\n"
        result = call(["exec", "--no-preamble", source])
        value = json.loads(result.get("stdout", ""))
        validate_power_evidence(value)
        report.setdefault("power_checks", []).append(value)
        save()
        return value

    def observed_quiet(seconds):
        required = getattr(args, "require_power_lease", False)
        before = power_checkpoint(reset=True) if required and seconds else None
        quiet(seconds)
        if before:
            after = power_checkpoint()
            validate_power_evidence(after, before["watchdog_ticks"], seconds)

    def camera():
        observation = call(
            ["camera", "observe", "--output-dir", str(output / "captures")]
        )
        if not observation.get("control_ready"):
            raise RuntimeError("Postcapture control is not ready")

    start = time.monotonic()
    exit_code = 1
    try:
        if (
            args.quiet_seconds + args.after_stop_quiet > args.duration
            or args.camera_interval < 0
        ):
            raise ValueError(
                "Quiet period must fit the duration; camera interval cannot be negative"
            )
        phase("preflight")
        cached = call(["session", "status"])
        report["context"] = {
            key: cached.get(key)
            for key in (
                "tool_version",
                "transport",
                "name",
                "id",
                "device_info",
                "keepalive",
            )
        }
        if getattr(args, "require_power_lease", False):
            power = cached.get("keepalive", {}).get("power", {})
            if power.get("supported") is not True or power.get("active") is not True:
                raise RuntimeError(
                    "Candidate must report its supported active power lease"
                )
        if getattr(args, "probe_watchdog_expiry", False):
            if not getattr(args, "require_power_lease", False):
                raise ValueError("Watchdog expiry probe requires power lease checks")
            phase("watchdog_expiry")
            call(
                [
                    "exec",
                    "--no-preamble",
                    "_va_expiry_ref = _va_power_lease\n_va_expiry_ref.ttl_ms = 1500\n_va_expiry_ref.renewed_ms = int(_va_expiry_ref.now())\nprint('expiry armed')",
                ]
            )
            # No foreground command renews or repairs the lease during this gap.
            time.sleep(3.5)
            call(["info"])
            result = call(
                [
                    "exec",
                    "--no-preamble",
                    "print(_va_json.dumps({'expired':_va_expiry_ref.expired,'released':_va_expiry_ref.released,'old_active':_va_expiry_ref.active,'new_active':_va_power_lease.active,'sleep_disabled':_va_power_lease.control()}))",
                ]
            )
            evidence = json.loads(result.get("stdout", ""))
            report["watchdog_expiry"] = evidence
            save()
            if evidence != {
                "expired": True,
                "released": True,
                "old_active": False,
                "new_active": True,
                "sleep_disabled": True,
            }:
                raise RuntimeError("Robot-side watchdog expiry was not established")
            phase("preflight_after_expiry")
        call(
            [
                "exec",
                "--no-preamble",
                "_va_endurance_nonce = " + repr(nonce) + "; print(_va_endurance_nonce)",
            ]
        )
        if args.display:
            call(["screen", "show-emoji", "HAPPY"])
        sample()
        phase("quiet_before")
        observed_quiet(args.quiet_seconds)
        if args.quiet_seconds:
            sample()
        if args.after_stop_quiet:
            phase("camera_display_stop")
            camera()
            call(["screen", "show-emoji", "HAPPY"])
            if getattr(args, "capture_lcd", False):
                display_before = (
                    power_checkpoint(reset=True)
                    if getattr(args, "require_power_lease", False)
                    else None
                )
                display_started = time.monotonic()
                lcd = call(
                    [
                        "screen",
                        "screenshot",
                        str(output / ("lcd-happy-" + nonce + ".png")),
                    ]
                )
                if lcd.get("control_ready") is not True:
                    raise RuntimeError("Control not ready after LCD capture")
                report["lcd_path"] = lcd["path"]
                save()
                if display_before:
                    display_after = power_checkpoint()
                    validate_power_evidence(
                        display_after,
                        display_before["watchdog_ticks"],
                        time.monotonic() - display_started,
                    )
            call(["stop"])
            if getattr(args, "require_power_lease", False):
                recovered = call(["info"])["robot_state"]
                if recovered.get("stopped") is not True:
                    raise RuntimeError("Poststop live state is not stopped")
                # 1.0.4 native display/REPL program transitions replace the
                # interpreter. Verify persistence within each quiet context;
                # sample() separately requires continuous robot system time.
                nonce = str(uuid.uuid4())
                call(
                    [
                        "exec",
                        "--no-preamble",
                        "_va_endurance_nonce = "
                        + repr(nonce)
                        + "; print(_va_endurance_nonce)",
                    ]
                )
                report.setdefault("context_transitions", []).append(
                    {
                        "reason": "explicit display and stop program transition",
                        "elapsed_s": time.monotonic() - start,
                    }
                )
                save()
            sample()
            phase("quiet_after_stop")
            observed_quiet(args.after_stop_quiet)
            sample()
            camera()
        phase("functional_interval")
        deadline = start + args.duration
        next_camera = (
            start + args.camera_interval if args.camera_interval else deadline + 1
        )
        while time.monotonic() < deadline:
            check_cancel()
            time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
            sample()
            if time.monotonic() >= next_camera:
                camera()
                next_camera = time.monotonic() + args.camera_interval
        report["elapsed_s"] = time.monotonic() - start
        check_cancel()
        sample()
        report["passed"] = report["elapsed_s"] >= args.duration
        report["state"] = "passed" if report["passed"] else "incomplete"
        exit_code = 0 if report["passed"] else 2
    except (Incomplete, KeyboardInterrupt) as error:
        report.update(state="incomplete", error=str(error) or "Interrupted by operator")
        exit_code = 2
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        report["state"] = "failed"
        report["failure_class"] = (
            "interpreter_state_lost"
            if "nonce" in str(error)
            else "command_or_transport_error"
        )
    finally:
        report["elapsed_s"] = time.monotonic() - start
        report["finished_at_unix_ms"] = int(time.time() * 1000)
        save()
        print(
            json.dumps(
                {
                    "passed": report["passed"],
                    "elapsed_s": round(report["elapsed_s"]),
                    "report": str(path),
                    "error": report.get("error"),
                }
            ),
            flush=True,
        )
    attention_directory = getattr(args, "attention_dir", None)
    if exit_code == 1 and attention_directory:
        report["state"] = "awaiting_user"
        report["outcome"] = "failed"
        save()
        try:
            report["attention"] = Attention(attention_directory).request(
                "Return to the computer to review the paused AIM test.",
                report["error"]
                + " No actuator command was sent; do not replay any action.",
            )
        except (RuntimeError, OSError, ValueError) as error:
            report["attention"] = {"state": "incomplete", "error": str(error)}
        report["state"] = "failed"
        save()
    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument(
        "--duration", type=int, default=420, choices=range(60, 1801), metavar="60..1800"
    )
    parser.add_argument(
        "--interval", type=int, default=15, choices=range(1, 31), metavar="1..30"
    )
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--require-power-lease", action="store_true")
    parser.add_argument("--probe-watchdog-expiry", action="store_true")
    parser.add_argument("--capture-lcd", action="store_true")
    parser.add_argument(
        "--quiet-seconds", type=int, default=0, choices=range(901), metavar="0..900"
    )
    parser.add_argument("--camera-interval", type=int, default=0)
    parser.add_argument(
        "--after-stop-quiet", type=int, default=0, choices=range(901), metavar="0..900"
    )
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--attention-dir", type=Path)
    parser.add_argument(
        "--allow-inactive-monitor",
        action="store_true",
        help="Baseline only: firmware with no validated link monitor may still be tested; no sleep claim is inferred",
    )
    parser.add_argument("--label", default="stationary-endurance")
    parser.add_argument("--output-dir", type=Path, default=Path(".vexaim/keepalive"))
    sys.exit(main(parser.parse_args()))
