from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    """MoveItでSAM3マスク中心にカメラ(手先)を横方向追従させる。

    前提(別途起動): realsense, sam3_server + ros2_realsense_object_name_bridge,
    sam3_bridge target_diff.launch, piper_single_ctrl_moveit, piper_moveit_bridge,
    piper_with_gripper_moveit piper_real_moveit.launch.py
    """
    return LaunchDescription([
        DeclareLaunchArgument('start_enabled', default_value='false'),
        DeclareLaunchArgument('gain_m_per_px', default_value='0.0004'),
        DeclareLaunchArgument('deadband_px', default_value='15.0'),
        DeclareLaunchArgument('max_step', default_value='0.03'),
        DeclareLaunchArgument('orientation_tolerance', default_value='0.0'),
        Node(
            package='piper',
            executable='moveit_follow_target',
            name='follow_target',
            output='screen',
            parameters=[{
                'start_enabled': LaunchConfiguration('start_enabled'),
                'gain_m_per_px': LaunchConfiguration('gain_m_per_px'),
                'deadband_px': LaunchConfiguration('deadband_px'),
                'max_step': LaunchConfiguration('max_step'),
                'orientation_tolerance': LaunchConfiguration('orientation_tolerance'),
            }],
        ),
    ])
