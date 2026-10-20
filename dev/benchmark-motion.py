"""Developer-only hardware evidence. Students use prompts, never this harness.

Default: stationary warm-session calls. --motion --ready enables supervised
turns. Independent measurements are evaluated separately; IMU cannot verify itself.
"""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import time


def invoke(tool, args, timeout=135):
    started = time.monotonic()
    process = subprocess.run([tool, "--json", *args], capture_output=True, text=True, timeout=timeout)
    records = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    if process.returncode or not records or not records[-1].get("ok"):
        raise RuntimeError(f"Command failed; do not retry movement: {records or process.stderr}")
    return dict(result=records[-1], events=records[:-1], wall_ms=round((time.monotonic()-started)*1000, 2))


def summary(values):
    values = sorted(values)
    return dict(count=len(values), median_ms=statistics.median(values),
                p95_ms=values[max(0, math.ceil(.95*len(values))-1)], max_ms=max(values)) if values else None


def evaluate(report, observations):
    """Require independent unwrapped signed turn angles, not wrapped final headings."""
    by_id = {item["trial"]: item for item in observations["observations"]}
    if len(by_id) != len(observations["observations"]):
        raise ValueError("Duplicate independent observations")
    if observations.get("source") not in ("external_video", "physical_angle_reference"):
        raise ValueError("Use independent video/angle measurements, not robot IMU or odometry")
    rows = []
    for trial in report["trials"]:
        if trial["kind"] != "turn":
            continue
        item = by_id.get(trial["trial"])
        if item is None:
            rows.append(dict(trial=trial["trial"], verified=False))
            continue
        actual = float(item["measured_turn_deg"])
        if not math.isfinite(actual):
            raise ValueError("Nonfinite independent measurement")
        rows.append(dict(trial=trial["trial"], speed=trial["speed"], surface=report["surface"],
                         verified=True, error_deg=actual-trial["requested_deg"], within_5_deg=abs(actual-trial["requested_deg"])<=5,
                         robot_displaced=bool(item.get("robot_displaced", True))))
    speeds = sorted({trial["speed"] for trial in report["trials"] if trial["kind"]=="turn"})
    turns = [trial for trial in report["trials"] if trial["kind"]=="turn"]
    passing = []
    for speed in speeds:
        complete = all(sum(t["speed"]==speed and t["requested_deg"]==angle for t in turns)>=5
                       for angle in (-360,-180,-90,90,180,360))
        good = all(row.get("verified") and row.get("within_5_deg") and not row.get("robot_displaced")
                   for row,trial in zip(rows,turns) if trial["speed"]==speed)
        if complete and good:
            passing.append(speed)
    return dict(source=observations["source"], rows=rows, passing_speeds=passing,
                fastest_passing_speed=max(passing, default=None), other_surfaces_still_required=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool")
    parser.add_argument("--name")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--surface", default="unrecorded")
    parser.add_argument("--motion", action="store_true")
    parser.add_argument("--ready", action="store_true", help="Developer has confirmed clear floor, supervision and physical stop access")
    parser.add_argument("--speeds", type=int, nargs="+", default=[30,60,90])
    parser.add_argument("--capture-pairs", action="store_true", help="Extra stationary JPEGs before/after 360 turns; never normal workshop behavior")
    parser.add_argument("--evaluate", type=Path)
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    if args.evaluate:
        if not args.observations:
            parser.error("--evaluate needs --observations")
        report = json.loads(args.evaluate.read_text())
        report["independent_evaluation"] = evaluate(report, json.loads(args.observations.read_text()))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        return
    if not args.tool or not args.name or not 1 <= args.samples <= 20:
        parser.error("Supply --tool, --name and 1..20 samples")
    if args.motion and (not args.ready or args.surface=="unrecorded"):
        parser.error("Movement requires --ready and a developer surface label; this is never student setup")
    if any(speed not in (30,60,90) for speed in args.speeds):
        parser.error("Test speeds must be 30, 60 or 90")
    report = dict(ok=False, surface=args.surface, physical_accuracy_verified=False, trials=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    session = None
    try:
        cold = invoke(args.tool,["--name",args.name,"session","start"],65)
        session = cold["result"]["session"]
        report["session_start"] = cold
        for i in range(args.samples):
            trial = invoke(args.tool,["--session",session,"exec","print('warm')"])
            report["trials"].append(dict(trial=f"warm-{i}",kind="stationary",**trial))
        if args.motion:
            for speed in sorted(set(args.speeds)):
                for degrees in (90,180,360):
                    for sample in range(args.samples):
                        for direction in ("left","right"):
                            label = f"{speed}-{degrees}-{sample}-{direction}"
                            before = args.output.parent / f"{label}-before.jpg"
                            after = args.output.parent / f"{label}-after.jpg"
                            if args.capture_pairs and degrees==360:
                                invoke(args.tool,["--session",session,"snap","-o",str(before.resolve())])
                            trial = invoke(args.tool,["--session",session,"turn",direction,str(degrees),"--speed",str(speed)])
                            row = dict(trial=label,kind="turn",speed=speed,requested_deg=degrees*(-1 if direction=="left" else 1),**trial)
                            report["trials"].append(row)
                            if args.capture_pairs and degrees==360:
                                invoke(args.tool,["--session",session,"snap","-o",str(after.resolve())])
                                row["camera_pair"] = dict(before=str(before),after=str(after))
                            args.output.write_text(json.dumps(report,indent=2))
        report["warm_calls"] = summary([row["wall_ms"] for row in report["trials"] if row["kind"]=="stationary"])
        dispatch = [event["dispatch_ms"] for row in report["trials"] for event in row["events"] if "dispatch_ms" in event]
        report["dispatch"] = summary(dispatch)
        report["ok"] = True
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as error:
        report["error"] = str(error)
        raise
    finally:
        if session:
            try:
                report["close"] = invoke(args.tool,["--session",session,"session","close"],20)
            except Exception as error:
                report["close_error"] = str(error)
        args.output.write_text(json.dumps(report,indent=2))


if __name__ == "__main__":
    main()
