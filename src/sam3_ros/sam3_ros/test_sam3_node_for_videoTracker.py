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

os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
# パス調整
try:
    from sam3_ros.test_sam3_online_tracker import Sam3OnlineTracker
except ImportError:
    import sys
    import os
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
    from test_sam3_online_tracker import Sam3OnlineTracker

class Sam3VideoOnlineTracker(Node):
    def __init__(self):
        super().__init__('ssam3_node_online_tracker')
        
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        import pathlib
        home = pathlib.Path.home()
        ckpt_path = home / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
        
        self.get_logger().info(f"Loading SAM3 Video Model on {self.device}...")
        # Tracker側の設定は変更なし
        self.tracker = Sam3OnlineTracker(device=self.device, checkpoint_path=str(ckpt_path), max_frames=4)
        self.get_logger().info("SAM3 Video Ready.")

        self.latest_cv_image = None
        self.tracking_active = False

        # --- 平滑化用変数 ---
        self.last_valid_box = None  # (x, y, w, h)
        self.last_valid_mask = None
        self.missed_frames = 0      # 見失った連続フレーム数
        self.MAX_MISS_TOLERANCE = 8 # 何フレームまで「残像」を表示するか (リセットの隙間を埋める)

        # --- Subscribers ---
        self.sub_img = self.create_subscription(
            Image, '/camera/camera/color/image_raw', self.image_cb, 1)
            
        self.sub_start = self.create_subscription(
            String, '/sam3/start_track', self.start_text_cb, 1)
            
        self.sub_point = self.create_subscription(
            PointStamped, '/clicked_point', self.start_point_cb, 1)
            
        # --- Publishers ---
        self.pub_debug = self.create_publisher(Image, '/sam3/track_debug', 1)
        self.pub_result = self.create_publisher(Point, '/sam3/track_result', 1)

    def image_cb(self, msg):
        img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
        
        if 'bgr' in msg.encoding:
            img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
        else:
            img_rgb = img_np

        self.latest_cv_image = img_rgb
        
        # 常にstepを回す（自動復帰のため）
        # まだ初期化されていなければ None が返るだけ
        masks = self.tracker.step(img_rgb)
        
        # 表示・出力処理
        debug_img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        self.process_result(debug_img_bgr, masks)

    def start_text_cb(self, msg):
        target = msg.data
        self.get_logger().info(f"Set target text: {target}")
        # Trackerにプロンプトを登録（step内で自動初期化される）
        self.tracker.current_text_prompt = target
        # 手動で一回キックしても良い
        if self.latest_cv_image is not None:
             self.tracker.init_track(self.latest_cv_image)

    def start_point_cb(self, msg):
        self.get_logger().info("Point clicked! Resetting to 'red apple'.")
        if self.latest_cv_image is not None:
             self.tracker.current_text_prompt = "red apple"
             self.tracker.init_track(self.latest_cv_image)

    def process_result(self, img, masks):
        debug_img = img.copy()
        
        # --- 検出判定と平滑化 ---
        detected = False
        current_mask = None
        
        if masks and len(masks) > 0:
            # 検出成功
            current_mask = masks[0]
            if np.sum(current_mask) > 0:
                detected = True
                self.last_valid_mask = current_mask
                self.missed_frames = 0
                
                # BB更新
                contours, _ = cv2.findContours(current_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if len(contours) > 0:
                    largest = max(contours, key=cv2.contourArea)
                    self.last_valid_box = cv2.boundingRect(largest)
            else:
                detected = False
        
        # --- 描画とPublish ---
        final_x, final_y = 0.0, 0.0
        should_publish = False

        if detected:
            # A. リアルタイム検出中（緑）
            self._draw_mask(debug_img, current_mask, color=(0, 255, 0))
            if self.last_valid_box:
                bx, by, bw, bh = self.last_valid_box
                cv2.rectangle(debug_img, (bx, by), (bx+bw, by+bh), (0, 255, 0), 2)
                cv2.putText(debug_img, "Tracking", (bx, by-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                final_x = bx + bw/2.0
                final_y = by + bh/2.0
                should_publish = True

        elif self.last_valid_box is not None and self.missed_frames < self.MAX_MISS_TOLERANCE:
            # B. ロストしたが、残像を表示（黄色）
            self.missed_frames += 1
            bx, by, bw, bh = self.last_valid_box
            
            # 破線などで描画したいが、簡易的に黄色枠
            cv2.rectangle(debug_img, (bx, by), (bx+bw, by+bh), (0, 255, 255), 2)
            cv2.putText(debug_img, f"Coasting ({self.missed_frames})", (bx, by-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            
            # マスクも薄く表示（オプション）
            if self.last_valid_mask is not None:
                self._draw_mask(debug_img, self.last_valid_mask, color=(0, 255, 255), alpha=0.3)

            final_x = bx + bw/2.0
            final_y = by + bh/2.0
            should_publish = True # 残像期間も座標を出し続ける
        else:
            # C. 完全に見失った
            cv2.putText(debug_img, "Lost", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
            should_publish = False

        # 結果Publish
        if should_publish:
            self.pub_result.publish(Point(x=final_x, y=final_y, z=0.0))
            cv2.drawMarker(debug_img, (int(final_x), int(final_y)), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)

        # Debug画像Publish
        msg = Image()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.height = debug_img.shape[0]
        msg.width = debug_img.shape[1]
        msg.encoding = 'bgr8'
        msg.step = debug_img.shape[1] * 3
        msg.data = debug_img.tobytes()
        self.pub_debug.publish(msg)

    def _draw_mask(self, img, mask, color=(0, 255, 0), alpha=0.5):
        if mask is None: return
        colored_mask = np.zeros_like(img)
        colored_mask[mask > 0] = color
        # 元画像に重ねる
        mask_indices = mask > 0
        if mask_indices.any():
            img[mask_indices] = cv2.addWeighted(img[mask_indices], 1-alpha, colored_mask[mask_indices], alpha, 0)

def main():
    rclpy.init()
    node = Sam3VideoOnlineTracker()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()