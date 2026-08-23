#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${COTYAKA_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="${COTYAKA_COMPOSE_FILE:-$REPO_DIR/docker/docker-compose.robot-core.yml}"
CAN_INTERFACE="${CAN_INTERFACE:-can0}"
CAN_BITRATE="${CAN_BITRATE:-1000000}"

log() { echo "[cotyaka-robot-core] $*"; }

preflight() {
  command -v docker >/dev/null || { log "docker command not found"; exit 1; }
  docker info >/dev/null 2>&1 || { log "Docker daemon is not available"; exit 1; }

  if [[ ! -f "$REPO_DIR/can_activate.sh" ]]; then
    log "can_activate.sh not found under $REPO_DIR"
    exit 1
  fi

  log "Configuring $CAN_INTERFACE at $CAN_BITRATE bit/s"
  bash "$REPO_DIR/can_activate.sh" "$CAN_INTERFACE" "$CAN_BITRATE"

  ip link show "$CAN_INTERFACE" | grep -q 'UP' || {
    log "$CAN_INTERFACE is not UP after CAN configuration"
    exit 1
  }

  [[ -f "$REPO_DIR/install/setup.bash" ]] || {
    log "Piper workspace is not built. Run scripts/setup_robot_core.sh first."
    exit 1
  }

  if [[ ! -f "$REPO_DIR/../oit_kobuki_ws-main/install/setup.bash" ]]; then
    log "Kobuki workspace is not built: $REPO_DIR/../oit_kobuki_ws-main/install/setup.bash"
    exit 1
  fi
}

case "${1:-}" in
  preflight)
    preflight
    ;;
  up)
    preflight
    log "Starting Docker Compose robot core"
    docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  down)
    log "Stopping Docker Compose robot core"
    docker compose -f "$COMPOSE_FILE" down
    ;;
  restart)
    "$0" down
    "$0" up
    ;;
  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;
  logs)
    docker compose -f "$COMPOSE_FILE" logs -f --tail=200
    ;;
  *)
    echo "Usage: $0 {preflight|up|down|restart|status|logs}" >&2
    exit 2
    ;;
esac
