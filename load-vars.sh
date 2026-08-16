#!/usr/bin/env bash
set -euo pipefail

LOAD_VARS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/x11vnc-wayland-bridge"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp}"

RAWFB_PATH="$RUNTIME_DIR/pwfb.raw"
META_PATH="$STATE_DIR/pwfb.meta"
TOKEN_FILE="$STATE_DIR/pwfb.restore_token"
PIDFILE="$RUNTIME_DIR/pwfb-bridge.pid"
READYFILE="$RUNTIME_DIR/pwfb-bridge.ready"

LISTEN_HOST="0.0.0.0"
LISTEN_PORT="5900"

LOG_MAX_BYTES="2097152"
LOG_KEEP_BYTES="1048576"
LISTENER_LOG="$STATE_DIR/listener.log"
INETD_LOG="$STATE_DIR/inetd.log"
BRIDGE_LOG="$STATE_DIR/bridge.log"
PIPEINPUT_LOG="$STATE_DIR/pipeinput.log"

POLL_INTERVAL="2"
WAKE_RETRY_EVERY="5"
BRIDGE_FRAMERATE="${BRIDGE_FRAMERATE:-15}"
X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE="${X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE:-0}"
X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS="${X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS:-60,160,350}"

PIPE_LOGS="$LOAD_VARS_DIR/pipe-logs.py"
RUN_COMPONENT="$LOAD_VARS_DIR/run_component.sh"
BRIDGE="$LOAD_VARS_DIR/portal_rawfb_bridge.py"
PIPEINPUT_HELPER="$LOAD_VARS_DIR/x11vnc_pipeinput.py"

mkdir -p "$STATE_DIR" "$(dirname -- "$RAWFB_PATH")"

component_log_file() {
  case "${1:-}" in
    listener) printf '%s\n' "$LISTENER_LOG" ;;
    inetd) printf '%s\n' "$INETD_LOG" ;;
    bridge) printf '%s\n' "$BRIDGE_LOG" ;;
    pipeinput) printf '%s\n' "$PIPEINPUT_LOG" ;;
    *)
      printf 'unknown log component: %s\n' "${1:-}" >&2
      return 1
      ;;
  esac
}
