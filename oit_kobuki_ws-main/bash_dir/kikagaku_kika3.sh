#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to kika3"
    read imp
    source install/setup.bash
    ros2 run kikagaku kika3


done

