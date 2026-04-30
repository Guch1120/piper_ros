#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to launch slam_toolbox..."
    read imp
    source install/setup.bash
    ros2 launch slam_toolbox online_async_launch.py
done

