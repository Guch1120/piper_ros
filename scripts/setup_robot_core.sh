#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="${COTYAKA_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
COMPOSE_FILE="$REPO_DIR/docker/docker-compose.robot-core.yml"
KOBUKI_WS="${KOBUKI_WS:-$(cd "$REPO_DIR/.." && pwd)/oit_kobuki_ws-main}"

log() { echo "[cotyaka-setup] $*"; }

command -v docker >/dev/null || { log "docker command not found"; exit 1; }
docker info >/dev/null 2>&1 || { log "Docker daemon is not available"; exit 1; }
[[ -d "$KOBUKI_WS" ]] || { log "Kobuki workspace not found: $KOBUKI_WS"; exit 1; }

log "Installing Kobuki udev rule"
bash "$REPO_DIR/scripts/install_kobuki_udev.sh"

log "Pulling VOICEVOX CPU engine"
docker compose -f "$COMPOSE_FILE" pull cotyaka-voicevox

log "Building Robot Core, System Monitor and Audio container images"
docker compose -f "$COMPOSE_FILE" build

log "Installing dependencies and building Piper/Cotyaka workspace"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps piper-robot-core bash -lc '
  set -e
  source /opt/ros/humble/setup.bash
  rosdep update
  rosdep install -i --from-path src --rosdistro humble -y
  colcon build --symlink-install
'

log "Installing dependencies and building Kobuki workspace"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps kobuki-robot-core bash -lc '
  set -e
  source /opt/ros/humble/setup.bash
  rosdep update
  rosdep install -i --from-path src --rosdistro humble -y
  colcon build --symlink-install --executor sequential
'

log "Setup complete. If /dev/kobuki is absent, unplug/replug the Kobuki USB cable."
log "Then run: bash scripts/robot_core.sh up"
