from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([Node(package="piper_websim", executable="vision_bridge", name="piper_websim_vision_bridge", output="screen")])
