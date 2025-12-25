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

class Sam3ServiceNode(Node):
    def __init__(self):
        super().__init__('sam3_node')
        self.bridge = CvBridge()
        self.latest_rgb = None
        self.latest_depth = None
        
        # ROS 2 Topics
        self.sub_rgb = self.create_subscription(Image, '/camera/camera/color/image_raw', self.rgb_cb, 1)
        self.sub_depth = self.create_subscription(Image, '/camera/camera/aligned_depth_to_color/image_raw', self.depth_cb, 1)
        
        # Request (String: "cup") -> Result (Point: u, v, z)
        self.sub_req = self.create_subscription(String, '/sam3/request', self.request_cb, 1)
        self.pub_res = self.create_publisher(Point, '/sam3/result', 1)

        self.get_logger().info("Loading SAM3 Model...")
        self.model, self.processor = self._setup_sam3()
        self.get_logger().info("SAM3 Ready!")

    def _setup_sam3(self):
        device = "cuda" if torch.cuda.is_available() else "cpu"
        sam3_root = os.path.dirname(sam3.__file__)
        bpe_path = os.path.join(sam3_root, "..", "assets", "bpe_simple_vocab_16e6.txt.gz")
        model = build_sam3_image_model(bpe_path=bpe_path, device=device)
        processor = Sam3Processor(model, confidence_threshold=0.5, device=device)
        return model, processor

    def rgb_cb(self, msg): self.latest_rgb = msg
    def depth_cb(self, msg): self.latest_depth = msg

    def request_cb(self, msg):
        target_name = msg.data
        self.get_logger().info(f"Request received: {target_name}")
        
        if self.latest_rgb is None or self.latest_depth is None:
            self.get_logger().warn("No images available yet.")
            return

        try:
            rgb = self.bridge.imgmsg_to_cv2(self.latest_rgb, 'rgb8')
            depth = self.bridge.imgmsg_to_cv2(self.latest_depth, 'passthrough')
            
            # Inference
            image_pil = PILImage.fromarray(rgb)
            state = self.processor.set_image(image_pil)
            results = self.processor.set_text_prompt(target_name, state)

            if len(results['masks']) > 0:
                mask = results['masks'][0].squeeze().cpu().numpy().astype(bool)
                indices = np.argwhere(mask)
                if len(indices) > 0:
                    v = float(np.mean(indices[:, 0]))
                    u = float(np.mean(indices[:, 1]))
                    masked_depth = depth[mask]
                    z = float(np.median(masked_depth) / 1000.0)
                    
                    # Publish Result
                    res = Point()
                    res.x = u
                    res.y = v
                    res.z = z
                    self.pub_res.publish(res)
                    self.get_logger().info(f"Published: u={u}, v={v}, z={z}")
                else:
                    self.get_logger().info("Mask empty.")
            else:
                self.get_logger().info("Nothing found.")
                
        except Exception as e:
            self.get_logger().error(f"Inference failed: {e}")

def main():
    rclpy.init()
    node = Sam3ServiceNode()
    rclpy.spin(node)
    rclpy.shutdown()

if __name__ == '__main__':
    main()