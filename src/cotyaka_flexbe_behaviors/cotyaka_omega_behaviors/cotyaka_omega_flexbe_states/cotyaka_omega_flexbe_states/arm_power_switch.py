#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher, ProxySubscriberCached

from std_msgs.msg import Bool


class ArmPowerSwitch(EventState):
    """
    アーム有効化フラグを publish する

    -- enable_flag      bool      有効化トピックへ publish する値
    -- topic            string    有効化フラグのトピック名
    -- verify           bool      同じトピックを subscribe して publish 値を確認するかどうか
    -- timeout          float     確認処理のタイムアウト時間
    -- publish_period   float     確認待機中の publish 周期

    <= done                       有効化フラグの publish 完了。
    """

    def __init__(self,
                 enable_flag=True,
                 topic='/enable_flag',
                 verify=True,
                 timeout=2.0,
                 publish_period=0.2):

        super().__init__(
            outcomes=['done']
        )

        self._enable_flag = bool(enable_flag)
        self._topic = topic
        self._verify = bool(verify)
        self._timeout = float(timeout)
        self._publish_period = float(publish_period)

        self._pub = ProxyPublisher({
            self._topic: Bool
        })

        self._sub = ProxySubscriberCached({
            self._topic: Bool
        })

        self._start_time = None
        self._last_publish_time = 0.0
        self._published_once = False

    def on_enter(self, userdata):
        self._start_time = time.monotonic()
        self._last_publish_time = 0.0
        self._published_once = False

        # 古いメッセージが残っていると確認判定を誤るので消す
        if self._sub.has_msg(self._topic):
            self._sub.remove_last_msg(self._topic)

        Logger.loginfo(
            'ArmPowerSwitch: set {} to {}'.format(
                self._topic,
                self._enable_flag
            )
        )

        self._publish_enable_flag()

    def execute(self, userdata):
        if not self._verify:
            return 'done'

        # 自分がpublishした値がtopic上で確認できたらdone
        if self._sub.has_msg(self._topic):
            msg = self._sub.get_last_msg(self._topic)
            self._sub.remove_last_msg(self._topic)

            if bool(msg.data) == self._enable_flag:
                Logger.loginfo(
                    'ArmPowerSwitch: verified {} = {}'.format(
                        self._topic,
                        msg.data
                    )
                )
                return 'done'

            Logger.logwarn(
                'ArmPowerSwitch: observed {} = {}, expected {}'.format(
                    self._topic,
                    msg.data,
                    self._enable_flag
                )
            )

        now = time.monotonic()

        # 念のためtimeoutまで周期的に再publishする
        if now - self._last_publish_time >= self._publish_period:
            self._publish_enable_flag()

        if now - self._start_time >= self._timeout:
            Logger.logwarn(
                'ArmPowerSwitch: verification timeout. Published {} to {}, but matching echo was not confirmed.'.format(
                    self._enable_flag,
                    self._topic
                )
            )
            return 'done'

        return None

    def _publish_enable_flag(self):
        msg = Bool()
        msg.data = self._enable_flag

        self._pub.publish(self._topic, msg)

        self._published_once = True
        self._last_publish_time = time.monotonic()

        Logger.loginfo(
            'ArmPowerSwitch: published {} to {}'.format(
                msg.data,
                self._topic
            )
        )#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyPublisher, ProxySubscriberCached

from std_msgs.msg import Bool


class ArmPowerSwitch(EventState):
    """
    Publish arm enable flag.

    -- enable_flag      bool      enable トピックへ送信する値
    -- topic            string    enable フラグのトピック名
    -- verify           bool      同じトピックを購読して送信値を確認するかどうか
    -- timeout          float     確認処理のタイムアウト時間
    -- publish_period   float     確認待機中の publish 間隔

    <= done                       enable フラグの送信完了
    """

    def __init__(self,enable_flag=True,topic='/enable_flag',verify=True,timeout=2.0,publish_period=0.2):
        super().__init__(outcomes=['done'])
        self._enable_flag = bool(enable_flag)
        self._topic = topic
        self._verify = bool(verify)
        self._timeout = float(timeout)
        self._publish_period = float(publish_period)
        self._pub = ProxyPublisher({self._topic: Bool})
        self._sub = ProxySubscriberCached({self._topic: Bool})
        self._start_time = None
        self._last_publish_time = 0.0
        self._published_once = False

    def on_enter(self, userdata):
        self._start_time = time.monotonic()
        self._last_publish_time = 0.0
        self._published_once = False

        # 古いメッセージが残っていると確認判定を誤るので消す
        if self._sub.has_msg(self._topic):
            self._sub.remove_last_msg(self._topic)

        Logger.loginfo(
            'ArmPowerSwitch: set {} to {}'.format(
                self._topic,
                self._enable_flag
            )
        )

        self._publish_enable_flag()

    def execute(self, userdata):
        if not self._verify:
            return 'done'

        # 自分がpublishした値がtopic上で確認できたらdone
        if self._sub.has_msg(self._topic):
            msg = self._sub.get_last_msg(self._topic)
            self._sub.remove_last_msg(self._topic)

            if bool(msg.data) == self._enable_flag:
                Logger.loginfo(
                    'ArmPowerSwitch: verified {} = {}'.format(
                        self._topic,
                        msg.data
                    )
                )
                return 'done'

            Logger.logwarn(
                'ArmPowerSwitch: observed {} = {}, expected {}'.format(
                    self._topic,
                    msg.data,
                    self._enable_flag
                )
            )

        now = time.monotonic()

        # 念のためtimeoutまで周期的に再publishする
        if now - self._last_publish_time >= self._publish_period:
            self._publish_enable_flag()

        if now - self._start_time >= self._timeout:
            Logger.logwarn(
                'ArmPowerSwitch: verification timeout. Published {} to {}, but matching echo was not confirmed.'.format(
                    self._enable_flag,
                    self._topic
                )
            )
            return 'done'

        return None

    def _publish_enable_flag(self):
        msg = Bool()
        msg.data = self._enable_flag

        self._pub.publish(self._topic, msg)

        self._published_once = True
        self._last_publish_time = time.monotonic()

        Logger.loginfo(
            'ArmPowerSwitch: published {} to {}'.format(
                msg.data,
                self._topic
            )
        )