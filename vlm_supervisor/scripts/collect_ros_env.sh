#!/usr/bin/env bash
# ROS graph / FlexBE interface を調査してファイルに保存する (Phase 1 の topic 確認, Phase 2 の FlexBE 調査用).
# FlexBE の behavior を実行中に走らせると status/heartbeat/structure の実例も取れる.
#
# コンテナ内で:
#   bash /ros2_ws/vlm_supervisor/scripts/collect_ros_env.sh
# 出力: vlm_supervisor/logs/ros_env_<date>/ (このディレクトリを共有すればよい)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$SCRIPT_DIR")"
WS_DIR="$(dirname "$PKG_DIR")"
umask 000
set +u
source /opt/ros/humble/setup.bash
[ -f "$WS_DIR/install/setup.bash" ] && source "$WS_DIR/install/setup.bash"

OUT="${VLM_SUPERVISOR_LOG_DIR:-$PKG_DIR/logs}/ros_env_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
echo "[collect] output: $OUT"

run() {  # run <file> <timeout> <cmd...>
  local f="$1" t="$2"; shift 2
  echo "\$ $*" >> "$OUT/$f"
  timeout "$t" "$@" >> "$OUT/$f" 2>&1
  echo "[exit $?]" >> "$OUT/$f"
  echo >> "$OUT/$f"
}

{
  echo "date: $(date -Is)"
  echo "ROS_DISTRO=$ROS_DISTRO ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-} RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-}"
} > "$OUT/env.txt"

run graph.txt 15 ros2 node list
run graph.txt 15 ros2 topic list -t
run graph.txt 15 ros2 service list -t
run graph.txt 15 ros2 action list -t

# FlexBE interface
for m in BEStatus BehaviorSync ContainerStructure Container BehaviorSelection BehaviorLog OutcomeRequest; do
  run flexbe_interfaces.txt 10 ros2 interface show flexbe_msgs/msg/$m
done
run flexbe_interfaces.txt 10 ros2 interface show flexbe_msgs/srv/GetUserdata
run flexbe_interfaces.txt 10 ros2 pkg prefix flexbe_core
run flexbe_interfaces.txt 10 bash -c "ros2 pkg xml flexbe_core | grep -m1 '<version>'"

# FlexBE topic の情報と実例 (behavior 実行中でないと echo は timeout する)
for t in $(ros2 topic list 2>/dev/null | grep -E '/flexbe/'); do
  run flexbe_topics_info.txt 10 ros2 topic info -v "$t"
done
for t in /flexbe/status /flexbe/heartbeat /flexbe/behavior_update /flexbe/debug/current_state; do
  run flexbe_echo.txt 4 ros2 topic echo --once "$t"
done
run flexbe_echo.txt 4 ros2 service call /get_user_data flexbe_msgs/srv/GetUserdata "{userdata_key: ''}"

# Phase 1 対象 topic の周期と型
for t in /camera/camera/color/image_raw /camera/camera/color/image_raw/compressed /joint_states /odom /sam3/result /sam3/result_points /sam3/bbox; do
  if ros2 topic list 2>/dev/null | grep -qx "$t"; then
    run sensor_topics.txt 10 ros2 topic info -v "$t"
    run sensor_topics.txt 6 ros2 topic hz "$t" --window 20
  else
    echo "$t: (not published)" >> "$OUT/sensor_topics.txt"
  fi
done
run sensor_topics.txt 6 ros2 run tf2_ros tf2_echo base_link link6

echo "[collect] done: $OUT"
ls -la "$OUT"
