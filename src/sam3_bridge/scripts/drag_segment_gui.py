#!/usr/bin/env python3
import threading

import cv2
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Point32, Polygon
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


class DragSegmentGUI(Node):
    WINDOW_NAME = "Drag Segment"

    def __init__(self):
        super().__init__("drag_segment_gui")
        self.declare_parameter(
            "topic_name", "/hsrb/head_rgbd_sensor/rgb/image_rect_color"
        )
        self.declare_parameter("overlay_topic", "/sam/overlay")
        self.declare_parameter("drag_box_topic", "/drag_box")

        self.bridge = CvBridge()
        self.current_frame = None
        self.overlay_frame = None
        self.frame_lock = threading.Lock()
        self.dragging = False
        self.drag_start = None
        self.drag_end = None

        self.box_pub = self.create_publisher(
            Polygon, str(self.get_parameter("drag_box_topic").value), 1
        )
        self.image_sub = self.create_subscription(
            Image,
            str(self.get_parameter("topic_name").value),
            self._image_callback,
            qos_profile_sensor_data,
        )
        self.overlay_sub = self.create_subscription(
            Image,
            str(self.get_parameter("overlay_topic").value),
            self._overlay_callback,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            "[DragGUI] 起動完了 - OpenCVウィンドウでドラッグしてください"
        )

    def _image_callback(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        with self.frame_lock:
            self.current_frame = frame
            self.overlay_frame = None

    def _overlay_callback(self, msg):
        overlay = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        with self.frame_lock:
            self.overlay_frame = overlay

    def _mouse_callback(self, event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.drag_start = (x, y)
            self.drag_end = (x, y)
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            self.drag_end = (x, y)
        elif event == cv2.EVENT_LBUTTONUP and self.dragging:
            self.drag_end = (x, y)
            self.dragging = False
            self._publish_box()

    def _publish_box(self):
        if self.drag_start is None or self.drag_end is None:
            return
        x1 = min(self.drag_start[0], self.drag_end[0])
        y1 = min(self.drag_start[1], self.drag_end[1])
        x2 = max(self.drag_start[0], self.drag_end[0])
        y2 = max(self.drag_start[1], self.drag_end[1])
        if x2 - x1 < 10 or y2 - y1 < 10:
            self.get_logger().warning(
                "[DragGUI] ボックスが小さすぎるためスキップ"
            )
            return
        msg = Polygon(
            points=[
                Point32(x=float(x1), y=float(y1), z=0.0),
                Point32(x=float(x2), y=float(y2), z=0.0),
            ]
        )
        self.box_pub.publish(msg)
        self.get_logger().info(
            f"[DragGUI] bbox publish: ({x1},{y1}) -> ({x2},{y2})"
        )

    def run(self):
        cv2.namedWindow(self.WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.WINDOW_NAME, 700, 500)
        cv2.setMouseCallback(self.WINDOW_NAME, self._mouse_callback)
        try:
            while rclpy.ok():
                rclpy.spin_once(self, timeout_sec=0.01)
                with self.frame_lock:
                    source = (
                        self.overlay_frame
                        if self.overlay_frame is not None
                        else self.current_frame
                    )
                    display = source.copy() if source is not None else None
                if display is not None:
                    if self.drag_start and self.drag_end:
                        color = (255, 100, 0) if self.dragging else (0, 255, 0)
                        cv2.rectangle(
                            display, self.drag_start, self.drag_end, color, 2
                        )
                    cv2.imshow(self.WINDOW_NAME, display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("r"):
                    self.drag_start = None
                    self.drag_end = None
                    with self.frame_lock:
                        self.overlay_frame = None
                    self.get_logger().info("[DragGUI] リセット")
                elif key in (ord("q"), 27):
                    break
        finally:
            cv2.destroyAllWindows()


def main(args=None):
    rclpy.init(args=args)
    node = DragSegmentGUI()
    try:
        node.run()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
