#!/usr/bin/env python3
"""Gate 2 replug test. usage: replug.py VEXAIM_BIN [CYCLES]

For each cycle: wait for the human to UNPLUG (USB 2888:0700 disappears; also confirm vexaim reports no robot),
then REPLUG; measure seconds from reappearance until `vexaim exec` round-trips (retrying), run a few more
round trips, record everything as JSON lines on stdout. No actuators are touched.
"""
import json, subprocess, sys, time

BIN = sys.argv[1]
CYCLES = int(sys.argv[2]) if len(sys.argv) > 2 else 5


def present():
    r = subprocess.run(["lsusb", "-d", "2888:0700"], capture_output=True, text=True)
    return r.returncode == 0 and "2888:0700" in r.stdout


def vexaim(*args, timeout=20):
    t = time.time()
    try:
        r = subprocess.run([BIN, "--json", *args], capture_output=True, text=True, timeout=timeout)
        try:
            j = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            j = {"raw": r.stdout[-200:], "err": r.stderr[-200:]}
        return r.returncode, j, time.time() - t
    except subprocess.TimeoutExpired:
        return 99, {"timeout": True}, time.time() - t


def wait_for(cond, secs):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.2)
    return False


def log(**kw):
    print(json.dumps({"t": round(time.time(), 1), **kw}), flush=True)


def beep(name):
    """Audible cue for the human at the robot (paplay + freedesktop sounds; silently skipped if absent)."""
    try:
        subprocess.Popen(["paplay", f"/usr/share/sounds/freedesktop/stereo/{name}.oga"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


results = []
beep("message")  # harness ready: you may unplug now
for c in range(1, CYCLES + 1):
    log(event="waiting_for_unplug", cycle=c)
    if not wait_for(lambda: not present(), 300):
        log(event="FAIL_no_unplug_seen", cycle=c)
        results.append(False)
        continue
    rc, j, _ = vexaim("exec", "print(1)", timeout=15)
    log(event="unplugged", cycle=c, vexaim_rc_while_unplugged=rc, detail=str(j)[:120])
    log(event="waiting_for_replug", cycle=c)
    if not wait_for(present, 300):
        log(event="FAIL_no_replug_seen", cycle=c)
        results.append(False)
        continue
    t0 = time.time()
    ok = False
    attempts = 0
    while time.time() - t0 < 90:
        attempts += 1
        rc, j, dt = vexaim("exec", 'print("PONG" + str(6*7))', timeout=20)
        if rc == 0 and j.get("ok") and "PONG42" in j.get("stdout", ""):
            ok = True
            break
        time.sleep(1)
    recovery = round(time.time() - t0, 1)
    trips = []
    failures = []
    if ok:
        for k in range(5):
            rc, j, dt = vexaim("exec", 'print("PONG" + str(6*7))', timeout=20)
            good = rc == 0 and "PONG42" in j.get("stdout", "")
            trips.append(good)
            if not good:
                failures.append({"trip": k + 1, "rc": rc, "detail": str(j)[:300], "s": round(dt, 2)})
    log(event="recovered" if ok else "FAIL_no_recovery", cycle=c, recovery_s=recovery, attempts=attempts, followup_roundtrips_ok=f"{sum(trips)}/{len(trips)}", failures=failures)
    results.append(ok and all(trips))
    time.sleep(1)
    beep("complete")  # follow-ups are done: safe to unplug for the next cycle

log(event="SUMMARY", passed=sum(results), cycles=CYCLES, all_ok=all(results) and len(results) == CYCLES)
