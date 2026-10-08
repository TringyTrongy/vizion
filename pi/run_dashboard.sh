#!/bin/sh
# Opens the Vizion dashboard full screen on the Pi's monitor. Works from a desktop terminal, the
# desktop icon, or over SSH. Extra arguments go to dashboard.py, e.g.  ./run_dashboard.sh --conf 0.3
#
# To close it: hold EXIT in the title block for a second, or press Q or Esc.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DISPLAY="${DISPLAY:-:0}"
cd "$(dirname "$0")" || exit 1

PORT=8765
URL="http://127.0.0.1:$PORT/"
LOG="$PWD/dashboard.log"
PY=.venv/bin/python

answers() {  # is a dashboard serving on $PORT?
    "$PY" -c "import socket,sys; s=socket.socket(); s.settimeout(0.5); sys.exit(s.connect_ex(('127.0.0.1',$PORT)))"
}

# Only one program can use the camera: close the camera preview, and any dashboard already open.
pkill -f "[c]amera_preview[.]py" && sleep 1
if answers; then
    echo "Closing the dashboard that is already open"
    "$PY" -c "import urllib.request as u; u.urlopen(u.Request('${URL}api/quit', b'{}', method='POST'), timeout=3)" 2>/dev/null
    i=0
    while answers && [ $i -lt 20 ]; do sleep 0.25; i=$((i + 1)); done
fi

echo "--- $(date '+%F %T') run_dashboard.sh $*" >>"$LOG"
"$PY" dashboard.py --port "$PORT" "$@" >>"$LOG" 2>&1 &
SERVER=$!
i=0
until answers; do
    if ! kill -0 "$SERVER" 2>/dev/null || [ $i -ge 80 ]; then
        echo "The dashboard did not start. See $LOG"
        kill "$SERVER" 2>/dev/null
        exit 1
    fi
    sleep 0.25
    i=$((i + 1))
done

# A separate profile, so kiosk mode never touches the desktop's normal Chromium windows.
chromium --kiosk "$URL" \
    --user-data-dir="$HOME/.config/vizion-kiosk" \
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
