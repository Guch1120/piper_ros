#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to launch kobuki_keyop..."
    read imp
    source install/setup.bash
    ros2 run kobuki_keyop kobuki_keyop_node cmd_vel:=/commands/velocity
done

