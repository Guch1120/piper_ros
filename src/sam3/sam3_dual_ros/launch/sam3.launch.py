from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.substitutions import FindPackagePrefix


def _arg(name: str, default: str, description: str):
    return DeclareLaunchArgument(
        name,
        default_value=default,
        description=description,
    )


def _launch_setup(context, *args, **kwargs):
    package_prefix = FindPackagePrefix("sam3_dual_ros").perform(context)

    backend = LaunchConfiguration("backend").perform(context)
    node_name = LaunchConfiguration("node_name").perform(context)
    checkpoint_path = LaunchConfiguration("checkpoint_path").perform(context)
    device = LaunchConfiguration("device").perform(context)
    resolution = LaunchConfiguration("resolution").perform(context)
    text_prompt = LaunchConfiguration("text_prompt").perform(context)

    image_topic = LaunchConfiguration("image_topic").perform(context)
    prompt_topic = LaunchConfiguration("prompt_topic").perform(context)
    annotated_topic = LaunchConfiguration("annotated_topic").perform(context)
    masks_topic = LaunchConfiguration("masks_topic").perform(context)
    boxes_topic = LaunchConfiguration("boxes_topic").perform(context)
    scores_topic = LaunchConfiguration("scores_topic").perform(context)

    frame_id = LaunchConfiguration("frame_id").perform(context)
    input_encoding = LaunchConfiguration("input_encoding").perform(context)
    queue_size = LaunchConfiguration("queue_size").perform(context)

    executable_path = f"{package_prefix}/lib/sam3_dual_ros/sam3-dual-ros"

    cmd = [
        executable_path,
        "--backend", backend,
        "--node-name", node_name,
        "--device", device,
        "--resolution", resolution,
        "--image-topic", image_topic,
        "--prompt-topic", prompt_topic,
        "--annotated-topic", annotated_topic,
        "--masks-topic", masks_topic,
        "--boxes-topic", boxes_topic,
        "--scores-topic", scores_topic,
        "--frame-id", frame_id,
        "--input-encoding", input_encoding,
        "--queue-size", queue_size,
    ]

    # 空文字のときは渡さない。
    # 渡してしまうと `--checkpoint-path --device cuda` のように崩れる。
    if checkpoint_path:
        cmd.extend(["--checkpoint-path", checkpoint_path])

    if text_prompt:
        cmd.extend(["--text-prompt", text_prompt])

    return [
        ExecuteProcess(
            cmd=cmd,
            output="screen",
            name=node_name,
        )
    ]


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

    return LaunchDescription(
        launch_args + [
            OpaqueFunction(function=_launch_setup),
        ]
    )