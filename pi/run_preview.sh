#!/bin/sh
# Opens the camera preview on the Pi desktop. Works from a desktop terminal or over SSH.
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export DISPLAY="${DISPLAY:-:0}"
# OpenCV's bundled Qt only ships the xcb plugin, so the window goes through Xwayland.
export QT_QPA_PLATFORM=xcb
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python camera_preview.py "$@"
