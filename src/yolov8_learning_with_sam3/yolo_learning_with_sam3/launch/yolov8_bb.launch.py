from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():

    return LaunchDescription([

        Node(
            package='yolov8_learning_with_sam3',
            executable='yolov8_node_bb',
            name='yolov8_node_bb',
            output='screen',
            parameters=[{
                'image_topic': '/camera/camera/color/image_raw',
                'model': '/ros2_ws/src/sam3/sam3_for_YOLO_Learning/models/best.pt',
                'mode': 'detection',
                'device': 'cuda:0',
            }]
        ),

        # Node(
        #     package='yolov8_learning_with_sam3',
        #     executable='debug_yolov8_bb_node',
        #     name='debug_yolov8_bb',
        #     output='screen',
        # ),
    ])
