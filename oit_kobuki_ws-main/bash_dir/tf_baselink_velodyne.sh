#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to   0 0 0.48 0 0 0 "base_link" "velodyne"..."
    read imp
    source install/setup.bash
    ros2 run tf2_ros static_transform_publisher 0 0 0.48 0 0 0 "base_link" "velodyne"
done

