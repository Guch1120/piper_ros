#!/usr/bin/env python3
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher

import rclpy
from rclpy.duration import Duration

import tf2_ros
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
import tf2_geometry_msgs

from geometry_msgs.msg import PointStamped, TransformStamped


class BroadcastTFfromVision(EventState):
    """
    FlexBEのuserdata(u,v,z) から TF(child_frame) を parent_frame に発行するState
    """

    def __init__(self,
                 parent_frame='base_link',
                 child_frame='target_object',
                 camera_frame='camera_color_optical_frame'):
        super(BroadcastTFfromVision, self).__init__(
            outcomes=['succeeded', 'tf_not_found', 'failed'],
            input_keys=['u', 'v', 'z']
        )

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._camera_frame = camera_frame

        # FlexBE 管理 Node
        self._node = ProxyPublisher._node

        # TF
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self._node)
        self._broadcaster = StaticTransformBroadcaster(self._node)

        # Camera intrinsics
        self.fx = 909.4475708007812
        self.fy = 907.5896606445312
        self.cx = 637.9448852539062
        self.cy = 378.9811706542969

        self._outcome = None

    def on_enter(self, userdata):
        self._outcome = None

        try:
            u = float(userdata.u)
            v = float(userdata.v)
            z = float(userdata.z)

            Logger.loginfo(
                f'[TF State] Input uvz: u={u:.2f}, v={v:.2f}, z={z:.3f} [m]'
            )

            if z <= 0.0:
                Logger.logwarn('[TF State] Invalid depth (z <= 0)')
                self._outcome = 'failed'
                return

            # 画像座標 → カメラ座標（optical frame）
            x_cam = (u - self.cx) * z / self.fx
            y_cam = (v - self.cy) * z / self.fy
            z_cam = z

            Logger.loginfo(
                f'[TF State] Camera({self._camera_frame}): '
                f'x={x_cam:.3f}, y={y_cam:.3f}, z={z_cam:.3f}'
            )

            p = PointStamped()
            p.header.frame_id = self._camera_frame
            p.header.stamp = self._node.get_clock().now().to_msg()
            p.point.x = x_cam
            p.point.y = y_cam
            p.point.z = z_cam

            # TF確認
            if not self._tf_buffer.can_transform(
                self._parent_frame,
                self._camera_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=2.0)
            ):
                Logger.logwarn(
                    f'[TF State] TF not found: {self._camera_frame} -> {self._parent_frame}'
                )
                self._outcome = 'tf_not_found'
                return

            # 座標変換
            pw = self._tf_buffer.transform(p, self._parent_frame)

            Logger.loginfo(
                f'[TF State] Parent({self._parent_frame}): '
                f'x={pw.point.x:.3f}, y={pw.point.y:.3f}, z={pw.point.z:.3f}'
            )

            # Static TF 発行
            t = TransformStamped()
            t.header.stamp = self._node.get_clock().now().to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame
            t.transform.translation.x = pw.point.x
            t.transform.translation.y = pw.point.y
            t.transform.translation.z = pw.point.z
            t.transform.rotation.w = 1.0

            self._broadcaster.sendTransform(t)

            Logger.loginfo(
                f'[TF State] Broadcasted TF: '
                f'{self._parent_frame} -> {self._child_frame}'
            )

            self._outcome = 'succeeded'

        except Exception as e:
            Logger.logerr(f'[TF State] Exception: {e}')
            self._outcome = 'failed'

    def execute(self, userdata):
        return self._outcome
