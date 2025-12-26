#!/usr/bin/env python3
from flexbe_core import EventState, Logger
import rclpy
from rclpy.duration import Duration
import tf2_ros
from geometry_msgs.msg import PointStamped, TransformStamped


class _TfPublishNode(rclpy.node.Node):
    def __init__(self):
        super().__init__('sam3_tf_state_node')

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.broadcaster = tf2_ros.StaticTransformBroadcaster(self)

        # Camera intrinsics
        self.fx = 909.4475708007812
        self.fy = 907.5896606445312
        self.cx = 637.9448852539062
        self.cy = 378.9811706542969

    def publish_tf(self, u, v, z, camera_frame, parent_frame, child_frame):
        if z <= 0.0:
            return False

        x = (u - self.cx) * z / self.fx
        y = (v - self.cy) * z / self.fy

        p = PointStamped()
        p.header.frame_id = camera_frame
        p.header.stamp = self.get_clock().now().to_msg()
        p.point.x = x
        p.point.y = y
        p.point.z = z

        if not self.tf_buffer.can_transform(
            parent_frame, camera_frame,
            rclpy.time.Time(),
            timeout=Duration(seconds=2.0)
        ):
            return False

        pw = self.tf_buffer.transform(p, parent_frame)

        t = TransformStamped()
        t.header.frame_id = parent_frame
        t.child_frame_id = child_frame
        t.header.stamp = self.get_clock().now().to_msg()
        t.transform.translation.x = pw.point.x
        t.transform.translation.y = pw.point.y
        t.transform.translation.z = pw.point.z
        t.transform.rotation.w = 1.0

        self.broadcaster.sendTransform(t)
        return True


class PublishObjectTFState(EventState):
    """
    (u,v,z) から TF を生成する FlexBE State
    """

    _node = None   # ★ クラス変数として保持（重要）

    def __init__(self, parent_frame, child_frame, camera_frame):
        super().__init__(
            outcomes=['succeeded', 'tf_not_found', 'failed'],
            input_keys=['u', 'v', 'z']
        )

        self.parent_frame = parent_frame
        self.child_frame = child_frame
        self.camera_frame = camera_frame

        self._outcome = None

        # Node は1回だけ生成
        if PublishObjectTFState._node is None:
            PublishObjectTFState._node = _TfPublishNode()

    def on_enter(self, userdata):
        Logger.loginfo('[TF State] Publishing object TF...')

        try:
            ok = self._node.publish_tf(
                userdata.u, userdata.v, userdata.z,
                self.camera_frame,
                self.parent_frame,
                self.child_frame
            )

            self._outcome = 'succeeded' if ok else 'tf_not_found'

        except Exception as e:
            Logger.logerr(f'[TF State] Failed: {e}')
            self._outcome = 'failed'

    def execute(self, userdata):
        return self._outcome
