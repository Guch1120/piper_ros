from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, Command
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    # Arguments
    piper_description_path = get_package_share_directory('piper_description')
    xacro_file = os.path.join(piper_description_path, 'urdf', 'piper_description.xacro')
    
    # Robot State Publisher (TF) - Required for Expected CoR
    robot_description = ParameterValue(Command(['xacro ', xacro_file]), value_type=str)
    
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        parameters=[{'robot_description': robot_description}]
    )
    
    # Calibration Node
    calibration_node = Node(
        package='piper',
        executable='camera_calibration',
        name='camera_calibration_node',
        output='screen'
    )
    
    return LaunchDescription([
        robot_state_publisher_node,
        calibration_node
    ])
