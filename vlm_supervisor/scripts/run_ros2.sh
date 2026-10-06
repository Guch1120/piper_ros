#!/usr/bin/env bash
# VLM Supervisor (ROS 2) を起動し, console 出力も logs/<run_id>/console.log に保存する.
#
# コンテナ内で:
#   bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh [追加の --ros-args ...]
# 例:
#   bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh --ros-args -p use_sim_time:=true
#   SUPERVISOR_CONFIG=/ros2_ws/vlm_supervisor/config/my.yaml bash .../run_ros2.sh
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
WS_DIR="$(dirname "$PKG_DIR")"          # piper_ros (= コンテナ内 /ros2_ws)

# コンテナ(root)で作ったログをホストのユーザーでも消せるように
umask 000

set +u
source /opt/ros/humble/setup.bash
[ -f "$WS_DIR/install/setup.bash" ] && source "$WS_DIR/install/setup.bash"
set -u

export PYTHONPATH="$WS_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
export RCUTILS_COLORIZED_OUTPUT=0
export VLM_SUPERVISOR_LOG_DIR="${VLM_SUPERVISOR_LOG_DIR:-$PKG_DIR/logs}"
export VLM_SUPERVISOR_RUN_ID="${VLM_SUPERVISOR_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="$VLM_SUPERVISOR_LOG_DIR/$VLM_SUPERVISOR_RUN_ID"
mkdir -p "$RUN_DIR"

SUPERVISOR_CONFIG="${SUPERVISOR_CONFIG:-$PKG_DIR/config/supervisor.yaml}"
TOPICS_CONFIG="${TOPICS_CONFIG:-$PKG_DIR/config/topics.yaml}"

{
  echo "date: $(date -Is)"
  echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-} RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
  echo "supervisor_config=$SUPERVISOR_CONFIG"
  echo "topics_config=$TOPICS_CONFIG"
  echo "args: $*"
  echo "git: $(git -C "$WS_DIR" rev-parse --short HEAD 2>/dev/null) $(git -C "$WS_DIR" status --porcelain -- vlm_supervisor 2>/dev/null | wc -l) uncommitted file(s) in vlm_supervisor"
} > "$RUN_DIR/env.txt"

echo "[run_ros2] log dir: $RUN_DIR"
cd "$WS_DIR"
EXTRA=("$@")
if [ "${EXTRA[0]:-}" = "--ros-args" ]; then EXTRA=("${EXTRA[@]:1}"); fi
python3 -m vlm_supervisor.ros2.supervisor_node --ros-args \
  -p supervisor_config:="$SUPERVISOR_CONFIG" -p topics_config:="$TOPICS_CONFIG" \
  "${EXTRA[@]}" 2>&1 | tee "$RUN_DIR/console.log"
status=${PIPESTATUS[0]}
echo "[run_ros2] exited with status $status. log dir: $RUN_DIR"
exit "$status"
