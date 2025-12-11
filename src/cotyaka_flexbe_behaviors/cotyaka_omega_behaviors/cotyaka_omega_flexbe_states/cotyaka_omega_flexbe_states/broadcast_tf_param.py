#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
import tf_transformations
import math

class BroadcastStaticTfParamState(EventState):
    '''
    パラメータで指定された座標にStatic TFを発行するState。

    -- parent_frame string 親フレーム (例: 'base_link')
    -- child_frame  string 発行するフレーム名 (例: 'grasp_target')
    -- xyz_val      list   [x, y, z] (メートル)
    -- rpy_val      list   [roll, pitch, yaw] (ラジアン)

    <= done         発行完了
    '''

    def __init__(self, parent_frame='base_link', child_frame='interactive_set', xyz_val=[0.0, 0.0, 0.0], rpy_val=[0.0, 0.0, 0.0]):
        super(BroadcastStaticTfParamState, self).__init__(outcomes=['done'])
        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._xyz_val = xyz_val
        self._rpy_val = rpy_val
        self._node = ProxyPublisher._node        
        self._broadcaster = StaticTransformBroadcaster(self._node)

    def on_enter(self, userdata):
        t = TransformStamped()
        t.header.stamp = self._node.get_clock().now().to_msg()
        t.header.frame_id = self._parent_frame
        t.child_frame_id = self._child_frame

        t.transform.translation.x = float(self._xyz_val[0])
        t.transform.translation.y = float(self._xyz_val[1])
        t.transform.translation.z = float(self._xyz_val[2])

        qx, qy, qz, qw = self.euler_to_quaternion(
            float(self._rpy_val[0]), float(self._rpy_val[1]), float(self._rpy_val[2]))
        
        t.transform.rotation.x = qx
        t.transform.rotation.y = qy
        t.transform.rotation.z = qz
        t.transform.rotation.w = qw

        self._broadcaster.sendTransform(t)
        Logger.loginfo(f'Static TF Broadcasted (Param): {self._parent_frame} -> {self._child_frame}')

    def execute(self, userdata):
        return 'done'

    def euler_to_quaternion(self, roll, pitch, yaw):
        cy = math.cos(yaw * 0.5)
        sy = math.sin(yaw * 0.5)
        cp = math.cos(pitch * 0.5)
        sp = math.sin(pitch * 0.5)
        cr = math.cos(roll * 0.5)
        sr = math.sin(roll * 0.5)

        w = cr * cp * cy + sr * sp * sy
        x = sr * cp * cy - cr * sp * sy
        y = cr * sp * cy + sr * cp * sy
        z = cr * cp * sy - sr * sp * cy
        return x, y, z, w