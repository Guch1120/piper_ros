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

python3 src/kobuki_ble/ble_server.py
