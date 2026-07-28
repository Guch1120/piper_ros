#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher
from geometry_msgs.msg import Twist


class VisualServoControl(EventState):
    """
    画像上のpixel差分を用いて、HSRのbase_link y方向を制御する。

    大きな誤差では高いPゲインを使用し、
    目標付近では低いPゲインを使用する。
    """

    def __init__(self,kp_near=0.0003,kp_far=0.0009,gain_near_pixel=40,gain_far_pixel=180,stop_threshold=8,restart_threshold=15,max_linear_y=0.22,min_linear_y=0.03,direction_sign=-1.0,cmd_vel_topic='/hsrb/command_velocity'):

        super(VisualServoControl, self).__init__(outcomes=['done'],input_keys=['diff_pixel'])
        self.kp_near = kp_near
        self.kp_far = kp_far
        self.gain_near_pixel = gain_near_pixel
        self.gain_far_pixel = gain_far_pixel
        self.stop_threshold = stop_threshold
        self.restart_threshold = restart_threshold
        self.max_linear_y = max_linear_y
        self.min_linear_y = min_linear_y
        self.direction_sign = direction_sign
        self._cmd_vel_topic = cmd_vel_topic

        assert isinstance(self.kp_near, float)
        assert isinstance(self.kp_far, float)
        assert isinstance(self.gain_near_pixel, int)
        assert isinstance(self.gain_far_pixel, int)
        assert isinstance(self.stop_threshold, int)
        assert isinstance(self.restart_threshold, int)
        assert isinstance(self.max_linear_y, float)
        assert isinstance(self.min_linear_y, float)
        assert isinstance(self.direction_sign, float)

        assert self.kp_near >= 0.0
        assert self.kp_far >= self.kp_near
        assert self.gain_far_pixel > self.gain_near_pixel
        assert self.restart_threshold >= self.stop_threshold
        assert 0.0 <= self.min_linear_y <= self.max_linear_y

        self._pub = ProxyPublisher({self._cmd_vel_topic: Twist})
        self._aligned = False

    def on_enter(self, userdata):
        Logger.loginfo('VisualServoControl: start')

    def execute(self, userdata):
        try:
            diff_pixel = int(userdata.diff_pixel)
        except (TypeError, ValueError, AttributeError):
            Logger.logwarn('VisualServoControl: invalid diff_pixel. Stop robot.')
            self._publish_twist(0.0)
            return 'done'

        abs_diff = abs(diff_pixel)

        # --------------------------------------------------
        # ヒステリシス
        # --------------------------------------------------
        if self._aligned:
            if abs_diff > self.restart_threshold:
                self._aligned = False
            else:
                self._publish_twist(0.0)
                Logger.loginfo('VisualServoControl: aligned hold, diff_pixel={}'.format(diff_pixel))
                return 'done'

        if abs_diff <= self.stop_threshold:
            self._aligned = True
            self._publish_twist(0.0)
            Logger.loginfo('VisualServoControl: aligned, diff_pixel={}'.format(diff_pixel))
            return 'done'

        # --------------------------------------------------
        # 誤差に応じてPゲインを連続的に変更
        # --------------------------------------------------
        kp = self._calculate_kp(abs_diff)
        linear_y = (self.direction_sign* kp* float(diff_pixel))

        # --------------------------------------------------
        # 最大速度制限
        # --------------------------------------------------
        linear_y = max(-self.max_linear_y,min(self.max_linear_y, linear_y))

        # --------------------------------------------------
        # 最低速度
        #
        # stop_threshold付近で突然min_linear_yにならないよう、
        # stop_thresholdからrestart_thresholdの間は徐々に増やす。
        # --------------------------------------------------
        if 0.0 < abs(linear_y) < self.min_linear_y:
            min_speed_ratio = self._calculate_min_speed_ratio(abs_diff)
            minimum_speed = self.min_linear_y * min_speed_ratio

            if linear_y > 0.0:
                linear_y = minimum_speed
            else:
                linear_y = -minimum_speed

        # executeごとに1回だけpublishする
        self._publish_twist(linear_y)

        Logger.loginfo(
            'VisualServoControl: '
            'diff_pixel={}, kp={:.6f}, linear_y={:.4f}, aligned={}'.format(
                diff_pixel,
                kp,
                linear_y,
                self._aligned
            )
        )

        return 'done'

    def _calculate_kp(self, abs_diff):
        """
        pixel差分に応じてkp_nearからkp_farまで連続的に変化させる。
        """

        if abs_diff <= self.gain_near_pixel:
            return self.kp_near

        if abs_diff >= self.gain_far_pixel:
            return self.kp_far

        ratio = (
            float(abs_diff - self.gain_near_pixel)
            / float(self.gain_far_pixel - self.gain_near_pixel)
        )

        return self.kp_near + ratio * (self.kp_far - self.kp_near)

    def _calculate_min_speed_ratio(self, abs_diff):
        """
        停止閾値付近で最低速度が急に立ち上がらないようにする。
        """

        if abs_diff <= self.stop_threshold:
            return 0.0

        if abs_diff >= self.restart_threshold:
            return 1.0

        denominator = self.restart_threshold - self.stop_threshold

        if denominator <= 0:
            return 1.0

        return (
            float(abs_diff - self.stop_threshold)
            / float(denominator)
        )

    def _publish_twist(self, linear_y):
        twist = Twist()

        twist.linear.x = 0.0
        twist.linear.y = linear_y
        twist.linear.z = 0.0

        twist.angular.x = 0.0
        twist.angular.y = 0.0
        twist.angular.z = 0.0

        self._pub.publish(self._cmd_vel_topic, twist)

    def on_exit(self, userdata):
        self._publish_twist(0.0)

    def on_stop(self):
        self._publish_twist(0.0)

    def on_pause(self):
        self._publish_twist(0.0)
