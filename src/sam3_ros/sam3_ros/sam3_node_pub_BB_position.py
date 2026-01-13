#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from std_msgs.msg import String, Int32MultiArray # 追加: Int32MultiArray
from cv_bridge import CvBridge
import numpy as np
import torch
from PIL import Image as PILImage
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
from sam3.visualization_utils import plot_results
import os
import matplotlib.pyplot as plt


class Sam3ServiceForTracker(Node):
    
    '''
    sam3ノード
    /sam3/request トピックで対象物の名前を受け取り、
    RGB-D画像からSAM3で対象物を検出し、
    重心の(u, v)座標と深度zを /sam3/result トピックに配信する。
    また、検出した対象物のバウンディングボックスを /sam3/bbox トピックに配信する。
    デバッグ用に検出結果の可視化画像を /sam3/debug_image トピックに配信する。
    もし検出に失敗した場合、z座標を-1.0として通知する。
    '''
    
    def __init__(self):
        super().__init__('sam3_service_for_tracker')
        self.bridge = CvBridge()

        self.latest_rgb_msg = None
        self.latest_depth_msg = None

        # ---- Subscribers ----
        self.create_subscription(
            Image,
            '/camera/camera/color/image_raw',
            self.rgb_cb,
            1
        )
        self.create_subscription(
            Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_cb,
            1
        )
        self.create_subscription(
            String,
            '/sam3/request',
            self.request_cb,
            1
        )

        # ---- Publishers ----
        self.pub_result = self.create_publisher(Point, '/sam3/result', 1)
        # 追加: Tracker用のBounding Box配信 [x, y, w, h]
        self.pub_bbox = self.create_publisher(Int32MultiArray, '/sam3/bbox', 1)
        self.pub_debug = self.create_publisher(Image, '/sam3/debug_image', 1)

        self.get_logger().info('Loading SAM3 model...')
        self.model, self.processor = self._setup_sam3()
        self.get_logger().info('SAM3 ready.')

    def _setup_sam3(self):
        device = "cuda" if torch.cuda.is_available() else "cpu"

        sam3_root = os.path.dirname(sam3.__file__)
        bpe_path = os.path.join(
            sam3_root, "..", "assets",
            "bpe_simple_vocab_16e6.txt.gz"
        )

        model = build_sam3_image_model(
            bpe_path=bpe_path,
            device=device
        )
        processor = Sam3Processor(
            model,
            confidence_threshold=0.5,
            device=device
        )
        return model, processor

    def rgb_cb(self, msg):
        self.latest_rgb_msg = msg

    def depth_cb(self, msg):
        self.latest_depth_msg = msg

    def request_cb(self, msg):
        target = msg.data
        self.get_logger().info(f'Request: {target}')

        if self.latest_rgb_msg is None or self.latest_depth_msg is None:
            self.get_logger().warn('No image received yet.')
            return

        try:
            rgb = self.bridge.imgmsg_to_cv2(
                self.latest_rgb_msg,
                desired_encoding='rgb8'
            )
            depth = self.bridge.imgmsg_to_cv2(
                self.latest_depth_msg,
                desired_encoding='passthrough'
            )

            # ===== SAM3 推論 =====
            image_pil = PILImage.fromarray(rgb)
            state = self.processor.set_image(image_pil)
            results = self.processor.set_text_prompt(target, state)

            # ===== 検出結果なしの場合=====
            if len(results['masks']) == 0:
                # 失敗を通知
                fail_res = Point(x=0.0, y=0.0, z=-1.0)
                self.pub_result.publish(fail_res)
                
                # Trackerにも失敗を通知 [-1, -1, -1, -1]
                fail_bbox = Int32MultiArray()
                fail_bbox.data = [-1, -1, -1, -1]
                self.pub_bbox.publish(fail_bbox)
                
                self.get_logger().info('Nothing detected.')
                return

            # ===== 重心 + depth =====
            mask = results['masks'][0].squeeze().cpu().numpy().astype(bool)
            indices = np.argwhere(mask)
            if len(indices) == 0:
                return

            # indices は (row, col) つまり (y, x)
            v = float(np.mean(indices[:, 0]))
            u = float(np.mean(indices[:, 1]))
            
            # --- 追加: Bounding Box 計算 ---
            y_min = int(np.min(indices[:, 0]))
            y_max = int(np.max(indices[:, 0]))
            x_min = int(np.min(indices[:, 1]))
            x_max = int(np.max(indices[:, 1]))
            
            w_box = x_max - x_min
            h_box = y_max - y_min
            
            # Tracker用Publish [x, y, w, h]
            bbox_msg = Int32MultiArray()
            bbox_msg.data = [x_min, y_min, w_box, h_box]
            self.pub_bbox.publish(bbox_msg)
            # ---------------------------

            masked_depth = depth[mask]
            if depth.dtype == np.uint16:
                z = float(np.median(masked_depth) / 1000.0)
            else:
                z = float(np.median(masked_depth))

            # ===== 結果 publish =====
            res = Point(x=u, y=v, z=z)
            self.pub_result.publish(res)

            # ===== デバッグ画像（余白なし・最大表示）=====

            plt.close('all')

            # SAM3公式可視化
            plot_results(image_pil, results)

            # --- 重心位置の追加描画 ---
            # カレントの軸（gca）に対して描画
            plt.scatter(u, v, color='red', marker='+', s=500, linewidth=3, label='Center of Gravity')
            plt.text(u + 5, v - 5, f'CG({u:.1f}, {v:.1f})', 
                     color='red', fontsize=14, fontweight='bold',
                     bbox=dict(facecolor='white', alpha=0.5, edgecolor='none'))
            # ------------------------

            fig = plt.gcf()

            plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
            fig.set_size_inches(12, 9, forward=True)
            # tight_layout は scatter 等を追加した後に呼ぶと安全
            fig.tight_layout(pad=0)

            fig.canvas.draw()

            w, h = fig.canvas.get_width_height()
            img = np.frombuffer(
                fig.canvas.tostring_rgb(),
                dtype=np.uint8
            ).reshape(h, w, 3)

            plt.close(fig)

            # Publish
            img_msg = self.bridge.cv2_to_imgmsg(img, encoding='rgb8')
            self.pub_debug.publish(img_msg)

            self.get_logger().info(
                f'Published: u={u:.1f}, v={v:.1f}, z={z:.3f}, Box=[{x_min},{y_min},{w_box},{h_box}]'
            )

        except Exception as e:
            self.get_logger().error(f'SAM3 failed: {e}')
            import traceback
            traceback.print_exc()


def main():
    rclpy.init()
    node = Sam3ServiceForTracker()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()