#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# ==================================================
# PyTorch 2.6+ workaround (MUST be before ultralytics)
# ==================================================
import torch

_original_load = torch.load

def unsafe_load(*args, **kwargs):
    if 'weights_only' not in kwargs:
        kwargs['weights_only'] = False
    return _original_load(*args, **kwargs)

torch.load = unsafe_load

# ==================================================
# Normal imports
# ==================================================
from typing import List
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from cv_bridge import CvBridge
from sensor_msgs.msg import Image

from ultralytics import YOLO
from ultralytics.engine.results import Results

from yolov8_msgs.msg import (
    BoundingBox2D,
    Detection,
    DetectionArray,
)

# YOLOv8 msgs
#OIT-HSR内のyolov8_hsrリポジトリ内のyolov8_msgsパッケージを移行するのが面倒なので一旦無しで
# from yolov8_msgs.msg import (
#     Point2D,
#     BoundingBox2D,
#     Mask,
#     KeyPoint2D,
#     KeyPoint2DArray,
#     Detection,
#     DetectionArray,
# )

class YOLOV8NodeBB(Node):

    def __init__(self):
        super().__init__('yolov8_node_bb')

        # --------------------
        # Parameters
        # --------------------
        self.declare_parameter('model', '')
        self.declare_parameter('device', 'cuda:0')
        self.declare_parameter('conf_thres', 0.5)
        self.declare_parameter('image_topic', '/camera/color/image_raw')

        self.model_path: str = self.get_parameter('model').value
        self.device: str = self.get_parameter('device').value
        self.conf_thres: float = self.get_parameter('conf_thres').value
        self.image_topic: str = self.get_parameter('image_topic').value

        if not self.model_path:
            self.get_logger().fatal('model parameter is empty')
            raise RuntimeError('YOLO model path is not set')

        self.get_logger().info(f'YOLOv8 model   : {self.model_path}')
        self.get_logger().info(f'YOLOv8 device  : {self.device}')
        self.get_logger().info(f'YOLOv8 conf    : {self.conf_thres}')
        self.get_logger().info(f'Subscribe img  : {self.image_topic}')

        # --------------------
        # Utils
        # --------------------
        self.bridge = CvBridge()

        # --------------------
        # YOLO
        # --------------------
        self.yolo = YOLO(self.model_path)
        self.yolo.fuse()

        # --------------------
        # Pub / Sub
        # --------------------
        self.result_pub = self.create_publisher(
            DetectionArray,
            '/yolov8_node/result',
            10
        )

        self.sub = self.create_subscription(
            Image,
            self.image_topic,
            self.callback,
            qos_profile_sensor_data
        )

        self.last_time = time.time()

    # ==================================================
    # Callback
    # ==================================================
    def callback(self, msg: Image):
        now = time.time()
        self.get_logger().debug(
            f'callback dt: {now - self.last_time:.3f}s'
        )
        self.last_time = now

        # ROS Image -> OpenCV
        cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')

        # YOLO inference
        results_list = self.yolo.predict(
            source=cv_image,
            conf=self.conf_thres,
            device=self.device,
            verbose=False,
            stream=False,
        )

        if not results_list:
            return

        results: Results = results_list[0].cpu()

        detection_array = DetectionArray()
        detection_array.header = msg.header
        detection_array.input_image = msg

        if results.boxes is None:
            self.result_pub.publish(detection_array)
            return

        # --------------------
        # Parse detections
        # --------------------
        for box in results.boxes:
            det = Detection()

            class_id = int(box.cls)
            det.class_id = class_id
            det.class_name = self.yolo.names[class_id]
            det.score = float(box.conf)

            bbox_msg = BoundingBox2D()
            xywh = box.xywh[0]

            bbox_msg.center.position.x = float(xywh[0])
            bbox_msg.center.position.y = float(xywh[1])
            bbox_msg.size.x = float(xywh[2])
            bbox_msg.size.y = float(xywh[3])

            det.bbox = bbox_msg
            detection_array.detections.append(det)

        self.result_pub.publish(detection_array)


# ==================================================
# main
# ==================================================
def main():
    rclpy.init()
    node = YOLOV8NodeBB()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
