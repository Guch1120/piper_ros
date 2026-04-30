#!/bin/bash

cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "Press Enter to MOVE to thegoal position (4.56804, -7.25028)"
    read imp
    source install/setup.bash

    ros2 topic pub -1 /goal_pose geometry_msgs/msg/PoseStamped "{
      header: {
        stamp: {sec: 0, nanosec: 0},
        frame_id: 'map'
      },
      pose: {
        position: {
          x: 4.56804,
          y: -7.25028,
          z: 0.0
        },
        orientation: {
          x: 0.0,
          y: 0.0,
          z: -0.91006,
          w: 0.414476
        }
      }
    }"
done

