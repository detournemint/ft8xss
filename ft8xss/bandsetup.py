"""Automatic band-change setup: tune if needed, then set drive for clean ALC.

Called on every band change. Transmits deliberately and briefly to measure,
then puts the transmitter back the way it found it.
"""
import asyncio
import json
import re
import time
from pathlib import Path

INI = Path.home() / ".config/WSJT-X.ini"
DRIVE_FILE = Path.home() / ".config/ft8web-drive.json"

# what "good" looks like
ALC_MAX = 0.30           # above this we are compressing
ALC_IDEAL = 0.20
SWR_TRIGGER = 2.0
PO_FLOOR = 0.80          # accept >= 80% of the rig's set power
ATT_MIN, ATT_MAX = 30, 250
MAX_STEPS = 4


def load_drive():
    try:
        return json.loads(DRIVE_FILE.read_text())
    except Exception:
        return {}


def save_drive(d):
    try:
        DRIVE_FILE.write_text(json.dumps(d, indent=1))
    except OSError:
        pass


def read_att():
    try:
        m = re.search(r"^OutAttenuation=(\d+)", INI.read_text(errors="ignore"), re.M)
        return int(m.group(1)) if m else None
    except OSError:
        return None


class BandSetup:
    """Owns one band-setup run. Injected with the callbacks it needs so it
    stays testable and does not import the server."""

    def __init__(self, *, rig_cmd, set_tx, send_cq, get_status, log,
                 restart_wsjtz, target_watts):
        self.rig_cmd = rig_cmd
        self.set_tx = set_tx
        self.send_cq = send_cq
        self.get_status = get_status
        self.log = log
        self.restart_wsjtz = restart_wsjtz
        self.target_watts = target_watts

    async def _set_att(self, val):
        val = max(ATT_MIN, min(ATT_MAX, int(val)))
        await self.restart_wsjtz(val)
        return val

    async def _measure(self, timeout=60):
        """One transmission; return peak PO / ALC / SWR."""
        if await self.send_cq() is False:
            return None
        peak = {"po": 0.0, "alc": 0.0, "swr": 1.0}
        saw = False
        end = time.time() + timeout
        while time.time() < end:
            if (await self.rig_cmd("t")) == "1":
                saw = True
                for key, lvl in (("po", "l RFPOWER_METER_WATTS"),
                                 ("alc", "l ALC"), ("swr", "l SWR")):
                    v = await self.rig_cmd(lvl)
                    try:
                        f = float(v)
                    except (TypeError, ValueError):
                        continue
                    if f > peak[key]:
                        peak[key] = round(f, 3)
            elif saw and peak["po"] > 0:
                break
            await asyncio.sleep(0.25)
        if not saw:                       # one retry: FT8 only keys on slot edges
            self.log("[band] no TX seen, retrying once")
            if await self.send_cq() is False:
                return None
            end = time.time() + timeout
            while time.time() < end:
                if (await self.rig_cmd("t")) == "1":
                    saw = True
                    for key, lvl in (("po", "l RFPOWER_METER_WATTS"),
                                     ("alc", "l ALC"), ("swr", "l SWR")):
                        v = await self.rig_cmd(lvl)
                        try:
                            f = float(v)
                        except (TypeError, ValueError):
                            continue
                        if f > peak[key]:
                            peak[key] = round(f, 3)
                elif saw and peak["po"] > 0:
                    break
                await asyncio.sleep(0.25)
        return peak if saw else None

    async def run(self, band):
        drive = load_drive()
        start_att = drive.get(band) or read_att() or 100
        was_enabled = self.get_status().get("tx_enabled") is True

        self.log(f"[band] {band}: setup starting (from {start_att})")
        await self.set_tx(True)
        try:
            att = start_att
            best = None
            for step in range(MAX_STEPS):
                m = await self._measure()
                if not m:
                    self.log(f"[band] {band}: no transmission detected, aborting")
                    return None

                # 1. antenna first -- a bad match makes the drive numbers lie
                if m["swr"] >= SWR_TRIGGER:
                    self.log(f"[band] {band}: SWR {m['swr']:.2f}, running ATU")
                    await self.rig_cmd("G TUNE")
                    await asyncio.sleep(7)
                    m = await self._measure() or m
                    self.log(f"[band] {band}: after tune SWR {m['swr']:.2f}")

                po, alc = m["po"], m["alc"]
                self.log(f"[band] {band}: att={att} PO={po:.1f}W "
                         f"ALC={alc:.3f} SWR={m['swr']:.2f}")

                good = alc <= ALC_MAX and po >= PO_FLOOR * self.target_watts
                if best is None or (alc <= ALC_MAX and po > best[1]["po"]):
                    best = (att, dict(m))
                if good:
                    break

                # 2. move drive: ALC is the hard constraint, power the goal
                if alc > ALC_MAX:
                    bump = 15 if alc > 0.6 else 8       # back off harder when badly over
                    att += bump
                elif po < PO_FLOOR * self.target_watts:
                    att -= 10
                else:
                    break
                if not (ATT_MIN <= att <= ATT_MAX):
                    break
                att = await self._set_att(att)

            if best:
                final_att, m = best
                if read_att() != final_att:
                    await self._set_att(final_att)
                drive[band] = final_att
                save_drive(drive)
                self.log(f"[band] {band}: settled att={final_att} "
                         f"PO={m['po']:.1f}W ALC={m['alc']:.3f} SWR={m['swr']:.2f}")
                return {"band": band, "att": final_att, **m}
            return None
        finally:
            # leave the transmitter as we found it -- do not silently arm it
            if not was_enabled:
                await self.set_tx(False)
                self.log(f"[band] {band}: TX returned to disabled")
