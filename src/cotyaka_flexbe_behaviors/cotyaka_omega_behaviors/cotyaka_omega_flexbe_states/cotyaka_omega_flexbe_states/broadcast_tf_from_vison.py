#!/usr/bin/env python3
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
import rclpy
from rclpy.duration import Duration
import tf2_ros
import tf2_geometry_msgs 
from tf2_ros.static_transform_broadcaster import StaticTransformBroadcaster
from sensor_msgs.msg import CameraInfo
from geometry_msgs.msg import PointStamped, TransformStamped, PoseArray
import math


class BroadcastTFfromVision(EventState):
    """
    userdata(pose_array) から 点群の重心を計算し、
    TF(child_frame) を parent_frame に発行する FlexBE State
    
    -- parent_frame     string  親フレーム（必ず 'base_link' や 'world' を指定すること）
    -- child_frame      string  発行する子フレーム名（例: 'target'）
    -- camera_frame     string  uvzの基準（PoseArrayのheaderが空の場合の予備。基本は 'camera_color_optical_frame'）
    -- camera_info_topic string CameraInfo トピック名
    -- wait_info_sec    float   CameraInfo を待機するタイムアウト
    -- tf_timeout_sec   float   TF 変換のタイムアウト

    ># pose_array       PoseArray  SAM3ノードからの出力 (u, v, depth) のリスト
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
            input_keys=['pose_array']
        )

        self._parent_frame = parent_frame
        self._child_frame = child_frame
        # 復活させた引数をデフォルト値として保存
        self._default_camera_frame = camera_frame
        
        self._camera_info_topic = camera_info_topic
        self._wait_info_sec = float(wait_info_sec)
        self._tf_timeout = Duration(seconds=float(tf_timeout_sec))

        # FlexBE managed node
        self._node = ProxyPublisher._node

        # TF Buffer and Listener
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self._node)
        self._broadcaster = StaticTransformBroadcaster(self._node)

        # Debug Publishers
        self._pub_cam_point = self._node.create_publisher(PointStamped, '/sam3/point_cam_avg', 1)
        self._pub_parent_point = self._node.create_publisher(PointStamped, '/sam3/point_parent_avg', 1)

        self._fx = self._fy = self._cx = self._cy = None
        self._got_info = False

        self._sub_info = self._node.create_subscription(
            CameraInfo, self._camera_info_topic, self._info_cb, 1
        )

        self._calculation_done = False

    def _info_cb(self, msg: CameraInfo):
        try:
            self._fx = float(msg.k[0])
            self._fy = float(msg.k[4])
            self._cx = float(msg.k[2])
            self._cy = float(msg.k[5])
            self._got_info = True
        except Exception as e:
            Logger.logwarn(f'[TF State] CameraInfo parse error: {e}')

    def on_enter(self, userdata):
        self._calculation_done = False
        Logger.loginfo(f'[TF State] Entering for target: {self._child_frame}')

    def execute(self, userdata):
        if self._calculation_done:
            return 'succeeded'

        if not self._got_info:
            return None 

        try:
            pose_array_msg = userdata.pose_array
            
            if not pose_array_msg or len(pose_array_msg.poses) == 0:
                Logger.logwarn('[TF State] Received empty PoseArray')
                return 'failed'

            # フレームIDの解決: PoseArrayにheaderがあればそれを優先、なければ引数のcamera_frameを使う
            current_camera_frame = pose_array_msg.header.frame_id
            if not current_camera_frame:
                current_camera_frame = self._default_camera_frame

            # --- 平均計算ロジック ---
            sum_x = 0.0
            sum_y = 0.0
            sum_z = 0.0
            valid_count = 0

            for pose in pose_array_msg.poses:
                u = float(pose.position.x)
                v = float(pose.position.y)
                z = float(pose.position.z)

                if z <= 0.0:
                    continue

                xc = (u - self._cx) * z / self._fx
                yc = (v - self._cy) * z / self._fy
                zc = z

                sum_x += xc
                sum_y += yc
                sum_z += zc
                valid_count += 1

            if valid_count == 0:
                Logger.logwarn('[TF State] No valid points (z>0) in PoseArray')
                return 'failed'

            avg_x_cam = sum_x / valid_count
            avg_y_cam = sum_y / valid_count
            avg_z_cam = sum_z / valid_count

            Logger.loginfo(f'[TF State] Avg Centroid: ({avg_x_cam:.3f}, {avg_y_cam:.3f}, {avg_z_cam:.3f}) N={valid_count}')

            p = PointStamped()
            p.header.frame_id = current_camera_frame
            p.header.stamp = self._node.get_clock().now().to_msg()
            p.point.x = avg_x_cam
            p.point.y = avg_y_cam
            p.point.z = avg_z_cam
            self._pub_cam_point.publish(p)

            # TF確認
            if not self._tf_buffer.can_transform(
                self._parent_frame,
                current_camera_frame,
                rclpy.time.Time(),
                timeout=self._tf_timeout
            ):
                Logger.logwarn(f'[TF State] No TF from {current_camera_frame} to {self._parent_frame}')
                return 'tf_not_found'

            # 座標変換 (PointStamped: cam -> parent)
            pw = self._tf_buffer.transform(p, self._parent_frame, timeout=self._tf_timeout)
            self._pub_parent_point.publish(pw)

            # TF構築
            t = TransformStamped()
            t.header.stamp = self._node.get_clock().now().to_msg()
            t.header.frame_id = self._parent_frame
            t.child_frame_id = self._child_frame
            
            # Rotation (link6 align) & Offset Calculation
            try:
                tf_link6 = self._tf_buffer.lookup_transform(
                    self._parent_frame, 'link6', rclpy.time.Time(), timeout=self._tf_timeout
                )
                q = tf_link6.transform.rotation
                t.transform.rotation = q
                
                # --- Offset Calculation Logic Modified ---
                # オフセット設定 (単位: m)
                off_val_z = -0.05 # 既存: Z軸(青)の負方向へ5cm (ハンドの手前)
                off_val_x = 0.06  # 新規: X軸(赤)方向へのオフセット (必要に応じて値を変更してください)

                # クォータニオン成分
                qx, qy, qz, qw = q.x, q.y, q.z, q.w

                # 回転行列の第1列 (ローカルX軸ベクトル)
                # R00 = 1 - 2(y^2 + z^2)
                # R10 = 2(xy + wz)
                # R20 = 2(xz - wy)
                vec_x_x = 1.0 - 2.0 * (qy*qy + qz*qz)
                vec_x_y = 2.0 * (qx*qy + qw*qz)
                vec_x_z = 2.0 * (qx*qz - qw*qy)

                # 回転行列の第3列 (ローカルZ軸ベクトル)
                # R02 = 2(xz + wy)
                # R12 = 2(yz - wx)
                # R22 = 1 - 2(x^2 + y^2)
                vec_z_x = 2.0 * (qx*qz + qw*qy)
                vec_z_y = 2.0 * (qy*qz - qw*qx)
                vec_z_z = 1.0 - 2.0 * (qx*qx + qy*qy)

                # 合成オフセット計算 (Global Frameでの変位)
                x_off = (off_val_x * vec_x_x) + (off_val_z * vec_z_x)
                y_off = (off_val_x * vec_x_y) + (off_val_z * vec_z_y)
                z_off = (off_val_x * vec_x_z) + (off_val_z * vec_z_z)
                
                # 位置に加算
                t.transform.translation.x = pw.point.x + x_off
                t.transform.translation.y = pw.point.y + y_off
                t.transform.translation.z = pw.point.z + z_off

            except Exception as e:
                Logger.logwarn(f"[TF State] Rotation error: {e}")
                t.transform.rotation.w = 1.0
                t.transform.translation.x = pw.point.x
                t.transform.translation.y = pw.point.y
                t.transform.translation.z = pw.point.z
                
            # Broadcast
            self._broadcaster.sendTransform(t)
            Logger.loginfo(f'[TF State] Broadcasted TF: {self._child_frame} -> {self._parent_frame}')
            
            # Propagation check
            if self._tf_buffer.can_transform(
                self._parent_frame,
                self._child_frame,
                rclpy.time.Time(),
                timeout=Duration(seconds=0.5)
            ):
                self._calculation_done = True
                return 'succeeded'            
            else:
                Logger.logwarn('[TF State] Waiting for TF propagation...')
                return None

        except Exception as e:
            Logger.logerr(f'[TF State] Critical Exception: {e}')
            return 'failed'