#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/load-vars.sh"

usage() {
  printf 'usage: %s <component> -- <command> [args...]\n' "$0" >&2
}

component="${1:-}"

[[ -n "$component" ]] || {
  usage
  exit 2
}

shift
[[ "${1:-}" == "--" ]] || {
  usage
  exit 2
}
shift
[[ "$#" -gt 0 ]] || {
  usage
  exit 2
}

log_file="$(component_log_file "$component")"

logger_cmd() {
  local echo_mode="none"
  case "${X11VNC_WAYLAND_ECHO_LOGS:-}" in
    all)
      echo_mode="all"
      ;;
    1|errors)
      echo_mode="errors"
      ;;
  esac

  if [[ "$component" == "listener" && "$echo_mode" == "none" ]]; then
    echo_mode="errors"
  fi

  LOGPIPE_COMPONENT="$component" \
  LOGPIPE_FILE="$log_file" \
  LOGPIPE_MAX_BYTES="$LOG_MAX_BYTES" \
  LOGPIPE_KEEP_BYTES="$LOG_KEEP_BYTES" \
  LOGPIPE_ECHO_MODE="$echo_mode" \
  python3 "$PIPE_LOGS"
}

case "$component" in
  inetd)
    exec 2> >(logger_cmd)
    ;;
  listener|bridge|pipeinput)
    exec > >(logger_cmd) 2>&1
    ;;
  *)
    usage
    exit 2
    ;;
esac

exec "$@"
