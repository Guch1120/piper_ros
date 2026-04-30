#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    read -p "Enter map filename (or just Enter to quit): " FILENAME
    if [ -z "$FILENAME" ]; then
        echo "Exit."
        break
    fi

    source install/setup.bash
    ros2 run nav2_map_server map_saver_cli -f ~/kobuki_ws/map/$FILENAME
done
