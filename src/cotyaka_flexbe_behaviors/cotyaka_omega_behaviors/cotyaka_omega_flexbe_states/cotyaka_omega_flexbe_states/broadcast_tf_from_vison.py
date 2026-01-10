#!/usr/bin/env python3
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
import rclpy
from rclpy.duration import Duration
import tf2_ros
import tf2_geometry_msgs 
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from sensor_msgs.msg import CameraInfo
from geometry_msgs.msg import PointStamped, TransformStamped
import math


class BroadcastTFfromVision(EventState):
    """
    userdata(u,v,z) から TF(child_frame) を parent_frame に発行する FlexBE State
    一度計算して TF を発行したらすぐに succeeded で終了する (One-shot)
    
    -- parent_frame     string  親フレーム（必ず 'base_link' や 'world' を指定すること）
    -- child_frame      string  発行する子フレーム名（例: 'target'）
    -- camera_frame     string  uvzの基準（'camera_color_optical_frame' を推奨）
    -- camera_info_topic string CameraInfo トピック名
    -- wait_info_sec    float   CameraInfo を待機するタイムアウト
    -- tf_timeout_sec   float   TF 変換のタイムアウト
    """

    def __init__(self,
                 parent_frame='base_link',
                 child_frame='target',
                 camera_frame='camera_color_optical_frame',
                 camera_info_topic='/camera/camera/color/camera_info',
                 wait_info_sec=0.5,
                 tf_timeout_sec=2.0):
        super(BroadcastTFfromVision, self).__init__(
            outcomes=['succeeded', 'tf_not_found', 'failed'],
            input_keys=['u', 'v', 'z']
        )

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        self._camera_frame = camera_frame
        self._camera_info_topic = camera_info_topic
        self._wait_info_sec = float(wait_info_sec)
        self._tf_timeout = Duration(seconds=float(tf_timeout_sec))

        # FlexBE managed node
        self._node = ProxyPublisher._node

        # TF Buffer and Listener
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self._node)
        # 静的TF発行（一度発行すればその位置に固定される）
        self._broadcaster = StaticTransformBroadcaster(self._node)

        # Debug Publishers
        self._pub_cam_point = self._node.create_publisher(PointStamped, '/sam3/point_cam', 1)
        self._pub_parent_point = self._node.create_publisher(PointStamped, '/sam3/point_parent', 1)

        self._fx = self._fy = self._cx = self._cy = None
        self._got_info = False

        # Subscriber for CameraInfo
        self._sub_info = self._node.create_subscription(
            CameraInfo, self._camera_info_topic, self._info_cb, 1
        )

        self._calculation_done = False

    def _info_cb(self, msg: CameraInfo):
        try:
            # K = [fx 0 cx; 0 fy cy; 0 0 1]
            self._fx = float(msg.k[0])
            self._fy = float(msg.k[4])
            self._cx = float(msg.k[2])
            self._cy = float(msg.k[5])
            self._got_info = True
        except Exception as e:
            Logger.logwarn(f'[TF State] CameraInfo parse error: {e}')

    def on_enter(self, userdata):
        # 状態に入るたびにフラグをリセット
        self._calculation_done = False
        Logger.loginfo(f'[TF State] Entering for target: {self._child_frame}')

    def execute(self, userdata):
        # すでに一度計算が完了していればその結果（outcome）を返す
        if self._calculation_done:
            return 'succeeded'

        # 1. CameraInfo 待機
        if not self._got_info:
            # CameraInfoがまだ来ていない場合は execute のループを継続（ブロッキング回避）
            return None 

        try:
            # 2. 入力データの取得
            u, v, z = float(userdata.u), float(userdata.v), float(userdata.z)

            if z <= 0.0:
                Logger.logwarn('[TF State] Invalid depth (z <= 0)')
                return 'failed'

            # 3. 2Dピクセル座標 -> 3Dカメラ座標（Optical Frame 基準）
            x_cam = (u - self._cx) * z / self._fx
            y_cam = (v - self._cy) * z / self._fy
            z_cam = z

            # PointStamped メッセージ構築
            p = PointStamped()
            p.header.frame_id = self._camera_frame
            # 現在時刻ではなく「0」を指定して最新の変換を利用、またはノード時刻を使用
            p.header.stamp = self._node.get_clock().now().to_msg()
            p.point.x = x_cam
            p.point.y = y_cam
            p.point.z = z_cam
            self._pub_cam_point.publish(p)

            # 4. TFの利用可能性確認
            if not self._tf_buffer.can_transform(
                self._parent_frame,
                self._camera_frame,
                rclpy.time.Time(),
                timeout=self._tf_timeout
            ):
                Logger.logwarn(f'[TF State] No TF from {self._camera_frame} to {self._parent_frame}')
                return 'tf_not_found'

            # 5. カメラ座標系から世界（親）座標系へ点を変換
            # ここで camera_color_optical_frame -> base_link の変換が行われる
            pw = self._tf_buffer.transform(p, self._parent_frame, timeout=self._tf_timeout)
            self._pub_parent_point.publish(pw)

            # 6. 静的 TF として発行
            # これにより target は parent_frame (base_link) に対して固定される
            t = TransformStamped()
            t.header.stamp = self._node.get_clock().now().to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame
            # rotationはlink6の姿勢に合わせることでmoveitで到達不可姿勢を避ける
            try:
            # base_link -> link6 の姿勢を取得してtarget にコピー
                tf_link6 = self._tf_buffer.lookup_transform(
                    self._parent_frame,   # base_link
                    'link6',              
                    rclpy.time.Time(),
                    timeout=self._tf_timeout
                )
                q = tf_link6.transform.rotation
                t.transform.rotation = q
            # link6 の -Z 方向に 0.06m
                d = 0.06
            # クォータニオン → 回転行列の -Z 列だけ計算
            # R * (0,0,-d)
                x = -d * (2*(q.x*q.z + q.w*q.y))
                y = -d * (2*(q.y*q.z - q.w*q.x))
                z = -d * (1 - 2*(q.x*q.x + q.y*q.y))
            # --- 位置に加算 ---
                t.transform.translation.x = pw.point.x + x
                t.transform.translation.y = pw.point.y + y
                t.transform.translation.z = pw.point.z + z
            except Exception as e:
                Logger.logwarn(f"[TF State] Could not get rotation from {self._parent_frame} -> link6: {e}")
                # フォールバック（回転なし・オフセットなし）
                t.transform.rotation.x = 0.0
                t.transform.rotation.y = 0.0
                t.transform.rotation.z = 0.0
                t.transform.rotation.w = 1.0
                t.transform.translation.x = pw.point.x
                t.transform.translation.y = pw.point.y
                t.transform.translation.z = pw.point.z
                
            # 7. TF 発行
            self._broadcaster.sendTransform(t)
            Logger.loginfo(f'[TF State] Broadcasted TF: {self._child_frame} -> {self._parent_frame}')
            
            # 8 同期確認 発行したTFが自分のバッファで引けるようになるまで待つ
            # ここが「succeeded」を返す前の最終チェック
            propagation_timeout = Duration(seconds=0.5)
            if self._tf_buffer.can_transform(
                self._parent_frame,
                self._child_frame,
                rclpy.time.Time(),
                timeout=propagation_timeout
            ):
                Logger.loginfo(f'[TF State] SUCCESS: Verified {self._child_frame} is active.')
                self._calculation_done = True
                return 'succeeded'            
            else:
                # 0.5秒待っても見つからない場合は、まだ反映されていないので次回ループで再試行
                # (Noneを返してステートに留まる)
                Logger.logwarn('[TF State] Waiting for TF propagation...')
                return None

        except Exception as e:
            Logger.logerr(f'[TF State] Critical Exception: {e}')
            return 'failed'