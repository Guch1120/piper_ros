#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
import numpy as np
import math
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached, ProxyPublisher
from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PointStamped
from cv_bridge import CvBridge
import tf2_ros
import tf2_geometry_msgs
from rclpy.duration import Duration

class SAM3DiffTargetdHead(EventState):
    """
    マスク画像から物体の端線または中心を取得し、
    理想グリッド位置との差分を pixel ではなく base_link 座標系での移動量として出力する。

    グリッド点のDepthは使用せず、対象物体位置のDepthを基準にして
    pixel差分を実距離化する。

    固定使用トピック:
        CameraInfo:
            /hsrb/head_rgbd_sensor/rgb/camera_info

        RGB image:
            /hsrb/head_rgbd_sensor/rgb/image_rect_color

        Depth image:
            /hsrb/head_rgbd_sensor/depth_registered/image_rect_raw

        TF変換先:
            base_link

    -- mask_topic          string    参照するマスク画像トピック名
    -- grid_x_pixel        int       理想グリッドのx座標[pixel]。Noneの場合は画像中心を使用
    -- target_edge         string    使用する物体位置。"left", "right", "center" のいずれか
    -- y_min_ratio         float     マスク領域として使うy範囲の下限比率
    -- y_max_ratio         float     マスク領域として使うy範囲の上限比率
    -- debug_image_topic   string    デバッグ画像のpublish先
    -- publish_debug_image bool      デバッグ画像をpublishするか

    #> x                   float     グリッド線と対象物体位置との差分移動量[m]
    #> y                   float     対象物体のbase_link座標系でのy位置[m]

    <= done                         差分計算完了
    """

    def __init__(self,mask_topic='/sam/mask',grid_x_pixel=None,target_edge='center',y_min_ratio=0.0,y_max_ratio=1.0,debug_image_topic='/debug/mask_grid/image',publish_debug_image=True):

        super().__init__(outcomes=['done'],output_keys=['x', 'y'])
        self._mask_topic = mask_topic
        self._grid_x_pixel = grid_x_pixel
        self._target_edge = target_edge
        self._y_min_ratio = y_min_ratio
        self._y_max_ratio = y_max_ratio
        self._debug_image_topic = debug_image_topic
        self._publish_debug_image = publish_debug_image
        self._camera_info_topic = '/hsrb/head_rgbd_sensor/rgb/camera_info'
        self._rgb_topic = '/hsrb/head_rgbd_sensor/rgb/image_rect_color'
        self._depth_topic = '/hsrb/head_rgbd_sensor/depth_registered/image_rect_raw'
        self._target_frame = 'base_link'
        self._bridge = CvBridge()
        self._sub = ProxySubscriberCached({self._mask_topic: Image,self._camera_info_topic: CameraInfo,self._depth_topic: Image})
        self._pub = ProxyPublisher({self._debug_image_topic: Image})
        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(
            self._tf_buffer,
            self._node
        )

    def on_enter(self, userdata):
        self._sub.remove_last_msg(self._mask_topic)

    def execute(self, userdata):
        userdata.x = 0.0
        userdata.y = 0.0

        #トピック受信チェック
        if not self._sub.has_msg(self._mask_topic):
            return None

        if not self._sub.has_msg(self._camera_info_topic):
            Logger.logwarn('[DiffTarget] Waiting for CameraInfo.')
            return None

        if not self._sub.has_msg(self._depth_topic):
            Logger.logwarn('[DiffTarget] Waiting for depth image.')
            return None
        # ここまでがチェック

        #　受信したカメラ情報・マスク画像・深度情報の3兄弟
        mask_msg = self._sub.get_last_msg(self._mask_topic)
        camera_info_msg = self._sub.get_last_msg(self._camera_info_topic)
        depth_msg = self._sub.get_last_msg(self._depth_topic)

        # ROS Image -> OpenCV image 変換
        try:
            mask_img = self._bridge.imgmsg_to_cv2(mask_msg,desired_encoding='passthrough')
        except Exception as e:
            Logger.logwarn('[DiffTarget] Failed to convert mask image: {}'.format(e))
            return 'done'

        try:
            depth_img = self._bridge.imgmsg_to_cv2(depth_msg,desired_encoding='passthrough')
        except Exception as e:
            Logger.logwarn('[DiffTarget] Failed to convert depth image: {}'.format(e))
            return 'done'

        # マスクの左右端と中心のx・y座標を取得する。
        try:
            object_x, object_y, x_left, x_right, x_center = self._get_object_pixel_from_mask(
                mask_img=mask_img,
                target_edge=self._target_edge,
                y_min_ratio=self._y_min_ratio,
                y_max_ratio=self._y_max_ratio
            )

            image_height = mask_img.shape[0]
            image_width = mask_img.shape[1]

            if self._grid_x_pixel is None:
                grid_x = image_width // 2
            else:
                grid_x = int(self._grid_x_pixel)

            grid_x = max(0, min(image_width - 1, grid_x))

            object_depth_m = self._get_valid_depth_m(
                depth_img=depth_img,
                u=object_x,
                v=object_y,
                window_size=5
            )

            # 深度情報が無いときはそのことをデバッグ画像に描画
            if object_depth_m is None:
                Logger.logwarn('[DiffTarget] Failed to get valid object depth.')
                self._publish_debug_if_needed(
                    mask_img=mask_img,
                    mask_msg=mask_msg,
                    grid_x=grid_x,
                    object_x=object_x,
                    object_y=object_y,
                    x_left=x_left,
                    x_right=x_right,
                    x_center=x_center,
                    move_diff_m=0.0,
                    object_base_y=0.0,
                    target_edge=self._target_edge,
                    status_text='No valid depth'
                )
                return 'done'

            # ここからカメラ座標変換開始。必要なカメラパラメータを取得
            fx = camera_info_msg.k[0]
            fy = camera_info_msg.k[4]
            cx = camera_info_msg.k[2]
            cy = camera_info_msg.k[5]

            if fx == 0.0 or fy == 0.0:
                Logger.logwarn('[DiffTarget] Invalid camera intrinsics: fx={}, fy={}'.format(fx, fy))
                return 'done'

            # 対象物体位置のカメラ座標変換
            object_point_cam = self._pixel_to_point_stamped(
                u=object_x,
                v=object_y,
                depth_m=object_depth_m,
                fx=fx,
                fy=fy,
                cx=cx,
                cy=cy,
                frame_id=camera_info_msg.header.frame_id,
                stamp=depth_msg.header.stamp
            )

            # 目標グリッド位置のカメラ座標変換。グリッド位置は物体位置と等距離としている。
            grid_point_cam = self._pixel_to_point_stamped(
                u=grid_x,
                v=object_y,
                depth_m=object_depth_m,
                fx=fx,
                fy=fy,
                cx=cx,
                cy=cy,
                frame_id=camera_info_msg.header.frame_id,
                stamp=depth_msg.header.stamp
            )

            # base_link座標系に変換 
            object_point_base = self._transform_point_to_base(object_point_cam)
            grid_point_base = self._transform_point_to_base(grid_point_cam)

            if object_point_base is None or grid_point_base is None:
                Logger.logwarn('[DiffTarget] Failed to transform point to base_link.')
                return 'done'

            # base_link上での差分。
            # 画像横方向のズレは、HSRのbase_linkでは主にy方向差分として出る想定。
            base_y_diff = object_point_base.point.y - grid_point_base.point.y

            # xに「差分移動量」、yに「対象物体のbase_link y位置」を入れる。
            userdata.x = float(object_point_base.point.x)
            userdata.y = float(base_y_diff)

            Logger.loginfo('[DiffTarget] target_edge={}, object_pixel=({}, {}), grid_x={}, depth={:.4f}, ''object_base=({:.4f}, {:.4f}, {:.4f}), grid_base=({:.4f}, {:.4f}, {:.4f}), ''output_x_diff={:.4f}, output_y_object={:.4f}'.format(self._target_edge,object_x,object_y,grid_x,object_depth_m,object_point_base.point.x,object_point_base.point.y,object_point_base.point.z,grid_point_base.point.x,grid_point_base.point.y,grid_point_base.point.z,userdata.x,userdata.y))
            # デバッグ画像をpublishする
            self._publish_debug_if_needed(
                mask_img=mask_img,
                mask_msg=mask_msg,
                grid_x=grid_x,
                object_x=object_x,
                object_y=object_y,
                x_left=x_left,
                x_right=x_right,
                x_center=x_center,
                move_diff_m=userdata.x,
                object_base_y=userdata.y,
                target_edge=self._target_edge,
                status_text='OK'
            )

            return 'done'

        except Exception as e:
            Logger.logwarn('[DiffTarget] Failed to calculate base_link diff: {}'.format(e))

            # マスク取得失敗時にも確認用画像を出す。
            try:
                if self._publish_debug_image:
                    debug_img = self._create_debug_image_no_mask(mask_img)
                    debug_msg = self._bridge.cv2_to_imgmsg(debug_img, encoding='bgr8')
                    debug_msg.header = mask_msg.header
                    self._pub.publish(self._debug_image_topic, debug_msg)
            except Exception:
                pass

            return 'done'




#────────────────────────────────────────────────────────────────────────────────────────────
#　　　　　　　　　　　　　　　　　　 ここから下は内部処理用関数群
#────────────────────────────────────────────────────────────────────────────────────────────




    def _get_object_pixel_from_mask(self,mask_img,target_edge='center',y_min_ratio=0.0,y_max_ratio=1.0):
        """
        マスク画像から対象物のx座標と代表y座標を取得する。
        target_edge:
            "left"   : マスク領域の左端
            "right"  : マスク領域の右端
            "center" : マスク領域の中心
        """
        if mask_img.ndim == 3:
            mask_gray = mask_img[:, :, 0]
        else:
            mask_gray = mask_img

        height, width = mask_gray.shape[:2]
        y_min = int(height * y_min_ratio)
        y_max = int(height * y_max_ratio)
        y_min = max(0, min(height - 1, y_min))
        y_max = max(y_min + 1, min(height, y_max))
        mask_roi = mask_gray[y_min:y_max, :]
        ys, xs = np.where(mask_roi > 0)

        if xs.size == 0:
            raise RuntimeError('No mask pixels found.')

        x_left = int(xs.min())
        x_right = int(xs.max())
        x_center = int((x_left + x_right) / 2.0)

        # ROI内のマスク画素の中央値を代表yにする。
        object_y = int(np.median(ys) + y_min)

        if target_edge == 'left':
            object_x = x_left
        elif target_edge == 'right':
            object_x = x_right
        elif target_edge == 'center':
            object_x = x_center
        else:
            raise ValueError('Invalid target_edge: {}. Use "left", "right", or "center".'.format(target_edge))

        object_x = max(0, min(width - 1, int(object_x)))
        object_y = max(0, min(height - 1, int(object_y)))
        return object_x, object_y, x_left, x_right, x_center

    def _get_valid_depth_m(self, depth_img, u, v, window_size=5):
        """
        指定pixel周辺の有効Depth中央値を[m]で返す。

        depth_registered/image_rect_raw は環境によって
        16UC1[mm] または 32FC1[m] の可能性があるため、
        dtypeを見て変換する。
        """

        height, width = depth_img.shape[:2]
        u = int(max(0, min(width - 1, u)))
        v = int(max(0, min(height - 1, v)))
        half = int(window_size // 2)
        u0 = max(0, u - half)
        u1 = min(width, u + half + 1)
        v0 = max(0, v - half)
        v1 = min(height, v + half + 1)
        patch = depth_img[v0:v1, u0:u1].astype(np.float32)
        valid = patch[np.isfinite(patch)]
        valid = valid[valid > 0.0]
        if valid.size == 0:
            return None
        depth = float(np.median(valid))

        if depth_img.dtype == np.uint16:
            depth = depth * 0.001

        if depth <= 0.0 or not math.isfinite(depth):
            return None

        return depth

    def _pixel_to_point_stamped(self,u,v,depth_m,fx,fy,cx,cy,frame_id,stamp):
        """
        pixel座標とDepthから、カメラ座標系の3D点を作る。

        カメラ座標系:
            X: 画像右方向
            Y: 画像下方向
            Z: カメラ前方
        """

        x = (float(u) - float(cx)) * float(depth_m) / float(fx)
        y = (float(v) - float(cy)) * float(depth_m) / float(fy)
        z = float(depth_m)

        point = PointStamped()
        point.header.stamp = stamp
        point.header.frame_id = frame_id
        point.point.x = x
        point.point.y = y
        point.point.z = z

        return point

    def _transform_point_to_base(self, point_cam):
        """
        PointStampedをbase_linkへ変換する。
        """

        try:
            trans = self._tf_buffer.lookup_transform(
                self._target_frame,
                point_cam.header.frame_id,
                point_cam.header.stamp,
                timeout=Duration(seconds=0.5)
            )

            point_base = tf2_geometry_msgs.do_transform_point(point_cam, trans)
            return point_base

        except Exception as e:
            Logger.logwarn('[DiffTarget] TF transform failed: {} -> {} : {}'.format(point_cam.header.frame_id, self._target_frame, e))
            return None

    def _publish_debug_if_needed(self,mask_img,mask_msg,grid_x,object_x,object_y,x_left,x_right,x_center,move_diff_m,object_base_y,target_edge,status_text='OK'):
        if not self._publish_debug_image:
            return

        debug_img = self._create_debug_image(
            mask_img=mask_img,
            grid_x=grid_x,
            object_x=object_x,
            object_y=object_y,
            x_left=x_left,
            x_right=x_right,
            x_center=x_center,
            move_diff_m=move_diff_m,
            object_base_y=object_base_y,
            target_edge=target_edge,
            status_text=status_text
        )
        debug_msg = self._bridge.cv2_to_imgmsg(debug_img,encoding='bgr8')
        debug_msg.header = mask_msg.header
        self._pub.publish(self._debug_image_topic, debug_msg)

    def _create_debug_image(self,mask_img,grid_x,object_x,object_y,x_left,x_right,x_center,move_diff_m,object_base_y,target_edge,status_text='OK'):
        """
        マスク画像に理想グリッド線と検出線を描画する。
        """

        debug_img = self._mask_to_bgr(mask_img)
        height, width = debug_img.shape[:2]
        grid_x = max(0, min(width - 1, int(grid_x)))
        object_x = max(0, min(width - 1, int(object_x)))
        object_y = max(0, min(height - 1, int(object_y)))
        x_left = max(0, min(width - 1, int(x_left)))
        x_right = max(0, min(width - 1, int(x_right)))
        x_center = max(0, min(width - 1, int(x_center)))
        pixel_diff = int(object_x - grid_x)

        # 理想グリッド線: 緑
        cv2.line(debug_img,(grid_x, 0),(grid_x, height - 1),(0, 255, 0),2)

        # 実際に比較対象として使う線: 赤
        cv2.line(debug_img,(object_x, 0),(object_x, height - 1),(0, 0, 255),2)

        # マスク左端・右端: 青
        cv2.line(debug_img,(x_left, 0),(x_left, height - 1),(255, 0, 0),1)
        cv2.line(debug_img,(x_right, 0),(x_right, height - 1),(255, 0, 0),1)

        # マスク中心: 黄
        cv2.line(debug_img,(x_center, 0),(x_center, height - 1),(0, 255, 255),1)

        # 代表点: 紫
        cv2.circle(debug_img,(object_x, object_y),5,(255, 0, 255),-1)

        # デバッグ文字列描画
        text_1 = 'status: {}'.format(status_text)
        text_2 = 'grid_x: {}'.format(grid_x)
        text_3 = '{}_x: {}, object_y: {}'.format(target_edge, object_x, object_y)
        text_4 = 'pixel_diff: {} px'.format(pixel_diff)
        text_5 = 'output x obj: {:.4f} m'.format(move_diff_m)
        text_6 = 'output y diff: {:.4f} m'.format(object_base_y)

        #表示する場所
        cv2.putText(debug_img, text_1, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_img, text_2, (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        cv2.putText(debug_img, text_3, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(debug_img, text_4, (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_img, text_5, (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(debug_img, text_6, (10, 180), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        return debug_img

    def _create_debug_image_no_mask(self, mask_img):
        """
        マスク取得失敗時にも確認用画像を出す。
        """
        debug_img = self._mask_to_bgr(mask_img)
        cv2.putText(debug_img,'No mask pixels found.',(10, 30),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0, 0, 255),2)
        return debug_img

    def _mask_to_bgr(self, mask_img):
        """
        入力マスク画像を描画用BGR画像へ変換する。
        """

        if mask_img.ndim == 3:
            if mask_img.shape[2] == 3:
                return mask_img.copy()
            else:
                mask_gray = mask_img[:, :, 0]
        else:
            mask_gray = mask_img

        if mask_gray.dtype != np.uint8:
            mask_norm = cv2.normalize(mask_gray, None, 0, 255, cv2.NORM_MINMAX)
            mask_gray_u8 = mask_norm.astype(np.uint8)
        else:
            mask_gray_u8 = mask_gray.copy()
        debug_img = cv2.cvtColor(mask_gray_u8,cv2.COLOR_GRAY2BGR)
        return debug_img
