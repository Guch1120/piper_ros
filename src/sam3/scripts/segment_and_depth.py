#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import numpy as np
import torch
from PIL import Image as PILImage
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import os
from datetime import datetime

class RealSenseSegmentWithDepth(Node):
    def __init__(self):
        super().__init__('realsense_segment_with_depth')
        self.bridge = CvBridge()
        self.frame_processed = False

        # RGBトピック購読
        self.rgb_sub = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.rgb_callback,
            10
        )
        # Depthトピック購読
        self.depth_sub = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_callback,
            10
        )
        
        # RGBとDepth画像を保持する変数
        self.latest_rgb = None
        self.latest_depth = None
        # SAM3初期化
        self.model, self.processor, self.device = self.setup_sam3()

    def setup_sam3(self):
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.get_logger().info(f"Using device : {device}")

        current_dir = os.path.dirname(os.path.abspath(__file__))
        bpe_path = os.path.join(current_dir, "assets", "bpe_simple_vocab_16e6.txt.gz")
        if not os.path.exists(bpe_path):
            sam3_root = os.path.dirname(sam3.__file__)
            bpe_path = os.path.join(sam3_root, "..", "assets", "bpe_simple_vocab_16e6.txt.gz")
        self.get_logger().info(f"Loading SAM3 with BPE : {bpe_path}")

        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
        if device == "cpu":
            model = model.to("cpu")
        processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
        return model, processor, device

    def rgb_callback(self, msg):
        if self.frame_processed:
            return
        # OpenCVで扱える画像データ（NumPy配列）に変換
        self.latest_rgb = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
        self.try_process_frame()

    def depth_callback(self, msg):
        if self.frame_processed:
            return
        self.latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
        self.try_process_frame()

    # RGBとDepthの両方が揃っている場合に処理を実行
    def try_process_frame(self):
        if self.latest_rgb is not None and self.latest_depth is not None:
            self.process_frame(self.latest_rgb, self.latest_depth)
            self.frame_processed = True
            rclpy.shutdown()


    def process_frame(self, rgb_image, depth_image):
        timestamp = datetime.now().strftime('%Y_%m%d_%H_%M_%S')

        # SAM3でセグメント
        image_pil = PILImage.fromarray(rgb_image)
        inference_state = self.processor.set_image(image_pil)
        # 検出したい物体を指定
        input_text = "magcup"
        self.get_logger().info(f"SAM3 text prompt : {input_text}")
        results = self.processor.set_text_prompt(input_text, inference_state)

        if len(results['masks']) == 0:
            self.get_logger().warn("Object not found")
            return

        mask_tensor = results['masks'][0]
        # squeeze() を追加して次元を (1, H, W) -> (H, W) に変換 --> numpyに変換
        mask = mask_tensor.squeeze().cpu().numpy().astype(bool)

        try:
            # Depthを抽出
            masked_depth = depth_image[mask]
        except IndexError as e:
            self.get_logger().error(f"IndexError during masking : {e}")
            self.get_logger().error(f"Mask shape : {mask.shape}, Depth shape : {depth_image.shape}")
            return
        if masked_depth.size == 0:
            self.get_logger().warn("No depth info in masked area")
            return

        # 中央値を計算
        median_depth = np.median(masked_depth)
        
        # uint16 (mm) の場合は m に換算
        if depth_image.dtype == np.uint16:
            median_depth_m = median_depth / 1000.0
            unit_str = "(converted from mm)"
        else:
            # float32 (m) の場合
            median_depth_m = median_depth
            unit_str = "(original unit)"

        self.get_logger().info(f"Median Depth : {median_depth_m:.3f} m {unit_str}")
        self.get_logger().info(f"Detected objects count : {len(results['scores'])}")

def main(args=None):
    rclpy.init(args=args)
    node = RealSenseSegmentWithDepth()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()

if __name__ == '__main__':
    main()