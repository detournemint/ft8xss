#!/usr/bin/env python3
"""Probe how this rig's ATU can be driven through rigctld, safely.

Only acts while the radio is idle, and reports SWR before/after so we can tell
whether U TUNER actually starts a tune cycle on the FT-991A.
"""
import socket
import sys
import time


def conn():
    return socket.create_connection(("127.0.0.1", 4532), timeout=6)


def q(s, cmd, wait=0.5):
    s.sendall((cmd + "\n").encode())
    time.sleep(wait)
    try:
        return s.recv(512).decode(errors="replace").strip()
    except Exception:
        return "ERR"


def wait_idle(s, timeout=40):
    """Wait for a gap between FT8 transmissions."""
    end = time.time() + timeout
    while time.time() < end:
        if q(s, "t", 0.3) == "0":
            time.sleep(0.4)
            if q(s, "t", 0.3) == "0":
                return True
        time.sleep(0.5)
    return False


s = conn()
print("  freq       :", q(s, "f"))
print("  tuner state:", q(s, "u TUNER"))
if not wait_idle(s):
    print("  radio never went idle -- aborting (will not tune during a transmission)")
    sys.exit(1)
print("  radio idle, safe to proceed")
print("  swr (idle) :", q(s, "l SWR"))
print()
print("  sending: U TUNER 1")
print("  result   :", q(s, "U TUNER 1", 1.0))
time.sleep(6)                       # a tune cycle takes a few seconds
print("  tuner now:", q(s, "u TUNER"))
print("  ptt now  :", q(s, "t"))
print("  swr now  :", q(s, "l SWR"))
s.close()
