#!/bin/sh
# Forced-crash test: kills the Vizion service with SIGKILL (no clean shutdown) N times and measures
# how long until the dashboard answers again. Needs vizion-dashboard.service installed.
#
#   ./crash_test.sh 5        # writes logs/crash_test.csv and prints each restart time
set -u
N="${1:-5}"
URL=http://127.0.0.1:8765/api/state
OUT="$(dirname "$0")/../logs/crash_test.csv"
mkdir -p "$(dirname "$OUT")"
[ -f "$OUT" ] || echo "wall_time,attempt,old_pid,new_pid,restart_s" > "$OUT"

for i in $(seq 1 "$N"); do
    until curl -fs "$URL" >/dev/null; do sleep 0.2; done
    old=$(systemctl show -p MainPID --value vizion-dashboard)
    t0=$(date +%s.%N)
    sudo kill -9 "$old"
    until curl -fs "$URL" >/dev/null 2>&1; do sleep 0.1; done
    t1=$(date +%s.%N)
    new=$(systemctl show -p MainPID --value vizion-dashboard)
    s=$(echo "$t1 - $t0" | bc)
    echo "$(date '+%F %T'),$i,$old,$new,$s" | tee -a "$OUT"
    sleep 3
done
echo "Restarts: $(systemctl show -p NRestarts --value vizion-dashboard) (systemd count). Log: $OUT"
