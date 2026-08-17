---
name: ft8xss-station
description: Diagnose and repair an FT8 station running ft8xss with WSJT-X — no decodes, transmitter not being heard, QSOs that answer but never complete, stuck PTT, drive/ALC calibration, CAT and audio faults, UDP port conflicts. Use when a WSJT-X/ft8xss station misbehaves, when contacts stall mid-exchange, or when setting transmit drive on a new band.
---

# FT8 station diagnosis

Repairing an FT8 station is mostly about **measuring rather than guessing**. Most
faults look identical from the operator's chair — "nobody answers me" is caused
by a dozen different things — so work the checks in order and let the data
eliminate causes.

## Ground rules

**Never key the transmitter to test something if a real transmission would do.**
Trigger a CQ and measure that, rather than sending a tune carrier onto a busy
FT8 frequency.

**Stopping WSJT-X mid-transmission latches CAT PTT.** The radio never receives
the un-key and will sit there transmitting. Always drop PTT after stopping it:

```
# via rigctld (preferred, it owns the port)
printf 'T 0\n' | nc -q1 127.0.0.1 4532
# or direct serial, Yaesu
python3 -c "import serial,time; p=serial.Serial('/dev/ttyUSB0',38400); p.write(b'TX0;')"
```

**Enable Tx is a safety interlock, not a bug.** It is not persisted by WSJT-X.
Auto-restoring it turns the station into an unattended CQ machine whenever Tx6
is selected. Restore it only on explicit operator action.

## The decision tree

### 1. Is it decoding at all?

```
tail -3 ~/.local/share/WSJT-X/ALL.TXT      # timestamps recent?
```

No decodes → audio or radio, not propagation. Check in this order:

- Is the radio on? (`printf 'f\n' | nc -q1 127.0.0.1 4532`)
- Does the sound card exist? `arecord -l | grep -i codec`
- Can the *service user* open it? Missing `audio` group is the classic cause;
  over SSH there is no login seat so device ACLs are not granted.
- If PipeWire shows only `auto_null`, its process has stale credentials —
  check `grep ^Groups /proc/$(pgrep -x pipewire)/status` against
  `getent group audio`. Fix by restarting `user@<uid>.service`, not the
  PipeWire units (they inherit from the manager).

### 2. Are you being heard?

This is the question operators most often get wrong. Do not infer it — measure:

```
curl -s "https://retrieve.pskreporter.info/query?senderCallsign=CALL&flowStartSeconds=-900"
```

Use a browser User-Agent; PSK Reporter rejects default curl.

**PSK Reporter only spots messages containing a grid square.** A CQ carries one;
a signal report (`W1ABC N0CALL -07`) does not. So "my CQs are spotted but my
reports are not" is expected and proves nothing about your transmitter.

### 3. Stations answer but the QSO never completes

The signature: they send their report, you reply, and they **repeat the same
message** instead of advancing. Check in order:

- **Slot parity.** Both stations transmitting in the same period cannot hear
  each other. Compare the seconds field of their decodes against yours in
  `ALL.TXT`; they must alternate `:00/:30` against `:15/:45`.
- **Truncated transmissions.** A transmission starting more than ~2 s into the
  slot is undecodable. Clicking a decode mid-cycle causes this — WSJT-X keys
  immediately rather than waiting for the boundary. Look for `Tx` lines whose
  seconds are not on a 15-second boundary.
- **Transmit level.** See below. A station reporting you steadily at -14 while
  hearing you fine is not the problem; a *silent* under-drive is.
- **QRM you cannot see.** If they hear you well (-1 or better) and still repeat,
  something near them is on your TX frequency. You cannot see it — QSY 1000+ Hz.
  A small nudge is useless; you are escaping interference of unknown width.

### 4. Transmit level

Read the meters through rigctld while a real transmission is in flight:

```
printf 'l RFPOWER_METER_WATTS\n' | nc -q1 127.0.0.1 4532   # PO in watts
printf 'l ALC\n'                 | nc -q1 127.0.0.1 4532   # 0..1
printf 'l SWR\n'                 | nc -q1 127.0.0.1 4532
```

Target: **full set power with ALC barely moving** (≲0.25). Then:

- **PO well below the rig's setting and ALC near zero** → under-driven. Reduce
  `OutAttenuation` (WSJT-X `Pwr` slider; units are tenths of a dB, 0–450).
- **PO at target and ALC high** → over-driven. The extra audio is being
  compressed into intermodulation, making you *harder* to decode. Increase
  attenuation. There is a knee; find it and sit just below.
- **PO at the rig's limit with ALC high** → the radio is ALC-limiting. Raise RF
  power to give headroom, then re-trim drive.

`OutAttenuation` is stored **per band**, and editing the `.ini` directly bypasses
WSJT-X's per-band memory — the last written value then follows you across band
changes. Re-measure after every band change.

### 5. SWR and the tuner

Meters read meaningfully only while transmitting; SWR at idle is always 1.0.
Trigger the internal ATU through hamlib:

```
printf 'G TUNE\n' | nc -q1 127.0.0.1 4532
```

Hamlib's `U TUNER 1` only sets the tuner *in line* — it does not start a tune
cycle. `G TUNE` (vfo_op) does. Only tune while idle: it keys the radio, and
mid-slot it corrupts the transmission.

**A tune changes the match, which changes the drive curve.** Always re-check ALC
after tuning; a value calibrated before the tune will be wrong after it.

### 6. UDP and CAT contention

**WSJT-X binds the UDP port itself if nothing else has it.** Start ft8xss (or
GridTracker) first, then WSJT-X — otherwise the port is taken and ft8xss sees
nothing. With systemd, order it with `After=`/`Wants=`.

**Only one process can own the serial port.** If ft8xss and WSJT-X both need
CAT, run `rigctld` and point WSJT-X at it as *Hamlib NET rigctl*
(`127.0.0.1:4532`). Then both can query the radio concurrently and nothing has
to steal the port.

### 7. The Log QSO dialog

WSJT-X can raise a modal Log QSO dialog that **blocks auto-sequencing** and
swallows the contact until dismissed. On a headless display nobody sees it and
every subsequent QSO stalls. Detect and clear it:

```
DISPLAY=:99 xdotool search --name "Log QSO"
DISPLAY=:99 xwininfo -id <id> | grep "Map State"     # IsViewable = really open
```

Qt keeps the window object after closing, so *existence is not openness* —
always check `Map State`.

## Automating the GUI

If you must drive the WSJT-X GUI (headless stations):

- Accelerators: `Alt+N` Enable Tx, `Alt+H` Halt Tx, `Alt+T` Tune, `Alt+M` Monitor,
  `Alt+E` **Erase** (not Enable — easy to get wrong).
- `xdotool key --window <id>` uses `XSendEvent`, which **Qt ignores**. Focus the
  window and send without `--window` so it goes through XTEST.
- `xdotool getwindowgeometry` reports the **frame** origin. With a window manager
  running, clicks computed from it land ~20 px high. Use `xwininfo`'s
  *Absolute upper-left*, which is the client area.
- Enable Tx is a **toggle**. Read the current state from WSJT-X's UDP Status
  before sending the keystroke, or you will turn on what you meant to turn off.

## Reading ALL.TXT

Format: `YYMMDD_HHMMSS  freq Rx/Tx MODE SNR DT DF MESSAGE`

A message is `TO FROM [GRID]`. **The second callsign is the transmitting
station.** `EI4KF KT4DZ EM82` is KT4DZ calling EI4KF — it does *not* mean you can
hear EI4KF. Confirm a station is actually audible before chasing it:

```
awk '$3=="Rx" && $9=="CALL"' ~/.local/share/WSJT-X/ALL.TXT   # they transmitted
```

`RR73` matches the Maidenhead pattern and will parse as a grid square if you are
careless; exclude `RR73`, `RRR`, `73`.
