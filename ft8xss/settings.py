"""Editable settings, defined once and rendered from the schema.

Values live in an env file (default ~/.config/ft8xss.env) that the systemd unit
reads. Most changes need a restart to take effect; the schema says which.
"""
import os
import re
from pathlib import Path

ENV_FILE = Path(os.environ.get("FT8XSS_ENV_FILE",
                               str(Path.home() / ".config/ft8xss.env")))

# key, label, section, type, restart-needed, secret, help
SCHEMA = [
    ("CALL", "Callsign", "Station", "text", True, False,
     "Your callsign. Must match WSJT-X."),
    ("GRID", "Grid square", "Station", "text", True, False,
     "Maidenhead locator, 4 or 6 characters. Used for distance and bearing."),

    ("HTTP_PORT", "Web port", "Server", "number", True, False,
     "Port this interface listens on."),
    ("UDP_PORT", "WSJT-X UDP port", "Server", "number", True, False,
     "Must match WSJT-X Settings > Reporting > UDP Server port."),
    ("BIND", "Bind address", "Server", "text", True, False,
     "0.0.0.0 for the whole network, 127.0.0.1 to require an SSH tunnel."),

    ("QRZ_KEY", "QRZ logbook API key", "Logging", "password", True, True,
     "From logbook.qrz.com. Enables automatic QSO upload. Leave blank to disable."),
    ("LOG", "WSJT-X ADIF path", "Logging", "text", True, False,
     "Defaults to ~/.local/share/WSJT-X/wsjtx_log.adi."),

    ("PARK", "Park reference", "POTA", "text", False, False,
     "The park you are activating, e.g. US-3407. Self-spotting and the "
     "activation upload both need it. Leave blank when not at a park."),
    ("POTA_USER", "POTA account email", "POTA", "text", False, False,
     "Only needed to upload an activation log. Spotting works without it."),
    ("POTA_PASS", "POTA password", "POTA", "password", False, True,
     "Stored in ~/.config/ft8xss.env, mode 600. Only used to upload logs."),

    ("DEADMAN", "Dead-man timeout (s)", "Safety", "number", False, False,
     "Stop transmitting if the browser stops responding while armed. 0 disables."),
    ("AUTO_ARM", "Auto-arm transmit", "Safety", "bool", False, False,
     "Let the station re-enable transmit by itself. With CQ selected this means "
     "it transmits unattended. Off is strongly recommended."),
    ("AUTO_FIX_DRIVE", "Correct drive automatically", "Safety", "bool", False, False,
     "After a transmission, if power or ALC is wrong for the band, fix the drive "
     "automatically. Only ever applied while the station is idle, never mid-QSO."),
    ("AUTO_DF", "Auto-place TX audio", "Safety", "bool", False, False,
     "Before a transmission you start, move the TX audio offset to a clear slot. "
     "Never transmits by itself."),
    ("SWR_TRIGGER", "Auto-tune SWR threshold", "Safety", "number", False, False,
     "Run the ATU when a transmission ends above this SWR."),
    ("TUNE_COOLDOWN", "Tune cooldown (s)", "Safety", "number", False, False,
     "Minimum gap between automatic tuner runs."),

    ("WSJTX_WINDOW", "WSJT-X window title", "Headless", "text", True, False,
     "Window to drive with xdotool. Only needed for headless stations."),
    ("WSJTX_UNIT", "WSJT-X systemd unit", "Headless", "text", True, False,
     "Unit restarted when changing transmit drive."),
    ("DISPLAY_NUM", "X display", "Headless", "text", True, False,
     "Virtual display WSJT-X runs on, e.g. :99."),
    ("NO_GUI", "Disable GUI automation", "Headless", "bool", True, False,
     "Force UDP-only operation even if xdotool is present."),
]

BOOLS = {"1": True, "true": True, "yes": True, "on": True}


def _get(key, default=""):
    return os.environ.get(f"FT8XSS_{key}", default)


def current(reveal_secrets=False):
    """Values as the running process sees them, secrets masked by default."""
    out = []
    for key, label, section, typ, restart, secret, helptext in SCHEMA:
        val = _get(key)
        if secret and not reveal_secrets:
            val = "********" if val else ""
        if typ == "bool":
            val = str(BOOLS.get(str(val).lower(), False)).lower()
        out.append({"key": key, "label": label, "section": section,
                    "type": typ, "restart": restart, "secret": secret,
                    "help": helptext, "value": val})
    return out


def read_file():
    try:
        txt = ENV_FILE.read_text(errors="ignore")
    except OSError:
        return {}
    vals = {}
    for line in txt.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        vals[k.strip()] = v.strip()
    return vals


def save(updates):
    """Merge updates into the env file. Returns (written, restart_needed).

    A masked secret is left untouched, so submitting the form does not wipe a
    key the user could not see.
    """
    by_key = {k: (typ, restart, secret)
              for k, _, _, typ, restart, secret, _ in SCHEMA}
    existing = read_file()
    restart_needed = False
    written = []

    for key, raw in (updates or {}).items():
        if key not in by_key:
            continue
        typ, restart, secret = by_key[key]
        val = "" if raw is None else str(raw).strip()
        if secret and set(val) == {"*"}:
            continue                       # untouched masked field
        if typ == "bool":
            val = "1" if str(val).lower() in ("1", "true", "yes", "on") else "0"
        if typ == "number" and val and not re.fullmatch(r"-?\d+(\.\d+)?", val):
            continue                       # ignore junk rather than corrupt config
        name = f"FT8XSS_{key}"
        if existing.get(name) != val:
            restart_needed = restart_needed or restart
        existing[name] = val
        written.append(key)
        # apply immediately for settings that do not need a restart
        if not restart:
            os.environ[name] = val

    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    body = ["# ft8xss settings -- written by the web interface.",
            "# Restart the service after changing anything marked 'restart'.", ""]
    body += [f"{k}={v}" for k, v in sorted(existing.items())]
    ENV_FILE.write_text("\n".join(body) + "\n")
    try:
        ENV_FILE.chmod(0o600)              # it holds an API key
    except OSError:
        pass
    return written, restart_needed
