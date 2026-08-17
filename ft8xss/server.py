#!/usr/bin/env python3
"""ft8web - browser front end for a headless WSJT-X / WSJT-X station.

Binds the WSJT-X UDP port, decodes the Qt DataStream protocol, and serves a
live web UI over WebSocket. Supports click-to-call (Reply packets) and
automatic QRZ logbook upload of logged QSOs.
"""
import asyncio
import html as _html
import json
import os
import re
import struct
import time
from datetime import datetime, timezone
from math import radians, degrees, sin, cos, asin, atan2, sqrt
from pathlib import Path

from aiohttp import web, ClientSession

import dxcc
import gui
from bandsetup import BandSetup

MAGIC = 0xADBCCBDA
def _env(name, default=""):
    """Read FT8XSS_<NAME>, falling back to the older FT8WEB_ prefix."""
    return os.environ.get(f"FT8XSS_{name}",
                          os.environ.get(f"FT8WEB_{name}", default))


UDP_PORT = int(_env("UDP_PORT", "2237"))
HTTP_PORT = int(_env("HTTP_PORT", "8073"))
BIND_ADDR = _env("BIND", "0.0.0.0")
MY_GRID = _env("GRID").strip().upper()
MY_CALL = _env("CALL").strip().upper()
QRZ_KEY = _env("QRZ_KEY").strip()
LOG_ADIF = Path(_env("ADIF", str(Path.home() / "ft8xss-uploads.adif")))
# Which WSJT-X window and service to drive when the headless helper is used.
WSJTX_WINDOW = _env("WSJTX_WINDOW", "WSJT-X")
WSJTX_UNIT = _env("WSJTX_UNIT", "wsjtx.service")
# WSJT-X's ADIF log. Override to point at a different logbook, or at test
# data when producing screenshots.
WORKED_FILES = [Path(_env("LOG", str(Path.home() /
                                     ".local/share/WSJT-X/wsjtx_log.adi")))]
STATIC = Path(__file__).parent / "static"
XDOTOOL_DISPLAY = _env("DISPLAY_NUM", ":99")
# Auto-arming Enable Tx means the station calls CQ unattended whenever
# Tx6 is selected. Off by default -- the operator opts in.
AUTO_ARM = _env("AUTO_ARM", "0") == "1"
# If a browser has been driving the station and then stops responding, stop
# transmitting. Idea from w5eez/ft8web. 0 disables.
DEADMAN_SECS = float(_env("DEADMAN", "12"))
MAX_DECODES = 400

# ---------------------------------------------------------------- Qt decoding


class Reader:
    def __init__(self, buf):
        self.b, self.i = buf, 0

    def _take(self, n):
        if self.i + n > len(self.b):
            raise EOFError
        v = self.b[self.i:self.i + n]
        self.i += n
        return v

    def u32(self):
        return struct.unpack(">I", self._take(4))[0]

    def i32(self):
        return struct.unpack(">i", self._take(4))[0]

    def u64(self):
        return struct.unpack(">Q", self._take(8))[0]

    def f64(self):
        return struct.unpack(">d", self._take(8))[0]

    def u8(self):
        return self._take(1)[0]

    def boolean(self):
        return self._take(1)[0] != 0

    def string(self):
        n = self.u32()
        if n == 0xFFFFFFFF:
            return ""
        return self._take(n).decode("utf-8", "replace")


def qstring(s):
    if s is None:
        return struct.pack(">I", 0xFFFFFFFF)
    b = s.encode()
    return struct.pack(">I", len(b)) + b


# ---------------------------------------------------------------- geo helpers


def grid_to_latlon(g):
    g = (g or "").strip().upper()
    if len(g) < 4:
        return None
    try:
        lon = (ord(g[0]) - 65) * 20 - 180 + (ord(g[2]) - 48) * 2
        lat = (ord(g[1]) - 65) * 10 - 90 + (ord(g[3]) - 48)
        if len(g) >= 6:
            lon += (ord(g[4]) - 65) * (2 / 24) + 1 / 24
            lat += (ord(g[5]) - 65) * (1 / 24) + 1 / 48
        else:
            lon, lat = lon + 1, lat + 0.5
        return lat, lon
    except (IndexError, ValueError):
        return None


def dist_bearing(a, b):
    if not a or not b:
        return None, None
    la1, lo1, la2, lo2 = map(radians, [a[0], a[1], b[0], b[1]])
    dlon, dlat = lo2 - lo1, la2 - la1
    h = sin(dlat / 2) ** 2 + cos(la1) * cos(la2) * sin(dlon / 2) ** 2
    d = 6371 * 2 * asin(sqrt(h))
    br = (degrees(atan2(sin(dlon) * cos(la2),
                        cos(la1) * sin(la2) - sin(la1) * cos(la2) * cos(dlon))) + 360) % 360
    return round(d), round(br)


HOME = grid_to_latlon(MY_GRID)

# (low_hz, high_hz, label) -- amateur allocations we might sit in
BAND_PLAN = [
    (1_800_000, 2_000_000, "160m"), (3_500_000, 4_000_000, "80m"),
    (5_250_000, 5_450_000, "60m"), (7_000_000, 7_300_000, "40m"),
    (10_100_000, 10_150_000, "30m"), (14_000_000, 14_350_000, "20m"),
    (18_068_000, 18_168_000, "17m"), (21_000_000, 21_450_000, "15m"),
    (24_890_000, 24_990_000, "12m"), (28_000_000, 29_700_000, "10m"),
    (50_000_000, 54_000_000, "6m"), (144_000_000, 148_000_000, "2m"),
    (222_000_000, 225_000_000, "1.25m"), (420_000_000, 450_000_000, "70cm"),
]


def band_of(hz):
    if not hz:
        return ""
    for lo, hi, label in BAND_PLAN:
        if lo <= hz <= hi:
            return label
    return f"{hz / 1e6:.3f}"

CALL_RE = re.compile(r"^[A-Z0-9]{1,3}\d[A-Z0-9]*[A-Z](/[A-Z0-9]+)?$")
_GRID_RE = re.compile(r"^[A-R]{2}\d{2}$")
# RR73 / RRR / 73 are acknowledgements, not locations. RR73 in particular
# matches the Maidenhead pattern and would yield a bogus grid and distance.
NOT_GRIDS = {"RR73", "RRR", "73", "R73"}


def GRID_RE_match(tok):
    return bool(_GRID_RE.match(tok)) and tok not in NOT_GRIDS


class GRID_RE:  # keep call sites readable
    match = staticmethod(GRID_RE_match)


def parse_message(msg):
    """Return (sender, addressee, grid, is_cq) from an FT8 message."""
    t = msg.replace("<", "").replace(">", "").split()
    if not t:
        return None, None, "", False
    if t[0] == "CQ":
        rest = t[1:]
        # skip directional tags such as CQ DX / CQ POTA / CQ NA
        while rest and not CALL_RE.match(rest[0]):
            rest = rest[1:]
        if not rest:
            return None, None, "", True
        grid = rest[1] if len(rest) > 1 and GRID_RE.match(rest[1]) else ""
        return rest[0], None, grid, True
    if len(t) >= 2:
        grid = t[2] if len(t) > 2 and GRID_RE.match(t[2]) else ""
        return t[1], t[0], grid, False
    return None, None, "", False


def load_worked():
    worked = set()
    for p in WORKED_FILES:
        try:
            txt = p.read_text(errors="ignore")
        except OSError:
            continue
        worked |= {c.upper() for c in re.findall(r"<call:\d+>([^<\s]+)", txt, re.I)}
    return worked


# ---------------------------------------------------------------- app state


class Station:
    def __init__(self):
        self.status = {}
        self.decodes = []
        self.qsos = []
        self.worked = load_worked()
        self.worked_entities = {e for e in (dxcc.entity(c) for c in self.worked) if e}
        self.clients = set()
        self.wsjtx_addr = None
        self.wsjtx_id = "WSJT-X"
        self.seq = 0
        self.last_tx_msg = None
        self.last_tx_at = 0.0
        self.rig = {}
        self.last_decode_ts = 0.0
        self.psk = {"count": 0, "median": None, "top": [], "at": None}
        self.bands = {"at": None, "sfi": None, "k": None, "a": None,
                      "sun": None, "cond": {}}
        self.last_dial = None
        self.tune = {"last": 0.0, "count": 0, "swr": None, "msg": None}
        self.txfix = {"state": "unknown"}
        self.bandfix = {}
        self.busy_band = False
        self.last_beat = 0.0
        self.ever_beat = False
        self.uploads = {"ok": 0, "failed": 0, "last": None}

    async def broadcast(self, kind, payload):
        if not self.clients:
            return
        msg = json.dumps({"type": kind, "data": payload})
        dead = []
        for ws in self.clients:
            try:
                await ws.send_str(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


ST = Station()


# ---------------------------------------------------------------- UDP handler


async def _rearm_after_qso():
    if not AUTO_ARM:
        return
    await asyncio.sleep(4)
    if ST.status.get("tx_enabled") is False:
        ok = await arm_tx()
        print(f"[armtx] re-armed after QSO: {ok}", flush=True)


async def _push_card(call):
    card = await lookup_call(call)
    await ST.broadcast("card", card)


class WsjtxProtocol(asyncio.DatagramProtocol):
    def __init__(self, loop):
        self.loop = loop
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        print(f"[udp] listening on :{UDP_PORT}", flush=True)

    def datagram_received(self, data, addr):
        try:
            r = Reader(data)
            if r.u32() != MAGIC:
                return
            r.u32()                      # schema
            ptype = r.u32()
            wid = r.string()
        except Exception:
            return
        ST.wsjtx_addr = addr
        ST.wsjtx_id = wid or ST.wsjtx_id
        try:
            if ptype == 1:
                self._status(r)
            elif ptype == 2:
                self._decode(r)
            elif ptype == 12:
                self._logged_adif(r)
        except EOFError:
            pass
        except Exception as e:
            print(f"[udp] parse error type={ptype}: {e}", flush=True)

    # --- packet handlers -------------------------------------------------
    def _status(self, r):
        s = {
            "dial": r.u64(), "mode": r.string(), "dx_call": r.string(),
            "report": r.string(), "tx_mode": r.string(),
            "tx_enabled": r.boolean(), "transmitting": r.boolean(),
            "decoding": r.boolean(), "rx_df": r.u32(), "tx_df": r.u32(),
            "de_call": r.string(), "de_grid": r.string(), "dx_grid": r.string(),
            "tx_watchdog": r.boolean(), "sub_mode": r.string(),
            "fast_mode": r.boolean(),
        }
        # remaining fields are optional across versions -- read what is there
        try:
            s["special_op"] = r.u8()
            s["freq_tolerance"] = r.u32()
            s["tr_period"] = r.u32()
            s["config_name"] = r.string()
            s["tx_message"] = r.string()
        except EOFError:
            pass

        prev = ST.status
        ST.status = s
        nb = band_of(s.get("dial"))
        if nb and nb != ST.last_dial:
            if ST.last_dial is not None:
                asyncio.create_task(band_setup(nb))
            ST.last_dial = nb
        dxc = (s.get("dx_call") or "").strip().upper()
        if dxc and dxc != (prev.get("dx_call") or "").strip().upper():
            asyncio.create_task(_push_card(dxc))
        # log our own transmissions: a new tx_message, or transmit just started
        txm = (s.get("tx_message") or "").strip()
        started = bool(s.get("transmitting")) and not bool(prev.get("transmitting"))
        changed = bool(txm) and txm != (ST.last_tx_msg or "")
        # guard against status bursts: WSJT-X can emit several status packets
        # for one transmission, and an identical message inside one T/R period
        # is the same transmission, not a new one.
        now = time.time()
        recent = (txm == (ST.last_tx_msg or "")
                  and now - getattr(ST, "last_tx_at", 0) < 12.0)
        if txm and (started or changed) and not recent:
            if _env("DEBUG_TX"):
                print(f"[tx] add started={started} changed={changed} "
                      f"prev_tx={prev.get('transmitting')} msg={txm!r}", flush=True)
            ST.last_tx_msg = txm
            ST.last_tx_at = now
            ST.seq += 1
            _, addressee, _, is_cq = parse_message(txm)
            tx = {
                "id": ST.seq, "tx": True,
                "utc": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                "tms": int(time.time() * 1000) % 86400000,
                "snr": 0, "dt": 0.0, "df": s.get("tx_df", 0),
                "mode": s.get("tx_mode", ""), "msg": txm, "low": False,
                "sender": MY_CALL, "to": addressee, "grid": "", "cq": is_cq,
                "km": None, "bearing": None, "worked": False, "to_me": False,
                "dial": s.get("dial"), "band": band_of(s.get("dial")),
                "entity": None, "new_entity": False,
            }
            ST.decodes.append(tx)
            if len(ST.decodes) > MAX_DECODES:
                del ST.decodes[:len(ST.decodes) - MAX_DECODES]
            asyncio.create_task(ST.broadcast("decode", tx))
        asyncio.create_task(ST.broadcast("status", s))

    def _decode(self, r):
        new = r.boolean()
        tms = r.u32()
        snr = r.i32()
        dt = round(r.f64(), 2)
        df = r.u32()
        mode = r.string()
        msg = r.string()
        low = r.boolean()
        if not new:
            return
        sender, addressee, grid, is_cq = parse_message(msg)
        km, brg = dist_bearing(HOME, grid_to_latlon(grid)) if grid else (None, None)
        ST.seq += 1
        d = {
            "id": ST.seq,
            "utc": time.strftime("%H:%M:%S", time.gmtime(tms / 1000)),
            "tms": tms, "snr": snr, "dt": dt, "df": df, "mode": mode,
            "msg": msg, "low": low,
            "sender": sender, "to": addressee, "grid": grid, "cq": is_cq,
            "km": km, "bearing": brg,
            "worked": bool(sender and sender.upper() in ST.worked),
            "to_me": addressee == MY_CALL,
        }
        dial = ST.status.get("dial")
        d["dial"] = dial
        d["band"] = band_of(dial)
        ent = dxcc.entity(sender)
        d["entity"] = ent
        d["new_entity"] = bool(ent and ent not in ST.worked_entities)
        ST.last_decode_ts = time.time()
        ST.decodes.append(d)
        if len(ST.decodes) > MAX_DECODES:
            del ST.decodes[:len(ST.decodes) - MAX_DECODES]
        asyncio.create_task(ST.broadcast("decode", d))

    def _logged_adif(self, r):
        adif = r.string()

        def fld(name, default=""):
            m = re.search(r"<%s:\d+(?::[A-Za-z])?>([^<]*)" % name, adif, re.I)
            return m.group(1).strip() if m else default

        call = fld("call", "?")
        grid = fld("gridsquare")
        t = fld("time_on") or fld("time_off")
        km, brg = dist_bearing(HOME, grid_to_latlon(grid)) if grid else (None, None)
        rec = {
            "adif": adif, "call": call, "grid": grid,
            "sent": fld("rst_sent"), "rcvd": fld("rst_rcvd"),
            "band": fld("band"), "mode": fld("mode"),
            "freq": fld("freq"), "date": fld("qso_date"),
            "time": f"{t[:2]}:{t[2:4]}:{t[4:6]}" if len(t) >= 6 else "",
            "km": km, "bearing": brg, "upload": "pending",
            "at": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        }
        ST.qsos.append(rec)
        if call and call != "?":
            ST.worked.add(call.upper())
            e = dxcc.entity(call)
            if e:
                ST.worked_entities.add(e)
                rec["entity"] = e
        try:
            with LOG_ADIF.open("a") as fh:
                fh.write(adif.strip() + "\n")
        except OSError:
            pass
        asyncio.create_task(ST.broadcast("qso", rec))
        asyncio.create_task(upload_qrz(adif, call, rec))
        # WSJT-X drops Enable Tx when a QSO closes; put it back
        asyncio.create_task(_rearm_after_qso())

    # --- outbound --------------------------------------------------------
    def send_reply(self, d):
        if not ST.wsjtx_addr:
            return False
        p = struct.pack(">III", MAGIC, 2, 4) + qstring(ST.wsjtx_id)
        p += struct.pack(">I", d["tms"])
        p += struct.pack(">i", d["snr"])
        p += struct.pack(">d", d["dt"])
        p += struct.pack(">I", d["df"])
        p += qstring(d["mode"])
        p += qstring(d["msg"])
        p += struct.pack(">?", d["low"])
        p += struct.pack(">B", 0)          # modifiers: none
        self.transport.sendto(p, ST.wsjtx_addr)
        return True

    def send_halt_tx(self, auto=False):
        if not ST.wsjtx_addr:
            return False
        p = struct.pack(">III", MAGIC, 2, 8) + qstring(ST.wsjtx_id)
        p += struct.pack(">?", auto)
        self.transport.sendto(p, ST.wsjtx_addr)
        return True

    def send_free_text(self, text, send=True):
        """Type 9. With send=True WSJT-X transmits it in the next slot.
        'CQ N0CALL AA00' encodes as a standard message, not literal free text."""
        if not ST.wsjtx_addr:
            return False
        p = struct.pack(">III", MAGIC, 2, 9) + qstring(ST.wsjtx_id)
        p += qstring(text) + struct.pack(">?", send)
        self.transport.sendto(p, ST.wsjtx_addr)
        return True

    def send_configure(self, mode="", ftol=0, submode="", fast=False,
                       tr_period=0, rx_df=0, dx_call="", dx_grid="",
                       gen_msgs=False):
        """Type 15. The subset of station settings the protocol exposes."""
        if not ST.wsjtx_addr:
            return False
        p = struct.pack(">III", MAGIC, 2, 15) + qstring(ST.wsjtx_id)
        p += qstring(mode)
        p += struct.pack(">I", ftol)
        p += qstring(submode)
        p += struct.pack(">?", fast)
        p += struct.pack(">II", tr_period, rx_df)
        p += qstring(dx_call) + qstring(dx_grid)
        p += struct.pack(">?", gen_msgs)
        self.transport.sendto(p, ST.wsjtx_addr)
        return True


PROTO = None


# ---------------------------------------------------------------- QRZ upload


async def upload_qrz(adif, call, rec=None):
    if not QRZ_KEY:
        ST.uploads["last"] = f"{call}: no API key configured"
        if rec is not None:
            rec["upload"] = "no key"
        await ST.broadcast("uploads", ST.uploads)
        await ST.broadcast("qso_update", rec or {})
        return
    body = {"KEY": QRZ_KEY, "ACTION": "INSERT", "ADIF": adif.strip()}
    try:
        async with ClientSession() as s:
            async with s.post("https://logbook.qrz.com/api", data=body,
                              timeout=20) as resp:
                text = await resp.text()
        if "RESULT=OK" in text:
            ST.uploads["ok"] += 1
            ST.uploads["last"] = f"{call}: uploaded"
            if rec is not None:
                rec["upload"] = "ok"
        else:
            ST.uploads["failed"] += 1
            reason = (re.search(r"REASON=([^&]*)", text) or [None, text[:60]])[1]
            ST.uploads["last"] = f"{call}: {reason}"
            if rec is not None:
                rec["upload"] = f"failed: {reason[:40]}"
    except Exception as e:
        ST.uploads["failed"] += 1
        ST.uploads["last"] = f"{call}: {type(e).__name__}"
        if rec is not None:
            rec["upload"] = f"failed: {type(e).__name__}"
    await ST.broadcast("uploads", ST.uploads)
    if rec is not None:
        await ST.broadcast("qso_update", rec)


# ---------------------------------------------------------------- HTTP / WS


async def ws_handler(req):
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(req)
    ST.clients.add(ws)
    await ws.send_str(json.dumps({"type": "snapshot", "data": {
        "status": ST.status, "decodes": ST.decodes[-200:],
        "qsos": ST.qsos[-30:], "uploads": ST.uploads, "rig": ST.rig,
        "psk": ST.psk, "tune": ST.tune, "bandfix": ST.bandfix,
        "bands": {**ST.bands, "recommend": recommend_band(band_of(ST.status.get("dial")))},
        "last_decode_age": (time.time() - ST.last_decode_ts) if ST.last_decode_ts else None,
        "entities": sorted(ST.worked_entities),
        "me": {"call": MY_CALL, "grid": MY_GRID},
        "caps": {"gui": gui.available(), "gui_reason": gui.reason()},
    }}))
    try:
        async for m in ws:
            if m.type != web.WSMsgType.TEXT:
                continue
            try:
                req_msg = json.loads(m.data)
            except ValueError:
                continue
            act = req_msg.get("action")
            if act == "call":
                d = next((x for x in ST.decodes if x["id"] == req_msg.get("id")), None)
                if d and ST.status.get("tx_enabled") is not True:
                    await set_tx(True)
                ok = PROTO.send_reply(d) if d else False
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "call", "ok": ok,
                    "who": d["sender"] if d else None}}))
            elif act == "halt":
                ok = await full_stop()
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "halt", "ok": ok,
                    "who": "stopped — TX disabled"}}))
            elif act == "beat":
                ST.last_beat = time.time()
                ST.ever_beat = True
            elif act == "bandsetup":
                b = band_of(ST.status.get("dial"))
                asyncio.create_task(band_setup(b))
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "bandsetup", "ok": bool(b), "who": b or "?"}}))
            elif act == "tune":
                cur = (ST.rig.get("peak") or {}).get("swr") or 0.0
                ok = await run_tuner(cur, manual=True)
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "tune", "ok": ok, "who": "ATU"}}))
            elif act == "armtx":
                ok = await arm_tx()
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "armtx", "ok": ok, "who": "Enable Tx"}}))
            elif act == "setfreq":
                try:
                    hz = int(req_msg.get("hz", 0))
                except (TypeError, ValueError):
                    hz = 0
                ok = False
                if 1_000_000 <= hz <= 500_000_000:
                    # drive the rig; WSJT-X follows the dial on its next poll
                    resp = await rig_cmd(f"F {hz}")
                    ok = resp is not None and "RPRT 0" in resp
                    if ok:
                        await asyncio.sleep(0.6)
                        cur = await rig_cmd("f")
                        ok = bool(cur and cur.isdigit() and abs(int(cur) - hz) < 100)
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "setfreq", "ok": ok, "who": f"{hz/1e6:.3f}"}}))
            elif act == "cq":
                grid = MY_GRID[:4].upper()
                text = f"CQ {MY_CALL} {grid}"
                # Call CQ is the explicit opt-in: arm the transmitter for it
                if ST.status.get("tx_enabled") is not True:
                    await set_tx(True)
                ok = PROTO.send_free_text(text, send=True)
                await ws.send_str(json.dumps({"type": "ack", "data": {
                    "action": "cq", "ok": ok, "who": text}}))
    finally:
        ST.clients.discard(ws)
    return ws


async def index(req):
    return web.FileResponse(STATIC / "index.html")


async def api_state(req):
    return web.json_response({
        "status": ST.status, "decodes": ST.decodes[-200:],
        "qsos": ST.qsos[-30:], "uploads": ST.uploads,
        "wsjtx": str(ST.wsjtx_addr), "worked_count": len(ST.worked),
        "rig": ST.rig, "psk": ST.psk, "tune": ST.tune, "bandfix": ST.bandfix,
        "bands": {**ST.bands, "recommend": recommend_band(band_of(ST.status.get("dial")))},
        "entities": sorted(ST.worked_entities),
        "caps": {"gui": gui.available(), "gui_reason": gui.reason()},
        "last_decode_age": (time.time() - ST.last_decode_ts) if ST.last_decode_ts else None,
    })


# ---------------------------------------------------------------- rig (rigctld)

RIG_HOST, RIG_PORT = "127.0.0.1", 4532
_rig_lock = asyncio.Lock()


async def rig_cmd(cmd, timeout=3.0):
    """One rigctld request. Short-lived connections keep us robust against
    rigctld restarts, and the traffic is trivial."""
    try:
        async with _rig_lock:
            r, w = await asyncio.wait_for(
                asyncio.open_connection(RIG_HOST, RIG_PORT), timeout)
            w.write((cmd + "\n").encode())
            await w.drain()
            data = await asyncio.wait_for(r.read(256), timeout)
            w.close()
            return data.decode(errors="replace").strip()
    except Exception:
        return None


async def rig_poll():
    """Poll the radio. Meters are only meaningful while transmitting, so we
    sample fast during TX and hold the peak of each transmission."""
    peak = {"po": 0.0, "alc": 0.0, "swr": 1.0}
    was_tx = False
    while True:
        try:
            tx = (await rig_cmd("t")) == "1"
            rig = {"ptt": tx}
            if tx:
                for key, lvl in (("po", "l RFPOWER_METER_WATTS"),
                                 ("alc", "l ALC"), ("swr", "l SWR")):
                    v = await rig_cmd(lvl)
                    try:
                        f = float(v)
                    except (TypeError, ValueError):
                        continue
                    rig[key] = round(f, 3)
                    if f > peak[key] or (key == "swr" and f > peak[key]):
                        peak[key] = round(f, 3)
                rig["peak"] = dict(peak)
                was_tx = True
            else:
                if was_tx:
                    rig["peak"] = dict(peak)      # keep the last TX peaks
                    # high SWR at the end of a transmission -> run the ATU,
                    # but only while idle and not more often than the cooldown
                    if (peak["swr"] >= SWR_TRIGGER
                            and peak["po"] > 1.0
                            and time.time() - ST.tune["last"] > TUNE_COOLDOWN):
                        asyncio.create_task(run_tuner(peak["swr"]))
                    was_tx = False
                    peak = {"po": 0.0, "alc": 0.0, "swr": 1.0}
                else:
                    rig["peak"] = ST.rig.get("peak", {})
                f = await rig_cmd("f")
                if f and f.isdigit():
                    rig["freq"] = int(f)
                m = await rig_cmd("m")
                if m:
                    rig["mode"] = m.split("\n")[0]
                p = await rig_cmd("l RFPOWER")
                try:
                    rig["rfpower_pct"] = round(float(p) * 100)
                except (TypeError, ValueError):
                    pass
                s = await rig_cmd("l STRENGTH")
                try:
                    rig["strength"] = int(float(s))
                except (TypeError, ValueError):
                    pass
            rig["ok"] = True
            ST.rig = rig
            await ST.broadcast("rig", rig)
        except Exception as e:
            ST.rig = {"ok": False, "error": type(e).__name__}
        await asyncio.sleep(0.7 if ST.rig.get("ptt") else 2.5)


UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")


def is_daylight():
    """Rough day/night at our QTH -- solar time from longitude."""
    if not HOME:
        return True
    lon = HOME[1]
    utc_h = datetime.now(timezone.utc).hour + datetime.now(timezone.utc).minute / 60
    solar = (utc_h + lon / 15.0) % 24
    return 6.5 <= solar < 18.5


# hamqsl band groups -> the FT8 dial we would actually use, best DX first
BAND_CHOICE = [
    ("12m-10m", "10m", 28_074_000),
    ("17m-15m", "15m", 21_074_000),
    ("30m-20m", "20m", 14_074_000),
    ("80m-40m", "40m", 7_074_000),
]
RANK = {"good": 3, "fair": 2, "poor": 1}


def recommend_band(current_band):
    """Suggest a band from current conditions. Prefers the highest-frequency
    band rated Good, since those carry the best DX when they are open."""
    cond = (ST.bands or {}).get("cond") or {}
    if not cond:
        return None
    period = "day" if is_daylight() else "night"
    scored = []
    for group, band, hz in BAND_CHOICE:
        v = (cond.get(group) or {}).get(period)
        if v:
            scored.append((RANK.get(v.lower(), 0), band, hz, v, group))
    if not scored:
        return None
    best_rank = max(s[0] for s in scored)
    if best_rank < 3:                       # nothing rated Good
        return None
    top = [s for s in scored if s[0] == best_rank][0]   # highest freq wins
    cur = next((s for s in scored if s[1] == current_band), None)
    if cur and cur[0] >= best_rank:
        return {"ok": True, "band": current_band, "rating": cur[3],
                "period": period, "msg": f"{current_band} is rated {cur[3]} — good place to be"}
    return {"ok": False, "band": top[1], "hz": top[2], "rating": top[3],
            "period": period,
            "msg": (f"{top[1]} is rated {top[3]} ({period})"
                    + (f" — better than {current_band}" if current_band else ""))}


SWR_TRIGGER = float(_env("SWR_TRIGGER", "2.0"))
TUNE_COOLDOWN = float(_env("TUNE_COOLDOWN", "300"))


async def run_tuner(swr_seen, manual=False):
    """Run the rig's ATU via hamlib vfo_op TUNE.

    Only fires between transmissions -- tuning keys the radio, so doing it
    mid-slot would corrupt the transmission and splatter the frequency.
    """
    ST.tune["last"] = time.time()
    if (await rig_cmd("t")) == "1":
        ST.tune["msg"] = "skipped: transmitting"
        await ST.broadcast("tune", ST.tune)
        return False
    ST.tune["msg"] = f"tuning (SWR was {swr_seen:.1f})…"
    await ST.broadcast("tune", ST.tune)
    resp = await rig_cmd("G TUNE")
    ok = resp is not None and "RPRT 0" in resp
    await asyncio.sleep(6)
    ST.tune["count"] += 1
    ST.tune["swr"] = swr_seen
    ST.tune["msg"] = (f"tuned at {datetime.now(timezone.utc):%H:%M} "
                      f"(SWR was {swr_seen:.1f})") if ok else f"tune failed: {resp}"
    await ST.broadcast("tune", ST.tune)
    print(f"[tune] swr={swr_seen:.2f} manual={manual} ok={ok}", flush=True)
    return ok


CALL_CACHE = {}


async def lookup_call(call):
    """FCC data for US calls via callook.info. Cached; returns {} on miss."""
    c = (call or "").upper().strip("<>")
    if not c:
        return {}
    if c in CALL_CACHE:
        return CALL_CACHE[c]
    out = {}
    try:
        async with ClientSession(headers={"User-Agent": UA}) as sess:
            async with sess.get(f"https://callook.info/{c}/json", timeout=12) as r:
                d = await r.json(content_type=None)
        if d.get("status") == "VALID":
            addr = d.get("address", {}) or {}
            loc = d.get("location", {}) or {}
            oi = d.get("otherInfo", {}) or {}
            grid = loc.get("gridsquare", "")
            km, brg = dist_bearing(HOME, grid_to_latlon(grid)) if grid else (None, None)
            out = {
                "call": c, "name": d.get("name", ""),
                "qth": addr.get("line2", ""),
                "cls": (d.get("current", {}) or {}).get("operClass", ""),
                "grid": grid, "km": km, "bearing": brg,
                "licensed": oi.get("grantDate", ""),
                "entity": dxcc.entity(c),
                "source": "FCC",
            }
    except Exception:
        out = {}
    if not out:
        out = {"call": c, "entity": dxcc.entity(c), "source": "prefix only"}
    CALL_CACHE[c] = out
    if len(CALL_CACHE) > 500:
        CALL_CACHE.pop(next(iter(CALL_CACHE)))
    return out


async def seed_from_qrz():
    """The local ADIF only covers recent QSOs, so 'new DXCC' would be wrong.
    Pull the full QRZ logbook once at startup for an accurate worked set."""
    if not QRZ_KEY:
        print("[qrz] no key; worked set is local ADIF only", flush=True)
        return
    try:
        async with ClientSession() as sess:
            async with sess.post("https://logbook.qrz.com/api",
                                 data={"KEY": QRZ_KEY, "ACTION": "FETCH",
                                       "OPTION": "ALL"}, timeout=90) as r:
                body = await r.text()
        adif = body
        if "ADIF=" in body:
            adif = body.split("ADIF=", 1)[1]
        # QRZ returns the ADIF HTML-escaped inside a urlencoded response
        adif = _html.unescape(adif)
        calls = {c.upper() for c in re.findall(r"<call:\d+>([^<\s]+)", adif, re.I)}
        if not calls:
            print(f"[qrz] fetch returned no calls ({body[:80]})", flush=True)
            return
        before_c, before_e = len(ST.worked), len(ST.worked_entities)
        ST.worked |= calls
        ST.worked_entities |= {e for e in (dxcc.entity(c) for c in calls) if e}
        print(f"[qrz] seeded {len(calls)} calls: worked {before_c}->{len(ST.worked)}, "
              f"entities {before_e}->{len(ST.worked_entities)}", flush=True)
        await ST.broadcast("entities", sorted(ST.worked_entities))
    except Exception as e:
        print(f"[qrz] seed failed: {type(e).__name__}: {e}", flush=True)


# Calibrated Pwr-slider attenuation per band (tenths of a dB), measured with
# calibrate.py: target is full power with ALC barely moving.
BAND_DRIVE = {"20m": 90, "15m": 105}
DRIVE_FILE = Path.home() / ".config/ft8web-drive.json"


def load_drive():
    try:
        BAND_DRIVE.update(json.loads(DRIVE_FILE.read_text()))
    except Exception:
        pass


def save_drive():
    try:
        DRIVE_FILE.write_text(json.dumps(BAND_DRIVE, indent=1))
    except OSError:
        pass


SPLIT_VARIANTS = {
    "none": "split_mode_none",
    "rig": "split_mode_rig",
    "fake": "split_mode_emulate",
}


def set_split_mode(mode="fake"):
    """Enable WSJT-X's own 'Fake It' split: it shifts the VFO on transmit so the
    audio tone sits near the middle of the SSB filter, avoiding power roll-off
    and splatter at the passband edges. Idea surfaced by ok1cdj/FT8web; WSJT-X
    implements it natively, so we just turn it on.
    """
    want = SPLIT_VARIANTS.get(mode, "split_mode_emulate")
    ini = Path.home() / ".config/WSJT-X.ini"
    try:
        txt = ini.read_text(errors="ignore")
    except OSError:
        return False
    m = re.search(r"^SplitMode=@Variant\(.*?\)$", txt, re.M)
    if not m:
        return False
    cur = m.group(0)
    if want in cur:
        return True
    # the Qt QVariant blob length-prefixes the enum name (len + 1 for the NUL)
    new = re.sub(r"\\0\\0\\0\\x[0-9a-f]{2}split_mode_[a-z]+\\0",
                 lambda _: "\\0\\0\\0\\x%02x%s\\0" % (len(want) + 1, want),
                 cur)
    if new == cur:
        return False
    ini.write_text(txt.replace(cur, new))
    return True


async def restart_wsjtx_with(att):
    """Set the Pwr attenuation and restart WSJT-X so it takes effect."""
    ini = Path.home() / ".config/WSJT-X.ini"

    def rewrite():
        try:
            txt = ini.read_text(errors="ignore")
            ini.write_text(re.sub(r"^OutAttenuation=.*$",
                                  f"OutAttenuation={att}", txt, flags=re.M))
        except OSError:
            pass

    ST.status = {}
    await gui.restart_wsjtx(prepare=rewrite)
    for _ in range(60):
        await asyncio.sleep(0.5)
        if ST.status.get("dial") and ST.status.get("tx_enabled") is not None:
            break
    await asyncio.sleep(3)
    print(f"[band] wsjtx back: dial={ST.status.get('dial')} "
          f"tx_enabled={ST.status.get('tx_enabled')}", flush=True)


async def _cq_once():
    """Arm (verifying) then transmit one CQ. Enable Tx never survives a
    WSJT-X restart, so this must confirm rather than assume."""
    for attempt in range(3):
        if ST.status.get("tx_enabled") is True:
            break
        ok = await set_tx(True)
        if ok:
            break
        print(f"[band] arm attempt {attempt + 1} failed", flush=True)
        await asyncio.sleep(2)
    else:
        print("[band] could not arm TX", flush=True)
        return False
    grid = MY_GRID[:4].upper()
    PROTO.send_free_text(f"CQ {MY_CALL} {grid}", send=True)
    return True


async def band_setup(band):
    """Tune if needed, then find the drive that gives full power with clean ALC.

    Needs GUI automation: measuring means transmitting, and changing the Pwr
    slider means restarting WSJT-X.
    """
    if ST.busy_band:
        return None
    if not gui.available():
        ST.bandfix = {"band": band, "state": "unavailable", "err": gui.reason()}
        await ST.broadcast("bandfix", ST.bandfix)
        return ST.bandfix
    ST.busy_band = True
    ST.bandfix = {"band": band, "state": "running"}
    await ST.broadcast("bandfix", ST.bandfix)
    try:
        pct = (ST.rig or {}).get("rfpower_pct") or 25
        target = pct                       # rig is 100W nominal -> pct == watts
        bs = BandSetup(
            rig_cmd=rig_cmd, set_tx=set_tx, send_cq=_cq_once,
            get_status=lambda: ST.status,
            log=lambda m: print(m, flush=True),
            restart_wsjtx=restart_wsjtx_with, target_watts=target)
        res = await bs.run(band)
        ST.bandfix = {"band": band, "state": "done", **(res or {"ok": False})}
    except Exception as e:
        ST.bandfix = {"band": band, "state": "error", "err": f"{type(e).__name__}: {e}"}
        print(f"[band] {band}: {type(e).__name__}: {e}", flush=True)
    finally:
        ST.busy_band = False
    await ST.broadcast("bandfix", ST.bandfix)
    return ST.bandfix


PHOTO_CACHE = {}
PLACEHOLDER = "qrz_com200x150"


async def qrz_photo(call):
    """Public og:image from the QRZ profile page. No API key required.
    Cached hard -- one request per callsign, ever."""
    c = (call or "").upper().strip("<>")
    if not c:
        return {}
    if c in PHOTO_CACHE:
        return PHOTO_CACHE[c]
    out = {"call": c, "photo": None}
    try:
        async with ClientSession(headers={"User-Agent": UA}) as sess:
            async with sess.get(f"https://www.qrz.com/db/{c}", timeout=15,
                                allow_redirects=True) as r:
                html = await r.text()
        m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', html, re.I)
        if m and PLACEHOLDER not in m.group(1):
            out["photo"] = m.group(1)
    except Exception:
        pass
    PHOTO_CACHE[c] = out
    if len(PHOTO_CACHE) > 800:
        PHOTO_CACHE.pop(next(iter(PHOTO_CACHE)))
    return out


async def deadman():
    """Stop transmitting if the browser that armed the station goes away.

    Only arms once a client has actually been heartbeating, so a station
    driven from the WSJT-X GUI alone is unaffected.
    """
    if DEADMAN_SECS <= 0:
        return
    tripped = False
    while True:
        await asyncio.sleep(2)
        if not ST.ever_beat:
            continue
        stale = time.time() - ST.last_beat
        live = any(not w.closed for w in ST.clients)
        if ST.status.get("tx_enabled") is True and not live and stale > DEADMAN_SECS:
            if not tripped:
                tripped = True
                print(f"[deadman] no browser for {stale:.0f}s and TX armed "
                      f"-- stopping", flush=True)
                await full_stop()
                ST.txfix = {"state": "deadman", "note": f"no client for {stale:.0f}s"}
                await ST.broadcast("txfix", ST.txfix)
        elif live:
            tripped = False


async def tx_watchdog():
    """Enable Tx is not persisted by WSJT-X and gets dropped after QSOs and
    restarts. Rather than just warn, put it back -- and only surface a warning
    if re-arming actually fails."""
    disabled_since = None
    attempts = 0
    while True:
        await asyncio.sleep(5)
        te = ST.status.get("tx_enabled")
        if te is None:                       # no status yet: nothing to judge
            continue
        if te:
            disabled_since, attempts = None, 0
            ST.txfix = {"state": "ok"}
            continue
        now = time.time()
        if disabled_since is None:
            disabled_since = now
            continue
        # let a restart settle before deciding anything is wrong
        if now - disabled_since < 20 or attempts >= 3:
            continue
        if not AUTO_ARM:
            ST.txfix = {"state": "disabled", "note": "auto-arm off"}
            continue
        attempts += 1
        ok = await arm_tx()
        ST.txfix = {"state": "recovering", "attempt": attempts, "ok": ok}
        print(f"[txwd] tx disabled {now - disabled_since:.0f}s; "
              f"re-arm attempt {attempts} -> {ok}", flush=True)
        await ST.broadcast("txfix", ST.txfix)
        disabled_since = now if not ok else None


async def psk_poll():
    """Who is hearing us right now, straight from PSK Reporter."""
    url = ("https://retrieve.pskreporter.info/query?senderCallsign="
           f"{MY_CALL}&flowStartSeconds=-900")
    while True:
        try:
            async with ClientSession(headers={"User-Agent": UA}) as s:
                async with s.get(url, timeout=25) as r:
                    body = await r.text()
            best = {}
            for m in re.finditer(r'receiverCallsign="([^"]+)".*?'
                                 r'receiverLocator="([^"]+)".*?sNR="([-\d]+)"', body):
                c, g, snr = m.group(1).upper(), m.group(2), int(m.group(3))
                if c not in best or snr > best[c][1]:
                    best[c] = (g, snr)
            snrs = sorted(v[1] for v in best.values())
            ST.psk = {
                "count": len(best),
                "median": snrs[len(snrs) // 2] if snrs else None,
                "best": snrs[-1] if snrs else None,
                "top": [{"call": c, "grid": g, "snr": s2}
                        for c, (g, s2) in sorted(best.items(),
                                                 key=lambda kv: -kv[1][1])[:8]],
                "at": datetime.now(timezone.utc).strftime("%H:%M"),
            }
            await ST.broadcast("psk", ST.psk)
        except Exception as e:
            ST.psk["error"] = type(e).__name__
        await asyncio.sleep(180)


async def bands_poll():
    """Full solar/propagation picture from hamqsl."""
    while True:
        try:
            async with ClientSession(headers={"User-Agent": UA}) as sess:
                async with sess.get("https://www.hamqsl.com/solarxml.php",
                                    timeout=25) as r:
                    xml = await r.text()

            def tag(name):
                m = re.search(rf"<{name}>\s*([^<>]*?)\s*</{name}>", xml, re.I)
                v = m.group(1).strip() if m else None
                return v or None

            cond = {}
            for m in re.finditer(r'<band name="([^"]+)" time="([^"]+)">([^<]+)</band>',
                                 xml, re.I):
                cond.setdefault(m.group(1), {})[m.group(2).lower()] = m.group(3).strip()
            vhf = {}
            for m in re.finditer(r'<phenomenon name="([^"]+)" location="([^"]+)">'
                                 r'([^<]+)</phenomenon>', xml, re.I):
                vhf[f"{m.group(1)}/{m.group(2)}"] = m.group(3).strip()

            ST.bands = {
                "updated": tag("updated"),
                "sfi": tag("solarflux"), "sun": tag("sunspots"),
                "a": tag("aindex"), "k": tag("kindex"),
                "geomag": tag("geomagfield"),
                "xray": tag("xray"), "muf": tag("muf"),
                "sn": tag("signalnoise"),
                "solarwind": tag("solarwind"), "bz": tag("magneticfield"),
                "protonflux": tag("protonflux"), "electronflux": tag("electonflux"),
                "helium": tag("heliumline"),
                "aurora": tag("aurora"), "auroralat": tag("latdegree"),
                "cond": cond, "vhf": vhf,
                "at": datetime.now(timezone.utc).strftime("%H:%M"),
            }
            ST.bands["recommend"] = recommend_band(band_of(ST.status.get("dial")))
            await ST.broadcast("bands", ST.bands)
        except Exception as e:
            ST.bands["error"] = type(e).__name__
        await asyncio.sleep(900)


async def set_tx(want, tries=3):
    """Enable/disable transmit. Needs GUI automation -- WSJT-X does not expose
    Enable Tx over UDP. Without it the operator does this in the GUI."""
    if not gui.available():
        return False
    return await gui.set_tx(want, lambda: ST.status.get("tx_enabled"), tries)


async def click_at(dx, dy):
    return await gui.click_at(dx, dy) if gui.available() else False


async def arm_tx():
    return await set_tx(True)


async def full_stop():
    """Halt means stop: kill the transmission, drop auto-sequence, and
    disable Enable Tx so nothing transmits again until explicitly asked."""
    PROTO.send_halt_tx(auto=True)          # stop TX and auto-sequencing
    await asyncio.sleep(0.4)
    # Disabling Enable Tx needs the GUI. Without it we can still halt the
    # transmission and drop PTT, but WSJT-X may transmit again on its own.
    off = await set_tx(False) if gui.available() else False
    # belt and braces: make sure PTT is actually down
    if (await rig_cmd("t")) == "1":
        await rig_cmd("T 0")
    ST.txfix = {"state": "halted", "tx_enabled": ST.status.get("tx_enabled"),
                "full": bool(gui.available())}
    await ST.broadcast("txfix", ST.txfix)
    print(f"[halt] full stop; tx_enabled now "
          f"{ST.status.get('tx_enabled')} (set_tx ok={off})", flush=True)
    # without GUI automation, halting the transmission is still a success
    return True if not gui.available() else off


async def arm_tx():
    """Enable Tx via the GUI -- WSJT-X never persists this checkbox, so it is
    off after every restart and there is no UDP message for it."""
    env = {**os.environ, "DISPLAY": XDOTOOL_DISPLAY}

    async def run(*args):
        pr = await asyncio.create_subprocess_exec(
            *args, env=env, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL)
        out, _ = await pr.communicate()
        return out.decode(errors="replace").strip()

    wid = (await run("xdotool", "search", "--name", "WSJT-X MOD")).splitlines()
    if not wid:
        return False
    await run("xdotool", "windowfocus", "--sync", wid[0])
    await asyncio.sleep(0.4)
    await run("xdotool", "key", "--clearmodifiers", "alt+n")
    await asyncio.sleep(1.5)
    return True


ADIF_FIELD = re.compile(r"<([A-Za-z_0-9]+):(\d+)(?::[A-Za-z])?>")


def parse_adif(text):
    """Yield dicts for each <eor>-terminated record."""
    out, rec, i = [], {}, 0
    for m in ADIF_FIELD.finditer(text):
        name, ln = m.group(1).lower(), int(m.group(2))
        val = text[m.end():m.end() + ln]
        rec[name] = val.strip()
    # simple split approach: records are separated by <eor>
    out = []
    for chunk in re.split(r"<eor>", text, flags=re.I):
        rec = {}
        for m in ADIF_FIELD.finditer(chunk):
            name, ln = m.group(1).lower(), int(m.group(2))
            rec[name] = chunk[m.end():m.end() + ln].strip()
        if rec.get("call"):
            out.append(rec)
    return out


async def api_log(req):
    """Full logbook, parsed, with distance/bearing/entity added."""
    rows = []
    try:
        text = WORKED_FILES[0].read_text(errors="ignore")
    except OSError:
        text = ""
    for rec in parse_adif(text):
        grid = rec.get("gridsquare", "")
        km, brg = dist_bearing(HOME, grid_to_latlon(grid)) if grid else (None, None)
        d = rec.get("qso_date", "")
        t = rec.get("time_on", "") or rec.get("time_off", "")
        rows.append({
            "call": rec.get("call", ""), "grid": grid,
            "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d,
            "time": f"{t[:2]}:{t[2:4]}" if len(t) >= 4 else t,
            "band": rec.get("band", ""), "mode": rec.get("mode", ""),
            "freq": rec.get("freq", ""),
            "sent": rec.get("rst_sent", ""), "rcvd": rec.get("rst_rcvd", ""),
            "km": km, "bearing": brg, "entity": dxcc.entity(rec.get("call", "")),
        })
    rows.reverse()
    ents = {}
    for r in rows:
        if r["entity"]:
            ents[r["entity"]] = ents.get(r["entity"], 0) + 1
    return web.json_response({
        "qsos": rows, "total": len(rows),
        "entities": sorted(ents.items(), key=lambda kv: -kv[1]),
        "bands": sorted({r["band"] for r in rows if r["band"]}),
    })


async def api_photo(req):
    return web.json_response(await qrz_photo(req.match_info["call"]))


async def api_call(req):
    return web.json_response(await lookup_call(req.match_info["call"]))


async def main():
    global PROTO
    loop = asyncio.get_running_loop()
    PROTO = WsjtxProtocol(loop)
    await loop.create_datagram_endpoint(lambda: PROTO, local_addr=("0.0.0.0", UDP_PORT))
    asyncio.create_task(rig_poll())
    asyncio.create_task(psk_poll())
    asyncio.create_task(bands_poll())
    asyncio.create_task(seed_from_qrz())
    asyncio.create_task(tx_watchdog())
    asyncio.create_task(deadman())

    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/call/{call}", api_call)
    app.router.add_get("/api/log", api_log)
    app.router.add_get("/api/photo/{call}", api_photo)
    app.router.add_static("/static/", STATIC)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, BIND_ADDR, HTTP_PORT).start()
    print(f"[gui] automation: "
          f"{'available -- ' if gui.available() else 'unavailable -- '}{gui.reason()}",
          flush=True)
    if not MY_CALL or not MY_GRID:
        print("[config] FT8XSS_CALL and FT8XSS_GRID are required "
              "(set them in ~/.config/ft8xss.env)", flush=True)
    print(f"[http] http://{BIND_ADDR}:{HTTP_PORT}  (worked calls loaded: {len(ST.worked)})",
          flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
