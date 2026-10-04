#!/usr/bin/env python3

import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from scipy.spatial.transform import Rotation as R


class BroadcastStaticTfInout(EventState):
    '''
    input, outputでTFを発行
    '''

    def __init__(self,parent_frame='base_link',child_frame='target_position',wait_time=0.5):
        super(BroadcastStaticTfInout, self).__init__(
            outcomes=['done', 'failed'],
            input_keys=['xyz_val', 'rpy_val'],
            output_keys=['answerTF']
        )

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._wait_time = wait_time

        self._node = ProxyPublisher._node
        self._broadcaster = StaticTransformBroadcaster(self._node)

        self._start_time = None

    def on_enter(self, userdata):
        try:
            xyz_val = userdata.xyz_val
            rpy_val = userdata.rpy_val

            # 開始時間
            self._start_time = self._node.get_clock().now()

            t = TransformStamped()
            t.header.stamp = self._start_time.to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame

            # position
            x = float(xyz_val[0])
            y = float(xyz_val[1])
            z = float(xyz_val[2])

            # rotation (rpy)
            roll = float(rpy_val[0])
            pitch = float(rpy_val[1])
            yaw = float(rpy_val[2])

            # Translation
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = z

            # RPY → Quaternion
            rot = R.from_euler('xyz', [roll, pitch, yaw])
            qx, qy, qz, qw = rot.as_quat()

            t.transform.rotation.x = qx
            t.transform.rotation.y = qy
            t.transform.rotation.z = qz
            t.transform.rotation.w = qw

            self._broadcaster.sendTransform(t)

            # output
            userdata.answerTF = self._child_frame

            Logger.loginfo(
                f'Static TF Broadcasted: '
                f'{self._parent_frame} -> {self._child_frame}'
            )

        except Exception as e:
            Logger.logerr(f'Failed to broadcast TF: {str(e)}')
            self._start_time = None
            return 'failed'

    def execute(self, userdata):

        # エラー時 or wait_time <= 0
        if self._start_time is None:
            return 'failed'

        if self._wait_time <= 0:
            return 'done'

        elapsed = (
            self._node.get_clock().now()
            - self._start_time
        ).nanoseconds / 1e9

        if elapsed >= self._wait_time:
            return 'done'

        return None