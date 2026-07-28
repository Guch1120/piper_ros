cmake_minimum_required(VERSION 3.8)
project(sam3_bridge)

find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(std_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(cv_bridge REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Sam3Object.msg"
  "msg/Sam3ObjectArray.msg"
  "msg/StringArray.msg"
  DEPENDENCIES std_msgs
)

install(
  DIRECTORY launch config
  DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

install(PROGRAMS
  scripts/object_name_bridge.py
  scripts/object_tracking_by_using_depth.py
  scripts/click_segment_bridge.py
  scripts/drag_segment_bridge.py
  scripts/drag_segment_gui.py
  scripts/grpc_bridge.py
  scripts/ros_publisher.py
  scripts/ros2_realsense_object_name_bridge_node.py
  scripts/gemma4_image_node.py
  scripts/gemma4_wait_enter_key_and_msg_node.py
  scripts/wait_enter_and_pub_msg_node.py
  DESTINATION lib/${PROJECT_NAME}
)

install(
  DIRECTORY scripts/click_segment/
  DESTINATION lib/${PROJECT_NAME}/click_segment
  FILES_MATCHING PATTERN "*.py"
)

install(
  DIRECTORY scripts/drag_segment/
  DESTINATION lib/${PROJECT_NAME}/drag_segment
  FILES_MATCHING PATTERN "*.py"
)


install(FILES
  scripts/segment_overlay_pb2.py
  scripts/segment_overlay_pb2_grpc.py
  scripts/segment_pb2.py
  scripts/segment_pb2_grpc.py
  scripts/ping_pb2.py
  scripts/ping_pb2_grpc.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
