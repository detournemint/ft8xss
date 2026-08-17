#!/usr/bin/env python3
"""Build the static demo published on GitHub Pages.

The demo is the real interface -- the same HTML, CSS and JavaScript the station
serves -- with the network layer replaced by a shim that answers from canned
data. Nothing is reimplemented, so the demo cannot drift from the product: it
is regenerated from `ft8xss/static/index.html` every time.

    python3 docs/build_demo.py        # writes docs/demo/index.html

Every control is inert. Anything that would key a transmitter answers with a
refusal, because there is no transmitter.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "ft8xss"
OUT = ROOT / "docs" / "demo" / "index.html"

# import the real helpers so distances, bearings and entities in the demo are
# computed exactly as the station computes them
os.environ.setdefault("FT8XSS_CALL", "N0CALL")
os.environ.setdefault("FT8XSS_GRID", "CM87ws")
os.environ.setdefault("FT8XSS_NO_GUI", "1")
sys.path.insert(0, str(PKG))
import dxcc                                                    # noqa: E402
import server                                                  # noqa: E402

HOME_CALL, HOME_GRID = "N0CALL", "CM87ws"
HOME = server.grid_to_latlon(HOME_GRID)

# the same traffic the screenshot feed uses, so demo and screenshots agree
TRAFFIC = [
    (-7, 0.2, 1240, "CQ VK3ANP QF22"),
    (-13, 0.1, 1478, "CQ JA1XYZ PM95"),
    (3, -0.3, 902, "N0CALL EA5TT IM98"),
    (-19, 0.4, 2104, "CQ DL9ZZZ JO62"),
    (-2, 0.0, 1655, "CQ LU4AA GF05"),
    (-9, 0.1, 660, "CQ POTA W7ABC CN87"),
    (-15, 0.3, 2410, "CQ SV1EAG KM17"),
    (5, 0.1, 1120, "CQ K5DXX EM12"),
    (-11, 0.2, 1830, "W6TOX ZL2AAA RE78"),
    (-4, 0.1, 980, "CQ VE6NIX DO31"),
    (-17, 0.5, 2280, "CQ 3D2USU RH82"),
    (0, 0.1, 1390, "CQ KB9XYZ EN52"),
    (-21, 0.2, 745, "CQ TF3ABC HP94"),
    (-6, 0.0, 2050, "CQ CT1FMX IM58"),
    (8, 0.1, 1705, "CQ W1AW FN31"),
    (-16, 0.2, 880, "CQ PY2XYZ GG66"),
    (-1, 0.1, 2190, "CQ OH2BBB KP20"),
]

DIAL = 14074000
WORKED = {"W1AW", "K5DXX", "VE6NIX", "PY2XYZ"}


def decode(idx, snr, dt, df, msg, when):
    sender, addressee, grid, is_cq = server.parse_message(msg)
    km, brg = (server.dist_bearing(HOME, server.grid_to_latlon(grid))
               if grid else (None, None))
    ent = dxcc.entity(sender) if sender else None
    return {
        "id": idx, "tx": False,
        "utc": when.strftime("%H:%M:%S"),
        "tms": ((when.hour * 60 + when.minute) * 60 + when.second) * 1000,
        "snr": snr, "dt": dt, "df": df, "mode": "~", "msg": msg,
        "low": snr <= -20, "sender": sender, "to": addressee, "grid": grid,
        "cq": is_cq, "km": km, "bearing": brg,
        "worked": sender in WORKED, "to_me": addressee == HOME_CALL,
        "dial": DIAL, "band": server.band_of(DIAL),
        "entity": ent, "new_entity": bool(ent) and sender not in WORKED,
    }


def build_decodes():
    """Three T/R cycles of traffic, oldest first, with one of our own overs."""
    now = datetime.now(timezone.utc).replace(microsecond=0)
    out, idx = [], 1
    for cycle in range(3):
        when = now - timedelta(seconds=15 * (2 - cycle))
        for snr, dt, df, msg in TRAFFIC:
            out.append(decode(idx, snr + (cycle - 1), dt, df, msg, when))
            idx += 1
        if cycle == 1:
            # our own transmission, shown as a TX row and never callable
            t = when + timedelta(seconds=7)
            out.append({
                "id": idx, "tx": True, "utc": t.strftime("%H:%M:%S"),
                "tms": ((t.hour * 60 + t.minute) * 60 + t.second) * 1000,
                "snr": 0, "dt": 0.0, "df": 1620, "mode": "~",
                "msg": f"EA5TT {HOME_CALL} -09", "low": False,
                "sender": HOME_CALL, "to": "EA5TT", "grid": "", "cq": False,
                "km": None, "bearing": None, "worked": False, "to_me": False,
                "dial": DIAL, "band": server.band_of(DIAL),
                "entity": None, "new_entity": False,
            })
            idx += 1
    return out


def build_qsos():
    now = datetime.now(timezone.utc)
    rows = []
    for i, (call, grid, band, sent, rcvd) in enumerate([
            ("W1AW", "FN31pr", "20m", "-09", "-12"),
            ("PY2XYZ", "GG66rc", "20m", "-15", "-18"),
            ("VE6NIX", "DO31", "20m", "+02", "-04"),
            ("K5DXX", "EM12", "40m", "-06", "-08")]):
        t = now - timedelta(minutes=11 * (i + 1))
        km, brg = server.dist_bearing(HOME, server.grid_to_latlon(grid))
        rows.append({
            "call": call, "grid": grid, "band": band, "mode": "FT8",
            "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
            "utc": t.strftime("%H:%M:%S"), "freq": "14.074",
            "sent": sent, "rcvd": rcvd, "km": km, "bearing": brg,
            "entity": dxcc.entity(call),
        })
    return rows


def build_snapshot():
    decodes = build_decodes()
    qsos = build_qsos()
    return {
        "status": {
            "dial": DIAL, "mode": "FT8", "dx_call": "EA5TT", "report": "-09",
            "tx_mode": "FT8", "tx_enabled": False, "transmitting": False,
            "decoding": False, "rx_df": 1500, "tx_df": 1620,
            "de_call": HOME_CALL, "de_grid": HOME_GRID, "dx_grid": "IM98",
            "tx_watchdog": False, "sub_mode": "", "fast_mode": False,
            "tx_message": "EA5TT N0CALL -09",
        },
        "decodes": decodes,
        "qsos": qsos,
        "uploads": {"ok": 4, "failed": 0, "last": "K5DXX: uploaded"},
        "rig": {"ok": True, "power": True, "ptt": False, "freq": DIAL,
                "mode": "PKTUSB", "rfpower_pct": 25, "strength": -14,
                "peak": {"po": 23.4, "alc": 0.11, "swr": 1.2}},
        "psk": {"count": 37, "median": -13, "best": -3, "at": "12:44",
                "top": [{"call": "VK3ANP", "snr": -3, "km": 12690},
                        {"call": "JA1XYZ", "snr": -8, "km": 8420},
                        {"call": "DL9ZZZ", "snr": -11, "km": 9150},
                        {"call": "LU4AA", "snr": -14, "km": 10240},
                        {"call": "OH2BBB", "snr": -19, "km": 8480}]},
        "tune": {"last": 0.0, "count": 1, "swr": 1.2, "msg": "ATU: SWR 1.2"},
        "bandfix": {"band": "20m", "state": "done", "att": 70,
                    "po": 23.8, "alc": 0.25, "swr": 1.2},
        "swr_block": {"blocked": False, "swr": 1.2, "at": "12:41", "limit": 3.0},
        "txcheck": {"band": "20m", "po": 23.8, "alc": 0.25, "swr": 1.2,
                    "target": 25, "att": 70, "suggest": None,
                    "reason": "within tolerance", "ok": True, "at": "12:41:07"},
        "audio": {"tx": 1620, "rx": 1500, "hold": False, "auto": True,
                  "busy": False,
                  "note": "auto: 1620 Hz -- 0 signals nearby vs 6 at 1500"},
        "station": {"state": "running", "steps": [], "at": None},
        "drive": {"att": 70, "band": "20m", "db": 7.0, "min": 0, "max": 450,
                  "stored": {"20m": 70, "40m": 66, "15m": 110},
                  "gui": True, "gui_reason": "demo"},
        "bands": {
            "updated": datetime.now(timezone.utc).strftime("%d %b %Y %H%M GMT"),
            "sfi": "168", "sun": "112", "a": "6", "k": "2",
            "geomag": "QUIET", "xray": "B7.4", "muf": "24.6",
            "sn": "S0-S1", "solarwind": "412.7", "bz": "1.4",
            "protonflux": "38", "electronflux": "1420", "helium": "121.0",
            "cond": {"80m-40m": {"day": "Good", "night": "Fair"},
                     "30m-20m": {"day": "Good", "night": "Good"},
                     "17m-15m": {"day": "Good", "night": "Poor"},
                     "12m-10m": {"day": "Fair", "night": "Poor"}},
            "vhf": {"vhf-aurora": "Band Closed", "E-Skip": "50MHz ES"},
            # key names must match what the interface reads, not what reads
            # well here -- the banner takes `msg`
            "recommend": {"band": "20m", "rating": "Good", "ok": True,
                          "period": "day",
                          "msg": "20m is rated Good \u2014 good place to be"},
        },
        "last_decode_age": 3,
        "entities": sorted({d["entity"] for d in decodes if d["entity"]}),
        "me": {"call": HOME_CALL, "grid": HOME_GRID},
        "caps": {"gui": True, "gui_reason": "demo", "wsjtx": True},
    }


def build_log(qsos):
    ents = {}
    for q in qsos:
        if q["entity"]:
            ents[q["entity"]] = ents.get(q["entity"], 0) + 1
    return {"qsos": qsos, "total": len(qsos),
            "entities": sorted(ents.items(), key=lambda kv: -kv[1]),
            "bands": sorted({q["band"] for q in qsos})}


SHIM = """
/* ------------------------------------------------------------------------
   Demo shim. Replaces the network layer with canned data so the interface
   can be published as a static page. Everything above this line is the
   station's real code, unmodified.
   ------------------------------------------------------------------------ */
(function(){
  const DEMO = __DATA__;
  const TICK = 15000;                      // one FT8 T/R period
  let nextId = Math.max(...DEMO.snapshot.decodes.map(d => d.id)) + 1;

  function stamp(d){
    const now = new Date();
    d.utc = now.toISOString().substr(11, 8);
    d.tms = ((now.getUTCHours()*60 + now.getUTCMinutes())*60
             + now.getUTCSeconds()) * 1000;
    return d;
  }

  class DemoSocket {
    constructor(){
      this.readyState = 0;
      setTimeout(() => {
        this.readyState = 1;
        this.onopen && this.onopen();
        this.emit("snapshot", DEMO.snapshot);
        this.run();
      }, 60);
    }
    emit(type, data){
      this.onmessage && this.onmessage({data: JSON.stringify({type, data})});
    }
    run(){
      // a fresh batch of decodes every T/R period, drawn from the same pool
      let n = 0;
      setInterval(() => {
        const pool = DEMO.snapshot.decodes;
        const batch = 4 + Math.floor(Math.random() * 4);
        for (let i = 0; i < batch; i++){
          const src = pool[(n * 5 + i * 3) % pool.length];
          const d = stamp(Object.assign({}, src, {
            id: nextId++,
            snr: Math.max(-24, Math.min(12,
                 src.snr + Math.round((Math.random() - 0.5) * 6))),
          }));
          this.emit("decode", d);
        }
        n++;
      }, TICK);
      // meters drift the way real ones do
      setInterval(() => {
        const r = JSON.parse(JSON.stringify(DEMO.snapshot.rig));
        r.strength = -20 + Math.round(Math.random() * 12);
        this.emit("rig", r);
      }, 4000);
    }
    send(raw){
      let act = "?";
      try { act = (JSON.parse(raw) || {}).action || "?"; } catch(e){}
      if (act === "beat") return;
      this.emit("ack", {action: act, ok: false,
                        who: "demo \\u2014 no radio attached"});
      if (window.toast) toast("Demo: no radio attached");
    }
    close(){ this.readyState = 3; }
  }
  window.WebSocket = DemoSocket;

  const NOT_HERE = {ok: false, error: "not available in the demo"};
  window.fetch = async (url) => {
    const u = String(url);
    let body = NOT_HERE;
    if (u.indexOf("/api/log") === 0) body = DEMO.log;
    else if (u.indexOf("/api/settings") === 0) body = DEMO.settings;
    else if (u.indexOf("/api/photo/") === 0) body = {photo: null};
    return {ok: true, status: 200, json: async () => body,
            text: async () => JSON.stringify(body)};
  };

  document.addEventListener("DOMContentLoaded", () => {
    const tag = document.createElement("a");
    tag.href = "https://github.com/detournemint/ft8xss";
    tag.textContent = "DEMO \\u00b7 synthetic data \\u00b7 no radio attached";
    tag.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:9999;"
      + "background:#3a2d10;border:1px solid #8a6d1e;color:#f5dd9a;"
      + "padding:7px 13px;border-radius:999px;font:600 11px/1 ui-monospace,"
      + "monospace;letter-spacing:.06em;text-decoration:none;"
      + "box-shadow:0 4px 14px rgba(0,0,0,.45)";
    document.body.appendChild(tag);
  });
})();
"""


def main():
    html = (PKG / "static" / "index.html").read_text()
    worldmap = (PKG / "static" / "worldmap.js").read_text()

    # the demo is one file: no server to serve /static
    tag = '<script src="/static/worldmap.js"></script>'
    if tag not in html:
        raise SystemExit("worldmap script tag not found -- did the UI change?")

    snapshot = build_snapshot()
    data = {
        "snapshot": snapshot,
        "log": build_log(snapshot["qsos"]),
        "settings": {
            "file": "(demo)",
            "settings": [
                {"key": "CALL", "label": "Callsign", "section": "Station",
                 "type": "text", "restart": True, "secret": False,
                 "help": "Your callsign. Must match WSJT-X.", "value": HOME_CALL},
                {"key": "GRID", "label": "Grid square", "section": "Station",
                 "type": "text", "restart": True, "secret": False,
                 "help": "Maidenhead locator, 4 or 6 characters.",
                 "value": HOME_GRID},
                {"key": "HTTP_PORT", "label": "Web port", "section": "Server",
                 "type": "number", "restart": True, "secret": False,
                 "help": "Port this interface listens on.", "value": "8073"},
                {"key": "QRZ_KEY", "label": "QRZ logbook API key",
                 "section": "Logging", "type": "password", "restart": True,
                 "secret": True, "help": "From logbook.qrz.com.", "value": ""},
                {"key": "AUTO_ARM", "label": "Auto-arm transmit",
                 "section": "Safety", "type": "bool", "restart": False,
                 "secret": False,
                 "help": "Let the station re-enable transmit by itself. "
                         "Off is strongly recommended.", "value": "false"},
                {"key": "AUTO_FIX_DRIVE", "label": "Correct drive automatically",
                 "section": "Safety", "type": "bool", "restart": False,
                 "secret": False,
                 "help": "After a transmission, if power or ALC is wrong for "
                         "the band, fix the drive automatically.",
                 "value": "true"},
            ],
        },
    }
    shim = SHIM.replace("__DATA__", json.dumps(data, separators=(",", ":")))

    html = html.replace(tag, f"<script>\n{worldmap}\n</script>\n<script>{shim}</script>")
    html = html.replace("<title>ft8xss</title>", "<title>ft8xss — live demo</title>")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html)
    kb = len(html) / 1024
    print(f"wrote {OUT.relative_to(ROOT)}  ({kb:.0f} KB, "
          f"{len(snapshot['decodes'])} decodes, {len(snapshot['qsos'])} QSOs)")


if __name__ == "__main__":
    main()
