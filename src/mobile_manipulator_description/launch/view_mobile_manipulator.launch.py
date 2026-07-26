# Kobuki + カチャカシェルフ(placeholder) + Piper の合成モバイルマニピュレータを
# joint_state_publisher_gui + robot_state_publisher + rviz2 で表示確認するための launch。
#
# NOTE (Docker環境):
# piper_ros (piper-humble-dev コンテナ, /ros2_ws) と oit_kobuki_ws-main
# (oit-kobuki-ws-ros2 コンテナ) はファイルシステムを共有していない別コンテナのため、
# mobile_manipulator.urdf.xacro が参照する kobuki_description パッケージを
# piper-humble-dev コンテナから見えるようにする必要がある。
# docker/docker-compose.yml の piper-humble-dev サービスに
#   - ../../oit_kobuki_ws-main:/home/kobuki_ws:ro
# を追加済み(要: `docker compose ... up -d --force-recreate piper-humble-dev` でコンテナ再作成)。
# この launch を実行する前に、コンテナ内で以下を両方 source すること:
#   source /ros2_ws/install/setup.bash
#   source /home/kobuki_ws/install/setup.bash

from ament_index_python.packages import get_package_share_path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import Command, LaunchConfiguration

from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_share_path = get_package_share_path('mobile_manipulator_description')
    default_model_path = pkg_share_path / 'urdf/mobile_manipulator.urdf.xacro'
    default_rviz_config_path = pkg_share_path / 'rviz/mobile_manipulator.rviz'

    gui_arg = DeclareLaunchArgument(
        name='gui', default_value='true', choices=['true', 'false'],
        description='Flag to enable joint_state_publisher_gui')
    model_arg = DeclareLaunchArgument(
        name='model', default_value=str(default_model_path),
        description='Absolute path to robot urdf/xacro file')
    rviz_arg = DeclareLaunchArgument(
        name='rvizconfig', default_value=str(default_rviz_config_path),
        description='Absolute path to rviz config file')

    robot_description = ParameterValue(
        Command(['xacro ', LaunchConfiguration('model')]), value_type=str)

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description}]
    )

    # Depending on gui parameter, either launch joint_state_publisher or joint_state_publisher_gui.
    # NOTE: this only exercises the static/TODO joint configuration for visual inspection of the
    # combined Kobuki + Kachaka shelf + Piper geometry; it does not drive the real robot.
    joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        condition=UnlessCondition(LaunchConfiguration('gui'))
    )

    joint_state_publisher_gui_node = Node(
        package='joint_state_publisher_gui',
        executable='joint_state_publisher_gui',
        parameters=[{'rate': 200.0}],
        condition=IfCondition(LaunchConfiguration('gui'))
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rvizconfig')],
    )

    return LaunchDescription([
        gui_arg,
        model_arg,
        rviz_arg,
        joint_state_publisher_node,
        joint_state_publisher_gui_node,
        robot_state_publisher_node,
        rviz_node
    ])
