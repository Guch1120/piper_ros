cmake_minimum_required(VERSION 3.8)
project(sam3_bridge)

find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(cv_bridge REQUIRED)

install(
  DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

install(PROGRAMS
  scripts/object_name_bridge.py
  scripts/click_segment_bridge.py
  scripts/drag_segment_bridge.py
  scripts/grpc_bridge.py
  scripts/ros_publisher.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()