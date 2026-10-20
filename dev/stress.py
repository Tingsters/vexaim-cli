#!/usr/bin/env python3
"""stress.py VEXAIM_BIN [N]: N consecutive `vexaim exec` round trips, logging every failure in full."""
import json, subprocess, sys, time

BIN = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 100
ok, fails, lat = 0, [], []
for i in range(1, N + 1):
    t = time.time()
    r = subprocess.run([BIN, "--json", "exec", 'print("PONG" + str(6*7))'], capture_output=True, text=True, timeout=30)
    dt = time.time() - t
    good = r.returncode == 0 and "PONG42" in r.stdout
    if good:
        ok += 1
        lat.append(dt)
    else:
        fails.append({"i": i, "rc": r.returncode, "stdout": r.stdout[-300:], "stderr": r.stderr[-300:], "s": round(dt, 2)})
print(json.dumps({"n": N, "ok": ok, "fails": fails, "ms_mean": round(1000 * sum(lat) / max(len(lat), 1)), "ms_max": round(1000 * max(lat, default=0))}, indent=1))
