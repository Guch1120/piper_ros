#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from std_msgs.msg import String
import cv2
import numpy as np
import torch
import os

# パスは適宜調整してください
from sam3_ros.test_sam3_online_tracker import Sam3OnlineTracker

class Sam3VideoOnlineTracker(Node):
    def __init__(self):
        super().__init__('ssam3_node_online_tracker')
        
        # --- 設定 ---
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        # モデルのパス (ユーザー環境に合わせて書き換えてください)
        import pathlib
        home = pathlib.Path.home()
        ckpt_path = home / ".cache/huggingface/hub/models--facebook--sam3/snapshots/3c879f39826c281e95690f02c7821c4de09afae7/sam3.pt"
        
        self.get_logger().info(f"Loading SAM3 Video Model on {self.device}...")
        self.tracker = Sam3OnlineTracker(device=self.device, checkpoint_path=str(ckpt_path))
        self.get_logger().info("SAM3 Video Ready.")

        self.latest_cv_image = None
        self.tracking_active = False

        # --- 通信 ---
        # 画像受信 (QoS=1 で最新のみ)
        self.sub_img = self.create_subscription(
            Image, '/camera/camera/color/image_raw', self.image_cb, 1)
            
        # 追跡開始コマンド "apple" など
        self.sub_start = self.create_subscription(
            String, '/sam3/start_track', self.start_cb, 1)
            
        self.pub_debug = self.create_publisher(Image, '/sam3/track_debug', 1)
        self.pub_result = self.create_publisher(Point, '/sam3/track_result', 1)

    def image_cb(self, msg):
            # バッファから配列へ
            img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
            
            # ★追加: エンコーディングに応じた色変換
            if 'bgr' in msg.encoding:
                # BGRで来ているなら、SAM3(RGB)のために変換
                img_rgb = cv2.cvtColor(img_np, cv2.COLOR_BGR2RGB)
            else:
                # rgb8などで来ているならそのまま (ただし表示用にはBGRが必要かも)
                img_rgb = img_np

            self.latest_cv_image = img_rgb # SAM3にはRGBを渡す

            if self.tracking_active:
                # 追跡実行
                masks = self.tracker.step(img_rgb)
                
                # 結果処理 (表示用にBGRに戻す処理を入れると親切)
                debug_img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR) if 'bgr' not in msg.encoding else img_rgb.copy()
                self.process_result(debug_img_bgr, masks)
                
    def start_cb(self, msg):
        target = msg.data
        if self.latest_cv_image is None:
            self.get_logger().warn("No image to initialize tracking!")
            return
            
        self.get_logger().info(f"Initializing track for: {target}")
        masks = self.tracker.init_track(self.latest_cv_image, target)
        
        if masks:
            self.tracking_active = True
            self.get_logger().info("Tracking Started!")
        else:
            self.get_logger().warn("Failed to find object in initial frame.")
            self.tracking_active = False

    def process_result(self, img, masks):
            debug_img = img.copy() # BGR画像
            
            if masks:
                mask = masks[0] 
                indices = np.argwhere(mask > 128)
                
                if len(indices) > 0:
                    y = float(np.mean(indices[:, 0]))
                    x = float(np.mean(indices[:, 1]))
                    
                    self.pub_result.publish(Point(x=x, y=y, z=0.0))
                    
                    # --- 1. セグメンテーション描画 (半透明) ---
                    # 緑色で塗りつぶす
                    colored_mask = np.zeros_like(debug_img)
                    colored_mask[mask > 128] = [0, 255, 0] # BGRで緑
                    debug_img = cv2.addWeighted(debug_img, 0.7, colored_mask, 0.3, 0)
                    
                    # --- 2. 輪郭描画 ---
                    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(debug_img, contours, -1, (0, 255, 0), 2)
                    
                    # --- 3. Bounding Box (BB) 描画 ---
                    # 最大の輪郭からBBを計算
                    if len(contours) > 0:
                        largest_contour = max(contours, key=cv2.contourArea)
                        bx, by, bw, bh = cv2.boundingRect(largest_contour)
                        cv2.rectangle(debug_img, (bx, by), (bx+bw, by+bh), (255, 0, 0), 2) # 青枠
                        
                        # ラベル表示
                        cv2.putText(debug_img, f"Apple (Conf: High)", (bx, by-10), 
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)

                    # 重心
                    cv2.drawMarker(debug_img, (int(x), int(y)), (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
                else:
                    cv2.putText(debug_img, "Mask empty", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)
            else:
                cv2.putText(debug_img, "Lost", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,255), 2)

            # Publish
            msg = Image()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.height = debug_img.shape[0]
            msg.width = debug_img.shape[1]
            msg.encoding = 'bgr8'
            msg.step = debug_img.shape[1] * 3
            msg.data = debug_img.tobytes()
            self.pub_debug.publish(msg)
        
def main():
    rclpy.init()
    node = Sam3VideoOnlineTracker()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()