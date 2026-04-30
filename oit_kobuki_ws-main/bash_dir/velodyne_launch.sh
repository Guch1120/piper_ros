#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to launch velodyne-all-nodes-VLP16 ..."
    read imp
    source install/setup.bash
    ros2 launch velodyne velodyne-all-nodes-VLP16-launch.py
done

