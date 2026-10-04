"""AMR_TOOLKIT YAML を使う Kobuki Nav2 巡回 launch。"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            "waypoint_file", default_value="",
            description="AMR_TOOLKIT の waypoint YAML"),
        DeclareLaunchArgument(
            "map_yaml", default_value="",
            description="旧 points 形式の pixel->world 変換に使う map YAML"),
        DeclareLaunchArgument("frame_id", default_value="map"),
        DeclareLaunchArgument("action_name", default_value="navigate_to_pose"),
        DeclareLaunchArgument("start_delay_sec", default_value="1.0"),
        DeclareLaunchArgument("goal_timeout_sec", default_value="180.0"),
        DeclareLaunchArgument("localization_timeout_sec", default_value="30.0"),
        DeclareLaunchArgument("localization_settle_sec", default_value="2.0"),
        DeclareLaunchArgument("inter_goal_settle_sec", default_value="2.0"),
        DeclareLaunchArgument("amcl_pose_max_age_sec", default_value="2.0"),
        DeclareLaunchArgument("clear_costmaps_before_goal", default_value="true"),
        DeclareLaunchArgument("publish_initial_pose", default_value="false"),
        DeclareLaunchArgument("initial_pose_x", default_value="0.0"),
        DeclareLaunchArgument("initial_pose_y", default_value="0.0"),
        DeclareLaunchArgument("initial_pose_yaw", default_value="0.0"),
        DeclareLaunchArgument("initial_pose_stamp_offset_sec", default_value="0.2"),
        DeclareLaunchArgument("initial_pose_publish_count", default_value="6"),
        DeclareLaunchArgument("initial_pose_publish_period_sec", default_value="0.5"),
        Node(
            package="kobuki_unity",
            executable="waypoint_patrol",
            name="waypoint_patrol",
            output="screen",
            parameters=[{
                "waypoint_file": LaunchConfiguration("waypoint_file"),
                "map_yaml": LaunchConfiguration("map_yaml"),
                "frame_id": LaunchConfiguration("frame_id"),
                "action_name": LaunchConfiguration("action_name"),
                "start_delay_sec": LaunchConfiguration("start_delay_sec"),
                "goal_timeout_sec": LaunchConfiguration("goal_timeout_sec"),
                "localization_timeout_sec": LaunchConfiguration("localization_timeout_sec"),
                "localization_settle_sec": LaunchConfiguration("localization_settle_sec"),
                "inter_goal_settle_sec": LaunchConfiguration("inter_goal_settle_sec"),
                "amcl_pose_max_age_sec": LaunchConfiguration("amcl_pose_max_age_sec"),
                "clear_costmaps_before_goal": LaunchConfiguration(
                    "clear_costmaps_before_goal"),
                "publish_initial_pose": LaunchConfiguration("publish_initial_pose"),
                "initial_pose_x": LaunchConfiguration("initial_pose_x"),
                "initial_pose_y": LaunchConfiguration("initial_pose_y"),
                "initial_pose_yaw": LaunchConfiguration("initial_pose_yaw"),
                "initial_pose_stamp_offset_sec": LaunchConfiguration(
                    "initial_pose_stamp_offset_sec"),
                "initial_pose_publish_count": LaunchConfiguration(
                    "initial_pose_publish_count"),
                "initial_pose_publish_period_sec": LaunchConfiguration(
                    "initial_pose_publish_period_sec"),
                "use_sim_time": False,
            }],
        ),
    ])
