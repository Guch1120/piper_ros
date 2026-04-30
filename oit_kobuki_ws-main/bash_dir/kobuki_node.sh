#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to launch kobuki_node..."
    read imp
    source install/setup.bash
    ros2 launch kobuki_node kobuki_node-launch.py
done

