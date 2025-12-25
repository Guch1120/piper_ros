#!/usr/bin/env python3
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
import rclpy
from rclpy.node import Node
from rclpy.duration import Duration
import tf2_ros
from geometry_msgs.msg import PointStamped, TransformStamped

class _TfPublishNode(Node):
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
        x = (u - self.cx) * z / self.fx
        y = (v - self.cy) * z / self.fy

        p = PointStamped()
        p.header.frame_id = camera_frame
        p.header.stamp = rclpy.time.Time().to_msg()
        p.point.x = x
        p.point.y = y
        p.point.z = z

        if not self.tf_buffer.can_transform(
            parent_frame, camera_frame, rclpy.time.Time(),
            timeout=Duration(seconds=2.0)
        ):
            return False

        pw = self.tf_buffer.transform(p, parent_frame)

        t = TransformStamped()
        t.header.frame_id = parent_frame
        t.child_frame_id = child_frame
        t.header.stamp = self.get_clock().now().to_msg()
        t.transform.translation = pw.point
        t.transform.rotation.w = 1.0

        self.broadcaster.sendTransform(t)
        return True


class PublishObjectTFState(EventState):
    """
    (u,v,z) から指定TFを生成するState
    """

    def __init__(self, parent_frame, child_frame, camera_frame):
        super().__init__(
            outcomes=['succeeded', 'tf_not_found', 'failed'],
            input_keys=['u', 'v', 'z']
        )
        self.parent_frame = parent_frame
        self.child_frame = child_frame
        self.camera_frame = camera_frame
        self._node = None

    def on_enter(self, userdata):
        rclpy.init(args=None)
        self._node = _TfPublishNode()

        ok = self._node.publish_tf(
            userdata.u, userdata.v, userdata.z,
            self.camera_frame,
            self.parent_frame,
            self.child_frame
        )

        self._outcome = 'succeeded' if ok else 'tf_not_found'

    def execute(self, userdata):
        return self._outcome

    def on_exit(self, userdata):
        self._node.destroy_node()
        rclpy.shutdown()
