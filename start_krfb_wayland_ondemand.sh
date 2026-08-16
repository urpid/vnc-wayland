#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/load-vars.sh"

require_commands() {
  local command
  for command in "$@"; do
    if ! command -v "$command" >/dev/null; then
      echo "missing dependency: $command" >&2
      exit 1
    fi
  done
}

validate_port() {
  local name="$1"
  local port="$2"
  if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
    echo "invalid $name: $port" >&2
    exit 1
  fi
}

validate_positive_integer() {
  local name="$1"
  local value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]] || (( value < 1 )); then
    echo "invalid $name: $value" >&2
    exit 1
  fi
}

configure_krfb_port() {
  kwriteconfig6 --file krfbrc --group TCP --key useDefaultPort false
  kwriteconfig6 --file krfbrc --group TCP --key port "$KRFB_PORT"
}

clear_krfb_portal_restore_token() {
  local state_home="${XDG_STATE_HOME:-$HOME/.local/state}"

  kwriteconfig6 \
    --file "$state_home/krfbstaterc" \
    --group XdgPortal \
    --key RestoreToken \
    --delete ''
}

outputs_active() {
  local path status enabled dpms
  local found=0
  local inactive=0

  shopt -s nullglob
  for path in /sys/class/drm/card*-*; do
    [[ -r "$path/status" && -r "$path/enabled" && -r "$path/dpms" ]] || continue
    status="$(<"$path/status")"
    enabled="$(<"$path/enabled")"
    [[ "$status" == "connected" && "$enabled" == "enabled" ]] || continue
    found=1
    dpms="$(<"$path/dpms")"
    if [[ "$dpms" != "On" ]]; then
      inactive=1
    fi
  done
  shopt -u nullglob

  (( found == 1 && inactive == 0 ))
}

wake_outputs_best_effort() {
  local obj current max nudged

  qdbus6 \
    org.kde.Solid.PowerManagement \
    /org/kde/Solid/PowerManagement \
    org.kde.Solid.PowerManagement.wakeup || true

  while IFS= read -r obj; do
    [[ "$obj" =~ ^/org/kde/ScreenBrightness/display[0-9]+$ ]] || continue
    current="$(qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.Brightness || true)"
    max="$(qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.MaxBrightness || true)"
    [[ "$current" =~ ^[0-9]+$ && "$max" =~ ^[0-9]+$ ]] || continue

    nudged="$current"
    if (( current < max )); then
      nudged=$((current + 1))
    elif (( current > 0 )); then
      nudged=$((current - 1))
    fi

    if (( nudged != current )); then
      qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.SetBrightnessWithContext "$nudged" 0 krfb-wayland || true
    fi
    qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.SetBrightnessWithContext "$current" 0 krfb-wayland || true
  done < <(qdbus6 org.kde.Solid.PowerManagement || true)
}

wait_until_outputs_active() {
  local attempt=1
  while ! outputs_active; do
    if (( attempt % WAKE_RETRY_EVERY == 0 )); then
      wake_outputs_best_effort
    fi
    sleep "$POLL_INTERVAL"
    attempt=$((attempt + 1))
  done
}

krfb_port_ready() {
  local line
  while IFS= read -r line; do
    if [[ "$line" == *'(("krfb",pid='* ]]; then
      return 0
    fi
  done < <(ss -H -ltnp "sport = :$KRFB_PORT")
  return 1
}

wait_for_krfb() {
  local start_mode="$1"
  local krfb_pid="${2:-}"
  local attempts=$((KRFB_START_TIMEOUT * 4))
  local attempt

  for ((attempt = 0; attempt < attempts; attempt++)); do
    if krfb_port_ready; then
      return 0
    fi
    if [[ "$start_mode" == "direct" ]] && ! kill -0 "$krfb_pid" 2>/dev/null; then
      echo "krfb exited before port $KRFB_PORT became ready" >&2
      return 1
    fi
    if [[ "$start_mode" == "systemd" ]] && ! systemctl --user is-active --quiet "$KRFB_UNIT"; then
      echo "krfb exited before port $KRFB_PORT became ready" >&2
      return 1
    fi
    sleep 0.25
  done

  echo "krfb did not open port $KRFB_PORT within $KRFB_START_TIMEOUT seconds" >&2
  return 1
}

stop_krfb_processes() {
  pkill -TERM -u "$EUID" -x krfb 2>/dev/null || true

  local attempt
  for ((attempt = 0; attempt < 20; attempt++)); do
    if ! pgrep -u "$EUID" -x krfb >/dev/null; then
      return 0
    fi
    sleep 0.25
  done

  pkill -KILL -u "$EUID" -x krfb 2>/dev/null || true
  sleep 0.25
  if pgrep -u "$EUID" -x krfb >/dev/null; then
    echo "krfb did not stop" >&2
    return 1
  fi
}

restart_krfb() {
  local start_mode="$1"

  if [[ "$start_mode" == "systemd" ]]; then
    systemctl --user stop "$KRFB_UNIT" 2>/dev/null || true
    stop_krfb_processes
    systemctl --user start "$KRFB_UNIT"
    if ! wait_for_krfb systemd; then
      systemctl --user stop "$KRFB_UNIT" 2>/dev/null || true
      stop_krfb_processes
      return 1
    fi
    return
  fi

  stop_krfb_processes
  krfb --nodialog </dev/null >/dev/null &
  local krfb_pid=$!
  if ! wait_for_krfb direct "$krfb_pid"; then
    stop_krfb_processes
    return 1
  fi
}

run_setup() {
  require_commands krfb kwriteconfig6 pgrep pkill qdbus6
  validate_port KRFB_PORT "$KRFB_PORT"
  stop_krfb_processes
  configure_krfb_port
  clear_krfb_portal_restore_token
  echo "krfb uses port $KRFB_PORT. Configure desktop sharing and the VNC password." >&2

  local kwin_plugin=krfb-wayland-setup-quit-on-close
  local kwin_script="$SCRIPT_DIR/quit_krfb_on_close.js"
  local script_id

  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$kwin_plugin" >/dev/null 2>&1 || true
  if ! script_id="$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$kwin_script" "$kwin_plugin")"; then
    echo "could not load the KWin setup close watcher" >&2
    return 1
  fi
  if [[ ! "$script_id" =~ ^[0-9]+$ ]]; then
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$kwin_plugin" >/dev/null 2>&1 || true
    echo "could not load the KWin setup close watcher" >&2
    return 1
  fi
  if ! qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start; then
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$kwin_plugin" >/dev/null 2>&1 || true
    echo "could not start the KWin setup close watcher" >&2
    return 1
  fi

  krfb &
  local krfb_pid=$!
  trap "kill $krfb_pid 2>/dev/null || true; qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript $kwin_plugin >/dev/null 2>&1 || true" INT TERM EXIT

  local status=0
  local unload_result
  wait "$krfb_pid" || status=$?
  if ! unload_result="$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$kwin_plugin")" || [[ "$unload_result" != "true" ]]; then
    echo "could not unload the KWin setup close watcher" >&2
    status=1
  fi
  trap - INT TERM EXIT
  return "$status"
}

run_connection_session() {
  local start_mode="$1"

  require_commands krfb kwriteconfig6 pgrep pkill qdbus6 socat ss
  if [[ "$start_mode" == "systemd" ]]; then
    require_commands systemctl
  fi
  validate_port LISTEN_PORT "$LISTEN_PORT"
  validate_port KRFB_PORT "$KRFB_PORT"
  validate_positive_integer KRFB_START_TIMEOUT "$KRFB_START_TIMEOUT"
  validate_positive_integer POLL_INTERVAL "$POLL_INTERVAL"
  validate_positive_integer WAKE_RETRY_EVERY "$WAKE_RETRY_EVERY"
  if [[ "$LISTEN_PORT" == "$KRFB_PORT" ]]; then
    echo "LISTEN_PORT and KRFB_PORT must be different" >&2
    exit 1
  fi
  if [[ "$start_mode" == "systemd" ]] && ! systemctl --user cat "$KRFB_UNIT" >/dev/null 2>&1; then
    echo "missing systemd user unit: $KRFB_UNIT" >&2
    exit 1
  fi
  configure_krfb_port

  local outputs_were_active=0
  if outputs_active; then
    outputs_were_active=1
  else
    echo "Monitor is sleeping; sending wake request and waiting for DPMS On." >&2
  fi

  wake_outputs_best_effort

  if (( outputs_were_active == 0 )); then
    wait_until_outputs_active
    echo "Monitor is active; restarting krfb with a fresh PipeWire session." >&2
    restart_krfb "$start_mode"
  elif ! krfb_port_ready; then
    echo "krfb is not available on port $KRFB_PORT; starting it." >&2
    restart_krfb "$start_mode"
  fi

  exec socat STDIO "TCP:${KRFB_HOST}:${KRFB_PORT},nodelay"
}

usage() {
  printf 'usage: %s [--setup|--script|--socket]\n' "$0" >&2
}

case "${1:-}" in
  --setup)
    shift
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    run_setup
    ;;
  --script)
    shift
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    run_connection_session direct
    ;;
  --socket)
    shift
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    run_connection_session systemd
    ;;
  *)
    usage
    exit 2
    ;;
esac
