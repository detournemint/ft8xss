"""Logging and diagnostics bundle.

Keeps a ring buffer of log lines in memory (and optionally a file), and can
assemble a redacted report an operator can paste into a bug report.

Redaction is not optional: the QRZ logbook API key would otherwise appear in
every report anyone sends.
"""
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

MAX_LINES = int(os.environ.get("FT8XSS_LOG_LINES", "3000"))
LOG_FILE = os.environ.get("FT8XSS_LOG_FILE", "")

_lines = deque(maxlen=MAX_LINES)
_secrets = set()
_fh = None

# things that look like credentials even if we were not told about them
_PATTERNS = [
    (re.compile(r"\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b"), "<API-KEY>"),
    (re.compile(r"(?i)(key|token|password|secret)\s*[=:]\s*\S+"), r"\1=<REDACTED>"),
]


def register_secret(value):
    """Mark a literal string to be scrubbed from all output."""
    if value and len(str(value)) >= 6:
        _secrets.add(str(value))


def redact(text):
    if not text:
        return text
    for s in _secrets:
        text = text.replace(s, "<REDACTED>")
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text


def log(msg, level="info"):
    """Record a line. Always safe to call; never raises."""
    try:
        line = (f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} "
                f"{level.upper():<5} {msg}")
        line = redact(line)
        _lines.append(line)
        print(line, flush=True)
        global _fh
        if LOG_FILE:
            if _fh is None:
                _fh = open(LOG_FILE, "a", buffering=1)
            _fh.write(line + "\n")
    except Exception:
        pass


def error(msg):
    log(msg, "error")


def exception(prefix, exc):
    import traceback
    log(f"{prefix}: {type(exc).__name__}: {exc}", "error")
    for ln in traceback.format_exception(type(exc), exc, exc.__traceback__):
        for part in ln.rstrip().splitlines():
            log("    " + part, "error")


def recent(n=400, level=None):
    out = list(_lines)[-n:]
    if level:
        out = [x for x in out if f" {level.upper():<5} " in x]
    return out


def _run(*args, timeout=6):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return f"({type(e).__name__})"


def _rig_probe(host="127.0.0.1", port=4532):
    import socket
    try:
        s = socket.create_connection((host, port), timeout=3)
        s.sendall(b"f\n")
        time.sleep(0.3)
        freq = s.recv(64).decode(errors="replace").strip()
        s.sendall(b"\\dump_state\n")
        time.sleep(0.3)
        st = s.recv(256).decode(errors="replace").strip().splitlines()
        s.close()
        return f"reachable, freq={freq}, model={st[1] if len(st) > 1 else '?'}"
    except Exception as e:
        return f"unreachable ({type(e).__name__})"


def bundle(state_fn=None, extra=None):
    """A redacted diagnostic report as plain text."""
    b = io.StringIO()
    w = b.write

    w("ft8xss diagnostics\n")
    w(f"generated  {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC\n")
    w("=" * 68 + "\n\n")

    w("-- environment --\n")
    w(f"python     {sys.version.split()[0]}\n")
    w(f"platform   {platform.platform()}\n")
    try:
        import aiohttp
        w(f"aiohttp    {aiohttp.__version__}\n")
    except Exception:
        w("aiohttp    (missing)\n")
    for tool in ("rigctld", "xdotool", "xwininfo", "wsjtx"):
        w(f"{tool:<10} {shutil.which(tool) or '(not installed)'}\n")
    hl = _run("rigctld", "--version")
    w(f"hamlib     {hl.splitlines()[0] if hl else '(unknown)'}\n\n")

    w("-- configuration (redacted) --\n")
    for k, v in sorted(os.environ.items()):
        if k.startswith("FT8XSS_"):
            shown = "<SET>" if "KEY" in k or "PASS" in k else v
            w(f"{k}={shown}\n")
    w("\n")

    w("-- radio --\n")
    w(f"rigctld    {_rig_probe()}\n")
    ports = sorted([str(p) for p in Path("/dev").glob("ttyUSB*")]
                   + [str(p) for p in Path("/dev").glob("ttyACM*")])
    w(f"serial     {ports or '(none)'}\n")
    usb = _run("lsusb")
    w("usb        " + "\n           ".join(
        [l for l in usb.splitlines()
         if not re.search(r"root hub", l, re.I)][:8] or ["(unavailable)"]) + "\n\n")

    w("-- audio --\n")
    cards = _run("aplay", "-l")
    w("playback   " + "\n           ".join(
        [l for l in cards.splitlines() if l.startswith("card")] or ["(none)"]) + "\n")
    caps = _run("arecord", "-l")
    w("capture    " + "\n           ".join(
        [l for l in caps.splitlines() if l.startswith("card")] or ["(none)"]) + "\n\n")

    if state_fn:
        w("-- station state --\n")
        try:
            for k, v in (state_fn() or {}).items():
                w(f"{k:<14} {v}\n")
        except Exception as e:
            w(f"(state unavailable: {type(e).__name__})\n")
        w("\n")

    if extra:
        w("-- extra --\n")
        for k, v in extra.items():
            w(f"{k:<14} {v}\n")
        w("\n")

    errs = recent(200, "error")
    w(f"-- errors ({len(errs)}) --\n")
    w("\n".join(errs) if errs else "(none recorded)")
    w("\n\n")

    w(f"-- log (last {min(len(_lines), 500)} lines) --\n")
    w("\n".join(recent(500)))
    w("\n")

    return redact(b.getvalue())
