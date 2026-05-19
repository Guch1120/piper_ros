#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rospy
from flexbe_core import EventState, Logger
from std_msgs.msg import String


class PublishObjectName(EventState):
    """
    object_list[index]を/object_nameにpublishする State
    このStateではindexの更新・範囲管理は行わない
    index の管理は別Stateで行う

    ># object_list   list    対象とするリスト
    ># index         int     現在のindex

    #> object_name   string  Pubするobject name

    <= done                  Pub成功
    """

    def __init__(self):
        super(PublishObjectName, self).__init__(outcomes=['done'],input_keys=['object_list', 'index'],output_keys=['object_name'])
        self._pub = rospy.Publisher('/object_name',String,queue_size=10)

    @staticmethod
    def _extract_object_name(entry):
        """
        object_list の要素から object_name を取り出す
        想定される entry:
          - "apple" のような文字列
          - {"object_name": "apple"}
          - {"name": "apple"}
        """
        if isinstance(entry, dict):
            for key in ['object_name', 'name', 'label', 'color_type']:
                value = entry.get(key)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ''

        if entry is None:
            return ''

        return str(entry).strip()

    def execute(self, userdata):
        Logger.loginfo('PublishObjectName: start')
        Logger.loginfo('  index       = {}'.format(userdata.index))
        Logger.loginfo('  object_list = {}'.format(userdata.object_list))

        # 念のため output_key は必ず代入しておく
        userdata.object_name = ''

        # index を int に変換
        try:
            current_index = int(userdata.index)
        except Exception as e:
            Logger.logerr('PublishObjectName: userdata.index cannot be converted to int. ''index={}, error={}'.format(userdata.index, e))
            return 'done'

        # object_list の型チェック
        if userdata.object_list is None:
            Logger.logerr('PublishObjectName: object_list is None.')
            return 'done'

        if not isinstance(userdata.object_list, list):
            Logger.logerr('PublishObjectName: object_list is not list. type={}'.format(type(userdata.object_list)))
            return 'done'

        # object name を取得
        object_entry = userdata.object_list[current_index]
        object_name = self._extract_object_name(object_entry)

        if not object_name:
            Logger.logwarn('PublishObjectName: could not extract object_name from entry: {}'.format(object_entry))
            return 'done'

        userdata.object_name = object_name
        msg = String()
        msg.data = object_name
        self._pub.publish(msg)
        Logger.loginfo('PublishObjectName: published /object_name = {}'.format(object_name))
        return 'done'