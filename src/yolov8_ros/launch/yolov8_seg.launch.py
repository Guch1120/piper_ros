from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument(
            'model_path',
            default_value='yolov8n-seg.pt',
            description='Path to YOLOv8 segmentation model'
        ),
        DeclareLaunchArgument(
            'device',
            default_value='cpu',
            description='Device to run inference on (cpu or cuda)'
        ),
        DeclareLaunchArgument(
            'conf_thres',
            default_value='0.5',
            description='Confidence threshold'
        ),
        DeclareLaunchArgument(
            'iou_thres',
            default_value='0.45',
            description='IoU threshold'
        ),
        Node(
            package='yolov8_ros',
            executable='yolov8_seg_node',
            name='yolov8_seg_node',
            output='screen',
            parameters=[{
                'model_path': LaunchConfiguration('model_path'),
                'device': LaunchConfiguration('device'),
                'conf_thres': LaunchConfiguration('conf_thres'),
                'iou_thres': LaunchConfiguration('iou_thres'),
            }]
        )
    ])
