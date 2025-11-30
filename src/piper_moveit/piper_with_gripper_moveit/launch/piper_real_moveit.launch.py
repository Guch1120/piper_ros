import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launch_utils import add_debuggable_node, DeclareBooleanLaunchArg

def generate_launch_description():
    # 1. MoveItの設定を読み込む
    moveit_config = MoveItConfigsBuilder("piper", package_name="piper_with_gripper_moveit").to_moveit_configs()

    ld = LaunchDescription()

    # 2. robot_state_publisher (重要: これがないとRVizにロボットが出ない)
    #    URDFを読み込んで、関節角度(/joint_states)からリンクの位置(TF)を計算する
    rsp_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both", #screen と logの両方．ターミナルにログを流すし.ros/logにファイルとしても保存している
        parameters=[moveit_config.robot_description],
    )
    ld.add_action(rsp_node)

    # 3. move_group (MoveItの脳みそ)
    my_generate_move_group_launch(ld, moveit_config)

    # 4. RViz (表示画面)
    my_generate_moveit_rviz_launch(ld, moveit_config)

    return ld


def my_generate_move_group_launch(ld, moveit_config):
    # 実機なので use_sim_time は False にする
    use_sim_time = False

    ld.add_action(DeclareBooleanLaunchArg("debug", default_value=False))
    ld.add_action(DeclareBooleanLaunchArg("allow_trajectory_execution", default_value=True))
    ld.add_action(DeclareBooleanLaunchArg("publish_monitored_planning_scene", default_value=True))
    ld.add_action(DeclareLaunchArgument("capabilities", default_value=""))
    ld.add_action(DeclareLaunchArgument("disable_capabilities", default_value=""))
    ld.add_action(DeclareBooleanLaunchArg("monitor_dynamics", default_value=False))

    should_publish = LaunchConfiguration("publish_monitored_planning_scene")

    move_group_configuration = {
        "publish_robot_description_semantic": True,
        "allow_trajectory_execution": LaunchConfiguration("allow_trajectory_execution"),
        "capabilities": ParameterValue(LaunchConfiguration("capabilities"), value_type=str),
        "disable_capabilities": ParameterValue(LaunchConfiguration("disable_capabilities"), value_type=str),
        "publish_planning_scene": should_publish,
        "publish_geometry_updates": should_publish,
        "publish_state_updates": should_publish,
        "publish_transforms_updates": should_publish,
        "monitor_dynamics": False,
    }

    move_group_params = [
        moveit_config.to_dict(),
        move_group_configuration,
    ]
    # ここ重要：実機なら False
    move_group_params.append({"use_sim_time": use_sim_time})

    add_debuggable_node(
        ld,
        package="moveit_ros_move_group",
        executable="move_group",
        commands_file=str(moveit_config.package_path / "launch" / "gdb_settings.gdb"),
        output="screen",
        parameters=move_group_params,
        extra_debug_args=["--debug"],
        additional_env={"DISPLAY": ":0"},
    )
    return ld

def my_generate_moveit_rviz_launch(ld, moveit_config):
    # 実機なので use_sim_time は False
    use_sim_time = False

    ld.add_action(DeclareBooleanLaunchArg("debug", default_value=False))
    ld.add_action(
        DeclareLaunchArgument(
            "rviz_config",
            default_value=str(moveit_config.package_path / "config/moveit.rviz"),
        )
    )

    rviz_parameters = [
        moveit_config.planning_pipelines,
        moveit_config.robot_description_kinematics,
        # ▼▼▼ これを追加！ ▼▼▼
        # RVizがロボットモデルを表示するために必要
        moveit_config.robot_description,
    ]
    rviz_parameters.append({"use_sim_time": use_sim_time})

    add_debuggable_node(
        ld,
        package="rviz2",
        executable="rviz2",
        output="log",
        respawn=False,
        arguments=["-d", LaunchConfiguration("rviz_config")],
        parameters=rviz_parameters,
    )

    return ld