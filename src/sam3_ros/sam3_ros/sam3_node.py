#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from std_msgs.msg import String
from cv_bridge import CvBridge
import numpy as np
import torch
from PIL import Image as PILImage
import sam3
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor
import os
import cv2

class Sam3ServiceNode(Node):
    def __init__(self):
        super().__init__('sam3_node')
        self.bridge = CvBridge()
        self.latest_rgb = None
        self.latest_depth = None

        self.create_subscription(Image,
            '/camera/camera/color/image_raw',
            self.rgb_cb, 1)
        self.create_subscription(Image,
            '/camera/camera/aligned_depth_to_color/image_raw',
            self.depth_cb, 1)
        self.create_subscription(String,
            '/sam3/request',
            self.request_cb, 1)

        self.pub_res = self.create_publisher(Point, '/sam3/result', 1)
        self.pub_debug = self.create_publisher(Image, '/sam3/debug_image', 1)

        self.get_logger().info('Loading SAM3 Model...')
        self.model, self.processor = self._setup_sam3()
        self.get_logger().info('SAM3 Ready! Waiting for request...')

    def _setup_sam3(self):
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam3_root = os.path.dirname(sam3.__file__)
        bpe_path = os.path.join(sam3_root, "..", "assets",
                                "bpe_simple_vocab_16e6.txt.gz")
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
        processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
        return model, processor

    def rgb_cb(self, msg):
        self.latest_rgb = msg

    def depth_cb(self, msg):
        self.latest_depth = msg

    def request_cb(self, msg):
        target = msg.data
        self.get_logger().info(f'Request received: {target}')

        if self.latest_rgb is None or self.latest_depth is None:
            self.get_logger().warn('No image received yet.')
            return

        try:
            # ===== RGB decode =====
            rgb = np.frombuffer(
                self.latest_rgb.data, dtype=np.uint8
            ).reshape(self.latest_rgb.height,
                      self.latest_rgb.width, -1)
            if rgb.shape[2] == 4:
                rgb = rgb[:, :, :3]
            rgb = rgb.copy()

            # ===== Depth decode =====
            depth_dtype = np.uint16
            if '32FC' in self.latest_depth.encoding:
                depth_dtype = np.float32
            depth = np.frombuffer(
                self.latest_depth.data, dtype=depth_dtype
            ).reshape(self.latest_depth.height,
                      self.latest_depth.width)
            depth = depth.copy()

            # ===== SAM3 inference =====
            image_pil = PILImage.fromarray(rgb)
            state = self.processor.set_image(image_pil)
            results = self.processor.set_text_prompt(target, state)

            if len(results['masks']) == 0:
                self.get_logger().info('Nothing detected.')
                return

            mask = results['masks'][0].squeeze().cpu().numpy().astype(bool)
            indices = np.argwhere(mask)
            if len(indices) == 0:
                self.get_logger().info('Mask empty.')
                return

            v = float(np.mean(indices[:, 0]))
            u = float(np.mean(indices[:, 1]))

            masked_depth = depth[mask]
            if depth.dtype == np.uint16:
                z = float(np.median(masked_depth) / 1000.0)
            else:
                z = float(np.median(masked_depth))

            # ===== Debug image =====
            vis = rgb[:, :, ::-1].copy()  # RGB->BGR
            vis[mask] = (
                vis[mask] * 0.5 + np.array([0, 255, 0]) * 0.5
            ).astype(np.uint8)

            cv2.circle(vis, (int(u), int(v)), 10, (0, 0, 255), -1)
            cv2.putText(
                vis, f'{target}: {z:.3f}m',
                (int(u)+15, int(v)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7, (255, 255, 255), 2
            )

            try:
                img_msg = self.bridge.cv2_to_imgmsg(vis, encoding='bgr8')
                self.pub_debug.publish(img_msg)
            except Exception:
                pass

            # ===== Publish result =====
            res = Point()
            res.x = u
            res.y = v
            res.z = z
            self.pub_res.publish(res)

            self.get_logger().info(
                f'Published: u={u:.1f}, v={v:.1f}, z={z:.3f}')

        except Exception as e:
            self.get_logger().error(f'Inference failed: {e}')
            import traceback
            traceback.print_exc()

def main():
    rclpy.init()
    node = Sam3ServiceNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
