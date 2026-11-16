"""Webシミュレータ(kotyaka_web_sim)をMoveItから動かすための統合launch。

実機用 `piper/launch/start_single_moveit_piper_action.launch.py` +
`piper_with_gripper_moveit/launch/piper_real_moveit.launch.py` に相当するシミュレータ版。

起動するもの:
  1. rosbridge_websocket + rosapi  (piper/launch/rosbridge_websocket.launch.py を include。既定 ws://:9090)
  2. trajectory_bridge             (FollowJointTrajectory action serverの代わりをする。ブラウザへ軌道を転送)
  3. robot_state_publisher + move_group (piper_with_gripper_moveit の設定。use_sim_time は既定 true)
  4. (任意) rviz2                  (rviz:=true)

実機との関係:
  trajectory_bridge は実機ノード `piper_single_ctrl_moveit_action` と**同じaction名**
  (/arm_controller/follow_joint_trajectory, /gripper_controller/follow_joint_trajectory) を提供する。
  MoveIt側の設定(moveit_controllers.yaml)は実機と共通のまま、action serverだけが入れ替わる。
  そのため実機用ノードとは**同時に起動しないこと**。

前提:
  - ブラウザでWeb simに rosbridge 接続し「再生」していること (use_sim_time が Web の /clock に従う)。
  - ROS_DOMAIN_ID は rosbridge と同じ(12)であること。

使い方:
  ros2 launch piper_websim websim_moveit.launch.py
  ros2 launch piper_websim websim_moveit.launch.py rviz:=true
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from moveit_configs_utils import MoveItConfigsBuilder


def generate_launch_description():
    moveit_config = MoveItConfigsBuilder("piper", package_name="piper_with_gripper_moveit").to_moveit_configs()

    port = LaunchConfiguration("port")
    use_sim_time = ParameterValue(LaunchConfiguration("use_sim_time"), value_type=bool)
    sim_time_param = {"use_sim_time": use_sim_time}

    bridge_params = os.path.join(get_package_share_directory("piper_websim"), "config", "bridge.yaml")

    rosbridge = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory("piper"), "launch", "rosbridge_websocket.launch.py")
        ),
        launch_arguments={"port": port}.items(),
    )

    trajectory_bridge = Node(
        package="piper_websim",
        executable="trajectory_bridge",
        name="piper_websim",  # config/bridge.yaml のルートキーと一致させる
        output="screen",
        parameters=[bridge_params, sim_time_param],
    )

    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both",
        parameters=[moveit_config.robot_description, sim_time_param],
    )

    move_group = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        parameters=[
            moveit_config.to_dict(),
            {
                "publish_robot_description_semantic": True,
                "allow_trajectory_execution": True,
                "publish_planning_scene": True,
                "publish_geometry_updates": True,
                "publish_state_updates": True,
                "publish_transforms_updates": True,
                "monitor_dynamics": False,
                # piper_with_gripper_moveit の既定は chomp。Web simの初期姿勢(joint2/3が可動域の端=0)では
                # "Goal state violates joint limits" で失敗したため、Web sim側の検証済み構成と同じ ompl を既定にする。
                "default_planning_pipeline": "ompl",
                # bridgeはブラウザの再生に合わせて壁時計で軌道を再生する。
                # Webの/clockと壁時計がずれても実行を打ち切らないよう、実行時間監視を無効にする。
                "trajectory_execution.execution_duration_monitoring": False,
                "trajectory_execution.allowed_execution_duration_scaling": 3.0,
                "trajectory_execution.allowed_goal_duration_margin": 5.0,
                "trajectory_execution.allowed_start_tolerance": 0.05,
            },
            sim_time_param,
        ],
    )

    rviz = Node(
        package="rviz2",
        executable="rviz2",
        output="log",
        arguments=["-d", LaunchConfiguration("rviz_config")],
        parameters=[
            moveit_config.planning_pipelines,
            moveit_config.robot_description,
            moveit_config.robot_description_semantic,
            moveit_config.robot_description_kinematics,
            sim_time_param,
        ],
        condition=IfCondition(LaunchConfiguration("rviz")),
    )

    return LaunchDescription([
        DeclareLaunchArgument("port", default_value="9090", description="rosbridge_websocket port (ws://)"),
        DeclareLaunchArgument("use_sim_time", default_value="true", description="WebシミュレータのROS /clock に従う"),
        DeclareLaunchArgument("rviz", default_value="false", description="RViz2(MotionPlanning)も起動する"),
        DeclareLaunchArgument(
            "rviz_config",
            default_value=str(moveit_config.package_path / "config/moveit.rviz"),
        ),
        rosbridge,
        trajectory_bridge,
        robot_state_publisher,
        move_group,
        rviz,
    ])
