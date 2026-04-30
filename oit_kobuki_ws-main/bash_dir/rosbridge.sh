#!/bin/bash

set -euo pipefail

cd ~/kobuki_ws
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-12}"

set +u
source /opt/ros/humble/setup.bash
if [ -f install/setup.bash ]; then
    source install/setup.bash
fi
set -u

ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
    port:=9090 \
    default_call_service_timeout:=5.0 \
    call_services_in_new_thread:=true \
    send_action_goals_in_new_thread:=true
