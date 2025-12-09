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
from sam3.visualization_utils import plot_results
import os
from datetime import datetime
import matplotlib.pyplot as plt

class RealSenseSegmentWithDepth(Node):
    def __init__(self):
        super().__init__('realsense_segment_with_depth')
        self.bridge = CvBridge()
        self.frame_processed = False

        # 保存パスを指定
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(script_dir, '..', 'assets', 'saved_frames')
        # ディレクトリが存在しない場合は作成
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        # RGB画像のサブスクライバー
        self.rgb_sub = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.rgb_callback,
            10
        )
        
        # Depth画像のサブスクライバー (RGBにアライメントされたDepthを使用)
        self.depth_sub = self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_callback,
            10
        )
        
        # 画像を一時保持する変数
        self.latest_rgb = None
        self.latest_depth = None

        # SAM3のセットアップ
        self.model, self.processor, self.device = self.setup_sam3()

    def setup_sam3(self):
        # デバイスの決定
        if torch.cuda.is_available():
            device = "cuda"
            self.get_logger().info("Using CUDA")
        else:
            device = "cpu"
            self.get_logger().info("Using CPU")

        # BPEファイルのパス設定
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
        try:
            # ROS Image -> OpenCV image (numpy array)
            self.latest_rgb = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
            self.try_process_frame()
        except Exception as e:
            self.get_logger().error(f"RGB callback error: {e}")

    def depth_callback(self, msg):
        if self.frame_processed:
            return
        try:
            # Depth画像は通常 16UC1 (uint16) でmm単位
            self.latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            self.try_process_frame()
        except Exception as e:
            self.get_logger().error(f"Depth callback error: {e}")

    def try_process_frame(self):
        # RGBとDepthの両方が揃ったら処理を開始
        if self.latest_rgb is not None and self.latest_depth is not None:
            self.process_frame(self.latest_rgb, self.latest_depth)
            self.frame_processed = True
            rclpy.shutdown()

    def process_frame(self, rgb_image, depth_image):
        timestamp = datetime.now().strftime('%Y_%m%d_%H_%M_%S')
        self.get_logger().info("Starting SAM3 segmentation and depth calculation...")

        # SAM3用にPIL画像へ変換
        image_pil = PILImage.fromarray(rgb_image)
        
        # 推論の実行
        inference_state = self.processor.set_image(image_pil)
        input_text = "magcup"
        self.get_logger().info(f"SAM3 text prompt : {input_text}")
        results = self.processor.set_text_prompt(input_text, inference_state)

        # マスクが見つからなかった場合の処理
        if len(results['masks']) == 0:
            self.get_logger().warn("Object not found by SAM3.")
            return

        # Depth計算処理       
        # 最初のマスクを取得 (Tensor -> Numpy, Shape: [H, W])
        # SAM3の出力形式に合わせて次元を調整
        mask_tensor = results['masks'][0]
        mask = mask_tensor.squeeze().cpu().numpy().astype(bool)

        # Depth画像をNumpy配列として扱う
        depth_np = depth_image
        if torch.is_tensor(depth_image):
            depth_np = depth_image.cpu().numpy()
        
        # Depth画像の次元を確認して調整 (H, W) にする
        if depth_np.ndim == 3:
            depth_np = np.squeeze(depth_np)

        # マスク領域のDepth値のみを抽出
        # maskがTrueの場所にあるdepth_npの値を取得します
        masked_depth = depth_np[mask]

        if masked_depth.size == 0:
            self.get_logger().warn("No depth pixels found in the masked area.")
        else:
            # 中央値 (Median) を計算
            median_depth = np.median(masked_depth)
            
            # RealSenseのDepthは通常mm単位 (uint16)
            # 見やすくするためにメートル変換してログ出力
            if depth_np.dtype == np.uint16:
                median_depth_m = median_depth / 1000.0
                unit_str = "(converted from mm)"
            else:
                median_depth_m = median_depth
                unit_str = "(original unit)"

            self.get_logger().info(f"Median Depth : {median_depth_m:.3f} m {unit_str}")
            self.get_logger().info(f"Raw Median Depth Value : {median_depth}")

        # 結果画像の保存
        result_path = os.path.join(self.output_dir, f"segmented_{timestamp}.png")
        plot_results(image_pil, results)
        plt.savefig(result_path)
        plt.close()
        self.get_logger().info(f"Segmented image saved : {result_path}")
        self.get_logger().info("Processing complete.")


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