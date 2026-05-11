#!/usr/bin/env python3
import rospy
import cv2
import numpy as np
import threading

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "drag_segment"))

from sensor_msgs.msg import Image
from geometry_msgs.msg import Polygon, Point32
from cv_bridge import CvBridge


class DragSegmentGUI:
    def __init__(self):
        rospy.init_node("drag_segment_gui", anonymous=True)

        topic = rospy.get_param(
            "~topic_name",
            "/hsrb/head_rgbd_sensor/rgb/image_rect_color",
        )

        self.bridge = CvBridge()
        self.current_frame = None
        self.overlay_frame = None
        self.frame_lock = threading.Lock()

        # ドラッグ状態
        self.dragging = False
        self.drag_start = None
        self.drag_end = None

        # Publisher
        self.box_pub = rospy.Publisher("/drag_box", Polygon, queue_size=1)

        # Subscriber
        rospy.Subscriber(topic, Image, self._image_callback, queue_size=1)
        rospy.Subscriber("/sam/overlay", Image, self._overlay_callback, queue_size=1)

        rospy.loginfo("[DragGUI] 起動完了 - OpenCVウィンドウでドラッグしてください")

    def _image_callback(self, msg):
        frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        with self.frame_lock:
            self.current_frame = frame
            self.overlay_frame = None  # 新フレームが来たらオーバーレイをリセット

    def _overlay_callback(self, msg):
        overlay = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        with self.frame_lock:
            self.overlay_frame = overlay

    def _mouse_callback(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.drag_start = (x, y)
            self.drag_end = (x, y)

        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            self.drag_end = (x, y)

        elif event == cv2.EVENT_LBUTTONUP:
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

        # ボックスが小さすぎる場合はスキップ
        if (x2 - x1) < 10 or (y2 - y1) < 10:
            rospy.logwarn("[DragGUI] ボックスが小さすぎるためスキップ")
            return

        msg = Polygon()
        msg.points = [
            Point32(x=float(x1), y=float(y1), z=0.0),  # 左上
            Point32(x=float(x2), y=float(y2), z=0.0),  # 右下
        ]
        self.box_pub.publish(msg)
        rospy.loginfo(f"[DragGUI] bbox publish: ({x1},{y1}) → ({x2},{y2})")

    def run(self):
        cv2.namedWindow("Drag Segment", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Drag Segment", 700, 500)
        cv2.setMouseCallback("Drag Segment", self._mouse_callback)

        while not rospy.is_shutdown():
            with self.frame_lock:
                # オーバーレイがあればオーバーレイを表示、なければカメラ画像
                if self.overlay_frame is not None:
                    display = self.overlay_frame.copy()
                elif self.current_frame is not None:
                    display = self.current_frame.copy()
                else:
                    display = None

            if display is not None:
                # ドラッグ中は矩形をリアルタイム描画
                if self.dragging and self.drag_start and self.drag_end:
                    cv2.rectangle(
                        display,
                        self.drag_start,
                        self.drag_end,
                        (255, 100, 0),  # 青色
                        2,
                    )

                # ドラッグ完了後のボックスを表示
                elif not self.dragging and self.drag_start and self.drag_end:
                    cv2.rectangle(
                        display,
                        self.drag_start,
                        self.drag_end,
                        (0, 255, 0),  # 緑色
                        2,
                    )

                cv2.imshow("Drag Segment", display)

            key = cv2.waitKey(30)
            # r キーでリセット
            if key == ord("r"):
                self.drag_start = None
                self.drag_end = None
                with self.frame_lock:
                    self.overlay_frame = None
                rospy.loginfo("[DragGUI] リセット")
            # q キーで終了
            elif key == ord("q") or key == 27:
                break

        cv2.destroyAllWindows()


if __name__ == "__main__":
    gui = DragSegmentGUI()
    gui.run()
