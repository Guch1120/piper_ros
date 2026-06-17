import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from moveit_configs_utils import MoveItConfigsBuilder
from moveit_configs_utils.launch_utils import add_debuggable_node, DeclareBooleanLaunchArg

os.environ["RCUTILS_COLORIZED_OUTPUT"] = "1"


def generate_launch_description():
    moveit_config = MoveItConfigsBuilder(
        "piper", package_name="piper_with_gripper_moveit"
    ).to_moveit_configs()

    ld = LaunchDescription()

    # Launch arguments
    ld.add_action(DeclareLaunchArgument(
        'log_level', default_value='info',
        description='Logging level (debug, info, warn, error, fatal).'))
    ld.add_action(DeclareLaunchArgument(
        'auto_enable', default_value='true',
        description='Automatically enable the sim node.'))
    ld.add_action(DeclareLaunchArgument(
        'gripper_exist', default_value='true',
        description='Whether gripper is present.'))
    ld.add_action(DeclareBooleanLaunchArg("debug", default_value=False))
    ld.add_action(DeclareBooleanLaunchArg("allow_trajectory_execution", default_value=True))
    ld.add_action(DeclareBooleanLaunchArg("publish_monitored_planning_scene", default_value=True))
    ld.add_action(DeclareLaunchArgument("capabilities", default_value=""))
    ld.add_action(DeclareLaunchArgument("disable_capabilities", default_value=""))
    ld.add_action(DeclareLaunchArgument(
        "rviz_config",
        default_value=str(moveit_config.package_path / "config/moveit.rviz")))

    # 1. robot_state_publisher: /joint_states → TF
    ld.add_action(Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="screen",
        parameters=[moveit_config.robot_description],
    ))

    # 2. move_group (MoveIt2)
    should_publish = LaunchConfiguration("publish_monitored_planning_scene")
    move_group_params = [
        moveit_config.to_dict(),
        {
            "publish_robot_description_semantic": True,
            "allow_trajectory_execution": LaunchConfiguration("allow_trajectory_execution"),
            "capabilities": LaunchConfiguration("capabilities"),
            "disable_capabilities": LaunchConfiguration("disable_capabilities"),
            "publish_planning_scene": should_publish,
            "publish_geometry_updates": should_publish,
            "publish_state_updates": should_publish,
            "publish_transforms_updates": should_publish,
            "monitor_dynamics": False,
            "use_sim_time": False,
            # Unity sim: disable start-state deviation check (robot may not be at plan start)
            "trajectory_execution.allowed_start_tolerance": 0.0,
        },
    ]
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

    # 3. RViz
    add_debuggable_node(
        ld,
        package="rviz2",
        executable="rviz2",
        output="log",
        respawn=False,
        arguments=["-d", LaunchConfiguration("rviz_config")],
        parameters=[
            moveit_config.planning_pipelines,
            moveit_config.robot_description_kinematics,
            moveit_config.robot_description,
            {"use_sim_time": False},
        ],
    )

    # 4. piper_unity_sim_node (Unity simulator bridge, same external interface as real hardware)
    ld.add_action(Node(
        package='piper_unity',
        executable='piper_unity_sim',
        name='piper_ctrl_single_node',  # same node name as real hardware for compatibility
        output='screen',
        ros_arguments=['--log-level', LaunchConfiguration('log_level')],
        parameters=[{
            'auto_enable': LaunchConfiguration('auto_enable'),
            'gripper_exist': LaunchConfiguration('gripper_exist'),
        }],
        remappings=[
            ('joint_states_single', '/joint_states'),  # match MoveIt2 expectation
        ],
    ))

    # 5. ROS-TCP-Endpoint (Unity ↔ ROS2 TCP bridge, port 10000)
    ld.add_action(Node(
        package='ros_tcp_endpoint',
        executable='default_server_endpoint',
        emulate_tty=True,
        parameters=[{'ROS_IP': '0.0.0.0'}, {'ROS_TCP_PORT': 10000}],
    ))

    return ld
