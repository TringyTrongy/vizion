#!/bin/sh
# Over-the-air update with automatic rollback.
#
# Each release lives in ~/vizion-releases/<tag>; ~/vizion is a symlink to the one running.
# An update downloads the tagged version from GitHub, switches the symlink, restarts the service
# and runs a health check (the dashboard must answer and report the model "ready" within 90 s).
# If the check fails, the symlink goes back to the previous release and the service restarts:
# the rollback. Every step is appended to ~/vizion-releases/ota.log.
#
#   ./ota_update.sh v1          # first install (or go back to v1)
#   ./ota_update.sh v2          # update v1 -> v2
#   ./ota_update.sh v2-bad      # a deliberately broken release: watch it roll back to v2
#
# Tags are made on the repo: git tag v2 && git push origin v2 (v2-bad: see docs/M4_reliability.md).
set -eu
TAG="${1:?usage: ota_update.sh <tag>}"
REPO="${VIZION_REPO:-https://github.com/TringyTrongy/vizion.git}"
REL="$HOME/vizion-releases"
LIVE="$HOME/vizion"
VENV="$HOME/vizion-venv"            # shared by all releases
LOG="$REL/ota.log"
mkdir -p "$REL"
log() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

healthy() {
    i=0
    while [ $i -lt 90 ]; do
        if curl -fs http://127.0.0.1:8765/api/state 2>/dev/null | grep -q '"model":{"state":"ready"'; then
            return 0
        fi
        sleep 1; i=$((i + 1))
    done
    return 1
}

prev=$(readlink "$LIVE" 2>/dev/null || true)
log "OTA start: $(basename "${prev:-none}") -> $TAG"

if [ ! -d "$REL/$TAG" ]; then
    tmp=$(mktemp -d)
    git clone --quiet --depth 1 --branch "$TAG" "$REPO" "$tmp/repo"
    cp -r "$tmp/repo/pi" "$REL/$TAG"
    git -C "$tmp/repo" rev-parse --short HEAD > "$REL/$TAG/RELEASE"
    rm -rf "$tmp"
    ln -s "$VENV" "$REL/$TAG/.venv"
    [ -f "${prev:-/nonexistent}/empty_table.png" ] && cp "$prev/empty_table.png" "$REL/$TAG/"
    log "downloaded $TAG (commit $(cat "$REL/$TAG/RELEASE"))"
fi

ln -sfn "$REL/$TAG" "$LIVE.new" && mv -T "$LIVE.new" "$LIVE"
sudo systemctl restart vizion-dashboard
if healthy; then
    log "OTA OK: $TAG is live and healthy"
    exit 0
fi

log "HEALTH CHECK FAILED for $TAG"
if [ -n "$prev" ]; then
    ln -sfn "$prev" "$LIVE.new" && mv -T "$LIVE.new" "$LIVE"
    sudo systemctl restart vizion-dashboard
    if healthy; then
        log "ROLLBACK OK: back on $(basename "$prev")"
    else
        log "ROLLBACK FAILED: check journalctl -u vizion-dashboard"
    fi
fi
exit 1
