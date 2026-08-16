#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/load-vars.sh"

if [[ "${1:-}" == "--inetd" ]]; then
  if [[ "${2:-}" != "--logged" ]]; then
    exec "$RUN_COMPONENT" inetd -- "$0" --inetd --logged
  fi
  shift 2
  set -- --inetd "$@"
fi

selected_outputs=()
width=""
height=""
bytes=""
clip_x=""
clip_y=""
clip_width=""
clip_height=""

is_running() {
  if [[ -f "$PIDFILE" ]]; then
    local pid
    pid="$(cat "$PIDFILE" || true)"
    [[ -n "${pid}" ]] && kill -0 "$pid"
  else
    return 1
  fi
}

start_bridge() {
  local no_restore="${1:-0}"

  if is_running; then
    return 0
  fi

  mkdir -p "$STATE_DIR"
  rm -f "$READYFILE"
  local bridge_args=()
  if [[ "$no_restore" == "1" ]]; then
    bridge_args+=(--no-restore)
  fi

  if [[ -n "${X11VNC_WAYLAND_ECHO_LOGS:-}" ]]; then
    nohup "$RUN_COMPONENT" bridge -- \
      "$BRIDGE" -o "$RAWFB_PATH" --meta-file "$META_PATH" --token-file "$TOKEN_FILE" --ready-file "$READYFILE" --framerate "$BRIDGE_FRAMERATE" "${bridge_args[@]}" \
      >/proc/self/fd/2 2>&1 &
  else
    nohup "$RUN_COMPONENT" bridge -- \
      "$BRIDGE" -o "$RAWFB_PATH" --meta-file "$META_PATH" --token-file "$TOKEN_FILE" --ready-file "$READYFILE" --framerate "$BRIDGE_FRAMERATE" "${bridge_args[@]}" \
      >>"$BRIDGE_LOG" 2>&1 &
  fi
  local pid=$!
  echo "$pid" > "$PIDFILE"

  local waited=0
  while (( waited < 80 )); do
    if ! kill -0 "$pid"; then
      rm -f "$PIDFILE"
      echo "bridge exited early, see $BRIDGE_LOG" >&2
      return 1
    fi
    if [[ -f "$READYFILE" ]]; then
      return 0
    fi
    sleep 0.25
    waited=$((waited + 1))
  done

  return 0
}

stop_bridge() {
  local pids=()
  local pid

  if [[ -f "$PIDFILE" ]]; then
    pid="$(cat "$PIDFILE" || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid"; then
      pids+=("$pid")
    fi
  fi

  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    if [[ " ${pids[*]} " != *" $pid "* ]]; then
      pids+=("$pid")
    fi
  done < <(pgrep -f "python3 $BRIDGE" || true)

  if (( ${#pids[@]} == 0 )); then
    rm -f "$PIDFILE" "$READYFILE"
    return 0
  fi

  kill "${pids[@]}" || true
  for ((i = 0; i < 20; i++)); do
    local alive=0
    for pid in "${pids[@]}"; do
      if kill -0 "$pid"; then
        alive=1
        break
      fi
    done
    if (( alive == 0 )); then
      rm -f "$PIDFILE" "$READYFILE"
      return 0
    fi
    sleep 0.25
  done

  kill -9 "${pids[@]}" || true
  rm -f "$PIDFILE" "$READYFILE"
}

clear_logs() {
  mkdir -p "$STATE_DIR"
  find "$STATE_DIR" -mindepth 1 -maxdepth 1 \( -type f -o -type l \) -delete
  echo "State files cleared in $STATE_DIR" >&2
}

print_runtime_paths() {
  printf '%s\n' 'Runtime paths:' >&2
  printf '  SCRIPT_DIR=%s\n' "$SCRIPT_DIR" >&2
  printf '  RUNTIME_DIR=%s\n' "$RUNTIME_DIR" >&2
  printf '  STATE_DIR=%s\n' "$STATE_DIR" >&2
  printf '  RAWFB_PATH=%s\n' "$RAWFB_PATH" >&2
  printf '  META_PATH=%s\n' "$META_PATH" >&2
  printf '  TOKEN_FILE=%s\n' "$TOKEN_FILE" >&2
  printf '  PIDFILE=%s\n' "$PIDFILE" >&2
  printf '  READYFILE=%s\n' "$READYFILE" >&2
  printf '  INETD_LOG=%s\n' "$INETD_LOG" >&2
  printf '  BRIDGE_LOG=%s\n' "$BRIDGE_LOG" >&2
  printf '  PIPEINPUT_LOG=%s\n' "$PIPEINPUT_LOG" >&2
  printf '  LOG_MAX_BYTES=%s\n' "$LOG_MAX_BYTES" >&2
  printf '  LOG_KEEP_BYTES=%s\n' "$LOG_KEEP_BYTES" >&2
  printf '  BRIDGE_FRAMERATE=%s\n' "$BRIDGE_FRAMERATE" >&2
  printf '  X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE=%s\n' "$X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE" >&2
  printf '  X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS=%s\n' "$X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS" >&2
  printf '  BRIDGE=%s\n' "$BRIDGE" >&2
  printf '  PIPEINPUT_HELPER=%s\n' "$PIPEINPUT_HELPER" >&2
  printf '  RUN_COMPONENT=%s\n' "$RUN_COMPONENT" >&2
}

load_meta() {
  local key value
  selected_outputs=()
  while IFS='=' read -r key value; do
    case "$key" in
      outputs)
        if [[ -n "$value" ]]; then
          IFS='/' read -r -a selected_outputs <<< "$value"
        fi
        ;;
    esac
  done < "$META_PATH"
}

xrandr_output_geometry() {
  local target="$1"
  local line
  while IFS= read -r line; do
    if [[ "$line" =~ ^([A-Za-z0-9.-]+)[[:space:]]+connected([[:space:]]+primary)?[[:space:]]+([0-9]+)x([0-9]+)\+([0-9]+)\+([0-9]+) ]]; then
      if [[ "${BASH_REMATCH[1]}" == "$target" ]]; then
        printf '%s %s %s %s\n' \
          "${BASH_REMATCH[3]}" \
          "${BASH_REMATCH[4]}" \
          "${BASH_REMATCH[5]}" \
          "${BASH_REMATCH[6]}"
        return 0
      fi
    fi
  done < <(xrandr --query || true)
  return 1
}

compute_selection_geometry() {
  [[ -f "$META_PATH" ]] || return 1
  load_meta
  (( ${#selected_outputs[@]} > 0 )) || return 1

  local name geom ow oh ox oy
  local min_x="" min_y="" max_x=0 max_y=0
  for name in "${selected_outputs[@]}"; do
    geom="$(xrandr_output_geometry "$name")" || continue
    read -r ow oh ox oy <<< "$geom"
    [[ -n "$ow" && -n "$oh" && -n "$ox" && -n "$oy" ]] || continue
    if [[ -z "$min_x" || "$ox" -lt "$min_x" ]]; then
      min_x="$ox"
    fi
    if [[ -z "$min_y" || "$oy" -lt "$min_y" ]]; then
      min_y="$oy"
    fi
    if (( ox + ow > max_x )); then
      max_x=$((ox + ow))
    fi
    if (( oy + oh > max_y )); then
      max_y=$((oy + oh))
    fi
  done

  [[ -n "$min_x" && -n "$min_y" ]] || return 1
  width="$max_x"
  height="$max_y"
  bytes="$((width * height * 4))"
  clip_x="$min_x"
  clip_y="$min_y"
  clip_width="$((max_x - min_x))"
  clip_height="$((max_y - min_y))"
}

desktop_geometry() {
  local desktop_width desktop_height line
  desktop_width="$width"
  desktop_height="$height"
  if line="$(xrandr --query | awk '/^Screen 0:/{print $0; exit}')"; then
    if [[ "$line" =~ current[[:space:]]+([0-9]+)[[:space:]]+x[[:space:]]+([0-9]+) ]]; then
      desktop_width="${BASH_REMATCH[1]}"
      desktop_height="${BASH_REMATCH[2]}"
    fi
  fi
  printf '%s %s\n' "$desktop_width" "$desktop_height"
}

output_is_active() {
  local name="$1" path status enabled dpms
  shopt -s nullglob
  for path in /sys/class/drm/card*-"$name"; do
    [[ -d "$path" ]] || continue
    status="$(cat "$path/status" || true)"
    enabled="$(cat "$path/enabled" || true)"
    dpms="$(cat "$path/dpms" || true)"
    [[ "$status" == "connected" && "$enabled" == "enabled" && "$dpms" == "On" ]] && return 0
    return 1
  done
  shopt -u nullglob
  return 1
}

selected_outputs_active() {
  local name
  load_meta
  (( ${#selected_outputs[@]} > 0 )) || return 1
  for name in "${selected_outputs[@]}"; do
    output_is_active "$name" || return 1
  done
  return 0
}

wake_selected_outputs_best_effort() {
  local obj current max nudged

  qdbus6 \
    org.kde.Solid.PowerManagement \
    /org/kde/Solid/PowerManagement \
    org.kde.Solid.PowerManagement.wakeup || true

  while IFS= read -r obj; do
    [[ -n "$obj" ]] || continue
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
      qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.SetBrightnessWithContext "$nudged" 0 x11vnc-wayland-bridge || true
    fi
    qdbus6 org.kde.Solid.PowerManagement "$obj" org.kde.ScreenBrightness.Display.SetBrightnessWithContext "$current" 0 x11vnc-wayland-bridge || true
  done < <(qdbus6 org.kde.Solid.PowerManagement | rg '^/org/kde/ScreenBrightness/display[0-9]+$' || true)
}

wait_until_selected_outputs_active() {
  local attempt=0
  while ! selected_outputs_active; do
    attempt=$((attempt + 1))
    if (( attempt == 1 || attempt % WAKE_RETRY_EVERY == 0 )); then
      wake_selected_outputs_best_effort
    fi
    sleep "$POLL_INTERVAL"
  done
}

ensure_selection_exists() {
  if [[ -f "$META_PATH" && -f "$TOKEN_FILE" ]]; then
    return 0
  fi

  echo "No saved selection or restore token; opening a fresh portal selection for this connection." >&2
  rm -f "$META_PATH" "$TOKEN_FILE"
  start_bridge 1
  if [[ ! -f "$META_PATH" || ! -f "$TOKEN_FILE" ]]; then
    echo "missing selection or restore token after portal bootstrap" >&2
    exit 1
  fi
}

reseed_selection() {
  mkdir -p "$STATE_DIR"
  print_runtime_paths
  stop_bridge || true
  rm -f "$META_PATH" "$TOKEN_FILE"
  echo "Preparing Wayland capture metadata..." >&2
  start_bridge 1
  if [[ ! -f "$META_PATH" ]]; then
    echo "missing $META_PATH after bridge bootstrap" >&2
    exit 1
  fi
  stop_bridge || true
  echo "Wayland capture selection saved." >&2
}

run_inetd_session() {
  mkdir -p "$STATE_DIR"
  print_runtime_paths
  trap 'stop_bridge || true' EXIT INT TERM
  ensure_selection_exists

  if ! selected_outputs_active; then
    echo "Selected monitor is sleeping; sending wake request." >&2
    wake_selected_outputs_best_effort
    echo "Selected monitor is not active yet; waiting for DPMS On." >&2
    wait_until_selected_outputs_active
  fi

  start_bridge 0

  if ! compute_selection_geometry; then
    echo "invalid metadata or unresolved outputs in $META_PATH" >&2
    exit 1
  fi
  if [[ -z "$width" || -z "$height" || -z "$bytes" ]]; then
    echo "invalid geometry derived from selected outputs" >&2
    exit 1
  fi

  local desktop_width desktop_height
  read -r desktop_width desktop_height <<< "$(desktop_geometry)"

  mkdir -p "$(dirname "$RAWFB_PATH")"
  truncate -s "$bytes" "$RAWFB_PATH"

  local clip_args=()
  if [[ -n "$clip_width" && -n "$clip_height" && -n "$clip_x" && -n "$clip_y" ]]; then
    clip_args=(-clip "${clip_width}x${clip_height}+${clip_x}+${clip_y}")
  fi

  local pipe_cmd=(
    "$RUN_COMPONENT"
    pipeinput
    --
    env
    "X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE=$X11VNC_PIPEINPUT_KEY_REFRESH_NUDGE"
    "X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS=$X11VNC_PIPEINPUT_KEY_REFRESH_DELAYS_MS"
    python3
    "$PIPEINPUT_HELPER"
    --meta "$META_PATH"
    --desktop "${desktop_width}x${desktop_height}"
  )
  local pipeinput_cmd
  printf -v pipeinput_cmd '%q ' "${pipe_cmd[@]}"
  pipeinput_cmd="${pipeinput_cmd% }"

  env -u LISTEN_PID -u LISTEN_FDS -u LISTEN_FDNAMES x11vnc \
    -inetd \
    -o /proc/self/fd/2 \
    -pointer_mode 1 \
    -input_skip 0 \
    -allinput \
    -rawfb "map:${RAWFB_PATH}@${width}x${height}x32:ff0000/ff00/ff" \
    "${clip_args[@]}" \
    -pipeinput "$pipeinput_cmd" \
    -nopw
}

usage() {
  printf 'usage: %s [--clear|--reseed|--inetd]\n' "$0" >&2
}

case "${1:-}" in
  --clear)
    shift
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    clear_logs
    ;;
  --reseed)
    shift
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    reseed_selection
    ;;
  --inetd)
    shift
    if [[ "${1:-}" == "--logged" ]]; then
      shift
    fi
    [[ "$#" -eq 0 ]] || { usage; exit 2; }
    run_inetd_session
    ;;
  "")
    printf '%s\n' 'Use --reseed to save the monitor selection. Runtime now happens via systemd socket activation.' >&2
    ;;
  *)
    usage
    exit 2
    ;;
esac
