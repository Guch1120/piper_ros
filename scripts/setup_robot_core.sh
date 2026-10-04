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

log "Installing dependencies and building Kobuki Robot Core workspace"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps kobuki-robot-core bash -lc '
  set -e
  source /opt/ros/humble/setup.bash
  apt-get update
  rosdep update
  mapfile -t robot_core_paths < <(
    colcon list --paths-only --packages-up-to \
      kobuki_node \
      kobuki_description \
      kobuki_safety_controller \
      nav2_bringup \
      slam_toolbox \
      urg_node2
  )
  rosdep install -i --from-paths "${robot_core_paths[@]}" --rosdistro humble -y
  colcon --log-base log/robot_core build \
    --build-base build/robot_core \
    --install-base install/robot_core \
    --symlink-install \
    --executor sequential \
    --cmake-args -DBUILD_TESTING=OFF \
    --packages-up-to \
      kobuki_node \
      kobuki_description \
      kobuki_safety_controller \
      nav2_bringup \
      slam_toolbox \
      urg_node2
'

log "Installing dependencies and building Piper/Cotyaka Robot Core workspace"
docker compose -f "$COMPOSE_FILE" run --rm --no-deps piper-robot-core bash -lc '
  set -e
  source /opt/ros/humble/setup.bash
  source /home/kobuki/kobuki_ws/install/robot_core/setup.bash
  apt-get update
  rosdep update
  mapfile -t robot_core_paths < <(
    colcon list --paths-only --packages-up-to \
      cotyaka_bringup \
      cotyaka_system \
      cotyaka_audio
  )
  rosdep install -i \
    --from-paths \
      "${robot_core_paths[@]}" \
      src/mobile_manipulator_description \
      /home/kobuki/kobuki_ws/src/kobuki_ros/kobuki_description \
    --rosdistro humble \
    -y
  colcon --log-base log/robot_core build \
    --build-base build/robot_core \
    --install-base install/robot_core \
    --symlink-install \
    --packages-up-to \
      cotyaka_bringup \
      cotyaka_system \
      cotyaka_audio
  source install/robot_core/setup.bash
  colcon --log-base log/robot_core build \
    --build-base build/robot_core \
    --install-base install/robot_core \
    --symlink-install \
    --packages-select mobile_manipulator_description
'

log "Setup complete. If /dev/kobuki is absent, unplug/replug the Kobuki USB cable."
log "Then run: bash scripts/robot_core.sh up"
