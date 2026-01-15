#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import random
import cv2
import numpy as np

import rclpy
from rclpy.node import Node

from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from visualization_msgs.msg import Marker, MarkerArray
from yolov8_msgs.msg import DetectionArray, BoundingBox2D

class DebugYOLOv8(Node):

    def __init__(self):
        super().__init__('debug_yolov8_bb')

        self.bridge = CvBridge()
        self.class_color = {}

        self.sub = self.create_subscription(
            DetectionArray,
            '/yolov8_node/result',
            self.callback,
            1
        )

        self.image_pub = self.create_publisher(
            Image, 'debug/yolov8/image', 1
        )
        self.bb_pub = self.create_publisher(
            MarkerArray, 'debug/yolov8/bbox', 1
        )

    def callback(self, msg: DetectionArray):
        cv_image = self.bridge.imgmsg_to_cv2(
            msg.input_image, 'bgr8'
        )

        marker_array = MarkerArray()

        for i, det in enumerate(msg.detections):
            label = det.class_name
            if label not in self.class_color:
                self.class_color[label] = (
                    random.randint(0,255),
                    random.randint(0,255),
                    random.randint(0,255),
                )
            color = self.class_color[label]

            cv_image = self.draw_box(cv_image, det, color)

        self.image_pub.publish(
            self.bridge.cv2_to_imgmsg(cv_image, 'bgr8')
        )
        self.bb_pub.publish(marker_array)

    def draw_box(self, img, det, color):
        box: BoundingBox2D = det.bbox
        cx, cy = box.center.position.x, box.center.position.y
        w, h = box.size.x, box.size.y

        p1 = (int(cx - w/2), int(cy - h/2))
        p2 = (int(cx + w/2), int(cy + h/2))

        cv2.rectangle(img, p1, p2, color, 2)
        cv2.putText(
            img,
            f'{det.class_name} {det.score:.2f}',
            (p1[0], p1[1]-5),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2
        )
        return img


def main():
    rclpy.init()
    node = DebugYOLOv8()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
