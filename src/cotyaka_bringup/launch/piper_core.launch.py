import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    piper_share = get_package_share_directory('piper')
    moveit_share = get_package_share_directory('piper_with_gripper_moveit')

    piper_driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(piper_share, 'launch', 'start_single_moveit_piper.launch.py')
        ),
        launch_arguments={
            'can_port': 'can0',
            'auto_enable': 'true',
            'gripper_exist': 'true',
        }.items(),
    )

    moveit_rsp = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(moveit_share, 'launch', 'rsp.launch.py')
        )
    )

    move_group = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(moveit_share, 'launch', 'move_group.launch.py')
        )
    )

    moveit_bridge = Node(
        package='piper',
        executable='piper_moveit_bridge',
        name='piper_moveit_bridge',
        output='screen',
    )

    return LaunchDescription([
        piper_driver,
        moveit_rsp,
        move_group,
        moveit_bridge,
    ])
