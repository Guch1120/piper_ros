#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import os
from datetime import datetime
import numpy as np
import torch
from PIL import Image as PILImage
import matplotlib.pyplot as plt
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results


class RealSenseSaveAndSegment(Node):
    def __init__(self):
        super().__init__('realsense_save_and_segment')
        self.bridge = CvBridge()

        # 保存パスを指定
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(script_dir, '..', 'assets', 'saved_frames')
        self.output_dir = os.path.normpath(self.output_dir)
        
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        self.subscription = self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.listener_callback,
            10
        )
        self.frame_saved = False
        

        # SAM3の設定（初回だけロード）
        self.model, self.processor, self.device = self.setup_sam3()

    def setup_sam3(self):
        try:
            #  CUDA使用可能か確認
            if torch.cuda.is_available():
                t = torch.randn(1, 1, 32, 32).cuda()
                conv = torch.nn.Conv2d(1, 1, 3).cuda()
                _ = conv(t)
                torch.cuda.synchronize()
                device = "cuda"
                self.get_logger().info("Using CUDA")
            else:
                device = "cpu"
                self.get_logger().info("Using CPU")
        except RuntimeError as e:
            self.get_logger().warn(f"CUDA available but failed to init: {e}")
            device = "cpu"

        ## BPEファイル(SAM3が必要とするtokenizer辞書)のパスを決定
        bpe_path = os.path.join(current_dir, "assets", "bpe_simple_vocab_16e6.txt.gz")
        if not os.path.exists(bpe_path):
            sam3_root = os.path.dirname(sam3.__file__)
            bpe_path = os.path.join(sam3_root, "..", "assets", "bpe_simple_vocab_16e6.txt.gz")
        self.get_logger().info(f"Loading SAM3 with BPE: {bpe_path}")
        
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
        if device == "cpu":
            model = model.to("cpu")

        #  SAM3 Processorの初期化
        processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
        return model, processor, device

    def listener_callback(self, msg):
        if self.frame_saved:
            return

        try:
            rgb_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')  # ROS → OpenCV変換
            bgr_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)  # RGB → BGR変換

            # 画像保存
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = os.path.join(self.output_dir, f'realsense_frame_{timestamp}.png')
            cv2.imwrite(save_path, bgr_image)
            self.get_logger().info(f"画像を保存しました: {save_path}")

            # SAM3セグメント処理
            self.run_sam3(save_path, timestamp)

            self.frame_saved = True
            rclpy.shutdown()

        except Exception as e:
            self.get_logger().error(f"画像保存中にエラー発生: {str(e)}")

    def run_sam3(self, img_path, timestamp):
        self.get_logger().info("SAM3 によるセグメンテーションを開始します")

        # 画像読込（PIL）
        image = PILImage.open(img_path)

        # 特徴抽出
        inference_state = self.processor.set_image(image)

        # 検出したい物体を指定
        input_text = "magcup"
        self.get_logger().info(f"SAM3 テキストプロンプト: {input_text}")

        results = self.processor.set_text_prompt(input_text, inference_state)

        count = len(results["scores"])
        self.get_logger().info(f"SAM3 が検出した物体数: {count}")

        # 可視化して保存
        result_path = os.path.join(self.output_dir, f"segmented_{timestamp}.png")
        plot_results(image, results)
        plt.savefig(result_path)
        plt.close()

        self.get_logger().info(f"SAM3 セグメント結果を保存: {result_path}")


def main(args=None):
    rclpy.init(args=args)
    node = RealSenseSaveAndSegment()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()