from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
import os

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('can_port', default_value='can0'),
        DeclareLaunchArgument('auto_enable', default_value='true'),
        DeclareLaunchArgument('gripper_exist', default_value='true'),
        DeclareLaunchArgument('visual_servo_enable', default_value='true'),
        
        Node(
            package='piper',
            executable='piper_single_ctrl_moveit_visual_servo',
            name='piper_ctrl_single_visual_servo',
            output='screen',
            parameters=[{
                'can_port': LaunchConfiguration('can_port'),
                'auto_enable': LaunchConfiguration('auto_enable'),
                'gripper_exist': LaunchConfiguration('gripper_exist'),
                'visual_servo_enable': LaunchConfiguration('visual_servo_enable'),
                'gain_x': 0.00005, # Conservative initial gain
                'gain_y': 0.00005,
            }],
            remappings=[
                ('joint_states_single', '/joint_states')
            ]
        )
    ])
