#!/usr/bin/env bash
#
# ft8xss installer.
#
# Installs dependencies, detects your radio, writes a config file and sets up
# systemd user services. Safe to re-run: it asks before overwriting anything
# and never changes your WSJT-X settings.
#
#   ./install.sh              local station (WSJT-X on this machine's desktop)
#   ./install.sh --headless   server station (virtual display, no monitor)
#   ./install.sh --uninstall  remove the services, keep the config
#
set -uo pipefail

HEADLESS=0
UNINSTALL=0
ASSUME_YES=0
for a in "$@"; do
  case "$a" in
    --headless)  HEADLESS=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -y|--yes)    ASSUME_YES=1 ;;
    -h|--help)   sed -n '2,14p' "$0" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $a (try --help)"; exit 2 ;;
  esac
done

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$HOME/.config/ft8xss.env"
UNIT_DIR="$HOME/.config/systemd/user"
DISPLAY_NUM=":99"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

ask() {  # ask "prompt" "default"
  local reply
  if [ "$ASSUME_YES" = 1 ]; then echo "$2"; return; fi
  read -r -p "  $1 [$2]: " reply </dev/tty
  echo "${reply:-$2}"
}
confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  local reply; read -r -p "  $1 [y/N]: " reply </dev/tty
  [[ "$reply" =~ ^[Yy] ]]
}

# ---------------------------------------------------------------- uninstall --
if [ "$UNINSTALL" = 1 ]; then
  step "Removing services"
  for u in ft8xss xvfb99 openbox99 rigctld wsjtx-headless; do
    systemctl --user disable --now "$u.service" 2>/dev/null && ok "$u removed"
    rm -f "$UNIT_DIR/$u.service"
  done
  systemctl --user daemon-reload
  echo
  ok "Done. Your config is still at $ENV_FILE"
  exit 0
fi

bold "ft8xss installer"
echo "  Mode: $([ "$HEADLESS" = 1 ] && echo 'headless server' || echo 'local desktop')"

# ------------------------------------------------------------- dependencies --
step "1. Dependencies"

if   command -v apt-get >/dev/null; then PM=apt
elif command -v dnf     >/dev/null; then PM=dnf
elif command -v pacman  >/dev/null; then PM=pacman
elif command -v zypper  >/dev/null; then PM=zypper
else PM=""; fi

case "$PM" in
  apt)    PKGS=(python3 python3-aiohttp libhamlib-utils) ;;
  dnf)    PKGS=(python3 python3-aiohttp hamlib) ;;
  pacman) PKGS=(python python-aiohttp hamlib) ;;
  zypper) PKGS=(python3 python3-aiohttp hamlib) ;;
esac
if [ "$HEADLESS" = 1 ]; then
  case "$PM" in
    apt)    PKGS+=(xvfb x11vnc openbox xdotool x11-utils) ;;
    dnf)    PKGS+=(xorg-x11-server-Xvfb x11vnc openbox xdotool xorg-x11-utils) ;;
    pacman) PKGS+=(xorg-server-xvfb x11vnc openbox xdotool xorg-xwininfo) ;;
    zypper) PKGS+=(xorg-x11-server-Xvfb x11vnc openbox xdotool xwininfo) ;;
  esac
else
  case "$PM" in
    apt)    PKGS+=(xdotool x11-utils) ;;
    dnf)    PKGS+=(xdotool xorg-x11-utils) ;;
    pacman) PKGS+=(xdotool xorg-xwininfo) ;;
    zypper) PKGS+=(xdotool xwininfo) ;;
  esac
fi

if [ -z "$PM" ]; then
  warn "Unknown package manager. Install by hand: python3, aiohttp, hamlib (rigctld), xdotool, xwininfo"
else
  echo "  Will install: ${PKGS[*]}"
  if confirm "Install these with $PM (needs sudo)?"; then
    case "$PM" in
      apt)    sudo apt-get update -qq && sudo apt-get install -y "${PKGS[@]}" ;;
      dnf)    sudo dnf install -y "${PKGS[@]}" ;;
      pacman) sudo pacman -S --needed --noconfirm "${PKGS[@]}" ;;
      zypper) sudo zypper install -y "${PKGS[@]}" ;;
    esac
  else
    warn "Skipped. Missing packages will show up as errors below."
  fi
fi

if python3 -c 'import aiohttp' 2>/dev/null; then
  ok "python aiohttp present"
else
  warn "aiohttp missing from the system python"
  if confirm "Install aiohttp with pip --user?"; then
    python3 -m pip install --user aiohttp || python3 -m pip install --user --break-system-packages aiohttp
  fi
fi

for t in rigctl rigctld; do
  command -v $t >/dev/null && ok "$t $( $t --version 2>/dev/null | head -1 | awk '{print $NF}')" \
                           || bad "$t not found — rig telemetry, ATU and band changes will not work"
done
if [ "$HEADLESS" = 1 ]; then
  for t in Xvfb openbox x11vnc xdotool xwininfo; do
    command -v $t >/dev/null && ok "$t" || bad "$t not found (needed for headless)"
  done
fi
command -v wsjtx >/dev/null && ok "wsjtx $(wsjtx --version 2>/dev/null | head -1)" || {
  warn "WSJT-X not found. Install it from https://wsjt.sourceforge.io/ — ft8xss drives it, it does not replace it."
}

# --------------------------------------------------------------------- rig --
step "2. Radio"

mapfile -t PORTS < <(ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null)
if [ "${#PORTS[@]}" -eq 0 ]; then
  warn "No USB serial ports found. Plug the radio in and re-run, or set the port later in Settings."
  RIG_PORT=""
else
  echo "  Serial ports found:"
  for p in "${PORTS[@]}"; do
    info=$(udevadm info --query=property --name="$p" 2>/dev/null \
           | awk -F= '/ID_MODEL=|ID_VENDOR=/{printf "%s ", $2}')
    printf '    %-16s %s\n' "$p" "${info:-unknown}"
  done
  # A CAT port is usually the lower-numbered of a pair on the same chip.
  RIG_PORT=$(ask "Which port is CAT control?" "${PORTS[0]}")
fi

if ! id -nG "$USER" | grep -qw dialout && ! id -nG "$USER" | grep -qw uucp; then
  warn "You are not in the 'dialout' group — opening the serial port will fail."
  if confirm "Add $USER to dialout?"; then
    sudo usermod -aG dialout "$USER" && warn "Log out and back in for this to take effect."
  fi
fi

RIG_MODEL=$(ask "Hamlib rig model number (rigctl --list to search; 1035 = Yaesu FT-991/991A, 2 = NET rigctl)" "1035")
RIG_SPEED=$(ask "CAT baud rate" "38400")

if [ -n "$RIG_PORT" ] && command -v rigctl >/dev/null; then
  if confirm "Test CAT now (reads the current frequency)?"; then
    if out=$(timeout 8 rigctl -m "$RIG_MODEL" -r "$RIG_PORT" -s "$RIG_SPEED" f 2>&1); then
      ok "Radio replied: $out Hz"
    else
      bad "No reply: $out"
      warn "Check the port, baud rate, model, and that the radio's CAT is enabled."
    fi
  fi
fi

# ------------------------------------------------------------------ station --
step "3. Station"

DEF_CALL=$(grep -oP '(?<=^FT8XSS_CALL=).*' "$ENV_FILE" 2>/dev/null || echo N0CALL)
DEF_GRID=$(grep -oP '(?<=^FT8XSS_GRID=).*' "$ENV_FILE" 2>/dev/null || echo AA00aa)
CALL=$(ask "Callsign" "$DEF_CALL")
GRID=$(ask "Grid square (4 or 6 characters)" "$DEF_GRID")
PORT=$(ask "Web interface port" "8073")
BIND=$(ask "Bind address (0.0.0.0 = whole LAN, 127.0.0.1 = SSH tunnel only)" "0.0.0.0")
QRZ=$(ask "QRZ logbook API key (blank to skip automatic upload)" "")

CALL=$(echo "$CALL" | tr '[:lower:]' '[:upper:]')
if ! [[ "$GRID" =~ ^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$ ]]; then
  warn "'$GRID' does not look like a Maidenhead locator — distances and bearings will be wrong."
fi
if [ "$BIND" = "0.0.0.0" ]; then
  warn "ft8xss has no password. On 0.0.0.0 anyone on your network can key your transmitter."
fi

if [ -f "$ENV_FILE" ] && ! confirm "Overwrite $ENV_FILE?"; then
  warn "Keeping existing config."
else
  mkdir -p "$(dirname "$ENV_FILE")"
  {
    echo "# ft8xss — written by install.sh on $(date -u '+%Y-%m-%d %H:%M UTC')"
    echo "FT8XSS_CALL=$CALL"
    echo "FT8XSS_GRID=$GRID"
    echo "FT8XSS_HTTP_PORT=$PORT"
    echo "FT8XSS_UDP_PORT=2237"
    echo "FT8XSS_BIND=$BIND"
    echo "FT8XSS_QRZ_KEY=$QRZ"
    echo "FT8XSS_DEADMAN=12"
    echo "FT8XSS_AUTO_ARM=0"
    echo "FT8XSS_AUTO_DF=1"
    echo "FT8XSS_AUTO_FIX_DRIVE=1"
    echo "FT8XSS_RIG_MODEL=$RIG_MODEL"
    echo "FT8XSS_RIG_PORT=$RIG_PORT"
    echo "FT8XSS_RIG_SPEED=$RIG_SPEED"
    if [ "$HEADLESS" = 1 ]; then
      echo "FT8XSS_DISPLAY_NUM=$DISPLAY_NUM"
      echo "FT8XSS_WSJTX_WINDOW=WSJT-X"
      echo "FT8XSS_WSJTX_UNIT=wsjtx-headless.service"
    fi
  } > "$ENV_FILE"
  chmod 600 "$ENV_FILE"          # it holds an API key
  ok "Wrote $ENV_FILE (mode 600)"
fi

# ----------------------------------------------------------------- services --
step "4. Services"

mkdir -p "$UNIT_DIR"

cat > "$UNIT_DIR/rigctld.service" <<EOF
[Unit]
Description=Hamlib rigctld — shared CAT control for ft8xss and WSJT-X
[Service]
EnvironmentFile=-%h/.config/ft8xss.env
ExecStart=/usr/bin/rigctld -m $RIG_MODEL -r $RIG_PORT -s $RIG_SPEED -T 127.0.0.1 -t 4532
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
EOF
ok "rigctld.service"

cat > "$UNIT_DIR/ft8xss.service" <<EOF
[Unit]
Description=ft8xss — browser front end for WSJT-X
# ft8xss must own the UDP port before WSJT-X starts, or WSJT-X binds it itself
After=rigctld.service
Wants=rigctld.service
[Service]
EnvironmentFile=-%h/.config/ft8xss.env
WorkingDirectory=$SRC
ExecStart=/usr/bin/python3 -m ft8xss.server
Restart=always
RestartSec=3
[Install]
WantedBy=default.target
EOF
ok "ft8xss.service"

if [ "$HEADLESS" = 1 ]; then
  cat > "$UNIT_DIR/xvfb99.service" <<EOF
[Unit]
Description=Virtual X display for the headless station
[Service]
ExecStart=/usr/bin/Xvfb $DISPLAY_NUM -screen 0 1400x900x24 -nolisten tcp
Restart=always
[Install]
WantedBy=default.target
EOF
  cat > "$UNIT_DIR/openbox99.service" <<EOF
[Unit]
Description=Window manager for the headless station
After=xvfb99.service
Requires=xvfb99.service
[Service]
Environment=DISPLAY=$DISPLAY_NUM
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/openbox
Restart=always
[Install]
WantedBy=default.target
EOF
  cat > "$UNIT_DIR/wsjtx-headless.service" <<EOF
[Unit]
Description=WSJT-X on the virtual display
After=openbox99.service ft8xss.service
Requires=openbox99.service
[Service]
Environment=DISPLAY=$DISPLAY_NUM
EnvironmentFile=-%h/.config/ft8xss.env
ExecStartPre=/bin/sleep 3
ExecStart=/usr/bin/wsjtx
# Stopping WSJT-X mid-transmission can leave CAT PTT latched down. Drop it.
ExecStopPost=-/usr/bin/python3 $SRC/packaging/unkey.py
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF
  ok "xvfb99, openbox99, wsjtx-headless services"
  echo "  Optional VNC to watch WSJT-X:  x11vnc -display $DISPLAY_NUM -localhost -nopw -forever"
fi

systemctl --user daemon-reload

if [ "$HEADLESS" = 1 ] && ! loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; then
  warn "Lingering is off — services will stop when you log out."
  confirm "Enable it (sudo loginctl enable-linger $USER)?" && sudo loginctl enable-linger "$USER"
fi

if confirm "Enable and start ft8xss now?"; then
  UNITS=(rigctld ft8xss)
  [ "$HEADLESS" = 1 ] && UNITS+=(xvfb99 openbox99 wsjtx-headless)
  for u in "${UNITS[@]}"; do
    systemctl --user enable --now "$u.service" >/dev/null 2>&1 \
      && ok "$u started" || bad "$u failed — journalctl --user -u $u -n 30"
  done
fi

# ------------------------------------------------------------------- wrap-up --
step "Done"
IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "  Open  http://${IP:-localhost}:$PORT"
echo
echo "  Two things WSJT-X still needs from you, in its own Settings:"
echo "    Radio     → Rig: 'Hamlib NET rigctl', Network Server: 127.0.0.1:4532"
echo "                (so ft8xss and WSJT-X can share the radio)"
echo "    Reporting → UDP Server port 2237, 'Accept UDP requests' ticked"
echo
echo "  Order matters: ft8xss must start before WSJT-X, or WSJT-X takes the UDP port."
echo "  Logs:    journalctl --user -u ft8xss -f"
echo "  Remove:  ./install.sh --uninstall"
