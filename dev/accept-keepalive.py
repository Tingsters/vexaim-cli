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
    }
    path = output / ("endurance-" + str(uuid.uuid4()) + ".json")

    def call(words):
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
        report["checks"].append({"command": words, "result": value})
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        if result.returncode or value.get("ok") is not True:
            raise RuntimeError(value.get("error", "CLI command failed"))
        return value

    def sample():
        state = call(["info"])["robot_state"]
        if not state["stopped"] or state["imu_calibrating"]:
            raise RuntimeError("Robot is not stationary; endurance check stopped")
        uptime = call(["timer", "system"])["value"]["value"]
        report.setdefault("samples", []).append(
            {"elapsed_s": time.monotonic() - start, "uptime_ms": uptime, **state}
        )
        if uptime < report["samples"][0]["uptime_ms"]:
            raise RuntimeError("Robot uptime went backwards")
        report["elapsed_s"] = time.monotonic() - start
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(
            json.dumps(
                {
                    "elapsed_s": round(time.monotonic() - start),
                    "battery_pct": state["battery_pct"],
                    "stopped": state["stopped"],
                    "uptime_ms": uptime,
                }
            ),
            flush=True,
        )

    def quiet(seconds):
        deadline = time.monotonic() + seconds
        first_count = None
        last_count = None
        while time.monotonic() < deadline:
            if args.stop_file and args.stop_file.exists():
                report["handoff_requested"] = True
                return
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            # Cached IPC only: no radio activity or owner lease renewal.
            health = call(["session", "status"]).get("keepalive", {})
            count = health.get("confirmed_polls")
            if count is not None:
                if first_count is None:
                    first_count = count
                last_count = count
            if (
                health.get("active") is False
                or health.get("consecutive_failures", 0) >= 3
            ):
                raise RuntimeError(
                    "Background keepalive stopped; inspect cached health"
                )
            if (
                health.get("last_confirmed_ms_ago", 0) is not None
                and health.get("last_confirmed_ms_ago", 0) > 12000
            ):
                raise RuntimeError("Background keepalive acknowledgments are stale")
        if seconds >= 10 and first_count is not None and last_count <= first_count:
            raise RuntimeError(
                "Background keepalive acknowledgment count did not advance"
            )

    def camera():
        observation = call(
            ["camera", "observe", "--output-dir", str(output / "captures")]
        )
        if not observation.get("control_ready"):
            raise RuntimeError("Postcapture control is not ready")

    start = time.monotonic()
    try:
        if args.quiet_seconds > args.duration or args.camera_interval < 0:
            raise ValueError(
                "Quiet period must fit the duration; camera interval cannot be negative"
            )
        if args.display:
            call(["screen", "show-emoji", "HAPPY"])
        sample()
        quiet(args.quiet_seconds)
        if args.quiet_seconds:
            sample()
        if args.after_stop_quiet and not report.get("handoff_requested"):
            camera()
            call(["screen", "show-emoji", "HAPPY"])
            call(["stop"])
            sample()
            quiet(args.after_stop_quiet)
            sample()
            camera()
        deadline = start + args.duration
        next_camera = (
            start + args.camera_interval if args.camera_interval else deadline + 1
        )
        while time.monotonic() < deadline:
            if args.stop_file and args.stop_file.exists():
                report["handoff_requested"] = True
                break
            time.sleep(min(args.interval, max(0, deadline - time.monotonic())))
            sample()
            if time.monotonic() >= next_camera:
                camera()
                next_camera = time.monotonic() + args.camera_interval
        report["elapsed_s"] = time.monotonic() - start
        report["passed"] = report["elapsed_s"] >= args.duration
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
    finally:
        report["elapsed_s"] = time.monotonic() - start
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
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
    return 0 if report["passed"] or report.get("handoff_requested") else 1


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
    parser.add_argument(
        "--quiet-seconds", type=int, default=0, choices=range(901), metavar="0..900"
    )
    parser.add_argument("--camera-interval", type=int, default=0)
    parser.add_argument(
        "--after-stop-quiet", type=int, default=0, choices=range(901), metavar="0..900"
    )
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(".vexaim/keepalive"))
    sys.exit(main(parser.parse_args()))
