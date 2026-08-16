#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/load-vars.sh"
STARTER="$SCRIPT_DIR/start_x11vnc_wayland_ondemand.sh"

if [[ "${1:-}" != "--inner" ]]; then
  mkdir -p "$STATE_DIR"
  printf 'Logfiles: %s\n' "$STATE_DIR" >&2
  exec "$RUN_COMPONENT" listener -- "$0" --inner "$@"
fi
shift

if [[ -z "$(command -v socat || true)" ]]; then
  echo "missing dependency: socat" >&2
  exit 1
fi

if [[ ! -x "$STARTER" ]]; then
  echo "missing executable starter: $STARTER" >&2
  exit 1
fi

printf 'Listening on %s:%s\n' "$LISTEN_HOST" "$LISTEN_PORT" >&2
printf 'Starter: %s --inetd\n' "$STARTER" >&2
printf 'Logfiles: %s\n' "$STATE_DIR" >&2

while true; do
  if socat \
    TCP-LISTEN:"$LISTEN_PORT",bind="$LISTEN_HOST",reuseaddr \
    EXEC:"env X11VNC_WAYLAND_ECHO_LOGS=errors $STARTER --inetd" ; then
    :
  else
    rc=$?
    printf '%s socat exited with status %s; continuing listener loop\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "$rc" >&2
  fi
  sleep 0.25
done
