#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    read -p "Enter map filename (without path, or Enter to quit): " FILENAME
    if [ -z "$FILENAME" ]; then
        echo "Exit."
        break
    fi

    source install/setup.bash
    ros2 launch nav2_bringup bringup_launch.py use_sim_time:=False map:=/home/user25/kobuki_ws/map/$FILENAME.yaml
done
