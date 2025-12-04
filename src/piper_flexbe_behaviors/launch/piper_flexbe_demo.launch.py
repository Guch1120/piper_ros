from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch.substitutions import PathJoinSubstitution, LaunchConfiguration
from launch_ros.substitutions import FindPackageShare

def generate_launch_description():
    
    # 1. Realsense Launch
    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('realsense2_camera'),
                'launch',
                'rs_launch.py'
            ])
        ]),
        launch_arguments={
            'align_depth.enable': 'true',
            'enable_sync': 'true',
            'enable_rgbd': 'true'
        }.items()
    )

    # 2. Detic Node (Disabled by user request)
    # detic_node = Node(
    #     package='detic_onnx_ros2',
    #     executable='detic_onnx_ros2_node',
    #     name='detic_onnx_ros2_node',
    #     output='screen'
    # )

    # 3. Piper MoveIt Launch
    piper_moveit_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('piper_with_gripper_moveit'),
                'launch',
                'piper_real_moveit.launch.py'
            ])
        ])
    )

    # 4. Piper Bridge Node
    piper_bridge_node = Node(
        package='piper',
        executable='piper_moveit_bridge',
        name='piper_moveit_bridge',
        output='screen'
    )

    # 5. FlexBE App (UI)
    flexbe_app_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            PathJoinSubstitution([
                FindPackageShare('flexbe_app'),
                'launch',
                'flexbe_full.launch.py'
            ])
        ])
    )

    return LaunchDescription([
        realsense_launch,
        # detic_node,
        piper_moveit_launch,
        piper_bridge_node,
        flexbe_app_launch
    ])
