#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${COTYAKA_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="${COTYAKA_COMPOSE_FILE:-$REPO_DIR/docker/docker-compose.robot-core.yml}"
CAN_INTERFACE="${CAN_INTERFACE:-can0}"
CAN_BITRATE="${CAN_BITRATE:-1000000}"
PIPER_PROBE_MODE="${PIPER_PROBE_MODE:-can-traffic}"
PIPER_PROBE_TIMEOUT_SEC="${PIPER_PROBE_TIMEOUT_SEC:-2}"
KOBUKI_DEVICE="${KOBUKI_DEVICE:-/dev/kobuki}"
KOBUKI_WS="${KOBUKI_WS:-$REPO_DIR/../oit_kobuki_ws-main}"

PIPER_DETECTED=false
KOBUKI_DETECTED=false

log() { echo "[cotyaka] $*"; }
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

common_preflight() {
  command -v docker >/dev/null || { log "docker command not found"; exit 1; }
  docker info >/dev/null 2>&1 || { log "Docker daemon is not available"; exit 1; }
  [[ -f "$REPO_DIR/install/setup.bash" ]] || {
    log "Cotyaka workspace is not built. Run scripts/setup_robot_core.sh first."
    exit 1
  }
}

probe_piper() {
  PIPER_DETECTED=false

  if ! ip -br link show type can 2>/dev/null | grep -q .; then
    log "Piper: no CAN adapter detected"
    return 1
  fi

  if ! bash "$REPO_DIR/can_activate.sh" "$CAN_INTERFACE" "$CAN_BITRATE" >/tmp/cotyaka-can-activate.log 2>&1; then
    log "Piper: CAN activation failed (see /tmp/cotyaka-can-activate.log)"
    return 1
  fi

  if [[ "$PIPER_PROBE_MODE" == "adapter" ]]; then
    PIPER_DETECTED=true
    log "Piper: CAN adapter is ready (adapter-only probe)"
    return 0
  fi

  if ! command -v candump >/dev/null; then
    log "Piper: candump not found; install can-utils on the host or use PIPER_PROBE_MODE=adapter"
    return 1
  fi

  if timeout "${PIPER_PROBE_TIMEOUT_SEC}s" candump -n 1 "$CAN_INTERFACE" >/tmp/cotyaka-piper-can-frame.log 2>&1; then
    PIPER_DETECTED=true
    log "Piper: CAN traffic detected"
    return 0
  fi

  log "Piper: CAN adapter exists but no Piper traffic was observed"
  return 1
}

probe_kobuki() {
  KOBUKI_DETECTED=false
  if [[ -e "$KOBUKI_DEVICE" ]]; then
    KOBUKI_DETECTED=true
    log "Kobuki: detected at $KOBUKI_DEVICE"
    return 0
  fi
  log "Kobuki: $KOBUKI_DEVICE not found"
  return 1
}

probe_components() {
  probe_piper || true
  probe_kobuki || true
  log "Detected components: piper=$PIPER_DETECTED kobuki=$KOBUKI_DETECTED"
}

validate_selected_workspaces() {
  if [[ "$PIPER_DETECTED" == true && ! -f "$REPO_DIR/install/setup.bash" ]]; then
    log "Piper/Cotyaka workspace is not built"
    exit 1
  fi
  if [[ "$KOBUKI_DETECTED" == true && ! -f "$KOBUKI_WS/install/setup.bash" ]]; then
    log "Kobuki workspace is not built: $KOBUKI_WS/install/setup.bash"
    exit 1
  fi
}

start_stack() {
  common_preflight
  probe_components
  validate_selected_workspaces

  export COTYAKA_EXPECT_PIPER="$PIPER_DETECTED"
  export COTYAKA_EXPECT_KOBUKI="$KOBUKI_DETECTED"

  compose stop piper-robot-core kobuki-robot-core >/dev/null 2>&1 || true

  services=(cotyaka-audio cotyaka-system-monitor)
  [[ "$PIPER_DETECTED" == true ]] && services+=(piper-robot-core)
  [[ "$KOBUKI_DETECTED" == true ]] && services+=(kobuki-robot-core)

  log "Starting services: ${services[*]}"
  compose up -d "${services[@]}"
  compose ps
}

case "${1:-}" in
  preflight)
    common_preflight
    probe_components
    validate_selected_workspaces
    ;;
  probe)
    probe_components
    ;;
  up)
    start_stack
    ;;
  down)
    log "Stopping Cotyaka stack"
    compose down
    ;;
  restart)
    "$0" down
    "$0" up
    ;;
  status)
    compose ps
    ;;
  logs)
    compose logs -f --tail=200
    ;;
  *)
    echo "Usage: $0 {preflight|probe|up|down|restart|status|logs}" >&2
    exit 2
    ;;
esac
