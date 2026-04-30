#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to MOVE to the target position (-0.192781, 0.823378)"
    read imp
    source install/setup.bash

    ros2 topic pub -1 /goal_pose geometry_msgs/msg/PoseStamped "{
      header: {
        stamp: {sec: 0, nanosec: 0},
        frame_id: 'map'
      },
      pose: {
        position: {
          x: -0.192781,
          y: 0.823378,
          z: 0.0
        },
        orientation: {
          x: 0.0,
          y: 0.0,
          z: -0.343753,
          w: 0.93906
        }
      }
    }"
done

