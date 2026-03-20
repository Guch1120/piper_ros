from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        Node(
            package='sam3_ros',
            executable='sam3_node',
            name='sam3_node',
            output='screen',
            parameters=[
                {'model_path': ''},
                {'device': 'cuda'}
            ]
        )
    ])
