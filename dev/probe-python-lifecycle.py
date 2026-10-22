"""Compare executing Python with idle REPL access; stationary developer control.

Uses documented AIM wait/Thread operations, never a candidate power API. This is
an isolated experiment, not sleep-prevention acceptance or student setup.
"""

import argparse
import json
import subprocess
import time
import uuid
from pathlib import Path

from attention import write_json


def source_for(token, seconds, mode):
    if not token.isidentifier() or not 60 <= seconds <= 1200:
        raise ValueError("Invalid control token or duration")
    if mode not in ("main", "thread"):
        raise ValueError("Unknown Python lifecycle control")
    return (
        "import json\n"
        f"{token} = {{'nonce': {token!r}, 'ticks': 0, 'done': False, "
        "'start_ms': robot.timer.system()}\n"
        f"def {token}_run():\n"
        f"    while robot.timer.system() - {token}['start_ms'] < {seconds * 1000}:\n"
        "        wait(100, MSEC)\n"
        f"        {token}['ticks'] += 1\n"
        f"    {token}['end_ms'] = robot.timer.system()\n"
        f"    {token}['done'] = True\n"
        + (
            f"{token}_run()\nprint(json.dumps({token}))\n"
            if mode == "main"
            else f"{token}_thread = Thread({token}_run)\nprint({token!r})\n"
        )
    )


def validate_result(value, token, seconds, elapsed):
    if value.get("nonce") != token or value.get("done") is not True:
        raise RuntimeError("Python control lost its marker or did not finish")
    if value.get("ticks", 0) <= 0:
        raise RuntimeError("Waiting Python worker did not advance")
    if value.get("end_ms", 0) - value.get("start_ms", 0) < seconds * 1000:
        raise RuntimeError("Robot did not complete the requested interval")
    if elapsed < seconds:
        raise RuntimeError("Host did not observe the requested interval")


def cli_result(result):
    rows = [json.loads(row) for row in result.stdout.splitlines() if row.strip()]
    value = rows[-1] if rows else {"error": result.stderr}
    if not isinstance(value, dict):
        raise TypeError("CLI did not return a result object")
    if result.returncode or value.get("ok") is not True:
        raise RuntimeError(
            value.get("error")
            or value.get("stderr")
            or result.stderr
            or "CLI control failed"
        )
    return value


def execution_command(tool, session, source, seconds, mode, standalone_name=None):
    timeout = 30 if mode == "thread" else seconds + 30
    if mode != "main" and standalone_name:
        raise ValueError("Standalone mode is only for the main-thread control")
    if timeout > 120 and not standalone_name:
        raise ValueError(
            "Session main-thread control must fit the existing 120-second exec limit; "
            "use --duration 60..90 or explicitly select --standalone-name for a long control"
        )
    if standalone_name:
        return [
            tool,
            "--json",
            "--transport",
            "bluetooth",
            "--name",
            standalone_name,
            "exec",
            "--timeout",
            str(timeout),
            source,
        ]
    return [
        tool,
        "--json",
        "--session",
        session,
        "exec",
        "--no-preamble",
        "--timeout",
        str(timeout),
        source,
    ]


def wait_for_close(tool, session):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = subprocess.run(
            [tool, "--json", "--session", session, "session", "status"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=4,
            check=False,
        )
        if result.returncode:
            value = json.loads(result.stdout)
            if "Session unavailable (" in value.get("error", ""):
                return
            cli_result(result)
        time.sleep(0.1)
    raise RuntimeError("Previous session did not release its connection in time")


def run(args):
    tool = str(args.tool.resolve(strict=True))
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(
            "Preserve the previous report; choose a new --output path"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    token = "_va_lifecycle_" + uuid.uuid4().hex
    source = source_for(token, args.duration, args.mode)
    report = {
        "state": "running",
        "passed": False,
        "mode": args.mode,
        "stationary": True,
        "requested_seconds": args.duration,
        "scope": "isolated Python lifecycle control",
        "saved_program_uploaded": False,
        "started_at_unix_ms": int(time.time() * 1000),
        "checks": [],
    }
    started = time.monotonic()
    child = None
    thread_created = False
    standalone_name = getattr(args, "standalone_name", None)

    def save():
        report["elapsed_s"] = time.monotonic() - started
        write_json(output, report)

    def call(words):
        result = subprocess.run(
            [tool, "--json", "--session", args.session, *words],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=45,
            check=False,
        )
        value = cli_result(result)
        report["checks"].append({"command": words, "result": value})
        save()
        return value

    try:
        save()
        command = execution_command(
            tool, args.session, source, args.duration, args.mode, standalone_name
        )
        context = call(["session", "status"])
        identity = context.get("device_info", {})
        if (
            context.get("transport"),
            identity.get("model"),
            identity.get("hardware"),
            identity.get("firmware"),
        ) != ("bluetooth", "AIM", "REV1", "1.0.4.b0"):
            raise RuntimeError(
                "Control requires the observed AIM REV1 / 1.0.4.b0 profile"
            )
        before = call(["info"])["robot_state"]
        if before.get("stopped") is not True or before.get("imu_calibrating"):
            raise RuntimeError("Robot must be stopped and not calibrating")
        if standalone_name:
            if context.get("name") != standalone_name:
                raise RuntimeError(
                    "Standalone name differs from the verified session robot"
                )
            call(["session", "close"])
            wait_for_close(tool, args.session)
            report["session_closed_for_control"] = True
            report["background_link_monitor_during_control"] = False
        report["before"] = before
        report["phase"] = "executing_python"
        child = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        measured_start = time.monotonic()
        last = measured_start
        while child.poll() is None:
            time.sleep(1)
            now = time.monotonic()
            if now - last > 15:
                report["state"] = "incomplete"
                raise RuntimeError(
                    "Host monitoring paused; uninterrupted control not established"
                )
            last = now
            if now - measured_start > args.duration + 60:
                raise RuntimeError("Bounded Python control did not return in time")
            save()
        stdout, stderr = child.communicate()
        result = cli_result(
            subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
        )
        report["execution"] = result
        if args.mode == "thread":
            if result.get("stdout", "").strip() != token:
                raise RuntimeError("Python thread startup marker missing")
            thread_created = True
            report["phase"] = "quiet_thread"
            while time.monotonic() - measured_start < args.duration + 1:
                time.sleep(5)
                now = time.monotonic()
                if now - last > 15:
                    report["state"] = "incomplete"
                    raise RuntimeError("Host monitoring paused during thread control")
                last = now
                # Cached local IPC only; no foreground radio requests in this phase.
                health = call(["session", "status"]).get("keepalive", {})
                if (
                    not health.get("active")
                    or health.get("consecutive_failures", 0) >= 3
                ):
                    raise RuntimeError(
                        "Link monitor failed during Python thread control"
                    )
            result = call(["exec", "--no-preamble", f"print(json.dumps({token}))"])
        measured_elapsed = time.monotonic() - measured_start
        value = json.loads(result.get("stdout", ""))
        report["worker"] = value
        validate_result(value, token, args.duration, measured_elapsed)
        if standalone_name:
            after_call = subprocess.run(
                [
                    tool,
                    "--json",
                    "--transport",
                    "bluetooth",
                    "--name",
                    standalone_name,
                    "info",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=45,
                check=False,
            )
            after = json.loads(cli_result(after_call)["stdout"])
            report["after_reconnect"] = True
        else:
            after = call(["info"])["robot_state"]
        if after.get("stopped") is not True:
            raise RuntimeError("Stopped state was not confirmed after the control")
        report.update(after=after, state="passed", passed=True)
    except KeyboardInterrupt:
        report.update(error="Interrupted by operator", passed=False, state="incomplete")
    except (
        RuntimeError,
        OSError,
        ValueError,
        TypeError,
        subprocess.SubprocessError,
    ) as error:
        report.update(error=str(error) or "Interrupted", passed=False)
        if report["state"] != "incomplete":
            report["state"] = "failed"
    finally:
        if child is not None and child.poll() is None:
            # Terminating this CLI client does not claim robot execution stopped.
            # The generated robot code has its own finite duration, regardless.
            child.terminate()
            try:
                child.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate(timeout=10)
            report["execution_delivery_uncertain"] = True
        if thread_created:
            try:
                call(["exec", "--no-preamble", f"{token}_thread.stop()"])
                report["thread_cleanup"] = "confirmed"
            except (
                RuntimeError,
                OSError,
                ValueError,
                TypeError,
                subprocess.SubprocessError,
            ) as error:
                report.update(thread_cleanup=str(error), passed=False, state="failed")
        save()
        print(
            json.dumps(
                {
                    "state": report["state"],
                    "passed": report["passed"],
                    "report": str(output),
                    "error": report.get("error"),
                }
            )
        )
    return 0 if report["passed"] else 2 if report["state"] == "incomplete" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tool", type=Path)
    parser.add_argument("--session", required=True)
    parser.add_argument("--mode", choices=("main", "thread"), required=True)
    parser.add_argument(
        "--standalone-name",
        help="Long main control only: verify this name, close its session, then use a standalone connection",
    )
    parser.add_argument("--duration", type=int, choices=range(60, 1201), default=420)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
