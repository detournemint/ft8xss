#!/usr/bin/env python3
"""Run everything: the Python tests, the browser-logic tests, and a syntax
check on the shipped page.

    python3 tests/run.py

Needs nothing but python3. node is used for the browser tests if it is
installed, and skipped with a warning if not.
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GREEN, RED, DIM, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def run(label, args, optional=False):
    print(f"\n{DIM}$ {' '.join(str(a) for a in args)}{OFF}")
    try:
        r = subprocess.run(args, cwd=ROOT)
    except FileNotFoundError:
        msg = f"{args[0]} not installed"
        print(f"{RED if not optional else DIM}  {label}: {msg}{OFF}")
        return optional
    ok = r.returncode == 0
    print(f"{GREEN if ok else RED}  {label}: {'passed' if ok else 'FAILED'}{OFF}")
    return ok


def check_page_scripts():
    """The interface is one big inline script; a syntax error there is a blank
    page for every operator, and nothing else in this suite would catch it."""
    html = (ROOT / "ft8xss/static/index.html").read_text()
    blocks = re.findall(r"<script>([\s\S]*?)</script>", html)
    if not blocks:
        print(f"{RED}  page scripts: no <script> block found{OFF}")
        return False
    if not shutil.which("node"):
        print(f"{DIM}  page scripts: skipped (node not installed){OFF}")
        return True
    import tempfile
    for i, b in enumerate(blocks):
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
            fh.write(b)
            path = fh.name
        r = subprocess.run(["node", "--check", path], capture_output=True, text=True)
        Path(path).unlink(missing_ok=True)
        if r.returncode != 0:
            print(f"{RED}  page scripts: block {i} has a syntax error{OFF}")
            print(r.stderr.strip()[:400])
            return False
    print(f"{GREEN}  page scripts: {len(blocks)} block(s) parse{OFF}")
    return True


def main():
    results = [
        ("python", run("python", [sys.executable, "tests/test_server.py"])),
        ("browser logic", run("browser logic", ["node", "tests/test_ui.mjs"],
                              optional=not shutil.which("node"))),
        ("page scripts", check_page_scripts()),
    ]
    print()
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"{RED}FAILED: {', '.join(bad)}{OFF}")
        return 1
    print(f"{GREEN}All suites passed.{OFF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
