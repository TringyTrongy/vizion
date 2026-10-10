#!/bin/sh
# Opens Vizion Motor, the servo-arm anomaly dashboard, full screen on the Pi's monitor.
# Works from a desktop terminal, the desktop icon, or over SSH. Extra arguments go to
# motor_monitor/motor_dashboard.py, e.g.  ./run_motor.sh --host 0.0.0.0
#
# To close it: hold "Hold to exit" for a second, or press Q or Esc.
# It needs the webcam (like the camera dashboard) and the servo and LEDs (like Vizion Sense),
# so close those two first. This script does not close them for you.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DISPLAY="${DISPLAY:-:0}"
cd "$(dirname "$0")" || exit 1

PORT=8767
URL="http://127.0.0.1:$PORT/?kiosk"
LOG="$PWD/motor_monitor/motor_dashboard.log"
PY=.venv/bin/python

answers() {  # is a server listening on port $1?
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(s.connect_ex(('127.0.0.1',$1)))"
}

answers 8765 && echo "The camera dashboard is open: it holds the webcam. Close it first (hold its EXIT)."
answers 8766 && echo "Vizion Sense is open: it holds the servo and LEDs. Close it first (hold to exit)."

if answers $PORT; then
    echo "Closing the Vizion Motor that is already open"
    "$PY" -c "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:$PORT/api/quit', b'{}', method='POST'), timeout=3)" 2>/dev/null
    i=0
    while answers $PORT && [ $i -lt 20 ]; do sleep 0.25; i=$((i + 1)); done
fi

echo "--- $(date '+%F %T') run_motor.sh $*" >>"$LOG"
"$PY" motor_monitor/motor_dashboard.py --port "$PORT" "$@" >>"$LOG" 2>&1 &
SERVER=$!
i=0
until answers $PORT; do
    if ! kill -0 "$SERVER" 2>/dev/null || [ $i -ge 80 ]; then
        echo "Vizion Motor did not start. See $LOG"
        kill "$SERVER" 2>/dev/null
        exit 1
    fi
    sleep 0.25
    i=$((i + 1))
done

# Its own Chromium profile, separate from the other Vizion kiosks and the desktop browser.
chromium --kiosk "$URL" \
    --user-data-dir="$HOME/.config/vizion-motor-kiosk" \
    --ozone-platform=wayland \
    --no-first-run --noerrdialogs --disable-infobars \
    --disable-session-crashed-bubble --hide-crash-restore-bubble \
    --disable-features=Translate,TranslateUI \
    --password-store=basic --overscroll-history-navigation=0 --disable-pinch \
    --check-for-update-interval=31536000 >/dev/null 2>&1 &
BROWSER=$!

stop() {
    kill "$BROWSER" "$SERVER" 2>/dev/null
    wait "$SERVER" 2>/dev/null
}
trap 'stop; exit 0' INT TERM HUP

# Whichever closes first, the page or the server, takes the other with it.
while kill -0 "$SERVER" 2>/dev/null && kill -0 "$BROWSER" 2>/dev/null; do
    sleep 0.5
done
stop
