#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import cv2
import numpy as np

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached, ProxyPublisher
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist
from cv_bridge import CvBridge


class PixelServoHead(EventState):
    """
    Head RGBカメラから生成されたSAM3マスクを使い、画像上のx方向誤差から
    HSR台車の左右速度 linear.y を比例制御する。

    注意:
        このState自身はSAM3へRGB画像を送らない。
        mask_topicのマスクを生成する上流ノードを、次のhead画像トピックへ接続すること。
        /hsrb/head_rgbd_sensor/rgb/image_rect_color

    -- mask_topic          string  Head画像から生成されたマスク画像トピック
    -- cmd_vel_topic       string  HSR台車速度指令トピック
    -- grid_x_pixel        int     目標x座標。Noneなら画像中心
    -- target_edge         string  left / right / center
    -- y_min_ratio         float   マスク探索範囲の上端比率
    -- y_max_ratio         float   マスク探索範囲の下端比率
    -- kp                  float   比例ゲイン [(m/s)/pixel]
    -- max_speed           float   左右速度の上限 [m/s]
    -- min_speed           float   deadband外での最低速度 [m/s]
    -- deadband_pixel      int     停止とみなす誤差 [pixel]
    -- stable_frames       int     連続してdeadband内に入る必要があるフレーム数
    -- direction           float   通常は-1.0。動作方向が逆なら1.0
    -- timeout             float   タイムアウト [s]。0以下なら無効
    -- stale_timeout       float   マスクが来ない場合に停止するまでの時間 [s]
    -- debug_image_topic   string  デバッグ画像publish先
    -- publish_debug_image bool    デバッグ画像をpublishするか

    #> diff_pixel          int     object_x - grid_x [pixel]
    #> velocity_y          float   publishしたlinear.y [m/s]

    <= done                        位置合わせ完了
    <= failed                      タイムアウトまたは処理失敗
    """

    def __init__(self,mask_topic='/sam/mask',cmd_vel_topic='/hsrb/command_velocity',grid_x_pixel=None,target_edge='center',y_min_ratio=0.0,y_max_ratio=1.0,kp=0.0005,max_speed=0.12,min_speed=0.015,deadband_pixel=10,stable_frames=5,direction=-1.0,timeout=15.0,stale_timeout=0.5,debug_image_topic='/debug/mask_grid/image',publish_debug_image=True):

        super(PixelServoHead, self).__init__(outcomes=['done', 'failed'],output_keys=['diff_pixel', 'velocity_y'])
        self._mask_topic = mask_topic
        self._cmd_vel_topic = cmd_vel_topic
        self._grid_x_pixel = grid_x_pixel
        self._target_edge = target_edge
        self._y_min_ratio = float(y_min_ratio)
        self._y_max_ratio = float(y_max_ratio)

        self._kp = abs(float(kp))
        self._max_speed = abs(float(max_speed))
        self._min_speed = abs(float(min_speed))
        self._deadband_pixel = abs(int(deadband_pixel))
        self._stable_frames_required = max(1, int(stable_frames))
        self._direction = float(direction)
        self._timeout = float(timeout)
        self._stale_timeout = max(0.0, float(stale_timeout))

        self._debug_image_topic = debug_image_topic
        self._publish_debug_image = bool(publish_debug_image)

        self._bridge = CvBridge()
        self._sub = ProxySubscriberCached({self._mask_topic: Image})

        publisher_topics = {self._cmd_vel_topic: Twist}
        if self._publish_debug_image:
            publisher_topics[self._debug_image_topic] = Image
        self._pub = ProxyPublisher(publisher_topics)

        self._start_time = None
        self._last_mask_time = None
        self._stable_count = 0

    def on_enter(self, userdata):
        userdata.diff_pixel = 0
        userdata.velocity_y = 0.0

        self._stable_count = 0
        self._start_time = self._node.get_clock().now()
        self._last_mask_time = None

        if self._sub.has_msg(self._mask_topic):
            self._sub.remove_last_msg(self._mask_topic)

        self._publish_velocity(0.0)

    def execute(self, userdata):
        now = self._node.get_clock().now()

        if self._timeout > 0.0 and self._start_time is not None:
            if (now - self._start_time).nanoseconds * 1.0e-9 >= self._timeout:
                self._publish_velocity(0.0)
                Logger.logwarn('[PixelServoHead] Alignment timed out.')
                return 'failed'

        if not self._sub.has_msg(self._mask_topic):
            if self._last_mask_time is not None and self._stale_timeout > 0.0:
                if ((now - self._last_mask_time).nanoseconds * 1.0e-9
                        >= self._stale_timeout):
                    self._publish_velocity(0.0)
                    userdata.velocity_y = 0.0
            return None

        mask_msg = self._sub.get_last_msg(self._mask_topic)
        self._sub.remove_last_msg(self._mask_topic)
        self._last_mask_time = now

        try:
            mask_img = self._bridge.imgmsg_to_cv2(
                mask_msg,
                desired_encoding='passthrough'
            )
        except Exception as e:
            self._publish_velocity(0.0)
            Logger.logwarn(
                '[PixelServoHead] Failed to convert mask image: {}'.format(e)
            )
            return 'failed'

        try:
            object_x, object_y, x_left, x_right, x_center = \
                self._get_object_pixel_from_mask(
                    mask_img=mask_img,
                    target_edge=self._target_edge,
                    y_min_ratio=self._y_min_ratio,
                    y_max_ratio=self._y_max_ratio
                )

            image_width = mask_img.shape[1]
            if self._grid_x_pixel is None:
                grid_x = image_width // 2
            else:
                grid_x = int(self._grid_x_pixel)
            grid_x = max(0, min(image_width - 1, grid_x))

            # 画像右方向を正とするpixel誤差
            diff_pixel = int(object_x - grid_x)
            userdata.diff_pixel = diff_pixel

            if abs(diff_pixel) <= self._deadband_pixel:
                velocity_y = 0.0
                self._stable_count += 1
            else:
                self._stable_count = 0

                # 通常のhead画像では、対象が画像右側なら台車も右へ動く必要がある。
                # base_linkの+Yは左方向なので、direction=-1.0を標準とする。
                velocity_y = self._direction * self._kp * float(diff_pixel)
                velocity_y = float(np.clip(
                    velocity_y,
                    -self._max_speed,
                    self._max_speed
                ))

                if 0.0 < abs(velocity_y) < self._min_speed:
                    velocity_y = float(np.sign(velocity_y) * self._min_speed)

            userdata.velocity_y = velocity_y
            self._publish_velocity(velocity_y)

            Logger.loginfo(
                '[PixelServoHead] edge={}, object_x={}, grid_x={}, '
                'diff={} px, velocity_y={:.4f} m/s, stable={}/{}'.format(
                    self._target_edge,
                    object_x,
                    grid_x,
                    diff_pixel,
                    velocity_y,
                    self._stable_count,
                    self._stable_frames_required
                )
            )

            if self._publish_debug_image:
                debug_img = self._create_debug_image(
                    mask_img=mask_img,
                    grid_x=grid_x,
                    object_x=object_x,
                    object_y=object_y,
                    x_left=x_left,
                    x_right=x_right,
                    x_center=x_center,
                    diff_pixel=diff_pixel,
                    velocity_y=velocity_y,
                    target_edge=self._target_edge,
                    status_text='ALIGN' if velocity_y != 0.0 else 'IN DEADBAND'
                )
                debug_msg = self._bridge.cv2_to_imgmsg(debug_img, encoding='bgr8')
                debug_msg.header = mask_msg.header
                self._pub.publish(self._debug_image_topic, debug_msg)

            if self._stable_count >= self._stable_frames_required:
                self._publish_velocity(0.0)
                userdata.velocity_y = 0.0
                Logger.loginfo('[PixelServoHead] Alignment completed.')
                return 'done'

            return None

        except RuntimeError as e:
            # マスクが一時的に消えた場合は、即失敗ではなく停止して再検出を待つ。
            self._stable_count = 0
            self._publish_velocity(0.0)
            userdata.diff_pixel = 0
            userdata.velocity_y = 0.0
            Logger.logwarn('[PixelServoHead] {}'.format(e))

            if self._publish_debug_image:
                debug_img = self._create_debug_image_no_mask(mask_img)
                debug_msg = self._bridge.cv2_to_imgmsg(debug_img, encoding='bgr8')
                debug_msg.header = mask_msg.header
                self._pub.publish(self._debug_image_topic, debug_msg)

            return None

        except Exception as e:
            self._publish_velocity(0.0)
            userdata.velocity_y = 0.0
            Logger.logwarn(
                '[PixelServoHead] Failed to calculate velocity: {}'.format(e)
            )
            return 'failed'

    def on_exit(self, userdata):
        self._publish_velocity(0.0)

    def on_stop(self):
        self._publish_velocity(0.0)

    def on_pause(self):
        self._publish_velocity(0.0)

    def _publish_velocity(self, velocity_y):
        twist = Twist()
        twist.linear.y = float(velocity_y)
        self._pub.publish(self._cmd_vel_topic, twist)

    def _get_object_pixel_from_mask(self,mask_img,target_edge='center',y_min_ratio=0.0,y_max_ratio=1.0):
        if mask_img.ndim == 3:
            mask_gray = mask_img[:, :, 0]
        else:
            mask_gray = mask_img

        height, width = mask_gray.shape[:2]

        y_min_ratio = max(0.0, min(1.0, float(y_min_ratio)))
        y_max_ratio = max(0.0, min(1.0, float(y_max_ratio)))
        if y_max_ratio <= y_min_ratio:
            raise ValueError('y_max_ratio must be larger than y_min_ratio.')

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
        object_y = int(np.median(ys) + y_min)

        if target_edge == 'left':
            object_x = x_left
        elif target_edge == 'right':
            object_x = x_right
        elif target_edge == 'center':
            object_x = x_center
        else:
            raise ValueError(
                'Invalid target_edge: {}. Use left, right, or center.'.format(
                    target_edge
                )
            )

        object_x = max(0, min(width - 1, int(object_x)))
        object_y = max(0, min(height - 1, int(object_y)))

        return object_x, object_y, x_left, x_right, x_center

    def _create_debug_image(self,mask_img,grid_x,object_x,object_y,x_left,x_right,x_center,diff_pixel,velocity_y,target_edge,status_text='OK'):
        debug_img = self._mask_to_bgr(mask_img)
        height, width = debug_img.shape[:2]

        grid_x = max(0, min(width - 1, int(grid_x)))
        object_x = max(0, min(width - 1, int(object_x)))
        object_y = max(0, min(height - 1, int(object_y)))
        x_left = max(0, min(width - 1, int(x_left)))
        x_right = max(0, min(width - 1, int(x_right)))
        x_center = max(0, min(width - 1, int(x_center)))

        # 理想グリッド線: 緑
        cv2.line(debug_img, (grid_x, 0), (grid_x, height - 1), (0, 255, 0), 2)
        # 制御対象線: 赤
        cv2.line(debug_img, (object_x, 0), (object_x, height - 1), (0, 0, 255), 2)
        # 左右端: 青
        cv2.line(debug_img, (x_left, 0), (x_left, height - 1), (255, 0, 0), 1)
        cv2.line(debug_img, (x_right, 0), (x_right, height - 1), (255, 0, 0), 1)
        # 中心: 黄
        cv2.line(debug_img, (x_center, 0), (x_center, height - 1), (0, 255, 255), 1)
        # 代表点: 紫
        cv2.circle(debug_img, (object_x, object_y), 5, (255, 0, 255), -1)

        texts = [
            'status: {}'.format(status_text),
            'grid_x: {}'.format(grid_x),
            '{}_x: {}, object_y: {}'.format(target_edge, object_x, object_y),
            'diff_pixel: {} px'.format(diff_pixel),
            'linear.y: {:.4f} m/s'.format(velocity_y)
        ]

        for index, text in enumerate(texts):
            cv2.putText(
                debug_img,
                text,
                (10, 30 + 30 * index),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2
            )

        return debug_img

    def _create_debug_image_no_mask(self, mask_img):
        debug_img = self._mask_to_bgr(mask_img)
        cv2.putText(
            debug_img,
            'No mask pixels found. STOP',
            (10, 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (0, 0, 255),
            2
        )
        return debug_img

    def _mask_to_bgr(self, mask_img):
        if mask_img.ndim == 3:
            if mask_img.shape[2] == 3:
                return mask_img.copy()
            mask_gray = mask_img[:, :, 0]
        else:
            mask_gray = mask_img

        if mask_gray.dtype != np.uint8:
            mask_norm = cv2.normalize(
                mask_gray,
                None,
                0,
                255,
                cv2.NORM_MINMAX
            )
            mask_gray = mask_norm.astype(np.uint8)
        else:
            mask_gray = mask_gray.copy()

        return cv2.cvtColor(mask_gray, cv2.COLOR_GRAY2BGR)
