"""Command line entrypoint for SAM3 ROS integration."""

from __future__ import annotations

import argparse

from .bridge import resolve_backend
from .config import RosTopicConfig, Sam3ModelConfig, Sam3RosConfig


def _build_config(args: argparse.Namespace) -> Sam3RosConfig:
    model = Sam3ModelConfig(
        checkpoint_path=args.checkpoint_path,
        device=args.device,
        load_from_hf=not args.no_load_from_hf,
        enable_segmentation=not args.no_segmentation,
        enable_inst_interactivity=args.enable_inst_interactivity,
        compile=args.compile,
        resolution=args.resolution,
        use_autocast=None if args.autocast is None else bool(args.autocast),
        use_channels_last=None
        if args.channels_last is None
        else bool(args.channels_last),
        text_prompt=args.text_prompt,
        cache_text_features=not args.disable_text_cache,
        query_limit=args.query_limit,
        decoder_layers=args.decoder_layers,
        image_encoder_onnx_path=args.image_encoder_onnx or None,
        onnx_provider=args.onnx_provider,
        onnx_trt_fp16=not args.disable_onnx_trt_fp16,
    )
    topics = RosTopicConfig(
        image_topic=args.image_topic,
        prompt_topic=args.prompt_topic,
        annotated_topic=args.annotated_topic,
        masks_topic=args.masks_topic,
        boxes_topic=args.boxes_topic,
        scores_topic=args.scores_topic,
        frame_id=args.frame_id,
        input_encoding=args.input_encoding,
        queue_size=args.queue_size,
    )
    return Sam3RosConfig(
        model=model,
        topics=topics,
        backend=args.backend,
        node_name=args.node_name,
        drop_frames_when_busy=not args.keep_all_frames,
    )


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SAM3 as a ROS1 or ROS2 node")
    parser.add_argument("--backend", default="auto", choices=("auto", "ros1", "ros2"))
    parser.add_argument("--node-name", default="sam3_ros")
    parser.add_argument("--checkpoint-path", default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--no-load-from-hf", action="store_true")
    parser.add_argument("--no-segmentation", action="store_true")
    parser.add_argument("--enable-inst-interactivity", action="store_true")
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--resolution", type=int, default=854)
    parser.add_argument("--autocast", dest="autocast", action="store_true")
    parser.add_argument("--no-autocast", dest="autocast", action="store_false")
    parser.set_defaults(autocast=None)
    parser.add_argument(
        "--channels-last", dest="channels_last", action="store_true"
    )
    parser.add_argument(
        "--no-channels-last", dest="channels_last", action="store_false"
    )
    parser.set_defaults(channels_last=None)
    parser.add_argument("--disable-text-cache", action="store_true")
    parser.add_argument("--query-limit", type=int, default=0)
    parser.add_argument("--decoder-layers", type=int, default=0)
    parser.add_argument("--image-encoder-onnx", default="")
    parser.add_argument(
        "--onnx-provider",
        default="tensorrt",
        choices=("tensorrt", "cuda", "cpu"),
    )
    parser.add_argument("--disable-onnx-trt-fp16", action="store_true")
    parser.add_argument("--text-prompt", default="")
    parser.add_argument("--image-topic", default="/camera/image_raw")
    parser.add_argument("--prompt-topic", default="/sam3/text_prompt")
    parser.add_argument("--annotated-topic", default="/sam3/annotated_image")
    parser.add_argument("--masks-topic", default="/sam3/masks")
    parser.add_argument("--boxes-topic", default="/sam3/boxes")
    parser.add_argument("--scores-topic", default="/sam3/scores")
    parser.add_argument("--frame-id", default="camera")
    parser.add_argument("--input-encoding", default="bgr8")
    parser.add_argument("--queue-size", type=int, default=1)
    parser.add_argument("--keep-all-frames", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    config = _build_config(args)
    bindings = resolve_backend(config.backend)

    if bindings.version == 2:
        import rclpy

        from .ros2_node import build_ros2_node

        rclpy.init(args=None)
        node = build_ros2_node(bindings, config)
        try:
            rclpy.spin(node)
        finally:
            node.destroy_node()
            rclpy.shutdown()
        return

    import rospy

    from .ros1_node import build_ros1_node

    rospy.init_node(config.node_name, anonymous=False)
    build_ros1_node(bindings, config)
    rospy.spin()


if __name__ == "__main__":  # pragma: no cover
    main()
