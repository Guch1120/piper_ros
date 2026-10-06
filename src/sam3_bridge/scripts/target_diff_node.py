#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS2版 DiffTarget (HSR: ditf_target.py の移植)。

SAM3 が出したマスク画像 (/sam/mask) から物体の左端/右端/中心のx座標を求め、
ガイド線 (既定は画像中心) との差分[pixel]を publish する。

出力 (geometry_msgs/PointStamped, header はマスクのheaderをそのまま引き継ぐ):
    point.x = diff_pixel   (object_x - grid_x, 物体が右にあるとき正)
    point.y = object_y     (代表y座標[pixel])
    point.z = image_width  (差分を正規化したい場合用)
マスクが空のときは publish しない (追従側は timeout で停止する)。
"""
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import PointStamped


def mask_to_gray(msg):
    """sensor_msgs/Image (mono8 / bgr8 / rgb8 / mono16) -> 2D numpy配列 (cv_bridge不使用)。"""
    enc = msg.encoding.lower()
    if enc in ('mono8', '8uc1'):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
        return arr[:, :msg.width]
    if enc in ('mono16', '16uc1'):
        dtype = np.dtype(np.uint16).newbyteorder('>' if msg.is_bigendian else '<')
        arr = np.frombuffer(msg.data, dtype=dtype).reshape(msg.height, msg.step // 2)
        return arr[:, :msg.width]
    if enc in ('bgr8', 'rgb8'):
        arr = np.frombuffer(msg.data, dtype=np.uint8).reshape(msg.height, msg.step)
        return arr[:, :msg.width * 3].reshape(msg.height, msg.width, 3)[:, :, 0]
    raise ValueError('unsupported mask encoding: {}'.format(msg.encoding))


def get_object_pixel_from_mask(mask_gray, target_edge='center',
                               y_min_ratio=0.0, y_max_ratio=1.0, min_pixels=1):
    """ditf_target.py の _get_object_pixel_from_mask と同じ定義。

    Returns: object_x, object_y, x_left, x_right, x_center
    """
    height, width = mask_gray.shape[:2]
    y_min = max(0, min(height - 1, int(height * y_min_ratio)))
    y_max = max(y_min + 1, min(height, int(height * y_max_ratio)))
    ys, xs = np.where(mask_gray[y_min:y_max, :] > 0)
    if xs.size < max(1, min_pixels):
        raise RuntimeError('No mask pixels found.')

    x_left = int(xs.min())
    x_right = int(xs.max())
    x_center = int((x_left + x_right) / 2.0)
    object_y = int(np.median(ys) + y_min)

    if target_edge == 'left':
        object_x = x_left
    elif target_edge == 'right':
        object_x = x_right
    elif target_edge == 'center':
        object_x = x_center
    else:
        raise ValueError('Invalid target_edge: {}. Use "left", "right", or "center".'
                         .format(target_edge))
    object_x = max(0, min(width - 1, object_x))
    object_y = max(0, min(height - 1, object_y))
    return object_x, object_y, x_left, x_right, x_center


class TargetDiffNode(Node):
    def __init__(self):
        super().__init__('target_diff')
        self.declare_parameter('mask_topic', '/sam/mask')
        self.declare_parameter('diff_topic', '/sam3/target_diff')
        self.declare_parameter('grid_x_pixel', -1)          # <0: 画像中心
        self.declare_parameter('target_edge', 'center')     # left / right / center
        self.declare_parameter('y_min_ratio', 0.0)
        self.declare_parameter('y_max_ratio', 1.0)
        self.declare_parameter('min_mask_pixels', 50)       # ノイズ対策
        self.declare_parameter('publish_debug_image', True)
        self.declare_parameter('debug_image_topic', '/debug/mask_grid/image')

        p = self.get_parameter
        self.mask_topic = p('mask_topic').value
        self.grid_x_pixel = int(p('grid_x_pixel').value)
        self.target_edge = p('target_edge').value
        self.y_min_ratio = float(p('y_min_ratio').value)
        self.y_max_ratio = float(p('y_max_ratio').value)
        self.min_mask_pixels = int(p('min_mask_pixels').value)
        self.publish_debug = bool(p('publish_debug_image').value)

        self.diff_pub = self.create_publisher(PointStamped, p('diff_topic').value, 10)
        self.debug_pub = (self.create_publisher(Image, p('debug_image_topic').value, 1)
                          if self.publish_debug else None)
        self.create_subscription(Image, self.mask_topic, self.mask_cb, 1)
        self.get_logger().info('target_diff: {} -> {} (edge={})'.format(
            self.mask_topic, p('diff_topic').value, self.target_edge))

    def mask_cb(self, msg):
        try:
            gray = mask_to_gray(msg)
            ox, oy, xl, xr, xc = get_object_pixel_from_mask(
                gray, self.target_edge, self.y_min_ratio, self.y_max_ratio,
                self.min_mask_pixels)
        except Exception as e:  # マスク無し等。publishしないことで追従側を止める
            self.get_logger().warn('diff not computed: {}'.format(e),
                                   throttle_duration_sec=2.0)
            return

        width = gray.shape[1]
        grid_x = width // 2 if self.grid_x_pixel < 0 else max(0, min(width - 1, self.grid_x_pixel))
        diff = int(ox - grid_x)

        out = PointStamped()
        out.header = msg.header
        out.point.x = float(diff)
        out.point.y = float(oy)
        out.point.z = float(width)
        self.diff_pub.publish(out)

        if self.debug_pub is not None:
            self.publish_debug(gray, msg.header, grid_x, ox, xl, xr)

    def publish_debug(self, gray, header, grid_x, object_x, x_left, x_right):
        """緑=ガイド, 赤=比較対象, 青=左右端 (bgr8)。"""
        h, w = gray.shape[:2]
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[gray > 0] = (255, 255, 255)
        for x, bgr, t in ((x_left, (255, 0, 0), 1), (x_right, (255, 0, 0), 1),
                          (grid_x, (0, 255, 0), 2), (object_x, (0, 0, 255), 2)):
            img[:, max(0, x - t // 2):min(w, x + t // 2 + 1)] = bgr
        m = Image()
        m.header = header
        m.height, m.width = h, w
        m.encoding = 'bgr8'
        m.step = w * 3
        m.data = img.tobytes()
        self.debug_pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = TargetDiffNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
