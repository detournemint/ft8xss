# Roadmap

Ideas credited to the projects they came from — see README for links.

## Before first release

- [ ] **Core / headless split.** Extract a core that needs only UDP + rigctld
      (works with WSJT-X on any machine, including the operator's desktop) from
      the optional headless helper that drives the GUI with xdotool.
- [x] **Drop WSJT-Z coupling.** Window title, unit name and the Auto CQ /
      Auto Call buttons are the only Z-specific pieces. Removing the auto
      buttons *is* the port — that automation does not exist in WSJT-X and is
      the part the community objects to.
- [ ] **First-run wizard.** Web form: callsign, grid, QRZ logbook key, radio,
      audio devices. Writes config + systemd units.
- [ ] **Radio auto-detection.** Enumerate `/dev/ttyUSB*` and `/dev/ttyACM*`,
      read USB VID/PID, map to a hamlib model, verify by starting rigctld and
      reading the frequency back. Pick the audio codec on the same USB device.
- [ ] **Config file** instead of environment variables only.
- [x] Licence: GPL-3.0, matching the WSJT-X ecosystem.
- [x] Remove hardcoded callsign/grid defaults; env prefix is now FT8XSS_.
- [ ] Install docs for both **local** (WSJT-X and ft8xss on one desktop) and
      **server** (headless station, browser elsewhere) layouts.

## Adopted from prior art

- [x] **Browser dead-man switch** — no heartbeat while armed → stop
      transmitting. *(idea: w5eez/ft8web)*
- [x] **Fake-split transmit** — keep the audio tone near the middle of the SSB
      filter to avoid roll-off and splatter at the passband edges. WSJT-X
      implements this natively as `SplitMode=split_mode_emulate`; we enable it.
      *(idea: ok1cdj/FT8web)*

## Still worth taking

- [ ] **`cty.dat` for DXCC** instead of the hand-built prefix table. Canonical,
      handles exceptions and portable suffixes properly, and replaces ~200 lines
      of approximation. *(ok1cdj)*
- [ ] **New/Worked badges filtered by band *and* mode**, not just entity —
      that is how award chasing actually works. *(ok1cdj)*
- [ ] **SWR protection** — inhibit TX above a threshold rather than only
      reporting it. *(w5eez)*
- [ ] **New GRID and new BAND flags** alongside new entity. *(w5eez)*
- [ ] **POTA integration** — nearby parks, one-tap self-spot, activation
      uploads. *(w5eez)*
- [ ] **Cabrillo export** and **LoTW upload** (needs TQSL). *(w5eez)*
- [ ] **Multiple radio profiles.** *(w5eez)*
- [ ] **AutoGrid from GPS** for portable operation. *(w5eez)*
- [ ] **Outbound JSON stream** so companion apps (GridTracker, JTAlert) can
      consume our data the way they consume WSJT-X UDP. *(ok1cdj)*

## Own ideas not yet built

- [x] Hash routing so tabs are bookmarkable (`#log`).
- [x] Configurable logbook path, so demos and tests need not touch the real log.

- [ ] Alerting when a new DXCC entity appears — browser notification or sound.
- [ ] Persist the decode buffer across restarts.
- [ ] History of what the service did: tunes, band changes, arm/stop events.
- [ ] Authentication. The UI can key a transmitter and currently binds
      `0.0.0.0` with no auth. Offer localhost-only + SSH tunnel, or a password.
- [ ] Embed **noVNC** so the full WSJT-X GUI is reachable in a panel — the
      honest answer to "make the settings available", since the UDP protocol
      exposes only a fraction of them.
- [ ] Re-run band setup automatically when ALC drifts, not only on band change.
      The ATU changes the match, which moves the drive curve.

## Notes worth keeping

- WSJT-X **binds the UDP port itself** if nothing else has it. Start ft8xss
  first, then WSJT-X.
- `OutAttenuation` is **per band**, and writing the `.ini` directly bypasses
  WSJT-X's own per-band memory.
- Enable Tx, Auto CQ and Auto Call are **never persisted** by WSJT-X/WSJT-Z.
- Stopping WSJT-X mid-transmission **latches CAT PTT**. Always drop it after.
- When calling CQ, the odd time slot is often less congested. *(w5eez)*
