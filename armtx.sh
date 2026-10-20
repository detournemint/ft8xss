#!/bin/bash
# WSJT-Z never persists Enable Tx / Auto CQ / Auto Call, so they are off after
# every start. Re-arm Enable Tx once the GUI is up.
export DISPLAY="${DISPLAY:-:99}"
for i in $(seq 1 20); do
  wid=$(xdotool search --name "WSJT-Z MOD" 2>/dev/null | head -1)
  [ -n "$wid" ] && break
  sleep 1
done
[ -z "$wid" ] && { echo "armtx: WSJT-Z window not found"; exit 0; }
sleep 3
xdotool windowfocus --sync "$wid" 2>/dev/null
sleep 0.5
xdotool key --clearmodifiers alt+n
sleep 1
echo "armtx: sent Alt+N to $wid"
