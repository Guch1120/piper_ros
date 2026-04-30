from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _arg(name: str, default: str, description: str):
    return DeclareLaunchArgument(name, default_value=default, description=description)


def generate_launch_description() -> LaunchDescription:
    launch_args = [
        _arg("backend", "ros2", "Backend to use: auto, ros1, or ros2"),
        _arg("node_name", "sam3_dual_ros", "Node name"),
        _arg("checkpoint_path", "", "Optional checkpoint path"),
        _arg("device", "cuda", "Torch device"),
        _arg("resolution", "854", "Inference resolution"),
        _arg("text_prompt", "", "Optional text prompt"),
        _arg("image_topic", "/camera/camera/color/image_raw", "Input image topic"),
        _arg("prompt_topic", "/sam3/request", "Prompt topic"),
        _arg("annotated_topic", "/sam3/annotated_image", "Annotated image topic"),
        _arg("masks_topic", "/sam3/masks", "Masks topic"),
        _arg("boxes_topic", "/sam3/boxes", "Boxes topic"),
        _arg("scores_topic", "/sam3/scores", "Scores topic"),
        _arg("frame_id", "camera", "Frame id"),
        _arg("input_encoding", "bgr8", "Input image encoding"),
        _arg("queue_size", "1", "Queue size"),
    ]

    node = Node(
        package="sam3_dual_ros",
        executable="sam3-dual-ros",
        name=LaunchConfiguration("node_name"),
        output="screen",
        arguments=[
            "--backend", LaunchConfiguration("backend"),
            "--node-name", LaunchConfiguration("node_name"),
            "--checkpoint-path", LaunchConfiguration("checkpoint_path"),
            "--device", LaunchConfiguration("device"),
            "--resolution", LaunchConfiguration("resolution"),
            "--text-prompt", LaunchConfiguration("text_prompt"),
            "--image-topic", LaunchConfiguration("image_topic"),
            "--prompt-topic", LaunchConfiguration("prompt_topic"),
            "--annotated-topic", LaunchConfiguration("annotated_topic"),
            "--masks-topic", LaunchConfiguration("masks_topic"),
            "--boxes-topic", LaunchConfiguration("boxes_topic"),
            "--scores-topic", LaunchConfiguration("scores_topic"),
            "--frame-id", LaunchConfiguration("frame_id"),
            "--input-encoding", LaunchConfiguration("input_encoding"),
            "--queue-size", LaunchConfiguration("queue_size"),
        ],
    )

    return LaunchDescription(launch_args + [node])
