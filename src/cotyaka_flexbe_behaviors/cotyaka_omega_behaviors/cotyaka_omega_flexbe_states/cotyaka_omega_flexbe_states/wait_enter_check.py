#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxySubscriberCached

from std_msgs.msg import String


class WaitEnterCheck(EventState):
    """
    wait_enter_and_pub_msg_node からのコマンドトピックを確認する。

    -- command_topic      string    コマンドトピック名。
    -- record_command     string    記録用のコマンド文字列。
    -- done_command       string    終了用のコマンド文字列。

    <= record                       記録コマンドを受信。
    <= done                         終了コマンドを受信。
    """

    def __init__(self,
                 command_topic='/record_joint_command',
                 record_command='record',
                 done_command='done'):

        super().__init__(
            outcomes=['record', 'done']
        )

        self._command_topic = command_topic
        self._record_command = record_command
        self._done_command = done_command

        self._sub = ProxySubscriberCached({
            self._command_topic: String
        })

    def on_enter(self, userdata):
        # 古いコマンドが残っていると、入った瞬間に前回入力で遷移してしまうので消す
        if self._sub.has_msg(self._command_topic):
            self._sub.remove_last_msg(self._command_topic)

        Logger.loginfo(
            'WaitEnterCheck: waiting command on {}. record="{}", done="{}"'.format(
                self._command_topic,
                self._record_command,
                self._done_command
            )
        )

    def execute(self, userdata):
        if not self._sub.has_msg(self._command_topic):
            return None

        cmd_msg = self._sub.get_last_msg(self._command_topic)
        self._sub.remove_last_msg(self._command_topic)

        cmd = cmd_msg.data.strip().lower()

        if cmd == self._record_command:
            Logger.loginfo('WaitEnterCheck: record command received.')
            return 'record'

        if cmd == self._done_command:
            Logger.loginfo('WaitEnterCheck: done command received.')
            return 'done'

        Logger.logwarn(
            'WaitEnterCheck: unknown command "{}".'.format(cmd)
        )

        return None