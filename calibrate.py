#!/usr/bin/env python3
"""Trigger one CQ via ft8web and sample the radio's meters through rigctld.

Measures a real FT8 transmission rather than keying a carrier on a shared
frequency. Reports peak PO / ALC / SWR for setting OutAttenuation.
"""
import asyncio
import json
import sys

import aiohttp

WS = "http://127.0.0.1:8073/ws"
RIG = ("127.0.0.1", 4532)


async def rig(cmd):
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(*RIG), 3)
        w.write((cmd + "\n").encode())
        await w.drain()
        data = await asyncio.wait_for(r.read(128), 3)
        w.close()
        return data.decode(errors="replace").strip()
    except Exception:
        return None


async def sample(seconds=30):
    peak = {"po": 0.0, "alc": 0.0, "swr": 1.0}
    saw_tx = False
    deadline = asyncio.get_event_loop().time() + seconds
    while asyncio.get_event_loop().time() < deadline:
        if (await rig("t")) == "1":
            saw_tx = True
            for k, lvl in (("po", "l RFPOWER_METER_WATTS"),
                           ("alc", "l ALC"), ("swr", "l SWR")):
                v = await rig(lvl)
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    continue
                if f > peak[k]:
                    peak[k] = round(f, 3)
        elif saw_tx and peak["po"] > 0:
            break
        await asyncio.sleep(0.25)
    return peak, saw_tx


async def main():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(WS) as ws:
            await ws.receive()                       # snapshot
            await ws.send_str(json.dumps({"action": "cq"}))
            print("  CQ requested; sampling meters...", flush=True)
            peak, saw = await sample(40)
    if not saw:
        print("  no transmission detected -- is Enable Tx on?")
        return 1
    print(f"  peak PO  : {peak['po']:.1f} W")
    print(f"  peak ALC : {peak['alc']:.3f}")
    print(f"  peak SWR : {peak['swr']:.2f}")
    return 0


sys.exit(asyncio.run(main()))
