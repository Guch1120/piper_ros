from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    ld = LaunchDescription()

    # Launch arguments (mirror kobuki_node_params.yaml defaults)
    ld.add_action(DeclareLaunchArgument(
        'log_level', default_value='info',
        description='Logging level (debug, info, warn, error, fatal).'))
    ld.add_action(DeclareLaunchArgument(
        'cmd_vel_timeout_sec', default_value='0.6',
        description='Seconds without commands/velocity before zero-ing wheel '
                    'velocities (mirrors real kobuki_node cmd_vel_timeout_sec).'))
    ld.add_action(DeclareLaunchArgument(
        'odom_frame', default_value='odom', description='Odometry frame id.'))
    ld.add_action(DeclareLaunchArgument(
        'base_frame', default_value='base_footprint', description='Robot base frame id.'))
    ld.add_action(DeclareLaunchArgument(
        'publish_tf', default_value='true',
        description='Whether to broadcast the odom_frame -> base_frame TF.'))
    ld.add_action(DeclareLaunchArgument(
        'wheel_left_joint_name', default_value='wheel_left_joint',
        description='Name of the left wheel joint.'))
    ld.add_action(DeclareLaunchArgument(
        'wheel_right_joint_name', default_value='wheel_right_joint',
        description='Name of the right wheel joint.'))

    # 1. kobuki_unity_sim_node (Unity simulator bridge, same external interface as real kobuki_node)
    ld.add_action(Node(
        package='kobuki_unity',
        executable='kobuki_unity_sim',
        name='kobuki',  # same node name as real hardware (kobuki_node) for compatibility
        output='screen',
        ros_arguments=['--log-level', LaunchConfiguration('log_level')],
        parameters=[{
            'cmd_vel_timeout_sec': LaunchConfiguration('cmd_vel_timeout_sec'),
            'odom_frame': LaunchConfiguration('odom_frame'),
            'base_frame': LaunchConfiguration('base_frame'),
            'publish_tf': LaunchConfiguration('publish_tf'),
            'wheel_left_joint_name': LaunchConfiguration('wheel_left_joint_name'),
            'wheel_right_joint_name': LaunchConfiguration('wheel_right_joint_name'),
        }],
    ))

    # 2. ROS-TCP-Endpoint (Unity <-> ROS2 TCP bridge, port 10000 - same as piper_unity)
    ld.add_action(Node(
        package='ros_tcp_endpoint',
        executable='default_server_endpoint',
        emulate_tty=True,
        parameters=[{'ROS_IP': '0.0.0.0'}, {'ROS_TCP_PORT': 10000}],
    ))

    return ld
