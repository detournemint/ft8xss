# Installing ft8xss

Two arrangements; pick the one that matches your station.

## A. Local — WSJT-X and ft8xss on the same desktop

You keep using the WSJT-X GUI. ft8xss adds a web dashboard you can open on the
same machine or from a phone on your network.

1. Install: `pip install ft8xss` (or `pip install -e .` from a clone)
2. Copy `ft8xss.example.toml` to `~/.config/ft8xss.toml` and set callsign/grid
3. In WSJT-X: **Settings -> Reporting -> UDP Server** `127.0.0.1`, port `2237`,
   and tick **Accept UDP requests** (required for click-to-call)
4. Start ft8xss **first**, then WSJT-X
5. Open `http://localhost:8073`

For rig telemetry (power, ALC, SWR) and band changes, run `rigctld` and set
WSJT-X's rig to **Hamlib NET rigctl** at `127.0.0.1:4532`. Without this ft8xss
still works, but the Radio panel stays empty.

## B. Server — headless station

WSJT-X runs on a server or Pi with the radio attached; you operate from a
browser elsewhere. Additionally requires a virtual X display, since WSJT-X has
no headless mode.

See `docs/HEADLESS.md`.

## Ordering

WSJT-X binds the UDP port itself if nothing else has it. Whatever you use to
start things, ft8xss must be up first. With systemd, the shipped unit declares
`Before=wsjtx.service`.
