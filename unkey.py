#!/usr/bin/env python3
"""Drop PTT.

Stopping WSJT-X while it is transmitting can leave CAT PTT latched down: the
radio keys up and stays there with no audio, into whatever the antenna is. The
operator hears nothing and sees nothing unless they are looking at the rig.

Run this from ExecStopPost so shutting the station down can never leave the
transmitter on. It talks to rigctld and is deliberately dumb: no state, no
retries beyond a couple of attempts, and it never fails the unit stop.
"""
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 4532


def send(sock, cmd):
    sock.sendall((cmd + "\n").encode())
    time.sleep(0.2)
    try:
        return sock.recv(128).decode(errors="replace").strip()
    except OSError:
        return ""


def main():
    try:
        s = socket.create_connection((HOST, PORT), timeout=3)
    except OSError as e:
        print(f"unkey: rigctld unreachable ({e}) — cannot verify PTT", file=sys.stderr)
        return 0                      # never block the unit from stopping
    with s:
        for _ in range(2):
            send(s, "T 0")            # set_ptt off
            state = send(s, "t")      # get_ptt
            if state.strip().startswith("0"):
                print("unkey: PTT is down")
                return 0
            time.sleep(0.4)
        print(f"unkey: PTT still reads {state!r} — check the radio", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
