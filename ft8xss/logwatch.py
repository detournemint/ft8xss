#!/usr/bin/env python3
"""Auto-accept WSJT-Z's 'Log QSO' dialog on a headless display.

WSJT-Z only auto-accepts that dialog when Auto CQ or Auto Call is ticked, and
neither checkbox is persisted to the config -- so on a headless station the
dialog can sit forever, silently swallowing the QSO and stalling auto-sequence.
This watches for it and presses OK.
"""
import os
import re
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY", ":99")
POLL = float(os.environ.get("LOGWATCH_POLL", "2.0"))
ENV = {**os.environ, "DISPLAY": DISPLAY}


def sh(*args):
    try:
        return subprocess.run(args, env=ENV, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


def find_dialog():
    out = sh("xdotool", "search", "--name", "Log QSO")
    return [w for w in out.splitlines() if w.strip().isdigit()]


def geometry(wid):
    out = sh("xdotool", "getwindowgeometry", "--shell", wid)
    g = dict(re.findall(r"^(\w+)=(-?\d+)$", out, re.M))
    if not {"X", "Y", "WIDTH", "HEIGHT"} <= g.keys():
        return None
    return {k: int(v) for k, v in g.items()}


def is_mapped(wid):
    return "IsViewable" in sh("xwininfo", "-id", wid)


def accept(wid):
    g = geometry(wid)
    if not g:
        return False
    # OK sits at the right end of the button row along the bottom edge
    x = g["X"] + g["WIDTH"] - 60
    y = g["Y"] + g["HEIGHT"] - 24
    sh("xdotool", "windowfocus", "--sync", wid)
    sh("xdotool", "key", "Return")
    time.sleep(0.6)
    if not is_mapped(wid):
        return True
    sh("xdotool", "mousemove", "--sync", str(x), str(y), "click", "1")
    time.sleep(0.6)
    return not is_mapped(wid)


def main():
    print(f"[logwatch] watching {DISPLAY} for Log QSO dialogs", flush=True)
    while True:
        try:
            for wid in find_dialog():
                if is_mapped(wid):
                    ok = accept(wid)
                    print(f"[logwatch] dialog {wid}: "
                          f"{'accepted' if ok else 'FAILED to accept'}", flush=True)
        except Exception as e:
            print(f"[logwatch] error: {type(e).__name__}: {e}", flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
