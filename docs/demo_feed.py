#!/usr/bin/env python3
"""Feed a running ft8xss synthetic WSJT-X UDP traffic.

Used to produce documentation screenshots without keying a transmitter, and to
exercise the UI offline. Sends the same Qt DataStream packets WSJT-X emits.
"""
import argparse
import random
import socket
import struct
import time
from datetime import datetime, timezone

MAGIC = 0xADBCCBDA
SCHEMA = 2


def qstr(s):
    if s is None:
        return struct.pack(">I", 0xFFFFFFFF)
    b = s.encode()
    return struct.pack(">I", len(b)) + b


def head(ptype, wid="WSJT-X"):
    return struct.pack(">III", MAGIC, SCHEMA, ptype) + qstr(wid)


def msecs_now():
    n = datetime.now(timezone.utc)
    return ((n.hour * 60 + n.minute) * 60 + n.second) * 1000


def status(dial, tx_df, rx_df, dx_call="", tx_msg="", transmitting=False,
           tx_enabled=True, mode="FT8", cfg="Default"):
    p = head(1)
    p += struct.pack(">Q", dial)
    p += qstr(mode) + qstr(dx_call) + qstr("") + qstr(mode)
    p += struct.pack(">???", tx_enabled, transmitting, True)
    p += struct.pack(">II", rx_df, tx_df)
    p += qstr("N0CALL") + qstr("AA00aa") + qstr("")
    p += struct.pack(">?", False) + qstr("") + struct.pack(">?", False)
    p += struct.pack(">B", 0) + struct.pack(">II", 0xFFFFFFFF, 0xFFFFFFFF)
    p += qstr(cfg) + qstr(tx_msg)
    return p


def decode(snr, dt, df, msg):
    p = head(2)
    p += struct.pack(">?", True)
    p += struct.pack(">I", msecs_now())
    p += struct.pack(">i", snr)
    p += struct.pack(">d", dt)
    p += struct.pack(">I", df)
    p += qstr("~") + qstr(msg)
    p += struct.pack(">??", False, False)
    return p


def logged_adif(call, grid, band, sent, rcvd):
    now = datetime.now(timezone.utc)
    fields = [("call", call), ("gridsquare", grid), ("mode", "FT8"),
              ("rst_sent", sent), ("rst_rcvd", rcvd),
              ("qso_date", now.strftime("%Y%m%d")),
              ("time_on", now.strftime("%H%M%S")),
              ("band", band), ("station_callsign", "N0CALL"),
              ("my_gridsquare", "AA00aa")]
    adif = "".join(f"<{k}:{len(v)}>{v}" for k, v in fields) + "<eor>"
    return head(12) + qstr(adif)


# A plausible slice of a busy 20 m evening: DX, POTA, locals, callers.
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
    (-12, 0.3, 1560, "K5DXX N0CALL AA00"),
    (8, 0.1, 1705, "CQ W1AW FN31"),
    (-16, 0.2, 880, "CQ PY2XYZ GG66"),
    (-1, 0.1, 2190, "CQ OH2BBB KP20"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=2237)
    ap.add_argument("--cycles", type=int, default=3)
    a = ap.parse_args()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest = (a.host, a.port)

    def send(p):
        s.sendto(p, dest)

    send(head(0) + struct.pack(">I", 3) + qstr("3.0.2") + qstr("demo"))
    send(status(14074000, 1500, 1500))

    for c in range(a.cycles):
        for snr, dt, df, msg in TRAFFIC:
            send(decode(snr + random.randint(-2, 2), dt, df, msg))
            time.sleep(0.02)
        # our own transmission, so the TX row and thread populate
        send(status(14074000, 1500, 1240, dx_call="VK3ANP",
                    tx_msg="VK3ANP N0CALL AA00", transmitting=True))
        time.sleep(0.4)
        send(status(14074000, 1500, 1240, dx_call="VK3ANP",
                    tx_msg="VK3ANP N0CALL AA00", transmitting=False))
        send(decode(-7, 0.2, 1240, "N0CALL VK3ANP -09"))
        time.sleep(0.3)

    # a couple of logged QSOs for the logbook panel
    send(logged_adif("VK3ANP", "QF22", "20m", "-09", "-07"))
    time.sleep(0.2)
    send(logged_adif("EA5TT", "IM98", "20m", "+03", "-05"))
    print(f"sent demo traffic to {a.host}:{a.port}")


if __name__ == "__main__":
    main()
