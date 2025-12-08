#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2
import os
from datetime import datetime
import numpy as np


class RealSenseOneFrameSaver(Node):
    def __init__(self):
        super().__init__('realsense_one_frame_saver')
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
        self.frame_saved = False  # フレームが保存されたかどうかのフラグ

    def listener_callback(self, msg):
        if self.frame_saved:
            return  # 既にフレームが保存されている場合は何もしない

        try:
            rgb_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')  # ROS>>>OpenCV変換
            bgr_image = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2BGR)  # RGB>>>BGR変換

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            save_path = os.path.join(self.output_dir, f'realsense_frame_{timestamp}.png')
            cv2.imwrite(save_path, bgr_image)
            self.get_logger().info(f"画像を保存しました: {save_path}")

            self.frame_saved = True
            rclpy.shutdown()

        except Exception as e:
            self.get_logger().error(f"画像保存中にエラー発生: {str(e)}")


def main(args=None):
    rclpy.init(args=args)
    node = RealSenseOneFrameSaver()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    node.destroy_node()
    cv2.destroyAllWindows()


if __name__ == '__main__':
    main()
