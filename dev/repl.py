#!/usr/bin/env python3
"""repl.py PORT 'expr1' 'expr2' ...: send each line to the AIM REPL (CRLF), print what comes back."""
import sys, time, serial
def open_port(path, wait=90):
    end = time.time() + wait
    while True:
        try: return serial.Serial(path, 115200, timeout=0.1)
        except serial.SerialException:
            if time.time() > end: raise
            time.sleep(1)   # busy: ModemManager probing (see linux/99-vex-aim.rules)
s = open_port(sys.argv[1])
def drain(t):
    end, buf = time.time() + t, b""
    while time.time() < end:
        buf += s.read(4096)
    return buf
print("initial:", repr(drain(0.5)))
s.write(b"\r\n"); print("prompt:", repr(drain(0.8)))
for line in sys.argv[2:]:
    t = time.time(); s.write(line.encode() + b"\r\n"); out = drain(float(__import__("os").environ.get("DRAIN","1.5")))
    print(f"[{time.time()-t:.2f}s] {line!r} -> {out!r}")
