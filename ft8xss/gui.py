"""Optional GUI automation for headless stations.

WSJT-X exposes a lot over its UDP protocol, but not everything: Enable Tx, the
Pwr slider and the Log QSO dialog exist only in the GUI. On a desktop the
operator handles those. On a headless station nobody can, so this module drives
them with xdotool against a virtual X display.

Everything here is optional. If xdotool or the display is unavailable,
`available()` returns False and the caller degrades to UDP-only behaviour.
"""
import asyncio
import os
import re
import shutil

_checked = None
_reason = "not checked"


def _env(name, default=""):
    return os.environ.get(f"FT8XSS_{name}", os.environ.get(f"FT8WEB_{name}", default))


DISPLAY = _env("DISPLAY_NUM", ":99")
WINDOW = _env("WSJTX_WINDOW", "WSJT-X")
UNIT = _env("WSJTX_UNIT", "wsjtx.service")
ENV = {**os.environ, "DISPLAY": DISPLAY}


def reason():
    return _reason


def available():
    """True if we can actually drive a WSJT-X window on this display."""
    global _checked, _reason
    if _checked is not None:
        return _checked
    if _env("NO_GUI") == "1":
        _checked, _reason = False, "disabled by FT8XSS_NO_GUI"
        return False
    for tool in ("xdotool", "xwininfo"):
        if not shutil.which(tool):
            _checked, _reason = False, f"{tool} not installed"
            return False
    try:
        import subprocess
        out = subprocess.run(["xdotool", "search", "--name", WINDOW],
                             env=ENV, capture_output=True, timeout=5)
        if out.returncode != 0 or not out.stdout.strip():
            _checked, _reason = False, f"no window matching {WINDOW!r} on {DISPLAY}"
            return False
    except Exception as e:
        _checked, _reason = False, f"{type(e).__name__}"
        return False
    _checked, _reason = True, f"driving {WINDOW!r} on {DISPLAY}"
    return True


def invalidate():
    """Force re-detection, e.g. after WSJT-X restarts."""
    global _checked
    _checked = None


async def _run(*args):
    pr = await asyncio.create_subprocess_exec(
        *args, env=ENV, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL)
    out, _ = await pr.communicate()
    return out.decode(errors="replace").strip()


async def xdo(*args):
    return await _run("xdotool", *args)


async def window_id():
    ids = (await xdo("search", "--name", WINDOW)).splitlines()
    return ids[0] if ids else None


async def client_origin():
    """Absolute screen position of the client area.

    xdotool reports the *frame* origin; with a window manager running that is
    offset by the title bar, so clicks computed from it land high. xwininfo's
    'Absolute upper-left' is the client area, which is what we want.
    """
    wid = await window_id()
    if not wid:
        return None
    txt = await _run("xwininfo", "-id", wid)
    mx = re.search(r"Absolute upper-left X:\s+(-?\d+)", txt)
    my = re.search(r"Absolute upper-left Y:\s+(-?\d+)", txt)
    return (int(mx.group(1)), int(my.group(1))) if mx and my else None


async def click_at(dx, dy):
    origin = await client_origin()
    if not origin:
        return False
    await xdo("mousemove", "--sync", str(origin[0] + dx), str(origin[1] + dy))
    await asyncio.sleep(0.2)
    await xdo("click", "1")
    await asyncio.sleep(0.6)
    return True


async def press(keys):
    """Send an accelerator to the WSJT-X window.

    Uses XTEST (no --window): Qt ignores the XSendEvent that `xdotool key
    --window` produces.
    """
    wid = await window_id()
    if not wid:
        return False
    await xdo("windowfocus", "--sync", wid)
    await asyncio.sleep(0.3)
    await xdo("key", "--clearmodifiers", keys)
    return True


async def set_tx(want, is_enabled, tries=2, settle=8.0):
    """Set Enable Tx to `want`.

    Alt+N is a *toggle*, so this reads the state WSJT-X reports rather than
    blindly sending the keystroke. Crucially it waits long enough for the
    resulting Status packet before considering a retry -- retrying too eagerly
    sends a second toggle and undoes the first.

    `is_enabled` is a callable returning the current state (None if unknown).
    """
    for attempt in range(tries):
        if is_enabled() is want:
            return True
        if not await press("alt+n"):
            return False
        deadline = asyncio.get_event_loop().time() + settle
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.2)
            if is_enabled() is want:
                return True
        # not confirmed: re-read before deciding, the state may have flipped
        if is_enabled() is want:
            return True
    return is_enabled() is want


async def restart_wsjtx(prepare=None):
    """Restart WSJT-X, optionally mutating its config while it is stopped."""
    pr = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "stop", UNIT,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await pr.wait()
    await asyncio.sleep(1.5)
    if prepare:
        prepare()
    pr = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "start", UNIT,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    await pr.wait()
    invalidate()
    return True
