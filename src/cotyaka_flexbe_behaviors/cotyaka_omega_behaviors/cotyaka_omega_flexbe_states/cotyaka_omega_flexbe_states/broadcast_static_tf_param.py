#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from geometry_msgs.msg import TransformStamped
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster

from scipy.spatial.transform import Rotation as R


class BroadcastStaticTFParamState(EventState):
    '''
    パラメータで指定された座標にStatic TFを発行し、反映を待機するState
    ラジアンで与えて内部でTFに合わせてクォータニオンに変換する

    -- parent_frame string 親フレーム (例: 'base_link')
    -- child_frame  string 発行するフレーム名 (例: 'grasp_target')
    -- xyz_val      list   [x, y, z] (メートル)
    -- rpy_val      list   [roll, pitch, yaw] (ラジアン)
    -- wait_time    float  TF発行後の待機時間 [s] (default: 1.0)
                           ※MoveItへのTF伝播遅延を防ぐため、0.5〜1.0秒程度を推奨

    <= done         発行完了し、待機時間が経過した
    '''

    def __init__(self, parent_frame='base_link', child_frame='target_position', xyz_val=[0.0, 0.0, 0.0], rpy_val=[0.0, 0.0, 0.0], wait_time=0.5):
        super(BroadcastStaticTFParamState, self).__init__(outcomes=['done'])

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._xyz_val = xyz_val
        self._rpy_val = rpy_val
        self._wait_time = wait_time

        self._node = ProxyPublisher._node
        self._broadcaster = StaticTransformBroadcaster(self._node)
        self._start_time = None

    def on_enter(self, userdata):
        try:
            # 待機用の開始時刻を記録
            self._start_time = self._node.get_clock().now()

            t = TransformStamped()
            t.header.stamp = self._start_time.to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame

            # パラメータの取得と型変換
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

            Logger.loginfo(
                f'Static TF Broadcasted: {self._parent_frame} -> {self._child_frame} | '
                f'Wait {self._wait_time:.1f}s for propagation...'
            )
            
        except Exception as e:
            Logger.logerr(f'Failed to broadcast TF: {e}')
            self._start_time = None # エラー時は即終了させる

    def execute(self, userdata):
        # エラー発生時や待機時間が0以下の場合は即時終了
        if self._start_time is None or self._wait_time <= 0:
            return 'done'
        
        # 経過時間の計算 (ナノ秒 -> 秒)
        elapsed = (self._node.get_clock().now() - self._start_time).nanoseconds / 1e9
        
        # 待機時間が経過したら終了
        if elapsed >= self._wait_time:
            return 'done'
        
        # まだ待機中 (FlexBEはこの間 execute をループし続ける)
        return None