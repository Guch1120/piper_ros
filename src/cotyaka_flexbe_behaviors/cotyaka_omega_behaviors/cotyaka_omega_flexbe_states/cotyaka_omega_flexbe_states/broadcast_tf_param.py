#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster

from scipy.spatial.transform import Rotation as R


class BroadcastStaticTFParamState(EventState):
    '''
    パラメータで指定された座標にStatic TFを発行するState。

    -- parent_frame string 親フレーム (例: 'base_link')
    -- child_frame  string 発行するフレーム名 (例: 'grasp_target')
    -- xyz_val      list   [x, y, z] (メートル)
    -- rpy_val      list   [roll, pitch, yaw] (ラジアン)

    <= done         発行完了
    <= failed       発行失敗
    '''

    # FlexBE UIのために引数を1行で記述
    def __init__(self, parent_frame='base_link', child_frame='interactive_set', xyz_val=[0.0, 0.0, 0.0], rpy_val=[0.0, 0.0, 0.0]):
        super(BroadcastStaticTFParamState, self).__init__(outcomes=['done'])

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._xyz_val = xyz_val
        self._rpy_val = rpy_val

        self._node = ProxyPublisher._node
        self._broadcaster = StaticTransformBroadcaster(self._node)

    def on_enter(self, userdata):
        try:
            t = TransformStamped()
            t.header.stamp = self._node.get_clock().now().to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame

            # パラメータが文字列で渡ってくる可能性を考慮しつつfloat変換
            x = float(self._xyz_val[0])
            y = float(self._xyz_val[1])
            z = float(self._xyz_val[2])
            
            roll = float(self._rpy_val[0])
            pitch = float(self._rpy_val[1])
            yaw = float(self._rpy_val[2])

            # Translation
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = z

            # Rotation (RPY → Quaternion) using scipy
            rot = R.from_euler('xyz', [roll, pitch, yaw])
            qx, qy, qz, qw = rot.as_quat()

            t.transform.rotation.x = qx
            t.transform.rotation.y = qy
            t.transform.rotation.z = qz
            t.transform.rotation.w = qw

            self._broadcaster.sendTransform(t)

            # 値確認用ログ（重要）
            Logger.loginfo(
                f'Static TF Broadcasted: {self._parent_frame} -> {self._child_frame} | '
                f'XYZ=[{x:.3f}, {y:.3f}, {z:.3f}]'
            )
            
        except Exception as e:
            Logger.logerr(f'Failed to broadcast TF: {e}')
            return # on_enterでのreturnは本来影響しないが、エラーログを残す

    def execute(self, userdata):
        return 'done'