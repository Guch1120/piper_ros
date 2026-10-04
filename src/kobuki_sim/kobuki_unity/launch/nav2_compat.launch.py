"""Small compatibility layer between nav2_bringup and the Kotyaka Unity
simulator's kobuki_unity_sim_node.

nav2's costmaps (robot_base_frame) expect a 'base_link' frame that this
simulator does not publish (only base_footprint), and nav2's
controller_server publishes velocity commands on 'cmd_vel' while
kobuki_unity_sim_node subscribes to 'commands/velocity' (matching the real
kobuki_node's external interface). Both gaps mirror steps the real robot
also needs by hand (see oit_kobuki_ws-main/bash_dir/tf_basefootprint_baselink.sh)
- this launch file just makes them repeatable. Bring this up alongside
start_kobuki_unity.launch.py whenever nav2 is used against the simulator.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    ld = LaunchDescription()

    ld.add_action(DeclareLaunchArgument(
        'base_frame', default_value='base_footprint',
        description='Robot base frame id actually published by the simulator.'))
    ld.add_action(DeclareLaunchArgument(
        'nav2_base_frame', default_value='base_link',
        description='robot_base_frame expected by nav2 costmaps.'))
    ld.add_action(DeclareLaunchArgument(
        'cmd_vel_topic', default_value='cmd_vel',
        description="nav2 controller_server's velocity command output topic."))
    ld.add_action(DeclareLaunchArgument(
        'velocity_topic', default_value='commands/velocity',
        description='kobuki_unity_sim_node/real kobuki_node velocity command input topic.'))

    ld.add_action(Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='base_footprint_to_base_link',
        arguments=[
            '0', '0', '0', '0', '0', '0',
            LaunchConfiguration('base_frame'),
            LaunchConfiguration('nav2_base_frame'),
        ],
    ))

    ld.add_action(Node(
        package='kobuki_unity',
        executable='cmd_vel_relay',
        name='kotyaka_cmd_vel_relay',
        parameters=[{
            'input_topic': LaunchConfiguration('cmd_vel_topic'),
            'output_topic': LaunchConfiguration('velocity_topic'),
        }],
    ))

    return ld
