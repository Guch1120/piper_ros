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

    -- parent_frame   string  親フレーム（例: 'base_link'）
    -- child_frame    string  発行する子フレーム（例: 'target_object'）
    -- camera_frame   string  uvz の基準（例: 'camera_color_optical_frame'）

    ># u float
    ># v float
    ># z float

    <= succeeded
    <= tf_not_found
    <= failed
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

        # ★ FlexBEが管理するNodeを使う（これが最重要）
        self._node = ProxyPublisher._node

        # TF関連もこのNodeにぶら下げる
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
        Logger.loginfo('[TF State] Publishing object TF...')

        try:
            u = float(userdata.u)
            v = float(userdata.v)
            z = float(userdata.z)

            if z <= 0.0:
                Logger.logwarn('[TF State] Invalid depth (z <= 0).')
                self._outcome = 'failed'
                return

            # 画像座標 -> カメラ座標
            x = (u - self.cx) * z / self.fx
            y = (v - self.cy) * z / self.fy

            p = PointStamped()
            p.header.frame_id = self._camera_frame
            p.header.stamp = self._node.get_clock().now().to_msg()
            p.point.x = x
            p.point.y = y
            p.point.z = z

            # TFが無いと変換できないので待つ
            can = self._tf_buffer.can_transform(
                self._parent_frame,
                self._camera_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=2.0)
            )
            if not can:
                Logger.logwarn(
                    f'[TF State] TF not found: {self._camera_frame} -> {self._parent_frame}'
                )
                self._outcome = 'tf_not_found'
                return

            pw = self._tf_buffer.transform(p, self._parent_frame)

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
                f'[TF State] Broadcasted: {self._parent_frame} -> {self._child_frame}'
            )
            self._outcome = 'succeeded'

        except Exception as e:
            Logger.logerr(f'[TF State] Exception: {e}')
            self._outcome = 'failed'

    def execute(self, userdata):
        # on_enterで即決めているので、ここは返すだけ
        return self._outcome
