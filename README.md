# ft8xss

A browser front end for **WSJT-X**. Live decodes, click-to-call, logging, QRZ
upload, DXCC tracking, propagation data and rig telemetry — from a phone,
laptop or tablet.

> **This software keys your transmitter.** You are the control operator. Read
> the safety notes below before running it.

![Operate view](docs/images/operate.png)

*Band activity, current QSO, azimuthal map, propagation and rig telemetry.
Screenshots use synthetic data — see `docs/demo_feed.py`.*

## What makes it different

Other web FT8 projects either implement their own modem in the browser or embed
WSJT-X's DSP binaries. **ft8xss drives an unmodified WSJT-X over its standard
UDP protocol.** You install it beside the WSJT-X you already run and trust —
no forked decoder, no replacement DSP, and it keeps working when WSJT-X updates.

## Features

- **Band activity** — live decodes with SNR, distance, bearing, DXCC entity and
  band; filter by CQ / new / new-DXCC / addressed-to-you; sort by signal, time
  or distance
- **Click to call** — any decode, or Call CQ, straight from the browser
- **Current QSO thread** — the exchange as a conversation, with a warning when
  the other station keeps repeating a reply to you (they are not hearing you)
- **Logbook** — full history with map, entity summary, sortable table, filters
- **Automatic logging and QRZ upload**
- **Rig telemetry** — live PO, ALC, SWR and S-meter through hamlib
- **Automatic band setup** — on band change: tune the ATU if SWR is high, then
  find the drive that gives full power with clean ALC
- **Propagation** — full solar/band data, VHF phenomena, and a band
  recommendation for the current conditions
- **Who hears me** — live PSK Reporter reception reports
- **Azimuthal map** centred on your QTH: true bearing and distance
- **QRZ photos** on callsign hover

### Logbook

![Logbook](docs/images/logbook.png)

### Settings

![Settings](docs/images/settings.png)

Everything configurable from the browser. Values are written to an env file
(mode 600, since it holds your API key) and fields that need a service restart
are marked.

### Diagnostics

If something is not working, **download diagnostics** from the Radio panel and
attach it to an issue. It collects versions, radio and audio device detection,
live station state, recent errors and the log — with API keys redacted.

## Safety

- **Dead-man switch.** If the browser driving the station stops responding while
  the transmitter is armed, ft8xss stops transmitting.
- **STOP means stop.** It halts the transmission, disables Enable Tx and
  verifies PTT is down. Nothing transmits again until you ask.
- **No silent arming.** Every transmission traces to an action you took.
  Automatic band setup arms the radio only for its own measurements and returns
  it to the state it found.

## Installation

ft8xss runs in two arrangements. Both use the same code.

### Local — one machine

WSJT-X and ft8xss on your desktop. You keep using the WSJT-X GUI normally and
open the web UI alongside it, or from your phone on the same network.

### Server — headless station

WSJT-X runs on a server or Pi with the radio attached; you operate entirely
from a browser. This needs the optional headless helper (a virtual X display
plus the GUI automation). See `docs/`.

### Requirements

- WSJT-X (any recent version)
- Python 3.10+, `aiohttp`
- `hamlib` (`rigctld`) for rig telemetry, band changes and the ATU
- A QRZ logbook API key for upload (optional)

### Ordering matters

**Start ft8xss before WSJT-X.** WSJT-X binds the UDP port itself if nothing
else has it, and ft8xss will then see nothing.

**Point WSJT-X at `rigctld`** ("Hamlib NET rigctl", `127.0.0.1:4532`) rather
than the serial port directly, so ft8xss and WSJT-X can both reach the radio.

## Credits

Built on the work of others:

- **WSJT-X** — K1JT and contributors. The UDP protocol and the modem.
  <https://wsjt.sourceforge.io/>
- **hamlib** — CAT control. <https://hamlib.github.io/>
- **PSK Reporter** — reception reports. <https://pskreporter.info/>
- **hamqsl.com** (N0NBH) — solar and band condition data.
- **QRZ.com** — logbook API and profile data.

Ideas taken from other web FT8 projects, with thanks:

- **[w5eez/ft8web](https://github.com/w5eez/ft8web)** — the browser dead-man
  switch, and a good deal of inspiration on scope.
- **[ok1cdj/FT8web](https://github.com/ok1cdj/FT8web)** — fake-split transmit to
  keep the audio tone off the SSB filter edges (WSJT-X implements this natively;
  ft8xss enables it), and the band/mode-filtered new/worked indicators.

Neither project shares code with this one — the debt is conceptual.

ft8xss is not affiliated with or endorsed by the WSJT-X authors.

## Licence

See `LICENSE`.
