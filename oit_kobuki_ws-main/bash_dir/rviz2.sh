#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to launch RViz2..."
    read imp
    source install/setup.bash
    rviz2 
done

