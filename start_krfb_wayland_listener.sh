#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/load-vars.sh"
STARTER="$SCRIPT_DIR/start_krfb_wayland_ondemand.sh"

if ! command -v socat >/dev/null; then
  echo "missing dependency: socat" >&2
  exit 1
fi

if [[ ! -x "$STARTER" ]]; then
  echo "missing executable starter: $STARTER" >&2
  exit 1
fi

if [[ ! "$LISTEN_PORT" =~ ^[0-9]+$ ]] || (( LISTEN_PORT < 1 || LISTEN_PORT > 65535 )); then
  echo "invalid LISTEN_PORT: $LISTEN_PORT" >&2
  exit 1
fi

if [[ ! "$KRFB_PORT" =~ ^[0-9]+$ ]] || (( KRFB_PORT < 1 || KRFB_PORT > 65535 )); then
  echo "invalid KRFB_PORT: $KRFB_PORT" >&2
  exit 1
fi

if [[ "$LISTEN_PORT" == "$KRFB_PORT" ]]; then
  echo "LISTEN_PORT and KRFB_PORT must be different" >&2
  exit 1
fi

printf 'Listening on %s:%s and forwarding to krfb on %s:%s\n' \
  "$LISTEN_HOST" "$LISTEN_PORT" "$KRFB_HOST" "$KRFB_PORT" >&2

while true; do
  if socat \
    TCP-LISTEN:"$LISTEN_PORT",bind="$LISTEN_HOST",reuseaddr \
    EXEC:"$STARTER --script"; then
    :
  else
    rc=$?
    printf '%s connection handler exited with status %s; continuing listener loop\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "$rc" >&2
  fi
  sleep 0.25
done
