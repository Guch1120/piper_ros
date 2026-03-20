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
import cv2  # OpenCVを追加

class RealSenseSegmentWithDepth(Node):
    def __init__(self):
        super().__init__('realsense_segment_with_depth')
        self.bridge = CvBridge()
        self.frame_processed = False

        # 保存パスを指定
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(script_dir, '..', 'assets', 'saved_frames')
        os.makedirs(self.output_dir, exist_ok=True)

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
            # インタラクティブ表示が終わるまでシャットダウンしない
            rclpy.shutdown()

    def process_frame(self, rgb_image, depth_image):
        timestamp = datetime.now().strftime('%Y_%m%d_%H_%M_%S')

        # SAM3でセグメント
        image_pil = PILImage.fromarray(rgb_image)
        inference_state = self.processor.set_image(image_pil)
        input_text = "magcup"
        self.get_logger().info(f"SAM3 text prompt : {input_text}")
        results = self.processor.set_text_prompt(input_text, inference_state)

        if len(results['masks']) == 0:
            self.get_logger().warn("Object not found")
            return

        # 最初のマスクを取得して numpy に変換
        mask_tensor = results['masks'][0]
        mask = mask_tensor.squeeze().cpu().numpy().astype(bool)

        # Depthを抽出
        depth_np = depth_image
        if torch.is_tensor(depth_image):
            depth_np = depth_image.cpu().numpy()
        if depth_np.ndim == 3:
            depth_np = np.squeeze(depth_np)
        
        # マスク領域のDepth値を取得
        masked_depth = depth_np[mask]

        if masked_depth.size == 0:
            self.get_logger().warn("No depth info in masked area")
            return

        # 中央値Depthを計算
        median_depth = np.median(masked_depth)
        if depth_np.dtype == np.uint16:
            median_depth_m = median_depth / 1000.0
            unit_str = "(converted from mm)"
        else:
            median_depth_m = median_depth
            unit_str = "(original unit)"

        self.get_logger().info(f"Median Depth : {median_depth_m:.3f} m {unit_str}")
        self.get_logger().info(f"Detected objects count : {len(results['scores'])}")

        # セグメント結果の画像も保存
        result_path = os.path.join(self.output_dir, f"segmented_{timestamp}.png")
        plot_results(image_pil, results)
        plt.savefig(result_path)
        plt.close()
        self.get_logger().info(f"Segmented image saved : {result_path}")

        # --- ここからインタラクティブ確認機能を追加 ---
        self.interactive_view(rgb_image, depth_np, mask)

    def interactive_view(self, rgb_img, depth_img, mask):
        """
        OpenCVを使って画像を表示し、マウスホバーでDepth値を確認する機能
        """
        self.get_logger().info("Starting interactive depth viewer. Press 'q' or 'ESC' to exit.")

        # RGB画像をBGRに変換 (OpenCV表示用)
        bgr_img = cv2.cvtColor(rgb_img, cv2.COLOR_RGB2BGR)

        # マスクを可視化 (緑色で透過表示)
        mask_overlay = bgr_img.copy()
        mask_overlay[mask] = [0, 255, 0] # BGRで緑
        cv2.addWeighted(mask_overlay, 0.5, bgr_img, 0.5, 0, bgr_img)

        # Depth画像をカラーマップ化 (可視化用)
        # alpha=0.03は、約8.5mまでを0-255にマッピングする調整値 (255 / 0.03 = 8500)
        depth_visual = cv2.convertScaleAbs(depth_img, alpha=0.03)
        depth_colormap = cv2.applyColorMap(depth_visual, cv2.COLORMAP_JET)

        # ウィンドウの作成
        window_name = "Depth Viewer (Hover to check depth)"
        cv2.namedWindow(window_name)

        # マウスコールバック関数の定義
        # クロージャを使って depth_img にアクセスできるようにする
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_MOUSEMOVE:
                # 座標チェック
                if 0 <= y < depth_img.shape[0] and 0 <= x < depth_img.shape[1]:
                    # 生のDepth値 (mm)
                    d_val = depth_img[y, x]
                    
                    # コンソールに上書き表示 (\r使用)
                    print(f"\r[Hover] X: {x:3d}, Y: {y:3d} | Depth: {d_val:5} mm ({d_val/1000.0:.3f} m)   ", end="")

        # コールバックをセット
        cv2.setMouseCallback(window_name, mouse_callback)

        # 横に並べて表示するために画像を連結 (高さが同じ前提)
        # RGB画像とDepthカラーマップを結合
        combined_img = np.hstack((bgr_img, depth_colormap))

        while True:
            # 画像を表示
            cv2.imshow(window_name, combined_img)
            
            # キー入力待ち (1ms)
            key = cv2.waitKey(1) & 0xFF
            
            # 'q' か ESC(27) で終了
            if key == ord('q') or key == 27:
                print("\nInteractive viewer closed.")
                break
        
        cv2.destroyAllWindows()

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