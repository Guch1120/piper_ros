# コチャカ (Kobuki + カチャカシェルフ + Piper の合成モバイルマニピュレータ) を
# Unity シミュレータ経由で動かすための launch。
#
# 起動するもの:
#   1. robot_state_publisher    (mobile_manipulator.urdf.xacro から生成した robot_description)
#   2. kobuki_unity パッケージの start_kobuki_unity.launch.py (IncludeLaunchDescription)
#      -> kobuki_unity_sim_node (commands/velocity を購読し、odom/joint_states を実機と
#         同じインターフェースでpublishしつつ、内部で Unity と /kobuki_unity/wheel_cmd,
#         /kobuki_unity/wheel_states を介して通信する) + ros_tcp_endpoint
#   3. rviz2                    (既存の rviz/mobile_manipulator.rviz を流用)
#   4. joint_state_publisher    (Piper アーム側の joint1..6, joint7/8 等を既定値0で埋める。
#      kobuki_unity_sim_node は車輪の joint_states しか publish しないため、これが無いと
#      アーム部分の TF が RViz 上で欠落してしまう。robot_state_publisher は同一トピック
#      /joint_states に届く複数の JointState メッセージをジョイント名単位でマージするため、
#      車輪分は kobuki_unity_sim_node から、アーム分はこちらから、それぞれ問題なく供給できる)
#
# 使い方の例 (別ターミナルから):
#   ros2 topic pub /commands/velocity geometry_msgs/msg/Twist \
#     '{linear: {x: 0.1}, angular: {z: 0.0}}' -r 10
#   または: ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args -r cmd_vel:=commands/velocity
#
# NOTE (Docker環境): mobile_manipulator.urdf.xacro が kobuki_description を参照するため、
# view_mobile_manipulator.launch.py と同様にコンテナ内で
#   source /ros2_ws/install/setup.bash
#   source /home/kobuki_ws/install/setup.bash
# の両方を source してから実行すること。

from ament_index_python.packages import get_package_share_path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import Command, LaunchConfiguration

from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    pkg_share_path = get_package_share_path('mobile_manipulator_description')
    default_model_path = pkg_share_path / 'urdf/mobile_manipulator.urdf.xacro'
    default_rviz_config_path = pkg_share_path / 'rviz/mobile_manipulator.rviz'

    kobuki_unity_launch_path = (
        get_package_share_path('kobuki_unity') / 'launch' / 'start_kobuki_unity.launch.py'
    )

    model_arg = DeclareLaunchArgument(
        name='model', default_value=str(default_model_path),
        description='Absolute path to robot urdf/xacro file')
    rviz_arg = DeclareLaunchArgument(
        name='rvizconfig', default_value=str(default_rviz_config_path),
        description='Absolute path to rviz config file')
    log_level_arg = DeclareLaunchArgument(
        name='log_level', default_value='info',
        description='Logging level for kobuki_unity_sim (debug, info, warn, error, fatal).')
    external_arm_joint_states_arg = DeclareLaunchArgument(
        name='external_arm_joint_states', default_value='false',
        description=(
            'Set true when piper_unity publishes the arm joint states. '
            'This prevents the composite launch from publishing zero-valued defaults.'))

    robot_description = ParameterValue(
        Command(['xacro ', LaunchConfiguration('model')]), value_type=str)

    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
    )

    # Piper アーム側 (kobuki_unity が publish しない joint) を既定値0で埋める。
    # gui は使わない (テレオペで見たいのは車輪/base の動きであり、アームの手動姿勢調整ではないため)。
    arm_joint_state_publisher_node = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        condition=UnlessCondition(LaunchConfiguration('external_arm_joint_states')),
    )

    kobuki_unity_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(kobuki_unity_launch_path)),
        launch_arguments={
            'log_level': LaunchConfiguration('log_level'),
        }.items(),
    )

    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', LaunchConfiguration('rvizconfig')],
    )

    return LaunchDescription([
        model_arg,
        rviz_arg,
        log_level_arg,
        external_arm_joint_states_arg,
        robot_state_publisher_node,
        arm_joint_state_publisher_node,
        kobuki_unity_launch,
        rviz_node,
    ])
