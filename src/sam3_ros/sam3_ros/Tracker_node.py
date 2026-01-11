#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point, PointStamped
from std_msgs.msg import String
import cv2
import numpy as np
import torch
import os
import pathlib

# SAM3ライブラリのインポート
try:
    from sam3_ros.test_sam3_online_tracker import Sam3OnlineTracker
except ImportError:
    import sys
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from test_sam3_online_tracker import Sam3OnlineTracker

class Sam3HybridTracker(Node):
    def __init__(self):
        super().__init__('sam3_hybrid_tracker')
        
        # --- 1. SAM3 (The Brain) の初期化 ---
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        home = pathlib.Path.home()
        # SAM3チェックポイントのパス (環境に合わせて確認してください)
        ckpt_path = home / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
        
        self.get_logger().info("Loading SAM3 (Brain)...")
        # メモリ制限は8フレームで十分 (初期化の一瞬しか使わないため)
        self.sam3 = Sam3OnlineTracker(device=self.device, checkpoint_path=str(ckpt_path), max_frames=8)
        self.get_logger().info("SAM3 Ready.")

        # --- 2. DaSiamRPN (The Runner) の準備 ---
        self.tracker = None
        self.tracker_name = "DaSiamRPN"
        
        # モデルパスの設定 (~/.ros/dasiamrpn/ 配下を想定)
        model_dir = home / ".ros/dasiamrpn"
        self.dasiam_model = str(model_dir / "dasiamrpn_model.onnx")
        self.dasiam_kernel_r1 = str(model_dir / "dasiamrpn_kernel_r1.onnx")
        self.dasiam_kernel_cls1 = str(model_dir / "dasiamrpn_kernel_cls1.onnx")
        
        # ファイル存在確認
        if not os.path.exists(self.dasiam_model):
            self.get_logger().error(f"DaSiamRPN models not found at {model_dir}!")
            self.get_logger().error("Please download them to ~/.ros/dasiamrpn/")
            # CSRTにフォールバック
            self.tracker_name = "CSRT"
        else:
            self.get_logger().info(f"DaSiamRPN models found. Using CPU Tracker.")

        # --- 変数 ---
        self.latest_cv_image = None
        self.tracking_active = False
        self.target_prompt = None
        self.missed_frames = 0

        # --- 通信 ---
        self.sub_img = self.create_subscription(
            Image, '/camera/camera/color/image_raw', self.image_cb, 1)
            
        self.sub_start = self.create_subscription(
            String, '/sam3/start_track', self.start_text_cb, 1)
        
        self.pub_debug = self.create_publisher(Image, '/sam3/track_debug', 1)
        self.pub_result = self.create_publisher(Point, '/sam3/track_result', 1)

    def _create_tracker(self):
        """トラッカーインスタンスを作成"""
        if self.tracker_name == "DaSiamRPN":
            params = cv2.TrackerDaSiamRPN_Params()
            params.model = self.dasiam_model
            params.kernel_cls1 = self.dasiam_kernel_cls1
            params.kernel_r1 = self.dasiam_kernel_r1
            return cv2.TrackerDaSiamRPN_create(params)
        else:
            return cv2.TrackerCSRT_create()

    def image_cb(self, msg):
        # 画像受信
        img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
        if 'rgb' in msg.encoding:
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        else:
            img_bgr = img_np
            
        self.latest_cv_image = img_bgr
        debug_img = img_bgr.copy()
        
        detected = False
        center_x, center_y = 0.0, 0.0

        # === フェーズA: 高速追跡 (DaSiamRPN) ===
        if self.tracking_active and self.tracker is not None:
            success, box = self.tracker.update(img_bgr)
            
            if success:
                # 追跡成功
                x, y, w, h = [int(v) for v in box]
                
                # 画面端判定（画面端に行くとロストしやすいので警告）
                h_img, w_img, _ = img_bgr.shape
                if x < 5 or y < 5 or (x+w) > w_img-5 or (y+h) > h_img-5:
                    pass # 端っこ注意
                
                # 描画
                cv2.rectangle(debug_img, (x, y), (x+w, y+h), (0, 255, 0), 2)
                cv2.putText(debug_img, f"{self.tracker_name}: OK", (x, y-10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                center_x = x + w/2.0
                center_y = y + h/2.0
                detected = True
                self.missed_frames = 0
            else:
                self.missed_frames += 1
                if self.missed_frames > 5: # 5フレーム連続失敗でSAM3へ
                    self.get_logger().warn("Tracker lost! Requesting SAM3...")
                    self.tracking_active = False
                    self.tracker = None

        # === フェーズB: SAM3による初期化/リカバリー ===
        if not self.tracking_active and self.target_prompt is not None:
            # SAM3はRGB画像を期待する
            img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
            
            # 初期化実行 (GPU)
            masks = self.sam3.init_track(img_rgb, text_prompt=self.target_prompt)
            
            if masks and len(masks) > 0:
                mask = masks[0]
                if np.sum(mask) > 0:
                    # マスクからBBを生成
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    if len(contours) > 0:
                        largest = max(contours, key=cv2.contourArea)
                        bx, by, bw, bh = cv2.boundingRect(largest)
                        
                        # ★DaSiamRPNを初期化★
                        self.tracker = self._create_tracker()
                        self.tracker.init(img_bgr, (bx, by, bw, bh))
                        
                        self.tracking_active = True
                        self.missed_frames = 0
                        self.get_logger().info(f"SAM3 found '{self.target_prompt}'! Handing over to {self.tracker_name}.")
                        
                        # 今回分の描画
                        cv2.rectangle(debug_img, (bx, by), (bx+bw, by+bh), (255, 0, 0), 2)
                        cv2.putText(debug_img, "SAM3 Init", (bx, by-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                        center_x = bx + bw/2.0
                        center_y = by + bh/2.0
                        detected = True

        # === Publish ===
        if detected:
            self.pub_result.publish(Point(x=center_x, y=center_y, z=0.0))
            cv2.drawMarker(debug_img, (int(center_x), int(center_y)), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        elif self.target_prompt:
            cv2.putText(debug_img, f"Searching: {self.target_prompt}...", (20, 50), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height = debug_img.shape[0]
        msg.width = debug_img.shape[1]
        msg.encoding = 'bgr8'
        msg.step = debug_img.shape[1] * 3
        msg.data = debug_img.tobytes()
        self.pub_debug.publish(msg)

    def start_text_cb(self, msg):
        target = msg.data
        self.get_logger().info(f"New Target: {target}")
        self.target_prompt = target
        self.tracking_active = False # 再検索トリガー

def main():
    rclpy.init()
    node = Sam3HybridTracker()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()